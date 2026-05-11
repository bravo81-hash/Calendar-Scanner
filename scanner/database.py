"""SQLite scan history."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from scanner.models import CalendarCandidate, ScanSettings


DEFAULT_DB_PATH = "data/calendar_scan_history.db"


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                strategy TEXT NOT NULL,
                symbol TEXT NOT NULL,
                settings_json TEXT NOT NULL,
                candidate_json TEXT NOT NULL,
                score REAL NOT NULL,
                rank INTEGER NOT NULL
            )
            """
        )


def save_scan_history(settings: ScanSettings, strategy: str, candidates: list[CalendarCandidate], db_path: str = DEFAULT_DB_PATH, limit: int = 20) -> str:
    init_db(db_path)
    timestamp = datetime.now().isoformat(timespec="seconds")
    scan_id = f"{strategy}-{settings.symbol}-{timestamp}"
    settings_json = json.dumps(settings.to_dict(), sort_keys=True, default=str)

    rows = [
        (scan_id, timestamp, strategy, settings.symbol, settings_json,
         json.dumps(c.to_dict(), sort_keys=True, default=str), c.custom_score, c.rank)
        for c in candidates[:limit]
    ]
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO scan_history
            (scan_id, timestamp, strategy, symbol, settings_json, candidate_json, score, rank)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return scan_id
