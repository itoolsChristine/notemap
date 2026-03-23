#!/usr/bin/env bash
# notemap-post-edit.sh -- PostToolUse hook: notemap check after editing

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"file_path"[[:space:]]*:[[:space:]]*"//' | sed 's/"$//')

if [ -n "$FILE_PATH" ]; then
    echo "STOP. You just edited $FILE_PATH. You MUST now run: notemap_check(file_path=\"$FILE_PATH\") -- report the result before doing anything else. If you learned something surprising, run notemap_create immediately."
fi
