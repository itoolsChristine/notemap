#!/usr/bin/env bash
# test_install_uninstall.sh -- End-to-end test of install and uninstall scripts
#
# Creates a fake HOME in ./temp, runs install.sh (local mode), verifies
# every file and config entry, then runs uninstall.sh and verifies cleanup.
#
# Usage:  ./tests/test_install_uninstall.sh
# Run from the project root (D:\_Source\_interactive-tools\notemap)

set -euo pipefail

# ============================================================================
#  Setup
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMP_DIR="$PROJECT_ROOT/temp"

# Colors
GREEN="\033[92m"
RED="\033[91m"
YELLOW="\033[93m"
BOLD="\033[1m"
RESET="\033[0m"

pass() { echo -e "  ${GREEN}[PASS]${RESET} $*"; }
fail() { echo -e "  ${RED}[FAIL]${RESET} $*"; FAILURES=$((FAILURES + 1)); }
info() { echo -e "  ${YELLOW}[INFO]${RESET} $*"; }

FAILURES=0
CHECKS=0

# Convert bash path to Windows path for Python (cygpath available in Git Bash)
win_path() {
    if command -v cygpath &>/dev/null; then
        cygpath -w "$1"
    else
        echo "$1"
    fi
}

check() {
    CHECKS=$((CHECKS + 1))
    if eval "$1"; then
        pass "$2"
    else
        fail "$2"
    fi
}

echo ""
echo "  ============================================================"
echo "    NOTEMAP INSTALL/UNINSTALL TEST"
echo "    Testing in sandboxed temp/ directory"
echo "  ============================================================"
echo ""

# ============================================================================
#  Clean slate
# ============================================================================

if [ -d "$TEMP_DIR" ]; then
    rm -rf "$TEMP_DIR"
    info "Removed existing temp/"
fi

mkdir -p "$TEMP_DIR/.claude"
info "Created temp/.claude/"

# Create a fake CLAUDE.md with some existing content
cat > "$TEMP_DIR/.claude/CLAUDE.md" << 'EOF'
# CLAUDE.md

## Existing Section

This is pre-existing content that should be preserved.

## Another Section

More content here.
EOF
info "Created fake CLAUDE.md with pre-existing content"

# Create a fake .claude.json with an existing MCP server
cat > "$TEMP_DIR/.claude.json" << 'EOF'
{
  "mcpServers": {
    "other-server": {
      "type": "stdio",
      "command": "node",
      "args": ["other-server.js"],
      "env": {}
    }
  },
  "someOtherSetting": true
}
EOF
info "Created fake .claude.json with existing server + settings"

# Create a fake settings.json with pre-existing hooks (should not be damaged)
cat > "$TEMP_DIR/.claude/settings.json" << 'EOF'
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "powershell -File play-notification.ps1",
            "async": true
          }
        ]
      }
    ]
  },
  "alwaysThinkingEnabled": true
}
EOF
info "Created fake settings.json with existing Stop hook + settings"

# ============================================================================
#  Run install (with HOME overridden to temp/)
# ============================================================================

echo ""
echo "  --- Running install.sh ---"
echo ""

# Run install in non-interactive mode (piped input = auto-yes)
export HOME="$TEMP_DIR"
echo "y" | bash "$PROJECT_ROOT/install.sh" 2>&1 | sed 's/^/    /'
INSTALL_EXIT=$?

echo ""

check '[ $INSTALL_EXIT -eq 0 ]' "install.sh exited with code 0"

# ============================================================================
#  Integrity checks -- verify everything installed correctly
# ============================================================================

echo ""
echo "  --- Post-install integrity checks ---"
echo ""

# MCP server files
for f in server.py notes.py search.py audit.py lint.py preflight.py check.py index.py models.py utils.py; do
    check "[ -f '$TEMP_DIR/.claude/notemap-mcp/$f' ]" "MCP file installed: $f"
done
check "[ -f '$TEMP_DIR/.claude/notemap-mcp/requirements.txt' ]" "MCP file installed: requirements.txt"

# Docs
check "[ -f '$TEMP_DIR/.claude/docs/notemap.md' ]" "Docs installed: notemap.md"

# Commands
check "[ -f '$TEMP_DIR/.claude/commands/notemap.md' ]" "Command installed: notemap.md"

# Skills
check "[ -f '$TEMP_DIR/.claude/skills/notemap-review.md' ]" "Skill installed: notemap-review.md"

# Note storage directory created
check "[ -d '$TEMP_DIR/.claude/notemap' ]" "Note storage directory created"

