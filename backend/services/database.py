"""
Database service — PostgreSQL via asyncpg, with in-memory fallback for local dev.
Manages watchlist and price alert persistence.
"""

import logging
import os
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import asyncpg
    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False

# In-memory fallback stores (used when Postgres is unavailable)
_watchlist_mem: List[Dict] = []
_alerts_mem:   List[Dict] = []
_pool = None   # asyncpg connection pool


async def init_db():
    """Create connection pool and ensure tables exist. Silently falls back to in-memory."""
    global _pool
    if not _PG_AVAILABLE:
        logger.warning("asyncpg not installed — watchlist stored in-memory (lost on restart)")
        return

    dsn = os.getenv("DATABASE_URL") or (
        f"postgresql://{os.getenv('POSTGRES_USER','stockuser')}:"
        f"{os.getenv('POSTGRES_PASSWORD','stockpass')}@"
        f"{os.getenv('POSTGRES_HOST','localhost')}:"
        f"{os.getenv('POSTGRES_PORT','5432')}/"
        f"{os.getenv('POSTGRES_DB','stockdb')}"
    )
    try:
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, command_timeout=10)
        async with _pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS watchlists (
                    id        SERIAL PRIMARY KEY,
                    ticker    VARCHAR(20) NOT NULL,
                    exchange  VARCHAR(20) NOT NULL,
                    added_at  TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(ticker, exchange)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS price_alerts (
                    id        SERIAL PRIMARY KEY,
                    ticker    VARCHAR(20) NOT NULL,
                    exchange  VARCHAR(20) NOT NULL,
                    threshold DECIMAL(18,4) NOT NULL,
                    direction VARCHAR(4) NOT NULL CHECK(direction IN ('up','down')),
                    triggered BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        logger.info("PostgreSQL connected — watchlist/alerts tables ready")
    except Exception as e:
        logger.warning("PostgreSQL unavailable (%s) — using in-memory storage", e)
        _pool = None


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


# ── Watchlist ─────────────────────────────────────────────────────────────────

async def add_watchlist(ticker: str, exchange: str) -> bool:
    ticker = ticker.upper()
    if _pool:
        try:
            async with _pool.acquire() as conn:
                result = await conn.execute(
                    "INSERT INTO watchlists(ticker,exchange) VALUES($1,$2) ON CONFLICT DO NOTHING",
                    ticker, exchange,
                )
                return result != "INSERT 0 0"
        except Exception as e:
            logger.error("add_watchlist db error: %s", e)
    if not any(w["ticker"] == ticker and w["exchange"] == exchange for w in _watchlist_mem):
        _watchlist_mem.append({
            "ticker": ticker, "exchange": exchange,
            "added_at": datetime.now().isoformat(),
        })
        return True
    return False


async def get_watchlist() -> List[Dict]:
    if _pool:
        try:
            async with _pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT ticker, exchange, added_at FROM watchlists ORDER BY added_at DESC"
                )
                return [{"ticker": r["ticker"], "exchange": r["exchange"],
                         "added_at": str(r["added_at"])} for r in rows]
        except Exception as e:
            logger.error("get_watchlist db error: %s", e)
    return list(_watchlist_mem)


async def remove_watchlist(ticker: str, exchange: str) -> bool:
    ticker = ticker.upper()
    if _pool:
        try:
            async with _pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM watchlists WHERE ticker=$1 AND exchange=$2", ticker, exchange
                )
                return result != "DELETE 0"
        except Exception as e:
            logger.error("remove_watchlist db error: %s", e)
    global _watchlist_mem
    before = len(_watchlist_mem)
    _watchlist_mem = [w for w in _watchlist_mem
                      if not (w["ticker"] == ticker and w["exchange"] == exchange)]
    return len(_watchlist_mem) < before


# ── Price Alerts ──────────────────────────────────────────────────────────────

async def add_alert(ticker: str, exchange: str, threshold: float, direction: str) -> bool:
    ticker = ticker.upper()
    direction = direction.lower()
    if _pool:
        try:
            async with _pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO price_alerts(ticker,exchange,threshold,direction) VALUES($1,$2,$3,$4)",
                    ticker, exchange, threshold, direction,
                )
            return True
        except Exception as e:
            logger.error("add_alert db error: %s", e)
    _alerts_mem.append({
        "ticker": ticker, "exchange": exchange,
        "threshold": threshold, "direction": direction,
        "triggered": False,
        "created_at": datetime.now().isoformat(),
    })
    return True


async def get_alerts(ticker: Optional[str] = None) -> List[Dict]:
    if _pool:
        try:
            async with _pool.acquire() as conn:
                if ticker:
                    rows = await conn.fetch(
                        "SELECT * FROM price_alerts WHERE ticker=$1 AND triggered=FALSE "
                        "ORDER BY created_at DESC",
                        ticker.upper(),
                    )
                else:
                    rows = await conn.fetch(
                        "SELECT * FROM price_alerts WHERE triggered=FALSE ORDER BY created_at DESC"
                    )
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error("get_alerts db error: %s", e)
    base = _alerts_mem if not ticker else [a for a in _alerts_mem
                                           if a["ticker"] == ticker.upper()]
    return [a for a in base if not a.get("triggered")]


async def delete_alert(alert_id: int) -> bool:
    if _pool:
        try:
            async with _pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM price_alerts WHERE id=$1", alert_id
                )
                return result != "DELETE 0"
        except Exception as e:
            logger.error("delete_alert db error: %s", e)
    return False
