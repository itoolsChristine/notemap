"""Text chunking module for notemap knowledge ingestion.

Splits text into boundary-aware chunks for storage and embedding.
"""
from __future__ import annotations

import re
from typing import Any

from utils import estimate_tokens, today_str

try:
    from embed import encode_text, EMBEDDINGS_AVAILABLE
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    encode_text = None


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')


def _split_sentences(text: str) -> list[str]:
    """Split text on sentence boundaries (. ! ?)."""
    parts = _SENTENCE_RE.split(text)
    return [s for s in parts if s.strip()]


# ---------------------------------------------------------------------------
# Core chunking
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    max_tokens: int = 800,
    overlap_tokens: int = 100,
) -> list[dict[str, Any]]:
    """Split text into token-bounded chunks with overlap.

    Splits on double newlines (paragraphs) first. If a paragraph exceeds
    max_tokens, splits on sentence boundaries. Overlap includes the last
    overlap_tokens worth of text from the previous chunk.

    Returns a list of dicts with content, chunk_index, and token_count.
    """
    if not text or not text.strip():
        return []

    paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    # Expand paragraphs that exceed max_tokens into sentences
    segments: list[str] = []
    for para in paragraphs:
        if estimate_tokens(para) <= max_tokens:
            segments.append(para)
        else:
            sentences = _split_sentences(para)
            if sentences:
                segments.extend(sentences)
            else:
                segments.append(para)

    # Accumulate segments into chunks
    chunks: list[dict[str, Any]] = []
    current_parts: list[str] = []
    current_tokens = 0

    for segment in segments:
        seg_tokens = estimate_tokens(segment)
        if current_parts and current_tokens + seg_tokens > max_tokens:
            content = "\n\n".join(current_parts)
            chunks.append({
                "content": content,
                "chunk_index": len(chunks),
                "token_count": estimate_tokens(content),
            })
            # Build overlap from tail of current_parts
            overlap_parts: list[str] = []
            overlap_count = 0
            for part in reversed(current_parts):
                part_tokens = estimate_tokens(part)
                if overlap_count + part_tokens > overlap_tokens:
                    break
                overlap_parts.insert(0, part)
                overlap_count += part_tokens
            current_parts = overlap_parts
            current_tokens = overlap_count

        current_parts.append(segment)
        current_tokens += seg_tokens

    # Final chunk
    if current_parts:
        content = "\n\n".join(current_parts)
        chunks.append({
            "content": content,
            "chunk_index": len(chunks),
            "token_count": estimate_tokens(content),
        })

    return chunks


# ---------------------------------------------------------------------------
# Section-aware chunking
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)


def chunk_with_sections(
    text: str,
    source_type: str,
    source_path: str,
    source_title: str = "",
    max_tokens: int = 800,
    overlap_tokens: int = 100,
) -> list[dict[str, Any]]:
    """Chunk text with awareness of markdown section boundaries.

    Detects markdown headings (# lines) and always starts a new chunk at
    a section boundary. Each chunk includes metadata about its source.

    Returns a list of dicts with chunk_text fields plus source metadata.
    """
    if not text or not text.strip():
        return []

    # Find all headings and their positions
    headings = list(_HEADING_RE.finditer(text))

    if not headings:
        # No headings - fall back to plain chunking with metadata
        plain_chunks = chunk_text(text, max_tokens, overlap_tokens)
        for chunk in plain_chunks:
            chunk["source_type"] = source_type
            chunk["source_path"] = source_path
            chunk["source_title"] = source_title
            chunk["section"] = ""
        return plain_chunks

    # Split text into sections
    sections: list[tuple[str, str]] = []  # (heading_text, section_content)

    # Content before first heading
    pre_heading = text[:headings[0].start()].strip()
    if pre_heading:
        sections.append(("", pre_heading))

    for i, match in enumerate(headings):
        heading_text = match.group(2).strip()
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        section_content = text[start:end].strip()
        if section_content:
            sections.append((heading_text, section_content))

    # Chunk each section independently, then assemble
    all_chunks: list[dict[str, Any]] = []
    for heading_text, section_content in sections:
        section_chunks = chunk_text(section_content, max_tokens, overlap_tokens)
        for chunk in section_chunks:
            chunk["chunk_index"] = len(all_chunks)
            chunk["source_type"] = source_type
            chunk["source_path"] = source_path
            chunk["source_title"] = source_title
            chunk["section"] = heading_text
            all_chunks.append(chunk)

    return all_chunks


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def store_chunks(
    chunks: list[dict[str, Any]],
    conn: Any,
) -> list[int]:
    """Store chunks in the database and optionally generate embeddings.

    Inserts each chunk into the chunks table. If embeddings are available,
    generates and stores an embedding for each chunk's content.

    Returns a list of chunk IDs (integer primary keys).
    """
    if not chunks:
        return []

    today = today_str()
    chunk_ids: list[int] = []

    for chunk in chunks:
        cursor = conn.execute(
            """INSERT INTO chunks (
                source_type, source_path, source_title, section,
                chunk_index, content, token_count, created
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chunk.get("source_type", ""),
                chunk.get("source_path", ""),
                chunk.get("source_title", ""),
                chunk.get("section", ""),
                chunk.get("chunk_index", 0),
                chunk["content"],
                chunk.get("token_count", 0),
                today,
            ),
        )
        chunk_id = cursor.lastrowid
        chunk_ids.append(chunk_id)

        if EMBEDDINGS_AVAILABLE and encode_text is not None:
            vec_bytes = encode_text(chunk["content"])
            if vec_bytes is not None:
                from embed import MODEL_NAME, DIMENSIONS
                conn.execute(
                    "INSERT OR REPLACE INTO chunk_embeddings (chunk_id, model, dimensions, vector) VALUES (?, ?, ?, ?)",
                    (chunk_id, MODEL_NAME, DIMENSIONS, vec_bytes),
                )

    conn.commit()
    return chunk_ids


def get_chunks_for_note(
    note_id: str,
    conn: Any,
) -> list[dict[str, Any]]:
    """Retrieve all chunks linked to a note via the note_chunks join table.

    Returns a list of chunk dicts with all stored fields plus the relevance tag.
    """
    rows = conn.execute(
        """SELECT c.*, nc.relevance
        FROM chunks c
        JOIN note_chunks nc ON nc.chunk_id = c.id
        WHERE nc.note_id = ?
        ORDER BY c.chunk_index""",
        (note_id,),
    ).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        result.append({
            "id": row["id"],
            "source_type": row["source_type"],
            "source_path": row["source_path"],
            "source_title": row["source_title"],
            "section": row["section"],
            "chunk_index": row["chunk_index"],
            "content": row["content"],
            "token_count": row["token_count"],
            "created": row["created"],
            "relevance": row["relevance"],
        })

    return result
