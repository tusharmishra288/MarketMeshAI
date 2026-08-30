"""
MarketMesh AI — Macro Routes (FRED proxy and AI macro context).

This router proxies FRED (Federal Reserve Economic Data) macroeconomic series
from the economics MCP server and generates an AI-narrated macro environment
summary using the dual-LLM strategy (Groq primary, Gemini fallback).

Endpoints
---------
- GET /api/macro/{indicator}:  Proxy to a single FRED data series. Supported
  indicators: ``yield_curve``, ``inflation``, ``fed_rate``, ``gdp``,
  ``indicators``, ``macro_indicators``.
- GET /api/ai/macro-context:   Fetches all four macro series in parallel, then
  asks an LLM to produce a structured JSON analysis (summary, equity_impact,
  risks, stance). Cached 4 hours to limit LLM API usage.

Dependencies
------------
- mcp_client:     Dispatches calls to the economics MCP server.
- cache_helpers:  L1 cache — 3600 s for raw FRED data, 14400 s for AI context.
- groq/gemini:    Dual-LLM fallback for the AI macro context narrative.
"""

import os
import json
import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException

from helpers.mcp_client    import mcp_call
from helpers.cache_helpers import _mem_get, _mem_set

log    = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/macro/{indicator}")
async def get_macro(indicator: str, refresh: bool = False):
    """
    Proxy a FRED macroeconomic series through the economics MCP server.

    Maps the user-facing ``indicator`` slug to the correct MCP tool name and
    delegates to the economics MCP server which calls the FRED REST API.

    Cache TTL: 3600 seconds (L1). Set ``refresh=true`` to bypass the cache and
    force a fresh FRED fetch (useful for dashboards that poll on a schedule).

    Args:
        indicator: One of: ``"yield_curve"``, ``"inflation"``, ``"fed_rate"``,
                   ``"gdp"``, ``"indicators"``, ``"macro_indicators"``.
        refresh:   When ``True``, skips the L1 cache lookup and fetches fresh data.

    Returns:
        JSON dict with FRED series observations and computed metrics.
        Shape depends on the indicator — see economics MCP server docstrings.

    Raises:
        HTTPException 400: Unknown indicator slug not in the tool map.
        HTTPException 503: Economics MCP server unavailable.
    """
    tool_map = {
        "yield_curve":      "get_yield_curve",
        "inflation":        "get_inflation_data",
        "fed_rate":         "get_fed_rate",
        "gdp":              "get_gdp_growth",
        "indicators":       "get_macro_indicators",
        "macro_indicators": "get_macro_indicators",
    }
    tool = tool_map.get(indicator.lower())
    if not tool:
        raise HTTPException(status_code=400,
                            detail=f"Unknown indicator. Choose from: {list(tool_map.keys())}")
    key = f"macro:{indicator}"
    if not refresh:
        if cached := _mem_get(key):
            return cached
    data = await mcp_call("economics", tool, {})
    _mem_set(key, data, ttl_seconds=3600)
    return data


