"""
Intelligent Cache Manager
Multi-tier caching — Redis when available, no-op fallback when not.
"""

import pickle
from datetime import datetime
from enum import Enum
from typing import Optional, Any

import redis as redis_lib

class CacheTier(Enum):
    REAL_TIME    = 60
    INTRADAY     = 300
    DAILY        = 3600
    FUNDAMENTALS = 86400
    HISTORICAL   = 604800
    STATIC       = 2592000

class IntelligentCacheManager:

    def __init__(self, redis_host: str = 'localhost', redis_port: int = 6379):
        try:
            self.redis_client = redis_lib.Redis(
                host=redis_host,
                port=redis_port,
                db=0,
                decode_responses=False,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            # Probe immediately — if this fails we know Redis is absent.
            self.redis_client.ping()
            self._available = True
        except Exception:
            self.redis_client = None
            self._available = False

    # ── internal helpers ──────────────────────────────────────────────────────

    def _get(self, key: str) -> Optional[Any]:
        if not self._available:
            return None
        try:
            raw = self.redis_client.get(key)
            return pickle.loads(raw) if raw else None
        except Exception:
            return None

    def _set(self, key: str, value: Any, ttl: int) -> None:
        if not self._available:
            return
        try:
            self.redis_client.setex(key, ttl, pickle.dumps(value))
        except Exception:
            pass

    # ── public async interface (called from FastAPI handlers) ─────────────────

    async def get(self, key: str) -> Optional[Any]:
        return self._get(key)

    async def set(self, key: str, value: Any, tier: CacheTier = CacheTier.REAL_TIME) -> None:
        self._set(key, value, tier.value)

    async def get_market_data(self, ticker: str, exchange: str, data_type: str) -> Optional[Any]:
        return self._get(f"{exchange}:{ticker}:{data_type}")

    async def store_market_data(self, ticker: str, exchange: str, data_type: str, data: Any) -> None:
        tier_map = {
            'real_time':   CacheTier.REAL_TIME,
            'intraday':    CacheTier.INTRADAY,
            'daily':       CacheTier.DAILY,
            'fundamentals':CacheTier.FUNDAMENTALS,
            'historical':  CacheTier.HISTORICAL,
        }
        tier = tier_map.get(data_type.lower(), CacheTier.REAL_TIME)
        self._set(f"{exchange}:{ticker}:{data_type}", data, tier.value)

    async def invalidate(self, pattern: str) -> None:
        if not self._available:
            return
        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                self.redis_client.delete(*keys)
        except Exception:
            pass

    def get_stats(self) -> dict:
        if not self._available:
            return {"available": False, "note": "Redis not running"}
        try:
            info = self.redis_client.info('stats')
            hits   = info.get('keyspace_hits', 0)
            misses = info.get('keyspace_misses', 0)
            return {
                "available": True,
                "total_keys": self.redis_client.dbsize(),
                "hits":       hits,
                "misses":     misses,
                "hit_rate":   hits / max(1, hits + misses),
            }
        except Exception:
            return {"available": False, "note": "Redis unreachable"}
