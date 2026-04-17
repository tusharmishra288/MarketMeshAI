"""
StockPilot AI — Europe MCP Server.

This MCP server handles all market-data requests for European exchanges. It
runs as a standalone subprocess communicating over stdio, managed by the
backend orchestrator's lifespan context.

Primary data source:  yfinance — all data (quotes, fundamentals, history,
  indices). Exchange-specific suffixes are appended to tickers so yfinance
  fetches from the correct exchange (e.g. ``AZN.L`` for AstraZeneca on LSE).
Secondary source:     Finnhub — company news only (for some EU tickers).

Supported exchanges and yfinance suffixes
-----------------------------------------
- LSE    (London Stock Exchange)     — suffix ``.L``
- XETRA  (Frankfurt / Germany)       — suffix ``.DE``
- EPA    (Euronext Paris / France)   — suffix ``.PA``
- AMS    (Euronext Amsterdam)        — suffix ``.AS``
- SWX    (SIX Swiss Exchange)        — suffix ``.SW``
- BIT    (Borsa Italiana / Milan)    — suffix ``.MI``
- MCE    (Bolsa de Madrid / Spain)   — suffix ``.MC``
- OSL    (Oslo Stock Exchange)       — suffix ``.OL``
- HEL    (Helsinki Stock Exchange)   — suffix ``.HE``

Currency handling
-----------------
Each exchange's local currency is stored in ``EXCHANGE_CURRENCY`` so the API
returns the correct currency code (e.g. ``"GBp"`` for LSE pence, ``"CHF"`` for
SWX, ``"NOK"`` for OSL) rather than defaulting to EUR for all European markets.

Tools exposed
-------------
- get_european_quote:        Real-time (15-min delayed) quote via yfinance.
- get_european_indices:      Major European benchmark indices (FTSE, DAX, CAC40, AEX, IBEX, SMI).
- get_european_fundamentals: Full fundamental data from yfinance.info.
- get_european_historical:   OHLCV candle array for a European stock.
- get_european_news:         Company news via Finnhub (falls back to suffixed symbol).
- batch_european_quotes:     Bulk price fetch for multiple European tickers.

Dependencies
------------
- yfinance:       All quote/fundamental/historical data.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [europe] %(message)s")
log = logging.getLogger(__name__)

server = Server("europe-markets")
finnhub_client = finnhub.Client(api_key=os.getenv('FINNHUB_API_KEY', ''))

# yfinance suffix per exchange
EXCHANGE_SUFFIXES = {
    "LSE": ".L", "XETRA": ".DE", "EPA": ".PA", "AMS": ".AS",
    "SWX": ".SW", "BIT": ".MI", "MCE": ".MC", "OSL": ".OL", "HEL": ".HE"
}

# Correct currency per exchange (not all European exchanges use EUR)
EXCHANGE_CURRENCY = {
    "LSE":   "GBp",   # London — pence
    "XETRA": "EUR",
    "EPA":   "EUR",
    "AMS":   "EUR",
    "SWX":   "CHF",   # Swiss franc
    "BIT":   "EUR",
    "MCE":   "EUR",
    "OSL":   "NOK",   # Norwegian krone
    "HEL":   "EUR",
}


def _sym(ticker: str, exchange: str) -> str:
    suffix = EXCHANGE_SUFFIXES.get(exchange, "")
    return f"{ticker}{suffix}" if suffix and not ticker.endswith(suffix) else ticker


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_european_quote",
            description="Get quote for European stocks. Returns JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":   {"type": "string"},
                    "exchange": {"enum": ["LSE","XETRA","EPA","AMS","SWX","BIT","MCE","OSL","HEL"]}
                },
                "required": ["ticker", "exchange"]
            }
        ),
        Tool(
            name="get_european_indices",
            description="Get major European indices (FTSE, DAX, CAC40, etc.). Returns JSON.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="get_european_fundamentals",
            description="Get fundamentals for a European company. Returns JSON.",
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
            name="get_european_historical",
            description="Get OHLCV historical data for a European stock. Returns JSON.",
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
            name="get_european_news",
            description="Get latest news for a European company via Finnhub. Returns JSON.",
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
            name="batch_european_quotes",
            description="Get quotes for multiple European tickers. Returns JSON list.",
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
        "get_european_quote":        get_european_quote,
        "get_european_indices":      get_european_indices,
        "get_european_fundamentals": get_european_fundamentals,
        "get_european_historical":   get_european_historical,
        "get_european_news":         get_european_news,
        "batch_european_quotes":     batch_european_quotes,
    }
    handler = handlers.get(name)
    if not handler:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
    return await handler(**arguments)


async def get_european_quote(ticker: str, exchange: str) -> List[TextContent]:
    """
    Fetch a real-time (15-min delayed) quote for a European-listed stock.

    Appends the exchange-specific yfinance suffix to the ticker before fetching
    (e.g. ``AZN`` on ``LSE`` becomes ``AZN.L``). The ``currency`` field is
    sourced from yfinance first; falls back to ``EXCHANGE_CURRENCY`` to ensure
    the correct local currency is always returned.

    Args:
        ticker:   Stock ticker symbol without suffix (e.g. ``"VOW3"``, ``"AZN"``).
        exchange: One of the 9 supported European exchange codes.

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
            "currency": info.get('currency') or EXCHANGE_CURRENCY.get(exchange, 'EUR'),
            "volume":   info.get('regularMarketVolume') or info.get('volume') or 0,
            "timestamp": datetime.now().isoformat(), "source": "yfinance", "delay_minutes": 15
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def get_european_indices(**kwargs) -> List[TextContent]:
    """
    Fetch current levels and day-change for 6 major European benchmark indices.

    Fetches FTSE 100 (^FTSE), DAX (^GDAXI), CAC 40 (^FCHI), AEX (^AEX),
    IBEX 35 (^IBEX), and SMI (^SSMI) via yfinance. Individual index failures
    are caught and represented as ``{"value": None, "change": 0}``.

    Returns:
        List with a single TextContent containing: ``{"indices": {name: {value, change}},
        "source": "yfinance"}``.
    """
    indices = {'^FTSE': 'FTSE 100', '^GDAXI': 'DAX', '^FCHI': 'CAC 40',
               '^AEX': 'AEX', '^IBEX': 'IBEX 35', '^SSMI': 'SMI'}
    try:
        results = {}
        for symbol, name in indices.items():
            try:
                info = yf.Ticker(symbol).info
                price = info.get('regularMarketPrice') or info.get('previousClose')
                prev  = info.get('regularMarketPreviousClose') or info.get('previousClose') or price
                chg   = round(((float(price) - float(prev)) / float(prev)) * 100, 2) if price and prev else 0
                results[name] = {"value": round(float(price), 2) if price else None, "change": chg}
            except Exception:
                results[name] = {"value": None, "change": 0}
        return [TextContent(type="text", text=json.dumps({"indices": results, "source": "yfinance"}))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def get_european_fundamentals(ticker: str, exchange: str) -> List[TextContent]:
    """
    Fetch comprehensive fundamental data for a European-listed company.

    Appends the exchange suffix before the yfinance call. The description is
    truncated at 500 characters; the backend's Alpha Vantage enrichment pipeline
    supplements PE, ROE, and margin data if yfinance returns None for those fields.

    Args:
        ticker:   Stock ticker symbol without suffix.
        exchange: European exchange code (e.g. ``"LSE"``, ``"XETRA"``).

    Returns:
        List with a single TextContent containing full fundamental fields plus
        ``symbol`` (suffixed ticker), ``currency`` (from yfinance or lookup table).
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
            "currency": info.get('currency') or EXCHANGE_CURRENCY.get(exchange, 'EUR'),
            "updated_at":    datetime.now().isoformat(),
            "source":        "yfinance"
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def get_european_historical(ticker: str, exchange: str,
                                   period: str = "1y", interval: str = "1d") -> List[TextContent]:
    """
    Fetch OHLCV candle array for a European stock.

    Unlike the Americas ``get_historical_data`` tool which returns only summary
    stats, this tool returns the full ``candles`` array suitable for charting.
    ``auto_adjust=True`` is passed to yfinance to apply dividend/split adjustments.

    Args:
        ticker:   Stock ticker symbol without suffix.
        exchange: European exchange code.
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


async def get_european_news(ticker: str, exchange: str = "") -> List[TextContent]:
    """
    Fetch recent news articles for a European company via Finnhub.

    Tries the bare ticker first (works for some European companies listed in
    Finnhub's database), then retries with the exchange-suffixed symbol if the
    first attempt returns no results.

    Args:
        ticker:   Stock ticker symbol (bare, without suffix).
        exchange: European exchange code (optional — used only for suffix fallback).

    Returns:
        List with a single TextContent containing: ``{"ticker": str,
        "articles": [{"headline", "source", "url", "published_at"}, ...],
        "source": "finnhub"}``.
    """
    try:
        symbol   = _sym(ticker, exchange) if exchange else ticker
        from_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        to_date   = datetime.now().strftime('%Y-%m-%d')
        # Finnhub works for some EU tickers; use both bare ticker and suffixed
        news = finnhub_client.company_news(ticker, _from=from_date, to=to_date)
        if not news:
            news = finnhub_client.company_news(symbol, _from=from_date, to=to_date)
        articles = [
            {"headline": a['headline'], "source": a['source'], "url": a.get('url',''),
             "published_at": datetime.fromtimestamp(a.get('datetime',0)).isoformat()}
            for a in (news or [])[:10]
        ]
        return [TextContent(type="text", text=json.dumps({"ticker": ticker, "articles": articles, "source": "finnhub"}))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def batch_european_quotes(tickers: List[str], exchange: str) -> List[TextContent]:
    """
    Fetch current prices for multiple European tickers on the same exchange.

    Applies the exchange suffix to each ticker before the yfinance call. Failed
    individual tickers are included in the result as ``{"price": None, "error":
    "fetch failed"}`` to ensure the batch response is always complete.

    Args:
        tickers:  List of ticker symbols (without suffix).
        exchange: European exchange code applied to all tickers in the batch.

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
                "currency": info.get('currency') or EXCHANGE_CURRENCY.get(exchange, 'EUR'),
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
