"""Embeddings support for semantic search."""

import struct
from typing import Optional, List
import numpy as np

# Default model (FastEmbed format)
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384  # Dimension for MiniLM models

# Lazy-loaded model
_model = None
_model_name = None


def get_model(model_name: str = DEFAULT_MODEL):
    """Get or load the FastEmbed text embedding model."""
    global _model, _model_name

    if _model is None or _model_name != model_name:
        try:
            from fastembed import TextEmbedding
            _model = TextEmbedding(model_name=model_name)
            _model_name = model_name
        except ImportError:
            raise ImportError(
                "\n\n  ❌ Semantic search requires the embeddings extra.\n"
                "     Install with:  pip install rtfm-ai[embeddings]\n"
                "     (~85 MB ONNX model, no GPU needed)\n"
            )

    return _model


def _normalize(v: np.ndarray) -> np.ndarray:
    """L2-normalize embeddings so dot product = cosine similarity."""
    norm = np.linalg.norm(v, axis=-1, keepdims=True)
    norm = np.where(norm == 0, 1, norm)
    return v / norm


def embed_text(text: str, model_name: str = DEFAULT_MODEL) -> np.ndarray:
    """Generate embedding for a single text."""
    model = get_model(model_name)
    embeddings = list(model.embed([text]))
    vec = np.array(embeddings[0], dtype=np.float32)
    return _normalize(vec)


def embed_texts(texts: List[str], model_name: str = DEFAULT_MODEL,
                batch_size: int = 32, show_progress: bool = False) -> np.ndarray:
    """Generate embeddings for multiple texts."""
    model = get_model(model_name)
    embeddings = list(model.embed(texts, batch_size=batch_size))
    arr = np.array(embeddings, dtype=np.float32)
    return _normalize(arr)


def embedding_to_bytes(embedding: np.ndarray) -> bytes:
    """Convert numpy embedding to bytes for SQLite storage."""
    return embedding.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """Convert bytes from SQLite back to numpy embedding."""
    return np.frombuffer(data, dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two embeddings."""
    # If embeddings are normalized, dot product = cosine similarity
    return float(np.dot(a, b))


def cosine_similarity_batch(query: np.ndarray, embeddings: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between query and multiple embeddings."""
    # query: (dim,), embeddings: (n, dim)
    # If normalized, dot product = cosine similarity
    return np.dot(embeddings, query)
