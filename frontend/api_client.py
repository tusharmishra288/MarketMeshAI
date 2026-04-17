"""
MarketMesh AI — Centralised API client for the FastAPI backend.

All HTTP calls to the backend originate from this module.
Pages import individual fetch functions; no page should call ``requests``
directly, keeping network logic decoupled from UI rendering logic.

Each function returns the parsed JSON dict on success, or raises / returns
``None`` on failure — callers decide how to surface errors to the user.
"""

import os
import requests
from typing import Optional

BACKEND_URL: str = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
_DEFAULT_TIMEOUT: int = 20  # seconds


def _get(path: str, params: Optional[dict] = None, timeout: int = _DEFAULT_TIMEOUT) -> Optional[dict]:
    """
    Perform a GET request to the backend and return the parsed JSON body.

    Parameters
    ----------
    path : str
        URL path relative to BACKEND_URL (e.g. ``"/api/quote/AAPL"``).
    params : dict, optional
        Query-string parameters.
    timeout : int
        Request timeout in seconds.

    Returns
    -------
    dict or None
        Parsed JSON on HTTP 200; None on any error.
    """
    try:
        resp = requests.get(f"{BACKEND_URL}{path}", params=params, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        return None
    except requests.RequestException:
        return None


# ── Quote & fundamentals ──────────────────────────────────────────────────────

def fetch_quote(ticker: str, exchange: str) -> Optional[dict]:
    """Return real-time / EOD quote for *ticker* on *exchange*."""
    return _get(f"/api/quote/{ticker}", {"exchange": exchange})


def fetch_fundamentals(ticker: str, exchange: str) -> Optional[dict]:
    """Return company fundamentals (P/E, EPS, sector, description…)."""
    return _get(f"/api/fundamentals/{ticker}", {"exchange": exchange})


def fetch_news(ticker: str, exchange: str, company_name: str = "") -> Optional[dict]:
    """Return news articles and aggregate sentiment for *ticker*."""
    params = {"exchange": exchange}
    if company_name:
        params["company_name"] = company_name
    return _get(f"/api/news/{ticker}", params)


def fetch_global_snapshot() -> Optional[dict]:
    """Return live index snapshot for all 4 regions (used by Global Overview)."""
    return _get("/api/global-snapshot", timeout=60)


# ── Analytics ─────────────────────────────────────────────────────────────────

def fetch_history(ticker: str, exchange: str, period: str = "1y") -> Optional[dict]:
    """Return OHLCV price history for the requested period."""
    return _get(f"/api/history/{ticker}", {"exchange": exchange, "period": period})


def fetch_technicals(ticker: str, exchange: str, period: str = "1y") -> Optional[dict]:
    """Return technical indicator values (RSI, MACD, Bollinger Bands…)."""
    return _get(f"/api/technicals/{ticker}", {"exchange": exchange, "period": period})


def fetch_prediction(ticker: str, exchange: str) -> Optional[dict]:
    """Return XGBoost ML direction prediction with SHAP feature importance."""
    return _get(f"/api/predict/{ticker}", {"exchange": exchange}, timeout=30)


def fetch_anomalies(ticker: str, exchange: str) -> Optional[dict]:
    """Return IsolationForest anomaly events for the past year."""
    return _get(f"/api/anomalies/{ticker}", {"exchange": exchange})


def fetch_factors(ticker: str, exchange: str) -> Optional[dict]:
    """Return factor exposure scores (Value, Momentum, Quality, Low-Vol)."""
    return _get(f"/api/factors/{ticker}", {"exchange": exchange})


# ── Intelligence ──────────────────────────────────────────────────────────────

def fetch_correlation() -> Optional[dict]:
    """Return cross-market correlation matrix and regime classification."""
    return _get("/api/intelligence/correlation", timeout=30)


def fetch_sector_performance(period: str = "1mo") -> Optional[dict]:
    """Return US sector ETF performance for the requested period."""
    return _get("/api/sector-performance", {"period": period})


def fetch_peers(ticker: str, exchange: str) -> Optional[dict]:
    """Return sector peer companies with live quotes."""
    return _get(f"/api/peers/{ticker}", {"exchange": exchange})


# ── Macro ─────────────────────────────────────────────────────────────────────

def fetch_macro(indicator: str, refresh: bool = False) -> Optional[dict]:
    """Return a FRED macro indicator (yield_curve, inflation, fed_rate, gdp, indicators)."""
    params = {}
    if refresh:
        params["refresh"] = "true"
    return _get(f"/api/macro/{indicator}", params, timeout=30)


# ── AI ────────────────────────────────────────────────────────────────────────

def fetch_ai_summary(ticker: str, exchange: str, refresh: bool = False) -> Optional[dict]:
    """Return AI-generated company analysis (Groq/Gemini, cached 24h)."""
    params = {"exchange": exchange}
    if refresh:
        params["refresh"] = "true"
    return _get(f"/api/ai/company-summary/{ticker}", params, timeout=45)


def fetch_ai_description(ticker: str, exchange: str) -> Optional[dict]:
    """Return 2–3 sentence AI-generated company description (cached 7d)."""
    return _get(f"/api/ai/company-description/{ticker}", {"exchange": exchange}, timeout=12)


def fetch_macro_context(refresh: bool = False) -> Optional[dict]:
    """Return AI-generated macro narrative (Groq/Gemini, cached 4h)."""
    params = {}
    if refresh:
        params["refresh"] = "true"
    return _get("/api/ai/macro-context", params, timeout=60)


# ── Search & watchlist ────────────────────────────────────────────────────────

def search_companies(query: str, limit: int = 30) -> list:
    """Search for companies by name or ticker. Returns list of match dicts."""
    data = _get("/api/search", {"query": query, "limit": limit})
    return (data or {}).get("results", [])


def fetch_watchlist() -> list:
    """Return the current watchlist items [{ticker, exchange}, …]."""
    data = _get("/api/watchlist", timeout=5)
    return (data or {}).get("watchlist", [])


def add_to_watchlist(ticker: str, exchange: str) -> bool:
    """Add ticker/exchange to the watchlist. Returns True on success."""
    try:
        resp = requests.post(
            f"{BACKEND_URL}/api/watchlist",
            params={"ticker": ticker, "exchange": exchange},
            timeout=5,
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False


def remove_from_watchlist(ticker: str, exchange: str) -> bool:
    """Remove ticker/exchange from the watchlist. Returns True on success."""
    try:
        resp = requests.delete(
            f"{BACKEND_URL}/api/watchlist/{ticker}",
            params={"exchange": exchange},
            timeout=5,
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False


def fetch_health() -> Optional[dict]:
    """Return backend health status including MCP server states."""
    return _get("/health", timeout=5)
