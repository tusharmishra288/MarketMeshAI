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
from typing import Dict
from contextlib import AsyncExitStack

from fastapi import HTTPException
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

log = logging.getLogger(__name__)

SERVERS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "mcp_servers")

# Shared session state — populated during lifespan startup
_sessions:       Dict[str, ClientSession] = {}
_session_status: Dict[str, str]           = {}


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
        HTTPException 502: The tool returned an empty ``content`` list, which
            indicates a protocol-level failure in the MCP server subprocess.
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
    data = json.loads(result.content[0].text)
    if "error" in data:
        # Tool-level errors (e.g. "No data for AAPL") become HTTP 404 so the
        # frontend can distinguish "server down" (503) from "not found" (404).
        raise HTTPException(status_code=404, detail=data["error"])
    return data
