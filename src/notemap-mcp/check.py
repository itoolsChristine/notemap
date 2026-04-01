"""Combined code checker: library detection, lint, and function-note lookup."""
from __future__ import annotations

import logging
import os
import re
from collections import Counter
from typing import Any

from lint import lint_code

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stop words for topic-discovery mode (excluded from keyword extraction)
# ---------------------------------------------------------------------------

STOP_WORDS: set[str] = {
    "the", "and", "this", "that", "with", "from", "have", "been", "will",
    "just", "more", "than", "when", "what", "about", "each", "which",
    "their", "there", "would", "could", "should", "also", "into", "only",
    "some", "then", "them", "these", "those", "does", "done", "were",
    "your", "they", "here", "like", "make", "over", "such", "very",
    "after", "before", "other", "being", "still", "most", "many", "much",
    "need", "want", "take", "come", "know", "find", "look", "give",
    "tell", "call", "keep", "work", "seem", "feel", "same", "back",
    "even", "well", "long", "right", "down", "part", "left",
}

# ---------------------------------------------------------------------------
# Library detection patterns
# ---------------------------------------------------------------------------

LIBRARY_DETECTORS: dict[str, list[str]] = {
    "zendb":        [r"\bDB::", r"\bZenDB\b", r"\bDB::get\b", r"\bDB::select\b", r"\bDB::insert\b", r"\bDB::update\b", r"\bDB::delete\b"],
    "smartstring":  [r"\bSmartString\b", r"->value\(\)", r"->maxChars\(", r"->nl2br\(", r"->ifBlank\(", r"->textOnly\(", r"->htmlEncode\("],
    "smartarray":   [r"\bSmartArray\b", r"\bSmartArrayHtml\b", r"\bSmartNull\b", r"->pluck\(", r"->groupBy\(", r"->indexBy\(", r"->sortBy\(", r"->isEmpty\(\)"],
    "anthropic-sdk": [r"\bAnthropic\(", r"messages\.create\(", r"messages\.parse\(", r"\bbatches\.", r"from anthropic\b", r"import anthropic\b"],
    "python":       [r"\bdef\s+\w+\(", r"\bimport\s+\w+"],
}

EXTENSION_HINTS: dict[str, list[str]] = {
    ".php": ["zendb", "smartstring", "smartarray"],
    ".py":  ["anthropic-sdk", "python"],
    ".js":  ["anthropic-sdk"],
    ".ts":  ["anthropic-sdk"],
}

# When a library is detected, also include these related libraries
# (e.g., SDK code should also check API behavior notes)
LIBRARY_DEPENDENCIES: dict[str, list[str]] = {
    "anthropic-sdk": ["claude"],
    "zendb":         ["smartarray", "smartstring"],
}

# ---------------------------------------------------------------------------
# Function-reference extraction patterns
# ---------------------------------------------------------------------------

