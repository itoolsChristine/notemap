"""Tests for hybrid BM25F + vector search."""
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

from search import reciprocal_rank_fusion, search_notes  # noqa: E402


class TestReciprocalRankFusion(unittest.TestCase):
    """Tests for the RRF merge function."""

    def test_basic_merge(self) -> None:
        """Two ranked lists merge correctly with RRF scoring."""
        list_a = [("note-1", 10.0), ("note-2", 8.0), ("note-3", 6.0)]
        list_b = [("note-3", 9.0), ("note-1", 7.0), ("note-4", 5.0)]
        result = reciprocal_rank_fusion([list_a, list_b])
        result_ids = [r[0] for r in result]
        # All IDs from both lists should be present
        self.assertEqual(set(result_ids), {"note-1", "note-2", "note-3", "note-4"})
        # All scores should be positive
        for _, score in result:
            self.assertGreater(score, 0.0)

    def test_single_list(self) -> None:
        """With one list, RRF preserves the original order."""
        ranked = [("a", 10.0), ("b", 5.0), ("c", 1.0)]
        result = reciprocal_rank_fusion([ranked])
        result_ids = [r[0] for r in result]
        self.assertEqual(result_ids, ["a", "b", "c"])

    def test_overlapping_ids_score_higher(self) -> None:
        """IDs appearing in both lists get higher RRF scores."""
        list_a = [("shared", 10.0), ("only-a", 5.0)]
        list_b = [("shared", 10.0), ("only-b", 5.0)]
        result = reciprocal_rank_fusion([list_a, list_b])
        scores = {r[0]: r[1] for r in result}
        # "shared" appears in both lists at rank 0, so should score higher
        self.assertGreater(scores["shared"], scores["only-a"])
        self.assertGreater(scores["shared"], scores["only-b"])

    def test_empty_lists(self) -> None:
        """Empty input returns empty output."""
        self.assertEqual(reciprocal_rank_fusion([]), [])
        self.assertEqual(reciprocal_rank_fusion([[]]), [])
        self.assertEqual(reciprocal_rank_fusion([[], []]), [])

    def test_sorted_descending(self) -> None:
        """Output is sorted by RRF score descending."""
        list_a = [("x", 1.0), ("y", 2.0)]
        list_b = [("y", 1.0), ("z", 2.0)]
        result = reciprocal_rank_fusion([list_a, list_b])
        scores = [r[1] for r in result]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_k_parameter(self) -> None:
        """Different k values change scores but not relative order of overlapping items."""
        ranked = [("a", 10.0), ("b", 5.0)]
        result_60 = reciprocal_rank_fusion([ranked], k=60)
        result_10 = reciprocal_rank_fusion([ranked], k=10)
        # Both should have same order
        self.assertEqual(
            [r[0] for r in result_60],
            [r[0] for r in result_10],
        )
        # But different absolute scores
        self.assertNotEqual(result_60[0][1], result_10[0][1])


class TestSearchNotesBackwardCompat(unittest.TestCase):
    """Verify existing search_notes interface still works with new parameters."""

    def setUp(self) -> None:
        self.index: dict[str, dict[str, Any]] = {
            "test-note": {
                "library":            "testlib",
                "topic":              "Test note for backward compatibility",
                "type":               "knowledge",
                "source_quality":     "documented",
                "confidence":         "strong",
                "lifecycle":          "active",
                "summary":            "A simple test note.",
                "related_functions":  ["test_func"],
                "cues":               ["Is this backward compatible?"],
                "tags":               ["testing"],
            },
        }

    def test_search_without_use_embeddings(self) -> None:
        """Calling search_notes without use_embeddings param still works."""
        result = search_notes(self.index, {"library": "testlib"})
        self.assertIn("count", result)
        self.assertIn("results", result)
        self.assertEqual(result["count"], 1)

    def test_search_with_use_embeddings_false(self) -> None:
        """Explicitly setting use_embeddings=False still works."""
        result = search_notes(self.index, {
            "query": "test",
            "use_embeddings": False,
        })
        self.assertIn("count", result)
        self.assertIn("results", result)

    def test_result_fields_unchanged(self) -> None:
        """Result entries still contain all expected fields."""
        result = search_notes(self.index, {"library": "testlib"})
        expected_keys = {
            "id", "library", "library_version", "topic", "type",
            "source_quality", "confidence", "lifecycle", "summary",
            "sources", "related_functions", "relevance_score",
        }
        for r in result["results"]:
            self.assertTrue(
                expected_keys.issubset(set(r.keys())),
                f"Missing keys: {expected_keys - set(r.keys())}",
            )


