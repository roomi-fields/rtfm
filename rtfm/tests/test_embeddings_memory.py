"""The model sees passages a few at a time.

Its runtime sizes working memory on the largest batch it has seen and keeps
it. Every job sent all its passages — up to 64 — at once, twelve lanes share
the model, and the indexer held 4.3 GB it never gave back.
"""
from __future__ import annotations


import pytest

from rtfm.core import embeddings


def test_no_batch_larger_than_the_cap_reaches_the_model(monkeypatch):
    np = pytest.importorskip("numpy")
    seen = []

    class FakeModel:
        def embed(self, texts, batch_size):
            seen.append(batch_size)
            return [np.ones(4, dtype=np.float32) for _ in texts]

    monkeypatch.setattr(embeddings, "get_model", lambda name=None: FakeModel())
    out = embeddings.embed_texts(["x"] * 64, batch_size=64)
    assert out.shape == (64, 4)
    assert seen == [embeddings.INFERENCE_BATCH_MAX]


def test_the_index_path_does_not_ask_for_one_big_batch():
    from pathlib import Path
    src = (Path(embeddings.__file__).parent / "library.py").read_text(encoding="utf-8")
    assert "batch_size=len(texts)" not in src
