"""Tests for the generic JSON schema mapping system."""

import json
from pathlib import Path

import pytest

from rtfm.parsers.json_parser import JSONParser
from rtfm.parsers.mappings import (
    ChunkSpec,
    EdgeSpec,
    Mapping,
    MappingRegistry,
    MatchSpec,
    load_mapping_file,
    load_mappings_from_dir,
)
from rtfm.parsers.mappings.apply import apply_chunks, apply_edges
from rtfm.parsers.mappings.template import render, resolve_path


@pytest.fixture(autouse=True)
def _clean_registry():
    MappingRegistry.clear()
    yield
    MappingRegistry.clear()


# ---- template engine ----


class TestTemplate:
    def test_resolve_simple(self):
        assert resolve_path({"a": 1}, "a") == 1

    def test_resolve_nested(self):
        assert resolve_path({"a": {"b": {"c": 42}}}, "a.b.c") == 42

    def test_resolve_list_index(self):
        assert resolve_path({"xs": [10, 20, 30]}, "xs.1") == 20

    def test_resolve_missing_returns_none(self):
        assert resolve_path({"a": 1}, "b") is None
        assert resolve_path({"a": 1}, "a.b.c") is None

    def test_render_substitutes(self):
        assert render("hello {{ name }}", {"name": "world"}) == "hello world"

    def test_render_nested(self):
        assert render("{{ a.b }}", {"a": {"b": "X"}}) == "X"

    def test_render_missing_path_empty(self):
        assert render("X={{ missing }}", {}) == "X="

    def test_render_passthrough_no_template(self):
        assert render("plain text", {}) == "plain text"

    def test_render_multiple_substitutions(self):
        out = render("{{ a }} + {{ b }} = {{ c }}", {"a": 1, "b": 2, "c": 3})
        assert out == "1 + 2 = 3"


# ---- match logic ----


class TestMatching:
    def test_match_by_schema_url(self):
        m = Mapping(
            name="t",
            match=MatchSpec(schema_url="https://example.com/s.json"),
            chunks=[],
        )
        assert m.matches({"$schema": "https://example.com/s.json"}) is True
        assert m.matches({"$schema": "other"}) is False
        assert m.matches({}) is False

    def test_match_by_schema_id_fallback(self):
        m = Mapping(
            name="t",
            match=MatchSpec(schema_url="https://example.com/s.json"),
            chunks=[],
        )
        assert m.matches({"$id": "https://example.com/s.json"}) is True

    def test_match_by_discriminator(self):
        m = Mapping(
            name="t",
            match=MatchSpec(discriminator={"type": "thing"}),
            chunks=[],
        )
        assert m.matches({"type": "thing"}) is True
        assert m.matches({"type": "other"}) is False
        assert m.matches({}) is False

    def test_match_by_nested_discriminator(self):
        m = Mapping(
            name="t",
            match=MatchSpec(discriminator={"meta.kind": "x"}),
            chunks=[],
        )
        assert m.matches({"meta": {"kind": "x"}}) is True
        assert m.matches({"meta": {"kind": "y"}}) is False

    def test_match_multiple_discriminator_fields(self):
        m = Mapping(
            name="t",
            match=MatchSpec(discriminator={"type": "a", "version": "1"}),
            chunks=[],
        )
        assert m.matches({"type": "a", "version": "1"}) is True
        assert m.matches({"type": "a", "version": "2"}) is False

    def test_no_match_rule_means_no_match(self):
        m = Mapping(name="t", match=MatchSpec(), chunks=[])
        assert m.matches({"anything": "here"}) is False


# ---- registry ----


class TestRegistry:
    def test_register_and_find(self):
        m = Mapping(name="x", match=MatchSpec(discriminator={"k": "v"}), chunks=[])
        MappingRegistry.register(m)
        assert MappingRegistry.find_mapping({"k": "v"}) is m
        assert MappingRegistry.find_mapping({"k": "other"}) is None

    def test_register_replaces_by_name(self):
        m1 = Mapping(name="x", match=MatchSpec(discriminator={"k": "v1"}), chunks=[])
        m2 = Mapping(name="x", match=MatchSpec(discriminator={"k": "v2"}), chunks=[])
        MappingRegistry.register(m1)
        MappingRegistry.register(m2)
        assert len(MappingRegistry.all()) == 1
        assert MappingRegistry.find_mapping({"k": "v2"}) is m2

    def test_find_returns_none_for_non_dict(self):
        MappingRegistry.register(
            Mapping(name="x", match=MatchSpec(discriminator={"k": "v"}), chunks=[])
        )
        assert MappingRegistry.find_mapping([1, 2]) is None
        assert MappingRegistry.find_mapping("string") is None
        assert MappingRegistry.find_mapping(None) is None


