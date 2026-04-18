# MarketMesh AI

> Production-grade, multi-region stock intelligence platform powered by 6 MCP agent servers, XGBoost ML prediction, dual-LLM AI analysis, and real-time data from 31 global exchanges.

**🌐 [Live App](https://marketmeshai.duckdns.org) · [API Docs](https://marketmeshai.duckdns.org/docs) · [Health](https://marketmeshai.duckdns.org/health)**

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109%2B-009688?logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.37%2B-FF4B4B?logo=streamlit&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-1.0%2B-6366f1)
![GCP](https://img.shields.io/badge/Deploy-GCP%20e2--micro-4285F4?logo=googlecloud&logoColor=white)

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

The platform is built on the **Model Context Protocol (MCP)** — six specialised agent servers (Americas, Europe, Asia-Pacific, MENA, Analytics, Economics) run as managed `stdio` subprocesses under a central FastAPI orchestrator. The orchestrator routes requests, applies L1 in-memory caching, and exposes a unified 26-endpoint REST API.

**Persistence:** In-memory locally · Cloud Firestore on GCP (free tier, zero-ops)  
**Deployment:** Every push to `main`/`master` triggers GitHub Actions — writes `.env` from repository secrets and runs `docker compose` on the GCP VM. No manual SSH or local `gcloud` CLI needed.

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
| L1 in-memory cache only | TTL dict in the orchestrator process. Fast, zero dependencies. Sufficient for the e2-micro single-process deployment pattern. |
| Firestore for persistence | Schema-free, zero-ops, generous free tier (1 GB / 50 K reads / 20 K writes per day). Works with GCP ADC — no credentials file needed on the VM. Falls back to in-memory when `GCP_PROJECT_ID` is not set. |
| Dual-LLM (Groq → Gemini) | Groq `llama-3.1-8b-instant` is sub-200 ms on the free tier. Gemini 2.0 Flash activates automatically on Groq timeout (>15 s) or rate limit. |
| GitHub Actions-only deployment | A service account key in GitHub Secrets authenticates the workflow, which provisions infrastructure, derives SSH keys, writes `.env`, and runs `docker compose` — entirely from the browser. |

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
| Cache | Python dict with TTL — L1 in-memory only |
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
├── deploy/gcp/
│   ├── vm-startup.sh              # First-boot: 2 GB swap + Docker + repo clone (used by provision workflow)
│   └── nginx.conf                 # Nginx reverse proxy base config — HTTP block only; certbot adds HTTPS
│
├── .github/workflows/
│   ├── provision-gcp.yml          # Run once: VM + Firestore + static IP + SSH key upload
│   └── deploy-gcp.yml             # On push: write .env + docker compose up
│
├── docker-compose.yml             # Local development (in-memory cache)
├── docker-compose-gcp.yml         # GCP cloud (Firestore, mem_limit)
├── requirements.txt
└── .env                           # All local secrets — .gitignore'd, never committed
```

---

## Local Development

### 1. Clone and install

```bash
git clone https://github.com/tusharmishra288/MarketMeshAI.git
cd MarketMeshAI

python -m venv venv
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 2. Configure `.env`

The `.env` file is already present in the repo root and `.gitignore`'d. Fill in your API keys:

```
FINNHUB_API_KEY=your_key
ALPHA_VANTAGE_KEY=your_key
MARKETAUX_API_KEY=your_key
FRED_API_KEY=your_key
GROQ_API_KEY=your_key
GEMINI_API_KEY=your_key

GCP_PROJECT_ID=          # leave empty → in-memory watchlist
```

### 3. Run

```bash
# Terminal 1 — backend
cd backend && python orchestrator.py
# FastAPI → http://localhost:8000  (6 MCP servers initialise in ~10–20 s)

# Terminal 2 — frontend
cd frontend && streamlit run app.py
# Streamlit → http://localhost:8501
```

---

## Environment Variables

| Variable | Required | Local | Cloud (GCP) | Description |
|---|---|---|---|---|
| `FINNHUB_API_KEY` | ✅ | `.env` | GitHub Secret | Real-time US quotes — [finnhub.io](https://finnhub.io/register) |
| `ALPHA_VANTAGE_KEY` | ✅ | `.env` | GitHub Secret | Fundamentals + search — [alphavantage.co](https://www.alphavantage.co/support/#api-key) (25/day) |
| `MARKETAUX_API_KEY` | ✅ | `.env` | GitHub Secret | News + sentiment — [marketaux.com](https://www.marketaux.com/account/signup) (100/day) |
| `FRED_API_KEY` | ✅ | `.env` | GitHub Secret | Macro data — [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `GROQ_API_KEY` | ✅ | `.env` | GitHub Secret | Primary AI LLM — [console.groq.com](https://console.groq.com) (30 req/min) |
| `GEMINI_API_KEY` | ✅ | `.env` | GitHub Secret | Fallback AI LLM — [aistudio.google.com](https://aistudio.google.com/apikey) |
| `GCP_PROJECT_ID` | ⬜ | Empty → in-memory | GitHub Secret → Firestore | GCP project ID — enables Firestore persistence |
| `BACKEND_HOST` | ⬜ | `0.0.0.0` | `0.0.0.0` | FastAPI bind host |
| `BACKEND_PORT` | ⬜ | `8000` | `8000` | FastAPI port |
| `STREAMLIT_PORT` | ⬜ | `8501` | `8501` | Streamlit port |

---

## Docker (Local)

```bash
docker compose up -d               # build and start
docker compose logs -f orchestrator
docker compose up -d --build       # rebuild after code changes
docker compose down
```

`docker-compose.yml` runs orchestrator + frontend with in-memory cache.  
`docker-compose-gcp.yml` is used by GitHub Actions on the GCP VM — adds `mem_limit`, longer `start_period`, and `GCP_PROJECT_ID` for Firestore.

---

## API Reference

Full interactive docs: `http://localhost:8000/docs`

### System
| Method | Path | Description |
|---|---|---|
| GET | `/` | Version + MCP session status |
| GET | `/health` | MCP server status, L1 cache key count, rate limiter state |
| GET | `/mcp/tools/{region}` | List tools on a specific MCP server |
| GET | `/api/validation/stats` | Cache key count and data quality stats |

### Market Data
| Method | Path | Description |
|---|---|---|
| GET | `/api/quote/{ticker}` | Live / EOD quote. `?exchange=NASDAQ` |
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

### AI & User Data
| Method | Path | Description |
|---|---|---|
| GET | `/api/ai/company-summary/{ticker}` | Outlook, risks, technical view, sentiment stance |
| GET/POST/DELETE | `/api/watchlist` | Watchlist management |
| GET/POST/DELETE | `/api/alerts` | Price alert management |

---

## MCP Servers

Each server is a standalone Python process in `mcp_servers/<name>/server.py`, launched at startup via MCP stdio transport. A failed server is marked `"timeout"` or `"error"` in `/health` but does not abort startup — the app continues in degraded mode.

| Server | Exchanges | Key Tools | Data Sources |
|---|---|---|---|
| `americas` | NYSE, NASDAQ, TSX, AMEX | quote, fundamentals, history, news, search, batch | Finnhub (real-time), yfinance |
| `europe` | LSE, XETRA, EPA, AMS, SWX, BIT, MCE, OSL, HEL | same | yfinance `.L` `.DE` `.PA` `.AS` `.SW` `.MI` `.MC` `.OL` `.HE` |
| `asia_pacific` | TSE, HKEX, SSE, SZSE, NSE, BSE, ASX, SGX, KRX, TWSE | same | yfinance `.T` `.HK` `.SS` `.SZ` `.NS` `.BO` `.AX` `.SI` `.KS` `.TW` |
| `mena` | TADAWUL, DFM, ADX, TASE, EGX, DSM | same | yfinance `.SR` `.DU` `.AD` `.TA` `.CA` |
| `analytics` | Global (yfinance) | price history, technicals, prediction, anomalies, sector perf | yfinance, XGBoost, IsolationForest, ta, SHAP |
| `economics` | US macro (FRED) | yield curve, inflation, fed rate, GDP, indicators | FRED API via `fredapi` |

---

## Data Pipeline & Fallback Chains

### Quote
```
L1 cache (60 s) → Finnhub real-time (Americas) → yfinance EOD (all others)
```

### Fundamentals
```
L1 cache (3600 s) → yfinance .info → Alpha Vantage OVERVIEW (P/E, ROE, EPS layered on top)
```

### News
```
1. Marketaux entity search  (symbols={ticker})
2. Marketaux text search    (search={company_name})   ← if 0 results
3. yfinance .news           (ticker-specific, no key) ← if still 0
4. DuckDuckGo web search    ("{company} stock news")  ← final fallback
```

### AI Company Summary
```
L1 cache (24 h) → parallel fetch fundamentals+quote+news+technicals
  → Groq llama-3.1-8b-instant (timeout 15 s)
  → Google Gemini 2.0 Flash (auto-fallback on timeout or rate limit)
```

### Macro Indicators
```
Each FRED series (UNRATE, UMCSENT, NAPM) fetched independently.
One series failing does not block the others — partial data is returned.
```

---

## AI & ML Components

### Dual-LLM AI Analysis
- **Primary:** Groq `llama-3.1-8b-instant` — sub-200 ms, 30 req/min free tier
- **Fallback:** Google Gemini 2.0 Flash — activates on timeout (>15 s) or HTTP 429
- **Output:** `summary`, `technical_view`, `risks` (3 bullets), `sentiment_context`, `model_used`, `generated_at`
- **Cache:** 24 h per ticker — overridable via the "🔄 Regenerate" button

### XGBoost Price Direction Prediction
- **Features (16):** RSI-14, MACD histogram, Bollinger Band %, volume Z-score, ATR-14, SMA 20/50/200 ratios, 5/10/20-day return, 6M momentum
- **Target:** Binary next-day direction (up / down), walk-forward validation on 2 years of daily data
- **Output:** `direction`, `confidence` (0–1), `backtest_accuracy` (~0.54), `top_features` (SHAP)
- **UI disclaimer:** "Not financial advice. Historical accuracy: ~54%"

### IsolationForest Anomaly Detection
- **Features:** Daily price % change + volume Z-score vs 30-day mean
- **Flags:** Volume spikes >3σ, overnight gaps >5%, RSI divergence from price trend
- **UI:** Anomaly banner above tabs in Company Explorer when recent events detected

### Factor Exposure Model
Scores each stock 0–100 on four factors, rendered as a Plotly radar chart:

| Factor | Signal |
|---|---|
| Value | P/E and P/B percentile vs sector |
| Momentum | 6-month and 1-year price return |
| Quality | ROE and profit margin (Alpha Vantage OVERVIEW) |
| Low-Volatility | 6-month realised daily return standard deviation |

---

## Frontend Pages

| Page | Key Content |
|---|---|
| **Market Dashboard** | Live quote strip for major indices · quick quote lookup · market open/closed per region (DST-aware) · watchlist navigation |
| **Global Overview** | 30-day cross-market correlation heatmap · regime badge (Risk-On/Off/Rotation) · US sector ETF performance bars |
| **Company Explorer** | 5 tabs: Quote · Financials (P/E, factor radar, peers) · AI Analysis (outlook, risks, stance badge) · News (up to 10 articles, source badge) · Technicals (RSI, MACD, anomaly alerts) |
| **Stock Charts** | Candlestick + volume · SMA/BB overlays · RSI + MACD sub-panels · XGBoost prediction panel with SHAP bar chart · CSV download |
| **Macro Dashboard** | Yield curve · CPI/PCE/PPI · Fed rate · GDP · unemployment/sentiment/PMI · Groq AI narrative with regenerate |

---

## Caching Strategy

All caching is L1 in-memory (TTL dict in the orchestrator process). Requests hit cache first; on miss they call the MCP server → external API → store result → return.

| Endpoint | TTL |
|---|---|
| Quote | 60 s |
| Technicals | 300 s |
| Global snapshot | 300 s |
| Fundamentals | 3 600 s |
| Macro data | 3 600 s |
| AI company summary | 86 400 s (24 h) |
| Factor scores | 86 400 s |
| News / search | 86 400 s |

---

## GCP Deployment — GitHub Actions Only

> **Everything runs from your browser.** No local `gcloud` CLI, no manual SSH, no `.env` copying. Two GitHub Actions workflows handle all infrastructure and deployment.

### Step 1 — Add 9 GitHub Secrets

**Settings → Secrets and variables → Actions → New repository secret**

**Infrastructure secrets (3):**

| Secret | How to get it |
|---|---|
| `GCP_SA_KEY` | GCP Console → IAM & Admin → Service Accounts → Create (`marketmesh-deploy`) → grant 5 roles (Compute Admin, Service Account User, Cloud Datastore Owner, Project IAM Admin, Service Usage Admin) → Keys → Add Key → JSON → paste entire file contents |
| `GCP_PROJECT_ID` | Your GCP project ID (visible in Console top bar, e.g. `marketmesh-ai-461023`) |
| `GCP_SSH_KEY` | In GCP Cloud Shell: `ssh-keygen -t ed25519 -f ~/.ssh/marketmesh_gcp -C "github-actions" -N "" && cat ~/.ssh/marketmesh_gcp` → paste entire output including header/footer |

**Application secrets (6):**

| Secret | Source | Free tier |
|---|---|---|
| `FINNHUB_API_KEY` | [finnhub.io/register](https://finnhub.io/register) | 60 req/min |
| `ALPHA_VANTAGE_KEY` | [alphavantage.co](https://www.alphavantage.co/support/#api-key) | 25 req/day |
| `MARKETAUX_API_KEY` | [marketaux.com](https://www.marketaux.com/account/signup) | 100 req/day |
| `FRED_API_KEY` | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) | 120 req/min |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) | 30 req/min |
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Free |

---

### Step 2 — Run Provision Workflow (once)

**Actions → "1 - Provision GCP VM (run once)" → Run workflow**

What it creates automatically (~2 min):

| Resource | Detail |
|---|---|
| VM | e2-micro, Ubuntu 22.04, 30 GB HDD, `us-central1-a` |
| VM startup | Installs Docker, creates 2 GB swap, clones repo (runs in background ~3 min) |
| SSH key | Derives public key from `GCP_SSH_KEY`, uploads with username `marketmesh` |
| Firestore | API enabled, `roles/datastore.user` granted to VM service account, DB created (`nam5`) |
| Static IP | Reserved as `marketmesh-ip` — VM IP never changes on restart |
| Firewall | Ports 80, 443, 8000, 8501 open |

**Wait ~3 minutes** after this finishes (Docker install runs in the background on the VM), then proceed.

---

### Step 3 — Deploy (automatic on every push)

Push any commit to `main` or `master`, or trigger manually via **Actions → "2 - Deploy to GCP" → Run workflow**.

```bash
git add . && git commit -m "deploy" && git push origin master
```

What it does on each run:

| Step | Detail |
|---|---|
| Auth + IP | Authenticates with GCP, resolves VM IP dynamically |
| Write `.env` | SSHs as `marketmesh` → writes `/opt/marketmesh/.env` from all 6 app secrets |
| Pull code | `git reset --hard origin/<branch>` |
| Build & start | `sudo docker compose -f docker-compose-gcp.yml build + up -d` |
| Health poll | Waits up to 3 min for orchestrator `healthy` status |
| Final check | `GET /health` from Actions runner — must return HTTP 200 |

**First build: ~20 minutes** (cold pip install on e2-micro — backend ML stack).  
**Subsequent deploys: 3–5 minutes** (Docker layer cache preserved).  
A green checkmark = app is live at the URLs below.

### Live URLs

| | URL |
|---|---|
| **Frontend** | https://marketmeshai.duckdns.org |
| **API docs** | https://marketmeshai.duckdns.org/docs |
| **Health** | https://marketmeshai.duckdns.org/health |

DuckDNS is updated automatically on every deploy — if the VM IP ever changes the domain stays correct with no manual intervention.

---

### Infrastructure Summary

| Component | Detail |
|---|---|
| VM | e2-micro · 0.25 vCPU burst / 1 GB RAM + 2 GB swap |
| Disk | 30 GB standard persistent HDD |
| Region | `us-central1-a` (Always Free eligible) |
| Monthly cost | **$0** (GCP Always Free tier) |
| Static IP | `marketmesh-ip` |
| Domain | `marketmeshai.duckdns.org` (free, auto-updated on deploy) |
| Firewall | TCP 80, 443, 8000, 8501 |
| Containers | orchestrator 700 MB limit · frontend 250 MB limit |
| Persistence | Cloud Firestore — 1 GB / 50 K reads / 20 K writes per day free |

### Updating API Keys

Change the GitHub Secret value → push any commit → the deploy workflow writes the new `.env` on the next run. No SSH into the VM required.

### HTTPS via Nginx + DuckDNS

HTTPS is served by Nginx (reverse proxy) with a free Let's Encrypt certificate. The deploy workflow automatically keeps `marketmeshai.duckdns.org` pointed at the current VM IP via the DuckDNS API on every run.

```bash
# One-time setup on the VM (already done)
sudo apt install nginx certbot python3-certbot-nginx -y
sudo certbot --nginx -d marketmeshai.duckdns.org
```

Nginx routes `marketmeshai.duckdns.org` → Streamlit (8501) and `/api/` → FastAPI (8000) with WebSocket support for Streamlit.

---

## Firestore Watchlist Persistence

On GCP, watchlist items and price alerts are stored in **Cloud Firestore (Native mode)**. Locally, an in-memory dict is used — data is lost on process restart.

### Collections schema

```
watchlist/
  {TICKER}_{EXCHANGE}          e.g. "AAPL_NASDAQ"
    ticker, exchange, added_at

alerts/
  {auto_id}
    ticker, exchange, threshold, direction ("up"/"down"), triggered, created_at
```

### Authentication

**GCP VM:** The VM's Compute Engine service account provides Application Default Credentials (ADC) automatically — no key file needed. The provision workflow grants `roles/datastore.user` to this account.

**Local (optional):** To test Firestore locally:
```bash
gcloud auth application-default login
# Then set GCP_PROJECT_ID=your-project-id in .env
```

Leave `GCP_PROJECT_ID` empty to use the in-memory fallback. Any Firestore connection error is caught — the app logs a warning and falls back silently.
