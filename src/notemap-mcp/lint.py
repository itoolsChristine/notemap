"""Anti-pattern detection for code snippets against the notemap index."""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def lint_code(
    index: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Check code against anti-pattern notes in the index.

    Params:
        code (required): the source code string to lint
        library (optional): filter anti-patterns to a specific library

    Returns dict with warnings list and clean boolean.
    """
    code    = params.get("code") or ""
    library = (params.get("library") or "").strip()

    if not code:
        return {"warnings": [], "clean": True}

    # Filter to anti-pattern notes
    anti_patterns: list[tuple[str, dict[str, Any]]] = []
    for nid, entry in index.items():
        if entry.get("type") != "anti-pattern":
            continue
        if library and entry.get("library") != library:
            continue
        anti_patterns.append((nid, entry))

    warnings: list[dict[str, Any]] = []

    for nid, entry in anti_patterns:
        patterns = entry.get("primitives_to_avoid") or []
        if not patterns:
            continue

        alternatives = entry.get("preferred_alternatives") or []
        suggestion   = alternatives[0] if alternatives else ""

        for pattern in patterns:
            try:
                match = re.search(pattern, code)
            except re.error as exc:
                logger.warning(
                    "Invalid regex pattern %r in note %s: %s",
                    pattern, nid, exc,
                )
                continue

            if match:
                warnings.append({
                    "match":      match.group(0),
                    "note_id":    nid,
                    "message":    entry.get("summary", ""),
                    "why":        entry.get("summary", ""),
                    "suggestion": suggestion,
                })

    return {
        "warnings": warnings,
        "clean":    len(warnings) == 0,
    }
