"""
sync.py -- Sync notemap files from ~/.claude/ into the repo's src/ directory.

Copies Python MCP server files verbatim and applies transforms to .md files:
- Path normalization (Windows-specific paths -> $HOME/.claude/)
- CLAUDE.md section extraction (notemap instructions between sentinel tags)

Also handles version management:
- Reads VERSION file as single source of truth
- Auto-bumps patch (Z) when synced files have actual changes
- Propagates version to README badge and CHANGELOG header

Usage:
    python sync.py              # Full sync (auto-bumps patch if changes detected)
    python sync.py --dry-run    # Show what would change without writing
    python sync.py --minor      # Bump minor version (Y), reset patch
    python sync.py --major      # Bump major version (X), reset minor + patch
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLAUDE_HOME        = Path.home() / ".claude"
REPO_ROOT          = Path(__file__).resolve().parent
SRC_DIR            = REPO_ROOT / "src"
SUBSTITUTIONS_FILE = REPO_ROOT / "substitutions.local.json"
VERSION_FILE       = REPO_ROOT / "VERSION"

# Source -> destination mappings (relative to CLAUDE_HOME and SRC_DIR)
PYTHON_FILES = [
    ("notemap-mcp/server.py",       "notemap-mcp/server.py"),
    ("notemap-mcp/notes.py",        "notemap-mcp/notes.py"),
    ("notemap-mcp/search.py",       "notemap-mcp/search.py"),
    ("notemap-mcp/audit.py",        "notemap-mcp/audit.py"),
    ("notemap-mcp/lint.py",         "notemap-mcp/lint.py"),
    ("notemap-mcp/preflight.py",    "notemap-mcp/preflight.py"),
    ("notemap-mcp/check.py",        "notemap-mcp/check.py"),
    ("notemap-mcp/index.py",        "notemap-mcp/index.py"),
    ("notemap-mcp/models.py",       "notemap-mcp/models.py"),
    ("notemap-mcp/utils.py",        "notemap-mcp/utils.py"),
    ("notemap-mcp/requirements.txt", "notemap-mcp/requirements.txt"),
]

DOC_FILES = [
    ("docs/notemap.md", "docs/notemap.md"),
]

SKILL_FILES = [
    ("skills/notemap-review.md", "skills/notemap-review.md"),
]

COMMAND_FILES = [
    ("commands/notemap.md", "commands/notemap.md"),
]

HOOK_FILES = [
    ("scripts/notemap/session-start.sh", "hooks/session-start.sh"),
    ("scripts/notemap/pre-edit.sh",      "hooks/pre-edit.sh"),
    ("scripts/notemap/post-edit.sh",     "hooks/post-edit.sh"),
]

# Sentinel tags for the CLAUDE.md notemap section
CLAUDE_MD_SENTINELS = (
    "<!-- NOTEMAP:INSTRUCTIONS:BEGIN -->",
    "<!-- NOTEMAP:INSTRUCTIONS:END -->",
)

# Section markers in CLAUDE.md
NOTEMAP_SECTION_START = "## Notemap -- API KNOWLEDGE CAPTURE"
NOTEMAP_SECTION_END   = "## PHP LSP"
NOTEMAP_SECTION_TAIL  = "@docs/notemap.md"

# ANSI color codes
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ---------------------------------------------------------------------------
# Version management (VERSION file is the single source of truth)
# ---------------------------------------------------------------------------

def read_version() -> str:
    """Read the current version from the VERSION file."""
    if not VERSION_FILE.exists():
        return "0.0.0"
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def write_version(version: str) -> None:
    """Write a version string to the VERSION file."""
    VERSION_FILE.write_text(version + "\n", encoding="utf-8", newline="\n")


def bump_version(version: str, part: str) -> str:
    """Bump a semver version string by part ('major', 'minor', or 'patch').

        bump_version("1.2.3", "patch") -> "1.2.4"
        bump_version("1.2.3", "minor") -> "1.3.0"
        bump_version("1.2.3", "major") -> "2.0.0"
    """
    parts = version.split(".")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    if part == "major":
        major += 1
        minor = 0
        patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    else:
        patch += 1

    return f"{major}.{minor}.{patch}"


def patch_readme_badge(version: str, dry_run: bool = False) -> bool:
    """Update the version badge in README.md. Returns True if changed."""
    readme = REPO_ROOT / "README.md"
    if not readme.exists():
        return False
    content = readme.read_text(encoding="utf-8")
    new_content = re.sub(
        r'!\[Version\]\(https://img\.shields\.io/badge/version-[^)]*\)',
        f'![Version](https://img.shields.io/badge/version-{version}-blue)',
        content,
    )
    if new_content != content:
        if not dry_run:
            readme.write_text(new_content, encoding="utf-8")
        return True
    return False


def patch_py_version(file_path: Path, version: str, dry_run: bool = False) -> bool:
    """Replace __version__ = "..." in a Python file. Returns True if changed."""
    if not file_path.exists():
        return False
    raw = file_path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw[:2000] else "\n"
    content = file_path.read_text(encoding="utf-8")
    new_content, count = re.subn(
        r'(__version__\s*=\s*")[^"]*(")',
        rf'\g<1>{version}\2',
        content,
        count=1,
    )
    if count == 0 or new_content == content:
        return False
    if not dry_run:
        file_path.write_text(new_content, encoding="utf-8", newline=newline)
    return True


def patch_changelog_header(version: str, dry_run: bool = False) -> bool:
    """Update the first version header in CHANGELOG.md. Returns True if changed."""
    changelog = REPO_ROOT / "CHANGELOG.md"
    if not changelog.exists():
        return False
    content = changelog.read_text(encoding="utf-8")
    new_content = re.sub(
        r'(## \[)\d+\.\d+\.\d+(\])',
        rf'\g<1>{version}\2',
        content,
        count=1,
    )
    if new_content != content:
        if not dry_run:
            changelog.write_text(new_content, encoding="utf-8")
        return True
    return False


# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------

def normalize_paths(content: str) -> str:
    """Replace platform-specific path references with cross-platform $HOME equivalents.

    Auto-detects the current user's home directory and generates replacement
    patterns for both backslash and forward-slash variants. Also handles
    generic %USERPROFILE% and $USERPROFILE references.
    """
    result = content

    # Build home-directory patterns dynamically (no hardcoded usernames)
    home     = str(Path.home())
    home_fwd = home.replace("\\", "/")
    home_bk  = home.replace("/", "\\")

    literal_replacements = [
        (home_bk  + "\\.claude\\",  "$HOME/.claude/"),
        (home_fwd + "/.claude/",    "$HOME/.claude/"),
        (home_bk  + "\\.claude",    "$HOME/.claude"),
        (home_fwd + "/.claude",     "$HOME/.claude"),
        ("%USERPROFILE%\\.claude\\", "$HOME/.claude/"),
        ("%USERPROFILE%/.claude/",   "$HOME/.claude/"),
        ("$USERPROFILE/.claude/",    "$HOME/.claude/"),
    ]
    for old, new in literal_replacements:
        result = result.replace(old, new)

    # Normalize backslash paths in .claude/ contexts that remain after literal replacement.
    def _fix_claude_backslashes(m: re.Match) -> str:
        return m.group(0).replace("\\", "/")

    result = re.sub(r'\$HOME/\.claude[\\\/][^\s"\'`\n]*', _fix_claude_backslashes, result)

    return result


# ---------------------------------------------------------------------------
# Project-specific substitutions
# ---------------------------------------------------------------------------

def load_substitutions() -> dict[str, str]:
    """Load project-specific substitutions from substitutions.local.json.

    Returns empty dict if file doesn't exist.
    For path entries (containing / with a drive letter or absolute prefix),
    auto-generates single-backslash and double-backslash variants.
    """
    if not SUBSTITUTIONS_FILE.exists():
        return {}

    raw = json.loads(SUBSTITUTIONS_FILE.read_text(encoding="utf-8"))

    expanded: dict[str, str] = {}
    for key, value in raw.items():
        expanded[key] = value

        # Auto-generate backslash variants for path entries
        is_path = "/" in key and (len(key) > 2 and key[1] == ":" or key.startswith("/"))
        if is_path:
            # Single backslash: D:/_Source/ -> D:\_Source\
            single = key.replace("/", "\\")
            expanded[single] = value

            # Double backslash: D:/_Source/ -> D:\\_Source\\ (JSON-in-markdown contexts)
            double = key.replace("/", "\\\\")
            expanded[double] = value

    return expanded


def apply_substitutions(content: str, substitutions: dict[str, str]) -> str:
    """Apply substitutions to content, longest keys first to prevent partial matches."""
    if not substitutions:
        return content

    sorted_subs = sorted(substitutions.items(), key=lambda x: len(x[0]), reverse=True)

    for old, new in sorted_subs:
        content = content.replace(old, new)

    # Normalize remaining backslashes in ~/paths (substitution may leave mixed slashes)
    def _fix_backslashes(m: re.Match) -> str:
        return m.group(0).replace("\\", "/")

    content = re.sub(r'~/[^\s"\'`\n]*\\[^\s"\'`\n]*', _fix_backslashes, content)

    return content


# ---------------------------------------------------------------------------
# CLAUDE.md section extraction
# ---------------------------------------------------------------------------

def extract_notemap_section(claude_md_path: Path) -> tuple[str, list[str]]:
    """Extract the notemap instructions section from CLAUDE.md.

    Returns:
        (extracted_content_with_sentinels, list_of_warnings)

    If CLAUDE.md already has NOTEMAP:INSTRUCTIONS sentinel tags, extracts
    the content between them (inclusive). Otherwise falls back to heading-based
    extraction and wraps the result in sentinels.
    """
    warnings: list[str] = []

    if not claude_md_path.exists():
        warnings.append(f"CLAUDE.md not found: {claude_md_path}")
        return "", warnings

    content = claude_md_path.read_text(encoding="utf-8")

    # Prefer sentinel-based extraction if CLAUDE.md already has the tags
    begin_tag = CLAUDE_MD_SENTINELS[0]
    end_tag   = CLAUDE_MD_SENTINELS[1]

    begin_idx = content.find(begin_tag)
    end_idx   = content.find(end_tag, begin_idx + 1) if begin_idx != -1 else -1

    if begin_idx != -1 and end_idx != -1:
        # Extract from start of BEGIN tag through end of END tag
        result = content[begin_idx:end_idx + len(end_tag)].rstrip() + "\n"

        # Verify the @docs/notemap.md reference is present
        if NOTEMAP_SECTION_TAIL not in result:
            warnings.append(f"Expected tail marker not found in section: '{NOTEMAP_SECTION_TAIL}'")

        return result, warnings

    # Fallback: heading-based extraction (no sentinel tags in CLAUDE.md)
    start_idx = content.find(NOTEMAP_SECTION_START)
    if start_idx == -1:
        warnings.append(f"Section start marker not found: '{NOTEMAP_SECTION_START}'")
        return "", warnings

    heading_end_idx = content.find(NOTEMAP_SECTION_END, start_idx)
    if heading_end_idx == -1:
        warnings.append(f"Section end marker not found: '{NOTEMAP_SECTION_END}'")
        return "", warnings

    # Extract the section -- everything from start up to (but not including) the next heading
    section = content[start_idx:heading_end_idx].rstrip()

    # Verify the @docs/notemap.md reference is present
    if NOTEMAP_SECTION_TAIL not in section:
        warnings.append(f"Expected tail marker not found in section: '{NOTEMAP_SECTION_TAIL}'")

    # Wrap in sentinels
    result = f"{begin_tag}\n{section}\n{end_tag}\n"

    return result, warnings


# ---------------------------------------------------------------------------
# File sync
# ---------------------------------------------------------------------------

def sync_file(
    src: Path,
    dst: Path,
    transforms: list[str] | None = None,
    dry_run: bool = False,
    substitutions: dict[str, str] | None = None,
) -> dict:
    """Copy a file from src to dst, optionally applying transforms.

    Args:
        src: Source file path
        dst: Destination file path
        transforms: List of transform names to apply. Options:
            - "normalize_paths"
        dry_run: If True, do not write files
        substitutions: Project-specific string replacements

    Returns:
        dict with keys: src, dst, src_lines, dst_lines, warnings, skipped
    """
    transforms = transforms or []
    stats: dict = {
        "src":       src,
        "dst":       dst,
        "src_lines": 0,
        "dst_lines": 0,
        "warnings":  [],
        "skipped":   False,
        "changed":   False,
    }

    if not src.exists():
        stats["warnings"].append(f"Source not found: {src}")
        stats["skipped"] = True
        return stats

    content = src.read_text(encoding="utf-8")
    stats["src_lines"] = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

    if "normalize_paths" in transforms:
        content = normalize_paths(content)

    if substitutions:
        content = apply_substitutions(content, substitutions)

    stats["dst_lines"] = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

    # Detect whether content actually changed from what's on disk
    old_content = dst.read_text(encoding="utf-8") if dst.exists() else ""
    stats["changed"] = (content != old_content)

    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8", newline="\n")

    return stats


def sync_claude_md_section(
    dst: Path,
    dry_run: bool = False,
    substitutions: dict[str, str] | None = None,
) -> dict:
    """Extract the notemap section from CLAUDE.md and write to dst.

    Returns:
        dict with keys: src, dst, src_lines, dst_lines, warnings, skipped
    """
    claude_md_path = CLAUDE_HOME / "CLAUDE.md"
    stats: dict = {
        "src":       claude_md_path,
        "dst":       dst,
        "src_lines": 0,
        "dst_lines": 0,
        "warnings":  [],
        "skipped":   False,
        "changed":   False,
    }

    content, extract_warnings = extract_notemap_section(claude_md_path)
    stats["warnings"].extend(extract_warnings)

    if not content:
        stats["skipped"] = True
        return stats

    # Count lines before transforms for reporting
    stats["src_lines"] = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

    # Apply path normalization
    content = normalize_paths(content)

    if substitutions:
        content = apply_substitutions(content, substitutions)

    stats["dst_lines"] = content.count("\n") + (1 if content and not content.endswith("\n") else 0)

    # Detect changes
    old_content = dst.read_text(encoding="utf-8") if dst.exists() else ""
    stats["changed"] = (content != old_content)

    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8", newline="\n")

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    dry_run    = "--dry-run" in sys.argv
    bump_minor = "--minor" in sys.argv
    bump_major = "--major" in sys.argv

    print()
    print(f"  {BOLD}NOTEMAP SYNC{RESET}")
    if dry_run:
        print(f"  {YELLOW}(dry run -- no files will be written){RESET}")
    print()

    # -----------------------------------------------------------------------
    # Load substitutions
    # -----------------------------------------------------------------------
    substitutions = load_substitutions()
    if substitutions:
        # Count original entries (before backslash expansion)
        raw_count = 0
        if SUBSTITUTIONS_FILE.exists():
            raw_count = len(json.loads(SUBSTITUTIONS_FILE.read_text(encoding="utf-8")))
        print(f"  {GREEN}Substitutions loaded: {raw_count} entries ({len(substitutions)} with variants){RESET}")
    else:
        print(f"  {YELLOW}No substitutions.local.json found (personal paths will not be sanitized){RESET}")
    print()

    # -----------------------------------------------------------------------
    # Verify all source files exist
    # -----------------------------------------------------------------------
    all_sources = PYTHON_FILES + DOC_FILES + SKILL_FILES + COMMAND_FILES + HOOK_FILES
    missing = []
    for src_rel, _ in all_sources:
        src_path = CLAUDE_HOME / src_rel
        if not src_path.exists():
            missing.append(str(src_path))

    # Also check CLAUDE.md
    claude_md_path = CLAUDE_HOME / "CLAUDE.md"
    if not claude_md_path.exists():
        missing.append(str(claude_md_path))

    if missing:
        print(f"  {RED}ERROR: Source files not found:{RESET}")
        for m in missing:
            print(f"    - {m}")
        print()
        print(f"  Ensure the notemap MCP server is installed in {CLAUDE_HOME}")
        return 1

    # -----------------------------------------------------------------------
    # Sync Python/MCP files (verbatim copy)
    # -----------------------------------------------------------------------
    print(f"  {CYAN}MCP server files:{RESET}")
    python_stats = []
    for src_rel, dst_rel in PYTHON_FILES:
        src_path = CLAUDE_HOME / src_rel
        dst_path = SRC_DIR / dst_rel
        stats = sync_file(src_path, dst_path, dry_run=dry_run)
        python_stats.append((dst_rel, stats))
        status = "would copy" if dry_run else "copied"
        name = Path(dst_rel).name
        print(f"    {GREEN}{name:<22}{RESET} [{status} - {stats['src_lines']:,} lines]")

    # -----------------------------------------------------------------------
    # Sync doc files (with path normalization)
    # -----------------------------------------------------------------------
    print()
    print(f"  {CYAN}Documentation:{RESET}")
    doc_stats = []
    for src_rel, dst_rel in DOC_FILES:
        src_path = CLAUDE_HOME / src_rel
        dst_path = SRC_DIR / dst_rel
        stats = sync_file(
            src_path, dst_path,
            transforms=["normalize_paths"],
            dry_run=dry_run,
            substitutions=substitutions,
        )
        doc_stats.append((dst_rel, stats))
        name   = Path(dst_rel).name
        status = "would sync" if dry_run else "synced"
        print(f"    {GREEN}{name:<22}{RESET} [{status} - {stats['dst_lines']:,} lines]")

    # -----------------------------------------------------------------------
    # Sync skill files (with path normalization)
    # -----------------------------------------------------------------------
    print()
    print(f"  {CYAN}Skills:{RESET}")
    skill_stats = []
    for src_rel, dst_rel in SKILL_FILES:
        src_path = CLAUDE_HOME / src_rel
        dst_path = SRC_DIR / dst_rel
        stats = sync_file(
            src_path, dst_path,
            transforms=["normalize_paths"],
            dry_run=dry_run,
            substitutions=substitutions,
        )
        skill_stats.append((dst_rel, stats))
        name   = Path(dst_rel).name
        status = "would sync" if dry_run else "synced"
        print(f"    {GREEN}{name:<22}{RESET} [{status} - {stats['dst_lines']:,} lines]")

    # -----------------------------------------------------------------------
    # Sync command files (with path normalization)
    # -----------------------------------------------------------------------
    print()
    print(f"  {CYAN}Commands:{RESET}")
    command_stats = []
    for src_rel, dst_rel in COMMAND_FILES:
        src_path = CLAUDE_HOME / src_rel
        dst_path = SRC_DIR / dst_rel
        stats = sync_file(
            src_path, dst_path,
            transforms=["normalize_paths"],
            dry_run=dry_run,
            substitutions=substitutions,
        )
        command_stats.append((dst_rel, stats))
        name   = Path(dst_rel).name
        status = "would sync" if dry_run else "synced"
        print(f"    {GREEN}{name:<22}{RESET} [{status} - {stats['dst_lines']:,} lines]")

    # -----------------------------------------------------------------------
    # Sync hook scripts (verbatim copy)
    # -----------------------------------------------------------------------
    print()
    print(f"  {CYAN}Hook scripts:{RESET}")
    hook_stats = []
    for src_rel, dst_rel in HOOK_FILES:
        src_path = CLAUDE_HOME / src_rel
        dst_path = SRC_DIR / dst_rel
        stats = sync_file(src_path, dst_path, dry_run=dry_run)
        hook_stats.append((dst_rel, stats))
        status = "would copy" if dry_run else "copied"
        name = Path(dst_rel).name
        print(f"    {GREEN}{name:<22}{RESET} [{status} - {stats['src_lines']:,} lines]")

    # -----------------------------------------------------------------------
    # Extract CLAUDE.md notemap section
    # -----------------------------------------------------------------------
    print()
    print(f"  {CYAN}CLAUDE.md section:{RESET}")
    claude_dst = SRC_DIR / "claude-md" / "notemap-instructions.md"
    claude_stats = sync_claude_md_section(
        claude_dst,
        dry_run=dry_run,
        substitutions=substitutions,
    )
    name   = "notemap-instructions.md"
    status = "would extract" if dry_run else "extracted"

    if claude_stats["skipped"]:
        print(f"    {RED}{name:<22}{RESET} [SKIPPED]")
    else:
        print(f"    {GREEN}{name:<22}{RESET} [{status} - {claude_stats['dst_lines']:,} lines]")

    for w in claude_stats["warnings"]:
        print(f"      {YELLOW}WARNING: {w}{RESET}")

    # -----------------------------------------------------------------------
    # Collect all warnings
    # -----------------------------------------------------------------------
    all_warnings = []
    for _, stats in python_stats + doc_stats + skill_stats + command_stats + hook_stats:
        all_warnings.extend(stats["warnings"])
    all_warnings.extend(claude_stats["warnings"])

    # -----------------------------------------------------------------------
    # Version management
    # -----------------------------------------------------------------------
    print()
    print(f"  {CYAN}Version:{RESET}")

    old_version = read_version()
    any_changed = any(s.get("changed") for _, s in python_stats + doc_stats + skill_stats + command_stats + hook_stats)
    any_changed = any_changed or claude_stats.get("changed", False)

    if bump_major:
        new_version = bump_version(old_version, "major")
        bump_reason = "major bump (--major)"
    elif bump_minor:
        new_version = bump_version(old_version, "minor")
        bump_reason = "minor bump (--minor)"
    elif any_changed:
        new_version = bump_version(old_version, "patch")
        bump_reason = "patch bump (changes detected)"
    else:
        new_version = old_version
        bump_reason = ""

    if new_version != old_version:
        verb = "would bump" if dry_run else "bumped"
        print(f"    {GREEN}v{old_version} -> v{new_version}{RESET} [{verb}: {bump_reason}]")
        if not dry_run:
            write_version(new_version)
    else:
        print(f"    {GREEN}v{old_version}{RESET} [no changes, no bump]")

    # Propagate version to all targets
    propagated = []
    src_server = SRC_DIR / "notemap-mcp" / "server.py"
    live_server = CLAUDE_HOME / "notemap-mcp" / "server.py"
    if patch_py_version(src_server, new_version, dry_run=dry_run):
        propagated.append("src/__version__")
    if patch_py_version(live_server, new_version, dry_run=dry_run):
        propagated.append("live/__version__")
    if patch_readme_badge(new_version, dry_run=dry_run):
        propagated.append("README.md badge")
    if patch_changelog_header(new_version, dry_run=dry_run):
        propagated.append("CHANGELOG.md header")
    if propagated:
        verb = "would update" if dry_run else "updated"
        print(f"    {GREEN}Version propagated:{RESET} {', '.join(propagated)} [{verb}]")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print()
    print(f"  {'=' * 60}")
    if dry_run:
        print(f"  {BOLD}  DRY RUN COMPLETE -- no files written{RESET}")
    else:
        print(f"  {BOLD}  SYNC COMPLETE{RESET}")
    print(f"  {'=' * 60}")

    total_files = len(python_stats) + len(doc_stats) + len(skill_stats) + len(command_stats) + len(hook_stats) + 1  # +1 for claude-md
    print(f"  {total_files} files processed")

    if all_warnings:
        print()
        print(f"  {YELLOW}Warnings ({len(all_warnings)}):{RESET}")
        for w in all_warnings:
            print(f"    - {w}")

    if not dry_run:
        print()
        print(f"  {CYAN}Next steps:{RESET}")
        print(f"    1. Review changes:  git diff")
        print(f"    2. Commit & tag:    git add -A && git commit && git tag v{new_version}")

    print()
    return 1 if all_warnings else 0


if __name__ == "__main__":
    sys.exit(main())
