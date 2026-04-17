"""
StockPilot AI — Enrichment (Alpha Vantage pipeline, factor scoring, sentiment).

This module runs after a raw fundamentals dict has been fetched from an MCP
server, supplementing it with additional data and derived scores.

Alpha Vantage enrichment pipeline
----------------------------------
``_enrich_with_alpha_vantage()`` calls the OVERVIEW endpoint for a given ticker
and back-fills any missing fields (PE, forward PE, ROE, profit margin, etc.)
into the existing fundamentals dict. Results are cached in L1 for 24 hours to
stay within Alpha Vantage's free-tier rate limit (5 calls/minute, 500/day).

Factor scoring algorithm
-------------------------
``_compute_factors()`` computes four quantitative factor scores on a 0–100 scale
using one year of daily OHLCV data from yfinance:

- Value (0–100):    ``100 - norm(PE, 5, 50)``
  A lower P/E relative to the 5–50 range earns a higher value score.
  Price-to-Book is used as a secondary confirmation (required to be > 0).
- Momentum (0–100): ``norm(ret_6m, -30%, +60%)`` if 126 trading days available,
  else ``norm(ret_1y, -40%, +80%)``.
  Captures the 6-month (or 12-month) price return normalised to the range.
- Quality (0–100):  ``avg(norm(ROE_pct, -10, 40), norm(margin_pct, -5, 30))``
  Arithmetic mean of normalised Return-on-Equity and net profit margin.
  Falls back to ROE alone when margin is unavailable.
- Low-Vol (0–100):  ``norm(100 - vol_6m_ann, 0, 70)``
  Annualised 6-month daily return volatility is inverted so low-volatility
  stocks receive a high score; normalised over the 0–70% volatility range.

All scores are guaranteed to be JSON-safe floats (no NaN, no inf) via
``_safe_float()``.

Dependencies
------------
- httpx:       Async HTTP client for Alpha Vantage OVERVIEW calls.
- yfinance:    Historical OHLCV data for factor computation.
- numpy:       Standard deviation and array arithmetic for factor scoring.
- cache_helpers: L1 cache for Alpha Vantage 24-hour results.
"""

import os
import logging

import httpx
import numpy as np
import yfinance as yf

from helpers.cache_helpers import _mem_get, _mem_set
from helpers.services      import rate_limiter

log = logging.getLogger(__name__)


async def _enrich_with_alpha_vantage(ticker: str, data: dict) -> dict:
    """
    Supplement a fundamentals dict with Alpha Vantage OVERVIEW data.

    Fetches the Alpha Vantage OVERVIEW endpoint for *ticker* and merges any
    fields that are missing or falsy in *data*. Fields already present in
    *data* from the MCP server are never overwritten. The raw AV response is
    cached in L1 for 24 hours (86400 s) to avoid burning the 500-calls/day
    free tier. Sets ``data["av_enriched"] = True`` when enrichment succeeds.

    Silently no-ops (returns *data* unchanged) when:
    - ``ALPHA_VANTAGE_KEY`` env var is not set.
    - AV returns a non-200 status or an empty/invalid JSON body.
    - Any network or timeout error occurs.

    Args:
        ticker: Uppercase stock ticker as used on its primary US listing
                (e.g. ``"AAPL"``, ``"TCS"``). AV OVERVIEW works best with
                US-listed symbols and US-listed ADR tickers.
        data:   Fundamentals dict to enrich in-place. Modified by reference.

    Returns:
        The same *data* dict, potentially enriched with additional fields.
    """
    av_key = os.getenv("ALPHA_VANTAGE_KEY", "")
    if not av_key:
        return data

    cache_key = f"av:{ticker}"
    if cached := _mem_get(cache_key):
        for k, v in cached.items():
            if v is not None and not data.get(k):
                data[k] = v
        data["av_enriched"] = True
        return data

    await rate_limiter.acquire("alpha_vantage")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://www.alphavantage.co/query",
                params={"function": "OVERVIEW", "symbol": ticker, "apikey": av_key},
            )
        if r.status_code != 200:
            return data
        av = r.json()
        if not av.get("Symbol"):
            return data

        def _f(val):
            try:
                v = float(val)
                return v if v != 0 else None
            except (TypeError, ValueError):
                return None

        enrichments = {
            "description":    av.get("Description") or None,
            "sector":         av.get("Sector") or None,
            "industry":       av.get("Industry") or None,
            "pe_ratio":       _f(av.get("PERatio")),
            "forward_pe":     _f(av.get("ForwardPE")),
            "peg_ratio":      _f(av.get("PEGRatio")),
            "eps":            _f(av.get("EPS")),
            "dividend_yield": _f(av.get("DividendYield")),
            "52_week_high":   _f(av.get("52WeekHigh")),
            "52_week_low":    _f(av.get("52WeekLow")),
            "beta":           _f(av.get("Beta")),
            "profit_margin":  _f(av.get("ProfitMargin")),
            "roe":            _f(av.get("ReturnOnEquityTTM")),
            "price_to_book":  _f(av.get("PriceToBookRatio")),
            "market_cap":     _f(av.get("MarketCapitalization")),
        }
        _mem_set(cache_key, enrichments, ttl_seconds=86400)
        for key, val in enrichments.items():
            if val is not None and not data.get(key):
                data[key] = val
        data["av_enriched"] = True
        log.info("[AV] enriched %s", ticker)
    except Exception as e:
        log.warning("[AV] enrichment skipped for %s: %s", ticker, e)
    return data


