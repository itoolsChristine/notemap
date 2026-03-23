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

from search import search_notes  # noqa: E402


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
        # +100 exact + 10 verified-from-source + 10 strong = 120
        self.assertEqual(self._score_of(result, "zendb-get-empty"), 120.0)

    # ------------------------------------------------------------------
    # 2. Substring function_name match => +50
    # ------------------------------------------------------------------

    def test_function_name_substring_match(self) -> None:
        """Substring match in related_functions scores +50 plus boosts."""
        # "value" is a substring of "SmartString::value"
        result = search_notes(self.index, {"function_name": "value"})
        self.assertEqual(result["count"], 1)
        self.assertIn("smartstring-trim", self._ids(result))
        # +50 substring + 10 strong (runtime-tested is not verified-from-source) = 60
        self.assertEqual(self._score_of(result, "smartstring-trim"), 60.0)

    # ------------------------------------------------------------------
    # 3. Query matching topic => +40
    # ------------------------------------------------------------------

    def test_query_matches_topic(self) -> None:
        """Single word found only in topic field scores +40 (no boosts)."""
        # "prefixed" appears only in the topic, not summary/cues/tags
        result = search_notes(self.index, {"query": "prefixed"})
        self.assertIn("zendb-select-join", self._ids(result))
        # +40 topic (no verified-from-source, no strong confidence) = 40
        self.assertEqual(self._score_of(result, "zendb-select-join"), 40.0)

    # ------------------------------------------------------------------
    # 4. Query matching cue => +30
    # ------------------------------------------------------------------

    def test_query_matches_cue(self) -> None:
        """Query substring found in a cue scores +30."""
        result = search_notes(self.index, {"query": "How to trim a SmartString"})
        self.assertIn("smartstring-trim", self._ids(result))
        score = self._score_of(result, "smartstring-trim")
        # Must include the +30 cue component; could also match topic/summary
        self.assertGreaterEqual(score, 30.0)

    # ------------------------------------------------------------------
    # 5. Query matching summary => +20
    # ------------------------------------------------------------------

    def test_query_matches_summary_only(self) -> None:
        """Single word found only in summary scores +20 (no boosts)."""
        # "auto-increment" appears only in the summary of zendb-insert
        result = search_notes(self.index, {"query": "auto-increment"})
        self.assertIn("zendb-insert", self._ids(result))
        # +20 summary, unverified + weak = no boosts = 20
        self.assertEqual(self._score_of(result, "zendb-insert"), 20.0)

    def test_multi_word_query_matches_more_than_single(self) -> None:
        """Multi-word query scores higher when more words match."""
        # Single word: "trim" matches in topic + summary + cues
        single = search_notes(self.index, {"query": "trim"})
        # Two words: "trim SmartString" -- both words match independently
        multi = search_notes(self.index, {"query": "trim SmartString"})
        self.assertIn("smartstring-trim", self._ids(single))
        self.assertIn("smartstring-trim", self._ids(multi))
        # Multi-word should score higher due to more word hits + bonus
        self.assertGreater(
            self._score_of(multi, "smartstring-trim"),
            self._score_of(single, "smartstring-trim"),
        )

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
        """Query that exactly matches a tag scores +60."""
        result = search_notes(self.index, {"query": "gotcha"})
        self.assertIn("zendb-get-empty", self._ids(result))
        score = self._score_of(result, "zendb-get-empty")
        # +60 tag match, possibly +40 topic, +20 summary, +10 verified, +10 strong
        self.assertGreaterEqual(score, 60.0)

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
        # +100 exact fn + topic/summary/cue matches + boosts
        self.assertGreater(score, 120.0)

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
        }
        for r in result["results"]:
            self.assertEqual(set(r.keys()), expected_keys)


if __name__ == "__main__":
    unittest.main()
