"""
MarketMesh AI — Macro Dashboard.

US macroeconomic environment page powered by the Economics MCP Server (FRED)
and AI narrative generation (Groq / Gemini). Displays the full suite of FRED
time series used by institutional investors to assess recession risk, inflation
pressure, Fed policy trajectory, and GDP growth. All FRED data is session-cached
to avoid repeated API calls; individual charts can be force-refreshed via the
Refresh button which bypasses both the session cache and the 1-hour backend cache.

Key sections
------------
- US Treasury Yield Curve: Current tenor snapshot (3M–30Y) with inversion detection and spread badge
- Inflation Trends: CPI and PCE index series chart with YoY headline metrics
- Federal Funds Rate: Historical rate area chart with current rate metric
- Real GDP Growth: Quarterly QoQ bar chart (green = expansion, red = contraction)
- Key Economic Indicators: Unemployment rate and University of Michigan consumer sentiment
- AI Macro Narrative: Groq/Gemini plain-English interpretation of macro conditions (fragment, 4h cache)
"""

import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import os

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

st.title("🌐 Macro Dashboard")
st.markdown(
    "US economic indicators from FRED — yield curves, inflation, Fed rate, GDP, "
    "and key macro signals"
)

with st.expander("📋 Operational Guide"):
    st.markdown(
        "This page shows the US macroeconomic environment — the 'big picture' context that affects all stock markets globally. "
        "Understanding macro conditions helps explain why markets are rising or falling.\n\n"
        "**Yield Curve chart** — The line chart plots US government bond yields at different time horizons (3 months → 30 years). "
        "A normal upward-sloping curve = healthy economy. A flat or downward-sloping (inverted) curve = recession warning. "
        "Check the **Spread (10Y−2Y)** value: negative spread = curve is inverted.\n\n"
        "**Inflation charts** — Three lines track price changes: CPI (what consumers pay), PCE (Fed's preferred measure), "
        "and PPI (what producers pay, a leading indicator for consumer prices). "
        "The Fed targets ~2% annual PCE inflation. Above 2% = inflationary pressure. Below 2% = deflationary risk.\n\n"
        "**Federal Funds Rate chart** — Shows the interest rate the US Federal Reserve has set over time. "
        "Rising rates = Fed fighting inflation (slows the economy, pressures stock valuations). "
        "Falling rates = Fed stimulating growth (boosts stocks and bonds).\n\n"
        "**GDP Growth chart** — Quarterly percentage change in US economic output. "
        "Positive bars = economy expanding. Negative bars = contracting. "
        "Two consecutive negative quarters = official recession.\n\n"
        "**Key Economic Indicators** — Three real-time readings: Unemployment Rate, Consumer Sentiment, ISM PMI. "
        "These are 'pulse check' metrics for the economy's current health.\n\n"
        "**AI Macro Narrative** — An AI-generated analysis interpreting all the above data together in plain English. "
        "Click **🔄 Regenerate** for a fresh analysis, or **🔄 Refresh** at the top to reload all FRED data."
    )

