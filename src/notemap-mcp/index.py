"""In-memory search index management for the notemap system.

Bridge layer: loads notes from SQLite into the same dict format that all
other modules expect. Replaces the old JSON index + markdown file parsing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db import get_db, load_all_notes, load_note_dict

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_index: dict[str, dict[str, Any]] = {}
_notemap_dir: Path = Path.home() / ".claude" / "notemap"

# Backlink reverse index: {target_note_id: [{"source": source_id, "type": link_type}, ...]}
_backlinks: dict[str, list[dict[str, str]]] = {}

# Tag co-occurrence matrix: {tag_a: {tag_b: count}}
_tag_cooccurrence: dict[str, dict[str, int]] = {}

# Graph scores (populated by build_graph_scores)
_pagerank_scores: dict[str, float] = {}
_hub_scores: dict[str, float] = {}
_authority_scores: dict[str, float] = {}

# Entry-point index: {function_name_lower: [note_id, ...]}
_entry_points: dict[str, list[str]] = {}

# Project-to-topic mapping
_project_topics: dict[str, list[str]] = {}

# Topic metadata
_topic_metadata: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_or_rebuild_index(notemap_dir: Path) -> dict[str, dict[str, Any]]:
    """Load notes from SQLite into the same dict format other modules expect.

    Opens the database, loads all notes, and builds derived indexes
    (backlinks, tag co-occurrence, graph scores, entry points).
    """
    global _index, _notemap_dir
    _notemap_dir = notemap_dir

    conn = get_db(notemap_dir)
    _index = load_all_notes(conn)

    # Auto-dormancy: if valid_until is set and in the past, mark as dormant
    from datetime import date
    today = date.today()
    for entry in _index.values():
        valid_until = entry.get("valid_until", "")
        if valid_until:
            try:
                until_date = date.fromisoformat(valid_until)
                if until_date < today and entry.get("lifecycle") == "active":
                    entry["lifecycle"] = "dormant"
            except (ValueError, TypeError):
                pass

    build_backlink_index(_index)
    build_anchor_text(_index)
    build_tag_cooccurrence(_index)
    build_graph_scores(_index, _backlinks)
    build_entry_points(_index)
    load_project_topics(notemap_dir)
    load_topic_metadata(notemap_dir)
    return _index


def rebuild_index(notemap_dir: Path) -> dict[str, dict[str, Any]]:
    """Reload everything from the database."""
    return load_or_rebuild_index(notemap_dir)


def save_index(notemap_dir: Path, index: dict[str, dict[str, Any]]) -> None:
    """No-op. SQLite handles persistence via transactions."""
    pass


def update_entry(index: dict[str, dict[str, Any]], note_id: str, entry: dict[str, Any]) -> None:
    """Update (or insert) a single entry in the in-memory index."""
    index[note_id] = entry


def remove_entry(index: dict[str, dict[str, Any]], note_id: str) -> None:
    """Remove a single entry from the in-memory index."""
    index.pop(note_id, None)


def load_project_topics(notemap_dir: Path) -> dict[str, list[str]]:
    """Load project-to-topic mapping from the database."""
    global _project_topics
    conn = get_db(notemap_dir)
    _project_topics = {}
    try:
        rows = conn.execute("SELECT project_path, library FROM project_topics").fetchall()
        for row in rows:
            path = row["project_path"]
            lib = row["library"]
            _project_topics.setdefault(path, []).append(lib)
    except Exception:
        _project_topics = {}
    return _project_topics


def get_project_topics(project_path: str = "") -> list[str]:
    """Get relevant topics/libraries for a project path."""
    if not project_path or not _project_topics:
        return []
    normalized = project_path.replace("\\", "/").lower()
    best_match: str = ""
    best_topics: list[str] = []
    for pattern, topics in _project_topics.items():
        pat_normalized = pattern.replace("\\", "/").lower()
        if normalized.startswith(pat_normalized) and len(pat_normalized) > len(best_match):
            best_match = pat_normalized
            best_topics = topics
    return best_topics


def load_topic_metadata(notemap_dir: Path) -> dict[str, dict[str, Any]]:
    """Load per-library topic metadata from the database."""
    global _topic_metadata
    conn = get_db(notemap_dir)
    _topic_metadata = {}
    try:
        rows = conn.execute("SELECT library, description, volatility FROM topic_metadata").fetchall()
        for row in rows:
            _topic_metadata[row["library"]] = {
                "description": row["description"],
                "volatility": row["volatility"],
            }
    except Exception:
        _topic_metadata = {}
    return _topic_metadata


def get_topic_volatility(library: str) -> str:
    """Get volatility classification for a library."""
    meta = _topic_metadata.get(library, {})
    return meta.get("volatility", "stable")


def get_topic_metadata() -> dict[str, dict[str, Any]]:
    """Return the full topic metadata dict."""
    return _topic_metadata


# ---------------------------------------------------------------------------
# Backlink index
# ---------------------------------------------------------------------------

def build_backlink_index(index: dict[str, dict[str, Any]]) -> None:
    """Build reverse mapping from related_notes links."""
    global _backlinks
    _backlinks = {}

    for note_id, entry in index.items():
        related = entry.get("related_notes") or []
        for link in related:
            if isinstance(link, str):
                target_id = link
                link_type = "related"
            elif isinstance(link, dict):
                target_id = link.get("id", "")
                link_type = link.get("type", "related")
            else:
                continue

            if target_id:
                if target_id not in _backlinks:
                    _backlinks[target_id] = []
                _backlinks[target_id].append({
                    "source": note_id,
                    "type": link_type,
                })


def get_backlinks(note_id: str) -> list[dict[str, str]]:
    """Return all notes that link TO the given note."""
    return _backlinks.get(note_id, [])


def get_backlink_index() -> dict[str, list[dict[str, str]]]:
    """Return the full backlink index."""
    return _backlinks


# ---------------------------------------------------------------------------
# Tag co-occurrence
# ---------------------------------------------------------------------------

def build_tag_cooccurrence(index: dict[str, dict[str, Any]]) -> None:
    """Build tag co-occurrence matrix from note tags."""
    global _tag_cooccurrence
    _tag_cooccurrence = {}

    for nid, entry in index.items():
        tags = sorted(set(t.lower() for t in (entry.get("tags") or [])))
        for i, tag_a in enumerate(tags):
            for tag_b in tags[i + 1:]:
                if tag_a not in _tag_cooccurrence:
                    _tag_cooccurrence[tag_a] = {}
                _tag_cooccurrence[tag_a][tag_b] = _tag_cooccurrence[tag_a].get(tag_b, 0) + 1


def get_tag_cooccurrence() -> dict[str, dict[str, int]]:
    """Return the tag co-occurrence matrix."""
    return _tag_cooccurrence


# ---------------------------------------------------------------------------
# Graph scores
# ---------------------------------------------------------------------------

def build_graph_scores(
    index: dict[str, dict[str, Any]],
    backlinks: dict[str, list[dict[str, str]]],
) -> None:
    """Compute and cache PageRank and HITS scores from the link graph."""
    global _pagerank_scores, _hub_scores, _authority_scores
    from graph import pagerank, hits
    _pagerank_scores = pagerank(index, backlinks)
    _hub_scores, _authority_scores = hits(index, backlinks)


def get_pagerank_scores() -> dict[str, float]:
    """Return the cached PageRank scores dict (note_id -> score 0-1)."""
    return dict(_pagerank_scores)


def get_hub_scores() -> dict[str, float]:
    """Return cached HITS hub scores."""
    return _hub_scores


def get_authority_scores() -> dict[str, float]:
    """Return cached HITS authority scores."""
    return _authority_scores


# ---------------------------------------------------------------------------
# Anchor text index
# ---------------------------------------------------------------------------

def build_anchor_text(index: dict[str, dict[str, Any]]) -> None:
    """Build anchor text for notes from their inbound link context."""
    anchor_map: dict[str, list[str]] = {}
    for note_id, entry in index.items():
        related = entry.get("related_notes") or []
        linker_summary = entry.get("summary", "")
        if not linker_summary:
            continue
        for link in related:
            target_id = link.get("id", link) if isinstance(link, dict) else link
            if target_id in index:
                anchor_map.setdefault(target_id, []).append(linker_summary)

    for target_id, summaries in anchor_map.items():
        index[target_id]["anchor_text"] = " ".join(summaries)


# ---------------------------------------------------------------------------
# Entry-point index
# ---------------------------------------------------------------------------

def build_entry_points(index: dict[str, dict[str, Any]]) -> None:
    """Pre-compute top note IDs for each related_function."""
    global _entry_points
    _entry_points = {}

    fn_to_notes: dict[str, list[tuple[str, float]]] = {}
    for nid, entry in index.items():
        if entry.get("lifecycle") not in ("active", "evergreen"):
            continue
        quality = {"strong": 1.0, "maybe": 0.7, "weak": 0.4}.get(
            entry.get("confidence", "maybe"), 0.7
        )
        for fn in (entry.get("related_functions") or []):
            fn_lower = fn.lower()
            fn_to_notes.setdefault(fn_lower, []).append((nid, quality))

    for fn, notes in fn_to_notes.items():
        notes.sort(key=lambda x: -x[1])
        _entry_points[fn] = [nid for nid, _ in notes[:5]]


def get_entry_points() -> dict[str, list[str]]:
    """Return the pre-computed entry-point index."""
    return _entry_points


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
# Legacy: parse_note_file (kept for backward compat with tests)
# ---------------------------------------------------------------------------

def parse_note_file(file_path: Path, notemap_dir: Path) -> dict[str, Any]:
    """Parse a single .md note file into an index entry dict.

    Legacy function kept for migration and tests. New code should use
    load_note_dict() from db.py instead.
    """
    import re
    import frontmatter

    post = frontmatter.load(str(file_path))
    meta: dict[str, Any] = dict(post.metadata)
    body: str = post.content

    heading_re = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    sections: dict[str, str] = {}
    matches = list(heading_re.finditer(body))
    for i, match in enumerate(matches):
        heading = match.group(1).strip().lower()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[heading] = body[start:end].strip()

    cues_text = sections.get("cues", "")
    cues: list[str] = []
    for line in cues_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            cues.append(stripped[2:].strip())

    summary = sections.get("summary", "").strip()

    context_prefix = "This note is about %s in %s" % (
        meta.get("topic", ""), meta.get("library", "")
    )
    notes_body_raw = sections.get("notes", "").strip()
    notes_body = (context_prefix + ". " + notes_body_raw)[:500]

    relative_path = file_path.relative_to(notemap_dir).as_posix()

    def _as_list(value):
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]

    def _normalize_related_notes(value):
        raw = _as_list(value)
        result = []
        for item in raw:
            if isinstance(item, str):
                result.append({"id": item, "type": "related"})
            elif isinstance(item, dict) and "id" in item:
                if "type" not in item:
                    item["type"] = "related"
                result.append(item)
        return result

    def _date_str(value):
        if not value:
            return ""
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        return str(value)

    entry: dict[str, Any] = {
        "id":                     meta.get("id", ""),
        "library":                meta.get("library", ""),
        "topic":                  meta.get("topic", ""),
        "type":                   meta.get("type", "knowledge"),
        "tags":                   _as_list(meta.get("tags") or []),
        "source_quality":         meta.get("source_quality", "unverified"),
        "confidence":             meta.get("confidence", "maybe"),
        "lifecycle":              meta.get("lifecycle", "active"),
        "library_version":        meta.get("library_version", ""),
        "related_functions":      _as_list(meta.get("related_functions") or []),
        "related_notes":          _normalize_related_notes(meta.get("related_notes") or []),
        "always_relevant":        bool(meta.get("always_relevant", False)),
        "valid_from":             _date_str(meta.get("valid_from", meta.get("created", ""))),
        "valid_until":            _date_str(meta.get("valid_until", "")),
        "additional_topics":      _as_list(meta.get("additional_topics") or []),
        "last_retrieved":         _date_str(meta.get("last_retrieved", "")),
        "retrieval_count":        int(meta.get("retrieval_count", 0)),
        "cues":                   cues,
        "summary":                summary,
        "notes_body":             notes_body,
        "miss_count":             int(meta.get("miss_count", 0)),
        "miss_log":               _as_list(meta.get("miss_log") or []),
        "review_count":           int(meta.get("review_count", 0)),
        "review_interval_days":   int(meta.get("review_interval_days", 30)),
        "created":                _date_str(meta.get("created", "")),
        "last_modified":          _date_str(meta.get("last_modified", "")),
        "last_reviewed":          _date_str(meta.get("last_reviewed", "")),
        "path":                   relative_path,
        "sources":                _as_list(meta.get("sources") or []),
        "primitives_to_avoid":    _as_list(meta.get("primitives_to_avoid") or []),
        "preferred_alternatives": _as_list(meta.get("preferred_alternatives") or []),
        "wrong_assumption":       meta.get("wrong_assumption", ""),
        "correct_behavior":       meta.get("correct_behavior", ""),
        "applies_to":             meta.get("applies_to", ""),
    }

    valid_until = entry.get("valid_until", "")
    if valid_until:
        try:
            from datetime import date
            until_date = date.fromisoformat(valid_until)
            if until_date < date.today() and entry.get("lifecycle") == "active":
                entry["lifecycle"] = "dormant"
        except (ValueError, TypeError):
            pass

    return entry
