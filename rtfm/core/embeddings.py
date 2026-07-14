"""Embeddings support for semantic search."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, List, NamedTuple, Optional, Tuple

# numpy is part of the [embeddings] extra. It's imported lazily inside
# the functions that actually need it, so this module's *metadata*
# helpers (resolve_model, DEFAULT_MODEL, EMBEDDING_MODELS) stay
# importable in a core/dev install without numpy — used by reconcile,
# the queue handlers, etc. ``from __future__ import annotations`` keeps
# the ``np.ndarray`` type hints from being evaluated at import time.
if TYPE_CHECKING:
    import numpy as np


class ModelInfo(NamedTuple):
    """Metadata for a supported FastEmbed model."""
    hf_name: str
    dim: int
    size_mb: int
    languages: str
    query_prefix: Optional[str] = None


# Registry of curated FastEmbed dense text-embedding models.
# Aliases map to the best options across the size/quality curve.
EMBEDDING_MODELS: dict[str, ModelInfo] = {
    "fast": ModelInfo(
        hf_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        dim=384, size_mb=85, languages="multilingual",
        query_prefix=None,
    ),
    "balanced": ModelInfo(
        hf_name="BAAI/bge-base-en-v1.5",
        dim=768, size_mb=210, languages="English",
        query_prefix=None,
    ),
    "quality": ModelInfo(
        hf_name="mixedbread-ai/mxbai-embed-large-v1",
        dim=1024, size_mb=640, languages="English",
        query_prefix="Represent this sentence for searching relevant passages: ",
    ),
}

# Reverse lookup: HF name → alias (for metadata retrieval from full names)
_HF_TO_ALIAS = {info.hf_name: alias for alias, info in EMBEDDING_MODELS.items()}

# Default model — kept small so first `rtfm init` is fast.
DEFAULT_ALIAS = "fast"
DEFAULT_MODEL = EMBEDDING_MODELS[DEFAULT_ALIAS].hf_name
EMBEDDING_DIM = EMBEDDING_MODELS[DEFAULT_ALIAS].dim  # legacy export

SIZE_WARNING_THRESHOLD_MB = 300

# Lazy-loaded model state
_model = None
_model_name: Optional[str] = None


def resolve_model(name_or_alias: str) -> ModelInfo:
    """Resolve an alias (fast/balanced/quality) or full HF name to ModelInfo.

    Unknown HF names are returned with dim/size set to -1 — used as a signal
    that the model is untracked by the registry but still loadable by FastEmbed.

    Also tolerates short HF names — early versions of RTFM stored
    ``paraphrase-multilingual-MiniLM-L12-v2`` in ``chunk_embeddings.model``
    instead of the fully-qualified ``sentence-transformers/...`` form. Newer
    fastembed releases only accept the qualified form, so we map back to
    the registered entry by suffix match when the short form is passed in.
    """
    if name_or_alias in EMBEDDING_MODELS:
        return EMBEDDING_MODELS[name_or_alias]
    alias = _HF_TO_ALIAS.get(name_or_alias)
    if alias is not None:
        return EMBEDDING_MODELS[alias]
    # Suffix match: short name (no org prefix) → fully-qualified registered name
    if "/" not in name_or_alias:
        suffix = "/" + name_or_alias
        for hf_name, alias in _HF_TO_ALIAS.items():
            if hf_name.endswith(suffix):
                return EMBEDDING_MODELS[alias]
    return ModelInfo(hf_name=name_or_alias, dim=-1, size_mb=-1, languages="unknown")


def is_model_cached(hf_name: str) -> bool:
    """Check if a FastEmbed ONNX model has already been downloaded locally."""
    cache_root = Path(
        os.environ.get("FASTEMBED_CACHE_PATH") or (Path.home() / ".cache" / "fastembed")
    )
    if not cache_root.exists():
        return False
    model_id = hf_name.replace("/", "--")
    for sub in cache_root.iterdir():
        if sub.is_dir() and model_id in sub.name:
            return True
    return False


def warn_if_heavy(name_or_alias: str, non_interactive: bool = False) -> bool:
    """Warn before downloading a heavy model; return True if download should proceed.

    Returns immediately True if the model is already cached, under the size
    threshold, or if running non-interactively (scripts never block).
    """
    info = resolve_model(name_or_alias)
    if info.size_mb < SIZE_WARNING_THRESHOLD_MB or info.size_mb < 0:
        return True
    if is_model_cached(info.hf_name):
        return True
    print(
        f"\n  ⚠️  First-time download: {info.hf_name}\n"
        f"     Size: ~{info.size_mb} MB  |  Languages: {info.languages}\n"
        f"     Cache: ~/.cache/fastembed/ (reused on future runs)\n",
        file=sys.stderr,
    )
    if non_interactive or not sys.stdin.isatty():
        return True
    answer = input("  Continue? [Y/n] ").strip().lower()
    return answer in ("", "y", "yes", "o", "oui")


def _embed_threads() -> Optional[int]:
    """Read ``RTFM_EMBED_THREADS`` — the onnxruntime intra-op thread cap
    for the embedding session. Default ``1`` (one worker ⇒ one core, no
    per-project overshoot on multi-project boxes). ``0`` returns
    ``None`` so fastembed picks its own default (cpu_count / 2).

    The env-var equivalents (``OMP_NUM_THREADS`` etc.) do NOT actually
    bound onnxruntime's intra-op pool — that pool is only controlled
    by ``SessionOptions.intra_op_num_threads``, which fastembed exposes
    through its ``threads=`` constructor argument. Setting OMP alone
    left workers running 12 intra-op threads and eating ~400 % CPU.
    """
    raw = os.environ.get("RTFM_EMBED_THREADS", "1")
    try:
        n = int(raw)
    except ValueError:
        return 1
    return None if n <= 0 else n


def get_model(model_name: str = DEFAULT_MODEL):
    """Get or load the FastEmbed text embedding model (cached in process)."""
    global _model, _model_name
    hf_name = resolve_model(model_name).hf_name

    if _model is None or _model_name != hf_name:
        try:
            from fastembed import TextEmbedding
            _model = TextEmbedding(model_name=hf_name, threads=_embed_threads())
            _model_name = hf_name
        except ImportError:
            raise ImportError(
                "\n\n  ❌ Semantic search requires the embeddings extra.\n"
                "     Install with:  pip install rtfm-ai[embeddings]\n"
                "     (~85 MB ONNX model, no GPU needed)\n"
            )

    return _model


def _normalize(v: "np.ndarray") -> "np.ndarray":
    """L2-normalize embeddings so dot product equals cosine similarity."""
    import numpy as np
    norm = np.linalg.norm(v, axis=-1, keepdims=True)
    norm = np.where(norm == 0, 1, norm)
    return v / norm


def _apply_query_prefix(text: str, model_name: str) -> str:
    """Prepend the model's required query prefix if any (e.g. mxbai)."""
    prefix = resolve_model(model_name).query_prefix
    if prefix:
        return prefix + text
    return text


