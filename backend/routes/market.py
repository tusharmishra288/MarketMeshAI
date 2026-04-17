"""
MarketMesh AI — Market Routes.

This router provides the core market-data endpoints consumed by the frontend.
It coordinates calls to the regional MCP servers, applies 2-tier caching, and
runs the multi-source news aggregation pipeline.

Endpoints
---------
- GET /api/quote/{ticker}:        Real-time (15-min delayed) stock quote.
- GET /api/fundamentals/{ticker}: Full fundamental data with AV enrichment and
                                  data-completeness validation score.
- GET /api/global-snapshot:       Live index values for all four regions plus
                                  market-open status and data-quality score.
- GET /api/news/{ticker}:         News aggregation pipeline — Marketaux entity
                                  search → Marketaux text search → yfinance news
                                  → DuckDuckGo web search (cascade fallback).
- GET /api/search:                Multi-source company search — Alpha Vantage
                                  SYMBOL_SEARCH → yfinance suffix probe →
                                  yfinance.Search with home-exchange ranking.

Dependencies
------------
- mcp_client:     Routes MCP tool calls to the correct regional server.
- cache_helpers:  L1 in-memory cache (TTL varies by endpoint, see docstrings).
- market_helpers: Exchange→region mapping, market-status windows, index fetch.
- enrichment:     Alpha Vantage enrichment and sentiment aggregation.
- services:       Redis cache manager and API rate limiters.
"""

import os
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import asyncio
import httpx
from fastapi import APIRouter

from helpers.mcp_client    import mcp_call
from helpers.cache_helpers import _mem_get, _mem_set
from helpers.market_helpers import (
    EXCHANGE_REGION, QUOTE_TOOL, FUNDAMENTALS_TOOL,
    _get_region, _fetch_index, _market_status,
)
from helpers.enrichment    import _enrich_with_alpha_vantage, _sentiment_aggregate
from helpers.services      import cache_manager, rate_limiter

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/quote/{ticker}")
async def get_quote(ticker: str, exchange: str = "NASDAQ", use_cache: bool = True):
    """
    Fetch a real-time (15-min delayed) stock quote for any globally-listed stock.

    Cache TTL: 60 seconds (L1 in-memory). Also checked/stored in L2 Redis via
    ``cache_manager``. Set ``use_cache=false`` to bypass both cache tiers and
    force a live MCP call (useful for testing or manual refresh).

    Args:
        ticker:    Stock ticker symbol (case-insensitive, uppercased internally).
        exchange:  Exchange code, e.g. ``"NASDAQ"``, ``"NSE"``, ``"LSE"``.
                   Determines which regional MCP server handles the request.
        use_cache: When ``True`` (default), checks L1 then L2 before calling
                   the MCP server.

    Returns:
        JSON dict with fields: ``ticker``, ``exchange``, ``price``,
        ``change``, ``change_percent``, ``high``, ``low``, ``open``,
        ``previous_close``, ``volume``, ``currency``, ``timestamp``,
        ``source``, ``delay_minutes``.

    Raises:
        HTTPException 503: MCP server for the exchange region is unavailable.
        HTTPException 404: No quote data found for the ticker.
    """
    ticker = ticker.upper()
    key    = f"quote:{ticker}:{exchange}"
    if use_cache:
        if cached := _mem_get(key):
            return cached
        cached_redis = await cache_manager.get_market_data(ticker, exchange, "real_time")
        if cached_redis:
            return cached_redis
    region = _get_region(exchange)
    data   = await mcp_call(region, QUOTE_TOOL[region], {"ticker": ticker, "exchange": exchange})
    _mem_set(key, data, ttl_seconds=60)
    await cache_manager.store_market_data(ticker, exchange, "real_time", data)
    return data


