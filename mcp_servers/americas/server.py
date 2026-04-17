"""
StockPilot AI — Americas MCP Server.

This MCP server handles all market-data requests for North and South American
exchanges. It runs as a standalone subprocess communicating over stdio and is
managed by the backend orchestrator's lifespan context.

Primary data source:  Finnhub REST API (US exchanges — real-time-ish quotes,
  company news). Falls back to yfinance for quotes when Finnhub returns no data
  or for non-US Americas exchanges (TSX, B3, BMV).
Fallback data source: yfinance (all fundamental data, historical data, and all
  non-US Americas quotes).

Supported exchanges
-------------------
- NASDAQ, NYSE, AMEX (US equities — Finnhub primary for quotes)
- TSX   (Toronto Stock Exchange, Canada)
- B3    (São Paulo / Brazil)
- BMV   (Mexico City Stock Exchange)

Tools exposed
-------------
- get_real_time_quote:       15-min delayed quote (Finnhub → yfinance fallback).
- get_company_fundamentals:  Full fundamental data from yfinance.info.
- get_historical_data:       OHLCV summary (data_points, latest_close, date_range).
- batch_get_quotes:          Bulk price fetch for a list of tickers via yfinance.
- search_companies:          Single-ticker yfinance lookup (limited search capability).
- get_market_news:           Recent news articles from Finnhub (7-day window).

Dependencies
------------
- finnhub-python: Official Finnhub Python client (quote, company_news).
- yfinance:       OHLCV history, company info, and fallback quotes.
- mcp:            MCP Python SDK (Server, Tool, TextContent).
"""

import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import yfinance as yf
import finnhub

from mcp.server import Server
from mcp.types import Tool, TextContent

