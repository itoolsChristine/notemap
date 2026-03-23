"""Tests for the private helper functions in notes.py.

Covers _extract_sections, _build_body, _cues_from_section, and
_build_frontmatter -- the pure-logic helpers that underpin CRUD operations.

Run with:  python -m unittest tests.test_notes_helpers
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Path setup -- allow imports from src/notemap-mcp/
# ---------------------------------------------------------------------------
_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src" / "notemap-mcp")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from notes import _build_body, _build_frontmatter, _cues_from_section, _extract_sections  # noqa: E402


# ===========================================================================
# _extract_sections
# ===========================================================================

class TestExtractSections(unittest.TestCase):
    """Tests for _extract_sections(body)."""

    def test_all_three_sections_present(self) -> None:
        """Body with all three headings returns populated cues, notes, summary."""
        body = (
            "## Cues\n"
            "- What is the gotcha?\n"
            "- When does it apply?\n"
            "\n"
            "## Notes\n"
            "Detailed explanation here.\n"
            "\n"
            "## Summary\n"
            "One-line summary.\n"
        )
        result = _extract_sections(body)
        self.assertIn("- What is the gotcha?", result["cues"])
        self.assertIn("- When does it apply?", result["cues"])
        self.assertEqual(result["notes"], "Detailed explanation here.")
        self.assertEqual(result["summary"], "One-line summary.")

    def test_missing_sections_return_empty_strings(self) -> None:
        """Body with no recognized headings returns all empty strings."""
        body = "Just some plain text with no headings.\n"
        result = _extract_sections(body)
        self.assertEqual(result["cues"], "")
        self.assertEqual(result["notes"], "")
        self.assertEqual(result["summary"], "")

    def test_only_notes_section_present(self) -> None:
        """Body with only ## Notes populates notes, leaves others empty."""
        body = "## Notes\nSome notes content.\n"
        result = _extract_sections(body)
        self.assertEqual(result["notes"], "Some notes content.")
        self.assertEqual(result["cues"], "")
        self.assertEqual(result["summary"], "")

    def test_only_cues_and_summary_present(self) -> None:
        """Body with Cues and Summary but no Notes leaves notes empty."""
        body = (
            "## Cues\n"
            "- A cue question\n"
            "## Summary\n"
            "A summary line.\n"
        )
        result = _extract_sections(body)
        self.assertEqual(result["cues"], "- A cue question")
        self.assertEqual(result["notes"], "")
        self.assertEqual(result["summary"], "A summary line.")

    def test_sections_in_reversed_order(self) -> None:
        """Sections in Summary -> Notes -> Cues order still parse correctly."""
        body = (
            "## Summary\n"
            "Summary first.\n"
            "## Notes\n"
            "Notes second.\n"
            "## Cues\n"
            "- Cues last.\n"
        )
        result = _extract_sections(body)
        self.assertEqual(result["summary"], "Summary first.")
        self.assertEqual(result["notes"], "Notes second.")
        self.assertEqual(result["cues"], "- Cues last.")

    def test_leading_content_before_first_heading_is_ignored(self) -> None:
        """Text before the first recognized heading is discarded."""
        body = (
            "This preamble should be ignored.\n"
            "So should this line.\n"
            "## Notes\n"
            "Actual notes.\n"
        )
        result = _extract_sections(body)
        self.assertEqual(result["notes"], "Actual notes.")
        self.assertEqual(result["cues"], "")
        self.assertEqual(result["summary"], "")

    def test_extra_whitespace_stripped(self) -> None:
        """Leading and trailing whitespace within sections is stripped."""
        body = (
            "## Notes\n"
            "\n"
            "   Content with whitespace.   \n"
            "\n"
        )
        result = _extract_sections(body)
        self.assertEqual(result["notes"], "Content with whitespace.")

    def test_unrecognized_headings_ignored(self) -> None:
        """Headings that are not cues/notes/summary are treated as body content."""
        body = (
            "## Cues\n"
            "- A cue\n"
            "## References\n"
            "This is an unknown heading section.\n"
            "## Notes\n"
            "Real notes.\n"
        )
        result = _extract_sections(body)
        self.assertEqual(result["cues"], "- A cue")
        self.assertEqual(result["notes"], "Real notes.")
        # "References" content should not leak into any known section

    def test_empty_body_returns_empty_sections(self) -> None:
        """Empty string body returns all empty section values."""
        result = _extract_sections("")
        self.assertEqual(result["cues"], "")
        self.assertEqual(result["notes"], "")
        self.assertEqual(result["summary"], "")

    def test_multiline_notes_preserved(self) -> None:
        """Multi-line content within a section is preserved as a single string."""
        body = (
            "## Notes\n"
            "Line one.\n"
            "Line two.\n"
            "Line three.\n"
        )
        result = _extract_sections(body)
        self.assertIn("Line one.", result["notes"])
        self.assertIn("Line two.", result["notes"])
        self.assertIn("Line three.", result["notes"])

    def test_case_insensitive_heading_match(self) -> None:
        """Heading matching is case-insensitive (e.g., ## NOTES works)."""
        body = "## NOTES\nUppercase heading content.\n"
        result = _extract_sections(body)
        self.assertEqual(result["notes"], "Uppercase heading content.")


