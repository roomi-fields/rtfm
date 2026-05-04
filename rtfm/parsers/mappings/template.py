"""Minimal templating for mapping expressions.

Supports only ``{{ dotted.path.to.field }}`` substitution. No control flow,
no eval, no imports. Missing paths render as empty strings.

This is deliberately tiny — we don't want a Jinja2 dep just for this.
"""

import re
from typing import Any

_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_$][\w.$]*)\s*\}\}")


def resolve_path(data: Any, path: str) -> Any:
    """Walk a dotted path through nested dicts/lists.

    Numeric segments index into lists. Returns ``None`` if any segment is
    missing or hits an unsupported type.
    """
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if cur is None:
            return None
    return cur


def render(template: str, data: Any) -> str:
    """Replace ``{{ path }}`` placeholders with stringified values from ``data``.

    Plain strings without placeholders are returned unchanged. Non-string
    values resolved by paths are coerced via ``str()``. Missing paths render
    as empty strings.
    """
    if not template:
        return ""

    def _sub(match: re.Match) -> str:
        val = resolve_path(data, match.group(1))
        if val is None:
            return ""
        return str(val)

    return _PATTERN.sub(_sub, template)
