"""Tests for the notemap index rebuild logic.

Covers parse_note_file, rebuild_index, and save_index round-tripping.
Run with: python -m unittest tests.test_index
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Make the index module importable
# ---------------------------------------------------------------------------
_SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "notemap-mcp"
sys.path.insert(0, str(_SRC_DIR))

import index  # noqa: E402 -- path manipulation required before import


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_SAMPLE_NOTE  = _FIXTURES_DIR / "sample-note.md"


class TestParseNoteFile(unittest.TestCase):
    """Tests for index.parse_note_file against the sample fixture."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_test_"))
        # Copy the fixture into the temp dir so relative-path logic works
        shutil.copy2(_SAMPLE_NOTE, self.tmp_dir / "sample-note.md")
        self.note_path = self.tmp_dir / "sample-note.md"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 1. Extracts correct ID from frontmatter
    def test_extracts_id(self) -> None:
        entry = index.parse_note_file(self.note_path, self.tmp_dir)
        self.assertEqual(entry["id"], "test-lib-sample-function")

    # 2. Extracts correct library, type, topic
    def test_extracts_library_type_topic(self) -> None:
        entry = index.parse_note_file(self.note_path, self.tmp_dir)
        self.assertEqual(entry["library"], "test-lib")
        self.assertEqual(entry["type"], "knowledge")
        self.assertEqual(entry["topic"], "Sample Function Behavior")

    # 3. Extracts cues as a list (2 items)
    def test_extracts_cues_as_list(self) -> None:
        entry = index.parse_note_file(self.note_path, self.tmp_dir)
        self.assertIsInstance(entry["cues"], list)
        self.assertEqual(len(entry["cues"]), 2)
        self.assertEqual(entry["cues"][0], "What does sample_func() return?")
        self.assertEqual(entry["cues"][1], "Is sample_func() safe with null input?")

    # 4. Extracts summary text
    def test_extracts_summary(self) -> None:
        entry = index.parse_note_file(self.note_path, self.tmp_dir)
        self.assertEqual(
            entry["summary"],
            "sample_func() returns null with no args. Always pass at least one argument.",
        )

    # 5. Stores relative path (not absolute)
    def test_stores_relative_path(self) -> None:
        entry = index.parse_note_file(self.note_path, self.tmp_dir)
        self.assertEqual(entry["path"], "sample-note.md")
        # Must not contain drive letter or absolute prefix
        self.assertFalse(entry["path"].startswith("/"))
        self.assertNotIn(":\\", entry["path"])

    # 6. Extracts related_functions as list
    def test_extracts_related_functions(self) -> None:
        entry = index.parse_note_file(self.note_path, self.tmp_dir)
        self.assertIsInstance(entry["related_functions"], list)
        self.assertEqual(entry["related_functions"], ["sample_func", "other_func"])

    # 7. Handles missing sections gracefully
    def test_handles_missing_sections(self) -> None:
        minimal_content = (
            "---\n"
            'id: "minimal-note"\n'
            'library: "test-lib"\n'
            'topic: "Minimal Note"\n'
            "---\n"
            "\n"
            "## Notes\n"
            "Just some notes, no Cues or Summary section.\n"
        )
        minimal_path = self.tmp_dir / "minimal-note.md"
        minimal_path.write_text(minimal_content, encoding="utf-8")

        entry = index.parse_note_file(minimal_path, self.tmp_dir)
        self.assertEqual(entry["id"], "minimal-note")
        self.assertEqual(entry["cues"], [])
        self.assertEqual(entry["summary"], "")


class TestRebuildIndex(unittest.TestCase):
    """Tests for index.rebuild_index scanning a temp directory."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_note(self, subpath: str, note_id: str) -> Path:
        """Write a minimal valid note file at the given subpath."""
        dest = self.tmp_dir / subpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "---\n"
            f'id: "{note_id}"\n'
            f'library: "test-lib"\n'
            f'topic: "Note {note_id}"\n'
            "---\n"
            "\n"
            "## Notes\n"
            "Some content.\n"
        )
        dest.write_text(content, encoding="utf-8")
        return dest

    # 8. Finds all .md files in the temp directory
    def test_finds_all_md_files(self) -> None:
        self._write_note("alpha.md", "alpha")
        self._write_note("beta.md", "beta")
        self._write_note("subdir/gamma.md", "gamma")

        result = index.rebuild_index(self.tmp_dir)

        self.assertIn("alpha", result)
        self.assertIn("beta", result)
        self.assertIn("gamma", result)
        self.assertEqual(len(result), 3)

    # 9. Skips files in _archive/ subdirectory
    def test_skips_archive_directory(self) -> None:
        self._write_note("active.md", "active")
        self._write_note("_archive/old.md", "archived")

        result = index.rebuild_index(self.tmp_dir)

        self.assertIn("active", result)
        self.assertNotIn("archived", result)
        self.assertEqual(len(result), 1)


class TestSaveAndReloadIndex(unittest.TestCase):
    """Tests for round-tripping through save_index + JSON reload."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 10. save_index + reload produces same entries
    def test_save_and_reload_round_trip(self) -> None:
        original_index = {
            "note-one": {
                "id": "note-one",
                "library": "test-lib",
                "topic": "First Note",
                "type": "knowledge",
                "tags": ["alpha"],
                "cues": ["What is note one?"],
                "summary": "Note one summary.",
                "related_functions": ["func_a"],
                "related_notes": [],
                "path": "note-one.md",
            },
            "note-two": {
                "id": "note-two",
                "library": "test-lib",
                "topic": "Second Note",
                "type": "anti-pattern",
                "tags": ["beta", "gamma"],
                "cues": [],
                "summary": "Note two summary.",
                "related_functions": [],
                "related_notes": ["note-one"],
                "path": "note-two.md",
            },
        }

        index.save_index(self.tmp_dir, original_index)

        # Reload from the written file
        index_path = self.tmp_dir / "_index.json"
        self.assertTrue(index_path.exists(), "_index.json must exist after save")

        raw = json.loads(index_path.read_text(encoding="utf-8"))
        reloaded = raw["notes"]

        self.assertEqual(set(reloaded.keys()), set(original_index.keys()))
        for note_id, original_entry in original_index.items():
            for field, value in original_entry.items():
                self.assertEqual(
                    reloaded[note_id][field],
                    value,
                    f"Mismatch on {note_id}.{field}",
                )


if __name__ == "__main__":
    unittest.main()