# ---- file loading ----


class TestLoading:
    def test_load_yaml_file(self, tmp_path):
        f = tmp_path / "m.yaml"
        f.write_text(
            "name: nblm\n"
            "match:\n"
            "  discriminator: { type: nblm-answer }\n"
            "chunks:\n"
            "  - title: 'Answer'\n"
            "    content: '{{ answer.text }}'\n",
            encoding="utf-8",
        )
        m = load_mapping_file(f)
        assert m is not None
        assert m.name == "nblm"
        assert m.match.discriminator == {"type": "nblm-answer"}
        assert len(m.chunks) == 1
        assert m.chunks[0].title == "Answer"

    def test_load_json_file(self, tmp_path):
        f = tmp_path / "m.json"
        f.write_text(json.dumps({
            "name": "x",
            "match": {"schema_url": "https://x.com/s.json"},
            "chunks": [{"title": "t", "content": "c"}],
        }), encoding="utf-8")
        m = load_mapping_file(f)
        assert m is not None
        assert m.match.schema_url == "https://x.com/s.json"

    def test_load_dir_skips_unknown_extensions(self, tmp_path):
        (tmp_path / "good.yaml").write_text(
            "name: a\nmatch: { discriminator: { x: 1 } }\nchunks: []\n",
            encoding="utf-8",
        )
        (tmp_path / "ignored.txt").write_text("noise", encoding="utf-8")
        n = load_mappings_from_dir(tmp_path)
        assert n == 1

    def test_load_dir_skips_malformed_files(self, tmp_path):
        (tmp_path / "good.yaml").write_text(
            "name: a\nmatch: { discriminator: { x: 1 } }\nchunks: []\n",
            encoding="utf-8",
        )
        (tmp_path / "broken.yaml").write_text(": : :\n[invalid", encoding="utf-8")
        n = load_mappings_from_dir(tmp_path)
        assert n == 1

    def test_load_dir_missing_returns_zero(self, tmp_path):
        assert load_mappings_from_dir(tmp_path / "nonexistent") == 0


# ---- apply: chunks + edges ----


class TestApplyChunks:
    def test_simple_root_chunk(self, tmp_path):
        m = Mapping(
            name="t",
            match=MatchSpec(discriminator={"type": "x"}),
            chunks=[ChunkSpec(title="T", content="hello {{ name }}")],
        )
        chunks = list(apply_chunks(m, {"name": "world"}, tmp_path / "f.json", "slug", "title"))
        assert len(chunks) == 1
        assert chunks[0].content == "hello world"
        assert chunks[0].chapter_title == "T"
        assert chunks[0].book_slug == "slug"

    def test_foreach_emits_one_per_item(self, tmp_path):
        m = Mapping(
            name="t",
            match=MatchSpec(discriminator={}),
            chunks=[ChunkSpec(
                title="{{ marker }}",
                content="{{ source_text }}",
                foreach="citations",
                metadata={"source_name": "{{ source_name }}"},
            )],
        )
        data = {
            "citations": [
                {"marker": "[1]", "source_name": "A", "source_text": "alpha"},
                {"marker": "[2]", "source_name": "B", "source_text": "beta"},
            ],
        }
        chunks = list(apply_chunks(m, data, tmp_path / "f.json", "s", "t"))
        assert len(chunks) == 2
        assert chunks[0].content == "alpha"
        assert chunks[0].chapter_title == "[1]"
        assert chunks[0].metadata["source_name"] == "A"
        assert chunks[1].content == "beta"
        assert chunks[1].metadata["source_name"] == "B"

    def test_root_then_foreach(self, tmp_path):
        m = Mapping(
            name="t",
            match=MatchSpec(discriminator={}),
            chunks=[
                ChunkSpec(title="Q", content="{{ question }}"),
                ChunkSpec(title="C", content="{{ x }}", foreach="items"),
            ],
        )
        data = {"question": "Why?", "items": [{"x": "one"}, {"x": "two"}]}
        chunks = list(apply_chunks(m, data, tmp_path / "f.json", "s", "t"))
        assert [c.content for c in chunks] == ["Why?", "one", "two"]

    def test_empty_content_skipped(self, tmp_path):
        m = Mapping(
            name="t",
            match=MatchSpec(discriminator={}),
            chunks=[ChunkSpec(content="{{ missing }}")],
        )
        chunks = list(apply_chunks(m, {}, tmp_path / "f.json", "s", "t"))
        assert chunks == []

    def test_foreach_missing_path_skipped(self, tmp_path):
        m = Mapping(
            name="t",
            match=MatchSpec(discriminator={}),
            chunks=[ChunkSpec(content="{{ x }}", foreach="absent")],
        )
        chunks = list(apply_chunks(m, {}, tmp_path / "f.json", "s", "t"))
        assert chunks == []


