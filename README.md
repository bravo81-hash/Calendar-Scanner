# Calendar Scanner

Local Python scanner for calendar / diagonal put-side option strategies, using Interactive Brokers market data.

**Scanner-only.** No order placement, no live trade modification, no portfolio management.

Designed to run **alongside** the existing batman-scanner without modifying it. Uses a distinct IBKR `client_id` (default `13`) so both can be connected simultaneously.

---

## Strategies covered

| Key                  | Strategy                                  | Default DTEs        | Target % | Notes |
|----------------------|-------------------------------------------|---------------------|----------|-------|
| `buddy_atm`          | Buddy's ATM put-calendar enumerator       | 1-20 (sweeps pairs) | 10%      | Heatmap of short×long DTE included |
| `triple_calendar`    | Triple Calendar Spread (3 puts at ATM±EM) | 21 / 28             | 10%      | EM from 21 DTE ATM straddle |
| `time_edge`          | TimeEdge main (ATM put cal)               | 15 / 22             | 10%      | Aborts if back IV − front IV > 1 pt |
| `time_edge_no_touch` | TimeEdge No-Touch (35Δ double cal)        | 15 / 43             | 10%      | Needs both puts AND calls |
| `time_zone`          | TimeZone (RUT PCS + 40Δ put cal)          | 15 / 43             | 5%       | 14Δ PCS @ 20pt width + cal |
| `a14_bwb`            | A14 Weekly put broken-wing butterfly      | ~14                 | 5%       | 50/35/20 put handles |
| `hv7_bwb`            | HV7 event-trigger put BWB                 | 7-14                | 5%       | Auto-detects SPX/RUT move + VIX in live scans |
| `fly_diagonal`       | FlyDiagonal 8-leg iron-fly/time-spread    | 8 / 15              | 10%      | ATM 50pt iron fly + OTM put/call time spreads |

Each strategy's full rule set is preserved in `docs/strategies_html/` (your original HTML reference pages) and summarised in `docs/STRATEGIES.md`.

---

## Regime gate (STFS v2.7 integration)

Your TradingView `STFS v2.7` Pine indicator's outputs feed the scanner via a manual sidebar paste. Effects:

- **Hard skip**: TimeEdge in BACKWARDATION (term structure) → candidate emitted with `regime_skip=True`, score 0
- **Soft demote**: Low IV Rank + calendar strategies → "VERTICAL instead" flag, 0.6× multiplier
- **Tier-1 event week**: 0.5× multiplier, "drop front shorts / size down" flag
- **CRISIS context**: 0.3× multiplier across all strategies
- **Expanding vol**: 0.85× (calendars are +vega, but shape risk rises)
- **Per-strategy STFS score**: 50 = neutral (1.0×); 100 = boost to 1.5×; 0 = demote to 0.5×

All flags surface in the candidate table and on the selected-candidate detail view.

---

## Setup (macOS / Linux)

```bash
cd Calendar-Scanner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.toml config.local.toml
streamlit run app.py
```

`config.local.toml` is gitignored. Tune ports, DTE windows, and scoring weights there or via the sidebar.

### Test offline first

1. Run the app, tick **MOCK DATA**, pick a strategy, click **Run Scan**.
2. Confirm candidate table, risk chart, CSV export, and the regime sidebar all render.

### Live use

1. Start TWS or IB Gateway. Enable API access. Keep `Read-Only API` on.
2. Default ports: TWS paper `7497`, TWS live `7496`, IB Gateway paper `4002`, IB Gateway live `4001`.
3. Set `client_id=13` (or whatever your `config.local.toml` says) — must differ from any running batman-scanner session (default `11`).
4. **Connect to IBKR**, then **Refresh Quote Cache** so live scans don't block on market-data round trips.
5. Pick the strategy in the sidebar. Click **Run Scan** (or untick `Run from quote cache` for a live IBKR fetch).
6. The scanner needed-rights mapping ensures correct puts/calls are fetched per strategy.
7. For Triple Calendar, enable **Require full straddle EM** if you want the scanner to fetch calls and require call+put ATM mids for expected move.

---

## Why this scanner exists (vs. batman)

**batman-scanner** targets long-DTE 3-leg call-side Batman structures (~250-350 DTE, +3 position delta, far-OTM upside skew). Its architecture is excellent — quote cache, risk chart, scan history, modular scoring — but its calendar logic, strike-window selection, and put/call handling are intentionally call-biased.

**Calendar-Scanner** reuses the same architectural patterns (NOT the code — zero imports from batman-scanner) for short-DTE put-side calendars. It is generalised to:

