"""
MarketMesh AI — application entry point.

This is the root Streamlit script executed by ``streamlit run app.py``. It must
be loaded before any page so that ``st.set_page_config`` (which must be the very
first Streamlit call) fires exactly once. All other pages are registered via
``st.navigation()`` and rendered by ``pg.run()`` at the bottom of this file.

Key sections
------------
- Page config: Title, icon, layout, and initial sidebar state (called first)
- Global CSS: Professional dark-theme overrides for metrics, headings, tabs, buttons, sidebar
- Shared sidebar: App title, feature summary, MCP server health check, coverage metrics, watchlist panel
- Navigation: st.navigation() registering all 5 pages with human-readable titles and icons
"""

import streamlit as st
import requests
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import ALL_EXCHANGES, EXCHANGE_SHORT_NAMES

# ── Must be the very first Streamlit call ─────────────────────────────────────
st.set_page_config(
    page_title="MarketMesh AI",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded",
)

BACKEND_URL = os.getenv('BACKEND_URL', 'http://127.0.0.1:8000')

# ── Global professional theme ─────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Typography ─────────────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
}

/* ── Metric cards ───────────────────────────────────────────────────────── */
[data-testid="metric-container"] {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px;
    padding: 14px 18px 12px 18px;
    box-shadow: 0 1px 6px rgba(0,0,0,0.25);
    transition: box-shadow 0.2s ease;
}
[data-testid="metric-container"]:hover {
    box-shadow: 0 4px 14px rgba(0,0,0,0.35);
    border-color: rgba(255,255,255,0.22);
}
[data-testid="metric-container"] label {
    font-size: 11px !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #94a3b8 !important;
}
[data-testid="metric-container"] [data-testid="stMetricValue"] {
    font-size: 1.4rem !important;
    font-weight: 700 !important;
    color: #f1f5f9 !important;
}
[data-testid="metric-container"] [data-testid="stMetricDelta"] {
    font-size: 0.82rem !important;
    font-weight: 600 !important;
}

/* ── Page headings (Streamlit-specific selectors for guaranteed override) ── */
[data-testid="stMarkdownContainer"] h1,
.stMarkdown h1 {
    font-size: 1.75rem !important;
    font-weight: 800 !important;
    color: #ffffff !important;
    letter-spacing: -0.01em !important;
    margin-bottom: 0.4rem !important;
}
[data-testid="stMarkdownContainer"] h2,
.stMarkdown h2 {
    font-size: 1.1rem !important;
    font-weight: 700 !important;
    color: #e2e8f0 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.07em !important;
    border-bottom: 1px solid rgba(255,255,255,0.15) !important;
    padding-bottom: 6px !important;
    margin-top: 1.5rem !important;
    margin-bottom: 0.75rem !important;
    background: none !important;
}
[data-testid="stMarkdownContainer"] h3,
.stMarkdown h3 {
    font-size: 1rem !important;
    font-weight: 600 !important;
    color: #93c5fd !important;
    letter-spacing: 0.01em !important;
    margin-top: 1.1rem !important;
    margin-bottom: 0.4rem !important;
    background: none !important;
    border: none !important;
}
[data-testid="stMarkdownContainer"] h4,
.stMarkdown h4 {
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    color: #94a3b8 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
    margin-top: 0.8rem !important;
}

