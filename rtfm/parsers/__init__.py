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

__all__ = ["BaseParser", "ParserRegistry"]
