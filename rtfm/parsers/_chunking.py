"""Shared chunking and slugification helpers.

Reused by ebook/office parsers (epub, fb2, docx, odt, rtf, mobi, djvu).
The existing markdown.py and pdf.py keep their own copies for now — this
module is the canonical version for new parsers; the older duplicates can
be folded in later without changing behaviour.
"""

import hashlib
import re


TARGET_CHUNK_CHARS = 1500
MIN_CHUNK_CHARS = 200
MAX_CHUNK_CHARS = 3000
CHARS_PER_PAGE = 2500


def slugify(text: str) -> str:
    text = re.sub(r'\([^)]*\)', '', text)
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')[:80]


def content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]


def estimate_page(char_position: int) -> int:
    return max(1, (char_position // CHARS_PER_PAGE) + 1)


def extract_title_from_filename(stem: str) -> str:
    title = re.sub(r'\([^)]*\)', '', stem)
    title = title.replace('-', ' ').replace('_', ' ')
    title = ' '.join(title.split())
    return title.strip()


def split_into_paragraphs(text: str) -> list[str]:
    paragraphs = re.split(r'\n\s*\n', text)
    result = []
    for p in paragraphs:
        p = ' '.join(p.split())
        if p and len(p) > 20:
            result.append(p)
    if not result:
        stripped = text.strip()
        if stripped:
            result.append(' '.join(stripped.split()))
    return result


def split_on_sentence(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    sentence_ends = []
    for i, char in enumerate(text):
        if char in '.!?' and (i + 1 >= len(text) or text[i + 1] in ' \n'):
            sentence_ends.append(i + 1)

    if not sentence_ends:
        return [text[:max_chars].strip(), text[max_chars:].strip()]

    chunks = []
    chunk_start = 0
    prev_end = 0

    for end in sentence_ends:
        current_len = end - chunk_start
        if current_len > max_chars and prev_end > chunk_start:
            chunks.append(text[chunk_start:prev_end].strip())
            chunk_start = prev_end
        prev_end = end

    if chunk_start < len(text):
        remaining = text[chunk_start:].strip()
        if remaining:
            chunks.append(remaining)

    return chunks if chunks else [text]


def merge_short_paragraphs(paragraphs: list[str]) -> list[str]:
    if not paragraphs:
        return []

    result = []
    buffer = ""

    for p in paragraphs:
        if buffer:
            buffer += "\n\n" + p
        else:
            buffer = p

        if len(buffer) >= TARGET_CHUNK_CHARS:
            if len(buffer) > MAX_CHUNK_CHARS:
                chunks = split_on_sentence(buffer, MAX_CHUNK_CHARS)
                result.extend(chunks[:-1])
                buffer = chunks[-1] if chunks else ""
            else:
                result.append(buffer)
                buffer = ""

    if buffer:
        if result and len(buffer) < MIN_CHUNK_CHARS:
            result[-1] += "\n\n" + buffer
        else:
            result.append(buffer)

    return result
