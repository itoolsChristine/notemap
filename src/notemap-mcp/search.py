"""Search with relevance scoring for the notemap system."""
from __future__ import annotations

from typing import Any


def search_notes(index: dict[str, dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
    """Search the note index with filters and relevance scoring.

    Params (at least one required):
        query, library, function_name, tag, type, source_quality,
        confidence, lifecycle (default "active"), max_results (default 10)

    Returns a dict with count and results list.
    """
    query           = (params.get("query") or "").strip()
    library         = (params.get("library") or "").strip()
    function_name   = (params.get("function_name") or "").strip()
    tag             = (params.get("tag") or "").strip()
    note_type       = (params.get("type") or "").strip()
    source_quality  = (params.get("source_quality") or "").strip()
    confidence      = (params.get("confidence") or "").strip()
    lifecycle       = (params.get("lifecycle") or "active").strip()
    max_results     = int(params.get("max_results", 0))

    query_lower         = query.lower()
    query_words         = query_lower.split() if query else []
    function_name_lower = function_name.lower()

    results: list[dict[str, Any]] = []

    for note_id, entry in index.items():
        # Hard filters (AND-combined)
        if library and entry.get("library") != library:
            continue
        if note_type and entry.get("type") != note_type:
            continue
        if source_quality and entry.get("source_quality") != source_quality:
            continue
        if confidence and entry.get("confidence") != confidence:
            continue
        if tag and tag not in (entry.get("tags") or []):
            continue
        if lifecycle in ("active", "stale") and entry.get("lifecycle") != lifecycle:
            continue

        # Relevance scoring
        score: float = 0.0
        fn_matched = False
        q_matched  = False

        # function_name matching
        if function_name:
            related = entry.get("related_functions") or []
            if function_name in related:
                score += 100
                fn_matched = True
            else:
                for rf in related:
                    if function_name_lower in rf.lower():
                        score += 50
                        fn_matched = True
                        break
            if not fn_matched:
                continue

        # query matching -- word-level (each word scored independently)
        if query_words:
            topic_lower   = (entry.get("topic") or "").lower()
            summary_lower = (entry.get("summary") or "").lower()
            cues          = entry.get("cues") or []
            tags          = entry.get("tags") or []
            cues_lower    = " ".join(c.lower() for c in cues)
            tags_lower    = [t.lower() for t in tags]

            words_matched = 0
            for word in query_words:
                word_hit = False

                # Tag exact match (highest signal)
                if word in tags_lower:
                    score += 60
                    word_hit = True

                # Topic match
                if word in topic_lower:
                    score += 40
                    word_hit = True

                # Cue match
                if word in cues_lower:
                    score += 30
                    word_hit = True

                # Summary match
                if word in summary_lower:
                    score += 20
                    word_hit = True

                if word_hit:
                    words_matched += 1

            # Require at least one word to match
            if words_matched > 0:
                q_matched = True
                # Bonus for matching multiple words (phrase relevance)
                if len(query_words) > 1 and words_matched > 1:
                    score += words_matched * 15

            if not q_matched and not fn_matched:
                continue

        # Boosts
        if entry.get("source_quality") == "verified-from-source":
            score += 10
        if entry.get("confidence") == "strong":
            score += 10

        # Filter-only search (no query, no function_name)
        if not query_words and not function_name:
            score = 10

        results.append({
            "id":                note_id,
            "library":           entry.get("library", ""),
            "library_version":   entry.get("library_version", ""),
            "topic":             entry.get("topic", ""),
            "type":              entry.get("type", "knowledge"),
            "source_quality":    entry.get("source_quality", "unverified"),
            "confidence":        entry.get("confidence", "weak"),
            "lifecycle":         entry.get("lifecycle", "active"),
            "summary":           entry.get("summary", ""),
            "sources":           entry.get("sources", []),
            "related_functions": entry.get("related_functions", []),
            "relevance_score":   round(score, 2),
        })

    results.sort(key=lambda r: r["relevance_score"], reverse=True)
    if max_results > 0:
        results = results[:max_results]

    return {
        "count":   len(results),
        "results": results,
    }