class TestApplyEdges:
    def test_foreach_edges(self):
        m = Mapping(
            name="t",
            match=MatchSpec(discriminator={}),
            chunks=[],
            edges=[EdgeSpec(relation="cites", foreach="cites", target="{{ name }}")],
        )
        data = {"cites": [{"name": "A"}, {"name": "B"}]}
        edges = apply_edges(m, data, "/tmp/f.json")
        assert len(edges) == 2
        assert edges[0].relation_type == "cites"
        assert edges[0].target_ref == "A"
        assert edges[1].target_ref == "B"

    def test_root_edge(self):
        m = Mapping(
            name="t",
            match=MatchSpec(discriminator={}),
            chunks=[],
            edges=[EdgeSpec(relation="parent", target="{{ parent_id }}")],
        )
        edges = apply_edges(m, {"parent_id": "X"}, "/tmp/f.json")
        assert len(edges) == 1
        assert edges[0].target_ref == "X"

    def test_empty_target_skipped(self):
        m = Mapping(
            name="t",
            match=MatchSpec(discriminator={}),
            chunks=[],
            edges=[EdgeSpec(relation="r", target="{{ missing }}")],
        )
        edges = apply_edges(m, {}, "/tmp/f.json")
        assert edges == []


# ---- end-to-end via JSONParser ----


class TestJSONParserIntegration:
    def test_unmapped_json_uses_generic_path(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"foo": "bar", "baz": [1, 2, 3]}), encoding="utf-8")
        chunks = list(JSONParser().parse(f))
        assert len(chunks) >= 1
        assert any("foo" in c.content for c in chunks)

    def test_mapped_json_uses_mapping(self, tmp_path):
        MappingRegistry.register(Mapping(
            name="nblm",
            match=MatchSpec(discriminator={"type": "nblm-answer"}),
            chunks=[
                ChunkSpec(title="Answer", content="{{ answer.text }}"),
                ChunkSpec(
                    title="{{ marker }} {{ source_name }}",
                    content="{{ source_text }}",
                    foreach="citations",
                ),
            ],
        ))
        f = tmp_path / "answer.json"
        f.write_text(json.dumps({
            "type": "nblm-answer",
            "answer": {"text": "OSBD is a 4-step framework."},
            "citations": [
                {"marker": "[1]", "source_name": "Keller", "source_text": "Observation neutre"},
                {"marker": "[2]", "source_name": "CNV", "source_text": "Communication bienveillante"},
            ],
        }), encoding="utf-8")
        chunks = list(JSONParser().parse(f))
        assert len(chunks) == 3
        assert chunks[0].chapter_title == "Answer"
        assert chunks[0].content == "OSBD is a 4-step framework."
        assert chunks[1].chapter_title == "[1] Keller"
        assert chunks[1].content == "Observation neutre"
        assert chunks[2].content == "Communication bienveillante"

    def test_mapped_json_extracts_edges(self, tmp_path):
        MappingRegistry.register(Mapping(
            name="nblm",
            match=MatchSpec(discriminator={"type": "nblm-answer"}),
            chunks=[ChunkSpec(content="{{ answer.text }}")],
            edges=[EdgeSpec(relation="cites", foreach="citations", target="{{ source_name }}")],
        ))
        f = tmp_path / "answer.json"
        f.write_text(json.dumps({
            "type": "nblm-answer",
            "answer": {"text": "x"},
            "citations": [{"source_name": "A"}, {"source_name": "B"}],
        }), encoding="utf-8")
        edges = JSONParser().extract_edges(f)
        assert len(edges) == 2
        assert {e.target_ref for e in edges} == {"A", "B"}
        assert all(e.relation_type == "cites" for e in edges)

    def test_unmapped_json_no_edges(self, tmp_path):
        f = tmp_path / "plain.json"
        f.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        assert JSONParser().extract_edges(f) == []
