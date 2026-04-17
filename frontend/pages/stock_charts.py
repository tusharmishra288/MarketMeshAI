"""
StockPilot AI — Stock Charts.

Interactive price-history and technical-analysis page powered entirely by the
Analytics MCP Server (yfinance + ``ta`` library). Renders a candlestick chart
with optional SMA overlays, Bollinger Bands, and Golden/Death Cross markers,
plus side-by-side RSI and MACD panels computed directly from the OHLCV DataFrame.
An XGBoost ML model provides next-day direction predictions with SHAP feature
importance, and IsolationForest flags unusual price/volume events.

Key sections
------------
- Controls: Ticker, exchange, and period selectors with SMA/Bollinger toggle checkboxes
- Candlestick chart: OHLCV with optional SMA 20/50/200, Bollinger Bands, volume subplot
- Cross markers: Golden Cross / Death Cross annotations when SMA 50 and SMA 200 are both enabled
- RSI panel: 14-period RSI with overbought (70) / oversold (30) reference lines
- MACD panel: Histogram, MACD line, and signal line (12, 26, 9)
- Prediction widget: XGBoost direction (Up/Down), confidence gauge, SHAP feature importance chart
- CSV download: One-click export of the raw OHLCV DataFrame
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

from utils import ALL_EXCHANGES, EXCHANGE_DISPLAY_NAMES, EXCHANGE_SHORT_NAMES, exchange_sym, exchange_code, CURRENCY_SYMBOLS, fmt_price, search_result_to_exchange, fmt_source

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

PERIOD_OPTIONS = {
    "1 Month":  "1mo",
    "3 Months": "3mo",
    "6 Months": "6mo",
    "1 Year":   "1y",
    "5 Years":  "5y",
}

st.title("📈 Stock Charts")
st.markdown(
    "Price history, technical indicators, and directional prediction — "
    "powered by MCP Analytics Server"
)

with st.expander("📋 Operational Guide"):
    st.markdown(
        "**Step 1 — Load a chart**: Type a ticker symbol (e.g. `AAPL`, `RELIANCE`, `7203`) and select the correct exchange. "
        "The chart loads automatically — no button needed. Change the period (1M / 3M / 6M / 1Y / 5Y) to zoom in or out.\n\n"
        "**Step 2 — Read the candlestick chart**: Each bar (candle) represents one trading day. "
        "🟢 Green candle = price closed higher than it opened. 🔴 Red candle = price closed lower than it opened. "
        "The thin lines (wicks) above and below show the day's high and low.\n\n"
        "**Step 3 — Add overlays**: Use the checkboxes to toggle:\n"
        "- **SMA 20 / 50 / 200** — Trend lines. Price above SMA = uptrend; below = downtrend\n"
        "- **Bollinger Bands** — Show when a stock is unusually cheap or expensive relative to recent volatility\n\n"
        "**Step 4 — Read the indicator panels below the chart**:\n"
        "- **Volume bars** — tall bars = high trading activity (confirms price moves)\n"
        "- **RSI line** — above 70 = stock may be overbought (due for a pullback); below 30 = oversold (potential rebound)\n"
        "- **MACD histogram** — green bars = upward momentum building; red bars = downward momentum\n\n"
        "**Step 5 — Price Prediction section**: Shows an AI/ML direction forecast (Up/Down) with a confidence %. "
        "The Top Features bar chart explains which indicators most influenced the prediction. "
        "⚠️ Historical accuracy is ~52–56% — slightly better than a coin flip. For education only, not financial advice.\n\n"
        "**Step 6 — Anomaly Alerts**: Unusual price or volume events are flagged automatically. "
        "These may indicate earnings surprises, news events, or institutional trading.\n\n"
        "**Download CSV** — saves the raw daily price data (Open, High, Low, Close, Volume) to your computer."
    )

with st.expander("📖 Glossary — Key Terms"):
    st.markdown(
        "### 📊 Chart Basics\n\n"
        "**Candlestick Chart** — The standard way to visualise price data. Each 'candle' shows 4 prices for one period:\n"
        "- **Open** — price at the start of the period\n"
        "- **Close** — price at the end of the period\n"
        "- **High** — highest price reached during the period\n"
        "- **Low** — lowest price reached during the period\n"
        "Green candle = closed above open (price rose). Red candle = closed below open (price fell).\n\n"

        "**OHLCV** — Open, High, Low, Close, Volume. The 5 standard data points for any trading period.\n\n"

        "**Volume** — The number of shares traded during a session. "
        "High volume on an up day confirms buying strength. "
        "High volume on a down day confirms selling pressure. "
        "Low volume moves are less reliable — they may reverse quickly.\n\n"

        "**Support Level** — A price level where a stock has historically stopped falling and bounced back up. "
        "Think of it as a 'floor'. If price breaks below support on high volume, it's a bearish signal.\n\n"

        "**Resistance Level** — A price level where a stock has historically struggled to break above. "
        "Think of it as a 'ceiling'. If price breaks above resistance on high volume, it's a bullish signal.\n\n"

        "### 📉 Moving Averages\n\n"
        "**SMA (Simple Moving Average)** — The average closing price over the last N days. "
        "SMA 20 = average of last 20 days. SMA 200 = average of last 200 days. "
        "Price above SMA = uptrend. Price below SMA = downtrend. "
        "*Longer SMAs show bigger trends; shorter SMAs react faster to price changes.*\n\n"

        "**EMA (Exponential Moving Average)** — Like SMA but gives more weight to recent prices, "
        "so it reacts faster to new price moves. Used in MACD calculations.\n\n"

        "**Golden Cross** — When the 50-day SMA crosses *above* the 200-day SMA. "
        "Considered a long-term bullish signal — historically associated with sustained uptrends.\n\n"

        "**Death Cross** — When the 50-day SMA crosses *below* the 200-day SMA. "
        "Considered a long-term bearish signal — historically associated with extended downtrends.\n\n"

        "### ⚡ Momentum Indicators\n\n"
        "**RSI (Relative Strength Index)** — Measures how fast and strongly a stock has been moving. "
        "Scale: 0 to 100.\n"
        "- Above 70 = **Overbought** — stock has risen quickly and may be due for a pullback\n"
        "- Below 30 = **Oversold** — stock has fallen quickly and may be due for a rebound\n"
        "- 30–70 = normal range\n"
        "*RSI alone is not a buy/sell signal — always use with other indicators.*\n\n"

        "**MACD (Moving Average Convergence Divergence)** — Tracks the relationship between two EMAs (12-day and 26-day). "
        "Consists of:\n"
        "- **MACD Line** — the difference between 12-day EMA and 26-day EMA\n"
        "- **Signal Line** — 9-day EMA of the MACD line\n"
        "- **Histogram** — difference between MACD and Signal lines\n"
        "MACD line crossing *above* signal line = bullish crossover. "
        "MACD line crossing *below* signal line = bearish crossover. "
        "Growing green histogram = upward momentum accelerating.\n\n"

        "**Bollinger Bands** — A volatility envelope around a 20-day SMA, set at ±2 standard deviations. "
        "When bands are narrow = low volatility (often before a big move). "
        "When bands are wide = high volatility. "
        "Price touching the upper band = potentially overbought. "
        "Price touching the lower band = potentially oversold. "
        "Price outside the bands = unusual move worth watching.\n\n"

        "**ATR (Average True Range)** — Measures average daily price movement (volatility). "
        "High ATR = stock moves a lot each day (higher risk). Low ATR = more stable daily moves.\n\n"

        "### 🤖 AI Prediction\n\n"
        "**XGBoost Prediction** — A machine learning model trained on historical technical indicators "
        "(RSI, MACD, Bollinger Band position, volume, moving average ratios) to predict whether "
        "the stock price is more likely to be higher or lower tomorrow. "
        "Output: direction (Up/Down) + confidence percentage.\n\n"

        "**Confidence %** — How strongly the model leans toward its predicted direction. "
        "50% = uncertain (like a coin flip). 65%+ = moderate conviction. "
        "Historical accuracy is ~52–56% — only marginally better than random chance.\n\n"

        "**SHAP Values (Top Features)** — Shows which technical indicators had the most influence on this prediction. "
        "For example, 'RSI: 0.32' means the RSI reading contributed 32% of the model's decision. "
        "Helps you understand *why* the model made its prediction.\n\n"

        "**Walk-Forward Backtesting** — The model is trained on old data and tested on newer data it has never seen, "
        "simulating real-world performance. This gives a more honest accuracy estimate than testing on training data.\n\n"

        "### 🚨 Anomaly Detection\n\n"
        "**Anomaly** — A data point that is statistically unusual compared to recent history. "
        "In stock markets, anomalies include sudden large price gaps, extreme volume spikes, or RSI divergences "
        "that don't match normal trading patterns.\n\n"

        "**IsolationForest** — The machine learning algorithm used to detect anomalies. "
        "It identifies unusual price-change and volume combinations by learning what 'normal' looks like over 1 year of data. "
        "Points that are easy to isolate are labelled anomalies.\n\n"

        "**Volume Spike** — When trading volume is significantly higher than the recent average (typically >3× the norm). "
        "A volume spike often signals institutional buying/selling, earnings surprises, or breaking news — "
        "and tends to validate the direction of the accompanying price move.\n\n"

        "**Overnight Gap** — A significant difference between yesterday's closing price and today's opening price. "
        "Gaps >5% typically indicate major news (earnings, M&A, macro events) that occurred after market close. "
        "Gaps are sometimes 'filled' later as the market corrects back.\n\n"

        "**RSI Divergence** — When the stock price makes a new high but the RSI indicator does not (or vice versa). "
        "This discrepancy can signal a weakening trend before a reversal occurs.\n\n"

        "⚠️ **Important**: All predictions and technical indicators are educational tools only. "
        "Past patterns do not guarantee future results. This is not financial advice."
    )

with st.expander("🔌 Data Sources — MCP Servers"):
    st.markdown(
        "Stock Charts is powered entirely by the **Analytics MCP Server**:\n\n"
        "| MCP Server | Data Provider | What it provides |\n"
        "|---|---|---|\n"
        "| 📊 **Analytics MCP** | yfinance | OHLCV price history (1M · 3M · 6M · 1Y · 5Y) |\n"
        "| 📊 **Analytics MCP** | yfinance + `ta` library | RSI · MACD · Bollinger Bands · SMA/EMA |\n"
        "| 📊 **Analytics MCP** | XGBoost + SHAP | ML directional prediction (Up/Down) with feature importance |\n"
        "| 📊 **Analytics MCP** | IsolationForest | Anomaly detection — unusual price/volume events |\n\n"
        "_The Analytics MCP server uses exchange suffixes (e.g. `.L` for LSE, `.T` for TSE, `.NS` for NSE) "
        "to fetch global data from Yahoo Finance — covering 200,000+ securities worldwide._"
    )

# ── Initialise persistent widget state ────────────────────────────────────────
if "sc_ticker" not in st.session_state:
    # Pick up ticker from any other page the user navigated from
    st.session_state["sc_ticker"] = st.session_state.get("global_ticker", "AAPL")
if "sc_exchange" not in st.session_state:
    st.session_state["sc_exchange"] = st.session_state.get("global_exchange", "NASDAQ")

# ── Company name search expander (above ticker input) ─────────────────────────
with st.expander("🔍 Don't know the ticker? Search by company name"):
    st.caption("1️⃣ Type a company name below and click **Search**  →  2️⃣ Select from the list  →  3️⃣ Click **Use this ticker**")
    sq1, sq2 = st.columns([4, 1])
    sc_search_q = sq1.text_input("Company name", placeholder="e.g. Apple, Tesla, Reliance Industries", key="sc_search_q")
    sq2.markdown("<br>", unsafe_allow_html=True)
    if sq2.button("Search", key="sc_search_btn"):
        if sc_search_q.strip():
            try:
                sr = requests.get(f"{BACKEND_URL}/api/search", params={"query": sc_search_q, "limit": 30}, timeout=20)
                if sr.status_code == 200:
                    st.session_state["_sc_search_results"] = sr.json().get("results", [])
            except Exception:
                st.session_state["_sc_search_results"] = []
        else:
            st.warning("Please enter a company name first.")
    sc_results = st.session_state.get("_sc_search_results", [])
    if sc_results:
        sc_options  = [f"{m['name']} ({m['ticker']}) — {m['region']}" for m in sc_results]
        sc_chosen   = st.selectbox("Select company", sc_options, key="sc_search_sel")
        sc_sel_idx  = sc_options.index(sc_chosen)
        if st.button("✅ Use this ticker", key="sc_search_use"):
            sel = sc_results[sc_sel_idx]
            raw_ticker   = sel["ticker"]
            clean_ticker = raw_ticker.rsplit(".", 1)[0] if "." in raw_ticker else raw_ticker
            exch = search_result_to_exchange(raw_ticker, sel.get("region", ""), sel.get("currency", ""))
            st.session_state["sc_ticker"]   = clean_ticker
            st.session_state["sc_exchange"] = exch if exch in ALL_EXCHANGES else "NASDAQ"
            st.session_state.pop("_sc_search_results", None)
            st.rerun()
    elif sc_search_q and "_sc_search_results" in st.session_state and not sc_results:
        st.info("No results found. Try a different spelling.")

# ── Controls (uses persistent widget keys) ────────────────────────────────────
c1, c2, c3 = st.columns([3, 2, 2])
with c1:
    ticker_input = st.text_input("Ticker symbol", key="sc_ticker",
                                  placeholder="e.g. AAPL, VOD, TCS, 7203")
with c2:
    exchange = st.selectbox("Exchange", ALL_EXCHANGES, key="sc_exchange",
                            format_func=lambda x: EXCHANGE_SHORT_NAMES.get(x, x))
with c3:
    period_label = st.selectbox("Period", list(PERIOD_OPTIONS.keys()), index=3)

# ── Overlay toggles ───────────────────────────────────────────────────────────
oc1, oc2, oc3, oc4, oc5 = st.columns(5)
show_sma20  = oc1.checkbox("SMA 20",  value=True)
show_sma50  = oc2.checkbox("SMA 50",  value=True)
show_sma200 = oc3.checkbox("SMA 200", value=False)
show_bb     = oc4.checkbox("Bollinger Bands", value=False)
show_volume = oc5.checkbox("Volume", value=True)

if not ticker_input.strip():
    st.info("Enter a ticker symbol above to display charts.")
    st.stop()

ticker = ticker_input.strip().upper()
period = PERIOD_OPTIONS[period_label]
sym    = exchange_sym(exchange)
code   = exchange_code(exchange)

# Persist globally so Company Explorer and Home pick it up when navigating
st.session_state["global_ticker"]   = ticker
st.session_state["global_exchange"] = exchange

# ── Fetch data (cached in session_state so overlay toggles don't re-fetch) ────
_cache_key = f"chart_data:{ticker}:{exchange}:{period}"
_cached     = st.session_state.get(_cache_key)

if _cached is None:
    with st.spinner(f"Loading chart data for {ticker}…"):
        hist_data, tech_data, pred_data = None, None, None

        try:
            r = requests.get(
                f"{BACKEND_URL}/api/history/{ticker}",
                params={"exchange": exchange, "period": period},
                timeout=30,
            )
            if r.status_code == 200:
                hist_data = r.json()
            elif r.status_code == 404:
                st.warning(f"No historical data found for **{ticker}** on **{exchange}**. Try a different exchange or period.")
                st.stop()
            else:
                st.warning(f"History unavailable (HTTP {r.status_code}). The analytics server may be starting up — please retry.")
                st.stop()
        except Exception as e:
            st.error(f"Failed to fetch price history: {e}")
            st.stop()

        try:
            r = requests.get(
                f"{BACKEND_URL}/api/technicals/{ticker}",
                params={"exchange": exchange, "period": period},
                timeout=30,
            )
            if r.status_code == 200:
                tech_data = r.json()
        except Exception:
            pass

        try:
            r = requests.get(
                f"{BACKEND_URL}/api/predict/{ticker}",
                params={"exchange": exchange},
                timeout=60,
            )
            if r.status_code == 200:
                pred_data = r.json()
        except Exception:
            pass

        st.session_state[_cache_key] = (hist_data, tech_data, pred_data)
        # Evict old cache keys for the same ticker (different periods)
        for k in list(st.session_state.keys()):
            if k.startswith("chart_data:") and k != _cache_key:
                del st.session_state[k]
                break
else:
    hist_data, tech_data, pred_data = _cached

# ── Build DataFrame ───────────────────────────────────────────────────────────
if not hist_data or not hist_data.get("candles"):
    st.warning("No candle data available for this ticker/period combination.")
    st.stop()

candles = hist_data["candles"]
df = pd.DataFrame(candles)
df["date"] = pd.to_datetime(df["date"])
df = df.set_index("date").sort_index()

resp_currency = hist_data.get("currency")
if resp_currency and resp_currency in CURRENCY_SYMBOLS:
    sym  = CURRENCY_SYMBOLS[resp_currency]
    code = resp_currency

company_name = hist_data.get("company_name", ticker)
header_label = f"{company_name} ({ticker})" if company_name and company_name != ticker else ticker
st.markdown(f"### {header_label} · {exchange} ({code}) · {period_label}")
st.caption(f"{len(df)} trading sessions · Source: {fmt_source(hist_data.get('source', 'yfinance'))}")

# ── Compute all indicators from OHLCV DataFrame (frontend — full time series) ─
# SMA overlays
df["sma_20"]  = df["close"].rolling(20).mean()
df["sma_50"]  = df["close"].rolling(50).mean()
df["sma_200"] = df["close"].rolling(200).mean()

# Bollinger Bands (20-day, ±2σ) — reuse sma_20 as the middle band
_bb_std        = df["close"].rolling(20).std()
df["bb_upper"] = df["sma_20"] + 2 * _bb_std
df["bb_lower"] = df["sma_20"] - 2 * _bb_std

# RSI(14)
_delta        = df["close"].diff()
_gain         = _delta.clip(lower=0).rolling(14).mean()
_loss         = (-_delta.clip(upper=0)).rolling(14).mean()
df["rsi"]     = 100 - 100 / (1 + _gain / _loss.replace(0, float("nan")))

# MACD(12, 26, 9)
_ema12         = df["close"].ewm(span=12, adjust=False).mean()
_ema26         = df["close"].ewm(span=26, adjust=False).mean()
df["macd"]     = _ema12 - _ema26
df["macd_sig"] = df["macd"].ewm(span=9, adjust=False).mean()
df["macd_h"]   = df["macd"] - df["macd_sig"]

# ── Candlestick chart ─────────────────────────────────────────────────────────
# Pre-check volume availability so subplot layout is correct from the start.
_vol_available = (
    show_volume
    and "volume" in df.columns
    and df["volume"].notna().any()
    and df["volume"].sum() > 0
)
n_rows      = 2 if _vol_available else 1
row_heights = [0.72, 0.28] if _vol_available else [1.0]

fig = make_subplots(
    rows=n_rows, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.08,
    row_heights=row_heights,
)

# Candlestick bars
fig.add_trace(
    go.Candlestick(
        x=df.index,
        open=df["open"], high=df["high"],
        low=df["low"],   close=df["close"],
        name="Price",
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
        whiskerwidth=0.5,
    ),
    row=1, col=1,
)

# ── SMA overlays ──────────────────────────────────────────────────────────────
if show_sma20:
    sma20_clean = df["sma_20"].dropna()
    fig.add_trace(
        go.Scatter(x=sma20_clean.index, y=sma20_clean,
                   mode="lines", name="SMA 20",
                   line=dict(color="#FF9800", width=1.8)),
        row=1, col=1,
    )
if show_sma50:
    sma50_clean = df["sma_50"].dropna()
    fig.add_trace(
        go.Scatter(x=sma50_clean.index, y=sma50_clean,
                   mode="lines", name="SMA 50",
                   line=dict(color="#2196F3", width=1.8)),
        row=1, col=1,
    )
if show_sma200:
    sma200_clean = df["sma_200"].dropna()
    fig.add_trace(
        go.Scatter(x=sma200_clean.index, y=sma200_clean,
                   mode="lines", name="SMA 200",
                   line=dict(color="#CE93D8", width=2.2)),
        row=1, col=1,
    )

# ── Golden Cross / Death Cross markers ────────────────────────────────────────
# Detect SMA 50 × SMA 200 crossovers and annotate them on the chart.
# Only shown when both SMA 50 and SMA 200 overlays are enabled.
if show_sma50 and show_sma200 and "sma_50" in df.columns and "sma_200" in df.columns:
    _cross_df = df[["sma_50", "sma_200", "close", "high", "low"]].dropna()
    if len(_cross_df) >= 2:
        _diff      = _cross_df["sma_50"] - _cross_df["sma_200"]
        _prev_diff = _diff.shift(1).dropna()
        _curr_diff = _diff.iloc[1:]

        # Golden cross: SMA50 crosses above SMA200 (diff negative → positive)
        _golden_dates = _curr_diff.index[(_prev_diff.values < 0) & (_curr_diff.values >= 0)]
        # Death cross: SMA50 crosses below SMA200 (diff positive → negative)
        _death_dates  = _curr_diff.index[(_prev_diff.values > 0) & (_curr_diff.values <= 0)]

        if len(_golden_dates) > 0:
            _gc_y = _cross_df.loc[_golden_dates, "high"] * 1.012
            fig.add_trace(
                go.Scatter(
                    x=list(_golden_dates),
                    y=list(_gc_y),
                    mode="markers+text",
                    marker=dict(symbol="triangle-up", size=14,
                                color="gold", line=dict(color="#333", width=1)),
                    text=["☀️ Golden Cross"] * len(_golden_dates),
                    textposition="top center",
                    textfont=dict(color="gold", size=11),
                    name="Golden Cross",
                    hovertemplate="<b>☀️ Golden Cross</b><br>SMA50 crossed above SMA200<br>%{x}<extra></extra>",
                ),
                row=1, col=1,
            )

        if len(_death_dates) > 0:
            _dc_y = _cross_df.loc[_death_dates, "low"] * 0.988
            fig.add_trace(
                go.Scatter(
                    x=list(_death_dates),
                    y=list(_dc_y),
                    mode="markers+text",
                    marker=dict(symbol="triangle-down", size=14,
                                color="#ef5350", line=dict(color="#333", width=1)),
                    text=["💀 Death Cross"] * len(_death_dates),
                    textposition="bottom center",
                    textfont=dict(color="#ef5350", size=11),
                    name="Death Cross",
                    hovertemplate="<b>💀 Death Cross</b><br>SMA50 crossed below SMA200<br>%{x}<extra></extra>",
                ),
                row=1, col=1,
            )

# ── Bollinger Bands ───────────────────────────────────────────────────────────
if show_bb:
    bb_valid = df[["bb_upper", "bb_lower"]].dropna()
    if not bb_valid.empty:
        fig.add_trace(
            go.Scatter(x=bb_valid.index, y=bb_valid["bb_upper"],
                       mode="lines", name="BB Upper",
                       line=dict(color="rgba(130,130,255,0.8)", width=1.2, dash="dot")),
            row=1, col=1,
        )
        # Lower band fills to upper band — creates the shaded Bollinger region
        fig.add_trace(
            go.Scatter(x=bb_valid.index, y=bb_valid["bb_lower"],
                       mode="lines", name="BB Lower",
                       line=dict(color="rgba(130,130,255,0.8)", width=1.2, dash="dot"),
                       fill="tonexty",
                       fillcolor="rgba(130,130,255,0.07)"),
            row=1, col=1,
        )

# ── Volume bars ───────────────────────────────────────────────────────────────
if _vol_available:
    bar_colors = [
        "#26a69a" if c >= o else "#ef5350"
        for c, o in zip(df["close"], df["open"])
    ]
    fig.add_trace(
        go.Bar(x=df.index, y=df["volume"],
               name="Volume", marker_color=bar_colors,
               showlegend=False, opacity=0.75),
        row=2, col=1,
    )

# ── Layout ────────────────────────────────────────────────────────────────────
_grid = dict(gridcolor="rgba(255,255,255,0.07)", showgrid=True)

fig.update_layout(
    height=680 if _vol_available else 480,
    xaxis_rangeslider_visible=False,
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(15,23,42,0.65)",
    font=dict(color="#e2e8f0", size=11),
    margin=dict(t=30, b=20, l=70, r=20),
    legend=dict(
        orientation="h", yanchor="bottom", y=1.01,
        xanchor="right", x=1,
        bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
    ),
)

# Apply grid + axis labels to every subplot row
fig.update_xaxes(**_grid)
fig.update_yaxes(**_grid)
fig.update_yaxes(title_text=f"Price ({code})", row=1, col=1,
                 title_font=dict(size=11), tickfont=dict(size=10))
if _vol_available:
    fig.update_yaxes(title_text="Volume", row=2, col=1,
                     title_font=dict(size=11), tickfont=dict(size=10))

# Unique key forces Plotly to fully re-mount when any toggle changes
_chart_key = f"mc_{int(show_sma20)}{int(show_sma50)}{int(show_sma200)}{int(show_bb)}{int(_vol_available)}"
st.plotly_chart(fig, use_container_width=True, key=_chart_key)

# ── RSI + MACD sub-panels (computed from candle data) ────────────────────────
tc1, tc2 = st.columns(2)

with tc1:
    st.markdown("#### RSI (14)")
    rsi_clean = df["rsi"].dropna()
    if not rsi_clean.empty:
        fig_rsi = go.Figure()
        # Shaded overbought / oversold bands
        fig_rsi.add_hrect(y0=70, y1=100,
                          fillcolor="rgba(239,83,80,0.10)", line_width=0)
        fig_rsi.add_hrect(y0=0,  y1=30,
                          fillcolor="rgba(38,166,154,0.10)", line_width=0)
        fig_rsi.add_trace(go.Scatter(
            x=rsi_clean.index, y=rsi_clean,
            mode="lines", name="RSI",
            line=dict(color="#E91E63", width=2),
        ))
        fig_rsi.add_hline(y=70, line_dash="dash",
                          line_color="rgba(239,83,80,0.7)", line_width=1,
                          annotation_text="Overbought",
                          annotation_font_color="#ef5350", annotation_font_size=10)
        fig_rsi.add_hline(y=30, line_dash="dash",
                          line_color="rgba(38,166,154,0.7)", line_width=1,
                          annotation_text="Oversold",
                          annotation_font_color="#26a69a", annotation_font_size=10)
        fig_rsi.update_layout(
            height=220,
            margin=dict(t=10, b=10, l=50, r=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(15,23,42,0.65)",
            font=dict(color="#e2e8f0", size=11),
            yaxis=dict(range=[0, 100], **_grid),
            xaxis=_grid,
            showlegend=False,
        )
        st.plotly_chart(fig_rsi, use_container_width=True)
        latest_rsi = float(rsi_clean.iloc[-1])
        if latest_rsi > 70:
            st.warning(f"RSI {latest_rsi:.1f} — **Overbought** (may pull back)")
        elif latest_rsi < 30:
            st.success(f"RSI {latest_rsi:.1f} — **Oversold** (potential rebound)")
        else:
            st.info(f"RSI {latest_rsi:.1f} — Neutral zone")
    else:
        st.caption("RSI unavailable (insufficient history)")

with tc2:
    st.markdown("#### MACD (12, 26, 9)")
    macd_clean = df[["macd", "macd_sig", "macd_h"]].dropna()
    if not macd_clean.empty:
        bar_c = ["#26a69a" if v >= 0 else "#ef5350"
                 for v in macd_clean["macd_h"]]
        fig_macd = go.Figure()
        fig_macd.add_trace(go.Bar(
            x=macd_clean.index, y=macd_clean["macd_h"],
            marker_color=bar_c, name="Histogram",
            showlegend=False, opacity=0.85,
        ))
        fig_macd.add_trace(go.Scatter(
            x=macd_clean.index, y=macd_clean["macd"],
            mode="lines", name="MACD",
            line=dict(color="#2196F3", width=2),
        ))
        fig_macd.add_trace(go.Scatter(
            x=macd_clean.index, y=macd_clean["macd_sig"],
            mode="lines", name="Signal",
            line=dict(color="#FF9800", width=2),
        ))
        fig_macd.add_hline(y=0,
                           line_color="rgba(255,255,255,0.25)", line_width=0.8)
        fig_macd.update_layout(
            height=220,
            margin=dict(t=10, b=10, l=50, r=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(15,23,42,0.65)",
            font=dict(color="#e2e8f0", size=11),
            legend=dict(orientation="h", y=1.18, font=dict(size=10),
                        bgcolor="rgba(0,0,0,0)"),
            yaxis=_grid,
            xaxis=_grid,
        )
        st.plotly_chart(fig_macd, use_container_width=True)
    else:
        st.caption("MACD unavailable (insufficient history)")

# ── Prediction widget ─────────────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 🤖 Price Direction Prediction")
st.caption(
    "XGBoost model trained on technical indicators with walk-forward backtesting. "
    "**Not financial advice.**"
)

if pred_data and not pred_data.get("error"):
    direction    = pred_data.get("direction", "unknown")
    confidence   = pred_data.get("confidence", 0.5)
    backtest_acc = pred_data.get("backtest_accuracy", 0)
    horizon      = pred_data.get("horizon_days", 1)
    top_features = pred_data.get("top_features", [])

    pc1, pc2, pc3 = st.columns(3)
    arrow = "⬆" if direction == "up" else "⬇"
    pc1.metric(
        "Predicted Direction",
        f"{arrow} {direction.upper()}",
        f"{confidence*100:.0f}% confidence",
    )
    pc2.metric(
        "Backtest Accuracy",
        f"{backtest_acc*100:.1f}%" if backtest_acc else "N/A",
        "Walk-forward validated",
    )
    pc3.metric("Forecast Horizon", f"{horizon} day{'s' if horizon != 1 else ''}")

    bar_color = "#26a69a" if direction == "up" else "#ef5350"
    fig_conf = go.Figure(go.Bar(
        x=[confidence * 100], y=["Confidence"],
        orientation="h",
        marker_color=bar_color,
        text=[f"{confidence*100:.1f}%"],
        textposition="inside",
    ))
    fig_conf.update_layout(
        height=90, margin=dict(t=5, b=5, l=5, r=80),
        xaxis=dict(range=[0, 100], title="Confidence %"),
        showlegend=False,
    )
    st.plotly_chart(fig_conf, use_container_width=True)

    # Plain-English model interpretation
    conf_pct   = confidence * 100
    dir_word   = "rise" if direction == "up" else "fall"
    dir_color  = "#22c55e" if direction == "up" else "#ef4444"
    if conf_pct >= 63:
        strength = "moderate conviction"
    elif conf_pct >= 57:
        strength = "slight lean"
    else:
        strength = "marginal lean (near coin-flip)"

    top2 = [f["feature"].replace("_", " ").upper() for f in top_features[:2]] if top_features else []
    driver_str = f" Key signals driving this: **{', '.join(top2)}**." if top2 else ""

    st.markdown(
        f'<div style="background:rgba(255,255,255,0.05);border-left:3px solid {dir_color};'
        f'padding:12px 16px;border-radius:0 8px 8px 0;margin:8px 0;font-size:0.92rem;color:#e2e8f0">'
        f'<b>Model says:</b> The price is likely to <b style="color:{dir_color}">{dir_word}</b> '
        f'over the next {horizon} day(s) — <b>{conf_pct:.0f}% confidence</b> ({strength}).{driver_str} '
        f'Walk-forward accuracy: <b>{backtest_acc*100:.1f}%</b> — slightly above random chance.</div>',
        unsafe_allow_html=True,
    )

    if top_features:
        with st.expander("📊 Top predictive features (SHAP importance)"):
            feat_df = pd.DataFrame(top_features).rename(
                columns={"feature": "Feature", "importance": "Importance"})
            feat_df["Feature"] = feat_df["Feature"].str.replace("_", " ").str.upper()
            feat_df = feat_df.sort_values("Importance")
            fig_feat = px.bar(
                feat_df, x="Importance", y="Feature", orientation="h",
                color="Importance", color_continuous_scale="Blues",
                text="Importance",
            )
            fig_feat.update_traces(texttemplate="%{text:.3f}", textposition="outside",
                                   marker_line_width=0)
            fig_feat.update_layout(
                height=max(200, len(feat_df) * 32),
                showlegend=False,
                coloraxis_showscale=False,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e2e8f0", size=11),
                margin=dict(t=10, b=10, l=10, r=70),
                xaxis=dict(gridcolor="rgba(255,255,255,0.08)"),
                yaxis=dict(gridcolor="rgba(0,0,0,0)"),
            )
            st.plotly_chart(fig_feat, use_container_width=True, key="feat_chart")

    st.warning(
        f"⚠️ **Disclaimer**: Statistical model for educational purposes only. "
        f"Historical accuracy **{backtest_acc*100:.1f}%** — near chance level (~50%). "
        "Do not make investment decisions based on this output."
    )
else:
    reason = (pred_data or {}).get("error", "requires at least 1 year of history for model training")
    st.info(f"Prediction unavailable — {reason}")

# ── CSV Download ──────────────────────────────────────────────────────────────
st.markdown("---")
csv_data = df.reset_index().to_csv(index=False)
st.download_button(
    label="📥 Download OHLCV CSV",
    data=csv_data,
    file_name=f"{ticker}_{exchange}_{period}.csv",
    mime="text/csv",
)
st.caption(f"Data source: {fmt_source(hist_data.get('source', 'yfinance'))} · Prices in {code} · 15-min delay")
