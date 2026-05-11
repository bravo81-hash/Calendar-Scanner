"""TimeEdge.

Two distinct setups in this module:

1. time_edge (main):
   - ATM Put Calendar
   - Short 15 DTE / Long 22 DTE
   - Thursday ~3:30 PM entry
   - ABORT if back-month IV - front-month IV > 1 vol point
   - ABORT next-day market holiday (we can't see calendar reliably; surface flag only)
   - +Theta, +Vega
   - TP 10% of margin; tent-breach SL; close by 1 DTE (Thursday); never to expiration

2. time_edge_no_touch (set-and-forget bonus):
   - Double Calendar, 35 delta Put + 35 delta Call
   - Short 15 DTE / Long 43 DTE
   - TP 10%, SL 10%, exit @ 1 DTE
   - No adjustments
"""

from __future__ import annotations

from typing import Any

from scanner.models import CalendarCandidate, CalendarLeg, OptionQuote, RegimeSnapshot, ScanSettings
from strategies.base import (
    add_rejection,
    atm_round,
    build_candidate_aggregates,
    expiry_pair_by_target_dte,
    nearest_by_abs_delta,
    nearest_by_strike,
)


NAME = "time_edge"
NAME_NO_TOUCH = "time_edge_no_touch"


def needed_rights(settings: ScanSettings) -> tuple[str, ...]:
    if settings.strategy == NAME:
        return (settings.te_right.upper(),)
    return ("P", "C")


# ---------------------------------------------------------------------------
# Main TimeEdge
# ---------------------------------------------------------------------------


