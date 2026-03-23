# Notemap -- Detailed Reference

This doc supplements the notemap section in CLAUDE.md with detailed trigger lists, note format specification, and usage examples. The 3 core rules in CLAUDE.md are the mandatory minimum. This doc provides the full reference.

## Quick Reference

**3 Core Rules:** (1) Preflight before coding. (2) Check after coding. (3) Capture surprises with sources.

**The Preflight-Check Workflow:**
1. **Preflight:** `notemap_preflight(libraries=["zendb", "smartarray"])` -- loads ALL notes, anti-patterns first
2. **Write code** -- with gotchas fresh in context
3. **Check:** `notemap_check(code="...", file_path="app.php")` -- auto-detects libraries, runs lint, surfaces function gotchas

**Tools at a glance:**

| Tool | When | Example |
|------|------|---------|
| **Preflight** | Session start / new task | `notemap_preflight(libraries=["zendb"], versions={"zendb": "3.0"})` |
| **Check** | After writing code | `notemap_check(code="...", file_path="app.php")` |
| **Search** | Specific function/keyword lookup | `notemap_search(function_name="DB::get")` |
| **Create** | Learned something surprising | `notemap_create(library, topic, notes, summary, sources)` |
| **Update** | Note is wrong/incomplete | `notemap_update(id, ..., mark_reviewed=true)` |
| **Delete** | Note is obsolete | `notemap_delete(id, reason="...")` |
| **Stats** | Discover what libraries have notes | `notemap_stats()` |
| **Lint** | Anti-pattern spot-check only | `notemap_lint(code="...", library="...")` |
| **Audit** | Find problematic notes | `notemap_audit(check="all")` |
| **Review** | Prioritized review queue | `notemap_review()` |

**Compliance formats:**
- `[notemap-preflight: zendb/3, smartstring/4, 2 anti-patterns loaded]`
- `[notemap-check: clean]` or `[notemap-check: 1 warning, 2 function notes]`

---

## Workflow Examples

### Example A: Preflight at Session Start

```
# 1. User is working on a project that uses ZenDB + SmartArray + SmartString
# Identify libraries from composer.json, then preflight:
notemap_preflight(libraries=["zendb", "smartarray", "smartstring"], versions={"zendb": "3.0"})
# Returns: 10 notes organized by type, anti-patterns first, function_index built
# [notemap-preflight: zendb/3, smartarray/3, smartstring/4 -- 1 anti-pattern loaded]

# 2. All gotchas are now in context. Key anti-pattern: never wrap SmartString in htmlspecialchars()
# function_index shows DB::get has 2 notes, filter has 1 note, sort/sortBy have 1 note
# Claude now knows which functions have gotchas without needing to search.
```

### Example B: Post-Error Note Creation (with sources)

```
# Claude hits an error: trim($smartString) doesn't work as expected
# After fixing the code to use $smartString->trim():

notemap_create(
  library="smartstring",
  topic="Use SmartString trim method not PHP trim",
  type="anti-pattern",
  notes="PHP trim() on SmartString operates on the HTML-encoded __toString() output, not the raw value. Use ->trim() method instead which operates on the raw data.",
  summary="Use ->trim() on SmartString, not PHP trim(). PHP trim() acts on encoded output.",
  sources=[
    {"type": "file", "path": "vendor/itools/smartstring/src/SmartString.php", "lines": "782-785"},
    {"type": "user", "context": "Discovered via runtime error during session"}
  ],
  primitives_to_avoid=["\\btrim\\(\\s*\\$"],
  preferred_alternatives=["->trim()"],
  source_quality="runtime-tested",
  confidence="strong"
)
```

### Example C: Verify and Update Flow

