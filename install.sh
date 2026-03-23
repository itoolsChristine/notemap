#!/usr/bin/env bash
# install.sh -- Notemap installer for macOS / Linux / Windows Git Bash
# Usage: curl -fsSL https://raw.githubusercontent.com/itoolsChristine/notemap/main/install.sh | bash
set -euo pipefail

# ============================================================================
#  Constants
# ============================================================================

REPO_URL="https://raw.githubusercontent.com/itoolsChristine/notemap/main"
CLAUDE_DIR="$HOME/.claude"
MCP_DIR="$CLAUDE_DIR/notemap-mcp"
NOTES_DIR="$CLAUDE_DIR/notemap"
DOCS_DIR="$CLAUDE_DIR/docs"
SKILLS_DIR="$CLAUDE_DIR/skills"
COMMANDS_DIR="$CLAUDE_DIR/commands"
CLAUDE_MD="$CLAUDE_DIR/CLAUDE.md"
MCP_JSON="$HOME/.claude.json"
SETTINGS_JSON="$CLAUDE_DIR/settings.json"
SCRIPTS_DIR="$CLAUDE_DIR/scripts/notemap"

# Files to install (source-relative-path : destination)
MCP_FILES="server.py notes.py search.py audit.py lint.py preflight.py check.py index.py models.py utils.py"
DOC_FILES="notemap.md"
SKILL_FILES="notemap-review.md"
COMMAND_FILES="notemap.md"
HOOK_FILES="session-start.sh pre-edit.sh post-edit.sh"

# ============================================================================
#  Banner
# ============================================================================

banner() {
    echo ""
    echo "  ============================================================"
    echo "    NOTEMAP INSTALLER"
    echo "    Cornell note-taking for Claude Code -- remember what you learn."
    echo "  ============================================================"
    echo ""
}

# ============================================================================
#  Helpers
# ============================================================================

info()    { echo "  [INFO]  $*"; }
ok()      { echo "  [OK]    $*"; }
warn()    { echo "  [WARN]  $*"; }
fail()    { echo "  [ERROR] $*" >&2; exit 1; }

# ============================================================================
#  Pre-flight checks
# ============================================================================

preflight() {
    # Find Python
    PYTHON=""
    if command -v python3 &>/dev/null; then
        PYTHON="python3"
    elif command -v python &>/dev/null; then
        PYTHON="python"
    fi

    if [ -z "$PYTHON" ]; then
        fail "Python not found. Install Python 3.10+ and ensure it is in your PATH."
    fi

    # Resolve to absolute path for verification
    PYTHON_ABS="$(command -v "$PYTHON")"

    # Verify Python version >= 3.10
    PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

    if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
        fail "Python 3.10+ required (found $PY_VERSION). Please upgrade Python."
    fi
    ok "Python $PY_VERSION ($PYTHON_ABS)"

    # Check pip is available
    if ! $PYTHON -m pip --version &>/dev/null; then
        fail "pip not found. Install pip for $PYTHON (python -m ensurepip or your package manager)."
    fi
    ok "pip available"

    # Check Claude Code directory
    if [ ! -d "$CLAUDE_DIR" ]; then
        fail "$CLAUDE_DIR does not exist. Install and run Claude Code at least once first."
    fi
    ok "Claude Code directory exists"

    # Check write permissions
    if [ ! -w "$CLAUDE_DIR" ]; then
        fail "No write permission to $CLAUDE_DIR"
    fi
    ok "Write permissions verified"
}

# ============================================================================
#  Determine source mode (local clone vs. curl from GitHub)
# ============================================================================

