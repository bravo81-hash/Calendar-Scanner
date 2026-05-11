# Regime Integration — stfs v2.6 → Calendar Scanner

The TradingView Pine script `stfs v2.6` (preserved at `docs/strategies_html/stfs v2.6.pine`) computes a regime context state, macro regime, per-strategy scores, and structural-modification flags. The scanner ingests a snapshot of these values once per session (or whenever you re-check the dashboard) and applies them to candidate rankings.

## Ingestion contract (v1)

Manual paste via the sidebar **Regime snapshot (stfs v2.6)** expander. Fields:

| Sidebar field | stfs v2.6 source | Effect |
|---------------|------------------|--------|
| CTX state | `ctx_state` dashboard row | CRISIS → 0.3× multiplier; RISK_OFF_VOL → 0.7× |
| Macro regime | `macro_regime` dashboard row | Display-only |
| Realized vol state | `vol_state` | EXPANDING → 0.85× (calendars +vega, shape risk rises) |
| Term structure | `term_state` | BACKWARDATION + TimeEdge/no-touch → **hard skip** |
| Skew | `skew_state` | CRASH_FEAR + Triple Cal → advisory flag ("watch left tent") |
| Credit | `credit_state` | Display-only in v1 |
| IV Rank | `iv_rank` manual input on stfs | <30 + TimeEdge/TimeZone → 0.6× ("VERTICAL instead of calendar") |
| Event flag | `event_flag` | Tier-1 → 0.5× + "drop front shorts" |
| Conviction | `conviction` (max strategy score) | Display-only: size mult mapping |
| Triple Cal score | (custom; user maps from stfs) | 0-100 → 0.5×-1.5× linear multiplier |
| TimeEdge score | `score_te` from stfs | 0-100 → 0.5×-1.5× linear multiplier |
| TimeZone score | `score_tz` from stfs | 0-100 → 0.5×-1.5× linear multiplier |
| Buddy ATM score | (default 50 — no direct stfs equivalent) | 0-100 → 0.5×-1.5× linear multiplier |

## How multipliers compose

```
regime_score = base_1.0
              × ctx_multiplier            (CRISIS=0.3 / RISK_OFF_VOL=0.7 / else 1.0)
              × event_multiplier          (Tier-1=0.5 / else 1.0)
              × structural_multiplier     (low IV Rank for cal=0.6 / else 1.0)
              × vol_state_multiplier      (EXPANDING=0.85 / else 1.0)
              × stfs_strategy_multiplier  (0.5 + score/100)

if term_state == BACKWARDATION and strategy in (time_edge, time_edge_no_touch):
    regime_score = 0.0
    regime_skip = True
```

`regime_score` enters the final score as a multiplicative factor on the normalised weighted score:

```
custom_score = max(0, raw_weighted_score × regime_score)
```

## stfs v2.6 features we use

From the Pine source (`docs/strategies_html/stfs v2.6.pine`):

- **`ctx_state`** (line 264): the smooth weighted-factor regime label. CRISIS, RISK_OFF_VOL, MEAN_REV_DN/UP, DRIFT_UP_*, CHOP_*, TRANSITION, NEUTRAL.
- **`macro_regime`** (line 285): RISK OFF / LIQUIDITY / GOLDILOCKS / NEUTRAL.
- **`vol_state`** (line 153): EXPANDING / COMPRESSED / NORMAL (ATR10/ATR60 ratio).
- **`term_state`** (line 156): BACKWARDATION / CONTANGO / FLAT (VIX/VIX3M ratio).
- **`skew_state`** (line 161): CRASH_FEAR / COMPLACENT / NORMAL (SKEW index).
- **`credit_state`** (line 164): STRESSED / BID / NEUTRAL (HYG 5d return).
- **`iv_rank`**: manual SPX IV Rank input on the Pine indicator.
- **`event_flag`**: manual dropdown on the Pine indicator.
- **`score_te`, `score_tz`, etc.**: per-strategy continuous weighted scores (lines 359-363).

## Structural modifications (from stfs `struct_mod`, line 433)

The Pine indicator surfaces these structural recommendations. The scanner mirrors them as candidate flags:

| stfs `struct_mod` | Scanner behavior |
|-------------------|------------------|
| "SKIP - calendar hates backwardation" | Hard skip for TimeEdge variants (regime_score=0) |
| "VERTICAL instead of calendar (IV too low)" | Soft demote 0.6× for TimeEdge/TimeZone, advisory flag |
| "Drop front shorts - Tier-1 event this week" | Soft demote 0.5×, advisory flag |
| "Put VERTICAL instead of diagonal (skew rich)" | Not in our 4 strategies; informational only |
| "Standard" | No flag |

## Future: webhook ingestion (v2)

When you're ready to automate, replace the manual paste with a TradingView webhook → local JSON file pattern:

```
.scanner_cache/regime_snapshot.json    # gitignored
{
  "ctx_state": "CHOP_NORMAL_VOL",
  "macro_regime": "GOLDILOCKS",
  "iv_rank": 42,
  "event_flag": "None",
  "conviction": 68,
  "score_te": 72,
  "score_tz": 58,
  ...
  "stamped_at": "2026-05-11T09:30:00-05:00"
}
```

`scanner/regime.py::load_snapshot_from_file()` would parse this and the sidebar would show "auto-loaded N minutes ago" instead of manual sliders. The scoring pipeline does not change.

## Size multiplier mapping (display-only)

From stfs v2.6 (line 391):

| Conviction | Size mult |
|------------|-----------|
| ≥ 85 | 1.15× |
| ≥ 70 | 1.00× |
| ≥ 50 | 0.65× |
| < 50 | 0.25× (floor trade mode) |

Surfaced in the regime banner. The scanner does not size positions; this is informational for your discretionary sizing.

## Important: scanner is regime-aware, not regime-driven

The strategies still **build** all candidates that pass structural filters. The regime layer only **weights** and (in extreme cases like BACKWARDATION + TimeEdge) **flags** for skip. You always see the full picture — the flag tells you why the candidate dropped down the ranking, so you can decide to override discretionarily.
