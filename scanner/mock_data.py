"""Clearly labelled mock data for offline UI testing.

Generates plausible put quotes near ATM at multiple expiries so all four
strategies have something to chew on.
"""

from __future__ import annotations

from datetime import date, timedelta

from scanner.models import OptionQuote


def _put(symbol: str, expiry: str, strike: float, spot: float, dte: int) -> OptionQuote:
    """Synthetic put quote rough enough to exercise the scoring pipeline."""
    # Toy IV ~ 0.18, scaled with sqrt(time)
    import math
    moneyness = (spot - strike) / spot
    # Approx put delta (negative): -0.5 + slope*moneyness
    delta_dec = max(-0.99, min(-0.01, -0.5 + 1.2 * moneyness - 0.005 * dte))
    delta = delta_dec * 100.0
    intrinsic = max(strike - spot, 0.0)
    time_value = max(0.05, 0.18 * spot * math.sqrt(dte / 365.0) * 0.4)
    # OTM puts cheaper than ATM
    distance_factor = math.exp(-2.0 * abs(moneyness))
    mid = round(intrinsic + time_value * distance_factor, 2)
    if mid < 0.05:
        mid = 0.05
    bid = round(mid - 0.10, 2)
    ask = round(mid + 0.10, 2)
    if bid < 0:
        bid = max(0.01, mid - 0.05)
        ask = round(bid + 0.10, 2)

    theta = -round(time_value * distance_factor / max(dte, 1), 4)
    vega = round(0.5 * distance_factor + 0.2, 4)
    gamma = round(0.001 + 0.005 * distance_factor / max(dte, 1), 6)
    return OptionQuote(
        symbol=symbol, expiry=expiry, strike=strike, right="P",
        bid=bid, ask=ask, mid=mid,
        delta=delta, theta=theta, vega=vega, gamma=gamma,
        implied_vol=0.18,
    )


def build_mock_chain(symbol: str = "SPX", spot: float = 5800.0) -> tuple[dict[str, list[OptionQuote]], dict[str, int], float]:
    """Return (quotes_by_expiry, dte_by_expiry, spot)."""
    today = date.today()
    dte_set = [3, 8, 15, 18, 22, 28, 43, 50]
    quotes_by_expiry: dict[str, list[OptionQuote]] = {}
    dte_by_expiry: dict[str, int] = {}
    # Strike grid: ±10% around spot in 5-pt steps
    strikes = sorted(set(round((spot + i * 5) / 5) * 5 for i in range(-80, 81)))
    for dte in dte_set:
        d = today + timedelta(days=dte)
        expiry = d.strftime("%Y%m%d")
        dte_by_expiry[expiry] = dte
        quotes_by_expiry[expiry] = [_put(symbol, expiry, float(k), spot, dte) for k in strikes]
    return quotes_by_expiry, dte_by_expiry, spot
