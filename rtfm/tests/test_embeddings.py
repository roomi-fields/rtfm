"""Tests for embeddings and semantic search."""

import pytest
import numpy as np

# Skip all tests if fastembed not installed
pytest.importorskip("fastembed")


class TestEmbeddingsModule:
    """Tests for the embeddings module."""

    def test_embed_text(self):
        """Test embedding a single text."""
        from rtfm.core.embeddings import embed_text

        embedding = embed_text("Hello world")
        assert isinstance(embedding, np.ndarray)
        assert embedding.shape == (384,)  # MiniLM dimension
        assert np.isclose(np.linalg.norm(embedding), 1.0, atol=0.01)  # Normalized

    def test_embed_texts_batch(self):
        """Test embedding multiple texts."""
        from rtfm.core.embeddings import embed_texts

        texts = ["Hello world", "Bonjour le monde", "Hola mundo"]
        embeddings = embed_texts(texts)

        assert embeddings.shape == (3, 384)

    def test_embedding_serialization(self):
        """Test converting embeddings to/from bytes."""
        from rtfm.core.embeddings import (
            embed_text, embedding_to_bytes, bytes_to_embedding
        )

        original = embed_text("Test text")
        as_bytes = embedding_to_bytes(original)
        restored = bytes_to_embedding(as_bytes)

        assert np.allclose(original, restored)

    def test_cosine_similarity(self):
        """Test cosine similarity calculation."""
        from rtfm.core.embeddings import embed_text, cosine_similarity

        emb1 = embed_text("The cat sat on the mat")
        emb2 = embed_text("A cat is sitting on a rug")
        emb3 = embed_text("Quantum physics equations")

        sim_similar = cosine_similarity(emb1, emb2)
        sim_different = cosine_similarity(emb1, emb3)

        # Similar texts should have higher similarity
        assert sim_similar > sim_different
        assert sim_similar > 0.5  # Should be reasonably similar

    def test_cosine_similarity_batch(self):
        """Test batch cosine similarity."""
        from rtfm.core.embeddings import (
            embed_text, embed_texts, cosine_similarity_batch
        )

        query = embed_text("cat")
        docs = embed_texts(["cat", "dog", "quantum physics"])
        similarities = cosine_similarity_batch(query, docs)

        assert len(similarities) == 3
        assert similarities[0] > similarities[2]  # "cat" more similar to "cat" than "quantum physics"


class TestLibraryEmbeddings:
    """Tests for Library embedding methods."""

    def test_generate_embeddings(self, library, sample_cgi_xml):
        """Test generating embeddings for chunks."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        stats = library.generate_embeddings(show_progress=False)
        assert stats["embedded"] > 0

    def test_get_embedding_stats(self, library, sample_cgi_xml):
        """Test getting embedding statistics."""
        library.ingest(sample_cgi_xml, corpus="cgi")
        library.generate_embeddings(show_progress=False)

        stats = library.get_embedding_stats()
        assert stats["total_chunks"] > 0
        assert stats["embedded"] > 0
        assert "coverage" in stats

    def test_semantic_search(self, library, sample_cgi_xml):
        """Test semantic search."""
        library.ingest(sample_cgi_xml, corpus="cgi")
        library.generate_embeddings(show_progress=False)

        results = library.semantic_search("impôt fiscal")
        assert len(results) > 0
        assert results[0].score > 0

    def test_hybrid_search(self, library, sample_cgi_xml):
        """Test hybrid search."""
        library.ingest(sample_cgi_xml, corpus="cgi")
        library.generate_embeddings(show_progress=False)

        results = library.hybrid_search("impôt")
        assert len(results) > 0

    def test_semantic_search_empty_corpus(self, library):
        """Test semantic search with no embeddings."""
        results = library.semantic_search("test query")
        assert len(results) == 0

    def test_generate_embeddings_idempotent(self, library, sample_cgi_xml):
        """Test that embeddings are not regenerated if they exist."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        stats1 = library.generate_embeddings(show_progress=False)
        stats2 = library.generate_embeddings(show_progress=False)

        assert stats1["embedded"] > 0
        assert stats2["embedded"] == 0  # Already embedded

    def test_generate_embeddings_force(self, library, sample_cgi_xml):
        """Test force regenerating embeddings."""
        library.ingest(sample_cgi_xml, corpus="cgi")

        stats1 = library.generate_embeddings(show_progress=False)
        stats2 = library.generate_embeddings(show_progress=False, force=True)

        assert stats1["embedded"] == stats2["embedded"]