def embed_text(
    text: str,
    model_name: str = DEFAULT_MODEL,
    is_query: bool = True,
) -> "np.ndarray":
    """Generate embedding for a single text.

    is_query=True applies the model's query prefix when required (mxbai, e5...).
    Set is_query=False for indexing/document embedding.
    """
    import numpy as np
    if is_query:
        text = _apply_query_prefix(text, model_name)
    model = get_model(model_name)
    embeddings = list(model.embed([text]))
    vec = np.array(embeddings[0], dtype=np.float32)
    return _normalize(vec)


def embed_texts(
    texts: List[str],
    model_name: str = DEFAULT_MODEL,
    batch_size: int = 32,
    show_progress: bool = False,
    is_query: bool = False,
) -> "np.ndarray":
    """Generate embeddings for multiple texts (documents by default).

    Set is_query=True only when embedding a batch of queries.
    """
    import numpy as np
    if is_query:
        texts = [_apply_query_prefix(t, model_name) for t in texts]
    model = get_model(model_name)
    embeddings = list(model.embed(texts, batch_size=batch_size))
    arr = np.array(embeddings, dtype=np.float32)
    return _normalize(arr)


def embedding_to_bytes(embedding: "np.ndarray") -> bytes:
    """Convert numpy embedding to bytes for SQLite storage."""
    import numpy as np
    return embedding.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> "np.ndarray":
    """Convert bytes from SQLite back to numpy embedding."""
    import numpy as np
    return np.frombuffer(data, dtype=np.float32)


def embedding_dim_from_bytes(data: bytes) -> int:
    """Infer embedding dimension from stored BLOB length (4 bytes per float32)."""
    return len(data) // 4


def cosine_similarity(a: "np.ndarray", b: "np.ndarray") -> float:
    """Cosine similarity; assumes both vectors are L2-normalized."""
    import numpy as np
    return float(np.dot(a, b))


def cosine_similarity_batch(query: "np.ndarray", embeddings: "np.ndarray") -> "np.ndarray":
    """Cosine similarity between a query vector and N embeddings (assumes normalized)."""
    import numpy as np
    return np.dot(embeddings, query)
