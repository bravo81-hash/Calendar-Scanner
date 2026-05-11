"""Convert IBKR tickers into OptionQuote models.

Right-agnostic: handles both puts and calls. For puts IBKR delta is negative;
we preserve the sign and use absolute value for screening when needed.
"""

from __future__ import annotations

from math import isfinite
from typing import Any

from scanner.models import OptionQuote


def _number_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return number


def quote_from_ticker(symbol: str, contract: Any, ticker: Any) -> OptionQuote | None:
    """Build an OptionQuote from an ib_insync ticker.

    Greeks: prefer modelGreeks (more stable across the chain); fall back to
    bidGreeks / askGreeks if model is missing.
    """
    bid = _number_or_none(getattr(ticker, "bid", None))
    ask = _number_or_none(getattr(ticker, "ask", None))

    greeks = (
        getattr(ticker, "modelGreeks", None)
        or getattr(ticker, "bidGreeks", None)
        or getattr(ticker, "askGreeks", None)
    )
    delta = _number_or_none(getattr(greeks, "delta", None))
    # IBKR returns delta as decimal (-1..1); rescale to 100-style so puts ~ -14
    if delta is not None and abs(delta) <= 1:
        delta *= 100.0

    mid = (bid + ask) / 2.0 if bid is not None and ask is not None and ask >= bid else None
    return OptionQuote(
        symbol=symbol,
        expiry=str(getattr(contract, "lastTradeDateOrContractMonth", "")),
        strike=float(getattr(contract, "strike", 0.0)),
        right=str(getattr(contract, "right", "P")),
        bid=bid,
        ask=ask,
        mid=mid,
        delta=delta,
        theta=_number_or_none(getattr(greeks, "theta", None)),
        vega=_number_or_none(getattr(greeks, "vega", None)),
        gamma=_number_or_none(getattr(greeks, "gamma", None)),
        implied_vol=_number_or_none(getattr(greeks, "impliedVol", None)),
        contract=contract,
    )
