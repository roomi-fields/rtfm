"""
Schema descriptor for biblirag.

Documents all fields used by biblirag core.
External applications can freely use the `metadata` dict for custom fields.
"""

# Fields used by biblirag core - DO NOT use these names in metadata
CORE_CHUNK_FIELDS = {
    # Identity
    "id": "Unique chunk identifier (str)",
    "content": "Text content of the chunk (str)",
    "content_chars": "Character count (int)",
    "content_hash": "MD5 hash for deduplication (str)",

    # Book/Document
    "book_title": "Document title (str)",
    "book_slug": "URL-safe identifier (str)",
    "book_file": "Original filename (str)",

    # Location
    "page_start": "Starting page number (int)",
    "page_end": "Ending page number (int)",
    "paragraph": "Paragraph number within section (int)",

    # Structure
    "chapter_num": "Chapter number (int, optional)",
    "chapter_title": "Chapter/section title (str, optional)",
    "part_num": "Part number for multi-part docs (int, optional)",
    "part_title": "Part title (str, optional)",
    "section_type": "Type: chapter, appendix, intro, etc. (str)",

    # Enrichment
    "tags": "List of topic tags from LLM (list[str], optional)",

    # Extension point
    "metadata": "Free-form dict for application-specific data (dict)",
}

CORE_BOOK_FIELDS = {
    "slug": "Unique book identifier (str)",
    "title": "Book title (str)",
    "filename": "Original filename (str)",
    "corpus": "Corpus grouping (str, default='default')",
    "chunk_count": "Number of chunks (int)",
    "total_chars": "Total character count (int)",
    "indexed_at": "ISO timestamp of indexing (str)",
    "metadata": "Free-form dict for application-specific data (dict)",
}

# Suggested namespaces for domain-specific metadata
SUGGESTED_NAMESPACES = {
    "legal_fr": "French legal documents (Légifrance, BOFiP)",
    "academic": "Academic papers (DOI, citations)",
    "media": "Audio/Video (timestamps, speakers)",
}

# Example metadata structures for common use cases
METADATA_EXAMPLES = {
    "legal_fr": {
        "numero_article": "39 decies A",
        "code": "cgi",  # cgi, bofip, etc.
        "date_debut": "2024-01-01",
        "date_fin": None,  # None = still in effect
        "references": ["44 quinquies", "39 decies B"],
    },
    "academic": {
        "doi": "10.1234/example",
        "authors": ["Smith, J.", "Doe, A."],
        "year": 2024,
        "journal": "Nature",
    },
    "media": {
        "timestamp_start": "00:15:32",
        "timestamp_end": "00:16:45",
        "speaker": "John Doe",
    },
}


def get_schema() -> dict:
    """Get the full schema as a dict."""
    return {
        "chunk_fields": CORE_CHUNK_FIELDS,
        "book_fields": CORE_BOOK_FIELDS,
        "suggested_namespaces": SUGGESTED_NAMESPACES,
        "metadata_examples": METADATA_EXAMPLES,
    }


def print_schema():
    """Print schema in human-readable format."""
    print("=" * 60)
    print("BIBLIRAG SCHEMA")
    print("=" * 60)

    print("\n## Chunk Fields (reserved by biblirag)")
    for field, desc in CORE_CHUNK_FIELDS.items():
        print(f"  {field:20} {desc}")

    print("\n## Book Fields (reserved by biblirag)")
    for field, desc in CORE_BOOK_FIELDS.items():
        print(f"  {field:20} {desc}")

    print("\n## Metadata (free for extensions)")
    print("  Use chunk.metadata or book.metadata for custom fields.")
    print("  Suggested namespaces:")
    for ns, desc in SUGGESTED_NAMESPACES.items():
        print(f"    {ns:15} {desc}")


if __name__ == "__main__":
    print_schema()
