# Notemap -- Detailed Reference

Supplements the notemap section in CLAUDE.md. The CLAUDE.md block has the behavioral triggers. This doc has the details, examples, and specifications.

---

## 14 Tools -- Complete Reference

| Tool | Purpose | Key Parameters |
|------|---------|----------------|
| `notemap_stats` | Overview: note counts, libraries, health metrics | `verbose` (default False -- omits the per-library coverage matrix and caps the libraries list to the 30 largest) |
| `notemap_preflight` | Load all notes for libraries, organized by priority | `libraries`, `versions`, `include_cross_cutting`, `context_budget` (default 12000 tokens; 0 = no limit), `topic_focus` |
| `notemap_check` | Auto-detect libraries from code, lint, surface gotchas | `code` or `file_path`, `versions` |
| `notemap_search` | Find notes by keyword, function, tag, type, library | `query`, `function_name`, `library`, `tag`, `type`, `max_results` (default 25; 0 = every match). `lifecycle="active"` also surfaces `evergreen` notes. Needs at least one of query/library/function_name/tag/type. |
| `notemap_create` | Create a new note with full metadata | `library`, `topic`, `notes`, `summary`, `type`, `sources`, `cues`, `tags`, `related_functions`, `related_notes` |
| `notemap_read` | Read a note's full content and linked note summaries | `id`, `section` |
| `notemap_update` | Modify any field, mark reviewed, record misses, change lifecycle | `id`, plus any field to change. Incremental: `cues={"add":[...]}`, `related_notes={"add":[...]}`. Warns on dangling `related_notes` targets. |
| `notemap_delete` | Soft-delete (archive) or hard-delete a note | `id`, `reason` |
| `notemap_lint` | Check code against anti-pattern regex rules | `code`, `library` |
| `notemap_audit` | Find stale, orphaned, leech, density, consolidation issues | `check` ("all", "stale", "orphan", "leech", "density", "consolidation", "source_changed", "confidence_decay"). Per-check result lists are capped. |
| `notemap_review` | Prioritized review queue sorted by urgency | `library`, `limit` (default 25; 0 = whole queue) |
| `notemap_connections` | Query the knowledge graph | `note_id`, `operation` ("neighborhood", "path", "suggest_links", "suggest_hubs", "pagerank", "communities"), `target_id`, `max_hops` |
| `notemap_embed` | Generate/refresh embeddings for all notes | (none required) |
| `notemap_ingest` | Chunk and ingest text content for semantic search | `code` or `file_path`, `library`, `chunk_size`. Ingested chunks are surfaced by the RAG hook alongside notes. |

> **Every tool's response is size-capped** (~80 KB of JSON, `utils.RESPONSE_CHAR_LIMIT`). Above that the largest lists are trimmed to a few leading entries plus a `_truncated` marker rather than returned raw -- a multi-MB result over stdio can disconnect the MCP server. Control the size deliberately with `max_results` / `context_budget` / `verbose=False` rather than relying on the cap.

---

## Workflow Examples

### Session Start

```
notemap_stats()
# -> claude: 70, _cross-cutting: 48, learning-principles: 24, ...

notemap_preflight(libraries=["zendb", "smartarray", "smartstring"])
# -> watch_out: 3 anti-patterns (sorted by quality)
# -> know_this: 8 knowledge notes
# -> reference: 2 reference notes
# -> function_index: {DB::get: [2 notes], isEmpty: [1 note]}
# -> library_summaries: {"zendb": "Key gotchas: DB::get returns empty SmartArrayHtml..."}
# -> always_relevant notes auto-included from learning-principles

# Report: [notemap-preflight: zendb/3, smartarray/5, smartstring/4, 2 anti-patterns loaded]
```

### Creating a Note (Full Quality)

