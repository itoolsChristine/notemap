"""SQLite database module for the notemap system.

Replaces the JSON index + markdown file storage with a single SQLite database.
Uses WAL journal mode for concurrent reads and FTS5 for full-text search.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_conn: sqlite3.Connection | None = None
_db_path: Path | None = None

DB_FILENAME = "notemap.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
-- Core notes table
CREATE TABLE IF NOT EXISTS notes (
    id                    TEXT PRIMARY KEY,
    library               TEXT NOT NULL,
    topic                 TEXT NOT NULL,
    type                  TEXT NOT NULL DEFAULT 'knowledge',
    summary               TEXT NOT NULL DEFAULT '',
    notes_body            TEXT NOT NULL DEFAULT '',
    cues_raw              TEXT NOT NULL DEFAULT '',

    -- Quality signals
    source_quality        TEXT NOT NULL DEFAULT 'unverified',
    confidence            TEXT NOT NULL DEFAULT 'maybe',
    lifecycle             TEXT NOT NULL DEFAULT 'active',

    -- Review scheduling
    review_interval_days  INTEGER NOT NULL DEFAULT 30,
    review_tier           INTEGER NOT NULL DEFAULT 2,
    review_count          INTEGER NOT NULL DEFAULT 0,
    miss_count            INTEGER NOT NULL DEFAULT 0,

    -- Dates
    created               TEXT NOT NULL DEFAULT '',
    last_modified         TEXT NOT NULL DEFAULT '',
    last_reviewed         TEXT NOT NULL DEFAULT '',
    valid_from            TEXT NOT NULL DEFAULT '',
    valid_until           TEXT NOT NULL DEFAULT '',

    -- Usage tracking
    last_retrieved        TEXT NOT NULL DEFAULT '',
    retrieval_count       INTEGER NOT NULL DEFAULT 0,

    -- Version
    library_version       TEXT NOT NULL DEFAULT '',

    -- Flags
    always_relevant       INTEGER NOT NULL DEFAULT 0,

    -- Correction-specific
    wrong_assumption      TEXT NOT NULL DEFAULT '',
    correct_behavior      TEXT NOT NULL DEFAULT '',
    applies_to            TEXT NOT NULL DEFAULT '',

    -- Full source JSON (array of source dicts)
    sources_json          TEXT NOT NULL DEFAULT '[]',

    -- Miss log JSON (array of {date, reason} dicts)
    miss_log_json         TEXT NOT NULL DEFAULT '[]',

    -- Anchor text from linking notes (for search)
    anchor_text           TEXT NOT NULL DEFAULT '',

    -- Notes body with context prefix (for search, max 500 chars)
    notes_body_search     TEXT NOT NULL DEFAULT '',

    -- Space-joined tags for FTS5 indexing
    tags_text             TEXT NOT NULL DEFAULT ''
);

-- Tags: many-to-many
CREATE TABLE IF NOT EXISTS note_tags (
    note_id  TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag      TEXT NOT NULL,
    PRIMARY KEY (note_id, tag)
);

-- Related functions: many-to-many
CREATE TABLE IF NOT EXISTS note_functions (
    note_id       TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    function_name TEXT NOT NULL,
    PRIMARY KEY (note_id, function_name)
);

-- Related notes: typed links
CREATE TABLE IF NOT EXISTS note_links (
    source_id  TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    target_id  TEXT NOT NULL,
    link_type  TEXT NOT NULL DEFAULT 'related',
    PRIMARY KEY (source_id, target_id)
);

-- Additional topics: many-to-many
CREATE TABLE IF NOT EXISTS note_topics (
    note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    topic   TEXT NOT NULL,
    PRIMARY KEY (note_id, topic)
);

-- Anti-pattern specific
CREATE TABLE IF NOT EXISTS note_anti_patterns (
    note_id               TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    primitive_to_avoid    TEXT NOT NULL,
    PRIMARY KEY (note_id, primitive_to_avoid)
);

CREATE TABLE IF NOT EXISTS note_alternatives (
    note_id               TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    alternative           TEXT NOT NULL,
    PRIMARY KEY (note_id, alternative)
);

-- Events table (replaces _events.jsonl)
CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    note_id   TEXT NOT NULL DEFAULT '',
    event     TEXT NOT NULL,
    tool      TEXT NOT NULL DEFAULT '',
    session   TEXT NOT NULL DEFAULT '',
    metadata  TEXT NOT NULL DEFAULT '{}'
);

-- Topic metadata (replaces _topics.json)
CREATE TABLE IF NOT EXISTS topic_metadata (
    library     TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    volatility  TEXT NOT NULL DEFAULT 'stable'
);

-- Project-to-topic mapping (replaces _project_topics.json)
CREATE TABLE IF NOT EXISTS project_topics (
    project_path TEXT NOT NULL,
    library      TEXT NOT NULL,
    PRIMARY KEY (project_path, library)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_notes_library ON notes(library);
CREATE INDEX IF NOT EXISTS idx_notes_lifecycle ON notes(lifecycle);
CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(type);
CREATE INDEX IF NOT EXISTS idx_notes_confidence ON notes(confidence);
CREATE INDEX IF NOT EXISTS idx_note_functions_fn ON note_functions(function_name);
CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags(tag);
CREATE INDEX IF NOT EXISTS idx_note_links_target ON note_links(target_id);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session);
CREATE INDEX IF NOT EXISTS idx_events_note ON events(note_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);

-- Embedding vectors for notes
CREATE TABLE IF NOT EXISTS note_embeddings (
    note_id    TEXT PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
    model      TEXT NOT NULL DEFAULT '',
    dimensions INTEGER NOT NULL DEFAULT 256,
    vector     BLOB NOT NULL
);

-- Raw text chunks from source material
CREATE TABLE IF NOT EXISTS chunks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type  TEXT NOT NULL,
    source_path  TEXT NOT NULL,
    source_title TEXT NOT NULL DEFAULT '',
    section      TEXT NOT NULL DEFAULT '',
    page_start   INTEGER,
    page_end     INTEGER,
    chunk_index  INTEGER NOT NULL,
    content      TEXT NOT NULL,
    token_count  INTEGER NOT NULL DEFAULT 0,
    created      TEXT NOT NULL DEFAULT '',
    parent_id    INTEGER REFERENCES chunks(id) ON DELETE SET NULL
);

-- Link chunks to notes
CREATE TABLE IF NOT EXISTS note_chunks (
    note_id   TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    chunk_id  INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    relevance TEXT NOT NULL DEFAULT 'primary',
    PRIMARY KEY (note_id, chunk_id)
);

-- Embedding vectors for chunks
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id   INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    model      TEXT NOT NULL DEFAULT '',
    dimensions INTEGER NOT NULL DEFAULT 256,
    vector     BLOB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_path);
CREATE INDEX IF NOT EXISTS idx_chunks_section ON chunks(section);
"""