@router.get("/api/fundamentals/{ticker}")
async def get_fundamentals(ticker: str, exchange: str = "NASDAQ"):
    """
    Fetch comprehensive fundamental data for a stock, enriched via Alpha Vantage.

    Pipeline:
      1. Check L1 (in-memory) cache — TTL 3600 s.
      2. Check L2 Redis cache.
      3. Call the appropriate regional MCP server (``get_*_fundamentals`` tool).
      4. Enrich the result with Alpha Vantage OVERVIEW data (fills PE, ROE, etc.).
      5. Compute a ``validation_score`` (0–100%) based on how many of the 5
         required fields (company_name, sector, market_cap, pe_ratio, currency)
         are present and non-null.

    Args:
        ticker:   Stock ticker symbol (case-insensitive).
        exchange: Exchange code, e.g. ``"NASDAQ"``, ``"NSE"``.

    Returns:
        JSON dict with all fundamental fields plus ``validation_score``,
        ``validation_fields_present``, ``validation_fields_total``, and
        ``av_enriched`` (bool).

    Raises:
        HTTPException 503: MCP server unavailable.
        HTTPException 404: No fundamental data found for the ticker.
    """
    ticker = ticker.upper()
    key    = f"fundamentals:{ticker}:{exchange}"
    if cached := _mem_get(key):
        return cached
    cached_redis = await cache_manager.get_market_data(ticker, exchange, "fundamentals")
    if cached_redis:
        return cached_redis
    region = _get_region(exchange)
    data   = await mcp_call(region, FUNDAMENTALS_TOOL[region], {"ticker": ticker, "exchange": exchange})
    data   = await _enrich_with_alpha_vantage(ticker, data)

    try:
        required_fields = ["company_name", "sector", "market_cap", "pe_ratio", "currency"]
        present         = sum(1 for f in required_fields if data.get(f))
        completeness    = round(present / len(required_fields) * 100, 1)
        data["validation_score"]           = completeness
        data["validation_fields_present"]  = present
        data["validation_fields_total"]    = len(required_fields)
    except Exception:
        pass

    _mem_set(key, data, ttl_seconds=3600)
    await cache_manager.store_market_data(ticker, exchange, "fundamentals", data)
    return data


@router.get("/api/global-snapshot")
async def global_snapshot():
    """
    Return a real-time snapshot of major indices across all four regions.

    Americas indices (NASDAQ, S&P 500, Dow Jones) are fetched concurrently via
    a ``ThreadPoolExecutor`` using yfinance (blocking calls). Europe, Asia-Pacific,
    and MENA index data are fetched asynchronously from their respective MCP
    servers as concurrent ``asyncio.Task`` objects.

    Also returns a ``data_quality`` section with the percentage of indices that
    returned a non-null value, the number of validated sources, and the Redis
    cache hit rate.

    Returns:
        JSON dict with keys ``timestamp``, ``regions`` (nested dict per region
        containing ``status`` and ``major_indices``), and ``data_quality``.

    Raises:
        No exceptions — individual index failures are silently caught and
        represented as ``{"value": None, "change": 0}``.
    """
    americas_symbols = {"^IXIC": "NASDAQ", "^GSPC": "S&P 500", "^DJI": "Dow Jones"}
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=3) as pool:
        am_futures = {sym: loop.run_in_executor(pool, _fetch_index, sym) for sym in americas_symbols}
        am_results = {name: await am_futures[sym] for sym, name in americas_symbols.items()}

    async def _regional_indices(region: str, tool: str) -> dict:
        try:
            return (await mcp_call(region, tool, {})).get("indices", {})
        except Exception:
            return {}

    europe_t = asyncio.create_task(_regional_indices("europe", "get_european_indices"))
    asia_t   = asyncio.create_task(_regional_indices("asia_pacific", "get_asian_indices"))
    mena_t   = asyncio.create_task(_regional_indices("mena", "get_mena_indices"))
    europe_idx, asia_idx, mena_idx = await asyncio.gather(europe_t, asia_t, mena_t)

    total_indices = (len(am_results) + len(europe_idx) + len(asia_idx) + len(mena_idx)) or 1
    non_null      = sum(
        1 for d in list(am_results.values()) + list(europe_idx.values())
                    + list(asia_idx.values()) + list(mena_idx.values())
        if d.get("value") is not None
    )
    quality_score = round(non_null / total_indices * 100, 1)

    return {
        "timestamp": datetime.now().isoformat(),
        "regions": {
            "americas":    {"status": _market_status("americas"),    "major_indices": am_results},
            "europe":      {"status": _market_status("europe"),      "major_indices": europe_idx},
            "asia_pacific":{"status": _market_status("asia_pacific"),"major_indices": asia_idx},
            "mena":        {"status": _market_status("mena"),        "major_indices": mena_idx},
        },
        "data_quality": {
            "average_quality_score": quality_score,
            "sources_validated":     2,
            "cache_hit_rate":        cache_manager.get_stats().get("hit_rate", 0),
        },
    }


