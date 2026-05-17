"""
rtfm - A local document library with semantic search.

Like NotebookLM, but local and extensible.
"""

from importlib.metadata import version as _pkg_version, PackageNotFoundError

from rtfm.core.library import Library
from rtfm.core.models import Chunk, SearchResult, SearchResults
from rtfm.schema import get_schema, CORE_CHUNK_FIELDS, METADATA_EXAMPLES

# Distribution name on PyPI is "rtfm-ai" (the "rtfm" import name was
# already taken). Looking up "rtfm" here returns PackageNotFoundError
# silently, which previously made __version__ permanently report
# "0.0.0" to users — including the CLI, the MCP server, and rtfm status.
try:
    __version__ = _pkg_version("rtfm-ai")
except PackageNotFoundError:  # source checkout without a wheel built
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
