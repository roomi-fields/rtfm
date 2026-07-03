"""
rtfm - A local document library with semantic search.

Like NotebookLM, but local and extensible.
"""


def _adopt_plugin_extras() -> None:
    """Expose the Claude Code plugin's extras venv to any rtfm entry point.

    When rtfm is used as a Claude Code plugin, optional parsers (pdftext,
    ebooklib, openpyxl, python-docx, mobi, pytesseract, ...) and
    fastembed live in an isolated venv at
    ``${CLAUDE_PLUGIN_DATA}/extras/venv``, populated by
    ``rtfm-install-extras``. ``bin/rtfm-serve`` already prepends its
    site-packages to sys.path so the MCP server can import them; but the
    CLI (``rtfm sync``, ``rtfm worker-daemon``, ``rtfm ocr-worker``, ...)
    runs from the pipx venv where those libs are typically absent, and
    the hook subprocess ran naked python before 0.24.2.

    We do the same lookup here at package import time so **any** entry
    point that imports ``rtfm`` — CLI, worker daemon, subprocesses
    launched by hooks — sees the extras without the user having to
    export PYTHONPATH themselves. Silent no-op when no plugin venv is
    installed. Appended (not prepended) so the current environment
    keeps priority.
    """
    import os
    import sys
    from pathlib import Path

    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data:
        venv = Path(data) / "extras" / "venv"
    else:
        venv = Path.home() / ".claude" / "plugins" / "data" / "rtfm" / "extras" / "venv"

    lib_dir = venv / "lib"
    if not lib_dir.is_dir():
        return
    for pyver_dir in lib_dir.iterdir():
        site_pkgs = pyver_dir / "site-packages"
        if site_pkgs.is_dir():
            site_str = str(site_pkgs)
            if site_str not in sys.path:
                sys.path.append(site_str)
            break


_adopt_plugin_extras()

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