detect_source() {
    # If this script is running from a cloned repo, src/ will exist nearby
    SCRIPT_DIR=""
    SOURCE_MODE="remote"

    # When piped from curl, BASH_SOURCE is empty
    if [ -n "${BASH_SOURCE[0]:-}" ] && [ "${BASH_SOURCE[0]}" != "bash" ]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        if [ -d "$SCRIPT_DIR/src/notemap-mcp" ] && [ -d "$SCRIPT_DIR/src/docs" ] && [ -d "$SCRIPT_DIR/src/commands" ]; then
            SOURCE_MODE="local"
        fi
    fi

    if [ "$SOURCE_MODE" = "local" ]; then
        info "Installing from local clone: $SCRIPT_DIR"
    else
        info "Installing from GitHub: $REPO_URL"
    fi
}

# ============================================================================
#  File retrieval (local copy or curl download)
# ============================================================================

get_file() {
    local src_rel="$1"   # e.g. src/notemap-mcp/server.py
    local dest="$2"      # e.g. ~/.claude/notemap-mcp/server.py

    if [ "$SOURCE_MODE" = "local" ]; then
        if [ ! -f "$SCRIPT_DIR/$src_rel" ]; then
            fail "Local file not found: $SCRIPT_DIR/$src_rel"
        fi
        cp "$SCRIPT_DIR/$src_rel" "$dest"
    else
        local url="$REPO_URL/$src_rel"
        if ! curl -fsSL "$url" -o "$dest" 2>/dev/null; then
            fail "Failed to download: $url"
        fi
    fi
}

# ============================================================================
#  Confirm before proceeding
# ============================================================================

confirm_install() {
    IS_UPGRADE=false
    local existing_mcp=false
    local existing_docs=false
    local existing_skills=false
    local existing_commands=false
    local existing_hooks=false
    local existing_claude_md=false
    local existing_mcp_json=false
    local existing_notes=false

    for f in $MCP_FILES; do [ -f "$MCP_DIR/$f" ] && existing_mcp=true && break; done
    for f in $DOC_FILES; do [ -f "$DOCS_DIR/$f" ] && existing_docs=true && break; done
    for f in $SKILL_FILES; do [ -f "$SKILLS_DIR/$f" ] && existing_skills=true && break; done
    for f in $COMMAND_FILES; do [ -f "$COMMANDS_DIR/$f" ] && existing_commands=true && break; done
    [ -d "$SCRIPTS_DIR" ] && existing_hooks=true
    [ -f "$CLAUDE_MD" ] && existing_claude_md=true
    [ -f "$MCP_JSON" ] && existing_mcp_json=true
    [ -d "$NOTES_DIR" ] && [ "$(ls -A "$NOTES_DIR" 2>/dev/null)" ] && existing_notes=true

    if $existing_mcp || $existing_docs || $existing_skills || $existing_commands || $existing_hooks; then
        IS_UPGRADE=true
    fi

    echo ""
    if $IS_UPGRADE; then
        echo "  Existing notemap installation detected."
        echo "  This will UPGRADE your installation."
    else
        echo "  This will install notemap."
    fi

    echo ""
    echo "  The following will be backed up before any changes:"
    if $existing_mcp;      then echo "    - MCP server files ($MCP_DIR)"; fi
    if $existing_docs;     then echo "    - Documentation (notemap.md)"; fi
    if $existing_skills;   then echo "    - Skill files (notemap-review.md)"; fi
    if $existing_commands; then echo "    - Command files (notemap.md)"; fi
    if $existing_hooks;    then echo "    - Hook scripts ($SCRIPTS_DIR)"; fi
    if $existing_claude_md; then echo "    - CLAUDE.md (sentinel blocks will be updated, not replaced)"; fi
    if $existing_mcp_json; then echo "    - .claude.json (notemap MCP entry will be merged, other settings preserved)"; fi
    if $existing_notes;    then echo "    - Existing notes ($NOTES_DIR)"; fi
    if ! $existing_mcp && ! $existing_docs && ! $existing_skills && ! $existing_commands && ! $existing_claude_md && ! $existing_mcp_json && ! $existing_notes; then
        echo "    (nothing to back up -- fresh install)"
    fi

    echo ""
    if $IS_UPGRADE; then
        echo "  Your existing notes will NOT be erased."
    fi

    echo ""
    # Default to NO if non-interactive (piped from curl)
    if [ -t 0 ]; then
        read -rp "  Continue? [y/N] " answer
    else
        # Non-interactive: proceed automatically (curl | bash usage)
        answer="y"
        info "Non-interactive mode: proceeding automatically"
    fi

    case "$answer" in
        [yY]|[yY][eE][sS]) ;;
        *)
            echo ""
            info "Installation cancelled."
            exit 0
            ;;
    esac
}

