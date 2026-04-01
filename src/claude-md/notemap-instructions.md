<!-- NOTEMAP:INSTRUCTIONS:BEGIN -->
## Notemap -- Persistent Knowledge Base

Notemap is your long-term memory. Notes you create persist across sessions in a
SQLite database and are searched automatically -- the RAG hook injects relevant
notes into your context on every user message. You don't need to search manually
for most knowledge retrieval; it happens behind the scenes.

### What to do actively

**Session start -- load anti-patterns:** Run notemap_preflight(libraries=[...])
including _cross-cutting. This loads gotchas and anti-patterns that prevent you
from repeating mistakes documented in previous sessions.

**After significant edits -- catch anti-patterns:** Run notemap_check(file_path="...")
on files where you made non-trivial changes. It detects libraries, runs lint
against known anti-patterns, and surfaces function-level gotchas. Trivial edits
(typo fixes, comment changes) don't need this.

**When you learn something surprising:** Create a note with notemap_create. If
you discovered a gotcha, corrected a misconception, or found something that
contradicts your training data, capture it before moving on. Future sessions
will benefit.

**When a note was wrong:** Fix it with notemap_update or delete it with
notemap_delete. Wrong notes are worse than no notes.

### Confidence tax

Your training data is unverified. The code is the ground truth. When your
confidence comes from training data rather than from reading this project's
code, notemap, or function map -- stop and verify first.

<examples>
<example>
User: "Fix the upload handler to validate file sizes"
Claude's approach:
1. notemap_search(function_name="processUpload") -- check for known gotchas
2. Read the upload handler code
3. Implement the fix
4. notemap_check(file_path="src/upload.php") -- verify no anti-patterns introduced
</example>
<example>
User: "Why does DB::get return an empty object instead of null?"
Claude's approach:
1. RAG already injected relevant notes about DB::get return types (automatic)
2. Answer using the note: "DB::get always returns SmartArrayHtml -- empty on
   no match. Check with ->isEmpty(), not empty()."
3. notemap_update(id=..., mark_reviewed=true) if the note was helpful
</example>
<example>
User: "I just found out that the cron job silently fails when the lock file exists"
Claude's approach:
1. notemap_create with type="anti-pattern", cues that fire when someone touches
   the cron code, source pointing to the relevant file and lines
2. Link to related notes about the cron system
</example>
</examples>

### Reference

Full tool list (14 tools), note creation guidelines, search architecture, and
review system: @docs/notemap.md
<!-- NOTEMAP:INSTRUCTIONS:END -->
