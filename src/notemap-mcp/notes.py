"""CRUD operations for notemap notes, backed by SQLite."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db import get_db, load_note_dict, _build_anchor_text, _update_anchor_text_for
from index import remove_entry, save_index, update_entry
from models import Lifecycle, NoteType
from utils import (
    ensure_dir,
    fuzzy_suggestions,
    generate_id,
    slugify_topic,
    today_str,
)

try:
    from embed import encode_text, EMBEDDINGS_AVAILABLE, MODEL_NAME, DIMENSIONS, invalidate_cache
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    encode_text = None
    MODEL_NAME = ""
    DIMENSIONS = 0
    invalidate_cache = None


# ---------------------------------------------------------------------------
# CRUD functions
# ---------------------------------------------------------------------------

def create_note(
    index: dict[str, Any],
    notemap_dir: Path,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Create a new note.

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

    # Quality warnings (non-blocking)
    warnings: list[str] = []

    # Duplicate detection: check if a very similar note already exists
    similar_notes: list[str] = []
    topic_lower = topic.lower()
    for existing_id, existing_entry in index.items():
        if existing_entry.get("library") != library:
            continue
        existing_topic = (existing_entry.get("topic") or "").lower()
        topic_words    = set(topic_lower.split())
        existing_words = set(existing_topic.split())
        if len(topic_words) >= 3 and len(existing_words) >= 3:
            overlap       = topic_words & existing_words
            overlap_ratio = len(overlap) / min(len(topic_words), len(existing_words))
            if overlap_ratio > 0.6:
                similar_notes.append(existing_id)

    if similar_notes:
        warnings.append(f"Similar notes may exist: {', '.join(similar_notes[:3])}. Consider updating instead of creating a new note.")

    # Check summary quality
    summary_text = params.get("summary", "").strip()
    if not summary_text:
        warnings.append("Missing summary. Notes without summaries are harder to find.")
    elif len(summary_text.split()) < 5:
        warnings.append("Summary is very short (< 5 words). Consider a more descriptive summary.")

    # Note type: warn (don't block) on a value outside the NoteType enum, since
    # a typo'd type misroutes the note's tier, review interval, and lint behavior.
    note_type = params.get("type", "knowledge")
    valid_types = {nt.value for nt in NoteType}
    if note_type not in valid_types:
        suggestion = fuzzy_suggestions(note_type, sorted(valid_types))
        hint = f" Did you mean: {', '.join(suggestion)}?" if suggestion else f" Valid types: {', '.join(sorted(valid_types))}."
        warnings.append(f"Unknown note type '{note_type}'.{hint}")

    # Source pointer: only nag when the source_quality doesn't already assert that
    # verification happened. runtime-tested / verified-from-source / user-correction
    # mean "I checked this" -- the note isn't unverifiable, it just lacks a file/URL
    # pointer for someone else to re-check later.
    asserts_verification = {"runtime-tested", "verified-from-source", "user-correction"}
    if not params.get("sources") and params.get("source_quality") not in asserts_verification:
        warnings.append(
            "No source pointer. Add a sources entry so this is traceable later: "
            "{type:'file', path:..., lines:...} / {type:'url', url:...} / "
            "{type:'user', context:'verified live this session: ...'}."
        )

    # Check related_functions for relevant types
    if note_type in ("anti-pattern", "knowledge", "correction") and not params.get("related_functions"):
        warnings.append(f"No related_functions for {note_type} note. Function names are the strongest search signal.")

    # Related notes: warn (don't block) when a link target isn't a known note --
    # the target may legitimately be created moments later, but a typo'd ID would
    # otherwise become a silent dangling link.
    for link in (params.get("related_notes") or []):
        target_id = link.get("id", "") if isinstance(link, dict) else (link if isinstance(link, str) else "")
        if target_id and target_id not in index:
            suggestion = fuzzy_suggestions(target_id, list(index.keys()))
            hint = f" Did you mean: {', '.join(suggestion)}?" if suggestion else ""
            warnings.append(f"related_notes target '{target_id}' is not a known note -- link will be dangling.{hint}")

    # Check body length
    body_text  = params.get("notes", "").strip()
    body_words = len(body_text.split()) if body_text else 0
    if body_words > 500:
        warnings.append(f"Note body is {body_words} words. Consider splitting into atomic notes.")
    if body_words < 10 and body_text:
        warnings.append(f"Note body is very short ({body_words} words). May not provide enough context.")

    # Link suggestions
    suggested_links: list[dict[str, Any]] = []
    topic_words = set(w.lower() for w in topic.split() if len(w) >= 3)
    note_tags = set(t.lower() for t in (params.get("tags") or []))
    note_functions = set(f.lower() for f in (params.get("related_functions") or []))

    for existing_id, existing_entry in index.items():
        if existing_entry.get("library") != library:
            continue

        link_score = 0
        reasons: list[str] = []

        ex_functions = set(f.lower() for f in (existing_entry.get("related_functions") or []))
        shared_fns = note_functions & ex_functions
        if shared_fns:
            link_score += len(shared_fns) * 40
            reasons.append(f"shared functions: {', '.join(sorted(shared_fns))}")

        ex_topic_words = set(w.lower() for w in (existing_entry.get("topic") or "").split() if len(w) >= 3)
        shared_words = topic_words & ex_topic_words
        if len(shared_words) >= 2:
            link_score += len(shared_words) * 10
            reasons.append(f"topic overlap: {', '.join(sorted(shared_words))}")

        ex_tags = set(t.lower() for t in (existing_entry.get("tags") or []))
        shared_tags = note_tags & ex_tags
        if shared_tags:
            link_score += len(shared_tags) * 15
            reasons.append(f"shared tags: {', '.join(sorted(shared_tags))}")

        if link_score >= 40:
            suggested_links.append({
                "id": existing_id,
                "score": link_score,
                "reasons": reasons,
            })

    # Unlinked mentions
    unlinked: list[dict[str, str]] = []
    body_lower = params.get("notes", "").lower()
    if body_lower:
        for existing_id, existing_entry in index.items():
            if existing_id == note_id:
                continue
            ex_topic = (existing_entry.get("topic") or "").lower()
            ex_words = [w for w in ex_topic.split() if len(w) >= 4]
            if len(ex_words) >= 2:
                matches = sum(1 for w in ex_words if w in body_lower)
                if matches >= len(ex_words) * 0.6:
                    unlinked.append({
                        "id": existing_id,
                        "topic": existing_entry.get("topic", ""),
                    })

    # Build data for DB insert
    today = today_str()
    is_anti_pattern = note_type == NoteType.ANTI_PATTERN.value

    review_intervals: dict[str, int] = {
        NoteType.ANTI_PATTERN.value:  60,
        NoteType.TECHNIQUE.value:     90,
        NoteType.REFERENCE.value:     90,
        NoteType.DECISION.value:      180,
        NoteType.FINDING.value:       60,
        NoteType.COMMUNICATION.value: 120,
        NoteType.COMMITMENT.value:    30,
        NoteType.REQUIREMENT.value:   90,
    }

    cues_list = params.get("cues", []) or []
    notes_body = params.get("notes", "").strip()
    context_prefix = "This note is about %s in %s" % (topic, library)
    notes_body_search = (context_prefix + ". " + notes_body)[:500]
    tags_text = " ".join(params.get("tags") or [])

    conn = get_db(notemap_dir)

    conn.execute("""
        INSERT INTO notes (
            id, library, topic, type, summary, notes_body, cues_raw,
            source_quality, confidence, lifecycle,
            review_interval_days, review_tier, review_count, miss_count,
            created, last_modified, last_reviewed,
            valid_from, valid_until,
            last_retrieved, retrieval_count,
            library_version, always_relevant,
            wrong_assumption, correct_behavior, applies_to,
            sources_json, miss_log_json,
            notes_body_search, tags_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        note_id,
        library,
        topic,
        note_type,
        summary_text,
        notes_body,
        "\n".join(cues_list),
        params.get("source_quality", "unverified"),
        params.get("confidence", "weak"),
        "active",
        review_intervals.get(note_type, 30),
        2,  # review_tier
        0,  # review_count
        0,  # miss_count
        today,
        today,
        today,
        today,  # valid_from
        "",     # valid_until
        "",     # last_retrieved
        0,      # retrieval_count
        params.get("library_version") or "",
        0,      # always_relevant
        params.get("wrong_assumption", "") or "",
        params.get("correct_behavior", "") or "",
        params.get("applies_to", "") or "",
        json.dumps(params.get("sources") or []),
        json.dumps([]),
        notes_body_search,
        tags_text,
    ))

    # Tags
    for tag in (params.get("tags") or []):
        conn.execute("INSERT OR IGNORE INTO note_tags VALUES (?, ?)", (note_id, tag))

    # Related functions
    for fn in (params.get("related_functions") or []):
        conn.execute("INSERT OR IGNORE INTO note_functions VALUES (?, ?)", (note_id, fn))

    # Related notes
    link_target_ids: list[str] = []
    for link in (params.get("related_notes") or []):
        if isinstance(link, str):
            target_id = link
            link_type = "related"
        elif isinstance(link, dict):
            target_id = link.get("id", "")
            link_type = link.get("type", "related")
        else:
            continue
        if target_id:
            conn.execute("INSERT OR IGNORE INTO note_links VALUES (?, ?, ?)",
                        (note_id, target_id, link_type))
            link_target_ids.append(target_id)

    # Rebuild anchor text for link targets
    if link_target_ids:
        _update_anchor_text_for(conn, link_target_ids)

    # Anti-pattern fields
    if is_anti_pattern:
        for pat in (params.get("primitives_to_avoid") or []):
            conn.execute("INSERT OR IGNORE INTO note_anti_patterns VALUES (?, ?)", (note_id, pat))
        for alt in (params.get("preferred_alternatives") or []):
            conn.execute("INSERT OR IGNORE INTO note_alternatives VALUES (?, ?)", (note_id, alt))

    conn.commit()

    # Generate embedding for the new note
    if EMBEDDINGS_AVAILABLE and encode_text is not None:
        cues_str = " ".join(params.get("cues") or [])
        embed_text = f"{topic} {summary_text} {cues_str} {notes_body}"
        vec_bytes = encode_text(embed_text)
        if vec_bytes is not None:
            conn.execute(
                "INSERT OR REPLACE INTO note_embeddings (note_id, model, dimensions, vector) VALUES (?, ?, ?, ?)",
                (note_id, MODEL_NAME, DIMENSIONS, vec_bytes),
            )
            conn.commit()
            if invalidate_cache:
                invalidate_cache()

    # Auto-link to related notes via embedding similarity
    if EMBEDDINGS_AVAILABLE and encode_text is not None:
        try:
            from embed import load_embedding_matrix, vector_search as _vs
            cache = load_embedding_matrix(conn)
            if cache:
                note_ids_all, matrix = cache
                cues_str = " ".join(params.get("cues") or [])
                embed_text = f"{topic} {summary_text} {cues_str} {notes_body}"
                similar = _vs(embed_text, note_ids_all, matrix, top_k=5)
                auto_link_targets: list[str] = []
                for sim_id, sim_score in similar:
                    if sim_id != note_id and sim_score > 0.5:
                        existing = conn.execute(
                            "SELECT 1 FROM note_links WHERE source_id=? AND target_id=?",
                            (note_id, sim_id)
                        ).fetchone()
                        if not existing:
                            conn.execute(
                                "INSERT OR IGNORE INTO note_links (source_id, target_id, link_type) VALUES (?, ?, ?)",
                                (note_id, sim_id, "related")
                            )
                            auto_link_targets.append(sim_id)
                if auto_link_targets:
                    _update_anchor_text_for(conn, auto_link_targets)
                conn.commit()
                if invalidate_cache:
                    invalidate_cache()
        except Exception:
            pass  # Auto-linking is best-effort, never block note creation

    # Update in-memory index
    entry_data = load_note_dict(conn, note_id)
    if entry_data:
        update_entry(index, note_id, entry_data)

    result: dict[str, Any] = {
        "id":      note_id,
        "path":    f"{library}/{note_id}.md",
        "message": f"Created note '{note_id}'",
    }
    if warnings:
        result["warnings"] = warnings
    if suggested_links:
        suggested_links.sort(key=lambda x: x["score"], reverse=True)
        result["suggested_links"] = suggested_links[:5]
    if unlinked:
        result["unlinked_mentions"] = unlinked[:5]
    return result


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

    conn = get_db(notemap_dir)
    row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        return {"error": f"Note '{note_id}' not found in database."}

    if section == "meta":
        # Build a meta dict from the DB row
        meta = {
            "id":                    row["id"],
            "library":               row["library"],
            "type":                  row["type"],
            "topic":                 row["topic"],
            "source_quality":        row["source_quality"],
            "confidence":            row["confidence"],
            "lifecycle":             row["lifecycle"],
            "library_version":       row["library_version"],
            "created":               row["created"],
            "last_modified":         row["last_modified"],
            "last_reviewed":         row["last_reviewed"],
            "review_interval_days":  row["review_interval_days"],
            "review_tier":           row["review_tier"],
            "miss_count":            row["miss_count"],
            "review_count":          row["review_count"],
            "always_relevant":       bool(row["always_relevant"]),
            "wrong_assumption":      row["wrong_assumption"],
            "correct_behavior":      row["correct_behavior"],
            "applies_to":            row["applies_to"],
            "tags": [r["tag"] for r in conn.execute(
                "SELECT tag FROM note_tags WHERE note_id = ?", (note_id,)).fetchall()],
            "related_functions": [r["function_name"] for r in conn.execute(
                "SELECT function_name FROM note_functions WHERE note_id = ?", (note_id,)).fetchall()],
            "related_notes": [{"id": r["target_id"], "type": r["link_type"]} for r in conn.execute(
                "SELECT target_id, link_type FROM note_links WHERE source_id = ?", (note_id,)).fetchall()],
            "sources": json.loads(row["sources_json"] or "[]"),
            "miss_log": json.loads(row["miss_log_json"] or "[]"),
        }
        return {"id": note_id, "section": "meta", "content": meta}

    if section == "cues":
        return {"id": note_id, "section": "cues", "content": row["cues_raw"]}

    if section == "notes":
        return {"id": note_id, "section": "notes", "content": row["notes_body"]}

    if section == "summary":
        return {"id": note_id, "section": "summary", "content": row["summary"]}

    # section == "all"
    # Build a full representation
    tags = [r["tag"] for r in conn.execute(
        "SELECT tag FROM note_tags WHERE note_id = ?", (note_id,)).fetchall()]
    related_functions = [r["function_name"] for r in conn.execute(
        "SELECT function_name FROM note_functions WHERE note_id = ?", (note_id,)).fetchall()]
    related_notes_list = [{"id": r["target_id"], "type": r["link_type"]} for r in conn.execute(
        "SELECT target_id, link_type FROM note_links WHERE source_id = ?", (note_id,)).fetchall()]

    frontmatter = {
        "id":                    row["id"],
        "library":               row["library"],
        "type":                  row["type"],
        "topic":                 row["topic"],
        "tags":                  tags,
        "source_quality":        row["source_quality"],
        "confidence":            row["confidence"],
        "lifecycle":             row["lifecycle"],
        "library_version":       row["library_version"],
        "created":               row["created"],
        "last_modified":         row["last_modified"],
        "last_reviewed":         row["last_reviewed"],
        "review_interval_days":  row["review_interval_days"],
        "review_tier":           row["review_tier"],
        "miss_count":            row["miss_count"],
        "miss_log":              json.loads(row["miss_log_json"] or "[]"),
        "review_count":          row["review_count"],
        "related_functions":     related_functions,
        "related_notes":         related_notes_list,
        "sources":               json.loads(row["sources_json"] or "[]"),
        "always_relevant":       bool(row["always_relevant"]),
        "wrong_assumption":      row["wrong_assumption"],
        "correct_behavior":      row["correct_behavior"],
        "applies_to":            row["applies_to"],
    }

    # Reconstruct a body similar to the old markdown format
    cues_section = row["cues_raw"]
    cue_lines = "\n".join(f"- {c}" for c in cues_section.split("\n") if c.strip()) if cues_section else ""
    body = f"## Cues\n{cue_lines}\n\n## Notes\n{row['notes_body']}\n\n## Summary\n{row['summary']}\n"

    return {
        "id":          note_id,
        "section":     "all",
        "frontmatter": frontmatter,
        "body":        body,
    }


