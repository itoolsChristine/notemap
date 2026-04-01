"""Event logging for the notemap system.

SQLite-backed event log stored in the notemap database.
Used for usage tracking, gap detection, and future FSRS scheduling.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

# Module-level state
_session_id: str = ""
_initialized: bool = False


def init_events(notemap_dir: "Path | None" = None, retention_days: int = 180) -> str:
    """Initialize event logging for this session.

    Generates a session ID, prunes events older than retention_days.
    Returns the session ID.
    """
    global _session_id, _initialized
    from pathlib import Path

    _session_id = uuid.uuid4().hex[:12]
    _initialized = True

    # Prune old events
    _prune_old_events(retention_days)

    return _session_id


def log_event(
    note_id: str,
    event_type: str,
    tool: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append a single event to the database.

    Event types:
        searched         - note appeared in search results
        preflight_loaded - note loaded during preflight
        check_surfaced   - note surfaced during code check
        check_warning    - note's anti-pattern fired a warning
        reviewed         - note explicitly reviewed (mark_reviewed)
        missed           - note had increment_miss called
        search_miss      - search returned zero results (note_id will be empty)
    """
    if not _initialized:
        return

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta_json = json.dumps(metadata, ensure_ascii=True) if metadata else "{}"

    try:
        from db import get_db
        conn = get_db()
        conn.execute(
            "INSERT INTO events (timestamp, note_id, event, tool, session, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, note_id, event_type, tool, _session_id, meta_json),
        )
        conn.commit()
    except Exception:
        pass  # Non-critical - don't crash on logging failure


def log_search_miss(query: str, tool: str = "notemap_search") -> None:
    """Log a zero-result search for gap detection."""
    log_event("", "search_miss", tool, metadata={"query": query})


def log_co_retrieval(note_ids: list[str], tool: str) -> None:
    """Log that these notes were surfaced together."""
    if len(note_ids) < 2:
        return
    log_event("", "co_retrieval", tool, metadata={"notes": note_ids[:10]})


def get_session_summary() -> dict:
    """Aggregate events for the current session."""
    if not _initialized:
        return {"session": _session_id, "events": 0}

    try:
        from db import get_db
        conn = get_db()
        rows = conn.execute(
            "SELECT event, note_id FROM events WHERE session = ?",
            (_session_id,),
        ).fetchall()
    except Exception:
        return {"session": _session_id, "events": 0}

    counts: dict[str, int] = {}
    notes_touched: set[str] = set()
    for row in rows:
        etype = row["event"]
        counts[etype] = counts.get(etype, 0) + 1
        if row["note_id"]:
            notes_touched.add(row["note_id"])

    return {
        "session":      _session_id,
        "events":       sum(counts.values()),
        "by_type":      counts,
        "unique_notes": len(notes_touched),
    }


def get_session_id() -> str:
    """Return the current session ID."""
    return _session_id


def _prune_old_events(retention_days: int) -> None:
    """Remove events older than retention_days from the database."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    try:
        from db import get_db
        conn = get_db()
        conn.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
        conn.commit()
    except Exception:
        pass
