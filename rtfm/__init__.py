"""
rtfm - A local document library with semantic search.

Like NotebookLM, but local and extensible.
"""

from importlib.metadata import version as _pkg_version, PackageNotFoundError

from rtfm.core.library import Library
from rtfm.core.models import Chunk, SearchResult, SearchResults
from rtfm.schema import get_schema, CORE_CHUNK_FIELDS, METADATA_EXAMPLES

try:
    __version__ = _pkg_version("rtfm")
except PackageNotFoundError:
    __version__ = "0.0.0"
__all__ = [
    "Library",
    "Chunk",
    "SearchResult",
    "SearchResults",
    "get_schema",
    "CORE_CHUNK_FIELDS",
    "METADATA_EXAMPLES",
]
