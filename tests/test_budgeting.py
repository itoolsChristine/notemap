"""Tests for context budgeting and token estimation."""
from __future__ import annotations

import sys
import os
import unittest
from typing import Any

# Add the source directory to sys.path so we can import directly.
_SRC_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "src", "notemap-mcp")
)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from utils import estimate_tokens  # noqa: E402
from preflight import preflight_notes  # noqa: E402


class TestEstimateTokens(unittest.TestCase):
    """Tests for the estimate_tokens utility function."""

    def test_empty_string(self) -> None:
        """Empty string returns 0 tokens."""
        self.assertEqual(estimate_tokens(""), 0)

    def test_short_text_minimum(self) -> None:
        """Short text returns at least 1 token."""
        self.assertEqual(estimate_tokens("hi"), 1)
        self.assertEqual(estimate_tokens("a"), 1)

    def test_proportional(self) -> None:
        """400 characters estimates to approximately 100 tokens."""
        text = "a" * 400
        self.assertEqual(estimate_tokens(text), 100)

    def test_longer_text(self) -> None:
        """Token count scales linearly with text length."""
        short = estimate_tokens("hello world")
        long = estimate_tokens("hello world " * 100)
        self.assertGreater(long, short)

    def test_none_returns_zero(self) -> None:
        """Falsy input returns 0."""
        self.assertEqual(estimate_tokens(""), 0)


class TestPreflightBackwardCompat(unittest.TestCase):
    """Verify preflight works without new parameters (backward compatibility)."""

    def setUp(self) -> None:
        self.index: dict[str, dict[str, Any]] = {
            "note-1": {
                "library":            "testlib",
                "library_version":    "",
                "topic":              "Test note one",
                "type":               "knowledge",
                "source_quality":     "documented",
                "confidence":         "strong",
                "lifecycle":          "active",
                "summary":            "First test note.",
                "related_functions":  ["func_a"],
                "cues":               ["What is note one?"],
                "tags":               ["test"],
            },
            "note-2": {
                "library":            "testlib",
                "library_version":    "",
                "topic":              "Test note two",
                "type":               "anti-pattern",
                "source_quality":     "verified-from-source",
                "confidence":         "strong",
                "lifecycle":          "active",
                "summary":            "Second test note - anti-pattern.",
                "related_functions":  ["func_b"],
                "primitives_to_avoid":    ["bad_pattern"],
                "preferred_alternatives": ["good_pattern"],
                "cues":               ["What is the anti-pattern?"],
                "tags":               ["test"],
            },
            "note-3": {
                "library":            "testlib",
                "library_version":    "",
                "topic":              "Test note three",
                "type":               "reference",
                "source_quality":     "inferred",
                "confidence":         "weak",
                "lifecycle":          "active",
                "summary":            "Third test note - reference.",
                "related_functions":  [],
                "cues":               [],
                "tags":               [],
            },
        }

    def test_no_new_params(self) -> None:
        """Calling preflight without context_budget or topic_focus works as before."""
        result = preflight_notes(self.index, {
            "libraries":            ["testlib"],
            "include_cross_cutting": False,
        })
        self.assertEqual(result["summary"]["total_notes"], 3)
        self.assertNotIn("tokens_used", result)
        self.assertNotIn("expandable_count", result)

    def test_context_budget_zero_means_unlimited(self) -> None:
        """context_budget=0 behaves the same as no budget."""
        result = preflight_notes(self.index, {
            "libraries":            ["testlib"],
            "include_cross_cutting": False,
            "context_budget":       0,
        })
        self.assertEqual(result["summary"]["total_notes"], 3)
        self.assertNotIn("tokens_used", result)


