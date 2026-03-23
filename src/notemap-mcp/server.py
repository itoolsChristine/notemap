"""MCP server entry point for the notemap Cornell note-taking system.

Registers 11 tools via FastMCP and connects them to implementation modules.
Uses stdio transport for communication with Claude Code.
"""
from __future__ import annotations

__version__ = "1.0.0"

import json
import traceback
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from index import load_or_rebuild_index, save_index
from notes import create_note, read_note, update_note, delete_note
from search import search_notes
from audit import audit_notes, review_queue
from lint import lint_code
from preflight import preflight_notes
from check import check_code

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOTEMAP_DIR = Path.home() / ".claude" / "notemap"

# ---------------------------------------------------------------------------
# Lazy-loaded index
# ---------------------------------------------------------------------------

_index: dict[str, dict[str, Any]] | None = None
_index_load_time: float = 0.0


def get_index() -> dict[str, dict[str, Any]]:
    """Load or rebuild the in-memory index, checking for staleness."""
    global _index, _index_load_time
    import time

    now = time.monotonic()
    needs_load = _index is None

    # Periodically check if any .md file is newer than our in-memory load
    if not needs_load and (now - _index_load_time) > 5.0:
        index_path = NOTEMAP_DIR / "_index.json"
        if index_path.exists():
            index_mtime = index_path.stat().st_mtime
            for md_file in NOTEMAP_DIR.rglob("*.md"):
                rel = md_file.relative_to(NOTEMAP_DIR)
                if rel.parts and rel.parts[0] == "_archive":
                    continue
                if md_file.stat().st_mtime > index_mtime:
                    needs_load = True
                    break

    if needs_load:
        NOTEMAP_DIR.mkdir(parents=True, exist_ok=True)
        _index = load_or_rebuild_index(NOTEMAP_DIR)
        _index_load_time = now

    return _index


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _error_response(message: str, detail: str = "") -> str:
    """Return a JSON error string for tool responses."""
    payload: dict[str, str] = {"error": message}
    if detail:
        payload["detail"] = detail
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------

mcp_server = FastMCP("notemap")


# ---------------------------------------------------------------------------
# Tool: notemap_create
# ---------------------------------------------------------------------------

@mcp_server.tool()
def notemap_create(
    library: str,
    topic: str,
    notes: str,
    summary: str,
    cues: list[str] | None = None,
    type: str = "knowledge",
    tags: list[str] | None = None,
    source_quality: str = "unverified",
    confidence: str = "weak",
    library_version: str | None = None,
    related_functions: list[str] | None = None,
    related_notes: list[str] | None = None,
    sources: list[dict] | None = None,
    primitives_to_avoid: list[str] | None = None,
    preferred_alternatives: list[str] | None = None,
    wrong_assumption: str | None = None,
    correct_behavior: str | None = None,
    applies_to: str | None = None,
) -> str:
    """Create a new Cornell note.

    Requires library, topic, notes body, and summary. Returns the created
    note's ID and path on success.

    Sources is a list of dicts, each with a "type" key and type-specific fields:
      - {type: "file", path: "src/DB.php", lines: "304-335"}
      - {type: "url", url: "https://...", section: "Rate limits"}
      - {type: "user", context: "User corrected assumption about..."}
    """
    try:
        index = get_index()
        params: dict[str, Any] = {
            "library":                library,
            "topic":                  topic,
            "notes":                  notes,
            "summary":                summary,
            "cues":                   cues,
            "type":                   type,
            "tags":                   tags,
            "source_quality":         source_quality,
            "confidence":             confidence,
            "library_version":        library_version,
            "related_functions":      related_functions,
            "related_notes":          related_notes,
            "sources":                sources,
            "primitives_to_avoid":    primitives_to_avoid,
            "preferred_alternatives": preferred_alternatives,
            "wrong_assumption":       wrong_assumption,
            "correct_behavior":       correct_behavior,
            "applies_to":             applies_to,
        }
        result = create_note(index, NOTEMAP_DIR, params)
        save_index(NOTEMAP_DIR, index)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_read
# ---------------------------------------------------------------------------

@mcp_server.tool()
def notemap_read(
    id: str,
    section: str = "all",
) -> str:
    """Read a note by ID.

    Returns the full note or a specific section (cues, notes, summary, meta).
    """
    try:
        index = get_index()
        result = read_note(index, NOTEMAP_DIR, {"id": id, "section": section})
        return json.dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_search