```
# During coding, Claude uses a note about DB::get() and confirms it's correct:
notemap_update(
  id="zendb-db-get-returns-empty-smartarrayhtml-on-no-match",
  mark_reviewed=true,
  source_quality="verified-from-source",
  confidence="strong",
  sources=[{"type": "file", "path": "vendor/itools/zendb/src/ConnectionInternals.php", "lines": "290-295"}]
)

# Later, discover the note is missing info about joins:
notemap_update(
  id="zendb-db-get-returns-empty-smartarrayhtml-on-no-match",
  notes_append="\n- With joins, returned keys are table-prefixed (e.g., 'users.name')\n  [verified-from-source | strong]"
)
```

### Example D: Check Catches an Issue You Didn't Know About

```
# Claude writes code that uses DB::get and empty():
code = '''
$record = DB::get("users", ["email" => $email]);
if (empty($record)) {
    return "User not found";
}
echo $record->name;
'''

# After writing, Claude calls check:
notemap_check(code=code, file_path="src/users.php")
# Returns:
#   detected_libraries: ["zendb", "_cross-cutting"]
#   lint_warnings: [empty() on objects is always false -- use ->isEmpty()]
#   function_notes: [DB::get returns empty SmartArrayHtml on no match, not SmartNull]
#   summary_line: "1 anti-pattern, 1 function gotcha for DB::get"
# [notemap-check: 1 warning, 1 function note]

# Claude fixes the code based on the check results.
```

---

## How to Identify Libraries in Scope

Before calling `notemap_preflight`, identify which libraries the project uses:
- Check `composer.json` / `composer.lock` for PHP dependencies (and versions)
- Check `package.json` / `package-lock.json` for JS dependencies
- Check import/require/use statements in the code you're about to touch
- Check the project's CLAUDE.md for library references
- Call `notemap_stats()` to see which libraries have notes

If function maps are also available, check them first for what functions exist, then call `notemap_preflight` to load gotchas for those libraries.

---

## When to Create Notes (Detailed Triggers)

- You discover a function/method you didn't know existed
- You get an argument order wrong and have to correct it
- You discover a gotcha (e.g., a function that silently fails on certain input types)
- You learn something non-obvious about library behavior
- You read source code and discover the return type differs from what you assumed
- The user corrects your approach or tells you the right way to do something
- You find a pattern that works well and should be reused
- An approach fails or hits a wall (e.g., bash inline strings mangle dollar signs, a tool rejects certain input formats) -- note what didn't work and what you did instead
- You discover an environment/tooling quirk that wastes time (e.g., path resolution differs between tools, a command behaves differently on Windows vs Unix)
- **After recovering from ANY error:** You just hit an error, debugged it, and fixed it. STOP. Before moving on, ask: "Would I hit this same wall again next session?" If yes, create a note. The fix-then-continue flow is where lessons are most commonly lost because the urgency of the fix overshadows the value of the lesson.

## When to Use Preflight vs Search vs Check

**Preflight** (`notemap_preflight`) -- use at session start or task transitions:
- Loads everything for specified libraries in one call
- Organizes by priority (anti-patterns first)
- Builds function_index so you know which functions have gotchas
- Pass `versions` when you know library versions for filtered results

**Check** (`notemap_check`) -- use after writing code:
- Auto-detects libraries from code patterns (no need to specify)
- Runs anti-pattern lint automatically
- Surfaces function-specific notes for functions used in the code
- The DATA-DRIVEN safety net -- catches issues you don't know to search for

**Search** (`notemap_search`) -- use for targeted lookups:
- When you need notes for a specific function: `notemap_search(function_name="DB::get")`
- When exploring a domain concept: `notemap_search(query="null handling")`
- When you need to search across all libraries without filtering

### How to act on search results

Searching is worthless without acting on what you find:
- **Summaries + sources are the fast path** -- search results include summaries, sources, related_functions, and library_version. Assess relevance without reading the full note.
- **Check sources for verification** -- if a note cites a file path and line range, you can verify the claim directly when it matters.
- **Apply gotchas immediately** -- if a note says "never use X, use Y instead," check the code you're about to write for X. This is the whole point.
- **Note contradicts your plan?** The note wins. It was verified against source; your assumption was not.
- **Note seems wrong?** Check the source citation. Verify against source. If wrong, update or delete it.
- **No results?** Proceed with extra caution and note anything surprising you discover.

