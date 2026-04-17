"""
MarketMesh AI — Intelligence Routes.

This router provides cross-market analytical endpoints that go beyond single-
ticker data to examine relationships between indices, sectors, and peer stocks.

Endpoints
---------
- GET /api/intelligence/correlation: Pearson correlation matrix for 8 major
  global indices over the trailing 30 days, plus a market-regime label
  (Risk-On / Risk-Off / Rotation) based on the fraction of positive-returning
  indices.
- GET /api/sector-performance:       US sector ETF performance for a chosen
  period, delegated to the analytics MCP server.
- GET /api/peers/{ticker}:           Up to 5 sector-peer stocks for a given
  ticker, with live price/change/market-cap via yfinance.fast_info.

Dependencies
------------
- numpy:       Pearson correlation matrix via ``np.corrcoef``.
- yfinance:    Index return history (correlation endpoint) and peer quotes.
- mcp_client:  Sector performance and fundamentals MCP calls.
- cache_helpers: L1 cache, 3600 s TTL for all three endpoints.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import numpy as np
import yfinance as yf
from fastapi import APIRouter

from helpers.mcp_client    import mcp_call
from helpers.cache_helpers import _mem_get, _mem_set
from helpers.market_helpers import FUNDAMENTALS_TOOL, SECTOR_PEERS, _get_region

log    = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/intelligence/correlation")
async def market_correlation():
    """
    Compute and return a Pearson correlation matrix for 8 major global indices.

    Fetches 30 days of daily returns for NASDAQ, S&P 500, FTSE 100, DAX,
    Nikkei 225, Hang Seng, Nifty 50, and ASX 200 concurrently via a
    ``ThreadPoolExecutor`` (yfinance is blocking). Indices with fewer than
    10 data points are excluded from the matrix.

    Market regime is classified by the fraction of the 8 indices that had a
    positive cumulative 30-day return:
    - ``"Risk-On"``:  ≥ 75% positive.
    - ``"Risk-Off"``: ≤ 25% positive.
    - ``"Rotation"``: between 25% and 75%.

    Cache TTL: 3600 seconds (L1).

    Returns:
        JSON dict with keys: ``matrix`` (nested dict of correlation coefficients
        rounded to 3 d.p.), ``labels``, ``regime``, ``regime_description``,
        ``period_days`` (actual trading days used), ``computed_at``.
    """
    key = "correlation"
    if cached := _mem_get(key):
        return cached

    index_symbols = {
        "NASDAQ": "^IXIC", "S&P 500": "^GSPC",
        "FTSE 100": "^FTSE", "DAX": "^GDAXI",
        "Nikkei 225": "^N225", "Hang Seng": "^HSI",
        "Nifty 50": "^NSEI", "ASX 200": "^AXJO",
    }

    loop = asyncio.get_event_loop()

    def _get_returns(name_sym):
        name, sym = name_sym
        try:
            hist = yf.Ticker(sym).history(period="1mo", interval="1d", auto_adjust=True)
            if hist.empty or len(hist) < 10:
                return name, None
            ret = hist["Close"].pct_change().dropna().values.tolist()
            return name, ret
        except Exception:
            return name, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [loop.run_in_executor(pool, _get_returns, item) for item in index_symbols.items()]
        rets = await asyncio.gather(*futs)

    valid   = {name: r for name, r in rets if r and len(r) >= 10}
    min_len = min(len(v) for v in valid.values()) if valid else 0

    corr_matrix = {}
    if min_len >= 5:
        names = list(valid.keys())
        arr   = np.array([valid[n][-min_len:] for n in names])
        corr  = np.corrcoef(arr)
        for i, n1 in enumerate(names):
            corr_matrix[n1] = {n2: round(float(corr[i][j]), 3) for j, n2 in enumerate(names)}

    regime = "Unknown"
    ratio  = 0
    if valid:
        avg_30d_ret = {n: float(np.sum(r)) for n, r in valid.items()}
        positives   = sum(1 for v in avg_30d_ret.values() if v > 0)
        ratio       = positives / len(avg_30d_ret)
        regime      = "Risk-On" if ratio >= 0.75 else ("Risk-Off" if ratio <= 0.25 else "Rotation")

    result = {
        "matrix":             corr_matrix,
        "labels":             list(corr_matrix.keys()),
        "regime":             regime,
        "regime_description": f"{int(ratio * 100) if valid else 0}% of indices positive over 30 days",
        "period_days":        min_len,
        "computed_at":        datetime.now().isoformat(),
    }
    _mem_set(key, result, ttl_seconds=3600)
    return result


@router.get("/api/sector-performance")
async def sector_performance(period: str = "1mo"):
    """
    Return performance of all 11 US GICS sectors via SPDR sector ETFs.

    Delegates to the analytics MCP server (``get_sector_performance`` tool) which
    calculates start-to-end price return for each sector ETF (XLK, XLF, etc.)
    over the requested period.

    Cache TTL: 3600 seconds (L1).

    Args:
        period: yfinance period string — ``"1wk"``, ``"1mo"`` (default),
                ``"3mo"``, ``"6mo"``, ``"1y"``.

    Returns:
        JSON dict with keys: ``period``, ``sectors`` (dict mapping sector name
        to ``{"etf": str, "performance_pct": float, "latest_price": float}``),
        ``source``, ``computed_at``.

    Raises:
        HTTPException 503: Analytics MCP server unavailable.
    """
    key = f"sector_perf:{period}"
    if cached := _mem_get(key):
        return cached
    data = await mcp_call("analytics", "get_sector_performance", {"period": period})
    _mem_set(key, data, ttl_seconds=3600)
    return data


@router.get("/api/peers/{ticker}")
async def get_peers(ticker: str, exchange: str = "NASDAQ"):
    """
    Return a list of sector-peer stocks with live quote data for a given ticker.

    Determines the sector by fetching fundamentals from the appropriate MCP
    server. Falls back to ``"Technology"`` if the sector cannot be determined.
    Selects up to 5 peers from the ``SECTOR_PEERS`` curated list (excluding the
    ticker itself), then fetches price, change%, and market cap concurrently via
    ``yfinance.fast_info`` (non-blocking via asyncio.to_thread with 8 s timeout).

    For non-US exchanges, a ``note`` field is added explaining that peers shown
    are US-listed comparables rather than local exchange peers.

    Cache TTL: 3600 seconds (L1).

    Args:
        ticker:   Stock ticker symbol (case-insensitive).
        exchange: Exchange code — used both for the fundamentals MCP call and
                  to determine whether to add the non-US peer note.

    Returns:
        JSON dict with keys: ``ticker``, ``sector``, ``peers`` (list of dicts
        with ``ticker``, ``exchange``, ``price``, ``change_percent``,
        ``market_cap``), and optionally ``note``.
    """
    ticker = ticker.upper()
    key    = f"peers:{ticker}:{exchange}"
    if cached := _mem_get(key):
        return cached

    sector = "Technology"
    try:
        region = _get_region(exchange)
        fund   = await mcp_call(region, FUNDAMENTALS_TOOL[region],
                                {"ticker": ticker, "exchange": exchange})
        sector = (fund or {}).get("sector", "Technology") or "Technology"
    except Exception:
        pass

    peer_tickers = [t for t in SECTOR_PEERS.get(sector, SECTOR_PEERS["Technology"])
                    if t != ticker][:5]

    async def _peer_info(pt: str) -> dict:
        """Fetch price, change%, and market_cap for a peer via yfinance (has market_cap)."""
        def _sync():
            try:
                info  = yf.Ticker(pt).fast_info
                price = getattr(info, "last_price", None)
                mcap  = getattr(info, "market_cap", None)
                prev  = getattr(info, "previous_close", None)
                chg_pct = round((price - prev) / prev * 100, 2) if price and prev else None
                if price:
                    return {"price": round(float(price), 2),
                            "change_percent": chg_pct,
                            "market_cap": int(mcap) if mcap else None}
            except Exception:
                pass
            return None
        try:
            return await asyncio.wait_for(asyncio.to_thread(_sync), timeout=8.0)
        except Exception:
            return None

    peer_results = await asyncio.gather(*[_peer_info(pt) for pt in peer_tickers])
    peers = []
    for pt, q in zip(peer_tickers, peer_results):
        if q:
            peers.append({"ticker": pt, "exchange": "NASDAQ", **q})
        else:
            peers.append({"ticker": pt, "exchange": "NASDAQ",
                          "price": None, "change_percent": None, "market_cap": None})

    US_EXCHANGES = {"NASDAQ", "NYSE", "AMEX"}
    result = {"ticker": ticker, "sector": sector, "peers": peers}
    if exchange.upper() not in US_EXCHANGES:
        result["note"] = (
            f"Showing comparable US-listed companies (global {sector} sector leaders). "
            "Local exchange peer data is not yet available."
        )
    _mem_set(key, result, ttl_seconds=3600)
    return result
