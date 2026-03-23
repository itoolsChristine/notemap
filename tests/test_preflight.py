"""Tests for the notemap preflight session-start loading module."""
from __future__ import annotations

import sys
import os
import unittest
from typing import Any

# Add the module directory to sys.path so we can import it directly.
_MODULE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "src", "notemap-mcp"
)
sys.path.insert(0, os.path.normpath(_MODULE_DIR))

from preflight import (  # noqa: E402
    preflight_notes, _check_version_compat, _parse_version_tuple,
    _tier_for_type, _build_tier_entry, _ALL_TYPES,
)


def _make_index() -> dict[str, dict[str, Any]]:
    """Build a mock note index with notes across multiple
    libraries including _cross-cutting, plus a stale note for filtering tests.
    """
    return {
        # -- zendb: 2 knowledge, 1 anti-pattern --
        "zendb-get-empty": {
            "library":            "zendb",
            "library_version":    "",
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
        "zendb-select-join": {
            "library":            "zendb",
            "library_version":    "",
            "topic":              "ZenDB join keys are table-prefixed",
            "type":               "knowledge",
            "source_quality":     "documented",
            "confidence":         "maybe",
            "lifecycle":          "active",
            "summary":            "Joined columns come back as table.column keys.",
            "notes":              "Access with $row['users.name'] syntax.",
            "related_functions":  ["DB::select"],
            "cues":               [],
            "tags":               ["zendb"],
        },
        "zendb-no-empty": {
            "library":            "zendb",
            "library_version":    "",
            "topic":              "Never use empty() on ZenDB results",
            "type":               "anti-pattern",
            "source_quality":     "verified-from-source",
            "confidence":         "strong",
            "lifecycle":          "active",
            "summary":            "empty() always false on objects. Use ->isEmpty().",
            "notes":              "PHP empty() is always false on objects.",
            "related_functions":  ["DB::get", "DB::select"],
            "primitives_to_avoid":    ["\\bempty\\("],
            "preferred_alternatives": ["->isEmpty()"],
            "tags":               ["zendb", "anti-pattern"],
        },
        # -- smartstring: 1 anti-pattern --
        "smartstring-trim": {
            "library":            "smartstring",
            "library_version":    "",
            "topic":              "Use SmartString trim method not PHP trim",
            "type":               "anti-pattern",
            "source_quality":     "runtime-tested",
            "confidence":         "strong",
            "lifecycle":          "active",
            "summary":            "Use ->trim() on SmartString, not PHP trim().",
            "notes":              "PHP trim() acts on encoded output.",
            "related_functions":  ["SmartString::trim", "SmartString::value"],
            "primitives_to_avoid":    ["\\btrim\\(\\s*\\$"],
            "preferred_alternatives": ["->trim()"],
            "tags":               ["smartstring", "anti-pattern"],
        },
        # -- smartarray: 1 correction (active), 1 stale --
        "smartarray-strict-compare": {
            "library":            "smartarray",
            "library_version":    "",
            "topic":              "Strict comparison fails on SmartString elements",
            "type":               "correction",
            "source_quality":     "user-correction",
            "confidence":         "strong",
            "lifecycle":          "active",
            "summary":            "Use ->value() before strict comparison.",
            "notes":              "Strict === always fails between string and SmartString.",
            "wrong_assumption":   "=== works directly on SmartString",
            "correct_behavior":   "Extract with ->value() first, then compare",
            "related_functions":  ["SmartString::value"],
            "tags":               ["smartarray", "correction"],
        },
        "smartarray-stale-note": {
            "library":            "smartarray",
            "library_version":    "",
            "topic":              "Old SmartArray iteration note",
            "type":               "knowledge",
            "source_quality":     "unverified",
            "confidence":         "weak",
            "lifecycle":          "stale",
            "summary":            "Stale note that should be excluded.",
            "notes":              "This should never appear in preflight results.",
            "related_functions":  [],
            "cues":               [],
            "tags":               ["smartarray"],
        },
        # -- _cross-cutting: 1 convention --
        "cross-cutting-naming": {
            "library":            "_cross-cutting",
            "library_version":    "",
            "topic":              "Use camelCase for local variables",
            "type":               "convention",
            "source_quality":     "documented",
            "confidence":         "strong",
            "lifecycle":          "active",
            "summary":            "Local variables use camelCase, not snake_case.",
            "notes":              "Project convention for all PHP code.",
            "applies_to":        "All PHP files",
            "related_functions":  [],
            "tags":               ["convention"],
        },
        # -- versioned notes for version filtering tests --
        "zendb-v2-feature": {
            "library":            "zendb",
            "library_version":    ">=2.0",
            "topic":              "ZenDB v2 introduced named placeholders",
            "type":               "knowledge",
            "source_quality":     "documented",
            "confidence":         "strong",
            "lifecycle":          "active",
            "summary":            "Named :param placeholders available since v2.0.",
            "notes":              "Use :name instead of ? for clarity.",
            "related_functions":  ["DB::select"],
            "cues":               ["When were named placeholders added?"],
            "tags":               ["zendb"],
        },
        "zendb-v1-only": {
            "library":            "zendb",
            "library_version":    "<2.0",
            "topic":              "ZenDB v1 only supports positional placeholders",
            "type":               "knowledge",
            "source_quality":     "documented",
            "confidence":         "strong",
            "lifecycle":          "active",
            "summary":            "Only ? positional placeholders in v1.",
            "notes":              "Named placeholders not supported before v2.",
            "related_functions":  ["DB::select"],
            "cues":               ["What placeholders does ZenDB v1 support?"],
            "tags":               ["zendb"],
        },
    }


class TestPreflightBasic(unittest.TestCase):
    """Core preflight functionality tests."""

    def setUp(self) -> None:
        self.index = _make_index()

    # ------------------------------------------------------------------
    # 1. Single library returns correct notes
    # ------------------------------------------------------------------

    def test_single_library_returns_correct_notes(self) -> None:
        """Loading a single library returns only that library's active notes."""
        result = preflight_notes(self.index, {
            "libraries":            ["smartstring"],
            "include_cross_cutting": False,
        })
        # smartstring has 1 anti-pattern -> watch_out tier
        self.assertEqual(result["summary"]["total_notes"], 1)
        ids = [n["id"] for n in result["tiers"]["watch_out"]]
        self.assertEqual(ids, ["smartstring-trim"])
        self.assertEqual(result["tiers"]["know_this"], [])
        self.assertEqual(result["tiers"]["reference"], [])

    # ------------------------------------------------------------------
    # 2. Multi-library combines correctly
    # ------------------------------------------------------------------

    def test_multi_library_combined(self) -> None:
        """Multiple libraries are combined into a single result."""
        result = preflight_notes(self.index, {
            "libraries":            ["zendb", "smartstring"],
            "include_cross_cutting": False,
        })
        # zendb: 2 knowledge + 1 anti-pattern + 2 versioned knowledge = 5
        # smartstring: 1 anti-pattern
        # Total = 6
        self.assertEqual(result["summary"]["total_notes"], 6)
        all_libs = set()
        for tier_name in ("watch_out", "know_this", "reference"):
            for note in result["tiers"][tier_name]:
                all_libs.add(note["library"])
        self.assertEqual(all_libs, {"zendb", "smartstring"})

    # ------------------------------------------------------------------
    # 3. Anti-patterns section populated before knowledge
    # ------------------------------------------------------------------

    def test_anti_patterns_in_watch_out_tier(self) -> None:
        """Anti-pattern notes appear in watch_out tier, not know_this."""
        result = preflight_notes(self.index, {
            "libraries":            ["zendb", "smartstring"],
            "include_cross_cutting": False,
        })
        wo_ids = {n["id"] for n in result["tiers"]["watch_out"]}
        kt_ids = {n["id"] for n in result["tiers"]["know_this"]}
        self.assertIn("zendb-no-empty", wo_ids)
        self.assertIn("smartstring-trim", wo_ids)
        # Anti-pattern notes must NOT appear in know_this tier
        self.assertNotIn("zendb-no-empty", kt_ids)
        self.assertNotIn("smartstring-trim", kt_ids)

    # ------------------------------------------------------------------
    # 4. function_index built correctly
    # ------------------------------------------------------------------

    def test_function_index_maps_correctly(self) -> None:
        """function_index maps function names to note IDs that reference them."""
        result = preflight_notes(self.index, {
            "libraries":            ["zendb"],
            "include_cross_cutting": False,
        })
        fi = result["function_index"]
        # DB::get is referenced by zendb-get-empty and zendb-no-empty
        self.assertIn("DB::get", fi)
        self.assertIn("zendb-get-empty", fi["DB::get"])
        self.assertIn("zendb-no-empty", fi["DB::get"])
        # DB::select is referenced by zendb-select-join, zendb-no-empty,
        # zendb-v2-feature, zendb-v1-only
        self.assertIn("DB::select", fi)
        self.assertIn("zendb-select-join", fi["DB::select"])

    # ------------------------------------------------------------------
    # 5. include_cross_cutting=True (default) includes _cross-cutting
    # ------------------------------------------------------------------

    def test_cross_cutting_included_by_default(self) -> None:
        """_cross-cutting notes are included when include_cross_cutting is True (default)."""
        result = preflight_notes(self.index, {
            "libraries": ["zendb"],
        })
        kt_ids = [n["id"] for n in result["tiers"]["know_this"]]
        self.assertIn("cross-cutting-naming", kt_ids)
        self.assertIn("_cross-cutting", result["summary"]["libraries_loaded"])

    # ------------------------------------------------------------------
    # 6. include_cross_cutting=False excludes _cross-cutting
    # ------------------------------------------------------------------

    def test_cross_cutting_excluded_when_false(self) -> None:
        """_cross-cutting notes are excluded when include_cross_cutting=False."""
        result = preflight_notes(self.index, {
            "libraries":            ["zendb"],
            "include_cross_cutting": False,
        })
        kt_ids = [n["id"] for n in result["tiers"]["know_this"]]
        self.assertNotIn("cross-cutting-naming", kt_ids)
        self.assertNotIn("_cross-cutting", result["summary"]["libraries_loaded"])

    # ------------------------------------------------------------------
    # 7. Empty library list returns empty results
    # ------------------------------------------------------------------

    def test_empty_library_list(self) -> None:
        """Empty libraries list returns empty results without errors."""
        result = preflight_notes(self.index, {
            "libraries":            [],
            "include_cross_cutting": False,
        })
        self.assertEqual(result["summary"]["total_notes"], 0)
        self.assertEqual(result["tiers"]["watch_out"], [])
        self.assertEqual(result["tiers"]["know_this"], [])
        self.assertEqual(result["tiers"]["reference"], [])
        self.assertEqual(result["function_index"], {})

    # ------------------------------------------------------------------
    # 8. Nonexistent library returns empty results
    # ------------------------------------------------------------------

    def test_nonexistent_library(self) -> None:
        """A library that has no notes returns empty results without errors."""
        result = preflight_notes(self.index, {
            "libraries":            ["nonexistent-lib"],
            "include_cross_cutting": False,
        })
        self.assertEqual(result["summary"]["total_notes"], 0)
        self.assertEqual(result["tiers"]["watch_out"], [])

    # ------------------------------------------------------------------
    # 9. Stale notes are excluded
    # ------------------------------------------------------------------

    def test_stale_notes_excluded(self) -> None:
        """Notes with lifecycle='stale' are not included in preflight output."""
        result = preflight_notes(self.index, {
            "libraries":            ["smartarray"],
            "include_cross_cutting": False,
        })
        all_ids = set()
        for tier_name in ("watch_out", "know_this", "reference"):
            for note in result["tiers"][tier_name]:
                all_ids.add(note["id"])
        self.assertNotIn("smartarray-stale-note", all_ids)
        # smartarray has 1 active correction, stale note excluded
        self.assertEqual(result["summary"]["total_notes"], 1)

    # ------------------------------------------------------------------
    # 10. Compliance string format
    # ------------------------------------------------------------------

    def test_compliance_string_format(self) -> None:
        """Compliance string matches 'lib/N, lib/N -- N anti-patterns' pattern."""
        result = preflight_notes(self.index, {
            "libraries":            ["zendb", "smartstring"],
            "include_cross_cutting": False,
        })
        compliance = result["summary"]["compliance"]
        # Should contain library counts and anti-pattern highlights
        self.assertIn("zendb/", compliance)
        self.assertIn("smartstring/", compliance)
        self.assertIn("anti-pattern", compliance)
        self.assertIn("--", compliance)

    # ------------------------------------------------------------------
    # 11. Summary counts are correct
    # ------------------------------------------------------------------

    def test_summary_counts_correct(self) -> None:
        """total_notes and by_type counts match actual tier totals."""
        result = preflight_notes(self.index, {
            "libraries":            ["zendb", "smartarray", "smartstring"],
            "include_cross_cutting": False,
        })
        s = result["summary"]
        tier_total = sum(len(t) for t in result["tiers"].values())
        self.assertEqual(s["total_notes"], tier_total)
        # by_type should have all 8 recognized types
        self.assertEqual(len(s["by_type"]), 8)
        # Spot-check counts against tier contents
        ap_count = sum(1 for n in result["tiers"]["watch_out"] if n["type"] == "anti-pattern")
        self.assertEqual(s["by_type"]["anti-pattern"], ap_count)
        corr_count = sum(1 for n in result["tiers"]["watch_out"] if n["type"] == "correction")
        self.assertEqual(s["by_type"]["correction"], corr_count)

    # ------------------------------------------------------------------
    # 12. libraries_loaded is sorted
    # ------------------------------------------------------------------

    def test_libraries_loaded_sorted(self) -> None:
        """libraries_loaded list is alphabetically sorted."""
        result = preflight_notes(self.index, {
            "libraries":            ["zendb", "smartarray", "smartstring"],
            "include_cross_cutting": True,
        })
        loaded = result["summary"]["libraries_loaded"]
        self.assertEqual(loaded, sorted(loaded))
        # Verify all requested libraries with active notes are present
        self.assertIn("zendb", loaded)
        self.assertIn("smartarray", loaded)
        self.assertIn("smartstring", loaded)
        self.assertIn("_cross-cutting", loaded)


class TestPreflightVersionFiltering(unittest.TestCase):
    """Version compatibility filtering tests."""

    def setUp(self) -> None:
        self.index = _make_index()

    # ------------------------------------------------------------------
    # 13. Version filtering - compatible notes kept
    # ------------------------------------------------------------------

    def test_version_compatible_kept(self) -> None:
        """Notes with compatible version specs are included."""
        result = preflight_notes(self.index, {
            "libraries":            ["zendb"],
            "include_cross_cutting": False,
            "versions":             {"zendb": "3.0"},
        })
        k_ids = [n["id"] for n in result["tiers"]["know_this"]]
        # >=2.0 is compatible with 3.0
        self.assertIn("zendb-v2-feature", k_ids)

    # ------------------------------------------------------------------
    # 14. Version filtering - incompatible notes excluded
    # ------------------------------------------------------------------

    def test_version_incompatible_excluded(self) -> None:
        """Notes with incompatible version specs are excluded."""
        result = preflight_notes(self.index, {
            "libraries":            ["zendb"],
            "include_cross_cutting": False,
            "versions":             {"zendb": "3.0"},
        })
        k_ids = [n["id"] for n in result["tiers"]["know_this"]]
        # <2.0 is incompatible with 3.0
        self.assertNotIn("zendb-v1-only", k_ids)

    # ------------------------------------------------------------------
    # 15. Empty library_version always included
    # ------------------------------------------------------------------

    def test_empty_library_version_always_included(self) -> None:
        """Notes with empty library_version pass version filtering."""
        result = preflight_notes(self.index, {
            "libraries":            ["zendb"],
            "include_cross_cutting": False,
            "versions":             {"zendb": "1.0"},
        })
        k_ids = [n["id"] for n in result["tiers"]["know_this"]]
        # zendb-get-empty and zendb-select-join have library_version=""
        self.assertIn("zendb-get-empty", k_ids)
        self.assertIn("zendb-select-join", k_ids)

    # ------------------------------------------------------------------
    # 16. Omitted versions returns all notes
    # ------------------------------------------------------------------

    def test_omitted_versions_returns_all(self) -> None:
        """When versions param is None/omitted, no version filtering occurs."""
        result = preflight_notes(self.index, {
            "libraries":            ["zendb"],
            "include_cross_cutting": False,
        })
        k_ids = [n["id"] for n in result["tiers"]["know_this"]]
        # Both versioned notes should be present since no filtering
        self.assertIn("zendb-v2-feature", k_ids)
        self.assertIn("zendb-v1-only", k_ids)

    # ------------------------------------------------------------------
    # 17. Version comparison >=
    # ------------------------------------------------------------------

    def test_version_compat_gte(self) -> None:
        """'>=2.6.2' with project '3.0' passes."""
        self.assertTrue(_check_version_compat(">=2.6.2", "3.0"))
        self.assertTrue(_check_version_compat(">=2.6.2", "2.6.2"))
        self.assertFalse(_check_version_compat(">=2.6.2", "2.6.1"))
        self.assertFalse(_check_version_compat(">=2.6.2", "1.0"))

    # ------------------------------------------------------------------
    # 18. Version comparison <
    # ------------------------------------------------------------------

    def test_version_compat_lt(self) -> None:
        """'<2.0' with project '3.0' is excluded."""
        self.assertFalse(_check_version_compat("<2.0", "3.0"))
        self.assertFalse(_check_version_compat("<2.0", "2.0"))
        self.assertTrue(_check_version_compat("<2.0", "1.9"))
        self.assertTrue(_check_version_compat("<2.0", "1.0"))


class TestPreflightNoteFields(unittest.TestCase):
    """Tests for note-type-specific fields in preflight output."""

    def setUp(self) -> None:
        self.index = _make_index()

    # ------------------------------------------------------------------
    # 19. Knowledge notes include top_cue
    # ------------------------------------------------------------------

    def test_knowledge_notes_include_top_cue(self) -> None:
        """Knowledge notes contain a top_cue field with the first cue."""
        result = preflight_notes(self.index, {
            "libraries":            ["zendb"],
            "include_cross_cutting": False,
        })
        get_empty = None
        for note in result["tiers"]["know_this"]:
            if note["id"] == "zendb-get-empty":
                get_empty = note
                break
        self.assertIsNotNone(get_empty)
        self.assertEqual(
            get_empty["top_cue"],
            "What does DB::get return when no record matches?",
        )

    def test_knowledge_notes_empty_cues_gives_empty_top_cue(self) -> None:
        """Knowledge notes with no cues have an empty top_cue string."""
        result = preflight_notes(self.index, {
            "libraries":            ["zendb"],
            "include_cross_cutting": False,
        })
        select_join = None
        for note in result["tiers"]["know_this"]:
            if note["id"] == "zendb-select-join":
                select_join = note
                break
        self.assertIsNotNone(select_join)
        self.assertEqual(select_join["top_cue"], "")

    # ------------------------------------------------------------------
    # 20. Correction notes include wrong_assumption and correct_behavior
    # ------------------------------------------------------------------

    def test_correction_notes_include_fields(self) -> None:
        """Correction notes contain wrong_assumption and correct_behavior fields."""
        result = preflight_notes(self.index, {
            "libraries":            ["smartarray"],
            "include_cross_cutting": False,
        })
        corrections = [n for n in result["tiers"]["watch_out"] if n["type"] == "correction"]
        self.assertEqual(len(corrections), 1)
        corr = corrections[0]
        self.assertEqual(corr["id"], "smartarray-strict-compare")
        self.assertEqual(corr["wrong_assumption"], "=== works directly on SmartString")
        self.assertEqual(corr["correct_behavior"], "Extract with ->value() first, then compare")


class TestPreflightEdgeCases(unittest.TestCase):
    """Additional edge-case and helper function tests."""

    def setUp(self) -> None:
        self.index = _make_index()

    def test_parse_version_tuple_normal(self) -> None:
        """_parse_version_tuple handles standard dotted versions."""
        self.assertEqual(_parse_version_tuple("1.2.3"), (1, 2, 3))
        self.assertEqual(_parse_version_tuple("3.0"), (3, 0))
        self.assertEqual(_parse_version_tuple("10"), (10,))

    def test_parse_version_tuple_beta_suffix(self) -> None:
        """_parse_version_tuple strips non-numeric suffixes."""
        self.assertEqual(_parse_version_tuple("1.2.3-beta"), (1, 2, 3))

    def test_parse_version_tuple_empty(self) -> None:
        """_parse_version_tuple returns empty tuple for blank input."""
        self.assertEqual(_parse_version_tuple(""), ())

    def test_version_compat_empty_spec_always_true(self) -> None:
        """Empty version spec is always compatible."""
        self.assertTrue(_check_version_compat("", "3.0"))
        self.assertTrue(_check_version_compat("", ""))

    def test_version_compat_no_project_version_always_true(self) -> None:
        """Empty project version always includes the note."""
        self.assertTrue(_check_version_compat(">=2.0", ""))

    def test_version_compat_gt(self) -> None:
        """'>' operator (strictly greater than)."""
        self.assertTrue(_check_version_compat(">1.0", "2.0"))
        self.assertFalse(_check_version_compat(">2.0", "2.0"))

    def test_version_compat_lte(self) -> None:
        """'<=' operator (less than or equal)."""
        self.assertTrue(_check_version_compat("<=3.0", "3.0"))
        self.assertTrue(_check_version_compat("<=3.0", "2.0"))
        self.assertFalse(_check_version_compat("<=3.0", "4.0"))

    def test_version_compat_exact_major_minor(self) -> None:
        """No operator means exact major.minor match."""
        self.assertTrue(_check_version_compat("2.1", "2.1.5"))
        self.assertTrue(_check_version_compat("2.1.0", "2.1.3"))
        self.assertFalse(_check_version_compat("2.1", "2.2"))
        self.assertFalse(_check_version_compat("2.1", "3.1"))

    def test_compliance_no_anti_patterns(self) -> None:
        """Compliance string omits type highlights when there are no anti-patterns or corrections."""
        # smartarray has only a correction, no anti-patterns
        # Build a minimal index with only knowledge notes
        mini_index = {
            "k1": {
                "library":            "mylib",
                "library_version":    "",
                "topic":              "A knowledge note",
                "type":               "knowledge",
                "lifecycle":          "active",
                "summary":            "Just a knowledge note.",
                "related_functions":  [],
                "cues":               [],
            },
        }
        result = preflight_notes(mini_index, {
            "libraries":            ["mylib"],
            "include_cross_cutting": False,
        })
        compliance = result["summary"]["compliance"]
        self.assertEqual(compliance, "mylib/1")
        self.assertNotIn("--", compliance)

    def test_compliance_no_notes(self) -> None:
        """Compliance string says 'no notes' when nothing is loaded."""
        result = preflight_notes(self.index, {
            "libraries":            [],
            "include_cross_cutting": False,
        })
        self.assertEqual(result["summary"]["compliance"], "no notes")

    def test_anti_pattern_fields_present(self) -> None:
        """Anti-pattern notes in watch_out tier include primitives_to_avoid and preferred_alternatives."""
        result = preflight_notes(self.index, {
            "libraries":            ["smartstring"],
            "include_cross_cutting": False,
        })
        ap = result["tiers"]["watch_out"][0]
        self.assertEqual(ap["id"], "smartstring-trim")
        self.assertEqual(ap["type"], "anti-pattern")
        self.assertEqual(ap["primitives_to_avoid"], ["\\btrim\\(\\s*\\$"])
        self.assertEqual(ap["preferred_alternatives"], ["->trim()"])
        self.assertIn("SmartString::trim", ap["related_functions"])

    def test_convention_in_know_this_tier(self) -> None:
        """Convention notes appear in know_this tier with common fields."""
        result = preflight_notes(self.index, {
            "libraries":            ["zendb"],
            "include_cross_cutting": True,
        })
        conventions = [n for n in result["tiers"]["know_this"] if n["type"] == "convention"]
        self.assertEqual(len(conventions), 1)
        self.assertEqual(conventions[0]["id"], "cross-cutting-naming")
        self.assertEqual(conventions[0]["type"], "convention")
        self.assertIn("summary", conventions[0])
        self.assertIn("top_cue", conventions[0])


if __name__ == "__main__":
    unittest.main()
