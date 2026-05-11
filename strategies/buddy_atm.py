"""buddy_atm — Generic ATM single-calendar enumerator (faithful to buddy's app.py).

Behaviour:
- ATM strike rounded to nearest 5
- Enumerate ALL valid (short_dte, long_dte) pairs in the DTE window
- Compute theta/debit, range/debit, days_to_10%, vega/debit per pair
- Build a short_dte × long_dte heatmap pivot for "best of the day" discovery

This complements the rule-based strategies (Triple/TimeEdge/TimeZone) by
showing what the chain itself is offering today regardless of strategy rules.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from scanner.models import CalendarCandidate, CalendarLeg, OptionQuote, RegimeSnapshot, ScanSettings
from strategies.base import (
    add_rejection,
    atm_round,
    build_candidate_aggregates,
    nearest_by_strike,
)


NAME = "buddy_atm"


def needed_rights(settings: ScanSettings) -> tuple[str, ...]:
    return (settings.buddy_right,)


def build(
    symbol: str,
    quotes_by_expiry: dict[str, list[OptionQuote]],
    dte_by_expiry: dict[str, int],
    settings: ScanSettings,
    regime: RegimeSnapshot | None,
    underlying_price: float | None,
) -> tuple[list[CalendarCandidate], dict[str, Any]]:
    """Build ATM single-calendar candidates by enumerating expiry pairs."""
    rejections: dict[str, int] = {}
    warnings: list[str] = []
    candidates: list[CalendarCandidate] = []

    if underlying_price is None or underlying_price <= 0:
        return candidates, {"rejection_reasons": rejections, "warnings": ["No underlying price for buddy_atm."]}

    # Use 5-pt rounding for SPX/RUT, 1-pt for SPY/QQQ (rough heuristic)
    increment = 5.0 if symbol.upper() in {"SPX", "SPXW", "RUT", "NDX"} else 1.0
    atm_strike = atm_round(underlying_price, increment)

    # Narrow DTE window to buddy defaults
    bd_dte_by_expiry = {
        exp: dte for exp, dte in dte_by_expiry.items()
        if settings.buddy_min_short_dte <= dte <= settings.buddy_max_long_dte
    }
    if not bd_dte_by_expiry:
        warnings.append("No expiries in buddy_atm DTE window.")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    # Pre-pick the ATM put (or call) per expiry, keyed by expiry
    atm_quote_by_expiry: dict[str, OptionQuote] = {}
    for exp, quotes in quotes_by_expiry.items():
        if exp not in bd_dte_by_expiry:
            continue
        # Filter by the requested right
        filtered = [q for q in quotes if q.right.upper() == settings.buddy_right.upper()]
        atm = nearest_by_strike(filtered, atm_strike)
        if atm is not None:
            atm_quote_by_expiry[exp] = atm

    expiries_sorted = sorted(atm_quote_by_expiry.keys(), key=lambda e: bd_dte_by_expiry[e])

    for short_exp in expiries_sorted:
        for long_exp in expiries_sorted:
            short_dte = bd_dte_by_expiry[short_exp]
            long_dte = bd_dte_by_expiry[long_exp]
            if long_dte <= short_dte:
                continue
            short_q = atm_quote_by_expiry[short_exp]
            long_q = atm_quote_by_expiry[long_exp]

            # Hard spread filter
            if short_q.spread_pct > settings.max_spread_pct_hard or long_q.spread_pct > settings.max_spread_pct_hard:
                add_rejection(rejections, "spread_too_wide")
                continue

            # Theta must be positive (long calendar)
            short_theta = short_q.theta
            long_theta = long_q.theta
            if short_theta is None or long_theta is None:
                add_rejection(rejections, "missing_theta")
                continue
            net_theta = abs(short_theta) - abs(long_theta)
            if net_theta <= settings.min_net_theta:
                add_rejection(rejections, "non_positive_net_theta")
                continue

            short_leg = CalendarLeg("CAL_short", "SELL", 1, short_q, role="atm_cal_short")
            long_leg = CalendarLeg("CAL_long", "BUY", 1, long_q, role="atm_cal_long")
            candidate = CalendarCandidate(
                strategy=NAME,
                symbol=symbol,
                legs=[short_leg, long_leg],
                front_expiry=short_exp,
                back_expiry=long_exp,
                front_dte=short_dte,
                back_dte=long_dte,
            )
            build_candidate_aggregates(candidate)

            if candidate.net_debit <= 0:
                add_rejection(rejections, "non_positive_debit")
                continue

            # Approx range for ATM single cal: ~4x debit (buddy's heuristic)
            candidate.extras["approx_range"] = candidate.net_debit * 4.0
            candidate.extras["atm_strike"] = atm_strike
            candidates.append(candidate)

    # Heatmap pivot for the UI
    if candidates:
        df = pd.DataFrame([{
            "short_dte": c.front_dte, "long_dte": c.back_dte,
            "theta_debit_ratio": c.total_theta / c.net_debit if c.net_debit > 0 else 0,
            "net_debit": c.net_debit,
        } for c in candidates])
        heatmap_pivot = df.pivot_table(index="short_dte", columns="long_dte", values="theta_debit_ratio", aggfunc="mean")
    else:
        heatmap_pivot = pd.DataFrame()

    extras: dict[str, Any] = {
        "rejection_reasons": rejections,
        "warnings": warnings,
        "atm_strike": atm_strike,
        "heatmap_pivot": heatmap_pivot,
    }
    return candidates, extras
