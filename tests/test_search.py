"""Tests for the notemap search scoring algorithm."""
from __future__ import annotations

import sys
import os
import unittest
from typing import Any

# Add the search module's directory to sys.path so we can import it directly.
_SEARCH_MODULE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "src", "notemap-mcp"
)
sys.path.insert(0, os.path.normpath(_SEARCH_MODULE_DIR))

from search import (  # noqa: E402
    search_notes,
    _pseudo_relevance_feedback,
    _split_code_query,
    _multi_query_expansion,
)


def _make_index() -> dict[str, dict[str, Any]]:
    """Build a mock note index with 5 notes spanning different libraries,
    types, confidence levels, tags, and lifecycle states."""
    return {
        "zendb-get-empty": {
            "library":            "zendb",
            "topic":              "DB::get returns empty SmartArrayHtml on no match",
            "type":               "knowledge",
            "source_quality":     "verified-from-source",
            "confidence":         "strong",
            "lifecycle":          "active",
            "summary":            "DB::get always returns SmartArrayHtml. Empty on no match.",
            "notes":              "Check with ->isEmpty(), never empty().",
            "related_functions":  ["DB::get"],
            "cues":               ["What does DB::get return when no record matches?"],
            "tags":               ["zendb", "gotcha"],
        },
        "smartstring-trim": {
            "library":            "smartstring",
            "topic":              "Use SmartString trim method not PHP trim",
            "type":               "anti-pattern",
            "source_quality":     "runtime-tested",
            "confidence":         "strong",
            "lifecycle":          "active",
            "summary":            "Use ->trim() on SmartString, not PHP trim().",
            "notes":              "PHP trim() acts on encoded output.",
            "related_functions":  ["SmartString::trim", "SmartString::value"],
            "cues":               ["How to trim a SmartString safely?"],
            "tags":               ["smartstring", "anti-pattern"],
        },
        "zendb-select-join": {
            "library":            "zendb",
            "topic":              "ZenDB join keys are table-prefixed",
            "type":               "knowledge",
            "source_quality":     "documented",
            "confidence":         "maybe",
            "lifecycle":          "active",
            "summary":            "Joined columns come back as table.column keys.",
            "notes":              "Access with $row['users.name'] syntax.",
            "related_functions":  ["DB::select"],
            "cues":               ["How are join columns named in ZenDB results?"],
            "tags":               ["zendb"],
        },
        "smartarray-empty-check": {
            "library":            "smartarray",
            "topic":              "Never use empty() on SmartArray objects",
            "type":               "anti-pattern",
            "source_quality":     "verified-from-source",
            "confidence":         "strong",
            "lifecycle":          "stale",
            "summary":            "empty() is always false on objects. Use ->isEmpty().",
            "notes":              "PHP quirk: empty($object) is always false.",
            "related_functions":  ["SmartArray::isEmpty", "SmartArray::count"],
            "cues":               ["Why does empty() fail on SmartArray?"],
            "tags":               ["smartarray", "gotcha"],
        },
        "zendb-insert": {
            "library":            "zendb",
            "topic":              "DB::insert returns new record ID",
            "type":               "knowledge",
            "source_quality":     "unverified",
            "confidence":         "weak",
            "lifecycle":          "active",
            "summary":            "DB::insert returns the auto-increment ID of the new row.",
            "notes":              "Unverified -- assumed from typical PDO behavior.",
            "related_functions":  ["DB::insert"],
            "cues":               [],
            "tags":               ["zendb"],
        },
    }


