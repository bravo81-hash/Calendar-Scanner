"""Read-only IBKR client wrapper.

Generalised from the Batman scanner:
- supports both rights ("P" and "C") per request
- handles multiple underlyings (SPX, RUT as Index; SPY, QQQ as Stock)
- uses ATM-centred strike selection (calendars want strikes near spot)

This module intentionally contains NO order placement methods.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from typing import Any, Callable

from scanner.contracts import days_to_expiry
from scanner.greeks import quote_from_ticker
from scanner.models import OptionQuote, ScanSettings
from scanner.option_chain import select_candidate_strikes


IB = None
Index = None
Option = None
Stock = None
util = None
IB_IMPORT_ERROR: Exception | None = None


def ensure_event_loop() -> asyncio.AbstractEventLoop:
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


def _load_ib_insync() -> None:
    global IB, Index, Option, Stock, util, IB_IMPORT_ERROR
    if IB is not None:
        return
    try:
        ensure_event_loop()
        module = importlib.import_module("ib_insync")
        IB = module.IB
        Index = module.Index
        Option = module.Option
        Stock = module.Stock
        util = module.util
        IB_IMPORT_ERROR = None
    except Exception as error:  # pragma: no cover
        IB_IMPORT_ERROR = error


def runtime_diagnostics() -> dict[str, Any]:
    _load_ib_insync()
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "ib_insync_available": IB is not None,
        "ib_insync_error": repr(IB_IMPORT_ERROR) if IB_IMPORT_ERROR else "",
    }


def resolve_underlying_price(ibkr_price: float | None, manual_override: float | None) -> float | None:
    if ibkr_price is not None and ibkr_price > 0:
        return ibkr_price
    if manual_override is not None and manual_override > 0:
        return manual_override
    return None


def market_data_type_code(label: str) -> int:
    return {"Live": 1, "Frozen": 2, "Delayed": 3, "Delayed frozen": 4}.get(label, 1)


def chunk_items(items: list[Any], batch_size: int) -> list[list[Any]]:
    safe = max(int(batch_size), 1)
    return [items[i : i + safe] for i in range(0, len(items), safe)]


# Underlyings classified as cash-settled indices vs. equity tickers
INDEX_SYMBOLS = {"SPX", "SPXW", "NDX", "RUT", "VIX"}


def underlying_exchange_currency(symbol: str) -> tuple[str, str, str]:
    """Best-effort exchange/currency hints per common underlying."""
    sym = symbol.upper()
    if sym in {"SPX", "SPXW"}:
        return ("CBOE", "USD", "INDEX")
    if sym in {"RUT"}:
        return ("RUSSELL", "USD", "INDEX")
    if sym in {"NDX"}:
        return ("NASDAQ", "USD", "INDEX")
    if sym in {"VIX"}:
        return ("CBOE", "USD", "INDEX")
    if sym in {"SPY", "QQQ", "IWM", "DIA"}:
        return ("SMART", "USD", "STOCK")
    return ("SMART", "USD", "STOCK")


class IBKRClient:
    def __init__(self) -> None:
        ensure_event_loop()
        _load_ib_insync()
        if IB is None:
            details = repr(IB_IMPORT_ERROR) if IB_IMPORT_ERROR else "unknown import error"
            raise RuntimeError(
                "ib_insync is not available in this Python env. "
                f"Python: {sys.executable}. Import error: {details}"
            )
        util.startLoop()
        self.ib = IB()

    @property
    def connected(self) -> bool:
        return bool(self.ib.isConnected())

    def connect(self, host: str, port: int, client_id: int) -> None:
        self.ib.connect(host, port, clientId=client_id, timeout=10)

    def set_market_data_type(self, label: str) -> None:
        self.ib.reqMarketDataType(market_data_type_code(label))

    def disconnect(self) -> None:
        if self.connected:
            self.ib.disconnect()

    def qualify_underlying(self, settings: ScanSettings) -> Any:
        sym = settings.symbol.upper()
        exch, cur, kind = underlying_exchange_currency(sym)
        # Allow user override from settings
        exch = settings.exchange or exch
        cur = settings.currency or cur
        contract = Index(sym, exch, cur) if kind == "INDEX" else Stock(sym, exch, cur)
        qualified = self.ib.qualifyContracts(contract)
        if not qualified:
            raise RuntimeError(f"Could not qualify underlying contract for {sym}.")
        return qualified[0]

    def option_chain(self, underlying: Any, settings: ScanSettings) -> Any:
        chains = self.ib.reqSecDefOptParams(
            underlying.symbol, "", underlying.secType, underlying.conId
        )
        if not chains:
            raise RuntimeError("IBKR returned no option chains for this underlying.")
        # Prefer the requested exchange; fall back to first available
        exch = settings.exchange.upper() if settings.exchange else ""
        preferred = [c for c in chains if c.exchange.upper() == exch] if exch else []
        return preferred[0] if preferred else chains[0]

    def all_chains(self, underlying: Any) -> list[Any]:
        """Return all chains (e.g. SPX and SPXW separately) for diagnostics."""
        return self.ib.reqSecDefOptParams(
            underlying.symbol, "", underlying.secType, underlying.conId
        ) or []

    def get_underlying_price(self, underlying: Any) -> float | None:
        ticker = self.ib.reqMktData(underlying, "", False, False)
        self.ib.sleep(2)
        price = ticker.marketPrice()
        self.ib.cancelMktData(underlying)
        return float(price) if price and price > 0 else None

    def fetch_quotes_for_expiry(
        self,
        expiry: str,
        chain: Any,
        settings: ScanSettings,
        underlying_price: float | None,
        right: str = "P",
        progress: Callable[[str], None] | None = None,
    ) -> list[OptionQuote]:
        """Fetch quotes for ATM-centred strikes at one expiry, one right."""
        progress = progress or (lambda m: None)
        dte = days_to_expiry(expiry)
        progress(f"requesting {right} for {expiry} ({dte} DTE)")

        strikes = select_candidate_strikes(
            list(chain.strikes),
            underlying_price,
            settings.max_contracts_per_expiry,
            settings.lower_strike_multiplier,
            settings.upper_strike_multiplier,
            settings.strike_increment,
        )
        contracts = [
            Option(
                settings.symbol,
                expiry,
                strike,
                right,
                settings.exchange or chain.exchange,
                currency=settings.currency,
                tradingClass=chain.tradingClass,
            )
            for strike in strikes
        ]
        qualified = self.ib.qualifyContracts(*contracts)
        quotes: list[OptionQuote] = []
        for batch_num, batch in enumerate(chunk_items(list(qualified), settings.market_data_batch_size), start=1):
            progress(f"batch {batch_num}: {len(batch)} contracts for {expiry} {right}")
            tickers = [self.ib.reqMktData(c, "", False, False) for c in batch]
            self.ib.sleep(4)
            for contract, ticker in zip(batch, tickers):
                quote = quote_from_ticker(settings.symbol, contract, ticker)
                if quote is not None:
                    quotes.append(quote)
                self.ib.cancelMktData(contract)
        return quotes


def summarize_chain(chain: Any, underlying_price: float | None, selected_strike_count: int) -> dict[str, Any]:
    expirations = getattr(chain, "expirations", []) or []
    strikes = getattr(chain, "strikes", []) or []
    return {
        "exchange": getattr(chain, "exchange", ""),
        "trading_class": getattr(chain, "tradingClass", ""),
        "expiration_count": len(expirations),
        "strike_count": len(strikes),
        "selected_strikes_per_expiry": selected_strike_count,
        "underlying_price": underlying_price,
    }
