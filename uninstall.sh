#!/usr/bin/env bash
# uninstall.sh -- Notemap uninstaller for macOS / Linux / Windows Git Bash
set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
MCP_DIR="$CLAUDE_DIR/notemap-mcp"
DOCS_DIR="$CLAUDE_DIR/docs"
SKILLS_DIR="$CLAUDE_DIR/skills"
COMMANDS_DIR="$CLAUDE_DIR/commands"
NOTES_DIR="$CLAUDE_DIR/notemap"
SCRIPTS_DIR="$CLAUDE_DIR/scripts/notemap"
MCP_JSON="$HOME/.claude.json"
SETTINGS_JSON="$CLAUDE_DIR/settings.json"
CLAUDE_MD="$CLAUDE_DIR/CLAUDE.md"

# Find Python for .claude.json manipulation
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
fi

# ============================================================================
#  Banner
# ============================================================================

echo ""
echo "  ============================================================"
echo "    NOTEMAP UNINSTALLER"
echo "  ============================================================"
echo ""

info()  { echo "  [INFO]  $*"; }
ok()    { echo "  [OK]    $*"; }
warn()  { echo "  [WARN]  $*"; }
fail()  { echo "  [FAIL]  $*"; exit 1; }

# ============================================================================
#  Check what's installed
# ============================================================================

has_mcp=false
has_docs=false
has_skills=false
has_commands=false
has_hooks=false
has_claude_md=false
has_mcp_json=false
has_settings_json=false
has_notes=false

[ -d "$MCP_DIR" ] && has_mcp=true
[ -f "$DOCS_DIR/notemap.md" ] && has_docs=true
[ -f "$SKILLS_DIR/notemap-review.md" ] && has_skills=true
[ -f "$COMMANDS_DIR/notemap.md" ] && has_commands=true
[ -d "$SCRIPTS_DIR" ] && has_hooks=true
[ -f "$SETTINGS_JSON" ] && grep -q "scripts/notemap/" "$SETTINGS_JSON" 2>/dev/null && has_settings_json=true
[ -f "$CLAUDE_MD" ] && grep -q "NOTEMAP:INSTRUCTIONS:BEGIN" "$CLAUDE_MD" 2>/dev/null && has_claude_md=true
[ -f "$MCP_JSON" ] && [ -n "$PYTHON" ] && $PYTHON -c "
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
if 'notemap' in d.get('mcpServers', {}):
    sys.exit(0)
sys.exit(1)
" "$MCP_JSON" 2>/dev/null && has_mcp_json=true
[ -d "$NOTES_DIR" ] && [ "$(ls -A "$NOTES_DIR" 2>/dev/null)" ] && has_notes=true

if ! $has_mcp && ! $has_docs && ! $has_skills && ! $has_commands && ! $has_hooks && ! $has_claude_md && ! $has_mcp_json && ! $has_settings_json; then
    info "Notemap does not appear to be installed. Nothing to uninstall."
    exit 0
fi

echo "  This will uninstall notemap."
echo ""
echo "  The following will be backed up before removal:"
if $has_mcp;       then echo "    - Python MCP server ($MCP_DIR)"; fi
if $has_docs;      then echo "    - Supplementary docs (notemap.md)"; fi
if $has_skills;    then echo "    - Skill file (notemap-review.md)"; fi
if $has_commands;   then echo "    - Command file (notemap.md)"; fi
if $has_claude_md; then echo "    - CLAUDE.md (notemap sentinel blocks will be removed)"; fi
if $has_hooks;     then echo "    - Hook scripts ($SCRIPTS_DIR)"; fi
if $has_mcp_json;  then echo "    - .claude.json (notemap MCP entry will be removed, other settings preserved)"; fi
if $has_settings_json; then echo "    - settings.json (notemap hooks will be removed, other hooks preserved)"; fi
if $has_notes;     then echo "    - Note storage ($NOTES_DIR) -- will NOT be deleted unless you choose to"; fi
echo ""
echo "  Your stored notes will NOT be deleted unless you choose to."
echo ""

# Default to NO if non-interactive (piped from curl)
if [ -t 0 ]; then
    read -rp "  Continue? [y/N] " answer
else
    answer="y"
    info "Non-interactive mode: proceeding automatically"
fi

case "$answer" in
    [yY]|[yY][eE][sS]) ;;
    *)
        echo ""
        info "Uninstall cancelled."
        exit 0
        ;;
