"""Minimal pure-Python MCP server — no external dependencies.

Replaces the upstream `mcp` SDK with a ~300-line implementation of the subset
RTFM needs: tool registration via decorator, stdio transport, JSON-RPC 2.0.

Advantages:
- Zero dependencies (Python 3.10+ stdlib only)
- No pydantic / cryptography / native binaries
- Cross-platform out of the box
- Plugin-bundleable (no pip install required)
"""

from rtfm._mcp.server import FastMCP

__all__ = ["FastMCP"]
