"""Tests for the notemap lint anti-pattern detection."""
from __future__ import annotations

import sys
import os
import unittest
from typing import Any

# Add the lint module's directory to sys.path so we can import it directly.
_LINT_MODULE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "src", "notemap-mcp"
)
sys.path.insert(0, os.path.normpath(_LINT_MODULE_DIR))

from lint import lint_code  # noqa: E402


def _make_index() -> dict[str, dict[str, Any]]:
    """Build a mock note index with anti-pattern and non-anti-pattern notes
    spanning multiple libraries, pattern types, and edge cases."""
    return {
        "smartstring-trim": {
            "library":                "smartstring",
            "topic":                  "Use SmartString trim method not PHP trim",
            "type":                   "anti-pattern",
            "source_quality":         "runtime-tested",
            "confidence":             "strong",
            "lifecycle":              "active",
            "summary":                "Use ->trim() on SmartString, not PHP trim().",
            "notes":                  "PHP trim() acts on encoded output.",
            "primitives_to_avoid":    ["\\btrim\\(\\s*\\$"],
            "preferred_alternatives": ["->trim()"],
            "related_functions":      ["SmartString::trim", "SmartString::value"],
            "tags":                   ["smartstring", "anti-pattern"],
        },
        "smartarray-empty-check": {
            "library":                "smartarray",
            "topic":                  "Never use empty() on SmartArray objects",
            "type":                   "anti-pattern",
            "source_quality":         "verified-from-source",
            "confidence":             "strong",
            "lifecycle":              "active",
            "summary":                "empty() is always false on objects. Use ->isEmpty().",
            "notes":                  "PHP quirk: empty($object) is always false.",
            "primitives_to_avoid":    ["\\bempty\\(\\s*\\$"],
            "preferred_alternatives": ["->isEmpty()", "->count()"],
            "related_functions":      ["SmartArray::isEmpty", "SmartArray::count"],
            "tags":                   ["smartarray", "gotcha"],
        },
        "zendb-get-empty": {
            "library":                "zendb",
            "topic":                  "DB::get returns empty SmartArrayHtml on no match",
            "type":                   "knowledge",
            "source_quality":         "verified-from-source",
            "confidence":             "strong",
            "lifecycle":              "active",
            "summary":                "DB::get always returns SmartArrayHtml. Empty on no match.",
            "notes":                  "Check with ->isEmpty(), never empty().",
            "related_functions":      ["DB::get"],
            "tags":                   ["zendb", "gotcha"],
        },
        "zendb-correction": {
            "library":                "zendb",
            "topic":                  "DB::select requires table name as first arg",
            "type":                   "correction",
            "source_quality":         "user-correction",
            "confidence":             "strong",
            "lifecycle":              "active",
            "summary":                "First arg to DB::select is the table name.",
            "notes":                  "Not the column list.",
            "tags":                   ["zendb"],
        },
        "smartstring-empty-antipattern": {
            "library":                "smartstring",
            "topic":                  "Never use empty() on SmartString objects",
            "type":                   "anti-pattern",
            "source_quality":         "verified-from-source",
            "confidence":             "strong",
            "lifecycle":              "active",
            "summary":                "empty() on SmartString is always false. Use ->isEmpty().",
            "notes":                  "Same PHP object quirk as SmartArray.",
            "primitives_to_avoid":    ["\\bempty\\(\\s*\\$"],
            "preferred_alternatives": ["->isEmpty()"],
            "related_functions":      ["SmartString::isEmpty"],
            "tags":                   ["smartstring", "anti-pattern"],
        },
        "empty-patterns-note": {
            "library":                "testlib",
            "topic":                  "Anti-pattern note with no primitives",
            "type":                   "anti-pattern",
            "source_quality":         "inferred",
            "confidence":             "weak",
            "lifecycle":              "active",
            "summary":                "This note has an empty patterns list.",
            "notes":                  "Should be skipped during lint.",
            "primitives_to_avoid":    [],
            "preferred_alternatives": [],
            "tags":                   ["testlib"],
        },
        "missing-patterns-note": {
            "library":                "testlib",
            "topic":                  "Anti-pattern note with no primitives key",
            "type":                   "anti-pattern",
            "source_quality":         "inferred",
            "confidence":             "weak",
            "lifecycle":              "active",
            "summary":                "This note lacks the primitives_to_avoid key entirely.",
            "notes":                  "Should be skipped during lint.",
            "tags":                   ["testlib"],
        },
        "bad-regex-note": {
            "library":                "badlib",
            "topic":                  "Anti-pattern with invalid regex",
            "type":                   "anti-pattern",
            "source_quality":         "inferred",
            "confidence":             "weak",
            "lifecycle":              "active",
            "summary":                "Pattern is broken regex.",
            "notes":                  "Should not crash lint.",
            "primitives_to_avoid":    ["(unclosed_group"],
            "preferred_alternatives": ["something_else"],
            "tags":                   ["badlib"],
        },
        "convention-note": {
            "library":                "smartstring",
            "topic":                  "SmartString naming conventions",
            "type":                   "convention",
            "source_quality":         "documented",
            "confidence":             "strong",
            "lifecycle":              "active",
            "summary":                "Naming convention note.",
            "notes":                  "Should not participate in lint.",
            "tags":                   ["smartstring"],
        },
        "no-alternatives-note": {
            "library":                "noalt",
            "topic":                  "Anti-pattern without preferred alternatives",
            "type":                   "anti-pattern",
            "source_quality":         "runtime-tested",
            "confidence":             "strong",
            "lifecycle":              "active",
            "summary":                "Avoid using print_r on objects.",
            "notes":                  "No suggestion provided.",
            "primitives_to_avoid":    ["\\bprint_r\\(\\s*\\$"],
            "preferred_alternatives": [],
            "tags":                   ["noalt"],
        },
        "case-sensitive-note": {
            "library":                "caselib",
            "topic":                  "Case sensitive pattern test",
            "type":                   "anti-pattern",
            "source_quality":         "runtime-tested",
            "confidence":             "strong",
            "lifecycle":              "active",
            "summary":                "Pattern only matches uppercase DANGER.",
            "notes":                  "Testing case sensitivity.",
            "primitives_to_avoid":    ["DANGER"],
            "preferred_alternatives": ["safe_call()"],
            "tags":                   ["caselib"],
        },
        "multiline-note": {
            "library":                "multilib",
            "topic":                  "Multi-line pattern detection",
            "type":                   "anti-pattern",
            "source_quality":         "runtime-tested",
            "confidence":             "strong",
            "lifecycle":              "active",
            "summary":                "Detects var_dump across lines.",
            "notes":                  "var_dump should never appear in production code.",
            "primitives_to_avoid":    ["\\bvar_dump\\("],
            "preferred_alternatives": ["->debug()"],
            "tags":                   ["multilib"],
        },
    }