FUNCTION_PATTERNS = [
    re.compile(r'(\w+)::(\w+)\s*\('),           # PHP static:   DB::get(, SmartString::new(
    re.compile(r'->\s*(\w+)\s*\('),              # PHP instance: ->isEmpty(, ->pluck(
    re.compile(r'\.(\w+)\.(\w+)\s*\('),          # Python chain: .batches.create(, .messages.parse(
    re.compile(r'\.(\w+)\s*\('),                 # Python call:  .create(, .retrieve(
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _library_in_set(note_library: str, filter_set: set[str]) -> bool:
    """Check if *note_library* matches any library in *filter_set*.

    Supports hierarchical matching: if ``"zendb"`` is in *filter_set*,
    a note with ``library="zendb/internals"`` also matches.
    """
    if note_library in filter_set:
        return True
    for lib in filter_set:
        if note_library.startswith(lib + "/"):
            return True
    return False


def check_code(
    index: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Run library detection, lint, and function-note lookup on a code snippet.

    Params:
        code (str, required): source code to check
        file_path (str|None): optional file path for extension-based hints
        versions (dict|None): optional library->version map for filtering

    Returns dict with detected_libraries, lint_warnings, function_notes,
    clean flag, issues_found count, and a human-readable summary_line.

    When no code library detectors match, switches to topic-discovery mode
    that searches notes by keyword instead of by function reference.
    """
    code      = params.get("code") or ""
    file_path = params.get("file_path")
    versions  = params.get("versions")

    # If no code provided but file_path given, read the file
    if not code and file_path:
        from pathlib import Path
        fp = Path(file_path)
        if fp.exists():
            try:
                code = fp.read_text(encoding="utf-8")
            except Exception:
                pass

    if not code:
        return {
            "detected_libraries": [],
            "lint_warnings":      [],
            "function_notes":     [],
            "clean":              True,
            "issues_found":       0,
            "mode":               "code-check",
            "summary_line":       "No code provided.",
        }

    # ------------------------------------------------------------------
    # Step 1 -- Detect libraries from code patterns
    # ------------------------------------------------------------------
    detected: set[str] = set()

    for lib, patterns in LIBRARY_DETECTORS.items():
        for pattern in patterns:
            try:
                if re.search(pattern, code):
                    detected.add(lib)
                    break
            except re.error as exc:
                logger.warning("Bad detector pattern %r for %s: %s", pattern, lib, exc)

    # If file_path has a known extension, add its hint libraries even without
    # a pattern match -- the extension alone is a reasonable signal.
    ext_libs_added: set[str] = set()
    if file_path:
        ext = os.path.splitext(file_path)[1].lower()
        for lib in EXTENSION_HINTS.get(ext, []):
            ext_libs_added.add(lib)
            detected.add(lib)

    # Always include cross-cutting notes
    detected.add("_cross-cutting")

    # Expand dependencies (e.g., anthropic-sdk -> also check claude notes)
    expanded: set[str] = set()
    for lib in detected:
        for dep in LIBRARY_DEPENDENCIES.get(lib, []):
            expanded.add(dep)
    detected.update(expanded)

    # ------------------------------------------------------------------
    # Mode detection: did any REAL code libraries get detected?
    # "Real" = from LIBRARY_DETECTORS patterns OR file extension hints.
    # If only _cross-cutting (and its expansions) are present, switch to
    # topic-discovery mode.
    # ------------------------------------------------------------------
    code_libs = detected - {"_cross-cutting"} - expanded
    # Also subtract deps that came solely from _cross-cutting
    # (currently _cross-cutting has no deps, but future-proof)
    cross_cutting_deps = set()
    for dep in LIBRARY_DEPENDENCIES.get("_cross-cutting", []):
        cross_cutting_deps.add(dep)

    real_code_libs = code_libs - cross_cutting_deps

    if real_code_libs:
        return _code_check_path(index, code, detected, versions)
    else:
        return _topic_discovery_path(index, code)


# ---------------------------------------------------------------------------
# Code-check path (existing behavior)
# ---------------------------------------------------------------------------

def _code_check_path(
    index: dict[str, dict[str, Any]],
    code: str,
    detected: set[str],
    versions: dict[str, str] | None,
) -> dict[str, Any]:
    """Run lint + function-note lookup. This is the original check_code logic."""

    # ------------------------------------------------------------------
    # Step 2 -- Run lint for each detected library
    # ------------------------------------------------------------------
    all_warnings: list[dict[str, Any]] = []
    seen_note_ids: set[str] = set()

    for lib in sorted(detected):
        result = lint_code(index, {"code": code, "library": lib})
        for warning in result.get("warnings", []):
            nid = warning.get("note_id", "")
            if nid and nid in seen_note_ids:
                continue
            seen_note_ids.add(nid)
            all_warnings.append({
                "note_id":    nid,
                "match":      warning.get("match", ""),
                "message":    warning.get("message", ""),
                "suggestion": warning.get("suggestion", ""),
                "library":    lib,
            })

    # ------------------------------------------------------------------
    # Step 3 -- Extract function references from code
    # ------------------------------------------------------------------
    function_refs: set[str] = set()

    for pattern in FUNCTION_PATTERNS:
        for match in pattern.finditer(code):
            groups = match.groups()
            if len(groups) == 2:
                cls, method = groups
                # PHP static: ("DB", "get") -> "DB::get"
                # Python chain: ("batches", "create") -> "batches.create"
                separator = "." if "." in pattern.pattern else "::"
                function_refs.add(f"{cls}{separator}{method}")
                function_refs.add(method)
            elif len(groups) == 1:
                # Instance/dot call: ("isEmpty",) or ("create",)
                function_refs.add(groups[0])

    # ------------------------------------------------------------------
    # Step 4 -- Look up function-specific notes
    # ------------------------------------------------------------------
    function_notes: list[dict[str, Any]] = []

    # Build set of libraries to match against (detected libs + _cross-cutting)
    lib_filter = detected

    for func_name in sorted(function_refs):
        func_lower = func_name.lower()
        matching_notes: list[dict[str, Any]] = []

        for nid, entry in index.items():
            # Skip notes already surfaced as lint warnings
            if nid in seen_note_ids:
                continue

            # Library must match, OR note is always-relevant
            note_lib = entry.get("library", "")
            if not entry.get("always_relevant") and not _library_in_set(note_lib, lib_filter):
                continue

            # Only active notes
            if entry.get("lifecycle", "active") != "active":
                continue

            # Library-combination requirement
            req_libs = entry.get("requires_libraries") or []
            if req_libs:
                if not all(rl in detected for rl in req_libs):
                    continue

            # Check related_functions for a match
            # Short names (< 4 chars) require exact match to avoid false positives
            # (e.g., "or" matching "sortBy", "get" matching "DB::get")
            related = entry.get("related_functions") or []
            matched = False
            for rf in related:
                rf_lower = rf.lower()
                if len(func_lower) < 4:
                    # Exact match only for short names
                    if func_lower == rf_lower:
                        matched = True
                        break
                else:
                    # Substring match for longer names
                    if func_lower in rf_lower:
                        matched = True
                        break
            if not matched:
                continue

            # Version filtering (if versions dict provided)
            if versions and note_lib in versions:
                note_ver = entry.get("library_version", "")
                if note_ver and note_ver != versions[note_lib]:
                    continue

            matching_notes.append({
                "id":         nid,
                "type":       entry.get("type", "knowledge"),
                "summary":    entry.get("summary", ""),
                "confidence": entry.get("confidence", "weak"),
            })

        if matching_notes:
            function_notes.append({
                "function": func_name,
                "notes":    matching_notes,
            })

    # ------------------------------------------------------------------
    # Step 4b -- Deduplicate: suppress bare method names when a qualified
    # name (e.g., DB::get or batches.create) already exists
    # ------------------------------------------------------------------
    def _is_qualified(name: str) -> bool:
        return "::" in name or "." in name

    qualified_names: set[str] = set()
    for fn_entry in function_notes:
        if _is_qualified(fn_entry["function"]):
            qualified_names.add(fn_entry["function"])

    if qualified_names:
        deduped: list[dict[str, Any]] = []
        for fn_entry in function_notes:
            fname = fn_entry["function"]
            if not _is_qualified(fname):
                # Bare method name -- suppress if ANY qualified name ends with this method
                # e.g., "create" is suppressed when "batches.create" or "messages.create" exists
                has_qualified_parent = any(
                    qn.endswith(f"::{fname}") or qn.endswith(f".{fname}")
                    for qn in qualified_names
                )
                if has_qualified_parent:
                    continue
            deduped.append(fn_entry)
        function_notes = deduped

    # ------------------------------------------------------------------
    # Step 5 -- Proactive "also relevant" from related_notes
    # ------------------------------------------------------------------
    also_relevant: list[dict[str, Any]] = []
    seen_also: set[str] = set(seen_note_ids)  # Don't duplicate already-surfaced notes
    # Also exclude notes already in function_notes
    for fn_entry in function_notes:
        for note_info in fn_entry.get("notes", []):
            seen_also.add(note_info.get("id", ""))

    for fn_entry in function_notes:
        for note_info in fn_entry.get("notes", []):
            primary_id = note_info.get("id", "")
            primary_entry = index.get(primary_id, {})
            related = primary_entry.get("related_notes") or []
            for link in related:
                link_id = link.get("id", link) if isinstance(link, dict) else link
                if link_id in seen_also:
                    continue
                seen_also.add(link_id)
                linked_entry = index.get(link_id)
                if linked_entry and linked_entry.get("lifecycle", "active") in ("active", "evergreen"):
                    also_relevant.append({
                        "id": link_id,
                        "type": linked_entry.get("type", "knowledge"),
                        "summary": linked_entry.get("summary", ""),
                        "library": linked_entry.get("library", ""),
                        "via": primary_id,
                    })

    # ------------------------------------------------------------------
    # Step 6 -- Build return dict
    # ------------------------------------------------------------------
    total_fn_notes = sum(len(fn["notes"]) for fn in function_notes)
    issues_found   = len(all_warnings) + total_fn_notes

    # ------------------------------------------------------------------
    # Step 7 -- Implicit review: mark relevant notes as reviewed when clean
    # ------------------------------------------------------------------
    implicitly_reviewed: list[str] = []
    if issues_found == 0:
        from utils import today_str
        from db import get_db
        from index import get_notemap_dir
        today = today_str()
        reviewed_ids: list[str] = []
        for nid, entry in index.items():
            note_lib = entry.get("library", "")
            if not _library_in_set(note_lib, detected):
                continue
            if entry.get("lifecycle", "active") != "active":
                continue
            related = entry.get("related_functions") or []
            if any(fn in function_refs for fn in related):
                entry["last_reviewed"] = today
                reviewed_ids.append(nid)
        if reviewed_ids:
            conn = get_db(get_notemap_dir())
            for nid in reviewed_ids:
                conn.execute(
                    "UPDATE notes SET last_reviewed = ?, review_count = review_count + 1 WHERE id = ?",
                    (today, nid)
                )
            conn.commit()
            implicitly_reviewed = reviewed_ids

    # Build human-readable summary line
    summary_line = _build_summary_line(all_warnings, function_notes)

    # Remove _cross-cutting from the reported libraries (internal detail)
    reported_libs = sorted(lib for lib in detected if lib != "_cross-cutting")

    result = {
        "detected_libraries": reported_libs,
        "lint_warnings":      all_warnings,
        "function_notes":     function_notes,
        "also_relevant":      also_relevant if also_relevant else [],
        "clean":              issues_found == 0,
        "issues_found":       issues_found,
        "mode":               "code-check",
        "summary_line":       summary_line,
    }
    if implicitly_reviewed:
        result["implicitly_reviewed"] = implicitly_reviewed
    return result


# ---------------------------------------------------------------------------
# Topic-discovery path (non-code content)
# ---------------------------------------------------------------------------

def _topic_discovery_path(
    index: dict[str, dict[str, Any]],
    content: str,
) -> dict[str, Any]:
    """Search notes by keyword when no code libraries are detected.

    Extracts significant words from the content, then matches them against
    note topics, summaries, and tags in the index.
    """

    # ------------------------------------------------------------------
    # Step 1 -- Extract keywords from content
    # ------------------------------------------------------------------
    words = re.findall(r'[a-zA-Z]+', content)
    words_lower = [w.lower() for w in words if len(w) >= 4]
    words_lower = [w for w in words_lower if w not in STOP_WORDS]

    # Take the top 20 most common significant words
    word_counts = Counter(words_lower)
    keywords = [word for word, _count in word_counts.most_common(20)]

    # ------------------------------------------------------------------
    # Step 2 -- Search index for notes matching each keyword
    # ------------------------------------------------------------------
    topic_matches: list[dict[str, Any]] = []
    seen_note_ids: set[str] = set()

    for keyword in keywords:
        matched_notes: list[dict[str, Any]] = []

        for nid, entry in index.items():
            # Only active notes
            if entry.get("lifecycle", "active") != "active":
                continue

            # Already matched by a previous keyword -- skip to avoid dupes
            if nid in seen_note_ids:
                continue

            # Check topic, summary, and tags for case-insensitive substring match
            topic   = (entry.get("topic") or "").lower()
            summary = (entry.get("summary") or "").lower()
            tags    = entry.get("tags") or []
            tags_str = " ".join(str(t).lower() for t in tags)

            if keyword in topic or keyword in summary or keyword in tags_str:
                seen_note_ids.add(nid)
                matched_notes.append({
                    "id":      nid,
                    "summary": entry.get("summary", ""),
                    "library": entry.get("library", ""),
                })

        if matched_notes:
            topic_matches.append({
                "topic": keyword,
                "notes": matched_notes,
            })

    # ------------------------------------------------------------------
    # Step 3 -- Build return dict
    # ------------------------------------------------------------------
    total_notes = sum(len(tm["notes"]) for tm in topic_matches)

    if total_notes > 0:
        summary_line = f"No code detected. {total_notes} topic-related note{'s' if total_notes != 1 else ''} found."
    else:
        summary_line = "No code detected. No relevant notes found."

    return {
        "detected_libraries": [],
        "lint_warnings":      [],
        "function_notes":     [],
        "topic_matches":      topic_matches,
        "clean":              total_notes == 0,
        "issues_found":       total_notes,
        "mode":               "topic-discovery",
        "summary_line":       summary_line,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_summary_line(
    warnings: list[dict[str, Any]],
    function_notes: list[dict[str, Any]],
) -> str:
    """Build a concise human-readable summary of findings."""
    parts: list[str] = []

    if warnings:
        n = len(warnings)
        parts.append(f"{n} anti-pattern violation{'s' if n != 1 else ''}")

    if function_notes:
        total = sum(len(fn["notes"]) for fn in function_notes)
        # Name the functions that have notes
        func_names = [fn["function"] for fn in function_notes]
        if len(func_names) <= 3:
            names_str = ", ".join(func_names)
        else:
            names_str = ", ".join(func_names[:3]) + f" +{len(func_names) - 3} more"
        parts.append(f"{total} function gotcha{'s' if total != 1 else ''} for {names_str}")

    if not parts:
        return "Clean -- no issues found."

    return ", ".join(parts)
