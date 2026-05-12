"""Preflight note loading for session-start library context.

Given a list of libraries the project uses, returns all active notes
organized into priority tiers with a function index and compliance summary.
Designed to be called once at session start so Claude has the full knowledge base
for in-scope libraries loaded before writing any code.
"""
from __future__ import annotations

import json
import re
from typing import Any

from utils import estimate_tokens

try:
    from embed import EMBEDDINGS_AVAILABLE, load_embedding_matrix, vector_search as _vector_search
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    load_embedding_matrix = None
    _vector_search = None


# ---------------------------------------------------------------------------
# Version compatibility
# ---------------------------------------------------------------------------

# Matches an optional operator prefix followed by a dotted version number.
# Groups: (1) operator or empty string, (2) version digits string.
_VERSION_RE = re.compile(r"^([><=!]{0,2})(\d[\d.]*)$")


def _parse_version_tuple(version_str: str) -> tuple[int, ...]:
    """Split a dotted version string into a tuple of ints.

    Ignores trailing non-numeric segments (e.g. "1.2.3-beta" -> (1, 2, 3)).
    Returns an empty tuple for blank/unparseable input.
    """
    if not version_str:
        return ()
    parts: list[int] = []
    for segment in version_str.split("."):
        # Strip non-digit suffixes like "3-beta"
        digits = ""
        for ch in segment:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            parts.append(int(digits))
    return tuple(parts)


def _check_version_compat(note_version_spec: str, project_version: str) -> bool:
    """Determine whether a note applies to the given project version.

    Rules:
        - Empty/missing spec: always compatible.
        - ">=X.Y.Z": project version >= X.Y.Z
        - ">X.Y.Z":  project version >  X.Y.Z
        - "<=X.Y.Z": project version <= X.Y.Z
        - "<X.Y.Z":  project version <  X.Y.Z
        - "X.Y.Z" (no operator): match on major.minor only.

    Comparison uses tuple ordering on integer segments.
    """
    spec = (note_version_spec or "").strip()
    if not spec:
        return True

    proj = (project_version or "").strip()
    if not proj:
        # No project version to compare against -- include the note
        return True

    match = _VERSION_RE.match(spec)
    if not match:
        # Unparseable spec -- be lenient, include the note
        return True

    operator = match.group(1)
    spec_ver = _parse_version_tuple(match.group(2))
    proj_ver = _parse_version_tuple(proj)

    if not spec_ver or not proj_ver:
        return True

    if operator == ">=":
        return proj_ver >= spec_ver
    if operator == ">":
        return proj_ver > spec_ver
    if operator == "<=":
        return proj_ver <= spec_ver
    if operator == "<":
        return proj_ver < spec_ver

    # No operator -- exact major.minor match
    spec_major_minor = spec_ver[:2]
    proj_major_minor = proj_ver[:2]
    return proj_major_minor == spec_major_minor


# ---------------------------------------------------------------------------
# Tier routing
# ---------------------------------------------------------------------------

# Maps note types to their output tier.
_TIER_WATCH_OUT = {"anti-pattern", "correction"}
_TIER_KNOW_THIS = {"knowledge", "technique", "convention", "requirement"}
_TIER_REFERENCE = {"reference", "decision", "finding", "communication", "commitment"}

# All recognized note types (union of all tiers).
_ALL_TYPES = _TIER_WATCH_OUT | _TIER_KNOW_THIS | _TIER_REFERENCE


def _tier_for_type(note_type: str) -> str:
    """Return the tier name for a given note type.

    Unrecognized types default to "reference" so they still appear.
    """
    if note_type in _TIER_WATCH_OUT:
        return "watch_out"
    if note_type in _TIER_KNOW_THIS:
        return "know_this"
    return "reference"