class TestVectorOnlyCandidates(unittest.TestCase):
    """Test that vector search can surface notes BM25F missed (vocabulary gap)."""

    def setUp(self) -> None:
        # Note uses domain-specific terms with zero word overlap to queries
        self.index: dict[str, dict[str, Any]] = {
            "learning-recitation-ratio": {
                "library":            "learning-principles",
                "topic":              "80-20 recitation ratio active use beats passive reading",
                "type":               "convention",
                "source_quality":     "documented",
                "confidence":         "strong",
                "lifecycle":          "active",
                "summary":            "Actively using and creating notes (80%) beats passively reading code (20%).",
                "notes_body":         "Note creation is learning, not overhead.",
                "related_functions":  [],
                "cues":               ["What ratio of active vs passive learning is optimal?"],
                "tags":               ["learning", "study-technique"],
            },
            "learning-macaulay-method": {
                "library":            "learning-principles",
                "topic":              "Macaulay method summarize before moving on",
                "type":               "convention",
                "source_quality":     "documented",
                "confidence":         "strong",
                "lifecycle":          "active",
                "summary":            "Summarize what you learned from each file before moving to the next.",
                "notes_body":         "Don't accumulate reads without synthesis.",
                "related_functions":  [],
                "cues":               ["Should I summarize after reading each file?"],
                "tags":               ["learning", "comprehension"],
            },
            "zendb-unrelated": {
                "library":            "zendb",
                "topic":              "DB::get returns empty SmartArrayHtml on no match",
                "type":               "knowledge",
                "source_quality":     "verified-from-source",
                "confidence":         "strong",
                "lifecycle":          "active",
                "summary":            "DB::get always returns SmartArrayHtml.",
                "related_functions":  ["DB::get"],
                "cues":               [],
                "tags":               ["zendb"],
            },
        }

    def _ids(self, result: dict[str, Any]) -> list[str]:
        return [r["id"] for r in result["results"]]

    def test_bm25f_misses_vocabulary_gap_query(self) -> None:
        """BM25F alone cannot find notes when query terms don't overlap."""
        result = search_notes(self.index, {
            "query": "memorizing",
            "use_embeddings": False,
        })
        # "memorizing" has zero word overlap with "recitation", "Macaulay", etc.
        self.assertNotIn("learning-recitation-ratio", self._ids(result))
        self.assertNotIn("learning-macaulay-method", self._ids(result))

    def _patch_embeddings(self, fake_vec_results):
        """Context manager that mocks the embedding pipeline for testing."""
        from unittest.mock import patch, MagicMock
        from contextlib import ExitStack

        stack = ExitStack()
        stack.enter_context(patch.object(
            sys.modules["search"], "EMBEDDINGS_AVAILABLE", True,
        ))
        stack.enter_context(patch.object(
            sys.modules["search"], "load_embedding_matrix",
            return_value=([r[0] for r in fake_vec_results], None),
        ))
        stack.enter_context(patch.object(
            sys.modules["search"], "_vector_search",
            return_value=fake_vec_results,
        ))
        # Mock get_db so it doesn't need a real database
        stack.enter_context(patch(
            "search.get_db", return_value=MagicMock(),
        ))
        return stack

    def test_vector_only_candidates_surface_on_vocabulary_gap(self) -> None:
        """Vector search surfaces notes when BM25F returns nothing."""
        fake_vec_results = [
            ("learning-recitation-ratio", 0.85),
            ("learning-macaulay-method", 0.72),
            ("zendb-unrelated", 0.15),
        ]

        with self._patch_embeddings(fake_vec_results):
            result = search_notes(self.index, {
                "query": "memorizing",
                "use_embeddings": True,
            })

        ids = self._ids(result)
        # Vector search should surface notes that BM25F missed
        self.assertIn("learning-recitation-ratio", ids)
        self.assertIn("learning-macaulay-method", ids)
        # They should have _rrf_score set
        for r in result["results"]:
            if r["id"] in ("learning-recitation-ratio", "learning-macaulay-method"):
                self.assertIn("_rrf_score", r)
                self.assertGreater(r["_rrf_score"], 0.0)

    def test_vector_only_candidates_respect_library_filter(self) -> None:
        """Vector-only candidates are still filtered by library when specified."""
        fake_vec_results = [
            ("learning-recitation-ratio", 0.85),
            ("zendb-unrelated", 0.60),
        ]

        with self._patch_embeddings(fake_vec_results):
            result = search_notes(self.index, {
                "query": "memorizing",
                "library": "zendb",
                "use_embeddings": True,
            })

        ids = self._ids(result)
        # learning-principles note should be filtered out by library=zendb
        self.assertNotIn("learning-recitation-ratio", ids)

    def test_vector_only_candidates_respect_lifecycle_filter(self) -> None:
        """Vector-only candidates with wrong lifecycle are excluded."""
        # Add a stale note to the index
        self.index["stale-note"] = {
            "library":            "learning-principles",
            "topic":              "Stale learning note",
            "type":               "knowledge",
            "source_quality":     "documented",
            "confidence":         "strong",
            "lifecycle":          "stale",
            "summary":            "This note is stale.",
            "related_functions":  [],
            "cues":               [],
            "tags":               [],
        }

        fake_vec_results = [
            ("stale-note", 0.90),
            ("learning-recitation-ratio", 0.70),
        ]

        with self._patch_embeddings(fake_vec_results):
            result = search_notes(self.index, {
                "query": "memorizing",
                "use_embeddings": True,
            })

        ids = self._ids(result)
        # Stale note should be excluded (default lifecycle=active)
        self.assertNotIn("stale-note", ids)
        # Active note should still surface
        self.assertIn("learning-recitation-ratio", ids)

    def test_bm25f_and_vector_results_merge_correctly(self) -> None:
        """When both BM25F and vectors find results, they merge via RRF."""
        # "active" appears in the recitation note summary ("Actively using")
        # so BM25F will find it. Vector search also finds macaulay.
        fake_vec_results = [
            ("learning-macaulay-method", 0.90),
            ("learning-recitation-ratio", 0.80),
        ]

        with self._patch_embeddings(fake_vec_results):
            result = search_notes(self.index, {
                "query": "actively learning summarize",
                "use_embeddings": True,
            })

        ids = self._ids(result)
        # Both notes should appear - one from BM25F, one from vectors (or both)
        self.assertIn("learning-recitation-ratio", ids)
        self.assertIn("learning-macaulay-method", ids)


if __name__ == "__main__":
    unittest.main()