## Session-Start Behavior

At the start of a coding session on a project with notemap notes:
1. **Discover:** Call `notemap_stats()` to see which libraries have notes in the knowledge base
2. **Identify libraries** from composer.json/package.json/imports/project CLAUDE.md -- cross-reference with stats to know which ones have gotchas to load
3. **Preflight:** `notemap_preflight(libraries=[...], versions={...})` -- one call loads all gotchas
4. **Read the results:** Specifically read the anti-patterns section and note which functions have entries in the `function_index`. These are the traps to watch for as you code.
5. **Report:** `[notemap-preflight: zendb/3, smartstring/4, 2 anti-patterns loaded]`
6. **Optionally check review queue:** `notemap_review()` surfaces stale or low-confidence notes

## During a Session

- **Before writing code:** If you preflighted at session start, the gotchas are already in context. If switching to a new library domain, preflight for the new libraries.
- **After writing code:** Call `notemap_check(code="...", file_path="...")` to catch anti-pattern violations and surface function-specific gotchas. Report `[notemap-check: ...]`.
- **After recovering from errors:** Note what went wrong BEFORE continuing.
- **When corrected by the user:** Create a `correction` type note with `wrong_assumption` and `correct_behavior`.
- **When tangential findings arise:** Capture them in a note ("Also noticed: X may need attention") rather than switching tasks mid-stream (the Worry Pad principle).
- **When a note helps you write correct code:** Mark it reviewed: `notemap_update(id=..., mark_reviewed=true)`. This is the organic review mechanism.

## After Task Completion

Before moving to the next task, quick self-check: "Did I learn anything noteworthy during this task that I haven't noted?" If yes, note it now. If you wait, the context is gone.

## How Notes Get Reviewed

There are two review mechanisms. Both are important.

**Organic review (during normal work):** When you search notemap before coding and USE a note successfully, that note is implicitly verified. Call `notemap_update(id=..., mark_reviewed=true)` after confirming a note helped you write correct code. This is the primary review mechanism -- notes prove their value by being used.

**Formal review (`/notemap review`):** The user triggers this periodically. Claude autonomously reads each flagged note, verifies it against source code, and marks it reviewed, fixed, or deleted. The user only handles ambiguous cases. See the skill file for details.

## When to Update Notes

- When you discover a note is wrong or incomplete
- When you verify a note against actual source code (upgrade source_quality)
- When you learn additional context about something already noted
- When the user corrects behavior that was informed by a note (call with increment_miss=true)

### What to update vs when to create new

- **Update** when the existing note covers the right topic but has wrong/incomplete content. Add the new information, upgrade confidence, fix the error.
- **Create new** when the discovery is a separate concept, even if related. "DB::get returns empty SmartArrayHtml" and "SmartNull is for missing keys" are two separate notes that cross-reference each other, not one mega-note.
- **Rule of thumb:** If the summary would need to cover two distinct ideas, split into two notes.

### How to upgrade confidence

When you verify a note against source code during a session:
```
notemap_update(id="...", source_quality="verified-from-source", confidence="strong", mark_reviewed=true)
```
This is the most valuable update -- it turns an uncertain note into a trusted one.

### How to record a miss

When the user corrects you and the mistake was informed by a note:
```
notemap_update(id="...", increment_miss=true, miss_reason="accuracy-problem")
```
Then fix the note content in the same call or a follow-up call. The miss_count helps identify notes that keep causing trouble.

## When to Delete Notes

- When a function/feature has been removed from the library
- When a note is completely superseded by a better, more complete note
- When a note tagged `unverified` cannot be verified after a genuine attempt

### Update vs Delete decision

