"""
Cache Manager — no-op stub.

Redis has been removed. All caching is handled by the L1 in-memory cache
in helpers/cache_helpers.py (_mem_get / _mem_set with TTL).

On GCP: Firestore is used for watchlist/alerts persistence (not caching).
Locally: in-memory cache only; data is lost on process restart.

This stub keeps the import path intact so existing call-sites compile
without changes. All methods return safe no-op defaults.
"""


class CacheTier:
    REAL_TIME    = 60
    INTRADAY     = 300
    DAILY        = 3600
    FUNDAMENTALS = 86400
    HISTORICAL   = 604800


class IntelligentCacheManager:
    """No-op cache manager — Redis removed, L1 in-memory cache is the only tier."""

    _available = False

    async def get(self, key: str):
        return None

    async def set(self, key: str, value, tier=None):
        pass

    async def get_market_data(self, ticker: str, exchange: str, data_type: str):
        return None

    async def store_market_data(self, ticker: str, exchange: str, data_type: str, data) -> None:
        pass

    async def invalidate(self, pattern: str) -> None:
        pass

    def get_stats(self) -> dict:
        return {"available": False, "note": "Redis removed — using L1 in-memory cache only"}
