"""Parse extracted Markdown into JSONL chunks with full metadata."""

import json
import re
import hashlib
from pathlib import Path
from typing import Optional, Iterator
from dataclasses import dataclass, asdict

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import MARKDOWN_DIR, JSONL_DIR


# Average chars per page (for estimation when page markers unavailable)
CHARS_PER_PAGE = 2500

# Target chunk size in characters (roughly 300-500 tokens)
TARGET_CHUNK_CHARS = 1500
MIN_CHUNK_CHARS = 200
MAX_CHUNK_CHARS = 3000


@dataclass
class Chunk:
    id: str
    book_title: str
    book_file: str
    book_slug: str
    chapter_num: int
    chapter_title: str
    page_start: int
    page_end: int
    paragraph: int
    content: str
    content_chars: int
    content_hash: str


def slugify(text: str) -> str:
    """Convert text to a slug."""
    text = re.sub(r'\([^)]*\)', '', text)
    text = text.replace('.pdf', '')
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


def extract_title_from_filename(filename: str) -> str:
    """Extract a clean title from the filename."""
    # Remove common patterns like (Z-Library), author in parens, etc.
    title = re.sub(r'\([^)]*\)', '', filename)
    title = title.replace('.pdf', '').replace('.md', '')
    title = title.replace('-', ' ').replace('_', ' ')
    title = ' '.join(title.split())  # Normalize whitespace
    return title.strip()


def is_chapter_heading(line: str, prev_empty: bool, next_empty: bool) -> bool:
    """Detect if a line is likely a chapter/section heading."""
    line = line.strip()

    if not line:
        return False

    # Markdown headings
    if line.startswith('#'):
        return True

    # Short lines in ALL CAPS (common in books)
    if len(line) < 60 and line.isupper() and len(line.split()) <= 8:
        # Must be surrounded by empty lines
        if prev_empty or next_empty:
            return True

    # Numbered chapters: "Chapter 1", "CHAPTER ONE", "1. Introduction"
    if re.match(r'^(chapter|part|section)\s+\d+', line, re.I):
        return True
    if re.match(r'^\d+\.\s+[A-Z]', line):
        return True

    return False


def clean_heading(line: str) -> str:
    """Clean up a heading line."""
    line = line.strip()
    # Remove markdown heading markers
    line = re.sub(r'^#+\s*', '', line)
    # Title case if all caps
    if line.isupper():
        line = line.title()
    return line


