"""A14 Weekly Strategy.

Reference: docs/strategies_html/A14.html

Scanner mapping:
- SPX put broken-wing butterfly
- Standard target around 14 DTE
- Delta handles roughly 50 / 35 / 20
- Profit target 5% of margin
"""

from __future__ import annotations

from typing import Any

from scanner.models import CalendarCandidate, OptionQuote, RegimeSnapshot, ScanSettings
from strategies.base import (
    add_rejection,
    build_bwb_legs,
    build_candidate_aggregates,
    expiry_by_target_dte,
)


NAME = "a14_bwb"


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

    expiry = expiry_by_target_dte(dte_by_expiry, settings.a14_dte, settings.a14_dte_tolerance)
    if expiry is None:
        warnings.append(f"No expiry near {settings.a14_dte} DTE for A14.")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    legs = build_bwb_legs(
        quotes_by_expiry.get(expiry, []),
        "P",
        settings.a14_upper_delta,
        settings.a14_short_delta,
        settings.a14_lower_delta,
        "A14_PUT_BWB",
    )
    if legs is None:
        add_rejection(rejections, "missing_bwb_legs")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    dte = dte_by_expiry[expiry]
    candidate = CalendarCandidate(
        strategy=NAME,
        symbol=symbol,
        legs=legs,
        front_expiry=expiry,
        back_expiry=expiry,
        front_dte=dte,
        back_dte=dte,
    )
    build_candidate_aggregates(candidate)
    upper_width = abs(legs[0].quote.strike - legs[1].quote.strike)
    lower_width = abs(legs[1].quote.strike - legs[2].quote.strike)
    candidate.extras.update({
        "structure": "put_broken_wing_butterfly",
        "bwb_width_upper": upper_width,
        "bwb_width_lower": lower_width,
        "target_pct": 0.05,
        "time_stop_dte": 2,
        "management_note": "Reference includes optional calendar hedges; scanner only builds the initial BWB.",
        "approx_range": max(upper_width + lower_width, 1.0),
    })
    candidates.append(candidate)
    return candidates, {"rejection_reasons": rejections, "warnings": warnings}
