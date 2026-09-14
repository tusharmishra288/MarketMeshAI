"""
MarketMesh AI — MCP Client (stdio transport, session pool, dispatcher).

This module manages the lifecycle of all MCP server connections and provides
the single ``mcp_call()`` dispatcher used by every route handler. Each MCP
server runs as a child Python subprocess communicating over stdin/stdout using
the Model Context Protocol (MCP) stdio transport.

Session pool
------------
``_sessions`` is a dict keyed by region name (e.g. ``"americas"``) that maps
to the live ``ClientSession`` object. It is populated during the FastAPI
lifespan startup and remains alive for the entire process lifetime. Route
handlers must never create their own sessions — they always call
``mcp_call(region, tool, arguments)`` which looks up the pool.

Dispatcher pattern
------------------
``mcp_call()`` hides all MCP protocol details from callers:
  - Looks up the session, raising HTTP 503 if the server never connected.
  - Invokes ``session.call_tool()`` and extracts the JSON payload.
  - Propagates tool-level errors as HTTP 404 exceptions so routes can handle
    them uniformly.

Dependencies
------------
- mcp (pip: mcp):          MCP Python SDK — ``stdio_client`` and ``ClientSession``.
- FastAPI:                  ``HTTPException`` for uniform error propagation.
"""

import os
import sys
import json
import logging
import asyncio
from typing import Dict, List
from contextlib import AsyncExitStack

from fastapi import HTTPException
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

log = logging.getLogger(__name__)

SERVERS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "mcp_servers")

# Shared session state — populated during lifespan startup
_sessions:       Dict[str, ClientSession] = {}
_session_status: Dict[str, str]           = {}

# Consecutive failed watchdog pings per region. Reset to 0 on any success.
_watchdog_strikes: Dict[str, int] = {}

# A ping must fail this many cycles in a row before a region is called dead.
# MCP stdio servers process requests serially, so a ping issued while a long
# tool call is running queues behind it and times out even though the server is
# perfectly healthy. One strike is not evidence of death.
_WATCHDOG_STRIKES_BEFORE_DEAD = 3

# Per-ping timeout. Generous because the slow path is a busy server, not a
# dead one — a dead subprocess fails immediately rather than timing out.
_WATCHDOG_TIMEOUT_S = 30


async def _start_mcp_server(region: str, stack: AsyncExitStack) -> ClientSession:
    """
    Spawn the MCP server subprocess for *region* and return an initialised session.

    The subprocess is started with ``sys.executable`` (same Python interpreter as
    the backend) pointing at ``mcp_servers/<region>/server.py``. Both the stdio
    transport and the ClientSession are entered into *stack* so they are torn
    down automatically when the lifespan context exits.

    Args:
        region: One of ``"americas"``, ``"europe"``, ``"asia_pacific"``,
                ``"mena"``, ``"analytics"``, or ``"economics"``.
        stack:  Shared ``AsyncExitStack`` from the lifespan context.

    Returns:
        An initialised ``ClientSession`` ready to accept ``call_tool`` calls.

    Raises:
        FileNotFoundError: If the server script for *region* does not exist.
        Exception:         Propagates any error raised during ``session.initialize()``.
    """
    script = os.path.join(SERVERS_DIR, region, "server.py")
    params = StdioServerParameters(command=sys.executable, args=[script], env=dict(os.environ))
    read, write = await stack.enter_async_context(stdio_client(params))
    session: ClientSession = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session


