"""Markdown parser - wraps existing toc_parser functionality."""

import json
import re
import hashlib
from pathlib import Path
from typing import Iterator, Optional

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry


# Chunk sizing
TARGET_CHUNK_CHARS = 1500
MIN_CHUNK_CHARS = 200
MAX_CHUNK_CHARS = 3000
CHARS_PER_PAGE = 2500


def slugify(text: str) -> str:
    """Convert text to a slug."""
    text = re.sub(r'\([^)]*\)', '', text)
    text = text.replace('.pdf', '').replace('.md', '')
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


def extract_title_from_filename(filename: str) -> str:
    """Extract a clean title from the filename."""
    title = re.sub(r'\([^)]*\)', '', filename)
    title = title.replace('.pdf', '').replace('.md', '')
    title = title.replace('-', ' ').replace('_', ' ')
    title = ' '.join(title.split())
    return title.strip()


def content_hash(text: str) -> str:
    """Generate a short hash of content."""
    return hashlib.md5(text.encode()).hexdigest()[:12]


def estimate_page(char_position: int) -> int:
    """Estimate page number from character position."""
    return max(1, (char_position // CHARS_PER_PAGE) + 1)


def split_into_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs."""
    paragraphs = re.split(r'\n\s*\n', text)
    result = []
    for p in paragraphs:
        p = ' '.join(p.split())
        if p and len(p) > 20:
            result.append(p)
    return result


def split_on_sentence(text: str, max_chars: int) -> list[str]:
    """Split text at sentence boundaries, respecting max_chars."""
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
    """Merge paragraphs that are too short, split those that are too long."""
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


@ParserRegistry.register
class MarkdownParser(BaseParser):
    """Parser for Markdown files."""

    extensions = ['.md', '.markdown']
    name = "markdown"

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None
    ) -> Iterator[Chunk]:
        """Parse a markdown file into chunks."""
        metadata = metadata or {}

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        book_title = metadata.get('title') or extract_title_from_filename(path.stem)
        book_slug = metadata.get('book_slug') or slugify(book_title)
        book_file = metadata.get('source_file') or path.name

        # Split by headers
        sections = self._split_by_headers(content)

        chunk_counter = 0
        for section in sections:
            paragraphs = split_into_paragraphs(section['content'])
            chunks = merge_short_paragraphs(paragraphs)

            for para_num, chunk_text in enumerate(chunks, 1):
                chunk_counter += 1

                char_start = section.get('char_start', 0)
                page_start = estimate_page(char_start)
                page_end = estimate_page(char_start + len(chunk_text))

                chunk_id = f"{book_slug}-{section['level']}-p{page_start:03d}-{chunk_counter:04d}"

                yield Chunk(
                    id=chunk_id,
                    content=chunk_text,
                    book_title=book_title,
                    book_slug=book_slug,
                    book_file=book_file,
                    chapter_title=section.get('title', ''),
                    chapter_num=section.get('num'),
                    page_start=page_start,
                    page_end=page_end,
                    paragraph=para_num,
                    line_start=section.get('line_start'),
                    line_end=section.get('line_end'),
                    section_type=section.get('type', 'section'),
                    content_chars=len(chunk_text),
                    content_hash=content_hash(chunk_text),
                    metadata=metadata.get('extended', {}),
                )

    def _split_by_headers(self, content: str) -> list[dict]:
        """Split content by markdown headers."""
        sections = []
        lines = content.split('\n')

        current_section = {
            'title': '',
            'level': 0,
            'type': 'intro',
            'num': None,
            'content_lines': [],
            'char_start': 0,
            'line_start': 1,
        }

        char_pos = 0
        for line_num, line in enumerate(lines, 1):
            # Check for header
            header_match = re.match(r'^(#{1,6})\s+(.+)$', line)
            if header_match:
                # Save previous section
                if current_section['content_lines']:
                    current_section['content'] = '\n'.join(current_section['content_lines'])
                    current_section['line_end'] = line_num - 1
                    if len(current_section['content'].strip()) > 100:
                        sections.append(current_section)

                # Start new section
                level = len(header_match.group(1))
                title = header_match.group(2).strip()

                # Try to extract chapter number
                num_match = re.match(r'^(?:Chapter|Part|Section)?\s*(\d+)[:\s.]?\s*(.*)$', title, re.I)
                if num_match:
                    num = int(num_match.group(1))
                    title = num_match.group(2) or title
                else:
                    num = None

                current_section = {
                    'title': title,
                    'level': level,
                    'type': 'chapter' if level <= 2 else 'section',
                    'num': num,
                    'content_lines': [],
                    'char_start': char_pos,
                    'line_start': line_num + 1,  # content starts after the header
                }
            else:
                current_section['content_lines'].append(line)

            char_pos += len(line) + 1

        # Save final section
        if current_section['content_lines']:
            current_section['content'] = '\n'.join(current_section['content_lines'])
            current_section['line_end'] = len(lines)
            if len(current_section['content'].strip()) > 100:
                sections.append(current_section)

        # If no headers found, treat whole content as one section
        if not sections:
            sections = [{
                'title': '',
                'level': 0,
                'type': 'content',
                'num': None,
                'content': content,
                'char_start': 0,
                'line_start': 1,
                'line_end': len(lines),
            }]

        return sections

    def extract_metadata(self, path: Path) -> dict:
        """Extract metadata from markdown file."""
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read(2000)  # Read first part for metadata

        metadata = {
            "source_file": path.name,
            "book_slug": slugify(path.stem),
        }

        # Try to find YAML frontmatter
        if content.startswith('---'):
            end = content.find('---', 3)
            if end > 0:
                try:
                    import yaml
                    frontmatter = yaml.safe_load(content[3:end])
                    if isinstance(frontmatter, dict):
                        metadata.update(frontmatter)
                except:
                    pass

        # Try to find title from first H1
        match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if match and 'title' not in metadata:
            metadata['title'] = match.group(1).strip()

        return metadata