with st.expander("📖 Glossary — Key Terms"):
    st.markdown(
        "### 📈 Yield Curve\n\n"
        "**Treasury Bond / Treasury Yield** — When the US government borrows money, it issues Treasury bonds. "
        "The yield is the interest rate investors receive for lending to the government. "
        "These are considered the safest investments in the world (backed by the US government).\n\n"

        "**Yield Curve** — A chart plotting Treasury yields at different maturities: 3-month, 2-year, 5-year, 10-year, 30-year. "
        "Normally, longer-term bonds pay higher yields (you get more for locking money up longer). "
        "This creates an upward-sloping curve — the 'normal' shape.\n\n"

        "**Yield Curve Inversion** — When short-term yields (e.g. 2-year) are *higher* than long-term yields (e.g. 10-year). "
        "This is abnormal — it means investors expect the economy to weaken or the Fed to cut rates in the future. "
        "Every US recession since 1955 was preceded by an inverted yield curve, typically 12–18 months earlier. "
        "*The 10Y−2Y spread is the most watched signal: negative = inverted.*\n\n"

        "**Spread (10Y−2Y)** — The difference between the 10-year Treasury yield and the 2-year Treasury yield. "
        "Positive spread (e.g. +0.5%) = normal curve. "
        "Negative spread (e.g. −0.3%) = inverted = recession concern.\n\n"

        "### 💹 Inflation\n\n"
        "**Inflation** — The rate at which prices of goods and services rise over time. "
        "Moderate inflation (~2%) is healthy. Too high = purchasing power erodes (bad for bonds, mixed for stocks). "
        "Too low or negative (deflation) = economic stagnation risk.\n\n"

        "**CPI (Consumer Price Index)** — Measures the average change in prices paid by consumers for a basket of everyday goods: "
        "food, housing, energy, clothing, healthcare. Published monthly by the US Bureau of Labor Statistics. "
        "YoY% shows how much prices have risen vs the same month a year ago.\n\n"

        "**PCE (Personal Consumption Expenditures Price Index)** — The Federal Reserve's *preferred* inflation measure. "
        "Covers a broader range of spending than CPI and adjusts for changes in consumer behaviour. "
        "The Fed's official inflation target is 2% annual PCE. "
        "PCE above 2% = Fed may raise rates. PCE below 2% = Fed may cut rates.\n\n"

        "**PPI (Producer Price Index)** — Measures price changes from the perspective of businesses (producers), "
        "not consumers. Because producer costs eventually pass through to consumers, "
        "PPI is a *leading indicator* — it often predicts future CPI changes by 1–3 months.\n\n"

        "**YoY % (Year-over-Year)** — The percentage change compared to the same period 12 months ago. "
        "Example: CPI YoY of 3.5% means prices are 3.5% higher than a year ago.\n\n"

        "### 🏦 Federal Reserve & Interest Rates\n\n"
        "**Federal Reserve (The Fed)** — The central bank of the United States. "
        "Its two main jobs are: (1) keeping inflation near 2%, and (2) maximising employment. "
        "The Fed controls interest rates as its primary tool.\n\n"

        "**Federal Funds Rate** — The target interest rate at which US banks lend money to each other overnight. "
        "This rate influences *all* borrowing costs: mortgages, car loans, business loans, and credit cards. "
        "Higher rate = borrowing is more expensive = economy slows = inflation falls. "
        "Lower rate = borrowing is cheaper = economy stimulates = inflation may rise.\n\n"

        "**Effect on Stocks** — Higher interest rates compress stock valuations because: "
        "(1) bonds become more attractive alternatives, (2) companies pay more to borrow, reducing profits, "
        "(3) future earnings are discounted more heavily. "
        "Rate cuts generally boost stock markets.\n\n"

        "**Basis Point (bps)** — One hundredth of a percentage point (0.01%). "
        "The Fed typically raises or cuts rates in 25bps (0.25%) increments. "
        "A '50bps hike' = raising rates by 0.5%.\n\n"

        "### 📊 Economic Growth\n\n"
        "**GDP (Gross Domestic Product)** — The total monetary value of all goods and services produced in a country "
        "during a specific period. The broadest measure of economic activity.\n\n"

        "**Real GDP Growth (QoQ %)** — The percentage change in inflation-adjusted GDP from one quarter to the next. "
        "'Real' means inflation has been stripped out, showing actual volume growth. "
        "Positive = economy growing. Negative = shrinking.\n\n"

        "**Recession** — Formally defined as two consecutive quarters of negative GDP growth. "
        "During recessions, unemployment rises, corporate profits fall, and stock markets typically decline.\n\n"

        "### 📡 Key Economic Indicators\n\n"
        "**Unemployment Rate** — The percentage of the labour force that is jobless and actively seeking work. "
        "Low unemployment (3–4%) = strong economy. Rising unemployment = economic weakness. "
        "Very low unemployment can also cause inflation (workers demand higher wages).\n\n"

        "**Consumer Sentiment (UMich)** — A monthly survey by the University of Michigan measuring how optimistic "
        "or pessimistic US consumers feel about the economy and their personal finances. "
        "Scale: higher = more confident. Below 70 = notably pessimistic. "
        "Consumer sentiment predicts spending — low sentiment often leads to reduced consumption.\n\n"

        "**ISM Manufacturing PMI (Purchasing Managers Index)** — A monthly survey of purchasing managers at US manufacturers. "
        "Scale: 0–100. "
        "Above 50 = manufacturing sector is *expanding* (orders, production, employment rising). "
        "Below 50 = manufacturing sector is *contracting*. "
        "It's a *leading indicator* — it changes before the broader economy does, giving early warning.\n\n"

        "**Leading vs Lagging Indicators** — Leading indicators (PMI, consumer sentiment, yield curve) "
        "change *before* the economy does, giving advance warning. "
        "Lagging indicators (unemployment, GDP) confirm trends that have already started."
    )

