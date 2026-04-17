"""
StockPilot AI — Analytics MCP Server.

This MCP server provides all quantitative analytics for the application. Unlike
the regional servers (which focus on quotes and fundamentals), this server
performs computationally intensive tasks: computing technical indicators,
training ML models for price direction prediction, and detecting statistical
anomalies. It is region-agnostic — it applies the correct yfinance exchange
suffix to any globally-listed ticker.

Primary data source: yfinance — all OHLCV data via ``_fetch_ohlcv()``.

XGBoost prediction approach
----------------------------
``predict_price_direction`` trains an XGBoost binary classifier on 5 years of
daily price history. Feature engineering (``_build_features``) produces 15
technical features: RSI-14, MACD (12/26/9) line/signal/histogram, Bollinger
Band width and position, SMA/EMA ratios (20/50/200), volume Z-score, ATR, and
daily/5d/20d/6m return. The target label is 1 if the closing price N days later
is higher than the current close. Walk-forward 5-fold TimeSeriesSplit is used
for honest backtest accuracy estimation. A final model is trained on the full
dataset for the live prediction.

IsolationForest anomaly detection
-----------------------------------
``detect_anomalies`` uses sklearn's IsolationForest with contamination=0.05
(flags approximately the 5% most unusual days) on three features: daily return,
volume Z-score (30-day rolling window), and price gap magnitude. Anomalies are
classified by type (``"volume_spike"`` if |vol_zscore| > 3, ``"price_gap"`` if
|return| > 5%, else ``"unusual_activity"``) and severity (``"high"`` if
|return| > 8% or |vol_zscore| > 5, else ``"medium"``).

Tools exposed
-------------
- get_price_history:           Full OHLCV candle array for any global ticker.
- compute_technical_indicators: RSI, MACD, Bollinger Bands, SMA/EMA, patterns.
- predict_price_direction:      XGBoost next-day (or N-day) direction + confidence.
- detect_anomalies:             IsolationForest unusual price/volume events.
- get_sector_performance:       US GICS sector ETF performance for a period.

Dependencies
------------
- yfinance:     All OHLCV data.
- numpy/pandas: Feature engineering and indicator computation.
- xgboost:      ML price direction prediction (optional — returns error if missing).
- scikit-learn: IsolationForest, StandardScaler, TimeSeriesSplit (optional).
- mcp:          MCP Python SDK.
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List

import numpy as np
import pandas as pd
import yfinance as yf

from mcp.server import Server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [analytics] %(message)s")
log = logging.getLogger(__name__)

server = Server("analytics")

# Exchange suffix map (union of all regional servers)
EXCHANGE_SUFFIXES = {
    "LSE": ".L",  "XETRA": ".DE", "EPA": ".PA", "AMS": ".AS",
    "SWX": ".SW", "BIT": ".MI",   "MCE": ".MC", "OSL": ".OL", "HEL": ".HE",
    "TSE": ".T",  "HKEX": ".HK",  "SSE": ".SS", "SZSE": ".SZ",
    "NSE": ".NS", "BSE": ".BO",   "ASX": ".AX", "SGX": ".SI",
    "KRX": ".KS", "TWSE": ".TW",
    "TADAWUL": ".SR", "DFM": ".DU", "ADX": ".AD", "TASE": ".TA",
    "EGX": ".CA", "DSM": ".QA",
}

def _symbol(ticker: str, exchange: str) -> str:
    suffix = EXCHANGE_SUFFIXES.get(exchange.upper(), "")
    if suffix and not ticker.endswith(suffix):
        return f"{ticker}{suffix}"
    return ticker


def _safe_float(v) -> float | None:
    try:
        f = float(v)
        return None if (np.isnan(f) or np.isinf(f)) else f
    except Exception:
        return None


# ── Tool registration ─────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_price_history",
            description="Get OHLCV price history for any global ticker. Returns JSON with candles array.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":   {"type": "string"},
                    "exchange": {"type": "string", "default": "NASDAQ"},
                    "period":   {"type": "string", "default": "1y",
                                 "enum": ["1wk","1mo","3mo","6mo","1y","2y","5y"]},
                    "interval": {"type": "string", "default": "1d",
                                 "enum": ["1d","1wk","1mo"]},
                },
                "required": ["ticker"],
            },
        ),
        Tool(
            name="compute_technical_indicators",
            description="Compute RSI, MACD, Bollinger Bands, SMA/EMA for a ticker. Returns JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":   {"type": "string"},
                    "exchange": {"type": "string", "default": "NASDAQ"},
                    "period":   {"type": "string", "default": "1y"},
                },
                "required": ["ticker"],
            },
        ),
        Tool(
            name="predict_price_direction",
            description=(
                "Predict next-day price direction using XGBoost on technical features. "
                "Returns direction (up/down), confidence, backtest_accuracy, and top features. "
                "NOT financial advice."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":        {"type": "string"},
                    "exchange":      {"type": "string", "default": "NASDAQ"},
                    "horizon_days":  {"type": "integer", "default": 1},
                },
                "required": ["ticker"],
            },
        ),
        Tool(
            name="detect_anomalies",
            description="Detect unusual price and volume activity using IsolationForest. Returns JSON list of anomalies.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker":        {"type": "string"},
                    "exchange":      {"type": "string", "default": "NASDAQ"},
                    "lookback_days": {"type": "integer", "default": 252},
                },
                "required": ["ticker"],
            },
        ),
        Tool(
            name="get_sector_performance",
            description="Get US sector ETF performance for a given period. Returns JSON.",
            inputSchema={
                "type": "object",
                "properties": {
                    "period": {"type": "string", "default": "1mo",
                               "enum": ["1wk","1mo","3mo","6mo","1y"]},
                },
            },
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
        "get_price_history":           get_price_history,
        "compute_technical_indicators": compute_technical_indicators,
        "predict_price_direction":      predict_price_direction,
        "detect_anomalies":             detect_anomalies,
        "get_sector_performance":       get_sector_performance,
    }
    handler = handlers.get(name)
    if not handler:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]
    return await handler(**arguments)


# ── Helper: fetch OHLCV ────────────────────────────────────────────────────────

def _fetch_ohlcv(ticker: str, exchange: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """
    Fetch OHLCV DataFrame for any globally-listed ticker using yfinance.

    Applies the exchange suffix from ``EXCHANGE_SUFFIXES`` so yfinance fetches
    from the correct exchange. Falls back to the bare ticker if the suffixed
    fetch fails or returns empty (handles cases where yfinance indexes US-listed
    ADRs without a suffix even when exchange is non-US).

    Args:
        ticker:   Stock ticker symbol without suffix.
        exchange: Exchange code (e.g. ``"NSE"``, ``"NASDAQ"``).
        period:   yfinance period string.
        interval: yfinance interval string.

    Returns:
        pandas DataFrame with columns ``Open``, ``High``, ``Low``, ``Close``,
        ``Volume``. May be empty if yfinance returns no data.
    """
    symbol = _symbol(ticker, exchange)
    hist = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
    if hist.empty and exchange.upper() not in ("NASDAQ", "NYSE", "AMEX"):
        # Try plain ticker as fallback
        hist = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
    return hist


# ── Technical indicator helpers ────────────────────────────────────────────────

def _rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """
    Compute the Relative Strength Index (RSI) using Wilder's smoothing method.

    Uses a rolling mean of gains and losses (``clip``-based gain/loss split)
    rather than true Wilder's EMA, which is a common and fast approximation.
    Returns NaN for the first ``window`` rows where there is insufficient data.

    Args:
        series: Close-price series (pandas Series with DatetimeIndex).
        window: Lookback period in bars (default 14).

    Returns:
        pandas Series of RSI values in [0, 100].
    """
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(window).mean()
    loss  = (-delta.clip(upper=0)).rolling(window).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series):
    """
    Compute MACD line, signal line, and histogram using standard parameters.

    Standard parameters: fast EMA 12, slow EMA 26, signal EMA 9.
    All three EMAs use ``adjust=False`` (recursive EMA, not corrected for bias).

    Args:
        series: Close-price series.

    Returns:
        Tuple of three pandas Series: ``(macd, signal, histogram)``.
    """
    ema12   = series.ewm(span=12, adjust=False).mean()
    ema26   = series.ewm(span=26, adjust=False).mean()
    macd    = ema12 - ema26
    signal  = macd.ewm(span=9, adjust=False).mean()
    hist    = macd - signal
    return macd, signal, hist


def _bollinger(series: pd.Series, window: int = 20):
    """
    Compute Bollinger Bands: upper (SMA + 2σ), middle (SMA), lower (SMA − 2σ).

    Args:
        series: Close-price series.
        window: Rolling window for both the SMA and standard deviation (default 20).

    Returns:
        Tuple of three pandas Series: ``(upper_band, middle_band, lower_band)``.
    """
    sma  = series.rolling(window).mean()
    std  = series.rolling(window).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    return upper, sma, lower


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build ML feature set from OHLCV data."""
    close = df["Close"]
    volume = df["Volume"]

    df = df.copy()
    df["rsi14"]       = _rsi(close, 14)
    macd, sig, hist   = _macd(close)
    df["macd"]        = macd
    df["macd_signal"] = sig
    df["macd_hist"]   = hist

    upper, mid, lower = _bollinger(close, 20)
    df["bb_width"]    = (upper - lower) / mid.replace(0, np.nan)
    df["bb_pos"]      = (close - lower) / (upper - lower).replace(0, np.nan)

    df["sma20"]       = close.rolling(20).mean()
    df["sma50"]       = close.rolling(50).mean()
    df["sma200"]      = close.rolling(200).mean()
    df["ema20"]       = close.ewm(span=20, adjust=False).mean()

    df["ma20_ratio"]  = close / df["sma20"].replace(0, np.nan)
    df["ma50_ratio"]  = close / df["sma50"].replace(0, np.nan)
    df["ma200_ratio"] = close / df["sma200"].replace(0, np.nan)

    df["vol_sma20"]   = volume.rolling(20).mean()
    df["vol_zscore"]  = (volume - df["vol_sma20"]) / volume.rolling(20).std().replace(0, np.nan)

    df["atr"]         = (df["High"] - df["Low"]).rolling(14).mean()
    df["ret1d"]       = close.pct_change(1)
    df["ret5d"]       = close.pct_change(5)
    df["ret20d"]      = close.pct_change(20)
    df["mom6m"]       = close.pct_change(126)

    return df


