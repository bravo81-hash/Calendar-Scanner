"""Double Calendar Alpha Engine with Flux IV-ratio annotations."""

from __future__ import annotations

from datetime import date
from typing import Any

from scanner.flux_metrics import average_iv, classify_flux_signal, iv_ratio
from scanner.models import CalendarCandidate, CalendarLeg, OptionQuote, RegimeSnapshot, ScanSettings
from scanner.vix_regime import classify_vix_regime
from strategies.base import add_rejection, atm_round, build_candidate_aggregates, nearest_by_strike


NAME = "double_calendar_alpha"
ALLOWED_SYMBOLS = {"SPX", "SPY", "QQQ", "AAPL", "MSFT"}


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
    sym = symbol.upper()

    if sym not in ALLOWED_SYMBOLS:
        add_rejection(rejections, "symbol_not_allowed")
        warnings.append("Double Calendar Alpha only scans SPX, SPY, QQQ, AAPL, and MSFT.")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings}
    if underlying_price is None or underlying_price <= 0:
        add_rejection(rejections, "missing_underlying_price")
        return candidates, {"rejection_reasons": rejections, "warnings": ["No underlying price for strike anchoring."]}

    vix_regime = classify_vix_regime(settings.vix_price)
    mode = vix_regime.structure_mode
    pair = _select_high_vix_pair(dte_by_expiry) if mode == "NEGATIVE_VEGA" else _select_standard_pair(dte_by_expiry, settings)
    if pair is None:
        add_rejection(rejections, "missing_expiry_pair")
        warnings.append("No Double Calendar Alpha expiry pair matched the configured rules.")
        return candidates, {
            "rejection_reasons": rejections,
            "warnings": warnings,
            "mode": mode,
            "vix_regime": vix_regime.name,
        }

    front_exp, back_exp = pair
    front_dte = dte_by_expiry[front_exp]
    back_dte = dte_by_expiry[back_exp]
    offset = _strike_offset(sym, underlying_price, settings)
    increment = 5.0 if sym in {"SPX", "SPXW", "RUT", "NDX"} else 1.0
    put_target = atm_round(underlying_price - offset, increment)
    call_target = atm_round(underlying_price + offset, increment)

    front_quotes = quotes_by_expiry.get(front_exp, [])
    back_quotes = quotes_by_expiry.get(back_exp, [])
    put_short = nearest_by_strike([q for q in front_quotes if q.right.upper() == "P"], put_target)
    put_long = nearest_by_strike([q for q in back_quotes if q.right.upper() == "P"], put_target)
    call_short = nearest_by_strike([q for q in front_quotes if q.right.upper() == "C"], call_target)
    call_long = nearest_by_strike([q for q in back_quotes if q.right.upper() == "C"], call_target)
    if None in (put_short, put_long, call_short, call_long):
        add_rejection(rejections, "missing_leg_quotes")
        return candidates, {
            "rejection_reasons": rejections,
            "warnings": warnings,
            "mode": mode,
            "vix_regime": vix_regime.name,
        }

    assert put_short is not None and put_long is not None and call_short is not None and call_long is not None
    legs = [
        CalendarLeg("PUT_short", "SELL", 1, put_short, role="put_cal_short"),
        CalendarLeg("PUT_long", "BUY", 1, put_long, role="put_cal_long"),
        CalendarLeg("CALL_short", "SELL", 1, call_short, role="call_cal_short"),
        CalendarLeg("CALL_long", "BUY", 1, call_long, role="call_cal_long"),
    ]
    candidate = CalendarCandidate(
        strategy=NAME,
        symbol=sym,
        legs=legs,
        front_expiry=front_exp,
        back_expiry=back_exp,
        front_dte=front_dte,
        back_dte=back_dte,
    )
    build_candidate_aggregates(candidate)
    if candidate.net_debit <= 0:
        add_rejection(rejections, "non_positive_debit")
        return candidates, {"rejection_reasons": rejections, "warnings": warnings, "mode": mode}

    ratio = iv_ratio(front_quotes, back_quotes)
    front_iv = average_iv(front_quotes)
    back_iv = average_iv(back_quotes)
    signal = classify_flux_signal(ratio, spike_threshold=settings.flux_ratio_spike_threshold)
    candidate.extras.update({
        "mode": mode,
        "vix_price": settings.vix_price,
        "vix_regime": vix_regime.name,
        "vix_message": vix_regime.message,
        "primary_alert_ok": vix_regime.primary_alert_ok and signal.status in {"ENTRY_SIGNAL", "WATCH"},
        "put_strike": put_short.strike,
        "call_strike": call_short.strike,
        "strike_offset": offset,
        "iv_ratio": ratio,
        "front_iv": front_iv,
        "back_iv": back_iv,
        "flux_signal": signal.status,
        "flux_reason": signal.reason,
        "target_profit_low_pct": 15.0,
        "target_profit_high_pct": 30.0,
        "time_stop_dte": 3,
        "approx_range": max(call_short.strike - put_short.strike, 1.0),
    })
    if not vix_regime.primary_alert_ok:
        candidate.regime_flags.append(vix_regime.message)
    candidates.append(candidate)
    return candidates, {
        "rejection_reasons": rejections,
        "warnings": warnings,
        "mode": mode,
        "vix_regime": vix_regime.name,
        "vix_message": vix_regime.message,
    }


def _select_standard_pair(
    dte_by_expiry: dict[str, int],
    settings: ScanSettings,
) -> tuple[str, str] | None:
    for front_exp, front_dte in sorted(dte_by_expiry.items(), key=lambda item: item[1]):
        if not (settings.double_cal_min_short_dte <= front_dte <= settings.double_cal_max_short_dte):
            continue
        for back_exp, back_dte in sorted(dte_by_expiry.items(), key=lambda item: item[1]):
            if back_dte - front_dte == settings.double_cal_gap_days:
                return front_exp, back_exp
    return None


def _select_high_vix_pair(dte_by_expiry: dict[str, int]) -> tuple[str, str] | None:
    today = date.today()
    candidates: list[tuple[int, str, str]] = []
    for front_exp, front_dte in dte_by_expiry.items():
        front_date = today.fromordinal(today.toordinal() + front_dte)
        if front_date.weekday() != 2:
            continue
        for back_exp, back_dte in dte_by_expiry.items():
            back_date = today.fromordinal(today.toordinal() + back_dte)
            if back_dte - front_dte == 2 and back_date.weekday() == 4:
                candidates.append((front_dte, front_exp, back_exp))
    if not candidates:
        return None
    candidates.sort()
    _, front_exp, back_exp = candidates[0]
    return front_exp, back_exp


def _strike_offset(symbol: str, underlying_price: float, settings: ScanSettings) -> float:
    if symbol in {"SPX", "SPXW"}:
        return float(settings.double_cal_strike_offset)
    return max(1.0, underlying_price * float(settings.double_cal_stock_offset_pct))