# ===========================================================================
# _build_body
# ===========================================================================

class TestBuildBody(unittest.TestCase):
    """Tests for _build_body(cues, notes_text, summary_text)."""

    def test_normal_build_with_all_sections(self) -> None:
        """All three sections produce a well-formed markdown body."""
        body = _build_body(
            cues=["What is the gotcha?", "When does it apply?"],
            notes_text="Detailed explanation here.",
            summary_text="One-line summary.",
        )
        self.assertIn("## Cues", body)
        self.assertIn("- What is the gotcha?", body)
        self.assertIn("- When does it apply?", body)
        self.assertIn("## Notes", body)
        self.assertIn("Detailed explanation here.", body)
        self.assertIn("## Summary", body)
        self.assertIn("One-line summary.", body)

    def test_empty_cues_list_produces_no_bullet_lines(self) -> None:
        """Empty cues list produces the ## Cues heading with no bullet lines."""
        body = _build_body(cues=[], notes_text="Notes.", summary_text="Summary.")
        self.assertIn("## Cues", body)
        # No "- " bullet line between ## Cues and ## Notes
        lines = body.splitlines()
        cue_idx = lines.index("## Cues")
        # Next non-empty content should be ## Notes (possibly with blank lines)
        found_bullet = False
        for line in lines[cue_idx + 1 :]:
            if line.startswith("- "):
                found_bullet = True
            if line.startswith("## "):
                break
        self.assertFalse(found_bullet, "Should have no bullet lines for empty cues")

    def test_cues_formatted_as_bullet_points(self) -> None:
        """Each cue is formatted with a '- ' prefix."""
        body = _build_body(
            cues=["First cue", "Second cue"],
            notes_text="",
            summary_text="",
        )
        self.assertIn("- First cue", body)
        self.assertIn("- Second cue", body)

    def test_body_ends_with_newline(self) -> None:
        """Built body always ends with a trailing newline."""
        body = _build_body(cues=[], notes_text="N", summary_text="S")
        self.assertTrue(body.endswith("\n"))

    def test_round_trip_build_then_extract(self) -> None:
        """Building a body and extracting sections recovers the original data."""
        cues = ["Cue alpha", "Cue beta"]
        notes = "These are detailed notes.\nWith multiple lines."
        summary = "A concise summary."

        body = _build_body(cues, notes, summary)
        sections = _extract_sections(body)

        # Notes and summary should round-trip exactly
        self.assertEqual(sections["notes"], notes)
        self.assertEqual(sections["summary"], summary)

        # Cues should be recoverable via _cues_from_section
        recovered_cues = _cues_from_section(sections["cues"])
        self.assertEqual(recovered_cues, cues)

    def test_all_sections_empty(self) -> None:
        """Building with all-empty inputs still produces valid section headings."""
        body = _build_body(cues=[], notes_text="", summary_text="")
        self.assertIn("## Cues", body)
        self.assertIn("## Notes", body)
        self.assertIn("## Summary", body)


