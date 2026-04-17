"""
StockPilot AI — Global Overview.

Real-time view of all 31 exchanges across 4 global regions, cross-market
correlations, and US sector ETF performance. Data is fetched from all 5 MCP
servers simultaneously via a single ``/api/global-snapshot`` call, with
supplementary calls to the Analytics MCP for correlation and sector data.

Key sections
------------
- Regional Markets: Live status cards (open/closed) and index level/change for Americas, Europe, Asia-Pacific, MENA
- Data Quality: Backend quality score, sources validated, and cache hit rate
- Exchange Coverage: Bar and pie charts summarising the 31 exchanges and listed company counts
- Cross-Market Correlation: 30-day return heatmap with market regime (Risk-On / Risk-Off / Rotation) badge
- US Sector Performance: Horizontal bar chart of SPDR sector ETF returns (XLK, XLF, XLV…)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")


def fmt_index(value) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "N/A"


# ── Header ────────────────────────────────────────────────────────────────────
col_title, col_refresh = st.columns([8, 1])
with col_title:
    st.title("🌍 Global Market Overview")
    st.markdown("Real-time status across 31 exchanges in 26 countries")
with col_refresh:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

with st.expander("📋 Operational Guide"):
    st.markdown(
        "**Regional Markets section** — Shows the live status and key index values for all 4 global regions. "
        "Each card shows whether the exchange is currently 🟢 Open or 🔴 Closed, the index level, and today's change.\n\n"
        "**Reading index cards** — The number shown is the index *level* (e.g. S&P 500 at 5,200). "
        "The change % below it shows how much the index has moved today. "
        "Green = markets rising, Red = markets falling.\n\n"
        "**Cross-Market Correlation heatmap** — Shows how 8 major global indices have moved together over the last 30 days. "
        "Dark blue = both indices tend to rise and fall together (high correlation). "
        "Dark red = they tend to move in opposite directions. "
        "White/light = they move independently.\n\n"
        "**Market Regime badge** — Automatically classified based on how many indices are trending upward:\n"
        "- 🟢 Risk-On: Most markets rising — investors are confident, favouring equities\n"
        "- 🔴 Risk-Off: Most markets falling — investors are cautious, moving to safe assets\n"
        "- 🔄 Rotation: Mixed signals — money is shifting between regions or sectors\n\n"
        "**US Sector Performance** — Shows how 11 major US industry sectors are performing. "
        "Use the period selector (1M / 3M / 6M / 1Y) to change the timeframe. "
        "Click **🔄 Refresh** to reload with latest data. "
        "Sectors in green are outperforming; red sectors are lagging the market."
    )

with st.expander("📖 Glossary — Key Terms"):
    st.markdown(
        "**Stock Index** — A number that represents the combined value of a specific group of stocks. "
        "It's used as a benchmark to measure how a whole market or sector is performing. "
        "Examples: S&P 500 (500 largest US companies) · DAX (30 largest German companies) · "
        "Nikkei 225 (225 largest Japanese companies) · FTSE 100 (100 largest UK companies).\n\n"

        "**Index Points vs Percentage** — Index levels (e.g. 5,200 for S&P 500) are not prices — "
        "they're calculated scores. The change % is more useful for comparison across different indices.\n\n"

        "**Bull Market** — A period of rising stock prices, typically defined as a 20%+ rise from recent lows. "
        "Signals investor optimism and economic growth.\n\n"

        "**Bear Market** — A period of falling stock prices, typically defined as a 20%+ drop from recent highs. "
        "Signals investor pessimism or economic slowdown.\n\n"

        "**Correlation** — A measure of how two indices or assets move relative to each other, scored −1 to +1. "
        "+1.0 = they always move in the same direction together · "
        "0.0 = completely independent movements · "
        "−1.0 = when one rises the other always falls. "
        "Low correlation between your holdings means better portfolio diversification.\n\n"

        "**Market Regime** — The current overall mood and direction of global financial markets:\n"
        "- **Risk-On**: Investors are confident — buying stocks, emerging markets, commodities\n"
        "- **Risk-Off**: Investors are cautious — selling stocks, buying bonds, gold, and USD\n"
        "- **Rotation**: Money is moving from one sector or region to another\n\n"

        "**ETF (Exchange-Traded Fund)** — A fund that tracks a basket of assets (stocks, bonds, or sectors) "
        "and trades on an exchange like a regular stock. "
        "For example, buying XLK gives exposure to all major US technology companies at once.\n\n"

        "**Sector ETF** — An ETF focused on one industry group. Key US sector ETFs:\n"
        "XLK = Technology · XLF = Financials · XLE = Energy · XLV = Healthcare · "
        "XLI = Industrials · XLP = Consumer Staples · XLY = Consumer Discretionary · "
        "XLB = Materials · XLU = Utilities · XLRE = Real Estate · XLC = Communication\n\n"

        "**Daily Change %** — How much an index or stock price has moved today vs yesterday's closing value. "
        "A +1.5% move on the S&P 500 means the index rose 1.5% during today's session.\n\n"

        "**Data Quality Score** — Percentage of index values successfully retrieved vs attempted. "
        "100% = all data loaded correctly. Lower scores mean some indices returned no data."
    )

with st.expander("🔌 Data Sources — MCP Servers"):
    st.markdown(
        "Global Overview is powered by **all 5 MCP servers** working in parallel:\n\n"
        "| MCP Server | Data Provider | What it provides |\n"
        "|---|---|---|\n"
        "| 🌎 **Americas MCP** | Finnhub | US index snapshots — S&P 500 · NASDAQ Composite · Dow Jones |\n"
        "| 🌍 **Europe MCP** | yfinance | European index snapshots — FTSE 100 · DAX · CAC 40 · AEX · SMI |\n"
        "| 🌏 **Asia-Pacific MCP** | yfinance | Asian index snapshots — Nikkei 225 · Hang Seng · BSE Sensex · KOSPI |\n"
        "| 🌐 **MENA MCP** | yfinance | MENA index snapshots — Tadawul · DFM · TASE |\n"
        "| 📊 **Analytics MCP** | yfinance | Cross-market correlation matrix · US sector ETF performance |\n\n"
        "_All 4 regional MCP servers fetch their index data simultaneously so the page loads in one pass._"
    )

# ── Fetch snapshot ────────────────────────────────────────────────────────────
with st.spinner("Fetching live market data…"):
    try:
        resp = requests.get(f"{BACKEND_URL}/api/global-snapshot", timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach the backend at " + BACKEND_URL)
        st.stop()
    except requests.exceptions.Timeout:
        st.error("Request timed out — backend is still fetching index data. Try refreshing.")
        st.stop()
    except Exception as e:
        st.error(f"Error fetching snapshot: {e}")
        st.stop()

regions = data.get("regions", {})

# ── Regional Status Cards ─────────────────────────────────────────────────────
st.markdown("## Regional Markets")

REGION_FLAGS = {
    "americas":     "🌎",
    "europe":       "🌍",
    "asia_pacific": "🌏",
    "mena":         "🌐",
}

cols = st.columns(4)
for idx, (region_key, region_data) in enumerate(regions.items()):
    with cols[idx]:
        status     = region_data.get("status", "unknown")
        is_open    = "open" in status
        status_dot = "🟢" if is_open else "🔴"
        flag       = REGION_FLAGS.get(region_key, "🌐")
        label      = region_key.replace("_", " ").title()

        st.markdown(f"### {flag} {label}")
        status_color = "#22c55e" if is_open else "#ef4444"
        status_text  = "Open" if is_open else "Closed"
        st.markdown(
            f'<span style="color:{status_color};font-weight:700;font-size:0.9rem">'
            f'{status_dot} {status_text}</span>',
            unsafe_allow_html=True,
        )

        indices = region_data.get("major_indices", {})
        if not indices:
            st.caption("No index data available")
            continue

        for name, idx_data in indices.items():
            value  = idx_data.get("value")
            change = idx_data.get("change", 0)
            try:
                change = float(change)
            except (TypeError, ValueError):
                change = 0.0

            st.metric(
                label=name,
                value=fmt_index(value),
                delta=f"{change:+.2f}%" if value is not None else None,
            )

st.markdown("---")

# ── Data Quality ──────────────────────────────────────────────────────────────
st.markdown("## Data Quality & System Health")
quality = data.get("data_quality", {})

q1, q2, q3 = st.columns(3)
with q1:
    score = quality.get("average_quality_score", 0)
    label = "Excellent" if score >= 80 else ("Good" if score >= 60 else "Partial")
    st.metric("Quality Score", f"{score:.1f}/100", label)
with q2:
    st.metric("Sources Validated", quality.get("sources_validated", 0), "Multi-source")
with q3:
    hit = quality.get("cache_hit_rate", 0)
    st.metric("Cache Hit Rate", f"{hit:.1%}" if hit else "N/A", "Efficient")

st.markdown("---")

# ── Exchange Coverage Charts ──────────────────────────────────────────────────
st.markdown("## Global Exchange Coverage")

exchange_df = pd.DataFrame({
    "Region":    ["Americas", "Europe", "Asia-Pacific", "MENA"],
    "Exchanges": [6, 9, 10, 6],
    "Companies": [9750, 5600, 24900, 1080],
})

c1, c2 = st.columns(2)
with c1:
    fig = px.bar(
        exchange_df, x="Region", y="Exchanges",
        title="Exchanges by Region",
        color="Exchanges", color_continuous_scale="viridis",
        text="Exchanges",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(showlegend=False, coloraxis_showscale=False)
    st.plotly_chart(fig, use_container_width=True)

with c2:
    fig = px.pie(
        exchange_df, values="Companies", names="Region",
        title="Listed Companies by Region",
        hole=0.4,
    )
    fig.update_traces(textinfo="percent+label")
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# ── Cross-Market Correlation ──────────────────────────────────────────────────
st.markdown("## Cross-Market Correlation")
st.caption("30-day return correlation between major global indices")

corr_data = None
with st.spinner("Computing correlations…"):
    try:
        r = requests.get(f"{BACKEND_URL}/api/intelligence/correlation", timeout=30)
        if r.status_code == 200:
            corr_data = r.json()
    except Exception:
        pass

if corr_data and not corr_data.get("error") and corr_data.get("matrix"):
    matrix     = corr_data["matrix"]
    labels     = corr_data.get("labels", list(matrix.keys()))
    regime     = corr_data.get("regime", "Unknown")
    regime_desc = corr_data.get("regime_description", "")

    # Regime banner
    regime_colors = {
        "Risk-On":   "#26a69a",
        "Risk-Off":  "#ef5350",
        "Rotation":  "#FF9800",
        "Unknown":   "#9E9E9E",
    }
    color = regime_colors.get(regime, "#9E9E9E")
    st.markdown(
        f"**Market Regime:** "
        f"<span style='color:{color};font-weight:bold;font-size:1.1em'>{regime}</span>"
        + (f" — {regime_desc}" if regime_desc else ""),
        unsafe_allow_html=True,
    )

    # Build correlation matrix for heatmap
    try:
        corr_df = pd.DataFrame(matrix, index=labels, columns=labels).astype(float)
        fig_corr = go.Figure(go.Heatmap(
            z=corr_df.values.tolist(),
            x=labels,
            y=labels,
            colorscale="RdBu",
            zmid=0,
            zmin=-1, zmax=1,
            text=[[f"{v:.2f}" for v in row] for row in corr_df.values.tolist()],
            texttemplate="%{text}",
            textfont=dict(size=11),
            hovertemplate="%{y} vs %{x}: %{z:.3f}<extra></extra>",
        ))
        fig_corr.update_layout(
            height=420,
            margin=dict(t=20, b=20, l=80, r=20),
            xaxis=dict(tickangle=-30),
        )
        st.plotly_chart(fig_corr, use_container_width=True)
        st.caption(
            "Blue = highly correlated (move together) · Red = inversely correlated · "
            "Based on last 30 trading days · Source: yfinance"
        )
    except Exception as e:
        st.info(f"Correlation matrix display error: {e}")
else:
    st.info(
        "Cross-market correlation unavailable. "
        "This requires the analytics MCP server and at least 30 days of index history."
    )

st.markdown("---")

# ── Sector Performance ────────────────────────────────────────────────────────
st.markdown("## US Sector Performance")
st.caption("Sector ETF returns via SPDR — XLK, XLF, XLV, XLE, XLY, XLI, XLU, XLB, XLRE, XLC, XLP")

sector_data = None
with st.spinner("Fetching sector ETF data…"):
    try:
        r = requests.get(f"{BACKEND_URL}/api/sector-performance", timeout=20)
        if r.status_code == 200:
            sector_data = r.json()
    except Exception:
        pass

if sector_data and sector_data.get("sectors"):
    sectors = sector_data["sectors"]
    period  = sector_data.get("period", "1mo")

    sec_df = pd.DataFrame([
        {"Sector": name, "Return (%)": info.get("performance_pct", 0)}
        for name, info in sectors.items()
        if info.get("performance_pct") is not None
    ]).sort_values("Return (%)", ascending=True)

    if not sec_df.empty:
        bar_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in sec_df["Return (%)"]]
        fig_sec = go.Figure(go.Bar(
            x=sec_df["Return (%)"],
            y=sec_df["Sector"],
            orientation="h",
            marker_color=bar_colors,
            text=[f"{v:+.2f}%" for v in sec_df["Return (%)"]],
            textposition="outside",
        ))
        fig_sec.add_vline(x=0, line_color="gray", line_width=0.8)
        fig_sec.update_layout(
            height=380,
            xaxis_title="Return (%)",
            margin=dict(t=10, b=20, l=20, r=80),
        )
        st.plotly_chart(fig_sec, use_container_width=True)
        st.caption(f"Period: {period} · Source: yfinance")
else:
    st.info("Sector performance data loading… (requires analytics MCP server)")

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | "
    "Prices delayed 15 min | "
    "Sources: yfinance · Finnhub · Alpha Vantage · Marketaux · MCP regional servers"
)
