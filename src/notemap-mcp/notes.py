"""CRUD operations for Cornell-format notemap notes."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import frontmatter

from index import remove_entry, save_index, update_entry
from models import Lifecycle, NoteType
from utils import (
    ensure_dir,
    fuzzy_suggestions,
    generate_id,
    slugify_topic,
    today_str,
)


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------

def _extract_sections(body: str) -> dict[str, str]:
    """Split a Cornell-note markdown body into its three sections.

    Returns a dict with keys ``cues``, ``notes``, ``summary``.  Each value
    is the raw text between its heading and the next heading (or EOF),
    with leading/trailing whitespace stripped.
    """
    sections: dict[str, str] = {"cues": "", "notes": "", "summary": ""}
    current_key: str | None = None
    current_lines: list[str] = []
    heading_map = {
        "cues": "cues",
        "notes": "notes",
        "summary": "summary",
    }

    for line in body.splitlines(keepends=True):
        stripped = line.strip().lower()
        if stripped.startswith("## "):
            # Flush previous section
            if current_key is not None:
                sections[current_key] = "".join(current_lines).strip()
            heading_text = stripped[3:].strip()
            current_key = heading_map.get(heading_text)
            current_lines = []
        else:
            current_lines.append(line)

    # Flush last section
    if current_key is not None:
        sections[current_key] = "".join(current_lines).strip()

    return sections


def _build_body(cues: list[str], notes_text: str, summary_text: str) -> str:
    """Reassemble the three Cornell sections into a markdown body."""
    cue_lines = "\n".join(f"- {c}" for c in cues) if cues else ""
    parts = [
        "## Cues",
        cue_lines,
        "",
        "## Notes",
        notes_text,
        "",
        "## Summary",
        summary_text,
    ]
    return "\n".join(parts) + "\n"


def _cues_from_section(section_text: str) -> list[str]:
    """Parse bullet lines from the Cues section into a plain list."""
    cues: list[str] = []
    for line in section_text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            cues.append(line[2:].strip())
        elif line.startswith("* "):
            cues.append(line[2:].strip())
        elif line:
            cues.append(line)
    return cues


# ---------------------------------------------------------------------------
# Frontmatter builder
# ---------------------------------------------------------------------------

def _build_frontmatter(params: dict[str, Any], note_id: str) -> dict[str, Any]:
    """Construct the full YAML frontmatter dict for a new note."""
    today = today_str()
    note_type = params.get("type", NoteType.KNOWLEDGE.value)
    is_anti_pattern = note_type == NoteType.ANTI_PATTERN.value

    review_intervals: dict[str, int] = {
        NoteType.ANTI_PATTERN.value: 60,
        NoteType.TECHNIQUE.value:    90,
        NoteType.REFERENCE.value:    90,
        NoteType.DECISION.value:     180,
        NoteType.FINDING.value:      60,
    }

    fm: dict[str, Any] = {
        "id":                    note_id,
        "library":               params["library"],
        "type":                  note_type,
        "topic":                 params["topic"],
        "tags":                  params.get("tags", []),
        "source_quality":        params.get("source_quality", "unverified"),
        "confidence":            params.get("confidence", "weak"),
        "lifecycle":             "active",
        "library_version":       params.get("library_version", ""),
        "created":               today,
        "last_modified":         today,
        "last_reviewed":         today,
        "review_interval_days":  review_intervals.get(note_type, 30),
        "miss_count":            0,
        "miss_log":              [],
        "review_count":          0,
        "related_functions":     params.get("related_functions", []),
        "related_notes":         params.get("related_notes", []),
        "sources":               params.get("sources", []),
    }

    # Anti-pattern specific fields
    if is_anti_pattern:
        fm["primitives_to_avoid"]   = params.get("primitives_to_avoid", [])
        fm["preferred_alternatives"] = params.get("preferred_alternatives", [])

    # Correction-specific fields
    if note_type == NoteType.CORRECTION.value:
        fm["wrong_assumption"]  = params.get("wrong_assumption", "")
        fm["correct_behavior"]  = params.get("correct_behavior", "")
        fm["applies_to"]        = params.get("applies_to", "")

    return fm


# ---------------------------------------------------------------------------
# CRUD functions
# ---------------------------------------------------------------------------

def create_note(
    index: dict[str, Any],
    notemap_dir: Path,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Create a new Cornell-format note.

    Returns a result dict with ``id``, ``path``, and ``message`` on success,
    or ``error`` on failure.
    """
    library: str = params["library"]
    topic: str   = params["topic"]
    note_id      = generate_id(library, topic)

    # Duplicate check
    if note_id in index:
        return {
            "error": f"Note '{note_id}' already exists. Use update_note to modify it.",
        }

    # Paths
    lib_dir  = notemap_dir / library
    ensure_dir(lib_dir)
    slug     = slugify_topic(topic)
    filepath = lib_dir / f"{slug}.md"

    # Frontmatter + body
    fm_dict    = _build_frontmatter(params, note_id)
    cues_list  = params.get("cues", [])
    body       = _build_body(cues_list, params["notes"], params["summary"])
    post       = frontmatter.Post(body, **fm_dict)

    filepath.write_text(frontmatter.dumps(post), encoding="utf-8")

    # Update index
    entry_data          = dict(fm_dict)
    entry_data["cues"]  = cues_list
    entry_data["summary"] = params["summary"]
    entry_data["path"]  = str(filepath.relative_to(notemap_dir))
    update_entry(index, note_id, entry_data)
    save_index(notemap_dir, index)

    return {
        "id":      note_id,
        "path":    str(filepath.resolve()),
        "message": f"Created note '{note_id}' at {filepath.resolve()}",
    }