```
notemap_create(
  library="zendb",
  topic="DB::get returns empty SmartArrayHtml on no match",
  type="anti-pattern",
  notes="DB::get() returns SmartArrayHtml in ALL cases. On no match, returns an EMPTY SmartArrayHtml, NOT SmartNull. Check with ->isEmpty(). SmartNull is for missing keys on rows, not for query no-match.\n\n[verified-from-source | strong]",
  summary="DB::get() always returns SmartArrayHtml. Empty on no match. Check ->isEmpty(), never empty().",
  cues=[
    "What does DB::get return when no record matches?",
    "Is the no-match return type SmartNull or SmartArrayHtml?",
    "How do you check if DB::get found a record?",
    "Why does empty() not work on DB::get results?"
  ],
  sources=[
    {"type": "file", "path": "vendor/itools/zendb/src/ConnectionInternals.php", "lines": "290-295"}
  ],
  related_functions=["DB::get", "DB::select", "SmartArrayHtml", "isEmpty"],
  related_notes=[
    {"id": "smartarray-smartnull-is-for-missing-keys", "type": "related"},
    {"id": "_cross-cutting-php-object-traps-with-smartstring-smartarray-smartnull", "type": "extends"}
  ],
  tags=["query", "return-type", "gotcha", "null-handling"],
  primitives_to_avoid=["\\bempty\\(\\s*\\$record"],
  preferred_alternatives=["->isEmpty()"],
  source_quality="verified-from-source",
  confidence="strong"
)
```

**Creation checklist:**
- 3-5 cues at varying specificity (exact name, broad area, wrong assumption, why)
- Sources with file/line or URL
- Typed related_notes links (related, extends, depends_on, supersedes, contradicts)
- related_functions for every function mentioned
- additional_topics if relevant to other libraries
- Tags: over-tag rather than under-tag

### After Writing Code

```
notemap_check(file_path="src/users.php")
# -> detected_libraries: ["zendb", "smartarray"]
# -> lint_warnings: [empty() on objects is always false]
# -> function_notes: [{function: "DB::get", notes: [...]}]
# -> also_relevant: [{id: "smartarray-isempty", via: "zendb-db-get-returns-empty"}]
# -> If clean: relevant notes auto-reviewed (last_reviewed updated)

# Report: [notemap-check: 1 warning, 1 function note]
```

### Marking a Note Reviewed

```
# Note helped you write correct code:
notemap_update(id="zendb-db-get-returns-empty-smartarrayhtml-on-no-match", mark_reviewed=true)
# -> Promotes review tier (longer interval next time)

# Note was WRONG and caused a mistake:
notemap_update(id="...", increment_miss=true, miss_reason="accuracy-problem")
# -> Demotes review tier, may mark as stale if 3+ misses
```

### Exploring the Knowledge Graph

```
# What's connected to this note?
notemap_connections(note_id="zendb-db-get-returns-empty", operation="neighborhood")
# -> Notes within 2 hops, scored by proximity

# Find path between two concepts:
notemap_connections(note_id="zendb-db-get-returns-empty", operation="path", target_id="smartstring-double-encoding")

# What notes should be linked?
notemap_connections(note_id="zendb-db-get-returns-empty", operation="suggest_links")

# Which libraries need hub/overview notes?
notemap_connections(operation="suggest_hubs")

# Most important notes by graph authority:
notemap_connections(operation="pagerank")

# Natural topic clusters:
notemap_connections(operation="communities")
```

---

## Note Types

| Type | Purpose | Extra Fields | Preflight Tier |
|------|---------|-------------|----------------|
| `anti-pattern` | "Don't use X, use Y" -- powers regex lint | `primitives_to_avoid`, `preferred_alternatives` | watch_out (highest priority) |
| `correction` | "I thought X but it's actually Y" | `wrong_assumption`, `correct_behavior` | watch_out |
| `knowledge` | How something works, return types, behavior | | know_this |
| `technique` | How to do something well | | know_this |
| `convention` | Codebase rules and standards | `applies_to` | know_this |
| `requirement` | A spec or constraint the work must satisfy | | know_this |
| `reference` | A fact to look up later | | reference |
| `decision` | Why a choice was made | | reference |
| `finding` | What was observed/discovered | | reference |
| `communication` | A message/email/conversation worth remembering (what was said, by whom) | | reference |
| `commitment` | A promise or deadline you've made and need to honor (short review interval) | | reference |

