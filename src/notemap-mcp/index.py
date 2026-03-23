"""In-memory search index management for the notemap system.

Maintains a JSON index at `~/.claude/notemap/_index.json` that caches note
metadata for fast search.  Loaded into memory at startup and updated on
every mutation.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import frontmatter

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_index: dict[str, dict[str, Any]] = {}
_notemap_dir: Path = Path.home() / ".claude" / "notemap"

_INDEX_FILENAME = "_index.json"

# Directories / file prefixes to skip when scanning .md files
_SKIP_DIRS  = {"_archive"}
_SKIP_CHARS = {"_"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_or_rebuild_index(notemap_dir: Path) -> dict[str, dict[str, Any]]:
    """Load the cached index if fresh, otherwise rebuild from .md files.

    "Fresh" means `_index.json` exists and no `.md` file anywhere inside
    *notemap_dir* has a modification time newer than the index file.

    Returns the ``notes`` dict keyed by note ID.
    """
    global _index, _notemap_dir
    _notemap_dir = notemap_dir

    index_path = notemap_dir / _INDEX_FILENAME

    if index_path.exists():
        index_mtime = index_path.stat().st_mtime
        needs_rebuild = False

        for md_file in _iter_md_files(notemap_dir):
            if md_file.stat().st_mtime > index_mtime:
                needs_rebuild = True
                break

        if not needs_rebuild:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
            _index = raw.get("notes", {})
            return _index

    # Index missing or stale -- rebuild
    _index = rebuild_index(notemap_dir)
    return _index


def rebuild_index(notemap_dir: Path) -> dict[str, dict[str, Any]]:
    """Scan all .md files and rebuild the index from scratch.

    Skips ``_archive/`` and files whose names start with ``_``.
    Writes the result to ``_index.json`` and returns the ``notes`` dict.
    """
    global _index, _notemap_dir
    _notemap_dir = notemap_dir

    notes: dict[str, dict[str, Any]] = {}

    for md_file in _iter_md_files(notemap_dir):
        try:
            entry = parse_note_file(md_file, notemap_dir)
        except Exception:
            # Malformed file -- skip rather than crash the whole index
            continue

        note_id = entry.get("id", "")
        if note_id:
            notes[note_id] = entry

    _index = notes
    save_index(notemap_dir, _index)
    return _index


def save_index(notemap_dir: Path, index: dict[str, dict[str, Any]]) -> None:
    """Persist the index dict to ``_index.json`` atomically.

    Uses a temp file in the same directory + ``os.replace()`` so the
    write is as close to atomic as Windows allows.
    """
    notemap_dir.mkdir(parents=True, exist_ok=True)
    index_path = notemap_dir / _INDEX_FILENAME

    payload = {
        "last_rebuilt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notes": index,
    }

    # Write to a temp file in the same directory, then replace
    fd, tmp_path = tempfile.mkstemp(
        dir=str(notemap_dir),
        prefix="_index_tmp_",
        suffix=".json",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=True, indent=2)
        os.replace(tmp_path, str(index_path))
    except Exception:
        # Clean up the temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def update_entry(index: dict[str, dict[str, Any]], note_id: str, entry: dict[str, Any]) -> None:
    """Update (or insert) a single entry in the in-memory index."""
    index[note_id] = entry


def remove_entry(index: dict[str, dict[str, Any]], note_id: str) -> None:
    """Remove a single entry from the in-memory index.

    Silently ignores missing keys.
    """
    index.pop(note_id, None)


def parse_note_file(file_path: Path, notemap_dir: Path) -> dict[str, Any]:
    """Parse a single .md note file into an index entry dict.

    Extracts:
    - All YAML frontmatter fields
    - Cues from the ``## Cues`` section (lines starting with ``- ``)
    - Summary text from the ``## Summary`` section

    The full ``## Notes`` body is **not** stored in the index.
    ``path`` is stored relative to *notemap_dir*.
    """
    post = frontmatter.load(str(file_path))
    meta: dict[str, Any] = dict(post.metadata)
    body: str = post.content

    sections = _split_sections(body)

    # --- Cues ---------------------------------------------------------------
    cues_text = sections.get("cues", "")
    cues: list[str] = []
    for line in cues_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            cues.append(stripped[2:].strip())

    # --- Summary ------------------------------------------------------------
    summary = sections.get("summary", "").strip()

    # --- Build entry --------------------------------------------------------
    relative_path = file_path.relative_to(notemap_dir).as_posix()

    entry: dict[str, Any] = {
        "id":                     meta.get("id", ""),
        "library":                meta.get("library", ""),
        "topic":                  meta.get("topic", ""),
        "type":                   meta.get("type", "knowledge"),
        "tags":                   _as_list(meta.get("tags", [])),
        "source_quality":         meta.get("source_quality", "unverified"),
        "confidence":             meta.get("confidence", "maybe"),
        "lifecycle":              meta.get("lifecycle", "active"),
        "library_version":        meta.get("library_version", ""),
        "related_functions":      _as_list(meta.get("related_functions", [])),
        "related_notes":          _as_list(meta.get("related_notes", [])),
        "cues":                   cues,
        "summary":                summary,
        "miss_count":             int(meta.get("miss_count", 0)),
        "miss_log":               _as_list(meta.get("miss_log", [])),
        "review_count":           int(meta.get("review_count", 0)),
        "review_interval_days":   int(meta.get("review_interval_days", 30)),
        "created":                _date_str(meta.get("created", "")),
        "last_modified":          _date_str(meta.get("last_modified", "")),
        "last_reviewed":          _date_str(meta.get("last_reviewed", "")),
        "path":                   relative_path,
        # Source citations
        "sources":                _as_list(meta.get("sources", [])),
        # Anti-pattern fields
        "primitives_to_avoid":    _as_list(meta.get("primitives_to_avoid", [])),
        "preferred_alternatives": _as_list(meta.get("preferred_alternatives", [])),
        # Correction fields
        "wrong_assumption":       meta.get("wrong_assumption", ""),
        "correct_behavior":       meta.get("correct_behavior", ""),
        # Convention fields
        "applies_to":             meta.get("applies_to", ""),
    }

    return entry


# ---------------------------------------------------------------------------
# Accessors for module-level state
# ---------------------------------------------------------------------------

def get_index() -> dict[str, dict[str, Any]]:
    """Return a reference to the in-memory index."""
    return _index


def get_notemap_dir() -> Path:
    """Return the configured notemap directory."""
    return _notemap_dir


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _iter_md_files(notemap_dir: Path) -> list[Path]:
    """Return all eligible .md files under *notemap_dir*.

    Skips ``_archive/`` directories and files whose names start with ``_``.
    """
    results: list[Path] = []

    if not notemap_dir.exists():
        return results

    for md_file in notemap_dir.rglob("*.md"):
        # Skip files starting with underscore
        if md_file.name[:1] in _SKIP_CHARS:
            continue

        # Skip files inside _archive/ or other skipped directories
        relative_parts = md_file.relative_to(notemap_dir).parts
        if any(part in _SKIP_DIRS for part in relative_parts):
            continue

        results.append(md_file)

    return results


_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _split_sections(body: str) -> dict[str, str]:
    """Split a markdown body on ``## `` headings into a dict.

    Keys are lower-cased heading text.  Values are the content between
    that heading and the next ``## `` heading (or end of string).
    """
    sections: dict[str, str] = {}
    matches = list(_HEADING_RE.finditer(body))

    for i, match in enumerate(matches):
        heading = match.group(1).strip().lower()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[heading] = body[start:end].strip()

    return sections


def _as_list(value: Any) -> list[Any]:
    """Coerce *value* to a list, wrapping scalars if needed."""
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _date_str(value: Any) -> str:
    """Normalise a date value to a ``YYYY-MM-DD`` string.

    Handles ``datetime.date``, ``datetime.datetime``, and plain strings.
    Returns an empty string for falsy / unparseable values.
    """
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)
