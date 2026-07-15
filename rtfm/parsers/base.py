"""Base parser interface for document ingestion."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator, Optional, Type
from rtfm.core.models import Chunk, EdgeCandidate


class BaseParser(ABC):
    """
    Abstract base class for document parsers.

    Subclasses must implement:
    - extensions: list of file extensions this parser handles
    - parse(): method to parse a file into chunks
    """

    # File extensions this parser handles (e.g., ['.pdf', '.PDF'])
    extensions: list[str] = []

    # Human-readable name
    name: str = "base"

    def __init__(self, **config):
        """Initialize parser with optional configuration."""
        self.config = config

    @classmethod
    def can_parse(cls, path: Path) -> bool:
        """Check if this parser can handle the given file."""
        return path.suffix.lower() in [ext.lower() for ext in cls.extensions]

    @classmethod
    def matches(cls, path: Path) -> bool:
        """Content-based routing hook. Override in a parser that needs
        to win over another parser sharing the same extension (e.g. a
        specialised dictionary XML vs the generic XML parser). The
        registry tries every ``matches``-overriding parser first, in
        registration order, before falling back to extension matching.

        Default returns ``False`` so extension-only parsers stay out of
        the content-check pass.
        """
        return False

    @abstractmethod
    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None
    ) -> Iterator[Chunk]:
        """
        Parse a document into chunks.

        Args:
            path: Path to the document file
            metadata: Optional metadata dict (title, slug, etc.)

        Yields:
            Chunk objects ready for indexing
        """
        pass

    def extract_edges(self, path: Path, metadata: Optional[dict] = None) -> list[EdgeCandidate]:
        """Extract dependency edges from the document.

        Override in subclasses to extract imports, links, citations, etc.
        Returns EdgeCandidate objects; resolution to book_ids happens in sync.
        """
        return []

    def extract_metadata(self, path: Path) -> dict:
        """
        Extract metadata from the document.

        Override in subclasses for format-specific metadata extraction.
        """
        return {
            "source_file": path.name,
            "book_slug": path.stem.lower().replace(" ", "-"),
        }


class ParserRegistry:
    """Registry of available parsers."""

    _parsers: dict[str, Type[BaseParser]] = {}
    # Parsers that override ``matches()`` — tried before the extension
    # lookup so a specialised parser (Littré dictionary XML) can win
    # over the generic one (Legifrance XML). Preserves registration
    # order so callers can reason about priority.
    _content_parsers: list[Type[BaseParser]] = []

    @classmethod
    def register(cls, parser_class: Type[BaseParser]) -> Type[BaseParser]:
        """
        Register a parser class.

        Can be used as a decorator:
            @ParserRegistry.register
            class MyParser(BaseParser):
                ...
        """
        for ext in parser_class.extensions:
            cls._parsers[ext.lower()] = parser_class
        # Only content-aware parsers (those that override matches())
        # participate in the content-check pass; extension-only parsers
        # stay out of it to keep get_parser cheap.
        if parser_class.matches is not BaseParser.matches:
            if parser_class not in cls._content_parsers:
                cls._content_parsers.append(parser_class)
        return parser_class

    @classmethod
    def get_parser(cls, path: Path) -> Optional[BaseParser]:
        """Get a parser instance for the given file. Content-aware
        parsers are consulted first; extension routing is the fallback."""
        for pc in cls._content_parsers:
            try:
                if pc.matches(path):
                    return pc()
            except Exception:
                # A misbehaving matches() must never block the fallback.
                continue
        ext = path.suffix.lower()
        parser_class = cls._parsers.get(ext)
        if parser_class:
            return parser_class()
        return None

    @classmethod
    def get_parser_for_extension(cls, ext: str) -> Optional[Type[BaseParser]]:
        """Get parser class for an extension."""
        return cls._parsers.get(ext.lower())

    @classmethod
    def list_extensions(cls) -> list[str]:
        """List all supported extensions."""
        return list(cls._parsers.keys())

    @classmethod
    def list_parsers(cls) -> dict[str, Type[BaseParser]]:
        """List all registered parsers."""
        return dict(cls._parsers)