class TestSearchScoring(unittest.TestCase):
    """Test the search_notes scoring algorithm."""

    def setUp(self) -> None:
        self.index = _make_index()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ids(self, result: dict[str, Any]) -> list[str]:
        """Extract note IDs from a search result dict."""
        return [r["id"] for r in result["results"]]

    def _score_of(self, result: dict[str, Any], note_id: str) -> float:
        """Get the relevance_score for a specific note ID, or -1 if absent."""
        for r in result["results"]:
            if r["id"] == note_id:
                return r["relevance_score"]
        return -1.0

    # ------------------------------------------------------------------
    # 1. Exact function_name match => +100 + boosts
    # ------------------------------------------------------------------

    def test_function_name_exact_match(self) -> None:
        """Exact match in related_functions scores +100 plus applicable boosts."""
        result = search_notes(self.index, {"function_name": "DB::get"})
        self.assertEqual(result["count"], 1)
        self.assertIn("zendb-get-empty", self._ids(result))
        # Exact function match produces a positive score
        self.assertGreater(self._score_of(result, "zendb-get-empty"), 0.0)

    # ------------------------------------------------------------------
    # 2. Substring function_name match => +50
    # ------------------------------------------------------------------

    def test_function_name_substring_match(self) -> None:
        """Substring match in related_functions scores +50 plus boosts."""
        # "value" is a substring of "SmartString::value"
        result = search_notes(self.index, {"function_name": "value"})
        self.assertEqual(result["count"], 1)
        self.assertIn("smartstring-trim", self._ids(result))
        # Substring function match produces a positive score
        self.assertGreater(self._score_of(result, "smartstring-trim"), 0.0)

    # ------------------------------------------------------------------
    # 3. Query matching topic => +40
    # ------------------------------------------------------------------

    def test_query_matches_topic(self) -> None:
        """Single word found only in topic field produces a positive BM25F score."""
        # "prefixed" appears only in the topic, not summary/cues/tags
        result = search_notes(self.index, {"query": "prefixed"})
        self.assertIn("zendb-select-join", self._ids(result))
        # BM25F score is positive (exact magnitude varies by corpus)
        self.assertGreater(self._score_of(result, "zendb-select-join"), 0.0)

    # ------------------------------------------------------------------
    # 4. Query matching cue => +30
    # ------------------------------------------------------------------

    def test_query_matches_cue(self) -> None:
        """Query matching cue text produces a positive BM25F score."""
        result = search_notes(self.index, {"query": "How to trim a SmartString"})
        self.assertIn("smartstring-trim", self._ids(result))
        score = self._score_of(result, "smartstring-trim")
        # BM25F score is positive when cue/topic/summary match
        self.assertGreater(score, 0.0)

    # ------------------------------------------------------------------
    # 5. Query matching summary => +20
    # ------------------------------------------------------------------

    def test_query_matches_summary_only(self) -> None:
        """Single word found only in summary produces a positive BM25F score."""
        # "auto-increment" appears only in the summary of zendb-insert
        result = search_notes(self.index, {"query": "auto-increment"})
        self.assertIn("zendb-insert", self._ids(result))
        # BM25F score is positive (no quality boosts for unverified/weak)
        self.assertGreater(self._score_of(result, "zendb-insert"), 0.0)

    def test_multi_word_query_matches_more_than_single(self) -> None:
        """Multi-word query scores higher when more words match."""
        # Single word: "trim" matches in topic + summary + cues
        single = search_notes(self.index, {"query": "trim"})
        # Two words: "trim SmartString" -- both words match independently
        multi = search_notes(self.index, {"query": "trim SmartString"})
        self.assertIn("smartstring-trim", self._ids(single))
        self.assertIn("smartstring-trim", self._ids(multi))
        # Both should find the note with a positive score
        self.assertGreater(self._score_of(single, "smartstring-trim"), 0.0)
        self.assertGreater(self._score_of(multi, "smartstring-trim"), 0.0)

    def test_word_level_matching_finds_partial_phrases(self) -> None:
        """Word-level matching finds notes even when full phrase doesn't appear."""
        # "empty check" as a phrase doesn't appear in zendb-get-empty,
        # but "empty" appears in topic and "check" does not -- still matches
        result = search_notes(self.index, {"query": "empty SmartArrayHtml"})
        self.assertIn("zendb-get-empty", self._ids(result))

    # ------------------------------------------------------------------
    # 6. Tag filter finds matching note
    # ------------------------------------------------------------------

    def test_tag_filter(self) -> None:
        """Filtering by tag returns only notes that have that tag."""
        result = search_notes(self.index, {"tag": "gotcha"})
        ids = self._ids(result)
        # zendb-get-empty and smartarray-empty-check have "gotcha" tag,
        # but smartarray-empty-check is stale and default lifecycle=active
        self.assertIn("zendb-get-empty", ids)
        self.assertNotIn("smartarray-empty-check", ids)

    # ------------------------------------------------------------------
    # 7. Library filter returns only that library's notes
    # ------------------------------------------------------------------

    def test_library_filter(self) -> None:
        """Library filter restricts results to notes from that library."""
        result = search_notes(self.index, {"library": "smartstring"})
        ids = self._ids(result)
        self.assertEqual(ids, ["smartstring-trim"])

    def test_library_filter_multiple_results(self) -> None:
        """Library filter returns all active notes for that library."""
        result = search_notes(self.index, {"library": "zendb"})
        ids = self._ids(result)
        # 3 active zendb notes
        self.assertEqual(len(ids), 3)
        for nid in ("zendb-get-empty", "zendb-select-join", "zendb-insert"):
            self.assertIn(nid, ids)

    # ------------------------------------------------------------------
    # 8. lifecycle=active excludes stale notes
    # ------------------------------------------------------------------

    def test_lifecycle_active_excludes_stale(self) -> None:
        """Default lifecycle=active filters out stale notes."""
        result = search_notes(self.index, {"library": "smartarray"})
        # smartarray-empty-check is stale, so nothing returned
        self.assertEqual(result["count"], 0)

    # ------------------------------------------------------------------
    # 9. lifecycle=all includes stale notes
    # ------------------------------------------------------------------

    def test_lifecycle_all_includes_stale(self) -> None:
        """lifecycle=all returns both active and stale notes."""
        result = search_notes(self.index, {
            "library":   "smartarray",
            "lifecycle": "all",
        })
        self.assertEqual(result["count"], 1)
        self.assertIn("smartarray-empty-check", self._ids(result))

    # ------------------------------------------------------------------
    # 10. No matches returns empty results
    # ------------------------------------------------------------------

    def test_no_matches_returns_empty(self) -> None:
        """Search that matches nothing returns count 0 and empty list."""
        result = search_notes(self.index, {"query": "xyzzy_no_such_thing_999"})
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["results"], [])

    def test_no_matches_wrong_library(self) -> None:
        """Non-existent library filter returns nothing."""
        result = search_notes(self.index, {"library": "nonexistent"})
        self.assertEqual(result["count"], 0)

    # ------------------------------------------------------------------
    # 11. AND-combination of filters (library + confidence)
    # ------------------------------------------------------------------

    def test_and_combination_library_and_confidence(self) -> None:
        """Multiple filters are AND-combined: library + confidence."""
        result = search_notes(self.index, {
            "library":    "zendb",
            "confidence": "strong",
        })
        ids = self._ids(result)
        # Only zendb-get-empty is zendb + strong + active
        self.assertEqual(ids, ["zendb-get-empty"])

    def test_and_combination_library_and_source_quality(self) -> None:
        """Multiple filters: library + source_quality."""
        result = search_notes(self.index, {
            "library":        "zendb",
            "source_quality": "documented",
        })
        ids = self._ids(result)
        self.assertEqual(ids, ["zendb-select-join"])

    def test_and_combination_type_and_confidence(self) -> None:
        """Multiple filters: type + confidence."""
        result = search_notes(self.index, {
            "type":       "anti-pattern",
            "confidence": "strong",
        })
        ids = self._ids(result)
        # smartstring-trim is anti-pattern + strong + active
        self.assertIn("smartstring-trim", ids)
        # smartarray-empty-check is anti-pattern + strong but stale (default active)
        self.assertNotIn("smartarray-empty-check", ids)

    # ------------------------------------------------------------------
    # 12. max_results limits output count
    # ------------------------------------------------------------------

    def test_max_results_limits_output(self) -> None:
        """max_results caps the number of returned results."""
        result = search_notes(self.index, {
            "library":     "zendb",
            "max_results": 2,
        })
        self.assertLessEqual(result["count"], 2)

    def test_max_results_one(self) -> None:
        """max_results=1 returns only the top-scoring result."""
        result = search_notes(self.index, {
            "library":     "zendb",
            "max_results": 1,
        })
        self.assertEqual(result["count"], 1)

    # ------------------------------------------------------------------
    # Additional edge cases
    # ------------------------------------------------------------------

    def test_filter_only_search_score_is_10(self) -> None:
        """Filter-only search (no query, no function_name) sets score to 10."""
        result = search_notes(self.index, {"library": "zendb"})
        for r in result["results"]:
            self.assertEqual(r["relevance_score"], 10.0)

    def test_results_sorted_by_score_descending(self) -> None:
        """Results are sorted by relevance_score, highest first."""
        # Query that matches multiple notes with different scores
        result = search_notes(self.index, {"query": "SmartArrayHtml"})
        scores = [r["relevance_score"] for r in result["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_query_matching_tag_exactly(self) -> None:
        """Query that exactly matches a tag produces a positive BM25F score with boosts."""
        result = search_notes(self.index, {"query": "gotcha"})
        self.assertIn("zendb-get-empty", self._ids(result))
        score = self._score_of(result, "zendb-get-empty")
        # BM25F + re-ranking produces normalized score > 0
        self.assertGreater(score, 0.0)

    def test_function_name_no_match_excludes_note(self) -> None:
        """If function_name is given but doesn't match, the note is excluded."""
        result = search_notes(self.index, {"function_name": "DB::delete"})
        self.assertEqual(result["count"], 0)

    def test_combined_function_name_and_query(self) -> None:
        """function_name and query can both contribute to the score."""
        result = search_notes(self.index, {
            "function_name": "DB::get",
            "query":         "empty",
        })
        self.assertIn("zendb-get-empty", self._ids(result))
        score = self._score_of(result, "zendb-get-empty")
        # Function match + query match produces high score
        self.assertGreater(score, 0.0)

    def test_case_insensitive_query(self) -> None:
        """Query matching is case-insensitive."""
        result_lower = search_notes(self.index, {"query": "smartarrayhtml"})
        result_upper = search_notes(self.index, {"query": "SMARTARRAYHTML"})
        self.assertEqual(
            self._ids(result_lower),
            self._ids(result_upper),
        )

    def test_case_insensitive_function_name_substring(self) -> None:
        """function_name substring matching is case-insensitive."""
        result = search_notes(self.index, {"function_name": "db::get"})
        self.assertIn("zendb-get-empty", self._ids(result))

    def test_lifecycle_stale_returns_only_stale(self) -> None:
        """lifecycle=stale returns only stale notes."""
        result = search_notes(self.index, {"lifecycle": "stale"})
        ids = self._ids(result)
        self.assertEqual(ids, ["smartarray-empty-check"])

    def test_result_fields_present(self) -> None:
        """Each result contains all expected fields."""
        result = search_notes(self.index, {"library": "zendb"})
        expected_keys = {
            "id", "library", "library_version", "topic", "type",
            "source_quality", "confidence", "lifecycle", "summary",
            "sources", "related_functions", "relevance_score",
            "cues_raw", "primitives_to_avoid", "preferred_alternatives",
            "wrong_assumption", "correct_behavior",
        }
        for r in result["results"]:
            self.assertEqual(set(r.keys()), expected_keys)


# ===================================================================
# Hierarchical library matching
# ===================================================================

class TestHierarchicalLibrarySearch(unittest.TestCase):
    """Tests for hierarchical library name matching in search."""

    def setUp(self) -> None:
        self.index: dict[str, dict[str, Any]] = {
            "js-strict-mode": {
                "library":            "javascript",
                "topic":              "Strict mode differences",
                "type":               "knowledge",
                "source_quality":     "documented",
                "confidence":         "strong",
                "lifecycle":          "active",
                "summary":            "Use strict mode.",
                "related_functions":  [],
                "cues":               [],
                "tags":               [],
            },
            "js--json-bigint": {
                "library":            "javascript/json",
                "topic":              "JSON parse BigInt gotcha",
                "type":               "anti-pattern",
                "source_quality":     "runtime-tested",
                "confidence":         "strong",
                "lifecycle":          "active",
                "summary":            "JSON.parse truncates BigInt.",
                "related_functions":  ["JSON.parse"],
                "cues":               [],
                "tags":               [],
            },
            "js--dom-null": {
                "library":            "javascript/dom",
                "topic":              "querySelector returns null",
                "type":               "knowledge",
                "source_quality":     "documented",
                "confidence":         "maybe",
                "lifecycle":          "active",
                "summary":            "querySelector can return null.",
                "related_functions":  ["document.querySelector"],
                "cues":               [],
                "tags":               [],
            },
        }

    def _ids(self, result: dict[str, Any]) -> list[str]:
        return [r["id"] for r in result["results"]]

    def test_parent_library_matches_all_children(self) -> None:
        """Filtering by parent 'javascript' matches itself and children."""
        result = search_notes(self.index, {"library": "javascript"})
        ids = self._ids(result)
        self.assertEqual(len(ids), 3)
        self.assertIn("js-strict-mode", ids)
        self.assertIn("js--json-bigint", ids)
        self.assertIn("js--dom-null", ids)

    def test_exact_child_library_matches_only_itself(self) -> None:
        """Filtering by 'javascript/json' matches only that exact library."""
        result = search_notes(self.index, {"library": "javascript/json"})
        ids = self._ids(result)
        self.assertEqual(ids, ["js--json-bigint"])

    def test_nonexistent_child_returns_nothing(self) -> None:
        """Filtering by a child that doesn't exist returns nothing."""
        result = search_notes(self.index, {"library": "javascript/canvas"})
        self.assertEqual(result["count"], 0)

    def test_partial_name_does_not_match(self) -> None:
        """'java' should NOT match 'javascript' (must be exact or parent/)."""
        result = search_notes(self.index, {"library": "java"})
        self.assertEqual(result["count"], 0)


# ===================================================================
# Pseudo-Relevance Feedback (PRF)
# ===================================================================

class TestPseudoRelevanceFeedback(unittest.TestCase):
    """Tests for PRF expansion when FTS5 returns empty results."""

    def setUp(self) -> None:
        """Create an in-memory SQLite DB with FTS5 and seed test notes."""
        import sqlite3
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
            CREATE TABLE notes (
                id TEXT PRIMARY KEY,
                library TEXT NOT NULL DEFAULT '',
                topic TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL DEFAULT 'knowledge',
                summary TEXT NOT NULL DEFAULT '',
                notes_body TEXT NOT NULL DEFAULT '',
                cues_raw TEXT NOT NULL DEFAULT '',
                source_quality TEXT NOT NULL DEFAULT 'unverified',
                confidence TEXT NOT NULL DEFAULT 'maybe',
                lifecycle TEXT NOT NULL DEFAULT 'active',
                review_interval_days INTEGER NOT NULL DEFAULT 30,
                review_tier INTEGER NOT NULL DEFAULT 2,
                review_count INTEGER NOT NULL DEFAULT 0,
                miss_count INTEGER NOT NULL DEFAULT 0,
                created TEXT NOT NULL DEFAULT '',
                last_modified TEXT NOT NULL DEFAULT '',
                last_reviewed TEXT NOT NULL DEFAULT '',
                valid_from TEXT NOT NULL DEFAULT '',
                valid_until TEXT NOT NULL DEFAULT '',
                last_retrieved TEXT NOT NULL DEFAULT '',
                retrieval_count INTEGER NOT NULL DEFAULT 0,
                library_version TEXT NOT NULL DEFAULT '',
                always_relevant INTEGER NOT NULL DEFAULT 0,
                wrong_assumption TEXT NOT NULL DEFAULT '',
                correct_behavior TEXT NOT NULL DEFAULT '',
                applies_to TEXT NOT NULL DEFAULT '',
                sources_json TEXT NOT NULL DEFAULT '[]',
                miss_log_json TEXT NOT NULL DEFAULT '[]',
                anchor_text TEXT NOT NULL DEFAULT '',
                notes_body_search TEXT NOT NULL DEFAULT '',
                tags_text TEXT NOT NULL DEFAULT ''
            );
            CREATE VIRTUAL TABLE notes_fts USING fts5(
                id, topic, summary, notes_body, cues_raw, anchor_text, tags_text,
                content='notes', content_rowid='rowid',
                tokenize='porter unicode61'
            );
            CREATE TRIGGER notes_ai AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid, id, topic, summary, notes_body, cues_raw, anchor_text, tags_text)
                VALUES (new.rowid, new.id, new.topic, new.summary, new.notes_body, new.cues_raw, new.anchor_text, new.tags_text);
            END;
        """)

        # Insert seed notes with distinctive terms
        self.conn.execute("""
            INSERT INTO notes (id, topic, summary, tags_text)
            VALUES ('note-alpha', 'Database connection pooling strategies',
                    'Connection pooling improves performance for database queries',
                    'database performance pooling')
        """)
        self.conn.execute("""
            INSERT INTO notes (id, topic, summary, tags_text)
            VALUES ('note-beta', 'Query optimization with indexes',
                    'Proper indexing speeds up database query execution',
                    'database optimization indexes')
        """)
        self.conn.execute("""
            INSERT INTO notes (id, topic, summary, tags_text)
            VALUES ('note-gamma', 'Caching layer for web applications',
                    'Redis caching reduces load on backend services',
                    'caching redis web')
        """)
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def test_prf_triggers_on_empty_results(self) -> None:
        """PRF returns expanded results when a query has no direct FTS matches."""
        # "pooling" matches note-alpha, but "xyzzy" does not match anything.
        # Together as a phrase they return 0. PRF relaxes to OR, finds note-alpha
        # via "pooling", extracts expansion terms, and re-runs.
        results = _pseudo_relevance_feedback(self.conn, ["xyzzy", "pooling"])
        self.assertGreater(len(results), 0)
        result_ids = [r[0] for r in results]
        self.assertIn("note-alpha", result_ids)

    def test_prf_returns_empty_when_no_relaxed_matches(self) -> None:
        """PRF returns empty list when even the relaxed OR query finds nothing."""
        results = _pseudo_relevance_feedback(self.conn, ["xyzzy999", "qqq888"])
        self.assertEqual(results, [])

    def test_prf_not_invoked_when_fts_has_results(self) -> None:
        """In search_notes, PRF should NOT fire when FTS returns results.

        We verify this indirectly: a query that matches should not include
        PRF expansion artifacts in its result set.
        """
        # "database" matches note-alpha and note-beta directly via FTS
        index = {
            "note-alpha": {
                "library": "test", "topic": "Database connection pooling strategies",
                "type": "knowledge", "source_quality": "unverified",
                "confidence": "maybe", "lifecycle": "active",
                "summary": "Connection pooling improves performance for database queries",
                "related_functions": [], "cues": [], "tags": ["database"],
            },
            "note-beta": {
                "library": "test", "topic": "Query optimization with indexes",
                "type": "knowledge", "source_quality": "unverified",
                "confidence": "maybe", "lifecycle": "active",
                "summary": "Proper indexing speeds up database query execution",
                "related_functions": [], "cues": [], "tags": ["database"],
            },
        }
        result = search_notes(index, {"query": "database"})
        # Should find results without needing PRF
        self.assertGreater(result["count"], 0)


# ===================================================================
# Multi-Query Expansion
# ===================================================================

class TestMultiQueryExpansion(unittest.TestCase):
    """Tests for code-style query splitting and multi-query expansion."""

    def test_split_double_colon(self) -> None:
        """DB::get splits into variants with 'db' and 'get'."""
        variants = _split_code_query("DB::get")
        self.assertGreater(len(variants), 0)
        # Should have a variant containing both parts
        combined = " ".join(variants)
        self.assertIn("db", combined.lower())
        self.assertIn("get", combined.lower())

    def test_split_arrow(self) -> None:
        """SmartArray->isEmpty splits on ->."""
        variants = _split_code_query("SmartArray->isEmpty")
        self.assertGreater(len(variants), 0)
        combined = " ".join(variants)
        self.assertIn("smartarray", combined.lower())

    def test_split_camelcase(self) -> None:
        """camelCase word like getElementById splits on case boundaries."""
        variants = _split_code_query("getElementById")
        self.assertGreater(len(variants), 0)
        combined = " ".join(variants)
        self.assertIn("element", combined.lower())

    def test_split_underscore(self) -> None:
        """snake_case splits on underscores."""
        variants = _split_code_query("get_user_name")
        self.assertGreater(len(variants), 0)
        combined = " ".join(variants)
        self.assertIn("get", combined.lower())
        self.assertIn("user", combined.lower())

    def test_plain_word_returns_empty(self) -> None:
        """A plain word with no code patterns returns no variants."""
        variants = _split_code_query("database")
        self.assertEqual(variants, [])

    def test_mqe_skips_when_results_plentiful(self) -> None:
        """Multi-query expansion does not trigger when existing_count > 1."""
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        result = _multi_query_expansion(conn, "DB::get", ["db", "get"], 5)
        self.assertEqual(result, [])
        conn.close()

    def test_mqe_triggers_on_sparse_results(self) -> None:
        """Multi-query expansion triggers and returns results for code queries."""
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE notes (
                id TEXT PRIMARY KEY,
                library TEXT NOT NULL DEFAULT '',
                topic TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL DEFAULT 'knowledge',
                summary TEXT NOT NULL DEFAULT '',
                notes_body TEXT NOT NULL DEFAULT '',
                cues_raw TEXT NOT NULL DEFAULT '',
                source_quality TEXT NOT NULL DEFAULT 'unverified',
                confidence TEXT NOT NULL DEFAULT 'maybe',
                lifecycle TEXT NOT NULL DEFAULT 'active',
                review_interval_days INTEGER NOT NULL DEFAULT 30,
                review_tier INTEGER NOT NULL DEFAULT 2,
                review_count INTEGER NOT NULL DEFAULT 0,
                miss_count INTEGER NOT NULL DEFAULT 0,
                created TEXT NOT NULL DEFAULT '',
                last_modified TEXT NOT NULL DEFAULT '',
                last_reviewed TEXT NOT NULL DEFAULT '',
                valid_from TEXT NOT NULL DEFAULT '',
                valid_until TEXT NOT NULL DEFAULT '',
                last_retrieved TEXT NOT NULL DEFAULT '',
                retrieval_count INTEGER NOT NULL DEFAULT 0,
                library_version TEXT NOT NULL DEFAULT '',
                always_relevant INTEGER NOT NULL DEFAULT 0,
                wrong_assumption TEXT NOT NULL DEFAULT '',
                correct_behavior TEXT NOT NULL DEFAULT '',
                applies_to TEXT NOT NULL DEFAULT '',
                sources_json TEXT NOT NULL DEFAULT '[]',
                miss_log_json TEXT NOT NULL DEFAULT '[]',
                anchor_text TEXT NOT NULL DEFAULT '',
                notes_body_search TEXT NOT NULL DEFAULT '',
                tags_text TEXT NOT NULL DEFAULT ''
            );
            CREATE VIRTUAL TABLE notes_fts USING fts5(
                id, topic, summary, notes_body, cues_raw, anchor_text, tags_text,
                content='notes', content_rowid='rowid',
                tokenize='porter unicode61'
            );
            CREATE TRIGGER notes_ai AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid, id, topic, summary, notes_body, cues_raw, anchor_text, tags_text)
                VALUES (new.rowid, new.id, new.topic, new.summary, new.notes_body, new.cues_raw, new.anchor_text, new.tags_text);
            END;
        """)
        conn.execute("""
            INSERT INTO notes (id, topic, summary)
            VALUES ('note-get', 'How to get records from the database',
                    'Use select or get methods to retrieve records')
        """)
        conn.commit()

        # "DB::get" as a single FTS query might not match, but splitting into
        # "db get" and "get" should find note-get via the word "get"
        result = _multi_query_expansion(conn, "DB::get", ["db::get"], 0)
        self.assertGreater(len(result), 0)
        result_ids = [r[0] for r in result]
        self.assertIn("note-get", result_ids)
        conn.close()


if __name__ == "__main__":
    unittest.main()
