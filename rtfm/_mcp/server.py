"""Minimal FastMCP-compatible server over stdio.

Implements the JSON-RPC 2.0 subset of the Model Context Protocol needed by
RTFM: initialize handshake, tools/list, tools/call. Uses newline-delimited
JSON on stdin/stdout as per the MCP stdio transport spec.

Not a full MCP SDK — purpose-built for RTFM's needs. Pure stdlib.
"""

from __future__ import annotations

import inspect
import json
import sys
import traceback
from typing import Any, Callable

from rtfm._mcp.schema import build_tool_schema


PROTOCOL_VERSION = "2025-06-18"


class FastMCP:
    """Minimal drop-in replacement for the FastMCP API used in rtfm/mcp.py."""

    def __init__(self, name: str, version: str = "0.7.2") -> None:
        self._name = name
        self._version = version
        self._tools: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._initialized = False

    # ── Registration API (decorators) ───────────────────────────────────

    def tool(self) -> Callable[[Callable], Callable]:
        """Decorator to register a function as an MCP tool.

        Tool name, description, and input schema are derived by introspecting
        the function signature and docstring.
        """
        def decorator(func: Callable) -> Callable:
            schema = build_tool_schema(func)
            self._tools[schema["name"]] = schema
            self._handlers[schema["name"]] = func
            return func
        return decorator

    # ── Transport ───────────────────────────────────────────────────────

    def run(self, transport: str = "stdio") -> None:
        """Run the server. Only stdio transport is supported."""
        if transport != "stdio":
            raise ValueError(f"Unsupported transport: {transport!r}")
        self._run_stdio()

    def _run_stdio(self) -> None:
        """Read NDJSON from stdin, write NDJSON to stdout."""
        stdin = sys.stdin
        stdout = sys.stdout

        for raw_line in stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as e:
                self._write(stdout, self._error(None, -32700, f"Parse error: {e}"))
                continue

            response = self._dispatch(message)
            if response is not None:
                self._write(stdout, response)

    @staticmethod
    def _write(stream, message: dict[str, Any]) -> None:
        stream.write(json.dumps(message, ensure_ascii=False) + "\n")
        stream.flush()

    # ── JSON-RPC dispatch ───────────────────────────────────────────────

    def _dispatch(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Route an incoming JSON-RPC message to the right handler.

        Returns a response dict (for requests) or None (for notifications).
        """
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}

        # Notifications have no id; we must not respond.
        is_notification = msg_id is None

        try:
            if method == "initialize":
                result = self._handle_initialize(params)
            elif method == "notifications/initialized":
                self._initialized = True
                return None
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = self._handle_tools_list(params)
            elif method == "tools/call":
                result = self._handle_tools_call(params)
            elif method == "prompts/list":
                result = {"prompts": []}
            elif method == "resources/list":
                result = {"resources": []}
            elif method and method.startswith("notifications/"):
                return None
            else:
                if is_notification:
                    return None
                return self._error(msg_id, -32601, f"Method not found: {method}")
        except Exception as e:
            if is_notification:
                return None
            return self._error(msg_id, -32603, f"Internal error: {e}", data={
                "traceback": traceback.format_exc(),
            })

        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    # ── Handlers ────────────────────────────────────────────────────────

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        # Honor the client's protocol version if it looks like one we know.
        requested = params.get("protocolVersion") or PROTOCOL_VERSION
        return {
            "protocolVersion": requested,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": self._name,
                "version": self._version,
            },
        }

    def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"tools": list(self._tools.values())}

    def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = self._handlers.get(name)
        if handler is None:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                "isError": True,
            }
        try:
            # Filter kwargs to those the handler declares.
            sig = inspect.signature(handler)
            valid_keys = set(sig.parameters.keys())
            filtered = {k: v for k, v in arguments.items() if k in valid_keys}
            result = handler(**filtered)
        except Exception as e:
            return {
                "content": [{"type": "text", "text": f"Error: {e}\n{traceback.format_exc()}"}],
                "isError": True,
            }

        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        }

    # ── Errors ──────────────────────────────────────────────────────────

    @staticmethod
    def _error(msg_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        err: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": msg_id, "error": err}
