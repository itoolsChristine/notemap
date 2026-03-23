<!-- NOTEMAP:INSTRUCTIONS:BEGIN -->
## Notemap -- PERSISTENT KNOWLEDGE BASE

**THIS IS A BLOCKING REQUIREMENT when the notemap MCP server is available.** Notemap captures what you LEARN across sessions -- gotchas, correct patterns, anti-patterns, corrections, and working principles. Function maps tell you WHAT exists. Notemap tells you HOW to use it correctly and what to watch out for. This system is standalone and does NOT depend on function maps.

**You MUST use notemap BEFORE writing code and AFTER writing code. No exceptions. No shortcuts. No "I'll check later." The preflight-then-check workflow catches issues you don't know to search for.**

**Notemap applies to shell commands too, not just code.** Before running Bash commands that involve shell-crossing (cmd/powershell from bash), path manipulation, symlinks/junctions, or Windows-specific operations, search or preflight `_cross-cutting` notes. Shell gotchas are just as costly as code gotchas.

**Notemap also applies to general learning.** Scan PDFs, URLs, and text files with `/notemap` to capture knowledge for future sessions. Point it at a textbook, documentation page, or transcript to build a persistent knowledge base on any topic.

### 3 Core Rules

1. **Preflight before coding.** Call `notemap_preflight(libraries=[...])` at session start or when switching task domains. **Always include `_cross-cutting`** -- it covers shell, environment, and tooling gotchas that apply regardless of which library is in scope. This loads ALL notes for those libraries -- anti-patterns, gotchas, corrections -- organized by impact. You don't need to guess keywords. **Read the anti-patterns it returns and apply them as you code.** Report: `[notemap-preflight: zendb/3, smartstring/4, 2 anti-patterns loaded]`
2. **Check after coding.** Call `notemap_check(code="...", file_path="...")` after writing or editing code that touches library APIs. You can pass code as a string OR just pass a file_path and it reads the file for you. It auto-detects libraries, runs anti-pattern lint, and surfaces function-specific gotchas. You don't need to know what to search for. Report: `[notemap-check: clean]` or `[notemap-check: 1 warning, 2 function notes]`
3. **Capture surprises.** When you learn something new, `notemap_create(...)` with `sources` and `library_version`. When a note is wrong, fix or delete it. After recovering from any error, note what went wrong BEFORE moving on.

### Identifying Libraries in Scope

Before calling preflight, identify which libraries the project uses:
- Call `notemap_stats()` to see which libraries have notes in the knowledge base
- Check `composer.json` / `package.json` for dependencies
- Check import/require/use statements in the code
- Check the project's CLAUDE.md for library references
- When you know library versions (from composer.lock, package.json, project CLAUDE.md), pass them: `notemap_preflight(libraries=[...], versions={"zendb": "3.0"})`

### When to Use Each Tool

| Situation | Tool |
|-----------|------|
| Session start / new task domain | `notemap_preflight(libraries=[...], versions={...})` |
| After writing significant code | `notemap_check(file_path="...")` or `notemap_check(code="...")` |
| Scan a PDF or document | `/notemap /path/to/file.pdf` |
| Scan a website | `/notemap https://example.com` |
| Looking up a specific function | `notemap_search(function_name="DB::get")` |
| Broad keyword exploration | `notemap_search(query="null handling")` |
| Learned something surprising | `notemap_create(...)` with sources + library_version |
| Note is wrong or outdated | `notemap_update(...)` or `notemap_delete(...)` |
| What libraries have notes? | `notemap_stats()` |
| Anti-pattern spot-check only | `notemap_lint(code="...", library="...")` |
| Periodic maintenance | `/notemap review` |

### Choosing a Note Type

Ask: "What is this note FOR?"

- Preventing a mistake I'd repeat -> `anti-pattern` (if regex-detectable) or `correction` (if misconception)
- Recording how something works -> `knowledge`
- Recording a fact to look up later -> `reference`
- Recording how to do something well -> `technique`
- Recording a rule/standard to follow -> `convention`
- Recording why a choice was made -> `decision`
- Recording what I found/observed -> `finding`

### Cross-Reference with Function Maps

After finding functions in the function map, the preflight already includes function-level notes via `function_index`. If you skipped preflight, at minimum run `notemap_check` on your code before finishing.

### Source Citations (mandatory for new notes)

Every note should have structured `sources` so claims can be verified during review:
- `{type: "file", path: "src/ConnectionInternals.php", lines: "395-405"}`
- `{type: "url", url: "https://docs.anthropic.com/...", section: "Rate limits"}`
- `{type: "user", context: "User corrected: DB::get returns SmartArrayHtml not SmartNull"}`

### Confidence Tax

Your training data is UNVERIFIED until confirmed against actual code. The code is the ground truth. Before reaching for a language built-in, ask: does this codebase have its own way of doing this?

**Concretely:** When your confidence comes from training data rather than from reading THIS project's code, notemap, or function map -- STOP and verify first.

### Evidence Quality

When creating notes, tag each claim with source quality and confidence:
- **Source quality:** verified-from-source > runtime-tested > documented > function-map > user-correction > inferred > unverified
- **Confidence:** strong / maybe / weak
- Rule: `unverified` can never pair with `strong`. Note what you DON'T know.

@docs/notemap.md
<!-- NOTEMAP:INSTRUCTIONS:END -->