# CLAUDE.md -- sentinels present
check "grep -q 'NOTEMAP:INSTRUCTIONS:BEGIN' '$TEMP_DIR/.claude/CLAUDE.md'" "CLAUDE.md has BEGIN sentinel"
check "grep -q 'NOTEMAP:INSTRUCTIONS:END' '$TEMP_DIR/.claude/CLAUDE.md'" "CLAUDE.md has END sentinel"
check "grep -q 'Notemap -- PERSISTENT KNOWLEDGE BASE' '$TEMP_DIR/.claude/CLAUDE.md'" "CLAUDE.md has notemap heading"
check "grep -q '@docs/notemap.md' '$TEMP_DIR/.claude/CLAUDE.md'" "CLAUDE.md has @docs reference"

# CLAUDE.md -- pre-existing content preserved
check "grep -q 'Existing Section' '$TEMP_DIR/.claude/CLAUDE.md'" "CLAUDE.md preserved: Existing Section"
check "grep -q 'Another Section' '$TEMP_DIR/.claude/CLAUDE.md'" "CLAUDE.md preserved: Another Section"
check "grep -q 'pre-existing content' '$TEMP_DIR/.claude/CLAUDE.md'" "CLAUDE.md preserved: pre-existing content"

# .claude.json -- notemap entry present
PYTHON=""
command -v python3 &>/dev/null && PYTHON="python3" || PYTHON="python"
MCP_JSON_WIN=$(win_path "$TEMP_DIR/.claude.json")
MCP_DIR_WIN=$(win_path "$TEMP_DIR/.claude/notemap-mcp")

check "$PYTHON -c \"
import json
d = json.load(open(r'$MCP_JSON_WIN'))
assert 'notemap' in d.get('mcpServers', {}), 'notemap not in mcpServers'
entry = d['mcpServers']['notemap']
assert entry.get('type') == 'stdio', 'missing type'
assert 'command' in entry, 'missing command'
assert 'args' in entry, 'missing args'
assert 'env' in entry, 'missing env'
\" 2>&1" ".claude.json has notemap entry with correct format"

# .claude.json -- existing server preserved
check "$PYTHON -c \"
import json
d = json.load(open(r'$MCP_JSON_WIN'))
assert 'other-server' in d.get('mcpServers', {}), 'other-server was lost'
\" 2>&1" ".claude.json preserved: other-server entry"

# .claude.json -- other settings preserved
check "$PYTHON -c \"
import json
d = json.load(open(r'$MCP_JSON_WIN'))
assert d.get('someOtherSetting') == True, 'someOtherSetting was lost'
\" 2>&1" ".claude.json preserved: someOtherSetting"

# Verify no preseed scripts leaked
check "[ ! -f '$TEMP_DIR/.claude/notemap-mcp/preseed.py' ]" "No preseed.py installed (good)"
check "[ ! -f '$TEMP_DIR/.claude/notemap-mcp/preseed_textbook.py' ]" "No preseed_textbook.py installed (good)"

# Verify server.py can import
check "$PYTHON -c \"
import sys
sys.path.insert(0, r'$MCP_DIR_WIN')
import server
\" 2>&1" "server.py imports successfully"

# Hook scripts installed
check "[ -f '$TEMP_DIR/.claude/scripts/notemap/session-start.sh' ]" "Hook installed: session-start.sh"
check "[ -f '$TEMP_DIR/.claude/scripts/notemap/pre-edit.sh' ]" "Hook installed: pre-edit.sh"
check "[ -f '$TEMP_DIR/.claude/scripts/notemap/post-edit.sh' ]" "Hook installed: post-edit.sh"

# settings.json -- notemap hooks registered
SETTINGS_WIN=$(win_path "$TEMP_DIR/.claude/settings.json")
check "$PYTHON -c \"
import json
d = json.load(open(r'$SETTINGS_WIN'))
hooks = d.get('hooks', {})
assert 'SessionStart' in hooks, 'SessionStart not in hooks'
assert 'PreToolUse' in hooks, 'PreToolUse not in hooks'
assert 'PostToolUse' in hooks, 'PostToolUse not in hooks'
# Verify notemap entries exist by checking command paths
for event in ['SessionStart', 'PreToolUse', 'PostToolUse']:
    found = False
    for group in hooks[event]:
        for h in group.get('hooks', []):
            if 'scripts/notemap/' in h.get('command', ''):
                found = True
    assert found, f'No notemap hook found in {event}'
\" 2>&1" "settings.json has notemap hooks in all 3 events"

