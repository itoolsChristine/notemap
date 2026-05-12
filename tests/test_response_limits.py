"""Tests for the response-size guards.

The headline bug these guard against: an unbounded tool response (a vague
notemap_search with no max_results, an unbudgeted notemap_preflight) serialized
thousands of fat note objects into a multi-MB string, which choked the stdio
transport and disconnected the MCP server for the rest of the session.

Covers:
  - utils.safe_json_dumps: small payloads pass through unchanged; oversized ones
    are trimmed (largest lists first, then long strings) and never raise
  - utils.cap_result_lists: per-list capping for dict-of-lists results
  - search.search_notes: respects max_results when passed
  - preflight.preflight_notes: a context_budget bounds the result

Run with:  python -m unittest tests.test_response_limits -v
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from typing import Any

_SRC_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "src", "notemap-mcp"))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from utils import (  # noqa: E402
    RESPONSE_CHAR_LIMIT,
    cap_result_lists,
    safe_json_dumps,
)
from search import search_notes  # noqa: E402
from preflight import preflight_notes  # noqa: E402


# ===================================================================
# safe_json_dumps
# ===================================================================

class TestSafeJsonDumps(unittest.TestCase):
    """Tests for utils.safe_json_dumps()."""

    def test_small_payload_byte_identical_to_json_dumps(self) -> None:
        """A payload that already fits is returned exactly as json.dumps would."""
        payload = {"count": 3, "results": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "ok": True}
        self.assertEqual(safe_json_dumps(payload), json.dumps(payload, indent=2))

    def test_huge_results_list_is_bounded(self) -> None:
        """A search-style result with thousands of fat notes comes back under the cap."""
        big = {
            "count": 10_000,
            "results": [
                {
                    "id": f"lib-note-{i}",
                    "topic": "x" * 200,
                    "summary": "y" * 300,
                    "cues_raw": "z" * 150,
                    "primitives_to_avoid": ["a" * 40],
                }
                for i in range(10_000)
            ],
        }
        out = safe_json_dumps(big)
        self.assertLessEqual(len(out), RESPONSE_CHAR_LIMIT)
        d = json.loads(out)
        # Scalar siblings survive; the list is trimmed with a marker as the last entry.
        self.assertEqual(d["count"], 10_000)
        self.assertIsInstance(d["results"], list)
        self.assertLess(len(d["results"]), 50)
        self.assertEqual(d["results"][0]["id"], "lib-note-0")
        self.assertTrue(d["results"][-1].get("_truncated"))
        self.assertGreater(d["results"][-1].get("_omitted", 0), 0)

    def test_nested_dict_of_lists_is_bounded(self) -> None:
        """A preflight-style nested {tiers: {watch_out: [...], know_this: [...]}} is bounded."""
        big = {
            "tiers": {
                "watch_out": [{"id": i, "summary": "a" * 500} for i in range(5_000)],
                "know_this": [{"id": i, "summary": "b" * 400} for i in range(5_000)],
                "reference": [{"id": i} for i in range(10)],
            },
            "function_index": {f"fn{i}": [f"note-{i}-{j}" for j in range(50)] for i in range(500)},
            "summary": {"total_notes": 10_010},
        }
        out = safe_json_dumps(big)
        self.assertLessEqual(len(out), RESPONSE_CHAR_LIMIT)
        d = json.loads(out)
        self.assertEqual(d["summary"]["total_notes"], 10_010)

    def test_single_giant_string_is_bounded(self) -> None:
        """A pathological lone giant string value is truncated, not propagated raw."""
        out = safe_json_dumps({"content": "q" * 5_000_000})
        self.assertLessEqual(len(out), RESPONSE_CHAR_LIMIT)
        d = json.loads(out)
        self.assertTrue(d["content"].endswith("...[truncated]"))

    def test_unserializable_object_does_not_raise(self) -> None:
        """A non-JSON-serializable value is coerced via default=str rather than raising."""
        class Widget:
            def __str__(self) -> str:
                return "a-widget"

        out = safe_json_dumps({"x": Widget(), "y": 1})
        d = json.loads(out)
        self.assertEqual(d["y"], 1)
        self.assertEqual(d["x"], "a-widget")

    def test_custom_max_chars_respected(self) -> None:
        """A tighter max_chars produces a tighter result."""
        big = {"results": [{"id": i, "blob": "x" * 100} for i in range(1_000)]}
        out = safe_json_dumps(big, max_chars=2_000)
        self.assertLessEqual(len(out), 2_000)

    def test_returns_string_always(self) -> None:
        """Return value is always a str, even for the give-up case."""
        # A deeply nested structure with no trimmable list/string slot large enough,
        # forced under an impossibly tiny cap -> minimal error string, still a str.
        out = safe_json_dumps({"a": {"b": {"c": "value"}}}, max_chars=5)
        self.assertIsInstance(out, str)
        # Still valid JSON.
        json.loads(out)


# ===================================================================
# cap_result_lists
# ===================================================================

class TestCapResultLists(unittest.TestCase):
    """Tests for utils.cap_result_lists()."""

    def test_caps_long_lists_keeps_short_ones(self) -> None:
        """Lists over the cap are trimmed with a marker; short lists and dicts untouched."""
        result = {
            "stale": [{"id": i} for i in range(120)],
            "orphaned": [{"id": "x"}, {"id": "y"}],
            "summary": {"total_issues": 122},
        }
        capped = cap_result_lists(result, max_per_list=50)
        self.assertEqual(len(capped["stale"]), 51)          # 50 + marker
        self.assertTrue(capped["stale"][-1].get("_truncated"))
        self.assertEqual(capped["stale"][-1]["_omitted"], 70)
        self.assertEqual(len(capped["orphaned"]), 2)        # untouched
        self.assertEqual(capped["summary"]["total_issues"], 122)

    def test_returns_same_object(self) -> None:
        """Mutates in place and returns the same dict (for chaining)."""
        result: dict[str, Any] = {"items": [1, 2, 3]}
        self.assertIs(cap_result_lists(result), result)


# ===================================================================
# search_notes respects max_results
# ===================================================================

class TestSearchMaxResults(unittest.TestCase):
    """search_notes truncates to max_results when one is given."""

    @staticmethod
    def _big_index(n: int = 300) -> dict[str, dict[str, Any]]:
        return {
            f"demo-note-{i}": {
                "library": "demo",
                "topic": f"demo note {i} about widgets and gadgets",
                "type": "knowledge",
                "source_quality": "documented",
                "confidence": "maybe",
                "lifecycle": "active",
                "summary": f"Note {i} explains widgets and gadgets in the demo library.",
                "notes": "Widgets connect to gadgets via the demo bus.",
                "related_functions": ["demo_connect"],
                "cues": ["How do widgets connect to gadgets?"],
                "tags": ["demo", "widget"],
            }
            for i in range(n)
        }

    def test_max_results_limits_count(self) -> None:
        """A query that matches everything still returns at most max_results."""
        index = self._big_index(300)
        result = search_notes(index, {"query": "widgets gadgets demo", "max_results": 25, "use_embeddings": False})
        self.assertLessEqual(result["count"], 25)
        self.assertLessEqual(len(result["results"]), 25)

    def test_filter_only_search_respects_max_results(self) -> None:
        """The pure-filter path (no query) is also bounded by max_results."""
        index = self._big_index(300)
        result = search_notes(index, {"library": "demo", "max_results": 10, "use_embeddings": False})
        self.assertLessEqual(len(result["results"]), 10)


# ===================================================================
# preflight respects context_budget
# ===================================================================

class TestPreflightBudget(unittest.TestCase):
    """preflight_notes assigns detail levels to fit a context_budget."""

    @staticmethod
    def _index(n_per_type: int = 40) -> dict[str, dict[str, Any]]:
        idx: dict[str, dict[str, Any]] = {}
        for kind in ("anti-pattern", "knowledge", "reference"):
            for i in range(n_per_type):
                nid = f"bigtopic-{kind}-{i}"
                idx[nid] = {
                    "library": "bigtopic",
                    "topic": f"{kind} note {i} with a fairly long descriptive topic line here",
                    "type": kind,
                    "source_quality": "documented",
                    "confidence": "maybe",
                    "lifecycle": "active",
                    "summary": "S" * 200,
                    "notes": "N" * 400,
                    "related_functions": [f"fn_{kind}_{i}"],
                    "cues": ["C" * 120],
                    "primitives_to_avoid": ["P" * 40] if kind == "anti-pattern" else [],
                    "preferred_alternatives": ["A" * 40] if kind == "anti-pattern" else [],
                    "tags": ["bigtopic"],
                }
        return idx

    def test_budget_keeps_tokens_in_range(self) -> None:
        """With a budget set, tokens_used is reported and roughly bounded."""
        index = self._index(40)
        result = preflight_notes(index, {"libraries": ["bigtopic"], "context_budget": 4_000, "include_cross_cutting": False})
        self.assertIn("tokens_used", result)
        # The estimator is approximate; allow generous headroom but not unbounded.
        self.assertLessEqual(result["tokens_used"], 4_000 * 3)

    def test_anti_patterns_stay_full_detail(self) -> None:
        """Anti-patterns keep their actionable fields even under a tight budget."""
        index = self._index(40)
        result = preflight_notes(index, {"libraries": ["bigtopic"], "context_budget": 2_000, "include_cross_cutting": False})
        watch_out = result["tiers"]["watch_out"]
        self.assertTrue(watch_out, "expected at least one anti-pattern note")
        # At least the first watch_out note should be full detail (level 3) with primitives.
        self.assertEqual(watch_out[0].get("detail_level", 3), 3)
        self.assertIn("primitives_to_avoid", watch_out[0])

    def test_serialized_preflight_under_hard_cap(self) -> None:
        """Even a large in-scope set serializes under the response char limit via safe_json_dumps."""
        index = self._index(80)
        result = preflight_notes(index, {"libraries": ["bigtopic"], "context_budget": 12_000, "include_cross_cutting": False})
        self.assertLessEqual(len(safe_json_dumps(result)), RESPONSE_CHAR_LIMIT)


if __name__ == "__main__":
    unittest.main()
