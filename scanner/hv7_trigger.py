"""HV7 trigger detection helpers."""

from __future__ import annotations

from dataclasses import dataclass

from scanner.models import ScanSettings


@dataclass
class HV7TriggerSnapshot:
    available: bool
    triggered: bool
    underlying_change_pct: float | None = None
    vix_price: float | None = None
    reason: str = ""


def detect_hv7_trigger(
    underlying_price: float | None,
    underlying_prior_close: float | None,
    vix_price: float | None,
    move_threshold_pct: float = -2.0,
    vix_threshold: float = 27.0,
) -> HV7TriggerSnapshot:
    """Detect the HV7 event trigger from an index price, prior close, and VIX."""
    if underlying_price is None or underlying_price <= 0:
        return HV7TriggerSnapshot(False, False, vix_price=vix_price, reason="missing underlying price")
    if underlying_prior_close is None or underlying_prior_close <= 0:
        return HV7TriggerSnapshot(False, False, vix_price=vix_price, reason="missing underlying prior close")
    if vix_price is None or vix_price <= 0:
        return HV7TriggerSnapshot(False, False, reason="missing VIX price")

    change_pct = (underlying_price - underlying_prior_close) / underlying_prior_close * 100.0
    move_ok = change_pct <= move_threshold_pct
    vix_ok = vix_price >= vix_threshold
    if move_ok and vix_ok:
        reason = f"HV7 trigger met: index {change_pct:.2f}% and VIX {vix_price:.2f}."
    elif not move_ok and not vix_ok:
        reason = f"HV7 trigger not met: index {change_pct:.2f}% and VIX {vix_price:.2f}."
    elif not move_ok:
        reason = f"HV7 trigger not met: index move {change_pct:.2f}% is above {move_threshold_pct:.2f}%."
    else:
        reason = f"HV7 trigger not met: VIX {vix_price:.2f} is below {vix_threshold:.2f}."
    return HV7TriggerSnapshot(True, move_ok and vix_ok, change_pct, vix_price, reason)


def apply_hv7_trigger_to_settings(settings: ScanSettings, snapshot: HV7TriggerSnapshot) -> ScanSettings:
    """Return settings with auto-detected HV7 trigger fields applied when available."""
    from dataclasses import replace

    if snapshot.available:
        return replace(
            settings,
            hv7_trigger_confirmed=snapshot.triggered,
            hv7_trigger_source="auto",
            hv7_underlying_change_pct=snapshot.underlying_change_pct,
            hv7_vix_price=snapshot.vix_price,
        )
    return replace(
        settings,
        hv7_trigger_source="manual_fallback",
        hv7_underlying_change_pct=snapshot.underlying_change_pct,
        hv7_vix_price=snapshot.vix_price,
    )
