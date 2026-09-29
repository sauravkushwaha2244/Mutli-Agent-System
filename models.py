"""Data structures for the evidence-first ResearchMind pipeline."""

from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


@dataclass
class PageRecord:
    """Represents a scraped webpage with metadata and rule-based credibility score."""
    source_id: str             # e.g., "s1", "s2"
    source_name: str           # Domain or extracted title (set by code)
    url: str                   # Page URL (set by code)
    raw_text: str              # Full extracted text from Trafilatura / scraper
    trimmed_text: str          # Text capped to ~2000 tokens (~8000 chars)
    published: str             # Publication date or year (set by code)
    credibility: float         # 0.1 to 1.0 rule-based score (set by code)
    is_snippet_fallback: bool  # True if scrape failed and search snippet was used

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClaimRecord:
    """Represents an atomic factual claim extracted from a source page."""
    id: str                    # e.g., "c1", "c2"
    text: str                  # The extracted factual claim statement
    quote: str                 # Exact snippet from the scraped page text
    source_id: str             # Source identifier (set by code)
    source_name: str           # Source publisher / domain (set by code)
    url: str                   # Source URL (set by code)
    published: str             # Publish date (set by code)
    credibility: float         # Inherited source credibility score (set by code)
    status: str = "verified"   # "verified" | "rejected"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClaimGroup:
    """Represents a cluster of claims on the same underlying topic/fact."""
    group_id: str              # e.g., "g1", "g2"
    topic: str                 # Summary of the fact/topic being addressed
    consensus: str             # "AGREE" | "DISPUTED" | "SINGLE_SOURCE"
    claim_ids: List[str]       # List of claim IDs in this group

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchResult:
    """Complete output package containing report, citations, audit, and visuals."""
    topic: str
    report_markdown: str       # Report with converted clickable links
    report_raw: str            # Raw report with [s1] markers
    sources: List[Dict[str, Any]]
    claims: List[Dict[str, Any]]
    groups: List[Dict[str, Any]]
    visuals: Dict[str, Any]    # Plotly configs and Mermaid diagram
    stats: Dict[str, Any]      # Counts, execution times, etc.

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
