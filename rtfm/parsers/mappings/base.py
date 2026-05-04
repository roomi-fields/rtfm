"""Data model for JSON schema mappings."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MatchSpec:
    """How to detect that a JSON document matches this mapping.

    A mapping matches when *any* declared rule matches:
    - ``schema_url`` matches the document's ``$schema`` or ``$id``
    - ``discriminator`` is a dict of ``{field_path: expected_value}`` — all must match
    """

    schema_url: Optional[str] = None
    discriminator: Optional[dict] = None


@dataclass
class ChunkSpec:
    """Declarative chunk extraction.

    - If ``foreach`` is set, it must resolve to a list; one chunk per item.
      Templates inside the spec are then evaluated against each item.
    - Otherwise, a single chunk is produced and templates evaluate against the
      root document.
    """

    title: str = ""
    content: str = ""
    foreach: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class EdgeSpec:
    """Declarative edge extraction.

    - ``relation``: stored as ``relation_type`` in the edges table.
    - ``foreach``: optional path to a list, one edge per item.
    - ``target``: template producing the target reference (slug, name, URL).
    """

    relation: str
    foreach: Optional[str] = None
    target: str = ""
    target_kind: str = "literal"  # "literal" | "slug" | "url" — informational


@dataclass
class Mapping:
    """A user-defined mapping from a JSON schema to chunks and edges."""

    name: str
    match: MatchSpec
    chunks: list[ChunkSpec] = field(default_factory=list)
    edges: list[EdgeSpec] = field(default_factory=list)

    def matches(self, data: dict) -> bool:
        """Return True if this mapping should be applied to ``data``."""
        if not isinstance(data, dict):
            return False

        if self.match.schema_url:
            actual = data.get("$schema") or data.get("$id")
            if actual == self.match.schema_url:
                return True

        if self.match.discriminator:
            for path, expected in self.match.discriminator.items():
                if _resolve(data, path) != expected:
                    return False
            return True

        return False


def _resolve(data, path: str):
    """Walk a dotted path through nested dicts/lists. Local helper to avoid
    circular import with ``template.py``."""
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
