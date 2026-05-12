"""Regime gate: apply STFS v2.7 snapshot to candidate set.

Effects (per STFS v2.7 structural modification rules in the Pine source):
- HARD SKIP for impossible structural conditions:
    * TimeEdge + term backwardation  → SKIP
    * TimeEdge / TimeZone + iv_rank < 30 → "VERTICAL instead" (flag but don't hard skip)
    * Tier-1 event week → flag "drop front shorts" (advisory)
    * ctx_state == CRISIS → demote all calendars heavily (multiplier ~0.3)
- SOFT WEIGHTING: stfs_score_<strategy> (0-100) becomes a multiplier on
  custom_score in scoring.rank_candidates.

This module is the single place strategy/regime coupling lives. Strategy
modules are otherwise regime-blind.
"""

from __future__ import annotations

from scanner.models import CalendarCandidate, RegimeSnapshot


# Strategy-name -> attribute on RegimeSnapshot
_STRATEGY_SCORE_FIELD = {
    "a14_bwb": "stfs_score_a14",
    "buddy_atm": "stfs_score_buddy_atm",
    "fly_diagonal": "stfs_score_flyagonal",
    "triple_calendar": "stfs_score_triple",
    "time_edge": "stfs_score_time_edge",
    "time_edge_no_touch": "stfs_score_time_edge",
    "time_zone": "stfs_score_time_zone",
}


def apply_regime(candidates: list[CalendarCandidate], regime: RegimeSnapshot | None) -> None:
    """Mutate candidates in place: set regime_score, regime_flags, regime_skip."""
    if regime is None:
        # No snapshot supplied → leave neutral
        for c in candidates:
            c.regime_score = 1.0
        return

    for c in candidates:
        flags: list[str] = []
        skip = False
        multiplier = 1.0

        # --- HARD SKIPS ---
        if c.strategy in ("time_edge", "time_edge_no_touch") and regime.term_state == "BACKWARDATION":
            flags.append("SKIP — calendar hates backwardation")
            skip = True
            multiplier = 0.0

        # --- STRUCTURAL FLAGS (advisory, soft demote) ---
        if c.strategy in ("time_edge", "time_zone") and regime.iv_rank < 30:
            flags.append("VERTICAL instead of calendar (IV too low)")
            multiplier *= 0.6

        if regime.event_is_tier1:
            flags.append("Tier-1 event this week — drop front shorts / size down")
            multiplier *= 0.5

        # --- CONTEXT MULTIPLIERS ---
        if regime.ctx_state == "CRISIS":
            flags.append("CRISIS — defense only")
            multiplier *= 0.3
        elif regime.ctx_state == "RISK_OFF_VOL":
            flags.append("Risk-off — reduce size")
            multiplier *= 0.7

        # Vol regime fit (long calendars are +vega; calm/compressed is fine, expanding is risky)
        if regime.vol_state == "EXPANDING":
            multiplier *= 0.85
            flags.append("Vol expanding — calendar shape less stable")

        if regime.skew_state == "CRASH_FEAR" and c.strategy in ("triple_calendar",):
            # Triple Cal puts get fat; can be opportunity but also adjustment risk
            flags.append("Crash fear skew — put-side fat, watch left tent")

        # --- SOFT STFS WEIGHT ---
        field = _STRATEGY_SCORE_FIELD.get(c.strategy, "")
        if field:
            stfs_score = getattr(regime, field, 50)
            # Map 0-100 onto 0.5-1.5 multiplier centred at 1.0 (so 50 = neutral)
            stfs_multiplier = 0.5 + (max(0, min(100, stfs_score)) / 100.0)
            multiplier *= stfs_multiplier

        c.regime_score = max(0.0, multiplier)
        c.regime_flags = flags
        c.regime_skip = skip


def regime_summary_text(regime: RegimeSnapshot | None) -> str:
    if regime is None:
        return "No regime snapshot — neutral weighting."
    parts = [
        f"CTX {regime.ctx_state}",
        f"Macro {regime.macro_regime}",
        f"Vol {regime.vol_state}",
        f"Term {regime.term_state}",
        f"Skew {regime.skew_state}",
        f"Credit {regime.credit_state}",
        f"IVRank {regime.iv_rank}",
        f"Event {regime.event_flag}",
        f"Conv {regime.conviction}/100",
    ]
    return " | ".join(parts)


def size_mult_from_conviction(conviction: int) -> float:
    """STFS v2.7 size mapping. Display-only — scanner doesn't size."""
    if conviction >= 85:
        return 1.15
    if conviction >= 70:
        return 1.00
    if conviction >= 50:
        return 0.65
    return 0.25
