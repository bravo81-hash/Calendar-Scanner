# Strategies — Distilled Rule Sets

Source of truth for each strategy's mechanics, abort criteria, and exit rules.
Original HTML reference pages preserved in `docs/strategies_html/`.

---

## 1. Triple Calendar Spread

**Source**: docs/strategies_html/Tripple Calendar.html

| Field | Value |
|-------|-------|
| Risk profile | 2/10, market-neutral, +Vega |
| Target win rate | ~80% |
| Profit target | 10% of initial debit |
| Avg time in trade | 2-10 days |
| Hard time stop | 7 days remaining on short leg (14 days in trade) |

### Setup
- **Underlying**: QQQ preferred. SPY/SPX also work. Avoid earnings/binary events.
- **Entry**: Typically Fridays.
- **Short leg**: 21 DTE.
- **Long leg**: 28 DTE (one week after short).
- **Middle calendar strike**: At-The-Money, rounded to nearest 5 (e.g. spot 638 → 635 or 640).
- **Expected Move (EM)**: Sum of ATM straddle prices (Call mid + Put mid) at the 21 DTE expiry.
- **Upper calendar strike**: ATM + EM + ~5 points margin.
- **Lower calendar strike**: ATM − EM − ~5 points margin.

All three calendars use puts (or your direction choice; default puts in this scanner) with short=21 DTE / long=28 DTE.

### Management
- TP: 10% of initial debit. Close the entire trade. Do not get greedy.
- SL: **No percentage stop.** Hard time stop at 7 days remaining on short.
- Avoid front-shorts directly ahead of FOMC, CPI, major earnings.
- Adjustment (advanced): If underlying blows past upper/lower strikes, can add a 4th calendar further out. Beginners should respect the 7-day hard stop instead.

### Scanner mapping
- `strategies/triple_calendar.py`
- 6 legs (3 calendars × 2 expiries)
- EM computed from puts only by default (2× ATM put mid as proxy); if calls are also cached, EM uses the full straddle.
- Sidebar option `Require full straddle EM` fetches calls and rejects the candidate if call quotes are not available.
- `extras.expected_move`, `extras.upper_strike`, `extras.lower_strike`, `extras.time_stop_dte` populated for the risk view.

---

## 2. TimeEdge (Main)

**Source**: docs/strategies_html/TimeEdge.html

| Field | Value |
|-------|-------|
| Style | Neutral / Non-Directional |
| Underlying | SPY preferred, SPX |
| Structure | ATM Put Calendar Spread |
| Greeks | +Theta, +Vega |
| Profit target | 10% of margin |
| Stop loss | Tent breach, or 15-20% max loss near expiration |
| Hard time stop | Exit by 1 DTE (Thursday). NEVER hold to expiration. |

### Setup
- **Entry**: Thursday @ ~3:30 PM ET.
- **Strike**: ATM.
- **Short leg**: 15 DTE.
- **Long leg**: 22 DTE.

### ABORT criteria (the scanner enforces #3 as a hard skip)
1. Next day is a market holiday (low liquidity).
2. Major announcement pending (FOMC, CPI, etc.).
3. **Back-month IV − Front-month IV > 1 vol point** ← hard skip.

### Routine
- Check once daily, ~30 min before close.
- Maximum **ONE** adjustment. If adjustment fails, exit.

### Adjustments (when price touches breakeven / tent edge)
- **Method A — Minimal Margin**: Sell 50% of long back-month puts, buy front puts at lower/higher strike. Goal: flatten deltas, low capital.
- **Method B — Expanded Margin**: Add long ATM diagonal (sell front ATM, buy back lower/higher). Goal: add theta, uses more capital.

### Exit targets after adjustment
- Minimal margin adjustment → still TP 10% of margin.
- Expanded margin adjustment → TP 5% of new margin.
- Flash profit: exit early if hit in 1-2 days.

### Scanner mapping
- `strategies/time_edge.py::build_main`
- 2 legs (single put calendar at ATM).
- If `long_q.implied_vol - short_q.implied_vol > settings.te_back_iv_excess_max` (default 1.0 vol pts), candidate is **not emitted** and warning surfaces.

