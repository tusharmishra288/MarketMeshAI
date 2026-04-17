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
6. [Quick Start — Local Development](#quick-start--local-development)
7. [Environment Variables](#environment-variables)
8. [Docker Development](#docker-development)
9. [API Reference](#api-reference)
10. [MCP Servers](#mcp-servers)
11. [Data Pipeline & Fallback Chains](#data-pipeline--fallback-chains)
12. [AI & ML Components](#ai--ml-components)
13. [Frontend Pages](#frontend-pages)
14. [GCP Deployment (e2-micro Free Tier)](#gcp-deployment-e2-micro-free-tier)
15. [GitHub Actions CI/CD](#github-actions-cicd)
16. [Firestore Watchlist Persistence](#firestore-watchlist-persistence)

---

## Overview

MarketMesh AI aggregates real-time and end-of-day equity data from **31 exchanges across 26 countries**, enriches it with AI-powered company analysis, XGBoost price-direction prediction, IsolationForest anomaly detection, and FRED macroeconomic context, and presents everything through a clean Streamlit interface.

The platform is built on the **Model Context Protocol (MCP)** — each of the six specialised agent servers (Americas, Europe, Asia-Pacific, MENA, Analytics, Economics) runs as a managed `stdio` subprocess under a central FastAPI orchestrator. The orchestrator routes requests to the right server, applies two-tier caching (in-memory L1 + optional Redis L2), and exposes a unified 26-endpoint REST API consumed by the frontend.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Streamlit Frontend                       │
│       5 pages: Dashboard · Overview · Explorer ·            │
│                Charts · Macro Dashboard                      │
└──────────────────────────┬──────────────────────────────────┘
                           │  HTTP / REST (port 8000)
┌──────────────────────────▼──────────────────────────────────┐
│                  FastAPI Orchestrator                        │
│   7 routers · L1 in-memory cache · Rate limiter             │
│   26 REST endpoints · CORS enabled                          │
└──┬──────┬───────┬──────┬────────────┬───────────────────────┘
   │      │       │      │            │
   ▼      ▼       ▼      ▼            ▼            ▼
[Americas][Europe][Asia-Pac][MENA]  [Analytics]  [Economics]
  MCP      MCP      MCP     MCP       MCP           MCP
  stdio    stdio    stdio   stdio     stdio         stdio
   │        │        │       │          │             │
Finnhub  yfinance yfinance yfinance  yfinance     FRED API
  +yf                               +XGBoost      (UNRATE
                                    +IsoForest     CPI/PCE
                                    +SHAP          GDP
                                                   Fed Rate)
                       ↕  optional
               ┌───────────────┐     ┌────────────────┐
               │  Redis cache  │     │   Firestore DB  │
               │  (L2, 512 MB) │     │  (watchlist +   │
               └───────────────┘     │   price alerts) │
                                     └────────────────┘
```

### Key design decisions

| Decision | Rationale |
|----------|-----------|
| MCP stdio subprocesses | Each server owns one domain; failures are isolated. The orchestrator continues in degraded mode if one server fails to start. |
| Two-tier cache | L1 in-memory (TTL dict) runs without Redis. L2 Redis adds persistence across requests but is optional — the app falls back gracefully. |
| Dual-LLM (Groq → Gemini) | Groq `llama-3.1-8b-instant` is sub-200 ms on the free tier. Gemini 2.0 Flash activates automatically when Groq is rate-limited. |
| No Redux / no WebSockets | Streamlit's natural rerun model is sufficient. `st.fragment` handles the live quote strip without a full page reload. |
| Firestore for persistence | Schema-free, zero-ops, free tier (1 GB / 50 K reads / 20 K writes per day), and works seamlessly with GCP ADC — no credentials file needed on the VM. |

---

## Features

- **Real-time & EOD quotes** across 31 exchanges in 26 countries — 40,000+ companies via yfinance + Finnhub
- **4 regional MCP agents** — Americas, Europe, Asia-Pacific, MENA — each with quotes, fundamentals, historical OHLCV, and news
- **Company deep dive** — P/E, EPS, P/B, PEG, ROE, Beta, 52-week range, dividend yield, AI outlook, news with sentiment, anomaly alerts
- **Technical charts** — candlestick + volume, SMA 20/50/200, Bollinger Bands, RSI (70/30), MACD histogram (Plotly)
- **XGBoost ML prediction** — next-day direction with calibrated confidence, walk-forward backtest accuracy (~54%), SHAP feature importance
- **IsolationForest anomaly detection** — flags price gaps >5% and volume spikes >3σ
- **Factor exposure radar** — Value, Momentum, Quality, Low-Volatility (0–100 per factor vs sector peers)
- **Cross-market correlation heatmap** — 30-day return correlation across major indices; regime classification (Risk-On / Risk-Off / Rotation)
- **US Sector ETF performance** — XLK, XLF, XLE, XLV, etc. over configurable periods
- **FRED macro dashboard** — yield curve, CPI/PCE/PPI inflation, Fed funds rate, GDP growth, unemployment, consumer sentiment
- **AI macro narrative** — Groq-generated plain-English interpretation of current macro data
- **Persistent watchlist** — stored in Firestore (GCP) or in-memory (local); one-click navigation to Company Explorer
- **2-tier caching** — L1 in-memory (TTL) + optional L2 Redis
- **Company name search** — Alpha Vantage SYMBOL_SEARCH; "Use this ticker" auto-fills exchange via suffix mapping

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Streamlit 1.37+, Plotly 5, pydeck |
| Backend | FastAPI 0.109+, uvicorn (ASGI) |
| Agent protocol | MCP (Model Context Protocol) 1.0 — stdio transport |
| ML / prediction | XGBoost 2.1, scikit-learn 1.5, SHAP 0.46 |
| Technical analysis | `ta` library (RSI, MACD, Bollinger Bands, ATR, EMA/SMA) |
| Anomaly detection | `sklearn.ensemble.IsolationForest` |
| Factor analysis | statsmodels 0.14 |
| AI (primary) | Groq `llama-3.1-8b-instant` |
| AI (fallback) | Google Gemini 2.0 Flash |
| Data — equities | yfinance (global EOD), Finnhub (real-time US), Alpha Vantage (fundamentals) |
| Data — news | Marketaux, yfinance.news, DuckDuckGo web search |
| Data — macro | FRED API via `fredapi` |
| Persistence | Google Cloud Firestore (GCP) / in-memory fallback |
| Cache L1 | Python dict with TTL (in-process, always active) |
| Cache L2 | Redis 7 (optional, Docker service) |
| Deployment | Docker Compose, GCP e2-micro (Always Free) |
| CI/CD | GitHub Actions + `appleboy/ssh-action` |

---

## Project Structure

```
multi-region-stock-ai/
│
├── backend/
│   ├── orchestrator.py          # FastAPI entry point; lifespan MCP startup; router registration
│   ├── Dockerfile
│   ├── helpers/
│   │   ├── mcp_client.py        # _sessions pool, _start_mcp_server(), mcp_call() dispatcher
│   │   ├── cache_helpers.py     # _mem_cache dict, _mem_get(), _mem_set() with TTL
│   │   ├── market_helpers.py    # EXCHANGE_REGION map, _market_status(), _get_region()
│   │   ├── enrichment.py        # _enrich_with_alpha_vantage(), _compute_factors()
│   │   └── ai_helpers.py        # _ai_company_summary() — Groq + Gemini fallback
│   ├── routes/
│   │   ├── system.py            # GET /, /health, /api/validation/stats, /mcp/tools/{region}
│   │   ├── market.py            # GET /api/quote, /api/fundamentals, /api/global-snapshot, /api/news, /api/search
│   │   ├── analytics.py         # GET /api/history, /api/technicals, /api/predict, /api/anomalies, /api/factors
│   │   ├── intelligence.py      # GET /api/intelligence/correlation, /api/sector-performance, /api/peers
│   │   ├── macro.py             # GET /api/macro/{indicator}, /api/ai/macro-context
│   │   ├── ai.py                # GET /api/ai/company-summary/{ticker}
│   │   └── user_data.py         # GET/POST/DELETE /api/watchlist, /api/alerts
│   └── services/
│       ├── database.py          # Firestore primary + in-memory fallback
│       ├── cache_manager.py     # Redis L2 cache wrapper
│       ├── rate_limiter.py      # Per-source token-bucket rate limiter
│       └── validator.py         # Multi-source data quality validator
│
├── frontend/
│   ├── app.py                   # st.set_page_config + sidebar + st.navigation
│   ├── utils.py                 # ALL_EXCHANGES, EXCHANGE_SHORT_NAMES, search_result_to_exchange()
│   ├── Dockerfile
│   └── pages/
│       ├── home.py              # Market Dashboard — live quote strip, global snapshot
│       ├── global_overview.py   # Global Overview — correlation heatmap, sector performance
│       ├── company_explorer.py  # Company Explorer — quote, fundamentals, charts, AI, news
│       ├── stock_charts.py      # Stock Charts — candlestick, technicals, ML prediction
│       └── macro_dashboard.py   # Macro Dashboard — FRED charts + AI narrative
│
├── mcp_servers/
│   ├── americas/server.py       # NYSE, NASDAQ, TSX, AMEX — Finnhub + yfinance
│   ├── europe/server.py         # LSE, XETRA, EPA, AMS, SWX, BIT, MCE, OSL, HEL
│   ├── asia_pacific/server.py   # TSE, HKEX, SSE, SZSE, NSE, BSE, ASX, SGX, KRX, TWSE
│   ├── mena/server.py           # TADAWUL, DFM, ADX, TASE, EGX, DSM
│   ├── analytics/server.py      # OHLCV, technical indicators, XGBoost, IsolationForest
│   └── economics/server.py      # FRED: yield curve, inflation, Fed rate, GDP, PMI
│
├── deploy/
│   └── gcp/
│       ├── create-vm.sh         # One-command GCP e2-micro provisioning
│       ├── vm-startup.sh        # First-boot: swap + Docker + clone repo
│       └── nginx.conf           # Optional reverse proxy with HTTPS
│
├── .github/
│   └── workflows/
│       └── deploy-gcp.yml       # GitHub Actions CD: push to main → SSH deploy
│
├── docker-compose.yml           # Local / full-stack (includes Redis)
├── docker-compose-gcp.yml       # GCP e2-micro (no Redis, Firestore, mem limits)
├── requirements.txt
├── .env                         # All secrets — .gitignore'd, never committed
└── init.sql                     # PostgreSQL schema (legacy reference)
```

---

## Quick Start — Local Development

### Prerequisites

- Python 3.11+
- Git

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/MarketMeshAI.git
cd MarketMeshAI
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

`.env` is already present and `.gitignore`'d — it will never be committed. Open it and fill in your API keys:

```bash
# Windows
notepad .env

# macOS / Linux
nano .env
```

See the [Environment Variables](#environment-variables) section for what each key does. The `LOCAL DEVELOPMENT` comments in `.env` tell you which values to leave empty for local use.

### 3. Start the backend

```bash
cd backend
python orchestrator.py
# FastAPI starts on http://localhost:8000
# 6 MCP servers spawn as subprocesses (takes ~10–20 s)
# Visit http://localhost:8000/health to confirm all 6 are "connected"
```

### 4. Start the frontend (new terminal)

```bash
cd frontend
streamlit run app.py
# Streamlit opens on http://localhost:8501
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FINNHUB_API_KEY` | ✅ | Real-time US quotes. Free at [finnhub.io](https://finnhub.io) |
| `ALPHA_VANTAGE_KEY` | ✅ | Fundamentals + company search. Free at [alphavantage.co](https://www.alphavantage.co) (25 calls/day) |
| `MARKETAUX_API_KEY` | ✅ | News + sentiment. Free at [marketaux.com](https://www.marketaux.com) (100 calls/day) |
| `FRED_API_KEY` | ✅ | Macro data. Free at [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `GROQ_API_KEY` | ✅ | Primary AI LLM. Free at [console.groq.com](https://console.groq.com) (30 req/min) |
| `GEMINI_API_KEY` | ✅ | Fallback AI LLM. Free at [aistudio.google.com](https://aistudio.google.com/apikey) |
| `GCP_PROJECT_ID` | ⬜ | GCP project ID for Firestore watchlist persistence. Omit for in-memory. |
| `REDIS_HOST` | ⬜ | Redis host for L2 cache. Leave empty to use in-memory cache only. |
| `REDIS_PORT` | ⬜ | Redis port (default `6379`) |
| `POSTGRES_*` | ⬜ | PostgreSQL credentials (legacy, not used when Firestore is active) |
| `BACKEND_HOST` | ⬜ | FastAPI bind host (default `0.0.0.0`) |
| `BACKEND_PORT` | ⬜ | FastAPI port (default `8000`) |

---

## Docker Development

Full stack with Redis:

```bash
# Build and start all services (orchestrator + frontend + redis)
docker compose up -d

# Tail logs
docker compose logs -f orchestrator

# Stop
docker compose down
```

GCP-optimised (no Redis, Firestore persistence):

```bash
docker compose -f docker-compose-gcp.yml up -d
```

---

## API Reference

All endpoints are documented interactively at `http://localhost:8000/docs`.

### System

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Root — version and MCP session status |
| GET | `/health` | Full health check — MCP servers, cache stats, rate limits |
| GET | `/mcp/tools/{region}` | List tools registered on a specific MCP server |
| GET | `/api/validation/stats` | Cache hit rate and key counts |

### Market Data

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/quote/{ticker}` | Live or EOD quote. `?exchange=NASDAQ` |
| GET | `/api/fundamentals/{ticker}` | P/E, EPS, P/B, PEG, ROE, Beta, 52W range. `?exchange=LSE` |
| GET | `/api/global-snapshot` | Top indices from all 4 regions |
| GET | `/api/news/{ticker}` | News articles with sentiment. 4-stage fallback pipeline. |
| GET | `/api/search` | Alpha Vantage SYMBOL_SEARCH. `?query=Apple` |

### Analytics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/history/{ticker}` | OHLCV candles. `?exchange=TSE&period=1y` |
| GET | `/api/technicals/{ticker}` | RSI, MACD, Bollinger Bands, SMA 20/50/200 |
| GET | `/api/predict/{ticker}` | XGBoost direction + confidence + SHAP features |
| GET | `/api/anomalies/{ticker}` | IsolationForest price/volume anomalies |
| GET | `/api/factors/{ticker}` | Value, Momentum, Quality, Low-Vol scores (0–100) |

### Intelligence

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/intelligence/correlation` | Cross-market 30-day correlation matrix + regime |
| GET | `/api/sector-performance` | US sector ETF returns. `?period=1mo` |
| GET | `/api/peers/{ticker}` | Sector peers with live quotes |

### Macro (FRED)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/macro/yield_curve` | US Treasury yields (3M, 2Y, 5Y, 10Y, 30Y) |
| GET | `/api/macro/inflation` | CPI, PCE, PPI series |
| GET | `/api/macro/fed_rate` | Federal funds rate history |
| GET | `/api/macro/gdp` | Real GDP quarterly growth |
| GET | `/api/macro/indicators` | Unemployment, consumer sentiment, ISM PMI |
| GET | `/api/ai/macro-context` | Groq-generated macro narrative |

### AI

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/ai/company-summary/{ticker}` | AI outlook, risks, technical view, sentiment context |

### User Data

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlist` | List all watchlist entries |
| POST | `/api/watchlist` | Add ticker. `?ticker=AAPL&exchange=NASDAQ` |
| DELETE | `/api/watchlist/{ticker}` | Remove ticker. `?exchange=NASDAQ` |
| GET | `/api/alerts` | List active price alerts. `?ticker=AAPL` |
| POST | `/api/alerts` | Create alert. `?ticker=AAPL&threshold=200&direction=up` |
| DELETE | `/api/alerts/{alert_id}` | Delete alert by ID |

---

## MCP Servers

Each server is a standalone Python process in `mcp_servers/<name>/server.py`, launched by the orchestrator at startup via the MCP stdio transport.

| Server | Region / Purpose | Key Tools | Data Sources |
|--------|-----------------|-----------|-------------|
| `americas` | NYSE, NASDAQ, TSX, AMEX | `get_real_time_quote`, `get_company_fundamentals`, `get_historical_data`, `get_news`, `search_companies` | Finnhub (real-time), yfinance (EOD + fundamentals) |
| `europe` | LSE, XETRA, EPA, AMS, SWX, BIT, MCE, OSL, HEL | same tool set | yfinance with `.L`, `.DE`, `.PA`, `.AS`, `.SW`, `.MI`, `.MC`, `.OL`, `.HE` suffixes |
| `asia_pacific` | TSE, HKEX, SSE, SZSE, NSE, BSE, ASX, SGX, KRX, TWSE | same tool set | yfinance with `.T`, `.HK`, `.SS`, `.SZ`, `.NS`, `.BO`, `.AX`, `.SI`, `.KS`, `.TW` suffixes |
| `mena` | TADAWUL, DFM, ADX, TASE, EGX, DSM | same tool set | yfinance with `.SR`, `.DU`, `.AD`, `.TA`, `.CA` suffixes |
| `analytics` | Technical analysis, ML, anomaly detection | `get_price_history`, `compute_technical_indicators`, `predict_price_direction`, `detect_anomalies`, `get_sector_performance` | yfinance, XGBoost, IsolationForest, ta library |
| `economics` | FRED macro data | `get_yield_curve`, `get_inflation_data`, `get_fed_rate`, `get_gdp_growth`, `get_macro_indicators` | FRED API via `fredapi` |

### How MCP servers start

```python
# backend/helpers/mcp_client.py
script = os.path.join(SERVERS_DIR, region, "server.py")
params = StdioServerParameters(command=sys.executable, args=[script], env=dict(os.environ))
read, write = await stack.enter_async_context(stdio_client(params))
session     = await stack.enter_async_context(ClientSession(read, write))
await session.initialize()
```

Each server has a 30-second initialisation timeout. Failed servers are marked `"timeout"` or `"error"` in `/health` but do not abort startup — the app runs in degraded mode.

---

## Data Pipeline & Fallback Chains

### Quote endpoint (`/api/quote/{ticker}`)

```
1. L1 in-memory cache (TTL: 60 s)
2. L2 Redis cache (TTL: 60 s)
3. Regional MCP server → Finnhub real-time (Americas only)
4. Regional MCP server → yfinance EOD
```

### News endpoint (`/api/news/{ticker}`)

```
1. Marketaux entity search (symbols={ticker})
2. Marketaux text search (search={company_name})     ← fallback if 0 results
3. yfinance .news (ticker-specific, no API key)      ← fallback if still 0
4. DuckDuckGo web search ("{company} stock news")    ← final fallback
```

### AI company summary (`/api/ai/company-summary/{ticker}`)

```
1. L1 cache (TTL: 24 h)
2. Fetch: fundamentals + quote + news + technicals (parallel)
3. Groq llama-3.1-8b-instant (timeout: 15 s)
4. Google Gemini 2.0 Flash                           ← automatic fallback
```

### Fundamentals (`/api/fundamentals/{ticker}`)

```
1. L1 cache (TTL: 3600 s)
2. Regional MCP → yfinance .info
3. Alpha Vantage OVERVIEW enrichment (layered on top)
```

---

## AI & ML Components

### Dual-LLM AI Analysis

- **Primary**: Groq `llama-3.1-8b-instant` — ~200 ms, 30 req/min free tier
- **Fallback**: Google Gemini 2.0 Flash — activates on Groq timeout (>15 s) or rate limit
- **Output**: JSON with `summary`, `technical_view`, `risks` (list of 3), `sentiment_context`, `model_used`, `generated_at`
- **Cache**: 24 hours per ticker (configurable via "🔄 Regenerate" button in UI)

### XGBoost Price Direction Prediction

- **Features** (16 total): RSI-14, MACD histogram, Bollinger Band %, volume Z-score, ATR-14, SMA 20/50/200 ratios, 5/10/20-day return, 6M momentum
- **Target**: binary next-day direction (up/down)
- **Training**: walk-forward validation on 2 years of daily data
- **Output**: `direction` (up/down), `confidence` (0–1), `backtest_accuracy` (~0.54), `top_features` (SHAP values)
- **Disclaimer**: displayed in UI — "Not financial advice. Historical accuracy: ~54%"

### IsolationForest Anomaly Detection

- **Features**: daily price % change, volume Z-score (vs 30-day mean)
- **Flags**: volume spikes >3σ, overnight gaps >5%, RSI divergence from price trend
- **Output**: list of `{date, type, severity, description}` dicts
- **Display**: anomaly alert banner in Company Explorer when recent events detected

### Factor Exposure Model

Scores each stock 0–100 on four Fama-French-inspired factors:

| Factor | Signal |
|--------|--------|
| Value | P/E and P/B percentile within sector (lower = better) |
| Momentum | 6-month and 1-year price return |
| Quality | ROE and profit margin from Alpha Vantage OVERVIEW |
| Low-Volatility | 6-month realized daily return standard deviation (lower = better score) |

Rendered as a Plotly radar chart in Company Explorer → Financials tab.

---

## Frontend Pages

### 1. Market Dashboard (`home.py`)

- Live quote strip for major indices (Americas, Europe, Asia-Pacific, MENA)
- Quick quote lookup with exchange selector and company name search
- Market open/closed status per region (pytz-aware, DST-correct)
- One-click navigate to Company Explorer from any index quote

### 2. Global Overview (`global_overview.py`)

- Cross-market correlation heatmap (30-day returns, Plotly)
- Market regime badge: Risk-On / Risk-Off / Rotation
- US Sector ETF performance bar chart (XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLB, XLRE, XLU)
- Configurable period selector

### 3. Company Explorer (`company_explorer.py`)

Five tabs:
- **Quote** — price, change %, volume, market cap, 52-week range, source
- **Financials** — P/E, EPS, P/B, PEG, ROE, Beta + factor radar + sector peers
- **AI Analysis** — Groq/Gemini outlook, technical momentum, risk factors, sentiment stance badge
- **News** — up to 10 articles, source badge (Marketaux / Yahoo Finance / Finnhub / Web), 🔵 Unscored for null sentiment
- **Technical** — RSI, MACD, anomaly alerts

### 4. Stock Charts (`stock_charts.py`)

- Candlestick + volume (Plotly)
- Overlays: SMA 20/50/200, Bollinger Bands (toggleable)
- Sub-panels: RSI (70/30 lines), MACD histogram
- Period: 1 Month / 3 Months / 6 Months / 1 Year / 5 Years (auto-renders on change)
- XGBoost prediction panel — confidence bar + SHAP feature importance bar chart
- CSV download

### 5. Macro Dashboard (`macro_dashboard.py`)

- US Yield curve chart (current vs 1 year ago, Plotly)
- Inflation trend: CPI, PCE, PPI (line chart)
- Federal funds rate history
- Real GDP quarterly growth (bar chart)
- Key indicators: unemployment, consumer sentiment, ISM PMI
- AI macro narrative — Groq-generated plain-English context (regenerate button)

---

## GCP Deployment (e2-micro Free Tier)

### Why e2-micro?

GCP e2-micro (0.25 vCPU burst / 1 GB RAM) is in the **Always Free** tier — zero cost permanently in `us-central1`, `us-east1`, or `us-west1`. Combined with a 2 GB swap file and the Redis-free `docker-compose-gcp.yml`, the full stack runs comfortably.

### One-command provisioning

```bash
# 1. Edit variables at the top of the script
nano deploy/gcp/create-vm.sh   # set PROJECT_ID, GITHUB_USERNAME

# 2. Run it
chmod +x deploy/gcp/create-vm.sh
./deploy/gcp/create-vm.sh
```

This script:
- Creates an e2-micro VM in `us-central1-a` with Ubuntu 22.04 and 30 GB HDD
- Passes a startup script that installs Docker, adds 2 GB swap, and clones the repo
- Enables the Firestore API and grants `roles/datastore.user` to the VM service account
- Creates a Firestore database in Native mode
- Opens firewall ports 80, 443, 8000, 8501

### First launch

`.env` is not in the repo (`.gitignore`'d). Transfer it from your local machine before starting the app:

```bash
# Run on your LOCAL machine — copies your configured .env to the VM
gcloud compute scp .env marketmesh-vm:/opt/marketmesh/.env --zone=us-central1-a

# Then SSH in and start
gcloud compute ssh marketmesh-vm --zone=us-central1-a
cd /opt/marketmesh
docker compose -f docker-compose-gcp.yml up -d
```

Make sure `GCP_PROJECT_ID` is set in your `.env` before copying — the `CLOUD DEPLOYMENT` section in `.env` explains each value.

First build: ~8–10 minutes (downloads all Python packages on slow e2-micro CPU).  
Subsequent deploys: ~2–3 minutes (Docker layer cache hits).

### Access URLs

| Service | URL |
|---------|-----|
| Streamlit UI | `http://VM_EXTERNAL_IP:8501` |
| FastAPI docs | `http://VM_EXTERNAL_IP:8000/docs` |
| Health check | `http://VM_EXTERNAL_IP:8000/health` |

### Optional: HTTPS with Nginx

```bash
sudo cp /opt/marketmesh/deploy/gcp/nginx.conf /etc/nginx/sites-available/marketmesh
sudo ln -s /etc/nginx/sites-available/marketmesh /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# Get free TLS certificate
sudo certbot --nginx -d yourdomain.com
```

The included `nginx.conf` routes `yourdomain.com` → Streamlit on port 8501, and `yourdomain.com/api/` → FastAPI on port 8000, with WebSocket support for Streamlit's live updates.

---

## GitHub Actions CI/CD

Every push to `main` automatically deploys to the GCP VM.

### Workflow file

`.github/workflows/deploy-gcp.yml` — SSH into VM → `git pull` → `docker compose build` → `docker compose up -d` → health check.

### Required GitHub Secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | How to get it |
|--------|--------------|
| `GCP_VM_IP` | Printed by `create-vm.sh`, or: `gcloud compute instances describe marketmesh-vm --zone=us-central1-a --format='get(networkInterfaces[0].accessConfigs[0].natIP)'` |
| `GCP_VM_USER` | `gcloud compute ssh marketmesh-vm --zone=us-central1-a --command="whoami"` |
| `GCP_SSH_KEY` | Generate: `ssh-keygen -t ed25519 -f ~/.ssh/marketmesh_gcp` → add public key to VM: `gcloud compute instances add-metadata marketmesh-vm --zone=us-central1-a --metadata ssh-keys="USER:$(cat ~/.ssh/marketmesh_gcp.pub)"` → paste contents of `~/.ssh/marketmesh_gcp` as the secret value |

### Reserve a static IP (recommended)

Without a static IP, `GCP_VM_IP` changes every time the VM is stopped and restarted.

```bash
gcloud compute addresses create marketmesh-ip --region=us-central1
gcloud compute instances delete-access-config marketmesh-vm \
  --access-config-name="External NAT" --zone=us-central1-a
gcloud compute instances add-access-config marketmesh-vm \
  --access-config-name="External NAT" \
  --address=$(gcloud compute addresses describe marketmesh-ip \
              --region=us-central1 --format='get(address)') \
  --zone=us-central1-a
```

---

## Firestore Watchlist Persistence

On GCP, watchlist items and price alerts are stored in **Cloud Firestore (Native mode)** — a serverless NoSQL document database with a generous free tier (1 GB storage, 50,000 reads/day, 20,000 writes/day).

### Collections

```
watchlist/
  {TICKER}_{EXCHANGE}          ← document ID, e.g. "AAPL_NASDAQ"
    ticker:   "AAPL"
    exchange: "NASDAQ"
    added_at: "2026-04-18T10:22:01+00:00"

alerts/
  {auto_generated_id}
    ticker:     "AAPL"
    exchange:   "NASDAQ"
    threshold:  200.0
    direction:  "up"
    triggered:  false
    created_at: "2026-04-18T10:22:01+00:00"
```

### Authentication

On the GCP VM, credentials are provided automatically via **Application Default Credentials (ADC)** — the VM's service account (granted `roles/datastore.user` by `create-vm.sh`) is used with no key file.

For local development:
```bash
gcloud auth application-default login
# Then set GCP_PROJECT_ID=your-project-id in .env
```

### Fallback behaviour

If `GCP_PROJECT_ID` is not set, or if the Firestore library is missing, or if credentials fail, `database.py` silently falls back to an in-memory store. The app logs a warning but starts normally. Watchlist items stored in-memory are lost on container restart.

---

## License

MIT — see `LICENSE` for details.
