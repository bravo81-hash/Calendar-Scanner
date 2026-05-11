"""IBKR contract / expiry / DTE helpers."""

from __future__ import annotations

from datetime import date, datetime


def parse_ib_expiry(expiry: str) -> date:
    """Parse IBKR expiry as YYYYMMDD or YYYY-MM-DD."""
    cleaned = str(expiry).replace("-", "")
    return datetime.strptime(cleaned, "%Y%m%d").date()


def format_ib_expiry(expiry: str) -> str:
    return parse_ib_expiry(expiry).strftime("%Y%m%d")


def days_to_expiry(expiry: str, as_of: date | None = None) -> int:
    today = as_of or date.today()
    return (parse_ib_expiry(expiry) - today).days
