"""
StockPilot AI — Shared utilities for the frontend.

Single source of truth for exchange/currency maps, price formatters,
and timezone-aware market-hours helpers used across all pages.

Key sections
------------
- Exchange maps: EXCHANGE_CURRENCY, EXCHANGE_DISPLAY_NAMES, EXCHANGE_SHORT_NAMES
- Currency helpers: CURRENCY_SYMBOLS, exchange_sym(), exchange_code(), resolve_currency()
- Price formatters: fmt_price(), fmt_pct(), fmt_cap()
- Market hours: market_open() — timezone-aware open/closed check for each region
- Search routing: search_result_to_exchange() — maps Alpha Vantage / yfinance tickers to our exchange codes
- Source labels: fmt_source() — human-readable names for MCP server / provider keys
- Sentiment: sentiment_label() — converts float score to labelled emoji string
"""

import pytz
from datetime import datetime

# Full exchange → (currency_code, display_symbol) mapping
EXCHANGE_CURRENCY = {
    # Americas
    "NASDAQ":  ("USD", "$"),
    "NYSE":    ("USD", "$"),
    "AMEX":    ("USD", "$"),
    "TSX":     ("CAD", "C$"),
    "B3":      ("BRL", "R$"),
    "BMV":     ("MXN", "MX$"),
    # Europe
    "LSE":     ("GBX", "p"),
    "XETRA":   ("EUR", "€"),
    "EPA":     ("EUR", "€"),
    "AMS":     ("EUR", "€"),
    "SWX":     ("CHF", "Fr"),
    "BIT":     ("EUR", "€"),
    "MCE":     ("EUR", "€"),
    "OSL":     ("NOK", "kr"),
    "HEL":     ("EUR", "€"),
    # Asia-Pacific
    "TSE":     ("JPY", "¥"),
    "HKEX":    ("HKD", "HK$"),
    "SSE":     ("CNY", "¥"),
    "SZSE":    ("CNY", "¥"),
    "NSE":     ("INR", "₹"),
    "BSE":     ("INR", "₹"),
    "ASX":     ("AUD", "A$"),
    "SGX":     ("SGD", "S$"),
    "KRX":     ("KRW", "₩"),
    "TWSE":    ("TWD", "NT$"),
    # MENA
    "TADAWUL": ("SAR", "﷼"),
    "DFM":     ("AED", "د.إ"),
    "ADX":     ("AED", "د.إ"),
    "TASE":    ("ILS", "₪"),
    "EGX":     ("EGP", "E£"),
    "DSM":     ("QAR", "QR"),
}

# Currency code → display symbol (for response-driven currency detection)
CURRENCY_SYMBOLS = {
    "USD": "$",   "CAD": "C$",  "BRL": "R$",  "MXN": "MX$",
    "GBP": "£",   "GBp": "p",   "GBX": "p",   "EUR": "€",   "CHF": "Fr",
    "NOK": "kr",  "SEK": "kr",  "DKK": "kr",
    "JPY": "¥",   "CNY": "¥",   "HKD": "HK$", "INR": "₹",
    "AUD": "A$",  "SGD": "S$",  "KRW": "₩",   "TWD": "NT$",
    "SAR": "﷼",  "AED": "د.إ", "ILS": "₪",   "EGP": "E£",
    "QAR": "QR",
}

ALL_EXCHANGES = list(EXCHANGE_CURRENCY.keys())