esac

# ============================================================================
#  Pre-uninstall backup (snapshot everything before deletion)
# ============================================================================

BACKUP_DIR=""
has_existing=false

[ -d "$MCP_DIR" ] && has_existing=true
[ -f "$DOCS_DIR/notemap.md" ] && has_existing=true
[ -f "$SKILLS_DIR/notemap-review.md" ] && has_existing=true
[ -f "$COMMANDS_DIR/notemap.md" ] && has_existing=true
[ -d "$SCRIPTS_DIR" ] && has_existing=true

if $has_existing || $has_claude_md || $has_mcp_json || $has_settings_json; then
    BACKUP_DIR="$CLAUDE_DIR/.notemap-backup-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$BACKUP_DIR"

    # Back up MCP server directory
    if [ -d "$MCP_DIR" ]; then
        cp -r "$MCP_DIR" "$BACKUP_DIR/notemap-mcp"
        ok "MCP server backed up"
    fi

    # Back up docs
    if [ -f "$DOCS_DIR/notemap.md" ]; then
        mkdir -p "$BACKUP_DIR/docs"
        cp "$DOCS_DIR/notemap.md" "$BACKUP_DIR/docs/notemap.md"
        ok "Docs backed up"
    fi

    # Back up skills
    if [ -f "$SKILLS_DIR/notemap-review.md" ]; then
        mkdir -p "$BACKUP_DIR/skills"
        cp "$SKILLS_DIR/notemap-review.md" "$BACKUP_DIR/skills/notemap-review.md"
        ok "Skills backed up"
    fi

    # Back up commands
    if [ -f "$COMMANDS_DIR/notemap.md" ]; then
        mkdir -p "$BACKUP_DIR/commands"
        cp "$COMMANDS_DIR/notemap.md" "$BACKUP_DIR/commands/notemap.md"
        ok "Commands backed up"
    fi

    # Back up hook scripts
    if [ -d "$SCRIPTS_DIR" ]; then
        cp -r "$SCRIPTS_DIR" "$BACKUP_DIR/scripts-notemap"
        ok "Hook scripts backed up"
    fi

    # Back up settings.json
    [ -f "$SETTINGS_JSON" ] && cp "$SETTINGS_JSON" "$BACKUP_DIR/settings.json"

    # Back up CLAUDE.md
    [ -f "$CLAUDE_MD" ] && cp "$CLAUDE_MD" "$BACKUP_DIR/CLAUDE.md"

    # Back up .claude.json
    [ -f "$MCP_JSON" ] && cp "$MCP_JSON" "$BACKUP_DIR/.claude.json"

    # Back up note storage
    if [ -d "$NOTES_DIR" ] && [ "$(ls -A "$NOTES_DIR" 2>/dev/null)" ]; then
        cp -r "$NOTES_DIR" "$BACKUP_DIR/notemap"
        ok "Note storage backed up"
    fi

    ok "Pre-uninstall backup created: $BACKUP_DIR"
else
    info "No existing files found to back up"
fi

# ============================================================================
#  Remove installed files
# ============================================================================

# MCP server directory (entire folder)
if [ -d "$MCP_DIR" ]; then
    rm -rf "$MCP_DIR"
    ok "Removed $MCP_DIR"
else
    info "MCP server directory not found (already removed?)"
fi

# Supplementary docs
if [ -f "$DOCS_DIR/notemap.md" ]; then
    rm -f "$DOCS_DIR/notemap.md"
    ok "Removed $DOCS_DIR/notemap.md"
fi

# Skill file
if [ -f "$SKILLS_DIR/notemap-review.md" ]; then
    rm -f "$SKILLS_DIR/notemap-review.md"
    ok "Removed $SKILLS_DIR/notemap-review.md"
fi

# Command file
if [ -f "$COMMANDS_DIR/notemap.md" ]; then
    rm -f "$COMMANDS_DIR/notemap.md"
    ok "Removed $COMMANDS_DIR/notemap.md"
fi

# Hook scripts
if [ -d "$SCRIPTS_DIR" ]; then
    rm -rf "$SCRIPTS_DIR"
    ok "Removed $SCRIPTS_DIR"
fi

# ============================================================================
#  Remove notemap hooks from settings.json
# ============================================================================

