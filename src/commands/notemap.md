---
description: "Scan a project, PDF, text file, or URL and take notes -- or review/manage existing notes."
argument-hint: "<path|file|URL|projectName|review|stats|help> [limit]"
allowed-tools: Read, Grep, Glob, Bash(*), Write, Edit, WebFetch, mcp__notemap__*(*)
---

# /notemap -- Project Knowledge Capture

You are running inside **Claude Code** as the `/notemap` command.

## Argument Routing

Parse `$ARGUMENTS` and route to the correct mode:

| Argument | Mode | Description |
|----------|------|-------------|
| `help` | Help | Show quick reference and available tools |
| `stats` | Stats | Run `notemap_stats()` and display overview |
| `review` [library] [limit] | Review | Run autonomous note review (delegate to `/notemap review` skill) |
| `/path/to/file.pdf` | **PDF Scan** | Read PDF, take notes on content |
| `/path/to/file.txt` or `.md` or `.srt` or `.log` | **Text Scan** | Read text/markdown/subtitle file, take notes |
| `https://...` or `http://...` | **URL Scan** | Fetch URL, take notes on content |
| `/path/to/project` (absolute path to a directory) | **First Scan** | Scan a new project, identify libraries, take notes |
| `projectname` (no slashes, not a keyword) | **Rescan** | Rescan an existing project by library name, update notes |

**Detection logic** (check in order):
1. Ends with `.pdf` -> PDF Scan
2. Ends with `.txt`, `.md`, `.srt`, `.log` -> Text Scan
3. Starts with `http://` or `https://` -> URL Scan
4. Is an absolute path to a directory -> First Scan (existing)
5. Otherwise -> Rescan (existing)

## Mode: Help

Output this quick reference:

```
notemap -- Project Knowledge Capture for Claude Code

Usage:
  /notemap /path/to/project    Scan a code project and take notes
  /notemap /path/to/file.pdf   Scan a PDF and take notes on its content
  /notemap /path/to/file.txt   Scan a text file and take notes
  /notemap https://example.com Scan a URL and take notes
  /notemap libraryname         Rescan and update notes for a library
  /notemap review [lib] [N]    Review notes (autonomous verification)
  /notemap stats               Show note counts by library
  /notemap help                Show this help

14 MCP Tools (available directly in conversation):
  notemap_preflight  Load all notes for libraries (session start)
  notemap_check      Auto-detect libraries & check code for issues
  notemap_create     Create a new note
  notemap_read       Read a note by ID
  notemap_search     Search notes by library/function/keyword
  notemap_update     Update a note (fix content, upgrade confidence)
  notemap_delete     Soft-delete or hard-delete a note
  notemap_audit      Find stale/low-confidence/problematic notes
  notemap_review     Get prioritized review queue
  notemap_lint       Check code against anti-pattern notes
  notemap_stats      Overview of libraries and note counts
  notemap_connections Query the knowledge graph (connections, paths, communities)
  notemap_embed      Generate/refresh embeddings for all notes (batch)
  notemap_ingest     Chunk and ingest text content for semantic search
```

Then stop.

## Mode: Stats

Call `notemap_stats()` and display the results in a readable format. Show libraries sorted by note count, total notes, and any health issues. Then stop.

## Mode: Review

Delegate to the `/notemap review` skill. Pass through any library name and limit arguments.

## Mode: PDF Scan

Scan a PDF file and create notes on its content. This workflow is designed to handle
book-length documents (500+ pages) with resume support across sessions.

### Step 0: Check for existing scan progress

Search for an existing progress note:
```
notemap_search(query="scan progress", library="slugified-name", max_results=1)
```

If a progress note exists, read it to find out which pages were already scanned.
Resume from the next unscanned page. Skip Step 1 (survey already done).

### Step 1: Survey the document (SQ3R "Survey" step)

Before scanning page-by-page, survey the document structure:

- Read the first 5 pages (title page, table of contents, preface/introduction)
- Identify the subject domain, structure (chapters/sections), and total scope
- Choose a `library` name from the filename (lowercase, no extension, slugified - e.g., `cognitive-psychology` from `Cognitive Psychology.pdf`)

**Create a structural overview note:**
```
notemap_create(
  library="slugified-name",
  topic="[Book Title] - structural overview",
  type="reference",
  notes="Chapters: 1. [topic], 2. [topic], ... N. [topic]\nTotal pages: N\nKey themes: ...",
  summary="Structural overview of [Book Title] covering [subject] across N chapters.",
  cues=["What topics does [Book Title] cover?", "What chapter covers [topic]?"],
  source_quality="documented",
  confidence="strong",
  sources=[{type: "file", path: "/path/to/file.pdf", section: "Table of Contents"}],
  tags=["overview", "structure"]
)
```

