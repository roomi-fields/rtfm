"""Generic JSON schema mappings.

Lets users declaratively map any JSON schema to chunks and edges, without
writing Python parsers. Mappings are loaded from ``.rtfm/mappings/*.{yaml,yml,json}``.

Public API:
    - ``MappingRegistry`` — global registry queried by ``json_parser``
    - ``load_mappings_from_dir(path)`` — scans a directory and registers mappings
    - ``Mapping``, ``ChunkSpec``, ``EdgeSpec``, ``MatchSpec`` — data model
"""

from rtfm.parsers.mappings.base import (
    ChunkSpec,
    EdgeSpec,
    Mapping,
    MatchSpec,
)
from rtfm.parsers.mappings.registry import (
    MappingRegistry,
    load_mapping_file,
    load_mappings_from_dir,
)

__all__ = [
    "ChunkSpec",
    "EdgeSpec",
    "Mapping",
    "MappingRegistry",
    "MatchSpec",
    "load_mapping_file",
    "load_mappings_from_dir",
]