# ---------------------------------------------------------------------------

@mcp_server.tool()
def notemap_search(
    query: str | None = None,
    library: str | None = None,
    function_name: str | None = None,
    tag: str | None = None,
    type: str | None = None,
    source_quality: str | None = None,
    confidence: str | None = None,
    lifecycle: str = "active",
    max_results: int = 0,
) -> str:
    """Search notes by keyword, library, function, tag, or type.

    Returns matching notes ranked by relevance score. max_results=0 means all.
    """
    try:
        index = get_index()
        params: dict[str, Any] = {
            "query":          query,
            "library":        library,
            "function_name":  function_name,
            "tag":            tag,
            "type":           type,
            "source_quality": source_quality,
            "confidence":     confidence,
            "lifecycle":      lifecycle,
            "max_results":    max_results,
        }
        result = search_notes(index, params)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_update
# ---------------------------------------------------------------------------

@mcp_server.tool()
def notemap_update(
    id: str,
    cues: dict | None = None,
    notes: str | None = None,
    notes_append: str | None = None,
    summary: str | None = None,
    tags: dict | None = None,
    source_quality: str | None = None,
    confidence: str | None = None,
    related_functions: dict | None = None,
    related_notes: dict | None = None,
    library_version: str | None = None,
    review_interval_days: int | None = None,
    primitives_to_avoid: dict | None = None,
    preferred_alternatives: dict | None = None,
    sources: list[dict] | None = None,
    wrong_assumption: str | None = None,
    correct_behavior: str | None = None,
    applies_to: str | None = None,
    mark_reviewed: bool = False,
    increment_miss: bool = False,
    miss_reason: str | None = None,
) -> str:
    """Update an existing note's fields.

    List/set fields (cues, tags, related_functions, related_notes,
    primitives_to_avoid, preferred_alternatives) accept a dict with
    an "add" and/or "remove" key for incremental updates.

    Sources is a list of dicts (full replacement, not incremental):
      - {type: "file", path: "src/DB.php", lines: "304-335"}
      - {type: "url", url: "https://...", section: "Rate limits"}
      - {type: "user", context: "User corrected assumption about..."}
    """
    try:
        index = get_index()
        params: dict[str, Any] = {
            "id":                     id,
            "cues":                   cues,
            "notes":                  notes,
            "notes_append":           notes_append,
            "summary":                summary,
            "tags":                   tags,
            "source_quality":         source_quality,
            "confidence":             confidence,
            "related_functions":      related_functions,
            "related_notes":          related_notes,
            "library_version":        library_version,
            "review_interval_days":   review_interval_days,
            "sources":                sources,
            "primitives_to_avoid":    primitives_to_avoid,
            "preferred_alternatives": preferred_alternatives,
            "wrong_assumption":       wrong_assumption,
            "correct_behavior":       correct_behavior,
            "applies_to":             applies_to,
            "mark_reviewed":          mark_reviewed,
            "increment_miss":         increment_miss,
            "miss_reason":            miss_reason,
        }
        # Strip None values so "key in params" checks in update_note only trigger for explicitly-set fields
        params = {k: v for k, v in params.items() if v is not None}
        result = update_note(index, NOTEMAP_DIR, params)
        save_index(NOTEMAP_DIR, index)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_delete
# ---------------------------------------------------------------------------

@mcp_server.tool()
def notemap_delete(
    id: str,
    reason: str | None = None,
    hard_delete: bool = False,
) -> str:
    """Delete (archive) a note by ID.

    Soft-deletes by default (moves to _archive/). Pass hard_delete=True
    to permanently remove the file.
    """
    try:
        index = get_index()
        params: dict[str, Any] = {
            "id":          id,
            "reason":      reason,
            "hard_delete": hard_delete,
        }
        result = delete_note(index, NOTEMAP_DIR, params)
        save_index(NOTEMAP_DIR, index)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_audit
# ---------------------------------------------------------------------------

@mcp_server.tool()
def notemap_audit(
    check: str = "all",
    stale_days: int | None = None,
    library: str | None = None,
) -> str:
    """Find notes needing attention.

    Checks: stale, low_confidence, unreviewed, high_miss_count,
    orphaned_functions, index_integrity, or all.
    """
    try:
        index = get_index()
        params: dict[str, Any] = {
            "check":      check,
            "stale_days": stale_days,
            "library":    library,
        }
        result = audit_notes(index, NOTEMAP_DIR, params)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_review