/* ── Tabs ────────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 6px;
    border-bottom: 2px solid #e2e8f0;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 6px 6px 0 0;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 0.88rem;
    color: #64748b;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    color: #1d4ed8 !important;
    border-bottom: 2px solid #1d4ed8;
    background: transparent;
}

/* ── Buttons ─────────────────────────────────────────────────────────────── */
.stButton > button {
    border-radius: 7px;
    font-weight: 600;
    font-size: 0.85rem;
    padding: 6px 18px;
    transition: all 0.15s ease;
}
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 100%);
    border: none;
    color: white;
    box-shadow: 0 2px 6px rgba(29,78,216,0.3);
}
.stButton > button[kind="primary"]:hover {
    background: linear-gradient(135deg, #1e40af 0%, #1d4ed8 100%);
    box-shadow: 0 4px 12px rgba(29,78,216,0.4);
}

/* ── DataFrames ──────────────────────────────────────────────────────────── */
.stDataFrame { border-radius: 8px; overflow: hidden; border: 1px solid rgba(255,255,255,0.1) !important; }
.stDataFrame th { font-weight: 700 !important;
                  font-size: 0.78rem !important; text-transform: uppercase;
                  letter-spacing: 0.04em; color: #94a3b8 !important; }
.stDataFrame td { font-size: 0.88rem !important; color: #e2e8f0 !important; }

/* ── Info / Warning / Success boxes ─────────────────────────────────────── */
.stAlert { border-radius: 8px !important; }

/* ── Expanders ───────────────────────────────────────────────────────────── */
.streamlit-expanderHeader {
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    color: #374151 !important;
}

/* ── Horizontal rule ─────────────────────────────────────────────────────── */
hr { border: none; border-top: 1px solid rgba(255,255,255,0.12) !important; margin: 1.2rem 0 !important; }

/* ── Caption text ────────────────────────────────────────────────────────── */
.stCaption { color: #64748b !important; font-size: 0.78rem !important; }

/* ── General text in main area ───────────────────────────────────────────── */
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li {
    color: #cbd5e1 !important;
}

/* ── Sidebar ─────────────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
}
section[data-testid="stSidebar"] .stMarkdown,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span {
    color: #cbd5e1 !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] h4,
section[data-testid="stSidebar"] strong,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3,
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h4 {
    color: #e2e8f0 !important;
    background: transparent !important;
    border-bottom-color: rgba(255,255,255,0.12) !important;
    letter-spacing: 0.04em !important;
}
section[data-testid="stSidebar"] [data-testid="metric-container"] {
    background: rgba(255,255,255,0.06);
    border-color: rgba(255,255,255,0.12);
}
section[data-testid="stSidebar"] [data-testid="metric-container"] label,
section[data-testid="stSidebar"] [data-testid="stMetricValue"],
section[data-testid="stSidebar"] [data-testid="stMetricDelta"] {
    color: #e2e8f0 !important;
}
section[data-testid="stSidebar"] .stButton > button {
    background: rgba(255,255,255,0.1);
    color: #f1f5f9;
    border: 1px solid rgba(255,255,255,0.2);
}

/* ── Plotly charts – remove white padding ────────────────────────────────── */
.js-plotly-plot .plotly { border-radius: 8px; }

/* ── Price up/down utility classes ──────────────────────────────────────── */
.eq-up   { color: #16a34a !important; font-weight: 700; }
.eq-down { color: #dc2626 !important; font-weight: 700; }
.eq-neutral { color: #d97706 !important; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

# ── Shared sidebar (rendered on every page) ───────────────────────────────────
with st.sidebar:
    st.title("🌐 MarketMesh AI")
    st.markdown("**Real-time stock intelligence across 31 exchanges in 26 countries, powered by 6 AI agents.**")
    st.markdown("---")

    st.markdown(
        "**What you can do:**\n"
        "- 📊 Live quotes, fundamentals & AI company analysis\n"
        "- 🌐 Global index snapshot & cross-market correlation\n"
        "- 📈 Technical charts: RSI, MACD, Bollinger Bands, prediction\n"
        "- 🏦 FRED macro dashboard with AI narrative\n"
        "- ⭐ Watchlist with one-click deep dive"
    )

    with st.expander("ℹ️ How it works"):
        st.markdown(
            "**Data pipeline:**\n"
            "yfinance → Finnhub → Alpha Vantage → Marketaux → FRED\n\n"
            "**AI:** Groq (llama-3.1-8b-instant) with Gemini fallback\n\n"
            "**Architecture:** FastAPI + 6 MCP stdio servers + Streamlit\n\n"
            "**Coverage:** 40,000+ companies across Americas, Europe, Asia-Pacific & MENA"
        )

    st.markdown("---")

    # System / MCP health
    try:
        resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
        if resp.status_code == 200:
            st.success("✅ System Online")
            health = resp.json()
            with st.expander("MCP Server Status"):
                for server, status in health.get("mcp_servers", {}).items():
                    icon = "🟢" if status == "connected" else "🔴"
                    st.write(f"{icon} **{server}**: {status}")
        else:
            st.error("⚠️ System Degraded")
    except Exception:
        st.warning("⚠️ Backend Offline")

    st.markdown("---")
    st.markdown("### Coverage")
    st.metric("Exchanges", "31")
    st.metric("Countries", "26")
    st.metric("Companies", "40,000+")

    st.markdown("---")
    st.markdown("### Data Sources")
    st.markdown("""
- **Finnhub** (Real-time US quotes)
- **yfinance** (Global EOD data)
- **Alpha Vantage** (Fundamentals & EPS)
- **Marketaux** (News & Sentiment)
- **FRED** (Economic indicators)
- **Groq / Gemini** (AI analysis)
""")

    # ── Watchlist panel ───────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### ⭐ Watchlist")

    try:
        wl_resp = requests.get(f"{BACKEND_URL}/api/watchlist", timeout=5)
        watchlist = wl_resp.json().get("watchlist", []) if wl_resp.status_code == 200 else []
    except Exception:
        watchlist = []

    if watchlist:
        for item in watchlist:
            wc1, wc2, wc3 = st.columns([3, 1, 1])
            wc1.markdown(f"**{item['ticker']}** `{EXCHANGE_SHORT_NAMES.get(item['exchange'], item['exchange'])}`")
            if wc2.button("📈", key=f"go_{item['ticker']}_{item['exchange']}", help="Open in Explorer"):
                st.session_state["wl_ticker"]   = item["ticker"]
                st.session_state["wl_exchange"] = item["exchange"]
                st.switch_page("pages/company_explorer.py")
            if wc3.button("✕", key=f"rm_{item['ticker']}_{item['exchange']}", help="Remove"):
                try:
                    requests.delete(
                        f"{BACKEND_URL}/api/watchlist/{item['ticker']}",
                        params={"exchange": item["exchange"]}, timeout=5,
                    )
                    st.rerun()
                except Exception:
                    pass
    else:
        st.caption("No tickers yet — add one below")

    with st.form("wl_add_form", clear_on_submit=True):
        wf1, wf2 = st.columns([3, 2])
        wl_ticker = wf1.text_input("Ticker", placeholder="AAPL", label_visibility="collapsed")
        wl_exch   = wf2.selectbox("Exchange",
                                   ALL_EXCHANGES,
                                   format_func=lambda x: EXCHANGE_SHORT_NAMES.get(x, x),
                                   label_visibility="collapsed")
        if st.form_submit_button("➕ Add", use_container_width=True):
            if wl_ticker.strip():
                try:
                    requests.post(
                        f"{BACKEND_URL}/api/watchlist",
                        params={"ticker": wl_ticker.strip().upper(), "exchange": wl_exch},
                        timeout=5,
                    )
                    st.rerun()
                except Exception:
                    st.error("Could not reach backend")

    st.markdown("---")
    st.caption("🌐 MarketMesh AI · Built with MCP Architecture")

# ── Page definitions with custom sidebar labels ───────────────────────────────
pg = st.navigation([
    st.Page("pages/home.py",            title="Market Dashboard", icon="🌍", default=True),
    st.Page("pages/global_overview.py", title="Global Overview",  icon="🌐"),
    st.Page("pages/company_explorer.py",title="Company Explorer", icon="🏢"),
    st.Page("pages/stock_charts.py",    title="Stock Charts",     icon="📈"),
    st.Page("pages/macro_dashboard.py", title="Macro Dashboard",  icon="🌐"),
])

pg.run()