**Create a scan progress note** (updated after each batch):
```
notemap_create(
  library="slugified-name",
  topic="[Book Title] - scan progress",
  type="reference",
  notes="Pages scanned: 1-5 of N\nPages remaining: 6-N\nNotes created: 1 (overview)\nLast scanned: [date]",
  summary="Scan progress tracker for [Book Title]. Resume from page 6.",
  cues=["scan progress"],
  source_quality="documented",
  confidence="strong"
)
```

Report what was found:
```
Source: /path/to/file.pdf
Title: [title from content]
Pages: N
Subject: [brief description]
Structure: N chapters covering [key topics]
Library: slugified-name
```

### Step 2: Scan and take notes

Read the PDF in batches of 20 pages. For each batch:

**A. Ingest raw text** - Preserve the original text for semantic search:
```
notemap_ingest(code=raw_text_from_pages, library="slugified-name")
```
This stores the raw passages as searchable chunks. Even passages that don't become
distilled notes remain findable via semantic search.

**B. Create distilled notes** - Use the 3-pass pipeline:

1. **Extract**: Identify noteworthy passages in this batch
2. **Crystallize**: Distill each into an atomic note with metadata
3. **Connect**: Search for related existing notes and link them

For each note, apply the three-gate filter:
- **Relevant?** Would this knowledge change how someone approaches a problem in this domain?
- **Important?** Would getting this wrong lead to a misconception or incorrect application?
- **Reliable?** Is this well-supported by the source material?

What to look for (varies by document type):

**For textbooks**: Capture principles and mental models, not definitions. Focus on:
- Causal mechanisms (X happens BECAUSE Y)
- Common misconceptions the book corrects
- Relationships between concepts
- Techniques and methods with their rationale
- Surprising findings or counterintuitive results

**For API docs**: Focus on gotchas, not every method signature.
**For tutorials**: Capture the "why" behind steps, not the steps.
**For reference material**: Capture facts someone would look up, with enough context to apply them.

Create each note with `notemap_create`:
- `library`: the slugified name from Step 1
- `sources`: `[{type: "file", path: "/path/to/the.pdf", section: "Chapter X, p.Y"}]`
- `cues`: Write as questions someone would ask when they NEED this knowledge.
  Not "What is photosynthesis?" (trivia) but "Why must the light reactions happen before
  the Calvin cycle?" (situational - fires when someone is reasoning about the process)
- `related_notes`: Search for and link to related notes within this library
- `source_quality`: documented
- `confidence`: strong

**C. Update scan progress** - After each batch, update the progress note:
```
notemap_update(id="progress-note-id", notes="Pages scanned: 1-N of TOTAL\n...")
```

**D. Move to next 20 pages** and repeat A-C.

### Stopping signals (stop when 3 of 5 are true)

1. Last 3 notes are all knowledge/reference (no gotchas or misconceptions found)
2. Finding more duplicates than new notes
3. Remaining content is background, not actionable
4. All major chapters/sections covered
5. Notes getting abstract rather than specific

**Quality test**: "Would someone search for terms in this note when they need to apply this
knowledge?" If the answer is no, skip it.

### Step 3: Report

```
Scan complete: /path/to/file.pdf
  Created: N notes (N knowledge, N technique, N reference, ...)
  Ingested: N chunks of raw text
  Library: slugified-name

  Notes by chapter:
  - Ch.1 [title]: N notes
  - Ch.2 [title]: N notes
  - ...

  To search: notemap_search(library="slugified-name")
  To review: /notemap review slugified-name
  To resume: /notemap /path/to/file.pdf (auto-detects progress)
```

## Mode: Text Scan

Scan a text, markdown, subtitle, or log file and create notes on its content.

### Step 1: Read the file

- Read the file using the Read tool
- Choose a `library` name from the filename (lowercase, no extension, slugified)
- Report what was found:

```
Source: /path/to/file.txt
Title: [title from content or filename]
Lines: N
Subject: [brief description of what the file covers]
Library name for notes: slugified-name
```

### Step 2: Scan and take notes

Same approach as PDF Scan:
- Apply the three-gate filter
- Scan systematically (by heading, section, or logical chunk)
- Select note type using the decision tree
- Create notes with `notemap_create`:
  - `sources`: `[{type: "file", path: "/path/to/file.txt", section: "line range or heading"}]`
  - `cues`: situational questions
  - `source_quality`: documented
  - `confidence`: strong

### Step 3: Report

Same format as PDF Scan.

## Mode: URL Scan

Fetch a URL and create notes on its content.

### Step 1: Fetch the URL

- Fetch the URL using the WebFetch tool
- Choose a `library` name from the domain/path (e.g., `docs-anthropic` from `docs.anthropic.com`, `mdn-web-api` from `developer.mozilla.org/en-US/docs/Web/API`)
- Report what was found:

```
Source: https://example.com/path
Title: [page title]
Subject: [brief description of what the page covers]
Library name for notes: domain-derived-name
```

### Step 2: Scan and take notes

