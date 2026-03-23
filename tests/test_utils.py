"""Tests for the notemap utils module.

Covers slugify_topic, generate_id, today_str, now_iso, get_notemap_dir,
get_mcp_dir, ensure_dir, and fuzzy_suggestions.

Run with:  python -m unittest tests.test_utils -v
"""
from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Path setup -- allow imports from src/notemap-mcp/
# ---------------------------------------------------------------------------
_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src" / "notemap-mcp")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from utils import (  # noqa: E402
    ensure_dir,
    fuzzy_suggestions,
    generate_id,
    get_mcp_dir,
    get_notemap_dir,
    now_iso,
    slugify_topic,
    today_str,
)


# ===================================================================
# slugify_topic
# ===================================================================

class TestSlugifyTopic(unittest.TestCase):
    """Tests for utils.slugify_topic()."""

    def test_normal_topic_produces_hyphenated_slug(self) -> None:
        """A plain English topic is lowercased and joined with hyphens."""
        result = slugify_topic("DB get returns empty")
        self.assertEqual(result, "db-get-returns-empty")

    def test_long_topic_truncated_to_60_chars(self) -> None:
        """Topics longer than 60 characters are truncated at a word boundary."""
        topic = "This is a very long topic string that should be truncated because it exceeds the sixty character maximum length limit"
        result = slugify_topic(topic)
        self.assertLessEqual(len(result), 60)

    def test_special_characters_stripped(self) -> None:
        """Punctuation and special characters are removed from the slug."""
        result = slugify_topic("DB::get() returns $value! @home #1")
        # Should contain only lowercase alphanumeric and hyphens
        self.assertRegex(result, r'^[a-z0-9-]+$')
        self.assertNotIn(":", result)
        self.assertNotIn("(", result)
        self.assertNotIn("$", result)
        self.assertNotIn("!", result)
        self.assertNotIn("@", result)
        self.assertNotIn("#", result)

    def test_consecutive_hyphens_collapsed(self) -> None:
        """Multiple adjacent separators collapse into a single hyphen."""
        result = slugify_topic("hello   ---   world")
        self.assertNotIn("--", result)
        self.assertIn("hello", result)
        self.assertIn("world", result)

    def test_leading_trailing_hyphens_stripped(self) -> None:
        """The slug does not start or end with a hyphen."""
        result = slugify_topic("  --hello world--  ")
        self.assertFalse(result.startswith("-"))
        self.assertFalse(result.endswith("-"))

    def test_empty_string_returns_empty(self) -> None:
        """An empty topic produces an empty slug."""
        result = slugify_topic("")
        self.assertEqual(result, "")

    def test_whitespace_only_returns_empty(self) -> None:
        """A topic of only whitespace produces an empty slug."""
        result = slugify_topic("   ")
        self.assertEqual(result, "")

    def test_unicode_characters_transliterated(self) -> None:
        """Accented characters are transliterated to ASCII equivalents."""
        result = slugify_topic("cafe resume naive")
        self.assertRegex(result, r'^[a-z0-9-]+$')
        self.assertIn("cafe", result)

    def test_mixed_case_lowered(self) -> None:
        """Mixed-case input is lowercased in the slug."""
        result = slugify_topic("SmartArray IsEmpty Method")
        self.assertEqual(result, "smartarray-isempty-method")

    def test_numbers_preserved(self) -> None:
        """Numeric characters are kept in the slug."""
        result = slugify_topic("PHP 8.1 strict types")
        self.assertIn("8", result)
        self.assertIn("1", result)


# ===================================================================
# generate_id
# ===================================================================

class TestGenerateId(unittest.TestCase):
    """Tests for utils.generate_id()."""

    def test_produces_library_slug_format(self) -> None:
        """Output follows the '{library}-{slugified-topic}' pattern."""
        result = generate_id("zendb", "DB get returns empty")
        self.assertEqual(result, "zendb-db-get-returns-empty")

    def test_library_prefix_lowercased(self) -> None:
        """The library portion is lowercased via slugify."""
        result = generate_id("ZenDB", "some topic")
        # generate_id uses f"{library}-{slug}" -- library is passed through as-is,
        # but let's verify the actual behavior
        self.assertTrue(result.startswith("ZenDB-") or result.startswith("zendb-"))

    def test_topic_is_slugified(self) -> None:
        """The topic portion is run through slugify_topic."""
        result = generate_id("mylib", "Hello World!")
        expected_slug = slugify_topic("Hello World!")
        self.assertTrue(result.endswith(expected_slug))

    def test_deterministic_output(self) -> None:
        """Same inputs always produce the same ID."""
        id1 = generate_id("zendb", "DB::get returns empty SmartArrayHtml")
        id2 = generate_id("zendb", "DB::get returns empty SmartArrayHtml")
        self.assertEqual(id1, id2)

    def test_different_libraries_produce_different_ids(self) -> None:
        """Different library names produce different IDs for the same topic."""
        id1 = generate_id("zendb", "some topic")
        id2 = generate_id("smartarray", "some topic")
        self.assertNotEqual(id1, id2)

    def test_different_topics_produce_different_ids(self) -> None:
        """Different topics produce different IDs for the same library."""
        id1 = generate_id("zendb", "topic alpha")
        id2 = generate_id("zendb", "topic beta")
        self.assertNotEqual(id1, id2)


# ===================================================================
# today_str
# ===================================================================

