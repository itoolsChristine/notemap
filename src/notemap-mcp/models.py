"""Data classes and enums for the notemap system."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SourceQuality(str, enum.Enum):
    VERIFIED_FROM_SOURCE = "verified-from-source"
    RUNTIME_TESTED       = "runtime-tested"
    DOCUMENTED           = "documented"
    FUNCTION_MAP         = "function-map"
    USER_CORRECTION      = "user-correction"
    INFERRED             = "inferred"
    UNVERIFIED           = "unverified"


class Confidence(str, enum.Enum):
    STRONG = "strong"
    MAYBE  = "maybe"
    WEAK   = "weak"


class NoteType(str, enum.Enum):
    KNOWLEDGE    = "knowledge"
    ANTI_PATTERN = "anti-pattern"
    CORRECTION   = "correction"
    CONVENTION   = "convention"
    TECHNIQUE    = "technique"
    REFERENCE    = "reference"
    DECISION     = "decision"
    FINDING      = "finding"


class Lifecycle(str, enum.Enum):
    ACTIVE = "active"
    STALE  = "stale"


class MissReason(str, enum.Enum):
    PSEUDO_FORGETTING = "pseudo-forgetting"
    RETRIEVAL_FAILURE = "retrieval-failure"
    ACCURACY_PROBLEM  = "accuracy-problem"
    UNCLASSIFIED      = "unclassified"


class AuditCheck(str, enum.Enum):
    STALE              = "stale"
    LOW_CONFIDENCE     = "low_confidence"
    UNREVIEWED         = "unreviewed"
    HIGH_MISS_COUNT    = "high_miss_count"
    ORPHANED_FUNCTIONS = "orphaned_functions"
    INDEX_INTEGRITY    = "index_integrity"
    ALL                = "all"


# ---------------------------------------------------------------------------
# Internal data classes
# ---------------------------------------------------------------------------

@dataclass
class IndexEntry:
    """All frontmatter fields plus cues, summary, and path. No note body."""

    id:                    str
    library:               str
    type:                  str
    topic:                 str
    tags:                  list[str]              = field(default_factory=list)
    source_quality:        str                    = SourceQuality.UNVERIFIED.value
    confidence:            str                    = Confidence.MAYBE.value
    lifecycle:             str                    = Lifecycle.ACTIVE.value
    library_version:       str                    = ""
    created:               str                    = ""
    last_modified:         str                    = ""
    last_reviewed:         str                    = ""
    review_interval_days:  int                    = 30
    miss_count:            int                    = 0
    miss_log:              list[dict[str, str]]   = field(default_factory=list)
    review_count:          int                    = 0
    related_functions:     list[str]              = field(default_factory=list)
    related_notes:         list[str]              = field(default_factory=list)
    cues:                  list[str]              = field(default_factory=list)
    summary:               str                    = ""
    path:                  str                    = ""

    # Source citations
    sources:               list[dict[str, str]]   = field(default_factory=list)

    # Anti-pattern specific fields
    primitives_to_avoid:   list[str]              = field(default_factory=list)
    preferred_alternatives: list[str]             = field(default_factory=list)


@dataclass
class SearchResult:
    """Lightweight result returned from search operations."""

    id:              str
    library:         str
    topic:           str
    type:            str
    source_quality:  str
    confidence:      str
    lifecycle:       str
    summary:         str
    relevance_score: float = 0.0