_FTS_SQL = """
-- FTS5 full-text search index
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    id,
    topic,
    summary,
    notes_body,
    cues_raw,
    anchor_text,
    tags_text,
    content='notes',
    content_rowid='rowid',
    tokenize='porter unicode61'
);
"""

_TRIGGERS_SQL = """
-- Triggers to keep FTS5 in sync
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, id, topic, summary, notes_body, cues_raw, anchor_text, tags_text)
    VALUES (new.rowid, new.id, new.topic, new.summary, new.notes_body, new.cues_raw, new.anchor_text, new.tags_text);
END;

CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, id, topic, summary, notes_body, cues_raw, anchor_text, tags_text)
    VALUES ('delete', old.rowid, old.id, old.topic, old.summary, old.notes_body, old.cues_raw, old.anchor_text, old.tags_text);
END;

CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, id, topic, summary, notes_body, cues_raw, anchor_text, tags_text)
    VALUES ('delete', old.rowid, old.id, old.topic, old.summary, old.notes_body, old.cues_raw, old.anchor_text, old.tags_text);
    INSERT INTO notes_fts(rowid, id, topic, summary, notes_body, cues_raw, anchor_text, tags_text)
    VALUES (new.rowid, new.id, new.topic, new.summary, new.notes_body, new.cues_raw, new.anchor_text, new.tags_text);
END;
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_db(notemap_dir: Path | None = None) -> sqlite3.Connection:
    """Get or create the database connection.

    Opens the SQLite database in WAL mode with foreign keys enabled.
    Creates the schema if it doesn't exist.
    """
    global _conn, _db_path

    if notemap_dir is None:
        notemap_dir = Path.home() / ".claude" / "notemap"

    target_path = notemap_dir / DB_FILENAME
    if _conn is not None and _db_path == target_path:
        return _conn
    # Different path or no connection - (re)open
    if _conn is not None:
        _conn.close()
        _conn = None

    notemap_dir.mkdir(parents=True, exist_ok=True)
    _db_path = target_path

    _conn = sqlite3.connect(str(_db_path), check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA foreign_keys=ON")
    _conn.execute("PRAGMA busy_timeout=5000")

    _create_schema(_conn)
    return _conn


def init_db(notemap_dir: Path) -> sqlite3.Connection:
    """Initialize the database. Alias for get_db with explicit dir."""
    return get_db(notemap_dir)


def close_db() -> None:
    """Close the database connection."""
    global _conn, _db_path
    if _conn is not None:
        _conn.close()
        _conn = None
        _db_path = None


def get_db_path() -> Path | None:
    """Return the path to the current database file."""
    return _db_path


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

def _create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables, indexes, FTS5 virtual table, and triggers."""
    conn.executescript(_SCHEMA_SQL)
    # FTS5 and triggers need separate execution since executescript
    # doesn't handle virtual table creation in all cases
    try:
        conn.executescript(_FTS_SQL)
    except sqlite3.OperationalError:
        pass  # FTS table already exists
    try:
        conn.executescript(_TRIGGERS_SQL)
    except sqlite3.OperationalError:
        pass  # Triggers already exist
    conn.commit()


