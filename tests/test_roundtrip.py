"""Tests for the full CRUD lifecycle: create -> read -> search -> update -> delete.

Verifies notes flow correctly through every operation, index stays
consistent, and error paths behave properly.

Run with:  python -m unittest tests.test_roundtrip
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup -- allow imports from src/notemap-mcp/
# ---------------------------------------------------------------------------
_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src" / "notemap-mcp")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from index import load_or_rebuild_index, save_index
from notes import create_note, delete_note, read_note, update_note
from search import search_notes
from utils import today_str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_params(
    library: str = "testlib",
    topic: str = "CRUD lifecycle note",
    **overrides,
) -> dict:
    """Return a minimal valid create_note params dict."""
    params = {
        "library":            library,
        "topic":              topic,
        "notes":              "Detailed notes body.",
        "summary":            "Quick summary for the index.",
        "cues":               ["When does this apply?", "What is the gotcha?"],
        "tags":               ["testing"],
        "source_quality":     "verified-from-source",
        "confidence":         "strong",
        "related_functions":  ["some_function"],
    }
    params.update(overrides)
    return params


class TestRoundtrip(unittest.TestCase):
    """Full CRUD lifecycle tests."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_rt_"))
        self.index: dict = load_or_rebuild_index(self.tmp_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # -- 1. Create note and verify index ------------------------------------

    def test_create_appears_in_index(self) -> None:
        params = _make_params()
        result = create_note(self.index, self.tmp_dir, params)

        self.assertNotIn("error", result)
        note_id = result["id"]
        self.assertIn(note_id, self.index)

        entry = self.index[note_id]
        self.assertEqual(entry["library"], "testlib")
        self.assertEqual(entry["topic"], "CRUD lifecycle note")
        self.assertEqual(entry["confidence"], "strong")
        self.assertEqual(entry["lifecycle"], "active")

    # -- 2. Read note back, verify all fields match -------------------------

    def test_read_returns_matching_fields(self) -> None:
        params = _make_params(topic="Read verification")
        result = create_note(self.index, self.tmp_dir, params)
        note_id = result["id"]

        read_result = read_note(self.index, self.tmp_dir, {"id": note_id})
        self.assertNotIn("error", read_result)
        self.assertEqual(read_result["id"], note_id)
        self.assertEqual(read_result["section"], "all")

        fm = read_result["frontmatter"]
        self.assertEqual(fm["library"], "testlib")
        self.assertEqual(fm["topic"], "Read verification")
        self.assertEqual(fm["source_quality"], "verified-from-source")
        self.assertEqual(fm["confidence"], "strong")
        self.assertEqual(fm["miss_count"], 0)
        self.assertEqual(fm["review_count"], 0)

        body = read_result["body"]
        self.assertIn("Detailed notes body.", body)
        self.assertIn("Quick summary for the index.", body)
        self.assertIn("When does this apply?", body)

    # -- 3. Search by function_name -----------------------------------------

    def test_search_by_function_name(self) -> None:
        params = _make_params(
            topic="Function search target",
            related_functions=["DB::get"],
        )
        create_note(self.index, self.tmp_dir, params)

        results = search_notes(self.index, {"function_name": "DB::get"})
        self.assertGreaterEqual(results["count"], 1)
        ids = [r["id"] for r in results["results"]]
        expected_id = self.index[list(self.index.keys())[0]]["id"]
        self.assertIn(expected_id, ids)

    # -- 4. Search by query -------------------------------------------------

    def test_search_by_query(self) -> None:
        params = _make_params(
            topic="Unique flamingo topic",
            summary="Flamingos stand on one leg.",
        )
        create_note(self.index, self.tmp_dir, params)

        results = search_notes(self.index, {"query": "flamingo"})
        self.assertGreaterEqual(results["count"], 1)
        topics = [r["topic"] for r in results["results"]]
        self.assertTrue(
            any("flamingo" in t.lower() for t in topics),
            f"Expected 'flamingo' in topics, got: {topics}",
        )

    # -- 5. Update note (add tag, change confidence) ------------------------

    def test_update_persists_changes(self) -> None:
        params = _make_params(topic="Update target")
        result = create_note(self.index, self.tmp_dir, params)
        note_id = result["id"]

        update_result = update_note(self.index, self.tmp_dir, {
            "id":         note_id,
            "confidence": "maybe",
            "tags":       {"add": ["extra-tag"]},
        })
        self.assertNotIn("error", update_result)
        self.assertGreater(len(update_result.get("changes", [])), 0)

        # Verify via read
        read_result = read_note(self.index, self.tmp_dir, {"id": note_id})
        fm = read_result["frontmatter"]
        self.assertEqual(fm["confidence"], "maybe")
        self.assertIn("extra-tag", fm["tags"])
        # Original tag should still be there
        self.assertIn("testing", fm["tags"])

    # -- 6. Soft-delete: gone from index, moved to _archive/ ----------------

    def test_soft_delete_archives(self) -> None:
        params = _make_params(topic="Soft delete target")
        result = create_note(self.index, self.tmp_dir, params)
        note_id = result["id"]

        # Capture original file path before deletion removes the index entry
        original_entry = self.index[note_id]
        original_path  = self.tmp_dir / original_entry["path"]
        self.assertTrue(original_path.exists(), "Note file should exist before delete")

        del_result = delete_note(self.index, self.tmp_dir, {
            "id":     note_id,
            "reason": "Testing soft delete",
        })
        self.assertNotIn("error", del_result)
        self.assertEqual(del_result["action"], "archived")

        # Gone from index
        self.assertNotIn(note_id, self.index)

        # Original file removed
        self.assertFalse(original_path.exists(), "Original file should be gone")

        # Archived file exists
        archive_path = self.tmp_dir / "_archive" / f"{note_id}.md"
        self.assertTrue(archive_path.exists(), "Archived file should exist")

    # -- 7. Hard-delete: file gone entirely ---------------------------------

    def test_hard_delete_removes_file(self) -> None:
        params = _make_params(topic="Hard delete target")
        result = create_note(self.index, self.tmp_dir, params)
        note_id = result["id"]

        original_entry = self.index[note_id]
        original_path  = self.tmp_dir / original_entry["path"]

        del_result = delete_note(self.index, self.tmp_dir, {
            "id":          note_id,
            "hard_delete": True,
        })
        self.assertNotIn("error", del_result)
        self.assertEqual(del_result["action"], "hard_delete")

        # Gone from index
        self.assertNotIn(note_id, self.index)

        # File removed from disk
        self.assertFalse(original_path.exists(), "File should be permanently gone")

        # No archive copy
        archive_path = self.tmp_dir / "_archive" / f"{note_id}.md"
        self.assertFalse(archive_path.exists(), "Hard-deleted file should not be archived")

    # -- 8. Duplicate topic returns error -----------------------------------

    def test_duplicate_topic_returns_error(self) -> None:
        params = _make_params(topic="Duplicate check")
        result1 = create_note(self.index, self.tmp_dir, params)
        self.assertNotIn("error", result1)

        result2 = create_note(self.index, self.tmp_dir, params)
        self.assertIn("error", result2)
        self.assertIn("already exists", result2["error"])

    # -- 9. Read non-existent ID returns error with suggestions -------------

    def test_read_nonexistent_returns_error(self) -> None:
        # Create a real note so fuzzy matching has candidates
        params = _make_params(topic="Similar name note")
        create_note(self.index, self.tmp_dir, params)

        result = read_note(self.index, self.tmp_dir, {
            "id": "testlib-similar-name-noet",  # typo on purpose
        })
        self.assertIn("error", result)
        self.assertIn("not found", result["error"])

    def test_read_completely_unknown_returns_error(self) -> None:
        result = read_note(self.index, self.tmp_dir, {
            "id": "nonexistent-garbage-id",
        })
        self.assertIn("error", result)
        self.assertIn("not found", result["error"])

    # -- 10. Index on disk matches in-memory after operations ---------------

    def test_index_disk_matches_memory(self) -> None:
        # Create two notes
        params1 = _make_params(topic="Index sync note one")
        params2 = _make_params(topic="Index sync note two")
        r1 = create_note(self.index, self.tmp_dir, params1)
        r2 = create_note(self.index, self.tmp_dir, params2)

        # Update one
        update_note(self.index, self.tmp_dir, {
            "id":            r1["id"],
            "mark_reviewed": True,
        })

        # Delete the other
        delete_note(self.index, self.tmp_dir, {
            "id":          r2["id"],
            "hard_delete": True,
        })

        # Read the disk index
        index_path = self.tmp_dir / "_index.json"
        self.assertTrue(index_path.exists(), "_index.json should be on disk")

        raw = json.loads(index_path.read_text(encoding="utf-8"))
        disk_notes = raw.get("notes", {})

        # Same set of IDs
        self.assertEqual(set(disk_notes.keys()), set(self.index.keys()))

        # Spot-check a few fields on the surviving note
        surviving_id = r1["id"]
        self.assertIn(surviving_id, disk_notes)
        self.assertEqual(
            disk_notes[surviving_id]["review_count"],
            self.index[surviving_id]["review_count"],
        )
        self.assertEqual(
            disk_notes[surviving_id]["lifecycle"],
            self.index[surviving_id]["lifecycle"],
        )

    # -- Bonus: read specific sections --------------------------------------

    def test_read_meta_section(self) -> None:
        params = _make_params(topic="Meta section test")
        result = create_note(self.index, self.tmp_dir, params)
        note_id = result["id"]

        read_result = read_note(self.index, self.tmp_dir, {
            "id":      note_id,
            "section": "meta",
        })
        self.assertNotIn("error", read_result)
        self.assertEqual(read_result["section"], "meta")
        content = read_result["content"]
        self.assertEqual(content["library"], "testlib")

    def test_read_notes_section(self) -> None:
        params = _make_params(topic="Notes section test")
        result = create_note(self.index, self.tmp_dir, params)
        note_id = result["id"]

        read_result = read_note(self.index, self.tmp_dir, {
            "id":      note_id,
            "section": "notes",
        })
        self.assertNotIn("error", read_result)
        self.assertEqual(read_result["section"], "notes")
        self.assertIn("Detailed notes body.", read_result["content"])

    def test_read_summary_section(self) -> None:
        params = _make_params(topic="Summary section test")
        result = create_note(self.index, self.tmp_dir, params)
        note_id = result["id"]

        read_result = read_note(self.index, self.tmp_dir, {
            "id":      note_id,
            "section": "summary",
        })
        self.assertNotIn("error", read_result)
        self.assertEqual(read_result["section"], "summary")
        self.assertIn("Quick summary for the index.", read_result["content"])

    # -- Bonus: search with no results returns empty list -------------------

    def test_search_no_results(self) -> None:
        results = search_notes(self.index, {"query": "xyzzy-nonexistent"})
        self.assertEqual(results["count"], 0)
        self.assertEqual(results["results"], [])


if __name__ == "__main__":
    unittest.main()
