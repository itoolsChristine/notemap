"""MCP server entry point for the notemap Cornell note-taking system.

Registers 14 tools via FastMCP and connects them to implementation modules.
Uses stdio transport for communication with Claude Code.
"""
from __future__ import annotations

# Single source of truth is the repo-root VERSION file; sync.py keeps this line
# in step with it (and tests/test_sync.py asserts they match in CI).
__version__ = "1.2.0"

import traceback
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from db import get_db, close_db
from index import load_or_rebuild_index, save_index, get_backlinks, get_backlink_index
from notes import create_note, read_note, update_note, delete_note
from search import search_notes
from audit import audit_notes, review_queue
from lint import lint_code
from preflight import preflight_notes
from check import check_code
from events import init_events, log_co_retrieval, log_event, log_search_miss
from utils import cap_result_lists, safe_json_dumps

try:
    from embed import EMBEDDINGS_AVAILABLE, encode_text, MODEL_NAME, DIMENSIONS, invalidate_cache
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    encode_text = None
    MODEL_NAME = ""
    DIMENSIONS = 0
    invalidate_cache = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOTEMAP_DIR = Path.home() / ".claude" / "notemap"

# ---------------------------------------------------------------------------
# Lazy-loaded index
# ---------------------------------------------------------------------------

_index: dict[str, dict[str, Any]] | None = None
_events_initialized: bool = False


def get_index() -> dict[str, dict[str, Any]]:
    """Load the in-memory index from SQLite."""
    global _index

    if _index is None:
        NOTEMAP_DIR.mkdir(parents=True, exist_ok=True)
        _index = load_or_rebuild_index(NOTEMAP_DIR)

    global _events_initialized
    if not _events_initialized:
        init_events(NOTEMAP_DIR)
        _events_initialized = True

    return _index


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _error_response(message: str, detail: str = "") -> str:
    """Return a JSON error string for tool responses."""
    payload: dict[str, str] = {"error": message}
    if detail:
        payload["detail"] = detail
    return safe_json_dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------

mcp_server = FastMCP(
    "notemap",
    instructions=(
        "Persistent knowledge base for gotchas, anti-patterns, and learned insights. "
        "Run notemap_preflight at session start to load anti-patterns. "
        "Run notemap_check after writing or editing code to catch issues. "
        "Use notemap_search before relying on training data alone. "
        "Create notes with notemap_create when you learn something surprising."
    ),
)


# ---------------------------------------------------------------------------
# Tool: notemap_create
# ---------------------------------------------------------------------------

