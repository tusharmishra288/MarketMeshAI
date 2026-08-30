"""
MarketMesh AI — Economics MCP Server (FRED Macro Data).

This MCP server provides macroeconomic context by proxying data from the
Federal Reserve Economic Data (FRED) REST API. It runs as a standalone
subprocess communicating over stdio, managed by the backend orchestrator's
lifespan context.

All data is sourced from FRED (St. Louis Fed) which provides free access to
over 800,000 economic time series. The free tier allows 120 API calls per
minute. No API key is needed for very light usage, but ``FRED_API_KEY`` should
be set for production deployments.

FRED series used
----------------
- DGS3MO / DGS2 / DGS5 / DGS10 / DGS30: US Treasury yield curve tenors.
- CPIAUCSL:         Consumer Price Index (urban, all items).
- PCEPI:            PCE Price Index (the Fed's preferred inflation gauge).
- PPIFIS:           Producer Price Index (final demand).
- FEDFUNDS:         Effective Federal Funds Rate (monthly).
- A191RL1Q225SBEA:  Real GDP growth rate (QoQ annualised, quarterly).
- UNRATE:           US unemployment rate (monthly).
- UMCSENT:          University of Michigan Consumer Sentiment index (monthly).
- NAPM:             REMOVED. FRED deleted all 22 Institute for Supply
                    Management series on 2016-06-24 at ISM's request, so this
                    ID returns HTTP 400. ISM licenses PMI commercially and
                    there is no free FRED equivalent. Replaced by INDPRO.
- INDPRO:           Industrial Production Index (monthly, 2017=100). Free
                    Fed-published proxy for manufacturing activity. NOTE: this
                    is an index level, NOT a 0-100 diffusion index — the "above
                    50 = expansion" reading that applies to PMI does not apply
                    here. Interpret via the year-over-year change instead.

Tools exposed
-------------
- get_yield_curve:      Current and recent Treasury yields; 10Y-2Y spread;
                        inversion signal.
- get_inflation_data:   CPI, PCE, and PPI series with year-over-year % change.
- get_fed_rate:         Federal funds rate history.
- get_gdp_growth:       Real GDP QoQ growth rate with average.
- get_macro_indicators: Latest snapshot of unemployment, consumer sentiment,
                        and industrial production.

Dependencies
------------
- httpx:  Async HTTP client for FRED REST API calls.
- mcp:    MCP Python SDK.
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List

from mcp.server import Server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [economics] %(message)s")
log = logging.getLogger(__name__)

server = Server("economics")

# FRED series IDs
SERIES = {
    # Yield curve
    "DGS3MO":  "3-Month Treasury",
    "DGS2":    "2-Year Treasury",
    "DGS5":    "5-Year Treasury",
    "DGS10":   "10-Year Treasury",
    "DGS30":   "30-Year Treasury",
    # Inflation
    "CPIAUCSL":  "CPI (Urban)",
    "PCEPI":     "PCE Price Index",
    "PPIFIS":    "PPI",
    # Fed rate
    "FEDFUNDS":  "Fed Funds Rate",
    # GDP
    "A191RL1Q225SBEA": "Real GDP Growth (QoQ)",
    # Labor & Sentiment
    "UNRATE":    "Unemployment Rate",
    "UMCSENT":   "Consumer Sentiment (UMich)",
    "INDPRO":    "Industrial Production Index",
}


async def _fred_series(series_id: str, limit: int = 12) -> list:
    """
    Fetch the N most recent observations for a FRED series via the REST API.

    Uses ``sort_order=desc`` so FRED returns the newest observations first,
    then reverses the list to chronological order for consistent frontend
    display. Observations with non-numeric values (FRED uses ``"."`` for
    missing/unreported data points) are silently skipped.

    Args:
        series_id: FRED series identifier (e.g. ``"DGS10"`` for 10-year yield,
                   ``"CPIAUCSL"`` for CPI). See the ``SERIES`` dict at module
                   level for all series used by this server.
        limit:     Number of most recent observations to fetch (default 12).

    Returns:
        List of dicts ``[{"date": "YYYY-MM-DD", "value": float}, ...]``
        in chronological order (oldest first). Returns an empty list when
        ``FRED_API_KEY`` is not configured or on any network/parse error.
    """
    import httpx
    fred_key = os.getenv("FRED_API_KEY", "")
    if not fred_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={
                    "series_id":  series_id,
                    "api_key":    fred_key,
                    "file_type":  "json",
                    "sort_order": "desc",
                    "limit":      limit,
                    # No observation_start: let FRED return the N most recent real observations
                },
            )
        if r.status_code != 200:
            return []
        obs = r.json().get("observations", [])
        result = []
        for o in obs:
            try:
                result.append({"date": o["date"], "value": float(o["value"])})
            except (ValueError, KeyError):
                pass
        return list(reversed(result))  # chronological order
    except Exception as e:
        log.warning("FRED fetch %s: %s", series_id, e)
        return []


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_yield_curve",
            description="Get US Treasury yield curve (3M, 2Y, 5Y, 10Y, 30Y). Returns JSON with current and historical values.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_inflation_data",
            description="Get CPI, PCE, and PPI inflation trends. Returns JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "periods": {"type": "integer", "default": 24, "description": "Number of months"}
                },
            },
        ),
        Tool(
            name="get_fed_rate",
            description="Get Federal funds rate history. Returns JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "periods": {"type": "integer", "default": 24}
                },
            },
        ),
        Tool(
            name="get_gdp_growth",
            description="Get real GDP growth rate by quarter. Returns JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "periods": {"type": "integer", "default": 12}
                },
            },
        ),
        Tool(
            name="get_macro_indicators",
            description="Get key macro indicators: unemployment, consumer sentiment, PMI. Returns JSON snapshot.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """
    MCP tool dispatcher — routes incoming tool calls to the correct handler.

    Args:
        name:      Tool name from the MCP call request.
        arguments: Dict of input parameters forwarded verbatim to the handler.

    Returns:
        List with a single TextContent containing the JSON response, or an
        error JSON if the tool name is not recognised.
    """
    handlers = {
        "get_yield_curve":      get_yield_curve,
        "get_inflation_data":   get_inflation_data,
        "get_fed_rate":         get_fed_rate,
        "get_gdp_growth":       get_gdp_growth,
        "get_macro_indicators": get_macro_indicators,
    }
    handler = handlers.get(name)
    if not handler:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
    return await handler(**arguments)


async def get_yield_curve(**kwargs) -> List[TextContent]:
    """
    Fetch the current US Treasury yield curve and compute the 10Y-2Y spread.

    Retrieves the 2 most recent observations for each of the 5 standard tenors
    (3M, 2Y, 5Y, 10Y, 30Y) from FRED. The 10Y-2Y spread is the most widely
    watched recession signal — a negative spread (inversion) has historically
    preceded US recessions by 6-18 months.

    Returns:
        List with a single TextContent containing: ``current`` (dict of latest
        yield per tenor), ``history`` (2 observations per tenor), ``spread_10y_2y``
        (float or None), ``inverted`` (bool), ``signal`` (str), ``source``,
        ``fetched_at``.
    """
    try:
        tenors = {
            "3M":  "DGS3MO",
            "2Y":  "DGS2",
            "5Y":  "DGS5",
            "10Y": "DGS10",
            "30Y": "DGS30",
        }
        current = {}
        history = {}
        for label, sid in tenors.items():
            obs = await _fred_series(sid, limit=2)
            current[label] = obs[-1]["value"] if obs else None
            history[label] = obs

        # Spread signals
        spread_10_2 = None
        if current.get("10Y") and current.get("2Y"):
            spread_10_2 = round(current["10Y"] - current["2Y"], 3)

        inverted = spread_10_2 is not None and spread_10_2 < 0

        result = {
            "current":       current,
            "history":       history,
            "spread_10y_2y": spread_10_2,
            "inverted":      inverted,
            "signal":        "Inverted (recession signal)" if inverted else "Normal",
            "source":        "FRED",
            "fetched_at":    datetime.now().isoformat(),
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def get_inflation_data(periods: int = 24, **kwargs) -> List[TextContent]:
    """
    Fetch CPI, PCE, and PPI inflation series with year-over-year percentage change.

    Fetches ``periods`` monthly observations for each of the three series.
    Year-over-year (YoY) percentage change is computed by comparing the latest
    observation to the observation 13 indices earlier in the series (12 months
    prior in the FRED data, assuming monthly frequency). Falls back to None if
    fewer than 13 observations are available.

    Args:
        periods: Number of monthly observations to fetch (default 24 — 2 years).

    Returns:
        List with a single TextContent containing: ``cpi``, ``pce``, ``ppi``
        (each a dict with ``series`` list, ``yoy_pct`` float, ``label`` str),
        ``source``, ``fetched_at``.
    """
    try:
        cpi  = await _fred_series("CPIAUCSL", limit=periods)
        pce  = await _fred_series("PCEPI",    limit=periods)
        ppi  = await _fred_series("PPIFIS",   limit=periods)

        def yoy(series):
            if len(series) >= 13:
                curr = series[-1]["value"]
                prev = series[-13]["value"]
                return round((curr - prev) / prev * 100, 2) if prev else None
            return None

        result = {
            "cpi":        {"series": cpi,  "yoy_pct": yoy(cpi),  "label": "CPI (Urban)"},
            "pce":        {"series": pce,  "yoy_pct": yoy(pce),  "label": "PCE Price Index"},
            "ppi":        {"series": ppi,  "yoy_pct": yoy(ppi),  "label": "PPI"},
            "source":     "FRED",
            "fetched_at": datetime.now().isoformat(),
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def get_fed_rate(periods: int = 24, **kwargs) -> List[TextContent]:
    """
    Fetch the Federal funds rate history from FRED (FEDFUNDS series).

    The FEDFUNDS series is monthly. ``periods`` observations are returned in
    chronological order. The ``current_rate`` field contains the most recent
    observation.

    Args:
        periods: Number of monthly observations to return (default 24 — 2 years).

    Returns:
        List with a single TextContent containing: ``current_rate`` (float or
        None), ``history`` (list of ``{date, value}`` dicts), ``source``,
        ``fetched_at``.
    """
    try:
        obs = await _fred_series("FEDFUNDS", limit=periods)
        current = obs[-1]["value"] if obs else None
        result = {
            "current_rate": current,
            "history":      obs,
            "source":       "FRED",
            "fetched_at":   datetime.now().isoformat(),
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def get_gdp_growth(periods: int = 12, **kwargs) -> List[TextContent]:
    """
    Fetch real GDP growth rate (QoQ annualised) from FRED.

    Uses the FRED series A191RL1Q225SBEA (Real Gross Domestic Product, percent
    change from preceding period, seasonally adjusted annual rate). Quarterly
    frequency — ``periods`` observations correspond to ``periods`` quarters.
    Also computes the simple arithmetic mean of all fetched observations as
    ``average_pct`` for trend context.

    Args:
        periods: Number of quarterly observations to return (default 12 — 3 years).

    Returns:
        List with a single TextContent containing: ``current_qoq_pct`` (float
        or None), ``average_pct`` (float or None), ``history`` (list of
        ``{date, value}`` dicts), ``source``, ``fetched_at``.
    """
    try:
        obs = await _fred_series("A191RL1Q225SBEA", limit=periods)
        current = obs[-1]["value"] if obs else None
        avg = round(sum(o["value"] for o in obs) / len(obs), 2) if obs else None
        result = {
            "current_qoq_pct": current,
            "average_pct":     avg,
            "history":         obs,
            "source":          "FRED",
            "fetched_at":      datetime.now().isoformat(),
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def get_macro_indicators(**kwargs) -> List[TextContent]:
    """
    Fetch a snapshot of key US macro leading/coincident indicators from FRED.

    Fetches unemployment rate (UNRATE, 24 months to avoid gaps with ``"."`
    values), University of Michigan Consumer Sentiment (UMCSENT, 12 months),
    and Industrial Production (INDPRO, 24 months so a year-over-year change
    can be computed).

    Returns:
        List with a single TextContent containing: ``unemployment`` (dict with
        ``date`` and ``value``), ``consumer_sentiment`` (dict),
        ``industrial_production`` (dict with ``date``, ``value``, and
        ``yoy_pct``), ``source``, ``fetched_at``.
    """
    async def safe_fred(series_id: str, limit: int = 2) -> list:
        try:
            return await _fred_series(series_id, limit)
        except Exception:
            return []

    unrate = await safe_fred("UNRATE",  24)   # 24-month window avoids "." gaps
    umcsi  = await safe_fred("UMCSENT", 12)
    indpro = await safe_fred("INDPRO",  24)   # 24 months → enough for YoY

    def latest(obs):
        return obs[-1] if obs else {"date": None, "value": None}

    # Year-over-year % change: compare the newest observation against the one
    # 12 months earlier. Guards against short series and division by zero.
    def with_yoy(obs):
        current = latest(obs)
        yoy = None
        if len(obs) >= 13 and obs[-13]["value"]:
            prior = obs[-13]["value"]
            yoy = round((obs[-1]["value"] - prior) / prior * 100, 2)
        return {**current, "yoy_pct": yoy}

    result = {
        "unemployment":          latest(unrate),
        "consumer_sentiment":    latest(umcsi),
        "industrial_production": with_yoy(indpro),
        "source":                "FRED",
        "fetched_at":            datetime.now().isoformat(),
    }
    return [TextContent(type="text", text=json.dumps(result))]


if __name__ == "__main__":
    from mcp.server.stdio import stdio_server

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(main())
