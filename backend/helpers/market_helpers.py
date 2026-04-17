"""
StockPilot AI — Market Helpers (exchange/region mappings, market status, index fetch).

This module provides shared look-up tables and lightweight helper functions
used by the market, analytics, and intelligence route modules. It does not
perform any network I/O directly except for ``_fetch_index()``, which pulls a
single price from yfinance.

Key responsibilities
--------------------
- ``EXCHANGE_REGION``: maps 27 exchange codes to one of four region strings so
  route handlers can route requests to the correct MCP server without a
  lengthy conditional chain.
- ``QUOTE_TOOL`` / ``FUNDAMENTALS_TOOL``: maps each region to the MCP tool
  name that should be invoked for quotes and fundamentals respectively.
- ``SECTOR_PEERS``: curated list of large-cap peers for each GICS sector, used
  by the ``/api/peers/{ticker}`` endpoint as a quick comparison set.
- ``_market_status()``: derives open/closed status from the local exchange time
  without calling any external API.
- ``_fetch_index()``: pulls a single benchmark index value from yfinance for
  the Americas regional snapshot (NASDAQ, S&P 500, Dow Jones).
- ``_get_region()``: exchange → region string lookup with a safe default.

Dependencies
------------
- yfinance:  Used only in ``_fetch_index()`` for US benchmark index prices.
- pytz:      Timezone-aware datetime for market status windows.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict

import yfinance as yf

log = logging.getLogger(__name__)

# ── Exchange → Region mapping ─────────────────────────────────────────────────

EXCHANGE_REGION: Dict[str, str] = {
    "NASDAQ": "americas", "NYSE": "americas", "AMEX": "americas",
    "TSX": "americas",    "B3": "americas",   "BMV": "americas",
    "LSE": "europe",  "XETRA": "europe", "EPA": "europe", "AMS": "europe",
    "SWX": "europe",  "BIT": "europe",   "MCE": "europe", "OSL": "europe", "HEL": "europe",
    "TSE": "asia_pacific", "HKEX": "asia_pacific", "SSE": "asia_pacific",
    "SZSE": "asia_pacific","NSE": "asia_pacific",  "BSE": "asia_pacific",
    "ASX": "asia_pacific", "SGX": "asia_pacific",  "KRX": "asia_pacific", "TWSE": "asia_pacific",
    "TADAWUL": "mena", "DFM": "mena", "ADX": "mena",
    "TASE": "mena",   "EGX": "mena", "DSM": "mena",
}

QUOTE_TOOL: Dict[str, str] = {
    "americas":    "get_real_time_quote",
    "europe":      "get_european_quote",
    "asia_pacific": "get_asian_quote",
    "mena":        "get_mena_quote",
}

FUNDAMENTALS_TOOL: Dict[str, str] = {
    "americas":    "get_company_fundamentals",
    "europe":      "get_european_fundamentals",
    "asia_pacific": "get_asian_fundamentals",
    "mena":        "get_mena_fundamentals",
}

SECTOR_PEERS: Dict[str, list] = {
    "Technology":            ["AAPL","MSFT","GOOGL","META","NVDA","AMD","INTC","CRM","ORCL"],
    "Financial Services":    ["JPM","BAC","GS","MS","WFC","C","BLK","AXP","SCHW"],
    "Healthcare":            ["JNJ","PFE","UNH","ABBV","MRK","TMO","ABT","AMGN","GILD"],
    "Consumer Cyclical":     ["AMZN","TSLA","HD","NKE","SBUX","MCD","LOW","TGT","BKNG"],
    "Consumer Defensive":    ["WMT","PG","KO","PEP","COST","CL","GIS","KHC","MO"],
    "Energy":                ["XOM","CVX","COP","EOG","SLB","MPC","PSX","OXY","PXD"],
    "Industrials":           ["CAT","HON","UPS","BA","MMM","RTX","LMT","NOC","GE"],
    "Communication Services":["GOOGL","META","NFLX","DIS","CMCSA","VZ","T","EA","ATVI"],
    "Utilities":             ["NEE","DUK","SO","D","AEP","EXC","SRE","XEL","PPL"],
    "Real Estate":           ["AMT","PLD","CCI","EQIX","SPG","PSA","WELL","DLR","O"],
    "Basic Materials":       ["LIN","APD","ECL","SHW","DOW","NEM","FCX","NUE","VMC"],
}


def _get_region(exchange: str) -> str:
    """
    Map an exchange code to its StockPilot region string.

    The lookup is case-insensitive. Unknown exchanges fall back to
    ``"americas"`` so US-default behaviour is preserved for unrecognised inputs
    (e.g. bare ticker lookups where the exchange is not provided).

    Args:
        exchange: Exchange identifier, e.g. ``"NSE"``, ``"NASDAQ"``, ``"LSE"``.

    Returns:
        One of ``"americas"``, ``"europe"``, ``"asia_pacific"``, or ``"mena"``.
    """
    return EXCHANGE_REGION.get(exchange.upper(), "americas")


def _fetch_index(symbol: str) -> dict:
    """
    Fetch the current level and day-change for a benchmark index via yfinance.

    Designed to be called from a ``ThreadPoolExecutor`` (yfinance is blocking).
    Returns a safe fallback dict on any error so the global snapshot endpoint
    does not fail if a single index is unavailable.

    Args:
        symbol: Yahoo Finance ticker for the index, e.g. ``"^IXIC"`` (NASDAQ),
                ``"^GSPC"`` (S&P 500), ``"^DJI"`` (Dow Jones).

    Returns:
        Dict with keys ``"value"`` (float or None) and ``"change"`` (float,
        percentage change from previous close, defaults to 0 on error).
    """
    try:
        info  = yf.Ticker(symbol).info
        price = info.get("regularMarketPrice") or info.get("previousClose")
        prev  = info.get("regularMarketPreviousClose") or info.get("previousClose") or price
        chg   = round(((float(price) - float(prev)) / float(prev)) * 100, 2) if price and prev else 0
        return {"value": round(float(price), 2) if price else None, "change": chg}
    except Exception:
        return {"value": None, "change": 0}


def _market_status(region: str) -> str:
    """
    Determine whether a regional exchange is currently open, based on local time.

    Uses fixed trading-hour windows expressed as decimal hours in the primary
    timezone of each region. Weekend detection (Saturday/Sunday) is applied
    universally — regional holiday calendars are not modelled.

    Trading windows used
    --------------------
    - americas:     America/New_York, 09:30–16:00 ET
    - europe:       Europe/London, 08:00–16:30 GMT/BST
    - asia_pacific: Asia/Tokyo, 09:00–15:30 JST
    - mena:         Asia/Riyadh, 10:00–15:00 AST (Sun–Thu; Fri/Sat treated as weekend)

    Note: MENA exchanges trade Sunday–Thursday, so the Saturday/Sunday check
    produces a correct result for most MENA markets (Thursday and Friday are the
    actual weekend), but this approximation treats Friday as open and Sunday as
    closed, which is a known limitation.

    Args:
        region: One of ``"americas"``, ``"europe"``, ``"asia_pacific"``, ``"mena"``.

    Returns:
        ``"market_open"`` if the current local time falls within the trading
        window on a weekday, otherwise ``"market_closed"``.
    """
    import pytz
    from datetime import datetime as dt
    windows = {
        "americas":     ("America/New_York", 9.5,  16.0),
        "europe":       ("Europe/London",    8.0,  16.5),
        "asia_pacific": ("Asia/Tokyo",       9.0,  15.5),
        "mena":         ("Asia/Riyadh",     10.0,  15.0),
    }
    entry = windows.get(region)
    if not entry:
        return "market_closed"
    tz_name, open_h, close_h = entry
    now = dt.now(pytz.timezone(tz_name))
    if now.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        return "market_closed"
    h = now.hour + now.minute / 60  # fractional hour for range comparison
    return "market_open" if open_h <= h < close_h else "market_closed"