# ===========================================================================
# _cues_from_section
# ===========================================================================

class TestCuesFromSection(unittest.TestCase):
    """Tests for _cues_from_section(section_text)."""

    def test_dash_bullet_prefix(self) -> None:
        """Lines starting with '- ' are parsed as cues."""
        text = "- First cue\n- Second cue\n"
        result = _cues_from_section(text)
        self.assertEqual(result, ["First cue", "Second cue"])

    def test_asterisk_bullet_prefix(self) -> None:
        """Lines starting with '* ' are parsed as cues."""
        text = "* Asterisk cue one\n* Asterisk cue two\n"
        result = _cues_from_section(text)
        self.assertEqual(result, ["Asterisk cue one", "Asterisk cue two"])

    def test_mixed_bullet_prefixes(self) -> None:
        """Mix of '- ' and '* ' prefixes are both recognized."""
        text = "- Dash cue\n* Asterisk cue\n"
        result = _cues_from_section(text)
        self.assertEqual(result, ["Dash cue", "Asterisk cue"])

    def test_lines_without_bullet_captured(self) -> None:
        """Non-empty lines without bullet prefix are captured as-is."""
        text = "No bullet here\nAnother plain line\n"
        result = _cues_from_section(text)
        self.assertEqual(result, ["No bullet here", "Another plain line"])

    def test_empty_lines_skipped(self) -> None:
        """Blank lines between cues are skipped."""
        text = "- Cue one\n\n- Cue two\n\n\n- Cue three\n"
        result = _cues_from_section(text)
        self.assertEqual(result, ["Cue one", "Cue two", "Cue three"])

    def test_whitespace_stripped_from_cues(self) -> None:
        """Leading/trailing whitespace is stripped from each cue."""
        text = "  - Padded cue  \n  * Another padded  \n"
        result = _cues_from_section(text)
        self.assertEqual(result, ["Padded cue", "Another padded"])

    def test_empty_section_returns_empty_list(self) -> None:
        """Empty input returns an empty list."""
        result = _cues_from_section("")
        self.assertEqual(result, [])

    def test_whitespace_only_section_returns_empty_list(self) -> None:
        """Input with only whitespace/blank lines returns an empty list."""
        result = _cues_from_section("   \n\n   \n")
        self.assertEqual(result, [])


# ===========================================================================
# _build_frontmatter
# ===========================================================================

