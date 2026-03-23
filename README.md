# notemap

**Give Claude a persistent knowledge base so it remembers gotchas, patterns, and corrections across sessions.**

![Version](https://img.shields.io/badge/version-1.0.0-blue)
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

An MCP server provides 11 tools for creating, searching, checking, and auditing notes -- all callable directly during Claude's coding sessions. The **preflight-then-check** workflow proactively surfaces gotchas before coding and catches anti-patterns after coding, without requiring Claude to know what to search for.

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

## How It Works

### The 3 Core Rules

Claude follows three simple rules (injected into CLAUDE.md):

1. **Before writing code, search notemap.** If the project uses libraries Claude has notes for, search first. Report what was found: `[notemap: zendb/2 notes, smartarray/0 notes]`.
2. **When you learn something surprising, create a note.** Gotchas, wrong arguments, failed approaches, user corrections -- if it would cause a bug if forgotten, note it.
3. **When a note is wrong, fix or delete it.** Wrong notes are worse than no notes.

### The `/notemap` Command

| Command | What it does |
|---------|-------------|
| `/notemap /path/to/project` | Scan a project's source code and create notes for gotchas, patterns, and conventions |
| `/notemap projectname` | Rescan an existing project -- update notes, create new ones, mark reviewed |
| `/notemap review [lib] [N]` | Autonomous note review (Claude verifies against source) |
| `/notemap stats` | Show note counts by library |
| `/notemap help` | Quick reference |

### The 11 MCP Tools

| Tool | Purpose |
|------|---------|
| `notemap_preflight` | Load all notes for specified libraries at session start (anti-patterns first) |
| `notemap_check` | Auto-detect libraries from code and check for anti-patterns + function gotchas |
| `notemap_create` | Create a new note (knowledge, anti-pattern, correction, or convention) |
| `notemap_read` | Read a specific note by ID |
| `notemap_search` | Search notes by library, function name, keyword, or tag |
| `notemap_update` | Update a note (fix content, upgrade confidence, record misses) |
| `notemap_delete` | Soft-delete (archive) or hard-delete a note |
| `notemap_audit` | Find stale, low-confidence, or problematic notes |
| `notemap_review` | Get a prioritized review queue |
| `notemap_lint` | Check code against anti-pattern notes (regex-based) |
| `notemap_stats` | Overview of libraries, note counts, and health |

### Evidence Quality System

Every note is tagged with two axes:

- **Source quality** (how we know): `verified-from-source` > `runtime-tested` > `documented` > `function-map` > `user-correction` > `inferred` > `unverified`
- **Confidence** (how sure): `strong` > `maybe` > `weak`

Rule: `unverified` can never pair with `strong`. If Claude's confidence comes from training data rather than reading this project's code, it's `unverified` until verified.

### Anti-Pattern Detection

Anti-pattern notes include `primitives_to_avoid` patterns (regex) and `preferred_alternatives`. The `notemap_lint` tool checks code against these patterns -- it's a data-driven linter that gets smarter with every correction, no code changes needed.

### Adaptive Review

Notes track `miss_count` (how often they led to wrong code) and `review_count` (how often they've been verified). Notes that keep causing errors get shorter review intervals and higher priority in the review queue. Notes that are consistently useful get longer intervals.

## What It Creates

```
~/.claude/
    notemap-mcp/              # Python MCP server (11 tools)
        server.py, notes.py, search.py, audit.py, lint.py,
        preflight.py, check.py, index.py, models.py, utils.py,
        requirements.txt
    notemap/                  # Note storage (created on first use)
        _index.json           # Search index (auto-rebuilt)
        {library}/            # One subdirectory per library
            {topic-slug}.md   # One note per topic (Cornell format)
        _archive/             # Soft-deleted notes
    commands/
        notemap.md            # /notemap slash command
    docs/
        notemap.md            # Detailed reference (@docs/ import)
    skills/
        notemap-review.md     # /notemap review skill
    scripts/notemap/          # Hook scripts (auto-run by Claude Code)
        session-start.sh      # Preflight reminder at session start
        pre-edit.sh           # Search reminder before edits
        post-edit.sh          # Check reminder after edits
    CLAUDE.md                 # Notemap instructions (sentinel-injected)
~/.claude.json                # MCP server registration (merged into existing config)
~/.claude/settings.json       # Hook registration (merged into existing hooks)
```

### Note File Format

Each note is a markdown file with YAML frontmatter:

```markdown
---
id: "zendb-db-get-returns-empty-smartarrayhtml-on-no-match"
library: "zendb"
type: "knowledge"
topic: "DB::get() returns empty SmartArrayHtml on no match"
source_quality: "verified-from-source"
confidence: "strong"
lifecycle: "active"
review_interval_days: 30
miss_count: 0
tags: ["query", "return-type", "gotcha"]
related_functions: ["DB::get", "DB::select"]
---

## Cues
- What does DB::get() return when no record matches?
- How do you check if DB::get() found a record?

## Notes
- Returns empty SmartArrayHtml, NOT SmartNull
- Check with ->isEmpty(), never empty()
- Auto-adds LIMIT 1
[verified-from-source | strong]

## Summary
DB::get() always returns SmartArrayHtml. Empty on no match.
Check ->isEmpty(), never empty().
```

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
# Returns: zendb/3, smartarray/3, learning-principles/24 ...

notemap_search(library="zendb")
# Returns summaries of all zendb notes
```

### During Coding

```
# Before using a function:
notemap_search(function_name="DB::get")

# After discovering a gotcha:
notemap_create(
  library="mylib",
  topic="transform() silently drops null values",
  notes="transform() skips null entries without warning...",
  summary="transform() silently drops nulls. Filter first or use transformAll().",
  source_quality="runtime-tested",
  confidence="strong"
)

# After writing code:
notemap_lint(code="result = raw_func(data)", library="mylib")
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
| Hooks not firing | Check `~/.claude/settings.json` for notemap entries under `hooks.SessionStart`, `hooks.PreToolUse`, `hooks.PostToolUse`. Settings are snapshotted at startup -- start a fresh session after install. |

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
            server.py             # FastMCP entry point (11 tools)
            notes.py              # CRUD operations
            search.py             # Relevance-scored search
            audit.py              # Staleness checks + review queue
            lint.py               # Anti-pattern detection
            preflight.py          # Library briefing (session start)
            check.py              # Code checker (post-coding safety net)
            index.py              # JSON index management
            models.py             # Enums and data classes
            utils.py              # Slugify, dates, paths
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
            pre-edit.sh               # PreToolUse: search reminder before edits
            post-edit.sh              # PostToolUse: check reminder after edits

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