---

## Typed Links

| Type | Meaning | When to Use |
|------|---------|-------------|
| `related` | General association | Default. Two notes about related topics. |
| `extends` | Builds on another note | This note adds detail to the linked note. |
| `depends_on` | Assumes the linked note is true | This note's advice only works if the linked note's fact holds. |
| `supersedes` | Replaces the linked note | The linked note is outdated. This one is the current truth. |
| `contradicts` | Disagrees with the linked note | Flag for resolution. Both can't be right. |

Format for updates: `related_notes={"add": [{"id": "note-id", "type": "extends"}]}`

---

## Cross-Domain Features

**additional_topics:** A note can belong to multiple libraries. A zendb note about SmartArrayHtml returns is also relevant to smartarray users.
```
notemap_update(id="zendb-db-get-returns-empty", additional_topics={"add": ["smartarray", "smartstring"]})
```

**always_relevant:** Notes that load in EVERY preflight regardless of library filter. Set on universal gotchas and cognitive techniques.

**Hierarchical libraries:** Use `/` for sub-topics: `javascript/json`, `networking/tcp-ip`. Preflight with the parent loads all children.

---

## Review System

**5-tier Leitner intervals:** Notes start at Tier 2 (30 days). Clean reviews promote to the next tier. Misses demote.

| Tier | Base Interval | Earned By |
|------|--------------|-----------|
| 1 | 14 days | Demoted (2+ misses) |
| 2 | 30 days | Default for new notes |
| 3 | 60 days | 2+ clean reviews, 0 misses |
| 4 | 120 days | Continued clean reviews |
| 5 | 365 days | Consistently verified |

**Modifiers multiply the base interval:**
- Confidence: strong 1.3x, maybe 1.0x, weak 0.7x
- Type: anti-pattern 0.8x (reviewed more often), reference 1.2x (less often)
- Miss penalty: 0.8^(miss_count)
- Fuzz: random 0.95-1.05x (prevents clustering)

**Implicit review:** `notemap_check` on clean code automatically updates `last_reviewed` for relevant notes. Actively used notes maintain themselves without explicit review.

**Leech detection:** Notes with miss_ratio > 0.5 (more misses than successes) are flagged for rewrite or deletion.

**Confidence decay:** `strong` decays to `maybe` at 2x the review interval without review. `maybe` decays to `weak` at 3x.

---

## Search Architecture

**Storage:** SQLite database at `~/.claude/notemap/notemap.db`. FTS5 full-text search with field-weighted BM25 scoring.

**Field weights (highest to lowest):** related_functions > topic = tags > cues > summary > notes_body > anchor_text

**Two-pass retrieval:**
1. FTS5 BM25 recall (broad candidate set)
2. Quality re-ranking: 55% text relevance + 5% PageRank graph authority + 10% freshness + 10% confidence + 10% source quality + 10% behavioral signals. Stale notes get 0.7x penalty.

**Additional features:**
- Phrase matching: consecutive query words in a field get 1.5x boost
- Pseudo-relevance feedback: top results expand sparse queries
- Multi-query expansion: when results are sparse, generate alias variants and merge via RRF
- Entry-point indexing: pre-computed top results for known function names
- Anchor text: notes findable by how OTHER notes describe them
- Snippets: most relevant sentence extracted for each result

### RAG Pipeline

The `UserPromptSubmit` hook runs `rag.py` on every user message:
1. Searches notemap with hybrid BM25 + vector search (`include_chunks=True`)
2. Injects relevant notes as `additionalContext` before Claude processes the message, then -- below the notes -- the top few ingested chunks above a cosine floor under an `## ingested sources` heading (so a `notemap_ingest`'d PDF surfaces even before it's distilled into notes)
3. Token-budgeted (default 6000 tokens) to avoid context bloat; notes and chunks share the budget, notes first

