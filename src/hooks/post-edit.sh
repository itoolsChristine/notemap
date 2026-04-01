#!/usr/bin/env bash
# notemap-post-edit.sh -- PostToolUse hook: brief notemap_check timing nudge

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"file_path"[[:space:]]*:[[:space:]]*"//' | sed 's/"$//')

if [ -n "$FILE_PATH" ]; then
    echo "notemap_check is available for $FILE_PATH"
fi