with st.expander("🔌 Data Sources — MCP Servers"):
    st.markdown(
        "Macro Dashboard is powered by the **Economics MCP Server** (FRED) and AI:\n\n"
        "| MCP Server | Data Provider | What it provides |\n"
        "|---|---|---|\n"
        "| 📈 **Economics MCP** | FRED (St. Louis Fed) | US Treasury yield curve — 3M · 2Y · 5Y · 10Y · 30Y |\n"
        "| 📈 **Economics MCP** | FRED | Inflation — CPI · PCE · PPI (monthly) |\n"
        "| 📈 **Economics MCP** | FRED | Federal Funds Rate history |\n"
        "| 📈 **Economics MCP** | FRED | Real GDP growth (quarterly) |\n"
        "| 📈 **Economics MCP** | FRED | Key indicators — Unemployment · Consumer Sentiment · ISM PMI |\n"
        "| 🤖 **AI (Groq / Gemini)** | LLM | Macro narrative — interprets all FRED data into plain-English insights |\n\n"
        "_FRED (Federal Reserve Economic Data) is the official economic data repository of the "
        "US Federal Reserve Bank of St. Louis, providing 800,000+ time series._"
    )

col_hdr, col_ref = st.columns([8, 1])
with col_ref:
    if st.button("🔄 Refresh"):
        # Clear FRED + AI session caches; set flags so both re-fetch bypassing backend caches
        st.session_state.pop("macro_ai", None)
        st.session_state.pop("macro_data", None)
        st.session_state["macro_hard_refresh"]  = True   # FRED calls bypass 1h backend cache
        st.session_state["macro_force_refresh"] = True   # AI call bypasses 4h backend cache
        st.rerun()

# ── Fetch all macro data — cached in session_state for speed ─────────────────
ENDPOINTS = {
    "yield_curve": "yield_data",
    "inflation":   "inflation_data",
    "fed_rate":    "fed_rate_data",
    "gdp":         "gdp_data",
    "indicators":  "indicators_data",
}

if "macro_data" not in st.session_state:
    hard_refresh = st.session_state.pop("macro_hard_refresh", False)
    _macro_fetch = {}
    with st.spinner("Refreshing FRED economic data…" if hard_refresh else "Fetching FRED economic data…"):
        for indicator in ENDPOINTS:
            try:
                params = {"refresh": "true"} if hard_refresh else {}
                r = requests.get(f"{BACKEND_URL}/api/macro/{indicator}", params=params, timeout=20)
                if r.status_code == 200:
                    _macro_fetch[indicator] = r.json()
            except Exception:
                _macro_fetch[indicator] = None
    st.session_state["macro_data"] = _macro_fetch

macro = st.session_state["macro_data"]

fred_configured = any(
    v and not v.get("error") for v in macro.values()
)

if not fred_configured:
    st.warning(
        "FRED data unavailable. Add `FRED_API_KEY` to your `.env` file "
        "(free at https://fred.stlouisfed.org/docs/api/api_key.html) and restart the backend."
    )

# ═══════════════════════════════════════════════════════════════════════════════
# YIELD CURVE
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("## US Treasury Yield Curve")

