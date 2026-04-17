"""
StockPilot AI — Cache Helpers (2-tier caching strategy).

This module implements the L1 (in-process) layer of a 2-tier cache:

  L1 — In-memory dict (this module)
      ``_mem_cache`` is a plain Python dict keyed by a string cache key.  Each
      entry stores the cached payload alongside an ``expires`` datetime. Lookups
      are O(1) and require no I/O. Data survives only for the lifetime of the
      Python process (restarting the backend clears all L1 entries).

  L2 — Redis (services/cache_manager.py)
      The ``cache_manager`` service wraps an async Redis client.  Route handlers
      typically check L1 first (``_mem_get``), then Redis (``cache_manager.get_*``),
      then call the MCP server, and store results in both tiers.

Concurrency note
----------------
``_mem_cache`` is a plain dict. Python's GIL serialises dict reads/writes in
CPython, so no additional locking is needed for async coroutines running in a
single-threaded event loop. This would need revisiting if the backend is ever
moved to a multi-threaded executor model.

Dependencies
------------
- datetime: Standard library — TTL expiry via ``datetime`` and ``timedelta``.
"""

from typing import Dict
from datetime import datetime, timedelta

_mem_cache: Dict[str, dict] = {}


def _mem_get(key: str):
    """
    Retrieve a value from the L1 in-memory cache if it has not expired.

    TTL semantics: expiry is checked against ``datetime.now()`` at call time.
    If the entry exists but is stale it is eagerly deleted to free memory;
    subsequent writes for the same key start with a fresh TTL.

    Thread safety: safe for concurrent async coroutines under CPython's GIL.
    Not safe for use across OS threads without an explicit lock.

    Args:
        key: Cache key string (e.g. ``"quote:AAPL:NASDAQ"``).

    Returns:
        The cached data payload (any type) if the key exists and has not
        expired, or ``None`` if the key is missing or stale.
    """
    entry = _mem_cache.get(key)
    if entry and datetime.now() < entry["expires"]:
        return entry["data"]
    if entry:
        # Eagerly evict stale entry so the dict does not grow unbounded
        del _mem_cache[key]
    return None


def _mem_set(key: str, data, ttl_seconds: int):
    """
    Store a value in the L1 in-memory cache with a TTL.

    The entry expires exactly ``ttl_seconds`` seconds from the moment this
    function is called. Calling ``_mem_set`` on an already-existing key
    overwrites both the data and the expiry timestamp (acts as a cache refresh).

    Thread safety: same note as ``_mem_get`` — safe under asyncio/GIL, but
    not across OS threads without an explicit lock.

    Args:
        key:         Cache key string (must match the key used in ``_mem_get``).
        data:        Arbitrary value to cache (typically a dict or list).
        ttl_seconds: How long the entry remains valid. Common values used
                     across the codebase: 60 (real-time quotes), 300
                     (technicals), 3600 (fundamentals/indices), 86400 (factors,
                     AI descriptions), 604800 (company descriptions — 7 days).
    """
    _mem_cache[key] = {
        "data":    data,
        "expires": datetime.now() + timedelta(seconds=ttl_seconds),
    }