An explicit `notemap_search(include_chunks=True)` still gives you the full chunk search separate from the hook.

---

## Evidence Quality

| Source Quality | Meaning |
|---------------|---------|
| `verified-from-source` | Read actual source code and confirmed |
| `runtime-tested` | Executed code and observed the result |
| `documented` | Found in official docs or docblocks |
| `function-map` | Found in function map, didn't read source |
| `user-correction` | The user said this is how it works |
| `inferred` | Deduced from patterns |
| `unverified` | Assumed or from training data |

| Confidence | Meaning |
|-----------|---------|
| `strong` | Would bet on it. Verified from source. |
| `maybe` | Likely correct, not fully verified. |
| `weak` | Plausible but could be wrong. |

Rule: `unverified` can never pair with `strong`.

---

## Audit Checks

| Check | What It Finds |
|-------|---------------|
| `stale` | Notes past their review interval |
| `orphan` | Notes with zero links, older than 30 days |
| `leech` | Notes with miss_ratio > 0.5 |
| `density` | Libraries with note counts > 2 stddev above mean |
| `consolidation` | Note pairs with > 60% topic word overlap |
| `source_changed` | Notes whose cited source files were modified |
| `confidence_decay` | Notes whose confidence should be downgraded due to staleness |
| `all` | Run every check |

---

## Three-Gate Filter for New Notes

Before creating any note:
1. **Relevant?** Does this relate to a codebase you actively work on?
2. **Important?** Would getting this wrong cause a bug, waste time, or produce incorrect code?
3. **Reliable?** Can the source be verified?

If the knowledge wouldn't change how you write code, skip it.

---

## Scanning Guidelines

**3-pass pipeline:** (1) Extract noteworthy passages. (2) Crystallize into atomic notes with metadata. (3) Connect to existing notes via related_notes.

**Stopping signals (stop when 3 of 5 are true):**
1. Last 3 notes are all knowledge/reference (no gotchas found)
2. Finding more duplicates than new notes
3. Remaining content is background, not actionable
4. All major sections/APIs covered
5. Notes getting abstract rather than specific

**By document type:**
- API docs: focus on gotchas, not every method signature
- Textbooks: capture principles and mental models, not definitions
- Tutorials: capture the "why" behind steps, not the steps
- Error logs: capture root causes and fixes

**Quality test:** "Would I Ctrl-F for this?" If no one would search for terms in this note during debugging, skip it.

---

## Note Creation Quality Checklist

**Before creating:**
- Is this one atomic idea? (If summary needs two sentences about unrelated things, split.)
- Does it already exist? (`notemap_search` by keyword AND function name)
- Would I search for this in 3 months?

**While creating:**
- 3-5 cues at varying specificity
- Sources with file:line or URL
- related_functions for every function mentioned
- Typed related_notes links to connected notes
- additional_topics if relevant to other libraries
- Tags: over-tag. Missed tags = retrieval failure. Extra tags = minor noise.

**After creating:**
- Does the summary stand alone?
- Are cues search-friendly (questions someone debugging would ask)?
- Front-loaded the signal (most important info in first 1-2 sentences)?

**Avoid:**
- Vague summaries ("has some gotchas" -- say WHAT)
- Missing sources (unverifiable forever)
- Mega-notes covering 5 topics (split them)
- Paraphrased technical facts (quote signatures/return types verbatim)

---

## Accountability Format

Report at the start of task responses:
- `[notemap-preflight: zendb/3, smartstring/4, 2 anti-patterns loaded]`
- `[notemap-check: clean]` or `[notemap-check: 1 warning, 2 function notes]`
- `[notemap: no libraries in scope]`
- `[notemap: created note for DB::get gotcha]`
