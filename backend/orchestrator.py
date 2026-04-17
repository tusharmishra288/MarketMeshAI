"""
StockPilot AI — Orchestrator (FastAPI Entry Point).

This module is the single entry-point for the backend service. It creates the
FastAPI application, bootstraps all six regional/analytical MCP servers as
persistent stdio subprocesses during startup, and registers the seven API
routers that expose every REST endpoint to the frontend.

Routers registered
------------------
- system:       Health check, root, MCP tool listing, cache/validation stats.
- market:       Quote, fundamentals, global snapshot, news aggregation, search.
- analytics:    Price history, technical indicators, ML prediction, anomalies, factors.
- intelligence: Cross-market correlation, sector performance, sector peers.
- macro:        FRED macro indicators and AI-generated macro context narrative.
- ai:           AI company summary and AI company description endpoints.
- user_data:    Watchlist and price-alert CRUD.

MCP servers started at lifespan
--------------------------------
- americas:     NYSE/NASDAQ/TSX quotes & fundamentals via Finnhub + yfinance.
- europe:       LSE/XETRA/Euronext/Nordic quotes & fundamentals via yfinance.
- asia_pacific: TSE/HKEX/NSE/KRX/ASX quotes & fundamentals via yfinance.
- mena:         TADAWUL/DFM/ADX/TASE quotes & fundamentals via yfinance.
- analytics:    Technical indicators, XGBoost prediction, IsolationForest anomaly detection.
- economics:    FRED macro series (yield curve, inflation, Fed rate, GDP, PMI).

Dependencies
------------
- FastAPI:          Web framework and router system.
- MCP (stdio):      Model Context Protocol for subprocess communication with servers.
- python-dotenv:    Loads API keys from the root-level .env file at startup.
- uvicorn:          ASGI server when run as __main__.
"""

import os
import sys
import asyncio
import logging
from contextlib import asynccontextmanager, AsyncExitStack
from dotenv import load_dotenv

# ── Bootstrap ─────────────────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Ensure backend/ is on sys.path so route/helper imports resolve
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from helpers.mcp_client import _sessions, _session_status, _start_mcp_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s [orchestrator] %(message)s")
log = logging.getLogger(__name__)

# ── Lifespan: start MCP servers and database ──────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager — startup and shutdown logic.

    Startup sequence:
      1. Open a shared AsyncExitStack so all MCP stdio transports share a single
         cleanup scope (prevents resource leaks if one server fails mid-startup).
      2. Warn about missing API keys so operators know which features are degraded.
      3. Start each MCP server subprocess sequentially with a 30-second timeout.
         Servers that timeout or raise are marked "timeout"/"error" in
         _session_status but do NOT abort the rest of the startup sequence —
         the app runs in degraded mode rather than refusing to start.
      4. Initialise the SQLite/PostgreSQL database (watchlists, alerts).

    Shutdown sequence (after ``yield``):
      1. Close the database connection pool.
      2. Tear down all MCP stdio transports via the shared AsyncExitStack.
    """
    stack   = AsyncExitStack()
    # Six regional/analytical servers started in declaration order
    regions = ["americas", "europe", "asia_pacific", "mena", "analytics", "economics"]
    await stack.__aenter__()

    # Warn early so logs are visible before the server startup loop
    missing = [k for k in ("FINNHUB_API_KEY", "MARKETAUX_API_KEY", "ALPHA_VANTAGE_KEY")
               if not os.getenv(k)]
    if missing:
        log.warning("Missing API keys: %s — some features will be degraded", missing)

    for region in regions:
        try:
            # 30-second timeout: MCP servers spawn a Python subprocess + initialize()
            # handshake. On slow machines (Windows with antivirus) this can be tight.
            session = await asyncio.wait_for(_start_mcp_server(region, stack), timeout=30)
            _sessions[region]       = session
            _session_status[region] = "connected"
            log.info("[MCP] %s server started", region)
        except asyncio.TimeoutError:
            # Server process started but did not complete initialize() in 30s
            _session_status[region] = "timeout"
            log.error("[MCP] %s server timed out after 30s — skipping", region)
        except Exception as e:
            # Import error, missing dependency, or port conflict in the subprocess
            _session_status[region] = "error"
            log.error("[MCP] %s server failed: %s", region, e)

    from services.database import init_db
    await init_db()

    yield  # Application runs here — request handlers are live

    from services.database import close_db
    await close_db()
    # AsyncExitStack tears down all stdio transports in LIFO order
    await stack.__aexit__(None, None, None)


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="StockPilot AI Orchestrator",
    description="Multi-Region Stock Intelligence API — 6 MCP servers, AI analysis, technical indicators",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ──────────────────────────────────────────────────────────

from routes.system      import router as system_router
from routes.market      import router as market_router
from routes.analytics   import router as analytics_router
from routes.intelligence import router as intelligence_router
from routes.macro       import router as macro_router
from routes.ai          import router as ai_router
from routes.user_data   import router as user_data_router

app.include_router(system_router)
app.include_router(market_router)
app.include_router(analytics_router)
app.include_router(intelligence_router)
app.include_router(macro_router)
app.include_router(ai_router)
app.include_router(user_data_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "orchestrator:app",
        host=os.getenv("BACKEND_HOST", "0.0.0.0"),
        port=int(os.getenv("BACKEND_PORT", "8000")),
        log_level="info",
        reload=False,
    )
