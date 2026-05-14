"""SQLite history for Flux IV-ratio snapshots."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_FLUX_HISTORY_PATH = "data/flux_ratio_history.db"


def init_flux_history(db_path: str = DEFAULT_FLUX_HISTORY_PATH) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flux_ratio_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                front_expiry TEXT NOT NULL,
                back_expiry TEXT NOT NULL,
                front_dte INTEGER NOT NULL,
                back_dte INTEGER NOT NULL,
                front_iv REAL,
                back_iv REAL,
                iv_ratio REAL NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_flux_ratio_history_pair
            ON flux_ratio_history(symbol, front_expiry, back_expiry, created_at)
            """
        )
        conn.commit()


def save_flux_snapshot(
    symbol: str,
    front_expiry: str,
    back_expiry: str,
    front_dte: int,
    back_dte: int,
    front_iv: float | None,
    back_iv: float | None,
    iv_ratio: float,
    db_path: str = DEFAULT_FLUX_HISTORY_PATH,
    timestamp: datetime | None = None,
) -> None:
    init_flux_history(db_path)
    created_at = (timestamp or datetime.now()).isoformat(timespec="seconds")
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO flux_ratio_history
            (symbol, front_expiry, back_expiry, front_dte, back_dte, front_iv, back_iv, iv_ratio, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                front_expiry,
                back_expiry,
                int(front_dte),
                int(back_dte),
                front_iv,
                back_iv,
                float(iv_ratio),
                created_at,
            ),
        )
        conn.commit()


def load_flux_history(
    symbol: str,
    front_expiry: str,
    back_expiry: str,
    db_path: str = DEFAULT_FLUX_HISTORY_PATH,
    lookback_hours: int = 120,
) -> list[dict[str, object]]:
    init_flux_history(db_path)
    cutoff = (datetime.now() - timedelta(hours=lookback_hours)).isoformat(timespec="seconds")
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT symbol, front_expiry, back_expiry, front_dte, back_dte, front_iv, back_iv, iv_ratio, created_at
            FROM flux_ratio_history
            WHERE symbol = ? AND front_expiry = ? AND back_expiry = ? AND created_at >= ?
            ORDER BY created_at
            """,
            (symbol, front_expiry, back_expiry, cutoff),
        ).fetchall()
    return [dict(row) for row in rows]
