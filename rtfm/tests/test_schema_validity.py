"""Sanity tests for the published rtfm-mapping-v1 JSON Schema.

These tests guard the contract between RTFM and any project shipping a
declarative mapping (NotebookLM, Linear export, etc.). They run if the
``jsonschema`` package is importable; otherwise the file's checks are
skipped as a soft dependency.
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

try:
    from jsonschema import Draft202012Validator
    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_SCHEMA = REPO_ROOT / "schemas" / "rtfm-mapping-v1.json"
PUBLISHED_URL = "https://schemas.roomi-fields.com/rtfm-mapping-v1.json"


@pytest.fixture(scope="module")
def local_schema() -> dict:
    return json.loads(LOCAL_SCHEMA.read_text(encoding="utf-8"))


@pytest.mark.skipif(not _HAS_JSONSCHEMA, reason="jsonschema not installed")
class TestSchemaValidity:
    def test_local_schema_is_valid_draft2020(self, local_schema):
        """The schema file itself must be a valid JSON Schema draft 2020-12."""
        Draft202012Validator.check_schema(local_schema)

    def test_id_is_canonical_url(self, local_schema):
        """$id must match the URL where the schema is hosted."""
        assert local_schema["$id"] == PUBLISHED_URL

    def test_minimal_mapping_validates(self, local_schema):
        """A minimal but complete mapping passes."""
        mapping = {
            "name": "minimal",
            "match": {"discriminator": {"type": "thing"}},
            "chunks": [{"content": "{{ value }}"}],
        }
        errors = list(Draft202012Validator(local_schema).iter_errors(mapping))
        assert errors == []

    def test_full_mapping_with_self_schema_validates(self, local_schema):
        """The doc's NBLM example, including the optional $schema self-reference."""
        mapping = {
            "$schema": PUBLISHED_URL,
            "name": "nblm-answer-v1",
            "match": {
                "schema_url": "https://schemas.roomi-fields.com/nblm-answer-v1.json",
                "discriminator": {"type": "nblm-answer"},
            },
            "chunks": [
                {
                    "title": "Q: {{ question }}",
                    "content": "{{ answer.text }}",
                    "metadata": {"notebook_id": "{{ notebook.id }}"},
                },
                {
                    "foreach": "citations",
                    "title": "{{ marker }} {{ source_name }}",
                    "content": "{{ source_text }}",
                    "metadata": {"source_name": "{{ source_name }}"},
                },
            ],
            "edges": [
                {
                    "relation": "cites",
                    "foreach": "citations",
                    "target": "{{ source_name }}",
                    "target_kind": "literal",
                }
            ],
        }
        errors = list(Draft202012Validator(local_schema).iter_errors(mapping))
        assert errors == [], [e.message for e in errors]

    def test_missing_match_is_rejected(self, local_schema):
        bad = {"name": "x", "chunks": [{"content": "x"}]}
        errors = list(Draft202012Validator(local_schema).iter_errors(bad))
        assert any("match" in e.message for e in errors)

    def test_empty_chunks_is_rejected(self, local_schema):
        bad = {
            "name": "x",
            "match": {"discriminator": {"a": 1}},
            "chunks": [],
        }
        errors = list(Draft202012Validator(local_schema).iter_errors(bad))
        assert errors, "empty chunks should be rejected"

    def test_match_with_neither_schema_url_nor_discriminator_rejected(self, local_schema):
        bad = {
            "name": "x",
            "match": {},
            "chunks": [{"content": "x"}],
        }
        errors = list(Draft202012Validator(local_schema).iter_errors(bad))
        assert errors, "match must declare schema_url or discriminator"

    def test_unknown_top_level_field_rejected(self, local_schema):
        bad = {
            "name": "x",
            "match": {"discriminator": {"a": 1}},
            "chunks": [{"content": "x"}],
            "totally_made_up_field": True,
        }
        errors = list(Draft202012Validator(local_schema).iter_errors(bad))
        assert errors, "additionalProperties: false should reject unknown fields"

    def test_invalid_target_kind_rejected(self, local_schema):
        bad = {
            "name": "x",
            "match": {"discriminator": {"a": 1}},
            "chunks": [{"content": "x"}],
            "edges": [{"relation": "r", "target": "t", "target_kind": "not-an-enum-value"}],
        }
        errors = list(Draft202012Validator(local_schema).iter_errors(bad))
        assert errors, "target_kind enum should be enforced"


@pytest.mark.skipif(not _HAS_JSONSCHEMA, reason="jsonschema not installed")
@pytest.mark.network
class TestPublishedSchemaIsCurrent:
    """Drift check between the local file and what's served at the canonical URL.

    Marked ``network`` so CI can skip it (`pytest -m 'not network'`). Fails
    intentionally when the local schema has been updated but the public CDN
    still serves an older version — a release-readiness signal.
    """

    def test_published_matches_local(self, local_schema):
        try:
            with urllib.request.urlopen(PUBLISHED_URL, timeout=10) as resp:
                published = json.loads(resp.read())
        except (urllib.error.URLError, OSError) as exc:
            pytest.skip(f"could not reach {PUBLISHED_URL}: {exc}")
        assert published == local_schema, (
            "Local schema differs from published version. "
            "Re-deploy schemas.roomi-fields.com/rtfm-mapping-v1.json."
        )
