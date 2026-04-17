"""
StockPilot AI — Asia-Pacific MCP Server.

This MCP server handles all market-data requests for Asia-Pacific exchanges.
It runs as a standalone subprocess communicating over stdio, managed by the
backend orchestrator's lifespan context.

Primary data source:  yfinance — all data (quotes, fundamentals, history,
  indices). Exchange-specific suffixes are appended to tickers so yfinance
  fetches from the correct exchange.
Secondary source:     Finnhub — company news (where coverage exists).

Supported exchanges and yfinance suffixes
-----------------------------------------
- TSE    (Tokyo Stock Exchange / Japan)       — suffix ``.T``
- HKEX   (Hong Kong Stock Exchange)          — suffix ``.HK``
- SSE    (Shanghai Stock Exchange / China)   — suffix ``.SS``
- SZSE   (Shenzhen Stock Exchange / China)   — suffix ``.SZ``
- NSE    (National Stock Exchange / India)   — suffix ``.NS``
- BSE    (Bombay Stock Exchange / India)     — suffix ``.BO``
- ASX    (Australian Securities Exchange)    — suffix ``.AX``
- SGX    (Singapore Exchange)                — suffix ``.SI``
- KRX    (Korea Stock Exchange)              — suffix ``.KS``
- TWSE   (Taiwan Stock Exchange)             — suffix ``.TW``

Currency handling
-----------------
Each exchange's local currency is stored in ``EXCHANGE_CURRENCY``, ensuring
the correct denomination is returned (e.g. ``"JPY"`` for TSE, ``"INR"`` for
NSE/BSE, ``"KRW"`` for KRX).

Tools exposed
-------------
- get_asian_quote:        Real-time (15-min delayed) quote via yfinance.
- get_asian_indices:      Major Asia-Pacific benchmark indices (Nikkei, Hang Seng,
                          Shanghai, Nifty 50, ASX 200, KOSPI).
- get_asian_fundamentals: Full fundamental data from yfinance.info.
- get_asian_historical:   OHLCV candle array for an Asia-Pacific stock.
- get_asian_news:         Company news via Finnhub.
- batch_asian_quotes:     Bulk price fetch for multiple Asia-Pacific tickers.

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [asia_pacific] %(message)s")
log = logging.getLogger(__name__)

server = Server("asia-pacific-markets")
finnhub_client = finnhub.Client(api_key=os.getenv('FINNHUB_API_KEY', ''))

EXCHANGE_SUFFIXES = {
    'TSE': '.T', 'HKEX': '.HK', 'SSE': '.SS', 'SZSE': '.SZ',
    'NSE': '.NS', 'BSE': '.BO', 'ASX': '.AX', 'SGX': '.SI',
    'KRX': '.KS', 'TWSE': '.TW'
}

# Correct currency per exchange
EXCHANGE_CURRENCY = {
    'TSE':  'JPY', 'HKEX': 'HKD', 'SSE':  'CNY', 'SZSE': 'CNY',
    'NSE':  'INR', 'BSE':  'INR', 'ASX':  'AUD', 'SGX':  'SGD',
    'KRX':  'KRW', 'TWSE': 'TWD',
}


def _sym(ticker: str, exchange: str) -> str:
    suffix = EXCHANGE_SUFFIXES.get(exchange, '')
    return f"{ticker}{suffix}" if suffix and not ticker.endswith(suffix) else ticker


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_asian_quote",
            description="Get quote for Asia-Pacific stocks. Returns JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":   {"type": "string"},
                    "exchange": {"enum": ["TSE","HKEX","SSE","SZSE","NSE","BSE","ASX","SGX","KRX","TWSE"]}
                },
                "required": ["ticker", "exchange"]
            }
        ),
        Tool(
            name="get_asian_indices",
            description="Get major Asia-Pacific indices. Returns JSON.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_asian_fundamentals",
            description="Get fundamentals for an Asia-Pacific company. Returns JSON.",
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
            name="get_asian_historical",
            description="Get OHLCV historical data for an Asia-Pacific stock. Returns JSON.",
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
            name="get_asian_news",
            description="Get latest news for an Asia-Pacific company via Finnhub. Returns JSON.",
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
            name="batch_asian_quotes",
            description="Get quotes for multiple Asia-Pacific tickers. Returns JSON list.",
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
        "get_asian_quote":        get_asian_quote,
        "get_asian_indices":      get_asian_indices,
        "get_asian_fundamentals": get_asian_fundamentals,
        "get_asian_historical":   get_asian_historical,
        "get_asian_news":         get_asian_news,
        "batch_asian_quotes":     batch_asian_quotes,
    }
    handler = handlers.get(name)
    if not handler:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
    return await handler(**arguments)


async def get_asian_quote(ticker: str, exchange: str) -> List[TextContent]:
    """
    Fetch a real-time (15-min delayed) quote for an Asia-Pacific-listed stock.

    Appends the exchange-specific yfinance suffix to the ticker before fetching
    (e.g. ``7203`` on ``TSE`` becomes ``7203.T`` for Toyota). The ``currency``
    field falls back to ``EXCHANGE_CURRENCY`` to ensure local denomination is
    always returned (e.g. ``"JPY"``, ``"INR"``, ``"KRW"``).

    Args:
        ticker:   Stock ticker symbol without suffix (e.g. ``"7203"``, ``"RELIANCE"``).
        exchange: One of the 10 supported Asia-Pacific exchange codes.

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