# Full display names for exchange dropdowns
EXCHANGE_DISPLAY_NAMES = {
    # Americas
    "NASDAQ":  "NASDAQ — National Association of Securities Dealers Automated Quotations (US)",
    "NYSE":    "NYSE — New York Stock Exchange (US)",
    "AMEX":    "AMEX — NYSE American (US)",
    "TSX":     "TSX — Toronto Stock Exchange (Canada)",
    "B3":      "B3 — Brasil Bolsa Balcão (Brazil)",
    "BMV":     "BMV — Bolsa Mexicana de Valores (Mexico)",
    # Europe
    "LSE":     "LSE — London Stock Exchange (UK)",
    "XETRA":   "XETRA — Deutsche Börse Electronic Trading (Germany)",
    "EPA":     "EPA — Euronext Paris (France)",
    "AMS":     "AMS — Euronext Amsterdam (Netherlands)",
    "SWX":     "SWX — SIX Swiss Exchange (Switzerland)",
    "BIT":     "BIT — Borsa Italiana (Italy)",
    "MCE":     "MCE — Bolsa de Madrid / BME (Spain)",
    "OSL":     "OSL — Oslo Børs (Norway)",
    "HEL":     "HEL — Nasdaq Helsinki (Finland)",
    # Asia-Pacific
    "TSE":     "TSE — Tokyo Stock Exchange (Japan)",
    "HKEX":    "HKEX — Hong Kong Stock Exchange",
    "SSE":     "SSE — Shanghai Stock Exchange (China)",
    "SZSE":    "SZSE — Shenzhen Stock Exchange (China)",
    "NSE":     "NSE — National Stock Exchange of India",
    "BSE":     "BSE — Bombay Stock Exchange (India)",
    "ASX":     "ASX — Australian Securities Exchange",
    "SGX":     "SGX — Singapore Exchange",
    "KRX":     "KRX — Korea Exchange (South Korea)",
    "TWSE":    "TWSE — Taiwan Stock Exchange",
    # MENA
    "TADAWUL": "Tadawul — Saudi Exchange (Saudi Arabia)",
    "DFM":     "DFM — Dubai Financial Market (UAE)",
    "ADX":     "ADX — Abu Dhabi Securities Exchange (UAE)",
    "TASE":    "TASE — Tel Aviv Stock Exchange (Israel)",
    "EGX":     "EGX — Egyptian Exchange (Egypt)",
    "DSM":     "DSM — Qatar Stock Exchange",
}

# Short display names for compact UI elements (tables, headers, chips)
EXCHANGE_SHORT_NAMES = {
    "NASDAQ":  "NASDAQ (US)", "NYSE":    "NYSE (US)", "AMEX":    "AMEX (US)",
    "TSX":     "TSX (Canada)", "B3":     "B3 (Brazil)", "BMV":   "BMV (Mexico)",
    "LSE":     "LSE (UK)", "XETRA":  "XETRA (Germany)", "EPA":  "Euronext Paris",
    "AMS":     "Euronext Amsterdam", "SWX": "SIX Swiss (Switzerland)",
    "BIT":     "Borsa Italiana (Italy)", "MCE": "BME (Spain)",
    "OSL":     "Oslo Børs (Norway)", "HEL": "Nasdaq Helsinki (Finland)",
    "TSE":     "Tokyo SE (Japan)", "HKEX": "HKEX (Hong Kong)",
    "SSE":     "Shanghai SE (China)", "SZSE": "Shenzhen SE (China)",
    "NSE":     "NSE India", "BSE": "BSE India",
    "ASX":     "ASX (Australia)", "SGX": "SGX (Singapore)",
    "KRX":     "KRX (South Korea)", "TWSE": "TWSE (Taiwan)",
    "TADAWUL": "Tadawul (Saudi Arabia)", "DFM": "DFM (UAE)", "ADX": "ADX (UAE)",
    "TASE":    "TASE (Israel)", "EGX": "EGX (Egypt)", "DSM": "Qatar SE",
}

REGION_EXCHANGES = {
    "Americas":     ["NASDAQ", "NYSE", "AMEX", "TSX", "B3", "BMV"],
    "Europe":       ["LSE", "XETRA", "EPA", "AMS", "SWX", "BIT", "MCE", "OSL", "HEL"],
    "Asia-Pacific": ["TSE", "HKEX", "SSE", "SZSE", "NSE", "BSE", "ASX", "SGX", "KRX", "TWSE"],
    "MENA":         ["TADAWUL", "DFM", "ADX", "TASE", "EGX", "DSM"],
}