@mcp_server.tool(
    meta={
        "anthropic/alwaysLoad": True,
        "anthropic/searchHint": "save learning gotcha note knowledge anti-pattern correction",
    },
)
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
    related_notes: list[dict | str] | None = None,
    sources: list[dict] | None = None,
    primitives_to_avoid: list[str] | None = None,
    preferred_alternatives: list[str] | None = None,
    wrong_assumption: str | None = None,
    correct_behavior: str | None = None,
    applies_to: str | None = None,
) -> str:
    """Create a new Cornell note.

    library is the topic/domain this note belongs to (e.g., 'zendb', 'python',
    'javascript/json'). Hierarchical names with '/' create nested directories.

    Requires library, topic, notes body, and summary. Returns the created
    note's ID and path on success.

    related_notes accepts plain ID strings or typed link dicts:
      - "other-note-id"  (defaults to type "related")
      - {"id": "other-note-id", "type": "related|extends|depends_on|supersedes|contradicts"}

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
        return safe_json_dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_read
# ---------------------------------------------------------------------------

@mcp_server.tool(
    meta={"anthropic/searchHint": "read note full detail body metadata cues"},
)
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

        # Add linked note summaries when reading successfully
        if "error" not in result and id in index:
            entry = index[id]
            related = entry.get("related_notes") or []
            linked_summaries: list[dict[str, str]] = []

            for link in related:
                link_id = link.get("id", link) if isinstance(link, dict) else link
                link_type = link.get("type", "related") if isinstance(link, dict) else "related"
                linked_entry = index.get(link_id)
                if linked_entry:
                    linked_summaries.append({
                        "id": link_id,
                        "direction": "outgoing",
                        "type": link_type,
                        "topic": linked_entry.get("topic", ""),
                        "summary": linked_entry.get("summary", ""),
                    })

            for bl in get_backlinks(id):
                bl_entry = index.get(bl["source"])
                if bl_entry:
                    linked_summaries.append({
                        "id": bl["source"],
                        "direction": "incoming",
                        "type": bl["type"],
                        "topic": bl_entry.get("topic", ""),
                        "summary": bl_entry.get("summary", ""),
                    })

            if linked_summaries:
                result["linked_notes"] = linked_summaries

        return safe_json_dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_search
# ---------------------------------------------------------------------------

@mcp_server.tool(
    meta={
        "anthropic/alwaysLoad": True,
        "anthropic/searchHint": "search lookup gotcha function note knowledge anti-pattern",
    },
)
def notemap_search(
    query: str | None = None,
    library: str | None = None,
    function_name: str | None = None,
    tag: str | None = None,
    type: str | None = None,
    source_quality: str | None = None,
    confidence: str | None = None,
    lifecycle: str = "active",
    max_results: int = 25,
    include_chunks: bool = False,
) -> str:
    """Search notes by keyword, library/topic, function, tag, or type.

    library filters by topic/domain. Supports hierarchical matching:
    library='javascript' matches both 'javascript' and 'javascript/json'.
    Also matches notes that list the library in their additional_topics.
    lifecycle='active' (the default) also surfaces evergreen notes.

    include_chunks=True also searches ingested document chunks by embedding
    similarity and returns them in a separate 'chunks' key.

    Returns matching notes ranked by relevance score. max_results defaults to 25;
    pass 0 to return every match -- a vague query can then produce a very large
    response, so only do that with a narrow query or strict filters.
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
            "include_chunks": include_chunks,
        }
        result = search_notes(index, params)
        result_ids = [r["id"] for r in result.get("results", [])]
        for rid in result_ids:
            log_event(rid, "searched", "notemap_search")
        if len(result_ids) >= 2:
            log_co_retrieval(result_ids, "notemap_search")
        if result.get("count", 0) == 0 and (query or function_name):
            log_search_miss(query or function_name)
        return safe_json_dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_update
# ---------------------------------------------------------------------------

