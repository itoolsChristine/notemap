# uninstall.ps1 -- Notemap uninstaller for Windows PowerShell
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

$HomeDir    = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
$ClaudeDir  = Join-Path $HomeDir ".claude"
$McpDir     = Join-Path $ClaudeDir "notemap-mcp"
$DocsDir    = Join-Path $ClaudeDir "docs"
$SkillsDir  = Join-Path $ClaudeDir "skills"
$CommandsDir = Join-Path $ClaudeDir "commands"
$NoteDataDir = Join-Path $ClaudeDir "notemap"
$ClaudeMd    = Join-Path $ClaudeDir "CLAUDE.md"
$McpJson     = Join-Path $HomeDir ".claude.json"
$SettingsJson = Join-Path $ClaudeDir "settings.json"
$ScriptsDir  = Join-Path $ClaudeDir "scripts\notemap"

$DocsFile    = Join-Path $DocsDir "notemap.md"
$SkillFile   = Join-Path $SkillsDir "notemap-review.md"
$CommandFile = Join-Path $CommandsDir "notemap.md"

# ============================================================================
#  Banner
# ============================================================================

Write-Host ""
Write-Host "  ============================================================"
Write-Host "    NOTEMAP UNINSTALLER"
Write-Host "  ============================================================"
Write-Host ""

function Write-Info { param([string]$Msg) Write-Host "  [INFO]  $Msg" }
function Write-Ok   { param([string]$Msg) Write-Host "  [OK]    $Msg" }
function Write-Warn { param([string]$Msg) Write-Host "  [WARN]  $Msg" -ForegroundColor Yellow }

# ============================================================================
#  Detect existing installation
# ============================================================================

$hasMcp      = Test-Path $McpDir
$hasDocs     = Test-Path $DocsFile
$hasSkill    = Test-Path $SkillFile
$hasCommand  = Test-Path $CommandFile
$hasHooks    = Test-Path $ScriptsDir
$hasClaudeMd = Test-Path $ClaudeMd
$hasMcpJson  = Test-Path $McpJson
$hasSettingsJson = (Test-Path $SettingsJson) -and ((Get-Content $SettingsJson -Raw -ErrorAction SilentlyContinue) -match "scripts/notemap/")
$hasNoteData = Test-Path $NoteDataDir

if (-not $hasMcp -and -not $hasDocs -and -not $hasSkill -and -not $hasCommand -and -not $hasHooks) {
    Write-Info "Notemap does not appear to be installed. Nothing to uninstall."
    exit 0
}

# ============================================================================
#  Confirm before proceeding
# ============================================================================

Write-Host "  This will uninstall notemap."
Write-Host ""
Write-Host "  The following will be backed up before removal:"
if ($hasMcp)      { Write-Host "    - MCP server ($McpDir)" }
if ($hasDocs)     { Write-Host "    - Documentation ($DocsFile)" }
if ($hasSkill)    { Write-Host "    - Skill file ($SkillFile)" }
if ($hasCommand)  { Write-Host "    - Command file ($CommandFile)" }
if ($hasHooks)    { Write-Host "    - Hook scripts ($ScriptsDir)" }
if ($hasClaudeMd) { Write-Host "    - CLAUDE.md (notemap sentinel blocks will be removed)" }
if ($hasMcpJson)  { Write-Host "    - .claude.json (notemap MCP entry will be removed, other settings preserved)" }
if ($hasSettingsJson) { Write-Host "    - settings.json (notemap hooks will be removed, other hooks preserved)" }
Write-Host ""
if ($hasNoteData) {
    Write-Host "  Your note data ($NoteDataDir) will NOT be deleted unless you choose to."
    Write-Host ""
}

try {
    $answer = Read-Host "  Continue? [y/N]"
} catch {
    $answer = "y"
    Write-Info "Non-interactive mode: proceeding automatically"
}

if ($answer -notmatch "^[yY]") {
    Write-Host ""
    Write-Info "Uninstall cancelled."
    exit 0
}

# ============================================================================
#  Pre-uninstall backup (snapshot everything before deletion)
# ============================================================================

$BackupDir = ""
$hasExisting = $hasMcp -or $hasDocs -or $hasSkill -or $hasCommand -or $hasHooks