# Timezone per region for market-open check (tz_name, open_hour, close_hour)
_REGION_TZ = {
    "Americas":     ("America/New_York", 9.5,  16.0),
    "Europe":       ("Europe/London",    8.0,  16.5),
    "Asia-Pacific": ("Asia/Tokyo",       9.0,  15.5),
    "MENA":         ("Asia/Riyadh",     10.0,  15.0),
}


def market_open(region: str) -> bool:
    """Return True if the market is currently open (approximate, weekdays only)."""
    entry = _REGION_TZ.get(region)
    if not entry:
        return False
    tz_name, open_h, close_h = entry
    now = datetime.now(pytz.timezone(tz_name))
    if now.weekday() >= 5:  # Sat=5, Sun=6
        return False
    h = now.hour + now.minute / 60
    return open_h <= h < close_h


def exchange_sym(exchange: str) -> str:
    return EXCHANGE_CURRENCY.get(exchange, ("USD", "$"))[1]


def exchange_code(exchange: str) -> str:
    return EXCHANGE_CURRENCY.get(exchange, ("USD", "$"))[0]


def resolve_currency(exchange: str, response_currency: str | None) -> tuple:
    """Return (code, symbol) — prefer response currency if known."""
    if response_currency and response_currency in CURRENCY_SYMBOLS:
        return response_currency, CURRENCY_SYMBOLS[response_currency]
    return exchange_code(exchange), exchange_sym(exchange)


def fmt_price(price, sym: str) -> str:
    if price is None:
        return "—"
    try:
        return f"{sym}{float(price):,.2f}"
    except (TypeError, ValueError):
        return "—"


def fmt_pct(val, multiplier: float = 100, decimals: int = 2) -> str:
    """Format a ratio or percentage value.
    Auto-detects: if abs(val) > 2 it's already a percentage; else multiply by multiplier.
    """
    if val is None:
        return "—"
    try:
        v = float(val)
        if abs(v) > 2:   # Already expressed as a percentage (e.g. 22.4 → 22.4%)
            return f"{v:.{decimals}f}%"
        return f"{v * multiplier:.{decimals}f}%"
    except (TypeError, ValueError):
        return "—"


def fmt_cap(cap, sym: str, code: str) -> str:
    if not cap:
        return "—"
    try:
        v    = float(cap)
        sfx  = f" {code}" if code else ""
        if v >= 1e12:
            return f"{sym}{v/1e12:.2f}T{sfx}"
        if v >= 1e9:
            return f"{sym}{v/1e9:.2f}B{sfx}"
        if v >= 1e6:
            return f"{sym}{v/1e6:.2f}M{sfx}"
        return f"{sym}{v:,.0f}{sfx}"
    except (TypeError, ValueError):
        return "—"


_SUFFIX_EXCHANGE = {
    # Yahoo Finance suffixes
    "L": "LSE", "DE": "XETRA", "PA": "EPA", "AS": "AMS",
    "SW": "SWX", "MI": "BIT", "MC": "MCE", "OL": "OSL", "HE": "HEL",
    "T": "TSE", "HK": "HKEX", "SS": "SSE", "SZ": "SZSE",
    "NS": "NSE", "BO": "BSE", "AX": "ASX", "SI": "SGX",
    "KS": "KRX", "TW": "TWSE", "SR": "TADAWUL",
    "DU": "DFM", "AD": "ADX", "TA": "TASE", "CA": "EGX",
    "TO": "TSX", "SA": "B3", "MX": "BMV",
    # Alpha Vantage / yfinance.Search suffixes
    "LON": "LSE", "DEX": "XETRA", "FRK": "XETRA",
    "BSE": "BSE", "NSE": "NSE",
    "SAO": "B3", "QAT": "DSM",
    "TRT": "TSX",   # Toronto (yfinance.Search)
    "NEO": "TSX",   # NEO Exchange (Toronto)
}