1. Support both rights per quote fetch (puts AND calls)
2. ATM-centred strike windows (`spot * [0.85, 1.15]` default) instead of far-OTM bias
3. Multi-leg multi-expiry candidates (Triple = 6 legs across 2 expiries; TimeZone = 4 legs hybrid PCS+cal; FlyDiagonal = 8-leg iron fly + put/call time spreads)
4. Put + call Black-Scholes-Merton risk chart
5. Multi-symbol underlyings (SPX index for buddy/Triple/TimeEdge, RUT for TimeZone, SPY/QQQ for Triple)

Both scanners can run simultaneously, each with their own SQLite cache and history database.

---

## Universal calendar entry-quality metrics

Ported and extended from buddy's enumerator, applied to every strategy:

- **theta/debit**: net daily theta per dollar paid. Higher = faster decay relative to cost
- **days_to_target_pct**: how many days for theta alone to earn the strategy's TP (5% or 10%). Lower = faster trade
- **range/debit**: profit-tent width per dollar of debit. Higher = more room to be wrong directionally
- **vega/debit**: vega exposure per dollar paid (positive for long calendars)
- **avg_spread%**: liquidity drag across legs
- **regime_score**: STFS v2.7 multiplier (1.0 = neutral, 0 = hard skip)

Each metric is normalised across the candidate set in the current scan (so "best of the day" floats up regardless of absolute regime drift), then weighted per your sidebar sliders.

The sidebar can pre-fill strategy-specific scoring weights. Switch **Scoring preset** to **Custom** when you want to use the values from `config.local.toml` or tune the sliders manually for that run.

---

## Repo layout

```
Calendar-Scanner/
├── app.py                       # Streamlit entry point
├── config.example.toml          # Copy to config.local.toml
├── requirements.txt
├── data/                        # SQLite (gitignored)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── STRATEGIES.md            # Distilled rules for implemented + reference strategies
│   ├── REGIME_INTEGRATION.md    # STFS v2.7 ingestion contract
│   └── strategies_html/         # Strategy HTML references + Pine
├── scanner/                     # Shared infrastructure (read-only IBKR, cache, scoring, risk chart)
│   ├── models.py                # OptionQuote, CalendarLeg, CalendarCandidate, ScanSettings, RegimeSnapshot
│   ├── ibkr_client.py           # Puts + calls + multi-symbol qualifier
│   ├── option_chain.py          # ATM-centred strike windows, generic scan driver
│   ├── quote_cache.py           # SQLite (right-aware)
│   ├── collector.py             # Background quote-cache refresh
│   ├── scoring.py               # Universal calendar entry-quality metrics
│   ├── regime.py                # STFS v2.7 snapshot → candidate multipliers
│   ├── risk_chart.py            # Put + call BS-M, multi-leg multi-expiry
│   ├── database.py              # Scan history
│   ├── export.py                # CSV (variable leg count)
│   ├── mock_data.py
│   ├── macro_data.py
│   └── config.py
├── strategies/                  # Per-strategy candidate builders
│   ├── base.py                  # ATM rounding, nearest-by-delta/strike, EM helpers
│   ├── buddy_atm.py             # Enumerator + heatmap
│   ├── triple_calendar.py       # 3 puts at ATM ± EM ± margin
│   ├── time_edge.py             # Main + No-Touch
│   ├── time_zone.py             # PCS + Put Cal hybrid
│   └── registry.py
└── tests/                       # Unit tests for strategies, scoring, risk charts, and STFS integration
```

---

## What's intentionally NOT included

- Order placement, modification, or cancellation
- Live trade management / adjustments
- Portfolio Greeks aggregation
- ML / ranking optimisation
- Replacing OptionNet Explorer

The scanner's job is to **shortlist candidates worth modelling in OptionNet Explorer**.

---

## Troubleshooting

- **No candidates**: Open the candidate table. Check `regime_score` — values <0.3 mean regime is demoting. Open rejection reasons in the diagnostics expander.
- **Missing Greeks**: IBKR market-data subscription issue. Try `Frozen` or `Delayed frozen` mode after-hours.
- **Slow scans**: Use the quote cache. The first cache refresh per session is slow; subsequent scans are fast.
- **`time_edge_no_touch` always empty**: It needs BOTH puts AND calls. The collector fetches both rights when this strategy is selected.

---

## Credits

- Original SPX Live Calendar Scanner v1.3-1.5 by Bhavik's trading buddy
- STFS v2.7 Pine indicator → preserved at `docs/strategies_html/stfs v2.7.pine`
- TimeEdge based on Amy Meissner workshop materials
- TimeZone based on SMB Training materials
- Architectural patterns inspired by batman-scanner