# ---------------------------------------------------------------------------
# Migration from markdown files
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def _split_sections(body: str) -> dict[str, str]:
    """Split a markdown body on ## headings into a dict."""
    sections: dict[str, str] = {}
    matches = list(_HEADING_RE.finditer(body))
    for i, match in enumerate(matches):
        heading = match.group(1).strip().lower()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[heading] = body[start:end].strip()
    return sections


def _extract_cues(cue_section: str) -> list[str]:
    """Parse bullet lines from a Cues section."""
    cues: list[str] = []
    for line in cue_section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            cues.append(stripped[2:].strip())
        elif stripped.startswith("* "):
            cues.append(stripped[2:].strip())
        elif stripped:
            cues.append(stripped)
    return cues


def _date_str(value: Any) -> str:
    """Normalize a date value to a string."""
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


def migrate_from_markdown(conn: sqlite3.Connection, notemap_dir: Path) -> dict[str, Any]:
    """Migrate all markdown note files into the SQLite database.

    Returns a stats dict with counts of migrated items.
    """
    import frontmatter

    stats = {
        "notes": 0,
        "tags": 0,
        "functions": 0,
        "links": 0,
        "topics": 0,
        "anti_patterns": 0,
        "alternatives": 0,
        "events": 0,
        "topic_metadata": 0,
        "project_topics": 0,
        "errors": [],
    }

    # Only skip _archive directory (not other _ prefixed dirs like _cross-cutting)
    skip_dirs = {"_archive"}

    for md_file in notemap_dir.rglob("*.md"):
        if md_file.name.startswith("_"):
            continue
        try:
            rel_parts = md_file.relative_to(notemap_dir).parts
        except ValueError:
            continue
        if any(part in skip_dirs for part in rel_parts[:-1]):
            continue

        try:
            post = frontmatter.load(str(md_file))
            meta = dict(post.metadata)
            body = post.content

            sections = _split_sections(body)
            cues = _extract_cues(sections.get("cues", ""))
            summary = sections.get("summary", "").strip()
            notes_body = sections.get("notes", "").strip()

            # Build notes_body_search (contextual retrieval, max 500 chars)
            context_prefix = "This note is about %s in %s" % (
                meta.get("topic", ""), meta.get("library", "")
            )
            notes_body_search = (context_prefix + ". " + notes_body)[:500]

            note_id = meta.get("id", "")
            if not note_id:
                stats["errors"].append(f"No ID in {md_file}")
                continue

            tags_text = " ".join(meta.get("tags") or [])

            conn.execute("""
                INSERT OR REPLACE INTO notes (
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
                meta.get("library", ""),
                meta.get("topic", ""),
                meta.get("type", "knowledge"),
                summary,
                notes_body,
                "\n".join(cues),
                meta.get("source_quality", "unverified"),
                meta.get("confidence", "maybe"),
                meta.get("lifecycle", "active"),
                int(meta.get("review_interval_days", 30)),
                int(meta.get("review_tier", 2)),
                int(meta.get("review_count", 0)),
                int(meta.get("miss_count", 0)),
                _date_str(meta.get("created", "")),
                _date_str(meta.get("last_modified", "")),
                _date_str(meta.get("last_reviewed", "")),
                _date_str(meta.get("valid_from", meta.get("created", ""))),
                _date_str(meta.get("valid_until", "")),
                _date_str(meta.get("last_retrieved", "")),
                int(meta.get("retrieval_count", 0)),
                meta.get("library_version", ""),
                1 if meta.get("always_relevant") else 0,
                meta.get("wrong_assumption", ""),
                meta.get("correct_behavior", ""),
                meta.get("applies_to", ""),
                json.dumps(meta.get("sources") or []),
                json.dumps(meta.get("miss_log") or []),
                notes_body_search,
                tags_text,
            ))
            stats["notes"] += 1

            # Tags
            for tag in (meta.get("tags") or []):
                conn.execute("INSERT OR IGNORE INTO note_tags VALUES (?, ?)", (note_id, tag))
                stats["tags"] += 1

            # Related functions
            for fn in (meta.get("related_functions") or []):
                conn.execute("INSERT OR IGNORE INTO note_functions VALUES (?, ?)", (note_id, fn))
                stats["functions"] += 1

            # Related notes (typed links)
            for link in (meta.get("related_notes") or []):
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
                    stats["links"] += 1

            # Additional topics
            for topic in (meta.get("additional_topics") or []):
                conn.execute("INSERT OR IGNORE INTO note_topics VALUES (?, ?)", (note_id, topic))
                stats["topics"] += 1

            # Anti-pattern fields
            for pat in (meta.get("primitives_to_avoid") or []):
                conn.execute("INSERT OR IGNORE INTO note_anti_patterns VALUES (?, ?)", (note_id, pat))
                stats["anti_patterns"] += 1
            for alt in (meta.get("preferred_alternatives") or []):
                conn.execute("INSERT OR IGNORE INTO note_alternatives VALUES (?, ?)", (note_id, alt))
                stats["alternatives"] += 1

        except Exception as e:
            stats["errors"].append(f"Error migrating {md_file}: {e}")
            continue

    # Build anchor text after all notes are inserted
    _build_anchor_text(conn)

    # Migrate events from _events.jsonl
    events_path = notemap_dir / "_events.jsonl"
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
                conn.execute("""
                    INSERT INTO events (timestamp, note_id, event, tool, session, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    evt.get("ts", ""),
                    evt.get("note", ""),
                    evt.get("event", ""),
                    evt.get("tool", ""),
                    evt.get("session", ""),
                    json.dumps(evt.get("meta", {})),
                ))
                stats["events"] += 1
            except (json.JSONDecodeError, KeyError):
                continue

    # Migrate topic metadata from _topics.json
    topics_path = notemap_dir / "_topics.json"
    if topics_path.exists():
        try:
            topics = json.loads(topics_path.read_text(encoding="utf-8"))
            for lib, meta in topics.items():
                conn.execute("INSERT OR IGNORE INTO topic_metadata VALUES (?, ?, ?)",
                            (lib, meta.get("description", ""), meta.get("volatility", "stable")))
                stats["topic_metadata"] += 1
        except (json.JSONDecodeError, OSError):
            pass

    # Migrate project topics from _project_topics.json
    pt_path = notemap_dir / "_project_topics.json"
    if pt_path.exists():
        try:
            pt = json.loads(pt_path.read_text(encoding="utf-8"))
            for path, libs in pt.items():
                for lib in libs:
                    conn.execute("INSERT OR IGNORE INTO project_topics VALUES (?, ?)", (path, lib))
                    stats["project_topics"] += 1
        except (json.JSONDecodeError, OSError):
            pass

    conn.commit()

    # Rebuild FTS5 index to ensure it's fully populated
    _rebuild_fts(conn)

    return stats