_REGION_EXCHANGE = {
    # Standard region names
    "United States": "NASDAQ", "United Kingdom": "LSE",
    "Germany": "XETRA", "France": "EPA", "Netherlands": "AMS",
    "Switzerland": "SWX", "Italy": "BIT", "Spain": "MCE",
    "Norway": "OSL", "Finland": "HEL", "Japan": "TSE",
    "Hong Kong": "HKEX", "China": "SSE",
    "India / Bombay": "BSE", "India/Bombay": "BSE",  # AV returns no spaces
    "India": "NSE",
    "Australia": "ASX", "Singapore": "SGX",
    "South Korea": "KRX", "Taiwan": "TWSE",
    "Saudi Arabia": "TADAWUL", "United Arab Emirates": "DFM",
    "Israel": "TASE", "Egypt": "EGX", "Qatar": "DSM",
    "Canada": "TSX",
    "Brazil": "B3", "Brazil/Sao Paolo": "B3", "Brazil/Sao Paulo": "B3",
    "Mexico": "BMV",
    # Alpha Vantage / yfinance.Search sometimes return exchange name as region
    "XETRA": "XETRA", "Frankfurt": "XETRA",
    "Lisbon": "EPA",  # closest supported exchange for Portugal
    "Toronto": "TSX", "TSX": "TSX",
    # Indian exchanges (yfinance.Search returns "NSE" / "BSE" as exchDisp)
    "NSE": "NSE", "BSE": "BSE",
    "National Stock Exchange of India": "NSE",
    "Bombay Stock Exchange": "BSE",
    "Mumbai": "NSE", "Bombay": "BSE",
    "Seoul": "KRX", "Shanghai": "SSE", "Shenzhen": "SZSE",
    "Sydney": "ASX", "Singapore": "SGX", "Taipei": "TWSE",
    "Tel Aviv": "TASE", "Cairo": "EGX", "Doha": "DSM",
    "Dubai": "DFM", "Abu Dhabi": "ADX", "Riyadh": "TADAWUL",
    "Oslo": "OSL", "Helsinki": "HEL",
    "Amsterdam": "AMS", "Paris": "EPA", "Milan": "BIT", "Madrid": "MCE",
    "Zurich": "SWX", "London": "LSE", "Tokyo": "TSE",
}


def search_result_to_exchange(ticker: str, region: str, currency: str = "") -> str:
    """Map an Alpha Vantage search result to our internal exchange code."""
    if "." in ticker:
        suffix = ticker.rsplit(".", 1)[-1].upper()
        if suffix in _SUFFIX_EXCHANGE:
            return _SUFFIX_EXCHANGE[suffix]
    # Normalise region: strip spaces around slashes for robust matching
    normalised = region.replace(" / ", "/").replace("/ ", "/").replace(" /", "/")
    return _REGION_EXCHANGE.get(region) or _REGION_EXCHANGE.get(normalised, "NASDAQ")


_SOURCE_LABELS: dict = {
    # MCP regional servers
    "americas":      "Finnhub (Americas MCP)",
    "europe":        "yfinance (Europe MCP)",
    "asia_pacific":  "yfinance (Asia-Pacific MCP)",
    "mena":          "yfinance (MENA MCP)",
    "analytics":     "yfinance (Analytics MCP)",
    "economics":     "FRED (Economics MCP)",
    # Data providers
    "finnhub":           "Finnhub",
    "yfinance":          "Yahoo Finance",
    "alpha_vantage":     "Alpha Vantage",
    "marketaux":         "Marketaux",
    "marketaux_search":  "Marketaux",
    "web_search":        "DuckDuckGo",
    "cache":             "Cache",
    "none":              "—",
}


def fmt_source(source: str) -> str:
    """Convert internal MCP/provider source name to a human-readable label."""
    if not source:
        return "—"
    return _SOURCE_LABELS.get(source.lower().strip(),
                              source.replace("_", " ").title())


def sentiment_label(score) -> str:
    if score is None:
        return "—"
    try:
        score = float(score)
    except (TypeError, ValueError):
        return "—"
    if score > 0.15:
        return f"🟢 Positive ({score:+.2f})"
    if score < -0.15:
        return f"🔴 Negative ({score:+.2f})"
    return f"🟡 Neutral ({score:+.2f})"
