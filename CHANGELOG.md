# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-03-26

### Added
- 11 MCP tools: preflight, check, create, read, search, update, delete, audit, review, lint, stats
- `notemap_preflight` -- load all notes for specified libraries at session start, organized by priority (anti-patterns first), with function_index for quick lookup and optional version filtering
- `notemap_check` -- auto-detect libraries from code patterns and file extensions, run anti-pattern lint, surface function-specific gotchas. Accepts code string or file path. Library dependency expansion (e.g., zendb -> also checks smartarray/smartstring notes). Topic-discovery mode for non-code content.
- 8 note types across 3 priority tiers: watch_out (anti-pattern, correction), know_this (knowledge, technique, convention), reference (reference, decision, finding)
- `/notemap` command supports PDF, text file, and URL scanning (not just code projects)
- Cornell Note-Taking System adapted for AI coding assistants and general learning (based on Walter Pauk's methodology)
- Two-axis evidence quality system (source_quality + confidence)
- Structured `sources` field on all notes for provenance tracking ({type: "file"/"url"/"user"} with paths, URLs, or context)
- 4 note types: knowledge, anti-pattern, correction, convention
- Anti-pattern notes with data-driven regex lint detection
- Word-level keyword search with multi-word scoring bonus
- Adaptive review intervals with miss tracking and error classification
- `/notemap` command: scan projects, rescan existing, review, stats, help
- `/notemap review` skill with autonomous Claude-driven verification (default: all notes)
- Preflight-then-check workflow with BLOCKING REQUIREMENT in CLAUDE.md
- Confidence Tax for false confidence defense (training data = unverified until checked)
- Cross-platform installers (bash + PowerShell + CMD) with backup/restore
- Cross-platform uninstallers with backup and optional note data preservation
- CLAUDE.md integration with `<!-- NOTEMAP:INSTRUCTIONS:BEGIN/END -->` sentinel injection
- MCP server registration via ~/.claude.json merge (preserves existing config)
- Hook scripts for automatic notemap enforcement (SessionStart, PreToolUse, PostToolUse) with safe merge into ~/.claude/settings.json (preserves existing hooks, cleans up empty arrays on uninstall)
- `@docs/notemap.md` supplementary reference with Quick Reference, workflow examples, and CRUD guidance
- Cross-reference between function maps and notemap in CLAUDE.md
- Library discovery guidance (notemap_stats, composer.json, imports, project CLAUDE.md)
- Organic review mechanism (notes verified by use during normal coding)
- Developer sync tool (sync.py) with path normalization and substitutions
- Comprehensive test suite (303 unit tests across 11 modules)
- End-to-end install/uninstall test (sandboxed in temp/ directory)
- CI pipeline (GitHub Actions: Ubuntu + macOS + Windows x Python 3.10 + 3.12)
