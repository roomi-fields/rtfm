"""Document parsers for rtfm."""

from rtfm.parsers.base import BaseParser, ParserRegistry

# Import parsers to trigger registration
from rtfm.parsers import markdown
from rtfm.parsers import xml_legifrance
from rtfm.parsers import html_bofip
from rtfm.parsers import plaintext

# PDF parser (optional dependency)
try:
    from rtfm.parsers import pdf
except ImportError:
    pass  # pdftext not installed

__all__ = ["BaseParser", "ParserRegistry"]
