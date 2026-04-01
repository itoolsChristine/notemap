"""Tests for the text chunking module."""
from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

# Add the source directory to sys.path so we can import directly.
_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src" / "notemap-mcp")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from chunk import chunk_text, chunk_with_sections, store_chunks, get_chunks_for_note  # noqa: E402
from db import close_db, get_db  # noqa: E402
from utils import estimate_tokens  # noqa: E402


class TestChunkTextBasic(unittest.TestCase):
    """Core chunking behavior tests."""

    def test_basic_split(self) -> None:
        """Simple text is split into at least one chunk."""
        text = "Hello world. This is a test."
        chunks = chunk_text(text)
        self.assertGreaterEqual(len(chunks), 1)
        self.assertIn("content", chunks[0])
        self.assertIn("chunk_index", chunks[0])
        self.assertIn("token_count", chunks[0])

    def test_empty_text_returns_empty(self) -> None:
        """Empty or whitespace-only text returns no chunks."""
        self.assertEqual(chunk_text(""), [])
        self.assertEqual(chunk_text("   "), [])
        self.assertEqual(chunk_text(None), [])

    def test_single_paragraph_one_chunk(self) -> None:
        """Text shorter than max_tokens returns exactly one chunk."""
        text = "Short paragraph that fits in one chunk."
        chunks = chunk_text(text, max_tokens=1000)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["content"], text)
        self.assertEqual(chunks[0]["chunk_index"], 0)

    def test_no_chunk_exceeds_max_tokens(self) -> None:
        """No chunk's token_count exceeds max_tokens (with reasonable tolerance)."""
        # Build text with many paragraphs
        paragraphs = [f"Paragraph {i}. " * 20 for i in range(20)]
        text = "\n\n".join(paragraphs)
        max_tokens = 100
        chunks = chunk_text(text, max_tokens=max_tokens)
        for chunk in chunks:
            # Allow some tolerance since paragraph boundaries may cause slight overflows
            self.assertLessEqual(
                chunk["token_count"], max_tokens * 1.5,
                f"Chunk {chunk['chunk_index']} exceeds budget: {chunk['token_count']} > {max_tokens}"
            )

    def test_paragraph_boundaries(self) -> None:
        """Text splits on double newlines (paragraph boundaries)."""
        # Each paragraph must exceed max_tokens to force multiple chunks
        text = (
            "First paragraph with enough words to be quite long indeed.\n\n"
            "Second paragraph also with enough words to push over the limit.\n\n"
            "Third paragraph similarly padded with extra text for length."
        )
        # Use very small max_tokens to guarantee splits
        chunks = chunk_text(text, max_tokens=5)
        # Should produce multiple chunks
        self.assertGreaterEqual(len(chunks), 2)

    def test_chunk_indices_sequential(self) -> None:
        """Chunk indices are sequential starting from 0."""
        text = "Para one.\n\n" * 10
        chunks = chunk_text(text, max_tokens=30)
        for i, chunk in enumerate(chunks):
            self.assertEqual(chunk["chunk_index"], i)


class TestChunkTextOverlap(unittest.TestCase):
    """Tests for chunk overlap behavior."""

    def test_overlap_content_shared(self) -> None:
        """Adjacent chunks share content from the overlap region."""
        # Create enough text to force multiple chunks
        paragraphs = [f"Paragraph number {i} with some extra words." for i in range(20)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_text(text, max_tokens=50, overlap_tokens=20)
        if len(chunks) >= 2:
            # The tail of chunk 0 should appear in chunk 1 due to overlap
            # Check that at least one paragraph from chunk 0 appears in chunk 1
            c0_parts = chunks[0]["content"].split("\n\n")
            c1_content = chunks[1]["content"]
            overlap_found = any(part in c1_content for part in c0_parts[-2:])
            self.assertTrue(
                overlap_found,
                "Expected overlap content between adjacent chunks"
            )


class TestChunkWithSections(unittest.TestCase):
    """Tests for section-aware chunking."""

    def test_headings_create_boundaries(self) -> None:
        """Markdown headings create section boundaries in chunks."""
        text = (
            "# Introduction\n\n"
            "Intro content here.\n\n"
            "# Methods\n\n"
            "Methods content here.\n\n"
            "# Results\n\n"
            "Results content here."
        )
        chunks = chunk_with_sections(text, "doc", "/path/to/doc.md")
        sections = [c["section"] for c in chunks]
        self.assertIn("Introduction", sections)
        self.assertIn("Methods", sections)
        self.assertIn("Results", sections)

    def test_metadata_fields_present(self) -> None:
        """Section-aware chunks include source metadata fields."""
        text = "# Test\n\nSome content."
        chunks = chunk_with_sections(
            text,
            source_type="doc",
            source_path="/docs/test.md",
            source_title="Test Doc",
        )
        self.assertGreaterEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertEqual(chunk["source_type"], "doc")
        self.assertEqual(chunk["source_path"], "/docs/test.md")
        self.assertEqual(chunk["source_title"], "Test Doc")
        self.assertIn("section", chunk)

    def test_no_headings_fallback(self) -> None:
        """Text without headings falls back to plain chunking with metadata."""
        text = "Just plain text without any headings."
        chunks = chunk_with_sections(text, "doc", "/path.md")
        self.assertGreaterEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["source_type"], "doc")
        self.assertEqual(chunks[0]["section"], "")

    def test_empty_text_returns_empty(self) -> None:
        """Empty text returns no chunks."""
        self.assertEqual(chunk_with_sections("", "doc", "/path.md"), [])
        self.assertEqual(chunk_with_sections("  \n  ", "doc", "/path.md"), [])

    def test_content_before_first_heading(self) -> None:
        """Content before the first heading gets its own chunk(s)."""
        text = "Preamble text.\n\n# First Section\n\nSection content."
        chunks = chunk_with_sections(text, "doc", "/path.md")
        # The preamble should appear with empty section
        preamble_chunks = [c for c in chunks if c["section"] == ""]
        self.assertGreaterEqual(len(preamble_chunks), 1)
        self.assertIn("Preamble", preamble_chunks[0]["content"])