async def _sentiment_aggregate(articles: list) -> dict:
    """Aggregate per-article sentiment into a single signal."""
    scores = [a.get("sentiment") for a in articles if a.get("sentiment") is not None]
    if not scores:
        return {"score": None, "label": "Unknown",
                "bull_articles": 0, "bear_articles": 0, "neutral_articles": 0}
    avg   = round(sum(scores) / len(scores), 3)
    bulls = sum(1 for s in scores if s >  0.15)
    bears = sum(1 for s in scores if s < -0.15)
    neuts = len(scores) - bulls - bears
    label = "Positive" if avg > 0.1 else ("Negative" if avg < -0.1 else "Neutral")
    return {"score": avg, "label": label,
            "bull_articles": bulls, "bear_articles": bears, "neutral_articles": neuts}


_YF_EXCHANGE_SUFFIX = {
    "LSE": ".L",   "XETRA": ".DE", "EPA": ".PA",  "AMS": ".AS",
    "SWX": ".SW",  "BIT": ".MI",   "MCE": ".MC",  "OSL": ".OL",  "HEL": ".HE",
    "TSE": ".T",   "HKEX": ".HK",  "SSE": ".SS",  "SZSE": ".SZ",
    "NSE": ".NS",  "BSE": ".BO",   "ASX": ".AX",  "SGX": ".SI",
    "KRX": ".KS",  "TWSE": ".TW",  "TADAWUL": ".SR",
    "DFM": ".DU",  "ADX": ".AD",   "TASE": ".TA", "EGX": ".CA",  "DSM": ".QA",
    "TSX": ".TO",  "B3": ".SA",    "BMV": ".MX",
}


def _safe_float(val) -> float | None:
    """
    Convert *val* to a JSON-safe float, returning ``None`` for problematic values.

    JSON does not support ``NaN`` or ``±Infinity`` as number literals. Pandas
    and numpy operations frequently produce these (e.g. 0/0, log of negative
    number, rolling std with all-zero window). Passing them to
    ``json.dumps()`` raises ``ValueError`` or silently writes the string
    ``"NaN"`` depending on the serialiser. This helper ensures every float
    that enters a route response is serialisable.

    Args:
        val: Any value — int, float, str, numpy scalar, or None.

    Returns:
        Python ``float`` if *val* is a finite number, otherwise ``None``.
    """
    if val is None:
        return None
    try:
        import math
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


