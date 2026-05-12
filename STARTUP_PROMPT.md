# Calendar Scanner — AI Continuation Prompt

Use this prompt when resuming development in VS Code, Cursor, Claude Code, or similar.

---

## Project context

This is **Calendar-Scanner**, a Python scanner for short-DTE put-side calendar / diagonal strategies. It runs alongside **batman-scanner** (a separate long-DTE call-side scanner) without modifying it. They use distinct IBKR `client_id`s (batman=11, calendar=13) and separate SQLite databases.

**Scanner-only. No order placement. No live trade modification.**

## Strategies implemented

1. `buddy_atm` — Generic ATM calendar enumerator + short×long DTE heatmap (port of buddy's app.py)
2. `triple_calendar` — 3 puts at ATM ± EM ± margin; short 21 DTE / long 28 DTE
3. `time_edge` — ATM put cal 15/22; **hard skip** if back IV − front IV > 1 pt
4. `time_edge_no_touch` — 35Δ put + 35Δ call double cal 15/43
5. `time_zone` — RUT PCS (14Δ × 20pt × ≥$1.50) + Put Cal (40Δ short / same strike long ~43 DTE), qty 2

Each strategy is a separate module under `strategies/`. Source rules preserved in `docs/strategies_html/`.

## Regime integration

`STFS v2.7` TradingView Pine indicator outputs are pasted into the sidebar manually (one snapshot per session). The regime module (`scanner/regime.py`) applies:
- Hard skip: TimeEdge + BACKWARDATION
- Soft demote: low IV Rank, Tier-1 events, CRISIS context, expanding vol
- Soft weight: per-strategy stfs score → 0.5×-1.5× linear multiplier

Strategies are regime-blind. Regime is composed POST-build.

## Files to inspect before changing code

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `docs/STRATEGIES.md`
4. `docs/REGIME_INTEGRATION.md`
5. `scanner/models.py` (OptionQuote, CalendarLeg, CalendarCandidate, ScanSettings, RegimeSnapshot)
6. `scanner/scoring.py` (universal entry-quality metrics + ranking)
7. `scanner/regime.py` (STFS v2.7 → multipliers)
8. `strategies/registry.py` (strategy dispatch)
9. `strategies/base.py` (shared helpers)
10. `app.py` (Streamlit UI)

## Test before any change

```bash
python -m unittest discover -s tests -v
```

All 19 tests must pass.

## Coding rules

- Preserve scanner stability, speed, and determinism.
- Keep functions small, comments where trading logic could be misread.
- Never add `placeOrder`, `modifyOrder`, `cancelOrder` or similar to `scanner/ibkr_client.py`.
- Don't import from `batman-scanner`.
- When adding a strategy: create `strategies/<name>.py` with `NAME`, `needed_rights(settings)`, `build(...)`. Register in `strategies/registry.py`.
- When adding a `ScanSettings` field: update `scanner/models.py` AND `config.example.toml` AND README if user-facing.

## Highest-priority next tasks

1. **Webhook regime ingestion** — auto-load `.scanner_cache/regime_snapshot.json` written by a TradingView webhook. Currently manual paste only.
2. **Multi-symbol batch scan** — run the same strategy across SPX/SPY/QQQ/RUT in one click and compare top candidates.
3. **Scan diff** — compare today's scan vs. previous N scans from `scan_history.db`. See which candidates persisted.
4. **Triple Cal call-side EM** — currently uses `2 × ATM put mid` as EM fallback. When calls are cached, full straddle is used. Add a sidebar toggle to enforce full straddle (fetch calls if not cached).
5. **TimeZone delta-flat check** — verify `|delta| ≤ 10% × theta` rule; flag candidates that fail.
6. **Per-strategy default scoring weight presets** — buddy ATM ≠ TimeZone in what matters most. Add a preset selector that pre-fills the weights.

## What NOT to add

- Order placement / execution / management
- Portfolio Greeks aggregation
- ML / black-box ranking
- Replacing OptionNet Explorer
- Coupling to batman-scanner

The scanner's job is to **surface the best candidates worth manually modelling in OptionNet Explorer.** That's it.
