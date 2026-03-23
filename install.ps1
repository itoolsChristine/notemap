# install.ps1 -- Notemap installer for Windows PowerShell
# Usage: irm https://raw.githubusercontent.com/itoolsChristine/notemap/main/install.ps1 | iex
#Requires -Version 5.1
$ErrorActionPreference = "Stop"

# ============================================================================
#  Constants
# ============================================================================

$RepoUrl    = "https://raw.githubusercontent.com/itoolsChristine/notemap/main"
$HomeDir    = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
$ClaudeDir  = Join-Path $HomeDir ".claude"
$McpDir     = Join-Path $ClaudeDir "notemap-mcp"
$StorageDir = Join-Path $ClaudeDir "notemap"
$DocsDir    = Join-Path $ClaudeDir "docs"
$SkillsDir  = Join-Path $ClaudeDir "skills"
$CommandsDir = Join-Path $ClaudeDir "commands"
$ClaudeMd   = Join-Path $ClaudeDir "CLAUDE.md"
$McpJson    = Join-Path $HomeDir ".claude.json"
$SettingsJson = Join-Path $ClaudeDir "settings.json"
$ScriptsDir = Join-Path $ClaudeDir "scripts\notemap"

$McpFiles = @("server.py", "models.py", "notes.py", "search.py", "index.py", "audit.py", "lint.py", "preflight.py", "check.py", "utils.py")
$DocFiles = @("notemap.md")
$SkillFiles = @("notemap-review.md")
$CommandFiles = @("notemap.md")
$HookFiles = @("session-start.sh", "pre-edit.sh", "post-edit.sh")

# ============================================================================
#  Banner
# ============================================================================

function Show-Banner {
    Write-Host ""
    Write-Host "  ============================================================"
    Write-Host "    NOTEMAP INSTALLER"
    Write-Host "    Cornell note-taking for Claude Code -- remember what you learn."
    Write-Host "  ============================================================"
    Write-Host ""
}

# ============================================================================
#  Helpers
# ============================================================================

function Write-Info { param([string]$Msg) Write-Host "  [INFO]  $Msg" }
function Write-Ok   { param([string]$Msg) Write-Host "  [OK]    $Msg" }
function Write-Warn { param([string]$Msg) Write-Host "  [WARN]  $Msg" -ForegroundColor Yellow }
function Stop-Install { param([string]$Msg) Write-Host "  [ERROR] $Msg" -ForegroundColor Red; throw $Msg }

# ============================================================================
#  Pre-flight checks
# ============================================================================

function Test-Preflight {
    # Find Python
    $script:Python = $null
    $script:PythonPath = $null
    $candidates = @("python3", "python")
    foreach ($cmd in $candidates) {
        try {
            $null = & $cmd --version 2>&1
            $script:Python = $cmd
            break
        } catch {
            continue
        }
    }

    if (-not $script:Python) {
        Stop-Install "Python not found. Install Python 3.10+ and ensure it is in your PATH."
    }

    # Verify version >= 3.10
    $pyVersion = & $script:Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
    $parts = $pyVersion.Split(".")
    $major = [int]$parts[0]
    $minor = [int]$parts[1]

    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
        Stop-Install "Python 3.10+ required (found $pyVersion). Please upgrade Python."
    }

    # Resolve full path to Python executable for verification
    $script:PythonPath = (& $script:Python -c "import sys; print(sys.executable)" 2>&1).Trim()
    if (-not $script:PythonPath -or -not (Test-Path $script:PythonPath)) {
        Stop-Install "Could not resolve full Python path from '$script:Python'."
    }
    Write-Ok "Python $pyVersion ($script:PythonPath)"

    # Check Claude Code directory
    if (-not (Test-Path $ClaudeDir)) {
        Stop-Install "$ClaudeDir does not exist. Install and run Claude Code at least once first."
    }
    Write-Ok "Claude Code directory exists"

    # Check write permissions
    try {
        $testFile = Join-Path $ClaudeDir ".install-test-$$"
        [System.IO.File]::WriteAllText($testFile, "test")
        Remove-Item $testFile -Force
    } catch {
        Stop-Install "No write permission to $ClaudeDir"
    }
    Write-Ok "Write permissions verified"
}

# ============================================================================
#  Determine source mode
# ============================================================================

