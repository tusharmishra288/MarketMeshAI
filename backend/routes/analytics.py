"""
MarketMesh AI — Analytics Routes.

This router exposes quantitative analytics endpoints that delegate computation
to the analytics MCP server (``mcp_servers/analytics/server.py``). All
endpoints support global tickers via the ``exchange`` query parameter; the
analytics MCP server applies the correct yfinance exchange suffix automatically.

Endpoints
---------
- GET /api/history/{ticker}:    OHLCV candle data for charting (cached 1 h).
- GET /api/technicals/{ticker}: RSI, MACD, Bollinger Bands, SMA/EMA, patterns
                                (cached 5 min — more volatile than history).
- GET /api/predict/{ticker}:    XGBoost next-day price direction with confidence
                                score and backtest accuracy (cached 1 h).
- GET /api/anomalies/{ticker}:  IsolationForest-detected unusual price/volume
                                events over the trailing year (cached 30 min).
- GET /api/factors/{ticker}:    Four factor scores (Value, Momentum, Quality,
                                Low-Vol) derived from fundamentals + price history
                                (cached 24 h; slow due to yfinance history fetch).

Dependencies
------------
- mcp_client:    Dispatches calls to the analytics MCP server.
- cache_helpers: L1 in-memory cache with per-endpoint TTLs.
- enrichment:    Alpha Vantage enrichment (used by factors endpoint to populate
                 PE, ROE, and margin before factor computation).
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

from helpers.mcp_client    import mcp_call
from helpers.cache_helpers import _mem_get, _mem_set
from helpers.market_helpers import FUNDAMENTALS_TOOL, _get_region
from helpers.enrichment     import _compute_factors, _enrich_with_alpha_vantage

log    = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/history/{ticker}")
async def get_history(ticker: str, exchange: str = "NASDAQ",
                      period: str = "1y", interval: str = "1d"):
    """
    Return OHLCV candle data for a stock, suitable for frontend charting.

    Cache TTL: 3600 seconds (L1). Cache key includes period and interval so
    different time ranges are cached independently.

    Args:
        ticker:   Stock ticker symbol (case-insensitive).
        exchange: Exchange code (default ``"NASDAQ"``). The analytics MCP server
                  applies the correct yfinance suffix for non-US exchanges.
        period:   yfinance period string, e.g. ``"1y"``, ``"6mo"``, ``"5y"``.
        interval: yfinance interval string, e.g. ``"1d"``, ``"1wk"``, ``"1mo"``.

    Returns:
        JSON dict with keys: ``ticker``, ``company_name``, ``exchange``,
        ``period``, ``interval``, ``data_points``, ``candles`` (list of OHLCV
        dicts), ``source``.

    Raises:
        HTTPException 503: Analytics MCP server unavailable.
        HTTPException 404: No historical data found for the ticker.
    """
    ticker = ticker.upper()
    key    = f"history:{ticker}:{exchange}:{period}:{interval}"
    if cached := _mem_get(key):
        return cached
    data = await mcp_call("analytics", "get_price_history",
                           {"ticker": ticker, "exchange": exchange,
                            "period": period, "interval": interval})
    _mem_set(key, data, ttl_seconds=3600)
    return data


@router.get("/api/technicals/{ticker}")
async def get_technicals(ticker: str, exchange: str = "NASDAQ", period: str = "1y"):
    """
    Compute and return technical indicators for a stock.

    Delegates to the analytics MCP server which computes RSI-14, MACD (12/26/9),
    Bollinger Bands (20-period), SMA/EMA (20, 50, 200), volume Z-score, 6-month
    momentum, and detects candlestick/MA-crossover patterns.

    Cache TTL: 300 seconds (L1) — shorter than history because the pattern list
    and RSI can change intraday.

    Args:
        ticker:   Stock ticker symbol (case-insensitive).
        exchange: Exchange code.
        period:   Lookback period for the underlying price data, e.g. ``"1y"``.
                  Must be long enough for the 200-day SMA (at least 14 months
                  of daily data). Falls back gracefully on insufficient data.

    Returns:
        JSON dict with indicator values, or an error dict with
        ``"error": "Insufficient data for this period"`` if the ticker has
        fewer than 30 trading days in the requested period.

    Raises:
        No HTTP exceptions raised — ``HTTPException`` from the MCP call is
        caught and converted to a soft error dict so the frontend can display
        a partial view.
    """
    ticker = ticker.upper()
    key    = f"technicals:{ticker}:{exchange}:{period}"
    if cached := _mem_get(key):
        return cached
    try:
        data = await mcp_call("analytics", "compute_technical_indicators",
                               {"ticker": ticker, "exchange": exchange, "period": period})
    except HTTPException:
        data = {"error": "Insufficient data for this period", "ticker": ticker, "exchange": exchange}
    _mem_set(key, data, ttl_seconds=300)
    return data


@router.get("/api/predict/{ticker}")
async def predict(ticker: str, exchange: str = "NASDAQ", horizon: int = 1):
    """
    Predict the price direction over the next N days using XGBoost.

    Delegates to the analytics MCP server which trains an XGBoost classifier on
    5 years of daily price history, using 15 technical features (RSI, MACD,
    Bollinger Band position, moving-average ratios, volume Z-score, momentum).
    Backtest accuracy is estimated via 5-fold time-series cross-validation.

    Cache TTL: 3600 seconds (L1) — model training is expensive (~2-5 s), so
    results are cached for 1 hour per ticker/exchange/horizon combination.

    Args:
        ticker:   Stock ticker symbol (case-insensitive).
        exchange: Exchange code.
        horizon:  Prediction horizon in trading days (default 1 = next day).

    Returns:
        JSON dict with keys: ``direction`` (``"up"``/``"down"``), ``confidence``
        (float 0.5–1.0), ``backtest_accuracy`` (float), ``top_features`` (list),
        ``training_samples`` (int), ``disclaimer``, ``computed_at``.

    Raises:
        HTTPException 503: Analytics MCP server unavailable.
        HTTPException 404: Insufficient history for model training.
    """
    ticker = ticker.upper()
    key    = f"predict:{ticker}:{exchange}:{horizon}"
    if cached := _mem_get(key):
        return cached
    data = await mcp_call("analytics", "predict_price_direction",
                           {"ticker": ticker, "exchange": exchange, "horizon_days": horizon})
    _mem_set(key, data, ttl_seconds=3600)
    return data


@router.get("/api/anomalies/{ticker}")
async def get_anomalies(ticker: str, exchange: str = "NASDAQ"):
    """
    Detect unusual price and volume events using IsolationForest.

    Delegates to the analytics MCP server which runs sklearn's IsolationForest
    with contamination=0.05 on three features: daily return, volume Z-score
    (30-day rolling), and price gap magnitude. The 10 most recent anomalies
    are returned, classified as ``"volume_spike"``, ``"price_gap"``, or
    ``"unusual_activity"`` with ``"high"``/``"medium"`` severity.

    Cache TTL: 1800 seconds (L1 — 30 min).

    Args:
        ticker:   Stock ticker symbol (case-insensitive).
        exchange: Exchange code.

    Returns:
        JSON dict with keys: ``ticker``, ``exchange``, ``anomalies`` (list of
        dicts with ``date``, ``type``, ``severity``, ``return_pct``,
        ``volume_zscore``, ``description``), ``analyzed_days``, ``computed_at``.

    Raises:
        HTTPException 503: Analytics MCP server unavailable.
        HTTPException 404: Insufficient data for anomaly detection.
    """
    ticker = ticker.upper()
    key    = f"anomalies:{ticker}:{exchange}"
    if cached := _mem_get(key):
        return cached
    data = await mcp_call("analytics", "detect_anomalies",
                           {"ticker": ticker, "exchange": exchange})
    _mem_set(key, data, ttl_seconds=1800)
    return data


@router.get("/api/factors/{ticker}")
async def get_factors(ticker: str, exchange: str = "NASDAQ"):
    """
    Compute the four quantitative factor scores (Value, Momentum, Quality, Low-Vol).

    Pipeline:
      1. Fetch fundamentals from the appropriate regional MCP server.
      2. Enrich with Alpha Vantage OVERVIEW to fill PE, ROE, and margin ratios.
      3. Call ``_compute_factors()`` which fetches 1 year of yfinance history
         and derives all four scores on a 0–100 scale.

    Cache TTL: 86400 seconds (L1 — 24 h) because fundamentals and one-year
    factor scores change at most once a trading day.

    Args:
        ticker:   Stock ticker symbol (case-insensitive).
        exchange: Exchange code. Used to route the fundamentals MCP call and
                  to determine the yfinance suffix for price history.

    Returns:
        JSON dict with keys: ``ticker``, ``exchange``, ``factors`` (dict
        with ``value``, ``momentum``, ``quality``, ``low_vol``, ``ret_6m_pct``,
        ``vol_6m_ann_pct``), ``computed_at``. On error, ``factors`` is ``{}``
        and an ``error`` key is present.

    Raises:
        No HTTP exceptions raised — errors are caught and returned as a soft
        error dict so the page continues to render.
    """
    ticker = ticker.upper()
    key    = f"factors:{ticker}:{exchange}"
    if cached := _mem_get(key):
        return cached
    try:
        region       = _get_region(exchange)
        fundamentals = await mcp_call(region, FUNDAMENTALS_TOOL[region],
                                       {"ticker": ticker, "exchange": exchange})
        # Enrich with Alpha Vantage so pe_ratio, pb, roe, margin are populated
        fundamentals = await _enrich_with_alpha_vantage(ticker, fundamentals)
        factors      = await _compute_factors(ticker, exchange, fundamentals)
        result       = {"ticker": ticker, "exchange": exchange, "factors": factors,
                        "computed_at": datetime.now().isoformat()}
        _mem_set(key, result, ttl_seconds=86400)
        return result
    except Exception as e:
        log.warning("Factors failed for %s/%s: %s", ticker, exchange, e)
        return {"ticker": ticker, "exchange": exchange, "factors": {},
                "error": str(e), "computed_at": datetime.now().isoformat()}
