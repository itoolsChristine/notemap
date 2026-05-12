"""Search with relevance scoring for the notemap system.

Uses SQLite FTS5 for full-text search recall, with a Python re-ranking pass
for quality signals (freshness, confidence, source quality, behavioral).
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from db import get_db

# Embedding support -- graceful degradation when model2vec is not installed
try:
    from embed import (
        EMBEDDINGS_AVAILABLE,
        encode_texts,
        load_embedding_matrix,
        vector_search as _vector_search,
        invalidate_cache,
    )
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    encode_texts = None
    load_embedding_matrix = None
    _vector_search = None
    invalidate_cache = None

# Common English stop words for pseudo-relevance feedback filtering
_STOP_WORDS = frozenset({
    "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
    "her", "was", "one", "our", "out", "has", "have", "been", "when", "who",
    "will", "more", "with", "from", "that", "this", "than", "its", "also",
    "into", "just", "only", "some", "such", "use", "used", "using",
})

# Topic/library alias normalization
_ALIASES: dict[str, str] = {
    "js":           "javascript",
    "ts":           "typescript",
    "py":           "python",
    "rb":           "ruby",
    "cs":           "csharp",
    "cpp":          "cplusplus",
    "smart_string": "smartstring",
    "smart_array":  "smartarray",
    "zen_db":       "zendb",
}


def _normalize_alias(word: str) -> str:
    """Normalize a single word through the alias table."""
    return _ALIASES.get(word, word)


def _is_code_query(query: str) -> bool:
    """Detect if query looks like a code/function lookup vs natural language."""
    code_patterns = [
        r'::', r'\(\)', r'->', r'\.\w+\(',  # method calls
        r'[a-z][a-zA-Z]+[A-Z]',  # camelCase
        r'\w+_\w+\(',  # snake_case function call
        r'\$\w+',  # variables
        r'(?:function|class|def|var|let|const)\s',  # language keywords
    ]
    return any(re.search(p, query) for p in code_patterns)


def reciprocal_rank_fusion(
    ranked_lists: list[list[tuple[str, float]]],
    k: int = 60,
    weights: list[float] | None = None,
) -> list[tuple[str, float]]:
    """Merge multiple ranked result lists using Reciprocal Rank Fusion.

    Each list is [(id, score), ...] sorted by score desc.
    Optional weights per list (default: equal).
    Returns merged list sorted by RRF score desc.
    """
    if weights is None:
        weights = [1.0] * len(ranked_lists)
    scores: dict[str, float] = {}
    for w, ranked in zip(weights, ranked_lists):
        for rank, (item_id, _score) in enumerate(ranked):
            scores[item_id] = scores.get(item_id, 0.0) + w * (1.0 / (k + rank + 1))
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def _library_matches(note_library: str, filter_library: str) -> bool:
    """Check if *note_library* matches *filter_library* (exact or child)."""
    if note_library == filter_library:
        return True
    return note_library.startswith(filter_library + "/")


def _lifecycle_excluded(entry_lifecycle: str, filter_lifecycle: str) -> bool:
    """Return True when a note should be filtered out for the given lifecycle filter.

    "active" surfaces both active and evergreen notes (evergreen = permanently
    relevant, never goes stale -- preflight already treats it this way, so search
    must too or evergreen notes vanish from results and from RAG auto-injection).
    "stale" is exact. Any other filter value disables lifecycle filtering entirely
    (escape hatch -- e.g. lifecycle="archived" to reach archived notes).
    """
    if filter_lifecycle == "active":
        return entry_lifecycle not in ("active", "evergreen")
    if filter_lifecycle == "stale":
        return entry_lifecycle != "stale"
    return False


def _escape_fts5_query(query: str) -> str:
    """Escape special FTS5 characters and build a safe query string.

    FTS5 treats certain characters as operators. We escape them to prevent
    syntax errors while preserving basic word matching. For multi-word queries,
    includes a phrase match attempt (highest relevance) alongside individual
    word matches.
    """
    # Remove FTS5 operators and special characters (but not double quotes yet)
    cleaned = re.sub(r"[:\(\)\*\+\-'{}]", ' ', query)
    # Now strip any user-provided double quotes
    cleaned = cleaned.replace('"', ' ')
    # Collapse whitespace
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    if not cleaned:
        return '""'
    words = cleaned.split()
    if len(words) == 1:
        return words[0]
    # Phrase match (highest relevance) plus individual word OR fallbacks
    phrase = '"' + " ".join(words) + '"'
    return phrase + " OR " + " OR ".join(words)


def _generate_snippet(text: str, query_words: list[str], max_chars: int = 200) -> str:
    """Extract the most relevant passage containing query terms."""
    if not text or not query_words:
        return ""

    sentences = [s.strip() for s in text.replace("\n", ". ").split(". ") if s.strip()]
    if not sentences:
        return text[:max_chars]

    scored: list[tuple[int, str]] = []
    for sent in sentences:
        sent_lower = sent.lower()
        hits = sum(1 for w in query_words if w in sent_lower)
        if hits > 0:
            scored.append((hits, sent))

    if not scored:
        return sentences[0][:max_chars] if sentences else ""

    scored.sort(reverse=True)
    result_parts: list[str] = []
    length = 0
    for _, sent in scored:
        if length + len(sent) > max_chars:
            break
        result_parts.append(sent)
        length += len(sent)

    return " ... ".join(result_parts) if result_parts else scored[0][1][:max_chars]


def _pseudo_relevance_feedback(
    conn: sqlite3.Connection,
    query_words: list[str],
    max_expansion_terms: int = 3,
) -> list[tuple[str, float]]:
    """Expand a query via pseudo-relevance feedback when FTS5 returns 0 results.

    Runs a relaxed OR query of individual terms, extracts distinctive terms
    from the top 3 results' topic/summary/tags, and re-runs FTS5 with an
    expanded query combining original + expansion terms.

    Returns list of (note_id, inverted_bm25_score) or empty list on failure.
    """
    if len(query_words) < 1:
        return []

    # Step 1: relaxed OR query of individual terms
    relaxed_query = " OR ".join(query_words)
    try:
        relaxed_rows = conn.execute("""
            SELECT n.id, n.topic, n.summary, n.tags_text,
                   bm25(notes_fts, 0, 3.0, 1.5, 1.0, 2.0, 1.0, 3.0) as relevance
            FROM notes_fts
            JOIN notes n ON n.rowid = notes_fts.rowid
            WHERE notes_fts MATCH ?
            ORDER BY relevance
            LIMIT 3
        """, (relaxed_query,)).fetchall()
    except (sqlite3.OperationalError, Exception):
        return []

    if not relaxed_rows:
        return []

    # Step 2: extract distinctive terms from top results
    query_word_set = set(query_words)
    term_freq: dict[str, int] = {}
    for row in relaxed_rows:
        text = " ".join(filter(None, [row["topic"], row["summary"], row["tags_text"]]))
        for word in re.split(r'\W+', text.lower()):
            if len(word) < 3:
                continue
            if word in _STOP_WORDS or word in query_word_set:
                continue
            term_freq[word] = term_freq.get(word, 0) + 1

    # Step 3: pick top expansion terms by frequency
    expansion_terms = sorted(term_freq, key=lambda w: term_freq[w], reverse=True)[:max_expansion_terms]
    if not expansion_terms:
        return []

    # Step 4: build expanded query and re-run FTS5
    expanded_query = " OR ".join(query_words + expansion_terms)
    try:
        expanded_rows = conn.execute("""
            SELECT n.id, bm25(notes_fts, 0, 3.0, 1.5, 1.0, 2.0, 1.0, 3.0) as relevance
            FROM notes_fts
            JOIN notes n ON n.rowid = notes_fts.rowid
            WHERE notes_fts MATCH ?
            ORDER BY relevance
            LIMIT 100
        """, (expanded_query,)).fetchall()
    except (sqlite3.OperationalError, Exception):
        return []

    return [(row["id"], -row["relevance"]) for row in expanded_rows]


def _split_code_query(query: str) -> list[str]:
    """Split a code-style query into variant search terms.

    Handles ::, ->, ., camelCase, and underscores. Returns 2-3 variants
    suitable for individual FTS5 queries, or empty list if not a code query.
    """
    variants: list[str] = []

    # Split on :: -> .
    if '::' in query or '->' in query or ('.' in query and not query.endswith('.')):
        parts = re.split(r'::|->|\.', query)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) >= 2:
            # Individual parts as separate queries
            variants.append(" ".join(parts))
            for p in parts:
                if len(p) >= 2:
                    variants.append(p)

    # Split camelCase
    camel_parts = re.sub(r'([a-z])([A-Z])', r'\1 \2', query).split()
    if len(camel_parts) >= 2:
        variants.append(" ".join(w.lower() for w in camel_parts))

    # Split underscores
    if '_' in query:
        underscore_parts = [p for p in query.split('_') if p]
        if len(underscore_parts) >= 2:
            variants.append(" ".join(underscore_parts))

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for v in variants:
        v_lower = v.lower().strip()
        if v_lower and v_lower not in seen and v_lower != query.lower().strip():
            seen.add(v_lower)
            unique.append(v_lower)

    return unique[:3]


def _multi_query_expansion(
    conn: sqlite3.Connection,
    query: str,
    query_words: list[str],
    existing_count: int,
) -> list[tuple[str, float]]:
    """Expand code-style queries into variants and merge results via RRF.

    Only triggers when the query looks like a code identifier (contains ::,
    ->, ., camelCase, or underscores) AND initial results are sparse (0-1).

    Returns merged (note_id, rrf_score) list, or empty list if not applicable.
    """
    if existing_count > 1:
        return []

    variants = _split_code_query(query)
    if not variants:
        return []

    ranked_lists: list[list[tuple[str, float]]] = []

    for variant in variants:
        fts_query = _escape_fts5_query(variant)
        try:
            rows = conn.execute("""
                SELECT n.id, bm25(notes_fts, 0, 3.0, 1.5, 1.0, 2.0, 1.0, 3.0) as relevance
                FROM notes_fts
                JOIN notes n ON n.rowid = notes_fts.rowid
                WHERE notes_fts MATCH ?
                ORDER BY relevance
                LIMIT 20
            """, (fts_query,)).fetchall()
            if rows:
                ranked_lists.append([(r["id"], -r["relevance"]) for r in rows])
        except (sqlite3.OperationalError, Exception):
            continue

    if not ranked_lists:
        return []

    return reciprocal_rank_fusion(ranked_lists)


def _rerank_results(results: list[dict[str, Any]], index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-rank results with quality and behavioral signals.

    Pass 2 of two-pass retrieval. Normalizes scores to 0-1 range, then
    combines with freshness, confidence, source quality, behavioral signals,
    and PageRank graph authority.
    """
    if not results:
        return results

    from datetime import date

    # PageRank scores -- graceful degradation if index module not ready
    try:
        from index import get_pagerank_scores
        pr_scores = get_pagerank_scores()
    except (ImportError, Exception):
        pr_scores = {}

    max_score = max(r["relevance_score"] for r in results)
    if max_score == 0:
        max_score = 1.0

    for r in results:
        note_id = r["id"]
        entry = index.get(note_id, {})

        text_rel = r["relevance_score"] / max_score

        freshness = 0.5
        last_reviewed = entry.get("last_reviewed", "")
        if last_reviewed:
            try:
                reviewed_date = date.fromisoformat(last_reviewed)
                days_ago = (date.today() - reviewed_date).days
                freshness = 1.0 / (1.0 + days_ago / 365.0)
            except (ValueError, TypeError):
                pass

        conf_map   = {"strong": 1.0, "maybe": 0.7, "weak": 0.4}
        confidence = conf_map.get(entry.get("confidence", "maybe"), 0.7)

        qual_map = {
            "verified-from-source": 1.0,
            "runtime-tested":      0.85,
            "documented":          0.7,
            "function-map":        0.6,
            "user-correction":     0.55,
            "inferred":            0.4,
            "unverified":          0.3,
        }
        source_qual = qual_map.get(entry.get("source_quality", "unverified"), 0.3)

        retrieval_count = entry.get("retrieval_count", 0)
        miss_count      = entry.get("miss_count", 0)
        retrieval_signal = retrieval_count / (retrieval_count + 10.0) if retrieval_count > 0 else 0.0
        miss_penalty = 1.0 / (1.0 + miss_count * 0.3) if miss_count > 0 else 1.0
        behavior = retrieval_signal * miss_penalty

        pagerank = pr_scores.get(note_id, 0.0) if pr_scores else 0.0

        lifecycle_mult = 0.7 if entry.get("lifecycle") == "stale" else 1.0

        final = (
            0.55 * text_rel
            + 0.05 * pagerank
            + 0.10 * freshness
            + 0.10 * confidence
            + 0.10 * source_qual
            + 0.10 * behavior
        ) * lifecycle_mult

        r["relevance_score"] = round(final, 4)

    results.sort(key=lambda r: r["relevance_score"], reverse=True)
    return results