# ---------------------------------------------------------------------------

@mcp_server.tool()
def notemap_review(
    library: str | None = None,
    limit: int = 0,
) -> str:
    """Get a prioritized review queue.

    Returns notes most in need of review, ranked by staleness, miss count,
    and confidence level. Limit=0 means return all.
    """
    try:
        index = get_index()
        params: dict[str, Any] = {
            "library": library,
            "limit":   limit,
        }
        result = review_queue(index, params)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_lint
# ---------------------------------------------------------------------------

@mcp_server.tool()
def notemap_lint(
    code: str,
    library: str | None = None,
) -> str:
    """Check code against known anti-patterns from notes.

    Scans the provided code string for primitives_to_avoid and returns
    warnings with preferred alternatives.
    """
    try:
        index = get_index()
        params: dict[str, Any] = {
            "code":    code,
            "library": library,
        }
        result = lint_code(index, params)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_stats
# ---------------------------------------------------------------------------

@mcp_server.tool()
def notemap_stats() -> str:
    """Get an overview of the notemap knowledge base.

    Returns: total note count, libraries with note counts,
    note type breakdown, and overall health indicators.
    Use this at session start to discover what libraries have notes.
    """
    try:
        index = get_index()

        # Count by library
        libs: dict[str, int] = {}
        types: dict[str, int] = {}
        stale_count = 0
        low_conf_count = 0

        for entry in index.values():
            lib = entry.get("library", "unknown")
            libs[lib] = libs.get(lib, 0) + 1

            ntype = entry.get("type", "knowledge")
            types[ntype] = types.get(ntype, 0) + 1

            if entry.get("lifecycle") == "stale":
                stale_count += 1
            if (entry.get("confidence") == "weak"
                    and entry.get("source_quality") in ("inferred", "unverified")):
                low_conf_count += 1

        result = {
            "version": __version__,
            "total_notes": len(index),
            "libraries": dict(sorted(libs.items(), key=lambda x: -x[1])),
            "note_types": types,
            "stale_notes": stale_count,
            "low_confidence_notes": low_conf_count,
        }
        return json.dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_preflight
# ---------------------------------------------------------------------------

@mcp_server.tool()
def notemap_preflight(
    libraries: list[str],
    versions: dict | None = None,
    include_cross_cutting: bool = True,
) -> str:
    """Load all notes for the specified libraries in a compact briefing format.

    Call this at session start or when switching to a new task domain.
    Returns all notes organized by priority: anti-patterns first, then
    corrections, knowledge, and conventions, grouped by library.

    include_cross_cutting=True (default) also includes notes from the
    _cross-cutting library, which apply regardless of specific library.

    versions is an optional dict mapping library names to version strings
    (e.g., {"zendb": "3.0", "smartstring": "2.8"}). When provided, notes
    with incompatible library_version fields are excluded.
    """
    try:
        index = get_index()
        params: dict[str, Any] = {
            "libraries":             libraries,
            "versions":              versions,
            "include_cross_cutting": include_cross_cutting,
        }
        result = preflight_notes(index, params)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_check
# ---------------------------------------------------------------------------

@mcp_server.tool()
def notemap_check(
    code: str = "",
    file_path: str | None = None,
    versions: dict | None = None,
) -> str:
    """Check code against notemap knowledge: anti-patterns, function gotchas,
    and cross-cutting notes.

    Auto-detects libraries from code patterns (DB::, SmartString, etc.) and
    file extension. Runs lint + function-specific note lookup in one call.
    Returns a consolidated report of everything noteworthy.

    Call this after writing code to catch issues you don't know to search for.
    You can pass code as a string, OR just pass a file_path and the tool
    will read the file for you. Both can be provided (file_path adds
    extension-based hints even when code is passed directly).

    versions is an optional dict mapping library names to version strings
    for filtering version-specific notes.
    """
    try:
        index = get_index()
        params: dict[str, Any] = {
            "code":      code,
            "file_path": file_path,
            "versions":  versions,
        }
        result = check_code(index, params)
        return json.dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp_server.run(transport="stdio")
