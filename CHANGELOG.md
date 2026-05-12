# Changelog

All notable changes to this project will be documented in this file.

## [1.2.0] - 2026-05-11

Hardening release. Bounds every tool response so a single oversized result can't disconnect the MCP transport, trims per-create noise, fixes a latent search bug, and lets the RAG hook surface ingested document chunks. Adds three note types.

### Added
- **Response size guard:** `utils.safe_json_dumps()` caps every tool's serialized JSON (default ~80 KB), trimming the largest lists then long strings rather than returning a multi-MB blob that chokes stdio. Every tool return (including error responses) routes through it. New `notemap_audit` per-check list cap via `utils.cap_result_lists()`.
- **Note types:** `requirement` (a spec/constraint the work must satisfy), `communication` (a message/conversation worth remembering), `commitment` (a promise or deadline -- short review interval).
- **RAG hook surfaces ingested chunks:** `rag.py` now searches with `include_chunks=True` and appends the top few chunk hits (above a cosine floor) under an `## ingested sources` heading, counted against the same token budget. Previously a `notemap_ingest`'d document never appeared in the automatic context.
- **`notemap_stats(verbose=False)`:** default response omits the per-library coverage matrix and caps the libraries list to the 30 largest; `verbose=True` returns the full picture.
- **`notemap_search`** now reports an error when called with no query and no filters instead of silently returning the whole index.
- **`notemap_update`** validates `related_notes` link targets and warns (does not block) on unknown note types; surfaces a `warnings` key.
- **35 new unit tests** (`test_response_limits.py`) plus additions to `test_rag.py` and `test_sync.py`.

### Changed
- **Default `notemap_search` `max_results` is 25** (was 0 = unbounded); pass 0 for all matches.
- **Default `notemap_preflight` `context_budget` is 12000 tokens** (was 0 = unbounded); pass 0 for no limit.
- **Default `notemap_review` `limit` is 25** (was 0); pass 0 for the whole queue.
- **`notemap_search` with `lifecycle="active"` now also surfaces `evergreen` notes** (matching preflight) -- they were silently dropped from search and from RAG injection.
- **`notemap_create` warnings:** removed the per-create "library has N notes" nag (the `notemap_audit(check="density")` outlier check is the real signal); the "no sources" warning no longer fires when `source_quality` already asserts verification (`runtime-tested`/`verified-from-source`/`user-correction`); new warnings for unknown note types and dangling `related_notes` targets; the `{type:'user', context:...}` source form is documented in the docstring.

### Fixed
- **`server.py.__version__` was stale** (`1.0.10` while `VERSION` was `1.1.0`), so `notemap_stats` reported the wrong version. `sync.py` already propagates `VERSION` into the `__version__` literal; `tests/test_sync.py` now asserts they match in CI.
- Removed two stray junk files (mangled-path artifacts) from the repo root.

## [1.1.0] - 2026-04-01

First feature release. Adds hybrid search, knowledge graph, context budgeting, RAG pipeline, chunk storage, and embeddings on top of the v1.0.0 foundation.

### Added
- **Hybrid search:** BM25F + vector embeddings (model2vec, 256-dim) with reciprocal rank fusion
- **Knowledge graph:** PageRank, HITS, Louvain communities, betweenness centrality, shortest paths, bridge detection, link suggestions
- **Context budgeting:** `context_budget` and `topic_focus` on preflight for token-aware note loading with progressive detail levels
- **RAG pipeline:** `rag.py` module with automatic hybrid search on every user prompt via `UserPromptSubmit` hook (token-budgeted, default 4000 tokens)
- **Chunk storage:** `chunk.py` module for boundary-aware text chunking with section metadata, chunk embeddings, and `notemap_ingest` tool
- **Embeddings:** `embed.py` module with `notemap_embed` tool for batch generation, auto-embed on create/update, in-memory vector cache
- **Event logging:** `events.py` module with SQLite events table for usage tracking and gap detection
- **Database layer:** `db.py` module for connection pooling, schema migrations, path-aware singleton
- **Graph module:** `graph.py` with typed link traversal, community detection, hub/authority scoring
- **New tools:** `notemap_embed`, `notemap_ingest`, `notemap_connections` (6 operations)
- **New hook:** `UserPromptSubmit` for RAG context injection
- **PDF scan workflow:** SQ3R survey step, progress tracking for multi-session scans, raw text ingestion
- **Pseudo-relevance feedback** for sparse queries, multi-query expansion with alias variants
- **Confidence decay** mutation via `notemap_audit(apply_decay=True)`
- **68 new unit tests** across 7 modules (test_embed, test_chunk, test_hybrid_search, test_rag, test_budgeting, test_graph, test_events)
- **Install/uninstall test** expanded: all 16 MCP files, 3 hook scripts, embed/chunk/rag verification

### Changed
- **Search:** two-pass retrieval with quality re-ranking (freshness, confidence, source quality, behavioral signals, PageRank)
- **Preflight:** budget allocation influenced by `topic_focus` via embedding similarity
- **CLAUDE.md instructions:** rewritten from prescriptive to examples-based style following Claude 4.6 prompt engineering research
- **Post-edit hook:** softened to minimal timing nudge (reduced context noise)
- **Session-start hook:** slimmed, removed duplicated behavioral triggers
- **Anchor text:** index rebuilds on note create/update, not just full rebuild
- **Search weights:** `tags_text` weight aligned with `topic` weight
- **Models:** `related_notes` type hint corrected to `list[dict | str]`, `type` field added to update `simple_fields`
- **Test isolation:** `get_db` is now path-aware singleton

