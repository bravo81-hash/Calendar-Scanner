import asyncio
import nest_asyncio
nest_asyncio.apply()

try:
    asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from ib_insync import IB, Index, Option
from datetime import datetime

st.set_page_config(layout="wide")
st.title("SPX Live Calendar Scanner - Version 1.5")
st.caption("ATM SPX/SPXW Calendar Scanner mit frei gewichtbarem Multi-Factor Score")

st.sidebar.header("IBKR Verbindung")
host = st.sidebar.text_input("Host", "127.0.0.1")
port = st.sidebar.number_input("Port", value=7496)
client_id = st.sidebar.number_input("Client ID", value=17)

st.sidebar.header("Scanner Einstellungen")
option_type = st.sidebar.selectbox("Optionstyp", ["Put", "Call"])
min_short_dte = st.sidebar.number_input("Min Short DTE", value=1, min_value=1, max_value=20)
max_long_dte = st.sidebar.number_input("Max Long DTE", value=20, min_value=2, max_value=20)
wait_time = st.sidebar.slider("Wartezeit für Marktdaten", 5, 30, 20)
market_data_type = st.sidebar.selectbox("IBKR Marktdaten-Typ", ["Live", "Frozen", "Delayed", "Delayed Frozen"])
spread_limit = st.sidebar.slider("Max Bid/Ask Spread %", 1, 100, 50)

st.sidebar.header("Score Gewichtung")
w_theta = st.sidebar.slider("Theta / Debit Gewicht", 0, 100, 50)
w_range = st.sidebar.slider("Range / Debit Gewicht", 0, 100, 30)
w_days = st.sidebar.slider("Days to 10% Gewicht", 0, 100, 20)
w_spread = st.sidebar.slider("Spread-Strafe Gewicht", 0, 100, 0)
w_vega = st.sidebar.slider("Vega/Debit Gewicht", 0, 100, 0)

heat_metric = st.sidebar.selectbox(
    "Heatmap Metrik",
    [
        "custom_score",
        "theta_debit_ratio",
        "range_debit_ratio",
        "theta_range_ratio",
        "days_to_10pct",
        "vega_debit_ratio",
        "avg_spread_pct"
    ]
)

def normalize_high_is_good(series):
    s = pd.to_numeric(series, errors="coerce")
    if s.dropna().empty:
        return pd.Series(0.0, index=series.index)
    mn = s.min()
    mx = s.max()
    if mx == mn:
        return pd.Series(1.0, index=series.index)
    return (s - mn) / (mx - mn)

def normalize_low_is_good(series):
    s = pd.to_numeric(series, errors="coerce")
    if s.dropna().empty:
        return pd.Series(0.0, index=series.index)
    mn = s.min()
    mx = s.max()
    if mx == mn:
        return pd.Series(1.0, index=series.index)
    return 1 - ((s - mn) / (mx - mn))

ib = IB()

try:
    ib.connect(host, int(port), clientId=int(client_id))
except Exception as e:
    st.error(f"IBKR Verbindung fehlgeschlagen: {e}")
    st.stop()

if market_data_type == "Live":
    ib.reqMarketDataType(1)
elif market_data_type == "Frozen":
    ib.reqMarketDataType(2)
elif market_data_type == "Delayed":
    ib.reqMarketDataType(3)
else:
    ib.reqMarketDataType(4)

spx = Index(symbol="SPX", exchange="CBOE", currency="USD")
ib.qualifyContracts(spx)

ticker = ib.reqMktData(spx)
ib.sleep(2)

spx_price = ticker.marketPrice()

if spx_price is None or np.isnan(spx_price):
    spx_price = ticker.close

if spx_price is None or np.isnan(spx_price):
    st.error("SPX Preis konnte nicht geladen werden.")
    ib.disconnect()
    st.stop()

atm_strike = round(spx_price / 5) * 5

chains = ib.reqSecDefOptParams(spx.symbol, "", spx.secType, spx.conId)

all_expirations = []

for c in chains:
    if c.tradingClass in ["SPX", "SPXW"]:
        for exp in c.expirations:
            all_expirations.append({
                "expiry": str(exp),
                "tradingClass": c.tradingClass
            })

exp_df = pd.DataFrame(all_expirations)

if exp_df.empty:
    st.error("Keine SPX/SPXW Expirations von IBKR geliefert.")
    ib.disconnect()
    st.stop()

exp_df["expiry"] = exp_df["expiry"].astype(str)
exp_df["expiry_date"] = pd.to_datetime(exp_df["expiry"], format="%Y%m%d", errors="coerce")
exp_df = exp_df.dropna(subset=["expiry_date"])

