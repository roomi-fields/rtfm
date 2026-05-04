"""Mapping registry + loader."""

import json
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None

from rtfm.parsers.mappings.base import (
    ChunkSpec,
    EdgeSpec,
    Mapping,
    MatchSpec,
)


class MappingRegistry:
    """Global registry of declarative mappings.

    The JSON parser consults this registry on every parse to dispatch to
    a user-defined mapping when a JSON document matches a known schema.
    """

    _mappings: list[Mapping] = []

    @classmethod
    def register(cls, mapping: Mapping) -> None:
        """Register a mapping. If one with the same name exists, replace it."""
        cls._mappings = [m for m in cls._mappings if m.name != mapping.name]
        cls._mappings.append(mapping)

    @classmethod
    def clear(cls) -> None:
        cls._mappings = []

    @classmethod
    def find_mapping(cls, data) -> Optional[Mapping]:
        if not isinstance(data, dict):
            return None
        for m in cls._mappings:
            if m.matches(data):
                return m
        return None

    @classmethod
    def all(cls) -> list[Mapping]:
        return list(cls._mappings)


def _from_dict(d: dict) -> Optional[Mapping]:
    if not isinstance(d, dict):
        return None

    name = d.get("name") or "unnamed"
    match_d = d.get("match") or {}
    match = MatchSpec(
        schema_url=match_d.get("schema_url"),
        discriminator=match_d.get("discriminator"),
    )

    chunks = []
    for c in d.get("chunks", []) or []:
        if not isinstance(c, dict):
            continue
        chunks.append(ChunkSpec(
            title=c.get("title", ""),
            content=c.get("content", ""),
            foreach=c.get("foreach"),
            metadata=c.get("metadata", {}) or {},
        ))

    edges = []
    for e in d.get("edges", []) or []:
        if not isinstance(e, dict):
            continue
        edges.append(EdgeSpec(
            relation=e.get("relation", "related"),
            foreach=e.get("foreach"),
            target=e.get("target", ""),
            target_kind=e.get("target_kind", "literal"),
        ))

    return Mapping(name=name, match=match, chunks=chunks, edges=edges)


def load_mapping_file(path: Path) -> Optional[Mapping]:
    """Parse a single mapping file (.yaml/.yml/.json).

    Returns ``None`` if the file is missing, malformed, or YAML is requested
    but PyYAML isn't installed (PyYAML is a core dependency, so this is rare).
    """
    if not path.exists() or not path.is_file():
        return None

    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    try:
        if suffix in (".yaml", ".yml"):
            if yaml is None:
                return None
            data = yaml.safe_load(text)
        elif suffix == ".json":
            data = json.loads(text)
        else:
            return None
    except (yaml.YAMLError if yaml else Exception, json.JSONDecodeError, ValueError):
        return None

    return _from_dict(data)


def load_mappings_from_dir(directory: Path) -> int:
    """Load all mappings under ``directory``. Returns the number registered.

    Silently skips malformed files — bad mappings shouldn't break sync.
    """
    if not directory.exists() or not directory.is_dir():
        return 0

    count = 0
    for f in sorted(directory.iterdir()):
        if f.suffix.lower() not in (".yaml", ".yml", ".json"):
            continue
        try:
            mapping = load_mapping_file(f)
        except Exception:
            continue
        if mapping is not None:
            MappingRegistry.register(mapping)
            count += 1

    return count
