"""Flux IV ratio analytics for double-calendar entry timing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from scanner.models import OptionQuote


@dataclass(frozen=True)
class FluxSignal:
    current_ratio: float
    previous_ratio: float | None
    change_pct: float
    status: str
    reason: str


def average_iv(quotes: Iterable[OptionQuote]) -> float | None:
    values = [
        float(q.implied_vol)
        for q in quotes
        if q.implied_vol is not None and q.implied_vol > 0
    ]
    if not values:
        return None
    return sum(values) / len(values)


def iv_ratio(front_quotes: Iterable[OptionQuote], back_quotes: Iterable[OptionQuote]) -> float | None:
    front_iv = average_iv(front_quotes)
    back_iv = average_iv(back_quotes)
    if front_iv is None or back_iv is None or back_iv <= 0:
        return None
    return front_iv / back_iv


def classify_flux_signal(
    current_ratio: float | None,
    previous_ratio: float | None = None,
    spike_threshold: float = 0.03,
    absolute_high_ratio: float = 1.08,
) -> FluxSignal:
    if current_ratio is None or current_ratio <= 0:
        return FluxSignal(0.0, previous_ratio, 0.0, "NO_DATA", "Missing IV ratio.")

    change_pct = 0.0
    if previous_ratio is not None and previous_ratio > 0:
        change_pct = (current_ratio - previous_ratio) / previous_ratio

    if previous_ratio is not None and change_pct >= spike_threshold:
        return FluxSignal(
            current_ratio,
            previous_ratio,
            change_pct,
            "ENTRY_SIGNAL",
            f"IV ratio spike {change_pct * 100:.1f}% from prior snapshot.",
        )
    if previous_ratio is not None:
        return FluxSignal(current_ratio, previous_ratio, change_pct, "WAIT", "IV ratio is elevated but not spiking.")
    if current_ratio >= absolute_high_ratio:
        return FluxSignal(
            current_ratio,
            previous_ratio,
            change_pct,
            "WATCH",
            f"IV ratio elevated at {current_ratio:.2f}; wait for spike confirmation if no prior snapshot.",
        )
    return FluxSignal(current_ratio, previous_ratio, change_pct, "WAIT", "IV ratio is flat or not elevated.")


def ratio_rows_for_pairs(
    quotes_by_expiry: dict[str, list[OptionQuote]],
    dte_by_expiry: dict[str, int],
    gap_days: int = 7,
) -> list[dict[str, float | int | str | None]]:
    rows: list[dict[str, float | int | str | None]] = []
    expiries = sorted(dte_by_expiry, key=lambda e: dte_by_expiry[e])
    for front_expiry in expiries:
        front_dte = dte_by_expiry[front_expiry]
        for back_expiry in expiries:
            back_dte = dte_by_expiry[back_expiry]
            if back_dte - front_dte != gap_days:
                continue
            front_quotes = quotes_by_expiry.get(front_expiry, [])
            back_quotes = quotes_by_expiry.get(back_expiry, [])
            ratio = iv_ratio(front_quotes, back_quotes)
            signal = classify_flux_signal(ratio)
            rows.append({
                "front_expiry": front_expiry,
                "back_expiry": back_expiry,
                "front_dte": front_dte,
                "back_dte": back_dte,
                "front_iv": average_iv(front_quotes),
                "back_iv": average_iv(back_quotes),
                "iv_ratio": ratio,
                "signal": signal.status,
                "reason": signal.reason,
            })
    return rows
