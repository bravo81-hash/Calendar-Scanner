"""Strategy registry. Wires names to builder functions and required rights."""

from __future__ import annotations

from typing import Callable

from scanner.models import ScanSettings
from strategies import a14, buddy_atm, fly_diagonal, hv7, time_edge, time_zone, triple_calendar


REGISTRY: dict[str, dict] = {
    "buddy_atm": {
        "label": "Buddy ATM Calendar (enumerator + heatmap)",
        "build": buddy_atm.build,
        "needed_rights": buddy_atm.needed_rights,
        "default_target_pct": 0.10,
    },
    "triple_calendar": {
        "label": "Triple Calendar (3 puts at ATM ± EM)",
        "build": triple_calendar.build,
        "needed_rights": triple_calendar.needed_rights,
        "default_target_pct": 0.10,
    },
    "time_edge": {
        "label": "TimeEdge (ATM put cal 15/22)",
        "build": time_edge.build,
        "needed_rights": time_edge.needed_rights,
        "default_target_pct": 0.10,
    },
    "time_edge_no_touch": {
        "label": "TimeEdge No-Touch (35Δ double cal 15/43)",
        "build": time_edge.build,
        "needed_rights": time_edge.needed_rights,
        "default_target_pct": 0.10,
    },
    "time_zone": {
        "label": "TimeZone (RUT PCS + 40Δ put cal)",
        "build": time_zone.build,
        "needed_rights": time_zone.needed_rights,
        "default_target_pct": 0.05,
    },
    "a14_bwb": {
        "label": "A14 Weekly (put broken-wing butterfly)",
        "build": a14.build,
        "needed_rights": a14.needed_rights,
        "default_target_pct": 0.05,
    },
    "hv7_bwb": {
        "label": "HV7 (event-trigger put BWB)",
        "build": hv7.build,
        "needed_rights": hv7.needed_rights,
        "default_target_pct": 0.05,
    },
    "fly_diagonal": {
        "label": "FlyDiagonal (call BWB + put diagonal)",
        "build": fly_diagonal.build,
        "needed_rights": fly_diagonal.needed_rights,
        "default_target_pct": 0.10,
    },
}


def strategy_choices() -> list[tuple[str, str]]:
    return [(key, info["label"]) for key, info in REGISTRY.items()]


def build_for(strategy_key: str) -> Callable:
    if strategy_key not in REGISTRY:
        raise KeyError(f"Unknown strategy: {strategy_key}")
    return REGISTRY[strategy_key]["build"]


def rights_for(strategy_key: str, settings: ScanSettings) -> tuple[str, ...]:
    info = REGISTRY[strategy_key]
    return info["needed_rights"](settings)


def target_pct_for(strategy_key: str, override: float | None = None) -> float:
    if override is not None:
        return override
    return REGISTRY[strategy_key]["default_target_pct"]
