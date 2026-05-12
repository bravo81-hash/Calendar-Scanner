"""Option chain orchestration: strike-window selection, expiry filtering, scan driver.

Differences from the Batman scanner:
- ATM-centred strike windows (calendars want strikes near spot, not far OTM)
- Supports both rights ("P" and "C")
- Strategy-agnostic: strategies/* modules supply the candidate builder
"""

from __future__ import annotations

from datetime import date
from typing import Callable, Optional, Tuple

from scanner.contracts import days_to_expiry
from scanner.models import OptionQuote, RegimeSnapshot, ScanResult, ScanSettings


ProgressCallback = Callable[[str], None]


def select_candidate_strikes(
    strikes: list[float],
    underlying_price: float | None,
    max_contracts: int,
    lower_multiplier: float = 0.85,
    upper_multiplier: float = 1.15,
    strike_increment: int = 0,
) -> list[float]:
    """Return an ATM-centred strike list bounded by max_contracts.

    Uses spot * [lower, upper] window so far-OTM strikes don't dominate
    market-data requests when the strategy only cares about ATM-ish prints.
    """
    clean = sorted(float(strike) for strike in strikes if float(strike) > 0)
    if strike_increment > 0:
        clean = [strike for strike in clean if round(strike) % strike_increment == 0]
    if not clean or max_contracts <= 0:
        return []

    if underlying_price is not None and underlying_price > 0:
        lower = underlying_price * max(lower_multiplier, 0.1)
        upper = underlying_price * max(upper_multiplier, 1.0)
        window = [strike for strike in clean if lower <= strike <= upper]
        if not window:
            window = clean

        # Always include the strike closest to spot
        closest_to_spot = min(window, key=lambda s: abs(s - underlying_price))

        # Split into below and above spot, take symmetric coverage
        below = [s for s in window if s <= underlying_price]
        above = [s for s in window if s > underlying_price]
        half = max(1, max_contracts // 2)
        selected = set()
        selected.update(_evenly_spaced(below, min(half, len(below))))
        selected.update(_evenly_spaced(above, min(max_contracts - len(selected), len(above))))
        selected.add(closest_to_spot)

        final = sorted(selected)
        while len(final) > max_contracts:
            removable = [s for s in final if s != closest_to_spot]
            if not removable:
                break
            # Drop the farthest from spot first
            farthest = max(removable, key=lambda s: abs(s - underlying_price))
            final.remove(farthest)
        return final

    # No underlying price: return a centred slice of the chain
    midpoint = len(clean) // 2
    half = max_contracts // 2
    start = max(midpoint - half, 0)
    end = min(start + max_contracts, len(clean))
    start = max(end - max_contracts, 0)
    return clean[start:end]


def _evenly_spaced(values: list[float], count: int) -> list[float]:
    if count <= 0 or not values:
        return []
    if count >= len(values):
        return list(values)
    if count == 1:
        return [values[len(values) // 2]]
    last = len(values) - 1
    indexes = [round(i * last / (count - 1)) for i in range(count)]
    return [values[i] for i in indexes]


def filter_expiries(
    expiries: list[str],
    settings: ScanSettings,
    as_of: date | None = None,
    min_dte_override: int | None = None,
    max_dte_override: int | None = None,
) -> dict[str, int]:
    """Return {expiry: dte} for expiries inside the strategy DTE window."""
    min_dte = settings.min_short_dte if min_dte_override is None else min_dte_override
    max_dte = settings.max_long_dte if max_dte_override is None else max_dte_override
    dte_by_expiry: dict[str, int] = {}
    for expiry in expiries:
        try:
            dte = days_to_expiry(expiry, as_of)
        except Exception:
            continue
        if min_dte <= dte <= max_dte:
            dte_by_expiry[expiry] = dte
    return dte_by_expiry


def quote_diagnostic_counts(quotes: list[OptionQuote]) -> dict[str, Any]:
    counts: dict[str, Any] = {
        "total": len(quotes),
        "usable": 0,
        "missing": 0,
        "missing_bid_ask": 0,
        "invalid_bid_ask": 0,
        "missing_delta": 0,
        "min_usable_strike": 0.0,
        "max_usable_strike": 0.0,
    }
    usable_strikes: list[float] = []
    for q in quotes:
        if q.has_required_data():
            counts["usable"] += 1
            usable_strikes.append(q.strike)
            continue
        counts["missing"] += 1
        for reason in q.missing_data_reasons():
            counts[reason] = counts.get(reason, 0) + 1
    if usable_strikes:
        counts["min_usable_strike"] = min(usable_strikes)
        counts["max_usable_strike"] = max(usable_strikes)
    return counts


# Strategies register their builder here. A builder takes everything it needs
# to produce candidates and returns (candidates, extras_dict).
StrategyBuilder = Callable[
    [str, dict[str, list[OptionQuote]], dict[str, int], ScanSettings, Optional[RegimeSnapshot], Optional[float]],
    Tuple[list, dict],
]


def scan_from_quote_fetcher(
    settings: ScanSettings,
    expiries: list[str],
    fetch_quotes_for_expiry: Callable[[str], list[OptionQuote]],
    strategy_builder: StrategyBuilder,
    regime: "RegimeSnapshot | None" = None,
    underlying_price: float | None = None,
    progress: ProgressCallback | None = None,
) -> ScanResult:
    """Generic scan: filter expiries, fetch quotes, dispatch to strategy builder."""
    progress = progress or (lambda msg: None)
    progress("filtering expiries")
    dte_by_expiry = filter_expiries(expiries, settings)
    if not dte_by_expiry:
        return ScanResult(
            settings=settings,
            strategy=settings.strategy,
            candidates=[],
            warnings=["No expiries matched the DTE window."],
            regime=regime,
        )

    quotes_by_expiry: dict[str, list[OptionQuote]] = {}
    quote_counts_by_expiry: dict[str, dict[str, Any]] = {}
    for expiry in sorted(dte_by_expiry):
        progress(f"requesting quotes for {expiry}")
        quotes = fetch_quotes_for_expiry(expiry)
        usable = [q for q in quotes if q.has_required_data()]
        quote_counts_by_expiry[expiry] = quote_diagnostic_counts(quotes)
        if usable:
            quotes_by_expiry[expiry] = usable

    progress("building candidates")
    candidates, extras = strategy_builder(
        settings.symbol, quotes_by_expiry, dte_by_expiry, settings, regime, underlying_price
    )

    return ScanResult(
        settings=settings,
        strategy=settings.strategy,
        candidates=candidates[: settings.max_results],
        underlying_price=underlying_price,
        quote_counts_by_expiry=quote_counts_by_expiry,
        rejection_reasons=extras.pop("rejection_reasons", {}) if isinstance(extras, dict) else {},
        warnings=extras.pop("warnings", []) if isinstance(extras, dict) else [],
        regime=regime,
        extras=extras or {},
    )


# Late import to keep module importable without the regime dataclass yet
from scanner.models import RegimeSnapshot  # noqa: E402,F401
