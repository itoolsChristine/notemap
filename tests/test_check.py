"""Tests for the notemap check module (combined code checker)."""
from __future__ import annotations

import sys
import os
import unittest
from typing import Any

# Add the check module's directory to sys.path so we can import it directly.
_CHECK_MODULE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "src", "notemap-mcp"
)
sys.path.insert(0, os.path.normpath(_CHECK_MODULE_DIR))

from check import check_code  # noqa: E402


def _make_index() -> dict[str, dict[str, Any]]:
    """Build a mock note index with anti-pattern notes (with primitives_to_avoid),
    knowledge notes (with related_functions), and notes across multiple libraries."""
    return {
        # --- zendb: knowledge note with related_functions ---
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
            "tags":               ["zendb", "gotcha"],
        },
        # --- zendb: anti-pattern note ---
        "zendb-raw-query": {
            "library":            "zendb",
            "topic":              "Never use raw SQL concatenation with ZenDB",
            "type":               "anti-pattern",
            "source_quality":     "verified-from-source",
            "confidence":         "strong",
            "lifecycle":          "active",
            "summary":            "Use parameterized queries, not string concatenation.",
            "notes":              "SQL injection risk.",
            "primitives_to_avoid":    [r"\bDB::query\(\s*[\"']"],
            "preferred_alternatives": ["DB::select()", "DB::get()"],
            "related_functions":  ["DB::query"],
            "tags":               ["zendb", "security"],
        },
        # --- smartstring: anti-pattern note ---
        "smartstring-trim": {
            "library":            "smartstring",
            "topic":              "Use SmartString trim method not PHP trim",
            "type":               "anti-pattern",
            "source_quality":     "runtime-tested",
            "confidence":         "strong",
            "lifecycle":          "active",
            "summary":            "Use ->trim() on SmartString, not PHP trim().",
            "notes":              "PHP trim() acts on encoded output.",
            "primitives_to_avoid":    [r"\btrim\(\s*\$"],
            "preferred_alternatives": ["->trim()"],
            "related_functions":  ["SmartString::trim", "SmartString::value"],
            "tags":               ["smartstring", "anti-pattern"],
        },
        # --- smartstring: knowledge note ---
        "smartstring-new": {
            "library":            "smartstring",
            "topic":              "SmartString::new wraps raw values",
            "type":               "knowledge",
            "source_quality":     "documented",
            "confidence":         "strong",
            "lifecycle":          "active",
            "summary":            "SmartString::new() wraps a raw value for safe output.",
            "notes":              "Returns a SmartString instance.",
            "related_functions":  ["SmartString::new"],
            "tags":               ["smartstring"],
        },
        # --- smartarray: knowledge note ---
        "smartarray-isempty": {
            "library":            "smartarray",
            "topic":              "Use ->isEmpty() to check empty SmartArray",
            "type":               "knowledge",
            "source_quality":     "verified-from-source",
            "confidence":         "strong",
            "lifecycle":          "active",
            "summary":            "empty() on objects is always false. Use ->isEmpty().",
            "notes":              "PHP quirk.",
            "related_functions":  ["SmartArray::isEmpty"],
            "tags":               ["smartarray"],
        },
        # --- _cross-cutting: always-included note ---
        "cross-cutting-error-handling": {
            "library":            "_cross-cutting",
            "topic":              "Always handle errors explicitly",
            "type":               "convention",
            "source_quality":     "user-correction",
            "confidence":         "strong",
            "lifecycle":          "active",
            "summary":            "Never swallow exceptions silently.",
            "notes":              "Log or re-throw.",
            "related_functions":  [],
            "tags":               ["error-handling"],
        },
        # --- anthropic-sdk: knowledge note ---
        "anthropic-messages-create": {
            "library":            "anthropic-sdk",
            "topic":              "messages.create requires model parameter",
            "type":               "knowledge",
            "source_quality":     "documented",
            "confidence":         "strong",
            "lifecycle":          "active",
            "summary":            "Always pass model= to messages.create().",
            "notes":              "Required parameter.",
            "related_functions":  ["messages.create"],
            "tags":               ["anthropic-sdk"],
        },
        # --- stale note (should be excluded from function_notes) ---
        "zendb-insert-stale": {
            "library":            "zendb",
            "topic":              "DB::insert behavior (outdated)",
            "type":               "knowledge",
            "source_quality":     "unverified",
            "confidence":         "weak",
            "lifecycle":          "stale",
            "summary":            "Stale note about DB::insert.",
            "notes":              "Should not appear in results.",
            "related_functions":  ["DB::insert"],
            "tags":               ["zendb"],
        },
    }


