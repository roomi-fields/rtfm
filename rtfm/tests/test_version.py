"""Regression test for the __version__ lookup.

The package is published on PyPI as ``rtfm-ai`` (the ``rtfm`` name was
already taken). Looking up the wrong distribution name in
``rtfm/__init__.py`` previously made ``rtfm.__version__`` report
``"0.0.0"`` to every user — including the CLI banner and the MCP
server's stats output. This test pins the contract: when the package
is installed (wheel or editable), ``__version__`` must match the
canonical version declared in ``pyproject.toml``.
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest

import rtfm


def _pyproject_version() -> str | None:
    """Read [project].version from pyproject.toml at the repo root."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if not pyproject.exists():
        return None
    text = pyproject.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else None


def test_version_is_not_the_default_fallback():
    """`__version__` must not silently fall back to "0.0.0" when the
    package is installed — that's the symptom of an incorrect dist name."""
    try:
        version("rtfm-ai")
    except PackageNotFoundError:
        pytest.skip("rtfm-ai not installed (pure source checkout)")
    assert rtfm.__version__ != "0.0.0", (
        "rtfm.__version__ is '0.0.0' even though the rtfm-ai distribution "
        "is installed — __init__.py is probably looking up the wrong "
        "distribution name."
    )


def test_version_matches_pyproject():
    """__version__ must agree with [project].version in pyproject.toml."""
    expected = _pyproject_version()
    if expected is None:
        pytest.skip("pyproject.toml not reachable from test context")
    try:
        installed = version("rtfm-ai")
    except PackageNotFoundError:
        pytest.skip("rtfm-ai not installed (pure source checkout)")
    assert installed == expected, (
        f"installed rtfm-ai is {installed}, pyproject.toml is {expected}"
    )
    assert rtfm.__version__ == expected, (
        f"rtfm.__version__ is {rtfm.__version__}, pyproject.toml is {expected}"
    )
