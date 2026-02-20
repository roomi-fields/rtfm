"""RTFM plugin for Claude Code — project knowledge indexing and discovery."""

from rtfm.plugin.discover import discover
from rtfm.plugin.claude_md import inject_claude_md
from rtfm.plugin.install import init_project

__all__ = ["discover", "inject_claude_md", "init_project"]
