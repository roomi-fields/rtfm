"""Whether the plugin agents load is older than the RTFM installed here.

The Claude Code plugin does not use the installed package: it carries its
own copy of RTFM and runs that, for the search tools and for the hooks. The
two are released together and updated separately, and nothing said when
they drifted apart. On one machine the plugin stayed at 0.39.4 for eight
days while the package went to 0.45.0: every fix published in between — a
project reachable by name, coverage, version history for agents, the hooks
that enrol a project — existed, was installed, and reached no agent.

This reports the drift where people look: ``rtfm status`` and ``rtfm audit``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

PLUGIN_KEY = "rtfm@roomi-fields"


def _as_tuple(version: str) -> tuple[int, ...]:
    parts = []
    for piece in str(version).split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def installed_version() -> Optional[str]:
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version("rtfm-ai")
    except (ImportError, PackageNotFoundError):
        return None


def plugin_version(project_root: Path | None = None,
                   registry: Path | None = None) -> Optional[str]:
    """The plugin version Claude Code loads for *project_root*.

    A plugin installed for one project overrides the one installed for the
    user, so that entry wins when it matches.
    """
    path = registry or Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entries = (data.get("plugins", data) or {}).get(PLUGIN_KEY) or []
    if isinstance(entries, dict):
        entries = [entries]
    user = None
    for entry in entries:
        scope = entry.get("scope")
        if (project_root is not None and scope in ("local", "project")
                and entry.get("projectPath")
                and Path(entry["projectPath"]).resolve() == Path(project_root).resolve()):
            return entry.get("version")
        if scope == "user":
            user = entry.get("version")
    return user


def plugin_behind(project_root: Path | None = None,
                  registry: Path | None = None) -> Optional[tuple[str, str]]:
    """``(plugin, installed)`` when agents load older code than is installed."""
    plugin = plugin_version(project_root, registry)
    installed = installed_version()
    if not plugin or not installed:
        return None
    if _as_tuple(plugin) < _as_tuple(installed):
        return plugin, installed
    return None


def warning(project_root: Path | None = None) -> Optional[str]:
    behind = plugin_behind(project_root)
    if behind is None:
        return None
    plugin, installed = behind
    return (f"⚠ Agents load RTFM {plugin} through the Claude Code plugin; "
            f"{installed} is installed. Fixes since {plugin} do not reach them.\n"
            f"  → claude plugin update {PLUGIN_KEY}   (then restart the sessions)")
