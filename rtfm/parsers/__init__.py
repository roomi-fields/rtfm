"""Document parsers for rtfm."""

from rtfm.parsers.base import BaseParser, ParserRegistry

# Import parsers to trigger registration (order = priority for overlapping extensions)
from rtfm.parsers import markdown
from rtfm.parsers import xml_legifrance
from rtfm.parsers import html_bofip
from rtfm.parsers import python
from rtfm.parsers import latex
from rtfm.parsers import yaml_parser
from rtfm.parsers import json_parser
from rtfm.parsers import shell
from rtfm.parsers import sqlite_parser
from rtfm.parsers import jupyter
from rtfm.parsers import csv_parser
from rtfm.parsers import fb2  # stdlib XML — no extra dep
from rtfm.parsers import djvu  # subprocess to djvutxt (system binary) — no Python dep
from rtfm.parsers import plaintext  # catch-all — must be last

# PDF parser (optional dependency: pdftext)
try:
    from rtfm.parsers import pdf
except ImportError:
    pass

# TOML parser (needs tomllib stdlib 3.11+ or tomli backport)
try:
    from rtfm.parsers import toml_parser
except ImportError:
    pass

# XLSX parser (optional dependency: openpyxl)
try:
    from rtfm.parsers import xlsx
except ImportError:
    pass

# EPUB parser (optional: ebooklib + beautifulsoup4)
try:
    from rtfm.parsers import epub
except ImportError:
    pass

# MOBI / AZW / AZW3 parser (optional: mobi + beautifulsoup4)
try:
    from rtfm.parsers import mobi_parser
except ImportError:
    pass

# DOCX parser (optional: python-docx)
try:
    from rtfm.parsers import docx
except ImportError:
    pass

# ODT parser (optional: odfpy)
try:
    from rtfm.parsers import odt
except ImportError:
    pass

# RTF parser (optional: striprtf)
try:
    from rtfm.parsers import rtf
except ImportError:
    pass

__all__ = ["BaseParser", "ParserRegistry"]
