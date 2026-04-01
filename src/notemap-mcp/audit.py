"""Audit checks and review queue for the notemap system."""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any


def _library_matches(note_library: str, filter_library: str) -> bool:
    """Check if *note_library* matches *filter_library* (exact or child)."""
    if note_library == filter_library:
        return True
    return note_library.startswith(filter_library + "/")


def audit_notes(
    index: dict[str, dict[str, Any]],
    notemap_dir: Path,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Run audit checks against the note index."""
    check      = (params.get("check") or "all").strip()
    stale_days = params.get("stale_days")
    library    = (params.get("library") or "").strip()
    today      = date.today()

    entries = list(index.items())
    if library:
        entries = [(k, v) for k, v in entries if _library_matches(v.get("library", ""), library)]

    run_all = check == "all"
    results: dict[str, Any] = {}
    total_issues = 0

    # stale
    if run_all or check == "stale":
        stale_items: list[dict[str, Any]] = []
        for nid, e in entries:
            interval = int(stale_days) if stale_days is not None else (e.get("review_interval_days") or 30)
            last_reviewed = _parse_date(e.get("last_reviewed"))
            if last_reviewed is None:
                continue
            days_since = (today - last_reviewed).days
            if days_since > interval:
                stale_items.append({
                    "id": nid, "topic": e.get("topic", ""),
                    "library": e.get("library", ""),
                    "last_reviewed": e.get("last_reviewed", ""),
                    "days_overdue": days_since - interval,
                })
        results["stale"] = stale_items
        total_issues += len(stale_items)

    # low_confidence
    if run_all or check == "low_confidence":
        low_items: list[dict[str, Any]] = []
        for nid, e in entries:
            if e.get("confidence") == "weak" and e.get("source_quality") in ("inferred", "unverified"):
                low_items.append({
                    "id": nid, "topic": e.get("topic", ""),
                    "library": e.get("library", ""),
                    "source_quality": e.get("source_quality", ""),
                    "confidence": e.get("confidence", ""),
                })
        results["low_confidence"] = low_items
        total_issues += len(low_items)

    # unreviewed
    if run_all or check == "unreviewed":
        unreviewed_items: list[dict[str, Any]] = []
        for nid, e in entries:
            created = (e.get("created") or "").strip()
            reviewed = (e.get("last_reviewed") or "").strip()
            review_count = e.get("review_count", 0) or 0
            if created and reviewed and created == reviewed and review_count < 1:
                unreviewed_items.append({
                    "id": nid, "topic": e.get("topic", ""),
                    "library": e.get("library", ""),
                    "created": created,
                })
        results["unreviewed"] = unreviewed_items
        total_issues += len(unreviewed_items)

    # high_miss_count
    if run_all or check == "high_miss_count":
        high_items: list[dict[str, Any]] = []
        for nid, e in entries:
            if (e.get("miss_count") or 0) >= 2:
                high_items.append({
                    "id": nid, "topic": e.get("topic", ""),
                    "library": e.get("library", ""),
                    "miss_count": e.get("miss_count", 0),
                })
        results["high_miss_count"] = high_items
        total_issues += len(high_items)

    # orphaned_functions
    if run_all or check == "orphaned_functions":
        orphaned_items: list[dict[str, Any]] = []
        functionmap_root = Path.home() / ".claude" / "functionmap"
        for nid, e in entries:
            related = e.get("related_functions") or []
            if not related:
                continue
            lib_map_dir = functionmap_root / e.get("library", "")
            if not lib_map_dir.is_dir():
                continue
            map_text = _read_functionmap_text(lib_map_dir)
            for func in related:
                if func not in map_text:
                    orphaned_items.append({
                        "id": nid, "topic": e.get("topic", ""),
                        "library": e.get("library", ""),
                        "function": func,
                    })
        results["orphaned_functions"] = orphaned_items
        total_issues += len(orphaned_items)

    # index_integrity
    if run_all or check == "index_integrity":
        integrity: dict[str, Any] = {"status": "ok", "indexed": len(index), "in_db": 0}
        try:
            from db import get_db
            conn = get_db(notemap_dir)
            db_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            integrity["in_db"] = db_count
            if len(index) != db_count:
                integrity["status"] = "mismatch"
                total_issues += 1
        except Exception:
            integrity["in_db"] = -1
            integrity["status"] = "error"
            total_issues += 1
        results["index_integrity"] = integrity

    # source_changed
    if run_all or check == "source_changed":
        source_items: list[dict[str, Any]] = []
        for nid, e in entries:
            sources = e.get("sources") or []
            last_reviewed = e.get("last_reviewed", "")
            for src in sources:
                if not isinstance(src, dict) or src.get("type") != "file":
                    continue
                src_path = src.get("path", "")
                if not src_path:
                    continue
                full_path = Path(src_path)
                if not full_path.is_absolute():
                    continue  # Can't resolve relative paths without project context
                if full_path.exists():
                    file_mtime = full_path.stat().st_mtime
                    if last_reviewed:
                        reviewed_date = _parse_date(last_reviewed)
                        if reviewed_date:
                            reviewed_ts = time.mktime(reviewed_date.timetuple())
                            if file_mtime > reviewed_ts:
                                source_items.append({
                                    "id":          nid,
                                    "topic":       e.get("topic", ""),
                                    "library":     e.get("library", ""),
                                    "source_path": src_path,
                                    "reason":      "source file modified since last review",
                                })
                else:
                    source_items.append({
                        "id":          nid,
                        "topic":       e.get("topic", ""),
                        "library":     e.get("library", ""),
                        "source_path": src_path,
                        "reason":      "source file not found",
                    })
        results["source_changed"] = source_items
        total_issues += len(source_items)

    # density
    if run_all or check == "density":
        lib_counts: dict[str, int] = {}
        for nid, e in entries:
            lib = e.get("library", "")
            lib_counts[lib] = lib_counts.get(lib, 0) + 1

        density_items: list[dict[str, Any]] = []
        if lib_counts:
            counts = list(lib_counts.values())
            mean_count = sum(counts) / len(counts)
            if len(counts) > 1:
                variance = sum((c - mean_count) ** 2 for c in counts) / len(counts)
                stddev = variance ** 0.5
            else:
                stddev = 0

            threshold = mean_count + 2 * stddev if stddev > 0 else mean_count * 2
            for lib, count in lib_counts.items():
                if count > threshold and count > 10:
                    density_items.append({
                        "library":   lib,
                        "count":     count,
                        "mean":      round(mean_count, 1),
                        "threshold": round(threshold, 1),
                    })
        results["density"] = density_items
        total_issues += len(density_items)

    # consolidation
    if run_all or check == "consolidation":
        consolidation_items: list[dict[str, Any]] = []
        by_lib: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for nid, e in entries:
            lib = e.get("library", "")
            by_lib.setdefault(lib, []).append((nid, e))

        for lib, notes_list in by_lib.items():
            if len(notes_list) < 3:
                continue
            for i, (nid_a, e_a) in enumerate(notes_list):
                topic_a = (e_a.get("topic") or "").lower().split()
                if len(topic_a) < 3:
                    continue
                for nid_b, e_b in notes_list[i + 1:]:
                    topic_b = (e_b.get("topic") or "").lower().split()
                    if len(topic_b) < 3:
                        continue
                    overlap = len(set(topic_a) & set(topic_b))
                    min_len = min(len(topic_a), len(topic_b))
                    if min_len > 0 and overlap / min_len > 0.6:
                        consolidation_items.append({
                            "note_a":        nid_a,
                            "note_b":        nid_b,
                            "library":       lib,
                            "overlap_ratio": round(overlap / min_len, 2),
                            "topic_a":       e_a.get("topic", ""),
                            "topic_b":       e_b.get("topic", ""),
                        })
        results["consolidation"] = consolidation_items
        total_issues += len(consolidation_items)

    # leech
    if run_all or check == "leech":
        leech_items: list[dict[str, Any]] = []
        for nid, e in entries:
            mc = e.get("miss_count", 0)
            rc = max(e.get("review_count", 1), 1)
            if mc > 0 and mc / rc > 0.5:
                leech_items.append({
                    "id": nid, "topic": e.get("topic", ""),
                    "library": e.get("library", ""),
                    "miss_count": mc,
                    "review_count": rc,
                    "miss_ratio": round(mc / rc, 2),
                })
        results["leech"] = leech_items
        total_issues += len(leech_items)

    # orphan
    if run_all or check == "orphan":
        orphan_items: list[dict[str, Any]] = []
        from index import get_backlink_index
        backlinks = get_backlink_index()
        for nid, e in entries:
            related = e.get("related_notes") or []
            incoming = backlinks.get(nid, [])
            if len(related) == 0 and len(incoming) == 0:
                created = _parse_date(e.get("created"))
                if created and (today - created).days > 30:
                    orphan_items.append({
                        "id": nid,
                        "topic": e.get("topic", ""),
                        "library": e.get("library", ""),
                        "days_old": (today - created).days,
                    })
        results["orphan"] = orphan_items
        total_issues += len(orphan_items)

    # confidence_decay
    if run_all or check == "confidence_decay":
        apply_decay = bool(params.get("apply_decay", False))
        decay_items: list[dict[str, Any]] = []
        decay_applied = 0
        for nid, e in entries:
            new_conf = _check_confidence_decay(e, today)
            if new_conf:
                last_rev = _parse_date(e.get("last_reviewed"))
                ds = (today - last_rev).days if last_rev else 0
                decay_items.append({
                    "id": nid, "topic": e.get("topic", ""),
                    "library": e.get("library", ""),
                    "current_confidence": e.get("confidence", "maybe"),
                    "suggested_confidence": new_conf,
                    "days_since_review": ds,
                    "review_interval": e.get("review_interval_days", 30),
                })
                if apply_decay:
                    try:
                        from db import get_db
                        conn = get_db(notemap_dir)
                        conn.execute(
                            "UPDATE notes SET confidence = ?, last_modified = ? WHERE id = ?",
                            (new_conf, today.isoformat(), nid),
                        )
                        conn.commit()
                        e["confidence"] = new_conf
                        decay_applied += 1
                    except Exception:
                        pass
        results["confidence_decay"] = decay_items
        results["confidence_decay_applied"] = decay_applied
        total_issues += len(decay_items)

    return {"total_issues": total_issues, **results}


def review_queue(
    index: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Build a prioritized review queue."""
    library = (params.get("library") or "").strip()
    limit   = int(params.get("limit", 0))
    today   = date.today()

    scored: list[dict[str, Any]] = []

    for nid, e in index.items():
        if library and not _library_matches(e.get("library", ""), library):
            continue

        # Skip notes exempt from review scheduling
        if e.get("lifecycle") in ("evergreen", "dormant", "archived"):
            continue

        score   = 0.0
        reasons: list[str] = []

        if e.get("source_quality") in ("unverified", "inferred"):
            score += 40
            reasons.append(f"source_quality: {e.get('source_quality')}")

        if e.get("confidence") == "weak":
            score += 50
            reasons.append("confidence: weak")

        last_reviewed = _parse_date(e.get("last_reviewed"))
        if last_reviewed is not None:
            days_since = (today - last_reviewed).days
            interval = e.get("review_interval_days") or 30
            if days_since > interval:
                overdue = days_since - interval
                score += overdue * 2
                reasons.append(f"{overdue} days overdue")

        created_str  = (e.get("created") or "").strip()
        reviewed_str = (e.get("last_reviewed") or "").strip()
        if created_str and reviewed_str and created_str == reviewed_str:
            score += 30
            reasons.append("never reviewed since creation")

        mc = e.get("miss_count") or 0
        if mc > 0:
            score += mc * 20
            reasons.append(f"miss_count: {mc}")

        if e.get("lifecycle") == "stale":
            score += 60
            reasons.append("lifecycle: stale")

        # Tier-1 urgency (unproven/demoted notes)
        tier = e.get("review_tier", 2)
        if tier <= 1:
            score += 20
            reasons.append("tier 1 (unproven)")

        # Leech scoring
        rc = max(e.get("review_count", 1), 1)
        if mc > 0 and mc / rc > 0.5:
            score += 30
            reasons.append(f"leech (miss_ratio: {mc/rc:.2f})")

        if score <= 0:
            continue

        scored.append({
            "id": nid, "topic": e.get("topic", ""),
            "library": e.get("library", ""),
            "type": e.get("type", "knowledge"),
            "source_quality": e.get("source_quality", ""),
            "confidence": e.get("confidence", ""),
            "priority_score": score,
            "reasons": reasons,
            "summary": e.get("summary", ""),
        })

    scored.sort(key=lambda x: x["priority_score"], reverse=True)
    queue = scored[:limit] if limit > 0 else scored

    return {"queue": queue, "total_due": len(scored), "showing": len(queue)}


_functionmap_cache: dict[str, str] = {}


def _read_functionmap_text(lib_map_dir: Path) -> str:
    key = str(lib_map_dir)
    if key in _functionmap_cache:
        return _functionmap_cache[key]
    parts: list[str] = []
    if lib_map_dir.is_dir():
        for md_file in lib_map_dir.rglob("*.md"):
            try:
                parts.append(md_file.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    combined = "\n".join(parts)
    _functionmap_cache[key] = combined
    return combined


def _check_confidence_decay(entry: dict[str, Any], ref_date: date) -> str | None:
    """Check if a note's confidence should decay due to staleness.

    Returns the new confidence level, or None if no change needed.
    """
    last_reviewed = _parse_date(entry.get("last_reviewed"))
    if not last_reviewed:
        return None

    days_since = (ref_date - last_reviewed).days
    interval = entry.get("review_interval_days", 30)
    confidence = entry.get("confidence", "maybe")

    if confidence == "strong" and days_since > 2 * interval:
        return "maybe"
    if confidence == "maybe" and days_since > 3 * interval:
        return "weak"
    return None


def _parse_date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, TypeError):
        return None