@mcp_server.tool(
    meta={"anthropic/searchHint": "update fix note mark reviewed record miss"},
)
def notemap_update(
    id: str,
    cues: dict | None = None,
    notes: str | None = None,
    notes_append: str | None = None,
    summary: str | None = None,
    tags: dict | None = None,
    source_quality: str | None = None,
    confidence: str | None = None,
    lifecycle: str | None = None,
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
    new_library: str | None = None,
    mark_reviewed: bool = False,
    increment_miss: bool = False,
    miss_reason: str | None = None,
) -> str:
    """Update an existing note's fields.

    List/set fields (cues, tags, related_functions, related_notes,
    primitives_to_avoid, preferred_alternatives) accept a dict with
    an "add" and/or "remove" key for incremental updates.

    new_library moves the note to a different library.

    lifecycle accepts: active / stale / evergreen / dormant / archived
    (see models.Lifecycle). Use 'archived' to retire a note that
    documented a now-resolved issue, keeping its history searchable
    via include_archived filters but excluding it from default
    preflight / search results.

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
            "lifecycle":              lifecycle,
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
            "new_library":            new_library,
            "mark_reviewed":          mark_reviewed,
            "increment_miss":         increment_miss,
            "miss_reason":            miss_reason,
        }
        params = {k: v for k, v in params.items() if v is not None}
        result = update_note(index, NOTEMAP_DIR, params)
        if mark_reviewed:
            log_event(id, "reviewed", "notemap_update")
        if increment_miss:
            log_event(id, "missed", "notemap_update")
        return safe_json_dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_delete
# ---------------------------------------------------------------------------

@mcp_server.tool(
    meta={"anthropic/searchHint": "delete remove archive obsolete note"},
)
def notemap_delete(
    id: str,
    reason: str | None = None,
    hard_delete: bool = False,
) -> str:
    """Delete (archive) a note by ID.

    Soft-deletes by default (sets lifecycle to archived). Pass hard_delete=True
    to permanently remove.
    """
    try:
        index = get_index()
        params: dict[str, Any] = {
            "id":          id,
            "reason":      reason,
            "hard_delete": hard_delete,
        }
        result = delete_note(index, NOTEMAP_DIR, params)
        return safe_json_dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_audit
# ---------------------------------------------------------------------------

@mcp_server.tool(
    meta={"anthropic/searchHint": "audit stale orphan leech density health check"},
)
def notemap_audit(
    check: str = "all",
    stale_days: int | None = None,
    library: str | None = None,
    apply_decay: bool = False,
) -> str:
    """Find notes needing attention.

    library filters by topic/domain. Supports hierarchical matching.

    Checks: stale, low_confidence, unreviewed, high_miss_count,
    orphaned_functions, index_integrity, source_changed, density,
    consolidation, confidence_decay, or all.

    apply_decay: when True and check includes confidence_decay, mutates
    notes in the database to apply the suggested confidence downgrades.
    """
    try:
        index = get_index()
        params: dict[str, Any] = {
            "check":       check,
            "stale_days":  stale_days,
            "library":     library,
            "apply_decay": apply_decay,
        }
        result = audit_notes(index, NOTEMAP_DIR, params)
        return safe_json_dumps(cap_result_lists(result), indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_review
# ---------------------------------------------------------------------------

@mcp_server.tool(
    meta={"anthropic/searchHint": "review queue prioritized stale notes due"},
)
def notemap_review(
    library: str | None = None,
    limit: int = 25,
) -> str:
    """Get a prioritized review queue.

    library filters by topic/domain. Supports hierarchical matching.

    Returns notes most in need of review, ranked by staleness, miss count,
    and confidence level. limit defaults to 25; pass 0 to return the whole queue.
    """
    try:
        index = get_index()
        params: dict[str, Any] = {
            "library": library,
            "limit":   limit,
        }
        result = review_queue(index, params)
        return safe_json_dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_lint
# ---------------------------------------------------------------------------

@mcp_server.tool(
    meta={"anthropic/searchHint": "lint code anti-pattern scan check quick"},
)
def notemap_lint(
    code: str,
    library: str | None = None,
) -> str:
    """Check code against known anti-patterns from notes.

    library filters by topic/domain. Supports hierarchical matching.

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
        return safe_json_dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_stats
# ---------------------------------------------------------------------------

