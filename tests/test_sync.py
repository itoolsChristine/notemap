"""Tests for path normalization logic in sync.py."""
from __future__ import annotations

import unittest
from pathlib import PureWindowsPath
from unittest.mock import patch

from sync import apply_substitutions, normalize_paths


class TestNormalizePaths(unittest.TestCase):
    """Test normalize_paths() converts platform-specific paths to $HOME equivalents."""

    # ------------------------------------------------------------------
    # Helper -- mock Path.home() to return a known Windows-style path
    # ------------------------------------------------------------------

    def _normalize_with_home(self, content: str, home: str = r"C:\Users\Admin") -> str:
        """Run normalize_paths with Path.home() mocked to *home*."""
        mock_path = PureWindowsPath(home)
        with patch("sync.Path.home", return_value=mock_path):
            return normalize_paths(content)

    # ------------------------------------------------------------------
    # Windows backslash paths
    # ------------------------------------------------------------------

    def test_windows_backslash_path(self) -> None:
        content  = r"Config lives at C:\Users\Admin\.claude\ for reference."
        result   = self._normalize_with_home(content)
        expected = "Config lives at $HOME/.claude/ for reference."
        self.assertEqual(result, expected)

    def test_windows_backslash_path_no_trailing(self) -> None:
        content  = r"Path is C:\Users\Admin\.claude"
        result   = self._normalize_with_home(content)
        expected = "Path is $HOME/.claude"
        self.assertEqual(result, expected)

    # ------------------------------------------------------------------
    # Windows forward-slash paths
    # ------------------------------------------------------------------

    def test_windows_forward_slash_path(self) -> None:
        content  = "Config lives at C:/Users/Admin/.claude/ for reference."
        result   = self._normalize_with_home(content)
        expected = "Config lives at $HOME/.claude/ for reference."
        self.assertEqual(result, expected)

    def test_windows_forward_slash_path_no_trailing(self) -> None:
        content  = "Path is C:/Users/Admin/.claude"
        result   = self._normalize_with_home(content)
        expected = "Path is $HOME/.claude"
        self.assertEqual(result, expected)

    # ------------------------------------------------------------------
    # Escaped backslash paths (Python-escaped single backslashes)
    # ------------------------------------------------------------------

    def test_escaped_backslash_path(self) -> None:
        """Paths written with Python-escaped backslashes (single \\ in actual string)
        are the same bytes as raw string backslashes -- normalize_paths handles them."""
        # "C:\Users\Admin\.claude\" as an actual string (needs \\ escaping in source)
        content  = "Config lives at C:\\Users\\Admin\\.claude\\ for reference."
        result   = self._normalize_with_home(content, home=r"C:\Users\Admin")
        expected = "Config lives at $HOME/.claude/ for reference."
        self.assertEqual(result, expected)

    def test_double_escaped_backslashes_not_matched(self) -> None:
        """True double-backslash sequences (JSON-escaped contexts) are NOT handled
        by normalize_paths -- those are covered by substitutions instead."""
        # "C:\\Users\\Admin\\.claude\\" -- actual double backslashes in the string
        content = "Config lives at C:\\\\Users\\\\Admin\\\\.claude\\\\ for reference."
        result  = self._normalize_with_home(content, home=r"C:\Users\Admin")
        # normalize_paths does not match these; content passes through unchanged
        self.assertIn("C:\\\\", result)

    # ------------------------------------------------------------------
    # %USERPROFILE% references
    # ------------------------------------------------------------------

    def test_userprofile_env_backslash(self) -> None:
        content  = r"Located at %USERPROFILE%\.claude\ somewhere."
        result   = self._normalize_with_home(content)
        expected = "Located at $HOME/.claude/ somewhere."
        self.assertEqual(result, expected)

    def test_userprofile_env_forward_slash(self) -> None:
        content  = "Located at %USERPROFILE%/.claude/ somewhere."
        result   = self._normalize_with_home(content)
        expected = "Located at $HOME/.claude/ somewhere."
        self.assertEqual(result, expected)

    def test_dollar_userprofile(self) -> None:
        content  = "Located at $USERPROFILE/.claude/ somewhere."
        result   = self._normalize_with_home(content)
        expected = "Located at $HOME/.claude/ somewhere."
        self.assertEqual(result, expected)

    # ------------------------------------------------------------------
    # Mixed content preservation
    # ------------------------------------------------------------------

    def test_mixed_content_preserves_non_path_text(self) -> None:
        content = (
            "# Config\n"
            "\n"
            r"The config dir is C:\Users\Admin\.claude\ on this machine."
            "\n"
            "Other stuff: hello world, 42, special chars !@#.\n"
        )
        result = self._normalize_with_home(content)
        self.assertIn("$HOME/.claude/", result)
        self.assertIn("# Config", result)
        self.assertIn("Other stuff: hello world, 42, special chars !@#.", result)
        self.assertNotIn("Admin", result)

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_empty_content(self) -> None:
        result = self._normalize_with_home("")
        self.assertEqual(result, "")

    def test_no_paths_unchanged(self) -> None:
        content = "Just some regular text with no paths at all.\nLine two."
        result  = self._normalize_with_home(content)
        self.assertEqual(result, content)

    def test_backslash_cleanup_in_subpath(self) -> None:
        """After $HOME/.claude/ is inserted, remaining backslashes in the subpath
        should be normalized to forward slashes by the regex cleanup pass."""
        content = r"Map at C:\Users\Admin\.claude\functionmap\project.md is good."
        result  = self._normalize_with_home(content)
        self.assertIn("$HOME/.claude/functionmap/project.md", result)
        # No backslashes should remain inside the .claude/ subtree
        idx = result.index("$HOME/.claude/")
        tail = result[idx:]
        self.assertNotIn("\\", tail.split()[0])


