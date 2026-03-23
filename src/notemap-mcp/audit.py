"""Audit checks and review queue for the notemap system."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any


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
        entries = [(k, v) for k, v in entries if v.get("library") == library]

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
        integrity: dict[str, Any] = {"status": "ok", "indexed": len(index), "on_disk": 0}
        if notemap_dir.is_dir():
            disk_count = 0
            for md_file in notemap_dir.rglob("*.md"):
                rel = md_file.relative_to(notemap_dir)
                parts = rel.parts
                if parts and parts[0] == "_archive":
                    continue
                disk_count += 1
            integrity["on_disk"] = disk_count
            if len(index) != disk_count:
                integrity["status"] = "mismatch"
                total_issues += 1
        results["index_integrity"] = integrity

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
        if library and e.get("library") != library:
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


def _parse_date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, TypeError):
        return None