class TestLintCode(unittest.TestCase):
    """Test the lint_code anti-pattern detection function."""

    def setUp(self) -> None:
        self.index = _make_index()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _note_ids(self, result: dict[str, Any]) -> list[str]:
        """Extract note IDs from all warnings in a lint result."""
        return [w["note_id"] for w in result["warnings"]]

    # ------------------------------------------------------------------
    # 1. Basic anti-pattern match
    # ------------------------------------------------------------------

    def test_basic_antipattern_match(self) -> None:
        """Code containing trim($smartString) should flag the smartstring-trim note."""
        code = '$result = trim($myVar);'
        result = lint_code(self.index, {"code": code, "library": "smartstring"})
        self.assertFalse(result["clean"])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(result["warnings"][0]["note_id"], "smartstring-trim")
        self.assertIn("trim(", result["warnings"][0]["match"])

    # ------------------------------------------------------------------
    # 2. Clean code returns no violations
    # ------------------------------------------------------------------

    def test_clean_code_no_violations(self) -> None:
        """Code that doesn't match any anti-pattern returns clean=True."""
        code = '$result = $myVar->trim();'
        result = lint_code(self.index, {"code": code, "library": "smartstring"})
        self.assertTrue(result["clean"])
        self.assertEqual(len(result["warnings"]), 0)

    # ------------------------------------------------------------------
    # 3. Empty code string
    # ------------------------------------------------------------------

    def test_empty_code_returns_clean(self) -> None:
        """Empty code string returns clean=True with no warnings."""
        result = lint_code(self.index, {"code": ""})
        self.assertTrue(result["clean"])
        self.assertEqual(result["warnings"], [])

    def test_none_code_returns_clean(self) -> None:
        """None code value returns clean=True with no warnings."""
        result = lint_code(self.index, {"code": None})
        self.assertTrue(result["clean"])
        self.assertEqual(result["warnings"], [])

    def test_missing_code_key_returns_clean(self) -> None:
        """Missing code key in params returns clean=True with no warnings."""
        result = lint_code(self.index, {})
        self.assertTrue(result["clean"])
        self.assertEqual(result["warnings"], [])

    # ------------------------------------------------------------------
    # 4. Library filter: only checks specified library
    # ------------------------------------------------------------------

    def test_library_filter_restricts_checks(self) -> None:
        """With library filter, only anti-patterns from that library are checked."""
        # This code matches both smartstring-trim and smartstring-empty-antipattern,
        # but NOT smartarray-empty-check because we filter to smartstring
        code = 'if (empty($record)) { trim($val); }'
        result = lint_code(self.index, {"code": code, "library": "smartstring"})
        ids = self._note_ids(result)
        self.assertIn("smartstring-trim", ids)
        self.assertIn("smartstring-empty-antipattern", ids)
        self.assertNotIn("smartarray-empty-check", ids)

    def test_library_filter_nonexistent_library(self) -> None:
        """Filtering by a library with no anti-pattern notes returns clean."""
        code = 'trim($val); empty($obj);'
        result = lint_code(self.index, {"code": code, "library": "nonexistent"})
        self.assertTrue(result["clean"])
        self.assertEqual(result["warnings"], [])

    # ------------------------------------------------------------------
    # 5. No library filter: checks all anti-patterns
    # ------------------------------------------------------------------

    def test_no_library_filter_checks_all(self) -> None:
        """Without library filter, anti-patterns from ALL libraries are checked."""
        code = 'if (empty($record)) { trim($val); }'
        result = lint_code(self.index, {"code": code})
        ids = self._note_ids(result)
        # Should match smartstring-trim, smartarray-empty-check,
        # and smartstring-empty-antipattern
        self.assertIn("smartstring-trim", ids)
        self.assertIn("smartarray-empty-check", ids)
        self.assertIn("smartstring-empty-antipattern", ids)
        self.assertFalse(result["clean"])

    # ------------------------------------------------------------------
    # 6. Multiple anti-pattern matches in same code
    # ------------------------------------------------------------------

    def test_multiple_matches_in_same_code(self) -> None:
        """Code triggering multiple anti-patterns returns multiple warnings."""
        code = '$x = trim($val); if (empty($obj)) { print_r($data); }'
        result = lint_code(self.index, {"code": code})
        self.assertFalse(result["clean"])
        ids = self._note_ids(result)
        self.assertIn("smartstring-trim", ids)
        self.assertIn("smartarray-empty-check", ids)
        self.assertIn("no-alternatives-note", ids)
        self.assertGreaterEqual(len(result["warnings"]), 3)

    # ------------------------------------------------------------------
    # 7. Invalid regex: handles gracefully
    # ------------------------------------------------------------------

    def test_invalid_regex_does_not_crash(self) -> None:
        """Invalid regex in primitives_to_avoid is skipped without crashing."""
        code = '(unclosed_group something'
        result = lint_code(self.index, {"code": code, "library": "badlib"})
        # Should not raise, should return a result dict
        self.assertIn("warnings", result)
        self.assertIn("clean", result)

    def test_invalid_regex_skipped_other_patterns_still_work(self) -> None:
        """Invalid regex in one note doesn't block checking of other notes."""
        code = 'trim($val);'
        result = lint_code(self.index, {"code": code})
        # badlib's broken regex is skipped, but smartstring-trim still matches
        self.assertIn("smartstring-trim", self._note_ids(result))

    # ------------------------------------------------------------------
    # 8. Empty primitives_to_avoid list
    # ------------------------------------------------------------------

    def test_empty_primitives_list_skipped(self) -> None:
        """Anti-pattern note with empty primitives_to_avoid produces no warnings."""
        code = 'anything goes here'
        result = lint_code(self.index, {"code": code, "library": "testlib"})
        self.assertTrue(result["clean"])
        self.assertEqual(result["warnings"], [])

    def test_missing_primitives_key_skipped(self) -> None:
        """Anti-pattern note missing primitives_to_avoid key entirely is skipped."""
        # missing-patterns-note has no primitives_to_avoid key
        code = 'anything goes here'
        result = lint_code(self.index, {"code": code, "library": "testlib"})
        self.assertTrue(result["clean"])

    # ------------------------------------------------------------------
    # 9. Non-anti-pattern notes are skipped
    # ------------------------------------------------------------------

    def test_knowledge_note_not_checked(self) -> None:
        """Knowledge-type notes are never used for lint checking."""
        # zendb-get-empty is type=knowledge; even if code matches something,
        # it should not produce a lint warning from that note
        code = 'DB::get returns empty'
        result = lint_code(self.index, {"code": code, "library": "zendb"})
        ids = self._note_ids(result)
        self.assertNotIn("zendb-get-empty", ids)
        self.assertTrue(result["clean"])

    def test_correction_note_not_checked(self) -> None:
        """Correction-type notes are never used for lint checking."""
        code = 'DB::select("users")'
        result = lint_code(self.index, {"code": code, "library": "zendb"})
        ids = self._note_ids(result)
        self.assertNotIn("zendb-correction", ids)
        self.assertTrue(result["clean"])

    def test_convention_note_not_checked(self) -> None:
        """Convention-type notes are never used for lint checking."""
        code = 'SmartString naming conventions apply here'
        result = lint_code(self.index, {"code": code, "library": "smartstring"})
        # Only anti-pattern notes should produce warnings; convention should not
        ids = self._note_ids(result)
        self.assertNotIn("convention-note", ids)

    # ------------------------------------------------------------------
    # 10. Preferred alternatives in output
    # ------------------------------------------------------------------

    def test_preferred_alternative_in_suggestion(self) -> None:
        """Warning includes the first preferred_alternative as suggestion."""
        code = 'trim($val);'
        result = lint_code(self.index, {"code": code, "library": "smartstring"})
        trim_warning = next(
            w for w in result["warnings"] if w["note_id"] == "smartstring-trim"
        )
        self.assertEqual(trim_warning["suggestion"], "->trim()")

    def test_no_preferred_alternative_gives_empty_suggestion(self) -> None:
        """When preferred_alternatives is empty, suggestion is empty string."""
        code = 'print_r($data);'
        result = lint_code(self.index, {"code": code, "library": "noalt"})
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(result["warnings"][0]["suggestion"], "")

    # ------------------------------------------------------------------
    # 11. No anti-pattern notes in index
    # ------------------------------------------------------------------

    def test_empty_index_returns_clean(self) -> None:
        """Empty index returns clean=True with no warnings."""
        result = lint_code({}, {"code": 'trim($val); empty($obj);'})
        self.assertTrue(result["clean"])
        self.assertEqual(result["warnings"], [])

    def test_index_with_no_antipattern_notes(self) -> None:
        """Index containing only non-anti-pattern notes returns clean."""
        knowledge_only_index = {
            "zendb-get-empty": self.index["zendb-get-empty"],
            "zendb-correction": self.index["zendb-correction"],
            "convention-note": self.index["convention-note"],
        }
        result = lint_code(knowledge_only_index, {"code": 'trim($val);'})
        self.assertTrue(result["clean"])
        self.assertEqual(result["warnings"], [])

    # ------------------------------------------------------------------
    # 12. Multi-line code matching
    # ------------------------------------------------------------------

    def test_multiline_code_detects_pattern(self) -> None:
        """Patterns match across multi-line code strings."""
        code = """$records = DB::select('users');
foreach ($records as $record) {
    var_dump($record);
    echo $record->name;
}"""
        result = lint_code(self.index, {"code": code, "library": "multilib"})
        self.assertFalse(result["clean"])
        self.assertIn("multiline-note", self._note_ids(result))

    def test_multiline_code_pattern_on_later_line(self) -> None:
        """Pattern appearing on a line other than the first is still detected."""
        code = """// This is fine
// Also fine
$x = trim($name);"""
        result = lint_code(self.index, {"code": code, "library": "smartstring"})
        self.assertFalse(result["clean"])
        self.assertIn("smartstring-trim", self._note_ids(result))

    # ------------------------------------------------------------------
    # 13. Case sensitivity in regex patterns
    # ------------------------------------------------------------------

    def test_case_sensitive_match(self) -> None:
        """Regex patterns are case-sensitive by default: DANGER matches."""
        code = 'call_DANGER_function();'
        result = lint_code(self.index, {"code": code, "library": "caselib"})
        self.assertFalse(result["clean"])
        self.assertIn("case-sensitive-note", self._note_ids(result))

    def test_case_sensitive_no_match_on_wrong_case(self) -> None:
        """Regex patterns are case-sensitive: lowercase 'danger' does NOT match."""
        code = 'call_danger_function();'
        result = lint_code(self.index, {"code": code, "library": "caselib"})
        self.assertTrue(result["clean"])
        self.assertEqual(result["warnings"], [])

    # ------------------------------------------------------------------
    # 14. Warning field structure
    # ------------------------------------------------------------------

    def test_warning_contains_expected_fields(self) -> None:
        """Each warning contains match, note_id, message, why, and suggestion."""
        code = 'trim($val);'
        result = lint_code(self.index, {"code": code, "library": "smartstring"})
        expected_keys = {"match", "note_id", "message", "why", "suggestion"}
        for warning in result["warnings"]:
            self.assertEqual(set(warning.keys()), expected_keys)

    def test_warning_message_is_summary(self) -> None:
        """Warning message and why fields are populated from the note summary."""
        code = 'if (empty($obj)) {}'
        result = lint_code(self.index, {"code": code, "library": "smartarray"})
        warning = result["warnings"][0]
        self.assertEqual(
            warning["message"],
            "empty() is always false on objects. Use ->isEmpty().",
        )
        self.assertEqual(warning["why"], warning["message"])

    # ------------------------------------------------------------------
    # 15. Return shape
    # ------------------------------------------------------------------

    def test_return_has_warnings_and_clean_keys(self) -> None:
        """Return dict always has 'warnings' (list) and 'clean' (bool) keys."""
        for code in ["", "clean code", "trim($val);"]:
            result = lint_code(self.index, {"code": code})
            self.assertIn("warnings", result)
            self.assertIn("clean", result)
            self.assertIsInstance(result["warnings"], list)
            self.assertIsInstance(result["clean"], bool)

    def test_clean_is_true_when_no_warnings(self) -> None:
        """clean is True if and only if warnings list is empty."""
        clean_result = lint_code(self.index, {"code": "$x = 1;"})
        self.assertTrue(clean_result["clean"])
        self.assertEqual(len(clean_result["warnings"]), 0)

        dirty_result = lint_code(self.index, {"code": "trim($val);"})
        self.assertFalse(dirty_result["clean"])
        self.assertGreater(len(dirty_result["warnings"]), 0)

    # ------------------------------------------------------------------
    # 16. Library filter whitespace handling
    # ------------------------------------------------------------------

    def test_library_filter_whitespace_trimmed(self) -> None:
        """Library filter trims leading/trailing whitespace."""
        code = 'trim($val);'
        result = lint_code(self.index, {"code": code, "library": "  smartstring  "})
        self.assertIn("smartstring-trim", self._note_ids(result))

    # ------------------------------------------------------------------
    # 17. Same pattern from multiple notes
    # ------------------------------------------------------------------

    def test_same_pattern_matches_from_different_notes(self) -> None:
        """When multiple notes have the same pattern, each produces a warning."""
        # Both smartarray-empty-check and smartstring-empty-antipattern
        # use the pattern \\bempty\\(\\s*\\$
        code = 'if (empty($record)) {}'
        result = lint_code(self.index, {"code": code})
        ids = self._note_ids(result)
        self.assertIn("smartarray-empty-check", ids)
        self.assertIn("smartstring-empty-antipattern", ids)

    # ------------------------------------------------------------------
    # 18. Match field contains the actual matched text
    # ------------------------------------------------------------------

    def test_match_field_contains_matched_text(self) -> None:
        """The match field contains the exact text that was matched by the regex."""
        code = '  trim(  $myVar  )'
        result = lint_code(self.index, {"code": code, "library": "smartstring"})
        trim_warning = next(
            w for w in result["warnings"] if w["note_id"] == "smartstring-trim"
        )
        # The regex \\btrim\\(\\s*\\$ should match "trim(  $"
        self.assertIn("trim(", trim_warning["match"])
        self.assertIn("$", trim_warning["match"])


if __name__ == "__main__":
    unittest.main()
