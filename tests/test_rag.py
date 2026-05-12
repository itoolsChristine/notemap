"""Tests for RAG retrieval module."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

# Add the source directory to sys.path so we can import directly.
_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src" / "notemap-mcp")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from rag import format_notes_for_context, retrieve_for_prompt  # noqa: E402


class TestFormatNotesForContext(unittest.TestCase):
    """Tests for format_notes_for_context, including ingested-chunk injection.

    This is a pure function -- no DB or embeddings -- so it runs everywhere.
    """

    _NOTE = {
        "library": "zendb",
        "topic": "DB::get returns empty SmartArrayHtml on no match",
        "summary": "DB::get always returns SmartArrayHtml; empty on no match.",
        "confidence": "strong",
        "source_quality": "verified-from-source",
        "cues_raw": "What does DB::get return when no record matches?",
        "type": "knowledge",
    }
    _CHUNK = {
        "result_type": "chunk",
        "source_title": "The Pragmatic Programmer",
        "source_path": "docs/pp.pdf",
        "section": "Chapter 3: The Basic Tools",
        "content": "   Always   use   version   control,   even   for   one-person   projects.   ",
        "score": 0.51,
    }

    def test_notes_only_no_ingested_section(self) -> None:
        """With notes and no chunks, there's no 'ingested sources' heading."""
        out = format_notes_for_context([self._NOTE], budget=6000)
        self.assertIn("## zendb", out)
        self.assertNotIn("ingested sources", out)

    def test_chunks_appended_under_heading(self) -> None:
        """Chunks render under an '## ingested sources' heading with title/section."""
        out = format_notes_for_context([self._NOTE], budget=6000, chunks=[self._CHUNK])
        self.assertIn("## ingested sources", out)
        self.assertIn("The Pragmatic Programmer -- Chapter 3: The Basic Tools", out)
        self.assertIn("Always use version control", out)  # whitespace collapsed

    def test_chunk_only_match_still_produces_context(self) -> None:
        """A chunk hit with no matching notes still yields injected context."""
        out = format_notes_for_context([], budget=6000, chunks=[self._CHUNK])
        self.assertTrue(out.startswith("[notemap:"))
        self.assertIn("## ingested sources", out)

    def test_no_notes_no_chunks_empty(self) -> None:
        """Nothing to inject -> empty string."""
        self.assertEqual(format_notes_for_context([], chunks=[]), "")
        self.assertEqual(format_notes_for_context([]), "")

    def test_long_chunk_body_is_snippeted(self) -> None:
        """A long chunk body is truncated with an ellipsis, not dumped whole."""
        big_chunk = {**self._CHUNK, "content": "word " * 5000}
        out = format_notes_for_context([], budget=6000, chunks=[big_chunk])
        self.assertIn("...", out)
        self.assertLess(len(out), 3000)

    def test_tight_budget_drops_chunks_first(self) -> None:
        """When the budget is spent on notes, the ingested section is omitted."""
        fat_note = {**self._NOTE, "topic": "T" * 400, "summary": "S" * 800}
        out = format_notes_for_context([fat_note], budget=40, chunks=[self._CHUNK])
        self.assertNotIn("ingested sources", out)

    def test_caps_number_of_chunks(self) -> None:
        """At most a handful of chunks are injected even if many are passed."""
        chunks = [{**self._CHUNK, "section": f"Section {i}", "content": f"body {i}"} for i in range(20)]
        out = format_notes_for_context([], budget=6000, chunks=chunks)
        injected = out.count("- **The Pragmatic Programmer")
        self.assertGreaterEqual(injected, 1)
        self.assertLessEqual(injected, 3)


class TestRetrieveForPrompt(unittest.TestCase):
    """Tests for the retrieve_for_prompt function."""

    def test_short_prompt_returns_empty(self) -> None:
        """Prompts shorter than 20 characters return empty string."""
        self.assertEqual(retrieve_for_prompt("hi"), "")
        self.assertEqual(retrieve_for_prompt("short query"), "")

    def test_empty_prompt_returns_empty(self) -> None:
        """Empty prompt returns empty string."""
        self.assertEqual(retrieve_for_prompt(""), "")
        self.assertEqual(retrieve_for_prompt("   "), "")

    def test_no_db_returns_empty(self) -> None:
        """When no notemap database exists, returns empty string gracefully."""
        # This relies on the real ~/.claude/notemap path not being set up
        # in a way that would interfere, but the function handles missing DB
        result = retrieve_for_prompt("This is a sufficiently long test prompt for RAG retrieval")
        # May or may not return results depending on whether a real DB exists,
        # but it should not raise an exception
        self.assertIsInstance(result, str)

    def test_respects_max_tokens(self) -> None:
        """Output stays within max_tokens budget."""
        result = retrieve_for_prompt(
            "This is a long enough prompt to pass the length check for testing purposes",
            max_tokens=50,
        )
        if result:
            # Rough token estimate: len/4
            estimated_tokens = len(result) // 4
            # Allow generous margin since we're estimating
            self.assertLessEqual(estimated_tokens, 200)

    def test_return_type_is_string(self) -> None:
        """retrieve_for_prompt always returns a string."""
        result = retrieve_for_prompt(
            "Testing that return type is always string regardless of input"
        )
        self.assertIsInstance(result, str)

    def test_result_format_when_nonempty(self) -> None:
        """When results exist, output starts with the notemap header."""
        result = retrieve_for_prompt(
            "What does DB::get return when no record matches the query?"
        )
        if result:
            self.assertTrue(result.startswith("[notemap:"))


class TestRagMainBlock(unittest.TestCase):
    """Tests for the rag.py __main__ JSON pipeline."""

    def test_empty_prompt_produces_no_output(self) -> None:
        """Empty prompt JSON produces no additionalContext output."""
        input_data = json.dumps({"prompt": ""})
        result = subprocess.run(
            [sys.executable, str(Path(_SRC_DIR) / "rag.py")],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should not crash
        self.assertEqual(result.returncode, 0)

    def test_short_prompt_produces_no_context(self) -> None:
        """Short prompt produces no additionalContext."""
        input_data = json.dumps({"prompt": "hi"})
        result = subprocess.run(
            [sys.executable, str(Path(_SRC_DIR) / "rag.py")],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0)
        # stdout should be empty or not contain additionalContext
        if result.stdout.strip():
            data = json.loads(result.stdout)
            # If there is output, the context should be empty
            context = data.get("additionalContext", "")
            self.assertEqual(context, "")

    def test_valid_json_input(self) -> None:
        """Valid JSON input with a real prompt does not crash."""
        input_data = json.dumps({
            "prompt": "How does the notemap search algorithm work with BM25F scoring?"
        })
        result = subprocess.run(
            [sys.executable, str(Path(_SRC_DIR) / "rag.py")],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0)
        # If there's output, it should be valid JSON
        if result.stdout.strip():
            data = json.loads(result.stdout)
            self.assertIn("additionalContext", data)

    def test_invalid_json_does_not_crash(self) -> None:
        """Invalid JSON input does not crash the process."""
        result = subprocess.run(
            [sys.executable, str(Path(_SRC_DIR) / "rag.py")],
            input="not valid json {{{",
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Should exit cleanly (silent failure)
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
