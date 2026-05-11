"""SQLite quote cache. Supports both rights via primary key including 'right'."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from scanner.models import OptionQuote


DEFAULT_QUOTE_CACHE_PATH = "data/calendar_quote_cache.db"


def init_quote_cache(db_path: str = DEFAULT_QUOTE_CACHE_PATH) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS option_quote_cache (
                symbol TEXT NOT NULL,
                expiry TEXT NOT NULL,
                strike REAL NOT NULL,
                right TEXT NOT NULL,
                bid REAL, ask REAL, mid REAL,
                delta REAL, theta REAL, vega REAL, gamma REAL,
                implied_vol REAL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (symbol, expiry, strike, right)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quote_cache_meta (
                symbol TEXT PRIMARY KEY,
                underlying_price REAL,
                updated_at TEXT NOT NULL
            )
            """
        )


def save_quotes(symbol: str, quotes: list[OptionQuote], db_path: str = DEFAULT_QUOTE_CACHE_PATH, timestamp: datetime | None = None) -> int:
    init_quote_cache(db_path)
    updated_at = (timestamp or datetime.now()).isoformat(timespec="seconds")
    rows = [
        (
            symbol, q.expiry, q.strike, q.right,
            q.bid, q.ask, q.mid, q.delta, q.theta, q.vega, q.gamma, q.implied_vol,
            updated_at,
        )
        for q in quotes
    ]
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO option_quote_cache
            (symbol, expiry, strike, right, bid, ask, mid, delta, theta, vega, gamma, implied_vol, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, expiry, strike, right) DO UPDATE SET
                bid=excluded.bid, ask=excluded.ask, mid=excluded.mid,
                delta=excluded.delta, theta=excluded.theta, vega=excluded.vega, gamma=excluded.gamma,
                implied_vol=excluded.implied_vol, updated_at=excluded.updated_at
            """,
            rows,
        )
    return len(rows)


def save_cache_underlying_price(symbol: str, underlying_price: float | None, db_path: str = DEFAULT_QUOTE_CACHE_PATH, timestamp: datetime | None = None) -> None:
    if underlying_price is None or underlying_price <= 0:
        return
    init_quote_cache(db_path)
    updated_at = (timestamp or datetime.now()).isoformat(timespec="seconds")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO quote_cache_meta (symbol, underlying_price, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                underlying_price=excluded.underlying_price, updated_at=excluded.updated_at
            """,
            (symbol, float(underlying_price), updated_at),
        )


def _is_fresh(updated_at: str, max_age_seconds: int) -> bool:
    try:
        ts = datetime.fromisoformat(updated_at)
    except ValueError:
        return False
    return (datetime.now() - ts).total_seconds() <= max_age_seconds


def load_cache_underlying_price(symbol: str, max_age_seconds: int, db_path: str = DEFAULT_QUOTE_CACHE_PATH) -> float | None:
    init_quote_cache(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT underlying_price, updated_at FROM quote_cache_meta WHERE symbol = ?",
            (symbol,),
        ).fetchone()
    if row is None:
        return None
    price, updated_at = row
    if not _is_fresh(str(updated_at), max_age_seconds):
        return None
    return float(price) if price and price > 0 else None


def load_cached_quotes(symbol: str, expiry: str, max_age_seconds: int, right: str | None = None, db_path: str = DEFAULT_QUOTE_CACHE_PATH) -> list[OptionQuote]:
    init_quote_cache(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if right is None:
            rows = conn.execute(
                "SELECT * FROM option_quote_cache WHERE symbol = ? AND expiry = ? ORDER BY strike",
                (symbol, expiry),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM option_quote_cache WHERE symbol = ? AND expiry = ? AND right = ? ORDER BY strike",
                (symbol, expiry, right),
            ).fetchall()

    quotes: list[OptionQuote] = []
    for row in rows:
        if not _is_fresh(str(row["updated_at"]), max_age_seconds):
            continue
        quotes.append(
            OptionQuote(
                symbol=str(row["symbol"]),
                expiry=str(row["expiry"]),
                strike=float(row["strike"]),
                right=str(row["right"]),
                bid=row["bid"], ask=row["ask"], mid=row["mid"],
                delta=row["delta"], theta=row["theta"], vega=row["vega"], gamma=row["gamma"],
                implied_vol=row["implied_vol"],
            )
        )
    return quotes


def list_cached_expiries(symbol: str, max_age_seconds: int, db_path: str = DEFAULT_QUOTE_CACHE_PATH, right: str | None = None) -> list[str]:
    init_quote_cache(db_path)
    where = "symbol = ?"
    params: tuple = (symbol,)
    if right is not None:
        where += " AND right = ?"
        params = (symbol, right)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT expiry, MAX(updated_at) FROM option_quote_cache WHERE {where} GROUP BY expiry",
            params,
        ).fetchall()
    return sorted(expiry for expiry, updated_at in rows if _is_fresh(str(updated_at), max_age_seconds))


def quote_cache_stats(symbol: str, db_path: str = DEFAULT_QUOTE_CACHE_PATH) -> dict[str, object]:
    init_quote_cache(db_path)
    with sqlite3.connect(db_path) as conn:
        quote_count = conn.execute("SELECT COUNT(*) FROM option_quote_cache WHERE symbol = ?", (symbol,)).fetchone()[0]
        expiry_count = conn.execute("SELECT COUNT(DISTINCT expiry) FROM option_quote_cache WHERE symbol = ?", (symbol,)).fetchone()[0]
        newest = conn.execute("SELECT MAX(updated_at) FROM option_quote_cache WHERE symbol = ?", (symbol,)).fetchone()[0]
        meta = conn.execute("SELECT underlying_price, updated_at FROM quote_cache_meta WHERE symbol = ?", (symbol,)).fetchone()
        right_breakdown = dict(conn.execute(
            "SELECT right, COUNT(*) FROM option_quote_cache WHERE symbol = ? GROUP BY right", (symbol,)
        ).fetchall())
    return {
        "quote_count": int(quote_count or 0),
        "expiry_count": int(expiry_count or 0),
        "newest_update": newest or "",
        "underlying_price": float(meta[0]) if meta and meta[0] else None,
        "underlying_price_updated_at": meta[1] if meta else "",
        "right_breakdown": right_breakdown,
    }