server = Server("americas-markets")
finnhub_client = finnhub.Client(api_key=os.getenv('FINNHUB_API_KEY', ''))

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_real_time_quote",
            description="Get 15-min delayed quote for US/Americas stocks. Returns JSON with price, change, volume.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Stock ticker symbol"},
                    "exchange": {"type": "string", "default": "NASDAQ"}
                },
                "required": ["ticker"]
            }
        ),
        Tool(
            name="get_company_fundamentals",
            description="Get comprehensive company fundamentals (financials, metrics, ratios). Returns JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "exchange": {"type": "string", "default": "NASDAQ"}
                },
                "required": ["ticker"]
            }
        ),
        Tool(
            name="get_historical_data",
            description="Get historical OHLCV data. Returns JSON with data_points, date_range, latest_close.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "period": {"enum": ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"]},
                    "interval": {"enum": ["1m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"]}
                },
                "required": ["ticker"]
            }
        ),
        Tool(
            name="batch_get_quotes",
            description="Get quotes for multiple tickers efficiently. Returns JSON list.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tickers": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["tickers"]
            }
        ),
        Tool(
            name="search_companies",
            description="Search companies by ticker in Americas exchanges. Returns JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "exchange": {"enum": ["NASDAQ", "NYSE", "AMEX", "all"]}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_market_news",
            description="Get latest market news for a ticker. Returns JSON list of articles.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "from_date": {"type": "string"},
                    "to_date": {"type": "string"}
                },
                "required": ["ticker"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """
    MCP tool dispatcher — routes incoming tool calls to the correct handler.

    This function is registered as the single entry-point for all tool
    invocations on this server. It looks up the handler function by name
    and forwards all keyword arguments from the MCP request.

    Args:
        name:      Tool name from the MCP call request.
        arguments: Dict of input parameters as provided by the caller.

    Returns:
        List containing a single ``TextContent`` with a JSON string payload.
        Returns an error JSON if the tool name is not recognised.
    """
    handlers = {
        "get_real_time_quote": get_real_time_quote,
        "get_company_fundamentals": get_company_fundamentals,
        "get_historical_data": get_historical_data,
        "batch_get_quotes": batch_get_quotes,
        "search_companies": search_companies,
        "get_market_news": get_market_news,
    }
    handler = handlers.get(name)
    if not handler:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
    return await handler(**arguments)

async def get_real_time_quote(ticker: str, exchange: str = "NASDAQ") -> List[TextContent]:
    """
    Fetch a real-time (15-min delayed) quote for a US or Americas-listed stock.

    For US exchanges (NASDAQ, NYSE, AMEX): tries Finnhub first. Finnhub returns
    a ``c`` field (current price) that is non-zero when a valid quote exists.
    Falls back to yfinance when Finnhub returns zero/null or raises an exception.

    For non-US Americas exchanges (TSX, B3, BMV): goes directly to yfinance
    since Finnhub's coverage outside the US is limited.

    Args:
        ticker:   Stock ticker symbol (e.g. ``"AAPL"``, ``"RY"`` for Royal Bank).
        exchange: Exchange code (default ``"NASDAQ"``).

    Returns:
        List with a single TextContent whose ``.text`` is a JSON string
        containing: ``ticker``, ``exchange``, ``price``, ``change``,
        ``change_percent``, ``high``, ``low``, ``open``, ``previous_close``,
        ``volume``, ``timestamp``, ``source`` (``"finnhub"`` or ``"yfinance"``),
        ``delay_minutes`` (15). On error, returns ``{"error": str}``.
    """
    try:
        # Try Finnhub first for US exchanges
        if exchange in ("NASDAQ", "NYSE", "AMEX"):
            quote = finnhub_client.quote(ticker)
            if quote and quote.get('c') and quote['c'] != 0:
                result = {
                    "ticker": ticker,
                    "exchange": exchange,
                    "price": round(quote['c'], 2),
                    "change": round(quote.get('d', 0), 2),
                    "change_percent": round(quote.get('dp', 0), 2),
                    "high": round(quote.get('h', 0), 2),
                    "low": round(quote.get('l', 0), 2),
                    "open": round(quote.get('o', 0), 2),
                    "previous_close": round(quote.get('pc', 0), 2),
                    "volume": 0,
                    "timestamp": datetime.now().isoformat(),
                    "source": "finnhub",
                    "delay_minutes": 15
                }
                return [TextContent(type="text", text=json.dumps(result))]
    except Exception:
        pass

    # Fallback: yfinance
    try:
        info = yf.Ticker(ticker).info
        price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        if not price:
            return [TextContent(type="text", text=json.dumps({"error": f"No data for {ticker}"}))]
        prev = info.get('previousClose') or price
        change = round(float(price) - float(prev), 2)
        change_pct = round((change / float(prev)) * 100, 2) if prev else 0
        result = {
            "ticker": ticker,
            "exchange": exchange,
            "price": round(float(price), 2),
            "change": change,
            "change_percent": change_pct,
            "high": round(float(info.get('dayHigh') or price), 2),
            "low": round(float(info.get('dayLow') or price), 2),
            "open": round(float(info.get('open') or price), 2),
            "previous_close": round(float(prev), 2),
            "volume": info.get('regularMarketVolume') or info.get('volume') or 0,
            "timestamp": datetime.now().isoformat(),
            "source": "yfinance",
            "delay_minutes": 15
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

async def get_company_fundamentals(ticker: str, exchange: str = "NASDAQ") -> List[TextContent]:
    """
    Fetch comprehensive fundamental data for an Americas-listed company.

    Uses ``yfinance.Ticker.info`` as the sole data source. The raw description
    (``longBusinessSummary``) is truncated at 300 characters to keep the MCP
    response payload manageable; the backend's AV enrichment pipeline provides
    a full description from Alpha Vantage OVERVIEW.

    Args:
        ticker:   Stock ticker symbol.
        exchange: Exchange code (default ``"NASDAQ"``).

    Returns:
        List with a single TextContent containing a JSON dict with fundamental
        fields including ``company_name``, ``sector``, ``industry``,
        ``market_cap``, ``pe_ratio``, ``forward_pe``, ``peg_ratio``,
        ``price_to_book``, ``dividend_yield``, ``profit_margin``, ``roe``,
        ``debt_to_equity``, ``beta``, ``52_week_high``, ``52_week_low``,
        ``employees``, ``website``, ``description``, ``source``.
    """
    try:
        info = yf.Ticker(ticker).info
        result = {
            "ticker": ticker,
            "exchange": exchange,
            "company_name": info.get('longName') or info.get('shortName') or ticker,
            "sector": info.get('sector'),
            "industry": info.get('industry'),
            "market_cap": info.get('marketCap'),
            "pe_ratio": info.get('trailingPE'),
            "forward_pe": info.get('forwardPE'),
            "peg_ratio": info.get('pegRatio'),
            "price_to_book": info.get('priceToBook'),
            "dividend_yield": info.get('dividendYield'),
            "profit_margin": info.get('profitMargins'),
            "roe": info.get('returnOnEquity'),
            "debt_to_equity": info.get('debtToEquity'),
            "beta": info.get('beta'),
            "52_week_high": info.get('fiftyTwoWeekHigh'),
            "52_week_low": info.get('fiftyTwoWeekLow'),
            "employees": info.get('fullTimeEmployees'),
            "website": info.get('website'),
            "description": (info.get('longBusinessSummary') or '')[:300],
            "updated_at": datetime.now().isoformat(),
            "source": "yfinance"
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

async def get_historical_data(ticker: str, period: str = '1y', interval: str = '1d') -> List[TextContent]:
    """
    Fetch OHLCV summary statistics for a ticker (not the full candle array).

    Returns metadata about the historical dataset rather than the full candle
    list, to keep the MCP response small. For full candle arrays, the analytics
    MCP server's ``get_price_history`` tool should be used instead.

    Args:
        ticker:   Stock ticker symbol.
        period:   yfinance period string (e.g. ``"1y"``, ``"6mo"``).
        interval: yfinance interval string (e.g. ``"1d"``, ``"1wk"``).

    Returns:
        List with a single TextContent containing: ``ticker``, ``period``,
        ``interval``, ``data_points`` (int), ``latest_close`` (float),
        ``latest_volume`` (int), ``date_range`` (str ``"YYYY-MM-DD to YYYY-MM-DD"``),
        ``source``.
    """
    try:
        hist = yf.Ticker(ticker).history(period=period, interval=interval)
        if hist.empty:
            return [TextContent(type="text", text=json.dumps({"error": f"No historical data for {ticker}"}))]
        latest = hist.iloc[-1]
        result = {
            "ticker": ticker,
            "period": period,
            "interval": interval,
            "data_points": len(hist),
            "latest_close": round(float(latest['Close']), 2),
            "latest_volume": int(latest['Volume']),
            "date_range": f"{hist.index[0].date()} to {hist.index[-1].date()}",
            "source": "yfinance"
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

async def batch_get_quotes(tickers: List[str]) -> List[TextContent]:
    """
    Fetch current prices for multiple tickers in a single call.

    Iterates the ticker list sequentially (yfinance does not have a true bulk
    quote API). Each ticker that fails returns ``{"ticker": ..., "price": None,
    "error": "fetch failed"}`` so the batch result is always complete.

    Args:
        tickers: List of ticker symbol strings.

    Returns:
        List with a single TextContent containing ``{"quotes": [...]}``.
    """
    try:
        results = []
        for ticker in tickers:
            try:
                info = yf.Ticker(ticker).info
                price = info.get('currentPrice') or info.get('regularMarketPrice')
                results.append({"ticker": ticker, "price": round(float(price), 2) if price else None})
            except Exception:
                results.append({"ticker": ticker, "price": None, "error": "fetch failed"})
        return [TextContent(type="text", text=json.dumps({"quotes": results}))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

async def search_companies(query: str, exchange: str = 'all') -> List[TextContent]:
    """
    Search for a company by exact ticker symbol using yfinance.

    This is a lightweight single-ticker probe rather than a full text search.
    The backend orchestrator's ``/api/search`` endpoint provides the full
    multi-source search pipeline (Alpha Vantage + yfinance.Search).

    Args:
        query:    Ticker symbol to probe (exact match only).
        exchange: Exchange filter (currently unused — yfinance probes globally).

    Returns:
        List with a single TextContent containing ``{"results": [...], "total": N}``.
        Returns an empty results list if no matching ticker is found.
    """
    try:
        info = yf.Ticker(query.upper()).info
        name = info.get('longName') or info.get('shortName')
        if name:
            result = {"results": [{"ticker": query.upper(), "name": name,
                                   "exchange": info.get('exchange', exchange),
                                   "sector": info.get('sector')}], "total": 1}
        else:
            result = {"results": [], "total": 0}
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

async def get_market_news(ticker: str, from_date: str = None, to_date: str = None) -> List[TextContent]:
    """
    Fetch recent news articles for a company via Finnhub.

    Defaults to a 7-day trailing window when dates are not provided. Returns
    the 5 most relevant articles from Finnhub (already ranked by relevance).
    Note: the backend's ``/api/news/{ticker}`` endpoint provides a richer
    multi-source pipeline (Marketaux + yfinance + DuckDuckGo) and is preferred
    for frontend display.

    Args:
        ticker:    Stock ticker symbol (US tickers work best with Finnhub).
        from_date: Start date string ``"YYYY-MM-DD"`` (defaults to 7 days ago).
        to_date:   End date string ``"YYYY-MM-DD"`` (defaults to today).

    Returns:
        List with a single TextContent containing: ``{"ticker": str,
        "articles": [{"headline", "source", "url"}, ...]}``.
    """
    try:
        if from_date is None:
            from_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        if to_date is None:
            to_date = datetime.now().strftime('%Y-%m-%d')
        news = finnhub_client.company_news(ticker, _from=from_date, to=to_date)
        articles = [{"headline": a['headline'], "source": a['source'], "url": a.get('url', '')}
                    for a in (news or [])[:5]]
        return [TextContent(type="text", text=json.dumps({"ticker": ticker, "articles": articles}))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

if __name__ == "__main__":
    from mcp.server.stdio import stdio_server

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            pass  # server running
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(main())
