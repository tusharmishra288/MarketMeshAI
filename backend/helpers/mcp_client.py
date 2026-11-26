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

# ── Supervisor state ──────────────────────────────────────────────────────────
# Each region runs under its own long-lived supervisor task that owns that
# subprocess's AsyncExitStack.
#
# This structure is not incidental. The MCP stdio transport is built on anyio
# task groups, and entering a cancel scope in one task while exiting it in
# another raises "Attempted to exit cancel scope in a different task than it
# was entered in". Previously every subprocess was entered into a single
# AsyncExitStack owned by the FastAPI lifespan task, which meant the watchdog
# — running in its own task — could not tear a dead server down even though it
# could detect one. One supervisor task per region, owning both the enter and
# the exit, is what makes automatic respawn safe.
_supervisors:    Dict[str, asyncio.Task]  = {}
_restart_events: Dict[str, asyncio.Event] = {}
_ready_events:   Dict[str, asyncio.Event] = {}
_shutdown = asyncio.Event()

# True only while a region's supervisor is actively spawning a replacement.
# ``mcp_call`` waits on this so a respawn shows up as a slow request rather
# than a failed one — but only then. A region sitting dead in backoff is False,
# so requests fail fast instead of every caller blocking for the full timeout.
_respawning: Dict[str, bool] = {}

# Serialises spawns. Six simultaneous pandas/numpy/yfinance imports peak past
# the container's 700 MB limit on an e2-micro, so only one server may start at
# a time — during initial startup and during any later respawn.
_spawn_lock = asyncio.Lock()

# Backoff between respawn attempts, indexed by consecutive failure count and
# held at the final value. A server that fails on every start (a missing native
# dependency, say) must not spin retrying forever.
_RESPAWN_BACKOFF_S = (5, 15, 60, 300)


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


def _request_restart(region: str) -> None:
    """
    Signal the supervisor for *region* to tear down and respawn its subprocess.

    Called by the watchdog when a region is judged dead. Deliberately does no
    teardown itself — only the owning supervisor task may close the stack (see
    the cancel-scope note at the top of this module). Safe to call repeatedly;
    a restart already pending is left alone.

    Args:
        region: Region key whose supervisor should restart it.
    """
    ev = _restart_events.get(region)
    if ev is None:
        # No supervisor — the process is shutting down, or the region was never
        # registered. Nothing to do.
        return
    if not ev.is_set():
        log.warning("[MCP] %s marked dead — requesting respawn", region)
        ev.set()