if ($hasExisting) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $BackupDir = Join-Path $ClaudeDir ".notemap-backup-$timestamp"
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null

    if ($hasMcp) {
        Copy-Item $McpDir "$BackupDir\notemap-mcp" -Recurse -Force
        Write-Ok "MCP server backed up"
    }
    if ($hasDocs) {
        New-Item -ItemType Directory -Path "$BackupDir\docs" -Force | Out-Null
        Copy-Item $DocsFile "$BackupDir\docs\notemap.md" -Force
        Write-Ok "Documentation backed up"
    }
    if ($hasSkill) {
        New-Item -ItemType Directory -Path "$BackupDir\skills" -Force | Out-Null
        Copy-Item $SkillFile "$BackupDir\skills\notemap-review.md" -Force
        Write-Ok "Skill file backed up"
    }
    if ($hasCommand) {
        New-Item -ItemType Directory -Path "$BackupDir\commands" -Force | Out-Null
        Copy-Item $CommandFile "$BackupDir\commands\notemap.md" -Force
        Write-Ok "Command file backed up"
    }
    if ($hasHooks) {
        Copy-Item $ScriptsDir "$BackupDir\scripts-notemap" -Recurse -Force
        Write-Ok "Hook scripts backed up"
    }
    if ($hasSettingsJson) {
        Copy-Item $SettingsJson "$BackupDir\settings.json" -Force
        Write-Ok "settings.json backed up"
    }
    if ($hasClaudeMd) {
        Copy-Item $ClaudeMd "$BackupDir\CLAUDE.md" -Force
        Write-Ok "CLAUDE.md backed up"
    }
    if ($hasMcpJson) {
        Copy-Item $McpJson "$BackupDir\.claude.json" -Force
        Write-Ok ".claude.json backed up"
    }

    Write-Ok "Pre-uninstall backup created: $BackupDir"
} else {
    Write-Info "No existing files found to back up"
}

# ============================================================================
#  Remove installed files
# ============================================================================

# MCP server directory (entire folder)
if ($hasMcp) {
    Remove-Item $McpDir -Recurse -Force
    Write-Ok "Removed $McpDir"
} else {
    Write-Info "MCP server directory not found (already removed?)"
}

# Documentation
if ($hasDocs) {
    Remove-Item $DocsFile -Force
    Write-Ok "Removed $DocsFile"
}

# Skill file
if ($hasSkill) {
    Remove-Item $SkillFile -Force
    Write-Ok "Removed $SkillFile"
}

# Command file
if ($hasCommand) {
    Remove-Item $CommandFile -Force
    Write-Ok "Removed $CommandFile"
}

# Hook scripts
if ($hasHooks) {
    Remove-Item $ScriptsDir -Recurse -Force
    Write-Ok "Removed $ScriptsDir"
}

# ============================================================================
#  Remove notemap hooks from settings.json
# ============================================================================

if ($hasSettingsJson) {
    Copy-Item $SettingsJson "$SettingsJson.bak" -Force
    Write-Info "Backup created: settings.json.bak"

    try {
        $settingsContent = [System.IO.File]::ReadAllText($SettingsJson)
        $settingsData = $null
        try {
            $settingsData = $settingsContent | ConvertFrom-Json -AsHashtable -ErrorAction Stop
        } catch {
            $settingsObj = $settingsContent | ConvertFrom-Json -ErrorAction Stop
            $settingsData = @{}
            foreach ($prop in $settingsObj.PSObject.Properties) {
                $settingsData[$prop.Name] = $prop.Value
            }
        }

        if ($null -ne $settingsData -and $settingsData.ContainsKey("hooks")) {
            $hooks = $settingsData["hooks"]
            if ($hooks -is [PSCustomObject]) {
                $hooksHash = @{}
                foreach ($prop in $hooks.PSObject.Properties) {
                    $hooksHash[$prop.Name] = $prop.Value
                }
                $hooks = $hooksHash
                $settingsData["hooks"] = $hooks
            }

            foreach ($eventName in @($hooks.Keys)) {
                $eventArray = @($hooks[$eventName])
                $filtered = @()
                foreach ($group in $eventArray) {
                    $isNotemap = $false
                    $groupHooks = if ($group -is [PSCustomObject]) { $group.hooks } else { $group["hooks"] }
                    if ($null -ne $groupHooks) {
                        foreach ($h in @($groupHooks)) {
                            $cmd = if ($h -is [PSCustomObject]) { $h.command } else { $h["command"] }
                            if ($cmd -and $cmd -match "scripts/notemap/") {
                                $isNotemap = $true
                                break
                            }
                        }
                    }
                    if (-not $isNotemap) {
                        $filtered += $group
                    }
                }
                if ($filtered.Count -gt 0) {
                    $hooks[$eventName] = $filtered
                } else {
                    $hooks.Remove($eventName)
                }
            }

            if ($hooks.Count -eq 0) {
                $settingsData.Remove("hooks")
            }

            $newJson = $settingsData | ConvertTo-Json -Depth 10
            [System.IO.File]::WriteAllText($SettingsJson, $newJson)
            Write-Ok "Removed notemap hooks from settings.json (other hooks preserved)"
        }
    } catch {
        Write-Warn "Failed to update settings.json: $_"
    }
}

