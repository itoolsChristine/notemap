"""Tests for the section parsing and cue extraction helpers.

After the SQLite migration, these functions moved from notes.py to db.py.
Covers _split_sections and _extract_cues -- the pure-logic helpers that
underpin migration and body reconstruction.

Run with:  python -m unittest tests.test_notes_helpers
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup -- allow imports from src/notemap-mcp/
# ---------------------------------------------------------------------------
_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src" / "notemap-mcp")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from db import _split_sections, _extract_cues  # noqa: E402


# ===========================================================================
# _split_sections (was _extract_sections in old notes.py)
# ===========================================================================

class TestSplitSections(unittest.TestCase):
    """Tests for _split_sections(body)."""

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
        result = _split_sections(body)
        self.assertIn("- What is the gotcha?", result["cues"])
        self.assertIn("- When does it apply?", result["cues"])
        self.assertEqual(result["notes"], "Detailed explanation here.")
        self.assertEqual(result["summary"], "One-line summary.")

    def test_missing_sections_return_empty_strings(self) -> None:
        """Body with no recognized headings returns empty for all keys."""
        body = "Just some plain text with no headings.\n"
        result = _split_sections(body)
        self.assertNotIn("cues", result)
        self.assertNotIn("notes", result)
        self.assertNotIn("summary", result)

    def test_only_notes_section_present(self) -> None:
        """Body with only ## Notes populates notes, leaves others absent."""
        body = "## Notes\nSome notes content.\n"
        result = _split_sections(body)
        self.assertEqual(result["notes"], "Some notes content.")
        self.assertNotIn("cues", result)
        self.assertNotIn("summary", result)

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
        result = _split_sections(body)
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
        result = _split_sections(body)
        self.assertEqual(result["notes"], "Actual notes.")
        self.assertNotIn("cues", result)
        self.assertNotIn("summary", result)

    def test_extra_whitespace_stripped(self) -> None:
        """Leading and trailing whitespace within sections is stripped."""
        body = (
            "## Notes\n"
            "\n"
            "   Content with whitespace.   \n"
            "\n"
        )
        result = _split_sections(body)
        self.assertEqual(result["notes"], "Content with whitespace.")

    def test_empty_body_returns_empty_dict(self) -> None:
        """Empty string body returns an empty dict."""
        result = _split_sections("")
        self.assertEqual(result, {})

    def test_multiline_notes_preserved(self) -> None:
        """Multi-line content within a section is preserved as a single string."""
        body = (
            "## Notes\n"
            "Line one.\n"
            "Line two.\n"
            "Line three.\n"
        )
        result = _split_sections(body)
        self.assertIn("Line one.", result["notes"])
        self.assertIn("Line two.", result["notes"])
        self.assertIn("Line three.", result["notes"])

    def test_case_insensitive_heading_match(self) -> None:
        """Heading matching is case-insensitive (## NOTES works)."""
        body = "## NOTES\nUppercase heading content.\n"
        result = _split_sections(body)
        self.assertEqual(result["notes"], "Uppercase heading content.")


# ===========================================================================
# _extract_cues
# ===========================================================================

class TestExtractCues(unittest.TestCase):
    """Tests for _extract_cues(section_text)."""

    def test_dash_bullet_prefix(self) -> None:
        """Lines starting with '- ' are parsed as cues."""
        text = "- First cue\n- Second cue\n"
        result = _extract_cues(text)
        self.assertEqual(result, ["First cue", "Second cue"])

    def test_asterisk_bullet_prefix(self) -> None:
        """Lines starting with '* ' are parsed as cues."""
        text = "* Asterisk cue one\n* Asterisk cue two\n"
        result = _extract_cues(text)
        self.assertEqual(result, ["Asterisk cue one", "Asterisk cue two"])

    def test_mixed_bullet_prefixes(self) -> None:
        """Mix of '- ' and '* ' prefixes are both recognized."""
        text = "- Dash cue\n* Asterisk cue\n"
        result = _extract_cues(text)
        self.assertEqual(result, ["Dash cue", "Asterisk cue"])

    def test_lines_without_bullet_captured(self) -> None:
        """Non-empty lines without bullet prefix are captured as-is."""
        text = "No bullet here\nAnother plain line\n"
        result = _extract_cues(text)
        self.assertEqual(result, ["No bullet here", "Another plain line"])

    def test_empty_lines_skipped(self) -> None:
        """Blank lines between cues are skipped."""
        text = "- Cue one\n\n- Cue two\n\n\n- Cue three\n"
        result = _extract_cues(text)
        self.assertEqual(result, ["Cue one", "Cue two", "Cue three"])

    def test_whitespace_stripped_from_cues(self) -> None:
        """Leading/trailing whitespace is stripped from each cue."""
        text = "  - Padded cue  \n  * Another padded  \n"
        result = _extract_cues(text)
        self.assertEqual(result, ["Padded cue", "Another padded"])

    def test_empty_section_returns_empty_list(self) -> None:
        """Empty input returns an empty list."""
        result = _extract_cues("")
        self.assertEqual(result, [])

    def test_whitespace_only_section_returns_empty_list(self) -> None:
        """Input with only whitespace/blank lines returns an empty list."""
        result = _extract_cues("   \n\n   \n")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