@mcp_server.tool(
    meta={
        "anthropic/alwaysLoad": True,
        "anthropic/searchHint": "stats overview knowledge base note count libraries health",
    },
)
def notemap_stats(verbose: bool = False) -> str:
    """Get an overview of the notemap knowledge base.

    Returns: total note count, libraries/topics with note counts,
    note type breakdown, and overall health indicators.
    Use this at session start to discover what topics have notes.

    verbose=False (default) keeps the response small: the per-library x per-type
    coverage matrix is omitted and the libraries list is capped to the 30
    largest. Pass verbose=True for the full matrix and every library.
    """
    try:
        index = get_index()

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

        backlinks = get_backlink_index()
        total_notes = len(index)
        notes_with_links = 0
        total_links = 0

        for nid, entry in index.items():
            related = entry.get("related_notes") or []
            incoming = backlinks.get(nid) or []
            link_count = len(related) + len(incoming)
            if link_count > 0:
                notes_with_links += 1
            total_links += len(related)

        # Health metrics: utilization from events table
        retrieved_note_ids: set[str] = set()
        try:
            conn = get_db(NOTEMAP_DIR)
            from datetime import datetime, timedelta, timezone
            cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
            rows = conn.execute("""
                SELECT DISTINCT note_id FROM events
                WHERE timestamp >= ? AND event IN ('searched', 'check_surfaced', 'preflight_loaded')
                AND note_id != ''
            """, (cutoff,)).fetchall()
            retrieved_note_ids = {r["note_id"] for r in rows}
        except Exception:
            pass

        utilization_rate = len(retrieved_note_ids) / total_notes if total_notes > 0 else 0.0

        # Per-library x per-type coverage matrix -- only built when requested;
        # for ~140 libraries it's the bulk of the response.
        coverage: dict[str, dict[str, int]] = {}
        if verbose:
            for nid, entry in index.items():
                lib = entry.get("library", "unknown")
                ntype = entry.get("type", "knowledge")
                coverage.setdefault(lib, {})
                coverage[lib][ntype] = coverage[lib].get(ntype, 0) + 1

        from datetime import date as _date_type
        review_backlog = 0
        tier_sum       = 0
        tier_count     = 0
        for nid, entry in index.items():
            if entry.get("lifecycle") not in ("active",):
                continue
            tier = entry.get("review_tier", 2)
            tier_sum += tier
            tier_count += 1
            last_reviewed = entry.get("last_reviewed", "")
            interval = entry.get("review_interval_days", 30)
            if last_reviewed:
                try:
                    reviewed = _date_type.fromisoformat(last_reviewed)
                    if (_date_type.today() - reviewed).days > interval:
                        review_backlog += 1
                except (ValueError, TypeError):
                    pass

        # Embedding statistics
        notes_with_embeddings = 0
        chunks_with_embeddings = 0
        total_chunks = 0
        try:
            conn_stats = get_db(NOTEMAP_DIR)
            ne_row = conn_stats.execute("SELECT COUNT(*) as cnt FROM note_embeddings").fetchone()
            notes_with_embeddings = ne_row["cnt"] if ne_row else 0
            ce_row = conn_stats.execute("SELECT COUNT(*) as cnt FROM chunk_embeddings").fetchone()
            chunks_with_embeddings = ce_row["cnt"] if ce_row else 0
            tc_row = conn_stats.execute("SELECT COUNT(*) as cnt FROM chunks").fetchone()
            total_chunks = tc_row["cnt"] if tc_row else 0
        except Exception:
            pass

        libs_sorted = sorted(libs.items(), key=lambda x: -x[1])
        if verbose or len(libs_sorted) <= 30:
            libraries_out: dict[str, Any] = dict(libs_sorted)
        else:
            libraries_out = dict(libs_sorted[:30])
            libraries_out["_truncated"] = True
            libraries_out["_total_libraries"] = len(libs_sorted)
            libraries_out["_note"] = "showing the 30 largest libraries -- pass verbose=True for all"

        health: dict[str, Any] = {
            "utilization_rate_90d": round(utilization_rate, 3),
            "notes_retrieved_90d":  len(retrieved_note_ids),
            "review_backlog":       review_backlog,
            "avg_review_tier":      round(tier_sum / tier_count, 2) if tier_count > 0 else 0,
        }
        if verbose:
            health["coverage_matrix"] = coverage

        result = {
            "version": __version__,
            "total_notes": total_notes,
            "libraries": libraries_out,
            "note_types": types,
            "stale_notes": stale_count,
            "low_confidence_notes": low_conf_count,
            "connection_stats": {
                "notes_with_links": notes_with_links,
                "total_links": total_links,
                "avg_links_per_note": round(total_links / max(total_notes, 1), 2),
                "orphan_count": total_notes - notes_with_links,
            },
            "health": health,
            "embeddings": {
                "available": EMBEDDINGS_AVAILABLE,
                "model": MODEL_NAME if EMBEDDINGS_AVAILABLE else None,
                "notes_with_embeddings": notes_with_embeddings,
                "chunks_with_embeddings": chunks_with_embeddings,
                "total_notes": total_notes,
                "total_chunks": total_chunks,
            },
        }
        return safe_json_dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_preflight