class TestStoreChunks(unittest.TestCase):
    """Tests for storing chunks in the database."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_chunk_"))
        self.conn = get_db(self.tmp_dir)

    def tearDown(self) -> None:
        close_db()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_returns_ids(self) -> None:
        """store_chunks returns a list of integer chunk IDs."""
        chunks = [
            {"content": "Chunk one", "chunk_index": 0, "token_count": 3,
             "source_type": "doc", "source_path": "/a.md"},
            {"content": "Chunk two", "chunk_index": 1, "token_count": 3,
             "source_type": "doc", "source_path": "/a.md"},
        ]
        ids = store_chunks(chunks, self.conn)
        self.assertEqual(len(ids), 2)
        for cid in ids:
            self.assertIsInstance(cid, int)
            self.assertGreater(cid, 0)

    def test_empty_list_returns_empty(self) -> None:
        """store_chunks([]) returns an empty list."""
        self.assertEqual(store_chunks([], self.conn), [])

    def test_chunks_persisted(self) -> None:
        """Stored chunks are readable from the database."""
        chunks = [
            {"content": "Persisted chunk", "chunk_index": 0, "token_count": 3,
             "source_type": "note", "source_path": "/b.md", "section": "Intro"},
        ]
        ids = store_chunks(chunks, self.conn)
        row = self.conn.execute(
            "SELECT * FROM chunks WHERE id = ?", (ids[0],)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["content"], "Persisted chunk")
        self.assertEqual(row["section"], "Intro")
        self.assertEqual(row["source_type"], "note")


class TestGetChunksForNote(unittest.TestCase):
    """Tests for retrieving chunks linked to a note."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_getchunk_"))
        self.conn = get_db(self.tmp_dir)
        # Insert a note
        self.conn.execute(
            "INSERT INTO notes (id, library, topic) VALUES (?, ?, ?)",
            ("test-note", "testlib", "Test Note"),
        )
        # Insert chunks and link them
        self.conn.execute(
            "INSERT INTO chunks (id, source_type, source_path, chunk_index, content, token_count, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, "doc", "/test.md", 0, "Chunk content A", 4, "2026-01-01"),
        )
        self.conn.execute(
            "INSERT INTO chunks (id, source_type, source_path, chunk_index, content, token_count, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (2, "doc", "/test.md", 1, "Chunk content B", 4, "2026-01-01"),
        )
        self.conn.execute(
            "INSERT INTO note_chunks (note_id, chunk_id, relevance) VALUES (?, ?, ?)",
            ("test-note", 1, "primary"),
        )
        self.conn.execute(
            "INSERT INTO note_chunks (note_id, chunk_id, relevance) VALUES (?, ?, ?)",
            ("test-note", 2, "supporting"),
        )
        self.conn.commit()

    def tearDown(self) -> None:
        close_db()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_returns_linked_chunks(self) -> None:
        """get_chunks_for_note returns all chunks linked to the note."""
        chunks = get_chunks_for_note("test-note", self.conn)
        self.assertEqual(len(chunks), 2)
        contents = [c["content"] for c in chunks]
        self.assertIn("Chunk content A", contents)
        self.assertIn("Chunk content B", contents)

    def test_includes_relevance(self) -> None:
        """Returned chunks include the relevance tag from the join table."""
        chunks = get_chunks_for_note("test-note", self.conn)
        relevances = {c["content"]: c["relevance"] for c in chunks}
        self.assertEqual(relevances["Chunk content A"], "primary")
        self.assertEqual(relevances["Chunk content B"], "supporting")

    def test_no_linked_chunks_returns_empty(self) -> None:
        """Note with no linked chunks returns empty list."""
        self.conn.execute(
            "INSERT INTO notes (id, library, topic) VALUES (?, ?, ?)",
            ("orphan-note", "testlib", "Orphan"),
        )
        self.conn.commit()
        chunks = get_chunks_for_note("orphan-note", self.conn)
        self.assertEqual(chunks, [])

    def test_ordered_by_chunk_index(self) -> None:
        """Returned chunks are ordered by chunk_index."""
        chunks = get_chunks_for_note("test-note", self.conn)
        indices = [c["chunk_index"] for c in chunks]
        self.assertEqual(indices, sorted(indices))


if __name__ == "__main__":
    unittest.main()
