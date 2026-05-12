"""RAG retrieval module for UserPromptSubmit hook.

Reads user prompt from stdin (JSON), searches notemap for relevant knowledge,
returns additionalContext via JSON stdout. Designed to run in <500ms.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add our directory to path so we can import siblings
_this_dir = Path(__file__).resolve().parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from db import get_db, close_db, load_all_notes
from search import search_notes


def _read_recent_context(session_id: str, max_messages: int = 5) -> str:
    """Read recent user messages from history.jsonl for conversation context.

    Returns a combined string of recent user messages (most recent last),
    or empty string if history is unavailable.
    """
    try:
        # history.jsonl lives alongside the config directory
        history = Path.home() / ".claude" / "history.jsonl"
        if not history.exists():
            # Try .claude-personal (symlinked or separate)
            history = Path.home() / ".claude-personal" / "history.jsonl"
        if not history.exists():
            return ""

        # Read from the end of file to find recent messages efficiently
        # Read last 8KB which covers ~20-30 messages
        file_size = history.stat().st_size
        read_size = min(file_size, 8192)

        with open(history, "r", encoding="utf-8", errors="replace") as f:
            if file_size > read_size:
                f.seek(file_size - read_size)
                f.readline()  # Skip partial first line
            lines = f.readlines()

        # Extract user messages from this session
        user_messages: list[str] = []
        for line in reversed(lines):
            try:
                entry = json.loads(line.strip())
                if entry.get("sessionId") != session_id:
                    continue
                display = entry.get("display", "")
                if display and not display.startswith("/") and not display.startswith("!"):
                    user_messages.append(display[:300])
                    if len(user_messages) >= max_messages:
                        break
            except (json.JSONDecodeError, KeyError):
                continue

        if not user_messages:
            return ""

        # Return oldest-first, joined with space
        return " ".join(reversed(user_messages))
    except Exception:
        return ""


# Snippet of an ingested chunk's body included in the injected context.
_CHUNK_SNIPPET_CHARS = 400
# How many ingested chunks (at most) to append after the notes.
_MAX_INJECTED_CHUNKS = 3


def format_notes_for_context(
    results: list[dict],
    budget: int = 6000,
    chunks: list[dict] | None = None,
) -> str:
    """Format search results (and any ingested chunks) as context for injection.

    Notes come first, grouped by library. If *chunks* are given (from a search
    with include_chunks=True), up to a few are appended under an
    "## ingested sources" heading -- raw prose from notemap_ingest'd documents.
    Everything is counted against the same token *budget*; once it's spent, the
    rest is dropped.
    """
    if not results and not chunks:
        return ""

    # Group notes by library
    by_library: dict[str, list[dict]] = {}
    for r in results:
        lib = r.get("library", "unknown")
        by_library.setdefault(lib, []).append(r)

    lines = ["[notemap: relevant knowledge retrieved]"]
    tokens_used = 10

    for lib, notes in sorted(by_library.items()):
        lib_header = f"\n## {lib}"
        lib_tokens = len(lib_header) // 4
        if tokens_used + lib_tokens > budget:
            break
        lines.append(lib_header)
        tokens_used += lib_tokens

        for r in notes:
            topic = r.get("topic", "")
            summary = r.get("summary", "")
            confidence = r.get("confidence", "")
            source_quality = r.get("source_quality", "")
            cues_raw = r.get("cues_raw", "")

            # Build entry with confidence indicator
            entry = f"- **{topic}**: {summary}"
            if confidence and source_quality:
                entry += f" [{confidence}, {source_quality}]"

            # Add most relevant cue if space permits
            if cues_raw:
                cues = [c.strip() for c in cues_raw.split("\n") if c.strip()]
                if cues:
                    entry += f"\n  Cue: {cues[0]}"

            # Actionable fields for anti-patterns and corrections
            note_type = r.get("type", "")
            if note_type == "anti-pattern":
                avoid = r.get("primitives_to_avoid") or []
                alts  = r.get("preferred_alternatives") or []
                if avoid:
                    entry += f"\n  Avoid: {', '.join(avoid)}"
                if alts:
                    entry += f"\n  Use instead: {', '.join(alts)}"
            elif note_type == "correction":
                wrong   = r.get("wrong_assumption", "")
                correct = r.get("correct_behavior", "")
                if wrong:
                    entry += f"\n  Wrong assumption: {wrong}"
                if correct:
                    entry += f"\n  Correct behavior: {correct}"

            entry_tokens = len(entry) // 4
            if tokens_used + entry_tokens > budget:
                break
            lines.append(entry)
            tokens_used += entry_tokens

    # Ingested chunks (raw prose from notemap_ingest'd documents), if any fit.
    if chunks:
        header = "\n## ingested sources"
        header_tokens = len(header) // 4
        chunk_lines: list[str] = []
        for c in chunks[:_MAX_INJECTED_CHUNKS]:
            title   = c.get("source_title") or c.get("source_path") or "ingested text"
            section = c.get("section") or ""
            body    = " ".join((c.get("content") or "").split())
            if len(body) > _CHUNK_SNIPPET_CHARS:
                body = body[:_CHUNK_SNIPPET_CHARS].rstrip() + "..."
            label = f"{title} -- {section}" if section else title
            entry = f"- **{label}**: {body}"
            entry_tokens = len(entry) // 4
            if tokens_used + header_tokens + entry_tokens > budget:
                break
            chunk_lines.append(entry)
            tokens_used += entry_tokens
        if chunk_lines:
            lines.append(header)
            lines.extend(chunk_lines)

    if len(lines) <= 1:
        return ""
    return "\n".join(lines)


def retrieve_for_prompt(
    prompt_text: str,
    max_tokens: int = 6000,
    session_id: str = "",
) -> str:
    """Search notemap and format relevant notes as context string.

    Returns empty string if no relevant results. For short prompts,
    reads recent conversation history to build a richer search query.
    """
    prompt_stripped = prompt_text.strip()
    # Skip only slash commands and shell escapes
    if prompt_stripped.startswith("/") or prompt_stripped.startswith("!"):
        return ""

    # Build search query: for short prompts, enrich with conversation context
    search_query = prompt_stripped
    if len(prompt_stripped) < 30:
        if session_id:
            recent_context = _read_recent_context(session_id, max_messages=5)
            if recent_context:
                # Context provides the topic, current prompt adds intent
                search_query = recent_context + " " + prompt_stripped
            else:
                # No context available - short prompt alone has no signal
                return ""
        else:
            # No session ID - can't get context for a short prompt
            return ""

    try:
        notemap_dir = Path.home() / ".claude" / "notemap"
        if not (notemap_dir / "notemap.db").exists():
            return ""

        conn = get_db(notemap_dir)
        index = load_all_notes(conn)
        if not index:
            return ""

        result = search_notes(index, {
            "query":          search_query[:500],  # Truncate long queries
            "max_results":    10,
            "use_embeddings": True,
            "include_chunks": True,  # also surface notemap_ingest'd prose
        })
    except Exception:
        return ""

    results = result.get("results", [])

    # Filter notes by relevance threshold -- RRF scores (0.01-0.05 range) and
    # reranked relevance scores (0-1 range) are on different scales.
    MIN_RRF_SCORE       = 0.015  # Threshold for RRF-scored results
    MIN_RELEVANCE_SCORE = 0.3    # Threshold for reranked 0-1 results
    filtered = []
    for r in results:
        if "_rrf_score" in r:
            if r["_rrf_score"] >= MIN_RRF_SCORE:
                filtered.append(r)
        elif r.get("relevance_score", 0) >= MIN_RELEVANCE_SCORE:
            filtered.append(r)
    results = filtered

    # Filter ingested chunks by cosine similarity. potion-base-8M cosine is
    # compressed (~0.65 "same topic", ~0.35 "merely related"); 0.3 keeps the
    # band that's at least related, no junk.
    MIN_CHUNK_SCORE = 0.30
    chunks = [c for c in result.get("chunks", []) if c.get("score", 0.0) >= MIN_CHUNK_SCORE]

    if not results and not chunks:
        return ""

    return format_notes_for_context(results, budget=max_tokens, chunks=chunks)


if __name__ == "__main__":
    try:
        input_data = json.load(sys.stdin)
        prompt = input_data.get("prompt", "")
        session_id = input_data.get("session_id", "")

        context = retrieve_for_prompt(prompt, session_id=session_id)

        if context:
            json.dump({"additionalContext": context}, sys.stdout)
    except Exception:
        pass  # Never crash the hook -- silent failure is safe
    finally:
        try:
            close_db()
        except Exception:
            pass