def _build_anchor_text(conn: sqlite3.Connection) -> None:
    """Build anchor text for notes from their inbound link context.

    For each note A that links to note B, A's summary becomes anchor text on B.
    """
    rows = conn.execute("""
        SELECT nl.target_id, n.summary
        FROM note_links nl
        JOIN notes n ON n.id = nl.source_id
        WHERE n.summary != ''
    """).fetchall()

    anchor_map: dict[str, list[str]] = {}
    for row in rows:
        target_id = row["target_id"]
        summary = row["summary"]
        anchor_map.setdefault(target_id, []).append(summary)

    for target_id, summaries in anchor_map.items():
        anchor = " ".join(summaries)
        conn.execute("UPDATE notes SET anchor_text = ? WHERE id = ?", (anchor, target_id))


def _update_anchor_text_for(conn: sqlite3.Connection, note_ids: list[str]) -> None:
    """Rebuild anchor text for specific notes only.

    For each target note ID, collects summaries from all notes that link to it
    and updates the anchor_text column. More efficient than a full rebuild when
    only a few links have changed.
    """
    if not note_ids:
        return

    for target_id in note_ids:
        rows = conn.execute("""
            SELECT n.summary
            FROM note_links nl
            JOIN notes n ON n.id = nl.source_id
            WHERE nl.target_id = ? AND n.summary != ''
        """, (target_id,)).fetchall()

        anchor = " ".join(row["summary"] for row in rows)
        conn.execute("UPDATE notes SET anchor_text = ? WHERE id = ?", (anchor, target_id))


