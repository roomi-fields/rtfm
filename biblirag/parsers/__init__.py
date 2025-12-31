"""Document parsers for biblirag."""

from biblirag.parsers.base import BaseParser, ParserRegistry

# Import parsers to trigger registration
from biblirag.parsers import markdown
from biblirag.parsers import xml_legifrance

__all__ = ["BaseParser", "ParserRegistry"]