# ---------------------------------------------------------------------------

@mcp_server.tool(
    meta={
        "anthropic/alwaysLoad": True,
        "anthropic/searchHint": "session start load gotchas anti-patterns preflight libraries",
    },
)
def notemap_preflight(
    libraries: list[str],
    versions: dict | None = None,
    include_cross_cutting: bool = True,
    context_budget: int = 12000,
    topic_focus: str = "",
) -> str:
    """Load all notes for the specified libraries/topics in a compact briefing format.

    Call this at session start or when switching to a new task domain.
    libraries is a list of topic/domain names to load notes for.
    Also includes notes that list any requested library in their additional_topics.

    Returns all notes organized by priority: anti-patterns first, then
    corrections, knowledge, and conventions, grouped by library.

    include_cross_cutting=True (default) also includes notes from the
    _cross-cutting library, which apply regardless of specific library.

    versions is an optional dict mapping library names to version strings
    (e.g., {"zendb": "3.0", "smartstring": "2.8"}). When provided, notes
    with incompatible library_version fields are excluded.

    context_budget is the max token budget for the response, default 12000.
    Notes are assigned detail levels (0-3) to fit within it; anti-patterns
    always get full detail, others are ranked by relevance. Pass 0 for no limit
    -- with many in-scope notes that can produce a very large response.

    topic_focus is an optional string describing the current task focus.
    When set and embeddings are available, uses semantic similarity to
    prioritize the most relevant notes within the budget.
    """
    try:
        index = get_index()
        params: dict[str, Any] = {
            "libraries":             libraries,
            "versions":              versions,
            "include_cross_cutting": include_cross_cutting,
            "context_budget":        context_budget,
            "topic_focus":           topic_focus,
        }
        result = preflight_notes(index, params)
        for tier_name in ("watch_out", "know_this", "reference"):
            for note in result.get("tiers", {}).get(tier_name, []):
                log_event(note.get("id", ""), "preflight_loaded", "notemap_preflight")
        return safe_json_dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_check
# ---------------------------------------------------------------------------