function Get-SourceMode {
    $script:SourceMode = "remote"
    $script:ScriptRoot = ""

    # Detect if running from a cloned repo
    $invocation = $MyInvocation.PSCommandPath
    if (-not $invocation) {
        # Piped from irm | iex -- no PSCommandPath
        $invocation = ""
    }

    if ($invocation -and (Test-Path $invocation)) {
        $script:ScriptRoot = Split-Path $invocation -Parent
        $srcMcp  = Join-Path $script:ScriptRoot "src\notemap-mcp"
        $srcDocs = Join-Path $script:ScriptRoot "src\docs"
        $srcCmds = Join-Path $script:ScriptRoot "src\commands"
        if ((Test-Path $srcMcp) -and (Test-Path $srcDocs) -and (Test-Path $srcCmds)) {
            $script:SourceMode = "local"
        }
    }

    if ($script:SourceMode -eq "local") {
        Write-Info "Installing from local clone: $script:ScriptRoot"
    } else {
        Write-Info "Installing from GitHub: $RepoUrl"
    }
}

# ============================================================================
#  File retrieval
# ============================================================================

function Get-InstallFile {
    param(
        [string]$SrcRel,    # e.g. src/notemap-mcp/server.py
        [string]$Dest       # e.g. ~/.claude/notemap-mcp/server.py
    )

    if ($script:SourceMode -eq "local") {
        $localPath = Join-Path $script:ScriptRoot $SrcRel.Replace("/", "\")
        if (-not (Test-Path $localPath)) {
            Stop-Install "Local file not found: $localPath"
        }
        Copy-Item $localPath $Dest -Force
    } else {
        $url = "$RepoUrl/$SrcRel"
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -ErrorAction Stop
            [System.IO.File]::WriteAllBytes($Dest, $response.Content)
        } catch {
            Stop-Install "Failed to download: $url"
        }
    }
}

# ============================================================================
#  Confirm install
# ============================================================================

function Confirm-Install {
    $existingMcp     = $false
    $existingDocs    = $false
    $existingSkills  = $false
    $existingCommands = $false
    $existingStorage = $false
    $existingClaudeMd = $false
    $existingMcpJson = $false
    $script:IsUpgrade = $false

    foreach ($f in $McpFiles) { if (Test-Path (Join-Path $McpDir $f)) { $existingMcp = $true; break } }
    foreach ($f in $DocFiles) { if (Test-Path (Join-Path $DocsDir $f)) { $existingDocs = $true; break } }
    foreach ($f in $SkillFiles) { if (Test-Path (Join-Path $SkillsDir $f)) { $existingSkills = $true; break } }
    foreach ($f in $CommandFiles) { if (Test-Path (Join-Path $CommandsDir $f)) { $existingCommands = $true; break } }
    if ((Test-Path $StorageDir) -and (Get-ChildItem $StorageDir -ErrorAction SilentlyContinue | Select-Object -First 1)) { $existingStorage = $true }
    if (Test-Path $ClaudeMd) { $existingClaudeMd = $true }
    if (Test-Path $McpJson) { $existingMcpJson = $true }

    if ($existingMcp -or $existingDocs -or $existingSkills -or $existingCommands) {
        $script:IsUpgrade = $true
    }

    Write-Host ""
    if ($script:IsUpgrade) {
        Write-Host "  Existing notemap installation detected."
        Write-Host "  This will UPGRADE your installation."
    } else {
        Write-Host "  This will install notemap."
    }

    Write-Host ""
    Write-Host "  The following will be backed up before any changes:"
    if ($existingMcp)      { Write-Host "    - MCP server files ($McpDir)" }
    if ($existingDocs)     { Write-Host "    - Documentation (notemap.md)" }
    if ($existingSkills)   { Write-Host "    - Skill files (notemap-review.md)" }
    if ($existingCommands) { Write-Host "    - Command files (notemap.md)" }
    if ($existingClaudeMd) { Write-Host "    - CLAUDE.md (sentinel blocks will be updated, not replaced)" }
    if ($existingMcpJson)  { Write-Host "    - .claude.json (notemap MCP entry will be merged, other settings preserved)" }
    if ($existingStorage)  { Write-Host "    - Note storage ($StorageDir)" }
    if (-not $existingMcp -and -not $existingDocs -and -not $existingSkills -and -not $existingCommands -and -not $existingClaudeMd -and -not $existingMcpJson -and -not $existingStorage) {
        Write-Host "    (nothing to back up -- fresh install)"
    }

    Write-Host ""
    if ($script:IsUpgrade) {
        Write-Host "  Your existing notes will NOT be erased."
    }

    Write-Host ""
    try {
        $answer = Read-Host "  Continue? [y/N]"
    } catch {
        # Non-interactive: proceed automatically
        $answer = "y"
        Write-Info "Non-interactive mode: proceeding automatically"
    }

    if ($answer -notmatch "^[yY]") {
        Write-Host ""
        Write-Info "Installation cancelled."
        exit 0
    }
}