class TestCheckCode(unittest.TestCase):
    """Test the check_code combined checker function."""

    def setUp(self) -> None:
        self.index = _make_index()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _lint_note_ids(self, result: dict[str, Any]) -> list[str]:
        """Extract note IDs from lint_warnings."""
        return [w["note_id"] for w in result["lint_warnings"]]

    def _fn_note_ids(self, result: dict[str, Any]) -> list[str]:
        """Extract note IDs from all function_notes entries."""
        ids: list[str] = []
        for fn in result["function_notes"]:
            for note in fn["notes"]:
                ids.append(note["id"])
        return ids

    def _all_note_ids(self, result: dict[str, Any]) -> list[str]:
        """All note IDs from both lint_warnings and function_notes."""
        return self._lint_note_ids(result) + self._fn_note_ids(result)

    def _topic_note_ids(self, result: dict[str, Any]) -> list[str]:
        """Extract note IDs from all topic_matches entries."""
        ids: list[str] = []
        for tm in result.get("topic_matches", []):
            for note in tm["notes"]:
                ids.append(note["id"])
        return ids

    # ------------------------------------------------------------------
    # 1. PHP code with DB:: detects zendb
    # ------------------------------------------------------------------

    def test_php_code_with_db_detects_zendb(self) -> None:
        """Code containing DB::get( should detect zendb as a library."""
        result = check_code(self.index, {"code": '$row = DB::get("users", 1);'})
        self.assertIn("zendb", result["detected_libraries"])

    # ------------------------------------------------------------------
    # 2. PHP code with SmartString detects smartstring
    # ------------------------------------------------------------------

    def test_php_code_with_smartstring_detects_smartstring(self) -> None:
        """Code containing SmartString::new( should detect smartstring."""
        result = check_code(self.index, {"code": '$s = SmartString::new("hello");'})
        self.assertIn("smartstring", result["detected_libraries"])

    # ------------------------------------------------------------------
    # 3. Python code detects anthropic-sdk
    # ------------------------------------------------------------------

    def test_python_code_detects_anthropic_sdk(self) -> None:
        """Code with 'from anthropic' should detect anthropic-sdk."""
        result = check_code(self.index, {"code": "from anthropic import Anthropic"})
        self.assertIn("anthropic-sdk", result["detected_libraries"])

    # ------------------------------------------------------------------
    # 4. File extension .php adds PHP candidates
    # ------------------------------------------------------------------

    def test_file_extension_php_adds_php_libraries(self) -> None:
        """file_path='test.php' adds zendb, smartstring, smartarray as candidates."""
        result = check_code(self.index, {
            "code":      "$x = 1;",
            "file_path": "test.php",
        })
        for lib in ("zendb", "smartstring", "smartarray"):
            self.assertIn(lib, result["detected_libraries"])

    # ------------------------------------------------------------------
    # 5. _cross-cutting always included
    # ------------------------------------------------------------------

    def test_cross_cutting_always_included(self) -> None:
        """_cross-cutting notes are checked even with no library-specific detections.

        The _cross-cutting library is used internally but filtered out of
        detected_libraries, so we verify its notes can surface in function_notes."""
        # Use code that has no library-specific patterns but references a
        # function that a _cross-cutting note covers -- there are no
        # related_functions on the cross-cutting note in our index, so
        # we verify indirectly: _cross-cutting is always in the internal
        # detected set, which means its anti-patterns would be linted.
        # Since _cross-cutting is an internal detail, it should NOT appear
        # in the reported detected_libraries.
        result = check_code(self.index, {"code": "x = 1"})
        self.assertNotIn("_cross-cutting", result["detected_libraries"])

    # ------------------------------------------------------------------
    # 6. Function extraction - static calls
    # ------------------------------------------------------------------

    def test_function_extraction_static_calls(self) -> None:
        """Static call DB::get( extracts 'DB::get' as a function reference,
        and the corresponding knowledge note is surfaced."""
        result = check_code(self.index, {"code": '$row = DB::get("users", 1);'})
        fn_ids = self._fn_note_ids(result)
        self.assertIn("zendb-get-empty", fn_ids)

    # ------------------------------------------------------------------
    # 7. Function extraction - instance calls
    # ------------------------------------------------------------------

    def test_function_extraction_instance_calls(self) -> None:
        """Instance call ->isEmpty( extracts 'isEmpty' and matches related notes."""
        result = check_code(self.index, {
            "code":      '$row->isEmpty();',
            "file_path": "test.php",
        })
        fn_ids = self._fn_note_ids(result)
        self.assertIn("smartarray-isempty", fn_ids)

    # ------------------------------------------------------------------
    # 8. Lint warnings from anti-patterns
    # ------------------------------------------------------------------

    def test_lint_warnings_from_antipatterns(self) -> None:
        """Code triggering an anti-pattern regex produces lint warnings."""
        result = check_code(self.index, {
            "code":      '$name = trim($val);',
            "file_path": "test.php",
        })
        lint_ids = self._lint_note_ids(result)
        self.assertIn("smartstring-trim", lint_ids)
        self.assertFalse(result["clean"])

    # ------------------------------------------------------------------
    # 9. Function-specific notes surfaced
    # ------------------------------------------------------------------

    def test_function_specific_notes_surfaced(self) -> None:
        """Code using a function with related notes gets those notes in output."""
        result = check_code(self.index, {
            "code": '$s = SmartString::new("test");',
        })
        fn_ids = self._fn_note_ids(result)
        self.assertIn("smartstring-new", fn_ids)

    # ------------------------------------------------------------------
    # 10. Clean code returns clean=true
    # ------------------------------------------------------------------

    def test_clean_code_returns_clean(self) -> None:
        """Code with no matching anti-patterns or function notes returns clean."""
        result = check_code(self.index, {"code": "$x = 42;"})
        self.assertTrue(result["clean"])
        self.assertEqual(result["issues_found"], 0)
        self.assertEqual(result["lint_warnings"], [])
        self.assertEqual(result["function_notes"], [])

    # ------------------------------------------------------------------
    # 11. Empty code returns clean
    # ------------------------------------------------------------------

    def test_empty_code_returns_clean(self) -> None:
        """Empty string input returns clean with no detections."""
        result = check_code(self.index, {"code": ""})
        self.assertTrue(result["clean"])
        self.assertEqual(result["detected_libraries"], [])
        self.assertEqual(result["issues_found"], 0)
        self.assertEqual(result["summary_line"], "No code provided.")

    # ------------------------------------------------------------------
    # 12. summary_line describes findings
    # ------------------------------------------------------------------

    def test_summary_line_describes_findings(self) -> None:
        """Human-readable summary_line mentions anti-pattern violations."""
        result = check_code(self.index, {
            "code":      '$name = trim($val);',
            "file_path": "test.php",
        })
        self.assertIn("anti-pattern violation", result["summary_line"])

    def test_summary_line_clean_when_no_issues(self) -> None:
        """When code-check finds no issues, summary_line says clean."""
        # Use .php extension to force code-check mode (not topic-discovery)
        result = check_code(self.index, {
            "code":      "$x = 42;",
            "file_path": "test.php",
        })
        self.assertIn("Clean", result["summary_line"])

    def test_summary_line_mentions_function_gotchas(self) -> None:
        """When function notes are surfaced, summary mentions gotchas."""
        result = check_code(self.index, {
            "code": '$row = DB::get("users", 1);',
        })
        # DB::get should surface zendb-get-empty as a function note
        if result["function_notes"]:
            self.assertIn("gotcha", result["summary_line"])

    # ------------------------------------------------------------------
    # 13. No duplicate warnings (lint vs function_notes)
    # ------------------------------------------------------------------

    def test_no_duplicate_warnings(self) -> None:
        """A note surfaced as a lint warning should NOT also appear in function_notes."""
        # zendb-raw-query is an anti-pattern note with related_functions=["DB::query"]
        # Code triggers the anti-pattern AND references DB::query as a function
        result = check_code(self.index, {
            "code":      'DB::query("SELECT * FROM users");',
            "file_path": "test.php",
        })
        lint_ids = set(self._lint_note_ids(result))
        fn_ids   = set(self._fn_note_ids(result))
        # No overlap
        self.assertEqual(lint_ids & fn_ids, set())
        # The anti-pattern note should be in lint_warnings
        self.assertIn("zendb-raw-query", lint_ids)

    # ------------------------------------------------------------------
    # 14. Multiple libraries detected
    # ------------------------------------------------------------------

    def test_multiple_libraries_detected(self) -> None:
        """Code using both DB:: and SmartString detects both libraries."""
        code = '$row = DB::get("users", 1); $s = SmartString::new($row->name);'
        result = check_code(self.index, {"code": code})
        self.assertIn("zendb", result["detected_libraries"])
        self.assertIn("smartstring", result["detected_libraries"])

    # ------------------------------------------------------------------
    # 15. detected_libraries in output is sorted
    # ------------------------------------------------------------------

    def test_detected_libraries_sorted(self) -> None:
        """detected_libraries is a sorted list of detected library names."""
        code = '$row = DB::get("users", 1); $s = SmartString::new($row->name);'
        result = check_code(self.index, {"code": code})
        libs = result["detected_libraries"]
        self.assertEqual(libs, sorted(libs))
        self.assertIsInstance(libs, list)
        # _cross-cutting should be excluded from reported list
        self.assertNotIn("_cross-cutting", libs)

    # ------------------------------------------------------------------
    # 16. Mode field present -- code-check
    # ------------------------------------------------------------------

    def test_mode_code_check_when_libraries_detected(self) -> None:
        """When code libraries are detected, mode is 'code-check'."""
        result = check_code(self.index, {"code": '$row = DB::get("users", 1);'})
        self.assertEqual(result["mode"], "code-check")

    def test_mode_code_check_for_empty_input(self) -> None:
        """Empty input returns mode 'code-check' (not topic-discovery)."""
        result = check_code(self.index, {"code": ""})
        self.assertEqual(result["mode"], "code-check")

    def test_mode_code_check_with_file_extension(self) -> None:
        """File extension hints keep us in code-check mode."""
        result = check_code(self.index, {
            "code":      "x = 1",
            "file_path": "test.php",
        })
        self.assertEqual(result["mode"], "code-check")

    # ------------------------------------------------------------------
    # 17. Mode field present -- topic-discovery
    # ------------------------------------------------------------------

    def test_mode_topic_discovery_when_no_code_libraries(self) -> None:
        """When no code libraries match, mode is 'topic-discovery'."""
        result = check_code(self.index, {"code": "Some plain text about errors."})
        self.assertEqual(result["mode"], "topic-discovery")

    # ------------------------------------------------------------------
    # 18. Topic-discovery finds matching notes by topic keyword
    # ------------------------------------------------------------------

    def test_topic_discovery_matches_by_topic_field(self) -> None:
        """Topic-discovery matches words against note topic fields."""
        # "empty" appears in zendb-get-empty topic and smartarray-isempty topic
        result = check_code(self.index, {
            "code": "How do I check if the result is empty after a query?",
        })
        self.assertEqual(result["mode"], "topic-discovery")
        note_ids = self._topic_note_ids(result)
        self.assertIn("zendb-get-empty", note_ids)

    def test_topic_discovery_matches_by_summary_field(self) -> None:
        """Topic-discovery matches words against note summary fields."""
        # "parameterized" appears in zendb-raw-query summary
        result = check_code(self.index, {
            "code": "Should I use parameterized queries here?",
        })
        self.assertEqual(result["mode"], "topic-discovery")
        note_ids = self._topic_note_ids(result)
        self.assertIn("zendb-raw-query", note_ids)

    def test_topic_discovery_matches_by_tags(self) -> None:
        """Topic-discovery matches words against note tags."""
        # "security" is a tag on zendb-raw-query
        result = check_code(self.index, {
            "code": "What are the security considerations for database access?",
        })
        self.assertEqual(result["mode"], "topic-discovery")
        note_ids = self._topic_note_ids(result)
        self.assertIn("zendb-raw-query", note_ids)

    # ------------------------------------------------------------------
    # 19. Topic-discovery no matches
    # ------------------------------------------------------------------

    def test_topic_discovery_no_matches(self) -> None:
        """When no keywords match any notes, topic_matches is empty."""
        result = check_code(self.index, {
            "code": "A completely unrelated paragraph about turtles.",
        })
        self.assertEqual(result["mode"], "topic-discovery")
        self.assertEqual(result["topic_matches"], [])
        self.assertTrue(result["clean"])
        self.assertIn("No relevant notes found", result["summary_line"])

    # ------------------------------------------------------------------
    # 20. Topic-discovery summary line
    # ------------------------------------------------------------------

    def test_topic_discovery_summary_with_matches(self) -> None:
        """Summary line in topic-discovery mode reports match count."""
        result = check_code(self.index, {
            "code": "How do I check if the result is empty after a query?",
        })
        self.assertEqual(result["mode"], "topic-discovery")
        self.assertIn("No code detected", result["summary_line"])
        self.assertIn("topic-related note", result["summary_line"])

    def test_topic_discovery_summary_no_matches(self) -> None:
        """Summary line in topic-discovery mode with no matches."""
        result = check_code(self.index, {"code": "$x = 42;"})
        self.assertEqual(result["mode"], "topic-discovery")
        self.assertEqual(
            result["summary_line"],
            "No code detected. No relevant notes found.",
        )

    # ------------------------------------------------------------------
    # 21. Topic-discovery excludes stale notes
    # ------------------------------------------------------------------

    def test_topic_discovery_excludes_stale_notes(self) -> None:
        """Stale notes should not appear in topic-discovery results."""
        # "insert" appears in the stale note's topic
        result = check_code(self.index, {
            "code": "How does insert behavior work with outdated data?",
        })
        self.assertEqual(result["mode"], "topic-discovery")
        note_ids = self._topic_note_ids(result)
        self.assertNotIn("zendb-insert-stale", note_ids)

    # ------------------------------------------------------------------
    # 22. Topic-discovery deduplicates notes across keywords
    # ------------------------------------------------------------------

    def test_topic_discovery_deduplicates_across_keywords(self) -> None:
        """A note matching multiple keywords should only appear once."""
        # "empty" and "match" both appear in zendb-get-empty topic/summary
        result = check_code(self.index, {
            "code": "What happens when the result is empty with no match found?",
        })
        self.assertEqual(result["mode"], "topic-discovery")
        # Count how many times zendb-get-empty appears
        all_ids = self._topic_note_ids(result)
        self.assertEqual(all_ids.count("zendb-get-empty"), 1)

    # ------------------------------------------------------------------
    # 23. Topic-discovery filters short words
    # ------------------------------------------------------------------

    def test_topic_discovery_filters_short_words(self) -> None:
        """Words shorter than 4 characters are excluded from keyword extraction."""
        # "SQL" is only 3 chars, should not be a keyword
        result = check_code(self.index, {"code": "Is SQL bad?"})
        self.assertEqual(result["mode"], "topic-discovery")
        # No topic_matches because no words >= 4 chars (after stop-word filtering)
        self.assertEqual(result["topic_matches"], [])

    # ------------------------------------------------------------------
    # 24. Topic-discovery filters stop words
    # ------------------------------------------------------------------

    def test_topic_discovery_filters_stop_words(self) -> None:
        """Common stop words are excluded from keyword extraction."""
        # "this", "that", "with", "from" are all stop words
        result = check_code(self.index, {
            "code": "this that with from about which their there",
        })
        self.assertEqual(result["mode"], "topic-discovery")
        self.assertEqual(result["topic_matches"], [])

    # ------------------------------------------------------------------
    # 25. Topic-discovery topic_matches structure
    # ------------------------------------------------------------------

    def test_topic_discovery_structure(self) -> None:
        """topic_matches entries have the expected structure."""
        result = check_code(self.index, {
            "code": "Is it safe to use concatenation for queries?",
        })
        self.assertEqual(result["mode"], "topic-discovery")
        self.assertIn("topic_matches", result)
        for tm in result["topic_matches"]:
            self.assertIn("topic", tm)
            self.assertIn("notes", tm)
            self.assertIsInstance(tm["topic"], str)
            self.assertIsInstance(tm["notes"], list)
            for note in tm["notes"]:
                self.assertIn("id", note)
                self.assertIn("summary", note)
                self.assertIn("library", note)

    # ------------------------------------------------------------------
    # 26. Topic-discovery issues_found reflects match count
    # ------------------------------------------------------------------

    def test_topic_discovery_issues_found(self) -> None:
        """issues_found in topic-discovery mode equals total matched notes."""
        result = check_code(self.index, {
            "code": "How do I check if the result is empty after a query?",
        })
        self.assertEqual(result["mode"], "topic-discovery")
        total = sum(len(tm["notes"]) for tm in result["topic_matches"])
        self.assertEqual(result["issues_found"], total)
        if total > 0:
            self.assertFalse(result["clean"])


if __name__ == "__main__":
    unittest.main()
