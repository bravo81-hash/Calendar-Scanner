"""TimeZone (RUT preferred).

Structure (from docs/strategies_html/TimeZone.html):
- Component A — Put Credit Spread (income generator):
    * 2 contracts minimum, 20 points wide
    * Short strike at ~14 delta
    * Net credit > $1.50
- Component B — Put Calendar (hedge / +vega):
    * 2 contracts
    * Front: 15 DTE, ~40 delta
    * Back: same strike as front, ~6 weeks (~43 DTE) out
- Entry: ~15 DTE, Thursday close
- Greeks: +Theta, +Vega, ~Delta flat (≤10% theta)
- TP 5% of planned capital
- SL 5% (do not hope for reversal)
- Hard close by 7 DTE
"""

from __future__ import annotations

from typing import Any

from scanner.models import CalendarCandidate, CalendarLeg, OptionQuote, RegimeSnapshot, ScanSettings
from strategies.base import (
    add_rejection,
    build_candidate_aggregates,
    expiry_pair_by_target_dte,
    nearest_by_abs_delta,
    nearest_by_strike,
)


NAME = "time_zone"


def needed_rights(settings: ScanSettings) -> tuple[str, ...]:
    return ("P",)


def build(
    symbol: str,
    quotes_by_expiry: dict[str, list[OptionQuote]],
    dte_by_expiry: dict[str, int],
    settings: ScanSettings,
    regime: RegimeSnapshot | None,
    underlying_price: float | None,
) -> tuple[list[CalendarCandidate], dict[str, Any]]:
    rejections: dict[str, int] = {}
    warnings: list[str] = []
    candidates: list[CalendarCandidate] = []

    if underlying_price is None or underlying_price <= 0:
        return candidates, {"rejection_reasons": rejections, "warnings": ["No underlying price for time_zone."]}

    pair = expiry_pair_by_target_dte(
        dte_by_expiry, settings.tz_short_dte, settings.tz_long_dte, settings.tz_dte_tolerance
    )
    if pair is None:
        warnings.append(f"No (front~{settings.tz_short_dte}, back~{settings.tz_long_dte}) expiry pair within ±{settings.tz_dte_tolerance} DTE.")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    short_exp, long_exp = pair
    short_dte = dte_by_expiry[short_exp]
    long_dte = dte_by_expiry[long_exp]

    front_puts = [q for q in quotes_by_expiry.get(short_exp, []) if q.right.upper() == "P"]
    back_puts = [q for q in quotes_by_expiry.get(long_exp, []) if q.right.upper() == "P"]

    # --- Calendar leg ---
    cal_short = nearest_by_abs_delta(front_puts, settings.tz_cal_short_delta)
    if cal_short is None:
        add_rejection(rejections, "no_cal_short")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}
    cal_long = nearest_by_strike(back_puts, cal_short.strike)
    if cal_long is None:
        add_rejection(rejections, "no_cal_long")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    # --- PCS (put credit spread) on front expiry ---
    pcs_short = nearest_by_abs_delta(front_puts, settings.tz_pcs_short_delta)
    if pcs_short is None:
        add_rejection(rejections, "no_pcs_short")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}
    pcs_long_target_strike = pcs_short.strike - settings.tz_pcs_width
    pcs_long = nearest_by_strike(front_puts, pcs_long_target_strike)
    if pcs_long is None:
        add_rejection(rejections, "no_pcs_long")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    # PCS credit check (short bid - long ask)
    pcs_credit_per_contract = (pcs_short.bid or 0.0) - (pcs_long.ask or 0.0)
    if settings.require_positive_credit_pcs and pcs_credit_per_contract < settings.tz_pcs_min_credit:
        add_rejection(rejections, f"pcs_credit_below_{settings.tz_pcs_min_credit}")
        warnings.append(
            f"PCS credit ${pcs_credit_per_contract:.2f} below min ${settings.tz_pcs_min_credit:.2f}. "
            f"Skipping — rule requires > ${settings.tz_pcs_min_credit:.2f}."
        )
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    qty = settings.tz_quantity
    legs = [
        CalendarLeg("PCS_short", "SELL", qty, pcs_short, role="pcs_short_put"),
        CalendarLeg("PCS_long", "BUY", qty, pcs_long, role="pcs_long_put"),
        CalendarLeg("CAL_short", "SELL", qty, cal_short, role="cal_short_put"),
        CalendarLeg("CAL_long", "BUY", qty, cal_long, role="cal_long_put"),
    ]
    candidate = CalendarCandidate(
        strategy=NAME, symbol=symbol, legs=legs,
        front_expiry=short_exp, back_expiry=long_exp,
        front_dte=short_dte, back_dte=long_dte,
    )
    build_candidate_aggregates(candidate)

    # TimeZone is a hybrid: PCS receives credit, calendar pays debit.
    # Net debit can be small/negative. We don't reject on debit sign.
    avg_spread = sum(l.quote.spread_pct for l in candidate.legs) / max(1, len(candidate.legs))
    if avg_spread > settings.max_spread_pct_hard:
        add_rejection(rejections, "spread_too_wide")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    # Planned capital approximation: PCS width * 100 - PCS credit, * qty
    planned_capital = qty * (settings.tz_pcs_width * 100 - pcs_credit_per_contract * 100)
    delta_flat_limit = abs(candidate.position_theta) * 0.10
    delta_flat_ratio = abs(candidate.position_delta) / abs(candidate.position_theta) if candidate.position_theta else float("inf")
    delta_flat_pass = abs(candidate.position_delta) <= delta_flat_limit
    if not delta_flat_pass:
        warnings.append(
            "Delta-flat rule failed: "
            f"|delta| {abs(candidate.position_delta):.2f} > 10% of theta {delta_flat_limit:.2f}."
        )
    # 5% target — translate "days_to_target_pct" to days for theta to earn 5%
    # of planned capital. We hand the scoring layer 0.05 via tp override.
    candidate.extras.update({
        "approx_range": settings.tz_pcs_width * 1.5,   # rough tent: from PCS short up through cal strike
        "pcs_short_strike": pcs_short.strike,
        "pcs_long_strike": pcs_long.strike,
        "cal_strike": cal_short.strike,
        "pcs_credit": pcs_credit_per_contract,
        "planned_capital": planned_capital,
        "quantity": qty,
        "target_pct": 0.05,   # TimeZone TP is 5%, not 10%
        "time_stop_dte": 7,
        "delta_flat_limit": delta_flat_limit,
        "delta_flat_pass": delta_flat_pass,
        "delta_flat_ratio": delta_flat_ratio,
    })
    candidates.append(candidate)
    return candidates, {"rejection_reasons": rejections, "warnings": warnings}