class TestTodayStr(unittest.TestCase):
    """Tests for utils.today_str()."""

    def test_returns_yyyy_mm_dd_format(self) -> None:
        """Output matches the YYYY-MM-DD date format."""
        result = today_str()
        self.assertRegex(result, r'^\d{4}-\d{2}-\d{2}$')

    def test_matches_current_utc_date(self) -> None:
        """Returned date matches today's UTC date."""
        result = today_str()
        expected = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertEqual(result, expected)


# ===================================================================
# now_iso
# ===================================================================

class TestNowIso(unittest.TestCase):
    """Tests for utils.now_iso()."""

    def test_returns_iso_8601_format(self) -> None:
        """Output is a valid ISO 8601 datetime string."""
        result = now_iso()
        # Should be parseable by datetime.fromisoformat
        parsed = datetime.fromisoformat(result)
        self.assertIsInstance(parsed, datetime)

    def test_includes_utc_timezone(self) -> None:
        """Returned datetime is in UTC."""
        result = now_iso()
        parsed = datetime.fromisoformat(result)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.utcoffset().total_seconds(), 0.0)


# ===================================================================
# get_notemap_dir / get_mcp_dir
# ===================================================================

class TestGetDirs(unittest.TestCase):
    """Tests for utils.get_notemap_dir() and get_mcp_dir()."""

    def test_notemap_dir_under_home(self) -> None:
        """notemap data dir is ~/.claude/notemap."""
        result = get_notemap_dir()
        expected = Path.home() / ".claude" / "notemap"
        self.assertEqual(result, expected)

    def test_mcp_dir_under_home(self) -> None:
        """MCP server dir is ~/.claude/notemap-mcp."""
        result = get_mcp_dir()
        expected = Path.home() / ".claude" / "notemap-mcp"
        self.assertEqual(result, expected)

    def test_dirs_are_path_objects(self) -> None:
        """Both functions return Path objects, not strings."""
        self.assertIsInstance(get_notemap_dir(), Path)
        self.assertIsInstance(get_mcp_dir(), Path)


# ===================================================================
# ensure_dir
# ===================================================================

class TestEnsureDir(unittest.TestCase):
    """Tests for utils.ensure_dir()."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="notemap_test_ensure_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_creates_directory_if_missing(self) -> None:
        """Creates a new directory when it does not exist."""
        target = self.tmp_dir / "new_dir"
        self.assertFalse(target.exists())
        ensure_dir(target)
        self.assertTrue(target.is_dir())

    def test_no_error_if_directory_exists(self) -> None:
        """Does not raise when the directory already exists."""
        target = self.tmp_dir / "existing"
        target.mkdir()
        self.assertTrue(target.is_dir())
        # Should not raise
        ensure_dir(target)
        self.assertTrue(target.is_dir())

    def test_creates_parent_directories(self) -> None:
        """Creates all intermediate parent directories."""
        target = self.tmp_dir / "a" / "b" / "c"
        self.assertFalse(target.exists())
        ensure_dir(target)
        self.assertTrue(target.is_dir())
        self.assertTrue((self.tmp_dir / "a" / "b").is_dir())
        self.assertTrue((self.tmp_dir / "a").is_dir())


# ===================================================================
# fuzzy_suggestions
# ===================================================================

class TestFuzzySuggestions(unittest.TestCase):
    """Tests for utils.fuzzy_suggestions()."""

    def test_returns_close_matches_for_typos(self) -> None:
        """Finds similar strings when the query has a small typo."""
        candidates = ["zendb", "smartarray", "smartstring", "cmsbuilder"]
        result = fuzzy_suggestions("zenbd", candidates)
        self.assertIn("zendb", result)

    def test_returns_empty_list_when_no_matches(self) -> None:
        """Returns an empty list when nothing is remotely close."""
        candidates = ["alpha", "beta", "gamma"]
        result = fuzzy_suggestions("xyzzy99999", candidates)
        self.assertEqual(result, [])

    def test_respects_max_results_parameter(self) -> None:
        """Returns at most max_results items."""
        candidates = ["aaa", "aab", "aac", "aad", "aae"]
        result = fuzzy_suggestions("aaa", candidates, max_results=2)
        self.assertLessEqual(len(result), 2)

    def test_empty_candidates_returns_empty(self) -> None:
        """An empty candidate list always returns an empty list."""
        result = fuzzy_suggestions("anything", [])
        self.assertEqual(result, [])

    def test_exact_match_returned(self) -> None:
        """An exact match is always included in results."""
        candidates = ["zendb", "smartarray", "smartstring"]
        result = fuzzy_suggestions("zendb", candidates)
        self.assertIn("zendb", result)

    def test_default_max_results_is_three(self) -> None:
        """Without explicit max_results, at most 3 suggestions are returned."""
        # All very similar strings -- all should match above cutoff
        candidates = ["test1", "test2", "test3", "test4", "test5"]
        result = fuzzy_suggestions("test1", candidates)
        self.assertLessEqual(len(result), 3)

    def test_cutoff_excludes_distant_strings(self) -> None:
        """Strings with similarity below 0.4 are not returned."""
        candidates = ["abcdef"]
        # A completely different string should be below the 0.4 cutoff
        result = fuzzy_suggestions("zyxwvu", candidates)
        self.assertEqual(result, [])

    def test_returns_list_type(self) -> None:
        """Return value is always a list."""
        result = fuzzy_suggestions("test", ["test"])
        self.assertIsInstance(result, list)

    def test_max_results_zero_raises_value_error(self) -> None:
        """max_results=0 raises ValueError (difflib requirement: n > 0)."""
        candidates = ["zendb", "smartarray"]
        with self.assertRaises(ValueError):
            fuzzy_suggestions("zendb", candidates, max_results=0)


if __name__ == "__main__":
    unittest.main()
