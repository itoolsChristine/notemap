"""Tests for the embedding module."""
from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

import numpy as np

# Add the source directory to sys.path so we can import directly.
_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src" / "notemap-mcp")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from embed import (  # noqa: E402
    EMBEDDINGS_AVAILABLE,
    DIMENSIONS,
    decode_vector,
    encode_text,
    encode_texts,
    get_model,
    invalidate_cache,
    vector_search,
)


class TestEmbeddingsAvailability(unittest.TestCase):
    """Verify model2vec is installed and the model loads."""

    def test_embeddings_available(self) -> None:
        """EMBEDDINGS_AVAILABLE is True when model2vec is installed."""
        self.assertTrue(EMBEDDINGS_AVAILABLE)

    def test_get_model_returns_model(self) -> None:
        """get_model() returns a non-None model object."""
        model = get_model()
        self.assertIsNotNone(model)


class TestEncodeTexts(unittest.TestCase):
    """Tests for batch text encoding."""

    def test_shape(self) -> None:
        """encode_texts returns an ndarray with shape (N, DIMENSIONS)."""
        result = encode_texts(["hello", "world"])
        self.assertIsInstance(result, np.ndarray)
        self.assertEqual(result.shape, (2, DIMENSIONS))

    def test_normalized(self) -> None:
        """Returned vectors have L2 norm approximately 1.0."""
        result = encode_texts(["The quick brown fox", "jumped over the lazy dog"])
        for i in range(result.shape[0]):
            norm = float(np.linalg.norm(result[i]))
            self.assertAlmostEqual(norm, 1.0, places=4)

    def test_dtype_is_float32(self) -> None:
        """Returned array is float32."""
        result = encode_texts(["test"])
        self.assertEqual(result.dtype, np.float32)

    def test_empty_list(self) -> None:
        """encode_texts([]) either returns None, an empty array, or raises."""
        try:
            result = encode_texts([])
            # If it returns without error, check it's empty or None
            if result is not None:
                self.assertEqual(result.shape[0], 0)
        except (ValueError, IndexError):
            # model2vec.encode raises ValueError on empty input - acceptable
            pass


class TestEncodeSingle(unittest.TestCase):
    """Tests for single text encoding and byte roundtrip."""

    def test_returns_bytes(self) -> None:
        """encode_text returns bytes of length DIMENSIONS * 4."""
        result = encode_text("test embedding")
        self.assertIsInstance(result, bytes)
        self.assertEqual(len(result), DIMENSIONS * 4)

    def test_roundtrip(self) -> None:
        """encode_text -> decode_vector produces a valid float32 array."""
        blob = encode_text("roundtrip test")
        vec = decode_vector(blob)
        self.assertIsInstance(vec, np.ndarray)
        self.assertEqual(vec.shape, (DIMENSIONS,))
        self.assertEqual(vec.dtype, np.float32)

    def test_roundtrip_values_preserved(self) -> None:
        """Encoding then decoding preserves vector values."""
        blob = encode_text("value preservation test")
        vec = decode_vector(blob)
        # Re-encode and compare
        expected = encode_texts(["value preservation test"])[0]
        np.testing.assert_array_almost_equal(vec, expected, decimal=5)


class TestDecodeVector(unittest.TestCase):
    """Tests for blob-to-vector decoding."""

    def test_known_bytes(self) -> None:
        """decode_vector correctly unpacks known float32 bytes."""
        values = [1.0, 2.0, 3.0]
        blob = struct.pack(f"{len(values)}f", *values)
        result = decode_vector(blob)
        np.testing.assert_array_equal(result, np.array(values, dtype=np.float32))


class TestVectorSearch(unittest.TestCase):
    """Tests for the vector_search function."""

    def setUp(self) -> None:
        """Build a small matrix of known vectors for testing."""
        self.note_ids = ["note-a", "note-b", "note-c"]
        # Create 3 distinct normalized vectors
        raw = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.7, 0.7, 0.0],
        ], dtype=np.float32)
        norms = np.linalg.norm(raw, axis=1, keepdims=True)
        self.matrix = (raw / norms).astype(np.float32)
        # Pad to DIMENSIONS with zeros for real vector_search
        self.full_matrix = np.zeros((3, DIMENSIONS), dtype=np.float32)
        self.full_matrix[:, :3] = self.matrix

    def test_returns_sorted_descending(self) -> None:
        """Results are sorted by score descending."""
        results = vector_search("test query", self.note_ids, self.full_matrix, top_k=3)
        scores = [s for _, s in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_top_k_limits_results(self) -> None:
        """Results are limited to top_k entries."""
        results = vector_search("test", self.note_ids, self.full_matrix, top_k=2)
        self.assertLessEqual(len(results), 2)

    def test_result_format(self) -> None:
        """Each result is a (note_id, float_score) tuple."""
        results = vector_search("test", self.note_ids, self.full_matrix, top_k=3)
        for item in results:
            self.assertEqual(len(item), 2)
            self.assertIsInstance(item[0], str)
            self.assertIsInstance(item[1], float)


class TestInvalidateCache(unittest.TestCase):
    """Tests for cache invalidation."""

    def test_invalidate_cache_runs_without_error(self) -> None:
        """invalidate_cache() does not raise."""
        invalidate_cache()

    def test_invalidate_cache_clears_state(self) -> None:
        """After invalidate_cache(), the module cache dict is empty."""
        from embed import _matrix_cache
        _matrix_cache["ids"] = ["fake"]
        _matrix_cache["matrix"] = "fake"
        invalidate_cache()
        self.assertNotIn("ids", _matrix_cache)
        self.assertNotIn("matrix", _matrix_cache)


if __name__ == "__main__":
    unittest.main()