class TestPreflightContextBudget(unittest.TestCase):
    """Tests for context budgeting in preflight."""

    def setUp(self) -> None:
        # Build a larger index to test budget trimming
        self.index: dict[str, dict[str, Any]] = {}
        for i in range(20):
            note_type = "anti-pattern" if i < 3 else "knowledge"
            self.index[f"note-{i}"] = {
                "library":            "biglib",
                "library_version":    "",
                "topic":              f"Topic number {i} with some extra words",
                "type":               note_type,
                "source_quality":     "documented",
                "confidence":         "strong",
                "lifecycle":          "active",
                "summary":            f"Summary for note {i}. " * 3,
                "related_functions":  [f"func_{i}"],
                "cues":               [f"What is note {i}?"],
                "tags":               ["biglib"],
            }
            if note_type == "anti-pattern":
                self.index[f"note-{i}"]["primitives_to_avoid"] = [f"avoid_{i}"]
                self.index[f"note-{i}"]["preferred_alternatives"] = [f"prefer_{i}"]

    def test_budget_adds_tokens_used(self) -> None:
        """With a budget, result includes tokens_used field."""
        result = preflight_notes(self.index, {
            "libraries":            ["biglib"],
            "include_cross_cutting": False,
            "context_budget":       500,
        })
        self.assertIn("tokens_used", result)
        self.assertIsInstance(result["tokens_used"], int)
        self.assertGreater(result["tokens_used"], 0)

    def test_budget_adds_expandable_count(self) -> None:
        """With a budget, result includes expandable_count field."""
        result = preflight_notes(self.index, {
            "libraries":            ["biglib"],
            "include_cross_cutting": False,
            "context_budget":       500,
        })
        self.assertIn("expandable_count", result)
        self.assertIsInstance(result["expandable_count"], int)

    def test_budget_summary_includes_context_budget(self) -> None:
        """Summary includes the context_budget value."""
        result = preflight_notes(self.index, {
            "libraries":            ["biglib"],
            "include_cross_cutting": False,
            "context_budget":       1000,
        })
        self.assertEqual(result["summary"]["context_budget"], 1000)

    def test_notes_get_detail_level(self) -> None:
        """With a budget, notes are assigned a detail_level field."""
        result = preflight_notes(self.index, {
            "libraries":            ["biglib"],
            "include_cross_cutting": False,
            "context_budget":       500,
        })
        all_notes = (
            result["tiers"]["watch_out"]
            + result["tiers"]["know_this"]
            + result["tiers"]["reference"]
        )
        for note in all_notes:
            self.assertIn("detail_level", note)
            self.assertIn(note["detail_level"], [0, 1, 2, 3])

    def test_anti_patterns_always_full_detail(self) -> None:
        """Anti-pattern notes always get detail_level 3 regardless of budget."""
        result = preflight_notes(self.index, {
            "libraries":            ["biglib"],
            "include_cross_cutting": False,
            "context_budget":       200,  # Very tight budget
        })
        for note in result["tiers"]["watch_out"]:
            self.assertEqual(
                note["detail_level"], 3,
                f"Anti-pattern note {note['id']} should have detail_level 3"
            )

    def test_tight_budget_produces_lower_detail(self) -> None:
        """A very tight budget forces some notes to lower detail levels."""
        result = preflight_notes(self.index, {
            "libraries":            ["biglib"],
            "include_cross_cutting": False,
            "context_budget":       300,  # Very tight for 20 notes
        })
        all_notes = (
            result["tiers"]["watch_out"]
            + result["tiers"]["know_this"]
            + result["tiers"]["reference"]
        )
        detail_levels = [n["detail_level"] for n in all_notes]
        # With a tight budget and many notes, some should be below full detail
        has_reduced = any(d < 3 for d in detail_levels)
        self.assertTrue(has_reduced, "Expected some notes at reduced detail level")

    def test_expandable_count_matches_reduced_notes(self) -> None:
        """expandable_count equals the number of notes with detail_level < 3."""
        result = preflight_notes(self.index, {
            "libraries":            ["biglib"],
            "include_cross_cutting": False,
            "context_budget":       500,
        })
        all_notes = (
            result["tiers"]["watch_out"]
            + result["tiers"]["know_this"]
            + result["tiers"]["reference"]
        )
        reduced_count = sum(1 for n in all_notes if n["detail_level"] < 3)
        self.assertEqual(result["expandable_count"], reduced_count)

    def test_level_0_has_minimal_fields(self) -> None:
        """Notes at detail_level 0 only have id, type, library, detail_level."""
        result = preflight_notes(self.index, {
            "libraries":            ["biglib"],
            "include_cross_cutting": False,
            "context_budget":       200,  # Force minimal detail
        })
        all_notes = (
            result["tiers"]["know_this"]
            + result["tiers"]["reference"]
        )
        level_0_notes = [n for n in all_notes if n.get("detail_level") == 0]
        for note in level_0_notes:
            self.assertIn("id", note)
            self.assertIn("type", note)
            self.assertIn("library", note)
            self.assertNotIn("summary", note)
            self.assertNotIn("related_functions", note)


if __name__ == "__main__":
    unittest.main()