# ============================================================================
#  Backup existing
# ============================================================================

function Backup-Existing {
    $script:BackupDir = ""
    $hasExisting = $false

    foreach ($f in $McpFiles) { if (Test-Path (Join-Path $McpDir $f)) { $hasExisting = $true; break } }
    if (Test-Path (Join-Path $McpDir "requirements.txt")) { $hasExisting = $true }
    foreach ($f in $DocFiles) { if (Test-Path (Join-Path $DocsDir $f)) { $hasExisting = $true; break } }
    foreach ($f in $SkillFiles) { if (Test-Path (Join-Path $SkillsDir $f)) { $hasExisting = $true; break } }
    foreach ($f in $CommandFiles) { if (Test-Path (Join-Path $CommandsDir $f)) { $hasExisting = $true; break } }
    if (Test-Path $ClaudeMd) { $hasExisting = $true }
    if (Test-Path $McpJson) { $hasExisting = $true }

    if (-not $hasExisting) {
        Write-Info "Fresh install (no existing files to back up)"
        return
    }

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $script:BackupDir = Join-Path $ClaudeDir ".notemap-backup-$timestamp"
    New-Item -ItemType Directory -Path "$script:BackupDir\notemap-mcp" -Force | Out-Null
    New-Item -ItemType Directory -Path "$script:BackupDir\docs" -Force | Out-Null
    New-Item -ItemType Directory -Path "$script:BackupDir\skills" -Force | Out-Null
    New-Item -ItemType Directory -Path "$script:BackupDir\commands" -Force | Out-Null

    foreach ($f in $McpFiles) {
        $src = Join-Path $McpDir $f
        if (Test-Path $src) { Copy-Item $src "$script:BackupDir\notemap-mcp\$f" -Force }
    }
    $reqFile = Join-Path $McpDir "requirements.txt"
    if (Test-Path $reqFile) { Copy-Item $reqFile "$script:BackupDir\notemap-mcp\requirements.txt" -Force }

    foreach ($f in $DocFiles) {
        $src = Join-Path $DocsDir $f
        if (Test-Path $src) { Copy-Item $src "$script:BackupDir\docs\$f" -Force }
    }

    foreach ($f in $SkillFiles) {
        $src = Join-Path $SkillsDir $f
        if (Test-Path $src) { Copy-Item $src "$script:BackupDir\skills\$f" -Force }
    }

    foreach ($f in $CommandFiles) {
        $src = Join-Path $CommandsDir $f
        if (Test-Path $src) { Copy-Item $src "$script:BackupDir\commands\$f" -Force }
    }

    if (Test-Path $ClaudeMd) { Copy-Item $ClaudeMd "$script:BackupDir\CLAUDE.md" -Force }
    if (Test-Path $McpJson) { Copy-Item $McpJson "$script:BackupDir\.claude.json" -Force }

    # Back up note storage (index only, not all notes -- those can be large)
    $indexFile = Join-Path $StorageDir "_index.json"
    if (Test-Path $indexFile) {
        New-Item -ItemType Directory -Path "$script:BackupDir\notemap" -Force | Out-Null
        Copy-Item $indexFile "$script:BackupDir\notemap\_index.json" -Force
        Write-Ok "Note index backed up"
    }

    Write-Ok "Pre-install backup created: $script:BackupDir"
}

# ============================================================================
#  Create directories
# ============================================================================

function New-Directories {
    @($McpDir, $StorageDir, $DocsDir, $SkillsDir, $CommandsDir, $ScriptsDir) | ForEach-Object {
        if (-not (Test-Path $_)) {
            New-Item -ItemType Directory -Path $_ -Force | Out-Null
        }
    }
    Write-Ok "Directories created"
}

# ============================================================================
#  Install files
# ============================================================================

