"""Universal calendar entry-quality scoring.

Metrics ported & extended from buddy's ATM enumerator, applied uniformly across
all strategies (buddy_atm, triple_calendar, time_edge, time_zone).

Core idea: normalise each metric across the candidate set in this scan so the
"best of the day" floats to the top regardless of absolute regime drift.
"""

from __future__ import annotations

import math

from scanner.models import CalendarCandidate, ScanSettings


# ---------------------------------------------------------------------------
# Primitive metrics (pure functions; safe to unit-test)
# ---------------------------------------------------------------------------


def theta_debit_ratio(net_theta: float, net_debit: float) -> float:
    """Net daily theta per dollar of debit. Higher = faster decay relative to cost."""
    if net_debit is None or net_debit <= 0:
        return 0.0
    return float(net_theta) / float(net_debit)


def days_to_target_pct(net_debit: float, net_theta: float, target_pct: float = 0.10) -> float:
    """Days for theta alone to earn target_pct of debit. Lower = faster."""
    if net_theta is None or net_theta <= 0 or net_debit is None or net_debit <= 0:
        return float("inf")
    return (net_debit * target_pct) / net_theta


def range_debit_ratio(approx_range: float, net_debit: float) -> float:
    """Profit tent width per dollar of debit. Higher = more room to be wrong."""
    if net_debit is None or net_debit <= 0:
        return 0.0
    return float(approx_range) / float(net_debit)


def vega_debit_ratio(net_vega: float, net_debit: float) -> float:
    """Vega exposure per dollar of debit (positive for long calendars)."""
    if net_debit is None or net_debit <= 0:
        return 0.0
    return float(net_vega) / float(net_debit)


def expected_move_from_straddle(call_mid: float, put_mid: float) -> float:
    """1-sigma ATM expected move at expiry. Used for Triple Cal upper/lower strikes."""
    return float(call_mid or 0.0) + float(put_mid or 0.0)


def approx_range_from_em(expected_move: float, fraction: float = 1.0) -> float:
    """Approximate calendar profit tent width.

    For a single ATM calendar a reasonable proxy is ~1 EM total span. For
    Triple Cal with overlapping tents the effective width is wider.
    Caller passes the appropriate fraction.
    """
    return float(expected_move) * float(fraction)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def normalize_high_is_good(values: list[float]) -> list[float]:
    """Min-max normalise; NaN/inf → 0; constant column → all 1.0."""
    clean = [v if math.isfinite(v) else float("nan") for v in values]
    finite = [v for v in clean if not math.isnan(v)]
    if not finite:
        return [0.0] * len(values)
    lo, hi = min(finite), max(finite)
    if hi == lo:
        return [1.0 if not math.isnan(v) else 0.0 for v in clean]
    return [
        0.0 if math.isnan(v) else (v - lo) / (hi - lo)
        for v in clean
    ]


def normalize_low_is_good(values: list[float]) -> list[float]:
    clean = [v if math.isfinite(v) else float("nan") for v in values]
    finite = [v for v in clean if not math.isnan(v)]
    if not finite:
        return [0.0] * len(values)
    lo, hi = min(finite), max(finite)
    if hi == lo:
        return [1.0 if not math.isnan(v) else 0.0 for v in clean]
    return [
        0.0 if math.isnan(v) else 1.0 - (v - lo) / (hi - lo)
        for v in clean
    ]


# ---------------------------------------------------------------------------
# Spread / liquidity
# ---------------------------------------------------------------------------


def average_spread_pct(candidate: CalendarCandidate) -> float:
    spreads = []
    for leg in candidate.legs:
        if leg.quote.mid and leg.quote.mid > 0:
            spreads.append(leg.quote.spread_pct)
    if not spreads:
        return 0.0
    return sum(spreads) / len(spreads)


def liquidity_score_from_spread_pct(spread_pct: float, ceiling: float = 20.0) -> float:
    """1.0 when spreads are tight, 0 when at/above ceiling%."""
    if spread_pct <= 0:
        return 1.0
    if spread_pct >= ceiling:
        return 0.0
    return max(0.0, 1.0 - (spread_pct / ceiling))


# ---------------------------------------------------------------------------
# Full candidate ranking pipeline (used by buddy_atm and shared by others)
# ---------------------------------------------------------------------------


def compute_entry_metrics(candidate: CalendarCandidate, target_pct: float) -> None:
    """Populate per-candidate metrics. Approx range is supplied via extras['approx_range']."""
    net_theta = candidate.total_theta
    net_debit = candidate.net_debit
    approx_range = float(candidate.extras.get("approx_range") or (net_debit * 4.0))

    candidate.theta_debit_ratio = theta_debit_ratio(net_theta, net_debit)
    candidate.range_debit_ratio = range_debit_ratio(approx_range, net_debit)
    candidate.days_to_target_pct = days_to_target_pct(net_debit, net_theta, target_pct)
    candidate.vega_debit_ratio = vega_debit_ratio(candidate.total_vega, net_debit)
    candidate.average_spread_pct = average_spread_pct(candidate)
    candidate.liquidity_score = liquidity_score_from_spread_pct(candidate.average_spread_pct)


def rank_candidates(
    candidates: list[CalendarCandidate],
    settings: ScanSettings,
    target_pct: float | None = None,
) -> list[CalendarCandidate]:
    """Normalise metrics across the set, apply user weights + regime multiplier, sort."""
    if not candidates:
        return candidates

    tp = target_pct if target_pct is not None else settings.default_target_pct
    for c in candidates:
        compute_entry_metrics(c, tp)

    theta_scores = normalize_high_is_good([c.theta_debit_ratio for c in candidates])
    range_scores = normalize_high_is_good([c.range_debit_ratio for c in candidates])
    days_scores = normalize_low_is_good([c.days_to_target_pct for c in candidates])
    vega_scores = normalize_high_is_good([c.vega_debit_ratio for c in candidates])
    spread_pens = normalize_low_is_good([c.average_spread_pct for c in candidates])
    # spread_pen normalised so 1.0 = tight; we invert weight sign in score formula

    total_w = (
        settings.w_theta_debit
        + settings.w_range_debit
        + settings.w_days_to_target
        + settings.w_vega_debit
        + settings.w_spread_penalty
    )
    if total_w <= 0:
        total_w = 1.0

    for c, ts, rs, ds, vs, sp in zip(candidates, theta_scores, range_scores, days_scores, vega_scores, spread_pens):
        c.theta_score = ts
        c.range_score = rs
        c.days_score = ds
        c.vega_score = vs
        c.spread_penalty = 1.0 - sp   # higher = worse; subtracted below
        raw = (
            ts * settings.w_theta_debit
            + rs * settings.w_range_debit
            + ds * settings.w_days_to_target
            + vs * settings.w_vega_debit
            + sp * settings.w_spread_penalty
        ) / total_w
        # Regime multiplier (1.0 neutral; <1.0 demote; 0 hard skip)
        c.custom_score = max(0.0, raw * float(c.regime_score))

    candidates.sort(key=lambda c: (c.custom_score, c.theta_debit_ratio, c.total_theta), reverse=True)
    for i, c in enumerate(candidates, start=1):
        c.rank = i
    return candidates