def read_note(
    index: dict[str, Any],
    notemap_dir: Path,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Read a note by ID, optionally returning only a specific section.

    ``section`` can be ``all`` (default), ``meta``, ``cues``, ``notes``,
    or ``summary``.
    """
    note_id: str = params["id"]
    section: str = params.get("section", "all")

    if note_id not in index:
        candidates = fuzzy_suggestions(note_id, list(index.keys()))
        msg = f"Note '{note_id}' not found."
        if candidates:
            msg += f" Did you mean: {', '.join(candidates)}?"
        return {"error": msg}

    entry    = index[note_id]
    filepath = notemap_dir / entry["path"]

    if not filepath.exists():
        return {"error": f"File missing on disk: {filepath}"}

    post = frontmatter.load(str(filepath))

    if section == "meta":
        return {"id": note_id, "section": "meta", "content": dict(post.metadata)}

    if section in ("cues", "notes", "summary"):
        sections = _extract_sections(post.content)
        return {"id": note_id, "section": section, "content": sections.get(section, "")}

    # section == "all"
    return {
        "id":          note_id,
        "section":     "all",
        "frontmatter": dict(post.metadata),
        "body":        post.content,
    }


def update_note(
    index: dict[str, Any],
    notemap_dir: Path,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Update an existing note.

    Accepts any combination of updatable fields.  Returns a result dict
    with ``id``, ``changes`` (list of human-readable strings), and
    ``message``.
    """
    note_id: str = params["id"]

    if note_id not in index:
        return {"error": f"Note '{note_id}' not found."}

    entry    = index[note_id]
    filepath = notemap_dir / entry["path"]

    if not filepath.exists():
        return {"error": f"File missing on disk: {filepath}"}

    post     = frontmatter.load(str(filepath))
    meta     = post.metadata
    sections = _extract_sections(post.content)
    changes: list[str] = []

    # ---- Simple scalar replacements ----
    simple_fields = [
        "source_quality",
        "confidence",
        "library_version",
        "review_interval_days",
        "wrong_assumption",
        "correct_behavior",
        "applies_to",
    ]
    for fld in simple_fields:
        if fld in params:
            old_val = meta.get(fld)
            meta[fld] = params[fld]
            changes.append(f"{fld}: {old_val!r} -> {params[fld]!r}")

    # ---- Summary (also a simple replacement but lives in body) ----
    if "summary" in params:
        sections["summary"] = params["summary"]
        changes.append("summary: replaced")

    # ---- List add/remove fields ----
    list_fields = [
        "cues",
        "tags",
        "related_functions",
        "related_notes",
        "primitives_to_avoid",
        "preferred_alternatives",
    ]
    for fld in list_fields:
        if fld not in params:
            continue
        spec = params[fld]
        to_add: list[str]    = spec.get("add", []) if isinstance(spec, dict) else []
        to_remove: list[str] = spec.get("remove", []) if isinstance(spec, dict) else []

        if fld == "cues":
            # Cues live in the body, not frontmatter
            current = _cues_from_section(sections.get("cues", ""))
        else:
            current = list(meta.get(fld, []))

        added   = [v for v in to_add if v not in current]
        removed = [v for v in to_remove if v in current]
        for v in added:
            current.append(v)
        for v in removed:
            current.remove(v)

        if fld == "cues":
            sections["cues"] = "\n".join(f"- {c}" for c in current) if current else ""
        else:
            meta[fld] = current

        if added:
            changes.append(f"{fld}: added {added}")
        if removed:
            changes.append(f"{fld}: removed {removed}")

    # ---- Sources: full replacement ----
    if "sources" in params:
        meta["sources"] = params["sources"]
        changes.append(f"sources: set to {len(params['sources'])} source(s)")

    # ---- Notes: full replacement ----
    if "notes" in params:
        sections["notes"] = params["notes"]
        changes.append("notes: replaced")

    # ---- Notes: append ----
    if "notes_append" in params:
        existing = sections.get("notes") or ""
        separator = "\n\n" if existing else ""
        sections["notes"] = existing + separator + params["notes_append"]
        changes.append("notes: appended")

    # ---- mark_reviewed ----
    if params.get("mark_reviewed"):
        today = today_str()
        meta["last_reviewed"] = today
        meta["review_count"]  = meta.get("review_count", 0) + 1
        changes.append(f"last_reviewed: {today}, review_count: {meta['review_count']}")

        # Extend interval if no misses and reviewed enough
        if meta.get("miss_count", 0) == 0 and meta["review_count"] >= 3:
            current_interval = meta.get("review_interval_days", 30)
            if current_interval < 60:
                meta["review_interval_days"] = 60
                changes.append("review_interval_days: 30 -> 60")
            elif current_interval < 90:
                meta["review_interval_days"] = 90
                changes.append("review_interval_days: 60 -> 90")

        # Reset stale notes back to active
        if meta.get("lifecycle") == Lifecycle.STALE.value:
            meta["lifecycle"]     = Lifecycle.ACTIVE.value
            meta["miss_count"]    = 0
            meta["review_count"]  = 0
            changes.append("lifecycle: stale -> active (reset miss_count and review_count)")

    # ---- increment_miss ----
    if params.get("increment_miss"):
        reason = params.get("miss_reason", "unclassified")
        today  = today_str()

        meta["miss_count"] = meta.get("miss_count", 0) + 1
        miss_log: list[dict[str, str]] = meta.get("miss_log", [])
        miss_log.append({"date": today, "reason": reason})
        meta["miss_log"] = miss_log
        changes.append(f"miss_count: {meta['miss_count']}, miss_log: +{{date: {today}, reason: {reason}}}")

        # Adjust review interval based on miss count
        mc = meta["miss_count"]
        if mc >= 3:
            meta["review_interval_days"] = 14
            meta["lifecycle"] = Lifecycle.STALE.value
            changes.append("review_interval_days: -> 14, lifecycle: -> stale")
        elif mc >= 2:
            meta["review_interval_days"] = 14
            changes.append("review_interval_days: -> 14")
        elif mc == 1:
            meta["review_interval_days"] = 30
            changes.append("review_interval_days: -> 30")

    # ---- Always update last_modified ----
    meta["last_modified"] = today_str()

    # ---- Rebuild and write ----
    cues_list = _cues_from_section(sections.get("cues", ""))
    body      = _build_body(cues_list, sections.get("notes", ""), sections.get("summary", ""))
    post.content  = body
    post.metadata = meta

    filepath.write_text(frontmatter.dumps(post), encoding="utf-8")

    # ---- Update index ----
    entry_data = dict(meta)
    entry_data["cues"]    = cues_list
    entry_data["summary"] = sections.get("summary", "")
    entry_data["path"]    = str(filepath.resolve())
    update_entry(index, note_id, entry_data)
    save_index(notemap_dir, index)

    return {
        "id":      note_id,
        "changes": changes,
        "message": f"Updated note '{note_id}' ({len(changes)} change(s))",
    }


def delete_note(
    index: dict[str, Any],
    notemap_dir: Path,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Delete (soft or hard) a note.

    Soft delete moves the file to ``_archive/`` and cleans up references.
    Hard delete removes the file permanently.
    """
    note_id: str     = params["id"]
    reason: str      = params.get("reason", "")
    hard_delete: bool = params.get("hard_delete", False)

    if note_id not in index:
        return {"error": f"Note '{note_id}' not found."}

    entry    = index[note_id]
    filepath = notemap_dir / entry["path"]

    if hard_delete:
        # Permanent deletion
        if filepath.exists():
            filepath.unlink()
        remove_entry(index, note_id)
        save_index(notemap_dir, index)
        return {
            "id":      note_id,
            "action":  "hard_delete",
            "message": f"Permanently deleted note '{note_id}'",
        }

    # ---- Soft delete ----

    # Load and stamp with archive metadata
    if filepath.exists():
        post = frontmatter.load(str(filepath))
        post.metadata["archive_reason"] = reason
        post.metadata["archived_date"]  = today_str()

        # Move to _archive
        archive_dir = notemap_dir / "_archive"
        ensure_dir(archive_dir)
        archive_path = archive_dir / f"{note_id}.md"
        archive_path.write_text(frontmatter.dumps(post), encoding="utf-8")

        # Remove original
        filepath.unlink()

    # Clean up related_notes references in other notes
    for other_id, other_entry in list(index.items()):
        if other_id == note_id:
            continue
        related: list[str] = other_entry.get("related_notes") or []
        if note_id in related:
            other_path = Path(other_entry["path"])
            if other_path.exists():
                other_post = frontmatter.load(str(other_path))
                other_related = list(other_post.metadata.get("related_notes", []))
                if note_id in other_related:
                    other_related.remove(note_id)
                    other_post.metadata["related_notes"] = other_related
                    other_path.write_text(
                        frontmatter.dumps(other_post), encoding="utf-8"
                    )
            other_entry["related_notes"] = [
                r for r in related if r != note_id
            ]

    remove_entry(index, note_id)
    save_index(notemap_dir, index)

    return {
        "id":      note_id,
        "action":  "archived",
        "message": f"Archived note '{note_id}'" + (f" (reason: {reason})" if reason else ""),
    }