function Install-Files {
    # MCP server files
    foreach ($f in $McpFiles) {
        Get-InstallFile "src/notemap-mcp/$f" (Join-Path $McpDir $f)
    }
    Get-InstallFile "src/notemap-mcp/requirements.txt" (Join-Path $McpDir "requirements.txt")
    Write-Ok "MCP server installed (10 Python files + requirements.txt)"

    # Documentation
    foreach ($f in $DocFiles) {
        Get-InstallFile "src/docs/$f" (Join-Path $DocsDir $f)
    }
    Write-Ok "Documentation installed (1 file)"

    # Skills
    foreach ($f in $SkillFiles) {
        Get-InstallFile "src/skills/$f" (Join-Path $SkillsDir $f)
    }
    Write-Ok "Skill files installed (1 file)"

    # Commands
    foreach ($f in $CommandFiles) {
        Get-InstallFile "src/commands/$f" (Join-Path $CommandsDir $f)
    }
    Write-Ok "Command files installed (1 file)"

    # Hook scripts
    foreach ($f in $HookFiles) {
        Get-InstallFile "src/hooks/$f" (Join-Path $ScriptsDir $f)
    }
    Write-Ok "Hook scripts installed (3 files)"

    # Clean up legacy flat hook scripts (pre-1.1.0 manual installs)
    foreach ($f in @("notemap-session-start.sh", "notemap-pre-edit.sh", "notemap-post-edit.sh")) {
        $legacy = Join-Path $ClaudeDir "scripts\$f"
        if (Test-Path $legacy) {
            Remove-Item $legacy -Force
            Write-Info "Removed legacy hook script: $f"
        }
    }
}

# ============================================================================
#  Install pip dependencies
# ============================================================================

function Install-PipDeps {
    $reqFile = Join-Path $McpDir "requirements.txt"
    if (-not (Test-Path $reqFile)) {
        Write-Warn "requirements.txt not found, skipping pip install"
        return
    }

    Write-Info "Installing Python dependencies..."
    try {
        $output = & $script:PythonPath -m pip install -r $reqFile --quiet 2>&1
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            Write-Warn "pip install returned exit code $exitCode"
            Write-Warn "Output: $output"
            Write-Warn "You may need to install dependencies manually:"
            Write-Warn "  $script:PythonPath -m pip install -r `"$reqFile`""
            return
        }
        Write-Ok "Python dependencies installed"
    } catch {
        Write-Warn "pip not available or install failed: $_"
        Write-Warn "You may need to install dependencies manually:"
        Write-Warn "  $script:PythonPath -m pip install -r `"$reqFile`""
    }
}

# ============================================================================
#  CLAUDE.md injection
# ============================================================================

function Update-ClaudeMd {
    # Load instruction content
    if ($script:SourceMode -eq "local") {
        $instrFile = Join-Path $script:ScriptRoot "src\claude-md\notemap-instructions.md"
        if (-not (Test-Path $instrFile)) {
            Stop-Install "CLAUDE.md source file not found: src\claude-md\notemap-instructions.md"
        }
        $instrContent = [System.IO.File]::ReadAllText($instrFile)
    } else {
        try {
            $instrContent = (Invoke-WebRequest -Uri "$RepoUrl/src/claude-md/notemap-instructions.md" -UseBasicParsing).Content
        } catch {
            Stop-Install "Failed to download CLAUDE.md integration file"
        }
        # Ensure string type (Invoke-WebRequest may return bytes)
        if ($instrContent -is [byte[]]) {
            $instrContent = [System.Text.Encoding]::UTF8.GetString($instrContent)
        }
    }

    $InstrBegin = "<!-- NOTEMAP:INSTRUCTIONS:BEGIN -->"
    $InstrEnd   = "<!-- NOTEMAP:INSTRUCTIONS:END -->"

    # Case 1: No CLAUDE.md -- create it
    if (-not (Test-Path $ClaudeMd)) {
        $newContent = "# CLAUDE.md`n`n$instrContent"
        [System.IO.File]::WriteAllText($ClaudeMd, $newContent)
        Write-Ok "Created $ClaudeMd with notemap instructions"
        return
    }

    # Create backup
    Copy-Item $ClaudeMd "$ClaudeMd.bak" -Force
    Write-Info "Backup created: CLAUDE.md.bak"

    $content = [System.IO.File]::ReadAllText($ClaudeMd)

    # Warn about potential duplication
    if ($content -match "Notemap -- API KNOWLEDGE CAPTURE" -and $content -notmatch [regex]::Escape($InstrBegin)) {
        Write-Warn 'Found existing "Notemap" section in CLAUDE.md without sentinel markers.'
        Write-Warn "The installer will append sentinel-wrapped blocks at the end of the file."
        Write-Warn "You may want to manually remove the old section to avoid duplication."
    }

    $hasInstrSentinels = $content.Contains($InstrBegin)

    # --- Instructions block ---
    if ($hasInstrSentinels) {
        # Extract existing instructions block for comparison
        $instrPattern = "(?s)" + [regex]::Escape($InstrBegin) + ".*?" + [regex]::Escape($InstrEnd)
        $existingInstr = [regex]::Match($content, $instrPattern).Value
        if ($existingInstr -eq $instrContent) {
            Write-Ok "Instructions block is up to date"
        } else {
            $content = [regex]::Replace($content, $instrPattern, $instrContent)
            Write-Ok "Updated instructions block in CLAUDE.md"
        }
    } else {
        $content = $content + "`n`n" + $instrContent
        Write-Ok "Appended instructions block to CLAUDE.md"
    }

    [System.IO.File]::WriteAllText($ClaudeMd, $content)
}

