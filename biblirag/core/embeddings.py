"""Embeddings support for semantic search."""

import struct
from typing import Optional, List
import numpy as np

# Default model
DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384  # Dimension for MiniLM models

# Lazy-loaded model
_model = None
_model_name = None


def get_model(model_name: str = DEFAULT_MODEL):
    """Get or load the sentence transformer model."""
    global _model, _model_name

    if _model is None or _model_name != model_name:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(model_name)
            _model_name = model_name
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for embeddings. "
                "Install with: pip install sentence-transformers"
            )

    return _model


def embed_text(text: str, model_name: str = DEFAULT_MODEL) -> np.ndarray:
    """Generate embedding for a single text."""
    model = get_model(model_name)
    return model.encode(text, normalize_embeddings=True)


def embed_texts(texts: List[str], model_name: str = DEFAULT_MODEL,
                batch_size: int = 32, show_progress: bool = False) -> np.ndarray:
    """Generate embeddings for multiple texts."""
    model = get_model(model_name)
    return model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=batch_size,
        show_progress_bar=show_progress
    )


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