# ============================================================================
#  Pre-install backup (snapshot everything that will be overwritten)
# ============================================================================

BACKUP_DIR=""

backup_existing() {
    local has_existing=false

    # Check if any files exist that we're about to overwrite
    for f in $MCP_FILES; do [ -f "$MCP_DIR/$f" ] && has_existing=true && break; done
    [ -f "$MCP_DIR/requirements.txt" ] && has_existing=true
    for f in $DOC_FILES; do [ -f "$DOCS_DIR/$f" ] && has_existing=true && break; done
    for f in $SKILL_FILES; do [ -f "$SKILLS_DIR/$f" ] && has_existing=true && break; done
    for f in $COMMAND_FILES; do [ -f "$COMMANDS_DIR/$f" ] && has_existing=true && break; done
    [ -d "$SCRIPTS_DIR" ] && has_existing=true
    [ -f "$SETTINGS_JSON" ] && has_existing=true
    [ -f "$CLAUDE_MD" ] && has_existing=true
    [ -f "$MCP_JSON" ] && has_existing=true

    if ! $has_existing; then
        info "Fresh install (no existing files to back up)"
        return
    fi

    BACKUP_DIR="$CLAUDE_DIR/.notemap-backup-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$BACKUP_DIR/notemap-mcp" "$BACKUP_DIR/docs" "$BACKUP_DIR/skills" "$BACKUP_DIR/commands"

    # Back up MCP server files
    for f in $MCP_FILES; do
        [ -f "$MCP_DIR/$f" ] && cp "$MCP_DIR/$f" "$BACKUP_DIR/notemap-mcp/$f"
    done
    [ -f "$MCP_DIR/requirements.txt" ] && cp "$MCP_DIR/requirements.txt" "$BACKUP_DIR/notemap-mcp/requirements.txt"

    # Back up docs
    for f in $DOC_FILES; do
        [ -f "$DOCS_DIR/$f" ] && cp "$DOCS_DIR/$f" "$BACKUP_DIR/docs/$f"
    done

    # Back up skills
    for f in $SKILL_FILES; do
        [ -f "$SKILLS_DIR/$f" ] && cp "$SKILLS_DIR/$f" "$BACKUP_DIR/skills/$f"
    done

    # Back up commands
    for f in $COMMAND_FILES; do
        [ -f "$COMMANDS_DIR/$f" ] && cp "$COMMANDS_DIR/$f" "$BACKUP_DIR/commands/$f"
    done

    # Back up hook scripts
    if [ -d "$SCRIPTS_DIR" ]; then
        cp -r "$SCRIPTS_DIR" "$BACKUP_DIR/scripts-notemap"
    fi

    # Back up settings.json
    [ -f "$SETTINGS_JSON" ] && cp "$SETTINGS_JSON" "$BACKUP_DIR/settings.json"

    # Back up CLAUDE.md
    [ -f "$CLAUDE_MD" ] && cp "$CLAUDE_MD" "$BACKUP_DIR/CLAUDE.md"

    # Back up .claude.json
    [ -f "$MCP_JSON" ] && cp "$MCP_JSON" "$BACKUP_DIR/.claude.json"

    ok "Pre-install backup created: $BACKUP_DIR"
}

