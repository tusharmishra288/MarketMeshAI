"""
StockPilot AI — User Data Routes (watchlist and price-alert CRUD).

This router exposes REST endpoints for persisted user data stored in the
application database (SQLite in development, PostgreSQL in production).
All database operations are delegated to the ``services.database`` module
which is imported lazily inside each handler to avoid circular imports.

Endpoints
---------
Watchlist
  - GET  /api/watchlist:         Retrieve all watchlist items for the user.
  - POST /api/watchlist:         Add a ticker/exchange pair to the watchlist.
  - DELETE /api/watchlist/{ticker}: Remove a ticker from the watchlist.

Price Alerts
  - GET  /api/alerts:            Retrieve all configured price alerts, optionally
                                 filtered by ticker.
  - POST /api/alerts:            Create a new price alert for a ticker.
  - DELETE /api/alerts/{alert_id}: Delete a price alert by its database ID.

Dependencies
------------
- services.database: Async ORM wrappers (``get_watchlist``, ``add_watchlist``,
  ``remove_watchlist``, ``get_alerts``, ``add_alert``, ``delete_alert``).
"""

import logging
from typing import Optional

from fastapi import APIRouter

log    = logging.getLogger(__name__)
router = APIRouter()


# ── Watchlist ─────────────────────────────────────────────────────────────────

@router.get("/api/watchlist")
async def watchlist_get():
    """
    Retrieve all tickers in the user's watchlist.

    Returns:
        JSON dict with keys: ``watchlist`` (list of dicts with ``ticker`` and
        ``exchange`` fields) and ``count`` (int).
    """
    from services.database import get_watchlist
    items = await get_watchlist()
    return {"watchlist": items, "count": len(items)}


@router.post("/api/watchlist")
async def watchlist_add(ticker: str, exchange: str = "NASDAQ"):
    """
    Add a ticker/exchange pair to the user's watchlist.

    The ticker is uppercased before storage. Duplicate entries are handled
    by the database layer (behaviour depends on the implementation — typically
    silently ignored or rejected).

    Args:
        ticker:   Stock ticker symbol (case-insensitive).
        exchange: Exchange code (default ``"NASDAQ"``).

    Returns:
        JSON dict with keys: ``added`` (bool), ``ticker`` (str, uppercased),
        ``exchange`` (str).
    """
    from services.database import add_watchlist
    added = await add_watchlist(ticker.upper(), exchange)
    return {"added": added, "ticker": ticker.upper(), "exchange": exchange}


@router.delete("/api/watchlist/{ticker}")
async def watchlist_remove(ticker: str, exchange: str = "NASDAQ"):
    """
    Remove a ticker from the user's watchlist.

    Args:
        ticker:   Stock ticker symbol (case-insensitive). Passed as a path
                  parameter.
        exchange: Exchange code — must match the value used when the item was
                  added (used to disambiguate tickers that trade on multiple
                  exchanges, e.g. ``HSBC`` on both LSE and HKEX).

    Returns:
        JSON dict with key ``removed`` (bool — ``True`` if a row was deleted).
    """
    from services.database import remove_watchlist
    removed = await remove_watchlist(ticker.upper(), exchange)
    return {"removed": removed}


# ── Price Alerts ──────────────────────────────────────────────────────────────

@router.get("/api/alerts")
async def alerts_get(ticker: Optional[str] = None):
    """
    Retrieve configured price alerts, optionally filtered by ticker.

    Args:
        ticker: Optional ticker symbol filter (case-insensitive). When
                ``None``, all alerts for all tickers are returned.

    Returns:
        JSON dict with keys: ``alerts`` (list of alert dicts) and
        ``count`` (int).
    """
    from services.database import get_alerts
    items = await get_alerts(ticker)
    return {"alerts": items, "count": len(items)}


@router.post("/api/alerts")
async def alerts_add(ticker: str, exchange: str = "NASDAQ",
                     threshold: float = 0.0, direction: str = "up"):
    """
    Create a new price alert for a ticker.

    The alert is triggered (by a background job, not this endpoint) when the
    live price moves above/below the threshold in the specified direction.

    Args:
        ticker:    Stock ticker symbol (case-insensitive).
        exchange:  Exchange code (default ``"NASDAQ"``).
        threshold: Price level that triggers the alert (absolute price value,
                   not a percentage). Default 0.0 — should be set by the caller.
        direction: ``"up"`` (alert when price rises above threshold) or
                   ``"down"`` (alert when price falls below threshold).

    Returns:
        JSON dict with key ``added`` (bool).
    """
    from services.database import add_alert
    added = await add_alert(ticker.upper(), exchange, threshold, direction)
    return {"added": added}


@router.delete("/api/alerts/{alert_id}")
async def alerts_delete(alert_id: int):
    """
    Delete a price alert by its database row ID.

    Args:
        alert_id: Integer primary key of the alert record to delete.

    Returns:
        JSON dict with key ``removed`` (bool — ``True`` if a row was deleted).
    """
    from services.database import delete_alert
    removed = await delete_alert(alert_id)
    return {"removed": removed}
