"""Calendar Scanner — Streamlit entry point.

Scanner only. No order placement, no live trade modification.
Runs alongside batman-scanner; uses a distinct IBKR client_id (default 13).
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from scanner.collector import QuoteCacheCollector
from scanner.config import ibkr_config, load_config, settings_from_config
from scanner.database import save_scan_history
from scanner.export import candidates_to_csv
from scanner.ibkr_client import (
    IBKRClient,
    resolve_underlying_price,
    runtime_diagnostics,
    summarize_chain,
)
from scanner.hv7_trigger import apply_hv7_trigger_to_settings
from scanner.mock_data import build_mock_chain
from scanner.models import CalendarCandidate, RegimeSnapshot, ScanResult, ScanSettings
from scanner.option_chain import scan_from_quote_fetcher
from scanner.quote_cache import (
    list_cached_expiries,
    load_cached_quotes,
    load_cache_underlying_price,
    quote_cache_stats,
)
from scanner.presets import scoring_preset_for_strategy
from scanner.regime import apply_regime, regime_summary_text, size_mult_from_conviction
from scanner.risk_chart import candidate_risk_frame
from scanner.scoring import rank_candidates
from strategies.registry import REGISTRY, build_for, rights_for, target_pct_for, strategy_choices


st.set_page_config(page_title="Calendar Scanner", layout="wide")


# ---------------------------------------------------------------------------
# Cached collector
# ---------------------------------------------------------------------------

@st.cache_resource
def get_collector() -> QuoteCacheCollector:
    return QuoteCacheCollector()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def sidebar_settings(defaults: ScanSettings, ib_defaults: dict[str, Any]) -> tuple[ScanSettings, dict[str, Any], RegimeSnapshot]:
    st.sidebar.header("Connection")
    host = st.sidebar.text_input("Host", value=str(ib_defaults["host"]))
    port_options = [7497, 7496, 4001, 4002]
    port_index = port_options.index(int(ib_defaults["port"])) if int(ib_defaults["port"]) in port_options else 0
    port = st.sidebar.selectbox("Port", options=port_options, index=port_index)
    client_id = st.sidebar.number_input("Client ID", min_value=1, max_value=999, value=int(ib_defaults["client_id"]))
    market_data_type = st.sidebar.selectbox("Market data type", options=["Live", "Frozen", "Delayed", "Delayed frozen"], index=0)
    manual_underlying_price = st.sidebar.number_input("Manual underlying price (off-hours fallback)", min_value=0.0, value=0.0, step=1.0)

    st.sidebar.header("Symbol")
    symbol = st.sidebar.selectbox("Underlying", options=["SPX", "SPY", "QQQ", "RUT"], index=0).upper()
    exchange_map = {"SPX": "CBOE", "SPY": "SMART", "QQQ": "SMART", "RUT": "RUSSELL"}
    exchange = st.sidebar.text_input("Exchange", value=exchange_map.get(symbol, "SMART"))

    st.sidebar.header("Strategy")
    choices = strategy_choices()
    strategy_key = st.sidebar.selectbox(
        "Strategy",
        options=[k for k, _ in choices],
        format_func=lambda k: dict(choices)[k],
        index=0,
    )
    triple_require_full_straddle = defaults.triple_require_full_straddle
    if strategy_key == "triple_calendar":
        triple_require_full_straddle = st.sidebar.checkbox(
            "Require full straddle EM",
            value=defaults.triple_require_full_straddle,
            help="Fetch calls as well as puts so Triple Calendar expected move uses ATM call mid + put mid.",
        )
    hv7_trigger_confirmed = defaults.hv7_trigger_confirmed
    hv7_auto_detect_trigger = defaults.hv7_auto_detect_trigger
    if strategy_key == "hv7_bwb":
        hv7_auto_detect_trigger = st.sidebar.checkbox(
            "Auto-detect HV7 trigger live",
            value=defaults.hv7_auto_detect_trigger,
            help="In live IBKR scans, check index same-day move and VIX automatically.",
        )
        hv7_trigger_confirmed = st.sidebar.checkbox(
            "Manual HV7 trigger fallback",
            value=defaults.hv7_trigger_confirmed,
            help="Used for mock/cache scans or when live auto-detection is unavailable.",
        )

    st.sidebar.header("DTE / Strike window")
    min_short_dte = st.sidebar.number_input("Min DTE", min_value=0, max_value=200, value=defaults.min_short_dte)
    max_long_dte = st.sidebar.number_input("Max DTE", min_value=1, max_value=400, value=defaults.max_long_dte)
    lower_mult = st.sidebar.slider("Strike window lower (× spot)", 0.50, 1.00, defaults.lower_strike_multiplier, 0.01)
    upper_mult = st.sidebar.slider("Strike window upper (× spot)", 1.00, 1.50, defaults.upper_strike_multiplier, 0.01)
    max_per_expiry = st.sidebar.number_input("Max contracts per expiry", min_value=20, max_value=200, value=defaults.max_contracts_per_expiry)
    batch_size = st.sidebar.number_input("Market-data batch size", min_value=10, max_value=95, value=min(defaults.market_data_batch_size, 95))

    st.sidebar.header("Scoring weights")
    scoring_mode = st.sidebar.selectbox("Scoring preset", options=["Strategy default", "Custom"], index=0)
    if scoring_mode == "Strategy default":
        weight_defaults = scoring_preset_for_strategy(strategy_key)
    else:
        weight_defaults = {
            "w_theta_debit": defaults.w_theta_debit,
            "w_range_debit": defaults.w_range_debit,
            "w_days_to_target": defaults.w_days_to_target,
            "w_vega_debit": defaults.w_vega_debit,
            "w_spread_penalty": defaults.w_spread_penalty,
        }
    w_theta = st.sidebar.slider("Theta / Debit weight", 0, 100, int(weight_defaults["w_theta_debit"]))
    w_range = st.sidebar.slider("Range / Debit weight", 0, 100, int(weight_defaults["w_range_debit"]))
    w_days = st.sidebar.slider("Days-to-target weight", 0, 100, int(weight_defaults["w_days_to_target"]))
    w_vega = st.sidebar.slider("Vega / Debit weight", 0, 100, int(weight_defaults["w_vega_debit"]))
    w_spread = st.sidebar.slider("Spread penalty weight", 0, 100, int(weight_defaults["w_spread_penalty"]))

    st.sidebar.header("Cache")
    use_cache = st.sidebar.checkbox("Run from quote cache", value=True)
    cache_minutes = st.sidebar.number_input("Cache max age (minutes)", min_value=1, max_value=1440, value=defaults.cache_max_age_minutes)

    st.sidebar.header("Risk chart")
    risk_chart_spot = st.sidebar.number_input("Risk chart spot price", min_value=0.0, value=float(manual_underlying_price), step=1.0)
    rfr = st.sidebar.number_input("Risk-free rate", min_value=0.0, max_value=0.2, value=defaults.risk_free_rate, step=0.005, format="%.3f")
    div_y = st.sidebar.number_input("Dividend yield", min_value=0.0, max_value=0.1, value=defaults.dividend_yield, step=0.001, format="%.3f")

    # --- stfs v2.6 regime snapshot ---
    st.sidebar.header("Regime snapshot (stfs v2.6)")
    with st.sidebar.expander("Paste stfs dashboard outputs", expanded=False):
        ctx_state = st.selectbox("CTX state", options=[
            "NEUTRAL", "CRISIS", "RISK_OFF_VOL", "MEAN_REV_DN", "MEAN_REV_UP",
            "DRIFT_UP_TRENDING", "DRIFT_UP_CALM", "CHOP_LOW_VOL", "CHOP_NORMAL_VOL", "TRANSITION",
        ], index=0)
        macro_regime = st.selectbox("Macro regime", options=["NEUTRAL", "GOLDILOCKS", "LIQUIDITY", "RISK OFF"], index=0)
        vol_state = st.selectbox("Realized vol state", options=["NORMAL", "EXPANDING", "COMPRESSED"], index=0)
        term_state = st.selectbox("Term structure", options=["FLAT", "CONTANGO", "BACKWARDATION", "UNKNOWN"], index=0)
        skew_state = st.selectbox("Skew", options=["NORMAL", "CRASH_FEAR", "COMPLACENT", "UNKNOWN"], index=0)
        credit_state = st.selectbox("Credit", options=["NEUTRAL", "STRESSED", "BID", "UNKNOWN"], index=0)
        iv_rank = st.slider("IV Rank (0-100)", 0, 100, 50)
        event_flag = st.selectbox("Event flag", options=["None", "Tier-1", "Tier-2", "OPEX", "Multiple"], index=0)
        conviction = st.slider("stfs Conviction", 0, 100, 50)
        st.markdown("**Per-strategy stfs scores (0-100)**")
        stfs_triple = st.slider("Triple Cal score", 0, 100, 50)
        stfs_te = st.slider("TimeEdge score", 0, 100, 50)
        stfs_tz = st.slider("TimeZone score", 0, 100, 50)
        stfs_buddy = st.slider("Buddy ATM score", 0, 100, 50)

    regime = RegimeSnapshot(
        ctx_state=ctx_state, macro_regime=macro_regime, vol_state=vol_state,
        term_state=term_state, skew_state=skew_state, credit_state=credit_state,
        iv_rank=int(iv_rank), event_flag=event_flag, conviction=int(conviction),
        stfs_score_triple=int(stfs_triple), stfs_score_time_edge=int(stfs_te),
        stfs_score_time_zone=int(stfs_tz), stfs_score_buddy_atm=int(stfs_buddy),
    )

    settings = ScanSettings(
        symbol=symbol, exchange=exchange, currency=defaults.currency,
        lower_strike_multiplier=float(lower_mult), upper_strike_multiplier=float(upper_mult),
        max_contracts_per_expiry=int(max_per_expiry), market_data_batch_size=int(batch_size),
        min_short_dte=int(min_short_dte), max_long_dte=int(max_long_dte),
        strategy=strategy_key,
        triple_require_full_straddle=bool(triple_require_full_straddle),
        hv7_trigger_confirmed=bool(hv7_trigger_confirmed),
        hv7_auto_detect_trigger=bool(hv7_auto_detect_trigger),
        w_theta_debit=float(w_theta), w_range_debit=float(w_range), w_days_to_target=float(w_days),
        w_vega_debit=float(w_vega), w_spread_penalty=float(w_spread),
        cache_max_age_minutes=int(cache_minutes),
        risk_free_rate=float(rfr), dividend_yield=float(div_y),
    )
    connection = {
        "host": host, "port": int(port), "client_id": int(client_id),
        "market_data_type": market_data_type,
        "manual_underlying_price": float(manual_underlying_price),
        "risk_chart_spot": float(risk_chart_spot),
        "use_cache": bool(use_cache),
        "cache_max_age_seconds": int(cache_minutes) * 60,
    }
    return settings, connection, regime


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def candidate_rows(candidates: list[CalendarCandidate]) -> list[dict[str, Any]]:
    rows = []
    for c in candidates:
        rows.append({
            "rank": c.rank,
            "score": round(c.custom_score, 4),
            "regime_score": round(c.regime_score, 3),
            "skip": "⛔" if c.regime_skip else "",
            "front_dte": c.front_dte,
            "back_dte": c.back_dte,
            "net_debit": round(c.net_debit, 2),
            "theta/$": round(c.theta_debit_ratio, 4),
            "days→target": round(c.days_to_target_pct, 2) if c.days_to_target_pct != float("inf") else "∞",
            "range/$": round(c.range_debit_ratio, 3),
            "vega/$": round(c.vega_debit_ratio, 4),
            "pos_theta": round(c.position_theta, 2),
            "pos_vega": round(c.position_vega, 2),
            "pos_delta": round(c.position_delta, 2),
            "avg_spread%": round(c.average_spread_pct, 2),
            "regime_flags": " ; ".join(c.regime_flags) if c.regime_flags else "",
        })
    return rows


def candidate_picker_label(c: CalendarCandidate) -> str:
    strikes = "/".join(f"{int(l.quote.strike)}" for l in c.legs[:6])
    skip = "⛔ " if c.regime_skip else ""
    return (
        f"{skip}#{c.rank} | {c.front_dte}d/{c.back_dte}d | "
        f"strikes {strikes} | debit {c.net_debit:.2f} | "
        f"θ/$ {c.theta_debit_ratio:.3f} | days {c.days_to_target_pct:.1f}"
    )


def leg_rows(c: CalendarCandidate) -> list[dict[str, Any]]:
    return [{
        "leg": l.name, "role": l.role, "action": l.action, "qty": l.quantity,
        "expiry": l.quote.expiry, "strike": l.quote.strike, "right": l.quote.right,
        "bid": l.quote.bid, "ask": l.quote.ask, "mid": l.quote.mid,
        "delta": l.quote.delta, "theta": l.quote.theta, "vega": l.quote.vega,
        "IV": l.quote.implied_vol,
    } for l in c.legs]


def show_risk_chart(c: CalendarCandidate, spot: float, settings: ScanSettings) -> None:
    frame = candidate_risk_frame(
        c, spot_price=spot, price_points=121, projection_count=5,
        lower_multiplier=settings.lower_strike_multiplier,
        upper_multiplier=settings.upper_strike_multiplier,
        risk_free_rate=settings.risk_free_rate, dividend_yield=settings.dividend_yield,
    )
    if frame.empty:
        st.info("Cannot render risk chart without a spot price.")
        return
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35],
        vertical_spacing=0.06, subplot_titles=("Projected PnL", "Greeks at T+0"),
    )
    for label, group in frame.groupby("projection_label"):
        fig.add_trace(go.Scatter(x=group["underlying_price"], y=group["pnl"], mode="lines", name=label), row=1, col=1)
    current = frame[frame["projection_day"] == 0]
    for greek in ["delta", "gamma", "theta", "vega"]:
        values = current[greek] / 100 if greek == "vega" else current[greek]
        label = "vega/100" if greek == "vega" else greek
        fig.add_trace(go.Scatter(x=current["underlying_price"], y=values, mode="lines", name=label), row=2, col=1)
    fig.add_vline(x=spot, line_dash="dash", line_color="white")
    fig.add_hline(y=0, row=1, col=1, line_color="gray")
    fig.update_layout(height=620, template="plotly_dark", margin={"l": 40, "r": 20, "t": 40, "b": 32}, legend={"orientation": "h"})
    fig.update_xaxes(title_text="Underlying Price", row=2, col=1)
    fig.update_yaxes(title_text="Profit/Loss ($)", row=1, col=1)
    fig.update_yaxes(title_text="Greeks", row=2, col=1)
    st.plotly_chart(fig, use_container_width=True)


def show_heatmap(extras: dict[str, Any]) -> None:
    pivot = extras.get("heatmap_pivot")
    if pivot is None or pivot.empty:
        return
    fig = px.imshow(
        pivot, text_auto=".3f", aspect="auto", color_continuous_scale="Viridis",
        labels={"x": "Long DTE", "y": "Short DTE", "color": "theta/debit"},
    )
    fig.update_layout(template="plotly_dark", height=420, margin={"l": 40, "r": 20, "t": 36, "b": 34})
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Scan drivers
# ---------------------------------------------------------------------------

def run_mock_scan(settings: ScanSettings, regime: RegimeSnapshot) -> ScanResult:
    quotes_by_expiry, dte_by_expiry, spot = build_mock_chain(settings.symbol, 5800.0 if settings.symbol == "SPX" else 580.0)
    builder = build_for(settings.strategy)
    candidates, extras = builder(settings.symbol, quotes_by_expiry, dte_by_expiry, settings, regime, spot)
    apply_regime(candidates, regime)
    target_pct = target_pct_for(settings.strategy)
    if candidates:
        candidates = rank_candidates(candidates, settings, target_pct=target_pct)
    return ScanResult(
        settings=settings, strategy=settings.strategy,
        candidates=candidates[: settings.max_results],
        underlying_price=spot, regime=regime, extras=extras, mock=True,
    )


def run_cache_scan(settings: ScanSettings, regime: RegimeSnapshot, connection: dict[str, Any]) -> ScanResult:
    """Build candidates from cached quotes (faster, no IBKR calls)."""
    max_age = connection["cache_max_age_seconds"]
    rights = rights_for(settings.strategy, settings)
    cached_expiries = list_cached_expiries(settings.symbol, max_age)
    if not cached_expiries:
        return ScanResult(
            settings=settings, strategy=settings.strategy, candidates=[],
            warnings=["No fresh cached quotes. Run 'Refresh Quote Cache' first."],
            regime=regime,
        )

    # Load all quotes, merging both rights when strategy needs them
    quotes_by_expiry: dict[str, list] = {}
    from scanner.contracts import days_to_expiry
    dte_by_expiry: dict[str, int] = {}
    for exp in cached_expiries:
        merged = []
        for right in rights:
            merged.extend(load_cached_quotes(settings.symbol, exp, max_age, right=right))
        if merged:
            quotes_by_expiry[exp] = merged
            dte_by_expiry[exp] = days_to_expiry(exp)

    # Filter by DTE window
    dte_by_expiry = {e: d for e, d in dte_by_expiry.items() if settings.min_short_dte <= d <= settings.max_long_dte}
    quotes_by_expiry = {e: q for e, q in quotes_by_expiry.items() if e in dte_by_expiry}

    underlying_price = load_cache_underlying_price(settings.symbol, max_age) or connection.get("manual_underlying_price")
    if underlying_price and underlying_price <= 0:
        underlying_price = None

    builder = build_for(settings.strategy)
    candidates, extras = builder(settings.symbol, quotes_by_expiry, dte_by_expiry, settings, regime, underlying_price)
    apply_regime(candidates, regime)
    target_pct = target_pct_for(settings.strategy)
    if candidates:
        candidates = rank_candidates(candidates, settings, target_pct=target_pct)
    return ScanResult(
        settings=settings, strategy=settings.strategy,
        candidates=candidates[: settings.max_results],
        underlying_price=underlying_price, regime=regime, extras=extras,
    )


def run_live_scan(settings: ScanSettings, connection: dict[str, Any], regime: RegimeSnapshot, status_box: Any) -> ScanResult:
    client = IBKRClient()
    try:
        status_box.info("connecting to IBKR")
        client.connect(connection["host"], connection["port"], connection["client_id"])
        client.set_market_data_type(connection["market_data_type"])

        status_box.info("qualifying underlying")
        underlying = client.qualify_underlying(settings)

        status_box.info("fetching option chain")
        chain = client.option_chain(underlying, settings)

        ibkr_price = client.get_underlying_price(underlying)
        underlying_price = resolve_underlying_price(ibkr_price, connection.get("manual_underlying_price"))
        if underlying_price is None:
            st.warning("No underlying price; strike filtering will fall back to a centred slice.")

        if settings.strategy == "hv7_bwb" and settings.hv7_auto_detect_trigger:
            status_box.info("checking HV7 trigger from underlying and VIX")
            snapshot = client.detect_hv7_trigger(settings.symbol, settings.exchange)
            settings = apply_hv7_trigger_to_settings(settings, snapshot)
            if snapshot.available:
                if snapshot.triggered:
                    status_box.success(snapshot.reason)
                else:
                    status_box.warning(snapshot.reason)
            else:
                status_box.warning(f"{snapshot.reason}; using manual HV7 fallback.")

        rights = rights_for(settings.strategy, settings)
        expiries = sorted(chain.expirations)

        def fetch_quotes(expiry: str):
            merged = []
            for right in rights:
                merged.extend(client.fetch_quotes_for_expiry(expiry, chain, settings, underlying_price, right=right, progress=status_box.info))
            return merged

        builder = build_for(settings.strategy)

        def strategy_dispatch(symbol, quotes_by_expiry, dte_by_expiry, settings, regime, underlying_price):
            return builder(symbol, quotes_by_expiry, dte_by_expiry, settings, regime, underlying_price)

        result = scan_from_quote_fetcher(
            settings, expiries, fetch_quotes, strategy_dispatch,
            regime=regime, underlying_price=underlying_price, progress=status_box.info,
        )
        apply_regime(result.candidates, regime)
        target_pct = target_pct_for(settings.strategy)
        if result.candidates:
            result.candidates = rank_candidates(result.candidates, settings, target_pct=target_pct)
        save_scan_history(settings, settings.strategy, result.candidates[:20])
        return result
    finally:
        client.disconnect()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    config = load_config()
    settings, connection, regime = sidebar_settings(settings_from_config(config), ibkr_config(config))
    collector = get_collector()

    st.title("Calendar Scanner")
    st.caption(
        "Scanner only. No order placement, no live trade modification. "
        f"Strategy: **{REGISTRY[settings.strategy]['label']}** | "
        f"Symbol: **{settings.symbol}** | "
        f"client_id: **{connection['client_id']}** (distinct from batman)"
    )

    # Regime banner
    st.info(f"**Regime:** {regime_summary_text(regime)} | Size mult: {size_mult_from_conviction(regime.conviction):.2f}x")

    with st.expander("Runtime diagnostics"):
        st.write(runtime_diagnostics())

    if "scan_result" not in st.session_state:
        st.session_state.scan_result = None

    status_box = st.empty()

    # Cache stats
    stats = quote_cache_stats(settings.symbol)
    collector_status = collector.status()
    with st.expander("Quote cache status", expanded=collector_status["running"]):
        st.write({
            "symbol": settings.symbol,
            "cached_quotes": stats["quote_count"],
            "cached_expiries": stats["expiry_count"],
            "right_breakdown": stats["right_breakdown"],
            "newest_update": stats["newest_update"],
            "underlying_price": stats["underlying_price"],
            "underlying_price_updated_at": stats["underlying_price_updated_at"],
            "collector": collector_status,
        })

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        connect_clicked = st.button("Connect to IBKR")
    with col2:
        refresh_cache_clicked = st.button("Refresh Quote Cache")
    with col3:
        run_clicked = st.button("Run Scan")
    with col4:
        mock_mode = st.checkbox("MOCK DATA", value=False)

    if connect_clicked:
        try:
            client = IBKRClient()
            client.connect(connection["host"], connection["port"], connection["client_id"])
            client.set_market_data_type(connection["market_data_type"])
            status_box.success(f"Connected to IBKR {connection['host']}:{connection['port']} as clientId {connection['client_id']}.")
            client.disconnect()
        except Exception as e:
            status_box.warning(f"Not connected: {e}")

    if refresh_cache_clicked:
        rights = rights_for(settings.strategy, settings)
        started = collector.start(settings, connection, rights=rights)
        if started:
            status_box.success(f"Quote cache refresh started (rights: {rights}).")
        else:
            status_box.warning("Quote cache refresh already running.")

    if run_clicked:
        try:
            if mock_mode:
                status_box.info("running MOCK scan")
                result = run_mock_scan(settings, regime)
            elif connection["use_cache"]:
                status_box.info("running cache scan")
                result = run_cache_scan(settings, regime, connection)
            else:
                result = run_live_scan(settings, connection, regime, status_box)
            st.session_state.scan_result = result
            status_box.success(f"Scan finished. {len(result.candidates)} candidates.")
        except Exception as e:
            status_box.error(f"Scan failed: {e}")

    result: ScanResult | None = st.session_state.scan_result
    if result is None:
        st.warning("Run a scan to see candidates. MOCK mode works without IBKR.")
        return

    if result.mock:
        st.warning("MOCK DATA. Do not treat as live market.")
    for w in result.warnings:
        st.warning(w)

    # Strategy-specific UI: heatmap for buddy_atm
    if result.strategy == "buddy_atm":
        with st.expander("ATM Calendar Heatmap (theta/debit by short × long DTE)", expanded=True):
            show_heatmap(result.extras)

    if not result.candidates:
        st.error("No candidates matched filters.")
        if result.rejection_reasons:
            st.write("Rejection reasons:", result.rejection_reasons)
        return

    # Workspace: candidate list | risk chart
    left, right = st.columns([0.40, 0.60], gap="large")
    label_by_rank = {c.rank: candidate_picker_label(c) for c in result.candidates}
    with left:
        st.subheader("Candidates")
        selected_rank = st.radio(
            "Ranked", options=[c.rank for c in result.candidates],
            format_func=lambda r: label_by_rank[r], label_visibility="collapsed",
        )
        with st.expander("Full table", expanded=False):
            st.dataframe(pd.DataFrame(candidate_rows(result.candidates)), use_container_width=True, hide_index=True)
        csv_text = candidates_to_csv(result.candidates)
        st.download_button(
            "Export CSV", data=csv_text,
            file_name=f"{result.strategy}_{settings.symbol.lower()}_candidates.csv",
            mime="text/csv",
        )

    selected = next(c for c in result.candidates if c.rank == selected_rank)
    with right:
        spot = connection.get("risk_chart_spot") or result.underlying_price or connection.get("manual_underlying_price") or 0.0
        spot = float(spot)
        st.markdown(
            f"**Selected:** Score {selected.custom_score:.4f} | "
            f"Debit {selected.net_debit:.2f} | "
            f"θ/$ {selected.theta_debit_ratio:.3f} | "
            f"Days→{int(target_pct_for(settings.strategy)*100)}% {selected.days_to_target_pct:.1f} | "
            f"Pos θ {selected.position_theta:.2f} | Pos vega {selected.position_vega:.2f}"
        )
        if selected.regime_flags:
            for flag in selected.regime_flags:
                st.warning(flag)
        if spot > 0:
            show_risk_chart(selected, spot, settings)
        else:
            st.info("Enter a risk-chart spot price in the sidebar.")

        with st.expander("Leg detail", expanded=True):
            st.dataframe(pd.DataFrame(leg_rows(selected)), use_container_width=True, hide_index=True)

        if selected.extras:
            with st.expander("Strategy extras"):
                # Avoid printing pandas pivot inside extras dict
                printable = {k: v for k, v in selected.extras.items() if not hasattr(v, "to_dict") or k != "heatmap_pivot"}
                st.write(printable)


if __name__ == "__main__":
    main()
