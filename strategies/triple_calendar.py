"""Triple Calendar Spread.

Rules (from docs/strategies_html/Tripple Calendar.html):
- Underlying: QQQ preferred, SPY/SPX work. Avoid earnings.
- Enter Fridays.
- Short leg: 21 DTE. Long leg: 28 DTE (1 week after short).
- Middle calendar: ATM, rounded to nearest 5
- Determine Expected Move from 21 DTE ATM straddle (P+C). If only puts in
  scan, falls back to 2 * ATM put mid.
- Upper calendar: ATM + EM + ~5 margin
- Lower calendar: ATM - EM - ~5 margin
- All three calendars share short=21 DTE / long=28 DTE
- TP 10% of debit. Hard time stop at 7 days to short expiration (~14 days in).
- +vega strategy.
"""

from __future__ import annotations

from typing import Any

from scanner.models import CalendarCandidate, CalendarLeg, OptionQuote, RegimeSnapshot, ScanSettings
from strategies.base import (
    add_rejection,
    atm_round,
    build_candidate_aggregates,
    expected_move_for_expiry,
    expiry_pair_by_target_dte,
    nearest_by_strike,
)


NAME = "triple_calendar"


def needed_rights(settings: ScanSettings) -> tuple[str, ...]:
    # Need puts for the calendar legs. Calls only needed if you want EM from
    # full straddle; otherwise EM fallback (2 * ATM put mid) is used.
    if settings.triple_require_full_straddle and settings.triple_right.upper() == "P":
        return ("P", "C")
    return (settings.triple_right,)


def _build_one_calendar(
    symbol: str,
    short_exp: str,
    long_exp: str,
    short_dte: int,
    long_dte: int,
    target_strike: float,
    quotes_by_expiry: dict[str, list[OptionQuote]],
    label: str,
    settings: ScanSettings,
) -> tuple[CalendarLeg, CalendarLeg] | None:
    """Pick short/long quotes at target_strike for the given expiry pair."""
    short_q = nearest_by_strike(
        [q for q in quotes_by_expiry.get(short_exp, []) if q.right.upper() == settings.triple_right.upper()],
        target_strike,
    )
    long_q = nearest_by_strike(
        [q for q in quotes_by_expiry.get(long_exp, []) if q.right.upper() == settings.triple_right.upper()],
        target_strike,
    )
    if short_q is None or long_q is None:
        return None
    short_leg = CalendarLeg(f"{label}_short", "SELL", 1, short_q, role=f"{label}_short")
    long_leg = CalendarLeg(f"{label}_long", "BUY", 1, long_q, role=f"{label}_long")
    return short_leg, long_leg


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
        return candidates, {"rejection_reasons": rejections, "warnings": ["No underlying price for triple_calendar."]}

    # Pick the expiry pair closest to (21, 28) DTE
    pair = expiry_pair_by_target_dte(
        dte_by_expiry,
        settings.triple_short_dte,
        settings.triple_long_dte,
        settings.triple_dte_tolerance,
    )
    if pair is None:
        warnings.append(f"No (short~{settings.triple_short_dte}, long~{settings.triple_long_dte}) expiry pair within ±{settings.triple_dte_tolerance} DTE.")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    short_exp, long_exp = pair
    short_dte = dte_by_expiry[short_exp]
    long_dte = dte_by_expiry[long_exp]

    increment = 5.0 if symbol.upper() in {"SPX", "SPXW", "RUT", "NDX"} else 1.0
    atm_strike = atm_round(underlying_price, increment)

    # Expected move from ATM straddle at SHORT expiry (the rule book is clear: 21 DTE straddle)
    calls_by_expiry = {
        exp: [q for q in quotes if q.right.upper() == "C"]
        for exp, quotes in quotes_by_expiry.items()
    }
    em = expected_move_for_expiry(quotes_by_expiry, short_exp, underlying_price, calls_by_expiry)
    if em is None or em <= 0:
        warnings.append("Could not compute expected move from ATM straddle.")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}
    if settings.triple_require_full_straddle and not calls_by_expiry.get(short_exp):
        warnings.append("Full-straddle EM required, but no call quotes were available.")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    margin = settings.triple_em_margin
    upper_target = atm_round(underlying_price + em + margin, increment)
    lower_target = atm_round(underlying_price - em - margin, increment)

    middle = _build_one_calendar(symbol, short_exp, long_exp, short_dte, long_dte, atm_strike, quotes_by_expiry, "middle", settings)
    upper = _build_one_calendar(symbol, short_exp, long_exp, short_dte, long_dte, upper_target, quotes_by_expiry, "upper", settings)
    lower = _build_one_calendar(symbol, short_exp, long_exp, short_dte, long_dte, lower_target, quotes_by_expiry, "lower", settings)
    if middle is None or upper is None or lower is None:
        add_rejection(rejections, "missing_leg_quotes")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    legs = [middle[0], middle[1], upper[0], upper[1], lower[0], lower[1]]
    candidate = CalendarCandidate(
        strategy=NAME,
        symbol=symbol,
        legs=legs,
        front_expiry=short_exp,
        back_expiry=long_exp,
        front_dte=short_dte,
        back_dte=long_dte,
    )
    build_candidate_aggregates(candidate)

    if candidate.net_debit <= 0:
        add_rejection(rejections, "non_positive_debit")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    # Spread filter
    avg_spread_legs = sum(l.quote.spread_pct for l in candidate.legs) / max(1, len(candidate.legs))
    if avg_spread_legs > settings.max_spread_pct_hard:
        add_rejection(rejections, "spread_too_wide")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    # Triple Cal effective tent width: roughly 2 * EM + 2 * margin (overlapping tents cover
    # ATM ± (EM + margin)). Use that as approx_range for range/debit metric.
    candidate.extras.update({
        "approx_range": 2.0 * (em + margin),
        "atm_strike": atm_strike,
        "upper_strike": upper_target,
        "lower_strike": lower_target,
        "expected_move": em,
        "em_margin": margin,
        "time_stop_dte": short_dte - 7,  # close at 7 days remaining on short
    })
    candidates.append(candidate)

    return candidates, {"rejection_reasons": rejections, "warnings": warnings}