def _build_tier_entry(note_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Build the per-note dict for a tier list.

    Anti-patterns and corrections get type-specific fields; all other
    types share a common shape with type + top_cue.  Every entry
    includes the ``type`` field.
    """
    note_type = entry.get("type", "knowledge")

    # Common quality fields included on all tier entries for ranking
    quality_fields = {
        "confidence":     entry.get("confidence", "maybe"),
        "source_quality": entry.get("source_quality", "unverified"),
    }

    if note_type == "anti-pattern":
        return {
            "id":                     note_id,
            "type":                   note_type,
            "library":                entry.get("library", ""),
            "summary":                entry.get("summary", ""),
            "primitives_to_avoid":    entry.get("primitives_to_avoid", []),
            "preferred_alternatives": entry.get("preferred_alternatives", []),
            "related_functions":      entry.get("related_functions", []),
            **quality_fields,
        }

    if note_type == "correction":
        return {
            "id":                note_id,
            "type":              note_type,
            "library":           entry.get("library", ""),
            "summary":           entry.get("summary", ""),
            "wrong_assumption":  entry.get("wrong_assumption", ""),
            "correct_behavior":  entry.get("correct_behavior", ""),
            "related_functions": entry.get("related_functions", []),
            **quality_fields,
        }

    # All other types: knowledge, technique, convention, reference,
    # decision, finding -- and any future/unrecognized types.
    cues = entry.get("cues") or []
    return {
        "id":                note_id,
        "type":              note_type,
        "library":           entry.get("library", ""),
        "summary":           entry.get("summary", ""),
        "related_functions": entry.get("related_functions", []),
        "top_cue":           cues[0] if cues else "",
        **quality_fields,
    }


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def _library_matches(note_library: str, filter_libraries: list[str]) -> bool:
    """Check if *note_library* matches any entry in *filter_libraries*.

    Supports hierarchical matching: ``"javascript"`` in the filter list
    matches both ``"javascript"`` (exact) and ``"javascript/json"`` (child).
    """
    for lib in filter_libraries:
        if note_library == lib or note_library.startswith(lib + "/"):
            return True
    return False


def preflight_notes(
    index: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Load all active notes for the given libraries, organized for session start.

    Params:
        libraries (list[str]):          Library names to load notes for.
        versions (dict|None):           Optional map of library name to version
                                        string.  Used to exclude notes whose
                                        library_version spec is incompatible.
        include_cross_cutting (bool):   Include "_cross-cutting" library notes.
                                        Defaults to True.
        context_budget (int):           Max tokens for output (0 = unlimited).
                                        When set, notes are assigned detail
                                        levels to fit within the budget.
        topic_focus (str):              Optional topic focus string. When set
                                        and embeddings are available, uses
                                        semantic similarity to reorder notes.

    Returns a dict with:
        tiers:          dict with watch_out, know_this, reference lists
        function_index: map of function name -> list of note IDs
        summary:        overview counts and compliance string
    """
    libraries: list[str]         = list(params.get("libraries") or [])
    versions: dict[str, str]     = dict(params.get("versions") or {})
    include_cross_cutting: bool  = params.get("include_cross_cutting", True)
    context_budget: int          = int(params.get("context_budget") or 0)
    topic_focus: str             = str(params.get("topic_focus") or "")

    if include_cross_cutting and "_cross-cutting" not in libraries:
        libraries.append("_cross-cutting")

    # -- Filter index entries ------------------------------------------------

    filtered: list[tuple[str, dict[str, Any]]] = []
    seen_ids: set[str] = set()

    for note_id, entry in index.items():
        # Must belong to a requested library (supports hierarchy: "js" matches "js/json")
        # Also checks additional_topics for multi-topic membership
        main_lib = entry.get("library", "")
        additional = entry.get("additional_topics") or []
        if not _library_matches(main_lib, libraries) and not any(_library_matches(t, libraries) for t in additional):
            continue

        # Must be active or evergreen (dormant/archived excluded)
        if entry.get("lifecycle") not in ("active", "evergreen"):
            continue

        # Version compatibility check
        note_lib = entry.get("library", "")
        note_ver_spec = entry.get("library_version", "")
        if note_ver_spec and note_lib in versions:
            if not _check_version_compat(note_ver_spec, versions[note_lib]):
                continue

        filtered.append((note_id, entry))
        seen_ids.add(note_id)

    # Include always-relevant notes from any library
    for note_id, entry in index.items():
        if entry.get("always_relevant") and note_id not in seen_ids:
            if entry.get("lifecycle") not in ("active", "evergreen"):
                continue
            # Version filtering still applies if versions provided
            note_lib = entry.get("library", "")
            note_ver_spec = entry.get("library_version", "")
            if note_ver_spec and note_lib in versions:
                if not _check_version_compat(note_ver_spec, versions[note_lib]):
                    continue
            filtered.append((note_id, entry))

    # -- Organize into priority tiers ----------------------------------------

    tiers: dict[str, list[dict[str, Any]]] = {
        "watch_out": [],
        "know_this": [],
        "reference": [],
    }

    for note_id, entry in filtered:
        note_type = entry.get("type", "knowledge")
        tier_name = _tier_for_type(note_type)
        tiers[tier_name].append(_build_tier_entry(note_id, entry))

    # Quality-rank within each tier
    def _quality_score(note_entry: dict[str, Any]) -> float:
        """Compute quality score for ranking within a tier."""
        conf = {"strong": 1.0, "maybe": 0.7, "weak": 0.4}.get(
            note_entry.get("confidence", "maybe"), 0.7
        )
        qual = {
            "verified-from-source": 1.0, "runtime-tested": 0.85,
            "documented": 0.7, "function-map": 0.6,
            "user-correction": 0.55, "inferred": 0.4, "unverified": 0.3,
        }.get(note_entry.get("source_quality", "unverified"), 0.3)
        return conf * 0.5 + qual * 0.5

    for tier_name in tiers:
        tiers[tier_name].sort(key=lambda n: _quality_score(n), reverse=True)

    # -- Generate per-library summaries for large collections (RAPTOR) -------

    lib_note_counts: dict[str, int] = {}
    for tier_name in tiers:
        for note in tiers[tier_name]:
            lib = note.get("library", "")
            lib_note_counts[lib] = lib_note_counts.get(lib, 0) + 1

    library_summaries: dict[str, str] = {}
    for lib, count in lib_note_counts.items():
        if count >= 15:
            # Collect anti-pattern summaries for this library
            ap_summaries: list[str] = []
            for note in tiers.get("watch_out", []):
                if note.get("library") == lib:
                    s = note.get("summary", "")
                    if s:
                        ap_summaries.append(s)
            if ap_summaries:
                library_summaries[lib] = (
                    f"Key gotchas for {lib} ({count} notes): "
                    + "; ".join(ap_summaries[:5])
                )

    # -- Build function index ------------------------------------------------

    function_index: dict[str, list[str]] = {}

    for note_id, entry in filtered:
        for fn_name in (entry.get("related_functions") or []):
            if fn_name not in function_index:
                function_index[fn_name] = []
            function_index[fn_name].append(note_id)

    # -- Build summary -------------------------------------------------------

    total_notes = len(filtered)

    # Count notes per library (excluding empty library names)
    lib_counts: dict[str, int] = {}
    for _, entry in filtered:
        lib = entry.get("library", "")
        if lib:
            lib_counts[lib] = lib_counts.get(lib, 0) + 1
    libraries_loaded = sorted(lib_counts.keys())

    # Count every recognized type (including those with zero notes)
    type_counts: dict[str, int] = {t: 0 for t in sorted(_ALL_TYPES)}
    for _, entry in filtered:
        t = entry.get("type", "knowledge")
        type_counts[t] = type_counts.get(t, 0) + 1

    # Compliance string: "zendb/5, claude/12 -- 2 anti-patterns, 1 correction"
    lib_parts = [f"{lib}/{lib_counts[lib]}" for lib in libraries_loaded]
    compliance_parts = ", ".join(lib_parts) if lib_parts else "no notes"

    type_highlights: list[str] = []
    if type_counts.get("anti-pattern"):
        n = type_counts["anti-pattern"]
        type_highlights.append(f"{n} anti-pattern{'s' if n != 1 else ''}")
    if type_counts.get("correction"):
        n = type_counts["correction"]
        type_highlights.append(f"{n} correction{'s' if n != 1 else ''}")

    if type_highlights:
        compliance = f"{compliance_parts} -- {', '.join(type_highlights)}"
    else:
        compliance = compliance_parts

    summary = {
        "total_notes":      total_notes,
        "libraries_loaded": libraries_loaded,
        "by_type":          type_counts,
        "compliance":       compliance,
    }

    result: dict[str, Any] = {
        "tiers":          tiers,
        "function_index": function_index,
        "summary":        summary,
    }
    if library_summaries:
        result["library_summaries"] = library_summaries

    # -- Context budgeting (when context_budget > 0) -------------------------

    if context_budget > 0:
        result = _apply_context_budget(result, filtered, context_budget, topic_focus)

    return result


# ---------------------------------------------------------------------------
# Context budgeting helpers
# ---------------------------------------------------------------------------

# Detail levels:
#   0 = index only (id + type + library)
#   1 = brief (id + type + library + summary)
#   2 = standard (id + type + library + summary + top_cue + related_functions)
#   3 = full (everything, as currently returned)

_DETAIL_LEVEL_TOKENS = {
    0: 15,   # ~15 tokens for id/type/library
    1: 40,   # ~40 tokens adds summary
    2: 80,   # ~80 tokens adds cue + functions
    3: 150,  # ~150 tokens full entry (varies, this is average)
}

# When topic_focus is active, watch_out notes below this similarity threshold
# get reduced detail (level 1 instead of 3).  Notes at or above stay full.
WATCH_OUT_SIMILARITY_THRESHOLD = 0.3


def _estimate_note_tokens(note: dict[str, Any], level: int) -> int:
    """Estimate token cost for a note at a given detail level."""
    if level <= 0:
        return _DETAIL_LEVEL_TOKENS[0]
    if level == 1:
        return _DETAIL_LEVEL_TOKENS[1] + estimate_tokens(note.get("summary", ""))
    if level == 2:
        return (_DETAIL_LEVEL_TOKENS[2]
                + estimate_tokens(note.get("summary", ""))
                + estimate_tokens(note.get("top_cue", "")))
    # level 3
    text = json.dumps(note, default=str)
    return estimate_tokens(text)


def _trim_note_to_level(note: dict[str, Any], level: int) -> dict[str, Any]:
    """Return a copy of a note dict trimmed to the given detail level."""
    if level >= 3:
        note["detail_level"] = 3
        return note

    if level <= 0:
        return {
            "id": note.get("id", ""),
            "type": note.get("type", ""),
            "library": note.get("library", ""),
            "detail_level": 0,
        }
    if level == 1:
        return {
            "id": note.get("id", ""),
            "type": note.get("type", ""),
            "library": note.get("library", ""),
            "summary": note.get("summary", ""),
            "detail_level": 1,
        }
    # level 2
    return {
        "id": note.get("id", ""),
        "type": note.get("type", ""),
        "library": note.get("library", ""),
        "summary": note.get("summary", ""),
        "related_functions": note.get("related_functions", []),
        "top_cue": note.get("top_cue", ""),
        "confidence": note.get("confidence", ""),
        "source_quality": note.get("source_quality", ""),
        "detail_level": 2,
    }


def _apply_context_budget(
    result: dict[str, Any],
    filtered: list[tuple[str, dict[str, Any]]],
    budget: int,
    topic_focus: str,
) -> dict[str, Any]:
    """Apply context budget constraints to the preflight result.

    Assigns detail levels to notes to fit within the token budget.
    Anti-patterns always get full detail. Other notes are ranked by
    relevance (optionally boosted by embedding similarity to topic_focus)
    and assigned decreasing detail levels as the budget fills.
    """
    tiers = result["tiers"]

    # Build a flat list of all notes with their tier for priority ordering
    # Priority: watch_out (anti-patterns/corrections) > know_this > reference
    priority_order = []
    for note in tiers.get("watch_out", []):
        priority_order.append(("watch_out", note))
    for note in tiers.get("know_this", []):
        priority_order.append(("know_this", note))
    for note in tiers.get("reference", []):
        priority_order.append(("reference", note))

    # If topic_focus is set and embeddings are available, compute similarity scores
    similarity_scores: dict[str, float] = {}
    if topic_focus and EMBEDDINGS_AVAILABLE and _vector_search is not None and load_embedding_matrix is not None:
        try:
            from db import get_db
            from pathlib import Path
            notemap_dir = Path.home() / ".claude" / "notemap"
            conn = get_db(notemap_dir)
            matrix_result = load_embedding_matrix(conn)
            if matrix_result is not None:
                note_ids, matrix = matrix_result
                vs_results = _vector_search(topic_focus, note_ids, matrix, top_k=len(note_ids))
                for nid, score in vs_results:
                    similarity_scores[nid] = score
        except Exception:
            pass

    # Reorder notes by similarity if we have scores
    if similarity_scores:
        watch_out_notes = [(t, n) for t, n in priority_order if t == "watch_out"]
        # Sort watch_out by similarity (highest first) so most relevant lead
        watch_out_notes.sort(
            key=lambda x: similarity_scores.get(x[1].get("id", ""), 0.0),
            reverse=True,
        )
        other_notes = [(t, n) for t, n in priority_order if t != "watch_out"]
        other_notes.sort(
            key=lambda x: similarity_scores.get(x[1].get("id", ""), 0.0),
            reverse=True,
        )
        priority_order = watch_out_notes + other_notes

    # Assign detail levels within budget
    tokens_used = 0
    expandable_count = 0

    for i, (tier_name, note) in enumerate(priority_order):
        # Watch_out notes: full detail unless topic_focus reduced low-relevance ones
        if tier_name == "watch_out":
            if similarity_scores:
                sim = similarity_scores.get(note.get("id", ""), 0.0)
                level = 3 if sim >= WATCH_OUT_SIMILARITY_THRESHOLD else 1
            else:
                level = 3
        elif tokens_used < budget * 0.5:
            level = 3  # First half of budget: full detail
        elif tokens_used < budget * 0.75:
            level = 2  # Next quarter: standard
        elif tokens_used < budget * 0.9:
            level = 1  # Next 15%: brief
        else:
            level = 0  # Remainder: index only

        note_tokens = _estimate_note_tokens(note, level)

        # If adding this note would exceed budget, reduce level
        # Skip budget reduction for watch_out notes at full detail (level 3),
        # but allow it for watch_out notes already reduced by topic_focus
        if tokens_used + note_tokens > budget and not (tier_name == "watch_out" and level == 3):
            for try_level in (level - 1, level - 2, level - 3):
                if try_level < 0:
                    try_level = 0
                note_tokens = _estimate_note_tokens(note, try_level)
                if tokens_used + note_tokens <= budget:
                    level = try_level
                    break
            else:
                level = 0
                note_tokens = _estimate_note_tokens(note, 0)

        tokens_used += note_tokens
        if level < 3:
            expandable_count += 1
        priority_order[i] = (tier_name, _trim_note_to_level(note, level))

    # Rebuild tiers from the reordered/trimmed list
    new_tiers: dict[str, list[dict[str, Any]]] = {
        "watch_out": [],
        "know_this": [],
        "reference": [],
    }
    for tier_name, note in priority_order:
        new_tiers[tier_name].append(note)

    result["tiers"] = new_tiers
    result["tokens_used"] = tokens_used
    result["expandable_count"] = expandable_count
    result["summary"]["context_budget"] = budget

    return result
