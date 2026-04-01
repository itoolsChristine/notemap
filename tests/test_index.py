"""Tests for the notemap index module (SQLite-backed).

Covers parse_note_file (legacy), load_or_rebuild_index (SQLite bridge),
and save_index (no-op in SQLite mode).

Run with: python -m unittest tests.test_index
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Make the modules importable
# ---------------------------------------------------------------------------
_SRC_DIR = Path(__file__).resolve().parent.parent / "src" / "notemap-mcp"
sys.path.insert(0, str(_SRC_DIR))

import index  # noqa: E402 -- path manipulation required before import
from db import close_db, get_db  # noqa: E402


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
        import shutil
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
    """Tests for index.rebuild_index loading from SQLite."""

    def setUp(self) -> None:
        close_db()
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_test_"))

    def tearDown(self) -> None:
        close_db()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _insert_note(self, note_id: str, library: str = "test-lib") -> None:
        """Insert a stub note directly into the SQLite DB."""
        conn = get_db(self.tmp_dir)
        conn.execute("""
            INSERT INTO notes (id, library, topic, type, summary, notes_body, cues_raw,
                             source_quality, confidence, lifecycle,
                             created, last_modified, last_reviewed)
            VALUES (?, ?, ?, 'knowledge', 'Summary', 'Notes content', '',
                    'unverified', 'maybe', 'active',
                    '2026-01-01', '2026-01-01', '2026-01-01')
        """, (note_id, library, f"Note {note_id}"))
        conn.commit()

    # 8. Loads all notes from the database
    def test_finds_all_notes(self) -> None:
        self._insert_note("alpha")
        self._insert_note("beta")
        self._insert_note("gamma")

        close_db()
        result = index.rebuild_index(self.tmp_dir)

        self.assertIn("alpha", result)
        self.assertIn("beta", result)
        self.assertIn("gamma", result)
        self.assertEqual(len(result), 3)

    # 9. Archived notes are loaded but have lifecycle='archived'
    def test_loads_archived_notes(self) -> None:
        self._insert_note("active-note")
        conn = get_db(self.tmp_dir)
        conn.execute("""
            INSERT INTO notes (id, library, topic, type, summary, notes_body, cues_raw,
                             source_quality, confidence, lifecycle,
                             created, last_modified, last_reviewed)
            VALUES ('archived-note', 'test-lib', 'Archived Note', 'knowledge', 'S', 'N', '',
                    'unverified', 'maybe', 'archived',
                    '2026-01-01', '2026-01-01', '2026-01-01')
        """)
        conn.commit()

        close_db()
        result = index.rebuild_index(self.tmp_dir)

        self.assertIn("active-note", result)
        self.assertIn("archived-note", result)
        self.assertEqual(result["archived-note"]["lifecycle"], "archived")


class TestSaveIndex(unittest.TestCase):
    """Tests for save_index (no-op in SQLite mode)."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_test_"))

    def tearDown(self) -> None:
        close_db()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 10. save_index is a no-op and does not create _index.json
    def test_save_index_is_noop(self) -> None:
        test_index = {
            "note-one": {
                "id": "note-one",
                "library": "test-lib",
                "topic": "First Note",
            },
        }

        index.save_index(self.tmp_dir, test_index)

        # No _index.json should be created (SQLite handles persistence)
        index_path = self.tmp_dir / "_index.json"
        self.assertFalse(index_path.exists(), "save_index should be a no-op in SQLite mode")

    # 11. Data persists through SQLite, not JSON
    def test_data_round_trips_via_sqlite(self) -> None:
        conn = get_db(self.tmp_dir)
        conn.execute("""
            INSERT INTO notes (id, library, topic, type, summary, notes_body, cues_raw,
                             source_quality, confidence, lifecycle,
                             created, last_modified, last_reviewed)
            VALUES ('rt-note', 'test-lib', 'Round Trip', 'knowledge', 'Summary text', 'Notes text', 'cue1',
                    'verified-from-source', 'strong', 'active',
                    '2026-01-01', '2026-01-01', '2026-01-01')
        """)
        conn.execute("INSERT INTO note_tags VALUES ('rt-note', 'alpha')")
        conn.commit()
        close_db()

        # Reload from SQLite
        result = index.rebuild_index(self.tmp_dir)
        self.assertIn("rt-note", result)
        self.assertEqual(result["rt-note"]["topic"], "Round Trip")
        self.assertEqual(result["rt-note"]["summary"], "Summary text")
        self.assertIn("alpha", result["rt-note"]["tags"])


if __name__ == "__main__":
    unittest.main()
