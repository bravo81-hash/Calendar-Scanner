"""Advisory trade-management math for double calendars.

This module produces alerts and leg instructions only. It does not place,
modify, or cancel orders.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ManagementResult:
    profit_pct: float
    profit_target_hit: bool
    time_stop_hit: bool
    stop_loss_hit: bool
    alerts: list[str]


@dataclass(frozen=True)
class TransformerPlan:
    legs: list[dict[str, float | int | str]]
    long_leg_credit: float
    wing_debit: float
    net_credit: float
    risk_funded: bool


def evaluate_position_management(
    entry_debit: float,
    current_value: float,
    front_dte: int,
    underlying_price: float,
    put_short_strike: float,
    call_short_strike: float,
    profit_target_low_pct: float = 15.0,
) -> ManagementResult:
    entry = max(float(entry_debit), 0.0)
    current = max(float(current_value), 0.0)
    profit_pct = ((entry - current) / entry * 100.0) if entry > 0 else 0.0
    profit_target_hit = profit_pct >= profit_target_low_pct
    time_stop_hit = int(front_dte) <= 3
    stop_loss_hit = underlying_price <= put_short_strike or underlying_price >= call_short_strike

    alerts: list[str] = []
    if profit_target_hit:
        alerts.append(f"Profit target hit: {profit_pct:.1f}% >= {profit_target_low_pct:.1f}%.")
    if time_stop_hit:
        alerts.append(f"Time stop: front expiry is {front_dte} DTE.")
    if stop_loss_hit:
        alerts.append("Stop loss: underlying touched a short strike.")
    if not alerts:
        alerts.append("No management alert.")

    return ManagementResult(profit_pct, profit_target_hit, time_stop_hit, stop_loss_hit, alerts)


def transformer_plan(
    put_short_strike: float,
    call_short_strike: float,
    put_wing_strike: float,
    call_wing_strike: float,
    back_put_long_bid: float,
    back_call_long_bid: float,
    front_put_wing_ask: float,
    front_call_wing_ask: float,
    quantity: int = 1,
) -> TransformerPlan:
    qty = max(int(quantity), 1)
    long_leg_credit = (float(back_put_long_bid) + float(back_call_long_bid)) * qty
    wing_debit = (float(front_put_wing_ask) + float(front_call_wing_ask)) * qty
    net_credit = long_leg_credit - wing_debit
    legs: list[dict[str, float | int | str]] = [
        {"action": "SELL_TO_CLOSE", "right": "P", "strike": put_short_strike, "quantity": qty, "price": back_put_long_bid},
        {"action": "SELL_TO_CLOSE", "right": "C", "strike": call_short_strike, "quantity": qty, "price": back_call_long_bid},
        {"action": "BUY_TO_OPEN", "right": "P", "strike": put_wing_strike, "quantity": qty, "price": front_put_wing_ask},
        {"action": "BUY_TO_OPEN", "right": "C", "strike": call_wing_strike, "quantity": qty, "price": front_call_wing_ask},
    ]
    return TransformerPlan(legs, long_leg_credit, wing_debit, net_credit, net_credit >= 0)