_POS_WORDS = {
    "surge", "surges", "beat", "beats", "profit", "profits", "growth", "record",
    "high", "gain", "gains", "rally", "rallies", "strong", "upgrade", "buy",
    "outperform", "positive", "rise", "rises", "up", "upbeat", "bullish",
    "revenue", "expand", "expands", "dividend", "opportunity",
}
_NEG_WORDS = {
    "fall", "falls", "miss", "misses", "loss", "losses", "decline", "declines",
    "down", "weak", "weakness", "crash", "crashes", "risk", "risks", "warning",
    "concern", "concerns", "sell", "underperform", "negative", "bearish",
    "cut", "cuts", "layoff", "layoffs", "lawsuit", "investigation", "fraud",
    "drop", "drops", "slump", "slumps", "disappoints", "disappoint",
}


def _ddg_sentiment(text: str) -> float:
    words = set(text.lower().split())
    pos = len(words & _POS_WORDS)
    neg = len(words & _NEG_WORDS)
    total = pos + neg
    return round((pos - neg) / total, 2) if total else 0.0


# Yahoo Finance exchange suffix mapping for yfinance news fallback
_YF_SUFFIX = {
    "LSE": ".L",   "XETRA": ".DE",  "EPA": ".PA",  "AMS": ".AS",
    "SWX": ".SW",  "BIT": ".MI",    "MCE": ".MC",  "OSL": ".OL",
    "HEL": ".HE",  "TSE": ".T",     "HKEX": ".HK", "SSE": ".SS",
    "SZSE": ".SZ", "NSE": ".NS",    "BSE": ".BO",  "ASX": ".AX",
    "SGX": ".SI",  "KRX": ".KS",    "TWSE": ".TW", "TADAWUL": ".SR",
    "DFM": ".DU",  "ADX": ".AD",    "TASE": ".TA", "EGX": ".CA",
    "DSM": ".QA",  "TSX": ".TO",    "B3": ".SA",   "BMV": ".MX",
}


def _yf_news_symbol(ticker: str, exchange: str) -> str:
    """Return Yahoo Finance symbol (with exchange suffix if non-US)."""
    suffix = _YF_SUFFIX.get(exchange.upper(), "")
    if suffix and not ticker.endswith(suffix):
        return ticker + suffix
    return ticker


