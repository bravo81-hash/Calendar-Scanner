"""Risk chart for calendar / diagonal / combo candidates.

Differences from the Batman scanner:
- Prices puts AND calls (uses right field on each leg)
- Handles multi-expiry legs (calendars naturally have different DTEs per leg)
- IV calibrated to observed mid per-leg via bisection (call or put pricer)

Purpose: quick visual triage. Not a replacement for OptionNet Explorer.
"""

from __future__ import annotations

from functools import lru_cache
from math import erf, exp, isclose, log, pi, sqrt

import pandas as pd

from scanner.models import CalendarCandidate, CalendarLeg


CONTRACT_MULTIPLIER = 100


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def _d1_d2(S: float, K: float, T: float, sigma: float, r: float, q: float) -> tuple[float, float]:
    sigma_sqrt_t = sigma * sqrt(T)
    d1 = (log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / sigma_sqrt_t
    d2 = d1 - sigma_sqrt_t
    return d1, d2


def bs_price(S: float, K: float, T: float, sigma: float, right: str, r: float = 0.045, q: float = 0.013) -> float:
    """Black-Scholes-Merton European price for put or call."""
    if S <= 0 or K <= 0:
        return 0.0
    if T <= 0 or sigma <= 0:
        return max((S - K) if right.upper().startswith("C") else (K - S), 0.0)
    d1, d2 = _d1_d2(S, K, T, sigma, r, q)
    disc_S = S * exp(-q * T)
    disc_K = K * exp(-r * T)
    if right.upper().startswith("C"):
        return disc_S * _norm_cdf(d1) - disc_K * _norm_cdf(d2)
    return disc_K * _norm_cdf(-d2) - disc_S * _norm_cdf(-d1)


def bs_greeks(S: float, K: float, T: float, sigma: float, right: str, r: float = 0.045, q: float = 0.013) -> dict[str, float]:
    """Per-contract Greeks (option-price units, theta per day, vega per vol-point)."""
    if S <= 0 or K <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    if T <= 0 or sigma <= 0:
        intrinsic_delta = 1.0 if right.upper().startswith("C") and S > K else (-1.0 if right.upper().startswith("P") and S < K else 0.0)
        return {"delta": intrinsic_delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    d1, d2 = _d1_d2(S, K, T, sigma, r, q)
    disc_S = exp(-q * T)
    disc_K = exp(-r * T)
    pdf_d1 = _norm_pdf(d1)

    if right.upper().startswith("C"):
        delta = disc_S * _norm_cdf(d1)
        theta_raw = (
            -S * disc_S * pdf_d1 * sigma / (2 * sqrt(T))
            - r * K * disc_K * _norm_cdf(d2)
            + q * S * disc_S * _norm_cdf(d1)
        )
    else:
        delta = -disc_S * _norm_cdf(-d1)
        theta_raw = (
            -S * disc_S * pdf_d1 * sigma / (2 * sqrt(T))
            + r * K * disc_K * _norm_cdf(-d2)
            - q * S * disc_S * _norm_cdf(-d1)
        )
    gamma = disc_S * pdf_d1 / (S * sigma * sqrt(T))
    vega = S * disc_S * pdf_d1 * sqrt(T) / 100.0
    theta = theta_raw / 365.0
    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


def implied_vol_from_price(S: float, K: float, T: float, observed_price: float, right: str, fallback_iv: float = 0.20, r: float = 0.045, q: float = 0.013) -> float:
    """Bisect for sigma matching observed_price. Falls back if intrinsic exceeds price."""
    intrinsic = max((S - K) if right.upper().startswith("C") else (K - S), 0.0)
    if S <= 0 or K <= 0 or T <= 0 or observed_price <= intrinsic:
        return fallback_iv
    lo, hi = 0.0001, 5.0
    for _ in range(80):
        mid = (lo + hi) / 2
        model = bs_price(S, K, T, mid, right, r, q)
        if isclose(model, observed_price, rel_tol=1e-8, abs_tol=1e-8):
            return mid
        if model < observed_price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def projection_days(horizon_dte: int, points: int = 5) -> list[int]:
    if points <= 1 or horizon_dte <= 0:
        return [0]
    return sorted(set(round(horizon_dte * i / (points - 1)) for i in range(points)))


# ---------------------------------------------------------------------------
# Multi-leg scenario engine
# ---------------------------------------------------------------------------


def _leg_starting_dte(leg: CalendarLeg, candidate: CalendarCandidate) -> int:
    """Use leg.quote.expiry to determine its expiry; map to front/back DTE."""
    if leg.quote.expiry == candidate.back_expiry:
        return candidate.back_dte
    return candidate.front_dte


def _leg_years_to_expiry(leg: CalendarLeg, candidate: CalendarCandidate, elapsed_days: int) -> float:
    remaining = max(_leg_starting_dte(leg, candidate) - elapsed_days, 0)
    return remaining / 365.0


@lru_cache(maxsize=8192)
def _calibrated_iv_cached(strike: float, mid: float, T0: float, right: str, fallback_iv: float, spot: float, r: float, q: float) -> float:
    return implied_vol_from_price(spot, strike, T0, mid, right, fallback_iv, r, q)


def _leg_calibrated_iv(leg: CalendarLeg, candidate: CalendarCandidate, spot: float, r: float, q: float) -> float:
    fallback = leg.quote.implied_vol or 0.20
    mid = leg.quote.mid
    if mid is None or mid <= 0:
        return fallback
    T0 = _leg_years_to_expiry(leg, candidate, 0)
    if T0 <= 0:
        return fallback
    return _calibrated_iv_cached(leg.quote.strike, mid, T0, leg.quote.right, fallback, spot, r, q)


def _scenario_leg_price(leg: CalendarLeg, candidate: CalendarCandidate, S: float, elapsed_days: int, spot: float, r: float, q: float) -> float:
    T = _leg_years_to_expiry(leg, candidate, elapsed_days)
    intrinsic = max((S - leg.quote.strike) if leg.quote.right.upper().startswith("C") else (leg.quote.strike - S), 0.0)
    if T <= 0:
        return intrinsic
    iv = _leg_calibrated_iv(leg, candidate, spot, r, q)
    px = bs_price(S, leg.quote.strike, T, iv, leg.quote.right, r, q)
    return max(px, intrinsic, 0.0)


def _candidate_mark_value(candidate: CalendarCandidate, S: float, elapsed_days: int, spot: float, r: float, q: float) -> float:
    """Total mark (dollars) of the position at given underlying & days elapsed.

    Sign convention: long legs contribute +price; short legs contribute -price.
    This is the marked value of the open position, NOT pnl.
    """
    total = 0.0
    for leg in candidate.legs:
        px = _scenario_leg_price(leg, candidate, S, elapsed_days, spot, r, q)
        total += leg.signed_quantity * px * CONTRACT_MULTIPLIER
    return total


def _candidate_greeks(candidate: CalendarCandidate, S: float, elapsed_days: int, spot: float, r: float, q: float) -> dict[str, float]:
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for leg in candidate.legs:
        T = _leg_years_to_expiry(leg, candidate, elapsed_days)
        iv = _leg_calibrated_iv(leg, candidate, spot, r, q)
        g = bs_greeks(S, leg.quote.strike, T, iv, leg.quote.right, r, q)
        for k in totals:
            totals[k] += leg.signed_quantity * g[k] * CONTRACT_MULTIPLIER
    return totals


def candidate_risk_frame(
    candidate: CalendarCandidate,
    spot_price: float,
    price_points: int = 121,
    projection_count: int = 5,
    lower_multiplier: float = 0.85,
    upper_multiplier: float = 1.15,
    risk_free_rate: float = 0.045,
    dividend_yield: float = 0.013,
    projection_horizon: str = "front",
) -> pd.DataFrame:
    """PnL and Greeks across underlying prices and projection dates."""
    if spot_price <= 0:
        return pd.DataFrame()

    low = max(spot_price * lower_multiplier, 1.0)
    high = max(spot_price * upper_multiplier, low + 1.0)
    if price_points <= 1:
        prices = [spot_price]
    else:
        step = (high - low) / (price_points - 1)
        prices = [low + step * i for i in range(price_points)]

    horizon_dte = candidate.front_dte if projection_horizon == "front" else candidate.back_dte
    projections = projection_days(horizon_dte, projection_count)
    r, q = risk_free_rate, dividend_yield
    entry_mark = _candidate_mark_value(candidate, spot_price, 0, spot_price, r, q)
    # Conservative entry credit/debit in dollars (short=bid, long=ask)
    executable_entry = sum(
        leg.signed_quantity * leg.conservative_price * CONTRACT_MULTIPLIER
        for leg in candidate.legs
    )

    rows = []
    for elapsed in projections:
        for S in prices:
            mark = _candidate_mark_value(candidate, S, elapsed, spot_price, r, q)
            greeks = _candidate_greeks(candidate, S, elapsed, spot_price, r, q)
            mid_pnl = mark - entry_mark
            executable_pnl = mark - executable_entry
            rows.append({
                "underlying_price": S,
                "projection_day": elapsed,
                "projection_label": f"T+{elapsed}",
                "pnl": mid_pnl,
                "mid_normalized_pnl": mid_pnl,
                "executable_pnl": executable_pnl,
                "delta": greeks["delta"],
                "gamma": greeks["gamma"],
                "theta": greeks["theta"],
                "vega": greeks["vega"],
            })
    return pd.DataFrame(rows)
