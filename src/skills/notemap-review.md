---
description: "Review and maintain notemap notes -- Claude autonomously verifies notes against source, fixes issues, and reports findings"
user-invocable: true
---

# /notemap review

Perform a deliberate review of the notemap knowledge base. Claude does the verification work autonomously -- the user only needs to make decisions on ambiguous cases.

## Arguments

- `$1` (optional): library name to focus on (e.g., `/notemap review zendb`). If omitted, reviews all libraries.
- `$2` (optional): max notes to review (default: all). Pass a number to limit.

## Steps

### 1. Audit

Run `notemap_audit(check="all")` to get the full report. Present a brief summary:
- N stale / N low-confidence / N unreviewed / N high-miss-count
- Total notes, by library

### 2. Autonomous Review (Claude does this, not the user)

Process notes in priority order (high-miss-count first, then stale, then low-confidence, then unreviewed). For each note:

**For library-specific notes (zendb, smartarray, smartstring, etc.):**
- Read the note with `notemap_read`
- Verify claims against the actual source code (read the relevant source file)
- If correct: `notemap_update(id=..., mark_reviewed=true)` -- optionally upgrade source_quality if you verified from source
- If wrong: `notemap_update(id=..., mark_reviewed=true, ...)` with corrected content
- If obsolete: `notemap_delete(id=..., reason="...")`
- If unable to verify (can't find source): flag for user and skip

**For learning-principles and convention notes:**
- These don't have source code to verify against. Mark reviewed if the principle is still sound.
- `notemap_update(id=..., mark_reviewed=true)`

**For anti-pattern notes:**
- Verify the `primitives_to_avoid` patterns still apply (the codebase still has the wrapper/alternative)
- If the alternative was removed, delete the anti-pattern note

### 3. Consolidation Check

Check if any library has more than 10 notes. If so, look for overlapping topics that could be merged into fewer comprehensive notes. Propose merges to the user before executing.

### 4. Miss Pattern Analysis

If any notes have `miss_log` data, report the distribution:
- N pseudo-forgetting (note didn't exist when needed)
- N retrieval-failure (note existed but wasn't found/searched)
- N accuracy-problem (note was wrong)

This tells the user whether the problem is note creation, search habits, or content quality.

### 5. Report

```
Notemap Review Complete:
- Reviewed: N notes
- Verified correct: N
- Updated/fixed: N
- Deleted: N
- Flagged for user: N (with reasons)
- Still pending: N
```

## Key Principle

The review is Claude's job, not the user's. The user invokes `/notemap review` and gets a report. They only need to make decisions on the flagged items. This follows the 80/20 ratio: Claude does 80% of the review work (reading, verifying, marking), the user handles the 20% that requires judgment.
