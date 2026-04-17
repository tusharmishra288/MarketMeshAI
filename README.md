# MarketMesh AI

> Production-grade, multi-region stock intelligence platform powered by 6 MCP agent servers, XGBoost ML prediction, dual-LLM AI analysis, and real-time data from 31 global exchanges.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109%2B-009688?logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.37%2B-FF4B4B?logo=streamlit&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-1.0%2B-6366f1)
![GCP](https://img.shields.io/badge/Deploy-GCP%20e2--micro-4285F4?logo=googlecloud&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Features](#features)
4. [Tech Stack](#tech-stack)
5. [Project Structure](#project-structure)
6. [Local Development](#local-development)
7. [Environment Variables](#environment-variables)
8. [Docker (Local)](#docker-local)
9. [API Reference](#api-reference)
10. [MCP Servers](#mcp-servers)
11. [Data Pipeline & Fallback Chains](#data-pipeline--fallback-chains)
12. [AI & ML Components](#ai--ml-components)
13. [Frontend Pages](#frontend-pages)
14. [Caching Strategy](#caching-strategy)
15. [GCP Deployment — GitHub Actions Only](#gcp-deployment--github-actions-only)
16. [Firestore Watchlist Persistence](#firestore-watchlist-persistence)

---

## Overview

MarketMesh AI aggregates real-time and end-of-day equity data from **31 exchanges across 26 countries**, enriches it with AI-powered company analysis, XGBoost price-direction prediction, IsolationForest anomaly detection, and FRED macroeconomic context, and presents everything through a clean Streamlit interface.

The platform is built on the **Model Context Protocol (MCP)** — each of the six specialised agent servers (Americas, Europe, Asia-Pacific, MENA, Analytics, Economics) runs as a managed `stdio` subprocess under a central FastAPI orchestrator. The orchestrator routes requests to the right server, applies L1 in-memory caching, and exposes a unified 26-endpoint REST API.

**Persistence:**
- **Local development** — in-memory (data clears on restart)
- **GCP cloud** — Cloud Firestore for watchlist and price alerts (free tier, zero-ops)

**Deployment model:** Every push to `main` triggers a GitHub Actions workflow that writes `.env` from repository secrets and runs `docker compose` on the GCP VM — no manual SSH, no local `gcloud` CLI needed.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      Streamlit Frontend                       │
│   5 pages: Dashboard · Overview · Explorer · Charts · Macro  │
└───────────────────────────┬──────────────────────────────────┘
                            │  HTTP / REST (port 8000)
┌───────────────────────────▼──────────────────────────────────┐
│                   FastAPI Orchestrator                        │
│   7 routers · L1 in-memory cache · Rate limiter              │
│   26 REST endpoints · CORS enabled                           │
└──┬──────┬───────┬──────┬──────────┬────────────────────────  ┘
   │      │       │      │          │            │
   ▼      ▼       ▼      ▼          ▼            ▼
[Americas][Europe][Asia] [MENA] [Analytics]  [Economics]
  MCP      MCP     MCP    MCP      MCP           MCP
  stdio    stdio   stdio  stdio    stdio         stdio
   │        │       │      │         │              │
Finnhub  yfinance yfinance yfinance yfinance    FRED API
  +yf                              +XGBoost    (UNRATE, CPI
                                   +IsoForest   GDP, PMI
                                   +SHAP        Fed Rate)
                                                     │
                                        ┌────────────▼───────┐
                                        │  Cloud Firestore    │
                                        │  (watchlist +       │
                                        │   price alerts)     │
                                        │  GCP only — ADC     │
                                        │  In-memory locally  │
                                        └────────────────────┘
```

### Key design decisions

| Decision | Rationale |
|---|---|
| MCP stdio subprocesses | Each server owns one domain; failures are isolated. The orchestrator runs in degraded mode if one server fails — never a full crash. |
| L1 in-memory cache only | TTL dict in the orchestrator process. Fast, zero dependencies. No Redis needed — reduces RAM on e2-micro by ~128 MB and removes a container entirely. |
| Firestore for persistence | Schema-free, zero-ops, generous free tier (1 GB / 50 K reads / 20 K writes per day). Works seamlessly with GCP ADC — no credentials file needed on the VM. Falls back to in-memory when `GCP_PROJECT_ID` is not set. |
| Dual-LLM (Groq → Gemini) | Groq `llama-3.1-8b-instant` is sub-200 ms on the free tier. Gemini 2.0 Flash activates automatically on Groq timeout (>15 s) or rate limit. |
| GitHub Actions-only deployment | No local `gcloud` CLI needed. A service account key in GitHub Secrets authenticates the workflow, which provisions infrastructure, derives SSH keys, writes `.env`, and runs `docker compose` — entirely from the browser. |

---

## Features

- **Real-time & EOD quotes** — 31 exchanges, 26 countries, 40,000+ companies via yfinance + Finnhub
- **4 regional MCP agents** — Americas, Europe, Asia-Pacific, MENA — each with quotes, fundamentals, OHLCV history, and news
- **Company name search** — Alpha Vantage SYMBOL_SEARCH; "Use this ticker" auto-fills exchange from suffix mapping (`.L` → LSE, `.T` → TSE, etc.)
- **Company deep dive** — P/E, EPS, P/B, PEG, ROE, Beta, 52-week range, dividend yield, AI outlook, news with sentiment, anomaly banner
- **Technical charts** — candlestick + volume, SMA 20/50/200, Bollinger Bands, RSI (70/30), MACD histogram
- **XGBoost ML prediction** — next-day direction, calibrated confidence (~54% backtest accuracy), SHAP feature importance
- **IsolationForest anomaly detection** — flags price gaps >5 % and volume spikes >3σ
- **Factor exposure radar** — Value, Momentum, Quality, Low-Volatility (0–100 per factor)
- **Cross-market correlation heatmap** — 30-day return matrix + regime badge (Risk-On / Risk-Off / Rotation)
- **US Sector ETF performance** — XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLB, XLRE, XLU
- **FRED macro dashboard** — yield curve, CPI/PCE/PPI, Fed rate, GDP, unemployment, consumer sentiment
- **AI macro narrative** — Groq-generated plain-English interpretation, regenerate button
- **Persistent watchlist** — Firestore on GCP, in-memory locally; one-click navigate to Company Explorer
- **Price alerts** — stored in Firestore (GCP) or in-memory (local)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Streamlit 1.37+, Plotly 5, pydeck |
| Backend | FastAPI 0.109+, uvicorn (ASGI) |
| Agent protocol | MCP (Model Context Protocol) 1.0 — stdio transport |
| ML / prediction | XGBoost 2.1, scikit-learn 1.5, SHAP 0.46 |
| Technical analysis | `ta` library (RSI, MACD, Bollinger Bands, ATR, EMA/SMA) |
| Anomaly detection | `sklearn.ensemble.IsolationForest` |
| Factor analysis | statsmodels 0.14 |
| AI — primary | Groq `llama-3.1-8b-instant` |
| AI — fallback | Google Gemini 2.0 Flash |
| Data — equities | yfinance (global EOD + fundamentals), Finnhub (real-time US) |
| Data — enrichment | Alpha Vantage OVERVIEW + SYMBOL_SEARCH |
| Data — news | Marketaux → yfinance.news → DuckDuckGo (cascade fallback) |
| Data — macro | FRED API (`fredapi`) |
| Cache | Python dict with TTL — L1 in-memory only (no Redis) |
| Persistence | Cloud Firestore (GCP) / in-memory fallback (local) |
| Deployment | Docker Compose, GCP e2-micro (Always Free) |
| CI/CD | GitHub Actions — provision + deploy workflows, service account auth |

---

## Project Structure

```
multi-region-stock-ai/
│
├── backend/
│   ├── orchestrator.py            # FastAPI entry point; lifespan MCP startup; router registration
│   ├── Dockerfile
│   ├── helpers/
│   │   ├── mcp_client.py          # _sessions pool, mcp_call() dispatcher, 30 s init timeout
│   │   ├── cache_helpers.py       # _mem_cache dict, _mem_get(), _mem_set() — L1 TTL cache
│   │   ├── market_helpers.py      # EXCHANGE_REGION map, _market_status(), _get_region()
│   │   ├── enrichment.py          # _enrich_with_alpha_vantage(), _compute_factors()
│   │   ├── ai_helpers.py          # _ai_company_summary() — Groq primary, Gemini fallback
│   │   └── services.py            # Shared singletons: rate_limiter, validator
│   ├── routes/
│   │   ├── system.py              # GET /, /health, /api/validation/stats, /mcp/tools/{region}
│   │   ├── market.py              # GET /api/quote, /fundamentals, /global-snapshot, /news, /search
│   │   ├── analytics.py           # GET /api/history, /technicals, /predict, /anomalies, /factors
│   │   ├── intelligence.py        # GET /api/intelligence/correlation, /sector-performance, /peers
│   │   ├── macro.py               # GET /api/macro/{indicator}, /api/ai/macro-context
│   │   ├── ai.py                  # GET /api/ai/company-summary/{ticker}
│   │   └── user_data.py           # GET/POST/DELETE /api/watchlist, /api/alerts
│   └── services/
│       ├── database.py            # Firestore (GCP) primary + in-memory fallback
│       ├── cache_manager.py       # No-op stub (Redis removed)
│       ├── rate_limiter.py        # Per-source token-bucket rate limiter
│       └── validator.py           # Multi-source data quality validator
│
├── frontend/
│   ├── app.py                     # st.set_page_config + sidebar watchlist + st.navigation
│   ├── utils.py                   # ALL_EXCHANGES, exchange display names, search_result_to_exchange()
│   ├── Dockerfile
│   └── pages/
│       ├── home.py                # Market Dashboard — live quote strip, global snapshot
│       ├── global_overview.py     # Global Overview — correlation heatmap, sector performance
│       ├── company_explorer.py    # Company Explorer — quote, financials, AI, news, technicals
│       ├── stock_charts.py        # Stock Charts — candlestick, technicals, ML prediction
│       └── macro_dashboard.py     # Macro Dashboard — FRED charts + AI narrative
│
├── mcp_servers/
│   ├── americas/server.py         # NYSE, NASDAQ, TSX, AMEX — Finnhub + yfinance
│   ├── europe/server.py           # LSE, XETRA, EPA, AMS, SWX, BIT, MCE, OSL, HEL
│   ├── asia_pacific/server.py     # TSE, HKEX, SSE, SZSE, NSE, BSE, ASX, SGX, KRX, TWSE
│   ├── mena/server.py             # TADAWUL, DFM, ADX, TASE, EGX, DSM
│   ├── analytics/server.py        # OHLCV, technical indicators, XGBoost, IsolationForest, SHAP
│   └── economics/server.py        # FRED: yield curve, inflation, Fed rate, GDP, PMI
│
├── deploy/
│   └── gcp/
│       ├── vm-startup.sh          # First-boot script: 2 GB swap + Docker + repo clone
│       └── nginx.conf             # Optional Nginx reverse proxy config (HTTPS)
│
├── .github/
│   └── workflows/
│       ├── provision-gcp.yml      # Run once: create VM + Firestore + static IP + SSH key upload
│       └── deploy-gcp.yml         # On push to main: write .env + docker compose up
│
├── docker-compose.yml             # Local development (no Redis, in-memory cache)
├── docker-compose-gcp.yml         # GCP cloud (Firestore, mem_limit, no Redis)
├── requirements.txt
└── .env                           # All local secrets — .gitignore'd, never committed
```

---

## Local Development

### Prerequisites

- Python 3.11+
- Git

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/MarketMeshAI.git
cd MarketMeshAI

python -m venv venv
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 2. Configure .env

`.env` is already present in the repo root and `.gitignore`'d — it will never be committed. Open it and fill in your API keys:

```
FINNHUB_API_KEY=your_key
ALPHA_VANTAGE_KEY=your_key
MARKETAUX_API_KEY=your_key
FRED_API_KEY=your_key
GROQ_API_KEY=your_key
GEMINI_API_KEY=your_key

# Leave empty for local — uses in-memory fallback
GCP_PROJECT_ID=
```

See [Environment Variables](#environment-variables) for the full list.

### 3. Start the backend

```bash
cd backend
python orchestrator.py
# FastAPI starts on http://localhost:8000
# 6 MCP servers spawn as subprocesses (~10–20 s to initialise)
# Confirm all 6 are connected: http://localhost:8000/health
```

### 4. Start the frontend

Open a second terminal:

```bash
cd frontend
streamlit run app.py
# Opens http://localhost:8501
```

---

## Environment Variables

All values live in `.env` (local) or GitHub Secrets (cloud). The file is `.gitignore`'d and never committed.

| Variable | Required | Local | Cloud (GCP) | Description |
|---|---|---|---|---|
| `FINNHUB_API_KEY` | ✅ | Set in `.env` | GitHub Secret | Real-time US quotes — [finnhub.io](https://finnhub.io/register) |
| `ALPHA_VANTAGE_KEY` | ✅ | Set in `.env` | GitHub Secret | Fundamentals + search — [alphavantage.co](https://www.alphavantage.co/support/#api-key) (25/day) |
| `MARKETAUX_API_KEY` | ✅ | Set in `.env` | GitHub Secret | News + sentiment — [marketaux.com](https://www.marketaux.com/account/signup) (100/day) |
| `FRED_API_KEY` | ✅ | Set in `.env` | GitHub Secret | Macro data — [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `GROQ_API_KEY` | ✅ | Set in `.env` | GitHub Secret | Primary AI LLM — [console.groq.com](https://console.groq.com) (30 req/min) |
| `GEMINI_API_KEY` | ✅ | Set in `.env` | GitHub Secret | Fallback AI LLM — [aistudio.google.com](https://aistudio.google.com/apikey) |
| `GCP_PROJECT_ID` | ⬜ | Empty → in-memory | GitHub Secret → Firestore | GCP project ID — enables Firestore watchlist/alerts |
| `BACKEND_HOST` | ⬜ | `0.0.0.0` | `0.0.0.0` | FastAPI bind host |
| `BACKEND_PORT` | ⬜ | `8000` | `8000` | FastAPI port |
| `STREAMLIT_PORT` | ⬜ | `8501` | `8501` | Streamlit port |

> **No Redis variables.** Redis has been removed. Caching is L1 in-memory only.

---

## Docker (Local)

```bash
# Build and start (orchestrator + frontend)
docker compose up -d

# Tail logs
docker compose logs -f orchestrator

# Rebuild after code changes
docker compose up -d --build

# Stop
docker compose down
```

`docker-compose.yml` runs both services with in-memory cache and no Redis.  
`docker-compose-gcp.yml` is used by GitHub Actions on the GCP VM — adds `mem_limit`, longer `start_period`, and passes `GCP_PROJECT_ID` for Firestore.

---

## API Reference

Full interactive docs at `http://localhost:8000/docs`.

### System

| Method | Path | Description |
|---|---|---|
| GET | `/` | Version + MCP session status |
| GET | `/health` | MCP server status, L1 cache key count, rate limiter state |
| GET | `/mcp/tools/{region}` | List tools on a specific MCP server |
| GET | `/api/validation/stats` | In-memory cache key count and quality stats |

### Market Data

| Method | Path | Description |
|---|---|---|
| GET | `/api/quote/{ticker}` | Live / EOD quote. `?exchange=NASDAQ&use_cache=true` |
| GET | `/api/fundamentals/{ticker}` | P/E, EPS, P/B, PEG, ROE, Beta, 52W range. `?exchange=LSE` |
| GET | `/api/global-snapshot` | Top indices from all 4 regions + market status |
| GET | `/api/news/{ticker}` | News with sentiment. 4-stage fallback. `?exchange=TSE` |
| GET | `/api/search` | Company search. `?query=Apple&limit=10` |

### Analytics

| Method | Path | Description |
|---|---|---|
| GET | `/api/history/{ticker}` | OHLCV candles. `?exchange=HKEX&period=1y` |
| GET | `/api/technicals/{ticker}` | RSI, MACD, Bollinger Bands, SMA 20/50/200. `?period=6mo` |
| GET | `/api/predict/{ticker}` | XGBoost direction + confidence + SHAP values |
| GET | `/api/anomalies/{ticker}` | IsolationForest price/volume anomaly list |
| GET | `/api/factors/{ticker}` | Value, Momentum, Quality, Low-Vol scores (0–100) |

### Intelligence

| Method | Path | Description |
|---|---|---|
| GET | `/api/intelligence/correlation` | 30-day cross-market correlation matrix + regime |
| GET | `/api/sector-performance` | US sector ETF returns. `?period=1mo` |
| GET | `/api/peers/{ticker}` | Sector peers with live quotes. `?exchange=NASDAQ` |

### Macro (FRED)

| Method | Path | Description |
|---|---|---|
| GET | `/api/macro/yield_curve` | US Treasury yields (3M, 2Y, 5Y, 10Y, 30Y) |
| GET | `/api/macro/inflation` | CPI, PCE, PPI time series |
| GET | `/api/macro/fed_rate` | Federal funds rate history |
| GET | `/api/macro/gdp` | Real GDP quarterly growth |
| GET | `/api/macro/indicators` | Unemployment, consumer sentiment, ISM PMI |
| GET | `/api/ai/macro-context` | Groq-generated macro narrative |

### AI

| Method | Path | Description |
|---|---|---|
| GET | `/api/ai/company-summary/{ticker}` | Outlook, risks, technical view, sentiment stance |

### User Data (Watchlist & Alerts)

| Method | Path | Description |
|---|---|---|
| GET | `/api/watchlist` | List all watchlist entries |
| POST | `/api/watchlist` | Add entry. `?ticker=AAPL&exchange=NASDAQ` |
| DELETE | `/api/watchlist/{ticker}` | Remove. `?exchange=NASDAQ` |
| GET | `/api/alerts` | List active alerts. `?ticker=AAPL` |
| POST | `/api/alerts` | Create alert. `?ticker=AAPL&threshold=200&direction=up` |
| DELETE | `/api/alerts/{alert_id}` | Delete alert by ID |

---

## MCP Servers

Each server is a standalone Python process in `mcp_servers/<name>/server.py`, launched by the orchestrator at startup via the MCP stdio transport. Each has a 30-second initialisation timeout. A failed server is marked `"timeout"` or `"error"` in `/health` but does not abort startup — the app continues in degraded mode.

| Server | Exchanges | Key Tools | Data Sources |
|---|---|---|---|
| `americas` | NYSE, NASDAQ, TSX, AMEX | `get_real_time_quote`, `get_company_fundamentals`, `get_historical_data`, `get_news`, `search_companies`, `get_batch_quotes` | Finnhub (real-time), yfinance (EOD + fundamentals) |
| `europe` | LSE, XETRA, EPA, AMS, SWX, BIT, MCE, OSL, HEL | same tool set | yfinance with `.L` `.DE` `.PA` `.AS` `.SW` `.MI` `.MC` `.OL` `.HE` suffixes |
| `asia_pacific` | TSE, HKEX, SSE, SZSE, NSE, BSE, ASX, SGX, KRX, TWSE | same tool set | yfinance with `.T` `.HK` `.SS` `.SZ` `.NS` `.BO` `.AX` `.SI` `.KS` `.TW` suffixes |
| `mena` | TADAWUL, DFM, ADX, TASE, EGX, DSM | same tool set | yfinance with `.SR` `.DU` `.AD` `.TA` `.CA` suffixes |
| `analytics` | Global (all exchanges via yfinance) | `get_price_history`, `compute_technical_indicators`, `predict_price_direction`, `detect_anomalies`, `get_sector_performance` | yfinance, XGBoost, IsolationForest, ta, SHAP |
| `economics` | US macro (FRED) | `get_yield_curve`, `get_inflation_data`, `get_fed_rate`, `get_gdp_growth`, `get_macro_indicators` | FRED API via `fredapi` |

### How MCP servers start

```python
# backend/helpers/mcp_client.py (simplified)
script = os.path.join(SERVERS_DIR, region, "server.py")
params = StdioServerParameters(command=sys.executable, args=[script], env=dict(os.environ))
read, write = await stack.enter_async_context(stdio_client(params))
session     = await stack.enter_async_context(ClientSession(read, write))
await session.initialize()
_sessions[region]       = session
_session_status[region] = "connected"
```

---

## Data Pipeline & Fallback Chains

### Quote — `/api/quote/{ticker}`

```
1. L1 in-memory cache (TTL: 60 s)
2. Regional MCP → Finnhub real-time  (Americas only)
3. Regional MCP → yfinance EOD       (all other regions)
```

### Fundamentals — `/api/fundamentals/{ticker}`

```
1. L1 in-memory cache (TTL: 3600 s)
2. Regional MCP → yfinance .info
3. Alpha Vantage OVERVIEW enrichment (PE, ROE, EPS layered on top)
```

### News — `/api/news/{ticker}`

```
1. Marketaux entity search  (symbols={ticker})
2. Marketaux text search    (search={company_name})   ← if 0 results
3. yfinance .news           (ticker-specific, no key) ← if still 0
4. DuckDuckGo web search    ("{company} stock news")  ← final fallback
```

### AI Company Summary — `/api/ai/company-summary/{ticker}`

```
1. L1 cache (TTL: 24 h)
2. Parallel fetch: fundamentals + quote + news + technicals
3. Groq llama-3.1-8b-instant   (timeout: 15 s)
4. Google Gemini 2.0 Flash     ← automatic fallback on timeout or rate limit
```

### Macro Indicators — `/api/macro/indicators`

```
Each FRED series (UNRATE, UMCSENT, NAPM) fetched independently.
One series failing does not block the others — partial data is returned.
```

---

## AI & ML Components

### Dual-LLM AI Analysis

- **Primary:** Groq `llama-3.1-8b-instant` — sub-200 ms, 30 req/min free tier
- **Fallback:** Google Gemini 2.0 Flash — activates on Groq timeout (>15 s) or HTTP 429
- **Output fields:** `summary`, `technical_view`, `risks` (list of 3), `sentiment_context`, `model_used`, `generated_at`
- **Cache TTL:** 24 hours per ticker — overridable via the "🔄 Regenerate" button in the UI

### XGBoost Price Direction Prediction

- **Features (16):** RSI-14, MACD histogram, Bollinger Band %, volume Z-score, ATR-14, SMA 20/50/200 ratios, 5/10/20-day return, 6M momentum
- **Target:** Binary next-day direction (up / down)
- **Training:** Walk-forward validation on 2 years of daily OHLCV data
- **Output:** `direction`, `confidence` (0–1), `backtest_accuracy` (~0.54), `top_features` (SHAP values)
- **UI disclaimer:** "Not financial advice. Historical accuracy: ~54%"

### IsolationForest Anomaly Detection

- **Features:** Daily price % change, volume Z-score vs 30-day mean
- **Flags:** Volume spikes >3σ, overnight gaps >5%, RSI divergence from price trend
- **Output:** List of `{date, type, severity, description}` dicts
- **UI:** Anomaly banner above tabs in Company Explorer when recent events detected

### Factor Exposure Model

Scores each stock 0–100 on four Fama-French-inspired factors, rendered as a Plotly radar chart:

| Factor | Signal |
|---|---|
| Value | P/E and P/B percentile vs sector (lower ratio = higher score) |
| Momentum | 6-month and 1-year price return |
| Quality | ROE and profit margin from Alpha Vantage OVERVIEW |
| Low-Volatility | 6-month realised daily return standard deviation (lower = better) |

---

## Frontend Pages

### 1. Market Dashboard (`home.py`)

- Live quote strip for major indices across all 4 regions
- Quick quote lookup with exchange selector and company name search expander
- Market open/closed status per region (pytz-aware, DST-correct)
- One-click navigate to Company Explorer from watchlist or index card

### 2. Global Overview (`global_overview.py`)

- Cross-market 30-day return correlation heatmap (Plotly)
- Market regime badge: Risk-On / Risk-Off / Rotation
- US Sector ETF performance bar chart (XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLB, XLRE, XLU)
- Configurable period selector

### 3. Company Explorer (`company_explorer.py`)

Five tabs:

| Tab | Content |
|---|---|
| Quote | Price, change %, volume, market cap, 52W range, data source badge |
| Financials | P/E, EPS, P/B, PEG, ROE, Beta + factor radar + sector peers |
| AI Analysis | Groq/Gemini outlook, technical momentum, 3 risk factors, sentiment stance badge |
| News | Up to 10 articles, source badge (Marketaux / Yahoo / Finnhub / Web), 🔵 Unscored for null sentiment |
| Technical | RSI, MACD, anomaly alerts |

### 4. Stock Charts (`stock_charts.py`)

- Candlestick + volume (Plotly)
- Toggleable overlays: SMA 20/50/200, Bollinger Bands
- Sub-panels: RSI (70/30 lines), MACD histogram
- Period: 1 Month / 3 Months / 6 Months / 1 Year / 5 Years (auto-renders on change, no load button)
- XGBoost prediction panel: confidence bar + SHAP feature importance bar chart
- CSV download button

### 5. Macro Dashboard (`macro_dashboard.py`)

- US Yield curve chart (current vs 1 year ago, Plotly line)
- Inflation trends: CPI, PCE, PPI (line chart)
- Federal funds rate history (line chart)
- Real GDP quarterly growth (bar chart)
- Key indicators: unemployment rate, consumer sentiment, ISM PMI
- AI macro narrative: Groq-generated plain-English context, "🔄 Regenerate" button

---

## Caching Strategy

```
Request
  │
  ▼
L1 In-Memory Cache (_mem_cache dict with TTL)
  │  HIT → return immediately
  │  MISS ↓
  ▼
MCP Server Call → External API
  │
  ▼
Store in L1 cache
  │
  ▼
Return response
```

| Endpoint | TTL |
|---|---|
| Quote | 60 s |
| Technicals | 300 s |
| Fundamentals | 3600 s |
| Global snapshot | 300 s |
| AI company summary | 86400 s (24 h) |
| Factor scores | 86400 s |
| News / search | 86400 s |
| Macro data | 3600 s |

**No Redis.** Removing Redis saves ~128 MB RAM on the e2-micro VM and eliminates a container. The L1 in-memory cache is sufficient for the free-tier usage pattern (one VM, one orchestrator process).

---

## GCP Deployment — GitHub Actions Only

> **Everything runs from your browser.** No local `gcloud` CLI, no manual SSH into the VM, no `.env` file copying. Two GitHub Actions workflows handle all infrastructure and deployment.

### Prerequisites

Before running any workflow, add **9 GitHub Secrets** to your repo:  
**Settings → Secrets and variables → Actions → New repository secret**

---

#### Secret 1 — `GCP_SA_KEY`

A service account JSON key that lets GitHub Actions authenticate with GCP.

**In GCP Console:**

1. **IAM & Admin → Service Accounts → Create Service Account**
2. Name: `marketmesh-deploy` → **Create and continue**
3. Grant these 5 roles:
   - `Compute Admin`
   - `Service Account User`
   - `Cloud Datastore Owner`
   - `Project IAM Admin`
   - `Service Usage Admin`
4. **Done** → click the new service account → **Keys → Add Key → JSON → Create**
5. A `.json` file downloads — open it, select all, copy the entire content
6. Paste as the `GCP_SA_KEY` secret value

---

#### Secret 2 — `GCP_PROJECT_ID`

Your GCP project ID (visible in the Console top bar, e.g. `marketmesh-ai-461023`).

---

#### Secret 3 — `GCP_SSH_KEY`

An SSH private key that GitHub Actions uses to connect to the VM.  
Generate it in **GCP Cloud Shell** (click `>_` in the GCP Console top bar — no local install needed):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/marketmesh_gcp -C "github-actions" -N ""
cat ~/.ssh/marketmesh_gcp
```

Copy the entire output (including `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END OPENSSH PRIVATE KEY-----`) and paste it as the `GCP_SSH_KEY` secret.

> The provision workflow derives the public key from this private key automatically and uploads it to the VM. You never manually manage the public key.

---

#### Secrets 4–9 — Application API Keys

| Secret | Get it from | Free tier |
|---|---|---|
| `FINNHUB_API_KEY` | [finnhub.io/register](https://finnhub.io/register) | 60 req/min |
| `ALPHA_VANTAGE_KEY` | [alphavantage.co/support/#api-key](https://www.alphavantage.co/support/#api-key) | 25 req/day |
| `MARKETAUX_API_KEY` | [marketaux.com/account/signup](https://www.marketaux.com/account/signup) | 100 req/day |
| `FRED_API_KEY` | [fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html) | 120 req/min |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) | 30 req/min |
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Free |

---

### Workflow 1 — Provision (run once)

**Actions → "1 - Provision GCP VM (run once)" → Run workflow → Run workflow**

What it does automatically (~2 min):

| Step | Detail |
|---|---|
| Create VM | e2-micro, Ubuntu 22.04, 30 GB HDD, `us-central1-a` |
| VM first-boot script | Installs Docker, creates 2 GB swap, clones repo (runs in background) |
| Upload SSH key | Derives public key from `GCP_SSH_KEY`, uploads with username `marketmesh` |
| Enable Firestore API | One-time per project |
| Grant IAM | `roles/datastore.user` to the VM's Compute Engine service account |
| Create Firestore DB | Native mode, `nam5` region |
| Reserve static IP | `marketmesh-ip` — so the VM IP never changes on restart |
| Open firewall | Ports 80, 443, 8000, 8501 |

End of the workflow log shows:

```
════════════════════════════════════════════════════════
 Provisioning complete!
 VM External IP : 34.XX.XX.XX  (static)
 ✅ Firestore, static IP, firewall — all configured.
 ⚠️  Wait ~3 minutes for Docker install to finish on VM.
    Then push to main to trigger the deploy workflow.
════════════════════════════════════════════════════════
```

**Wait ~3 minutes** after this workflow finishes (the VM startup script is still installing Docker in the background). Then proceed to Workflow 2.

---

### Workflow 2 — Deploy (every push to main)

Push any commit to `main`, or trigger manually: **Actions → "2 - Deploy to GCP" → Run workflow**

```bash
git add .
git commit -m "initial deploy"
git push origin main
```

What it does automatically:

| Step | Detail |
|---|---|
| Authenticate | Uses `GCP_SA_KEY` to log in to GCP |
| Get VM IP | Queries GCP dynamically — no `GCP_VM_IP` secret needed |
| Write `.env` | SSHs as `marketmesh` → writes `/opt/marketmesh/.env` from all 6 app secrets |
| Pull code | `git reset --hard origin/main` |
| Build & start | `docker compose -f docker-compose-gcp.yml build` + `up -d` |
| Health poll | Waits up to 3 min for orchestrator to report `healthy` |
| Final check | `GET /health` from the Actions runner → must return HTTP 200 |

**First build: 8–10 minutes** (downloading all Python packages on e2-micro CPU).  
**Subsequent deploys: 2–3 minutes** (Docker layer cache).

A green checkmark = the app is live.

---

### Access the App

Use the static IP from the provision workflow log:

| Service | URL |
|---|---|
| **Streamlit UI** | `http://EXTERNAL_IP:8501` |
| **FastAPI docs** | `http://EXTERNAL_IP:8000/docs` |
| **Health check** | `http://EXTERNAL_IP:8000/health` |

---

### Optional: HTTPS with Nginx

This is the only time you SSH into the VM manually. Skip if you don't have a domain.

```bash
gcloud compute ssh marketmesh-vm --zone=us-central1-a
```

Inside the VM:

```bash
sudo cp /opt/marketmesh/deploy/gcp/nginx.conf /etc/nginx/sites-available/marketmesh
sudo ln -s /etc/nginx/sites-available/marketmesh /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d yourdomain.com    # free TLS certificate
```

`nginx.conf` routes `yourdomain.com` → Streamlit (port 8501) and `yourdomain.com/api/` → FastAPI (port 8000), with WebSocket support for Streamlit's live updates.

---

### Updating API keys

Change the GitHub Secret value → push any commit → the deploy workflow writes the new `.env` on the next run. No SSH into the VM required.

---

### Infrastructure summary

| Component | Detail |
|---|---|
| VM | e2-micro, 0.25 vCPU burst / 1 GB RAM + 2 GB swap |
| Disk | 30 GB standard persistent HDD |
| Region | `us-central1-a` (Always Free eligible) |
| Monthly cost | **$0** (Always Free tier) |
| Static IP | Reserved as `marketmesh-ip` |
| Firewall | `allow-marketmesh`: TCP 80, 443, 8000, 8501 |
| Docker | `docker-compose-gcp.yml`: orchestrator 700 MB limit, frontend 250 MB limit |
| Cache | L1 in-memory only (no Redis) |
| Persistence | Cloud Firestore — 1 GB / 50 K reads / 20 K writes per day free |

---

## Firestore Watchlist Persistence

On GCP, watchlist items and price alerts are stored in **Cloud Firestore (Native mode)**. Locally, an in-memory dict is used — data is lost on process restart.

### Collections schema

```
watchlist/
  {TICKER}_{EXCHANGE}            ← document ID, e.g. "AAPL_NASDAQ"
    ticker:    "AAPL"
    exchange:  "NASDAQ"
    added_at:  "2026-04-18T10:22:01+00:00"

alerts/
  {auto_id}
    ticker:     "AAPL"
    exchange:   "NASDAQ"
    threshold:  200.0
    direction:  "up"             ← "up" or "down"
    triggered:  false
    created_at: "2026-04-18T10:22:01+00:00"
```

### Authentication

**GCP VM:** The VM's Compute Engine service account provides **Application Default Credentials (ADC)** automatically — no key file needed. The provision workflow grants `roles/datastore.user` to this service account.

**Local development (optional):** To test Firestore locally:

```bash
gcloud auth application-default login
# Then set in .env:
GCP_PROJECT_ID=your-project-id
```

Leave `GCP_PROJECT_ID` empty to use the in-memory fallback.

### Fallback behaviour

`backend/services/database.py` checks `GCP_PROJECT_ID` at startup:

```python
if not project_id:
    logger.info("GCP_PROJECT_ID not set — watchlist stored in-memory")
    return   # _using_firestore stays False; all ops use the in-memory dict
```

Any Firestore connection error after a valid project ID is also caught — the app logs a warning and falls back silently. Watchlist items stored in-memory are lost on container restart.

---

## License

MIT — see `LICENSE` for details.
