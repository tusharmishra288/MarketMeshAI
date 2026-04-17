# MarketMesh AI

> Production-grade, multi-region stock intelligence platform powered by MCP agents, XGBoost ML, and dual-LLM AI analysis across 31 global exchanges.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109%2B-009688?logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.56%2B-FF4B4B?logo=streamlit&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

---

## Why "MarketMesh AI"?

The name is built from two words and a suffix that each reflect a core principle of the platform:

**Market** — The scope is the entire global equity market: real-time quotes, company fundamentals, sector performance, cross-market correlations, and macroeconomic context — all in one place. The platform spans 31 exchanges across 26 countries, from NASDAQ and NYSE to NSE, TSE, LSE, and Tadawul, treating every publicly listed company worldwide as part of a single, unified market.

**Mesh** — A mesh is an interconnected network where every node is linked to every other. This perfectly describes both the platform's architecture and its analytical approach:

- **Architecturally**, six MCP (Model Context Protocol) agent servers — Americas, Europe, Asia-Pacific, MENA, Analytics, and Economics — form a mesh of specialised intelligence nodes. The FastAPI orchestrator weaves their outputs together into a single, coherent API response. No single source or server is a bottleneck; each enriches the others.
- **Analytically**, the platform cross-links data streams that are normally siloed: live prices are correlated with macroeconomic indicators, company fundamentals are scored against sector peers, news sentiment is aggregated alongside technical momentum signals, and yield curves are interpreted alongside GDP and inflation trends. The result is a mesh of insight — every data point connected to every other.
- **Coverage-wise**, the cross-market correlation heatmap literally visualises the mesh — showing how 31 exchanges move in relation to each other, and classifying the global market regime (Risk-On, Risk-Off, or Rotation) from that interconnected signal.

**AI** — Artificial intelligence runs through every layer: Groq and Gemini LLMs translate raw data into plain-English company outlooks and macro narratives, XGBoost predicts next-day price direction with SHAP explainability, IsolationForest detects statistically unusual price and volume events, and a four-factor model (Value, Momentum, Quality, Low-Volatility) scores each stock against its sector peers. AI is not a feature bolted on — it is the analytical engine that turns the mesh of raw market data into actionable intelligence.

> In short: **MarketMesh AI** weaves together 31 global exchanges, 6 AI agents, and 5 data providers into a single, interconnected intelligence platform — where every market signal is connected, every data point is enriched, and every decision is informed.

---

## Overview

MarketMesh AI is a production-grade stock market intelligence platform that aggregates real-time and end-of-day data from 31 exchanges across 26 countries, enriches it with AI-powered analysis, machine learning predictions, and macroeconomic context, and presents everything through a clean Streamlit interface.

The platform is built on the **Model Context Protocol (MCP)** — a standard for structured, tool-calling AI agents. Six MCP servers run as managed stdio subprocesses under a central FastAPI orchestrator. Each server owns a domain: four cover regional equity markets (Americas, Europe, Asia-Pacific, MENA), one handles technical analysis and ML inference, and one connects to the Federal Reserve's FRED API for macroeconomic data. The orchestrator routes requests to the appropriate server, applies 2-tier caching, and exposes a unified REST API consumed by the frontend.

AI capabilities are provided by a dual-LLM setup: Groq's `llama-3.1-8b-instant` as the primary (fast, free tier, sub-200ms) with Google Gemini 2.0 Flash as an automatic fallback when Groq is rate-limited. The ML stack combines XGBoost price-direction prediction with SHAP explainability, IsolationForest anomaly detection, and a four-factor exposure model (Value, Momentum, Quality, Low-Volatility) rendered as a radar chart alongside sector peers.

The data pipeline is designed for resilience: every data source has a fallback chain. Americas quotes try Finnhub (real-time WebSocket data) before falling back to yfinance. News tries Marketaux entity-match, then Marketaux search, then yfinance.news, then Finnhub. Fundamentals layer Alpha Vantage enrichment on top of yfinance base data. This layered approach means the app degrades gracefully even on free-tier rate limits.

---

## Features