on_failure() {
    echo ""
    echo "  [ERROR] Installation failed!"
    if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
        echo ""
        echo "  Your original files were backed up before any changes."
        echo "  To restore, run:"
        echo ""
        echo "    # Restore MCP server"
        echo "    cp \"$BACKUP_DIR/notemap-mcp/\"* \"$MCP_DIR/\" 2>/dev/null"
        echo "    # Restore docs"
        echo "    cp \"$BACKUP_DIR/docs/\"* \"$DOCS_DIR/\" 2>/dev/null"
        echo "    # Restore skills"
        echo "    cp \"$BACKUP_DIR/skills/\"* \"$SKILLS_DIR/\" 2>/dev/null"
        echo "    # Restore commands"
        echo "    cp \"$BACKUP_DIR/commands/\"* \"$COMMANDS_DIR/\" 2>/dev/null"
        echo "    # Restore CLAUDE.md"
        echo "    cp \"$BACKUP_DIR/CLAUDE.md\" \"$CLAUDE_MD\" 2>/dev/null"
        echo "    # Restore .claude.json"
        echo "    cp \"$BACKUP_DIR/.claude.json\" \"$MCP_JSON\" 2>/dev/null"
        echo ""
        echo "  Backup location: $BACKUP_DIR"
    fi
}

# ============================================================================
#  Create directories
# ============================================================================

create_dirs() {
    mkdir -p "$MCP_DIR" "$NOTES_DIR" "$DOCS_DIR" "$SKILLS_DIR" "$COMMANDS_DIR" "$SCRIPTS_DIR"
    ok "Directories created"
}

# ============================================================================
#  Install files
# ============================================================================

install_files() {
    # MCP server Python files
    for f in $MCP_FILES; do
        get_file "src/notemap-mcp/$f" "$MCP_DIR/$f"
    done
    ok "MCP server installed (10 Python files)"

    # requirements.txt
    get_file "src/notemap-mcp/requirements.txt" "$MCP_DIR/requirements.txt"
    ok "Requirements file installed"

    # Documentation
    for f in $DOC_FILES; do
        get_file "src/docs/$f" "$DOCS_DIR/$f"
    done
    ok "Documentation installed (1 file)"

    # Skill files
    for f in $SKILL_FILES; do
        get_file "src/skills/$f" "$SKILLS_DIR/$f"
    done
    ok "Skill files installed (1 file)"

    # Command files
    for f in $COMMAND_FILES; do
        get_file "src/commands/$f" "$COMMANDS_DIR/$f"
    done
    ok "Command files installed (1 file)"

    # Hook scripts
    for f in $HOOK_FILES; do
        get_file "src/hooks/$f" "$SCRIPTS_DIR/$f"
        chmod +x "$SCRIPTS_DIR/$f" 2>/dev/null || true
    done
    ok "Hook scripts installed (3 files)"

    # Clean up legacy flat hook scripts (pre-1.1.0 manual installs)
    for f in notemap-session-start.sh notemap-pre-edit.sh notemap-post-edit.sh; do
        local legacy="$CLAUDE_DIR/scripts/$f"
        if [ -f "$legacy" ]; then
            rm -f "$legacy"
            info "Removed legacy hook script: $f"
        fi
    done
}

# ============================================================================
#  Install pip dependencies
# ============================================================================

install_pip_deps() {
    info "Installing Python dependencies..."

    # Convert path for Windows Python if needed
    local req_path="$MCP_DIR/requirements.txt"
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*)
            req_path=$(cygpath -w "$req_path" 2>/dev/null || echo "$req_path")
            ;;
    esac

    if $PYTHON -m pip install -r "$req_path" --quiet 2>&1; then
        ok "Python dependencies installed"
    else
        warn "pip install had issues -- retrying with verbose output..."
        if $PYTHON -m pip install -r "$req_path" 2>&1; then
            ok "Python dependencies installed (with warnings)"
        else
            fail "Failed to install Python dependencies. Run manually: $PYTHON -m pip install -r \"$req_path\""
        fi
    fi
}

# ============================================================================
#  CLAUDE.md injection
# ============================================================================

