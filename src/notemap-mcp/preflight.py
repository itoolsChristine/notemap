"""Preflight note loading for session-start library context.

Given a list of libraries the project uses, returns all active notes
organized into priority tiers with a function index and compliance summary.
Designed to be called once at session start so Claude has the full knowledge base
for in-scope libraries loaded before writing any code.
"""
from __future__ import annotations

import re
from typing import Any


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
_TIER_KNOW_THIS = {"knowledge", "technique", "convention"}
_TIER_REFERENCE = {"reference", "decision", "finding"}

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

    if note_type == "anti-pattern":
        return {
            "id":                     note_id,
            "type":                   note_type,
            "library":                entry.get("library", ""),
            "summary":                entry.get("summary", ""),
            "primitives_to_avoid":    entry.get("primitives_to_avoid", []),
            "preferred_alternatives": entry.get("preferred_alternatives", []),
            "related_functions":      entry.get("related_functions", []),
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
    }


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

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

    Returns a dict with:
        tiers:          dict with watch_out, know_this, reference lists
        function_index: map of function name -> list of note IDs
        summary:        overview counts and compliance string
    """
    libraries: list[str]         = list(params.get("libraries") or [])
    versions: dict[str, str]     = dict(params.get("versions") or {})
    include_cross_cutting: bool  = params.get("include_cross_cutting", True)

    if include_cross_cutting and "_cross-cutting" not in libraries:
        libraries.append("_cross-cutting")

    # -- Filter index entries ------------------------------------------------

    filtered: list[tuple[str, dict[str, Any]]] = []

    for note_id, entry in index.items():
        # Must belong to a requested library
        if entry.get("library") not in libraries:
            continue

        # Must be active
        if entry.get("lifecycle") != "active":
            continue

        # Version compatibility check
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

    return {
        "tiers":          tiers,
        "function_index": function_index,
        "summary":        summary,
    }
