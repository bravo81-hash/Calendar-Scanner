"""Per-strategy candidate builders.

Each module exposes:
    NAME: str
    needed_rights() -> tuple[str, ...]
    build(symbol, quotes_by_expiry, dte_by_expiry, settings, regime, underlying_price)
        -> (list[CalendarCandidate], dict_of_extras)

Strategies are regime-blind; the regime module applies multipliers afterwards.
"""

from scanner.models import CalendarCandidate, CalendarLeg, OptionQuote, ScanSettings  # noqa: F401