if exp_df.empty:
    st.error("IBKR hat Expirations geliefert, aber keine konnten als Datum gelesen werden.")
    ib.disconnect()
    st.stop()

today = pd.Timestamp(datetime.now().date())
exp_df["dte"] = (exp_df["expiry_date"] - today).dt.days

exp_df = exp_df[
    (exp_df["dte"] >= min_short_dte) &
    (exp_df["dte"] <= max_long_dte)
]

exp_df = exp_df.sort_values(["dte", "tradingClass"])
exp_df = exp_df.drop_duplicates(subset=["expiry", "tradingClass"])

if exp_df.empty:
    st.error("Keine Expirations im gewählten DTE-Bereich gefunden.")
    ib.disconnect()
    st.stop()

contracts = []
right = "P" if option_type == "Put" else "C"

for _, row in exp_df.iterrows():
    opt = Option(
        symbol="SPX",
        lastTradeDateOrContractMonth=row["expiry"],
        strike=float(atm_strike),
        right=right,
        exchange="SMART",
        currency="USD",
        tradingClass=row["tradingClass"]
    )
    contracts.append(opt)

qualified = ib.qualifyContracts(*contracts)

if not qualified:
    st.error("IBKR konnte keine Optionskontrakte qualifizieren.")
    ib.disconnect()
    st.stop()

tickers = ib.reqTickers(*qualified)
ib.sleep(wait_time)

rows = []

for t in tickers:
    greeks = t.modelGreeks

    bid = t.bid if t.bid is not None and t.bid > 0 else None
    ask = t.ask if t.ask is not None and t.ask > 0 else None

    mid = None
    if bid is not None and ask is not None:
        mid = (bid + ask) / 2

    expiry_raw = str(t.contract.lastTradeDateOrContractMonth)
    expiry_date = pd.to_datetime(expiry_raw, format="%Y%m%d", errors="coerce")

    if pd.isna(expiry_date):
        continue

    dte = (expiry_date - today).days

    rows.append({
        "expiry": expiry_raw,
        "dte": dte,
        "strike": t.contract.strike,
        "right": t.contract.right,
        "tradingClass": t.contract.tradingClass,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "iv": greeks.impliedVol if greeks else None,
        "delta": greeks.delta if greeks else None,
        "gamma": greeks.gamma if greeks else None,
        "theta": greeks.theta if greeks else None,
        "vega": greeks.vega if greeks else None,
        "model_price": greeks.optPrice if greeks else None
    })

opt_df = pd.DataFrame(rows)

c1, c2, c3, c4 = st.columns(4)
c1.metric("SPX", round(spx_price, 2))
c2.metric("ATM Strike", atm_strike)
c3.metric("Geladene Expirations", len(opt_df))
c4.metric("mit Greeks", opt_df["theta"].notna().sum() if not opt_df.empty else 0)

with st.expander("Geladene Expirations / Diagnose"):
    st.dataframe(exp_df, use_container_width=True)

st.subheader("Geladene ATM Optionen")
st.dataframe(opt_df, use_container_width=True)

if opt_df.empty:
    st.warning("Keine ATM Optionen geladen.")
    ib.disconnect()
    st.stop()

cal_rows = []