Same approach as PDF Scan:
- Apply the three-gate filter
- Scan systematically by section/heading
- Select note type using the decision tree
- Create notes with `notemap_create`:
  - `sources`: `[{type: "url", url: "https://...", section: "heading or section name"}]`
  - `cues`: situational questions
  - `source_quality`: documented
  - `confidence`: strong

### Step 3: Report

Same format as PDF Scan, with URL instead of file path.

## Mode: First Scan (absolute path to a project)

This is the core feature. Claude scans a project directory and creates notes for everything noteworthy.

### Step 1: Discover the project

- Read the project's README, CLAUDE.md, composer.json, package.json to understand what it is
- Identify libraries, frameworks, and key dependencies
- Determine the primary language(s)
- Choose a `library` name for the notes (use the project folder name, lowercase)

Report what was found:
```
Project: /path/to/myproject
Language: PHP
Libraries: ZenDB, SmartArray, SmartString
Framework: CMS Builder
Library name for notes: myproject
```

### Step 2: Read source code and identify noteworthy knowledge

Go through the project's source files systematically. For each file/module, look for:

**Gotchas and surprises:**
- Functions that return unexpected types
- Silent failure modes (no error, just wrong behavior)
- Parameters with non-obvious behavior or ordering
- Things that look like they should work but don't

**Anti-patterns:**
- Language builtins that should be replaced by library methods
- Common mistakes that would cause bugs
- Deprecated patterns still in use

**Conventions:**
- Naming conventions, file organization patterns
- Error handling patterns, logging patterns
- Configuration patterns

**Corrections to training data:**
- Anything that differs from what Claude would assume based on training data
- Custom wrappers that override standard behavior

Apply the three-gate filter for each finding:
1. **Relevant?** -- Related to this codebase?
2. **Important?** -- Would getting it wrong cause a bug?
3. **Reliable?** -- Can it be verified from the source?

Skip trivial observations. Focus on the frontier zone: things Claude partially knows but gets subtly wrong.

### Step 3: Create notes

For each noteworthy finding, call `notemap_create` with:
- `library`: the project name chosen in Step 1
- `topic`: concise description of the finding
- `type`: knowledge, anti-pattern, correction, or convention as appropriate
- `notes`: the key facts, telegraphic but meaningful
- `summary`: one complete sentence distilling the finding
- `cues`: 1-2 questions that would naturally arise when Claude needs this knowledge
- `source_quality`: verified-from-source (you just read the code)
- `confidence`: strong (you verified it)
- `related_functions`: if applicable
- Anti-pattern fields (`primitives_to_avoid`, `preferred_alternatives`) if type is anti-pattern

### Step 4: Report

```
Scan complete: /path/to/myproject
  Created: N notes (N knowledge, N anti-pattern, N correction, N convention)
  Library: myproject

  Notes created:
  - [knowledge] Function X returns Y not Z
  - [anti-pattern] Never use raw_func(), use wrapper()
  - ...

  To search: notemap_search(library="myproject")
  To review: /notemap review myproject
  To rescan: /notemap myproject
```

## Mode: Rescan (project name, not a path)

Update notes for an existing project.

### Step 1: Check existing notes

Call `notemap_search(library="projectname", max_results=50, lifecycle="all")` to see what notes already exist.

### Step 2: Find the project path

Look for the project in common locations:
- Check if `$ARGUMENTS` matches a library name in the notemap index
- Check function maps for a project with that name (they store the source path)
- Check recent working directories
- If can't find it, ask the user for the path

### Step 3: Rescan source code

Read the source files again, comparing against existing notes:
- **New findings**: Create new notes
- **Changed behavior**: Update existing notes with corrections
- **Confirmed existing notes**: Mark as reviewed (`notemap_update(mark_reviewed=true)`)
- **Obsolete notes**: Delete notes for removed features/functions

### Step 4: Report

```
Rescan complete: projectname
  Existing notes: N
  New notes created: N
  Notes updated: N
  Notes marked reviewed: N
  Notes deleted: N

  To search: notemap_search(library="projectname")
```

## Key Principles (from the notemap learning-principles notes)

- **Three-gate filter**: Only note what's relevant, important, and reliable
- **Overmarking trap**: Notes must capture MEANING, not just observations
- **Telegraphic**: Concise notes, complete summaries
- **80/20 ratio**: Creating notes IS the learning, not overhead
- **Frontier zone**: Focus on what Claude partially knows but gets wrong
- **Evidence quality**: Tag every claim with source_quality and confidence

### Three-Gate Filter (apply to every note)

1. **Relevant?** -- Does this relate to work Claude actively does?
2. **Important?** -- Would getting it wrong cause problems?
3. **Reliable?** -- Can the source be verified?

Cool-to-know but wouldn't-change-behavior = skip it.

### Choosing Note Types

Ask: "What is this note FOR?"
- Preventing a mistake -> anti-pattern (regex-detectable) or correction (misconception)
- How something works -> knowledge
- Fact to look up later -> reference
- How to do something well -> technique
- Rule/standard to follow -> convention
- Why a choice was made -> decision
- What was found/observed -> finding
