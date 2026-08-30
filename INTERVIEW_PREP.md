# MarketMesh AI — Comprehensive Technical Interview Preparation Guide

> This file is gitignored and is exclusively for personal interview preparation.
> It covers every layer of the project: architecture, technology choices, ML, DevOps, APIs, and design decisions — with ready answers to the most likely interview questions.

---

## Table of Contents

1. [Project Overview (30-second pitch)](#1-project-overview)
2. [System Architecture — The Big Picture](#2-system-architecture)
3. [MCP — Model Context Protocol (the most unique part)](#3-mcp-model-context-protocol)
4. [Backend — FastAPI & Python Async](#4-backend-fastapi--python-async)
5. [Data Sources & API Integration](#5-data-sources--api-integration)
6. [Machine Learning & Analytics](#6-machine-learning--analytics)
7. [AI / LLM Integration](#7-ai--llm-integration)
8. [Caching Strategy](#8-caching-strategy)
9. [Database — Firestore vs Alternatives](#9-database--firestore)
10. [Frontend — Streamlit](#10-frontend--streamlit)
11. [Infrastructure & Cloud — GCP e2-micro](#11-infrastructure--cloud)
12. [CI/CD — GitHub Actions](#12-cicd--github-actions)
13. [Containerisation — Docker & Docker Compose](#13-containerisation--docker--docker-compose)
14. [Networking — Nginx + Certbot + DuckDNS](#14-networking--nginx--certbot--duckdns)
15. [Self-Healing — The 4-Layer Watchdog System](#15-self-healing--the-4-layer-watchdog-system)
16. [Security Considerations](#16-security-considerations)
17. [Rate Limiting & Quota Management](#17-rate-limiting--quota-management)
18. [Likely Interview Questions & Model Answers](#18-likely-interview-questions--model-answers)

---

## 1. Project Overview

**30-second pitch:**
> "MarketMesh AI is a full-stack, cloud-deployed stock intelligence platform covering 31 exchanges across 26 countries. It uses a microservice-like architecture built on the Model Context Protocol (MCP), where 6 specialised Python subprocesses — one per region and one for analytics — feed a central FastAPI orchestrator. The orchestrator integrates real-time quotes from Finnhub, fundamentals from yfinance and Alpha Vantage, macroeconomic data from FRED, and AI analysis from Groq and Google Gemini. The frontend is a Streamlit app featuring candlestick charts, RSI/MACD indicators, XGBoost price prediction, anomaly detection, and a persistent watchlist backed by Google Cloud Firestore. The entire stack is deployed on GCP's always-free e2-micro tier with zero ongoing cost, full HTTPS, CI/CD via GitHub Actions, and a self-healing system that guarantees automatic recovery from any subprocess or container failure within 7 minutes."

**What makes it technically interesting:**
- Uses MCP (Anthropic's Model Context Protocol) for inter-process communication — same protocol that powers Claude's tool use
- ML inference (XGBoost + IsolationForest) runs inside a subprocess, not a separate ML service
- Achieves "free forever" production deployment by fitting within GCP's always-free tier limits
- 4-layer self-healing: in-process watchdog → Docker health check → restart:always → VM cron

---

## 2. System Architecture

### High-Level Diagram

```
                          ┌─────────────────────────────────┐
                          │        GitHub Actions CI/CD      │
                          │  (provision.yml + deploy.yml)    │
                          └────────────┬────────────────────┘
                                       │ SSH + git pull + docker compose
                                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         GCP e2-micro VM (Ubuntu 22.04)               │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  Nginx reverse proxy (port 80/443) + Let's Encrypt SSL          │  │
│  └──────────────────┬──────────────────┬───────────────────────────┘  │
│                     │ /                │ /api/                          │
│                     ▼                 ▼                                │
│  ┌──────────────────────┐   ┌─────────────────────────────────────┐  │
│  │  Streamlit Frontend  │   │   FastAPI Orchestrator (port 8000)  │  │
│  │  (port 8501)         │   │                                     │  │
│  │  - 5 pages           │   │   7 routers:                        │  │
│  │  - Plotly charts     │   │   system / market / analytics /     │  │
│  │  - API client        │   │   intelligence / macro / ai /       │  │
│  └──────────────────────┘   │   user_data                         │  │
│                             │                                     │  │
│                             │  Spawns 6 MCP stdio subprocesses:   │  │
│                             │  ┌──────────┐  ┌──────────────┐    │  │
│                             │  │ americas │  │   europe     │    │  │
│                             │  ├──────────┤  ├──────────────┤    │  │
│                             │  │ asia_pac │  │    mena      │    │  │
│                             │  ├──────────┤  ├──────────────┤    │  │
│                             │  │analytics │  │  economics   │    │  │
│                             │  └──────────┘  └──────────────┘    │  │
│                             └─────────────────────────────────────┘  │
│                                                                        │
│  External APIs:  Finnhub · yfinance · Alpha Vantage · Marketaux ·     │
│                  FRED · Groq · Gemini · DuckDuckGo                     │
│  Cloud DB:       Google Cloud Firestore (watchlist + price alerts)     │
│  Domain:         marketmeshai.duckdns.org (free DDNS + HTTPS)          │
└──────────────────────────────────────────────────────────────────────┘
```

### Why this architecture? (key design decisions)

| Decision | What was chosen | Why |
|---|---|---|
| API orchestration | MCP stdio subprocesses | Isolation, single Python process per region, protocol standardisation |
| Backend framework | FastAPI | Async-first, automatic OpenAPI docs, Pydantic validation |
| Frontend | Streamlit | Rapid Python-native UI, no JS/React needed |
| Database | Firestore | Free 1 GB tier, serverless, no connection pooling needed on e2-micro |
| Cloud | GCP e2-micro | Always-free tier — zero cost indefinitely |
| CI/CD | GitHub Actions | Free for public repos, native GCP auth integration |

---

## 3. MCP — Model Context Protocol

### What is MCP?

MCP is a protocol developed by Anthropic (the company behind Claude) that standardises how AI applications communicate with tool-providing servers. In this project, MCP is repurposed as a general-purpose **inter-process communication protocol** between the FastAPI orchestrator and 6 specialised Python subprocesses.

**Key MCP concepts used in this project:**

| Concept | What it means in practice |
|---|---|
| **Server** | A Python subprocess exposing named "tools" (e.g., `get_real_time_quote`) |
| **Client** | The orchestrator's `ClientSession` object that calls tools via `session.call_tool()` |
| **stdio transport** | Communication via stdin/stdout — no TCP sockets, no ports |
| **Tool schema** | JSON Schema describing each tool's inputs, validated before dispatch |
| **TextContent** | Every tool returns `[TextContent(type="text", text=json_string)]` |
| **initialize()** | Handshake that registers all tools when the subprocess starts |

### MCP vs Alternatives

| Alternative | Why MCP was chosen over it |
|---|---|
| **HTTP microservices** | Would require 6 open ports + network stack. MCP stdio uses 0 extra ports |
| **gRPC** | Requires Protobuf schema definitions, complex setup for Python |
| **Message queues (RabbitMQ/Kafka)** | Overkill for tightly-coupled in-process services; adds infra cost |
| **REST APIs (Flask per server)** | Same port-management problem as HTTP microservices |
| **Direct function imports** | Would merge all 6 servers into one Python process — no isolation |
| **Celery tasks** | Designed for background jobs, not synchronous request/response |

### How MCP startup works (walk through the code)

```python
# orchestrator.py lifespan — the startup sequence
stack = AsyncExitStack()
for region in ["americas", "europe", "asia_pacific", "mena", "analytics", "economics"]:
    session = await asyncio.wait_for(_start_mcp_server(region, stack), timeout=30)
    _sessions[region] = session
    _session_status[region] = "connected"
```

```python
# mcp_client.py — what _start_mcp_server() does
script = os.path.join(SERVERS_DIR, region, "server.py")
params = StdioServerParameters(command=sys.executable, args=[script], env=dict(os.environ))
read, write = await stack.enter_async_context(stdio_client(params))
session = await stack.enter_async_context(ClientSession(read, write))
await session.initialize()  # MCP handshake — registers all tools
return session
```

**Key interview point:** `AsyncExitStack` is used so all 6 stdio transports share a single cleanup scope — if the orchestrator shuts down, all subprocesses are torn down in LIFO order automatically (no orphan processes).

### How a tool call flows

```
Route handler
  → mcp_call("americas", "get_real_time_quote", {"ticker": "AAPL", "exchange": "NASDAQ"})
    → _sessions["americas"].call_tool("get_real_time_quote", {"ticker": "AAPL", "exchange": "NASDAQ"})
      → [MCP protocol over stdin/stdout]
        → americas/server.py receives call
          → returns [TextContent(type="text", text='{"price": 189.5, ...}')]
      → orchestrator parses TextContent[0].text as JSON
    → returns dict to route handler
  → route handler caches + returns HTTP response
```

---

## 4. Backend — FastAPI & Python Async

### Why FastAPI over alternatives?

| Alternative | Reason not used |
|---|---|
| **Flask** | Synchronous by default — would block event loop on external API calls |
| **Django** | Too heavy; Django REST Framework adds unnecessary ORM/admin overhead |
| **aiohttp** | Lower-level; no automatic OpenAPI docs or Pydantic validation |
| **Tornado** | Older, less ergonomic async syntax; smaller ecosystem |
| **Sanic** | Smaller community, less mature ecosystem |

**FastAPI-specific features used:**
- `async def` route handlers — all MCP calls and HTTP calls are non-blocking
- `asyncio.create_task()` — parallel data fetching (e.g., fundamentals + quote + technicals simultaneously in the AI endpoint)
- `asyncio.gather()` — collect results from multiple concurrent tasks
- Automatic OpenAPI docs at `/docs` (Swagger UI)
- `@asynccontextmanager` lifespan — startup/shutdown logic for MCP and DB

### Key async patterns used

**Pattern 1: Parallel MCP calls with gather**
```python
# In ai.py — fetches 3 data sources simultaneously
fund_t = asyncio.create_task(mcp_call(region, FUNDAMENTALS_TOOL[region], {...}))
quot_t = asyncio.create_task(mcp_call(region, QUOTE_TOOL[region], {...}))
tech_t = asyncio.create_task(mcp_call("analytics", "compute_technical_indicators", {...}))
fundamentals, quote, technicals = await asyncio.gather(fund_t, quot_t, tech_t, return_exceptions=True)
```

**Pattern 2: asyncio.to_thread for blocking SDK calls**
```python
# Groq and Gemini SDKs are synchronous — wrap in to_thread to avoid blocking
resp = await asyncio.to_thread(
    client.chat.completions.create, model="llama-3.1-8b-instant", ...
)
```

**Pattern 3: ThreadPoolExecutor for yfinance (blocking I/O)**
```python
# yfinance uses requests (synchronous) — run in thread pool
with ThreadPoolExecutor(max_workers=3) as pool:
    am_futures = {sym: loop.run_in_executor(pool, _fetch_index, sym) for sym in symbols}
```

### Backend module structure

```
backend/
├── orchestrator.py          # FastAPI app init, lifespan, router registration
├── helpers/
│   ├── mcp_client.py        # _sessions dict, _start_mcp_server(), mcp_call(), mcp_watchdog()
│   ├── cache_helpers.py     # _mem_cache dict, _mem_get(), _mem_set()
│   ├── market_helpers.py    # EXCHANGE_REGION map, _get_region(), _market_status(), _fetch_index()
│   ├── enrichment.py        # Alpha Vantage enrichment, factor scoring, sentiment aggregation
│   ├── ai_helpers.py        # Dual-LLM functions: _ai_company_summary(), _ai_describe_company()
│   └── services.py          # Singleton instances: rate_limiter, cache_manager
└── routes/
    ├── system.py            # /, /health, /api/validation/stats, /mcp/tools/{region}
    ├── market.py            # /api/quote, /api/fundamentals, /api/global-snapshot, /api/news, /api/search
    ├── analytics.py         # /api/history, /api/technicals, /api/predict, /api/anomalies, /api/factors
    ├── intelligence.py      # /api/intelligence/correlation, /api/sector-performance, /api/peers
    ├── macro.py             # /api/macro/{indicator}, /api/ai/macro-context
    ├── ai.py                # /api/ai/company-summary, /api/ai/company-description
    └── user_data.py         # /api/watchlist (GET/POST/DELETE), /api/alerts (GET/POST/DELETE)
```

---

## 5. Data Sources & API Integration

### Data source map (what API powers what feature)

| Feature | Primary Source | Fallback | Notes |
|---|---|---|---|
| US real-time quotes | **Finnhub** | yfinance | 60 req/min free tier |
| Non-US quotes | **yfinance** | — | Exchange suffix mapping (e.g., `.T` for TSE) |
| Fundamentals (PE, ROE, etc.) | **yfinance .info** | Alpha Vantage OVERVIEW | AV enriches missing fields |
| Price history (OHLCV) | **yfinance .history()** | — | Used for charts, ML features |
| US macro data | **FRED REST API** | — | 800k+ free series |
| Company news (US) | **Marketaux** (entity-matched) | yfinance news → DuckDuckGo | 4-stage cascade |
| Company search | **Alpha Vantage SYMBOL_SEARCH** | yfinance.Search | 40k+ global equities |
| AI analysis | **Groq** (llama-3.1-8b-instant) | Google Gemini 2.0 Flash | Dual-LLM fallback |

### Exchange suffix mapping — how global stocks work

Non-US tickers on yfinance require an exchange suffix:
```python
EXCHANGE_SUFFIXES = {
    "LSE": ".L",      # London Stock Exchange (UK)
    "XETRA": ".DE",   # Deutsche Börse (Germany)
    "TSE": ".T",      # Tokyo Stock Exchange (Japan)
    "HKEX": ".HK",    # Hong Kong Exchange
    "NSE": ".NS",     # National Stock Exchange (India)
    "BSE": ".BO",     # Bombay Stock Exchange (India)
    "KRX": ".KS",     # Korea Exchange
    "ASX": ".AX",     # Australian Securities Exchange
    "TADAWUL": ".SR", # Saudi Arabia
    ...               # 25+ more
}
```

**Interview point:** Toyota's ticker on yfinance is `7203.T`, Samsung is `005930.KS`, Reliance Industries is `RELIANCE.NS`. The suffix tells yfinance which exchange's feed to use.

### Alpha Vantage enrichment pipeline

Why "enrich" rather than using AV as primary?
- AV's free tier allows only **5 calls/minute and 500/day** — not enough for primary data
- yfinance has no daily call limit and returns comprehensive `.info` dicts
- AV's OVERVIEW fills in fields that yfinance sometimes misses (forward PE, beta, EPS)
- Result: yfinance for speed + AV for completeness

```python
# The enrichment never overwrites — only fills missing fields
for key, val in av_enrichments.items():
    if val is not None and not data.get(key):   # only fill gaps
        data[key] = val
```

### News pipeline — 4-stage cascade

```
Stage 1: Marketaux entity-matched search (US stocks only)
         → Marketaux links articles to ticker via NLP entity extraction
         → Provides per-article financial sentiment scores from their model

Stage 2: Marketaux text/name search (fallback for non-US, or Stage 1 empty)
         → Uses company name (not numeric ticker) for non-US stocks
         → Sentiment falls back to keyword heuristics

Stage 3: yfinance .news (if < threshold articles after Stage 1+2)
         → Ticker-specific, no rate limit
         → Handles both new API format (content dict) and legacy flat format

Stage 4: DuckDuckGo web search (final fallback)
         → "{company_name} stock news" query
         → Keyword-based sentiment scoring
```

**Why this cascade?** Marketaux's free tier is 100 calls/day — exhausted quickly on a live platform. yfinance news is unlimited but lower quality. DDG ensures any obscure global stock always has some news.

---

## 6. Machine Learning & Analytics

### XGBoost Price Direction Prediction

**What it does:** Predicts whether a stock's closing price will be higher or lower N days from now.

**Why XGBoost over alternatives?**

| Alternative | Why XGBoost was chosen |
|---|---|
| **LSTM/GRU** (deep learning) | Requires GPU for training; e2-micro has 0.25 vCPU. XGBoost trains on CPU in 2-5s |
| **Random Forest** | Slower than XGBoost; less regularisation control |
| **Linear regression** | Too simple for non-linear market relationships |
| **ARIMA/SARIMA** | Time-series specific but doesn't handle feature interaction well |
| **Prophet** | Designed for trend/seasonality, not technical indicator features |
| **LightGBM** | Valid alternative — similar performance, but XGBoost has better SHAP integration |

**Feature engineering (15 features):**
```
RSI-14, MACD line, MACD signal, MACD histogram,
Bollinger Band width, Bollinger Band position (0=at lower, 1=at upper),
MA20 ratio (price/SMA20), MA50 ratio, MA200 ratio,
Volume Z-score (30-day rolling), ATR (14-day average true range),
1-day return, 5-day return, 20-day return, 6-month momentum
```

**Why these features?** They capture 4 distinct market signals:
- Momentum: RSI, MACD, returns
- Volatility regime: Bollinger Band width, ATR
- Trend: MA ratios (are we above/below moving averages?)
- Market participation: Volume Z-score

**Walk-forward cross-validation:**
```python
tscv = TimeSeriesSplit(n_splits=5)
# NOT standard k-fold — that would allow "future" data into training
# TimeSeriesSplit ensures each fold's test set is always AFTER its training set
```

**Why TimeSeriesSplit matters:** Standard k-fold randomly shuffles data, which would let a model train on December data to predict September data — cheating. TimeSeriesSplit respects chronological order.

**Honest accuracy reporting:** Backtest accuracy is typically 52-56% for liquid US stocks. This is explicitly disclosed in the response:
```json
{"disclaimer": "Not financial advice. ML predictions have limited accuracy (~52-56%)."}
```

### IsolationForest Anomaly Detection

**What it detects:** Unusual price/volume events — potential institutional activity, earnings surprises, or market-moving news.

**Why IsolationForest over alternatives?**

| Alternative | Limitation |
|---|---|
| **Z-score threshold** | Assumes normal distribution; stock returns are fat-tailed |
| **DBSCAN** | Density-based; sensitive to distance metric choice |
| **Autoencoders** | Requires training data, too heavy for per-request inference |
| **Grubbs test** | Univariate only; can't combine price + volume signals |

**IsolationForest intuition:** Anomalies are "easy to isolate" — they are separated from normal points by fewer random splits in a decision tree. Normal points cluster together and require many splits.

**3 features used:**
```python
features = {
    "ret":        daily_price_return,           # price anomaly
    "vol_zscore": (volume - vol_rolling_mean) / vol_rolling_std,  # volume spike
    "gap":        abs(close - prev_close) / prev_close,  # overnight gaps
}
```

**Contamination=0.05:** Flags approximately the 5% most unusual days, giving ~12 anomalies per year for a typical stock.

### Technical Indicators (implemented from scratch)

```python
# RSI — Wilder's smoothing approximation (rolling mean, not true EMA)
def _rsi(series, window=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(window).mean()
    loss  = (-delta.clip(upper=0)).rolling(window).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

# MACD — standard parameters: fast=12, slow=26, signal=9
def _macd(series):
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd  = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal, macd - signal

# Bollinger Bands — 20-period SMA ± 2 standard deviations
def _bollinger(series, window=20):
    sma   = series.rolling(window).mean()
    std   = series.rolling(window).std()
    return sma + 2*std, sma, sma - 2*std
```

**Why implemented from scratch instead of using `ta` library?**
- `ta` library is in requirements.txt but not used in the analytics server
- Custom implementation gives full control over edge cases (NaN handling, period boundaries)
- The code is more transparent and easier to explain in interviews
- Removes a dependency that could have version conflicts

### Factor Scoring Model

4-factor model inspired by quantitative finance frameworks (Fama-French):

| Factor | Formula | Financial meaning |
|---|---|---|
| **Value** | `100 - norm(PE, 5, 50)` | Low P/E = cheap relative to earnings |
| **Momentum** | `norm(6m_return, -30%, +60%)` | Trend-following signal |
| **Quality** | `avg(norm(ROE, -10, 40), norm(margin, -5, 30))` | Profitable, efficient business |
| **Low-Vol** | `norm(100 - annualised_vol, 0, 70)` | Low volatility = defensive/stable |

All scores are normalised to 0-100 and guaranteed JSON-safe (no NaN/Inf).

---

## 7. AI / LLM Integration

### Dual-LLM Strategy

```
Primary:  Groq (llama-3.1-8b-instant)
           └─ Sub-second inference, 14,400 tokens/min free, JSON mode
           
Fallback: Google Gemini 2.0 Flash
           └─ Higher quality output, JSON mime type, slightly more latency
           
Final:    Deterministic rule-based fallback
           └─ Always returns something — never a blank response
```

**Why Groq as primary?**
- `llama-3.1-8b-instant` inference is typically < 500ms — fast enough for interactive use
- Free tier: ~14,400 tokens/minute (generous for this use case)
- Native JSON mode (`response_format={"type": "json_object"}`) prevents markdown fences in output

**Why NOT OpenAI GPT as primary?**
- Cost: GPT-4o is ~$5-15/1M tokens vs Groq's free tier
- Latency: GPT-4o is typically 1-3s vs Groq's <0.5s
- Free tier: GPT's free tier is very limited; Groq's is much more generous

**Why NOT Claude (Anthropic) as LLM?**
- The project uses MCP (Anthropic's protocol) but not the Claude API for inference
- Claude would be ideal for quality, but Groq's free tier makes the project zero-cost to run
- Gemini fallback provides a Google-ecosystem backup that pairs naturally with GCP

### JSON mode — why it matters

Without JSON mode, LLMs tend to wrap JSON in markdown code blocks:
```
```json
{"summary": "..."}
```
```
This breaks `json.loads()`. JSON mode/mime-type forces the model to output raw JSON:
```python
# Groq:
response_format={"type": "json_object"}

# Gemini:
generation_config=genai.GenerationConfig(response_mime_type="application/json")
```

### Prompt engineering decisions

**Company summary prompt** (key constraints):
- Curated fundamentals keys only (not the full dict) — reduces hallucination from irrelevant data
- Top 5 news titles only — recency signal without overwhelming token budget
- Explicitly requests 4 specific fields — prevents LLM from adding/omitting structure
- `temperature=0.3` — analytical prose with slight creativity vs pure factual extraction

**Macro context prompt** (key constraints):
- Compact single-sentence FRED data summary — stays within llama-3.1-8b-instant's 8k context
- Explicitly bans `"Key: Value"` format inside text fields — forces Bloomberg-style prose
- Constrains `risks` to exactly 3 complete sentences — consistent frontend rendering
- `temperature` not set (uses model default) in macro route (contrast: 0.3 in company summary)

**asyncio.to_thread for SDKs:**
Both Groq and Gemini Python SDKs are synchronous. Calling them directly inside an `async def` route would block the entire FastAPI event loop, preventing all other requests from being processed. `asyncio.to_thread()` offloads the blocking call to a thread pool.

---

## 8. Caching Strategy

### 2-tier architecture

```
L1: In-memory dict (_mem_cache)
    → Python dict: {key: {data, expires}}
    → TTL-based eviction (checked on read, eager delete on stale)
    → O(1) lookup, zero I/O
    → Lives for process lifetime (cleared on container restart)
    → Thread-safe under asyncio/CPython GIL

L2: Redis (services/cache_manager.py)
    → Used on local dev only (Redis container in docker-compose.yml)
    → On GCP (e2-micro), Redis is skipped — not enough RAM
    → L1 alone handles production
```

### Why not Redis in production?

e2-micro has 1 GB RAM. Resource budget:
- Orchestrator container: 700 MB (ML libs, 6 MCP subprocesses, pandas/numpy)
- Frontend container: 250 MB (Streamlit + plotting)
- Redis: ~128 MB minimum

That's 1,078 MB — exceeds the 1 GB physical RAM. With 2 GB swap, it works, but:
- Swap is ~10x slower than RAM
- Redis under memory pressure evicts keys unpredictably
- The in-memory L1 cache already handles the low-traffic production workload well

**Alternative considered:** Memcached — lighter than Redis (~50 MB), but:
- No persistence if needed in future
- Less Python ecosystem support
- The in-memory dict is sufficient

### TTL decisions (design rationale)

| Data | TTL | Reasoning |
|---|---|---|
| Real-time quotes | 60s | Prices change second-by-second; 1-min is acceptable delay |
| Technical indicators | 300s | Computed from daily data; intraday changes are small |
| Fundamentals | 3600s | Quarterly earnings data — changes very rarely |
| AI company summary | 86400s | LLM calls are expensive; once/day is sufficient |
| Company descriptions | 604800s | Company's business doesn't change week-to-week |
| FRED macro data | 3600s | Published monthly — hourly refresh is more than enough |
| AI macro context | 14400s | LLM generation cost + FRED data changes monthly |
| Search results | 86400s | Ticker-to-company mappings are stable |

---

## 9. Database — Firestore

### Why Firestore over PostgreSQL?

The original plan included PostgreSQL with SQLAlchemy. Firestore replaced it for cloud deployment.

| Criterion | PostgreSQL | Firestore |
|---|---|---|
| **Cost on e2-micro** | Needs another container (~256 MB) — too much RAM | Serverless, no container needed |
| **Free tier** | Not included in GCP always-free | 1 GB storage, 50K reads/day, 20K writes/day — free forever |
| **Auth on GCP VM** | Needs password in .env | ADC (Application Default Credentials) — automatic via VM metadata |
| **Schema flexibility** | Fixed schema, migrations needed | Schema-free documents — easy to evolve |
| **Connection pooling** | Complex under asyncio | Async Firestore client, no pooling needed |
| **Consistency** | ACID transactions | Eventual consistency acceptable for watchlist |

**ADC (Application Default Credentials):** On a GCP VM with `cloud-platform` scope, the VM's service account credentials are automatically available via the instance metadata service at `http://metadata.google.internal`. The Firestore SDK picks these up without any key file — this is a key GCP feature.

```python
# No key file needed on the VM — ADC handles auth automatically
_fs_client = firestore.AsyncClient(project=project_id)
```

### Firestore data model

```
Collection: watchlist
  Document ID: {TICKER}_{EXCHANGE}  (e.g., "AAPL_NASDAQ", "RELIANCE_NSE")
  Fields:
    ticker:   "AAPL"
    exchange: "NASDAQ"
    added_at: "2026-04-28T10:30:00+00:00"

Collection: alerts
  Document ID: auto-generated
  Fields:
    ticker:     "AAPL"
    exchange:   "NASDAQ"
    threshold:  185.0
    direction:  "above"
    triggered:  false
    created_at: "2026-04-28T10:30:00+00:00"
```

**Why composite document ID for watchlist?** Using `{TICKER}_{EXCHANGE}` as the document ID ensures idempotent writes (same ticker+exchange always overwrites the same document) and makes existence checks O(1) — just a `.get()` on the known ID.

### In-memory fallback pattern

```python
# init_db() attempts Firestore; silently falls back to in-memory
if not GCP_PROJECT_ID:
    return  # use _watchlist_mem list
try:
    _fs_client = firestore.AsyncClient(...)
    # probe with a 1-doc stream to confirm credentials work
    async for _ in _fs_client.collection("watchlist").limit(1).stream():
        break
    _using_firestore = True
except Exception:
    _fs_client = None
    _using_firestore = False  # will use _watchlist_mem
```

This "try Firestore, fall back silently" pattern means the app always starts, even without GCP credentials — critical for local development.

---

## 10. Frontend — Streamlit

### Why Streamlit over alternatives?

| Alternative | Limitation for this project |
|---|---|
| **React + REST** | Requires JavaScript, separate build step, CORS config, deployment complexity |
| **Vue.js / Angular** | Same as React |
| **Dash (Plotly)** | Similar to Streamlit but more boilerplate; Plotly is shared anyway |
| **Gradio** | Primarily ML demo tool; limited layout flexibility |
| **Tableau/Power BI** | Commercial, not code-first, poor API integration |
| **Panel** | Less popular, less community support |

**Streamlit's advantages here:**
- Pure Python — same language as the backend, no context switching
- `st.plotly_chart()` renders Plotly figures natively
- Session state for persistent watchlist navigation (`st.session_state`)
- `st.rerun()` for programmatic page refresh
- Auto-layout: `st.columns()`, `st.tabs()`, `st.expander()` for complex UIs

### Frontend image size optimisation

Problem: Root `requirements.txt` includes xgboost, scikit-learn, nvidia-nccl-cu12 (294 MB GPU driver) — these are backend-only. Frontend Dockerfile was copying the root requirements.txt → 2 GB frontend image → 40-minute Docker build on e2-micro.

Solution: Separate `frontend/requirements.txt` with 9 packages only:
```
streamlit, plotly, pydeck, pandas, numpy, python-dateutil, requests, python-dotenv, pytz
```
Result: Frontend image ~200 MB vs ~2 GB.

### Page architecture

```
frontend/
├── app.py                    # Entry point: st.set_page_config, sidebar, watchlist
├── api_client.py             # HTTP requests to backend (timeout handling, error formatting)
├── utils.py                  # EXCHANGE_REGION map, formatters, market_open(), search_result_to_exchange()
├── components/
│   └── charts.py             # Reusable Plotly chart builders (candlestick, RSI, MACD, Bollinger)
└── pages/
    ├── home.py               # Quick quote + global market status
    ├── company_explorer.py   # Full company analysis: quote, fundamentals, AI, news, charts, peers
    ├── stock_charts.py       # Candlestick + technical indicators + XGBoost prediction
    ├── global_overview.py    # Cross-market correlation heatmap + sector performance
    └── macro_dashboard.py    # FRED macro charts + AI narrative
```

---

## 11. Infrastructure & Cloud

### GCP e2-micro Always-Free Tier

**Why e2-micro?** GCP's always-free tier includes:
- 1 e2-micro instance per month in `us-central1`, `us-east1`, or `us-west1`
- 30 GB standard persistent disk
- 1 GB external egress/month
- Cost: $0.00/month, no expiry, no credit card charge

**RAM management on 1 GB:**
- 2 GB swap file created at VM startup (`vm-startup.sh`)
- Docker memory limits: orchestrator 700 MB, frontend 250 MB
- Swap tuned to `vm.swappiness=10` (use swap only under real pressure)
- Redis excluded from GCP compose (saves 128 MB)
- Python selective ML imports: xgboost/sklearn are imported inside functions, not at module level

**Why 30 GB disk matters for Docker:** Docker layer exports (when building images) write to `/var/lib/docker`. The orchestrator image is ~2 GB. On a 30 GB disk, there's room for multiple image versions + build cache. The VM startup script explicitly sets `--boot-disk-size=30GB`.

### Infrastructure as Code

Two GitHub Actions workflows handle all infrastructure:

**provision-gcp.yml (run once):**
1. Create e2-micro VM with startup script
2. Upload SSH public key (derived from GCP_SSH_KEY secret, username = "marketmesh")
3. Enable Firestore API
4. Grant `roles/datastore.user` to VM's default service account
5. Create Firestore database (native mode, nam5 region)
6. Reserve static external IP (prevents IP change on VM restart)
7. Create firewall rules (open ports 80, 443, 8000, 8501)

**deploy-gcp.yml (on every push to main):**
1. Auth with GCP, get VM IP dynamically (no IP secret needed)
2. Update DuckDNS with current IP (idempotent)
3. SSH: write `.env` from GitHub Secrets
4. SSH: selective rebuild + docker compose up
5. SSH: configure Nginx + run Certbot (idempotent)
6. SSH: install/update watchdog cron
7. HTTP health check from Actions runner

### Why `gcloud compute instances describe` for IP instead of a secret?

Ephemeral IPs change on VM restart. Static IPs were reserved, but:
- The IP could theoretically change if the static reservation is accidentally deleted
- Dynamically looking up the IP via gcloud removes the `GCP_VM_IP` secret from the list
- Makes the workflow self-healing: even if the IP changes, the next deploy picks it up automatically

---

## 12. CI/CD — GitHub Actions

### Workflow design decisions

**Two separate workflows (provision vs deploy):**
- Provision is run-once — creating a VM twice would fail (idempotent checks protect against this, but it's unnecessary cost)
- Deploy runs on every push — must be fast and reliable
- Separating them prevents accidental infrastructure changes on every code push

**Selective rebuild logic (deploy-gcp.yml):**
```bash
CHANGED=$(git diff --name-only HEAD~1..HEAD)
echo "$CHANGED" | grep -qE '^(backend/|mcp_servers/|requirements\.txt|docker-compose)' \
  && BUILD_ORCHESTRATOR=yes || BUILD_ORCHESTRATOR=no
```
- Backend change → rebuild orchestrator only (~20 min) → skip frontend build (~2 min)
- Frontend change → rebuild frontend only (~2 min) → skip orchestrator build (~20 min)
- No code change (e.g., README edit) → skip both, just restart

**Why `timeout-minutes: 60`?** The orchestrator image is ~2 GB. On e2-micro's standard HDD:
- pip install layer: cached (no change if requirements.txt unchanged)
- COPY layers: ~15-20 min to export to HDD when code changes
- Health wait: up to 8 min (48 × 10s)
- Total worst case: ~30 min with 30 min buffer

**SSH quoted-string vs heredoc:**
YAML processes `|` block scalars before bash sees them. Nested heredocs inside YAML cause indentation conflicts (heredoc content must be at column 0, but YAML requires indentation). Solution: SSH quoted-string with escaped variables:
```yaml
run: |
  ssh ... marketmesh@$IP \
    "set -euo pipefail
     git pull
     sudo docker compose up -d"
```
Vs heredoc (BROKEN — `ENDSSH` content must be at column 0 in bash):
```yaml
run: |
  ssh ... << 'ENDSSH'       # YAML indentation conflict!
  git pull
  ENDSSH
```

**DuckDNS secret stripping:**
```bash
DOMAIN=$(printf '%s' '${{ secrets.DUCKDNS_DOMAIN }}' | tr -d '[:space:]')
```
GitHub Secrets sometimes have trailing newlines. If used directly in a URL, curl reports "exit code 3 (URL malformed)". `tr -d '[:space:]'` strips all whitespace characters.

---

## 13. Containerisation — Docker & Docker Compose

### Docker layer caching strategy

```dockerfile
# backend/Dockerfile — CORRECT order (cache-friendly)
COPY requirements.txt .        ← Layer 1: pip install layer — CACHED if requirements unchanged
RUN pip install --no-cache-dir -r requirements.txt
COPY . .                       ← Layer 2: code — only invalidated when code changes
```

If `COPY . .` came first, every code change would invalidate the pip install layer (Docker invalidates all subsequent layers when any layer changes). This would cause a full 15-20 minute pip install on every deploy instead of just when requirements change.

### Two compose files

`docker-compose.yml` (local dev):
- `restart: unless-stopped`
- Redis service included
- 90s health check start_period
- No mem_limit

`docker-compose-gcp.yml` (cloud):
- `restart: always` (restarts even after daemon restart)
- No Redis (saves RAM)
- 120s health check start_period (e2-micro is slower)
- `mem_limit: 700m` / `250m` (prevents OOM kill)
- Smarter health check (exits 1 on "degraded" status, not just any HTTP response)

**`restart: always` vs `restart: unless-stopped`:**
- `unless-stopped`: container does NOT restart if it was manually stopped (docker stop)
- `always`: container ALWAYS restarts, even after `docker stop` (requires `docker rm` to prevent)
- Production uses `always` — if the container crashes at 3am, it must self-restart without human intervention

### Memory limits — why they matter

Without `mem_limit: 700m`, the orchestrator (with 6 MCP subprocesses + pandas/numpy/xgboost loaded) could grow to 1.5 GB+ during ML prediction, triggering the Linux OOM killer on the entire VM. With the limit, Docker kills only the container when it exceeds 700 MB, and `restart: always` immediately respawns it.

---

## 14. Networking — Nginx + Certbot + DuckDNS

### Why this stack?

| Component | Purpose | Alternative |
|---|---|---|
| **Nginx** | Reverse proxy — routes `/` → Streamlit:8501, `/api/` → FastAPI:8000 | Caddy (auto-HTTPS, simpler config), Traefik |
| **Certbot** | Automates Let's Encrypt SSL cert issuance and renewal | Caddy (handles SSL automatically), acme.sh |
| **DuckDNS** | Free dynamic DNS — maps subdomain to changing VM IP | No-IP, Afraid.org, ngrok |

**Why Nginx over Caddy?** Both work equally well. Nginx was chosen because:
- More widely documented — easier to debug in interviews
- `--nginx` certbot flag integrates seamlessly
- Familiar to most DevOps engineers

**Nginx WebSocket config for Streamlit:**
```nginx
# Streamlit uses WebSocket for live updates — must proxy upgrade headers
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```
Without these, Streamlit's WebSocket connection falls back to polling, causing UI freezes.

**Certbot `--nginx` flag mechanics:**
1. Nginx must be running with an HTTP config already (the `__DOMAIN__` template)
2. Certbot performs ACME HTTP-01 challenge: GETs `http://domain/.well-known/acme-challenge/{token}`
3. Certbot reads the existing nginx config and ADDS a 443 SSL server block automatically
4. Certbot installs a cron job (or systemd timer) for auto-renewal
5. `--keep-until-expiring`: skips renewal if the cert is valid for more than 30 days (avoids Let's Encrypt rate limit of 5 certs/domain/week)

**DuckDNS update on every deploy:**
```bash
curl "https://www.duckdns.org/update?domains=${DOMAIN}&token=${TOKEN}&ip=${IP}"
```
- Returns "OK" if IP updated, "OK" if IP unchanged — always safe to call
- Runs before Nginx step — ensures domain points to correct IP before Certbot verifies it

---

## 15. Self-Healing — The 4-Layer Watchdog System

### The problem being solved

MCP servers are Python subprocesses. On a 1 GB RAM server, any subprocess can be OOM-killed by Linux when memory pressure spikes (e.g., during XGBoost training). When a subprocess dies:
- The `ClientSession` object in `_sessions` becomes stale (the process is dead but the Python object persists)
- `_session_status["analytics"]` still shows "connected" (it was set at startup and never updated)
- `/health` reports "healthy" (false positive!)
- User requests to that MCP server fail silently or return 503 errors
- No automatic recovery — the dead subprocess stays dead

### The 4-layer solution

```
Layer 1: In-process watchdog (mcp_watchdog asyncio task, 60s interval)
│   Pings each session via session.list_tools() every 60 seconds
│   Sets _session_status[region] = "timeout" when a session is dead
│   _session_status feeds the /health endpoint — now accurately reflects reality
│   └─ Detects death within 60 seconds

Layer 2: Docker health check (30s interval, exit 1 on "degraded")
│   Reads /health and exits 1 if status != "healthy"
│   After 5 consecutive failures → container marked "unhealthy"
│   BUT: Docker health check does NOT restart containers automatically!
│   restart: always handles the actual restart
│   └─ Marks container unhealthy within ~5 minutes

Layer 3: Docker restart policy (restart: always)
│   When a container EXITS (crashes or OOM-killed), Docker restarts it
│   Does NOT trigger on health check failure alone (common misconception)
│   Works for: process crash, OOM kill, unhandled exception
│   Does NOT work for: MCP subprocess death (parent container stays alive)
│   └─ Handles full container crashes, not subprocess-level failures

Layer 4: VM cron watchdog (every 5 minutes)
    Checks /health via curl on localhost:8000
    If status != "healthy" → runs docker compose restart orchestrator
    Forces a container restart even when the container itself is still running
    This closes the gap: Layer 3 (restart:always) doesn't help when the container
    is alive but has dead MCP subprocesses inside it
    └─ Catches the "alive container with dead subprocesses" case

Total worst-case downtime:
  MCP dies → Layer 1 detects in ≤60s
  → /health reports "degraded"
  → Layer 4 cron runs within ≤5min
  → docker compose restart orchestrator (~2 min to come back up)
  = worst case ~7-8 minutes, fully automatic
```

### Why all 4 layers are needed

| Failure scenario | Layer that handles it |
|---|---|
| Full container OOM-killed | Layer 3 (restart:always) |
| Full container unhandled exception | Layer 3 |
| MCP subprocess OOM-killed, container alive | Layer 4 (cron) |
| MCP subprocess crash, container alive | Layer 4 (cron) |
| Orchestrator HTTP server crash | Layer 3 |
| VM reboot | Layer 3 (containers restart with Docker daemon) |
| False positive health report | Layer 1 (watchdog updates status accurately) |

---

## 16. Security Considerations

### Secrets management

- API keys stored as GitHub Secrets — never in code or git history
- Written to VM's `/opt/marketmesh/.env` via SSH on each deploy (overwritten, not appended)
- `.env` has `chmod 600` — readable only by the `marketmesh` user
- `.env` is in `.gitignore` — never committed

### SSH setup

- ed25519 key pair generated once
- Private key stored as `GCP_SSH_KEY` GitHub Secret
- Public key derived at deploy time with `ssh-keygen -y -f priv_key` — the public key is never stored separately
- VM username hardcoded to "marketmesh" (not root, not ubuntu)
- `StrictHostKeyChecking=no` + `ssh-keyscan` — accepts VM host key automatically (necessary for CI, acceptable trade-off)

### GCP IAM

- Service account with minimal roles: `compute.admin`, `iam.serviceAccountUser`, `datastore.owner`
- VM service account has only `roles/datastore.user` — cannot manage other GCP resources
- `--scopes=https://www.googleapis.com/auth/cloud-platform` on VM — enables ADC for Firestore

### CORS

```python
app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)
```
`allow_origins=["*"]` is intentionally permissive here — this is a public read-only stock data API. For a production app handling user authentication, this would be locked to the specific frontend domain.

### Known limitations / trade-offs

1. `StrictHostKeyChecking=no` — accepts any host key (MITM risk, acceptable for demo)
2. `--register-unsafely-without-email` in Certbot — cert renewal notifications won't be emailed
3. `sudo docker compose` in cron — the `marketmesh` user has passwordless sudo for docker (required for cron context; Docker's socket permission model requires this)

---

## 17. Rate Limiting & Quota Management

### RateLimitManager implementation

```python
# Sliding window algorithm using a deque
self.limits = {
    'finnhub':       {'calls': deque(maxlen=60),   'limit': 60,   'window': 60},    # 60/min
    'alpha_vantage': {'calls': deque(maxlen=25),   'limit': 25,   'window': 86400}, # 25/day
    'marketaux':     {'calls': deque(maxlen=100),  'limit': 100,  'window': 86400}, # 100/day
    'yfinance':      {'calls': deque(maxlen=2000), 'limit': 2000, 'window': 3600},  # soft
}
```

**Why sliding window over fixed window?**
- Fixed window: 100 calls allowed per day reset at midnight. A burst of 100 calls at 11:59pm and 100 at 12:01am would send 200 calls in 2 minutes.
- Sliding window: the deque tracks call timestamps. At any moment, only calls within the last `window` seconds count toward the limit.

**How the deque approach works:**
- `deque(maxlen=60)`: automatically discards the oldest entry when full
- Before each call: remove timestamps older than `window` from the left
- If `len(deque) < limit`: append now() and allow the call
- Otherwise: calculate `wait_time = deque[0] + window - now` and sleep

### The L1 cache is the primary quota defence

The rate limiter is a safety net. The real quota protection is caching:
- Alpha Vantage: 25 calls/day free. With 86400s (24h) TTL on AV results and 500/day limit, each unique ticker only hits AV once per day.
- Marketaux: 100 calls/day. With the 4-stage cascade and news TTL, most requests are served from L1.
- The rate limiter only activates when a fresh fetch is genuinely needed.

---

## 18. Likely Interview Questions & Model Answers

### Architecture

**Q: Why did you use MCP instead of a standard REST API between your services?**

A: "MCP gave me three specific advantages. First, no port management — 6 REST services would need 6 open ports plus service discovery. MCP uses stdin/stdout, so 0 extra ports. Second, the protocol includes a built-in tool schema registry via `list_tools()` — each subprocess documents its own capabilities, so the orchestrator can introspect them programmatically. Third, `AsyncExitStack` handles teardown automatically — when the orchestrator shuts down, all 6 subprocesses are torn down in reverse order with no orphan processes. The main trade-off is that MCP requires all servers to be on the same machine; it doesn't support distributed deployment. For this project's scale on a single VM, that's fine."

**Q: How do you handle failures in your system?**

A: "Four layers. Layer 1 is an in-process asyncio watchdog that pings each MCP session every 60 seconds and updates the health status dict — so the /health endpoint always reflects reality, not just the startup state. Layer 2 is the Docker health check which exits 1 when any MCP server is degraded. Layer 3 is `restart: always` which handles full container crashes — OOM kills, unhandled exceptions, VM reboots. Layer 4 is a VM-level cron job that runs every 5 minutes and calls `docker compose restart orchestrator` whenever /health returns degraded. This closes the gap that Docker's restart policy misses: a container that's alive but has dead subprocesses inside. Worst case recovery is 7-8 minutes, fully automatic."

**Q: Why Streamlit and not React for the frontend?**

A: "The key constraint was team size and velocity. Streamlit lets you build the entire frontend in Python — same language as the backend, no context switching. For this project's data-heavy dashboard use case, Streamlit's built-in `st.plotly_chart()`, `st.tabs()`, `st.columns()`, and `st.session_state` handled everything needed. A React frontend would add a build step, separate deployment, CORS configuration, TypeScript types for the API responses, and state management complexity — easily 2-3x the development time for the same functional result. The trade-off is that Streamlit's server-side rendering model means more network round-trips for interactive widgets, but at this traffic scale, that's invisible to users."

### Machine Learning

**Q: Why XGBoost for stock prediction? Isn't LSTM better for time-series?**

A: "LSTMs are better in theory but impractical here for two reasons. First, the e2-micro VM has 0.25 vCPU — LSTM training on 5 years of daily data would take minutes per request instead of XGBoost's 2-5 seconds. Second, LSTMs shine with raw sequences; our features are already heavily engineered (RSI, MACD, Bollinger Bands) — these tabular technical features are exactly what tree-based models are designed for. XGBoost handles mixed-scale features without normalisation issues, is robust to outliers, and gives us SHAP values for explainability out of the box. We use TimeSeriesSplit for cross-validation — not k-fold — because shuffled folds would let future data leak into training. The honest backtest accuracy of 52-56% is explicitly shown in the UI with a disclaimer. We're not hiding the model's limitations."

**Q: What is IsolationForest and why use it for anomaly detection?**

A: "IsolationForest is an unsupervised anomaly detection algorithm. The key insight is that anomalies are 'easy to isolate' — in a random decision tree, you need fewer splits to isolate a data point that's far from the bulk of the data. Normal points cluster together and require many splits. We use it with 3 features: daily return, volume Z-score, and price gap. The contamination parameter (0.05) tells it to expect about 5% of days to be anomalous — roughly 12-13 days per year for a typical stock. We chose it over a simple Z-score threshold because stock returns are fat-tailed (leptokurtic), meaning Z-scores undercount true tail events. IsolationForest is distribution-free — it makes no normality assumption."

**Q: Explain the 4-factor scoring model.**

A: "It's inspired by academic factor models, especially Fama-French. The four factors — Value, Momentum, Quality, and Low-Volatility — are the four most academically well-supported sources of excess return in equities. Value uses P/E ratio (lower is better), Momentum uses 6-month price return (trend-following), Quality uses ROE and profit margin (profitable, efficient businesses tend to outperform), and Low-Vol uses annualised 6-month volatility inverted (low-volatility stocks historically outperform risk-adjusted). Everything is normalised to 0-100 using simple min-max scaling with hand-tuned min/max values based on typical ranges — for example, P/E between 5 and 50, where 5 is very cheap and 50 is expensive."

### API & Data

**Q: You have 8 external APIs. How do you manage their rate limits?**

A: "Two-layer defence. The primary defence is caching — fundamentals are cached for 1 hour, AI summaries for 24 hours. Most repeat requests for the same ticker never hit the external API. The secondary defence is a sliding-window rate limiter using Python's deque. Before each Alpha Vantage call, the rate limiter checks how many calls have been made in the last 86400 seconds and blocks (with asyncio.sleep) if we're at the limit. Alpha Vantage's 25 calls/day free tier is the tightest constraint — the 24-hour cache means each unique ticker only needs one AV call per day."

**Q: How do you handle global stocks? What makes a non-US ticker work?**

A: "yfinance uses exchange suffixes to identify non-US listings. For example, Toyota Motor Corporation's ticker on yfinance is `7203.T` — the `.T` suffix means Tokyo Stock Exchange. Samsung is `005930.KS` for Korea Exchange. Reliance Industries is `RELIANCE.NS` for India's National Stock Exchange. The project maintains a dictionary mapping exchange codes to suffixes: `{"TSE": ".T", "NSE": ".NS", "KRX": ".KS", ...}`. When a user selects 'Toyota' and 'TSE', the analytics server looks up `.T` and fetches `7203.T` from yfinance. For search, Alpha Vantage SYMBOL_SEARCH handles name→ticker lookup for 40k+ global securities, and yfinance.Search is used as a secondary source that's better for local-exchange tickers that AV underranks."

### DevOps & Infrastructure

**Q: How did you achieve zero-cost production deployment?**

A: "GCP's always-free tier includes one e2-micro instance per month in specific US regions — that's 1 vCPU burst / 1 GB RAM / 30 GB disk, no expiry, no credit card charge. The constraint is 1 GB RAM for the entire stack. I solved this by: excluding Redis (saves 128 MB), setting Docker memory limits (700 MB orchestrator + 250 MB frontend), adding 2 GB swap for ML workloads, and using Firestore instead of PostgreSQL (serverless — no container needed). The domain is DuckDNS (free), SSL is Let's Encrypt (free), and CI/CD is GitHub Actions (free for public repos)."

**Q: Walk me through what happens when you push code to main.**

A: "GitHub Actions triggers the deploy workflow. It authenticates with GCP using a service account key stored as a GitHub Secret, then looks up the VM's external IP dynamically using gcloud — no hardcoded IP secret needed. It updates DuckDNS with the current IP, writes a fresh `.env` file on the VM from GitHub Secrets via SSH, then SSHes in to do the actual deploy. The deploy step checks which files changed using `git diff HEAD~1..HEAD` and only rebuilds the Docker image(s) that need it — if only frontend files changed, it skips the 20-minute orchestrator rebuild. After building, it starts the orchestrator, waits up to 8 minutes for it to become healthy (checking the /health endpoint in a loop), then starts the frontend. After that, it re-configures Nginx and runs Certbot idempotently (no-ops if cert is still valid), reinstalls the watchdog cron, and finally does an HTTP health check from the Actions runner to confirm the app is responding."

**Q: What's the biggest technical challenge you faced?**

A: "The 40-minute CI/CD timeout caused by the e2-micro's slow HDD. The orchestrator Docker image is ~2 GB because it includes xgboost, scikit-learn, numpy, pandas, and 6 MCP server modules. Even with pip install cached, exporting new code layers to the HDD takes 20-25 minutes. I solved it two ways: first, split the frontend into a separate requirements.txt with only 9 Streamlit packages — this dropped the frontend image from ~2 GB to ~200 MB. Second, added selective rebuild logic that diffs HEAD~1..HEAD and skips rebuilding whichever image didn't change. A frontend-only push now finishes in 5 minutes. A backend-only push takes 25 minutes but stays well under the new 60-minute timeout."

### General Software Engineering

**Q: How does the in-memory cache work, and is it thread-safe?**

A: "It's a plain Python dictionary keyed by a string (e.g., `'quote:AAPL:NASDAQ'`) where each value stores the data and an expiry datetime. On read, we check `datetime.now() < entry['expires']`; if stale, we delete the entry and return None. On write, we store data + `datetime.now() + timedelta(seconds=ttl)`. Under CPython's asyncio model, it's thread-safe because the GIL serialises all dict operations, and asyncio is single-threaded — coroutines don't truly run concurrently, they interleave at `await` points. The caveat is that this wouldn't be safe if we used a multi-threaded executor or multiple processes sharing this dict — but we don't."

**Q: Why `asyncio.to_thread()` for Groq/Gemini SDK calls?**

A: "Both SDKs are synchronous — they use the `requests` library internally, which blocks the calling thread. FastAPI runs on a single event loop thread (by default). If we call a synchronous function from an `async def` route without wrapping it, the event loop is blocked for the entire duration of the HTTP call — typically 0.5-3 seconds for LLM inference. During that time, all other incoming requests are frozen. `asyncio.to_thread()` runs the blocking function in a thread pool (Python's default ThreadPoolExecutor), which frees the event loop to process other requests while the LLM call is in-flight. The alternative would be to use AsyncGroq (which the macro context endpoint does use), but for the company summary endpoint we use the sync client wrapped in to_thread."

**Q: If you were to scale this to 10,000 users, what would you change?**

A: "Several things. First, move MCP servers to separate containers or processes — they're currently subprocesses on one machine, which limits horizontal scaling. Second, add Redis as a shared L2 cache in front of multiple orchestrator instances — the current L1 in-memory cache is per-process. Third, replace Streamlit with a proper React frontend — Streamlit's server-side rendering doesn't scale well; every user interaction triggers a Python rerun. Fourth, use a managed PostgreSQL (Cloud SQL) instead of Firestore for the watchlist and alerts — more familiar query patterns and ACID guarantees if we add portfolio tracking. Fifth, add a proper job queue (Cloud Tasks or Celery) for ML predictions since XGBoost training per-request is expensive. Sixth, add CDN caching for static assets and add API authentication with rate limiting per user."

---

## Quick Reference — Technology Choices Summary

| Technology | Used For | Key Alternative(s) Not Used | Why Chosen |
|---|---|---|---|
| **FastAPI** | REST API framework | Flask, Django, aiohttp | Async-first, auto OpenAPI docs |
| **MCP (stdio)** | Inter-process communication | gRPC, HTTP microservices, REST | No ports, built-in schema, Anthropic standard |
| **Streamlit** | Frontend UI | React, Vue, Dash | Pure Python, fast development |
| **Plotly** | Charts | D3.js, Chart.js, Matplotlib | Interactive, Python-native |
| **yfinance** | OHLCV + fundamentals | Quandl, Bloomberg, Refinitiv | Free, no API key, 200k+ securities |
| **Finnhub** | Real-time US quotes | IEX Cloud, Polygon.io | 60 req/min free tier, WebSocket support |
| **Alpha Vantage** | Enrichment, search | Tiingo, EOD Historical Data | 40k+ global securities, SYMBOL_SEARCH |
| **FRED API** | Macroeconomic data | World Bank API, OECD | 800k+ free series, official US govt data |
| **Marketaux** | News + NLP sentiment | NewsAPI, GDELT | Entity-level sentiment scores, financial NLP |
| **DuckDuckGo Search** | News fallback | Bing News API, Google News | Completely free, no API key |
| **Groq** | AI inference (primary) | OpenAI GPT-4, Anthropic Claude | Sub-second, free tier, JSON mode |
| **Google Gemini** | AI inference (fallback) | OpenAI GPT-3.5, Mistral | Google ecosystem, JSON mime type |
| **XGBoost** | Price direction prediction | LSTM, ARIMA, Prophet, LightGBM | CPU-fast, SHAP support, tabular features |
| **IsolationForest** | Anomaly detection | DBSCAN, Z-score, Autoencoders | Distribution-free, unsupervised |
| **Firestore** | Persistent storage | PostgreSQL, SQLite, MongoDB | Serverless, free 1 GB, ADC auth on GCP |
| **Docker** | Containerisation | Podman, LXC | Industry standard, Compose ecosystem |
| **Nginx** | Reverse proxy | Caddy, Traefik, HAProxy | Battle-tested, excellent docs |
| **Certbot** | TLS certificates | Caddy (auto), acme.sh | Native --nginx flag, auto-renewal |
| **DuckDNS** | Free dynamic DNS | No-IP, Afraid.org, ngrok | Truly free, simple API |
| **GCP e2-micro** | Cloud hosting | AWS t2.micro, Hetzner CX11 | Always-free tier, no expiry, Firestore ADC |
| **GitHub Actions** | CI/CD | CircleCI, Jenkins, GitLab CI | Free for public repos, GCP integration |
| **asyncio** | Concurrency | Celery, threading, multiprocessing | Native Python async, event loop |
| **httpx** | Async HTTP client | aiohttp, requests | Async-first, clean API, timeout support |

---

*Last updated: April 2026. Covers codebase at commit 2a825a2 (selective rebuild + 60-min timeout fix).*
