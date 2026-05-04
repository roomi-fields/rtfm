"""Apply a Mapping to JSON data → chunks + edge candidates."""

import hashlib
from pathlib import Path
from typing import Iterator

from rtfm.core.models import Chunk, EdgeCandidate
from rtfm.parsers.mappings.base import Mapping
from rtfm.parsers.mappings.template import render, resolve_path


def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def _render_metadata(spec_metadata: dict, ctx) -> dict:
    """Render template strings in metadata values. Non-string values pass through."""
    out = {}
    for key, value in spec_metadata.items():
        if isinstance(value, str):
            out[key] = render(value, ctx)
        else:
            out[key] = value
    return out


def apply_chunks(
    mapping: Mapping,
    data: dict,
    path: Path,
    book_slug: str,
    book_title: str,
) -> Iterator[Chunk]:
    """Yield chunks declared by ``mapping`` against ``data``."""
    idx = 0
    for spec in mapping.chunks:
        if spec.foreach:
            items = resolve_path(data, spec.foreach)
            if not isinstance(items, list):
                continue
            for item in items:
                ctx = item if isinstance(item, dict) else {"value": item}
                idx += 1
                chunk = _build_chunk(spec, ctx, idx, path, book_slug, book_title)
                if chunk is not None:
                    yield chunk
        else:
            idx += 1
            chunk = _build_chunk(spec, data, idx, path, book_slug, book_title)
            if chunk is not None:
                yield chunk


def _build_chunk(spec, ctx, idx, path, book_slug, book_title):
    content = render(spec.content, ctx) if spec.content else ""
    if not content.strip():
        return None
    title = render(spec.title, ctx) if spec.title else ""
    metadata = _render_metadata(spec.metadata, ctx)
    return Chunk(
        id=f"{book_slug}-{idx:04d}",
        content=content,
        book_title=book_title,
        book_slug=book_slug,
        book_file=str(path),
        chapter_title=title,
        chapter_num=idx,
        page_start=1,
        page_end=1,
        paragraph=1,
        content_chars=len(content),
        content_hash=_hash(content),
        metadata=metadata,
    )


def apply_edges(mapping: Mapping, data: dict, source_file: str) -> list[EdgeCandidate]:
    """Return edge candidates declared by ``mapping`` against ``data``."""
    edges: list[EdgeCandidate] = []
    for spec in mapping.edges:
        if spec.foreach:
            items = resolve_path(data, spec.foreach)
            if not isinstance(items, list):
                continue
            for item in items:
                ctx = item if isinstance(item, dict) else {"value": item}
                target = render(spec.target, ctx)
                if target:
                    edges.append(EdgeCandidate(
                        source_file=source_file,
                        target_ref=target,
                        relation_type=spec.relation,
                        source_detail=spec.target_kind,
                    ))
        else:
            target = render(spec.target, data)
            if target:
                edges.append(EdgeCandidate(
                    source_file=source_file,
                    target_ref=target,
                    relation_type=spec.relation,
                    source_detail=spec.target_kind,
                ))
    return edges
