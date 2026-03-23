#!/usr/bin/env bash
# notemap-pre-edit.sh -- PreToolUse hook: notemap check before editing

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"file_path"[[:space:]]*:[[:space:]]*"//' | sed 's/"$//')

if [ -n "$FILE_PATH" ]; then
    echo "STOP. Before editing $FILE_PATH you MUST run: notemap_check(file_path=\"$FILE_PATH\") -- then confirm the result in your response before proceeding with the edit."
fi
