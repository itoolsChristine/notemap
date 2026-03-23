"""Tests for the audit module: audit_notes() and review_queue().

Covers all 7 audit check types (stale, low_confidence, unreviewed,
high_miss_count, orphaned_functions, index_integrity, all), the
review_queue priority scoring and limit/filter logic, and the
_parse_date helper.

Run with:  python -m unittest tests.test_audit
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Path setup -- allow imports from src/notemap-mcp/
# ---------------------------------------------------------------------------
_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src" / "notemap-mcp")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from audit import _parse_date, audit_notes, review_queue  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    """Return today's date as YYYY-MM-DD."""
    return date.today().isoformat()


def _days_ago(n: int) -> str:
    """Return a date string N days in the past."""
    return (date.today() - timedelta(days=n)).isoformat()


def _make_index() -> dict[str, dict[str, Any]]:
    """Build a mock note index with diverse entries for audit testing.

    Notes created:
      - zendb-get-empty:         active, strong, verified, reviewed 60 days ago (stale)
      - smartstring-trim:        active, strong, runtime-tested, reviewed recently
      - zendb-join-keys:         active, weak, unverified (low confidence)
      - smartarray-empty-check:  active, strong, never reviewed (created == last_reviewed)
      - zendb-insert:            active, maybe, inferred, miss_count=3
      - zendb-delete:            active, strong, verified, clean (no issues)
    """
    today = _today()
    return {
        "zendb-get-empty": {
            "library":              "zendb",
            "topic":                "DB::get returns empty SmartArrayHtml on no match",
            "type":                 "knowledge",
            "source_quality":       "verified-from-source",
            "confidence":           "strong",
            "lifecycle":            "active",
            "summary":              "DB::get always returns SmartArrayHtml.",
            "created":              _days_ago(90),
            "last_reviewed":        _days_ago(60),
            "review_interval_days": 30,
            "miss_count":           0,
            "review_count":         2,
            "related_functions":    ["DB::get"],
            "tags":                 ["zendb", "gotcha"],
            "path":                 "zendb/zendb-get-empty.md",
        },
        "smartstring-trim": {
            "library":              "smartstring",
            "topic":                "Use SmartString trim method not PHP trim",
            "type":                 "anti-pattern",
            "source_quality":       "runtime-tested",
            "confidence":           "strong",
            "lifecycle":            "active",
            "summary":              "Use ->trim() on SmartString, not PHP trim().",
            "created":              _days_ago(30),
            "last_reviewed":        _days_ago(5),
            "review_interval_days": 30,
            "miss_count":           0,
            "review_count":         1,
            "related_functions":    ["SmartString::trim"],
            "tags":                 ["smartstring"],
            "path":                 "smartstring/smartstring-trim.md",
        },
        "zendb-join-keys": {
            "library":              "zendb",
            "topic":                "ZenDB join keys are table-prefixed",
            "type":                 "knowledge",
            "source_quality":       "unverified",
            "confidence":           "weak",
            "lifecycle":            "active",
            "summary":              "Joined columns come back as table.column keys.",
            "created":              _days_ago(20),
            "last_reviewed":        _days_ago(10),
            "review_interval_days": 30,
            "miss_count":           0,
            "review_count":         1,
            "related_functions":    ["DB::select"],
            "tags":                 ["zendb"],
            "path":                 "zendb/zendb-join-keys.md",
        },
        "smartarray-empty-check": {
            "library":              "smartarray",
            "topic":                "Never use empty() on SmartArray objects",
            "type":                 "anti-pattern",
            "source_quality":       "verified-from-source",
            "confidence":           "strong",
            "lifecycle":            "active",
            "summary":              "empty() is always false on objects.",
            "created":              _days_ago(15),
            "last_reviewed":        _days_ago(15),
            "review_interval_days": 30,
            "miss_count":           0,
            "review_count":         0,
            "related_functions":    ["SmartArray::isEmpty"],
            "tags":                 ["smartarray"],
            "path":                 "smartarray/smartarray-empty-check.md",
        },
        "zendb-insert": {
            "library":              "zendb",
            "topic":                "DB::insert returns new record ID",
            "type":                 "knowledge",
            "source_quality":       "inferred",
            "confidence":           "weak",
            "lifecycle":            "active",
            "summary":              "DB::insert returns the auto-increment ID.",
            "created":              _days_ago(45),
            "last_reviewed":        _days_ago(40),
            "review_interval_days": 14,
            "miss_count":           3,
            "review_count":         1,
            "related_functions":    ["DB::insert"],
            "tags":                 ["zendb"],
            "path":                 "zendb/zendb-insert.md",
        },
        "zendb-delete": {
            "library":              "zendb",
            "topic":                "DB::delete requires WHERE clause",
            "type":                 "knowledge",
            "source_quality":       "verified-from-source",
            "confidence":           "strong",
            "lifecycle":            "active",
            "summary":              "DB::delete throws if no WHERE is given.",
            "created":              _days_ago(10),
            "last_reviewed":        _days_ago(2),
            "review_interval_days": 30,
            "miss_count":           0,
            "review_count":         1,
            "related_functions":    [],
            "tags":                 ["zendb"],
            "path":                 "zendb/zendb-delete.md",
        },
    }


