"""Embedding module for semantic search in notemap.

Uses model2vec for lightweight, fast text embeddings. Gracefully degrades
to None/empty returns when model2vec is not installed.
"""
from __future__ import annotations

import struct
from typing import Any

import numpy as np

# Try importing model2vec -- set availability flag
EMBEDDINGS_AVAILABLE = False
_model = None
MODEL_NAME = "minishlab/potion-base-8M"
DIMENSIONS = 256

try:
    from model2vec import StaticModel
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    StaticModel = None

# Module-level cache for the embedding matrix
_matrix_cache: dict[str, Any] = {}


def get_model() -> Any | None:
    """Return cached StaticModel instance. Load on first call.

    Returns None if model2vec is not installed.
    """
    global _model
    if not EMBEDDINGS_AVAILABLE:
        return None
    if _model is None:
        _model = StaticModel.from_pretrained(MODEL_NAME)
    return _model


def encode_texts(texts: list[str]) -> np.ndarray | None:
    """Encode a list of texts into L2-normalized embeddings.

    Returns an (N, 256) float32 ndarray, or None if unavailable.
    """
    model = get_model()
    if model is None:
        return None
    vectors = model.encode(texts)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vectors / norms).astype(np.float32)


def encode_text(text: str) -> bytes | None:
    """Encode a single text and return as packed float32 bytes.

    Returns None if model2vec is not installed.
    """
    result = encode_texts([text])
    if result is None:
        return None
    vec = result[0]
    return struct.pack(f"{len(vec)}f", *vec)


def decode_vector(blob: bytes) -> np.ndarray:
    """Unpack bytes back to a float32 numpy array."""
    return np.frombuffer(blob, dtype=np.float32).copy()


def load_embedding_matrix(conn) -> tuple[list[str], np.ndarray] | None:
    """Load all note embeddings from the database into a matrix.

    Returns (note_ids_list, matrix) where matrix is (N, dimensions) float32.
    Uses a module-level cache; call invalidate_cache() after mutations.
    Returns None if no embeddings exist.
    """
    if "ids" in _matrix_cache and "matrix" in _matrix_cache:
        return _matrix_cache["ids"], _matrix_cache["matrix"]

    rows = conn.execute(
        "SELECT note_id, vector FROM note_embeddings ORDER BY note_id"
    ).fetchall()
    if not rows:
        return None

    ids = []
    vectors = []
    for row in rows:
        ids.append(row["note_id"] if hasattr(row, "keys") else row[0])
        blob = row["vector"] if hasattr(row, "keys") else row[1]
        vectors.append(decode_vector(blob))

    matrix = np.vstack(vectors).astype(np.float32)
    _matrix_cache["ids"] = ids
    _matrix_cache["matrix"] = matrix
    return ids, matrix


def invalidate_cache() -> None:
    """Clear the cached embedding matrix.

    Call after note create, update, or delete operations.
    """
    _matrix_cache.clear()


def vector_search(
    query_text: str,
    note_ids: list[str],
    matrix: np.ndarray,
    top_k: int = 20,
) -> list[tuple[str, float]]:
    """Search notes by vector similarity.

    Encodes the query, computes cosine similarity via matmul against the
    pre-normalized matrix, and returns up to top_k (note_id, score) pairs
    sorted by descending similarity.
    """
    result = encode_texts([query_text])
    if result is None:
        return []
    query_vec = result[0]
    scores = matrix @ query_vec
    top_indices = np.argsort(scores)[::-1][:top_k]
    return [(note_ids[i], float(scores[i])) for i in top_indices]
