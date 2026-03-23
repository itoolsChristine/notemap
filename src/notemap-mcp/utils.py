"""Utility functions for the notemap system."""
from __future__ import annotations

import difflib
from datetime import datetime, timezone
from pathlib import Path

from slugify import slugify


def slugify_topic(topic: str) -> str:
    """Create a URL-safe slug from a topic string. Max length 60."""
    return slugify(topic, max_length=60)


def generate_id(library: str, topic: str) -> str:
    """Return a unique note ID in the form ``{library}-{slug}``."""
    return f"{library}-{slugify_topic(topic)}"


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