def split_into_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs."""
    # Split on double newlines
    paragraphs = re.split(r'\n\s*\n', text)
    # Clean up each paragraph
    result = []
    for p in paragraphs:
        p = ' '.join(p.split())  # Normalize whitespace
        if p and len(p) > 20:  # Skip very short fragments
            result.append(p)
    return result


def merge_short_paragraphs(paragraphs: list[str]) -> list[str]:
    """Merge paragraphs that are too short."""
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
            result.append(buffer)
            buffer = ""

    # Don't forget the last buffer
    if buffer:
        if result and len(buffer) < MIN_CHUNK_CHARS:
            # Merge with previous if too short
            result[-1] += "\n\n" + buffer
        else:
            result.append(buffer)

    return result


def estimate_page(char_position: int) -> int:
    """Estimate page number from character position."""
    return max(1, (char_position // CHARS_PER_PAGE) + 1)


def content_hash(text: str) -> str:
    """Generate a short hash of content."""
    return hashlib.md5(text.encode()).hexdigest()[:12]


def parse_markdown_file(md_path: Path, metadata: dict) -> Iterator[Chunk]:
    """
    Parse a markdown file into chunks.

    Args:
        md_path: Path to the markdown file
        metadata: Book metadata dict

    Yields:
        Chunk objects
    """
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    book_title = extract_title_from_filename(metadata.get('source_file', md_path.stem))
    book_file = metadata.get('source_file', '')
    book_slug = metadata.get('book_slug', slugify(book_title))

    # Parse into sections
    sections = []
    current_section = {
        'title': 'Introduction',
        'content': [],
        'start_char': 0
    }

    char_pos = 0
    for i, line in enumerate(lines):
        prev_empty = (i == 0) or (not lines[i-1].strip())
        next_empty = (i == len(lines)-1) or (not lines[i+1].strip() if i+1 < len(lines) else True)

        if is_chapter_heading(line, prev_empty, next_empty):
            # Save current section if it has content
            if current_section['content']:
                sections.append(current_section)

            # Start new section
            current_section = {
                'title': clean_heading(line),
                'content': [],
                'start_char': char_pos
            }
        else:
            if line.strip():
                current_section['content'].append(line)

        char_pos += len(line) + 1  # +1 for newline

    # Don't forget last section
    if current_section['content']:
        sections.append(current_section)

    # Generate chunks from sections
    chunk_num = 0
    for chapter_num, section in enumerate(sections):
        section_text = '\n'.join(section['content'])
        paragraphs = split_into_paragraphs(section_text)
        chunks = merge_short_paragraphs(paragraphs)

        for para_num, chunk_text in enumerate(chunks, 1):
            chunk_num += 1

            # Estimate page range
            chunk_start_char = section['start_char']
            page_start = estimate_page(chunk_start_char)
            page_end = estimate_page(chunk_start_char + len(chunk_text))

            chunk_id = f"{book_slug}-ch{chapter_num:02d}-p{page_start:03d}-{chunk_num:04d}"

            yield Chunk(
                id=chunk_id,
                book_title=book_title,
                book_file=book_file,
                book_slug=book_slug,
                chapter_num=chapter_num,
                chapter_title=section['title'],
                page_start=page_start,
                page_end=page_end,
                paragraph=para_num,
                content=chunk_text,
                content_chars=len(chunk_text),
                content_hash=content_hash(chunk_text)
            )


def parse_book(book_dir: Path, output_dir: Optional[Path] = None) -> Path:
    """
    Parse a single book's markdown into JSONL.

    Args:
        book_dir: Directory containing the book's markdown and metadata
        output_dir: Output directory for JSONL (default: JSONL_DIR)

    Returns:
        Path to the output JSONL file
    """
    output_dir = output_dir or JSONL_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find markdown file
    md_files = list(book_dir.glob('*.md'))
    if not md_files:
        raise FileNotFoundError(f"No markdown files in {book_dir}")
    md_path = md_files[0]

    # Load metadata
    metadata_path = book_dir / 'metadata.json'
    if metadata_path.exists():
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
    else:
        metadata = {'book_slug': book_dir.name}

    # Output file
    book_slug = metadata.get('book_slug', book_dir.name)
    output_path = output_dir / f"{book_slug}.jsonl"

    print(f"Parsing: {md_path.name}")

    # Parse and write chunks
    chunk_count = 0
    total_chars = 0

    with open(output_path, 'w', encoding='utf-8') as f:
        for chunk in parse_markdown_file(md_path, metadata):
            f.write(json.dumps(asdict(chunk), ensure_ascii=False) + '\n')
            chunk_count += 1
            total_chars += chunk.content_chars

    print(f"  Output: {output_path}")
    print(f"  Chunks: {chunk_count}, Total chars: {total_chars:,}")

    return output_path


def parse_all_books(
    input_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None
) -> list[Path]:
    """
    Parse all books in the markdown directory.

    Returns:
        List of output JSONL paths
    """
    input_dir = Path(input_dir) if input_dir else MARKDOWN_DIR
    output_dir = Path(output_dir) if output_dir else JSONL_DIR

    book_dirs = [d for d in input_dir.iterdir() if d.is_dir()]

    if not book_dirs:
        print(f"No book directories found in {input_dir}")
        return []

    print(f"Found {len(book_dirs)} books to parse\n")

    results = []
    total_chunks = 0

    for i, book_dir in enumerate(book_dirs, 1):
        print(f"[{i}/{len(book_dirs)}]")
        try:
            output_path = parse_book(book_dir, output_dir)
            results.append(output_path)

            # Count chunks
            with open(output_path) as f:
                total_chunks += sum(1 for _ in f)
        except Exception as e:
            print(f"  ERROR: {e}")
        print()

    print(f"=== Summary ===")
    print(f"Books parsed: {len(results)}")
    print(f"Total chunks: {total_chunks}")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parse Markdown to JSONL chunks")
    parser.add_argument("input", nargs="?", help="Book directory or markdown dir")
    parser.add_argument("-o", "--output", help="Output directory")

    args = parser.parse_args()

    if args.input:
        input_path = Path(args.input)
        if input_path.is_dir():
            # Check if it's a single book dir or parent dir
            if (input_path / 'metadata.json').exists() or list(input_path.glob('*.md')):
                parse_book(input_path, args.output)
            else:
                parse_all_books(input_path, args.output)
        else:
            print(f"Error: {input_path} is not a directory")
    else:
        parse_all_books()