def _rebuild_fts(conn: sqlite3.Connection) -> None:
    """Rebuild the FTS5 index from scratch."""
    try:
        conn.execute("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')")
        conn.commit()
    except sqlite3.OperationalError:
        pass


# ---------------------------------------------------------------------------
# Helper: load full note dict from DB (same format as old index entries)
# ---------------------------------------------------------------------------

def load_note_dict(conn: sqlite3.Connection, note_id: str) -> dict[str, Any] | None:
    """Load a single note from the DB into the same dict format as the old index."""
    row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        return None
    return _row_to_dict(conn, row)


def load_all_notes(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Load all notes from the DB into the same dict format as the old index.

    Uses bulk queries for related tables instead of per-note SELECTs.
    With 200 notes this avoids ~1,200 individual queries.
    """
    index: dict[str, dict[str, Any]] = {}
    rows = conn.execute("SELECT * FROM notes").fetchall()
    if not rows:
        return index

    # Bulk load all related tables into dicts keyed by note_id
    all_tags: dict[str, list[str]] = {}
    for r in conn.execute("SELECT note_id, tag FROM note_tags ORDER BY note_id").fetchall():
        all_tags.setdefault(r["note_id"], []).append(r["tag"])

    all_functions: dict[str, list[str]] = {}
    for r in conn.execute("SELECT note_id, function_name FROM note_functions ORDER BY note_id").fetchall():
        all_functions.setdefault(r["note_id"], []).append(r["function_name"])

    all_links: dict[str, list[dict[str, str]]] = {}
    for r in conn.execute("SELECT source_id, target_id, link_type FROM note_links ORDER BY source_id").fetchall():
        all_links.setdefault(r["source_id"], []).append({"id": r["target_id"], "type": r["link_type"]})

    all_topics: dict[str, list[str]] = {}
    for r in conn.execute("SELECT note_id, topic FROM note_topics ORDER BY note_id").fetchall():
        all_topics.setdefault(r["note_id"], []).append(r["topic"])

    all_anti_patterns: dict[str, list[str]] = {}
    for r in conn.execute("SELECT note_id, primitive_to_avoid FROM note_anti_patterns ORDER BY note_id").fetchall():
        all_anti_patterns.setdefault(r["note_id"], []).append(r["primitive_to_avoid"])

    all_alternatives: dict[str, list[str]] = {}
    for r in conn.execute("SELECT note_id, alternative FROM note_alternatives ORDER BY note_id").fetchall():
        all_alternatives.setdefault(r["note_id"], []).append(r["alternative"])

    # Build note dicts using bulk data
    for row in rows:
        note_id = row["id"]
        cues = [c.strip() for c in (row["cues_raw"] or "").split("\n") if c.strip()]
        sources = json.loads(row["sources_json"] or "[]")
        miss_log = json.loads(row["miss_log_json"] or "[]")

        entry = {
            "id":                     note_id,
            "library":                row["library"],
            "topic":                  row["topic"],
            "type":                   row["type"],
            "summary":                row["summary"],
            "notes_body":             row["notes_body"] or "",
            "cues_raw":               row["cues_raw"],
            "cues":                   cues,
            "source_quality":         row["source_quality"],
            "confidence":             row["confidence"],
            "lifecycle":              row["lifecycle"],
            "review_interval_days":   row["review_interval_days"],
            "review_tier":            row["review_tier"],
            "review_count":           row["review_count"],
            "miss_count":             row["miss_count"],
            "created":                row["created"],
            "last_modified":          row["last_modified"],
            "last_reviewed":          row["last_reviewed"],
            "valid_from":             row["valid_from"],
            "valid_until":            row["valid_until"],
            "last_retrieved":         row["last_retrieved"],
            "retrieval_count":        row["retrieval_count"],
            "library_version":        row["library_version"],
            "always_relevant":        bool(row["always_relevant"]),
            "wrong_assumption":       row["wrong_assumption"],
            "correct_behavior":       row["correct_behavior"],
            "applies_to":             row["applies_to"],
            "sources":                sources,
            "miss_log":               miss_log,
            "tags":                   all_tags.get(note_id, []),
            "related_functions":      all_functions.get(note_id, []),
            "related_notes":          all_links.get(note_id, []),
            "additional_topics":      all_topics.get(note_id, []),
            "primitives_to_avoid":    all_anti_patterns.get(note_id, []),
            "preferred_alternatives": all_alternatives.get(note_id, []),
            "anchor_text":            row["anchor_text"],
            "path":                   f"{row['library']}/{note_id}.md",
        }
        index[note_id] = entry

    return index


def _row_to_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    """Convert a SQLite Row into the dict format other modules expect."""
    note_id = row["id"]

    # Load related tables
    tags = [r["tag"] for r in conn.execute(
        "SELECT tag FROM note_tags WHERE note_id = ?", (note_id,)).fetchall()]

    related_functions = [r["function_name"] for r in conn.execute(
        "SELECT function_name FROM note_functions WHERE note_id = ?", (note_id,)).fetchall()]

    related_notes = [{"id": r["target_id"], "type": r["link_type"]} for r in conn.execute(
        "SELECT target_id, link_type FROM note_links WHERE source_id = ?", (note_id,)).fetchall()]

    additional_topics = [r["topic"] for r in conn.execute(
        "SELECT topic FROM note_topics WHERE note_id = ?", (note_id,)).fetchall()]

    primitives_to_avoid = [r["primitive_to_avoid"] for r in conn.execute(
        "SELECT primitive_to_avoid FROM note_anti_patterns WHERE note_id = ?", (note_id,)).fetchall()]

    preferred_alternatives = [r["alternative"] for r in conn.execute(
        "SELECT alternative FROM note_alternatives WHERE note_id = ?", (note_id,)).fetchall()]

    cues = [c.strip() for c in (row["cues_raw"] or "").split("\n") if c.strip()]

    sources = json.loads(row["sources_json"] or "[]")
    miss_log = json.loads(row["miss_log_json"] or "[]")

    return {
        "id":                     row["id"],
        "library":                row["library"],
        "topic":                  row["topic"],
        "type":                   row["type"],
        "summary":                row["summary"],
        "notes_body":             row["notes_body"] or "",
        "cues_raw":               row["cues_raw"],
        "cues":                   cues,
        "source_quality":         row["source_quality"],
        "confidence":             row["confidence"],
        "lifecycle":              row["lifecycle"],
        "review_interval_days":   row["review_interval_days"],
        "review_tier":            row["review_tier"],
        "review_count":           row["review_count"],
        "miss_count":             row["miss_count"],
        "created":                row["created"],
        "last_modified":          row["last_modified"],
        "last_reviewed":          row["last_reviewed"],
        "valid_from":             row["valid_from"],
        "valid_until":            row["valid_until"],
        "last_retrieved":         row["last_retrieved"],
        "retrieval_count":        row["retrieval_count"],
        "library_version":        row["library_version"],
        "always_relevant":        bool(row["always_relevant"]),
        "wrong_assumption":       row["wrong_assumption"],
        "correct_behavior":       row["correct_behavior"],
        "applies_to":             row["applies_to"],
        "sources":                sources,
        "miss_log":               miss_log,
        "tags":                   tags,
        "related_functions":      related_functions,
        "related_notes":          related_notes,
        "additional_topics":      additional_topics,
        "primitives_to_avoid":    primitives_to_avoid,
        "preferred_alternatives": preferred_alternatives,
        "anchor_text":            row["anchor_text"],
        # path field for backward compat - synthesized from library/id
        "path":                   f"{row['library']}/{row['id']}.md",
    }
