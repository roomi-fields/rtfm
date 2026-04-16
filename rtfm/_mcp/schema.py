"""Convert Python function signatures to MCP tool schemas.

Introspects type hints and Google-style docstrings to produce:
- JSON Schema for the `inputSchema` field
- Tool description from the docstring summary
- Per-parameter descriptions from the `Args:` section
"""

from __future__ import annotations

import inspect
import re
import types
import typing
from typing import Any, Callable, get_args, get_origin


_PRIMITIVE_TYPES: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _annotation_to_schema(annotation: Any) -> tuple[dict[str, Any], bool]:
    """Convert a Python type annotation to a JSON Schema fragment.

    Returns (schema_dict, is_nullable). `is_nullable` is True when the type
    is `X | None` / `Optional[X]`, indicating the parameter can be omitted.
    """
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {"type": "string"}, True

    origin = get_origin(annotation)

    # Handle `X | None` (PEP 604) and Optional[X]
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        nullable = len(args) != len(get_args(annotation))
        if len(args) == 1:
            inner, _ = _annotation_to_schema(args[0])
            return inner, nullable
        # Multi-type union: fall back to string
        return {"type": "string"}, nullable

    # Handle list[X] / List[X]
    if origin in (list, typing.List):
        args = get_args(annotation)
        if args:
            item_schema, _ = _annotation_to_schema(args[0])
            return {"type": "array", "items": item_schema}, False
        return {"type": "array"}, False

    # Handle dict[K, V]
    if origin in (dict, typing.Dict):
        return {"type": "object"}, False

    # Primitive types
    if annotation in _PRIMITIVE_TYPES:
        return {"type": _PRIMITIVE_TYPES[annotation]}, False

    # Unknown → string
    return {"type": "string"}, False


def _parse_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """Parse a Google-style docstring.

    Returns (description, {param_name: description, ...}).
    The description is the text before the first "Args:"/"Returns:"/"Raises:".
    """
    if not doc:
        return "", {}

    # Strip common leading whitespace
    doc = inspect.cleandoc(doc)

    # Split into description and sections
    section_split = re.split(
        r"^\s*(Args|Arguments|Parameters|Returns|Raises|Yields|Note|Notes|Examples?):\s*$",
        doc,
        maxsplit=0,
        flags=re.MULTILINE,
    )

    description = section_split[0].strip()
    param_descriptions: dict[str, str] = {}

    # section_split alternates: [text, section_name, content, section_name, content, ...]
    for i in range(1, len(section_split) - 1, 2):
        section_name = section_split[i]
        section_content = section_split[i + 1]
        if section_name in ("Args", "Arguments", "Parameters"):
            param_descriptions.update(_parse_args_section(section_content))

    return description, param_descriptions


def _parse_args_section(content: str) -> dict[str, str]:
    """Parse Google-style Args section: `name: description`, continuations indented."""
    result: dict[str, str] = {}
    current_name: str | None = None
    current_lines: list[str] = []

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Match "name: description" or "name (type): description"
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?:\([^)]*\))?\s*:\s*(.*)$", stripped)
        # Only treat as a new param if the line is not deeply indented
        leading = len(line) - len(line.lstrip())
        if m and leading <= 4:
            if current_name is not None:
                result[current_name] = " ".join(current_lines).strip()
            current_name = m.group(1)
            current_lines = [m.group(2)] if m.group(2) else []
        elif current_name is not None:
            current_lines.append(stripped)

    if current_name is not None:
        result[current_name] = " ".join(current_lines).strip()

    return result


def build_tool_schema(func: Callable) -> dict[str, Any]:
    """Introspect a function and produce a full MCP tool definition.

    Returns a dict with keys: name, description, inputSchema.
    """
    description, param_descriptions = _parse_docstring(func.__doc__)
    signature = inspect.signature(func)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in signature.parameters.items():
        if name in ("self", "cls"):
            continue
        prop_schema, nullable = _annotation_to_schema(param.annotation)
        if name in param_descriptions:
            prop_schema["description"] = param_descriptions[name]
        properties[name] = prop_schema

        # A parameter is required unless it has a default or is nullable
        if param.default is inspect.Parameter.empty and not nullable:
            required.append(name)

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        input_schema["required"] = required

    return {
        "name": func.__name__,
        "description": description,
        "inputSchema": input_schema,
    }
