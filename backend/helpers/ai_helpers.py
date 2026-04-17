"""
MarketMesh AI — AI Helpers (dual-LLM strategy for company analysis).

This module implements a dual-LLM fallback chain used across the ``/api/ai/*``
endpoints. Every LLM call attempts Groq first (lower latency, free tier) and
falls back to Google Gemini if Groq is unavailable or raises an exception. If
both providers fail, a deterministic rule-based fallback is returned so the
endpoint never returns an empty response.

LLM strategy
-------------
- Primary:  Groq ``llama-3.1-8b-instant`` — sub-1-second inference, JSON-mode
  supported, free tier allows ~14,400 tokens/minute.
- Fallback: Google ``gemini-2.0-flash`` — reliable quality, JSON mime type
  enforced via ``GenerationConfig``, slightly higher latency.
- Final fallback (``_ai_describe_company`` only): regex sentence-split of the
  raw description — always produces a usable 2-sentence output.

Both functions run LLM calls via ``asyncio.to_thread`` because the Groq and
Gemini SDKs are synchronous; this avoids blocking the event loop.

Dependencies
------------
- groq:                 Official Groq Python SDK (``pip install groq``).
- google-generativeai:  Google Gemini SDK (``pip install google-generativeai``).
- asyncio:              ``to_thread`` for non-blocking SDK calls.
"""

import os
import re
import json
import asyncio
import logging
from datetime import datetime

log = logging.getLogger(__name__)


async def _ai_describe_company(company_name: str, raw_description: str) -> dict:
    """
    Condense a raw company description to 2-3 clean sentences using an LLM.

    Prompt engineering notes:
    - Temperature 0.2 — low creativity ensures factual, stable output across
      repeated calls for the same ticker (the result is cached 7 days).
    - max_tokens=200 — sufficient for 2-3 sentences; keeps cost and latency low.
    - The prompt explicitly bans JSON/headings/bullets so the raw text can be
      stored and displayed directly in the UI without post-processing.
    - Raw description is truncated at 2000 chars to stay within context limits
      for the fast Groq model tier.

    Fallback chain: Groq → Gemini → regex sentence split of raw_description.

    Args:
        company_name:    Human-readable company name, used in the LLM prompt to
                         give the model context (e.g. ``"Apple Inc."``).
        raw_description: Full ``longBusinessSummary`` from yfinance/Alpha Vantage.
                         May be empty, in which case the function returns early.

    Returns:
        Dict with keys:
          - ``short_description`` (str): 2-3 sentence summary (or ``""``).
          - ``source`` (str): ``"groq"``, ``"gemini"``, ``"fallback"``, or ``"none"``.
    """
    if not raw_description or not raw_description.strip():
        return {"short_description": "", "source": "none"}

    # Prompt explicitly requests plain text output (no JSON/headings/bullets)
    # to keep the result UI-ready without post-processing
    prompt = (
        f"Summarize this company description for {company_name} into exactly "
        "2-3 clear, factual sentences. Focus on: what the company does, where it "
        "operates, and its main products or services. Do not add financial metrics. "
        "Output only the summary text — no JSON, no headings, no bullet points.\n\n"
        f"Description: {raw_description[:2000]}"
    )

    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            # asyncio.to_thread wraps the synchronous Groq SDK call so it does
            # not block the FastAPI event loop
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,   # low temperature → deterministic, factual
                max_tokens=200,    # 2-3 sentences fits comfortably in 200 tokens
            )
            short_desc = resp.choices[0].message.content.strip()
            if short_desc:
                return {"short_description": short_desc, "source": "groq"}
        except Exception as e:
            log.warning("Groq description generation failed: %s", e)

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-2.0-flash")
            # Gemini SDK is also synchronous — wrap in to_thread
            response = await asyncio.to_thread(model.generate_content, prompt)
            short_desc = response.text.strip()
            if short_desc:
                return {"short_description": short_desc, "source": "gemini"}
        except Exception as e:
            log.warning("Gemini description generation failed: %s", e)

    # Deterministic fallback: regex-split on sentence boundaries and take first 2.
    # Regex looks for punctuation followed by whitespace + capital letter so it
    # handles common sentence breaks without an NLP dependency.
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', raw_description.strip())
    fallback  = " ".join(sentences[:2]) if len(sentences) >= 2 else raw_description[:400]
    return {"short_description": fallback.strip(), "source": "fallback"}


