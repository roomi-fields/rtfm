"""Data models for rtfm."""

from dataclasses import dataclass, field, asdict
from typing import Optional, Any, TYPE_CHECKING
import json

if TYPE_CHECKING:
    pass


@dataclass
class Chunk:
    """A chunk of content from a document."""

    id: str
    content: str
    book_title: str
    book_slug: str

    # Location
    page_start: int
    page_end: int
    chapter_title: Optional[str] = None
    chapter_num: Optional[int] = None
    paragraph: int = 1
    line_start: Optional[int] = None  # First line in source file (1-indexed)
    line_end: Optional[int] = None    # Last line in source file (1-indexed)

    # Hierarchy (optional)
    book_file: Optional[str] = None
    book_num: Optional[int] = None
    book_name: Optional[str] = None
    part_num: Optional[int] = None
    part_title: Optional[str] = None
    section_type: str = "chapter"

    # Content metadata
    content_chars: int = 0
    content_hash: Optional[str] = None
    tags: Optional[list[str]] = None

    # Extended metadata (domain-specific, stored as JSON)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.content_chars == 0:
            self.content_chars = len(self.content)

    @property
    def source(self) -> str:
        """Human-readable source reference."""
        parts = [self.book_title]
        if self.chapter_title:
            parts.append(self.chapter_title)
        return " > ".join(parts)

    @property
    def page(self) -> str:
        """Page reference."""
        if self.page_start == self.page_end:
            return f"p.{self.page_start}"
        return f"pp.{self.page_start}-{self.page_end}"

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class SearchResult:
    """A single search result with relevance score."""

    chunk: Chunk
    score: float
    rank: int

    # Convenience accessors
    @property
    def content(self) -> str:
        return self.chunk.content

    @property
    def source(self) -> str:
        return self.chunk.source

    @property
    def page(self) -> str:
        return self.chunk.page

    @property
    def book_title(self) -> str:
        return self.chunk.book_title

    @property
    def chapter_title(self) -> Optional[str]:
        return self.chunk.chapter_title

    @property
    def tags(self) -> Optional[list[str]]:
        return self.chunk.tags

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "rank": self.rank,
            "score": self.score,
            "chunk": self.chunk.to_dict()
        }


@dataclass
class SearchResults:
    """Collection of search results with export methods."""

    results: list[SearchResult]
    query: str
    total_found: int

    def __iter__(self):
        return iter(self.results)

    def __len__(self):
        return len(self.results)

    def __getitem__(self, idx):
        return self.results[idx]

    def to_dict(self) -> dict:
        """Export as dictionary (for JSON API)."""
        return {
            "query": self.query,
            "total_found": self.total_found,
            "results": [r.to_dict() for r in self.results]
        }

    def to_json(self) -> str:
        """Export as JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        """Export as markdown (for display)."""
        lines = [f"## Search: {self.query}", f"*{self.total_found} results*\n"]

        for r in self.results:
            lines.append(f"### {r.rank}. {r.source} ({r.page})")
            if r.tags:
                lines.append(f"*Tags: {', '.join(r.tags)}*")
            lines.append(f"\n{r.content}\n")
            lines.append(f"*Score: {r.score:.2f}*\n")
            lines.append("---\n")

        return "\n".join(lines)

    def to_prompt(self, max_chars: int = 8000) -> str:
        """
        Export as context for LLM prompting.

        Formats results optimally for injection into an LLM prompt.
        """
        lines = [f"<search_results query=\"{self.query}\">"]

        char_count = 0
        for r in self.results:
            block = f"""
<result rank="{r.rank}" source="{r.source}" page="{r.page}">
{r.content}
</result>"""
            if char_count + len(block) > max_chars:
                break
            lines.append(block)
            char_count += len(block)

        lines.append("</search_results>")
        return "\n".join(lines)
