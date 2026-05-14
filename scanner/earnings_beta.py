"""Earnings IV crush edge calculator."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EarningsEdge:
    market_implied_move: float
    historical_average_move: float
    adjusted_historical_move: float
    edge: float
    overpriced_pct: float
    classification: str


def calculate_earnings_edge(
    market_implied_move: float,
    historical_average_move: float,
    iv_crush_factor_pct: float = 0.0,
) -> EarningsEdge:
    implied = max(float(market_implied_move), 0.0)
    historical = max(float(historical_average_move), 0.0)
    crush = max(0.0, min(float(iv_crush_factor_pct), 100.0)) / 100.0
    adjusted = historical * (1.0 - crush)
    edge = implied - adjusted
    overpriced_pct = (edge / implied * 100.0) if implied > 0 else 0.0
    if overpriced_pct >= 30.0:
        classification = "HEAVILY_OVERPRICED"
    elif overpriced_pct > 0.0:
        classification = "MODEST_EDGE"
    else:
        classification = "UNDERPRICED"
    return EarningsEdge(implied, historical, adjusted, edge, overpriced_pct, classification)
