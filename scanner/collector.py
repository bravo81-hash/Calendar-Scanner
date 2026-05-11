"""Background quote-cache collector for put + call quotes.

For calendar strategies we typically want puts only, but for TimeEdge no-touch
(double calendar) we need both. Default behavior: fetch the right(s) the
selected strategy needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import threading
from typing import Any, Callable

from scanner.contracts import days_to_expiry
from scanner.ibkr_client import IBKRClient, resolve_underlying_price
from scanner.models import ScanSettings
from scanner.option_chain import filter_expiries
from scanner.quote_cache import DEFAULT_QUOTE_CACHE_PATH, save_cache_underlying_price, save_quotes


StatusUpdater = Callable[..., None]


@dataclass
class CollectorStatus:
    running: bool = False
    message: str = "idle"
    started_at: str = ""
    finished_at: str = ""
    expiries_done: int = 0
    expiries_total: int = 0
    quotes_saved: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running, "message": self.message,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "expiries_done": self.expiries_done, "expiries_total": self.expiries_total,
            "quotes_saved": self.quotes_saved, "error": self.error,
        }


class QuoteCacheCollector:
    def __init__(self, collect_func: Callable | None = None) -> None:
        self._collect_func = collect_func or collect_quote_cache
        self._lock = threading.Lock()
        self._status = CollectorStatus()
        self._thread: threading.Thread | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status.to_dict()

    def _update(self, **changes: Any) -> None:
        with self._lock:
            for k, v in changes.items():
                setattr(self._status, k, v)

    def start(self, settings: ScanSettings, connection: dict[str, Any], rights: tuple[str, ...] = ("P",), db_path: str = DEFAULT_QUOTE_CACHE_PATH) -> bool:
        with self._lock:
            if self._status.running:
                return False
            self._status = CollectorStatus(running=True, message="starting", started_at=datetime.now().isoformat(timespec="seconds"))
        self._thread = threading.Thread(target=self._run, args=(settings, dict(connection), rights, db_path), daemon=True)
        self._thread.start()
        return True

    def _run(self, settings: ScanSettings, connection: dict[str, Any], rights: tuple[str, ...], db_path: str) -> None:
        try:
            saved = self._collect_func(settings, connection, rights, db_path, self._update)
            self._update(running=False, message="finished", finished_at=datetime.now().isoformat(timespec="seconds"), quotes_saved=saved, error="")
        except Exception as error:  # pragma: no cover
            self._update(running=False, message="failed", finished_at=datetime.now().isoformat(timespec="seconds"), error=str(error))

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)


def collect_quote_cache(settings: ScanSettings, connection: dict[str, Any], rights: tuple[str, ...], db_path: str, update_status: StatusUpdater) -> int:
    client = IBKRClient()
    total_saved = 0
    try:
        update_status(message="connecting to IBKR")
        client.connect(connection["host"], connection["port"], connection["client_id"])
        client.set_market_data_type(connection["market_data_type"])

        update_status(message="qualifying underlying")
        underlying = client.qualify_underlying(settings)
        chain = client.option_chain(underlying, settings)

        ibkr_price = client.get_underlying_price(underlying)
        underlying_price = resolve_underlying_price(ibkr_price, connection.get("manual_underlying_price"))
        save_cache_underlying_price(settings.symbol, underlying_price, db_path=db_path)

        expiries_by_dte = filter_expiries(sorted(chain.expirations), settings)
        expiries = sorted(expiries_by_dte, key=lambda e: days_to_expiry(e))
        update_status(expiries_total=len(expiries), expiries_done=0)

        for index, expiry in enumerate(expiries, start=1):
            for right in rights:
                update_status(message=f"refreshing {expiry} {right}", expiries_done=index - 1)
                quotes = client.fetch_quotes_for_expiry(expiry, chain, settings, underlying_price, right=right)
                total_saved += save_quotes(settings.symbol, quotes, db_path=db_path)
            update_status(expiries_done=index, quotes_saved=total_saved)
        return total_saved
    finally:
        client.disconnect()
