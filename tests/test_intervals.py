"""Tests for the adaptive review interval logic in update_note.

Covers miss_count escalation, review_count interval extension,
stale-to-active lifecycle transitions, and miss_log appending.

Run with:  python -m unittest tests.test_intervals
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
from notes import create_note, update_note
from utils import today_str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_note_params(
    library: str = "testlib",
    topic: str = "Test topic",
    **overrides,
) -> dict:
    """Return a minimal valid create_note params dict."""
    params = {
        "library":        library,
        "topic":          topic,
        "notes":          "Some notes content.",
        "summary":        "A short summary.",
        "cues":           ["What does it do?"],
        "source_quality": "verified-from-source",
        "confidence":     "strong",
    }
    params.update(overrides)
    return params


class TestIntervals(unittest.TestCase):
    """Test adaptive review interval logic in update_note."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_test_"))
        self.index: dict = load_or_rebuild_index(self.tmp_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # -- Convenience --------------------------------------------------------

    def _create(self, topic: str = "Interval test", **kw) -> str:
        """Create a note and return its ID."""
        params = _make_note_params(topic=topic, **kw)
        result = create_note(self.index, self.tmp_dir, params)
        self.assertNotIn("error", result, result.get("error", ""))
        return result["id"]

    def _entry(self, note_id: str) -> dict:
        """Return the current index entry for *note_id*."""
        return self.index[note_id]

    # -- miss_count=1 resets interval to 30 ---------------------------------

    def test_miss_count_1_sets_interval_to_30(self) -> None:
        note_id = self._create("Miss count one")

        result = update_note(self.index, self.tmp_dir, {
            "id":             note_id,
            "increment_miss": True,
            "miss_reason":    "accuracy-problem",
        })
        self.assertNotIn("error", result)

        entry = self._entry(note_id)
        self.assertEqual(entry["miss_count"], 1)
        self.assertEqual(entry["review_interval_days"], 30)
        self.assertEqual(entry["lifecycle"], "active")

    # -- miss_count>=2 shortens interval to 14 ------------------------------

    def test_miss_count_2_sets_interval_to_14(self) -> None:
        note_id = self._create("Miss count two")

        for _ in range(2):
            update_note(self.index, self.tmp_dir, {
                "id":             note_id,
                "increment_miss": True,
                "miss_reason":    "retrieval-failure",
            })

        entry = self._entry(note_id)
        self.assertEqual(entry["miss_count"], 2)
        self.assertEqual(entry["review_interval_days"], 14)
        self.assertEqual(entry["lifecycle"], "active")

    # -- miss_count>=3 transitions lifecycle to stale -----------------------

    def test_miss_count_3_transitions_to_stale(self) -> None:
        note_id = self._create("Miss count three")

        for _ in range(3):
            update_note(self.index, self.tmp_dir, {
                "id":             note_id,
                "increment_miss": True,
            })

        entry = self._entry(note_id)
        self.assertEqual(entry["miss_count"], 3)
        self.assertEqual(entry["review_interval_days"], 14)
        self.assertEqual(entry["lifecycle"], "stale")

    # -- miss_count=0 AND review_count>=3 extends interval ------------------

    def test_review_extends_interval_30_to_60(self) -> None:
        note_id = self._create("Interval extension 30->60")

        # Reviews 1-2: no change to interval
        for _ in range(2):
            update_note(self.index, self.tmp_dir, {
                "id":            note_id,
                "mark_reviewed": True,
            })
        self.assertEqual(self._entry(note_id)["review_interval_days"], 30)

        # Review 3: triggers extension 30 -> 60
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })

        entry = self._entry(note_id)
        self.assertEqual(entry["review_count"], 3)
        self.assertEqual(entry["review_interval_days"], 60)

    def test_review_extends_interval_60_to_90(self) -> None:
        note_id = self._create("Interval extension 60->90")

        # Get to review_count=3, interval=60
        for _ in range(3):
            update_note(self.index, self.tmp_dir, {
                "id":            note_id,
                "mark_reviewed": True,
            })
        self.assertEqual(self._entry(note_id)["review_interval_days"], 60)

        # Review 4: interval stays at 60 (needs to reach next threshold)
        # The code checks `current_interval < 90` so 60 -> 90 on review 4
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })

        entry = self._entry(note_id)
        self.assertEqual(entry["review_count"], 4)
        self.assertEqual(entry["review_interval_days"], 90)

    def test_review_interval_caps_at_90(self) -> None:
        note_id = self._create("Interval cap at 90")

        # Push through 5 reviews to get to 90
        for _ in range(5):
            update_note(self.index, self.tmp_dir, {
                "id":            note_id,
                "mark_reviewed": True,
            })
        self.assertEqual(self._entry(note_id)["review_interval_days"], 90)

        # One more review: should stay at 90
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })
        self.assertEqual(self._entry(note_id)["review_interval_days"], 90)

    # -- Stale note re-verified resets everything ---------------------------

    def test_stale_reverification_resets_to_active(self) -> None:
        note_id = self._create("Stale reverification")

        # Drive to stale (3 misses)
        for _ in range(3):
            update_note(self.index, self.tmp_dir, {
                "id":             note_id,
                "increment_miss": True,
            })
        entry = self._entry(note_id)
        self.assertEqual(entry["lifecycle"], "stale")
        self.assertEqual(entry["miss_count"], 3)

        # Re-verify: mark_reviewed on a stale note
        result = update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })
        self.assertNotIn("error", result)

        entry = self._entry(note_id)
        self.assertEqual(entry["lifecycle"], "active")
        self.assertEqual(entry["miss_count"], 0)
        self.assertEqual(entry["review_count"], 0)

    def test_stale_reverification_changes_reported(self) -> None:
        """The changes list should mention the lifecycle transition."""
        note_id = self._create("Stale changes report")

        for _ in range(3):
            update_note(self.index, self.tmp_dir, {
                "id":             note_id,
                "increment_miss": True,
            })

        result = update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })

        changes = result.get("changes", [])
        lifecycle_change = [c for c in changes if "stale -> active" in c]
        self.assertTrue(
            lifecycle_change,
            f"Expected lifecycle transition in changes, got: {changes}",
        )

    # -- increment_miss appends to miss_log ---------------------------------

    def test_miss_log_appended_with_reason(self) -> None:
        note_id = self._create("Miss log test")

        update_note(self.index, self.tmp_dir, {
            "id":             note_id,
            "increment_miss": True,
            "miss_reason":    "pseudo-forgetting",
        })

        entry = self._entry(note_id)
        self.assertEqual(len(entry["miss_log"]), 1)
        log_entry = entry["miss_log"][0]
        self.assertEqual(log_entry["date"], today_str())
        self.assertEqual(log_entry["reason"], "pseudo-forgetting")

    def test_miss_log_accumulates(self) -> None:
        note_id = self._create("Miss log accumulation")

        reasons = ["accuracy-problem", "retrieval-failure", "pseudo-forgetting"]
        for reason in reasons:
            update_note(self.index, self.tmp_dir, {
                "id":             note_id,
                "increment_miss": True,
                "miss_reason":    reason,
            })

        entry = self._entry(note_id)
        self.assertEqual(len(entry["miss_log"]), 3)
        logged_reasons = [e["reason"] for e in entry["miss_log"]]
        self.assertEqual(logged_reasons, reasons)

    # -- miss_reason defaults to "unclassified" -----------------------------

    def test_miss_reason_defaults_to_unclassified(self) -> None:
        note_id = self._create("Default miss reason")

        update_note(self.index, self.tmp_dir, {
            "id":             note_id,
            "increment_miss": True,
            # no miss_reason provided
        })

        entry = self._entry(note_id)
        self.assertEqual(entry["miss_log"][0]["reason"], "unclassified")

    # -- Interval not extended when misses exist ----------------------------

    def test_no_interval_extension_with_misses(self) -> None:
        """Even with 3+ reviews, interval should NOT extend if miss_count > 0."""
        note_id = self._create("No extension with misses")

        # One miss first
        update_note(self.index, self.tmp_dir, {
            "id":             note_id,
            "increment_miss": True,
        })

        # Three reviews on top of that miss
        for _ in range(3):
            update_note(self.index, self.tmp_dir, {
                "id":            note_id,
                "mark_reviewed": True,
            })

        entry = self._entry(note_id)
        # miss_count is 1, so interval should be 30 (from miss), not 60
        self.assertEqual(entry["review_interval_days"], 30)

    # -- File on disk reflects changes --------------------------------------

    def test_changes_persisted_to_file(self) -> None:
        """Verify the .md file on disk has the updated frontmatter."""
        import frontmatter

        note_id = self._create("Persistence check")

        # Drive to 3 misses (stale)
        for _ in range(3):
            update_note(self.index, self.tmp_dir, {
                "id":             note_id,
                "increment_miss": True,
            })

        # Re-verify
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })

        # Read the file directly
        entry = self._entry(note_id)
        filepath = Path(entry["path"])
        if not filepath.is_absolute():
            filepath = self.tmp_dir / entry["path"]
        post = frontmatter.load(str(filepath))

        self.assertEqual(post.metadata["lifecycle"], "active")
        self.assertEqual(post.metadata["miss_count"], 0)
        self.assertEqual(post.metadata["review_count"], 0)

    # -- Index on disk matches in-memory after interval changes -------------

    def test_index_on_disk_matches_memory(self) -> None:
        note_id = self._create("Index sync check")

        update_note(self.index, self.tmp_dir, {
            "id":             note_id,
            "increment_miss": True,
            "miss_reason":    "accuracy-problem",
        })

        # Reload index from disk
        disk_index = load_or_rebuild_index(self.tmp_dir)
        disk_entry = disk_index[note_id]
        mem_entry  = self._entry(note_id)

        self.assertEqual(disk_entry["miss_count"], mem_entry["miss_count"])
        self.assertEqual(
            disk_entry["review_interval_days"],
            mem_entry["review_interval_days"],
        )


if __name__ == "__main__":
    unittest.main()
