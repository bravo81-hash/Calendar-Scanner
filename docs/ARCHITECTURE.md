# Architecture

## Design principles

1. **Scanner-only.** No order placement, no order modification, no live trade management. Ever.
2. **Zero coupling to batman-scanner.** No imports, no shared databases, no shared client_id. Both can run side-by-side.
3. **Strategy-blind infra, regime-blind strategies.** The `scanner/` package knows nothing about Triple Cal vs. TimeEdge. Strategy modules know nothing about regime state. The regime gate composes them post-build.
4. **Deterministic ranking.** Same inputs → same ranking. No randomness, no ML.
5. **Safe defaults.** Failed market-data requests skip contracts; missing Greeks skip contracts; never crash the scan.

## Layers

```
┌─────────────────────────────────────────────────────────────┐
│ app.py (Streamlit UI)                                        │
│  - sidebar settings + regime snapshot                        │
│  - mock / cache / live scan drivers                          │
│  - workspace: candidate list + risk chart + leg detail       │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌───────────────┐  ┌────────────────┐  ┌──────────────────┐
│ strategies/   │  │ scanner/       │  │ scanner/regime   │
│  registry     │  │  scoring       │  │  apply_regime    │
│  buddy_atm    │  │  rank_candidates│ │  (post-build     │
│  triple_cal   │  │  (universal    │  │   multipliers)   │
│  time_edge    │  │   normalisation)│ │                  │
│  time_zone    │  └────────────────┘  └──────────────────┘
└───────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ scanner/option_chain (strike-window selection, scan driver)  │
│ scanner/ibkr_client (read-only, puts + calls, multi-symbol)  │
│ scanner/quote_cache (SQLite, right-aware)                    │
│ scanner/collector (background refresh)                       │
│ scanner/risk_chart (BS-M put + call, multi-leg multi-expiry) │
│ scanner/database (scan history)                              │
│ scanner/export (CSV, variable leg count)                     │
│ scanner/macro_data (rfr + div yield, harmless)               │
└─────────────────────────────────────────────────────────────┘
```

## Data flow (one scan)

1. **User clicks Run Scan** → `app.run_cache_scan` / `run_live_scan` / `run_mock_scan`.
2. **Quotes loaded** by right(s) the selected strategy needs (`strategies.registry.rights_for`).
3. **Strategy builder** runs (`strategies/<name>.py::build`) → returns `(candidates, extras)`. Builders are regime-blind.
4. **Aggregates** filled via `strategies.base.build_candidate_aggregates` (net_debit, total_delta/theta/vega/gamma).
5. **Regime gate** runs (`scanner.regime.apply_regime`) → sets `regime_score`, `regime_flags`, `regime_skip` on each candidate.
6. **Scoring + ranking** (`scanner.scoring.rank_candidates`):
   - Compute per-candidate entry metrics (theta/$, days→TP%, range/$, vega/$)
   - Normalise each metric across the candidate set
   - Weighted sum (user-tunable weights), multiplied by `regime_score`
   - Sort by `custom_score` desc, assign ranks
7. **Result returned** to UI → table + risk chart + CSV.
8. **Scan history persisted** to SQLite (live scans only).

## Why universal scoring beats strategy-specific scoring

Each metric is normalised **within the current scan**. Two consequences:

1. **Best-of-the-day floats up.** If today's chain is wide and slow (high IV, high days→TP, narrow tents), the highest-quality among-the-bad still ranks #1. Normalisation prevents absolute thresholds from rejecting all candidates.
2. **Cross-strategy ranking is comparable.** A Triple Cal candidate's `theta/$` and a TimeEdge candidate's `theta/$` are computed identically. You can't directly compare across strategies in the same scan run (we don't mix strategies in one ranking), but the *meaning* of each number is consistent across strategies.

## Quote cache strategy

`scanner/quote_cache.py` uses SQLite with PK `(symbol, expiry, strike, right)`. Both puts AND calls coexist. The collector fetches per-strategy rights (most strategies need puts only; TimeEdge no-touch needs both).

Cache freshness defaults to 30 min. Live scans bypass the cache; cache scans skip stale rows.

## Why batman's architecture inspired but didn't import

| Pattern | Batman | Calendar-Scanner | Why diverged |
|---------|--------|------------------|--------------|
| Quote cache | calls-only PK | (symbol, expiry, strike, right) PK | Calendars need puts (TimeEdge) and double-side (no-touch) |
| Strike-window | far-OTM bias (1.45-1.60× spot) | ATM-centred (0.85-1.15× spot) | Calendars are ATM strategies |
| Candidate model | 3-leg Batman (sc_high/lc_mid/sc_low) | N-leg list[CalendarLeg] | 2 legs (buddy), 4 (TimeZone), 6 (Triple) |
| Risk chart | calls only | calls + puts via right field | Self-explanatory |
| Symbols | SPX only | SPX, SPY, QQQ, RUT | TimeZone uses RUT, Triple prefers QQQ |
| client_id | 11 | 13 (default) | Must differ when both run simultaneously |
| Database files | data/scan_history.db, data/quote_cache.db | data/calendar_*.db | Separate to prevent any cross-pollination |

## Testing

`tests/` covers:
- `test_scoring_metrics.py` — pure scoring primitives
- `test_strategies_mock.py` — each strategy builds candidates from mock chain; regime gate hard-skip and soft-demote logic
- `test_risk_chart.py` — Black-Scholes put + call, IV bisection, multi-leg risk frame

19/19 tests pass. Run with `python -m unittest discover -s tests -v`.

## What can change without breaking anything

- Add a new strategy: drop a module in `strategies/`, register in `strategies/registry.py`, done. No changes to `scanner/`.
- Add a new scoring metric: add a function in `scanner/scoring.py`, call it from `compute_entry_metrics`, add weight knob to `ScanSettings`.
- Add a new regime input: extend `RegimeSnapshot`, add field to sidebar, add logic in `scanner/regime.py::apply_regime`. Strategies and scoring don't change.
- Add a new symbol: `scanner/ibkr_client.py::underlying_exchange_currency()` already handles index vs. stock detection.

## What you should NOT do

- Add anything that calls `placeOrder`, `modifyOrder`, `cancelOrder` on the IBKR client. The wrapper deliberately doesn't expose those.
- Import from `batman-scanner` directly.
- Couple the regime gate to strategy builders (regime is composed POST-build).
- Mix strategies in a single ranking — keep one strategy per scan so normalised metrics stay comparable within the set.