@router.get("/api/ai/macro-context")
async def ai_macro_context(refresh: bool = False):
    """
    Generate an AI-narrated macroeconomic analysis using live FRED data.

    Fetches yield curve, inflation (CPI/PCE), Fed funds rate, and real GDP
    in parallel from the economics MCP server, then constructs a compact
    context string and prompts an LLM to produce a structured JSON analysis.

    Prompt engineering notes:
    - Context is a single compact sentence to stay within token budgets for the
      fast Groq model (openai/gpt-oss-20b).
    - The prompt explicitly bans ``"Key: Value"`` pairs inside text fields to
      prevent the LLM from simply echoing the numbers instead of analysing them.
    - ``risks`` is constrained to exactly 3 complete sentences so the frontend
      can render them as a fixed-length bullet list.
    - Groq uses ``AsyncGroq`` (native async) with a 15 s timeout.
    - Gemini falls back via ``asyncio.to_thread`` if Groq fails.

    Cache TTL: 14400 seconds (L1 — 4 h). Set ``refresh=true`` to force
    regeneration (LLM calls are expensive; 4 h cache is intentionally long).

    Args:
        refresh: When ``True``, bypasses the cache and regenerates the analysis.

    Returns:
        JSON dict with keys: ``summary``, ``equity_impact``, ``risks`` (list of
        3 strings), ``stance`` (``"Risk-On"``/``"Risk-Off"``/``"Neutral"``),
        ``model_used``, ``generated_at``, ``macro_context`` (raw FRED summary).

    Raises:
        No HTTP exceptions — both LLM failures are caught and a static
        fallback text is placed in ``summary`` and ``equity_impact``.
    """
    key = "ai_macro_context"
    if not refresh:
        if cached := _mem_get(key):
            return cached

    macro = {}
    for ind, tool in [
        ("yield_curve", "get_yield_curve"),
        ("inflation",   "get_inflation_data"),
        ("fed_rate",    "get_fed_rate"),
        ("gdp",         "get_gdp_growth"),
    ]:
        try:
            macro[ind] = await mcp_call("economics", tool, {})
        except Exception:
            macro[ind] = {}

    yc   = macro.get("yield_curve", {})
    infl = macro.get("inflation", {})
    fed  = macro.get("fed_rate", {})
    gdp  = macro.get("gdp", {})

    context = (
        f"Yield curve: 10Y-2Y spread={yc.get('spread_10y_2y','N/A')}, "
        f"inverted={yc.get('inverted','N/A')}. "
        f"CPI YoY={infl.get('cpi',{}).get('yoy_pct','N/A')}%, "
        f"PCE YoY={infl.get('pce',{}).get('yoy_pct','N/A')}%. "
        f"Fed funds rate={fed.get('current_rate','N/A')}%. "
        f"Real GDP QoQ={gdp.get('current_qoq_pct','N/A')}%."
    )
    prompt = (
        f"You are a senior macroeconomic strategist. Current FRED data: {context}\n\n"
        "Respond ONLY with a JSON object containing exactly these 4 keys:\n"
        "- \"summary\": Two paragraphs of flowing analytical narrative about the macro environment. "
        "Write like a Bloomberg analyst — full sentences, no bullet points, no 'Key: Value' format. "
        "Interpret what the data means for the economy, don't just restate the numbers.\n"
        "- \"equity_impact\": One paragraph explaining implications for equity investors. "
        "Mention specific sectors or asset classes. Full sentences only, no key:value pairs.\n"
        "- \"risks\": Array of exactly 3 strings. Each string must be a complete sentence "
        "describing a specific risk and its potential market impact (e.g. 'A renewed CPI spike above 4% "
        "could force the Fed to resume rate hikes, compressing equity multiples across rate-sensitive sectors.').\n"
        "- \"stance\": Exactly one of: Risk-On, Risk-Off, Neutral.\n\n"
        "IMPORTANT: Do NOT output key:value pairs like 'CPI: 3.2%' or 'Fed Rate: 5.25%' inside any text field. "
        "Write analytical prose that interprets the data."
    )

    result = {
        "summary": None, "equity_impact": None,
        "risks": [], "stance": "Neutral",
        "model_used": None, "generated_at": datetime.now().isoformat(),
        "macro_context": context,
    }

    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            import groq as _groq
            client = _groq.AsyncGroq(api_key=groq_key, timeout=15.0)
            resp = await client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=700,
            )
            parsed = json.loads(resp.choices[0].message.content)
            result.update({k: v for k, v in parsed.items()
                           if k in ("summary", "equity_impact", "risks", "stance")})
            result["model_used"] = "groq/openai/gpt-oss-20b"
        except Exception as e:
            log.warning("Groq macro context failed: %s", e)

    if not result["summary"]:
        try:
            import google.generativeai as genai
            genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
            model = genai.GenerativeModel(
                "gemini-3.6-flash",
                generation_config=genai.GenerationConfig(response_mime_type="application/json"),
            )
            response = await asyncio.to_thread(model.generate_content, prompt)
            parsed   = json.loads(response.text)
            result.update({k: v for k, v in parsed.items()
                           if k in ("summary", "equity_impact", "risks", "stance")})
            result["model_used"] = "gemini-3.6-flash"
        except Exception as e:
            log.warning("Gemini macro fallback failed: %s", e)
            result["summary"]      = "AI analysis unavailable — GROQ_API_KEY not configured."
            result["equity_impact"] = "Review the FRED charts above for macro context."
            result["risks"] = [
                "Monitor yield curve for further inversion",
                "Track CPI/PCE trend relative to Fed 2% target",
                "Watch Fed guidance at upcoming FOMC meetings",
            ]

    _mem_set(key, result, ttl_seconds=14400)
    return result