# ── Handlers ──────────────────────────────────────────────────────────────────

async def get_price_history(ticker: str, exchange: str = "NASDAQ",
                            period: str = "1y", interval: str = "1d") -> List[TextContent]:
    """
    Fetch the full OHLCV candle array for any globally-listed stock.

    Applies the correct exchange suffix, then fetches history. Also performs a
    best-effort company name lookup (non-blocking, skipped on error) so the
    frontend can display the company name without a separate fundamentals call.
    All price values are passed through ``_safe_float`` to ensure JSON safety.

    Args:
        ticker:   Stock ticker symbol without suffix.
        exchange: Exchange code (used for suffix lookup).
        period:   yfinance period string (``"1wk"``–``"5y"``).
        interval: yfinance interval string (``"1d"``, ``"1wk"``, ``"1mo"``).

    Returns:
        List with a single TextContent containing: ``ticker``, ``company_name``,
        ``exchange``, ``period``, ``interval``, ``data_points``, ``candles``
        (list of ``{date, open, high, low, close, volume}``), ``source``.
        Returns ``{"error": str}`` if history is empty.
    """
    try:
        hist = _fetch_ohlcv(ticker, exchange, period, interval)
        if hist.empty:
            return [TextContent(type="text", text=json.dumps({"error": f"No history for {ticker}"}))]

        candles = []
        for idx, row in hist.iterrows():
            candles.append({
                "date":   str(idx.date()),
                "open":   _safe_float(row["Open"]),
                "high":   _safe_float(row["High"]),
                "low":    _safe_float(row["Low"]),
                "close":  _safe_float(row["Close"]),
                "volume": int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
            })

        # Fetch company name (best-effort, non-blocking)
        company_name = ticker
        try:
            info = yf.Ticker(_symbol(ticker, exchange)).info
            company_name = info.get("longName") or info.get("shortName") or ticker
        except Exception:
            pass

        result = {
            "ticker":       ticker,
            "company_name": company_name,
            "exchange":     exchange,
            "period":       period,
            "interval":     interval,
            "data_points":  len(candles),
            "candles":      candles,
            "source":       "yfinance",
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        log.error("get_price_history error: %s", e)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def compute_technical_indicators(ticker: str, exchange: str = "NASDAQ",
                                       period: str = "1y") -> List[TextContent]:
    """
    Compute a comprehensive set of technical indicators for a stock.

    Requires at least 30 trading days of data. Builds all features via
    ``_build_features``, then extracts the latest row's values. Also detects
    four chart patterns from the last two bars: golden cross (SMA20 crossing
    above SMA50), death cross (SMA20 crossing below SMA50), overbought RSI
    (RSI > 70), and oversold RSI (RSI < 30).

    Args:
        ticker:   Stock ticker symbol without suffix.
        exchange: Exchange code.
        period:   Lookback period (default ``"1y"``; should be at least 14 months
                  to populate SMA200 without NaN).

    Returns:
        List with a single TextContent containing all indicator values at the
        latest date: ``rsi14``, ``macd``, ``macd_signal``, ``macd_hist``,
        ``bb_upper``/``bb_middle``/``bb_lower``/``bb_width``, ``sma20``,
        ``sma50``, ``sma200``, ``ema20``, ``volume_zscore``, ``momentum_6m``,
        ``patterns`` (list of strings), ``computed_at``, ``source``.
        Returns ``{"error": str}`` if fewer than 30 bars are available.
    """
    try:
        hist = _fetch_ohlcv(ticker, exchange, period)
        if hist.empty or len(hist) < 30:
            return [TextContent(type="text", text=json.dumps({"error": f"Insufficient data for {ticker}"}))]

        df   = _build_features(hist)
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last

        close = hist["Close"].iloc[-1]
        upper_bb, mid_bb, lower_bb = _bollinger(hist["Close"], 20)

        # Pattern detection
        patterns = []
        if (df["sma20"].iloc[-2] < df["sma50"].iloc[-2] and
                df["sma20"].iloc[-1] >= df["sma50"].iloc[-1]):
            patterns.append("golden_cross_20_50")
        if (df["sma20"].iloc[-2] > df["sma50"].iloc[-2] and
                df["sma20"].iloc[-1] <= df["sma50"].iloc[-1]):
            patterns.append("death_cross_20_50")
        rsi_val = _safe_float(last["rsi14"])
        if rsi_val and rsi_val > 70:
            patterns.append("overbought_rsi")
        if rsi_val and rsi_val < 30:
            patterns.append("oversold_rsi")

        result = {
            "ticker":        ticker,
            "exchange":      exchange,
            "computed_at":   datetime.now().isoformat(),
            "rsi14":         _safe_float(last["rsi14"]),
            "macd":          _safe_float(last["macd"]),
            "macd_signal":   _safe_float(last["macd_signal"]),
            "macd_hist":     _safe_float(last["macd_hist"]),
            "bb_upper":      _safe_float(upper_bb.iloc[-1]),
            "bb_middle":     _safe_float(mid_bb.iloc[-1]),
            "bb_lower":      _safe_float(lower_bb.iloc[-1]),
            "bb_width":      _safe_float(last["bb_width"]),
            "sma20":         _safe_float(last["sma20"]),
            "sma50":         _safe_float(last["sma50"]),
            "sma200":        _safe_float(last["sma200"]),
            "ema20":         _safe_float(last["ema20"]),
            "volume_zscore": _safe_float(last["vol_zscore"]),
            "momentum_6m":   _safe_float(last["mom6m"]),
            "patterns":      patterns,
            "source":        "computed/yfinance",
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        log.error("compute_technical_indicators error: %s", e)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def predict_price_direction(ticker: str, exchange: str = "NASDAQ",
                                  horizon_days: int = 1) -> List[TextContent]:
    """
    Predict the price direction over the next N days using XGBoost.

    Training pipeline:
      1. Fetch 5 years of daily OHLCV data (minimum 200 bars required).
      2. Build 15 technical features via ``_build_features()``.
      3. Create binary label: 1 if price ``horizon_days`` later > current price.
      4. Walk-forward 5-fold TimeSeriesSplit to estimate backtest accuracy.
      5. Train a final XGBoost model on all data (with StandardScaler) and
         predict the probability of the ``"up"`` class for the latest row.
      6. Return ``direction``, ``confidence``, ``backtest_accuracy``, and
         the top 5 feature importances.

    Backtest accuracy typically ranges 52–56% for liquid US equities. Performance
    degrades for illiquid or less-efficient markets.

    Requires ``xgboost`` and ``scikit-learn`` — returns an error dict if either
    is not installed.

    Args:
        ticker:       Stock ticker symbol without suffix.
        exchange:     Exchange code.
        horizon_days: Number of trading days ahead to predict (default 1).

    Returns:
        List with a single TextContent containing: ``ticker``, ``exchange``,
        ``direction`` (``"up"``/``"down"``), ``confidence`` (float 0.5–1.0),
        ``horizon_days``, ``backtest_accuracy``, ``top_features``,
        ``training_samples``, ``disclaimer``, ``computed_at``.
        Returns ``{"error": str}`` if insufficient data or missing dependencies.
    """
    try:
        from xgboost import XGBClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.calibration import CalibratedClassifierCV
        import warnings
        warnings.filterwarnings("ignore")
    except ImportError:
        return [TextContent(type="text", text=json.dumps({"error": "xgboost not installed"}))]

    try:
        hist = _fetch_ohlcv(ticker, exchange, period="5y")
        if hist.empty or len(hist) < 200:
            return [TextContent(type="text", text=json.dumps({"error": f"Insufficient history for prediction ({len(hist)} days)."}))]

        df = _build_features(hist)

        feature_cols = [
            "rsi14", "macd", "macd_signal", "macd_hist",
            "bb_width", "bb_pos", "ma20_ratio", "ma50_ratio", "ma200_ratio",
            "vol_zscore", "atr", "ret1d", "ret5d", "ret20d", "mom6m",
        ]
        df = df.dropna(subset=feature_cols)
        if len(df) < 100:
            return [TextContent(type="text", text=json.dumps({"error": "Too many NaN values after feature engineering."}))]

        # Target: did price go up N days later?
        df["target"] = (df["Close"].shift(-horizon_days) > df["Close"]).astype(int)
        df = df.dropna(subset=["target"])

        X = df[feature_cols].values
        y = df["target"].values

        # Walk-forward cross-validation for honest backtest accuracy
        tscv = TimeSeriesSplit(n_splits=5)
        fold_accs = []
        for train_idx, test_idx in tscv.split(X):
            clf = XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.05,
                                use_label_encoder=False, eval_metric="logloss",
                                random_state=42, verbosity=0)
            clf.fit(X[train_idx], y[train_idx])
            preds = clf.predict(X[test_idx])
            acc = float((preds == y[test_idx]).mean())
            fold_accs.append(acc)
        backtest_accuracy = round(float(np.mean(fold_accs)), 3)

        # Final model on all data
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        final_clf = XGBClassifier(n_estimators=150, max_depth=4, learning_rate=0.05,
                                   use_label_encoder=False, eval_metric="logloss",
                                   random_state=42, verbosity=0)
        final_clf.fit(X_scaled, y)

        latest_features = scaler.transform(df[feature_cols].iloc[[-1]].values)
        prob = float(final_clf.predict_proba(latest_features)[0][1])
        direction = "up" if prob >= 0.5 else "down"
        confidence = round(prob if direction == "up" else 1 - prob, 3)

        # Feature importance (top 5)
        importances = final_clf.feature_importances_
        top_features = sorted(
            zip(feature_cols, importances.tolist()),
            key=lambda x: x[1], reverse=True
        )[:5]

        result = {
            "ticker":            ticker,
            "exchange":          exchange,
            "direction":         direction,
            "confidence":        confidence,
            "horizon_days":      horizon_days,
            "backtest_accuracy": backtest_accuracy,
            "top_features":      [{"feature": f, "importance": round(i, 4)} for f, i in top_features],
            "training_samples":  len(df),
            "disclaimer":        "Not financial advice. ML predictions have limited accuracy (~52-56%).",
            "computed_at":       datetime.now().isoformat(),
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        log.error("predict_price_direction error: %s", e)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def detect_anomalies(ticker: str, exchange: str = "NASDAQ",
                           lookback_days: int = 252) -> List[TextContent]:
    """
    Detect statistically unusual price and volume events using IsolationForest.

    Fetches 2 years of history, trims to ``lookback_days`` (default 252 = 1
    trading year), and fits IsolationForest with contamination=0.05 on three
    features: daily return, volume Z-score (30-day rolling), and day-over-day
    price gap. Returns the 10 most recent anomalies sorted by date descending.

    Requires ``scikit-learn`` — returns an error dict if not installed.

    Args:
        ticker:        Stock ticker symbol without suffix.
        exchange:      Exchange code.
        lookback_days: Number of most recent trading days to analyse (default 252).

    Returns:
        List with a single TextContent containing: ``ticker``, ``exchange``,
        ``anomalies`` (list of up to 10 dicts with ``date``, ``type``,
        ``severity``, ``return_pct``, ``volume_zscore``, ``description``),
        ``analyzed_days``, ``computed_at``.
        Returns empty ``anomalies`` list if fewer than 30 bars available.
    """
    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:
        return [TextContent(type="text", text=json.dumps({"error": "scikit-learn not installed"}))]

    try:
        hist = _fetch_ohlcv(ticker, exchange, period="2y")
        if hist.empty or len(hist) < 60:
            return [TextContent(type="text", text=json.dumps({"error": f"Insufficient data for {ticker}"}))]

        df = hist.copy().tail(lookback_days)
        close  = df["Close"]
        volume = df["Volume"]

        ret        = close.pct_change().fillna(0)
        vol_mean   = volume.rolling(30).mean()
        vol_zscore = ((volume - vol_mean) / volume.rolling(30).std().replace(0, np.nan)).fillna(0)
        gap        = (close - close.shift(1)).abs() / close.shift(1).replace(0, np.nan)

        features = pd.DataFrame({
            "ret":        ret,
            "vol_zscore": vol_zscore,
            "gap":        gap.fillna(0),
        }).dropna()

        if len(features) < 30:
            return [TextContent(type="text", text=json.dumps({"anomalies": [], "ticker": ticker}))]

        iso = IsolationForest(contamination=0.05, random_state=42)
        labels = iso.fit_predict(features.values)  # -1 = anomaly

        anomalies = []
        for i, (idx, row) in enumerate(features.iterrows()):
            if labels[i] == -1:
                ret_val   = float(row["ret"])
                volz_val  = float(row["vol_zscore"])
                gap_val   = float(row["gap"])

                if abs(volz_val) > 3:
                    atype = "volume_spike"
                elif abs(ret_val) > 0.05:
                    atype = "price_gap"
                else:
                    atype = "unusual_activity"

                severity = "high" if (abs(ret_val) > 0.08 or abs(volz_val) > 5) else "medium"

                anomalies.append({
                    "date":        str(idx.date()),
                    "type":        atype,
                    "severity":    severity,
                    "return_pct":  round(ret_val * 100, 2),
                    "volume_zscore": round(volz_val, 2),
                    "description": (
                        f"{atype.replace('_',' ').title()}: "
                        f"{ret_val*100:+.1f}% move, volume Z={volz_val:+.1f}σ"
                    ),
                })

        # Return most recent 10 anomalies
        anomalies = sorted(anomalies, key=lambda x: x["date"], reverse=True)[:10]

        result = {
            "ticker":    ticker,
            "exchange":  exchange,
            "anomalies": anomalies,
            "analyzed_days": len(features),
            "computed_at":   datetime.now().isoformat(),
        }
        return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        log.error("detect_anomalies error: %s", e)
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def get_sector_performance(period: str = "1mo") -> List[TextContent]:
    """
    Return performance statistics for all 11 US GICS sectors via SPDR ETFs.

    Maps each GICS sector to its SPDR ETF ticker (XLK for Technology, XLF for
    Financials, etc.) and computes start-to-end price return for the requested
    period. Individual ETF failures are silently caught and returned as
    ``{"performance_pct": None}``.

    Args:
        period: yfinance period string — ``"1wk"``, ``"1mo"`` (default),
                ``"3mo"``, ``"6mo"``, ``"1y"``.

    Returns:
        List with a single TextContent containing: ``period``, ``sectors``
        (dict mapping sector name to ``{"etf", "performance_pct", "latest_price"}``),
        ``source``, ``computed_at``.
    """
    SECTOR_ETFS = {
        "Technology":     "XLK",
        "Financials":     "XLF",
        "Healthcare":     "XLV",
        "Energy":         "XLE",
        "Consumer Disc.": "XLY",
        "Industrials":    "XLI",
        "Utilities":      "XLU",
        "Materials":      "XLB",
        "Real Estate":    "XLRE",
        "Comm. Services": "XLC",
        "Consumer Staples":"XLP",
    }
    try:
        results = {}
        for sector, etf in SECTOR_ETFS.items():
            try:
                hist = yf.Ticker(etf).history(period=period, interval="1d", auto_adjust=True)
                if not hist.empty and len(hist) >= 2:
                    start = float(hist["Close"].iloc[0])
                    end   = float(hist["Close"].iloc[-1])
                    perf  = round((end - start) / start * 100, 2) if start else None
                    results[sector] = {"etf": etf, "performance_pct": perf, "latest_price": round(end, 2)}
                else:
                    results[sector] = {"etf": etf, "performance_pct": None}
            except Exception:
                results[sector] = {"etf": etf, "performance_pct": None}

        return [TextContent(type="text", text=json.dumps({
            "period":  period,
            "sectors": results,
            "source":  "yfinance",
            "computed_at": datetime.now().isoformat(),
        }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


if __name__ == "__main__":
    from mcp.server.stdio import stdio_server

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(main())