async def mcp_call(region: str, tool: str, arguments: dict) -> dict:
    """
    Call a tool on the named MCP server and return the parsed JSON response.

    This is the single dispatch function used by all route handlers. It
    abstracts away MCP protocol details and converts tool-level errors into
    FastAPI ``HTTPException`` instances.

    Args:
        region:    Target MCP server key, e.g. ``"americas"``, ``"analytics"``.
        tool:      Name of the tool to invoke, e.g. ``"get_real_time_quote"``.
        arguments: Dict of tool input parameters as defined in each server's
                   ``inputSchema``.

    Returns:
        Parsed JSON dict returned by the MCP tool (the ``data`` field, not
        the raw MCP ``CallToolResult``).

    Raises:
        HTTPException 503: The MCP server for *region* is not in the session
            pool — it failed to start, timed out, or was never configured.
        HTTPException 502: The tool returned an empty ``content`` list, flagged
            the result as an error, or returned text that is not valid JSON.
        HTTPException 404: The tool returned a JSON payload containing an
            ``"error"`` key — e.g. ticker not found, no data available.
    """
    session = _sessions.get(region)
    if session is None:
        raise HTTPException(status_code=503, detail=f"MCP server '{region}' unavailable")
    result = await session.call_tool(tool, arguments)
    if not result.content:
        raise HTTPException(status_code=502, detail=f"Empty response from {region} MCP")
    # MCP tools always return a list of TextContent objects. The first element's
    # ``.text`` attribute contains the JSON string produced by the tool handler.
    raw = result.content[0].text

    # An exception escaping a tool handler is caught by the MCP SDK, which sets
    # isError and puts the plain-text message in content — not JSON. Without
    # this check json.loads() below turns every such failure into an opaque
    # JSONDecodeError, discarding the actual reason.
    if getattr(result, "isError", False):
        log.error("[MCP] %s.%s raised: %s", region, tool, raw)
        raise HTTPException(status_code=502,
                            detail=f"{region}.{tool} failed: {raw}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Malformed output that was not flagged as an error — e.g. a library
        # writing to stdout, which is the stdio transport itself.
        log.error("[MCP] %s.%s returned non-JSON output: %r", region, tool, raw[:500])
        raise HTTPException(status_code=502,
                            detail=f"{region}.{tool} returned malformed output")

    if "error" in data:
        # Tool-level errors (e.g. "No data for AAPL") become HTTP 404 so the
        # frontend can distinguish "server down" (503) from "not found" (404).
        raise HTTPException(status_code=404, detail=data["error"])
    return data


async def _ping_region(region: str, timeout_s: int) -> None:
    """
    Ping one MCP session and update its status and strike count.

    Failure is classified by exception type, because the two failure modes are
    not equally ambiguous:

    - ``TimeoutError`` — the ping was accepted but no reply arrived in time.
      MCP stdio servers are serial, so this is the signature of a server busy
      with a long tool call just as often as a hung one. Ambiguous, so it
      takes ``_WATCHDOG_STRIKES_BEFORE_DEAD`` in a row to count as death.
    - Any other exception — a transport-level error (closed pipe, broken
      resource, "Connection closed"). The subprocess is gone; a live server,
      however busy, queues the request rather than dropping the pipe. Not
      ambiguous, so the region is marked dead on the first occurrence.

    Args:
        region:    Region key to ping.
        timeout_s: Seconds to wait for ``list_tools()`` before counting a strike.
    """
    session = _sessions.get(region)
    if session is None:
        return
    try:
        await asyncio.wait_for(session.list_tools(), timeout=timeout_s)
        if _session_status.get(region) != "connected":
            log.info("[MCP watchdog] %s recovered → connected", region)
        _session_status[region]   = "connected"
        _watchdog_strikes[region] = 0
    except TimeoutError as exc:
        # Ambiguous — could be a busy server. Require repeated strikes.
        # repr(), not str() — TimeoutError stringifies to "", which is why the
        # original log line read "session dead: " with nothing after it.
        strikes = _watchdog_strikes.get(region, 0) + 1
        _watchdog_strikes[region] = strikes
        if strikes >= _WATCHDOG_STRIKES_BEFORE_DEAD:
            _session_status[region] = "timeout"
            log.warning("[MCP watchdog] %s unresponsive after %d consecutive "
                        "timed-out pings: %r", region, strikes, exc)
        else:
            log.info("[MCP watchdog] %s ping %d/%d timed out (server likely "
                     "busy): %r", region, strikes, _WATCHDOG_STRIKES_BEFORE_DEAD, exc)
    except Exception as exc:
        # Unambiguous — the pipe to the subprocess is broken. Fail fast.
        # "error" rather than "timeout" mirrors the lifespan startup handler,
        # which distinguishes the same two cases the same way.
        _watchdog_strikes[region] = _WATCHDOG_STRIKES_BEFORE_DEAD
        _session_status[region]   = "error"
        log.warning("[MCP watchdog] %s transport failed — subprocess gone: %r",
                    region, exc)


async def mcp_watchdog(regions: List[str], interval_s: int = 60) -> None:
    """
    Background asyncio task — pings every MCP session every *interval_s* seconds
    and updates ``_session_status`` to reflect real liveness.

    Why this is necessary
    ---------------------
    MCP servers are stdio subprocesses. If a subprocess is OOM-killed or crashes,
    the ``ClientSession`` object in ``_sessions`` becomes stale but the orchestrator
    process stays alive — ``_session_status`` would forever report ``"connected"``
    without this watchdog. The Docker health check reads ``_session_status`` via
    ``/health``, so a stale "connected" entry hides the failure from Docker.

    Avoiding false positives
    ------------------------
    MCP stdio servers handle one request at a time. A ping sent while a long
    tool call is in flight sits in the queue and times out, which previously
    marked a healthy server dead on a single strike — flipping ``/health`` to
    degraded and potentially triggering an unnecessary container restart.
    Three safeguards prevent that without slowing down real crash detection:

    - Regions are pinged concurrently via ``asyncio.gather``, so one slow
      server cannot delay every region queued behind it.
    - A *timed-out* ping is ambiguous, so it takes
      ``_WATCHDOG_STRIKES_BEFORE_DEAD`` consecutive failures to count as death.
    - A *transport error* is unambiguous — the subprocess is gone — so it is
      reported on the first cycle. See ``_ping_region``.

    Recovery path
    -------------
    1. Subprocess dies → detected on the next cycle (within *interval_s*) if
       the transport broke; within *interval_s* ×
       ``_WATCHDOG_STRIKES_BEFORE_DEAD`` if it merely stopped responding.
    2. ``_session_status[region]`` is set to ``"error"`` or ``"timeout"``.
    3. ``/health`` returns ``{"status": "degraded", ...}``.
    4. Docker health check (configured to exit 1 on degraded) marks container
       unhealthy after ``retries`` failures.
    5. VM cron watchdog runs ``docker compose restart orchestrator`` within 5 min.
    6. Container restarts → lifespan re-spawns all MCP subprocesses → recovered.

    Args:
        regions:    List of region keys to watch (same order as lifespan startup).
        interval_s: Seconds between full ping cycles. Default 60 s.
    """
    await asyncio.sleep(interval_s)          # let startup fully settle first
    while True:
        # gather, not a sequential for-loop: a single slow region previously
        # delayed every region after it by up to the full ping timeout.
        await asyncio.gather(
            *(_ping_region(region, _WATCHDOG_TIMEOUT_S) for region in regions),
            return_exceptions=True,
        )
        await asyncio.sleep(interval_s)