- Real-time and EOD quotes across 31 exchanges in 26 countries (40,000+ companies)
- 4 regional MCP servers: Americas, Europe, Asia-Pacific, MENA
- Company deep-dive: fundamentals (P/E, EPS, P/B, PEG, ROE, Beta), AI analysis, news with sentiment
- Technical charts: candlestick, SMA 20/50/200, Bollinger Bands, RSI, MACD, volume
- XGBoost ML direction prediction with SHAP feature importance (walk-forward backtest accuracy ~54%)
- IsolationForest anomaly detection for price and volume spikes
- Factor exposure radar: Value, Momentum, Quality, Low-Volatility (0–100 per factor)
- Cross-market correlation heatmap and market regime classification (Risk-On / Risk-Off / Rotation)
- US Sector ETF performance by configurable time period
- FRED macro dashboard: yield curve, inflation (CPI/PCE/PPI), Fed funds rate, GDP growth, key indicators
- AI macro narrative generated by Groq with Gemini fallback
- Persistent watchlist with one-click Company Explorer navigation
- 2-tier caching: L1 in-memory (TTL) + optional L2 Redis

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Streamlit Frontend                        │
│          (5 pages: Dashboard · Overview · Explorer ·            │
│                    Charts · Macro)                               │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTP / REST
┌────────────────────────▼────────────────────────────────────────┐
│                   FastAPI Orchestrator                           │
│              (7 routers · L1 cache · Rate limiter)              │
└──┬───────┬────────┬──────────┬───────────┬──────────┬───────────┘
   │       │        │          │           │          │
   ▼       ▼        ▼          ▼           ▼          ▼
[Americas][Europe][Asia-Pac][MENA]    [Analytics] [Economics]
  MCP      MCP      MCP      MCP        MCP          MCP
  │        │        │        │          │            │