class TestBuildFrontmatter(unittest.TestCase):
    """Tests for _build_frontmatter(params, note_id)."""

    def _base_params(self, **overrides) -> dict:
        """Return minimal valid params for _build_frontmatter."""
        params = {
            "library": "testlib",
            "topic":   "Sample topic",
        }
        params.update(overrides)
        return params

    @patch("notes.today_str", return_value="2026-03-23")
    def test_knowledge_type_no_anti_pattern_fields(self, _mock_today) -> None:
        """Knowledge type does not include primitives_to_avoid or preferred_alternatives."""
        params = self._base_params(type="knowledge")
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["type"], "knowledge")
        self.assertNotIn("primitives_to_avoid", fm)
        self.assertNotIn("preferred_alternatives", fm)

    @patch("notes.today_str", return_value="2026-03-23")
    def test_anti_pattern_type_includes_extra_fields(self, _mock_today) -> None:
        """Anti-pattern type includes primitives_to_avoid and preferred_alternatives."""
        params = self._base_params(
            type="anti-pattern",
            primitives_to_avoid=[r"\bempty\("],
            preferred_alternatives=["->isEmpty()"],
        )
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["type"], "anti-pattern")
        self.assertIn("primitives_to_avoid", fm)
        self.assertEqual(fm["primitives_to_avoid"], [r"\bempty\("])
        self.assertIn("preferred_alternatives", fm)
        self.assertEqual(fm["preferred_alternatives"], ["->isEmpty()"])

    @patch("notes.today_str", return_value="2026-03-23")
    def test_anti_pattern_review_interval_60(self, _mock_today) -> None:
        """Anti-pattern notes get a 60-day review interval (not the default 30)."""
        params = self._base_params(type="anti-pattern")
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["review_interval_days"], 60)

    @patch("notes.today_str", return_value="2026-03-23")
    def test_non_anti_pattern_review_interval_30(self, _mock_today) -> None:
        """Non-anti-pattern notes get a 30-day review interval."""
        params = self._base_params(type="knowledge")
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["review_interval_days"], 30)

    @patch("notes.today_str", return_value="2026-03-23")
    def test_correction_type_includes_extra_fields(self, _mock_today) -> None:
        """Correction type includes wrong_assumption, correct_behavior, applies_to."""
        params = self._base_params(
            type="correction",
            wrong_assumption="Assumed empty() works on objects",
            correct_behavior="Use ->isEmpty() instead",
            applies_to="All SmartArray instances",
        )
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["type"], "correction")
        self.assertEqual(fm["wrong_assumption"], "Assumed empty() works on objects")
        self.assertEqual(fm["correct_behavior"], "Use ->isEmpty() instead")
        self.assertEqual(fm["applies_to"], "All SmartArray instances")

    @patch("notes.today_str", return_value="2026-03-23")
    def test_correction_type_no_anti_pattern_fields(self, _mock_today) -> None:
        """Correction type does not include anti-pattern-specific fields."""
        params = self._base_params(type="correction")
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertNotIn("primitives_to_avoid", fm)
        self.assertNotIn("preferred_alternatives", fm)

    @patch("notes.today_str", return_value="2026-03-23")
    def test_convention_type_no_extra_fields(self, _mock_today) -> None:
        """Convention type has no anti-pattern or correction fields."""
        params = self._base_params(type="convention")
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["type"], "convention")
        self.assertNotIn("primitives_to_avoid", fm)
        self.assertNotIn("preferred_alternatives", fm)
        self.assertNotIn("wrong_assumption", fm)
        self.assertNotIn("correct_behavior", fm)
        self.assertNotIn("applies_to", fm)

    @patch("notes.today_str", return_value="2026-03-23")
    def test_default_source_quality_and_confidence(self, _mock_today) -> None:
        """Missing source_quality defaults to 'unverified', confidence to 'weak'."""
        params = self._base_params()
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["source_quality"], "unverified")
        self.assertEqual(fm["confidence"], "weak")

    @patch("notes.today_str", return_value="2026-03-23")
    def test_explicit_source_quality_and_confidence(self, _mock_today) -> None:
        """Explicitly provided source_quality and confidence override defaults."""
        params = self._base_params(
            source_quality="verified-from-source",
            confidence="strong",
        )
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["source_quality"], "verified-from-source")
        self.assertEqual(fm["confidence"], "strong")

    @patch("notes.today_str", return_value="2026-03-23")
    def test_sources_included_when_provided(self, _mock_today) -> None:
        """Sources list is included in frontmatter when provided."""
        sources = [
            {"url": "https://example.com/docs", "label": "Official docs"},
        ]
        params = self._base_params(sources=sources)
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["sources"], sources)

    @patch("notes.today_str", return_value="2026-03-23")
    def test_sources_default_to_empty_list(self, _mock_today) -> None:
        """Sources default to an empty list when not provided."""
        params = self._base_params()
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["sources"], [])

    @patch("notes.today_str", return_value="2026-03-23")
    def test_dates_set_to_today(self, _mock_today) -> None:
        """created, last_modified, and last_reviewed are all set to today."""
        params = self._base_params()
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["created"], "2026-03-23")
        self.assertEqual(fm["last_modified"], "2026-03-23")
        self.assertEqual(fm["last_reviewed"], "2026-03-23")

    @patch("notes.today_str", return_value="2026-03-23")
    def test_miss_count_starts_at_zero(self, _mock_today) -> None:
        """New notes start with miss_count of 0."""
        params = self._base_params()
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["miss_count"], 0)

    @patch("notes.today_str", return_value="2026-03-23")
    def test_review_count_starts_at_zero(self, _mock_today) -> None:
        """New notes start with review_count of 0."""
        params = self._base_params()
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["review_count"], 0)

    @patch("notes.today_str", return_value="2026-03-23")
    def test_note_id_stored_correctly(self, _mock_today) -> None:
        """The note_id argument is stored as the 'id' field."""
        params = self._base_params()
        fm = _build_frontmatter(params, "testlib-my-custom-id")
        self.assertEqual(fm["id"], "testlib-my-custom-id")

    @patch("notes.today_str", return_value="2026-03-23")
    def test_lifecycle_defaults_to_active(self, _mock_today) -> None:
        """New notes always start with lifecycle 'active'."""
        params = self._base_params()
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["lifecycle"], "active")

    @patch("notes.today_str", return_value="2026-03-23")
    def test_default_type_is_knowledge(self, _mock_today) -> None:
        """When no type is specified, it defaults to 'knowledge'."""
        params = self._base_params()  # no 'type' key
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["type"], "knowledge")

    @patch("notes.today_str", return_value="2026-03-23")
    def test_tags_included_when_provided(self, _mock_today) -> None:
        """Tags are carried through from params."""
        params = self._base_params(tags=["gotcha", "important"])
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["tags"], ["gotcha", "important"])

    @patch("notes.today_str", return_value="2026-03-23")
    def test_tags_default_to_empty_list(self, _mock_today) -> None:
        """Tags default to an empty list when not provided."""
        params = self._base_params()
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["tags"], [])

    @patch("notes.today_str", return_value="2026-03-23")
    def test_related_functions_carried_through(self, _mock_today) -> None:
        """related_functions from params are included in frontmatter."""
        params = self._base_params(related_functions=["DB::get", "DB::select"])
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["related_functions"], ["DB::get", "DB::select"])

    @patch("notes.today_str", return_value="2026-03-23")
    def test_miss_log_starts_empty(self, _mock_today) -> None:
        """New notes start with an empty miss_log list."""
        params = self._base_params()
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["miss_log"], [])

    @patch("notes.today_str", return_value="2026-03-23")
    def test_anti_pattern_defaults_empty_lists(self, _mock_today) -> None:
        """Anti-pattern with no primitives/alternatives defaults to empty lists."""
        params = self._base_params(type="anti-pattern")
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["primitives_to_avoid"], [])
        self.assertEqual(fm["preferred_alternatives"], [])

    @patch("notes.today_str", return_value="2026-03-23")
    def test_correction_defaults_empty_strings(self, _mock_today) -> None:
        """Correction with no wrong_assumption/correct_behavior/applies_to defaults to empty strings."""
        params = self._base_params(type="correction")
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["wrong_assumption"], "")
        self.assertEqual(fm["correct_behavior"], "")
        self.assertEqual(fm["applies_to"], "")

    @patch("notes.today_str", return_value="2026-03-23")
    def test_library_version_default_empty(self, _mock_today) -> None:
        """library_version defaults to empty string when not provided."""
        params = self._base_params()
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["library_version"], "")

    @patch("notes.today_str", return_value="2026-03-23")
    def test_library_version_set_when_provided(self, _mock_today) -> None:
        """library_version is stored when explicitly provided."""
        params = self._base_params(library_version="3.2.1")
        fm = _build_frontmatter(params, "testlib-sample-topic")
        self.assertEqual(fm["library_version"], "3.2.1")


if __name__ == "__main__":
    unittest.main()