if $has_settings_json && [ -n "$PYTHON" ]; then
    cp "$SETTINGS_JSON" "$SETTINGS_JSON.bak"
    info "Backup created: settings.json.bak"

    $PYTHON -c "
import json, sys
path = sys.argv[1]
with open(path, 'r') as f:
    d = json.load(f)
hooks = d.get('hooks', {})
for event_name in list(hooks.keys()):
    if not isinstance(hooks[event_name], list):
        continue
    filtered = [
        group for group in hooks[event_name]
        if not any('scripts/notemap/' in h.get('command', '') for h in group.get('hooks', []))
    ]
    if filtered:
        hooks[event_name] = filtered
    else:
        del hooks[event_name]
if not hooks:
    d.pop('hooks', None)
with open(path, 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
" "$SETTINGS_JSON"
    ok "Removed notemap hooks from settings.json (other hooks preserved)"
fi

# ============================================================================
#  Remove sentinel blocks from CLAUDE.md
# ============================================================================

if [ -f "$CLAUDE_MD" ]; then
    content=$(cat "$CLAUDE_MD")
    modified=false

    # Remove INSTRUCTIONS block (inclusive of sentinels)
    if echo "$content" | grep -q "NOTEMAP:INSTRUCTIONS:BEGIN"; then
        # Create backup before modifying
        cp "$CLAUDE_MD" "$CLAUDE_MD.bak"
        info "Backup created: CLAUDE.md.bak"

        content=$(echo "$content" | awk '
            /<!-- NOTEMAP:INSTRUCTIONS:BEGIN -->/{skip=1; next}
            /<!-- NOTEMAP:INSTRUCTIONS:END -->/{skip=0; next}
            !skip{print}
        ')
        modified=true
        ok "Removed notemap instructions block from CLAUDE.md"
    fi

    # Clean up trailing blank lines left behind
    if $modified; then
        echo "$content" | sed -e :a -e '/^\n*$/{$d;N;ba;}' > "$CLAUDE_MD"
    fi
else
    info "No CLAUDE.md found (nothing to clean)"
fi

# ============================================================================
#  Remove notemap entry from .claude.json
# ============================================================================

if [ -f "$MCP_JSON" ]; then
    if [ -n "$PYTHON" ] && $PYTHON -c "
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
if 'notemap' in d.get('mcpServers', {}):
    sys.exit(0)
sys.exit(1)
" "$MCP_JSON" 2>/dev/null; then
        # Back up before modifying
        cp "$MCP_JSON" "$MCP_JSON.bak"
        info "Backup created: .claude.json.bak"

        # Remove ONLY the notemap key from mcpServers.
        # Preserve ALL other keys in the file (this is Claude Code's main config).
        # Never delete the file -- it contains other settings.
        $PYTHON -c "
import json, sys
path = sys.argv[1]
with open(path, 'r') as f:
    d = json.load(f)
d.get('mcpServers', {}).pop('notemap', None)
# If no servers remain, remove the empty mcpServers key
if not d.get('mcpServers'):
    d.pop('mcpServers', None)
with open(path, 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
" "$MCP_JSON"
        ok "Removed notemap entry from .claude.json"
    else
        info "No notemap entry found in .claude.json"
    fi
else
    info "No .claude.json found"
fi

# ============================================================================
#  Prompt for note data removal
# ============================================================================

if [ -d "$NOTES_DIR" ]; then
    echo ""
    # Default to NO if non-interactive (piped)
    if [ -t 0 ]; then
        read -rp "  Remove stored notes ($NOTES_DIR)? [y/N] " answer
    else
        answer="n"
        info "Non-interactive mode: keeping stored notes"
    fi

    case "$answer" in
        [yY]|[yY][eE][sS])
            rm -rf "$NOTES_DIR"
            ok "Removed $NOTES_DIR"
            ;;
        *)
            info "Kept $NOTES_DIR (your notes are preserved)"
            ;;
    esac
fi

# ============================================================================
#  Done
# ============================================================================

echo ""
echo "  ============================================================"
echo "    NOTEMAP UNINSTALLED"
echo "  ============================================================"
echo ""
echo "    Restart Claude Code to complete the removal."
if [ -n "$BACKUP_DIR" ]; then
    echo ""
    echo "    Backup of removed files: $BACKUP_DIR"
    echo "    (Safe to delete once you've confirmed the uninstall is correct)"
fi
echo ""
