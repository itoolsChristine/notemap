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

from datetime import date, timedelta

from db import close_db, get_db, load_note_dict
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
        close_db()
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

    def _backdate(self, note_id: str, days_ago: int) -> None:
        """Set last_reviewed to *days_ago* days in the past (DB + index).

        This satisfies the time-gate requirement for tier promotion tests.
        """
        past = (date.today() - timedelta(days=days_ago)).isoformat()
        conn = get_db(self.tmp_dir)
        conn.execute("UPDATE notes SET last_reviewed = ? WHERE id = ?", (past, note_id))
        conn.commit()
        if note_id in self.index:
            self.index[note_id]["last_reviewed"] = past

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
        """Tier promotion from 2 (30d) to 3 (60d) after enough reviews."""
        note_id = self._create("Interval extension 30->60")

        # Review 1: no promotion yet (review_count=1, need >=2)
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })
        self.assertEqual(self._entry(note_id).get("review_tier", 2), 2)

        # Backdate so time gate (50% of 30d = 15d) is satisfied
        self._backdate(note_id, 16)

        # Review 2: triggers promotion from tier 2 -> 3
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })

        entry = self._entry(note_id)
        self.assertEqual(entry["review_count"], 2)
        self.assertEqual(entry.get("review_tier"), 3)
        # With fuzz and confidence=strong (1.3), type=knowledge (1.0):
        # base=60, range ~ 60*1.3*0.95 to 60*1.3*1.05 = 74..81
        self.assertGreaterEqual(entry["review_interval_days"], 70)
        self.assertLessEqual(entry["review_interval_days"], 85)

    def test_review_extends_interval_to_tier_4(self) -> None:
        """Tier promotion from 3 (60d) to 4 (120d)."""
        note_id = self._create("Interval extension to tier 4")

        # Review 1
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })
        # Backdate past tier 2 gate (50% of 30d = 15d)
        self._backdate(note_id, 16)

        # Review 2: promote tier 2 -> 3
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })
        self.assertEqual(self._entry(note_id).get("review_tier"), 3)

        # Backdate past tier 3 gate (50% of 60d = 30d)
        self._backdate(note_id, 31)

        # Review 3: promote tier 3 -> 4
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })

        entry = self._entry(note_id)
        self.assertEqual(entry["review_count"], 3)
        self.assertEqual(entry.get("review_tier"), 4)
        # base=120, strong conf=1.3, fuzz 0.95-1.05: range ~148..163
        self.assertGreaterEqual(entry["review_interval_days"], 140)
        self.assertLessEqual(entry["review_interval_days"], 170)

    def test_review_tier_caps_at_5(self) -> None:
        """Tier 5 (365d) is the maximum - further reviews stay at tier 5."""
        note_id = self._create("Tier cap at 5")
        tier_gates = [16, 31, 61, 121]  # 50% of tier 2/3/4/5 intervals

        # Push through tiers: 2->3->4->5
        for i in range(4):
            update_note(self.index, self.tmp_dir, {
                "id":            note_id,
                "mark_reviewed": True,
            })
            if i < len(tier_gates):
                self._backdate(note_id, tier_gates[i])

        # Final promotion review
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })
        self.assertEqual(self._entry(note_id).get("review_tier"), 5)

        # One more review: should stay at tier 5
        self._backdate(note_id, 183)
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })
        self.assertEqual(self._entry(note_id).get("review_tier"), 5)
        # base=365, strong conf=1.3, fuzz 0.95-1.05: range ~450..498
        self.assertGreaterEqual(self._entry(note_id)["review_interval_days"], 440)
        self.assertLessEqual(self._entry(note_id)["review_interval_days"], 510)

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

    def test_no_tier_promotion_with_misses(self) -> None:
        """Even with 3+ reviews, tier should NOT promote if miss_count > 0."""
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
        # miss_count is 1, so tier should stay at 2 (no promotion)
        self.assertEqual(entry.get("review_tier", 2), 2)
        # Interval should remain around tier 2 base with miss penalty
        # base=30, conf=1.3, miss_mod=0.8, fuzz 0.95-1.05: range ~29-33
        self.assertGreaterEqual(entry["review_interval_days"], 28)
        self.assertLessEqual(entry["review_interval_days"], 35)

    # -- File on disk reflects changes --------------------------------------

    def test_changes_persisted_to_db(self) -> None:
        """Verify the SQLite database has the updated fields."""
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

        # Read from DB directly
        conn = get_db(self.tmp_dir)
        row = conn.execute(
            "SELECT lifecycle, miss_count, review_count FROM notes WHERE id = ?",
            (note_id,),
        ).fetchone()

        self.assertEqual(row["lifecycle"], "active")
        self.assertEqual(row["miss_count"], 0)
        self.assertEqual(row["review_count"], 0)

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


    # -- Tier 5 promotion ------------------------------------------------

    def test_review_tier_promotes_to_5(self) -> None:
        """Verify full tier progression 2->3->4->5 with time gates."""
        note_id = self._create("Full tier progression")
        # Tier intervals: {2: 30, 3: 60, 4: 120, 5: 365}
        # Time gates (50%): 15, 30, 60, 183

        # Review 1 (no promotion, just sets review_count=1)
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })

        # Backdate + review to promote 2->3
        self._backdate(note_id, 16)
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })
        self.assertEqual(self._entry(note_id).get("review_tier"), 3)

        # Backdate + review to promote 3->4
        self._backdate(note_id, 31)
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })
        self.assertEqual(self._entry(note_id).get("review_tier"), 4)

        # Backdate + review to promote 4->5
        self._backdate(note_id, 61)
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })

        entry = self._entry(note_id)
        self.assertEqual(entry.get("review_tier"), 5)
        # base=365, strong conf=1.3: ~450-498
        self.assertGreaterEqual(entry["review_interval_days"], 440)

    # -- Miss demotes tier -----------------------------------------------

    def test_miss_demotes_tier(self) -> None:
        """Verify tier demotion on miss_count >= 2."""
        note_id = self._create("Tier demotion test")

        # Promote to tier 3 first (review 1, backdate, review 2)
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })
        self._backdate(note_id, 16)
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })
        self.assertEqual(self._entry(note_id).get("review_tier"), 3)

        # First miss: interval goes to 30, tier unchanged
        update_note(self.index, self.tmp_dir, {
            "id":             note_id,
            "increment_miss": True,
        })
        self.assertEqual(self._entry(note_id).get("review_tier"), 3)
        self.assertEqual(self._entry(note_id)["review_interval_days"], 30)

        # Second miss: tier demotes from 3 to 2
        update_note(self.index, self.tmp_dir, {
            "id":             note_id,
            "increment_miss": True,
        })
        entry = self._entry(note_id)
        self.assertEqual(entry.get("review_tier"), 2)
        self.assertEqual(entry["review_interval_days"], 30)

    # -- Fuzz factor varies interval -------------------------------------

    def test_fuzz_factor_varies_interval(self) -> None:
        """Verify interval isn't always exactly the base (fuzz adds variance)."""
        intervals = []
        for i in range(10):
            idx = load_or_rebuild_index(self.tmp_dir)
            self.index = idx
            nid = self._create(f"Fuzz test {i}")
            update_note(self.index, self.tmp_dir, {
                "id":            nid,
                "mark_reviewed": True,
            })
            intervals.append(self._entry(nid)["review_interval_days"])

        # With fuzz, not all 10 should be identical
        unique = set(intervals)
        # It's theoretically possible but astronomically unlikely for all to match
        self.assertGreater(len(unique), 1, f"Expected variance in intervals, got: {intervals}")

    # -- Confidence modifier affects interval ----------------------------

    def test_confidence_modifier_affects_interval(self) -> None:
        """Strong confidence should produce longer intervals than weak."""
        nid_strong = self._create("Conf strong test", confidence="strong")
        nid_weak = self._create("Conf weak test", confidence="weak")

        # Both at tier 2, first review
        update_note(self.index, self.tmp_dir, {
            "id":            nid_strong,
            "mark_reviewed": True,
        })
        update_note(self.index, self.tmp_dir, {
            "id":            nid_weak,
            "mark_reviewed": True,
        })

        strong_interval = self._entry(nid_strong)["review_interval_days"]
        weak_interval = self._entry(nid_weak)["review_interval_days"]

        # strong (1.3x) should be notably higher than weak (0.7x)
        self.assertGreater(strong_interval, weak_interval)

    # -- Type modifier: anti-pattern shorter interval --------------------

    def test_type_modifier_anti_pattern_shorter(self) -> None:
        """Anti-pattern notes should get shorter intervals than knowledge notes."""
        nid_knowledge = self._create("Type knowledge test", type="knowledge")
        nid_anti = self._create(
            "Type anti-pattern test",
            type="anti-pattern",
            primitives_to_avoid=["bad_func"],
            preferred_alternatives=["good_func"],
        )

        update_note(self.index, self.tmp_dir, {
            "id":            nid_knowledge,
            "mark_reviewed": True,
        })
        update_note(self.index, self.tmp_dir, {
            "id":            nid_anti,
            "mark_reviewed": True,
        })

        knowledge_interval = self._entry(nid_knowledge)["review_interval_days"]
        anti_interval = self._entry(nid_anti)["review_interval_days"]

        # anti-pattern (0.8x) should be shorter than knowledge (1.0x)
        self.assertLess(anti_interval, knowledge_interval)

    # -- Leech detection in audit ----------------------------------------

    def test_leech_detection_in_audit(self) -> None:
        """High miss ratio should be flagged as leech in audit."""
        from audit import audit_notes

        note_id = self._create("Leech detection test")

        # One review
        update_note(self.index, self.tmp_dir, {
            "id":            note_id,
            "mark_reviewed": True,
        })

        # Two misses -> miss_count=2, review_count=1 -> ratio=2.0 > 0.5
        for _ in range(2):
            update_note(self.index, self.tmp_dir, {
                "id":             note_id,
                "increment_miss": True,
            })

        result = audit_notes(self.index, self.tmp_dir, {"check": "leech"})
        leech_items = result.get("leech", [])
        leech_ids = [item["id"] for item in leech_items]
        self.assertIn(note_id, leech_ids)
        leech_entry = [item for item in leech_items if item["id"] == note_id][0]
        self.assertGreater(leech_entry["miss_ratio"], 0.5)

    # -- Confidence decay in audit ---------------------------------------

    def test_confidence_decay_in_audit(self) -> None:
        """Notes overdue for review should have confidence decay flagged."""
        from audit import audit_notes, _check_confidence_decay
        from datetime import date, timedelta

        # Test the helper directly
        entry = {
            "confidence": "strong",
            "review_interval_days": 30,
            "last_reviewed": (date.today() - timedelta(days=61)).isoformat(),
        }
        result = _check_confidence_decay(entry, date.today())
        self.assertEqual(result, "maybe")

        # Test "maybe" -> "weak" decay
        entry2 = {
            "confidence": "maybe",
            "review_interval_days": 30,
            "last_reviewed": (date.today() - timedelta(days=91)).isoformat(),
        }
        result2 = _check_confidence_decay(entry2, date.today())
        self.assertEqual(result2, "weak")

        # No decay when within interval
        entry3 = {
            "confidence": "strong",
            "review_interval_days": 30,
            "last_reviewed": (date.today() - timedelta(days=30)).isoformat(),
        }
        result3 = _check_confidence_decay(entry3, date.today())
        self.assertIsNone(result3)

    # -- Review queue tier scoring ---------------------------------------

    def test_review_queue_tier_scoring(self) -> None:
        """Low-tier notes should score higher in the review queue."""
        from audit import review_queue

        nid = self._create("Queue tier test")
        # Set to tier 1 manually via 3 misses
        for _ in range(3):
            update_note(self.index, self.tmp_dir, {
                "id":             nid,
                "increment_miss": True,
            })

        entry = self._entry(nid)
        self.assertEqual(entry.get("review_tier"), 1)

        result = review_queue(self.index, {})
        queue = result.get("queue", [])
        queue_entry = [item for item in queue if item["id"] == nid]
        self.assertTrue(queue_entry, "Expected note in review queue")
        reasons = queue_entry[0].get("reasons", [])
        tier_reasons = [r for r in reasons if "tier 1" in r]
        self.assertTrue(tier_reasons, f"Expected tier 1 scoring in reasons, got: {reasons}")


if __name__ == "__main__":
    unittest.main()