yield_data = macro.get("yield_curve")
if yield_data and not yield_data.get("error"):
    current  = yield_data.get("current", {})
    spread   = yield_data.get("spread_10y_2y")
    inverted = yield_data.get("inverted", False)
    signal   = yield_data.get("signal", "—")

    yc1, yc2, yc3, yc4 = st.columns(4)
    yc1.metric(
        "10Y-2Y Spread",
        f"{spread:.3f}%" if spread is not None else "N/A",
        "⚠ Inverted" if inverted else "Normal",
    )
    yc2.metric(
        "10-Year Treasury",
        f"{current.get('10Y', '—')}%" if current.get("10Y") else "N/A",
    )
    yc3.metric(
        "2-Year Treasury",
        f"{current.get('2Y', '—')}%" if current.get("2Y") else "N/A",
    )
    yc4.metric("Curve Signal", signal)

    # Always-visible inversion status badge
    inv_color = "#ef5350" if inverted else "#26a69a"
    inv_label = "⚠️ INVERTED — Watch for recession signals" if inverted else "✅ NORMAL — Yield curve not inverted"
    st.markdown(
        f"<div style='background:{inv_color};color:white;padding:6px 14px;"
        f"border-radius:6px;font-weight:600;display:inline-block;margin:4px 0'>"
        f"{inv_label}</div>",
        unsafe_allow_html=True,
    )
    if inverted:
        st.warning(
            "⚠️ **Inverted Yield Curve** — historically precedes recession by 12–18 months. "
            "Not a guarantee, but monitored closely by institutional investors."
        )

    tenors = ["3M", "2Y", "5Y", "10Y", "30Y"]
    values = [current.get(t) for t in tenors]
    if any(v is not None for v in values):
        fig_yc = go.Figure()
        fig_yc.add_trace(go.Scatter(
            x=tenors, y=values,
            mode="lines+markers",
            name="Current Yield Curve",
            line=dict(color="#2196F3", width=3),
            marker=dict(size=10),
            hovertemplate="%{x}: %{y:.3f}%<extra></extra>",
        ))
        fig_yc.add_hline(y=0, line_color="gray", line_width=0.5, line_dash="dot")
        fig_yc.update_layout(
            height=300,
            yaxis_title="Yield (%)",
            xaxis_title="Maturity",
            margin=dict(t=20, b=20, l=20, r=20),
            showlegend=False,
        )
        st.plotly_chart(fig_yc, use_container_width=True)
else:
    st.info("Yield curve data unavailable — FRED_API_KEY not configured.")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# INFLATION TRENDS
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("## Inflation Trends")

inflation_data = macro.get("inflation")
if inflation_data and not inflation_data.get("error"):
    cpi_info = inflation_data.get("cpi", {})
    pce_info = inflation_data.get("pce", {})
    ppi_info = inflation_data.get("ppi", {})

    cpi_yoy = cpi_info.get("yoy_pct")
    pce_yoy = pce_info.get("yoy_pct")
    ppi_yoy = ppi_info.get("yoy_pct")

    ic1, ic2, ic3 = st.columns(3)
    ic1.metric("CPI YoY", f"{cpi_yoy:.2f}%" if cpi_yoy is not None else "N/A",
               "Consumer prices")
    ic2.metric("PCE YoY", f"{pce_yoy:.2f}%" if pce_yoy is not None else "N/A",
               "Fed's preferred measure")
    ic3.metric("PPI YoY", f"{ppi_yoy:.2f}%" if ppi_yoy is not None else "N/A",
               "Producer prices")

    fig_inf = go.Figure()
    for label, info, color in [
        ("CPI (Urban)", cpi_info, "#E91E63"),
        ("PCE Price Index", pce_info, "#2196F3"),
    ]:
        series = info.get("series", [])
        if series:
            df_s = pd.DataFrame(series)
            df_s["date"] = pd.to_datetime(df_s["date"])
            fig_inf.add_trace(go.Scatter(
                x=df_s["date"], y=df_s["value"],
                mode="lines", name=label,
                line=dict(color=color, width=2),
            ))
    fig_inf.update_layout(
        height=300, yaxis_title="Index Value",
        margin=dict(t=20, b=20, l=20, r=20),
        legend=dict(orientation="h", y=1.1),
    )
    st.plotly_chart(fig_inf, use_container_width=True)
else:
    st.info("Inflation data unavailable — FRED_API_KEY not configured.")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# FED FUNDS RATE
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("## Federal Funds Rate")

