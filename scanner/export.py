"""CSV export helpers for multi-leg calendar candidates."""

from __future__ import annotations

import csv
from io import StringIO

from scanner.models import CalendarCandidate


def candidates_to_csv(candidates: list[CalendarCandidate]) -> str:
    """One row per leg, with candidate-level columns repeated."""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "rank", "score", "strategy", "symbol",
        "front_expiry", "back_expiry", "front_dte", "back_dte",
        "net_debit", "position_theta", "position_vega", "position_delta",
        "theta_debit_ratio", "days_to_target_pct", "range_debit_ratio",
        "avg_spread_pct", "regime_score", "regime_flags",
        "leg_name", "action", "quantity", "leg_expiry", "leg_strike", "leg_right",
        "bid", "ask", "mid", "delta", "theta", "vega", "gamma", "implied_vol",
    ])
    for c in candidates:
        for leg in c.legs:
            q = leg.quote
            writer.writerow([
                c.rank, round(c.custom_score, 4), c.strategy, c.symbol,
                c.front_expiry, c.back_expiry, c.front_dte, c.back_dte,
                round(c.net_debit, 4), round(c.position_theta, 2), round(c.position_vega, 2), round(c.position_delta, 2),
                round(c.theta_debit_ratio, 4), round(c.days_to_target_pct, 2), round(c.range_debit_ratio, 4),
                round(c.average_spread_pct, 2), round(c.regime_score, 3), "; ".join(c.regime_flags),
                leg.name, leg.action, leg.quantity, q.expiry, q.strike, q.right,
                q.bid, q.ask, q.mid, q.delta, q.theta, q.vega, q.gamma, q.implied_vol,
            ])
    return output.getvalue()
