"""FlyDiagonal.

Reference: docs/strategies_html/FlyDiagonal.html

Scanner mapping:
- ATM iron fly, 50 points wide by default
- OTM put time spread 50 points below the long put
- OTM call time spread 50 points above the long call
- Small strike-offset search prefers delta-neutral, theta-positive risk
"""

from __future__ import annotations

from typing import Any

from scanner.models import CalendarCandidate, CalendarLeg, OptionQuote, RegimeSnapshot, ScanSettings
from strategies.base import (
    add_rejection,
    build_candidate_aggregates,
    expiry_pair_by_target_dte,
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
    front_puts = [q for q in short_quotes if q.right.upper() == "P"]
    front_calls = [q for q in short_quotes if q.right.upper() == "C"]
    back_puts = [q for q in long_quotes if q.right.upper() == "P"]
    back_calls = [q for q in long_quotes if q.right.upper() == "C"]

    if underlying_price is None or underlying_price <= 0:
        warnings.append("No underlying price for FlyDiagonal strike anchoring.")
        add_rejection(rejections, "missing_underlying_price")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    best: CalendarCandidate | None = None
    best_key: tuple[float, float, float, float] | None = None
    step = max(settings.fly_dynamic_step, 1.0)
    count = max(settings.fly_dynamic_steps, 0)
    multipliers = range(-count, count + 1)

    for center_mult in multipliers:
        center = underlying_price + center_mult * step
        width = settings.fly_iron_fly_width
        put_wing_target = center - width
        call_wing_target = center + width
        for spread_mult in multipliers:
            spread_offset = max(step, settings.fly_time_spread_offset + spread_mult * step)
            put_spread_target = put_wing_target - spread_offset
            call_spread_target = call_wing_target + spread_offset

            put_long = nearest_by_strike(front_puts, put_wing_target)
            put_short = nearest_by_strike(front_puts, center)
            call_short = nearest_by_strike(front_calls, center)
            call_long = nearest_by_strike(front_calls, call_wing_target)
            put_ts_short = nearest_by_strike(front_puts, put_spread_target)
            put_ts_long = nearest_by_strike(back_puts, put_spread_target)
            call_ts_short = nearest_by_strike(front_calls, call_spread_target)
            call_ts_long = nearest_by_strike(back_calls, call_spread_target)
            quotes = [
                put_long,
                put_short,
                call_short,
                call_long,
                put_ts_short,
                put_ts_long,
                call_ts_short,
                call_ts_long,
            ]
            if any(q is None for q in quotes):
                continue
            assert all(q is not None for q in quotes)
            legs = [
                CalendarLeg("IRONFLY_put_long", "BUY", 1, put_long, role="ironfly_put_long"),
                CalendarLeg("IRONFLY_put_short", "SELL", 1, put_short, role="ironfly_put_short"),
                CalendarLeg("IRONFLY_call_short", "SELL", 1, call_short, role="ironfly_call_short"),
                CalendarLeg("IRONFLY_call_long", "BUY", 1, call_long, role="ironfly_call_long"),
                CalendarLeg("PUT_TS_short", "SELL", 1, put_ts_short, role="put_time_spread_short"),
                CalendarLeg("PUT_TS_long", "BUY", 1, put_ts_long, role="put_time_spread_long"),
                CalendarLeg("CALL_TS_short", "SELL", 1, call_ts_short, role="call_time_spread_short"),
                CalendarLeg("CALL_TS_long", "BUY", 1, call_ts_long, role="call_time_spread_long"),
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
            avg_spread = sum(leg.quote.spread_pct for leg in candidate.legs) / len(candidate.legs)
            if avg_spread > settings.max_spread_pct_hard:
                continue
            theta_penalty = 0.0 if candidate.position_theta >= 0 else abs(candidate.position_theta) * 10.0
            key = (
                theta_penalty,
                abs(candidate.position_delta),
                avg_spread,
                abs(candidate.net_debit),
            )
            candidate.extras.update({
                "structure": "atm_iron_fly_plus_put_call_time_spreads",
                "iron_fly_center": (put_short.strike + call_short.strike) / 2.0,
                "iron_fly_width": abs(call_long.strike - put_long.strike) / 2.0,
                "put_time_spread_strike": put_ts_short.strike,
                "call_time_spread_strike": call_ts_short.strike,
                "put_time_spread_offset": abs(put_long.strike - put_ts_short.strike),
                "call_time_spread_offset": abs(call_ts_short.strike - call_long.strike),
                "target_pct": 0.10,
                "selection_delta_abs": abs(candidate.position_delta),
                "selection_theta_positive": candidate.position_theta >= 0,
                "selection_avg_spread_pct": avg_spread,
                "approx_range": max(call_ts_short.strike - put_ts_short.strike, 1.0),
            })
            if best_key is None or key < best_key:
                best = candidate
                best_key = key

    if best is None:
        add_rejection(rejections, "missing_8_leg_flydiagonal")
        warnings.append("Could not build 8-leg FlyDiagonal around the configured anchors.")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    if best.position_theta < 0:
        warnings.append("Best 8-leg FlyDiagonal candidate is not theta-positive; model carefully.")
    candidates.append(best)
    return candidates, {"rejection_reasons": rejections, "warnings": warnings}