async def _ai_company_summary(ticker: str, fundamentals: dict, quote: dict,
                               news_articles: list, technicals: dict) -> dict:
    """
    Generate a structured AI market-analysis report for a stock.

    Combines fundamentals, live quote, technical indicators, and recent news
    headlines into a structured prompt and asks the LLM to produce a JSON
    object with four analytical fields. Tries Groq first; falls back to
    Gemini; returns a static placeholder if both providers are unavailable.

    Prompt engineering notes:
    - Temperature 0.3 — slightly more creative than the description prompt to
      allow nuanced analytical prose, but still grounded.
    - max_tokens=600 — sufficient for 3-5 sentence summary + 3 risks + 2 short
      sentences. Higher would risk the fast Groq model drifting off-topic.
    - ``response_format={"type": "json_object"}`` is set for Groq so it
      strictly returns JSON without markdown fences. Gemini uses
      ``response_mime_type="application/json"`` for the same effect.
    - Only a curated subset of fundamentals keys is sent to the LLM to keep
      the prompt short and reduce hallucination risk from irrelevant fields.
    - News headlines (top 5 titles only) provide recency signal without
      overwhelming the token budget.

    Args:
        ticker:        Uppercase stock ticker symbol.
        fundamentals:  Fundamentals dict (post AV enrichment).
        quote:         Live quote dict (price, change_percent, currency).
        news_articles: List of news article dicts (title, sentiment, …).
        technicals:    Technical indicators dict (rsi14, macd, patterns, …).

    Returns:
        Dict with keys: ``summary``, ``risks`` (list of 3 strings),
        ``sentiment_context``, ``technical_view``, ``model_used``,
        ``generated_at``. Always returns a complete dict — never raises.
    """
    prompt = f"""You are a professional financial analyst. Analyze this data for {ticker}:

FUNDAMENTALS: {json.dumps({k: v for k, v in fundamentals.items() if k in ['company_name','sector','industry','market_cap','pe_ratio','forward_pe','eps','dividend_yield','52_week_high','52_week_low','beta','profit_margin','roe','description']}, indent=2)}

LIVE QUOTE: Price={quote.get('price')}, Change={quote.get('change_percent')}%, Currency={quote.get('currency')}

TECHNICALS: RSI={technicals.get('rsi14')}, MACD={technicals.get('macd')}, Patterns={technicals.get('patterns',[])}, Momentum_6m={technicals.get('momentum_6m')}

RECENT NEWS HEADLINES: {[a.get('title','') for a in news_articles[:5]]}

Provide a JSON response with exactly these keys:
- "summary": One paragraph (3-5 sentences) company outlook based on current data
- "risks": Array of exactly 3 concise risk factors
- "sentiment_context": One sentence on what the price vs 52-week range implies about current market sentiment
- "technical_view": One sentence on technical momentum based on RSI and MACD"""

    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            # json_object mode guarantees a parseable response without markdown fences
            resp = await asyncio.to_thread(
                client.chat.completions.create,
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
            result = json.loads(resp.choices[0].message.content)
            result["model_used"]    = "groq/llama-3.1-8b-instant"
            result["generated_at"]  = datetime.now().isoformat()
            return result
        except Exception as e:
            log.warning("Groq failed: %s — trying Gemini", e)

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            # response_mime_type="application/json" is Gemini's equivalent of Groq's
            # json_object mode — forces the model to output valid JSON
            model = genai.GenerativeModel(
                "gemini-2.0-flash",
                generation_config=genai.GenerationConfig(response_mime_type="application/json"),
            )
            response = await asyncio.to_thread(
                model.generate_content,
                prompt + "\n\nRespond with valid JSON only.",
            )
            result = json.loads(response.text)
            result["model_used"]   = "gemini-2.0-flash"
            result["generated_at"] = datetime.now().isoformat()
            return result
        except Exception as e:
            log.warning("Gemini also failed: %s", e)

    return {
        "summary":          "AI analysis unavailable — configure GROQ_API_KEY or GEMINI_API_KEY.",
        "risks":            ["API key not configured"],
        "sentiment_context": "N/A",
        "technical_view":   "N/A",
        "model_used":       "none",
        "generated_at":     datetime.now().isoformat(),
    }
