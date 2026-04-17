"""
MarketMesh AI — Database Service (Firestore primary, in-memory fallback).

Storage priority
----------------
1. **Google Cloud Firestore** — used when ``GCP_PROJECT_ID`` is set in the
   environment and Application Default Credentials (ADC) are available.
   On a GCP VM launched with the ``cloud-platform`` scope, ADC is automatic —
   no key file is needed. For local development, run:
       gcloud auth application-default login
   or set ``GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json``.

2. **In-memory fallback** — used when Firestore is unavailable (no project ID,
   missing library, auth failure). Data is lost on process restart. Suitable
   for local development and demos.

Firestore collections
---------------------
- ``watchlist``  — documents keyed by ``{TICKER}_{EXCHANGE}``
  Fields: ticker (str), exchange (str), added_at (ISO-8601 str)

- ``alerts``     — documents with auto-generated IDs
  Fields: ticker (str), exchange (str), threshold (float), direction (str),
          triggered (bool), created_at (ISO-8601 str)

Public interface (unchanged from PostgreSQL version — routes import these)
--------------------------------------------------------------------------
  init_db()                                         → None
  close_db()                                        → None
  add_watchlist(ticker, exchange)                   → bool
  get_watchlist()                                   → List[Dict]
  remove_watchlist(ticker, exchange)                → bool
  add_alert(ticker, exchange, threshold, direction) → bool
  get_alerts(ticker=None)                           → List[Dict]
  delete_alert(alert_id)                            → bool
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Module-level state ────────────────────────────────────────────────────────
_fs_client      = None   # google.cloud.firestore.AsyncClient, or None
_using_firestore = False  # True once Firestore is confirmed reachable

# In-memory stores — used when Firestore is unavailable
_watchlist_mem: List[Dict] = []
_alerts_mem:    List[Dict] = []
_alert_counter: int = 0   # simulates auto-increment IDs for in-memory alerts


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Lifecycle ─────────────────────────────────────────────────────────────────

async def init_db() -> None:
    """
    Initialise the storage backend.

    Attempts to connect to Firestore when ``GCP_PROJECT_ID`` is set.
    Falls back silently to in-memory storage on any failure so the app
    always starts, even without GCP credentials.
    """
    global _fs_client, _using_firestore

    project_id = os.getenv("GCP_PROJECT_ID", "").strip()
    if not project_id:
        logger.info(
            "GCP_PROJECT_ID not set — watchlist stored in-memory "
            "(set GCP_PROJECT_ID to enable Firestore persistence)"
        )
        return

    try:
        from google.cloud import firestore  # type: ignore

        _fs_client = firestore.AsyncClient(project=project_id)
        # Lightweight probe: stream at most 1 document to verify credentials
        async for _ in _fs_client.collection("watchlist").limit(1).stream():
            break
        _using_firestore = True
        logger.info("Firestore connected (project=%s)", project_id)

    except ImportError:
        logger.warning(
            "google-cloud-firestore not installed — run "
            "`pip install google-cloud-firestore` and restart"
        )
    except Exception as exc:
        logger.warning(
            "Firestore unavailable (%s) — falling back to in-memory storage", exc
        )
        _fs_client       = None
        _using_firestore = False


async def close_db() -> None:
    """Close the Firestore client if open."""
    global _fs_client, _using_firestore
    if _fs_client is not None:
        try:
            _fs_client.close()
        except Exception:
            pass
        _fs_client       = None
        _using_firestore = False


# ── Watchlist helpers ─────────────────────────────────────────────────────────

def _wl_doc_id(ticker: str, exchange: str) -> str:
    """Stable Firestore document ID for a watchlist entry."""
    return f"{ticker.upper()}_{exchange.upper()}"


# ── Watchlist — public API ────────────────────────────────────────────────────

async def add_watchlist(ticker: str, exchange: str) -> bool:
    """
    Add a ticker/exchange pair to the watchlist.

    Returns True if a new entry was created, False if it already existed.
    """
    ticker = ticker.upper()
    doc_id = _wl_doc_id(ticker, exchange)

    if _using_firestore and _fs_client is not None:
        try:
            ref  = _fs_client.collection("watchlist").document(doc_id)
            snap = await ref.get()
            if snap.exists:
                return False
            await ref.set({
                "ticker":   ticker,
                "exchange": exchange,
                "added_at": _now_iso(),
            })
            return True
        except Exception as exc:
            logger.error("Firestore add_watchlist failed: %s", exc)

    # In-memory fallback
    if any(w["ticker"] == ticker and w["exchange"] == exchange
           for w in _watchlist_mem):
        return False
    _watchlist_mem.append({
        "ticker":   ticker,
        "exchange": exchange,
        "added_at": _now_iso(),
    })
    return True


async def get_watchlist() -> List[Dict]:
    """Return all watchlist entries, newest first."""
    if _using_firestore and _fs_client is not None:
        try:
            docs = _fs_client.collection("watchlist").order_by(
                "added_at", direction="DESCENDING"
            ).stream()
            return [
                {
                    "ticker":   doc.get("ticker"),
                    "exchange": doc.get("exchange"),
                    "added_at": doc.get("added_at"),
                }
                async for doc in docs
            ]
        except Exception as exc:
            logger.error("Firestore get_watchlist failed: %s", exc)

    return sorted(_watchlist_mem, key=lambda x: x.get("added_at", ""), reverse=True)


async def remove_watchlist(ticker: str, exchange: str) -> bool:
    """Remove a ticker/exchange entry. Returns True if a document was deleted."""
    ticker = ticker.upper()
    doc_id = _wl_doc_id(ticker, exchange)

    if _using_firestore and _fs_client is not None:
        try:
            ref  = _fs_client.collection("watchlist").document(doc_id)
            snap = await ref.get()
            if not snap.exists:
                return False
            await ref.delete()
            return True
        except Exception as exc:
            logger.error("Firestore remove_watchlist failed: %s", exc)

    global _watchlist_mem
    before         = len(_watchlist_mem)
    _watchlist_mem = [
        w for w in _watchlist_mem
        if not (w["ticker"] == ticker and w["exchange"] == exchange)
    ]
    return len(_watchlist_mem) < before


# ── Price Alerts — public API ─────────────────────────────────────────────────

async def add_alert(
    ticker: str,
    exchange: str,
    threshold: float,
    direction: str,
) -> bool:
    """Create a new price alert. Returns True on success."""
    ticker    = ticker.upper()
    direction = direction.lower()
    payload   = {
        "ticker":     ticker,
        "exchange":   exchange,
        "threshold":  threshold,
        "direction":  direction,
        "triggered":  False,
        "created_at": _now_iso(),
    }

    if _using_firestore and _fs_client is not None:
        try:
            await _fs_client.collection("alerts").add(payload)
            return True
        except Exception as exc:
            logger.error("Firestore add_alert failed: %s", exc)

    global _alert_counter
    _alert_counter += 1
    _alerts_mem.append({"id": _alert_counter, **payload})
    return True


async def get_alerts(ticker: Optional[str] = None) -> List[Dict]:
    """Return all active (non-triggered) alerts, optionally filtered by ticker."""
    if _using_firestore and _fs_client is not None:
        try:
            # Use positional where() args — works across all SDK versions
            query = _fs_client.collection("alerts").where("triggered", "==", False)
            if ticker:
                query = query.where("ticker", "==", ticker.upper())
            results = []
            async for doc in query.order_by(
                "created_at", direction="DESCENDING"
            ).stream():
                entry       = doc.to_dict()
                entry["id"] = doc.id   # expose Firestore doc ID as alert ID
                results.append(entry)
            return results
        except Exception as exc:
            logger.error("Firestore get_alerts failed: %s", exc)

    base = (
        _alerts_mem if not ticker
        else [a for a in _alerts_mem if a["ticker"] == ticker.upper()]
    )
    return [a for a in base if not a.get("triggered")]


async def delete_alert(alert_id) -> bool:
    """
    Delete an alert by ID.

    ``alert_id`` is a Firestore document-ID string when using Firestore,
    or an integer when using the in-memory fallback.
    """
    if _using_firestore and _fs_client is not None:
        try:
            ref  = _fs_client.collection("alerts").document(str(alert_id))
            snap = await ref.get()
            if not snap.exists:
                return False
            await ref.delete()
            return True
        except Exception as exc:
            logger.error("Firestore delete_alert failed: %s", exc)

    global _alerts_mem
    before     = len(_alerts_mem)
    _alerts_mem = [a for a in _alerts_mem if a.get("id") != alert_id]
    return len(_alerts_mem) < before