async def _wait_for_restart_or_shutdown(region: str) -> None:
    """
    Block until this region is asked to restart or the app is shutting down.

    Holding here is what keeps the region's AsyncExitStack open for the life of
    a healthy subprocess: returning from this call is the signal to tear down.

    Args:
        region: Region key to wait on.
    """
    restart  = asyncio.create_task(_restart_events[region].wait())
    shutdown = asyncio.create_task(_shutdown.wait())
    try:
        await asyncio.wait({restart, shutdown}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (restart, shutdown):
            if not task.done():
                task.cancel()


async def _supervise_region(region: str, startup_timeout_s: int) -> None:
    """
    Own one region's subprocess for the life of the app: spawn it, publish its
    session, hold it open, and respawn it whenever it dies.

    Every ``AsyncExitStack`` enter and exit happens inside this one task, which
    is what makes teardown of a dead transport safe (see the module-level note
    on anyio cancel scopes).

    Loop:
      1. Acquire ``_spawn_lock`` and start the subprocess, bounded by
         *startup_timeout_s*.
      2. On success publish the session into ``_sessions``, mark the region
         connected, and reset the failure counters.
      3. Block until the watchdog requests a restart or the app shuts down.
      4. Tear the stack down, suppressing teardown errors — if the subprocess
         is already gone, a broken pipe on close is expected, not a problem.
      5. Back off and loop.

    Args:
        region:            Region key to supervise.
        startup_timeout_s: Seconds allowed for spawn + ``initialize()``.
    """
    failures = 0

    while not _shutdown.is_set():
        _restart_events[region].clear()
        _respawning[region] = True     # callers may wait for this attempt
        stack = AsyncExitStack()
        started = False
        try:
            await stack.__aenter__()
            # One spawn at a time, process-wide — see _spawn_lock.
            async with _spawn_lock:
                session = await asyncio.wait_for(
                    _start_mcp_server(region, stack), timeout=startup_timeout_s)
            _sessions[region]         = session
            _session_status[region]   = "connected"
            _watchdog_strikes[region] = 0
            _respawning[region]       = False
            started  = True
            failures = 0
            log.info("[MCP] %s server started", region)
            _ready_events[region].set()

            # Hold the subprocess open. Returning here means "tear down now".
            await _wait_for_restart_or_shutdown(region)
            if not _shutdown.is_set():
                log.info("[MCP] %s tearing down dead session before respawn", region)

        except asyncio.TimeoutError:
            _session_status[region] = "timeout"
            log.error("[MCP] %s server timed out after %ds", region, startup_timeout_s)
        except asyncio.CancelledError:
            _shutdown.set()
            raise
        except Exception as exc:
            _session_status[region] = "error"
            log.error("[MCP] %s server failed: %s", region, exc)
        finally:
            # Drop the session first so mcp_call returns a clean 503 rather than
            # dispatching onto a transport that is being torn down.
            _sessions.pop(region, None)
            # Unblock startup even when the first attempt failed, so one bad
            # server cannot stall the whole boot sequence.
            _ready_events[region].set()
            try:
                await stack.aclose()
            except Exception as exc:
                # Expected when the subprocess is already gone: closing a broken
                # pipe raises. There is nothing left to clean up, so log at debug
                # and let the respawn proceed rather than killing the supervisor.
                log.debug("[MCP] %s teardown raised (subprocess already gone): %r",
                          region, exc)

        if _shutdown.is_set():
            break

        if started:
            # This server had been running fine and died once. Respawn straight
            # away and keep _respawning set, so in-flight callers wait out the
            # gap instead of seeing it. Backoff exists for servers that cannot
            # start at all, not for a one-off death.
            _respawning[region] = True
            log.info("[MCP] %s respawning immediately", region)
            continue

        failures += 1
        # Backoff is not "about to be available", so stop making callers wait.
        _respawning[region] = False
        delay = _RESPAWN_BACKOFF_S[min(failures - 1, len(_RESPAWN_BACKOFF_S) - 1)]
        log.info("[MCP] %s respawn attempt %d failed — retrying in %ds",
                 region, failures, delay)
        try:
            await asyncio.wait_for(_shutdown.wait(), timeout=delay)
            break                      # shutdown arrived during backoff
        except asyncio.TimeoutError:
            pass                       # backoff elapsed — try again

    log.info("[MCP] %s supervisor stopped", region)


async def start_mcp_supervisors(regions: List[str], startup_timeout_s: int = 120) -> None:
    """
    Launch one supervisor task per region and wait for each first attempt.

    Regions are brought up one at a time: the next supervisor is not started
    until the previous has reported ready (or failed), which preserves the
    sequential memory profile the e2-micro needs. A region that never reports
    is left to its supervisor and startup continues, so one bad server degrades
    the app rather than blocking it.

    Args:
        regions:           Region keys to supervise, in startup order.
        startup_timeout_s: Seconds allowed per spawn.
    """
    _shutdown.clear()
    for region in regions:
        _restart_events[region] = asyncio.Event()
        _ready_events[region]   = asyncio.Event()
        _supervisors[region]    = asyncio.create_task(
            _supervise_region(region, startup_timeout_s), name=f"mcp-supervisor-{region}")
        try:
            # +30 s over the spawn timeout so this waiter never fires before the
            # supervisor's own timeout has had a chance to classify the failure.
            await asyncio.wait_for(_ready_events[region].wait(),
                                   timeout=startup_timeout_s + 30)
        except asyncio.TimeoutError:
            log.error("[MCP] %s did not report ready — continuing startup", region)


async def stop_mcp_supervisors() -> None:
    """
    Signal every supervisor to shut down and wait for them to tear down cleanly.

    Each supervisor closes its own stack in its own task, which is the only
    place that teardown is safe. Supervisors that do not exit promptly are
    cancelled — the process is going away regardless.
    """
    _shutdown.set()
    for region in list(_supervisors):
        ev = _restart_events.get(region)
        if ev is not None:
            ev.set()                   # wake a supervisor parked on the hold
    for region, task in list(_supervisors.items()):
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=30)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            log.warning("[MCP] %s supervisor did not stop in time — cancelling", region)
            task.cancel()
        except Exception as exc:
            log.warning("[MCP] %s supervisor exited with error: %r", region, exc)
    _supervisors.clear()
    _restart_events.clear()
    _ready_events.clear()


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
    session = await _acquire_session(region)

    try:
        result = await session.call_tool(tool, arguments)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # A transport error on a live request is the earliest possible evidence
        # that the subprocess has died — up to a full watchdog cycle sooner than
        # the next ping would notice. Trigger the respawn now so the following
        # request has a working server, instead of waiting out the cycle.
        _session_status[region] = "error"
        _request_restart(region)
        log.warning("[MCP] %s.%s transport error — respawn requested: %r",
                    region, tool, exc)
        raise HTTPException(status_code=503,
                            detail=f"MCP server '{region}' is restarting — retry shortly")

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


async def _acquire_session(region: str, max_wait_s: float = 45.0) -> ClientSession:
    """
    Return the live session for *region*, briefly waiting out a respawn.

    A healthy region returns immediately. If the supervisor is mid-spawn, this
    waits for it rather than failing — a restart then costs the caller latency
    instead of an error, which is the difference between "the app healed itself"
    and "the page broke". A region that is dead but *not* currently spawning
    (sitting in backoff) raises straight away, so a persistently broken server
    cannot pile up blocked requests.

    Args:
        region:     Region key to resolve.
        max_wait_s: Ceiling on the wait. Slightly over the e2-micro's observed
                    15-30 s spawn so a slow respawn still succeeds.

    Returns:
        A live ``ClientSession``.

    Raises:
        HTTPException 503: No session, and none is on its way.
    """
    session = _sessions.get(region)
    if session is not None:
        return session

    loop     = asyncio.get_running_loop()
    deadline = loop.time() + max_wait_s
    waited   = False
    while _respawning.get(region) and loop.time() < deadline:
        waited = True
        await asyncio.sleep(0.5)
        session = _sessions.get(region)
        if session is not None:
            log.info("[MCP] %s became available mid-request after respawn", region)
            return session

    if waited:
        raise HTTPException(status_code=503,
                            detail=f"MCP server '{region}' is restarting — retry shortly")
    raise HTTPException(status_code=503, detail=f"MCP server '{region}' unavailable")


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
            _request_restart(region)
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
        _request_restart(region)


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
    3. ``_request_restart()`` wakes that region's supervisor, which tears the
       dead transport down and spawns a replacement subprocess. A healthy
       respawn flips the region back to ``"connected"`` on its own, usually
       within seconds, so the app self-heals without an external restart.
    4. Only if the respawn keeps failing does the region stay non-connected.
       ``/health`` then reports ``degraded``, the Docker health check exits 1,
       and the VM cron restarts the container — the backstop, no longer the
       primary recovery mechanism.

    Restarting the whole container was previously the *only* way a dead
    subprocess came back, which is why regions showed as error or offline at
    arbitrary times long after startup.

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