# settings.json -- existing Stop hook preserved
check "$PYTHON -c \"
import json
d = json.load(open(r'$SETTINGS_WIN'))
hooks = d.get('hooks', {})
assert 'Stop' in hooks, 'Stop hook was lost'
assert len(hooks['Stop']) > 0, 'Stop hook array is empty'
found_notification = False
for group in hooks['Stop']:
    for h in group.get('hooks', []):
        if 'play-notification' in h.get('command', ''):
            found_notification = True
assert found_notification, 'play-notification hook was lost'
\" 2>&1" "settings.json preserved: existing Stop hook"

# settings.json -- other settings preserved
check "$PYTHON -c \"
import json
d = json.load(open(r'$SETTINGS_WIN'))
assert d.get('alwaysThinkingEnabled') == True, 'alwaysThinkingEnabled was lost'
\" 2>&1" "settings.json preserved: alwaysThinkingEnabled"

# Idempotency: run install again and verify no duplicate hooks
echo "y" | bash "$PROJECT_ROOT/install.sh" 2>&1 > /dev/null
check "$PYTHON -c \"
import json
d = json.load(open(r'$SETTINGS_WIN'))
for event in ['SessionStart', 'PreToolUse', 'PostToolUse']:
    notemap_count = 0
    for group in d.get('hooks', {}).get(event, []):
        for h in group.get('hooks', []):
            if 'scripts/notemap/' in h.get('command', ''):
                notemap_count += 1
    assert notemap_count == 1, f'{event} has {notemap_count} notemap entries (expected 1)'
\" 2>&1" "Idempotent: re-install did not duplicate hooks"

echo ""
echo "  --- Post-install summary: $CHECKS checks, $FAILURES failures ---"
echo ""

if [ $FAILURES -gt 0 ]; then
    echo -e "  ${RED}${BOLD}INSTALL VERIFICATION FAILED${RESET} -- skipping uninstall test"
    echo ""
    # Don't clean up so we can inspect
    exit 1
fi

# ============================================================================
#  Create some fake notes (simulate user data)
# ============================================================================

mkdir -p "$TEMP_DIR/.claude/notemap/test-lib"
cat > "$TEMP_DIR/.claude/notemap/test-lib/test-note.md" << 'EOF'
---
id: "test-lib-test-note"
library: "test-lib"
type: "knowledge"
topic: "Test Note"
---

## Notes
This is a test note.

## Summary
Test note for install/uninstall testing.
EOF
info "Created fake note (simulates user data)"

# ============================================================================
#  Run uninstall (with HOME still overridden)
# ============================================================================

echo ""
echo "  --- Running uninstall.sh ---"
echo ""

# Non-interactive: auto-yes for uninstall, auto-no for note data removal
echo "y" | bash "$PROJECT_ROOT/uninstall.sh" 2>&1 | sed 's/^/    /'
UNINSTALL_EXIT=$?

echo ""

check '[ $UNINSTALL_EXIT -eq 0 ]' "uninstall.sh exited with code 0"

# ============================================================================
#  Post-uninstall integrity checks
# ============================================================================

echo ""
echo "  --- Post-uninstall integrity checks ---"
echo ""

# MCP server removed
check "[ ! -d '$TEMP_DIR/.claude/notemap-mcp' ]" "MCP server directory removed"

# Docs removed
check "[ ! -f '$TEMP_DIR/.claude/docs/notemap.md' ]" "Docs removed: notemap.md"

# Commands removed
check "[ ! -f '$TEMP_DIR/.claude/commands/notemap.md' ]" "Command removed: notemap.md"

# Skills removed
check "[ ! -f '$TEMP_DIR/.claude/skills/notemap-review.md' ]" "Skill removed: notemap-review.md"

# CLAUDE.md -- sentinels removed
check "! grep -q 'NOTEMAP:INSTRUCTIONS:BEGIN' '$TEMP_DIR/.claude/CLAUDE.md'" "CLAUDE.md: BEGIN sentinel removed"
check "! grep -q 'NOTEMAP:INSTRUCTIONS:END' '$TEMP_DIR/.claude/CLAUDE.md'" "CLAUDE.md: END sentinel removed"
check "! grep -q 'Notemap -- PERSISTENT KNOWLEDGE BASE' '$TEMP_DIR/.claude/CLAUDE.md'" "CLAUDE.md: notemap section removed"

# CLAUDE.md -- pre-existing content still preserved after uninstall
check "grep -q 'Existing Section' '$TEMP_DIR/.claude/CLAUDE.md'" "CLAUDE.md still has: Existing Section"
check "grep -q 'Another Section' '$TEMP_DIR/.claude/CLAUDE.md'" "CLAUDE.md still has: Another Section"