def update_note(
    index: dict[str, Any],
    notemap_dir: Path,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Update an existing note.

    Accepts any combination of updatable fields. Returns a result dict
    with ``id``, ``changes``, and ``message``.
    """
    note_id: str = params["id"]

    if note_id not in index:
        return {"error": f"Note '{note_id}' not found."}

    conn = get_db(notemap_dir)
    row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        return {"error": f"Note '{note_id}' not found in database."}

    changes: list[str] = []
    warnings: list[str] = []

    # ---- Note type: warn (don't block) on a value outside the NoteType enum ----
    if "type" in params:
        valid_types = {nt.value for nt in NoteType}
        if params["type"] not in valid_types:
            suggestion = fuzzy_suggestions(params["type"], sorted(valid_types))
            hint = f" Did you mean: {', '.join(suggestion)}?" if suggestion else f" Valid: {', '.join(sorted(valid_types))}."
            warnings.append(f"Unknown note type '{params['type']}'.{hint}")

    # ---- Related notes: warn on link targets that aren't known notes ----
    if isinstance(params.get("related_notes"), dict):
        for v in params["related_notes"].get("add", []):
            target_id = v.get("id", "") if isinstance(v, dict) else (v if isinstance(v, str) else "")
            if target_id and target_id not in index:
                suggestion = fuzzy_suggestions(target_id, list(index.keys()))
                hint = f" Did you mean: {', '.join(suggestion)}?" if suggestion else ""
                warnings.append(f"related_notes target '{target_id}' is not a known note -- link will be dangling.{hint}")

    # ---- Reclassification (library change) ----
    if "new_library" in params:
        new_lib = params["new_library"].strip()
        old_lib = row["library"]
        if new_lib and new_lib != old_lib:
            conn.execute("UPDATE notes SET library = ? WHERE id = ?", (new_lib, note_id))
            changes.append(f"library: reclassified from '{old_lib}' to '{new_lib}'")

    # ---- Lifecycle: validate against the Lifecycle enum before accepting ----
    # Invalid values would silently get written by the simple_fields path, so
    # we guard explicitly. Valid: active / stale / evergreen / dormant / archived
    # (see models.Lifecycle).
    if "lifecycle" in params:
        valid_lifecycles = {lc.value for lc in Lifecycle}
        new_lifecycle = params["lifecycle"]
        if new_lifecycle not in valid_lifecycles:
            return {"error": f"Invalid lifecycle '{new_lifecycle}'. Valid: {sorted(valid_lifecycles)}"}

    # ---- Simple scalar replacements ----
    simple_fields = {
        "type":                  "type",
        "source_quality":        "source_quality",
        "confidence":            "confidence",
        "lifecycle":             "lifecycle",
        "library_version":       "library_version",
        "review_interval_days":  "review_interval_days",
        "wrong_assumption":      "wrong_assumption",
        "correct_behavior":      "correct_behavior",
        "applies_to":            "applies_to",
    }
    for param_fld, db_fld in simple_fields.items():
        if param_fld in params:
            old_val = row[db_fld]
            new_val = params[param_fld]
            conn.execute(f"UPDATE notes SET {db_fld} = ? WHERE id = ?", (new_val, note_id))
            changes.append(f"{param_fld}: {old_val!r} -> {new_val!r}")

    # ---- Summary ----
    if "summary" in params:
        conn.execute("UPDATE notes SET summary = ? WHERE id = ?", (params["summary"], note_id))
        changes.append("summary: replaced")

    # ---- Notes body: full replacement ----
    if "notes" in params:
        new_body = params["notes"]
        # Also update notes_body_search
        topic = row["topic"]
        library = row["library"]
        context_prefix = "This note is about %s in %s" % (topic, library)
        search_body = (context_prefix + ". " + new_body)[:500]
        conn.execute("UPDATE notes SET notes_body = ?, notes_body_search = ? WHERE id = ?",
                     (new_body, search_body, note_id))
        changes.append("notes: replaced")

    # ---- Notes body: append ----
    if "notes_append" in params:
        existing_body = row["notes_body"]
        separator = "\n\n" if existing_body else ""
        new_body = existing_body + separator + params["notes_append"]
        topic = row["topic"]
        library = row["library"]
        context_prefix = "This note is about %s in %s" % (topic, library)
        search_body = (context_prefix + ". " + new_body)[:500]
        conn.execute("UPDATE notes SET notes_body = ?, notes_body_search = ? WHERE id = ?",
                     (new_body, search_body, note_id))
        changes.append("notes: appended")

    # ---- Cues (add/remove) ----
    if "cues" in params:
        spec = params["cues"]
        current_cues = [c.strip() for c in (row["cues_raw"] or "").split("\n") if c.strip()]
        to_add = spec.get("add", []) if isinstance(spec, dict) else []
        to_remove = spec.get("remove", []) if isinstance(spec, dict) else []
        added = [v for v in to_add if v not in current_cues]
        removed = [v for v in to_remove if v in current_cues]
        for v in added:
            current_cues.append(v)
        for v in removed:
            current_cues.remove(v)
        conn.execute("UPDATE notes SET cues_raw = ? WHERE id = ?",
                     ("\n".join(current_cues), note_id))
        if added:
            changes.append(f"cues: added {added}")
        if removed:
            changes.append(f"cues: removed {removed}")

    # ---- List add/remove for related tables ----
    list_field_handlers = {
        "tags": ("note_tags", "tag", "note_id"),
        "related_functions": ("note_functions", "function_name", "note_id"),
        "primitives_to_avoid": ("note_anti_patterns", "primitive_to_avoid", "note_id"),
        "preferred_alternatives": ("note_alternatives", "alternative", "note_id"),
    }

    for param_fld, (table, val_col, id_col) in list_field_handlers.items():
        if param_fld not in params:
            continue
        spec = params[param_fld]
        to_add = spec.get("add", []) if isinstance(spec, dict) else []
        to_remove = spec.get("remove", []) if isinstance(spec, dict) else []

        for v in to_add:
            conn.execute(f"INSERT OR IGNORE INTO {table} ({id_col}, {val_col}) VALUES (?, ?)",
                        (note_id, v))
        for v in to_remove:
            conn.execute(f"DELETE FROM {table} WHERE {id_col} = ? AND {val_col} = ?",
                        (note_id, v))

        added = to_add if to_add else []
        removed = to_remove if to_remove else []
        if added:
            changes.append(f"{param_fld}: added {added}")
        if removed:
            changes.append(f"{param_fld}: removed {removed}")

        # Keep tags_text column in sync for FTS5 indexing
        if param_fld == "tags" and (added or removed):
            current_tags = [r["tag"] for r in conn.execute(
                "SELECT tag FROM note_tags WHERE note_id = ?", (note_id,)).fetchall()]
            conn.execute("UPDATE notes SET tags_text = ? WHERE id = ?",
                         (" ".join(current_tags), note_id))

    # ---- Related notes (add/remove typed links) ----
    if "related_notes" in params:
        spec = params["related_notes"]
        to_add = spec.get("add", []) if isinstance(spec, dict) else []
        to_remove = spec.get("remove", []) if isinstance(spec, dict) else []

        affected_targets: list[str] = []
        for v in to_add:
            if isinstance(v, str):
                conn.execute("INSERT OR IGNORE INTO note_links VALUES (?, ?, ?)",
                            (note_id, v, "related"))
                affected_targets.append(v)
            elif isinstance(v, dict):
                tid = v.get("id", "")
                conn.execute("INSERT OR IGNORE INTO note_links VALUES (?, ?, ?)",
                            (note_id, tid, v.get("type", "related")))
                if tid:
                    affected_targets.append(tid)
        for v in to_remove:
            target = v if isinstance(v, str) else v.get("id", "") if isinstance(v, dict) else ""
            if target:
                conn.execute("DELETE FROM note_links WHERE source_id = ? AND target_id = ?",
                            (note_id, target))
                affected_targets.append(target)

        # Rebuild anchor text for affected link targets
        if affected_targets:
            _update_anchor_text_for(conn, affected_targets)

        if to_add:
            changes.append(f"related_notes: added {to_add}")
        if to_remove:
            changes.append(f"related_notes: removed {to_remove}")

    # ---- Sources: full replacement ----
    if "sources" in params:
        conn.execute("UPDATE notes SET sources_json = ? WHERE id = ?",
                     (json.dumps(params["sources"]), note_id))
        changes.append(f"sources: set to {len(params['sources'])} source(s)")

    # ---- mark_reviewed ----
    if params.get("mark_reviewed"):
        today = today_str()
        review_count = row["review_count"] + 1

        # Tier-based interval system
        _TIER_INTERVALS = {1: 14, 2: 30, 3: 60, 4: 120, 5: 365}
        current_tier = row["review_tier"] or 2
        miss_count = row["miss_count"]

        # Promote to next tier if no misses, reviewed enough, AND enough time has elapsed.
        # Time gate: at least 50% of the current tier interval must have passed since last_reviewed
        # to prevent racing to Tier 5 in a single session.
        if miss_count == 0 and review_count >= 2:
            elapsed_ok = True
            last_reviewed_str = row["last_reviewed"] or ""
            if last_reviewed_str:
                from datetime import date
                try:
                    last_reviewed_date = date.fromisoformat(last_reviewed_str)
                    days_elapsed = (date.fromisoformat(today) - last_reviewed_date).days
                    min_days = _TIER_INTERVALS.get(current_tier, 30) // 2
                    if days_elapsed < min_days:
                        elapsed_ok = False
                except (ValueError, TypeError):
                    pass  # If date parsing fails, allow promotion
            new_tier = min(current_tier + 1, 5)
            if elapsed_ok and new_tier != current_tier:
                current_tier = new_tier
                changes.append(f"review_tier: {row['review_tier']} -> {new_tier}")

        # Compute interval from tier with modifiers
        base_interval = _TIER_INTERVALS.get(current_tier, 30)

        conf = params.get("confidence") or row["confidence"]
        conf_mod = {"strong": 1.3, "maybe": 1.0, "weak": 0.7}.get(conf, 1.0)

        note_type = row["type"]
        type_mod = {
            "anti-pattern": 0.8, "correction": 0.8,
            "knowledge": 1.0, "technique": 1.0,
            "convention": 1.2, "reference": 1.2,
            "decision": 1.3, "finding": 1.0,
            "communication": 1.2, "commitment": 0.8,
            "requirement": 1.0,
        }.get(note_type, 1.0)

        miss_mod = 0.8 ** miss_count if miss_count > 0 else 1.0

        import random
        fuzz = random.uniform(0.95, 1.05)

        computed_interval = int(base_interval * conf_mod * type_mod * miss_mod * fuzz)
        computed_interval = max(7, computed_interval)

        lifecycle = row["lifecycle"]
        extra_updates = ""
        extra_params: list[Any] = []

        # Reset stale notes back to active
        if lifecycle == Lifecycle.STALE.value:
            extra_updates = ", lifecycle = ?, miss_count = 0, review_count = 0"
            extra_params = [Lifecycle.ACTIVE.value]
            review_count = 0
            changes.append("lifecycle: stale -> active (reset miss_count and review_count)")

        conn.execute(
            f"UPDATE notes SET last_reviewed = ?, review_count = ?, review_tier = ?, review_interval_days = ?{extra_updates} WHERE id = ?",
            [today, review_count, current_tier, computed_interval] + extra_params + [note_id]
        )
        changes.append(f"last_reviewed: {today}, review_count: {review_count}")
        changes.append(f"review_interval_days: {computed_interval} (tier {current_tier})")

    # ---- increment_miss ----
    if params.get("increment_miss"):
        reason = params.get("miss_reason", "unclassified")
        today  = today_str()

        new_miss_count = row["miss_count"] + 1
        miss_log = json.loads(row["miss_log_json"] or "[]")
        miss_log.append({"date": today, "reason": reason})

        _TIER_INTERVALS = {1: 14, 2: 30, 3: 60, 4: 120, 5: 365}
        current_tier = row["review_tier"] or 2

        if new_miss_count >= 3:
            conn.execute("""
                UPDATE notes SET miss_count = ?, miss_log_json = ?,
                    review_tier = 1, review_interval_days = 14, lifecycle = ?
                WHERE id = ?
            """, (new_miss_count, json.dumps(miss_log), Lifecycle.STALE.value, note_id))
            changes.append(f"miss_count: {new_miss_count}, review_tier: -> 1, lifecycle: -> stale")
        elif new_miss_count >= 2:
            new_tier = max(current_tier - 1, 1)
            interval = _TIER_INTERVALS.get(new_tier, 14)
            conn.execute("""
                UPDATE notes SET miss_count = ?, miss_log_json = ?,
                    review_tier = ?, review_interval_days = ?
                WHERE id = ?
            """, (new_miss_count, json.dumps(miss_log), new_tier, interval, note_id))
            changes.append(f"miss_count: {new_miss_count}, review_tier: -> {new_tier}")
        else:
            conn.execute("""
                UPDATE notes SET miss_count = ?, miss_log_json = ?,
                    review_interval_days = 30
                WHERE id = ?
            """, (new_miss_count, json.dumps(miss_log), note_id))
            changes.append(f"miss_count: {new_miss_count}, review_interval_days: -> 30")

    # ---- Always update last_modified ----
    conn.execute("UPDATE notes SET last_modified = ? WHERE id = ?", (today_str(), note_id))

    conn.commit()

    # Re-embed if content changed
    content_changed = any(k in params for k in ("notes", "notes_append", "summary"))
    if content_changed and EMBEDDINGS_AVAILABLE and encode_text is not None:
        updated_row = conn.execute(
            "SELECT topic, summary, notes_body FROM notes WHERE id = ?", (note_id,)
        ).fetchone()
        if updated_row:
            embed_text = f"{updated_row[0]} {updated_row[1]} {updated_row[2]}"
            vec_bytes = encode_text(embed_text)
            if vec_bytes is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO note_embeddings (note_id, model, dimensions, vector) VALUES (?, ?, ?, ?)",
                    (note_id, MODEL_NAME, DIMENSIONS, vec_bytes),
                )
                conn.commit()
                if invalidate_cache:
                    invalidate_cache()

    # Reload from DB into in-memory index
    entry_data = load_note_dict(conn, note_id)
    if entry_data:
        update_entry(index, note_id, entry_data)

    result: dict[str, Any] = {
        "id":      note_id,
        "changes": changes,
        "message": f"Updated note '{note_id}' ({len(changes)} change(s))",
    }
    if warnings:
        result["warnings"] = warnings
    return result


def delete_note(
    index: dict[str, Any],
    notemap_dir: Path,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Delete (soft or hard) a note.

    Soft delete sets lifecycle to 'archived'. Hard delete removes from DB.
    """
    note_id: str     = params["id"]
    reason: str      = params.get("reason", "")
    hard_delete: bool = params.get("hard_delete", False)

    if note_id not in index:
        return {"error": f"Note '{note_id}' not found."}

    conn = get_db(notemap_dir)

    if hard_delete:
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        conn.commit()
        if invalidate_cache:
            invalidate_cache()
        remove_entry(index, note_id)
        return {
            "id":      note_id,
            "action":  "hard_delete",
            "message": f"Permanently deleted note '{note_id}'",
        }

    # Soft delete: mark as archived
    conn.execute("UPDATE notes SET lifecycle = 'archived', last_modified = ? WHERE id = ?",
                 (today_str(), note_id))

    # Clean up related_notes references in other notes
    conn.execute("DELETE FROM note_links WHERE target_id = ?", (note_id,))

    conn.commit()
    if invalidate_cache:
        invalidate_cache()
    remove_entry(index, note_id)

    return {
        "id":      note_id,
        "action":  "archived",
        "message": f"Archived note '{note_id}'" + (f" (reason: {reason})" if reason else ""),
    }