@router.get("/api/news/{ticker}")
async def get_news(ticker: str, exchange: str = "NASDAQ", limit: int = 15,
                   company_name: str = ""):
    """
    News pipeline: Marketaux (entity-matched) → Marketaux (text/name search) → DuckDuckGo.
    Sentiment is calculated for every article regardless of source.
    company_name: when provided, used as the search query for non-entity searches so
                  numeric tickers (7203, 005930) return company-name-based articles.
    """
    ticker       = ticker.upper()
    api_key      = os.getenv("MARKETAUX_API_KEY", "")
    articles: list = []
    source        = "none"
    # Use company name as the search term when available (better than numeric ticker)
    search_term   = company_name.strip() or ticker

    def _article_sentiment(item: dict, entity_sym: str | None = None) -> float | None:
        """Return entity sentiment if available, else keyword-based score."""
        if entity_sym:
            entities = item.get("entities", [])
            scores = [e.get("sentiment_score") for e in entities
                      if e.get("symbol") == entity_sym and e.get("sentiment_score") is not None]
            if scores:
                return round(scores[0], 3)
        # Fall back to keyword sentiment
        text = (item.get("title") or "") + " " + (item.get("description") or "")
        return round(_ddg_sentiment(text), 3)

    _US_EXCHANGES = {"NASDAQ", "NYSE", "AMEX"}

    # ── 1. Marketaux by symbol (entity-matched, US stocks only) ──────────────
    # Entity-matched search is the highest-quality source: Marketaux explicitly
    # links articles to the ticker via NLP entity extraction, providing per-article
    # sentiment scores from the financial NLP model rather than keyword heuristics.
    # Skipped for non-US tickers: Marketaux entity matching often returns articles
    # about different companies that share the same ticker abbreviation (e.g. TCS
    # returns "The Container Store" instead of Tata Consultancy Services).
    if api_key and exchange.upper() in _US_EXCHANGES:
        await rate_limiter.acquire("marketaux")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://api.marketaux.com/v1/news/all",
                    params={"symbols": ticker, "filter_entities": "true",
                            "language": "en", "limit": limit, "api_token": api_key},
                )
            if r.status_code == 200:
                for item in r.json().get("data", []):
                    articles.append({
                        "title":        item.get("title"),
                        "description":  item.get("description", ""),
                        "source":       item.get("source", ""),
                        "url":          item.get("url", ""),
                        "published_at": item.get("published_at", ""),
                        "sentiment":    _article_sentiment(item, ticker),
                    })
                if articles:
                    source = "marketaux"
        except Exception as e:
            log.warning("Marketaux symbol search failed: %s", e)

    # ── 2. Marketaux text search (non-US or fallback) — use company name if known ─
    # Free-text search lacks entity linking so sentiment falls back to keyword
    # heuristics. Uses ``search_term`` (company name if provided, else ticker)
    # so numeric tickers (7203, 005930) return company-relevant articles.
    if not articles and api_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://api.marketaux.com/v1/news/all",
                    params={"search": search_term, "language": "en",
                            "limit": limit, "api_token": api_key},
                )
            if r.status_code == 200:
                for item in r.json().get("data", []):
                    articles.append({
                        "title":        item.get("title"),
                        "description":  item.get("description", ""),
                        "source":       item.get("source", ""),
                        "url":          item.get("url", ""),
                        "published_at": item.get("published_at", ""),
                        "sentiment":    _article_sentiment(item),
                    })
                if articles:
                    source = "marketaux_search"
        except Exception as e:
            log.warning("Marketaux text search failed: %s", e)

    _news_threshold = max(5, limit // 2)

    # ── 3. yfinance news (supplement / fallback — no rate limit) ─────────────────
    # Runs when Marketaux returned fewer than threshold articles.
    # yfinance.Ticker.news is ticker-specific and reliably returns 8-15 articles.
    # Supports both new API format (content dict with canonicalUrl/provider) and
    # the legacy flat format (link/publisher/providerPublishTime) for robustness
    # across yfinance ≥0.2.50 and earlier versions.
    if len(articles) < _news_threshold:
        yf_sym = _yf_news_symbol(ticker, exchange)
        try:
            import yfinance as yf
            from datetime import timezone

            def _yf_news_fetch():
                return yf.Ticker(yf_sym).news or []

            yf_news = await asyncio.wait_for(
                asyncio.to_thread(_yf_news_fetch), timeout=12.0
            )
            for item in yf_news[:20]:
                # yfinance ≥0.2.50 wraps news in {'id':..., 'content':{...}}
                # Older versions use a flat dict with title/link/publisher/providerPublishTime
                content = item.get("content") if isinstance(item.get("content"), dict) else item
                title   = content.get("title", "")
                desc    = content.get("summary") or content.get("description") or content.get("body") or title
                # pubDate is ISO string in new format; providerPublishTime is Unix int in old format
                pub_raw = content.get("pubDate") or content.get("displayTime") or ""
                if pub_raw and isinstance(pub_raw, str):
                    pub_str = pub_raw  # already ISO
                else:
                    pub_ts = content.get("providerPublishTime") or 0
                    try:
                        pub_str = datetime.fromtimestamp(int(pub_ts), tz=timezone.utc).isoformat()
                    except Exception:
                        pub_str = ""
                # URL: new format has canonicalUrl dict or clickThroughUrl dict; old has 'link'
                url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
                url     = (url_obj.get("url") if isinstance(url_obj, dict) else "") or content.get("link") or content.get("url", "")
                # Publisher: new format has provider.displayName; old has 'publisher'
                prov    = content.get("provider") or {}
                pub_name = (prov.get("displayName") if isinstance(prov, dict) else "") or content.get("publisher", "Yahoo Finance")
                if not (title and url):
                    continue
                articles.append({
                    "title":        title,
                    "description":  desc[:400] if desc else "",
                    "source":       pub_name,
                    "url":          url,
                    "published_at": pub_str,
                    "sentiment":    round(_ddg_sentiment(title + " " + (desc or "")), 3),
                })
            if yf_news:
                log.info("yfinance news: %d articles for %s", len(yf_news), yf_sym)
                source = source or "yfinance"
        except Exception as e:
            log.warning("yfinance news failed for %s: %s", yf_sym, e)

    # ── 4. DuckDuckGo web search (final fallback if still thin) ─────────────────
    # Last resort when all financial APIs return fewer than threshold articles.
    # Uses ``{search_term} stock news`` as the query string. Supports both the
    # ``ddgs`` package (newer) and ``duckduckgo_search`` (older) via try/except
    # import. Sentiment is keyword-based since DDG has no NLP sentiment API.
    if len(articles) < _news_threshold:
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
            query_str = f"{search_term} stock news"
            ddg_results = await asyncio.to_thread(
                lambda: list(DDGS().news(keywords=query_str, max_results=15))
            )
            for item in ddg_results:
                title = item.get("title", "")
                body  = item.get("body", "")
                if not title:
                    continue
                articles.append({
                    "title":        title,
                    "description":  body[:300],
                    "source":       item.get("source", "Web"),
                    "url":          item.get("url", ""),
                    "published_at": item.get("date", ""),
                    "sentiment":    round(_ddg_sentiment(title + " " + body), 3),
                })
            if articles:
                source = source or "web_search"
        except Exception as e:
            log.warning("DuckDuckGo news failed: %s", e)

    # De-duplicate by title (case-insensitive) keeping first occurrence
    seen_titles: set = set()
    unique_articles: list = []
    for a in articles:
        key = (a.get("title") or "").lower().strip()[:80]
        if key and key not in seen_titles:
            seen_titles.add(key)
            unique_articles.append(a)
    articles = unique_articles

    aggregate_sentiment = await _sentiment_aggregate(articles)
    return {
        "ticker":              ticker,
        "source":              source,
        "articles":            articles,
        "aggregate_sentiment": aggregate_sentiment,
    }


@router.get("/api/search")
async def search_companies(query: str, limit: int = 30):
    """
    Search for stocks by ticker symbol or company name across global exchanges.

    Multi-source cascade (each stage supplements or replaces the previous):

    1. Alpha Vantage SYMBOL_SEARCH (primary — 40k+ equities, strong for US/EU ADRs).
    2. yfinance suffix probe — attempts the query string with 13 exchange suffixes
       concurrently. Used when AV returns nothing (handles numeric tickers like
       7203 for Toyota, 005930 for Samsung).
    3. yfinance.Search — always runs for company-name queries (contains a space
       or lowercase letters). Returns home-exchange listings that AV may underrank.
       A secondary search on the first keyword broadens coverage for multi-word names.
       Indian stocks (BSE results) are probed for NSE equivalents.

    Results are deduplicated by ticker (case-insensitive), ranked to push APAC
    primary exchange listings to the top (NSE > other APAC > US/EU > OTC/pink sheets),
    and cached in L1 for 86400 seconds (24 hours).

    Args:
        query: Ticker symbol (e.g. ``"AAPL"``, ``"7203"``) or company name
               (e.g. ``"toyota motor"``, ``"reliance industries"``).
        limit: Maximum number of results to return (default 30).

    Returns:
        JSON dict with keys ``query`` and ``results`` (list of dicts containing
        ``ticker``, ``name``, ``type``, ``region``, ``currency``, ``score``).
    """
    key = f"search:{query.lower()}"
    if cached := _mem_get(key):
        # Skip empty cached results — let new fallbacks retry
        if cached.get("results"):
            return cached
    av_key = os.getenv("ALPHA_VANTAGE_KEY", "")
    results: list = []

    # Helper: deduplicate by ticker symbol keeping first occurrence
    def _dedup(lst: list) -> list:
        seen: set = set()
        out = []
        for item in lst:
            t = item.get("ticker", "").upper()
            if t and t not in seen:
                seen.add(t)
                out.append(item)
        return out

    # Detect company-name queries (contain spaces or mixed-case letters)
    _is_name_query = (" " in query) or any(c.islower() for c in query)

    # ── 1. Alpha Vantage SYMBOL_SEARCH (primary — 40k+ global equities) ──────
    if av_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://www.alphavantage.co/query",
                    params={"function": "SYMBOL_SEARCH", "keywords": query,
                            "apikey": av_key, "datatype": "json"},
                )
            if r.status_code == 200:
                for m in r.json().get("bestMatches", [])[:limit]:
                    sym = m.get("1. symbol", "")
                    if sym:
                        results.append({
                            "ticker":   sym,
                            "name":     m.get("2. name", ""),
                            "type":     m.get("3. type", ""),
                            "region":   m.get("4. region", ""),
                            "currency": m.get("8. currency", ""),
                            "score":    float(m.get("9. matchScore", 0)),
                        })
        except Exception as e:
            log.warning("Alpha Vantage SYMBOL_SEARCH failed: %s", e)

    # ── 2. yfinance suffix probe (for numeric tickers like 7203, 005930) ──────
    # Only runs when AV returned nothing — probes each exchange suffix concurrently.
    if not results:
        import yfinance as yf

        _PROBES = [
            (".T",  "Japan",          "TSE"),
            (".HK", "Hong Kong",      "HKEX"),
            (".KS", "South Korea",    "KRX"),
            (".SS", "China",          "SSE"),
            (".SZ", "China",          "SZSE"),
            (".NS", "India",          "NSE"),
            (".BO", "India / Bombay", "BSE"),
            (".AX", "Australia",      "ASX"),
            (".SI", "Singapore",      "SGX"),
            (".TW", "Taiwan",         "TWSE"),
            (".L",  "United Kingdom", "LSE"),
            (".DE", "Germany",        "XETRA"),
            ("",    "United States",  "NASDAQ"),
        ]

        async def _probe_one(sym_str: str, region: str):
            def _sync():
                try:
                    info  = yf.Ticker(sym_str).info
                    name  = info.get("longName") or info.get("shortName")
                    price = info.get("regularMarketPrice") or info.get("currentPrice")
                    if name and price:
                        return {"ticker": sym_str, "name": name,
                                "type": info.get("quoteType", "Equity"),
                                "region": region, "currency": info.get("currency", ""),
                                "score": 0.9}
                except Exception:
                    pass
                return None
            try:
                return await asyncio.wait_for(asyncio.to_thread(_sync), timeout=8.0)
            except Exception:
                return None

        probe_results = await asyncio.gather(
            *[_probe_one(query + s if s else query, r) for s, r, _ in _PROBES],
            return_exceptions=True,
        )
        results.extend(r for r in probe_results if isinstance(r, dict))

    # ── 3. yfinance.Search — always runs for name queries; fallback otherwise ──
    # Runs when: (a) no results yet, OR (b) query looks like a company name.
    # This ensures local-exchange tickers (NSE, TSE, KRX…) appear alongside US ADRs.
    if not results or _is_name_query:
        import yfinance as yf

        def _yf_search_sync():
            try:
                hits: list    = []
                seen: set     = set()   # dedup by ticker (upper-case)
                bse_bases: set = set()  # track bases needing NSE probe

                def _parse_quotes(quotes) -> None:
                    """Parse a yfinance quotes list into hits, skipping duplicates."""
                    for q in (quotes or []):
                        sym  = q.get("symbol", "")
                        name = q.get("longname") or q.get("shortname") or ""
                        if not (sym and name) or sym.upper() in seen:
                            continue
                        seen.add(sym.upper())
                        exch_disp = q.get("exchDisp", "")
                        hits.append({
                            "ticker":   sym,
                            "name":     name,
                            "type":     q.get("quoteType", "Equity"),
                            "region":   exch_disp,
                            "currency": q.get("currency", ""),
                            "score":    min(float(q.get("score", 0)) / 1_000_000, 1.0),
                        })
                        if sym.endswith(".BSE"):
                            bse_bases.add(sym[:-4])

                # Primary search — full query
                s1 = yf.Search(query, max_results=50)
                _parse_quotes(s1.quotes)

                # Secondary search — first meaningful word (captures more cross-listings
                # that Yahoo Finance omits from the full-phrase search)
                words = [w for w in query.strip().split() if len(w) > 2]
                if len(words) > 1:
                    try:
                        s2 = yf.Search(words[0], max_results=50)
                        _parse_quotes(s2.quotes)
                    except Exception:
                        pass

                # Probe NSE for any BSE results found (Indian companies)
                nse_extras = []
                for base in bse_bases:
                    ns_sym = base + ".NS"
                    # Skip if NSE already returned by yfinance.Search
                    if any(h["ticker"] == ns_sym for h in hits):
                        continue
                    try:
                        info = yf.Ticker(ns_sym).fast_info
                        price = getattr(info, "last_price", None)
                        if price:
                            # Find the corresponding BSE entry for name/type
                            bse_entry = next(
                                (h for h in hits if h["ticker"] == base + ".BSE"), {}
                            )
                            nse_extras.append({
                                "ticker":   ns_sym,
                                "name":     bse_entry.get("name", base),
                                "type":     bse_entry.get("type", "Equity"),
                                "region":   "NSE",
                                "currency": "INR",
                                "score":    (bse_entry.get("score", 0.5) or 0.5) + 0.05,
                            })
                    except Exception:
                        pass

                # Re-sort to boost APAC primary exchanges (NSE, TSE, KRX…) which Yahoo
                # Finance tends to underrank vs US ADRs.  For everything else we preserve
                # yfinance's natural relevance order (stable sort via original index).
                _APAC_PRIMARY = {".NS", ".BO", ".T", ".KS", ".HK", ".SS", ".SZ",
                                 ".AX", ".SI", ".TW", ".SR"}
                _OTC_MARKERS  = {"OTC", "OTC Markets", "Pink Sheets", "OQX"}

                for _i, _h in enumerate(hits):
                    _h["_idx"] = _i          # preserve yfinance relevance order

                def _exchange_rank(hit: dict) -> tuple:
                    sym  = hit["ticker"].upper()
                    exch = hit.get("region", "")
                    idx  = hit.get("_idx", 999)
                    # NSE (India's most liquid) → absolute top slot
                    if sym.endswith(".NS"):
                        return (0, 0, idx)
                    # Other APAC primary listings (TSE, KRX, HKEX, BSE, ASX…)
                    if any(sym.endswith(s.upper()) for s in _APAC_PRIMARY):
                        return (0, 1, idx)
                    # OTC / pink sheets → push to bottom
                    if any(o.lower() in exch.lower() for o in _OTC_MARKERS):
                        return (2, 0, idx)
                    # US major, European, LatAm, MENA — all same tier, yfinance order wins
                    return (1, 0, idx)

                hits.sort(key=_exchange_rank)
                # Return NSE/home tickers first, then rest
                return nse_extras + hits
            except Exception as exc:
                log.warning("yfinance.Search failed: %s", exc)
                return []

        try:
            yf_results = await asyncio.wait_for(
                asyncio.to_thread(_yf_search_sync), timeout=15.0
            )
            if _is_name_query:
                # For company-name queries yfinance.Search has better home-exchange
                # coverage (7203.T for Toyota, 005930.KS for Samsung, RELIANCE.NS for
                # Reliance). Put those results FIRST; AV's ADR/European listings follow.
                yf_tickers = {r["ticker"].upper() for r in yf_results}
                av_extras  = [r for r in results if r["ticker"].upper() not in yf_tickers]
                results    = yf_results + av_extras
            else:
                # For ticker queries AV is already correct; yfinance supplements
                existing = {r["ticker"].upper() for r in results}
                for r in yf_results:
                    if r["ticker"].upper() not in existing:
                        results.append(r)
                        existing.add(r["ticker"].upper())
        except Exception as exc:
            log.warning("yfinance.Search timeout/error: %s", exc)

    results = _dedup(results)[:limit]
    data    = {"query": query, "results": results}
    _mem_set(key, data, ttl_seconds=86400)
    return data
