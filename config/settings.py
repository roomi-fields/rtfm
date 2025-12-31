"""Configuration settings for PDF Library Indexer."""

from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MARKDOWN_DIR = DATA_DIR / "markdown"
JSONL_DIR = DATA_DIR / "jsonl"
DB_DIR = PROJECT_ROOT / "db"

# Default input directory for PDFs
PDF_INPUT_DIR = PROJECT_ROOT / "biblitest"

# Database
DB_PATH = DB_DIR / "library.db"

# Marker settings
MARKER_BATCH_MULTIPLIER = 2  # Reduce for lower memory usage
MARKER_LANGS = ["en", "fr"]  # Languages to detect

# Chunk settings
MAX_CHUNK_TOKENS = 512  # Max tokens per chunk for LLM injection
MIN_CHUNK_TOKENS = 50   # Minimum tokens to consider a valid chunk