---

## 3. TimeEdge No-Touch (Bonus)

**Source**: docs/strategies_html/TimeEdge.html, "No-Touch" section

| Field | Value |
|-------|-------|
| Style | Weekly Double Calendar, set-and-forget |
| Structure | 35Δ Put + 35Δ Call double calendar |
| Profit target | 10% |
| Stop loss | 10% |
| Hard time stop | Exit @ 1 DTE |
| Management | NONE — no adjustments |

### Setup
- **Entry**: Thursday @ 3:30 PM.
- **Short legs**: 15 DTE, 35Δ on each side.
- **Long legs**: 43 DTE, same strikes as short.

### Scanner mapping
- `strategies/time_edge.py::build_no_touch`
- 4 legs (put cal + call cal).
- Needs **both puts AND calls** in the quote cache (collector fetches both rights when this strategy is selected).

---

## 4. TimeZone

**Source**: docs/strategies_html/TimeZone.html

| Field | Value |
|-------|-------|
| Underlying | RUT (preferred — high-prob, short-term, market-neutral) |
| Avg duration | 5 days |
| Win rate | ~75% |
| Min capital | ~$7k |
| Margin / contract | ~$3k |
| Profit target | 5% of planned capital |
| Stop loss | ~5% (do not hope for reversal) |
| Hard time stop | 7 DTE |

### Setup (Entry: Thursday @ end-of-day, ~15 DTE)

**Component A — Put Credit Spread (income)**
- 2 contracts minimum.
- 20 points wide.
- Short strike at ~14Δ.
- Net credit > $1.50 per spread.

**Component B — Put Calendar (hedge / +Vega)**
- 2 contracts.
- Front: 15 DTE, short at ~40Δ.
- Back: same strike, ~6 weeks (~43 DTE) out.

### Greeks at entry
- +Theta, +Vega.
- Delta flat: ≤10% of theta in absolute terms.

### Management
- **Market rallies**: Trigger ~halfway between start and upside breakeven (Δ reaches 15-20% of theta).
  - Reverse Diagonal: sell back-month long / buy lower-strike front-month put.
  - Roll Long Put: roll back-month long put down (creates PCS in back month).
- **Market chops**: Do nothing if inside profit tent. Theta is your friend. Wait for 5%.
- **Market drops** (before price hits the top of the tent / peak profit zone):
  - Put Debit Spread: buy closer strike / sell further OTM (rolls short strike down).
  - Add Hedge: long put to flatten delta.

### Pro tips (encoded as warnings/flags)
- Enter as spreads, not legged in.
- Conditional orders for emergency hedges (e.g. if RUT drops 30 pts).
- Peel off layers when exiting large positions to keep delta flat.

### Scanner mapping
- `strategies/time_zone.py`
- 4 legs: PCS short put, PCS long put (20pt wide), Cal short put, Cal long put (same strike, back expiry).
- PCS credit check: requires `> tz_pcs_min_credit` (default $1.50). Configurable.
- Delta-flat check is surfaced as a warning when `|position_delta| > 10% × |position_theta|`.
- `extras.pcs_credit`, `extras.planned_capital`, `extras.target_pct=0.05`, `extras.delta_flat_pass`.

---

## 5. Buddy ATM Calendar Enumerator

**Source**: distilled from the original SPX Live Calendar Scanner v1.3-1.5.

| Field | Value |
|-------|-------|
| Style | Discovery — what's the chain offering today |
| Structure | Single ATM put (or call) calendar |
| DTE | 1-20, all valid pairs |
| Ranking | Multi-factor weighted (theta/debit, range/debit, days_to_10%, vega/debit, spread) |

### Setup
- ATM strike rounded to nearest 5 (SPX/RUT) or nearest 1 (SPY/QQQ).
- Enumerates **every** valid `(short_dte, long_dte)` pair where `long > short`.
- Filters: positive net theta, positive debit, spread ≤ `max_spread_pct_hard`.

