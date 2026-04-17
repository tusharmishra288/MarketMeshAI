"""
MarketMesh AI — AI Routes (company summary and description endpoints).

This router exposes LLM-powered analysis endpoints. Both endpoints use the
dual-LLM strategy (Groq primary, Gemini fallback) implemented in
``helpers/ai_helpers.py``. Data is gathered from MCP servers before being
passed to the LLM to ensure the model works with current market data.

Endpoints
---------
- GET /api/ai/company-summary/{ticker}:     Full AI market analysis — combines
  fundamentals, live quote, technicals, and recent news into a structured JSON
  report (summary, risks, sentiment_context, technical_view). Cached 24 h.
- GET /api/ai/company-description/{ticker}: Concise 2-3 sentence company
  description condensed from the raw ``longBusinessSummary``. Cached 7 days
  because company descriptions rarely change.

Dependencies
------------
- mcp_client:    Fetches fundamentals, quote, and technicals concurrently.
- enrichment:    Alpha Vantage enrichment for PE, ROE, margin before LLM call.
- ai_helpers:    Dual-LLM dispatch for both analysis types.
- cache_helpers: L1 cache — 86400 s for summary, 604800 s for description.
"""

import asyncio
import logging

from fastapi import APIRouter

from helpers.mcp_client    import mcp_call
from helpers.cache_helpers import _mem_get, _mem_set
from helpers.market_helpers import QUOTE_TOOL, FUNDAMENTALS_TOOL, _get_region
from helpers.enrichment    import _enrich_with_alpha_vantage
from helpers.ai_helpers    import _ai_company_summary, _ai_describe_company

log    = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/ai/company-summary/{ticker}")
async def ai_company_summary(ticker: str, exchange: str = "NASDAQ", refresh: bool = False):
    """
    Generate a structured AI market-analysis report for a stock.

    Data-gathering phase (parallel async tasks):
      - Fundamentals via the regional MCP server.
      - Live quote via the regional MCP server.
      - Technical indicators via the analytics MCP server.
    Any of these that fails is replaced with an empty dict so the LLM still
    produces a partial analysis rather than refusing to respond.

    Post-gather:
      - Enriches fundamentals with Alpha Vantage OVERVIEW data.
      - Fetches the 5 most recent news articles from ``get_news`` (same route).

    Cache TTL: 86400 seconds (L1 — 24 h). Set ``refresh=true`` to bypass cache
    and regenerate (triggers an LLM call, ~1-3 s latency).

    Args:
        ticker:   Stock ticker symbol (case-insensitive).
        exchange: Exchange code used to route MCP calls.
        refresh:  When ``True``, skips L1 cache and regenerates the analysis.

    Returns:
        JSON dict with keys: ``summary``, ``risks`` (list[str]),
        ``sentiment_context``, ``technical_view``, ``model_used``,
        ``generated_at``, ``ticker``, ``exchange``.

    Raises:
        No HTTP exceptions — MCP failures are caught; LLM failures return a
        static placeholder.
    """
    ticker = ticker.upper()
    key    = f"ai_summary:{ticker}:{exchange}"
    if not refresh:
        if cached := _mem_get(key):
            return cached

    region = _get_region(exchange)

    fund_t = asyncio.create_task(mcp_call(region, FUNDAMENTALS_TOOL[region],
                                           {"ticker": ticker, "exchange": exchange}))
    quot_t = asyncio.create_task(mcp_call(region, QUOTE_TOOL[region],
                                           {"ticker": ticker, "exchange": exchange}))
    tech_t = asyncio.create_task(mcp_call("analytics", "compute_technical_indicators",
                                           {"ticker": ticker, "exchange": exchange}))

    fundamentals, quote, technicals = await asyncio.gather(
        fund_t, quot_t, tech_t, return_exceptions=True
    )
    fundamentals = fundamentals if isinstance(fundamentals, dict) else {}
    quote        = quote        if isinstance(quote,        dict) else {}
    technicals   = technicals   if isinstance(technicals,   dict) else {}

    fundamentals = await _enrich_with_alpha_vantage(ticker, fundamentals)

    news_articles = []
    try:
        from routes.market import get_news
        news_data     = await get_news(ticker, limit=5)
        news_articles = news_data.get("articles", [])
    except Exception:
        pass

    result = await _ai_company_summary(ticker, fundamentals, quote, news_articles, technicals)
    result["ticker"]   = ticker
    result["exchange"] = exchange
    _mem_set(key, result, ttl_seconds=86400)
    return result


@router.get("/api/ai/company-description/{ticker}")
async def ai_company_description(ticker: str, exchange: str = "NASDAQ"):
    """
    Return a concise LLM-generated company description (2-3 sentences).

    Fetches the raw ``longBusinessSummary`` from the regional MCP server (with
    AV enrichment as backup), then passes it to ``_ai_describe_company()`` which
    distils it into 2-3 clean, factual sentences using Groq or Gemini.

    Cache TTL: 604800 seconds (L1 — 7 days). Company descriptions change very
    rarely so a long cache avoids unnecessary LLM calls on every page load.

    Args:
        ticker:   Stock ticker symbol (case-insensitive).
        exchange: Exchange code used to route the fundamentals MCP call.

    Returns:
        JSON dict with keys: ``short_description`` (str), ``source``
        (``"groq"``/``"gemini"``/``"fallback"``/``"none"``), ``ticker``,
        ``exchange``.

    Raises:
        No HTTP exceptions — MCP failures are caught; LLM failures fall back
        to a regex-split of the raw description.
    """
    ticker = ticker.upper()
    key    = f"ai_desc:{ticker}:{exchange}"
    if cached := _mem_get(key):
        return cached

    region = _get_region(exchange)
    try:
        fundamentals = await mcp_call(region, FUNDAMENTALS_TOOL[region],
                                      {"ticker": ticker, "exchange": exchange})
        fundamentals = await _enrich_with_alpha_vantage(ticker, fundamentals)
    except Exception:
        fundamentals = {}

    raw_desc     = fundamentals.get("description", "")
    company_name = fundamentals.get("company_name", ticker)

    result         = await _ai_describe_company(company_name, raw_desc)
    result["ticker"]   = ticker
    result["exchange"] = exchange
    _mem_set(key, result, ttl_seconds=86400 * 7)
    return result
