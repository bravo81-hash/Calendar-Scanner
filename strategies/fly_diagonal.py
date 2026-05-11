"""FlyDiagonal.

Reference: docs/strategies_html/FlyDiagonal.html

Scanner mapping:
- Call broken-wing butterfly above spot
- Put diagonal / time spread below spot
- Advanced 8-leg variants remain documented references, not automated here
"""

from __future__ import annotations

from typing import Any

from scanner.models import CalendarCandidate, CalendarLeg, OptionQuote, RegimeSnapshot, ScanSettings
from strategies.base import (
    add_rejection,
    build_bwb_legs,
    build_candidate_aggregates,
    expiry_pair_by_target_dte,
    nearest_by_abs_delta,
    nearest_by_strike,
)


NAME = "fly_diagonal"


def needed_rights(settings: ScanSettings) -> tuple[str, ...]:
    return ("P", "C")


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

    pair = expiry_pair_by_target_dte(
        dte_by_expiry,
        settings.fly_short_dte,
        settings.fly_long_dte,
        settings.fly_dte_tolerance,
    )
    if pair is None:
        warnings.append(f"No FlyDiagonal expiry pair near {settings.fly_short_dte}/{settings.fly_long_dte} DTE.")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    short_exp, long_exp = pair
    short_quotes = quotes_by_expiry.get(short_exp, [])
    long_quotes = quotes_by_expiry.get(long_exp, [])

    call_bwb = build_bwb_legs(
        short_quotes,
        "C",
        settings.fly_call_lower_delta,
        settings.fly_call_short_delta,
        settings.fly_call_upper_delta,
        "FLY_CALL_BWB",
    )
    if call_bwb is None:
        add_rejection(rejections, "missing_call_bwb_legs")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    front_puts = [q for q in short_quotes if q.right.upper() == "P"]
    back_puts = [q for q in long_quotes if q.right.upper() == "P"]
    put_short = nearest_by_abs_delta(front_puts, settings.fly_put_short_delta)
    if put_short is None:
        add_rejection(rejections, "missing_put_diagonal_short")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}
    put_long = nearest_by_strike(back_puts, put_short.strike - settings.fly_put_strike_gap)
    if put_long is None:
        add_rejection(rejections, "missing_put_diagonal_long")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    legs = [
        *call_bwb,
        CalendarLeg("FLY_PUT_DIAG_short", "SELL", 1, put_short, role="put_diagonal_short"),
        CalendarLeg("FLY_PUT_DIAG_long", "BUY", 1, put_long, role="put_diagonal_long"),
    ]
    candidate = CalendarCandidate(
        strategy=NAME,
        symbol=symbol,
        legs=legs,
        front_expiry=short_exp,
        back_expiry=long_exp,
        front_dte=dte_by_expiry[short_exp],
        back_dte=dte_by_expiry[long_exp],
    )
    build_candidate_aggregates(candidate)
    call_width_1 = abs(call_bwb[0].quote.strike - call_bwb[1].quote.strike)
    call_width_2 = abs(call_bwb[1].quote.strike - call_bwb[2].quote.strike)
    candidate.extras.update({
        "structure": "call_bwb_plus_put_diagonal",
        "call_bwb_width_lower": call_width_1,
        "call_bwb_width_upper": call_width_2,
        "put_diagonal_short_strike": put_short.strike,
        "put_diagonal_long_strike": put_long.strike,
        "put_diagonal_strike_gap": abs(put_short.strike - put_long.strike),
        "target_pct": 0.10,
        "management_note": "Advanced 8-leg FlyDiagonal variants are documented but not automated in this builder.",
        "approx_range": max(call_width_1 + call_width_2 + abs(put_short.strike - put_long.strike), 1.0),
    })
    candidates.append(candidate)
    return candidates, {"rejection_reasons": rejections, "warnings": warnings}