@mcp_server.tool(
    meta={
        "anthropic/alwaysLoad": True,
        "anthropic/searchHint": "check code after edit lint anti-pattern function gotcha",
    },
)
def notemap_check(
    code: str = "",
    file_path: str | None = None,
    versions: dict | None = None,
) -> str:
    """Check code against notemap knowledge: anti-patterns, function gotchas,
    and cross-cutting notes.

    Auto-detects libraries/topics from code patterns (DB::, SmartString, etc.)
    and file extension. Runs lint + function-specific note lookup in one call.
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
        for w in result.get("lint_warnings", []):
            log_event(w.get("note_id", ""), "check_warning", "notemap_check")
        check_note_ids: list[str] = []
        for fn in result.get("function_notes", []):
            for n in fn.get("notes", []):
                nid = n.get("id", "")
                log_event(nid, "check_surfaced", "notemap_check")
                if nid:
                    check_note_ids.append(nid)
        if len(check_note_ids) >= 2:
            log_co_retrieval(check_note_ids, "notemap_check")
        return safe_json_dumps(result, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_connections
# ---------------------------------------------------------------------------

@mcp_server.tool(
    meta={"anthropic/searchHint": "knowledge graph connections neighbors path communities pagerank"},
)
def notemap_connections(
    note_id: str | None = None,
    operation: str = "neighborhood",
    target_id: str | None = None,
    max_hops: int = 2,
) -> str:
    """Query the knowledge graph for connections, paths, and suggestions.

    Operations:
        neighborhood  - show notes connected to note_id within max_hops
        path          - find shortest path from note_id to target_id
        suggest_links - suggest new related_notes for note_id
        suggest_hubs  - find libraries that need hub/structure notes
        pagerank      - show top notes by PageRank importance
        communities   - show detected note communities
        bridges       - show top notes by betweenness centrality
    """
    try:
        index = get_index()
        backlinks = get_backlink_index()

        from graph import (
            betweenness_centrality,
            get_neighborhood,
            louvain_communities,
            pagerank,
            shortest_path,
            suggest_hub_notes,
        )

        if operation == "neighborhood":
            if not note_id:
                return safe_json_dumps({"error": "note_id required for neighborhood"})
            result = get_neighborhood(index, backlinks, note_id, max_hops)
            return safe_json_dumps({"note_id": note_id, "neighborhood": result, "count": len(result)}, indent=2)

        elif operation == "path":
            if not note_id or not target_id:
                return safe_json_dumps({"error": "note_id and target_id required for path"})
            path = shortest_path(index, backlinks, note_id, target_id)
            if path:
                return safe_json_dumps({"from": note_id, "to": target_id, "path": path, "hops": len(path) - 1}, indent=2)
            return safe_json_dumps({"from": note_id, "to": target_id, "path": None, "message": "No path found"}, indent=2)

        elif operation == "suggest_hubs":
            suggestions = suggest_hub_notes(index, backlinks)
            return safe_json_dumps({"suggestions": suggestions, "count": len(suggestions)}, indent=2)

        elif operation == "pagerank":
            scores = pagerank(index, backlinks)
            top = sorted(scores.items(), key=lambda x: -x[1])[:20]
            return safe_json_dumps({
                "top_notes": [
                    {"id": nid, "score": round(s, 6), "topic": index.get(nid, {}).get("topic", "")}
                    for nid, s in top
                ],
            }, indent=2)

        elif operation == "communities":
            comms = louvain_communities(index, backlinks)
            groups: dict[int, list[str]] = {}
            for nid, c in comms.items():
                groups.setdefault(c, []).append(nid)
            sorted_groups = sorted(groups.items(), key=lambda x: -len(x[1]))
            result_groups = []
            for comm_id, members in sorted_groups[:20]:
                result_groups.append({
                    "community": comm_id,
                    "size": len(members),
                    "members": members[:10],
                    "sample_topics": [index.get(m, {}).get("topic", "")[:60] for m in members[:5]],
                })
            return safe_json_dumps({"communities": result_groups, "total_communities": len(groups)}, indent=2)

        elif operation == "bridges":
            scores = betweenness_centrality(index, backlinks)
            top = sorted(scores.items(), key=lambda x: -x[1])[:20]
            return safe_json_dumps({
                "top_bridges": [
                    {"id": nid, "centrality": round(s, 6), "topic": index.get(nid, {}).get("topic", "")}
                    for nid, s in top
                ],
            }, indent=2)

        elif operation == "suggest_links":
            if not note_id or note_id not in index:
                return safe_json_dumps({"error": "valid note_id required"})
            entry = index[note_id]
            topic_words = set(w.lower() for w in (entry.get("topic") or "").split() if len(w) >= 3)
            note_tags = set(t.lower() for t in (entry.get("tags") or []))
            note_fns = set(f.lower() for f in (entry.get("related_functions") or []))

            suggestions: list[dict[str, Any]] = []
            for eid, e in index.items():
                if eid == note_id:
                    continue
                score = 0
                reasons: list[str] = []
                ex_fns = set(f.lower() for f in (e.get("related_functions") or []))
                shared = note_fns & ex_fns
                if shared:
                    score += len(shared) * 40
                    reasons.append(f"shared functions: {', '.join(sorted(shared))}")
                ex_tw = set(w.lower() for w in (e.get("topic") or "").split() if len(w) >= 3)
                sw = topic_words & ex_tw
                if len(sw) >= 2:
                    score += len(sw) * 10
                    reasons.append("topic overlap")
                ex_tags = set(t.lower() for t in (e.get("tags") or []))
                st = note_tags & ex_tags
                if st:
                    score += len(st) * 15
                    reasons.append(f"shared tags: {', '.join(sorted(st))}")
                if score >= 30:
                    suggestions.append({"id": eid, "score": score, "reasons": reasons, "topic": e.get("topic", "")})

            suggestions.sort(key=lambda x: -x["score"])
            return safe_json_dumps({"note_id": note_id, "suggestions": suggestions[:10]}, indent=2)

        else:
            return safe_json_dumps({"error": f"Unknown operation: {operation}. Valid: neighborhood, path, suggest_links, suggest_hubs, pagerank, communities, bridges"})

    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_ingest
# ---------------------------------------------------------------------------

@mcp_server.tool(
    meta={"anthropic/searchHint": "ingest chunk embed text document content semantic search"},
)
def notemap_ingest(
    content: str,
    library: str,
    source_type: str = "text",
    source_path: str = "",
    source_title: str = "",
) -> str:
    """Ingest text content by chunking, embedding, and storing for retrieval.

    Use this after reading a PDF/document to store the raw text as searchable
    chunks. Chunks are automatically embedded for semantic search.
    """
    try:
        try:
            from chunk import chunk_with_sections, store_chunks
        except ImportError:
            return _error_response(
                "Chunking module not available",
                "chunk.py is required for ingestion",
            )

        get_index()  # ensure DB + events initialized

        chunks = chunk_with_sections(content, source_type, source_path, source_title)
        if not chunks:
            return safe_json_dumps({
                "chunks_created": 0,
                "source": source_path,
                "library": library,
                "message": "No chunks produced from content (empty or whitespace-only)",
            }, indent=2)

        conn = get_db(NOTEMAP_DIR)
        chunk_ids = store_chunks(chunks, conn)

        log_event(
            note_id="",
            event_type="ingestion_complete",
            tool="notemap_ingest",
            metadata={
                "source": source_path,
                "source_title": source_title,
                "library": library,
                "chunks_created": len(chunk_ids),
                "source_type": source_type,
            },
        )

        return safe_json_dumps({
            "chunks_created": len(chunk_ids),
            "source": source_path,
            "library": library,
            "message": f"Ingested {len(chunk_ids)} chunk(s) from '{source_title or source_path or 'inline text'}'",
        }, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Tool: notemap_embed
# ---------------------------------------------------------------------------

@mcp_server.tool(
    meta={"anthropic/searchHint": "generate refresh embeddings batch vector search"},
)
def notemap_embed(
    force: bool = False,
) -> str:
    """Generate embeddings for all notes that lack them.

    Use force=True to re-embed all notes (e.g., after model upgrade).
    Returns a count of notes embedded and the model used.
    """
    try:
        if not EMBEDDINGS_AVAILABLE or encode_text is None:
            return safe_json_dumps({
                "embedded": 0,
                "total_notes": len(get_index()),
                "model": None,
                "available": False,
                "message": "Embeddings not available. Install model2vec: pip install model2vec",
            }, indent=2)

        index = get_index()
        conn = get_db(NOTEMAP_DIR)

        if force:
            rows = conn.execute(
                "SELECT id, topic, summary, notes_body FROM notes"
            ).fetchall()
        else:
            rows = conn.execute("""
                SELECT n.id, n.topic, n.summary, n.notes_body
                FROM notes n
                LEFT JOIN note_embeddings ne ON ne.note_id = n.id
                WHERE ne.vector IS NULL
            """).fetchall()

        embedded = 0
        for row in rows:
            embed_text = f"{row['topic']} {row['summary']} {row['notes_body']}"
            vec_bytes = encode_text(embed_text)
            if vec_bytes is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO note_embeddings (note_id, model, dimensions, vector) VALUES (?, ?, ?, ?)",
                    (row["id"], MODEL_NAME, DIMENSIONS, vec_bytes),
                )
                embedded += 1

        conn.commit()
        if invalidate_cache and embedded > 0:
            invalidate_cache()

        total_notes = len(index)
        return safe_json_dumps({
            "embedded": embedded,
            "total_notes": total_notes,
            "model": MODEL_NAME,
            "available": True,
            "message": f"Embedded {embedded} note(s) using {MODEL_NAME}",
        }, indent=2)
    except Exception as exc:
        return _error_response(str(exc), traceback.format_exc())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp_server.run(transport="stdio")
