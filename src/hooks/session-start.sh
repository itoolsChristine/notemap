#!/usr/bin/env bash
# notemap-session-start.sh -- SessionStart hook: notemap preflight nudge
cat <<'EOF'
notemap: Run notemap_preflight(libraries=[...]) to load anti-patterns and
gotchas for this session. Include _cross-cutting. Relevant notes are also
injected automatically on every prompt via RAG.
EOF
