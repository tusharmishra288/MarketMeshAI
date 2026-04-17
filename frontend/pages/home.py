"""
StockPilot AI — Market Dashboard.

The main landing page of the application. Displays a real-time market status
strip across all 4 global regions, a quick stock quote lookup with 30-second
auto-refresh, and a summary of the platform's capabilities. Page config and the
shared sidebar are handled by app.py; this module only renders main-area content.

Key sections
------------
- Market status strip: Timezone-aware open/closed badges for Americas, Europe, Asia-Pacific, MENA
- Quick Stock Lookup: Ticker + exchange search box with ``@st.fragment`` auto-refresh quote card
- Platform capabilities: Feature highlights grid (global coverage, data sources, AI, MCP architecture)
- Navigation guide: Summary table linking to the other four pages
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import requests
from utils import (
    ALL_EXCHANGES, EXCHANGE_CURRENCY, EXCHANGE_DISPLAY_NAMES, EXCHANGE_SHORT_NAMES,
    CURRENCY_SYMBOLS, fmt_price, market_open, search_result_to_exchange, fmt_source,
)

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

# ── Page header ───────────────────────────────────────────────────────────────
st.title("🌍 Global Market Intelligence Dashboard")
st.markdown("### Real-time insights across **31 exchanges** in **26 countries**")

st.info(
    "📊 **Data Freshness**: Intraday quotes delayed 15 minutes  |  "
    "Fundamentals enriched with Alpha Vantage  |  News via Marketaux  |  "
    "AI analysis via Groq + Gemini"
)

with st.expander("📋 Operational Guide"):
    st.markdown(
        "### How to use the Home Dashboard\n\n"
        "**Step 1 — Check market status** at the top of the page. "
        "Four regional badges show whether each major market zone is currently open or closed:\n"
        "- 🟢 **Open** — the exchange is live and trading right now\n"
        "- 🔴 **Closed** — after hours, weekend, or public holiday; prices reflect the last close\n"
        "- Americas (NYSE/NASDAQ): Mon–Fri 9:30 AM–4:00 PM ET\n"
        "- Europe (LSE/XETRA/EPA): Mon–Fri 8:00–16:30 local time\n"
        "- Asia-Pacific (TSE/HKEX/NSE): Mon–Fri 9:00–15:30 local time\n"
        "- MENA (TADAWUL/DFM): Sun–Thu 10:00–15:00 local time\n\n"
        "**Step 2 — Quick Stock Lookup**: Type a ticker symbol in the search box (e.g. `AAPL` for Apple, "
        "`VOD` for Vodafone, `7203` for Toyota, `TCS` for Tata Consultancy) and select the correct exchange. "
        "The quote card updates instantly with live price, change %, day range, volume, and data source.\n\n"
        "**Step 3 — Don't know the ticker?** Click **🔍 Search by company name** — type the company's name "
        "(e.g. 'Reliance', 'Samsung', 'LVMH') and the search will return matching tickers with their region. "
        "Select one and click **Use this ticker** to auto-fill the lookup box.\n\n"
        "**Step 4 — Read the quote card**:\n"
        "- **Price** — last traded price in the exchange's local currency\n"
        "- **Change / Change %** — today's movement vs yesterday's closing price\n"
        "- **Day High / Day Low** — intraday price range for the current session\n"
        "- **Volume** — total shares traded today\n"
        "- **52-Week Range** — lowest and highest price over the past 12 months\n"
        "- **Market Cap** — total market value (price × shares outstanding)\n"
        "- **Source** — which data provider served the quote (Finnhub / yfinance)\n\n"
        "**Step 5 — Explore deeper pages** using the sidebar:\n"
        "- 🌍 **Global Overview** — all 31 exchanges, correlation heatmap, sector performance\n"
        "- 🏢 **Company Explorer** — fundamentals, AI analysis, news, peers, factor radar\n"
        "- 📈 **Stock Charts** — candlestick, SMA, RSI, MACD, Bollinger Bands, ML prediction\n"
        "- 🌐 **Macro Dashboard** — yield curve, inflation, Fed rate, GDP growth, AI narrative\n\n"
        "**Watchlist (Sidebar ⭐)** — Save tickers you track regularly. "
        "Click 📈 next to any saved ticker to jump straight to its full Company Explorer page. "
        "Click ✕ to remove. Watchlist persists for the current session."
    )

with st.expander("📖 Glossary — Key Terms"):
    st.markdown(
        "### 🔤 Stock Identification\n\n"
        "**Ticker Symbol** — A short code that uniquely identifies a listed stock on a specific exchange. "
        "Examples: `AAPL` = Apple (NASDAQ), `VOD` = Vodafone (LSE), `7203` = Toyota (TSE), "
        "`TCS` = Tata Consultancy (NSE), `005930` = Samsung (KRX). "
        "The same company may have *different* ticker symbols on different exchanges "
        "(e.g. Vodafone is `VOD` on LSE but `VOD` also on NASDAQ as an ADR).\n\n"

        "**Exchange** — A regulated marketplace where buyers and sellers trade shares. "
        "Each exchange has its own trading hours, listing currency, regulatory body, and listed companies. "
        "This app covers 31 exchanges across 26 countries: "
        "NASDAQ, NYSE, AMEX, TSX, B3, BMV (Americas) · LSE, XETRA, EPA, AMS, SWX, BIT, MCE, OSL, HEL (Europe) · "
        "TSE, HKEX, SSE, SZSE, NSE, BSE, ASX, SGX, KRX, TWSE (Asia-Pacific) · "
        "TADAWUL, DFM, ADX, TASE, EGX, DSM (MENA).\n\n"

        "**ADR (American Depositary Receipt)** — A certificate that represents shares of a foreign company "
        "traded on a US exchange. Allows US investors to buy foreign stocks in USD without using foreign exchanges. "
        "Example: BABA (Alibaba on NYSE) is an ADR for a Chinese company.\n\n"

        "### 📊 Price & Quote Data\n\n"
        "**Price** — The last traded price of one share in the exchange's local currency "
        "($ USD for US, £ GBP for UK, ₹ INR for India, ¥ JPY for Japan, etc.).\n\n"

        "**Change / Change %** — How much the price has moved compared to yesterday's official closing price. "
        "🟢 Green = stock rose today (e.g. +2.3%). 🔴 Red = stock fell today (e.g. −1.5%).\n\n"

        "**Day High / Day Low** — The highest and lowest prices reached during the current trading session. "
        "Price near the day high → buying momentum is strong. Price near day low → selling pressure.\n\n"

        "**52-Week High / Low** — The highest and lowest price traded in the past 52 weeks. "
        "Price near 52-week high = strong recent trend. Price near 52-week low = recent weakness "
        "(could be a value opportunity or a continuing decline — requires further research).\n\n"

        "**Volume** — Total number of shares traded during the session. "
        "High volume = strong investor participation. Low volume = less conviction behind a price move. "
        "Unusually high volume often accompanies earnings releases, news, or institutional buying/selling.\n\n"

        "**Market Cap (Market Capitalisation)** — Share price × total shares outstanding. "
        "Represents the total market value of the company. "
        "Mega-cap: >$200B · Large-cap: $10B–$200B · Mid-cap: $2B–$10B · "
        "Small-cap: $300M–$2B · Micro-cap: <$300M.\n\n"

        "**Bid / Ask** — The bid is the highest price a buyer is willing to pay; "
        "the ask is the lowest price a seller will accept. The difference is the **spread** — "
        "tight spreads indicate a liquid, actively traded stock.\n\n"

        "### ⏰ Market Timing & Data Freshness\n\n"
        "**Market Open / Closed** — Exchanges only allow trading during specific hours in their local timezone. "
        "Outside trading hours, the quote shown is the last known closing price (no live movement).\n\n"

        "**Real-Time Quote** — Live price updated as trades happen (sourced from Finnhub, 15-min delayed for free tier). "
        "Available during market hours for US and major international exchanges.\n\n"

        "**EOD (End-of-Day) Quote** — The official closing price from the most recent completed session, "
        "sourced from yfinance. Used for non-US markets and after-hours lookups.\n\n"

        "**Pre-Market / After-Hours** — Trading activity outside regular market hours. "
        "Prices can be volatile with lower volume. This app shows regular-session data only.\n\n"

        "**Delayed Quote** — Intraday prices from some providers are delayed by 15 minutes "
        "(regulatory requirement). The Source field on the quote card shows the data provider.\n\n"

        "### 📡 Data Sources\n\n"
        "**Finnhub** — Real-time and intraday quote data for US and major global exchanges. "
        "Used as the primary live quote source.\n\n"
        "**yfinance (Yahoo Finance)** — Historical OHLCV data, fundamentals, and EOD quotes for "
        "200,000+ global securities. Used as the primary history source.\n\n"
        "**Alpha Vantage** — Company fundamentals (P/E, P/B, ROE, margins), earnings, and global symbol search. "
        "Free tier: 25 requests/day.\n\n"
        "**Marketaux** — News articles with sentiment scores for global stocks. "
        "Free tier: 100 requests/day.\n\n"
        "**FRED (Federal Reserve Economic Data)** — Official US macroeconomic time series "
        "(rates, inflation, GDP) from the St. Louis Federal Reserve Bank."
    )

with st.expander("🔌 Data Sources — MCP Servers"):
    st.markdown(
        "This page is powered by **4 regional MCP servers**, each routing data requests "
        "to the most appropriate provider for that exchange:\n\n"
        "| MCP Server | Data Provider | Exchanges Covered |\n"
        "|---|---|---|\n"
        "| 🌎 **Americas MCP** | Finnhub (real-time) | NASDAQ · NYSE · AMEX · TSX · B3 · BMV |\n"
        "| 🌍 **Europe MCP** | yfinance (EOD) | LSE · XETRA · EPA · AMS · SWX · BIT · MCE · OSL · HEL |\n"
        "| 🌏 **Asia-Pacific MCP** | yfinance (EOD) | TSE · HKEX · SSE · SZSE · NSE · BSE · ASX · SGX · KRX · TWSE |\n"
        "| 🌐 **MENA MCP** | yfinance (EOD) | TADAWUL · DFM · ADX · TASE · EGX · DSM |\n\n"
        "_Quotes from Americas MCP are delayed ~15 min (Finnhub free tier). "
        "All other regions return end-of-day closing prices via yfinance._"
    )

# ── Market status strip (timezone-aware) ─────────────────────────────────────
mc1, mc2, mc3, mc4 = st.columns(4)
for col, region in zip(
    [mc1, mc2, mc3, mc4],
    ["Americas", "Europe", "Asia-Pacific", "MENA"],
):
    icons = {"Americas": "🌎", "Europe": "🌍", "Asia-Pacific": "🌏", "MENA": "🌐"}
    is_open = market_open(region)
    color   = "#22c55e" if is_open else "#ef4444"
    label   = "Open" if is_open else "Closed"
    col.markdown(
        f"""<div style="border:1px solid rgba(255,255,255,0.1);border-radius:8px;
                        padding:14px 18px;text-align:center;
                        background:rgba(255,255,255,0.04)">
              <div style="font-size:0.75rem;color:#94a3b8;font-weight:600;
                          text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px">
                {icons[region]} {region}
              </div>
              <div style="font-size:1.25rem;font-weight:700;color:{color}">
                {'🟢' if is_open else '🔴'} {label}
              </div>
            </div>""",
        unsafe_allow_html=True,
    )

st.markdown("---")

# ── Quick Stock Lookup with auto-refresh ─────────────────────────────────────
st.markdown("### 🔍 Quick Stock Lookup")
st.caption("Full details, news & AI analysis → use **Company Explorer** in the sidebar")

# ── Initialise persistent widget state ────────────────────────────────────────
if "home_ticker" not in st.session_state:
    st.session_state["home_ticker"] = st.session_state.get("global_ticker", "AAPL")
if "home_exchange" not in st.session_state:
    st.session_state["home_exchange"] = st.session_state.get("global_exchange", "NASDAQ")

with st.expander("🔍 Don't know the ticker? Search by company name"):
    st.caption("1️⃣ Type a company name below and click **Search**  →  2️⃣ Select from the list  →  3️⃣ Click **Use this ticker**")
    hq1, hq2 = st.columns([4, 1])
    home_search_q = hq1.text_input("Company name", placeholder="e.g. Apple, Vodafone, Reliance", key="home_search_q")
    hq2.markdown("<br>", unsafe_allow_html=True)
    if hq2.button("Search", key="home_search_btn"):
        if home_search_q.strip():
            try:
                sr = requests.get(f"{BACKEND_URL}/api/search", params={"query": home_search_q, "limit": 30}, timeout=20)
                if sr.status_code == 200:
                    st.session_state["_home_search_results"] = sr.json().get("results", [])
            except Exception:
                st.session_state["_home_search_results"] = []
        else:
            st.warning("Please enter a company name first.")
    home_results = st.session_state.get("_home_search_results", [])
    if home_results:
        home_options = [f"{m['name']} ({m['ticker']}) — {m['region']}" for m in home_results]
        home_chosen  = st.selectbox("Select company", home_options, key="home_search_sel")
        home_sel_idx = home_options.index(home_chosen)
        if st.button("✅ Use this ticker", key="home_search_use"):
            sel = home_results[home_sel_idx]
            raw_ticker   = sel["ticker"]
            clean_ticker = raw_ticker.rsplit(".", 1)[0] if "." in raw_ticker else raw_ticker
            exch = search_result_to_exchange(raw_ticker, sel.get("region", ""), sel.get("currency", ""))
            st.session_state["home_ticker"]   = clean_ticker
            st.session_state["home_exchange"] = exch if exch in ALL_EXCHANGES else "NASDAQ"
            st.session_state.pop("_home_search_results", None)
            st.rerun()
    elif home_search_q and "_home_search_results" in st.session_state and not home_results:
        st.info("No results found. Try a different spelling.")

qc1, qc2, qc3 = st.columns([3, 2, 1])
with qc1:
    ticker = st.text_input(
        "Ticker Symbol", key="home_ticker",
        placeholder="e.g. AAPL, VOD, TCS, 7203",
    )
with qc2:
    exchange = st.selectbox(
        "Exchange", ALL_EXCHANGES,
        format_func=lambda x: EXCHANGE_SHORT_NAMES.get(x, x),
        key="home_exchange",
    )
with qc3:
    st.markdown("<br>", unsafe_allow_html=True)
    search_btn = st.button("Get Quote", type="primary", use_container_width=True)


@st.fragment(run_every=30)
def _quote_display(ticker_sym: str, exch: str):
    """Auto-refreshes every 30 s while rendered."""
    with st.spinner(f"Fetching {ticker_sym} on {exch}…"):
        try:
            resp = requests.get(
                f"{BACKEND_URL}/api/quote/{ticker_sym}",
                params={"exchange": exch},
                timeout=15,
            )
            if resp.status_code == 200:
                data          = resp.json()
                resp_currency = data.get("currency")
                sym  = CURRENCY_SYMBOLS.get(resp_currency,
                       EXCHANGE_CURRENCY.get(exch, ("USD", "$"))[1])
                code = resp_currency or EXCHANGE_CURRENCY.get(exch, ("USD", "$"))[0]
                # Normalise pence: GBp (ISO) → GBX (Bloomberg standard)
                if code in ("GBp",):
                    code = "GBX"

                price   = data.get("price")
                chg_pct = data.get("change_percent", 0)
                high    = data.get("high")
                low     = data.get("low")
                volume  = data.get("volume")

                st.success(f"✅ **{ticker_sym}** on **{exch}** ({code})")
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Price",    fmt_price(price, sym),
                          f"{chg_pct:+.2f}%" if chg_pct is not None else None)
                r2.metric("Day High", fmt_price(high, sym))
                r3.metric("Day Low",  fmt_price(low, sym))
                r4.metric("Volume",   f"{int(volume):,}" if volume else "N/A")
                st.caption(
                    f"⏱️ {data.get('delay_minutes', 15)}-min delayed · "
                    f"{data.get('timestamp', 'N/A')} · 🔄 Auto-refreshes every 30 s"
                )
            elif resp.status_code == 404:
                st.error(f"❌ **{ticker_sym}** not found on **{exch}**.")
                st.info(
                    "Examples: `AAPL` NASDAQ · `VOD` LSE · "
                    "`7203` TSE · `RELIANCE` NSE · `005930` KRX"
                )
            else:
                st.error(f"HTTP {resp.status_code}")
        except Exception as e:
            st.error(f"Failed to fetch quote: {e}")


if search_btn and ticker:
    # Persist globally so Company Explorer / Stock Charts pick it up on navigation
    st.session_state["global_ticker"]   = ticker.strip().upper()
    st.session_state["global_exchange"] = exchange
    _quote_display(ticker.strip().upper(), exchange)

st.markdown("---")

# ── Feature highlights ────────────────────────────────────────────────────────
st.markdown("### 🎯 Platform Capabilities")
fc1, fc2, fc3, fc4 = st.columns(4)
with fc1:
    st.markdown("#### 🌍 Global Coverage")
    st.write("31 exchanges · Americas, Europe, Asia-Pacific, MENA · 26 countries · 40,000+ companies")
with fc2:
    st.markdown("#### 📊 Multi-Source Data")
    st.write("Finnhub real-time · yfinance EOD · Alpha Vantage fundamentals · Marketaux news & sentiment")
with fc3:
    st.markdown("#### 🤖 AI Intelligence")
    st.write("Groq + Claude analysis · XGBoost direction prediction · IsolationForest anomaly detection · Factor exposure")
with fc4:
    st.markdown("#### 🏗️ MCP Architecture")
    st.write("6 MCP servers (4 regional + analytics + economics) · L1 cache · Rate limiter · Watchlist")

st.markdown("---")
st.markdown("### 📖 Navigate via sidebar:")
st.markdown("""
| Page | What you get |
|------|-------------|
| **Global Overview** | Live indices, correlation heatmap, sector ETF performance |
| **Company Explorer** | Fundamentals, AI analysis, factor radar, anomaly alerts, news sentiment |
| **Stock Charts** | Candlestick, RSI/MACD, Bollinger Bands, XGBoost price direction |
| **Macro Dashboard** | FRED yield curve, inflation, Fed rate, GDP, AI macro narrative |
""")
st.markdown("---")
st.caption("⚡ Powered by Multi-Agent MCP Architecture · Finnhub · yfinance · Alpha Vantage · Marketaux · FRED · Groq")
