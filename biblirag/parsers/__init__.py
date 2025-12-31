"""Document parsers for biblirag."""

from biblirag.parsers.base import BaseParser, ParserRegistry

# Import parsers to trigger registration
from biblirag.parsers import markdown
from biblirag.parsers import xml_legifrance
from biblirag.parsers import html_bofip

# PDF parser (optional dependency)
try:
    from biblirag.parsers import pdf
except ImportError:
    pass  # pdftext not installed

__all__ = ["BaseParser", "ParserRegistry"]