# ---------------------------------------------------------------------------
# Tests: _parse_date
# ---------------------------------------------------------------------------

class TestParseDate(unittest.TestCase):
    """Tests for the _parse_date helper function."""

    def test_valid_date_string(self) -> None:
        """A valid YYYY-MM-DD string returns the corresponding date object."""
        result = _parse_date("2026-03-23")
        self.assertEqual(result, date(2026, 3, 23))

    def test_empty_string_returns_none(self) -> None:
        """An empty string returns None."""
        self.assertIsNone(_parse_date(""))

    def test_none_returns_none(self) -> None:
        """None input returns None."""
        self.assertIsNone(_parse_date(None))

    def test_invalid_date_string_returns_none(self) -> None:
        """A malformed date string returns None."""
        self.assertIsNone(_parse_date("not-a-date"))

    def test_whitespace_only_returns_none(self) -> None:
        """A whitespace-only string returns None."""
        self.assertIsNone(_parse_date("   "))

    def test_whitespace_padded_valid_date(self) -> None:
        """A valid date with surrounding whitespace is parsed correctly."""
        result = _parse_date("  2026-01-15  ")
        self.assertEqual(result, date(2026, 1, 15))


# ---------------------------------------------------------------------------
# Tests: audit_notes -- individual checks
# ---------------------------------------------------------------------------

