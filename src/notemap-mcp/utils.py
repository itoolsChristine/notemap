"""Utility functions for the notemap system."""
from __future__ import annotations

import copy
import difflib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from slugify import slugify


def slugify_topic(topic: str) -> str:
    """Create a URL-safe slug from a topic string. Max length 60."""
    return slugify(topic, max_length=60)


def generate_id(library: str, topic: str) -> str:
    """Return a unique note ID in the form ``{library}-{slug}``.

    Forward slashes in *library* are replaced with double-dashes so the
    ID is safe for use as a filename (e.g. ``javascript/json`` becomes
    ``javascript--json``).
    """
    safe_library = library.replace("/", "--")
    return f"{safe_library}-{slugify_topic(topic)}"


def today_str() -> str:
    """Return today's date as ``YYYY-MM-DD``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def now_iso() -> str:
    """Return the current UTC datetime as ISO 8601."""
    return datetime.now(timezone.utc).isoformat()


def get_notemap_dir() -> Path:
    """Return the path to the notemap data directory."""
    return Path.home() / ".claude" / "notemap"


def get_mcp_dir() -> Path:
    """Return the path to the notemap-mcp server directory."""
    return Path.home() / ".claude" / "notemap-mcp"


def ensure_dir(path: Path) -> None:
    """Create *path* and all parent directories if they do not exist."""
    path.mkdir(parents=True, exist_ok=True)


def fuzzy_suggestions(
    query: str,
    candidates: list[str],
    max_results: int = 3,
) -> list[str]:
    """Return up to *max_results* close matches for *query* from *candidates*."""
    return difflib.get_close_matches(query, candidates, n=max_results, cutoff=0.4)


def estimate_tokens(text: str) -> int:
    """Estimate token count for context budget calculations.

    Uses a len/4 heuristic (roughly 4 characters per token for English text).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Response size guard
# ---------------------------------------------------------------------------
#
# Hard ceiling on any MCP tool's serialized JSON response. Above this the
# response is trimmed (largest lists first, then long strings) rather than
# returned raw: a multi-MB blob over stdio can choke the transport and take the
# server down for the rest of the session. This is the one place we are
# deliberately paranoid -- it's a system boundary, and an oversized result must
# never crash it. ~80 KB is roughly 20 K tokens, comfortably under the harness
# limit and large enough for a budgeted preflight.

RESPONSE_CHAR_LIMIT = 80_000

# Normal-pass trim limits: a list keeps this many leading entries (rest become a
# marker); a string is cut to this many characters.
_TRIM_LIST_KEEP = 5
_TRIM_STR_TO    = 2_000
# Aggressive second-pass limits, used only if the first pass didn't fit.
_AGG_LIST_KEEP = 1
_AGG_STR_TO    = 200
# Bound on the "drop the biggest top-level value" fallback (can't realistically
# need more iterations than there are keys, but keep it finite regardless).
_MAX_DROP_PASSES = 200


def _json_len(obj: Any, indent: int) -> int:
    """Serialized length of *obj*, or 0 if it can't be serialized."""
    try:
        return len(json.dumps(obj, indent=indent, default=str))
    except (TypeError, ValueError):
        return 0


def _list_marker(omitted: int) -> dict[str, Any]:
    """The marker entry appended in place of a trimmed list's tail."""
    return {
        "_truncated": True,
        "_omitted": omitted,
        "_note": "list trimmed to keep the response small -- narrow your query / pass max_results / pass context_budget",
    }


def _trim_lists_and_strings(node: Any, list_keep: int, str_to: int) -> None:
    """In place, recursively: shorten every over-long list and string in *node*.

    A list longer than ``list_keep + 1`` becomes its first ``list_keep`` entries
    plus a marker; a string longer than ``str_to`` is cut and suffixed with
    ``"...[truncated]"``. Recurses into the kept entries so nested oversized
    values are caught too. Does not touch *node* itself if it's a list -- the
    caller handles a top-level list.
    """
    if isinstance(node, dict):
        for k in list(node.keys()):
            v = node[k]
            if isinstance(v, list) and len(v) > list_keep + 1:
                node[k] = list(v[:list_keep]) + [_list_marker(len(v) - list_keep)]
            elif isinstance(v, str) and len(v) > str_to:
                node[k] = v[:str_to] + "...[truncated]"
            _trim_lists_and_strings(node[k], list_keep, str_to)
    elif isinstance(node, list):
        for i in range(len(node)):
            v = node[i]
            if isinstance(v, list) and len(v) > list_keep + 1:
                node[i] = list(v[:list_keep]) + [_list_marker(len(v) - list_keep)]
            elif isinstance(v, str) and len(v) > str_to:
                node[i] = v[:str_to] + "...[truncated]"
            _trim_lists_and_strings(node[i], list_keep, str_to)