inject_claude_md() {
    local instr_file

    # Load instruction content
    if [ "$SOURCE_MODE" = "local" ]; then
        instr_file="$SCRIPT_DIR/src/claude-md/notemap-instructions.md"
        if [ ! -f "$instr_file" ]; then
            fail "CLAUDE.md source file not found: src/claude-md/notemap-instructions.md"
        fi
        INSTR_CONTENT=$(cat "$instr_file")
    else
        INSTR_CONTENT=$(curl -fsSL "$REPO_URL/src/claude-md/notemap-instructions.md" 2>/dev/null) || fail "Failed to download notemap-instructions.md"
    fi

    # Sentinel markers
    local INSTR_BEGIN="<!-- NOTEMAP:INSTRUCTIONS:BEGIN -->"
    local INSTR_END="<!-- NOTEMAP:INSTRUCTIONS:END -->"

    # Case 1: No CLAUDE.md -- create it
    if [ ! -f "$CLAUDE_MD" ]; then
        {
            echo "# CLAUDE.md"
            echo ""
            echo "$INSTR_CONTENT"
        } > "$CLAUDE_MD"
        ok "Created $CLAUDE_MD with notemap instructions"
        return
    fi

    # Create backup before any modification
    cp "$CLAUDE_MD" "$CLAUDE_MD.bak"
    info "Backup created: CLAUDE.md.bak"

    local content
    content=$(cat "$CLAUDE_MD")

    # Check for existing "Notemap" heading without sentinels
    if echo "$content" | grep -q "## Notemap" && ! echo "$content" | grep -q "$INSTR_BEGIN"; then
        warn "Found existing \"Notemap\" section in CLAUDE.md without sentinel markers."
        warn "The installer will append sentinel-wrapped blocks at the end of the file."
        warn "You may want to manually remove the old section to avoid duplication."
    fi

    local has_sentinels=false
    echo "$content" | grep -q "$INSTR_BEGIN" && has_sentinels=true

    # --- Instructions block ---
    if $has_sentinels; then
        # Extract existing block for comparison
        local existing_instr
        existing_instr=$(echo "$content" | awk '
            /<!-- NOTEMAP:INSTRUCTIONS:BEGIN -->/{found=1}
            found{print}
            /<!-- NOTEMAP:INSTRUCTIONS:END -->/{exit}
        ')
        if [ "$existing_instr" = "$INSTR_CONTENT" ]; then
            ok "Instructions block is up to date"
        else
            content=$(echo "$content" | awk -v new="$INSTR_CONTENT" '
                /<!-- NOTEMAP:INSTRUCTIONS:BEGIN -->/{found=1; print new; next}
                /<!-- NOTEMAP:INSTRUCTIONS:END -->/{found=0; next}
                !found{print}
            ')
            ok "Updated instructions block in CLAUDE.md"
        fi
    else
        content="$content"$'\n\n'"$INSTR_CONTENT"
        ok "Appended instructions block to CLAUDE.md"
    fi

    echo "$content" > "$CLAUDE_MD"
}

# ============================================================================
#  .claude.json MCP injection
# ============================================================================

inject_mcp_config() {
    # Build the server.py path for .claude.json
    # On Windows (Git Bash), convert to forward-slash native path
    local server_path="$MCP_DIR/server.py"
    local python_cmd="$PYTHON"

    # Detect platform and convert server path for Claude Code
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*)
            server_path=$(cygpath -m "$server_path" 2>/dev/null || echo "$server_path")
            python_cmd="python"
            ;;
        Darwin*)
            python_cmd="python3"
            ;;
        *)
            python_cmd="python3"
            ;;
    esac

    local is_new=false
    if [ ! -f "$MCP_JSON" ]; then
        is_new=true
    else
        # Back up before modifying
        cp "$MCP_JSON" "$MCP_JSON.bak"
    fi

    # Use Python to read the FULL config file, merge only the notemap entry
    # into mcpServers, and write back ALL other keys untouched.
    # ~/.claude.json contains many Claude Code settings beyond mcpServers.
    local merge_script
    merge_script=$(cat <<'PYEOF'
import json
import sys

config_path = sys.argv[1]
python_cmd = sys.argv[2]
server_py = sys.argv[3]

try:
    with open(config_path, "r") as f:
        data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    data = {}

if "mcpServers" not in data:
    data["mcpServers"] = {}

data["mcpServers"]["notemap"] = {
    "type": "stdio",
    "command": python_cmd,
    "args": [server_py],
    "env": {}
}

with open(config_path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PYEOF
    )

    if echo "$merge_script" | $PYTHON - "$MCP_JSON" "$python_cmd" "$server_path" 2>/dev/null; then
        if $is_new; then
            ok "Created $MCP_JSON with notemap server"
        else
            ok "Merged notemap server into $MCP_JSON"
        fi
    else
        fail "Failed to update $MCP_JSON. Your backup is at $MCP_JSON.bak"
    fi
}

