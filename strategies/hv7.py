"""HV7 Option Trading System.

Reference: docs/strategies_html/HV7.html

Scanner mapping:
- SPX/RUT put broken-wing butterfly
- Weekly expiry with at least 7 DTE
- Entry only when HV7 event trigger is confirmed externally
"""

from __future__ import annotations

from typing import Any

from scanner.models import CalendarCandidate, OptionQuote, RegimeSnapshot, ScanSettings
from strategies.base import add_rejection, build_bwb_legs, build_candidate_aggregates, first_expiry_in_dte_window


NAME = "hv7_bwb"


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

    if not settings.hv7_trigger_confirmed:
        warnings.append("HV7 trigger not confirmed: requires same-day index drop and VIX threshold before entry.")

    expiry = first_expiry_in_dte_window(dte_by_expiry, settings.hv7_min_dte, settings.hv7_max_dte)
    if expiry is None:
        warnings.append(f"No expiry in HV7 DTE window {settings.hv7_min_dte}-{settings.hv7_max_dte}.")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    legs = build_bwb_legs(
        quotes_by_expiry.get(expiry, []),
        "P",
        settings.hv7_upper_delta,
        settings.hv7_short_delta,
        settings.hv7_lower_delta,
        "HV7_PUT_BWB",
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
        "trigger_confirmed": settings.hv7_trigger_confirmed,
        "bwb_width_upper": upper_width,
        "bwb_width_lower": lower_width,
        "target_pct": 0.05,
        "time_stop_dte": 0,
        "management_note": "HV7 reference says no adjustments; exit before expiration day.",
        "approx_range": max(upper_width + lower_width, 1.0),
    })
    candidates.append(candidate)
    return candidates, {"rejection_reasons": rejections, "warnings": warnings}
