"""
MarketMesh AI — MENA MCP Server.

This MCP server handles all market-data requests for Middle East and North
Africa (MENA) exchanges. It runs as a standalone subprocess communicating over
stdio, managed by the backend orchestrator's lifespan context.

Primary data source:  yfinance — all data (quotes, fundamentals, history,
  indices). Exchange-specific suffixes are appended to tickers so yfinance
  fetches from the correct exchange.
Secondary source:     Finnhub — company news (where coverage exists).

Supported exchanges and yfinance suffixes
-----------------------------------------
- TADAWUL (Saudi Exchange / Riyadh)          — suffix ``.SR``
- DFM     (Dubai Financial Market)           — suffix ``.DU``
- ADX     (Abu Dhabi Securities Exchange)    — suffix ``.AD``
- TASE    (Tel Aviv Stock Exchange / Israel) — suffix ``.TA``
- EGX     (Egyptian Exchange / Cairo)        — suffix ``.CA``
- DSM     (Doha Securities Market / Qatar)   — suffix ``.QA``

Currency handling
-----------------
Each exchange's local currency is stored in ``EXCHANGE_CURRENCY``:
- TADAWUL → SAR (Saudi Riyal)
- DFM/ADX → AED (UAE Dirham)
- TASE    → ILS (Israeli Shekel)
- EGX     → EGP (Egyptian Pound)
- DSM     → QAR (Qatari Riyal)

Tools exposed
-------------
- get_mena_quote:        Real-time (15-min delayed) quote via yfinance.
- get_mena_indices:      Major MENA benchmark indices (TADAWUL All Share, DFM
                         General, Tel Aviv 125, EGX 30).
- get_mena_fundamentals: Full fundamental data from yfinance.info.
- get_mena_historical:   Full OHLCV candle array for a MENA stock.
- get_mena_news:         Company news via Finnhub (7-day trailing window).
- batch_mena_quotes:     Bulk price fetch for multiple MENA tickers.

Dependencies
------------
- yfinance:       All quote/fundamental/historical/index data.
- finnhub-python: Company news.
- mcp:            MCP Python SDK.
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List
import yfinance as yf
import finnhub

from mcp.server import Server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [mena] %(message)s")
log = logging.getLogger(__name__)

server = Server("mena-markets")
finnhub_client = finnhub.Client(api_key=os.getenv('FINNHUB_API_KEY', ''))

EXCHANGE_SUFFIXES = {
    'TADAWUL': '.SR', 'DFM': '.DU', 'ADX': '.AD', 'TASE': '.TA',
    'EGX': '.CA', 'DSM': '.QA'
}

# Correct currency per exchange
EXCHANGE_CURRENCY = {
    'TADAWUL': 'SAR', 'DFM': 'AED', 'ADX': 'AED',
    'TASE': 'ILS',   'EGX': 'EGP', 'DSM': 'QAR',
}


def _sym(ticker: str, exchange: str) -> str:
    suffix = EXCHANGE_SUFFIXES.get(exchange, '')
    return f"{ticker}{suffix}" if suffix and not ticker.endswith(suffix) else ticker


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_mena_quote",
            description="Get quote for MENA stocks. Returns JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":   {"type": "string"},
                    "exchange": {"enum": ["TADAWUL","DFM","ADX","TASE","EGX","DSM"]}
                },
                "required": ["ticker", "exchange"]
            }
        ),
        Tool(
            name="get_mena_indices",
            description="Get major MENA indices. Returns JSON.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_mena_fundamentals",
            description="Get fundamentals for a MENA company. Returns JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":   {"type": "string"},
                    "exchange": {"type": "string"}
                },
                "required": ["ticker", "exchange"]
            }
        ),
        Tool(
            name="get_mena_historical",
            description="Get OHLCV historical data for a MENA stock. Returns JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":   {"type": "string"},
                    "exchange": {"type": "string"},
                    "period":   {"type": "string", "default": "1y",
                                 "enum": ["1mo","3mo","6mo","1y","2y","5y"]},
                    "interval": {"type": "string", "default": "1d",
                                 "enum": ["1d","1wk","1mo"]},
                },
                "required": ["ticker", "exchange"]
            }
        ),
        Tool(
            name="get_mena_news",
            description="Get latest news for a MENA company via Finnhub. Returns JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":   {"type": "string"},
                    "exchange": {"type": "string"},
                },
                "required": ["ticker"]
            }
        ),
        Tool(
            name="batch_mena_quotes",
            description="Get quotes for multiple MENA tickers. Returns JSON list.",
            inputSchema={
                "type": "object",
                "properties": {
                    "tickers":  {"type": "array", "items": {"type": "string"}},
                    "exchange": {"type": "string"}
                },
                "required": ["tickers", "exchange"]
            }
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
        "get_mena_quote":        get_mena_quote,
        "get_mena_indices":      get_mena_indices,
        "get_mena_fundamentals": get_mena_fundamentals,
        "get_mena_historical":   get_mena_historical,
        "get_mena_news":         get_mena_news,
        "batch_mena_quotes":     batch_mena_quotes,
    }
    handler = handlers.get(name)
    if not handler:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
    return await handler(**arguments)


async def get_mena_quote(ticker: str, exchange: str) -> List[TextContent]:
    """
    Fetch a real-time (15-min delayed) quote for a MENA-listed stock.

    Appends the exchange-specific yfinance suffix to the ticker before fetching
    (e.g. ``2222`` on ``TADAWUL`` becomes ``2222.SR`` for Saudi Aramco). The
    ``currency`` field is sourced from yfinance first; falls back to
    ``EXCHANGE_CURRENCY`` to ensure the correct local denomination is returned.

    Args:
        ticker:   Stock ticker symbol without suffix (e.g. ``"2222"``, ``"EMAAR"``).
        exchange: One of the 6 supported MENA exchange codes.

    Returns:
        List with a single TextContent containing: ``ticker``, ``symbol``
        (suffixed), ``exchange``, ``price``, ``change``, ``change_percent``,
        ``high``, ``low``, ``currency``, ``volume``, ``timestamp``, ``source``,
        ``delay_minutes``. Returns ``{"error": str}`` if no price data found.
    """
    try:
        symbol = _sym(ticker, exchange)
        info   = yf.Ticker(symbol).info
        price  = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        if not price:
            return [TextContent(type="text", text=json.dumps({"error": f"No data for {symbol}"}))]
        prev       = info.get('previousClose') or price
        change     = round(float(price) - float(prev), 2)
        change_pct = round((change / float(prev)) * 100, 2) if prev else 0
        result = {
            "ticker": ticker, "symbol": symbol, "exchange": exchange,
            "price": round(float(price), 2), "change": change, "change_percent": change_pct,
            "high": round(float(info.get('dayHigh') or price), 2),
            "low":  round(float(info.get('dayLow')  or price), 2),
            "currency": info.get('currency') or EXCHANGE_CURRENCY.get(exchange, 'USD'),
            "volume":   info.get('regularMarketVolume') or info.get('volume') or 0,
            "timestamp": datetime.now().isoformat(), "source": "yfinance", "delay_minutes": 15
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def get_mena_indices(**kwargs) -> List[TextContent]:
    """
    Fetch current levels and day-change for 4 major MENA benchmark indices.

    Fetches TADAWUL All Share (^TASI.SR), DFM General (^DFMGI), Tel Aviv 125
    (^TA125.TA), and EGX 30 (^EGX30) via yfinance. Individual failures are
    caught and represented as ``{"value": None, "change": 0}``.

    Returns:
        List with a single TextContent containing: ``{"indices": {name: {value, change}},
        "source": "yfinance"}``.
    """
    indices = {
        '^TASI.SR': 'TADAWUL All Share', '^DFMGI': 'DFM General',
        '^TA125.TA': 'Tel Aviv 125',      '^EGX30': 'EGX 30',
    }
    try:
        results = {}
        for symbol, name in indices.items():
            try:
                info  = yf.Ticker(symbol).info
                price = info.get('regularMarketPrice') or info.get('previousClose')
                prev  = info.get('regularMarketPreviousClose') or info.get('previousClose') or price
                chg   = round(((float(price) - float(prev)) / float(prev)) * 100, 2) if price and prev else 0
                results[name] = {"value": round(float(price), 2) if price else None, "change": chg}
            except Exception:
                results[name] = {"value": None, "change": 0}
        return [TextContent(type="text", text=json.dumps({"indices": results, "source": "yfinance"}))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def get_mena_fundamentals(ticker: str, exchange: str) -> List[TextContent]:
    """
    Fetch comprehensive fundamental data for a MENA-listed company.

    Appends the exchange suffix before the yfinance call. Description is
    truncated at 500 characters. The backend's Alpha Vantage enrichment pipeline
    may supplement PE, ROE, and margin fields if yfinance returns None.

    Args:
        ticker:   Stock ticker symbol without suffix.
        exchange: MENA exchange code (e.g. ``"TADAWUL"``, ``"DFM"``).

    Returns:
        List with a single TextContent containing full fundamental fields plus
        ``symbol`` (suffixed ticker) and ``currency`` (from yfinance or lookup table).
    """
    try:
        symbol = _sym(ticker, exchange)
        info   = yf.Ticker(symbol).info
        result = {
            "ticker": ticker, "symbol": symbol, "exchange": exchange,
            "company_name":  info.get('longName') or info.get('shortName') or ticker,
            "sector":        info.get('sector'),
            "industry":      info.get('industry'),
            "market_cap":    info.get('marketCap'),
            "pe_ratio":      info.get('trailingPE'),
            "forward_pe":    info.get('forwardPE'),
            "price_to_book": info.get('priceToBook'),
            "dividend_yield":info.get('dividendYield'),
            "profit_margin": info.get('profitMargins'),
            "roe":           info.get('returnOnEquity'),
            "beta":          info.get('beta'),
            "52_week_high":  info.get('fiftyTwoWeekHigh'),
            "52_week_low":   info.get('fiftyTwoWeekLow'),
            "employees":     info.get('fullTimeEmployees'),
            "website":       info.get('website'),
            "description":   (info.get('longBusinessSummary') or '')[:500],
            "currency": info.get('currency') or EXCHANGE_CURRENCY.get(exchange, 'USD'),
            "updated_at":    datetime.now().isoformat(),
            "source":        "yfinance"
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def get_mena_historical(ticker: str, exchange: str,
                               period: str = "1y", interval: str = "1d") -> List[TextContent]:
    """
    Fetch the full OHLCV candle array for a MENA-listed stock.

    Appends the exchange suffix and fetches with ``auto_adjust=True`` for
    dividend/split adjustments. Returns the full candles list suitable for
    frontend charting.

    Args:
        ticker:   Stock ticker symbol without suffix.
        exchange: MENA exchange code.
        period:   yfinance period string (``"1mo"``–``"5y"``).
        interval: yfinance interval string (``"1d"``, ``"1wk"``, ``"1mo"``).

    Returns:
        List with a single TextContent containing: ``ticker``, ``exchange``,
        ``period``, ``interval``, ``data_points``, ``candles`` (list of
        ``{date, open, high, low, close, volume}`` dicts), ``source``.
    """
    try:
        symbol = _sym(ticker, exchange)
        hist   = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
        if hist.empty:
            return [TextContent(type="text", text=json.dumps({"error": f"No history for {symbol}"}))]
        candles = [
            {"date": str(idx.date()), "open": round(float(r["Open"]),2),
             "high": round(float(r["High"]),2), "low": round(float(r["Low"]),2),
             "close": round(float(r["Close"]),2), "volume": int(r["Volume"])}
            for idx, r in hist.iterrows()
        ]
        return [TextContent(type="text", text=json.dumps({
            "ticker": ticker, "exchange": exchange, "period": period, "interval": interval,
            "data_points": len(candles), "candles": candles, "source": "yfinance"
        }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def get_mena_news(ticker: str, exchange: str = "") -> List[TextContent]:
    """
    Fetch recent news articles for a MENA company via Finnhub.

    Uses a 7-day trailing window. Finnhub's coverage for MENA tickers is limited
    to companies with a US ADR or international listing. For broader news, the
    backend orchestrator's ``/api/news/{ticker}`` endpoint (which also searches
    by company name) is more reliable for MENA stocks.

    Args:
        ticker:   Stock ticker symbol.
        exchange: Exchange code (currently unused in the Finnhub call).

    Returns:
        List with a single TextContent containing: ``{"ticker": str,
        "articles": [{"headline", "source", "url", "published_at"}, ...],
        "source": "finnhub"}``.
    """
    try:
        from_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        to_date   = datetime.now().strftime('%Y-%m-%d')
        news      = finnhub_client.company_news(ticker, _from=from_date, to=to_date)
        articles  = [
            {"headline": a['headline'], "source": a['source'], "url": a.get('url',''),
             "published_at": datetime.fromtimestamp(a.get('datetime',0)).isoformat()}
            for a in (news or [])[:10]
        ]
        return [TextContent(type="text", text=json.dumps({"ticker": ticker, "articles": articles, "source": "finnhub"}))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def batch_mena_quotes(tickers: List[str], exchange: str) -> List[TextContent]:
    """
    Fetch current prices for multiple MENA tickers on the same exchange.

    Applies the exchange suffix to each ticker before the yfinance call. Failed
    individual tickers are included as ``{"price": None, "error": "fetch failed"}``.
    The ``currency`` field is returned per-ticker from the local currency map.

    Args:
        tickers:  List of ticker symbols (without suffix).
        exchange: MENA exchange code applied to all tickers in the batch.

    Returns:
        List with a single TextContent containing ``{"quotes": [...]}``.
    """
    results = []
    for ticker in tickers:
        try:
            symbol = _sym(ticker, exchange)
            info   = yf.Ticker(symbol).info
            price  = info.get('currentPrice') or info.get('regularMarketPrice')
            results.append({
                "ticker": ticker, "price": round(float(price), 2) if price else None,
                "currency": info.get('currency') or EXCHANGE_CURRENCY.get(exchange, 'USD'),
            })
        except Exception:
            results.append({"ticker": ticker, "price": None, "error": "fetch failed"})
    return [TextContent(type="text", text=json.dumps({"quotes": results}))]


if __name__ == "__main__":
    from mcp.server.stdio import stdio_server

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(main())