def _truncate_top_list(node: Any, list_keep: int) -> Any:
    """If *node* is an over-long list, return its head plus a marker; else *node*."""
    if isinstance(node, list) and len(node) > list_keep + 1:
        return list(node[:list_keep]) + [_list_marker(len(node) - list_keep)]
    return node


def _shrink(obj: Any, max_chars: int, indent: int) -> Any:
    """Return a deep copy of *obj* trimmed so its JSON serialization fits *max_chars*.

    Three escalating passes, each re-checking the size:
      1. trim every over-long list to a few entries + marker, every long string;
      2. if still over, trim much harder (1 entry per list, 200 chars per string);
      3. if still over (a huge fixed structure), drop the largest remaining
         top-level value(s), replacing each with a ``{"_dropped": True}`` stub.
    Always terminates. Returns the trimmed copy even if it still doesn't fit --
    the caller decides what to do then.
    """
    work = copy.deepcopy(obj)
    if _json_len(work, indent) <= max_chars:
        return work

    work = _truncate_top_list(work, _TRIM_LIST_KEEP)
    _trim_lists_and_strings(work, _TRIM_LIST_KEEP, _TRIM_STR_TO)
    if _json_len(work, indent) <= max_chars:
        return work

    work = _truncate_top_list(work, _AGG_LIST_KEEP)
    _trim_lists_and_strings(work, _AGG_LIST_KEEP, _AGG_STR_TO)
    if _json_len(work, indent) <= max_chars or not isinstance(work, dict):
        return work

    for _ in range(_MAX_DROP_PASSES):
        if _json_len(work, indent) <= max_chars or len(work) <= 1:
            break
        biggest = max(work, key=lambda k: _json_len(work[k], 0))
        work[biggest] = {"_dropped": True, "_note": f"'{biggest}' was too large and was omitted"}
    return work


def safe_json_dumps(obj: Any, max_chars: int = RESPONSE_CHAR_LIMIT, indent: int = 2) -> str:
    """Serialize *obj* to a JSON string, trimming it to stay under *max_chars*.

    Returns ``json.dumps(obj, indent=indent)`` unchanged when it already fits.
    Otherwise trims the largest lists and longest strings (see :func:`_shrink`)
    and re-serializes; if it still won't fit, returns a tiny error object.
    Never raises -- every MCP tool routes its return through this so a single
    oversized result can't disconnect the transport.

        return safe_json_dumps({"count": n, "results": rows})
        return safe_json_dumps(result, max_chars=40_000)  # tighter cap

    """
    out = _try_dumps(obj, indent)
    if out is not None and len(out) <= max_chars:
        return out

    shrunk = _shrink(obj, max_chars, indent)
    out = _try_dumps(shrunk, indent)
    if out is not None and len(out) <= max_chars:
        return out

    return json.dumps({
        "error": "response too large to return",
        "hint": "narrow your query, pass max_results, or pass context_budget",
    }, indent=indent)


def _try_dumps(obj: Any, indent: int) -> str | None:
    """json.dumps with ``default=str``; returns None on failure instead of raising."""
    try:
        return json.dumps(obj, indent=indent, default=str)
    except (TypeError, ValueError):
        return None


def cap_result_lists(result: dict[str, Any], max_per_list: int = 50) -> dict[str, Any]:
    """Cap every top-level list in *result* to *max_per_list* entries.

    For tools (notemap_audit) that return a dict of named result lists where any
    one list could be long. Trimmed lists keep their first *max_per_list* entries
    plus a marker dict recording how many were omitted. Returns *result* mutated
    in place (and also returns it, for chaining).

        return safe_json_dumps(cap_result_lists(audit_notes(...)))

    """
    for key, value in result.items():
        if isinstance(value, list) and len(value) > max_per_list:
            omitted = len(value) - max_per_list
            result[key] = value[:max_per_list] + [{
                "_truncated": True,
                "_omitted": omitted,
                "_note": f"showing {max_per_list} of {len(value)} '{key}' entries -- filter by library or run a single check",
            }]
    return result
