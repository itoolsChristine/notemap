#!/usr/bin/env bash
# notemap-session-start.sh -- SessionStart hook: notemap preflight directive
cat <<'EOF'
NOTEMAP: You MUST run notemap_preflight before writing any code this session.

DO NOW:
  1. notemap_stats() to discover which libraries have notes
  2. notemap_preflight(libraries=[...]) -- always include _cross-cutting
  3. Report what loaded: [notemap-preflight: lib/count, ...]

BEFORE EVERY EDIT: notemap_search for relevant functions and gotchas. notemap_read for full note detail.
AFTER EVERY EDIT: notemap_check(file_path="...") to catch anti-patterns.
WHEN YOU LEARN SOMETHING: notemap_create with sources. Do not move on without capturing it.
WHEN A NOTE HELPED: notemap_update(id=..., mark_reviewed=true).
WHEN A NOTE WAS WRONG: notemap_update to fix it, or notemap_delete if obsolete.
EOF
