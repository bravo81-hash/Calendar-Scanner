"""VIX regime classification for Flux / Double Calendar Alpha."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VixRegime:
    name: str
    structure_mode: str
    primary_alert_ok: bool
    message: str


def classify_vix_regime(vix_price: float | None) -> VixRegime:
    if vix_price is None or vix_price <= 0:
        return VixRegime("UNKNOWN", "LONG_VEGA", False, "VIX unavailable; alerts are informational only.")
    if vix_price > 30:
        return VixRegime(
            "HIGH_VIX",
            "NEGATIVE_VEGA",
            False,
            "VIX > 30: use compressed Wed/Fri negative-vega hack.",
        )
    if vix_price < 15 or 13 <= vix_price <= 19:
        return VixRegime(
            "BASELINE",
            "LONG_VEGA",
            True,
            "VIX baseline/teens: standard long-vega double calendar is eligible.",
        )
    return VixRegime("NEUTRAL", "LONG_VEGA", False, "VIX outside preferred alert band.")
