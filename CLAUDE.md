# CLAUDE.md -- notemap

## What This Project Is

A redistributable Claude Code MCP server and skill suite that gives Claude a persistent knowledge base across sessions. Ships as cross-platform installers (bash + PowerShell) that place the MCP server, commands, skills, docs, and CLAUDE.md integration into `~/.claude/` and register the server in `~/.claude.json`.

**GitHub**: `itoolsChristine/notemap`
**License**: MIT
**Current version**: Read from `VERSION` file (single source of truth)

## Architecture

There are two copies of the notemap files:

1. **Live (installed)**: `~/.claude/notemap-mcp/`, `~/.claude/commands/`, `~/.claude/skills/`, `~/.claude/docs/` -- these are the actively-used files. Development happens here.
2. **Repo (distribution)**: `src/` -- distribution-ready copies with transforms applied (path normalization). Never edit `src/` directly.

**The live files are the source of truth.** `sync.py` copies them into `src/` with transforms. The install scripts copy from `src/` to the user's `~/.claude/`.

### Key directories

| Directory | Purpose | Tracked |
|-----------|---------|---------|
| `src/notemap-mcp/` | Python MCP server (11 tools) | Yes |
| `src/commands/` | Slash command (`/notemap`) | Yes |
| `src/skills/` | Skill file (`/notemap review`) | Yes |
| `src/docs/` | Supplementary reference doc (`@docs/notemap.md`) | Yes |
| `src/claude-md/` | CLAUDE.md integration content (instructions sentinel block) | Yes |
| `src/hooks/` | Hook scripts (SessionStart, PreToolUse, PostToolUse) | Yes |
| `temp/` | Sandboxed test directory (created/destroyed by test_install_uninstall.sh) | No (gitignored) |

### Installed file manifest

| File | Destination |
|------|-------------|
| `server.py` | `~/.claude/notemap-mcp/` |
| `notes.py` | `~/.claude/notemap-mcp/` |
| `search.py` | `~/.claude/notemap-mcp/` |
| `audit.py` | `~/.claude/notemap-mcp/` |
| `lint.py` | `~/.claude/notemap-mcp/` |
| `preflight.py` | `~/.claude/notemap-mcp/` |
| `check.py` | `~/.claude/notemap-mcp/` |
| `index.py` | `~/.claude/notemap-mcp/` |
| `models.py` | `~/.claude/notemap-mcp/` |
| `utils.py` | `~/.claude/notemap-mcp/` |
| `requirements.txt` | `~/.claude/notemap-mcp/` |
| `notemap.md` (command) | `~/.claude/commands/` |
| `notemap-review.md` | `~/.claude/skills/` |
| `notemap.md` (docs) | `~/.claude/docs/` |
| `notemap-instructions.md` | Injected into `~/.claude/CLAUDE.md` via sentinels |
| `session-start.sh` | `~/.claude/scripts/notemap/` |
| `pre-edit.sh` | `~/.claude/scripts/notemap/` |
| `post-edit.sh` | `~/.claude/scripts/notemap/` |
| MCP server entry | Merged into `~/.claude.json` |
| Hook entries | Merged into `~/.claude/settings.json` |

### Note storage (user data, NOT distributed)

`~/.claude/notemap/` contains the user's actual notes. This directory is created on first use and is never overwritten by the installer. The uninstaller preserves it by default.

## Development Workflow

### Making changes

1. Edit the **live** files in `~/.claude/` (MCP server, commands, skills, docs)
2. Run `sync.cmd` (or `python sync.py`) to pull changes into `src/`
3. sync.py automatically:
   - Copies Python MCP server files verbatim
   - Applies path normalization to .md files (`C:\Users\...` -> `$HOME/...`)
   - Extracts the notemap CLAUDE.md section from the live CLAUDE.md (between sentinels)
   - Applies project-specific substitutions from `substitutions.local.json`
4. Review changes with `git diff`
5. Update `CHANGELOG.md`
6. Commit and push

### Substitutions

`substitutions.local.json` (gitignored) maps personal/client paths and project names to generic equivalents for distribution. Auto-generates backslash variants for path entries. See `substitutions.example.json` for the format.

## Testing

### Unit tests (run by CI)

```bash
python -m unittest tests.test_search -v       # Search scoring algorithm
python -m unittest tests.test_index -v         # Index rebuild + section parsing
python -m unittest tests.test_intervals -v     # Adaptive review interval math
python -m unittest tests.test_roundtrip -v     # Full CRUD lifecycle
python -m unittest tests.test_sync -v          # Path normalization
python -m unittest tests.test_audit -v         # Audit checks + review queue
python -m unittest tests.test_lint -v          # Anti-pattern lint detection
python -m unittest tests.test_utils -v         # Utility functions
python -m unittest tests.test_notes_helpers -v # Note section parsing + frontmatter
python -m unittest tests.test_preflight -v     # Preflight briefing tool
python -m unittest tests.test_check -v         # Code check tool
```

### Install/uninstall test (manual, not in CI)

```bash
bash tests/test_install_uninstall.sh
```

Creates a sandboxed `temp/` directory with a fake HOME, runs install, verifies all files + CLAUDE.md sentinels + .claude.json merge + data preservation, runs uninstall, verifies cleanup. 45 checks total.

### CI matrix

Python 3.10 + 3.12 across ubuntu, macos, windows (6 jobs). Uses `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`.

## CLAUDE.md Integration (installed by installer)

The installer injects one sentinel-delimited block into the user's `~/.claude/CLAUDE.md`:

**Instructions block** (`NOTEMAP:INSTRUCTIONS:BEGIN/END`) -- The 3 core rules, confidence tax, evidence quality reference, and `@docs/notemap.md` import. Content from `src/claude-md/notemap-instructions.md`.

## MCP Server Registration

The installer merges a `notemap` entry into `~/.claude.json` (the Claude Code config file). The entry includes `type: stdio`, `command: python`, `args: [path/to/server.py]`, and `env: {}`. The uninstaller removes only the `notemap` key, preserving all other servers and settings.

## Things to Watch Out For

- **Never edit `src/` directly** -- changes will be overwritten by the next sync. Edit live files, then sync.
- **`~/.claude.json` is Claude Code's main config file** -- the install/uninstall scripts only touch the `mcpServers.notemap` key. Never truncate or replace the whole file.
- **Preseed scripts are dev-only** -- `preseed*.py` files in `~/.claude/notemap-mcp/` create initial notes for personal use. They are gitignored and NOT distributed.
- **Notes are never distributed** -- `~/.claude/notemap/` contains personal knowledge. The project distributes only the framework and tooling.
- **`substitutions.local.json` is gitignored** -- it contains personal paths. Each developer creates their own from `substitutions.example.json`.
