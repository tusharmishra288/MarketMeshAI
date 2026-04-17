"""
MarketMesh AI — Reusable Plotly chart builders.

All functions are pure: they accept data and config parameters and return
a ``plotly.graph_objects.Figure``. No Streamlit calls inside — callers
render via ``st.plotly_chart()``.
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from typing import Optional, List, Dict, Any


def build_candlestick_chart(
    df: pd.DataFrame,
    ticker: str,
    sym: str,
    show_sma20: bool = True,
    show_sma50: bool = True,
    show_sma200: bool = False,
    show_bb: bool = False,
) -> go.Figure:
    """
    Build an OHLCV candlestick chart with optional SMA overlays and Bollinger Bands.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns: date, open, high, low, close, volume,
        optionally sma_20, sma_50, sma_200, bb_upper, bb_middle, bb_lower.
    ticker : str
        Ticker symbol for the chart title.
    sym : str
        Currency display symbol (e.g. '$', 'p', '₹').
    show_sma20, show_sma50, show_sma200 : bool
        Whether to overlay the respective simple moving averages.
    show_bb : bool
        Whether to overlay Bollinger Bands (upper/middle/lower).

    Returns
    -------
    go.Figure
        A Plotly figure with 2 rows: price (top) and volume (bottom).
    """
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.03, row_heights=[0.75, 0.25],
    )
    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        increasing_line_color="#22c55e", decreasing_line_color="#ef4444",
        name=ticker,
    ), row=1, col=1)

    # SMA overlays
    sma_cfg = [
        ("sma_20",  show_sma20,  "#60a5fa", "SMA 20"),
        ("sma_50",  show_sma50,  "#f59e0b", "SMA 50"),
        ("sma_200", show_sma200, "#a78bfa", "SMA 200"),
    ]
    for col_name, show, color, label in sma_cfg:
        if show and col_name in df.columns:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df[col_name], name=label,
                line=dict(color=color, width=1.5, dash="dot"),
            ), row=1, col=1)

    # Bollinger Bands
    if show_bb and "bb_upper" in df.columns:
        for band_col, band_name, dash in [
            ("bb_upper", "BB Upper", "dash"),
            ("bb_middle", "BB Mid",  "dot"),
            ("bb_lower",  "BB Lower", "dash"),
        ]:
            if band_col in df.columns:
                fig.add_trace(go.Scatter(
                    x=df["date"], y=df[band_col], name=band_name,
                    line=dict(color="#94a3b8", width=1, dash=dash),
                ), row=1, col=1)

    # Volume bars
    colors = ["#22c55e" if c >= o else "#ef4444"
              for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(
        x=df["date"], y=df["volume"], name="Volume",
        marker_color=colors, opacity=0.7,
    ), row=2, col=1)

    fig.update_layout(
        height=580, showlegend=True,
        xaxis_rangeslider_visible=False,
        yaxis_title=f"Price ({sym})", yaxis2_title="Volume",
        margin=dict(t=30, b=20, l=60, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.06)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.06)")
    return fig


def build_rsi_macd_chart(df: pd.DataFrame) -> go.Figure:
    """
    Build a 2-panel RSI + MACD figure.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns: date, rsi, macd, macd_signal, macd_hist.

    Returns
    -------
    go.Figure
        A Plotly figure with RSI (top) and MACD histogram + signal (bottom).
    """
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.08, row_heights=[0.5, 0.5],
        subplot_titles=("RSI (14)", "MACD"),
    )
    # RSI
    if "rsi" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["rsi"], name="RSI",
            line=dict(color="#60a5fa", width=2),
        ), row=1, col=1)
        for level, color in [(70, "#ef4444"), (30, "#22c55e")]:
            fig.add_hline(y=level, line_dash="dash", line_color=color,
                          opacity=0.5, row=1, col=1)
        fig.update_yaxes(range=[0, 100], row=1, col=1)

    # MACD
    if "macd" in df.columns:
        hist_colors = [
            "#22c55e" if (v or 0) >= 0 else "#ef4444"
            for v in df.get("macd_hist", [])
        ]
        fig.add_trace(go.Bar(
            x=df["date"], y=df.get("macd_hist"), name="MACD Hist",
            marker_color=hist_colors, opacity=0.7,
        ), row=2, col=1)
        fig.add_trace(go.Scatter(
            x=df["date"], y=df["macd"], name="MACD",
            line=dict(color="#60a5fa", width=1.5),
        ), row=2, col=1)
        if "macd_signal" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["date"], y=df["macd_signal"], name="Signal",
                line=dict(color="#f59e0b", width=1.5),
            ), row=2, col=1)

    fig.update_layout(
        height=420, showlegend=True,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=40, b=20, l=60, r=20),
    )
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.06)")
    fig.update_yaxes(gridcolor="rgba(255,255,255,0.06)")
    return fig


def build_factor_radar(
    scores: List[float],
    categories: Optional[List[str]] = None,
) -> go.Figure:
    """
    Build a radar (spider) chart for factor exposure scores.

    Parameters
    ----------
    scores : list of float
        Four scores in order: [Value, Momentum, Quality, Low-Vol] (0–100 scale).
    categories : list of str, optional
        Axis labels. Defaults to ["Value", "Momentum", "Quality", "Low-Vol"].

    Returns
    -------
    go.Figure
    """
    if categories is None:
        categories = ["Value", "Momentum", "Quality", "Low-Vol"]
    fig = go.Figure(go.Scatterpolar(
        r=scores + [scores[0]],
        theta=categories + [categories[0]],
        fill="toself",
        line=dict(color="#60a5fa", width=2.5),
        fillcolor="rgba(96,165,250,0.18)",
        name="Factor Score",
    ))
    fig.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(visible=True, range=[0, 100],
                            tickfont=dict(color="#94a3b8", size=10),
                            gridcolor="rgba(255,255,255,0.1)"),
            angularaxis=dict(tickfont=dict(color="#e2e8f0", size=12)),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False, height=360,
        margin=dict(t=20, b=20, l=40, r=40),
    )
    return fig


def build_prediction_gauge(direction: str, confidence: float) -> go.Figure:
    """
    Build a bullet-style gauge showing ML prediction direction and confidence.

    Parameters
    ----------
    direction : str
        "up" or "down".
    confidence : float
        Confidence as a fraction (0–1) or percentage (0–100). Auto-detected.

    Returns
    -------
    go.Figure
        A Plotly indicator gauge figure.
    """
    pct = confidence if confidence > 1 else confidence * 100
    color = "#22c55e" if direction.lower() == "up" else "#ef4444"
    arrow = "▲" if direction.lower() == "up" else "▼"
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=pct,
        title={"text": f"{arrow} Predicted {direction.capitalize()}", "font": {"color": color, "size": 16}},
        gauge={
            "axis": {"range": [50, 100], "tickwidth": 1},
            "bar": {"color": color},
            "steps": [
                {"range": [50, 60], "color": "rgba(255,255,255,0.06)"},
                {"range": [60, 75], "color": "rgba(255,255,255,0.10)"},
                {"range": [75, 100], "color": "rgba(255,255,255,0.14)"},
            ],
            "threshold": {"line": {"color": "#f1f5f9", "width": 2}, "thickness": 0.8, "value": pct},
        },
        number={"suffix": "%", "font": {"size": 28, "color": color}},
    ))
    fig.update_layout(
        height=230, paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=40, b=10, l=30, r=30),
    )
    return fig
