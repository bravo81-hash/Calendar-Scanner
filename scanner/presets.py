"""Per-strategy scoring weight presets.

Presets only choose the starting slider values in the UI. The scoring algorithm
still lives in `scanner.scoring`, and users can switch to custom weights.
"""

from __future__ import annotations

from dataclasses import replace

from scanner.models import ScanSettings


WEIGHT_KEYS = (
    "w_theta_debit",
    "w_range_debit",
    "w_days_to_target",
    "w_vega_debit",
    "w_spread_penalty",
)


SCORING_PRESETS: dict[str, dict[str, float]] = {
    "buddy_atm": {
        "w_theta_debit": 50.0,
        "w_range_debit": 20.0,
        "w_days_to_target": 20.0,
        "w_vega_debit": 0.0,
        "w_spread_penalty": 10.0,
    },
    "triple_calendar": {
        "w_theta_debit": 30.0,
        "w_range_debit": 30.0,
        "w_days_to_target": 20.0,
        "w_vega_debit": 10.0,
        "w_spread_penalty": 10.0,
    },
    "time_edge": {
        "w_theta_debit": 45.0,
        "w_range_debit": 20.0,
        "w_days_to_target": 20.0,
        "w_vega_debit": 5.0,
        "w_spread_penalty": 10.0,
    },
    "time_edge_no_touch": {
        "w_theta_debit": 35.0,
        "w_range_debit": 35.0,
        "w_days_to_target": 15.0,
        "w_vega_debit": 5.0,
        "w_spread_penalty": 10.0,
    },
    "time_zone": {
        "w_theta_debit": 40.0,
        "w_range_debit": 15.0,
        "w_days_to_target": 25.0,
        "w_vega_debit": 5.0,
        "w_spread_penalty": 15.0,
    },
}


def scoring_preset_for_strategy(strategy: str) -> dict[str, float]:
    """Return a copy of the scoring preset for a strategy."""
    return dict(SCORING_PRESETS.get(strategy, SCORING_PRESETS["buddy_atm"]))


def apply_scoring_preset(settings: ScanSettings, strategy: str | None = None) -> ScanSettings:
    """Return settings with preset scoring weights applied."""
    preset = scoring_preset_for_strategy(strategy or settings.strategy)
    return replace(settings, **preset)