### Output
- Candidate table with all pairs and their metrics.
- **Heatmap** of `theta/debit` across `short_dte × long_dte` — visualises the entire calendar surface for the day.

### Why this is the 4th strategy
The rule-based strategies (Triple/TimeEdge/TimeZone) prescribe specific DTEs. The buddy enumerator answers the complementary question: **what does the chain itself prefer today?** If buddy_atm shows a 14/21 pair beating the rulebook 15/22, that's a tweak signal — but it does not override the rule book. It feeds the discretionary judgment that lives outside the scanner.

---

## How to read scanner output

For each candidate:

- `score` — final weighted score (0-1), normalised within this scan
- `regime_score` — multiplier from STFS v2.7 snapshot (1.0 = neutral; 0 = hard skip)
- `theta/$` — `net_theta / net_debit`, the primary entry-quality metric
- `days→target` — days for theta alone to earn the strategy's TP%; lower = faster
- `range/$` — profit tent width per dollar of debit
- `regime_flags` — narrative warnings (e.g. "VERTICAL instead of calendar (IV too low)")

Use the **risk chart** for visual triage; do final modelling in OptionNet Explorer before any trade.

---

## Additional implemented reference strategies

The following source pages are preserved in `docs/strategies_html/` and are now
available as selectable scanner strategies. The scanner builds initial entry
candidates only; adjustment workflows remain documented guidance.

### A14 Weekly Strategy

**Source**: docs/strategies_html/A14.html

- SPX put broken-wing butterfly.
- Standard entry: Friday morning, about 14 DTE.
- Typical construction: long ATM put, short 2x lower puts, long further-lower put.
- Rough delta handles from the reference: 50 / 35 / 20.
- Profit target: 5% of margin. Time stop: 2 DTE.
- Optional hedges include far OTM puts and calendar hedges when price challenges the tent.

### Scanner mapping
- `strategies/a14.py`
- 3 legs: buy upper/ATM-ish put, sell 2x middle puts, buy lower put.
- Default delta handles: 50 / 35 / 20.
- `extras.bwb_width_upper`, `extras.bwb_width_lower`, `extras.target_pct=0.05`.

### HV7 Option Trading System

**Source**: docs/strategies_html/HV7.html

- SPX or RUT weekly put broken-wing butterfly.
- Triggered by high-volatility event conditions: SPX down at least 2% and VIX at least 27 during regular market hours.
- Entry is near the close, using Friday expiration with at least 7 DTE.
- Standard setup uses ATM / ~35 delta / ~20 delta put handles.
- No adjustments. Exit before expiration day, and exit if theta becomes negative while spot is above the upper wing.

### Scanner mapping
- `strategies/hv7.py`
- 3 legs: put broken-wing butterfly using 50 / 35 / 20 handles.
- Live scans auto-detect the trigger from the underlying same-day move and VIX.
- Mock/cache scans, or live scans where data is unavailable, use the manual fallback checkbox.
- If the trigger is not confirmed, the candidate is still shown for modelling but a warning is emitted.

### FlyDiagonal

**Source**: docs/strategies_html/FlyDiagonal.html

- Multi-leg income structure combining an ATM iron fly with OTM put and call time spreads.
- Primary vehicle: SPX. Alternatives: SPY, QQQ, RUT, IWM.
- Reference time frame: roughly 4-14 DTE.
- Implemented structure: ATM 50-point-wide iron fly plus OTM put and call time spreads 50 points beyond the iron-fly wings.
- Profit target is usually 10-15%, with a quick-exit rule for early 4%+ gains.

### Scanner mapping
- `strategies/fly_diagonal.py`
- 8-leg variant: long put wing, short ATM put, short ATM call, long call wing, OTM put time spread, OTM call time spread.
- Default iron-fly width: 50 points.
- Default OTM time-spread anchor: 50 points beyond each long iron-fly wing.
- Builder searches a small strike grid around the anchors and prefers theta-positive, delta-neutral candidates.