fed_data = macro.get("fed_rate")
if fed_data and not fed_data.get("error"):
    current_rate = fed_data.get("current_rate")
    history      = fed_data.get("history", [])

    fr1, fr2 = st.columns([1, 3])
    fr1.metric(
        "Current Rate",
        f"{current_rate:.2f}%" if current_rate is not None else "N/A",
    )

    if history:
        df_fed = pd.DataFrame(history)
        df_fed["date"] = pd.to_datetime(df_fed["date"])
        fig_fed = go.Figure(go.Scatter(
            x=df_fed["date"], y=df_fed["value"],
            mode="lines", fill="tozeroy",
            line=dict(color="#FF9800", width=2),
            fillcolor="rgba(255,152,0,0.1)",
            hovertemplate="%{x|%b %Y}: %{y:.2f}%<extra></extra>",
        ))
        fig_fed.update_layout(
            height=260, yaxis_title="Rate (%)",
            margin=dict(t=20, b=20, l=20, r=20),
            showlegend=False,
        )
        with fr2:
            st.plotly_chart(fig_fed, use_container_width=True)
else:
    st.info("Fed rate data unavailable — FRED_API_KEY not configured.")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# GDP GROWTH
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("## Real GDP Growth (QoQ %)")

gdp_data = macro.get("gdp")
if gdp_data and not gdp_data.get("error"):
    current_gdp = gdp_data.get("current_qoq_pct")
    avg_gdp     = gdp_data.get("average_pct")
    gdp_hist    = gdp_data.get("history", [])

    gc1, gc2 = st.columns(2)
    gc1.metric(
        "Latest QoQ Growth",
        f"{current_gdp:.2f}%" if current_gdp is not None else "N/A",
    )
    gc2.metric(
        "Period Average",
        f"{avg_gdp:.2f}%" if avg_gdp is not None else "N/A",
    )

    if gdp_hist:
        df_gdp = pd.DataFrame(gdp_hist)
        df_gdp["date"] = pd.to_datetime(df_gdp["date"])
        bar_c = ["#26a69a" if v >= 0 else "#ef5350" for v in df_gdp["value"]]
        fig_gdp = go.Figure(go.Bar(
            x=df_gdp["date"], y=df_gdp["value"],
            marker_color=bar_c, name="GDP QoQ %",
            hovertemplate="%{x|%b %Y}: %{y:.2f}%<extra></extra>",
        ))
        fig_gdp.add_hline(y=0, line_color="gray", line_width=0.8)
        fig_gdp.update_layout(
            height=280, yaxis_title="Growth (%)",
            margin=dict(t=20, b=20, l=20, r=20),
            showlegend=False,
        )
        st.plotly_chart(fig_gdp, use_container_width=True)
else:
    st.info("GDP data unavailable — FRED_API_KEY not configured.")

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# KEY INDICATORS
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("## Key Economic Indicators")

ind_data = macro.get("indicators")
if ind_data and not ind_data.get("error"):
    unrate = ind_data.get("unemployment", {})
    umcsi  = ind_data.get("consumer_sentiment", {})

    ki1, ki2 = st.columns(2)
    ki1.metric(
        "Unemployment Rate",
        f"{unrate.get('value'):.1f}%" if unrate.get("value") is not None else "N/A",
        f"as of {unrate.get('date', 'N/A')}",
    )
    ki2.metric(
        "Consumer Sentiment (UMich)",
        f"{umcsi.get('value'):.1f}" if umcsi.get("value") is not None else "N/A",
        f"as of {umcsi.get('date', 'N/A')}",
    )
else:
    if fred_configured:
        st.info("Key indicators data temporarily unavailable — one or more FRED series may be experiencing delays. Other charts above should be available.")
    else:
        st.info("Key indicators unavailable — FRED_API_KEY not configured.")

