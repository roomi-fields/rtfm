"""Where the embedding model lives, and what a missing one says.

FastEmbed, left to itself, keeps the model in the system's temporary
directory. A reboot empties it and a container recreate drops it: the
~85 MB model came down again every time, and an embed job that ran after the
wipe failed with an ONNX "no such file" naming neither the cache nor a fix
(issue #7). Search kept answering, lexically only, so nobody noticed.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from rtfm.core import embeddings


@pytest.fixture
def fake_fastembed(monkeypatch):
    """A stand-in for FastEmbed that records how it was built."""
    calls = []

    class TextEmbedding:
        error: Exception | None = None

        def __init__(self, **kwargs):
            calls.append(kwargs)
            if TextEmbedding.error:
                raise TextEmbedding.error

    module = types.ModuleType("fastembed")
    module.TextEmbedding = TextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", module)
    monkeypatch.setattr(embeddings, "_model", None)
    monkeypatch.setattr(embeddings, "_model_name", None)
    return TextEmbedding, calls


def test_the_default_is_a_directory_that_survives_a_reboot(monkeypatch):
    monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    assert embeddings.model_cache_dir() == Path.home() / ".cache" / "fastembed"


def test_the_variable_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path))
    assert embeddings.model_cache_dir() == tmp_path


def test_the_model_is_loaded_from_that_directory(fake_fastembed, monkeypatch,
                                                 tmp_path):
    _, calls = fake_fastembed
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path))
    embeddings.get_model()
    assert calls[0]["cache_dir"] == str(tmp_path), (
        "without cache_dir FastEmbed falls back to the temporary directory")


def test_a_wiped_cache_says_what_happened(fake_fastembed, monkeypatch,
                                          tmp_path):
    cls, _ = fake_fastembed
    cls.error = RuntimeError("[ONNXRuntimeError] : 3 : NO_SUCHFILE : "
                             "Load model from /tmp/fastembed_cache/... failed")
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path))
    with pytest.raises(RuntimeError) as err:
        embeddings.get_model()
    assert str(tmp_path) in str(err.value)
    assert "FASTEMBED_CACHE_PATH" in str(err.value)


def test_other_failures_are_not_rewritten(fake_fastembed):
    cls, _ = fake_fastembed
    cls.error = ValueError("Model foo is not supported")
    with pytest.raises(ValueError, match="not supported"):
        embeddings.get_model()