async def get_asian_indices(**kwargs) -> List[TextContent]:
    """
    Fetch current levels and day-change for 6 major Asia-Pacific benchmark indices.

    Fetches Nikkei 225 (^N225), Hang Seng (^HSI), Shanghai Composite (000001.SS),
    Nifty 50 (^NSEI), ASX 200 (^AXJO), and KOSPI (^KS11) via yfinance.
    Individual index failures are caught and represented as ``{"value": None, "change": 0}``.

    Returns:
        List with a single TextContent containing: ``{"indices": {name: {value, change}},
        "source": "yfinance"}``.
    """
    indices = {
        '^N225': 'Nikkei 225', '^HSI': 'Hang Seng', '000001.SS': 'Shanghai',
        '^NSEI': 'Nifty 50',   '^AXJO': 'ASX 200',  '^KS11': 'KOSPI',
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


async def get_asian_fundamentals(ticker: str, exchange: str) -> List[TextContent]:
    """
    Fetch comprehensive fundamental data for an Asia-Pacific-listed company.

    Appends the exchange suffix before the yfinance call. The description is
    truncated at 500 characters. The backend's Alpha Vantage enrichment pipeline
    may supplement fields like PE and ROE if yfinance returns None.

    Args:
        ticker:   Stock ticker symbol without suffix.
        exchange: Asia-Pacific exchange code (e.g. ``"NSE"``, ``"TSE"``).

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
            "peg_ratio":     info.get('pegRatio'),
            "price_to_book": info.get('priceToBook'),
            "dividend_yield":info.get('dividendYield'),
            "profit_margin": info.get('profitMargins'),
            "roe":           info.get('returnOnEquity'),
            "debt_to_equity":info.get('debtToEquity'),
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


async def get_asian_historical(ticker: str, exchange: str,
                                period: str = "1y", interval: str = "1d") -> List[TextContent]:
    """
    Fetch the full OHLCV candle array for an Asia-Pacific stock.

    Appends the exchange suffix and fetches with ``auto_adjust=True`` to apply
    dividend/split adjustments. Returns the full candles list suitable for
    charting, unlike the Americas server which returns only summary stats.

    Args:
        ticker:   Stock ticker symbol without suffix.
        exchange: Asia-Pacific exchange code.
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


async def get_asian_news(ticker: str, exchange: str = "") -> List[TextContent]:
    """
    Fetch recent news articles for an Asia-Pacific company via Finnhub.

    Uses the bare ticker (Finnhub's coverage for Asian tickers is limited; the
    bare ticker sometimes works for ADR-listed or dual-listed companies).
    For better news coverage of Asian stocks, the backend orchestrator's
    ``/api/news/{ticker}`` endpoint with company name search is recommended.

    Args:
        ticker:   Stock ticker symbol.
        exchange: Exchange code (currently unused in this implementation).

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


async def batch_asian_quotes(tickers: List[str], exchange: str) -> List[TextContent]:
    """
    Fetch current prices for multiple Asia-Pacific tickers on the same exchange.

    Applies the exchange suffix to each ticker before the yfinance call. Failed
    individual tickers are included as ``{"price": None, "error": "fetch failed"}``.

    Args:
        tickers:  List of ticker symbols (without suffix).
        exchange: Asia-Pacific exchange code applied to all tickers in the batch.

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