def _has_phrase_match(text: str, query_words: list[str]) -> bool:
    """Check if query_words appear as a consecutive phrase in text."""
    if len(query_words) < 2:
        return False
    text_lower = text.lower()
    phrase = " ".join(query_words)
    return phrase in text_lower


def search_notes(index: dict[str, dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
    """Search the note index with filters and relevance scoring.

    Uses FTS5 for text search when a query is provided, falls back to
    dict iteration for filter-only searches.
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
    use_embeddings  = bool(params.get("use_embeddings", True))
    include_chunks  = bool(params.get("include_chunks", False))

    # A search with no query and no filters would just dump the whole index --
    # bounded now, but not what anyone means. Ask for at least one constraint.
    # (A non-default lifecycle, e.g. "stale"/"archived", counts as a constraint.)
    has_constraint = bool(query or function_name or tag or note_type or source_quality or confidence or library) or lifecycle != "active"
    if not has_constraint:
        return {
            "count": 0,
            "results": [],
            "error": "specify at least one of: query, library, function_name, tag, type, source_quality, confidence",
            "hint": "use notemap_stats to see what's in the knowledge base, or notemap_preflight to load a library",
        }

    query_lower         = query.lower()
    query_words         = [_normalize_alias(w) for w in query_lower.split()] if query else []
    function_name_lower = function_name.lower()

    if library:
        library = _normalize_alias(library)

    results: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # FTS5-accelerated path: when a text query is provided
    # ------------------------------------------------------------------
    if query_words:
        fts_query = _escape_fts5_query(query_lower)
        try:
            from index import get_notemap_dir
            conn = get_db(get_notemap_dir())

            # FTS5 search with weighted bm25 scoring
            # Weights: id=0, topic=3.0, summary=1.5, notes_body=1.0, cues_raw=2.0, anchor_text=1.0, tags_text=3.0
            fts_rows = conn.execute("""
                SELECT n.id, bm25(notes_fts, 0, 3.0, 1.5, 1.0, 2.0, 1.0, 3.0) as relevance
                FROM notes_fts
                JOIN notes n ON n.rowid = notes_fts.rowid
                WHERE notes_fts MATCH ?
                ORDER BY relevance
                LIMIT 100
            """, (fts_query,)).fetchall()

            fts_ids = set()
            fts_scores: dict[str, float] = {}
            for row in fts_rows:
                rid = row["id"]
                # bm25 returns negative scores (lower = more relevant), invert them
                fts_scores[rid] = -row["relevance"]
                fts_ids.add(rid)

        except (sqlite3.OperationalError, Exception):
            # Fall back to dict-based search if FTS fails
            fts_ids = set()
            fts_scores = {}
            conn = None

        # Pseudo-relevance feedback: expand query when FTS returns nothing
        if not fts_ids and conn is not None and len(query_words) >= 1:
            prf_results = _pseudo_relevance_feedback(conn, query_words)
            for rid, score in prf_results:
                fts_scores[rid] = score
                fts_ids.add(rid)

        # Multi-query expansion: split code-style queries when results are sparse
        if conn is not None and len(fts_ids) <= 1:
            mqe_results = _multi_query_expansion(conn, query, query_words, len(fts_ids))
            for rid, score in mqe_results:
                if rid not in fts_scores:
                    fts_scores[rid] = score
                    fts_ids.add(rid)

        # Now filter and score the FTS results plus any dict-based matches
        for note_id, entry in index.items():
            # Hard filters
            if library:
                main_lib = entry.get("library", "")
                additional = entry.get("additional_topics") or []
                if not _library_matches(main_lib, library) and not any(_library_matches(t, library) for t in additional):
                    continue
            if note_type and entry.get("type") != note_type:
                continue
            if source_quality and entry.get("source_quality") != source_quality:
                continue
            if confidence and entry.get("confidence") != confidence:
                continue
            if tag and tag not in (entry.get("tags") or []):
                continue
            if _lifecycle_excluded(entry.get("lifecycle", "active"), lifecycle):
                continue

            # function_name matching
            fn_matched = False
            if function_name:
                related = entry.get("related_functions") or []
                if function_name in related:
                    fn_matched = True
                else:
                    for rf in related:
                        if function_name_lower in rf.lower():
                            fn_matched = True
                            break
                if not fn_matched:
                    continue

            # Score from FTS5 or dict-based matching
            score: float = 0.0

            if note_id in fts_scores:
                score = fts_scores[note_id]
            else:
                # Dict-based fallback for notes not in FTS results
                # (handles cases where FTS tokenizer misses something)
                topic_lower   = (entry.get("topic") or "").lower()
                summary_lower = (entry.get("summary") or "").lower()
                cues_lower    = " ".join(c.lower() for c in (entry.get("cues") or []))
                tags_lower    = [t.lower() for t in (entry.get("tags") or [])]
                body_lower    = (entry.get("notes_body") or "").lower()
                anchor_lower  = (entry.get("anchor_text") or "").lower()

                words_matched = 0
                for word in query_words:
                    word_hit = False
                    if word in tags_lower:
                        score += 60
                        word_hit = True
                    if word in topic_lower:
                        score += 40
                        word_hit = True
                    if word in cues_lower:
                        score += 30
                        word_hit = True
                    if word in summary_lower:
                        score += 20
                        word_hit = True
                    if word in anchor_lower:
                        score += 15
                        word_hit = True
                    if word in body_lower:
                        score += 10
                        word_hit = True
                    if word_hit:
                        words_matched += 1

                if words_matched == 0 and not fn_matched:
                    continue

                if len(query_words) > 1 and words_matched > 1:
                    score += words_matched * 15

            # function_name score boost
            if function_name:
                related = entry.get("related_functions") or []
                if function_name in related:
                    score += 100
                else:
                    for rf in related:
                        if function_name_lower in rf.lower():
                            score += 50
                            break

            # Phrase matching boost
            if len(query_words) >= 2 and score > 0:
                for field_name in ("topic", "summary"):
                    if _has_phrase_match(entry.get(field_name, ""), query_words):
                        score *= 1.5
                        break
                else:
                    cues_text = " ".join(entry.get("cues") or [])
                    if _has_phrase_match(cues_text, query_words):
                        score *= 1.3

            # Quality boosts
            if entry.get("source_quality") == "verified-from-source":
                score += 10
            if entry.get("confidence") == "strong":
                score += 10

            if score <= 0 and not fn_matched:
                continue

            snippet = ""
            if query_words:
                combined_text = " ".join(filter(None, [
                    entry.get("topic", ""),
                    entry.get("summary", ""),
                    " ".join(entry.get("cues") or []),
                ]))
                snippet = _generate_snippet(combined_text, query_words)

            result_entry: dict[str, Any] = {
                "id":                     note_id,
                "library":                entry.get("library", ""),
                "library_version":        entry.get("library_version", ""),
                "topic":                  entry.get("topic", ""),
                "type":                   entry.get("type", "knowledge"),
                "source_quality":         entry.get("source_quality", "unverified"),
                "confidence":             entry.get("confidence", "weak"),
                "lifecycle":              entry.get("lifecycle", "active"),
                "summary":                entry.get("summary", ""),
                "sources":                entry.get("sources", []),
                "related_functions":      entry.get("related_functions", []),
                "relevance_score":        round(score, 2),
                "cues_raw":               "\n".join(entry.get("cues") or []),
                "primitives_to_avoid":    entry.get("primitives_to_avoid", []),
                "preferred_alternatives": entry.get("preferred_alternatives", []),
                "wrong_assumption":       entry.get("wrong_assumption", ""),
                "correct_behavior":       entry.get("correct_behavior", ""),
            }
            if snippet:
                result_entry["snippet"] = snippet
            results.append(result_entry)

        # Entry-point boost
        if function_name:
            try:
                from index import get_entry_points
                entry_points = get_entry_points()
                ep_notes = entry_points.get(function_name_lower, [])
                for r in results:
                    if r["id"] in ep_notes:
                        r["relevance_score"] *= 1.2
            except ImportError:
                pass

        results = _rerank_results(results, index)

        # --------------------------------------------------------------
        # Hybrid merge: combine BM25F results with vector search via RRF
        # --------------------------------------------------------------
        if use_embeddings and EMBEDDINGS_AVAILABLE and query:
            try:
                from index import get_notemap_dir as _get_nm_dir
                vec_conn = get_db(_get_nm_dir())
                cache = load_embedding_matrix(vec_conn)
                if cache is not None:
                    note_ids_vec, matrix = cache
                    vec_results = _vector_search(
                        query, note_ids_vec, matrix,
                        top_k=(max_results * 2) if max_results > 0 else 40,
                    )
                    # Build BM25F ranked list from existing results
                    bm25_ranked = [
                        (r["id"], r.get("relevance_score", 1.0 / (i + 1)))
                        for i, r in enumerate(results)
                    ]
                    # Adaptive RRF: code queries favor BM25F, knowledge queries favor vectors
                    is_code = _is_code_query(query)
                    rrf_k = 60 if is_code else 20
                    rrf_weights = [1.0, 1.0] if is_code else [0.5, 1.5]
                    merged = reciprocal_rank_fusion([bm25_ranked, vec_results], k=rrf_k, weights=rrf_weights)
                    # Reorder results by RRF score, including vector-only candidates
                    result_map = {r["id"]: r for r in results}
                    reordered: list[dict[str, Any]] = []
                    limit = max_results if max_results > 0 else len(merged)
                    for note_id, rrf_score in merged[:limit]:
                        if note_id in result_map:
                            entry = result_map[note_id]
                            entry["_rrf_score"] = rrf_score
                            reordered.append(entry)
                        elif note_id in index:
                            # Vector-only candidate: BM25F missed it due to vocabulary gap
                            vec_entry = index[note_id]
                            if library:
                                main_lib = vec_entry.get("library", "")
                                additional = vec_entry.get("additional_topics") or []
                                if not _library_matches(main_lib, library) and not any(_library_matches(t, library) for t in additional):
                                    continue
                            if note_type and vec_entry.get("type") != note_type:
                                continue
                            if source_quality and vec_entry.get("source_quality") != source_quality:
                                continue
                            if confidence and vec_entry.get("confidence") != confidence:
                                continue
                            if tag and tag not in (vec_entry.get("tags") or []):
                                continue
                            if _lifecycle_excluded(vec_entry.get("lifecycle", "active"), lifecycle):
                                continue
                            reordered.append({
                                "id":                     note_id,
                                "library":                vec_entry.get("library", ""),
                                "library_version":        vec_entry.get("library_version", ""),
                                "topic":                  vec_entry.get("topic", ""),
                                "type":                   vec_entry.get("type", "knowledge"),
                                "source_quality":         vec_entry.get("source_quality", "unverified"),
                                "confidence":             vec_entry.get("confidence", "weak"),
                                "lifecycle":              vec_entry.get("lifecycle", "active"),
                                "summary":                vec_entry.get("summary", ""),
                                "sources":                vec_entry.get("sources", []),
                                "related_functions":      vec_entry.get("related_functions", []),
                                "relevance_score":        0.0,
                                "_rrf_score":             rrf_score,
                                "cues_raw":               "\n".join(vec_entry.get("cues") or []),
                                "primitives_to_avoid":    vec_entry.get("primitives_to_avoid", []),
                                "preferred_alternatives": vec_entry.get("preferred_alternatives", []),
                                "wrong_assumption":       vec_entry.get("wrong_assumption", ""),
                                "correct_behavior":       vec_entry.get("correct_behavior", ""),
                            })
                    # Use reordered if it produced results
                    if reordered:
                        results = reordered
            except Exception:
                pass  # Fall back to BM25F-only results

        # Cue-query overlap boost (re-rank by cue affinity)
        query_word_set = set(query_words)
        for r in results:
            note_entry = index.get(r["id"], {})
            cues_text = " ".join(note_entry.get("cues") or [])
            if cues_text and len(query_word_set) >= 2:
                cue_words = set(cues_text.lower().split())
                overlap = len(query_word_set & cue_words)
                if overlap >= 2:
                    score_key = "_rrf_score" if "_rrf_score" in r else "relevance_score"
                    r[score_key] = r.get(score_key, 0) * (1.0 + overlap * 0.1)

    # ------------------------------------------------------------------
    # Filter-only path (no text query)
    # ------------------------------------------------------------------
    elif function_name:
        for note_id, entry in index.items():
            if library:
                main_lib = entry.get("library", "")
                additional = entry.get("additional_topics") or []
                if not _library_matches(main_lib, library) and not any(_library_matches(t, library) for t in additional):
                    continue
            if note_type and entry.get("type") != note_type:
                continue
            if source_quality and entry.get("source_quality") != source_quality:
                continue
            if confidence and entry.get("confidence") != confidence:
                continue
            if tag and tag not in (entry.get("tags") or []):
                continue
            if _lifecycle_excluded(entry.get("lifecycle", "active"), lifecycle):
                continue

            related = entry.get("related_functions") or []
            score = 0.0
            if function_name in related:
                score = 100
            else:
                for rf in related:
                    if function_name_lower in rf.lower():
                        score = 50
                        break
            if score == 0:
                continue

            if entry.get("source_quality") == "verified-from-source":
                score += 10
            if entry.get("confidence") == "strong":
                score += 10

            results.append({
                "id":                     note_id,
                "library":                entry.get("library", ""),
                "library_version":        entry.get("library_version", ""),
                "topic":                  entry.get("topic", ""),
                "type":                   entry.get("type", "knowledge"),
                "source_quality":         entry.get("source_quality", "unverified"),
                "confidence":             entry.get("confidence", "weak"),
                "lifecycle":              entry.get("lifecycle", "active"),
                "summary":               entry.get("summary", ""),
                "sources":                entry.get("sources", []),
                "related_functions":      entry.get("related_functions", []),
                "relevance_score":        round(score, 2),
                "cues_raw":               "\n".join(entry.get("cues") or []),
                "primitives_to_avoid":    entry.get("primitives_to_avoid", []),
                "preferred_alternatives": entry.get("preferred_alternatives", []),
                "wrong_assumption":       entry.get("wrong_assumption", ""),
                "correct_behavior":       entry.get("correct_behavior", ""),
            })

        results = _rerank_results(results, index)

    else:
        # Pure filter search
        for note_id, entry in index.items():
            if library:
                main_lib = entry.get("library", "")
                additional = entry.get("additional_topics") or []
                if not _library_matches(main_lib, library) and not any(_library_matches(t, library) for t in additional):
                    continue
            if note_type and entry.get("type") != note_type:
                continue
            if source_quality and entry.get("source_quality") != source_quality:
                continue
            if confidence and entry.get("confidence") != confidence:
                continue
            if tag and tag not in (entry.get("tags") or []):
                continue
            if _lifecycle_excluded(entry.get("lifecycle", "active"), lifecycle):
                continue

            results.append({
                "id":                     note_id,
                "library":                entry.get("library", ""),
                "library_version":        entry.get("library_version", ""),
                "topic":                  entry.get("topic", ""),
                "type":                   entry.get("type", "knowledge"),
                "source_quality":         entry.get("source_quality", "unverified"),
                "confidence":             entry.get("confidence", "weak"),
                "lifecycle":              entry.get("lifecycle", "active"),
                "summary":               entry.get("summary", ""),
                "sources":                entry.get("sources", []),
                "related_functions":      entry.get("related_functions", []),
                "relevance_score":        10.0,
                "cues_raw":               "\n".join(entry.get("cues") or []),
                "primitives_to_avoid":    entry.get("primitives_to_avoid", []),
                "preferred_alternatives": entry.get("preferred_alternatives", []),
                "wrong_assumption":       entry.get("wrong_assumption", ""),
                "correct_behavior":       entry.get("correct_behavior", ""),
            })

        results.sort(key=lambda r: r["relevance_score"], reverse=True)

    if max_results > 0:
        results = results[:max_results]

    # Chunk search integration: append chunk results when requested
    chunk_results: list[dict[str, Any]] = []
    if include_chunks and query:
        chunk_limit = max(5, max_results // 2) if max_results > 0 else 5
        chunk_results = search_chunks(query, max_results=chunk_limit)

    return_dict: dict[str, Any] = {
        "count":   len(results),
        "results": results,
    }
    if chunk_results:
        return_dict["chunks"] = chunk_results
        return_dict["chunk_count"] = len(chunk_results)

    if len(results) >= 2:
        if results[0]["relevance_score"] > 2 * results[1]["relevance_score"]:
            return_dict["high_confidence_match"] = True
    elif len(results) == 1 and results[0]["relevance_score"] > 0.5:
        return_dict["high_confidence_match"] = True

    return return_dict


def search_chunks(
    query: str,
    max_results: int = 10,
    source_path: str = "",
) -> list[dict[str, Any]]:
    """Search chunks by embedding similarity.

    Returns list of chunk dicts with result_type='chunk'. Falls back to
    empty list when embeddings are unavailable or no chunks exist.
    """
    if not EMBEDDINGS_AVAILABLE or not query:
        return []

    try:
        from index import get_notemap_dir
        conn = get_db(get_notemap_dir())

        # Build chunk embedding matrix on the fly (not cached like notes)
        sql = "SELECT ce.chunk_id, ce.vector FROM chunk_embeddings ce"
        sql_params: list[Any] = []
        if source_path:
            sql += " JOIN chunks c ON c.id = ce.chunk_id WHERE c.source_path = ?"
            sql_params.append(source_path)

        rows = conn.execute(sql, sql_params).fetchall()
        if not rows:
            return []

        from embed import encode_texts as _enc, decode_vector
        import numpy as np

        chunk_ids = []
        vectors = []
        for row in rows:
            chunk_ids.append(row["chunk_id"] if hasattr(row, "keys") else row[0])
            blob = row["vector"] if hasattr(row, "keys") else row[1]
            vectors.append(decode_vector(blob))

        matrix = np.vstack(vectors).astype(np.float32)

        # Encode query and compute similarities
        query_vecs = _enc([query])
        if query_vecs is None:
            return []
        query_vec = query_vecs[0]
        scores = matrix @ query_vec
        top_indices = np.argsort(scores)[::-1][:max_results]

        # Fetch chunk metadata for top results
        results: list[dict[str, Any]] = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            cid = chunk_ids[idx]
            chunk_row = conn.execute(
                "SELECT * FROM chunks WHERE id = ?", (cid,)
            ).fetchone()
            if chunk_row is None:
                continue
            results.append({
                "result_type":  "chunk",
                "chunk_id":     cid,
                "source_type":  chunk_row["source_type"],
                "source_path":  chunk_row["source_path"],
                "source_title": chunk_row["source_title"],
                "section":      chunk_row["section"],
                "chunk_index":  chunk_row["chunk_index"],
                "content":      chunk_row["content"],
                "token_count":  chunk_row["token_count"],
                "score":        round(float(scores[idx]), 4),
            })

        return results

    except Exception:
        return []