Finnhub  yfinance yfinance yfinance  yfinance+ML   FRED API
```

All MCP servers run as **stdio subprocesses** managed by the orchestrator at startup — no separate network services or ports required.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Streamlit 1.56, Plotly, pandas |
| Backend API | FastAPI, Uvicorn, Pydantic |
| Agent Protocol | Model Context Protocol (MCP) 1.0 |
| Data — Real-time quotes | Finnhub (Americas) |
| Data — EOD & history | yfinance (all regions) |
| Data — Fundamentals | Alpha Vantage OVERVIEW API |
| Data — News & sentiment | Marketaux + yfinance.news |
| Data — Macro | FRED (Federal Reserve Bank of St. Louis) |
| ML — Prediction | XGBoost + SHAP |
| ML — Anomalies | scikit-learn IsolationForest |
| ML — Technicals | ta (Technical Analysis library) |
| AI — Primary LLM | Groq (llama-3.1-8b-instant) |
| AI — Fallback LLM | Google Gemini 2.0 Flash |
| Caching | In-memory L1 (TTL) + Redis L2 (optional) |
| Database | PostgreSQL via asyncpg (optional, in-memory fallback) |
| Containerisation | Docker Compose |

---

## Project Structure

```
marketmesh-ai/
├── backend/
│   ├── orchestrator.py          # FastAPI app entry point + MCP lifespan
│   ├── helpers/
│   │   ├── mcp_client.py        # MCP stdio session pool & dispatcher
│   │   ├── cache_helpers.py     # L1 in-memory TTL cache
│   │   ├── market_helpers.py    # Exchange/region maps, market status
│   │   ├── enrichment.py        # Alpha Vantage enrichment + factor scoring
│   │   └── ai_helpers.py        # Groq + Gemini LLM wrappers
│   ├── routes/
│   │   ├── market.py            # /api/quote, /api/fundamentals, /api/news, /api/search
│   │   ├── analytics.py         # /api/history, /api/technicals, /api/predict, /api/anomalies, /api/factors
│   │   ├── intelligence.py      # /api/intelligence/correlation, /api/sector-performance, /api/peers
│   │   ├── macro.py             # /api/macro/{indicator}
│   │   ├── ai.py                # /api/ai/company-summary, /api/ai/company-description
│   │   ├── user_data.py         # /api/watchlist (GET/POST/DELETE)
│   │   └── system.py            # /health, /api/validation/stats
│   └── services/
│       ├── cache_manager.py     # Redis L2 cache manager
│       ├── database.py          # SQLAlchemy async DB init
│       ├── rate_limiter.py      # Token-bucket rate limiting
│       └── validator.py         # Input validation & data quality scoring
├── frontend/
│   ├── app.py                   # Streamlit entry point + global theme + sidebar
│   ├── utils.py                 # Shared exchange maps, formatters, market hours
│   ├── api_client.py            # Centralised HTTP calls to FastAPI backend
│   ├── components/
│   │   └── charts.py            # Reusable Plotly chart builder functions
│   └── pages/
│       ├── home.py              # Market Dashboard (quick quote, market status)
│       ├── global_overview.py   # Global index snapshot + correlation heatmap
│       ├── company_explorer.py  # Deep-dive: fundamentals, AI, news, peers, factors
│       ├── stock_charts.py      # Technical charts + ML prediction
│       └── macro_dashboard.py   # FRED macro indicators + AI narrative
├── mcp_servers/
│   ├── americas/server.py       # NYSE, NASDAQ, TSX, B3, BMV — Finnhub primary
│   ├── europe/server.py         # LSE, XETRA, EPA, SWX — yfinance
│   ├── asia_pacific/server.py   # TSE, HKEX, NSE, ASX, KRX — yfinance
│   ├── mena/server.py           # TADAWUL, DFM, TASE — yfinance
│   ├── analytics/server.py      # Price history, RSI/MACD/BB, XGBoost, IsolationForest
│   └── economics/server.py      # FRED yield curve, inflation, GDP, Fed rate
├── docker-compose.yml           # Redis + FastAPI + Streamlit orchestration
├── requirements.txt             # All Python dependencies
├── Makefile                     # Developer shortcuts
├── .env                         # Environment variables (not committed — add your API keys here)
└── .gitignore
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- API keys (see [Configuration](#configuration))

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/your-username/marketmesh-ai.git
cd marketmesh-ai

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate      # Linux/macOS
venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment — edit .env with your API keys
# (see Configuration section below for all available keys)

# 5. Start the application
make run
# OR start individually:
# Terminal 1: make backend
# Terminal 2: make frontend
```

Open **http://localhost:8501** in your browser.

### Docker (Recommended for Production)

```bash
# Edit .env with your API keys, then:
docker compose up --build -d
```

Services started: `redis` (L2 cache, port 6379), `orchestrator` (FastAPI, port 8000), `frontend` (Streamlit, port 8501).

---

## Configuration

All configuration is via environment variables in the `.env` file at the project root. Fill in the values before starting the app.

| Variable | Required | Description | Where to get it | Free tier |
|---|---|---|---|---|
| `FINNHUB_API_KEY` | Required | Real-time US quotes via WebSocket | [finnhub.io/register](https://finnhub.io/register) | 60 calls/min |
| `ALPHA_VANTAGE_KEY` | Recommended | Company fundamentals, EPS, PEG, symbol search | [alphavantage.co](https://www.alphavantage.co/support/#api-key) | 25 req/day |
| `MARKETAUX_API_KEY` | Recommended | Global financial news with per-article sentiment | [marketaux.com/register](https://www.marketaux.com/register) | 100 req/day |
| `GROQ_API_KEY` | Recommended | Primary LLM — llama-3.1-8b-instant | [console.groq.com](https://console.groq.com/) | 30 req/min |
| `GEMINI_API_KEY` | Recommended | Fallback LLM — Gemini 2.0 Flash | [aistudio.google.com](https://aistudio.google.com/app/apikey) | 15 req/min |
| `FRED_API_KEY` | Recommended | FRED macroeconomic data (yield curve, inflation, GDP) | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) | Unlimited |
| `REDIS_HOST` | Optional | Redis L2 cache hostname | Self-hosted or Redis Cloud | — |
| `REDIS_PORT` | Optional | Redis port (default: 6379) | — | — |
| `REDIS_PASSWORD` | Optional | Redis auth password | — | — |
| `DATABASE_URL` | Optional | PostgreSQL DSN for persistent watchlist | Self-hosted | — |
| `BACKEND_URL` | Optional | Frontend → backend URL (default: `http://127.0.0.1:8000`) | — | — |
| `BACKEND_HOST` | Optional | FastAPI bind host (default: `0.0.0.0`) | — | — |
| `BACKEND_PORT` | Optional | FastAPI bind port (default: `8000`) | — | — |

---

## API Reference

All endpoints are served by the FastAPI orchestrator on port 8000. Interactive docs are available at **http://localhost:8000/docs**.

### System

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | System health, MCP server status, cache stats, rate limit usage |
| `GET` | `/api/validation/stats` | Data quality scores per exchange |

### Market Data

| Method | Path | Key Parameters | Description |
|---|---|---|---|
| `GET` | `/api/quote/{ticker}` | `exchange` | Real-time (Finnhub) or EOD (yfinance) quote |
| `GET` | `/api/fundamentals/{ticker}` | `exchange` | Company fundamentals enriched with Alpha Vantage |
| `GET` | `/api/news/{ticker}` | `exchange`, `company_name` | News articles with aggregate sentiment |
| `GET` | `/api/search` | `query`, `limit` | Company name / ticker search across Alpha Vantage + yfinance |
| `GET` | `/api/global-snapshot` | — | All 31 exchange index values + data quality score |

### Technical Analysis & ML

| Method | Path | Key Parameters | Description |
|---|---|---|---|
| `GET` | `/api/history/{ticker}` | `exchange`, `period` | OHLCV candles (5d / 1mo / 3mo / 6mo / 1y / 5y) |
| `GET` | `/api/technicals/{ticker}` | `exchange`, `period` | RSI, MACD, Bollinger Bands, SMA 20/50/200 |
| `GET` | `/api/predict/{ticker}` | `exchange` | XGBoost direction prediction + confidence + SHAP feature importance |
| `GET` | `/api/anomalies/{ticker}` | `exchange` | IsolationForest anomaly list with severity scores |
| `GET` | `/api/factors/{ticker}` | `exchange` | Factor exposure scores: Value, Momentum, Quality, Low-Volatility (0–100) |

### Intelligence

| Method | Path | Key Parameters | Description |
|---|---|---|---|
| `GET` | `/api/intelligence/correlation` | — | Cross-market 30-day return correlation matrix + regime classification |
| `GET` | `/api/sector-performance` | `period` | US Sector ETF (SPDR family) returns for the given period |
| `GET` | `/api/peers/{ticker}` | `exchange` | Sector peer companies with live quotes |

### Macro (FRED)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/macro/yield_curve` | 3M / 2Y / 5Y / 10Y / 30Y Treasury yields + inversion signal |
| `GET` | `/api/macro/inflation` | CPI, PCE, PPI trends with YoY % change |
| `GET` | `/api/macro/fed_rate` | Federal funds rate history |
| `GET` | `/api/macro/gdp` | Real GDP quarterly growth |
| `GET` | `/api/macro/indicators` | Unemployment, consumer sentiment, ISM PMI |

### AI

| Method | Path | Key Parameters | Description |
|---|---|---|---|
| `GET` | `/api/ai/company-summary/{ticker}` | `exchange` | AI-generated company outlook, risks, and sentiment context |
| `GET` | `/api/ai/company-description/{ticker}` | `exchange` | Short plain-English company description |
| `GET` | `/api/ai/macro-context` | — | AI macro environment narrative (Groq / Gemini) |

### Watchlist

| Method | Path | Key Parameters | Description |
|---|---|---|---|
| `GET` | `/api/watchlist` | — | Retrieve all watchlist items |
| `POST` | `/api/watchlist` | `ticker`, `exchange` | Add a ticker to the watchlist |
| `DELETE` | `/api/watchlist/{ticker}` | `exchange` | Remove a ticker from the watchlist |

---

## MCP Server Architecture

The **Model Context Protocol (MCP)** is an open standard for exposing structured tool-calling interfaces to AI agents. Each MCP server defines a set of named tools with typed input/output schemas. The orchestrator calls tools over a **stdio transport** — it spawns each server as a subprocess, sends JSON-RPC messages to stdin, and reads responses from stdout. No network sockets or ports are required between the orchestrator and its MCP servers.

At FastAPI startup, the orchestrator spawns all six MCP servers and holds their sessions open for the lifetime of the process. Incoming API requests are dispatched to the appropriate server's tool via an async session pool managed by `backend/helpers/mcp_client.py`.

### MCP Server Summary

| Server | Path | Exchanges / Domain | Tools |
|---|---|---|---|
| Americas | `mcp_servers/americas/server.py` | NYSE, NASDAQ, AMEX, TSX, B3, BMV | `get_real_time_quote`, `get_company_fundamentals`, `get_market_overview`, `get_historical_data`, `get_company_news`, `batch_quotes` |
| Europe | `mcp_servers/europe/server.py` | LSE, XETRA, EPA, AMS, SWX, BIT, MCE, OSL, HEL | `get_european_quote`, `get_european_fundamentals`, `get_european_indices`, `get_european_historical`, `get_european_news`, `batch_european_quotes` |
| Asia-Pacific | `mcp_servers/asia_pacific/server.py` | TSE, HKEX, SSE, SZSE, NSE, BSE, ASX, SGX, KRX, TWSE | `get_asian_quote`, `get_asian_fundamentals`, `get_asian_indices`, `get_asian_historical`, `get_asian_news`, `batch_asian_quotes` |
| MENA | `mcp_servers/mena/server.py` | TADAWUL, DFM, ADX, TASE, EGX, DSM | `get_mena_quote`, `get_mena_fundamentals`, `get_mena_indices`, `get_mena_historical`, `get_mena_news`, `batch_mena_quotes` |
| Analytics | `mcp_servers/analytics/server.py` | All tickers — ML & technicals | `get_price_history`, `compute_technical_indicators`, `predict_price_direction`, `detect_anomalies`, `get_sector_performance` |
| Economics | `mcp_servers/economics/server.py` | FRED macroeconomic data | `get_yield_curve`, `get_inflation_data`, `get_fed_rate`, `get_gdp_growth`, `get_macro_indicators` |

---

## Data Pipeline

Every data path has a fallback chain to handle free-tier rate limits and source outages gracefully:

```
Quote:        Americas → Finnhub (real-time) → yfinance (EOD fallback)
              Europe / Asia-Pacific / MENA → yfinance (EOD)

Fundamentals: yfinance.info → Alpha Vantage OVERVIEW (enrichment layer)

News:         Marketaux (entity match) → Marketaux (keyword search)
              → yfinance.news → Finnhub news

Search:       Alpha Vantage SYMBOL_SEARCH → yfinance.Search (company name queries)

Macro:        FRED API via fredapi library (no fallback — key required)

AI Analysis:  Groq (llama-3.1-8b-instant) → Google Gemini 2.0 Flash
```

Data quality is scored per-source by `backend/services/validator.py` and exposed at `GET /api/validation/stats`. Each response includes a `data_quality` field (0.0–1.0) indicating confidence in the returned data.

---

## Caching Strategy

MarketMesh AI uses a two-tier cache to minimise API calls against free-tier rate limits.

**L1 — In-memory (always active)**

An async-safe dictionary with TTL timestamps stored in `backend/helpers/cache_helpers.py`. Zero dependencies — always available.

| Endpoint type | TTL |
|---|---|
| Real-time quote | 5 minutes |
| Price history | 1 hour |
| Fundamentals | 1 hour |
| News + sentiment | 30 minutes |
| Technical indicators | 15 minutes |
| Sector performance | 1 hour |
| AI company summary | 24 hours |
| AI macro narrative | 4 hours |

**L2 — Redis (optional)**

When `REDIS_HOST` is set and Redis is reachable, the cache manager (`backend/services/cache_manager.py`) writes through to Redis using the same TTLs. The app silently skips Redis if the connection fails, falling back to L1 only.

**Cache bypass**: append `?refresh=true` to any AI endpoint to force a fresh LLM call, bypassing both cache layers.

---

## Exchange Coverage

### Americas (6 exchanges)

| Exchange | Code | Country | Currency |
|---|---|---|---|
| New York Stock Exchange | NYSE | USA | USD |
| NASDAQ | NASDAQ | USA | USD |
| NYSE American (AMEX) | AMEX | USA | USD |
| Toronto Stock Exchange | TSX | Canada | CAD |
| B3 (Bovespa) | B3 | Brazil | BRL |
| Bolsa Mexicana de Valores | BMV | Mexico | MXN |

### Europe (9 exchanges)

| Exchange | Code | Country | Currency |
|---|---|---|---|
| London Stock Exchange | LSE | UK | GBp |
| Deutsche Boerse (XETRA) | XETRA | Germany | EUR |
| Euronext Paris | EPA | France | EUR |
| Euronext Amsterdam | AMS | Netherlands | EUR |
| SIX Swiss Exchange | SWX | Switzerland | CHF |
| Borsa Italiana | BIT | Italy | EUR |
| Bolsa de Madrid | MCE | Spain | EUR |
| Oslo Bors | OSL | Norway | NOK |
| Nasdaq Helsinki | HEL | Finland | EUR |

### Asia-Pacific (10 exchanges)

| Exchange | Code | Country | Currency |
|---|---|---|---|
| Tokyo Stock Exchange | TSE | Japan | JPY |
| Hong Kong Stock Exchange | HKEX | Hong Kong | HKD |
| Shanghai Stock Exchange | SSE | China | CNY |
| Shenzhen Stock Exchange | SZSE | China | CNY |
| National Stock Exchange | NSE | India | INR |
| BSE (Bombay) | BSE | India | INR |
| Australian Securities Exchange | ASX | Australia | AUD |
| Singapore Exchange | SGX | Singapore | SGD |
| Korea Exchange | KRX | South Korea | KRW |
| Taiwan Stock Exchange | TWSE | Taiwan | TWD |

### MENA (6 exchanges)

| Exchange | Code | Country | Currency |
|---|---|---|---|
| Saudi Exchange (Tadawul) | TADAWUL | Saudi Arabia | SAR |
| Dubai Financial Market | DFM | UAE | AED |
| Abu Dhabi Securities Exchange | ADX | UAE | AED |
| Tel Aviv Stock Exchange | TASE | Israel | ILS |
| Egyptian Exchange | EGX | Egypt | EGP |
| Qatar Stock Exchange | DSM | Qatar | QAR |

---

## Development

### Adding a New Exchange

1. Identify the yfinance ticker suffix for the exchange (e.g., `.AX` for ASX).
2. Add the exchange code, currency, and suffix to the region map in the appropriate MCP server (`mcp_servers/<region>/server.py`).
3. Update `EXCHANGE_CURRENCY` and `ALL_EXCHANGES` in `frontend/utils.py`.
4. Update `backend/helpers/market_helpers.py` with market hours if needed.

### Adding a New MCP Tool

1. Open the target MCP server file under `mcp_servers/`.
2. Define a new `@server.tool()` decorated async function with typed parameters.
3. Add the tool name to the server's tool list in `backend/helpers/mcp_client.py`.
4. Create or update a route in `backend/routes/` to call the tool via `await call_mcp_tool(region, tool_name, params)`.
5. Register the new route in `backend/orchestrator.py`.

### Adding a New Frontend Page

1. Create `frontend/pages/<page_name>.py`.
2. Import `api_client` for backend calls and `utils` for shared formatters.
3. Register the page in `frontend/app.py` under `st.navigation()`.
4. Any shared Plotly chart patterns belong in `frontend/components/charts.py`.

---

## Limitations

- **Finnhub free tier**: 60 calls/min. US stocks only for real-time quotes. International tickers fall back to yfinance EOD data.
- **Alpha Vantage free tier**: 25 calls/day. Fundamentals enrichment (EPS, PEG, description) may be skipped on high-traffic days once the quota is consumed.
- **Marketaux free tier**: 100 calls/day. News falls back to `yfinance.news` and Finnhub when exhausted.
- **XGBoost prediction accuracy**: ~52–56% in walk-forward backtests — better than random, but this is **not financial advice**. Past prediction accuracy does not guarantee future results.
- **Watchlist persistence**: Without a PostgreSQL `DATABASE_URL` configured, the watchlist is stored in-memory and lost on backend restart.
- **yfinance data quality**: yfinance relies on Yahoo Finance's unofficial API. Data may be delayed (15–20 min), unavailable, or inaccurate for some emerging market exchanges. Always verify with official exchange sources before making investment decisions.
- **Redis**: Optional. Without it, the L1 in-memory cache is used exclusively. L1 cache does not persist across restarts.

---

## License

This project is licensed under the **MIT License**.

```
MIT License

Copyright (c) 2025 MarketMesh AI Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

> **Disclaimer**: MarketMesh AI is an educational and research tool. Nothing in this software constitutes financial advice. Always consult a qualified financial professional before making investment decisions.