class TestAuditStale(unittest.TestCase):
    """Tests for the 'stale' audit check."""

    def setUp(self) -> None:
        self.index    = _make_index()
        self.tmp_dir  = Path(tempfile.mkdtemp(prefix="notemap_audit_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_stale_finds_overdue_notes(self) -> None:
        """Notes reviewed more than review_interval_days ago are flagged stale."""
        result = audit_notes(self.index, self.tmp_dir, {"check": "stale"})
        stale_ids = [item["id"] for item in result["stale"]]
        # zendb-get-empty: reviewed 60 days ago, interval 30 -> 30 days overdue
        self.assertIn("zendb-get-empty", stale_ids)
        # zendb-insert: reviewed 40 days ago, interval 14 -> 26 days overdue
        self.assertIn("zendb-insert", stale_ids)

    def test_stale_excludes_recently_reviewed(self) -> None:
        """Notes reviewed within their interval are not flagged."""
        result = audit_notes(self.index, self.tmp_dir, {"check": "stale"})
        stale_ids = [item["id"] for item in result["stale"]]
        # smartstring-trim: reviewed 5 days ago, interval 30 -> not stale
        self.assertNotIn("smartstring-trim", stale_ids)
        # zendb-delete: reviewed 2 days ago, interval 30 -> not stale
        self.assertNotIn("zendb-delete", stale_ids)

    def test_stale_custom_stale_days(self) -> None:
        """Custom stale_days overrides per-note review_interval_days."""
        # With stale_days=100, even 60-day-old review is within bounds
        result = audit_notes(self.index, self.tmp_dir, {
            "check":      "stale",
            "stale_days": 100,
        })
        stale_ids = [item["id"] for item in result["stale"]]
        self.assertNotIn("zendb-get-empty", stale_ids)

    def test_stale_days_overdue_calculation(self) -> None:
        """days_overdue is calculated as (days_since_review - interval)."""
        result = audit_notes(self.index, self.tmp_dir, {"check": "stale"})
        for item in result["stale"]:
            if item["id"] == "zendb-get-empty":
                # 60 days since review - 30 day interval = 30 overdue
                self.assertEqual(item["days_overdue"], 30)
                break
        else:
            self.fail("zendb-get-empty not found in stale results")


class TestAuditLowConfidence(unittest.TestCase):
    """Tests for the 'low_confidence' audit check."""

    def setUp(self) -> None:
        self.index   = _make_index()
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_audit_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_low_confidence_finds_weak_unverified(self) -> None:
        """Notes with weak confidence AND inferred/unverified source are flagged."""
        result = audit_notes(self.index, self.tmp_dir, {"check": "low_confidence"})
        low_ids = [item["id"] for item in result["low_confidence"]]
        # zendb-join-keys: weak + unverified
        self.assertIn("zendb-join-keys", low_ids)
        # zendb-insert: weak + inferred
        self.assertIn("zendb-insert", low_ids)

    def test_low_confidence_excludes_strong(self) -> None:
        """Notes with strong confidence are not flagged even if source is weak."""
        result = audit_notes(self.index, self.tmp_dir, {"check": "low_confidence"})
        low_ids = [item["id"] for item in result["low_confidence"]]
        # zendb-get-empty: strong + verified
        self.assertNotIn("zendb-get-empty", low_ids)

    def test_low_confidence_requires_both_conditions(self) -> None:
        """A note must be BOTH weak confidence AND inferred/unverified to be flagged."""
        # Add a weak + verified-from-source note -- should NOT be flagged
        self.index["test-weak-verified"] = {
            "library":         "testlib",
            "topic":           "Weak but verified",
            "source_quality":  "verified-from-source",
            "confidence":      "weak",
            "lifecycle":       "active",
        }
        result = audit_notes(self.index, self.tmp_dir, {"check": "low_confidence"})
        low_ids = [item["id"] for item in result["low_confidence"]]
        self.assertNotIn("test-weak-verified", low_ids)


class TestAuditUnreviewed(unittest.TestCase):
    """Tests for the 'unreviewed' audit check."""

    def setUp(self) -> None:
        self.index   = _make_index()
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_audit_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_unreviewed_finds_never_reviewed(self) -> None:
        """Notes where created == last_reviewed are flagged as unreviewed."""
        result = audit_notes(self.index, self.tmp_dir, {"check": "unreviewed"})
        unreviewed_ids = [item["id"] for item in result["unreviewed"]]
        # smartarray-empty-check: created 15 days ago, last_reviewed 15 days ago (same date)
        self.assertIn("smartarray-empty-check", unreviewed_ids)

    def test_unreviewed_excludes_reviewed_notes(self) -> None:
        """Notes where last_reviewed differs from created are not flagged."""
        result = audit_notes(self.index, self.tmp_dir, {"check": "unreviewed"})
        unreviewed_ids = [item["id"] for item in result["unreviewed"]]
        # zendb-get-empty: created 90 days ago, reviewed 60 days ago (different)
        self.assertNotIn("zendb-get-empty", unreviewed_ids)


class TestAuditHighMissCount(unittest.TestCase):
    """Tests for the 'high_miss_count' audit check."""

    def setUp(self) -> None:
        self.index   = _make_index()
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_audit_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_high_miss_count_finds_miss_ge_2(self) -> None:
        """Notes with miss_count >= 2 are flagged."""
        result = audit_notes(self.index, self.tmp_dir, {"check": "high_miss_count"})
        high_ids = [item["id"] for item in result["high_miss_count"]]
        # zendb-insert: miss_count=3
        self.assertIn("zendb-insert", high_ids)

    def test_high_miss_count_excludes_low_miss(self) -> None:
        """Notes with miss_count < 2 are not flagged."""
        result = audit_notes(self.index, self.tmp_dir, {"check": "high_miss_count"})
        high_ids = [item["id"] for item in result["high_miss_count"]]
        # All others have miss_count=0
        self.assertNotIn("zendb-get-empty", high_ids)
        self.assertNotIn("smartstring-trim", high_ids)

    def test_high_miss_count_threshold_exactly_2(self) -> None:
        """A note with miss_count == 2 is flagged (boundary)."""
        self.index["test-miss-2"] = {
            "library":    "testlib",
            "topic":      "Exactly two misses",
            "miss_count": 2,
        }
        result = audit_notes(self.index, self.tmp_dir, {"check": "high_miss_count"})
        high_ids = [item["id"] for item in result["high_miss_count"]]
        self.assertIn("test-miss-2", high_ids)

    def test_high_miss_count_threshold_exactly_1(self) -> None:
        """A note with miss_count == 1 is NOT flagged (below threshold)."""
        self.index["test-miss-1"] = {
            "library":    "testlib",
            "topic":      "Exactly one miss",
            "miss_count": 1,
        }
        result = audit_notes(self.index, self.tmp_dir, {"check": "high_miss_count"})
        high_ids = [item["id"] for item in result["high_miss_count"]]
        self.assertNotIn("test-miss-1", high_ids)


class TestAuditOrphanedFunctions(unittest.TestCase):
    """Tests for the 'orphaned_functions' audit check."""

    def setUp(self) -> None:
        self.index   = _make_index()
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_audit_"))
        # Create a fake home directory for functionmap mocking
        self.fake_home = Path(tempfile.mkdtemp(prefix="notemap_fhome_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        shutil.rmtree(self.fake_home, ignore_errors=True)
        # Clear the module-level cache between tests
        from audit import _functionmap_cache
        _functionmap_cache.clear()

    @patch("audit.Path.home")
    def test_orphaned_functions_detects_missing(self, mock_home: Any) -> None:
        """Functions not found in the functionmap are flagged as orphaned."""
        mock_home.return_value = self.fake_home

        # Create the functionmap structure with zendb dir
        zendb_map_dir = self.fake_home / ".claude" / "functionmap" / "zendb"
        zendb_map_dir.mkdir(parents=True)
        (zendb_map_dir / "categories.md").write_text(
            "# ZenDB Functions\n- DB::get\n- DB::select\n",
            encoding="utf-8",
        )

        result = audit_notes(self.index, self.tmp_dir, {"check": "orphaned_functions"})
        orphaned = result["orphaned_functions"]
        orphaned_funcs = [(item["id"], item["function"]) for item in orphaned]

        # DB::insert is NOT in the functionmap text -> orphaned
        self.assertIn(("zendb-insert", "DB::insert"), orphaned_funcs)
        # DB::get IS in the functionmap text -> not orphaned
        self.assertNotIn(("zendb-get-empty", "DB::get"), orphaned_funcs)

    @patch("audit.Path.home")
    def test_orphaned_functions_skips_notes_without_related_functions(
        self, mock_home: Any,
    ) -> None:
        """Notes with no related_functions are silently skipped."""
        mock_home.return_value = self.fake_home

        # Create the functionmap structure
        zendb_map_dir = self.fake_home / ".claude" / "functionmap" / "zendb"
        zendb_map_dir.mkdir(parents=True)
        (zendb_map_dir / "index.md").write_text("# Index\n", encoding="utf-8")

        result = audit_notes(self.index, self.tmp_dir, {"check": "orphaned_functions"})
        orphaned_ids = [item["id"] for item in result["orphaned_functions"]]
        # zendb-delete has empty related_functions -> should not appear
        self.assertNotIn("zendb-delete", orphaned_ids)

    @patch("audit.Path.home")
    def test_orphaned_functions_skips_unknown_library_dirs(
        self, mock_home: Any,
    ) -> None:
        """If a library has no functionmap directory, its notes are skipped."""
        mock_home.return_value = self.fake_home

        # Create functionmap root but NOT the smartstring or smartarray dirs
        functionmap_dir = self.fake_home / ".claude" / "functionmap"
        functionmap_dir.mkdir(parents=True)

        result = audit_notes(self.index, self.tmp_dir, {"check": "orphaned_functions"})
        orphaned_ids = [item["id"] for item in result["orphaned_functions"]]
        # smartstring-trim has related_functions but no functionmap dir -> skipped, not flagged
        self.assertNotIn("smartstring-trim", orphaned_ids)


class TestAuditIndexIntegrity(unittest.TestCase):
    """Tests for the 'index_integrity' audit check."""

    def setUp(self) -> None:
        self.index   = _make_index()
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_audit_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_index_integrity_mismatch(self) -> None:
        """When disk file count differs from index count, status is 'mismatch'."""
        # Create fewer files on disk than entries in the index
        zendb_dir = self.tmp_dir / "zendb"
        zendb_dir.mkdir(parents=True)
        (zendb_dir / "zendb-get-empty.md").write_text("# Note", encoding="utf-8")
        (zendb_dir / "zendb-join-keys.md").write_text("# Note", encoding="utf-8")
        # Only 2 files on disk, 6 in the index

        result = audit_notes(self.index, self.tmp_dir, {"check": "index_integrity"})
        integrity = result["index_integrity"]
        self.assertEqual(integrity["status"], "mismatch")
        self.assertEqual(integrity["indexed"], 6)
        self.assertEqual(integrity["on_disk"], 2)

    def test_index_integrity_ok_when_counts_match(self) -> None:
        """When disk file count matches index count, status is 'ok'."""
        # Create exactly 6 .md files (matching index count)
        for note_id, entry in self.index.items():
            note_path = self.tmp_dir / entry["path"]
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(f"# {entry['topic']}", encoding="utf-8")

        result = audit_notes(self.index, self.tmp_dir, {"check": "index_integrity"})
        integrity = result["index_integrity"]
        self.assertEqual(integrity["status"], "ok")
        self.assertEqual(integrity["indexed"], 6)
        self.assertEqual(integrity["on_disk"], 6)

    def test_index_integrity_excludes_archive(self) -> None:
        """Files in _archive/ are not counted toward the disk count."""
        # Create files matching the index
        for note_id, entry in self.index.items():
            note_path = self.tmp_dir / entry["path"]
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(f"# {entry['topic']}", encoding="utf-8")

        # Add an archived file that should be excluded
        archive_dir = self.tmp_dir / "_archive"
        archive_dir.mkdir(parents=True)
        (archive_dir / "old-note.md").write_text("# Archived", encoding="utf-8")

        result = audit_notes(self.index, self.tmp_dir, {"check": "index_integrity"})
        integrity = result["index_integrity"]
        self.assertEqual(integrity["status"], "ok")
        self.assertEqual(integrity["on_disk"], 6)  # archive file excluded

    def test_index_integrity_nonexistent_dir(self) -> None:
        """When notemap_dir does not exist, on_disk stays 0."""
        nonexistent = self.tmp_dir / "nonexistent_subdir"
        result = audit_notes(self.index, nonexistent, {"check": "index_integrity"})
        integrity = result["index_integrity"]
        self.assertEqual(integrity["on_disk"], 0)
        self.assertEqual(integrity["indexed"], 6)


# ---------------------------------------------------------------------------
# Tests: audit_notes -- combined and filter behavior
# ---------------------------------------------------------------------------

class TestAuditCombined(unittest.TestCase):
    """Tests for audit_notes with check='all', library filter, and edge cases."""

    def setUp(self) -> None:
        self.index   = _make_index()
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_audit_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("audit.Path.home")
    def test_all_runs_every_check(self, mock_home: Any) -> None:
        """check='all' populates results for every check type."""
        # Stub functionmap so orphaned_functions doesn't hit real filesystem
        fake_home = self.tmp_dir / "fakehome"
        mock_home.return_value = fake_home
        (fake_home / ".claude" / "functionmap").mkdir(parents=True)

        result = audit_notes(self.index, self.tmp_dir, {"check": "all"})
        expected_keys = {
            "stale", "low_confidence", "unreviewed",
            "high_miss_count", "orphaned_functions", "index_integrity",
            "total_issues",
        }
        self.assertTrue(expected_keys.issubset(set(result.keys())))

    def test_library_filter_restricts_all_checks(self) -> None:
        """The library param filters entries across all check types."""
        result = audit_notes(self.index, self.tmp_dir, {
            "check":   "stale",
            "library": "smartstring",
        })
        stale_ids = [item["id"] for item in result["stale"]]
        # smartstring-trim was reviewed 5 days ago with 30-day interval -> not stale
        self.assertEqual(len(stale_ids), 0)

    def test_library_filter_restricts_high_miss_count(self) -> None:
        """Library filter on high_miss_count only shows that library's notes."""
        result = audit_notes(self.index, self.tmp_dir, {
            "check":   "high_miss_count",
            "library": "smartarray",
        })
        high_ids = [item["id"] for item in result["high_miss_count"]]
        # smartarray has no high-miss notes
        self.assertEqual(len(high_ids), 0)

    def test_total_issues_counts_all_findings(self) -> None:
        """total_issues is the sum of issues across all check types."""
        result = audit_notes(self.index, self.tmp_dir, {"check": "stale"})
        self.assertEqual(result["total_issues"], len(result["stale"]))

    def test_empty_index_returns_no_issues(self) -> None:
        """An empty index produces zero issues for all checks."""
        result = audit_notes({}, self.tmp_dir, {"check": "all"})
        self.assertEqual(result["total_issues"], 0)
        self.assertEqual(result["stale"], [])
        self.assertEqual(result["low_confidence"], [])
        self.assertEqual(result["unreviewed"], [])
        self.assertEqual(result["high_miss_count"], [])

    def test_clean_audit_no_issues(self) -> None:
        """An index with only clean notes returns zero issues for targeted checks."""
        clean_index: dict[str, dict[str, Any]] = {
            "clean-note": {
                "library":              "testlib",
                "topic":                "Perfectly clean note",
                "type":                 "knowledge",
                "source_quality":       "verified-from-source",
                "confidence":           "strong",
                "lifecycle":            "active",
                "summary":              "Everything is fine.",
                "created":              _days_ago(10),
                "last_reviewed":        _days_ago(1),
                "review_interval_days": 30,
                "miss_count":           0,
                "review_count":         3,
                "related_functions":    [],
                "tags":                 [],
                "path":                 "testlib/clean-note.md",
            },
        }
        # Create the file on disk so index_integrity passes
        note_path = self.tmp_dir / "testlib" / "clean-note.md"
        note_path.parent.mkdir(parents=True)
        note_path.write_text("# Clean note", encoding="utf-8")

        result = audit_notes(clean_index, self.tmp_dir, {"check": "stale"})
        self.assertEqual(result["total_issues"], 0)

        result = audit_notes(clean_index, self.tmp_dir, {"check": "low_confidence"})
        self.assertEqual(result["total_issues"], 0)

        result = audit_notes(clean_index, self.tmp_dir, {"check": "high_miss_count"})
        self.assertEqual(result["total_issues"], 0)

    def test_check_param_defaults_to_all(self) -> None:
        """When check is not provided, it defaults to 'all'."""
        result = audit_notes(self.index, self.tmp_dir, {})
        # Should have all check keys present
        self.assertIn("stale", result)
        self.assertIn("low_confidence", result)
        self.assertIn("unreviewed", result)
        self.assertIn("high_miss_count", result)

    def test_stale_note_with_none_last_reviewed(self) -> None:
        """Notes with no last_reviewed date are skipped by the stale check."""
        self.index["no-review-date"] = {
            "library":              "testlib",
            "topic":                "No review date",
            "last_reviewed":        None,
            "review_interval_days": 30,
        }
        result = audit_notes(self.index, self.tmp_dir, {"check": "stale"})
        stale_ids = [item["id"] for item in result["stale"]]
        self.assertNotIn("no-review-date", stale_ids)


# ---------------------------------------------------------------------------
# Tests: review_queue
# ---------------------------------------------------------------------------

class TestReviewQueue(unittest.TestCase):
    """Tests for the review_queue priority scoring and filtering."""

    def setUp(self) -> None:
        self.index = _make_index()

    # -- Priority scoring ---------------------------------------------------

    def test_high_miss_count_scores_highest(self) -> None:
        """Notes with high miss_count should appear near the top of the queue."""
        result = review_queue(self.index, {"limit": 0})
        queue  = result["queue"]
        # zendb-insert has miss_count=3 (60 pts) + weak (50) + inferred (40)
        # + stale overdue (26 days * 2 = 52) + never-reviewed? No, created != reviewed.
        # This should be at or near the top.
        top_ids = [item["id"] for item in queue[:2]]
        self.assertIn("zendb-insert", top_ids)

    def test_stale_lifecycle_adds_60_points(self) -> None:
        """Notes with lifecycle='stale' get +60 to their score."""
        # Add a stale note with no other scoring factors
        self.index["stale-only"] = {
            "library":              "testlib",
            "topic":                "Stale lifecycle note",
            "type":                 "knowledge",
            "source_quality":       "verified-from-source",
            "confidence":           "strong",
            "lifecycle":            "stale",
            "created":              _days_ago(10),
            "last_reviewed":        _days_ago(1),
            "review_interval_days": 30,
            "miss_count":           0,
        }
        result = review_queue(self.index, {"limit": 0})
        for item in result["queue"]:
            if item["id"] == "stale-only":
                self.assertEqual(item["priority_score"], 60.0)
                self.assertIn("lifecycle: stale", item["reasons"])
                break
        else:
            self.fail("stale-only not found in queue")

    def test_weak_confidence_adds_50_points(self) -> None:
        """Notes with confidence='weak' get +50 to their score."""
        # zendb-join-keys is weak + unverified (50 + 40 = 90 base)
        result = review_queue(self.index, {"limit": 0})
        for item in result["queue"]:
            if item["id"] == "zendb-join-keys":
                self.assertGreaterEqual(item["priority_score"], 90.0)
                self.assertIn("confidence: weak", item["reasons"])
                break
        else:
            self.fail("zendb-join-keys not found in queue")

    def test_unverified_source_adds_40_points(self) -> None:
        """Notes with source_quality='unverified' get +40."""
        result = review_queue(self.index, {"limit": 0})
        for item in result["queue"]:
            if item["id"] == "zendb-join-keys":
                self.assertIn("source_quality: unverified", item["reasons"])
                break

    def test_unreviewed_note_adds_30_points(self) -> None:
        """Notes where created == last_reviewed get +30."""
        result = review_queue(self.index, {"limit": 0})
        for item in result["queue"]:
            if item["id"] == "smartarray-empty-check":
                self.assertIn("never reviewed since creation", item["reasons"])
                self.assertGreaterEqual(item["priority_score"], 30.0)
                break
        else:
            self.fail("smartarray-empty-check not found in queue")

    def test_overdue_review_adds_scaled_points(self) -> None:
        """Overdue days are scaled by 2 and added to score."""
        # zendb-get-empty: reviewed 60 days ago, interval 30 -> 30 overdue * 2 = 60
        result = review_queue(self.index, {"limit": 0})
        for item in result["queue"]:
            if item["id"] == "zendb-get-empty":
                self.assertIn("30 days overdue", item["reasons"])
                break
        else:
            self.fail("zendb-get-empty not found in queue")

    # -- Zero-score exclusion -----------------------------------------------

    def test_zero_score_notes_excluded(self) -> None:
        """Notes with score <= 0 do not appear in the queue."""
        # zendb-delete: verified-from-source, strong, reviewed 2 days ago,
        # miss_count=0, active lifecycle, created != last_reviewed -> score=0
        result = review_queue(self.index, {"limit": 0})
        queue_ids = [item["id"] for item in result["queue"]]
        self.assertNotIn("zendb-delete", queue_ids)

    def test_all_clean_notes_produce_empty_queue(self) -> None:
        """An index of only clean notes produces an empty queue."""
        clean_index: dict[str, dict[str, Any]] = {
            "clean-note": {
                "library":              "testlib",
                "topic":                "Clean note",
                "type":                 "knowledge",
                "source_quality":       "verified-from-source",
                "confidence":           "strong",
                "lifecycle":            "active",
                "summary":              "No issues.",
                "created":              _days_ago(10),
                "last_reviewed":        _days_ago(1),
                "review_interval_days": 30,
                "miss_count":           0,
            },
        }
        result = review_queue(clean_index, {"limit": 0})
        self.assertEqual(result["queue"], [])
        self.assertEqual(result["total_due"], 0)
        self.assertEqual(result["showing"], 0)

    # -- Limit parameter ----------------------------------------------------

    def test_limit_zero_returns_all(self) -> None:
        """limit=0 returns every scored note."""
        result = review_queue(self.index, {"limit": 0})
        self.assertEqual(result["showing"], result["total_due"])

    def test_limit_restricts_output(self) -> None:
        """limit=2 returns at most 2 items."""
        result = review_queue(self.index, {"limit": 2})
        self.assertLessEqual(result["showing"], 2)
        self.assertLessEqual(len(result["queue"]), 2)

    def test_limit_greater_than_total(self) -> None:
        """When limit exceeds total scored notes, all are returned."""
        result = review_queue(self.index, {"limit": 100})
        self.assertEqual(result["showing"], result["total_due"])

    # -- Library filter -----------------------------------------------------

    def test_library_filter_restricts_queue(self) -> None:
        """Library filter only returns notes from the specified library."""
        result = review_queue(self.index, {"library": "zendb", "limit": 0})
        for item in result["queue"]:
            self.assertEqual(item["library"], "zendb")

    def test_library_filter_nonexistent_returns_empty(self) -> None:
        """Non-existent library filter returns empty queue."""
        result = review_queue(self.index, {"library": "nonexistent", "limit": 0})
        self.assertEqual(result["queue"], [])
        self.assertEqual(result["total_due"], 0)

    # -- Empty index --------------------------------------------------------

    def test_empty_index_returns_empty_queue(self) -> None:
        """An empty index returns an empty queue."""
        result = review_queue({}, {"limit": 0})
        self.assertEqual(result["queue"], [])
        self.assertEqual(result["total_due"], 0)
        self.assertEqual(result["showing"], 0)

    # -- Sort order ---------------------------------------------------------

    def test_queue_sorted_by_priority_descending(self) -> None:
        """Queue is sorted by priority_score, highest first."""
        result = review_queue(self.index, {"limit": 0})
        scores = [item["priority_score"] for item in result["queue"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    # -- Result fields ------------------------------------------------------

    def test_queue_item_fields_present(self) -> None:
        """Each queue item contains all expected fields."""
        result = review_queue(self.index, {"limit": 0})
        expected_keys = {
            "id", "topic", "library", "type", "source_quality",
            "confidence", "priority_score", "reasons", "summary",
        }
        for item in result["queue"]:
            self.assertTrue(
                expected_keys.issubset(set(item.keys())),
                f"Missing keys in {item['id']}: {expected_keys - set(item.keys())}",
            )

    def test_queue_reasons_is_list_of_strings(self) -> None:
        """The reasons field is always a list of strings."""
        result = review_queue(self.index, {"limit": 0})
        for item in result["queue"]:
            self.assertIsInstance(item["reasons"], list)
            for reason in item["reasons"]:
                self.assertIsInstance(reason, str)


if __name__ == "__main__":
    unittest.main()