# ═══════════════════════════════════════════════════════════════════════════════
# AI MACRO NARRATIVE — fragment so Regenerate only re-renders this section
# ═══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _macro_ai_narrative():
    import re

    def _clean_macro(text) -> str:
        if isinstance(text, list):
            return "  \n".join(str(x).strip(" \"'{}[]") for x in text if x)
        s = str(text or "").strip()
        s = s.replace("\\n", "\n").replace("\\t", "  ")
        s = s.replace('\\"', '"').replace("\\'", "'")
        s = re.sub(r'^[\s\"\'\[\{]+', '', s)
        s = re.sub(r'[\s\"\'\]\}]+$', '', s)
        s = re.sub(r'\\u[0-9a-fA-F]{4}', '', s)
        return s.strip()

    st.markdown("## 🤖 AI Macro Analysis")
    st.caption("Powered by Groq (llama-3.1-8b-instant) with Claude fallback · 4-hour cache")

    # Regenerate button FIRST — clears cache before fetch block below runs
    _, regen_col = st.columns([5, 1])
    with regen_col:
        if st.button("🔄 Regenerate", key="macro_regen"):
            st.session_state.pop("macro_ai", None)
            st.session_state["macro_force_refresh"] = True
            st.rerun(scope="fragment")   # fragment reruns → cache miss → fresh fetch

    force_refresh = st.session_state.pop("macro_force_refresh", False)
    if "macro_ai" not in st.session_state:
        label = "Regenerating AI narrative…" if force_refresh else "Generating AI macro narrative…"
        with st.spinner(label):
            try:
                params = {}
                if force_refresh:
                    params["refresh"] = "true"   # backend skips its 4h cache
                r = requests.get(f"{BACKEND_URL}/api/ai/macro-context", params=params, timeout=60)
                if r.status_code == 200:
                    st.session_state["macro_ai"] = r.json()
            except Exception as e:
                st.session_state["macro_ai"] = {"error": str(e)}

    ai = st.session_state.get("macro_ai", {})

    if ai and not ai.get("error") and ai.get("summary"):
        model_used   = ai.get("model_used", "unknown")
        gen_at       = ai.get("generated_at", "")
        stance       = ai.get("stance", "Neutral")
        stance_color = {"Risk-On": "#26a69a", "Risk-Off": "#ef5350"}.get(stance, "#FF9800")

        st.caption(f"Model: **{model_used}** · Generated: {gen_at[:16] if gen_at else 'N/A'}")
        st.markdown(
            f"**Market Stance:** "
            f"<span style='color:{stance_color};font-weight:bold;font-size:1.1em'>{stance}</span>",
            unsafe_allow_html=True,
        )
        st.markdown("#### Macro Environment Summary")
        st.markdown(_clean_macro(ai.get("summary", "")))

        equity_impact = ai.get("equity_impact")
        if equity_impact:
            st.markdown("#### Implications for Equities")
            st.info(_clean_macro(equity_impact))

        risks = ai.get("risks", [])
        if risks:
            st.markdown("#### Key Risks to Watch")
            risk_list = risks if isinstance(risks, list) else [risks]
            for i, risk in enumerate(risk_list, 1):
                st.markdown(f"{i}. {_clean_macro(risk)}")

    elif ai and ai.get("error"):
        err_str = str(ai.get("error", ""))
        if "timeout" in err_str.lower() or "timed out" in err_str.lower():
            st.warning("AI narrative timed out — Groq API is slow. Click 🔄 Regenerate to retry.")
        elif not os.getenv("GROQ_API_KEY") and not os.getenv("GEMINI_API_KEY"):
            st.warning("AI narrative unavailable — add `GROQ_API_KEY` or `GEMINI_API_KEY` to your `.env` file.")
        else:
            st.warning("AI narrative temporarily unavailable. Click 🔄 Regenerate to retry.")
        st.caption(f"Details: {err_str[:300]}")
    else:
        st.info("AI analysis will appear here — add GROQ_API_KEY to .env to enable.")


_macro_ai_narrative()

st.markdown("---")
st.caption(
    "⚠️ AI-generated content is for informational purposes only. Not financial advice.  |  "
    "Data sourced from FRED (Federal Reserve Bank of St. Louis) · Updated daily  |  "
    "Series: DGS3MO, DGS2/5/10/30, CPIAUCSL, PCEPI, PPIFIS, FEDFUNDS, "
    "A191RL1Q225SBEA, UNRATE, UMCSENT, NAPM"
)
