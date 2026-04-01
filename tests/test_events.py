"""Tests for the notemap event logging module.

Covers init_events, log_event, log_search_miss, log_co_retrieval,
get_session_summary, get_session_id, and _prune_old_events.

Run with:  python -m unittest tests.test_events -v
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Path setup -- allow imports from src/notemap-mcp/
# ---------------------------------------------------------------------------
_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src" / "notemap-mcp")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import db as db_module  # noqa: E402
import events as events_module  # noqa: E402
from db import close_db, get_db  # noqa: E402
from events import (  # noqa: E402
    get_session_id,
    get_session_summary,
    init_events,
    log_co_retrieval,
    log_event,
    log_search_miss,
)


class TestEvents(unittest.TestCase):
    """Event logging tests using a temporary SQLite database."""

    def setUp(self) -> None:
        close_db()
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_evt_"))
        # Set up fake home so get_db() with no args resolves to our temp dir.
        # get_db(None) defaults to Path.home() / ".claude" / "notemap".
        # We make that path equal to self.tmp_dir by patching Path.home.
        self._fake_home = self.tmp_dir / "home"
        self._notemap_dir = self._fake_home / ".claude" / "notemap"
        self._notemap_dir.mkdir(parents=True, exist_ok=True)
        self._home_patcher = patch.object(
            Path, "home", return_value=self._fake_home
        )
        self._home_patcher.start()
        # Initialize the database via the default path (which now points to temp)
        get_db()
        # Reset events module state
        events_module._session_id = ""
        events_module._initialized = False

    def tearDown(self) -> None:
        self._home_patcher.stop()
        close_db()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ===================================================================
    # init_events
    # ===================================================================

    def test_init_returns_session_id(self) -> None:
        sid = init_events(self.tmp_dir)
        self.assertIsInstance(sid, str)
        self.assertEqual(len(sid), 12)

    def test_init_sets_initialized_flag(self) -> None:
        self.assertFalse(events_module._initialized)
        init_events(self.tmp_dir)
        self.assertTrue(events_module._initialized)

    def test_init_idempotent(self) -> None:
        """Calling init_events twice should not error. Each call generates
        a new session ID."""
        sid1 = init_events(self.tmp_dir)
        sid2 = init_events(self.tmp_dir)
        self.assertNotEqual(sid1, sid2)

    def test_get_session_id_matches_init(self) -> None:
        sid = init_events(self.tmp_dir)
        self.assertEqual(get_session_id(), sid)

    # ===================================================================
    # log_event
    # ===================================================================

    def test_log_event_writes_to_db(self) -> None:
        init_events(self.tmp_dir)
        log_event("note-abc", "searched", "notemap_search")

        conn = get_db()
        rows = conn.execute("SELECT * FROM events").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["note_id"], "note-abc")
        self.assertEqual(rows[0]["event"], "searched")
        self.assertEqual(rows[0]["tool"], "notemap_search")

    def test_log_event_includes_session(self) -> None:
        sid = init_events(self.tmp_dir)
        log_event("note-abc", "searched", "notemap_search")

        conn = get_db()
        row = conn.execute("SELECT session FROM events").fetchone()
        self.assertEqual(row["session"], sid)

    def test_log_event_includes_timestamp(self) -> None:
        init_events(self.tmp_dir)
        log_event("note-abc", "searched", "notemap_search")

        conn = get_db()
        row = conn.execute("SELECT timestamp FROM events").fetchone()
        ts = row["timestamp"]
        # Should be ISO format with Z suffix
        self.assertTrue(ts.endswith("Z"))
        # Should be parseable
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")

    def test_log_event_with_metadata(self) -> None:
        init_events(self.tmp_dir)
        meta = {"query": "DB::get", "results": 3}
        log_event("note-abc", "searched", "notemap_search", metadata=meta)

        conn = get_db()
        row = conn.execute("SELECT metadata FROM events").fetchone()
        parsed = json.loads(row["metadata"])
        self.assertEqual(parsed["query"], "DB::get")
        self.assertEqual(parsed["results"], 3)

    def test_log_event_without_metadata(self) -> None:
        init_events(self.tmp_dir)
        log_event("note-abc", "searched", "notemap_search")

        conn = get_db()
        row = conn.execute("SELECT metadata FROM events").fetchone()
        parsed = json.loads(row["metadata"])
        self.assertEqual(parsed, {})

    def test_log_event_various_types(self) -> None:
        """All documented event types should be writable."""
        init_events(self.tmp_dir)
        event_types = [
            "searched", "preflight_loaded", "check_surfaced",
            "check_warning", "reviewed", "missed", "search_miss",
        ]
        for etype in event_types:
            log_event("note-x", etype, "test_tool")

        conn = get_db()
        count = conn.execute("SELECT COUNT(*) as c FROM events").fetchone()["c"]
        self.assertEqual(count, len(event_types))

    def test_log_event_skipped_when_not_initialized(self) -> None:
        """Before init_events, log_event should silently do nothing."""
        log_event("note-abc", "searched", "notemap_search")
        conn = get_db()
        count = conn.execute("SELECT COUNT(*) as c FROM events").fetchone()["c"]
        self.assertEqual(count, 0)

    def test_log_event_empty_note_id(self) -> None:
        """Empty note_id is valid (used by search_miss events)."""
        init_events(self.tmp_dir)
        log_event("", "search_miss", "notemap_search")

        conn = get_db()
        row = conn.execute("SELECT note_id FROM events").fetchone()
        self.assertEqual(row["note_id"], "")

    # ===================================================================
    # log_search_miss
    # ===================================================================

    def test_log_search_miss(self) -> None:
        init_events(self.tmp_dir)
        log_search_miss("nonexistent function")

        conn = get_db()
        row = conn.execute("SELECT * FROM events").fetchone()
        self.assertEqual(row["event"], "search_miss")
        self.assertEqual(row["note_id"], "")
        meta = json.loads(row["metadata"])
        self.assertEqual(meta["query"], "nonexistent function")

    # ===================================================================
    # log_co_retrieval
    # ===================================================================

    def test_log_co_retrieval(self) -> None:
        init_events(self.tmp_dir)
        log_co_retrieval(["note-a", "note-b", "note-c"], "notemap_search")

        conn = get_db()
        row = conn.execute("SELECT * FROM events").fetchone()
        self.assertEqual(row["event"], "co_retrieval")
        meta = json.loads(row["metadata"])
        self.assertEqual(meta["notes"], ["note-a", "note-b", "note-c"])

    def test_log_co_retrieval_skips_single_note(self) -> None:
        """Co-retrieval with fewer than 2 notes should not log."""
        init_events(self.tmp_dir)
        log_co_retrieval(["note-a"], "notemap_search")

        conn = get_db()
        count = conn.execute("SELECT COUNT(*) as c FROM events").fetchone()["c"]
        self.assertEqual(count, 0)

    def test_log_co_retrieval_truncates_to_10(self) -> None:
        """Co-retrieval should cap at 10 note IDs."""
        init_events(self.tmp_dir)
        note_ids = [f"note-{i}" for i in range(15)]
        log_co_retrieval(note_ids, "notemap_search")

        conn = get_db()
        row = conn.execute("SELECT metadata FROM events").fetchone()
        meta = json.loads(row["metadata"])
        self.assertEqual(len(meta["notes"]), 10)

    # ===================================================================
    # get_session_summary
    # ===================================================================

    def test_session_summary_before_init(self) -> None:
        result = get_session_summary()
        self.assertEqual(result["events"], 0)

    def test_session_summary_counts(self) -> None:
        init_events(self.tmp_dir)
        log_event("note-a", "searched", "notemap_search")
        log_event("note-a", "searched", "notemap_search")
        log_event("note-b", "reviewed", "notemap_update")

        summary = get_session_summary()
        self.assertEqual(summary["events"], 3)
        self.assertEqual(summary["by_type"]["searched"], 2)
        self.assertEqual(summary["by_type"]["reviewed"], 1)
        self.assertEqual(summary["unique_notes"], 2)

    def test_session_summary_session_id(self) -> None:
        sid = init_events(self.tmp_dir)
        summary = get_session_summary()
        self.assertEqual(summary["session"], sid)

    # ===================================================================
    # Session consistency
    # ===================================================================

    def test_session_id_consistent_within_session(self) -> None:
        """All events logged after init should share the same session ID."""
        init_events(self.tmp_dir)
        log_event("note-a", "searched", "notemap_search")
        log_event("note-b", "reviewed", "notemap_update")

        conn = get_db()
        rows = conn.execute("SELECT DISTINCT session FROM events").fetchall()
        self.assertEqual(len(rows), 1)

    # ===================================================================
    # Pruning
    # ===================================================================

    def test_prune_old_events(self) -> None:
        """Events older than retention_days should be pruned on init."""
        conn = get_db()
        # Insert an old event (200 days ago)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=200)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        conn.execute(
            "INSERT INTO events (timestamp, note_id, event, tool, session, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (old_ts, "old-note", "searched", "test", "old-session", "{}"),
        )
        # Insert a recent event (10 days ago)
        recent_ts = (datetime.now(timezone.utc) - timedelta(days=10)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        conn.execute(
            "INSERT INTO events (timestamp, note_id, event, tool, session, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (recent_ts, "new-note", "searched", "test", "recent-session", "{}"),
        )
        conn.commit()

        # Verify both exist
        count = conn.execute("SELECT COUNT(*) as c FROM events").fetchone()["c"]
        self.assertEqual(count, 2)

        # Init with default 180-day retention should prune the 200-day-old event
        init_events(self.tmp_dir)

        count = conn.execute("SELECT COUNT(*) as c FROM events").fetchone()["c"]
        self.assertEqual(count, 1)
        remaining = conn.execute("SELECT note_id FROM events").fetchone()
        self.assertEqual(remaining["note_id"], "new-note")


if __name__ == "__main__":
    unittest.main()