for _, short_row in opt_df.iterrows():
    for _, long_row in opt_df.iterrows():

        short_dte = short_row["dte"]
        long_dte = long_row["dte"]

        if long_dte <= short_dte:
            continue

        if short_row["mid"] is None or long_row["mid"] is None:
            continue

        if pd.isna(short_row["mid"]) or pd.isna(long_row["mid"]):
            continue

        debit = long_row["mid"] - short_row["mid"]

        if debit <= 0:
            continue

        if short_row["bid"] is None or short_row["ask"] is None:
            continue

        if long_row["bid"] is None or long_row["ask"] is None:
            continue

        short_spread = abs(short_row["ask"] - short_row["bid"]) / short_row["mid"] * 100
        long_spread = abs(long_row["ask"] - long_row["bid"]) / long_row["mid"] * 100
        avg_spread = (short_spread + long_spread) / 2

        if short_spread > spread_limit or long_spread > spread_limit:
            continue

        short_theta = short_row["theta"]
        long_theta = long_row["theta"]

        if short_theta is None or long_theta is None:
            continue

        if pd.isna(short_theta) or pd.isna(long_theta):
            continue

        net_theta = abs(short_theta) - abs(long_theta)

        if net_theta <= 0:
            continue

        short_vega = short_row["vega"] if not pd.isna(short_row["vega"]) else 0
        long_vega = long_row["vega"] if not pd.isna(long_row["vega"]) else 0
        net_vega = long_vega - short_vega

        approx_range = debit * 4

        theta_debit_ratio = net_theta / debit
        range_debit_ratio = approx_range / debit
        theta_range_ratio = net_theta / approx_range
        days_to_10pct = (debit * 0.10) / net_theta
        vega_debit_ratio = net_vega / debit if debit > 0 else 0

        cal_rows.append({
            "short_expiry": short_row["expiry"],
            "long_expiry": long_row["expiry"],
            "short_dte": short_dte,
            "long_dte": long_dte,
            "debit": debit,
            "net_theta": net_theta,
            "net_vega": net_vega,
            "approx_range": approx_range,
            "theta_debit_ratio": theta_debit_ratio,
            "range_debit_ratio": range_debit_ratio,
            "theta_range_ratio": theta_range_ratio,
            "days_to_10pct": days_to_10pct,
            "vega_debit_ratio": vega_debit_ratio,
            "short_spread_pct": short_spread,
            "long_spread_pct": long_spread,
            "avg_spread_pct": avg_spread
        })

cal_df = pd.DataFrame(cal_rows)

if cal_df.empty:
    st.warning(
        "Keine gültigen Calendar-Kombinationen gefunden. "
        "Häufige Ursachen: Greeks fehlen, Bid/Ask fehlt oder Spread-Filter zu streng."
    )
    ib.disconnect()
    st.stop()

cal_df["theta_score"] = normalize_high_is_good(cal_df["theta_debit_ratio"])
cal_df["range_score"] = normalize_high_is_good(cal_df["range_debit_ratio"])
cal_df["days_score"] = normalize_low_is_good(cal_df["days_to_10pct"])
cal_df["spread_score"] = normalize_low_is_good(cal_df["avg_spread_pct"])
cal_df["vega_score"] = normalize_high_is_good(cal_df["vega_debit_ratio"])

total_weight = w_theta + w_range + w_days + w_spread + w_vega

if total_weight == 0:
    cal_df["custom_score"] = 0
else:
    cal_df["custom_score"] = (
        cal_df["theta_score"] * w_theta +
        cal_df["range_score"] * w_range +
        cal_df["days_score"] * w_days +
        cal_df["spread_score"] * w_spread +
        cal_df["vega_score"] * w_vega
    ) / total_weight

round_cols = [
    "debit", "net_theta", "net_vega", "approx_range",
    "theta_debit_ratio", "range_debit_ratio", "theta_range_ratio",
    "days_to_10pct", "vega_debit_ratio",
    "short_spread_pct", "long_spread_pct", "avg_spread_pct",
    "theta_score", "range_score", "days_score", "spread_score", "vega_score",
    "custom_score"
]

for col in round_cols:
    if col in cal_df.columns:
        cal_df[col] = cal_df[col].round(6)

st.subheader("Score Gewichtung aktuell")

g1, g2, g3, g4, g5 = st.columns(5)
g1.metric("Theta/Debit", f"{w_theta}%")
g2.metric("Range/Debit", f"{w_range}%")
g3.metric("Days to 10%", f"{w_days}%")
g4.metric("Spread", f"{w_spread}%")
g5.metric("Vega/Debit", f"{w_vega}%")

st.subheader("Top 10 Ranking nach Custom Score")

top10 = cal_df.sort_values("custom_score", ascending=False).head(10)
st.dataframe(top10, use_container_width=True)

st.subheader("Heatmap")

ascending = True if heat_metric in ["days_to_10pct", "avg_spread_pct"] else False

piv = cal_df.pivot_table(
    index="short_dte",
    columns="long_dte",
    values=heat_metric,
    aggfunc="mean"
)

fig = px.imshow(
    piv,
    text_auto=".2f",
    aspect="auto",
    color_continuous_scale="Viridis",
    labels=dict(x="Long DTE", y="Short DTE", color=heat_metric)
)

st.plotly_chart(fig, use_container_width=True)

st.subheader("Top 10 nach ausgewählter Heatmap-Metrik")

metric_top10 = cal_df.sort_values(
    heat_metric,
    ascending=ascending
).head(10)

st.dataframe(metric_top10, use_container_width=True)

with st.expander("Alle Calendar-Kombinationen"):
    st.dataframe(cal_df, use_container_width=True)

ib.disconnect()