#!/usr/bin/env bash
# notemap-user-prompt.sh -- UserPromptSubmit hook: RAG retrieval from notemap
# Searches notemap knowledge base and injects relevant notes as context

NOTEMAP_DIR="$HOME/.claude/notemap-mcp"

# Find Python
PYTHON=""
if command -v python3 &>/dev/null; then PYTHON="python3"
elif command -v python &>/dev/null; then PYTHON="python"
else exit 0; fi

# Run RAG retrieval, pipe stdin through
exec "$PYTHON" "$NOTEMAP_DIR/rag.py"