# ============================================================================
#  Hook registration in settings.json
# ============================================================================

inject_hooks_config() {
    info "Registering notemap hooks in settings.json..."

    # Resolve scripts path for the hook commands
    local scripts_path="$SCRIPTS_DIR"
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*)
            scripts_path=$(cygpath -m "$SCRIPTS_DIR" 2>/dev/null || echo "$SCRIPTS_DIR")
            ;;
    esac

    local merge_script
    merge_script=$(cat <<'PYEOF'
import json
import sys

settings_path = sys.argv[1]
scripts_dir = sys.argv[2]

try:
    with open(settings_path, "r") as f:
        data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    data = {}

if "hooks" not in data:
    data["hooks"] = {}

notemap_hooks = {
    "SessionStart": {
        "matcher": "startup|resume",
        "hooks": [{"type": "command", "command": f'bash "{scripts_dir}/session-start.sh"'}]
    },
    "PreToolUse": {
        "matcher": "Edit|Write",
        "hooks": [{"type": "command", "command": f'bash "{scripts_dir}/pre-edit.sh"'}]
    },
    "PostToolUse": {
        "matcher": "Edit|Write",
        "hooks": [{"type": "command", "command": f'bash "{scripts_dir}/post-edit.sh"'}]
    }
}

for event_name, hook_group in notemap_hooks.items():
    if event_name not in data["hooks"]:
        data["hooks"][event_name] = []

    # Find existing notemap entry (by command path containing scripts/notemap/)
    existing_idx = None
    for i, group in enumerate(data["hooks"][event_name]):
        for h in group.get("hooks", []):
            if "scripts/notemap/" in h.get("command", ""):
                existing_idx = i
                break

    if existing_idx is not None:
        data["hooks"][event_name][existing_idx] = hook_group
    else:
        data["hooks"][event_name].append(hook_group)

with open(settings_path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PYEOF
    )

    if echo "$merge_script" | $PYTHON - "$SETTINGS_JSON" "$scripts_path" 2>/dev/null; then
        ok "Notemap hooks registered in settings.json"
    else
        warn "Failed to register hooks in settings.json (non-critical)"
    fi
}

# ============================================================================
#  Post-install verification
# ============================================================================