# ============================================================================
#  MCP config injection
# ============================================================================

function Update-McpConfig {
    $serverPyPath = Join-Path $McpDir "server.py"

    # Use forward-slash path for the server.py entry
    $serverForwardSlash = $serverPyPath.Replace("\", "/")

    # Use just "python" (not the full path) for the command
    $pythonCmd = "python"

    # Read the FULL .claude.json config file -- it contains many Claude Code
    # settings beyond mcpServers. We must preserve ALL other keys.
    $mcpConfig = @{}

    if (Test-Path $McpJson) {
        try {
            $existingContent = [System.IO.File]::ReadAllText($McpJson)
            $mcpConfig = $existingContent | ConvertFrom-Json -AsHashtable -ErrorAction Stop
        } catch {
            # Try without -AsHashtable for older PowerShell
            try {
                $existingObj = $existingContent | ConvertFrom-Json -ErrorAction Stop
                $mcpConfig = @{}
                foreach ($prop in $existingObj.PSObject.Properties) {
                    $mcpConfig[$prop.Name] = $prop.Value
                }
            } catch {
                Write-Warn "Could not parse existing .claude.json, will create fresh"
                $mcpConfig = @{}
            }
        }
    }

    # Ensure mcpServers key exists
    if (-not $mcpConfig.ContainsKey("mcpServers")) {
        $mcpConfig["mcpServers"] = @{}
    }

    # Convert mcpServers to hashtable if it's a PSObject
    if ($mcpConfig["mcpServers"] -is [PSCustomObject]) {
        $servers = @{}
        foreach ($prop in $mcpConfig["mcpServers"].PSObject.Properties) {
            $servers[$prop.Name] = $prop.Value
        }
        $mcpConfig["mcpServers"] = $servers
    }

    # Add/update the notemap entry with type and env fields
    $mcpConfig["mcpServers"]["notemap"] = @{
        "type"    = "stdio"
        "command" = $pythonCmd
        "args"    = @($serverForwardSlash)
        "env"     = @{}
    }

    # Write back the COMPLETE config with proper formatting
    $jsonOutput = $mcpConfig | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($McpJson, $jsonOutput)

    $serverCount = $mcpConfig["mcpServers"].Count
    if ($serverCount -gt 1) {
        Write-Ok "MCP config updated (notemap + $($serverCount - 1) other server(s) preserved)"
    } else {
        Write-Ok "MCP config created with notemap server"
    }
}

# ============================================================================
#  Hook registration in settings.json
# ============================================================================

function Update-HooksConfig {
    Write-Info "Registering notemap hooks in settings.json..."

    # Use forward-slash path for bash commands in hook entries
    $scriptsFwd = $ScriptsDir.Replace("\", "/")

    # Read existing settings.json or start fresh
    $settings = @{}
    if (Test-Path $SettingsJson) {
        try {
            $existingContent = [System.IO.File]::ReadAllText($SettingsJson)
            $settings = $existingContent | ConvertFrom-Json -AsHashtable -ErrorAction Stop
        } catch {
            try {
                $existingObj = $existingContent | ConvertFrom-Json -ErrorAction Stop
                $settings = @{}
                foreach ($prop in $existingObj.PSObject.Properties) {
                    $settings[$prop.Name] = $prop.Value
                }
            } catch {
                Write-Warn "Could not parse existing settings.json, hooks will be added to fresh structure"
                $settings = @{}
            }
        }
    }

    # Ensure hooks key exists as a hashtable
    if (-not $settings.ContainsKey("hooks")) {
        $settings["hooks"] = @{}
    }
    if ($settings["hooks"] -is [PSCustomObject]) {
        $hooksHash = @{}
        foreach ($prop in $settings["hooks"].PSObject.Properties) {
            $hooksHash[$prop.Name] = $prop.Value
        }
        $settings["hooks"] = $hooksHash
    }

    # Define notemap hook groups
    $notemapHooks = @{
        "SessionStart" = @{
            "matcher" = "startup|resume"
            "hooks" = @(@{ "type" = "command"; "command" = "bash `"$scriptsFwd/session-start.sh`"" })
        }
        "PreToolUse" = @{
            "matcher" = "Edit|Write"
            "hooks" = @(@{ "type" = "command"; "command" = "bash `"$scriptsFwd/pre-edit.sh`"" })
        }
        "PostToolUse" = @{
            "matcher" = "Edit|Write"
            "hooks" = @(@{ "type" = "command"; "command" = "bash `"$scriptsFwd/post-edit.sh`"" })
        }
    }

    foreach ($eventName in $notemapHooks.Keys) {
        $hookGroup = $notemapHooks[$eventName]

        if (-not $settings["hooks"].ContainsKey($eventName)) {
            $settings["hooks"][$eventName] = @()
        }

        # Convert PSObject arrays to proper arrays if needed
        $eventArray = @($settings["hooks"][$eventName])

        # Find existing notemap entry
        $existingIdx = -1
        for ($i = 0; $i -lt $eventArray.Count; $i++) {
            $group = $eventArray[$i]
            $hooks = if ($group -is [PSCustomObject]) { $group.hooks } else { $group["hooks"] }
            if ($null -ne $hooks) {
                foreach ($h in @($hooks)) {
                    $cmd = if ($h -is [PSCustomObject]) { $h.command } else { $h["command"] }
                    if ($cmd -and $cmd -match "scripts/notemap/") {
                        $existingIdx = $i
                        break
                    }
                }
            }
            if ($existingIdx -ge 0) { break }
        }

        if ($existingIdx -ge 0) {
            $eventArray[$existingIdx] = $hookGroup
        } else {
            $eventArray += $hookGroup
        }

        $settings["hooks"][$eventName] = $eventArray
    }

    # Write back
    $jsonOutput = $settings | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($SettingsJson, $jsonOutput)
    Write-Ok "Notemap hooks registered in settings.json"
}

# ============================================================================
#  Post-install verification
# ============================================================================

function Test-Installation {
    $errors = 0

    # Check Python can import the server module
    try {
        $serverPy = Join-Path $McpDir "server.py"
        $null = & $script:PythonPath -c "import ast; ast.parse(open(r'$serverPy').read())" 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "server.py syntax check failed"
            $errors++
        }
    } catch {
        Write-Warn "Could not verify server.py syntax"
        $errors++
    }

    # Verify all expected files
    $expectedFiles = @()
    foreach ($f in $McpFiles) { $expectedFiles += (Join-Path $McpDir $f) }
    $expectedFiles += (Join-Path $McpDir "requirements.txt")
    foreach ($f in $DocFiles) { $expectedFiles += (Join-Path $DocsDir $f) }
    foreach ($f in $SkillFiles) { $expectedFiles += (Join-Path $SkillsDir $f) }
    foreach ($f in $CommandFiles) { $expectedFiles += (Join-Path $CommandsDir $f) }
    foreach ($f in $HookFiles) { $expectedFiles += (Join-Path $ScriptsDir $f) }

    $fileCount = 0
    foreach ($f in $expectedFiles) {
        if (-not (Test-Path $f)) {
            Write-Warn "Missing: $f"
            $errors++
        } else {
            $fileCount++
        }
    }

    # Verify CLAUDE.md sentinels
    if (Test-Path $ClaudeMd) {
        $mdContent = [System.IO.File]::ReadAllText($ClaudeMd)
        if ($mdContent -notmatch "NOTEMAP:INSTRUCTIONS:BEGIN") {
            Write-Warn "CLAUDE.md missing notemap instructions sentinel"
            $errors++
        }
    } else {
        Write-Warn "CLAUDE.md not found after install"
        $errors++
    }

    # Verify .claude.json has notemap entry
    if (Test-Path $McpJson) {
        $mcpContent = [System.IO.File]::ReadAllText($McpJson)
        if ($mcpContent -notmatch '"notemap"') {
            Write-Warn ".claude.json missing notemap server entry"
            $errors++
        }
    } else {
        Write-Warn ".claude.json not found after install"
        $errors++
    }

    # Verify settings.json has notemap hook entries
    if (Test-Path $SettingsJson) {
        $settingsContent = [System.IO.File]::ReadAllText($SettingsJson)
        if ($settingsContent -notmatch "scripts/notemap/") {
            Write-Warn "settings.json missing notemap hook entries"
            $errors++
        }
    } else {
        Write-Warn "settings.json not found after install"
        $errors++
    }

    if ($errors -eq 0) {
        Write-Ok "All $fileCount files verified"
        Write-Ok "CLAUDE.md sentinel verified"
        Write-Ok "MCP config verified"
        Write-Ok "settings.json hooks verified"
    } else {
        Write-Warn "$errors verification issue(s) found"
    }

    return $errors
}

# ============================================================================
#  Success message
# ============================================================================

function Show-Success {
    Write-Host ""
    Write-Host "  ============================================================"
    Write-Host "    NOTEMAP INSTALLED SUCCESSFULLY"
    Write-Host "  ============================================================"
    Write-Host ""
    Write-Host "    What was installed:"
    Write-Host "      - MCP server:    $McpDir"
    Write-Host "      - Note storage:  $StorageDir"
    Write-Host "      - Documentation: $DocsDir\notemap.md"
    Write-Host "      - Skill:         $SkillsDir\notemap-review.md"
    Write-Host "      - Command:       $CommandsDir\notemap.md"
    Write-Host "      - Hooks:         $ScriptsDir (3 scripts)"
    Write-Host "      - MCP config:    $McpJson"
    Write-Host "      - Hook config:   $SettingsJson"
    Write-Host "      - CLAUDE.md:     Instructions injected"
    Write-Host ""
    Write-Host "    Usage (in Claude Code):"
    Write-Host "      Notes are created/searched automatically during coding."
    Write-Host "      /notemap review   Trigger a deliberate review session"
    Write-Host ""
    Write-Host "    To update:  Re-run this installer"
    Write-Host "    To remove:  Run uninstall.ps1 or uninstall.cmd"
    Write-Host ""
    Write-Host "  ============================================================"
    Write-Host ""
}

# ============================================================================
#  Main
# ============================================================================

Show-Banner
Test-Preflight
Get-SourceMode
Confirm-Install
Backup-Existing

try {
    New-Directories
    Install-Files
    Install-PipDeps
    Update-ClaudeMd
    Update-McpConfig
    Update-HooksConfig
    $null = Test-Installation
    Show-Success
    if ($script:BackupDir) {
        Write-Info "Pre-install backup: $script:BackupDir"
    }
} catch {
    Write-Host ""
    Write-Host "  [ERROR] Installation failed: $_" -ForegroundColor Red
    if ($script:BackupDir -and (Test-Path $script:BackupDir)) {
        Write-Host ""
        Write-Host "  Your original files were backed up before any changes."
        Write-Host "  To restore, run:"
        Write-Host ""
        Write-Host "    Copy-Item '$script:BackupDir\notemap-mcp\*' '$McpDir\' -Force"
        Write-Host "    Copy-Item '$script:BackupDir\docs\*' '$DocsDir\' -Force"
        Write-Host "    Copy-Item '$script:BackupDir\skills\*' '$SkillsDir\' -Force"
        Write-Host "    Copy-Item '$script:BackupDir\commands\*' '$CommandsDir\' -Force"
        Write-Host "    Copy-Item '$script:BackupDir\CLAUDE.md' '$ClaudeMd' -Force"
        Write-Host "    Copy-Item '$script:BackupDir\.claude.json' '$McpJson' -Force"
        Write-Host ""
        Write-Host "  Backup location: $script:BackupDir"
    }
    throw
}