async def _compute_factors(ticker: str, exchange: str, fundamentals: dict) -> dict:
    """
    Compute the four quantitative factor scores (0–100 scale) for a stock.

    Uses one year of daily closing prices from yfinance plus fundamental ratios
    already present in *fundamentals* (populated by the MCP server and/or AV
    enrichment). Falls back to ``yfinance.info`` for PE/PB/ROE/margin when
    Alpha Vantage has not enriched the data.

    Factor formulas
    ---------------
    - Value:    ``100 - norm(PE, lo=5, hi=50)`` — lower PE → higher score.
      Requires both ``pe_ratio > 0`` and ``price_to_book`` to be non-None.
    - Momentum: ``norm(ret_6m, lo=-30, hi=60)`` (preferred, needs ≥126 trading days)
      or ``norm(ret_1y, lo=-40, hi=80)`` (fallback for shorter histories).
    - Quality:  ``mean(norm(ROE_pct, -10, 40), norm(margin_pct, -5, 30))``
      ROE and margin are scaled to percentage form if they arrive as decimals
      (|value| ≤ 1 is assumed to be a decimal fraction and multiplied by 100).
    - Low-Vol:  ``norm(100 - vol_6m_ann, lo=0, hi=70)`` — lower annualised
      volatility → higher score. vol_6m_ann is annualised via ``σ × √252``.

    All scores are in [0, 100] and guaranteed JSON-safe (``_safe_float`` used
    throughout). Returns an empty dict on any unrecoverable error.

    Uses exchange suffix for non-US tickers so yfinance fetches the right security.
    Falls back to yfinance.info for pe/pb/roe/margin when AV is rate-limited.
    All returned floats are guaranteed JSON-safe (no NaN/inf).

    Args:
        ticker:       Uppercase ticker symbol (e.g. ``"RELIANCE"``).
        exchange:     Exchange code (e.g. ``"NSE"``). Used to look up the
                      yfinance suffix so the correct security is fetched.
        fundamentals: Dict of fundamental data (output of MCP + AV enrichment).

    Returns:
        Dict with keys: ``value``, ``momentum``, ``quality``, ``low_vol``
        (each a float 0–100 or None), plus ``ret_6m_pct`` and
        ``vol_6m_ann_pct`` as diagnostic fields. Empty dict on failure.
    """
    try:
        # Build correct yfinance symbol (e.g. RELIANCE → RELIANCE.NS for NSE)
        suffix = _YF_EXCHANGE_SUFFIX.get(exchange.upper(), "")
        yf_sym = ticker + suffix if suffix else ticker

        hist = yf.Ticker(yf_sym).history(period="1y", interval="1d", auto_adjust=True)
        if hist.empty or len(hist) < 20:
            return {}

        close  = hist["Close"].dropna()
        if len(close) < 20:
            return {}

        # Compute returns and volatility — sanitize with _safe_float to avoid NaN in JSON
        ret_6m = _safe_float(
            (close.iloc[-1] / close.iloc[max(0, len(close) - 126)] - 1) * 100
        ) if len(close) >= 126 else None
        ret_1y = _safe_float((close.iloc[-1] / close.iloc[0] - 1) * 100)
        vol_6m = _safe_float(
            close.pct_change(fill_method=None).tail(126).std() * (252 ** 0.5) * 100
        ) if len(close) >= 126 else None

        def _norm(val, lo, hi):
            if val is None:
                return None
            try:
                import math
                f = float(val)
                if math.isnan(f) or math.isinf(f):
                    return None
                return round(max(0.0, min(100.0, (f - lo) / (hi - lo) * 100)), 1)
            except Exception:
                return None

        pe     = _safe_float(fundamentals.get("pe_ratio"))
        pb     = _safe_float(fundamentals.get("price_to_book"))
        roe    = _safe_float(fundamentals.get("roe"))
        margin = _safe_float(fundamentals.get("profit_margin"))

        # Fallback: fetch missing ratios from yfinance.info when AV is unavailable
        if any(v is None for v in [pe, pb, roe, margin]):
            try:
                info = yf.Ticker(yf_sym).info
                pe     = pe     or _safe_float(info.get("trailingPE")   or info.get("forwardPE"))
                pb     = pb     or _safe_float(info.get("priceToBook"))
                roe    = roe    or _safe_float(info.get("returnOnEquity"))
                margin = margin or _safe_float(info.get("profitMargins"))
            except Exception:
                pass

        value_score = None
        if pe and pb and pe > 0:
            raw_value = 100.0 - (_norm(pe, 5, 50) or 0)
            value_score = _safe_float(raw_value)

        mom_score = _norm(ret_6m, -30, 60) if ret_6m is not None else _norm(ret_1y, -40, 80)

        quality_score = None
        if roe is not None and margin is not None:
            roe_pct    = roe    * 100 if abs(roe)    <= 1 else roe
            margin_pct = margin * 100 if abs(margin) <= 1 else margin
            q1 = _norm(roe_pct, -10, 40)
            q2 = _norm(margin_pct, -5, 30)
            if q1 is not None and q2 is not None:
                quality_score = _safe_float((q1 + q2) / 2)
            elif q1 is not None:
                quality_score = q1
        elif roe is not None:
            roe_pct       = roe * 100 if abs(roe) <= 1 else roe
            quality_score = _norm(roe_pct, -10, 40)

        lowvol_score = _norm(100 - (vol_6m or 30), 0, 70) if vol_6m is not None else None

        return {
            "value":          value_score,
            "momentum":       mom_score,
            "quality":        quality_score,
            "low_vol":        lowvol_score,
            "ret_6m_pct":     round(ret_6m, 2) if ret_6m is not None else None,
            "vol_6m_ann_pct": round(vol_6m, 2) if vol_6m is not None else None,
        }
    except Exception as e:
        log.warning("Factor computation failed for %s/%s: %s", ticker, exchange, e)
        return {}