### Removed
- **Pre-edit hook** (PreToolUse) - redundant with RAG + CLAUDE.md examples
- Dead code: `node2vec_embeddings` function

### Fixed
- Note type corrections: 15 learning-principles notes reclassified
- Cross-library links and internal links for orphan reduction

---

## [1.0.0] - 2026-03-27

### Added

#### Storage & Data
- SQLite database storage (`~/.claude/notemap/notemap.db`) replacing markdown files
- `db.py` module for database management (schema creation, migrations, connection pooling)
- FTS5 full-text search with field-weighted BM25 scoring
- Typed links between notes (related, extends, depends_on, supersedes, contradicts)
- additional_topics for cross-domain note membership
- always_relevant flag for notes that load in every preflight
- Structured `sources` field for provenance tracking ({type: "file"/"url"/"user"} with paths, URLs, or context)
- Two-axis evidence quality system (source_quality + confidence)
- 8 note types across 3 priority tiers: watch_out (anti-pattern, correction), know_this (knowledge, technique, convention), reference (reference, decision, finding)

#### Search
- BM25F field-weighted search with phrase matching and snippet generation
- Pseudo-relevance feedback and multi-query expansion
- Anchor text indexing (notes findable by how other notes describe them)
- Entry-point indexing for known function names
- Topic alias normalization
- Two-pass retrieval: FTS5 recall then quality re-ranking (freshness, confidence, source quality, behavioral signals)

#### Knowledge Graph
- Graph algorithms: PageRank, HITS, Louvain community detection, betweenness centrality, shortest path
- `notemap_connections` tool with 6 operations: neighborhood, path, suggest_links, suggest_hubs, pagerank, communities
- Bridge detection via betweenness centrality
- Unlinked mention detection
- Link suggestions at note creation time

#### Review System
- 5-tier Leitner review system (14/30/60/120/365 day intervals)
- Review interval modifiers: confidence, type, miss penalty, fuzz factor
- Leech detection (miss_ratio > 0.5 flagged for rewrite)
- Confidence decay (strong -> maybe -> weak over time without review)
- Implicit review via notemap_check (clean code auto-updates last_reviewed)

#### MCP Tools (12 total)
- `notemap_preflight` -- load all notes for specified libraries at session start, organized by priority (anti-patterns first), with function_index for quick lookup and optional version filtering
- `notemap_check` -- auto-detect libraries from code patterns and file extensions, run anti-pattern lint, surface function-specific gotchas. Accepts code string or file path. Library dependency expansion (e.g., zendb -> also checks smartarray/smartstring notes). Topic-discovery mode for non-code content.
- `notemap_connections` -- query the knowledge graph for neighborhoods, shortest paths, link suggestions, hub analysis, PageRank, community detection, and bridge identification
- `notemap_create`, `notemap_read`, `notemap_update`, `notemap_delete` -- full CRUD
- `notemap_search` -- BM25F relevance-scored search by library, function, keyword, or tag
- `notemap_audit` -- find stale, orphaned, leech, density, and consolidation issues
- `notemap_review` -- prioritized review queue sorted by urgency
- `notemap_lint` -- anti-pattern regex lint detection
- `notemap_stats` -- overview of libraries, note counts, and health

#### Commands & Skills
- `/notemap` command: scan projects, PDFs, text files, and URLs; rescan existing; review; stats; help
- `/notemap review` skill with autonomous Claude-driven verification (default: all notes)
- Preflight-then-check workflow with BLOCKING REQUIREMENT in CLAUDE.md
- Confidence Tax for false confidence defense (training data = unverified until checked)

#### Event Logging
- Event logging system for usage tracking and gap detection
- SQLite events table (replaced append-only JSONL)
- Note creation quality warnings (duplicates, density, missing fields)

#### Cornell Method
- Cornell Note-Taking System adapted for AI coding assistants and general learning (based on Walter Pauk's methodology)
- Governance principles: complexity creep prevention, global flag anti-pattern avoidance, reinterpretation drift prevention, premature infrastructure avoidance, zero new tools principle, compound tools to reduce round-trips, permanent note IDs
- Note creation quality guidelines: atomic note principle, dual vocabulary, front-load signal, extraction over abstraction
- Scanning and ingestion guidelines: progressive summarization pipeline, 3-note stopping rule, 5-signal stop checklist, scan budgets by document type
- Review quality guidelines: tiered verification depth, mass-action safeguards, pruning decision matrix

#### Installation & Distribution
- Cross-platform installers (bash + PowerShell + CMD) with backup/restore
- Cross-platform uninstallers with backup and optional note data preservation
- CLAUDE.md integration with `<!-- NOTEMAP:INSTRUCTIONS:BEGIN/END -->` sentinel injection
- MCP server registration via ~/.claude.json merge (preserves existing config)
- Hook scripts for automatic notemap enforcement (SessionStart, PreToolUse, PostToolUse) with safe merge into ~/.claude/settings.json (preserves existing hooks, cleans up empty arrays on uninstall)
- `@docs/notemap.md` supplementary reference with Quick Reference, workflow examples, and CRUD guidance
- Cross-reference between function maps and notemap in CLAUDE.md
- Library discovery guidance (notemap_stats, composer.json, imports, project CLAUDE.md)
- Developer sync tool (sync.py) with path normalization and substitutions

#### Testing
- Comprehensive test suite (344 unit tests across 11 modules)
- End-to-end install/uninstall test (sandboxed in temp/ directory)
- CI pipeline (GitHub Actions: Ubuntu + macOS + Windows x Python 3.10 + 3.12)