- **Update** if the core topic is still relevant but the details are wrong. Fix the details, don't throw away the topic.
- **Delete** if the entire premise is obsolete (library removed the function, codebase no longer uses this pattern, the convention changed entirely).
- **Delete + Create** if the topic needs such a fundamental rewrite that updating would be confusing. Archive the old note (soft delete preserves history), create fresh.

### Consolidation (during /notemap review)

If a library has many small notes covering overlapping territory, merge them into fewer comprehensive notes. Five focused notes beat fifteen scattered fragments. Delete the fragments after merging their content into the consolidated note.

## Note Types

| Type | Purpose | Key Fields |
|------|---------|------------|
| `knowledge` | API behavior, signatures, return types, gotchas | related_functions, related_notes |
| `anti-pattern` | "Don't use X, use Y" -- powers notemap_lint | primitives_to_avoid, preferred_alternatives |
| `correction` | "I thought X but it's actually Y" | wrong_assumption, correct_behavior |
| `convention` | Codebase conventions and patterns | applies_to |

## Evidence Quality Reference

### Source Quality (how we know)

| Tag | Meaning |
|-----|---------|
| `verified-from-source` | Read the actual source code and confirmed |
| `runtime-tested` | Executed code and observed the result |
| `documented` | Found in official docs, README, or inline docblocks |
| `function-map` | Found in a function map but didn't read source |
| `user-correction` | The user told us this is how it works |
| `inferred` | Deduced from patterns or related behavior |
| `unverified` | Assumed, guessed, or from training data |

### Confidence (how sure)

| Level | Meaning |
|-------|---------|
| `strong` | Would bet on it. Multiple sources or read from source. |
| `maybe` | Likely correct, not fully verified. |
| `weak` | Plausible but could be wrong. Needs verification. |

### Filtering Rules

- Big claim + tiny evidence = `inferred | weak` at best
- Note what you DON'T know ("Unknown: behavior when collection is empty")
- `unverified` can never pair with `strong`
- Every `weak` entry should add `check_later` to the note's tags

## Three-Gate Note-Worthiness Filter

Before creating any note, the knowledge must pass three gates:

1. **Relevant?** -- Does this relate to a codebase Claude actively works on?
2. **Important?** -- Would getting this wrong cause a bug, waste time, or produce incorrect code?
3. **Reliable?** -- Can the source be verified?

If a piece of knowledge is cool to know but wouldn't change how you write code, skip it.

## False Confidence Defense Layers

1. **Confidence Tax** -- Training data is unverified. The code is the ground truth.
2. **Context Assessment** -- Before writing code, identify what abstractions are in scope.
3. **Abstraction-First** -- Before using a language built-in, check if the codebase has a wrapper.
4. **Anti-Pattern Notes** -- Check for "don't use X, use Y" notes (grows organically).
5. **Check Tool** -- `notemap_check` auto-detects libraries, runs lint, and surfaces function gotchas (data-driven safety net).

## Accountability Format

At the start of task responses, report what was checked:
- `[notemap-preflight: zendb/3, smartstring/4, 2 anti-patterns loaded]`
- `[notemap-check: clean]` or `[notemap-check: 1 warning, 2 function notes]`
- `[notemap: no libraries in scope]`
- `[notemap: created note for DB::get gotcha]`

## Example: Good Note Creation

After discovering that `DB::get()` returns empty SmartArrayHtml (not SmartNull) on no match:

```
notemap_create(
  library="zendb",
  topic="DB::get returns empty SmartArrayHtml on no match",
  notes="DB::get() returns SmartArrayHtml in ALL cases. On no match, returns an EMPTY SmartArrayHtml, NOT SmartNull. Check with ->isEmpty(). SmartNull is for missing keys on rows, not for query no-match.",
  summary="DB::get() always returns SmartArrayHtml. Empty on no match. Check ->isEmpty(), never empty().",
  cues=["What does DB::get return when no record matches?", "Is the no-match return type SmartNull?"],
  source_quality="verified-from-source",
  confidence="strong",
  related_functions=["DB::get"]
)
```
