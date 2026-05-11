"""Macro modelling inputs for risk-chart assumptions.

Isolated from scanner candidate generation. Safe fallbacks, no scan failures
if endpoints fail.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.request import urlopen

CACHE_DIR = Path(".scanner_cache")
CACHE_DIR.mkdir(exist_ok=True)
CACHE_FILE = CACHE_DIR / "macro_cache.json"
CACHE_TTL_SECONDS = 60 * 60 * 24

DEFAULT_RISK_FREE_RATE = 0.045
DEFAULT_DIVIDEND_YIELD = 0.013


def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text())
    except Exception:
        return {}


def _save_cache(payload: dict) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(payload, indent=2))
    except Exception:
        pass


def _is_cache_valid(ts: float | None) -> bool:
    if ts is None:
        return False
    return (time.time() - ts) < CACHE_TTL_SECONDS


def fetch_treasury_rate() -> float:
    cache = _load_cache()
    cached = cache.get("risk_free_rate")
    cached_ts = cache.get("risk_free_rate_ts")
    if _is_cache_valid(cached_ts) and isinstance(cached, (int, float)):
        return float(cached)
    try:
        url = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/avg_interest_rates"
        with urlopen(url, timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rows = payload.get("data", [])
        ten_year = [r for r in rows if r.get("security_desc", "").lower().startswith("10-year")]
        if ten_year:
            value = float(ten_year[0]["avg_interest_rate_amt"]) / 100.0
            cache["risk_free_rate"] = value
            cache["risk_free_rate_ts"] = time.time()
            _save_cache(cache)
            return value
    except Exception:
        pass
    if isinstance(cached, (int, float)):
        return float(cached)
    return DEFAULT_RISK_FREE_RATE


def fetch_spy_dividend_yield() -> float:
    cache = _load_cache()
    cached = cache.get("dividend_yield")
    cached_ts = cache.get("dividend_yield_ts")
    if _is_cache_valid(cached_ts) and isinstance(cached, (int, float)):
        return float(cached)
    value = DEFAULT_DIVIDEND_YIELD
    cache["dividend_yield"] = value
    cache["dividend_yield_ts"] = time.time()
    _save_cache(cache)
    return value


def resolve_macro_inputs(auto_fetch: bool, manual_rfr: float, manual_div: float) -> tuple[float, float, str]:
    if not auto_fetch:
        return (manual_rfr, manual_div, "manual")
    return (fetch_treasury_rate(), fetch_spy_dividend_yield(), "auto_fetch")