# .claude.json -- notemap entry removed
check "$PYTHON -c \"
import json
d = json.load(open(r'$MCP_JSON_WIN'))
assert 'notemap' not in d.get('mcpServers', {}), 'notemap still in mcpServers'
\" 2>&1" ".claude.json: notemap entry removed"

# .claude.json -- existing server STILL preserved
check "$PYTHON -c \"
import json
d = json.load(open(r'$MCP_JSON_WIN'))
assert 'other-server' in d.get('mcpServers', {}), 'other-server was lost during uninstall'
\" 2>&1" ".claude.json still has: other-server"

# .claude.json -- other settings STILL preserved
check "$PYTHON -c \"
import json
d = json.load(open(r'$MCP_JSON_WIN'))
assert d.get('someOtherSetting') == True, 'someOtherSetting lost during uninstall'
\" 2>&1" ".claude.json still has: someOtherSetting"

# .claude.json -- file still exists (not deleted)
check "[ -f '$TEMP_DIR/.claude.json' ]" ".claude.json file still exists (not deleted)"

# Hook scripts removed
check "[ ! -d '$TEMP_DIR/.claude/scripts/notemap' ]" "Hook scripts directory removed"

# settings.json -- notemap hooks removed
check "$PYTHON -c \"
import json
d = json.load(open(r'$SETTINGS_WIN'))
hooks = d.get('hooks', {})
for event in list(hooks.keys()):
    for group in hooks[event]:
        for h in group.get('hooks', []):
            assert 'scripts/notemap/' not in h.get('command', ''), f'notemap hook still in {event}'
\" 2>&1" "settings.json: notemap hooks removed"

# settings.json -- existing Stop hook STILL preserved
check "$PYTHON -c \"
import json
d = json.load(open(r'$SETTINGS_WIN'))
hooks = d.get('hooks', {})
assert 'Stop' in hooks, 'Stop hook was lost during uninstall'
found = False
for group in hooks['Stop']:
    for h in group.get('hooks', []):
        if 'play-notification' in h.get('command', ''):
            found = True
assert found, 'play-notification hook lost during uninstall'
\" 2>&1" "settings.json still has: Stop hook"

# settings.json -- no empty hook arrays left behind (prevents terminal corruption)
check "$PYTHON -c \"
import json
d = json.load(open(r'$SETTINGS_WIN'))
hooks = d.get('hooks', {})
for event, arr in hooks.items():
    assert len(arr) > 0, f'Empty hook array left behind: {event}'
\" 2>&1" "settings.json: no empty hook arrays (corruption prevention)"

# settings.json -- other settings STILL preserved
check "$PYTHON -c \"
import json
d = json.load(open(r'$SETTINGS_WIN'))
assert d.get('alwaysThinkingEnabled') == True, 'alwaysThinkingEnabled lost during uninstall'
\" 2>&1" "settings.json still has: alwaysThinkingEnabled"

# settings.json -- file still exists
check "[ -f '$TEMP_DIR/.claude/settings.json' ]" "settings.json file still exists (not deleted)"

# Note storage preserved (default: don't delete)
check "[ -d '$TEMP_DIR/.claude/notemap' ]" "Note storage preserved (not deleted)"
check "[ -f '$TEMP_DIR/.claude/notemap/test-lib/test-note.md' ]" "User note preserved: test-note.md"

# Backup created
BACKUP_COUNT=$(ls -d "$TEMP_DIR/.claude/.notemap-backup-"* 2>/dev/null | wc -l)
check "[ $BACKUP_COUNT -gt 0 ]" "Uninstall backup directory created ($BACKUP_COUNT found)"

# ============================================================================
#  Cleanup
# ============================================================================

echo ""
echo "  --- Cleaning up temp/ ---"
echo ""

rm -rf "$TEMP_DIR"
check "[ ! -d '$TEMP_DIR' ]" "temp/ directory removed"

# ============================================================================
#  Results
# ============================================================================

echo ""
echo "  ============================================================"
if [ $FAILURES -eq 0 ]; then
    echo -e "    ${GREEN}${BOLD}ALL $CHECKS CHECKS PASSED${RESET}"
else
    echo -e "    ${RED}${BOLD}$FAILURES of $CHECKS CHECKS FAILED${RESET}"
fi
echo "  ============================================================"
echo ""

# Reset HOME
export HOME="$TEMP_DIR"  # Already set, will be irrelevant after script exits

exit $FAILURES
