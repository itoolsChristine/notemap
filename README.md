# notemap

**Give Claude a persistent knowledge base so it remembers gotchas, patterns, and corrections across sessions.**

![Version](https://img.shields.io/badge/version-1.0.10-blue)
[![CI](https://github.com/itoolsChristine/notemap/actions/workflows/ci.yml/badge.svg)](https://github.com/itoolsChristine/notemap/actions/workflows/ci.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## The Problem

Claude forgets everything between sessions. Every new conversation starts from zero -- no memory of the gotchas it discovered yesterday, the function signatures it looked up last week, or the corrections the user made an hour ago. This leads to:

- **Repeating the same mistakes** -- using `empty()` on SmartString objects, getting function arguments wrong, reaching for PHP builtins when the codebase has better wrappers
- **False confidence** -- Claude "knows" how `trim()` works from training data, so it never checks whether the codebase has a `->trim()` method that handles encoding correctly
- **Re-learning from scratch** -- reading the same source files, re-discovering the same return types, hitting the same walls session after session

## The Solution

notemap is a Cornell Note-Taking System adapted for AI coding assistants. It gives Claude a persistent, searchable knowledge base of gotchas, anti-patterns, corrections, and conventions -- all tagged with evidence quality so Claude knows how much to trust each note.

The system is built on Walter Pauk's Cornell method (from *How to Study in College*), adapted for an agent that has a 100% forgetting cliff at session end instead of a gradual human forgetting curve. Each note has three sections: **Notes** (the facts), **Cues** (self-test questions), and **Summary** (one-line distillation for fast scanning).

An MCP server provides 14 tools for creating, searching, checking, and auditing notes -- all callable directly during Claude's coding sessions. The **preflight-then-check** workflow proactively surfaces gotchas before coding and catches anti-patterns after coding, without requiring Claude to know what to search for.

## Quick Install

**Windows (CMD -- double-click):**

Download and double-click `install.cmd`, or from a command prompt:
```cmd
install.cmd
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/itoolsChristine/notemap/main/install.ps1 | iex
```

**macOS / Linux / Git Bash:**
```bash
curl -fsSL https://raw.githubusercontent.com/itoolsChristine/notemap/main/install.sh | bash
```

**From a local clone (any platform):**
```bash
git clone https://github.com/itoolsChristine/notemap.git
cd notemap
install.cmd         # Windows CMD (or double-click)
.\install.ps1       # Windows PowerShell
./install.sh        # macOS/Linux/Git Bash
```

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and run at least once (so `~/.claude/` exists)
- Python 3.10+
- pip (for installing MCP server dependencies)

## Getting Started

### What happens automatically

After install, three hooks run in the background during every Claude Code session:

- **Session start** -- reminds Claude to run `notemap_preflight` and load your notes
- **Post-edit** -- reminds Claude to run `notemap_check` after writing code
- **User prompt (RAG)** -- automatically searches your notes on every prompt and injects relevant context before Claude processes your message

These hooks are registered in `~/.claude/settings.json` and can be adjusted or disabled there.

### Your first session

Once installed, start a Claude Code session and try:

```
notemap_stats()
```

This shows what's in your knowledge base (empty on first run). Then load any cross-cutting notes:

```
notemap_preflight(libraries=["_cross-cutting"])
```

Create your first note when you discover something worth remembering:

```
notemap_create(
  library="myproject",
  topic="config.load() silently returns empty dict on missing file",
  type="anti-pattern",
  notes="config.load() does not raise on missing files. Always check the return value.",
  summary="config.load() returns empty dict on missing file, does not raise.",
  cues=["What does config.load() do when the file is missing?"],
  source_quality="runtime-tested",
  confidence="strong"
)
```

From here, notes surface automatically via the RAG hook and the preflight/check workflow.

### Scanning a document for notes

Use the `/notemap` command to scan a PDF or project:

```
/notemap scan pdf
```

Claude reads 20 pages at a time, ingests the raw text, and creates distilled notes for anything noteworthy. Notes persist across sessions and surface automatically via RAG whenever they're relevant to your prompt.

## How It Works

### The Workflow

Claude follows a preflight-then-check workflow (injected into CLAUDE.md):

1. **Session start**: Run `notemap_stats()` to discover libraries, then `notemap_preflight()` to load all gotchas and anti-patterns for in-scope libraries.
2. **Before every edit**: Search notemap for relevant functions and gotchas.
3. **After every edit**: Run `notemap_check()` to auto-detect libraries and catch anti-patterns.
4. **When you learn something**: Create a note with sources. Don't move on without capturing it.
5. **When a note helped**: Mark it reviewed (strengthens its review tier).
6. **When a note was wrong**: Fix it, or delete it if obsolete.

### The `/notemap` Command

| Command | What it does |
|---------|-------------|
| `/notemap /path/to/project` | Scan a project's source code and create notes for gotchas, patterns, and conventions |
| `/notemap projectname` | Rescan an existing project -- update notes, create new ones, mark reviewed |
| `/notemap review [lib] [N]` | Autonomous note review (Claude verifies against source) |
| `/notemap stats` | Show note counts by library |
| `/notemap help` | Quick reference |

### The 14 MCP Tools

| Tool | Purpose |
|------|---------|
| `notemap_preflight` | Load all notes for specified libraries at session start (anti-patterns first). Supports `context_budget` for token-aware loading and `topic_focus` for semantic prioritization. |
| `notemap_check` | Auto-detect libraries from code and check for anti-patterns + function gotchas |
| `notemap_create` | Create a new note (knowledge, anti-pattern, correction, or convention). Auto-generates embedding for semantic search. |
| `notemap_read` | Read a specific note by ID |
| `notemap_search` | Hybrid search: BM25F keyword matching + vector embedding similarity, merged via reciprocal rank fusion |
| `notemap_update` | Update a note (fix content, upgrade confidence, record misses). Re-embeds on content change. |
| `notemap_delete` | Soft-delete (archive) or hard-delete a note |
| `notemap_audit` | Find stale, low-confidence, or problematic notes |
| `notemap_review` | Get a prioritized review queue |
| `notemap_lint` | Check code against anti-pattern notes (regex-based) |
| `notemap_stats` | Overview of libraries, note counts, health, and embedding status |
| `notemap_connections` | Query the knowledge graph for connections, paths, and suggestions |
| `notemap_embed` | Generate embeddings for all notes (batch). Use after bulk import or model upgrade. |
| `notemap_ingest` | Chunk and ingest text content for semantic search. Splits text into boundary-aware chunks with embeddings. |

### Evidence Quality System

Every note is tagged with two axes:

- **Source quality** (how we know): `verified-from-source` > `runtime-tested` > `documented` > `function-map` > `user-correction` > `inferred` > `unverified`
- **Confidence** (how sure): `strong` > `maybe` > `weak`

Rule: `unverified` can never pair with `strong`. If Claude's confidence comes from training data rather than reading this project's code, it's `unverified` until verified.

### Anti-Pattern Detection

Anti-pattern notes include `primitives_to_avoid` patterns (regex) and `preferred_alternatives`. The `notemap_lint` tool checks code against these patterns -- it's a data-driven linter that gets smarter with every correction, no code changes needed.

### Adaptive Review (5-Tier Leitner System)

Notes progress through 5 review tiers with increasing intervals:

| Tier | Interval | How to reach |
|------|----------|-------------|
| 1 | 14 days | Demoted (2+ misses) |
| 2 | 30 days | Default for new notes |
| 3 | 60 days | 2+ clean reviews, 0 misses |
| 4 | 120 days | Continued clean reviews |
| 5 | 365 days | Consistently verified |

Intervals are modified by confidence (strong 1.3x, weak 0.7x), note type (anti-patterns reviewed more often), and miss history (0.8^miss_count penalty). Notes with miss_ratio > 0.5 are flagged as leeches for rewrite or deletion. Confidence decays automatically without review (strong -> maybe -> weak).

`notemap_check` on clean code implicitly reviews relevant notes, so actively-used notes maintain themselves.

## What It Creates

```
~/.claude/
    notemap-mcp/              # Python MCP server (17 files)
        server.py, notes.py, search.py, audit.py, lint.py,
        preflight.py, check.py, index.py, db.py, graph.py,
        events.py, models.py, utils.py, embed.py, chunk.py,
        rag.py, requirements.txt
    notemap/                  # Note storage
        notemap.db            # SQLite database (single file, all notes + search index + events)
    commands/
        notemap.md            # /notemap slash command
    docs/
        notemap.md            # Detailed reference (@docs/ import)
    skills/
        notemap-review.md     # /notemap review skill
    scripts/notemap/          # Hook scripts (auto-run by Claude Code)
        session-start.sh, post-edit.sh,
        user-prompt.sh    # Automatically searches your notes on every prompt and injects relevant context
    CLAUDE.md                 # Notemap instructions (sentinel-injected)
~/.claude.json                # MCP server registration
~/.claude/settings.json       # Hook registration
```

### Database Schema

Notes are stored in a SQLite database with FTS5 full-text search:

- **`notes`** -- id, library, topic, type, summary, notes_body, cues, confidence, source_quality, lifecycle, review_tier, review_interval_days, miss_count, review_count, dates, sources (JSON), miss_log (JSON)
- **`note_tags`** -- many-to-many tags per note
- **`note_functions`** -- many-to-many function references per note
- **`note_links`** -- typed relationships between notes (related, extends, depends_on, supersedes, contradicts)
- **`note_topics`** -- additional library/topic memberships
- **`note_anti_patterns`** -- regex patterns to avoid (powers notemap_lint)
- **`note_alternatives`** -- preferred alternatives for anti-patterns
- **`notes_fts`** -- FTS5 full-text search index with BM25 scoring
- **`events`** -- usage tracking and gap detection log

## CLAUDE.md Integration

The installer adds one block to `~/.claude/CLAUDE.md`, delimited by sentinel comments:

```
<!-- NOTEMAP:INSTRUCTIONS:BEGIN -->
## Notemap -- API KNOWLEDGE CAPTURE
...3 core rules, confidence tax, evidence quality...
@docs/notemap.md
<!-- NOTEMAP:INSTRUCTIONS:END -->
```

The sentinel tags allow the installer to update the block without affecting the rest of CLAUDE.md. The `@docs/notemap.md` reference loads the detailed trigger lists, workflow examples, and CRUD guidance.

## Hooks

The installer registers three hook scripts in `~/.claude/settings.json`. These run automatically during Claude Code sessions to keep notemap integrated into the coding workflow.

| Hook | Event | What it does |
|------|-------|-------------|
| `session-start.sh` | `SessionStart` | Reminds Claude to run `notemap_preflight` so anti-patterns and gotchas are loaded before any coding begins |
| `post-edit.sh` | `PostToolUse` (Edit tool) | Reminds Claude to run `notemap_check` after editing to verify no anti-patterns were introduced |
| `user-prompt.sh` | `UserPromptSubmit` | Runs RAG retrieval against your notes and injects relevant context before Claude processes your message |

The first two hooks output short reminder messages. The third (`user-prompt.sh`) runs the RAG pipeline silently, injecting matching notes as `additionalContext` so Claude sees them without you having to ask.

### Disabling hooks

To disable any hook, remove or comment out its entry in `~/.claude/settings.json` under the appropriate event key (`hooks.SessionStart`, `hooks.PostToolUse`, or `hooks.UserPromptSubmit`). Changes take effect on the next Claude Code session.

## Usage

### Scan a New Project

```
/notemap /path/to/myproject
```

Claude reads the source code, identifies libraries and frameworks, discovers gotchas and patterns, and creates notes for everything noteworthy.

### Rescan an Existing Project

```
/notemap myproject
```

Claude re-reads the source, creates notes for new findings, updates changed notes, and marks confirmed notes as reviewed.

### Session Start

```
notemap_stats()
# -> zendb: 3, smartarray: 5, _cross-cutting: 48, learning-principles: 24 ...

notemap_preflight(libraries=["zendb", "smartarray", "smartstring"])
# -> watch_out: 3 anti-patterns (sorted by quality)
# -> know_this: 8 knowledge notes
# -> function_index: {DB::get: [2 notes], isEmpty: [1 note]}
# -> library_summaries: {"zendb": "Key gotchas: DB::get returns empty SmartArrayHtml..."}
```

### During Coding

```
# Before using a function:
notemap_search(function_name="DB::get")

# After discovering a gotcha:
notemap_create(
  library="mylib",
  topic="transform() silently drops null values",
  type="anti-pattern",
  notes="transform() skips null entries without warning...",
  summary="transform() silently drops nulls. Filter first or use transformAll().",
  cues=["What happens when transform() encounters null?",
        "How to safely transform a list that may contain nulls?",
        "Why did my data shrink after transform()?"],
  sources=[{"type": "file", "path": "src/transforms.py", "lines": "42-58"}],
  related_functions=["transform", "transformAll"],
  tags=["null-handling", "silent-failure", "data-loss"],
  primitives_to_avoid=["\\btransform\\([^)]*\\)"],
  preferred_alternatives=["transformAll() or filter nulls first"],
  source_quality="runtime-tested",
  confidence="strong"
)

# After writing code:
notemap_check(file_path="src/myfile.py")
# -> detected_libraries, lint_warnings, function_notes
```

### Periodic Review

```
/notemap review              # Review all libraries
/notemap review zendb        # Focus on one library
/notemap review zendb 20     # Review up to 20 notes
```

Claude autonomously reads each flagged note, verifies against source code, and marks it reviewed/fixed/deleted. You only handle ambiguous cases.

## Updating

Re-run the install command. The installer is idempotent -- it updates existing files and CLAUDE.md sentinel blocks without duplicating anything. Your notes in `~/.claude/notemap/` are never overwritten.

## Uninstalling

**Windows (CMD):** `uninstall.cmd`

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/itoolsChristine/notemap/main/uninstall.ps1 | iex
```

**macOS / Linux / Git Bash:**
```bash
curl -fsSL https://raw.githubusercontent.com/itoolsChristine/notemap/main/uninstall.sh | bash
```

**From a local clone:** Run `uninstall.cmd`, `.\uninstall.ps1`, or `./uninstall.sh`.

This removes the MCP server, docs, skill, and CLAUDE.md blocks. Your notes in `~/.claude/notemap/` are preserved unless you opt to remove them.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Python not found" | Install [Python 3.10+](https://www.python.org/downloads/) and ensure it's in your PATH |
| `~/.claude/` doesn't exist | Install and run [Claude Code](https://docs.anthropic.com/en/docs/claude-code) at least once |
| "pip install failed" | Run `python -m pip install --upgrade pip` then retry |
| Tools not showing up | Restart Claude Code after installation |
| Claude doesn't search notes | Check that CLAUDE.md has the `<!-- NOTEMAP:INSTRUCTIONS:BEGIN -->` sentinel block |
| MCP server not connecting | Check `~/.claude.json` has a "notemap" entry inside `mcpServers` with the correct Python path |
| Search returns nothing | Notes are created per-library; check `notemap_stats()` to see what libraries have notes |
| Hooks not firing | Check `~/.claude/settings.json` for notemap entries under `hooks.SessionStart`, `hooks.PostToolUse`, `hooks.UserPromptSubmit`. Settings are snapshotted at startup -- start a fresh session after install. |

## Architecture

```
notemap/
    README.md
    LICENSE
    CHANGELOG.md
    VERSION
    .gitignore
    .gitattributes
    install.sh                    # macOS/Linux/Git Bash installer
    install.ps1                   # Windows PowerShell installer
    install.cmd                   # Windows CMD installer (double-click)
    uninstall.sh                  # macOS/Linux/Git Bash uninstaller
    uninstall.ps1                 # Windows PowerShell uninstaller
    uninstall.cmd                 # Windows CMD uninstaller (double-click)
    sync.py                       # Dev: sync installed files back to src/
    sync.cmd                      # CMD wrapper for sync.py
    substitutions.example.json    # Path normalization template

    src/
        notemap-mcp/              # Python MCP server
            server.py             # FastMCP entry point (14 tools)
            notes.py              # CRUD operations (auto-embeds on create/update)
            search.py             # Hybrid BM25F + vector search with RRF
            audit.py              # Staleness checks + review queue
            lint.py               # Anti-pattern detection
            preflight.py          # Library briefing with context budgeting + topic focus
            check.py              # Code checker (post-coding safety net)
            index.py              # SQLite bridge (loads notes into in-memory dict format)
            db.py                 # Database management (schema, migrations, connections)
            embed.py              # Vector embeddings (model2vec, graceful degradation)
            chunk.py              # Boundary-aware text chunking for knowledge ingestion
            rag.py                # RAG retrieval for UserPromptSubmit hook
            graph.py              # Knowledge graph algorithms (PageRank, communities, paths)
            events.py             # Event logging (usage tracking, gap detection)
            models.py             # Enums and data classes
            utils.py              # Slugify, dates, paths, token estimation
            requirements.txt      # pip dependencies

        docs/
            notemap.md            # Detailed reference doc

        skills/
            notemap-review.md     # /notemap review skill

        commands/
            notemap.md                # /notemap slash command

        claude-md/
            notemap-instructions.md   # CLAUDE.md sentinel block

        hooks/                        # Hook scripts (auto-run by Claude Code)
            session-start.sh          # SessionStart: preflight reminder
            post-edit.sh              # PostToolUse: check reminder after edits
            user-prompt.sh            # UserPromptSubmit: RAG retrieval

    tests/
        test_search.py            # Search scoring tests
        test_index.py             # Index rebuild tests
        test_intervals.py         # Adaptive interval tests
        test_roundtrip.py         # Full CRUD lifecycle tests
        test_sync.py              # Path normalization tests
        test_audit.py             # Audit checks + review queue tests
        test_lint.py              # Anti-pattern lint tests
        test_utils.py             # Utility function tests
        test_notes_helpers.py     # Note section parsing tests
        test_preflight.py         # Preflight briefing tests
        test_check.py             # Code checker tests
        test_embed.py             # Embedding module tests
        test_chunk.py             # Text chunking tests
        test_hybrid_search.py     # Hybrid BM25F + vector search tests
        test_rag.py               # RAG retrieval tests
        test_budgeting.py         # Context budgeting + token estimation tests
        test_install_uninstall.sh # End-to-end install/uninstall test (sandboxed)
        fixtures/
            sample-note.md

    .github/
        workflows/
            ci.yml                # Cross-platform CI (Ubuntu, macOS, Windows)
```

## The Cornell Method (Adapted)

notemap is based on Walter Pauk's Cornell Note-Taking System from *How to Study in College* (10th Edition), adapted for an AI that has total amnesia between sessions:

| Cornell Phase | Human Student | Claude Adaptation |
|--------------|---------------|-------------------|
| **Record** | Take notes during lecture | `notemap_create` when discovering API behavior |
| **Review + Q** | Add cue questions same day | Cues and summary written at creation time |
| **Recite** | Self-test from cues | `notemap_search` before coding (read summaries, apply) |
| **Reflect** | Connect to existing knowledge | Cross-reference via `related_notes`, `related_functions` |

Key insight from the research: students who spent 80% of their time reciting (actively testing themselves) and 20% reading outperformed those who mostly read. For Claude, this means **actively checking notes before coding** beats passively re-reading source code.

## Contributing

Contributions are welcome! Here's how:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Commit (`git commit -m "Add my feature"`)
5. Push (`git push origin feature/my-feature`)
6. Open a Pull Request

For major changes, open an issue first to discuss the approach.

### Developer Workflow

After making changes to installed files in `~/.claude/`:

```bash
python sync.py          # Sync changes back to src/
python sync.py --dry-run  # Preview what would change
```

## License

[MIT](LICENSE)
