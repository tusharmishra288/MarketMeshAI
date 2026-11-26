"""
MarketMesh AI — Orchestrator (FastAPI Entry Point).

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

from helpers.mcp_client import (
    _sessions, _session_status, mcp_watchdog,
    start_mcp_supervisors, stop_mcp_supervisors,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [orchestrator] %(message)s")
log = logging.getLogger(__name__)

# ── Lifespan: start MCP servers and database ──────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager — startup and shutdown logic.

    Startup sequence:
      1. Warn about missing API keys so operators know which features are degraded.
      2. Launch one supervisor task per MCP server. Each supervisor owns its own
         subprocess and AsyncExitStack, starts sequentially with a 120-second
         timeout, and respawns its server automatically if it later dies.
         Servers that timeout or raise are marked "timeout"/"error" in
         _session_status but do NOT abort the rest of the startup sequence —
         the app runs in degraded mode rather than refusing to start.
      3. Initialise the SQLite/PostgreSQL database (watchlists, alerts).

    Shutdown sequence (after ``yield``):
      1. Close the database connection pool.
      2. Signal every supervisor to stop; each tears down its own stdio
         transport inside its own task, which is the only place anyio permits
         that cancel scope to be exited.
    """
    # Six regional/analytical servers started in declaration order
    regions = ["americas", "europe", "asia_pacific", "mena", "analytics", "economics"]

    # Warn early so logs are visible before the server startup loop
    missing = [k for k in ("FINNHUB_API_KEY", "MARKETAUX_API_KEY", "ALPHA_VANTAGE_KEY")
               if not os.getenv(k)]
    if missing:
        log.warning("Missing API keys: %s — some features will be degraded", missing)

    # 120-second spawn timeout: MCP servers spawn a Python subprocess +
    # initialize() handshake. On a dev laptop each takes well under a second,
    # but on an e2-micro (shared burstable vCPU, 1 GB RAM) importing pandas /
    # numpy / yfinance takes 15-30 s each. At 30 s, asia_pacific and mena timed
    # out on every cold start, leaving /health permanently "degraded" and
    # failing the deploy. Supervisors start sequentially and hold a shared spawn
    # lock thereafter: six simultaneous numpy/pandas imports would peak past the
    # container's 700 MB limit.
    await start_mcp_supervisors(regions, startup_timeout_s=120)

    from services.database import init_db
    await init_db()

    # Start background watchdog — pings each MCP session every 60 s and updates
    # _session_status so /health reflects real liveness. When a subprocess dies
    # the watchdog now also wakes that region's supervisor, which respawns it in
    # place; a container restart is only the backstop if respawning keeps
    # failing.
    watchdog_task = asyncio.create_task(mcp_watchdog(regions, interval_s=60))
    log.info("[MCP watchdog] started (interval=60s, auto-respawn enabled)")

    yield  # Application runs here — request handlers are live

    watchdog_task.cancel()
    try:
        await watchdog_task
    except asyncio.CancelledError:
        pass

    from services.database import close_db
    await close_db()
    # Each supervisor closes its own stdio transport inside its own task
    await stop_mcp_supervisors()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="MarketMesh AI Orchestrator",
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