# ============================================================================
#  Remove sentinel blocks from CLAUDE.md
# ============================================================================

if (Test-Path $ClaudeMd) {
    $content = [System.IO.File]::ReadAllText($ClaudeMd)
    $modified = $false

    # Remove INSTRUCTIONS block (inclusive of sentinels + surrounding blank lines)
    $instrPattern = "(?s)\r?\n?<!-- NOTEMAP:INSTRUCTIONS:BEGIN -->.*?<!-- NOTEMAP:INSTRUCTIONS:END -->\r?\n?"
    if ($content -match "NOTEMAP:INSTRUCTIONS:BEGIN") {
        $content = [regex]::Replace($content, $instrPattern, "`n")
        $modified = $true
        Write-Ok "Removed notemap instructions block from CLAUDE.md"
    }

    # Clean trailing whitespace
    if ($modified) {
        $content = $content.TrimEnd() + "`n"
        [System.IO.File]::WriteAllText($ClaudeMd, $content)
    }
} else {
    Write-Info "No CLAUDE.md found (nothing to clean)"
}

# ============================================================================
#  Remove notemap entry from .claude.json
# ============================================================================

if ((Test-Path $McpJson)) {
    $jsonContent = [System.IO.File]::ReadAllText($McpJson)

    # Parse with -AsHashtable to preserve all keys
    $config = $null
    try {
        $config = $jsonContent | ConvertFrom-Json -AsHashtable -ErrorAction Stop
    } catch {
        try {
            $configObj = $jsonContent | ConvertFrom-Json -ErrorAction Stop
            $config = @{}
            foreach ($prop in $configObj.PSObject.Properties) {
                $config[$prop.Name] = $prop.Value
            }
        } catch {
            Write-Warn "Could not parse .claude.json"
            $config = $null
        }
    }

    if ($null -ne $config) {
        # Get mcpServers as a hashtable
        $servers = $null
        if ($config.ContainsKey("mcpServers")) {
            if ($config["mcpServers"] -is [PSCustomObject]) {
                $servers = @{}
                foreach ($prop in $config["mcpServers"].PSObject.Properties) {
                    $servers[$prop.Name] = $prop.Value
                }
                $config["mcpServers"] = $servers
            } else {
                $servers = $config["mcpServers"]
            }
        }

        if ($null -ne $servers -and $servers.ContainsKey("notemap")) {
            $servers.Remove("notemap")

            # If no servers remain, remove the mcpServers key itself
            if ($servers.Count -eq 0) {
                $config.Remove("mcpServers")
            }

            # Write back the FULL config -- never delete this file
            $newJson = $config | ConvertTo-Json -Depth 10
            [System.IO.File]::WriteAllText($McpJson, $newJson)

            $remainingServers = $servers.Count
            if ($remainingServers -gt 0) {
                Write-Ok "Removed notemap entry from .claude.json ($remainingServers server(s) preserved)"
            } else {
                Write-Ok "Removed notemap entry from .claude.json"
            }
        } else {
            Write-Info "No notemap entry found in .claude.json"
        }
    }
} else {
    Write-Info "No .claude.json found (nothing to clean)"
}

# ============================================================================
#  Prompt for note data removal
# ============================================================================

if ($hasNoteData) {
    Write-Host ""
    Write-Warn "Your note data contains your accumulated knowledge notes."
    try {
        $answer = Read-Host "  Remove note data ($NoteDataDir)? [y/N]"
    } catch {
        # Non-interactive -- default to No
        $answer = "n"
        Write-Info "Non-interactive mode: keeping note data"
    }

    if ($answer -match "^[yY]") {
        Remove-Item $NoteDataDir -Recurse -Force
        Write-Ok "Removed $NoteDataDir"
    } else {
        Write-Info "Kept $NoteDataDir (your notes are preserved)"
    }
}

# ============================================================================
#  Done
# ============================================================================

Write-Host ""
Write-Host "  ============================================================"
Write-Host "    NOTEMAP UNINSTALLED"
Write-Host "  ============================================================"
Write-Host ""
Write-Host "    Restart Claude Code to complete the removal."
if ($BackupDir) {
    Write-Host ""
    Write-Host "    Backup of removed files: $BackupDir"
    Write-Host "    (Safe to delete once you've confirmed the uninstall is correct)"
}
Write-Host ""