def build_main(
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

    if underlying_price is None or underlying_price <= 0:
        return candidates, {"rejection_reasons": rejections, "warnings": ["No underlying price for time_edge."]}

    pair = expiry_pair_by_target_dte(
        dte_by_expiry, settings.te_short_dte, settings.te_long_dte, settings.te_dte_tolerance
    )
    if pair is None:
        warnings.append(f"No (short~{settings.te_short_dte}, long~{settings.te_long_dte}) expiry pair within ±{settings.te_dte_tolerance} DTE.")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    short_exp, long_exp = pair
    short_dte = dte_by_expiry[short_exp]
    long_dte = dte_by_expiry[long_exp]

    increment = 5.0 if symbol.upper() in {"SPX", "SPXW", "RUT", "NDX"} else 1.0
    atm_strike = atm_round(underlying_price, increment)

    short_q = nearest_by_strike(
        [q for q in quotes_by_expiry.get(short_exp, []) if q.right.upper() == settings.te_right.upper()],
        atm_strike,
    )
    long_q = nearest_by_strike(
        [q for q in quotes_by_expiry.get(long_exp, []) if q.right.upper() == settings.te_right.upper()],
        atm_strike,
    )
    if short_q is None or long_q is None:
        add_rejection(rejections, "missing_leg_quotes")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    # ABORT: back IV - front IV > threshold
    iv_excess_flag = False
    iv_excess_value: float | None = None
    if short_q.implied_vol is not None and long_q.implied_vol is not None:
        iv_excess_value = (long_q.implied_vol - short_q.implied_vol) * 100.0  # vol points
        if iv_excess_value > settings.te_back_iv_excess_max:
            iv_excess_flag = True
            warnings.append(
                f"ABORT criterion: back IV ({long_q.implied_vol*100:.2f}) - front IV "
                f"({short_q.implied_vol*100:.2f}) = {iv_excess_value:.2f} pts > "
                f"{settings.te_back_iv_excess_max:.2f}. Skipping per TimeEdge rule."
            )
            # Hard skip: don't even emit the candidate
            return candidates, {"rejection_reasons": rejections, "warnings": warnings, "iv_excess": iv_excess_value}

    legs = [
        CalendarLeg("PUT_short", "SELL", 1, short_q, role="atm_put_short"),
        CalendarLeg("PUT_long", "BUY", 1, long_q, role="atm_put_long"),
    ]
    candidate = CalendarCandidate(
        strategy=NAME, symbol=symbol, legs=legs,
        front_expiry=short_exp, back_expiry=long_exp,
        front_dte=short_dte, back_dte=long_dte,
    )
    build_candidate_aggregates(candidate)

    if candidate.net_debit <= 0:
        add_rejection(rejections, "non_positive_debit")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    avg_spread = sum(l.quote.spread_pct for l in candidate.legs) / max(1, len(candidate.legs))
    if avg_spread > settings.max_spread_pct_hard:
        add_rejection(rejections, "spread_too_wide")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    candidate.extras.update({
        "approx_range": candidate.net_debit * 4.0,
        "atm_strike": atm_strike,
        "iv_excess_pts": iv_excess_value,
        "time_stop_dte": 1,
    })
    candidates.append(candidate)
    return candidates, {"rejection_reasons": rejections, "warnings": warnings, "iv_excess": iv_excess_value}


# ---------------------------------------------------------------------------
# TimeEdge No-Touch (double calendar at 35 delta both sides)
# ---------------------------------------------------------------------------


def build_no_touch(
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

    if underlying_price is None or underlying_price <= 0:
        return candidates, {"rejection_reasons": rejections, "warnings": ["No underlying price for time_edge_no_touch."]}

    pair = expiry_pair_by_target_dte(
        dte_by_expiry, settings.te_nt_short_dte, settings.te_nt_long_dte, settings.te_nt_dte_tolerance
    )
    if pair is None:
        warnings.append(f"No (short~{settings.te_nt_short_dte}, long~{settings.te_nt_long_dte}) expiry pair within ±{settings.te_nt_dte_tolerance} DTE.")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    short_exp, long_exp = pair
    short_dte = dte_by_expiry[short_exp]
    long_dte = dte_by_expiry[long_exp]

    target_delta = settings.te_nt_target_delta

    # Put side: 35 delta put
    put_short = nearest_by_abs_delta(
        [q for q in quotes_by_expiry.get(short_exp, []) if q.right.upper() == "P"], target_delta
    )
    if put_short is None:
        add_rejection(rejections, "no_put_short")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}
    # Long leg: SAME STRIKE as short (calendar definition), back expiry
    put_long = nearest_by_strike(
        [q for q in quotes_by_expiry.get(long_exp, []) if q.right.upper() == "P"], put_short.strike
    )
    if put_long is None:
        add_rejection(rejections, "no_put_long")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    # Call side: 35 delta call
    call_short = nearest_by_abs_delta(
        [q for q in quotes_by_expiry.get(short_exp, []) if q.right.upper() == "C"], target_delta
    )
    if call_short is None:
        add_rejection(rejections, "no_call_short")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}
    call_long = nearest_by_strike(
        [q for q in quotes_by_expiry.get(long_exp, []) if q.right.upper() == "C"], call_short.strike
    )
    if call_long is None:
        add_rejection(rejections, "no_call_long")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    legs = [
        CalendarLeg("PUT_short", "SELL", 1, put_short, role="put_cal_short"),
        CalendarLeg("PUT_long", "BUY", 1, put_long, role="put_cal_long"),
        CalendarLeg("CALL_short", "SELL", 1, call_short, role="call_cal_short"),
        CalendarLeg("CALL_long", "BUY", 1, call_long, role="call_cal_long"),
    ]
    candidate = CalendarCandidate(
        strategy=NAME_NO_TOUCH, symbol=symbol, legs=legs,
        front_expiry=short_exp, back_expiry=long_exp,
        front_dte=short_dte, back_dte=long_dte,
    )
    build_candidate_aggregates(candidate)

    if candidate.net_debit <= 0:
        add_rejection(rejections, "non_positive_debit")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}

    # Range proxy: strike spread between put and call sides (where the tent floor is)
    candidate.extras.update({
        "approx_range": abs(call_short.strike - put_short.strike) + candidate.net_debit * 2.0,
        "put_strike": put_short.strike,
        "call_strike": call_short.strike,
        "target_delta": target_delta,
        "time_stop_dte": 1,
    })
    candidates.append(candidate)
    return candidates, {"rejection_reasons": rejections, "warnings": warnings}


def build(
    symbol: str,
    quotes_by_expiry: dict[str, list[OptionQuote]],
    dte_by_expiry: dict[str, int],
    settings: ScanSettings,
    regime: RegimeSnapshot | None,
    underlying_price: float | None,
) -> tuple[list[CalendarCandidate], dict[str, Any]]:
    """Dispatcher: builds main TE; no-touch is invoked via strategy='time_edge_no_touch'."""
    if settings.strategy == NAME_NO_TOUCH:
        return build_no_touch(symbol, quotes_by_expiry, dte_by_expiry, settings, regime, underlying_price)
    return build_main(symbol, quotes_by_expiry, dte_by_expiry, settings, regime, underlying_price)