verify() {
    local errors=0

    # Check Python can import MCP server modules
    local mcp_dir_py="$MCP_DIR"
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*)
            mcp_dir_py=$(cygpath -w "$MCP_DIR" 2>/dev/null || echo "$MCP_DIR")
            ;;
    esac
    if ! $PYTHON -c "import sys; sys.path.insert(0, r'$mcp_dir_py'); import server" &>/dev/null; then
        warn "server.py import check failed (may need pip dependencies)"
        errors=$((errors + 1))
    fi

    # Verify all expected files exist
    local expected_files=(
        "$MCP_DIR/server.py"
        "$MCP_DIR/notes.py"
        "$MCP_DIR/search.py"
        "$MCP_DIR/audit.py"
        "$MCP_DIR/lint.py"
        "$MCP_DIR/index.py"
        "$MCP_DIR/models.py"
        "$MCP_DIR/utils.py"
        "$MCP_DIR/requirements.txt"
        "$DOCS_DIR/notemap.md"
        "$SKILLS_DIR/notemap-review.md"
        "$COMMANDS_DIR/notemap.md"
        "$SCRIPTS_DIR/session-start.sh"
        "$SCRIPTS_DIR/pre-edit.sh"
        "$SCRIPTS_DIR/post-edit.sh"
    )
    for f in "${expected_files[@]}"; do
        if [ ! -f "$f" ]; then
            warn "Missing: $f"
            errors=$((errors + 1))
        fi
    done

    # Verify CLAUDE.md has sentinel pair
    if [ -f "$CLAUDE_MD" ]; then
        if ! grep -q "NOTEMAP:INSTRUCTIONS:BEGIN" "$CLAUDE_MD"; then
            warn "CLAUDE.md missing notemap instructions sentinel"
            errors=$((errors + 1))
        fi
    else
        warn "CLAUDE.md not found after install"
        errors=$((errors + 1))
    fi

    # Verify .claude.json has notemap entry
    if [ -f "$MCP_JSON" ]; then
        if ! grep -q '"notemap"' "$MCP_JSON"; then
            warn ".claude.json missing notemap server entry"
            errors=$((errors + 1))
        fi
    else
        warn ".claude.json not found after install"
        errors=$((errors + 1))
    fi

    # Verify settings.json has notemap hook entries
    if [ -f "$SETTINGS_JSON" ]; then
        if ! grep -q "scripts/notemap/" "$SETTINGS_JSON"; then
            warn "settings.json missing notemap hook entries"
            errors=$((errors + 1))
        fi
    else
        warn "settings.json not found after install"
        errors=$((errors + 1))
    fi

    # Verify notes directory exists
    if [ ! -d "$NOTES_DIR" ]; then
        warn "Notes directory not created: $NOTES_DIR"
        errors=$((errors + 1))
    fi

    local file_count=${#expected_files[@]}
    if [ $errors -eq 0 ]; then
        ok "All $file_count files verified"
        ok "CLAUDE.md sentinel verified"
        ok ".claude.json entry verified"
        ok "settings.json hooks verified"
        ok "Notes directory verified"
    else
        warn "$errors verification issue(s) found"
    fi

    return $errors
}

# ============================================================================
#  Success message
# ============================================================================

success_message() {
    echo ""
    echo "  ============================================================"
    echo "    NOTEMAP INSTALLED SUCCESSFULLY"
    echo "  ============================================================"
    echo ""
    echo "    What was installed:"
    echo "      MCP server:  $MCP_DIR/ (10 Python files)"
    echo "      Note storage: $NOTES_DIR/"
    echo "      Docs:         $DOCS_DIR/notemap.md"
    echo "      Skill:        $SKILLS_DIR/notemap-review.md"
    echo "      Command:      $COMMANDS_DIR/notemap.md"
    echo "      Hooks:        $SCRIPTS_DIR/ (3 scripts)"
    echo "      MCP config:   $MCP_JSON"
    echo "      Hook config:  $SETTINGS_JSON"
    echo "      CLAUDE.md:    Instructions injected"
    echo ""
    echo "    Usage (in Claude Code):"
    echo "      notemap tools are available automatically via MCP"
    echo "      /notemap review    Run periodic note maintenance"
    echo ""
    echo "    To update:  Re-run this installer"
    echo "    To remove:  curl -fsSL $REPO_URL/uninstall.sh | bash"
    echo ""
    echo "  ============================================================"
    echo ""
}

# ============================================================================
#  Main
# ============================================================================

main() {
    banner
    preflight
    detect_source
    confirm_install
    backup_existing
    trap on_failure ERR
    create_dirs
    install_files
    install_pip_deps
    inject_claude_md
    inject_mcp_config
    inject_hooks_config
    trap - ERR
    verify || true
    success_message
    if [ -n "$BACKUP_DIR" ]; then
        info "Pre-install backup: $BACKUP_DIR"
    fi
}

main