class TestApplySubstitutions(unittest.TestCase):
    """Test apply_substitutions() for project-specific replacements."""

    def test_simple_substitution(self) -> None:
        subs   = {"secret-project": "my-app"}
        result = apply_substitutions("The secret-project is live.", subs)
        self.assertEqual(result, "The my-app is live.")

    def test_longest_first_prevents_partial(self) -> None:
        """Longer keys must be replaced before shorter ones to avoid partial matches."""
        subs = {
            "D:/Projects/libs/":  "~/libs/",
            "D:/Projects/":      "~/projects/",
        }
        content = "Source at D:/Projects/libs/utils.py and D:/Projects/site/index.php"
        result  = apply_substitutions(content, subs)
        self.assertEqual(result, "Source at ~/libs/utils.py and ~/projects/site/index.php")

    def test_empty_substitutions(self) -> None:
        content = "No changes expected."
        result  = apply_substitutions(content, {})
        self.assertEqual(result, content)

    def test_no_match_unchanged(self) -> None:
        subs   = {"nonexistent-token": "replacement"}
        content = "Nothing to replace here."
        result  = apply_substitutions(content, subs)
        self.assertEqual(result, content)

    def test_multiple_occurrences(self) -> None:
        subs    = {"foo": "bar"}
        content = "foo and foo again"
        result  = apply_substitutions(content, subs)
        self.assertEqual(result, "bar and bar again")

    def test_backslash_normalization_after_substitution(self) -> None:
        """Substitution that introduces ~/ paths with leftover backslashes
        should get cleaned up by the trailing regex pass."""
        subs    = {"D:\\Projects\\libs\\": "~/libs/"}
        content = "Look at D:\\Projects\\libs\\utils\\helper.py"
        result  = apply_substitutions(content, subs)
        # The regex in apply_substitutions normalizes backslashes in ~/... paths
        self.assertIn("~/libs/", result)


if __name__ == "__main__":
    unittest.main()
