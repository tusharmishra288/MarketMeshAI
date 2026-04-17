"""
StockPilot AI — System Routes (health, root, MCP tool listing, cache stats).

This router exposes operational endpoints used by the frontend status panel,
monitoring systems, and developers. No market data is fetched here — all
information is sourced from in-process state (MCP session dict, cache stats,
rate-limiter status).

Endpoints
---------
- GET /:                    Root endpoint — returns app version and MCP session
                            status. Used by the frontend to confirm the API is
                            reachable.
- GET /health:              Full health check — reports overall status
                            (``"healthy"`` vs ``"degraded"``), per-server MCP
                            connection status, Redis cache stats, and API
                            rate-limiter status.
- GET /api/validation/stats: Cache and data-quality statistics (cache hit rate,
                              key count). Intended for the admin dashboard.
- GET /mcp/tools/{region}:  List all tools registered on a specific MCP server.
                             Useful for debugging and verifying server health.

Dependencies
------------
- helpers.mcp_client:    ``_sessions`` and ``_session_status`` dicts.
- helpers.cache_helpers: ``_mem_cache`` dict (for key-count stat).
- helpers.services:      ``cache_manager`` (Redis stats) and ``rate_limiter``.
"""

from fastapi import APIRouter, HTTPException

from helpers.mcp_client   import _sessions, _session_status
from helpers.cache_helpers import _mem_cache
from helpers.services      import cache_manager, rate_limiter

router = APIRouter()


@router.get("/")
async def root():
    """
    Root endpoint — confirms the API is reachable and shows MCP server status.

    Returns:
        JSON dict with keys: ``message``, ``version``, ``documentation`` (URL
        to the auto-generated OpenAPI docs), ``mcp_sessions`` (dict mapping
        each region to its connection status string).
    """
    return {
        "message":     "StockPilot AI Multi-Region MCP Orchestrator v3",
        "version":     "3.0.0",
        "documentation": "/docs",
        "mcp_sessions": _session_status,
    }


@router.get("/health")
async def health_check():
    """
    Full health check — aggregates status of all subsystems.

    Overall status is ``"healthy"`` only when all six MCP servers are
    ``"connected"``; any other status (``"timeout"``, ``"error"``) results
    in ``"degraded"``.

    Returns:
        JSON dict with keys:
          - ``status``:      ``"healthy"`` or ``"degraded"``.
          - ``timestamp``:   ISO 8601 datetime of the check.
          - ``mcp_servers``: Per-region connection status dict.
          - ``cache_stats``: Redis hit rate, total key count, L1 key count.
          - ``rate_limits``: Current throttle state for each external API
                             (Marketaux, Alpha Vantage, Finnhub, etc.).
    """
    overall    = "healthy" if all(v == "connected" for v in _session_status.values()) else "degraded"
    stats      = cache_manager.get_stats()
    cache_info = {
        "hit_rate":      stats.get("hit_rate", 0),
        "total_keys":    stats.get("total_keys", 0),
        "mem_cache_keys": len(_mem_cache),
    }
    return {
        "status":      overall,
        "timestamp":   __import__("datetime").datetime.now().isoformat(),
        "mcp_servers": _session_status,
        "cache_stats": cache_info,
        "rate_limits": rate_limiter.get_all_status(),
    }


@router.get("/api/validation/stats")
async def validation_stats():
    """
    Return cache and data-quality statistics for the admin/monitoring dashboard.

    ``average_quality_score`` and ``sources_agreement_rate`` are placeholder
    fields reserved for future cross-source validation logic (currently ``None``).

    Returns:
        JSON dict with keys: ``average_quality_score``, ``sources_agreement_rate``,
        ``cache_hit_rate`` (float 0–1), ``total_keys_cached`` (int),
        ``mem_cache_keys`` (int — current L1 in-memory key count).
    """
    stats = cache_manager.get_stats()
    return {
        "average_quality_score":   None,
        "sources_agreement_rate":  None,
        "cache_hit_rate":          stats.get("hit_rate", 0),
        "total_keys_cached":       stats.get("total_keys", 0),
        "mem_cache_keys":          len(_mem_cache),
    }


@router.get("/mcp/tools/{region}")
async def list_mcp_tools(region: str):
    """
    List all tools registered on a specific MCP server.

    Calls ``session.list_tools()`` on the live MCP session for the specified
    region, returning a simplified list of tool names and descriptions.
    Useful for verifying that an MCP server started correctly and registered
    its expected tool set.

    Args:
        region: One of ``"americas"``, ``"europe"``, ``"asia_pacific"``,
                ``"mena"``, ``"analytics"``, ``"economics"``.

    Returns:
        JSON dict with keys: ``region`` (str) and ``tools`` (list of dicts
        with ``name`` and ``description`` fields).

    Raises:
        HTTPException 404: No active session exists for the specified region
            (server failed to start or region name is invalid).
    """
    if region not in _sessions:
        raise HTTPException(status_code=404, detail=f"No session for '{region}'")
    tools = await _sessions[region].list_tools()
    return {"region": region, "tools": [{"name": t.name, "description": t.description}
                                         for t in tools.tools]}
