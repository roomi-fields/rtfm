#!/usr/bin/env python3
"""
TOC-aware parser for structured book extraction.

Detects Table of Contents and uses it to properly structure books into:
- Books/Volumes
- Parts/Sections
- Chapters
- Appendices
"""

import json
import re
import hashlib
from pathlib import Path
from typing import Optional, Iterator
from dataclasses import dataclass, asdict, field

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import MARKDOWN_DIR, JSONL_DIR


# Chunk sizing
TARGET_CHUNK_CHARS = 1500
MIN_CHUNK_CHARS = 200
MAX_CHUNK_CHARS = 3000
CHARS_PER_PAGE = 2500


@dataclass
class TOCEntry:
    """A single entry in the table of contents."""
    level: int  # 0=book, 1=part, 2=chapter, 3=appendix/section
    type: str   # 'book', 'part', 'chapter', 'appendix', 'section', 'other'
    number: Optional[str]  # "1", "2", "A", "B", etc.
    title: str
    full_title: str  # e.g., "Chapter 1  Dimensions of Self"
    line_num: int    # Line number in TOC


@dataclass
class Section:
    """A section of content (chapter, part, etc.)."""
    level: int
    type: str
    number: Optional[str]
    title: str
    full_title: str
    parent_titles: list[str]  # Hierarchy above this section
    content: str
    start_char: int
    end_char: int


@dataclass
class Chunk:
    """A chunk ready for indexing."""
    id: str
    book_title: str
    book_file: str
    book_slug: str
    # Hierarchy
    book_num: Optional[int]
    book_name: Optional[str]
    part_num: Optional[int]
    part_title: Optional[str]
    chapter_num: Optional[int]
    chapter_title: str
    section_type: str  # 'chapter', 'appendix', 'introduction', etc.
    # Location
    page_start: int
    page_end: int
    paragraph: int
    # Content
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


def detect_caps_sections(lines: list[str], min_sections: int = 3) -> list[TOCEntry]:
    """
    Detect ALL CAPS section headers when no formal TOC exists.

    Returns TOCEntry list if enough sections found, empty list otherwise.
    """
    entries = []

    for i, line in enumerate(lines):
        # Skip first 5 lines (likely title/author repetition)
        if i < 5:
            continue

        stripped = line.strip()
        # ALL CAPS, 5-50 chars, mostly letters/spaces
        if (stripped.isupper() and
            5 <= len(stripped) <= 50 and
            len(stripped.split()) <= 6 and
            sum(c.isalpha() or c.isspace() for c in stripped) > len(stripped) * 0.8):
            # Skip common non-section headers
            if stripped in ('CONTENTS', 'TABLE OF CONTENTS', 'BIBLIOGRAPHY',
                           'REFERENCES', 'INDEX', 'NOTES', 'ACKNOWLEDGEMENTS',
                           'BIBLIOGRAPHY AND FOOTNOTES'):
                continue
            entries.append(TOCEntry(
                level=2, type='chapter', number=str(len(entries) + 1),
                title=stripped.title(), full_title=stripped, line_num=i
            ))

    return entries if len(entries) >= min_sections else []


def detect_separator_sections(lines: list[str], separator: str = '***', min_sections: int = 2) -> list[TOCEntry]:
    """
    Detect sections separated by *** or similar markers.
    Looks for section title in lines following the separator.

    Returns TOCEntry list if enough sections found, empty list otherwise.
    """
    entries = []

    # First section starts at beginning (after title/copyright)
    first_title = None
    for i in range(2, min(20, len(lines))):
        line = lines[i].strip()
        # Look for short title-like line (not copyright, not empty)
        if (line and 3 <= len(line) <= 60 and
            not line.startswith('From ') and
            not line.startswith('©') and
            not line.startswith('Copyright')):
            first_title = (line, i)
            break

    if first_title:
        entries.append(TOCEntry(
            level=2, type='chapter', number='1',
            title=first_title[0], full_title=first_title[0], line_num=first_title[1]
        ))

    # Find sections after separators
    for i, line in enumerate(lines):
        if line.strip() == separator:
            # Look for title in next few non-empty lines
            for j in range(i + 1, min(i + 5, len(lines))):
                next_line = lines[j].strip()
                if (next_line and 3 <= len(next_line) <= 60 and
                    not next_line.startswith('From ') and
                    not next_line.startswith('©')):
                    entries.append(TOCEntry(
                        level=2, type='chapter', number=str(len(entries) + 1),
                        title=next_line, full_title=next_line, line_num=j
                    ))
                    break

    return entries if len(entries) >= min_sections else []


def find_toc_section(lines: list[str]) -> tuple[int, int]:
    """
    Find the start and end of the Table of Contents.

    Returns:
        (start_line, end_line) or (-1, -1) if not found
    """
    toc_start = -1
    toc_end = -1

    # Find TOC start
    for i, line in enumerate(lines):
        stripped = line.strip().upper()
        if stripped in ('CONTENTS', 'TABLE OF CONTENTS', 'CONTENTS:', 'TABLE OF CONTENTS:'):
            toc_start = i + 1
            break

    if toc_start == -1:
        return (-1, -1)

    # Find TOC end - look for major section start or too much content
    consecutive_empty = 0
    found_chapters = False

    for i in range(toc_start, min(toc_start + 300, len(lines))):
        line = lines[i].strip()

        # Check if we've found chapter entries
        if re.match(r'^(Chapter|Part|Book|Appendix)\s+\d', line, re.I):
            found_chapters = True

        # Empty line tracking
        if not line:
            consecutive_empty += 1
        else:
            consecutive_empty = 0

        # End markers
        if found_chapters:
            # Long text block = content started
            if len(line) > 100:
                toc_end = i
                break
            # Keywords indicating content start
            if line.upper() in ('INTRODUCTION', 'PREFACE', 'FOREWORD') and i > toc_start + 10:
                # Check if next lines have substantial content
                if i + 2 < len(lines) and len(lines[i + 2].strip()) > 50:
                    toc_end = i
                    break

    if toc_end == -1:
        toc_end = min(toc_start + 200, len(lines))

    return (toc_start, toc_end)


def parse_toc_entry(line: str, line_num: int) -> Optional[TOCEntry]:
    """Parse a single TOC line into a TOCEntry."""
    line = line.strip()
    if not line or len(line) < 3:
        return None

    # BOOK pattern: "BOOK ONE" or "BOOK 1"
    match = re.match(r'^BOOK\s+(\w+)\s*$', line, re.I)
    if match:
        return TOCEntry(
            level=0, type='book', number=match.group(1),
            title='', full_title=line, line_num=line_num
        )

    # BOOK with subtitle: "BOOK ONE" followed by subtitle on same line
    match = re.match(r'^BOOK\s+(\w+)\s+(.+)$', line, re.I)
    if match:
        return TOCEntry(
            level=0, type='book', number=match.group(1),
            title=match.group(2), full_title=line, line_num=line_num
        )

    # Part pattern: "Part 1  Title" or "Part 1: Title" or "Part One: Title"
    match = re.match(r'^Part\s+(\w+)\s*[:\s]\s*(.*)$', line, re.I)
    if match:
        num = match.group(1)
        # Convert word to number if needed
        word_to_num = {'one': '1', 'two': '2', 'three': '3', 'four': '4',
                       'five': '5', 'six': '6', 'seven': '7', 'eight': '8'}
        num = word_to_num.get(num.lower(), num)
        return TOCEntry(
            level=1, type='part', number=num,
            title=match.group(2), full_title=line, line_num=line_num
        )

    # Chapter pattern: "Chapter 1  Title" or "Chapter 1: Title"
    match = re.match(r'^Chapter\s+(\d+)\s*[:\s]\s*(.*)$', line, re.I)
    if match:
        return TOCEntry(
            level=2, type='chapter', number=match.group(1),
            title=match.group(2), full_title=line, line_num=line_num
        )

    # Appendix pattern: "Appendix A: Title" or "Appendix A  Title"
    match = re.match(r'^Appendix\s+([A-Z])\s*[:\s]\s*(.*)$', line, re.I)
    if match:
        return TOCEntry(
            level=2, type='appendix', number=match.group(1),
            title=match.group(2), full_title=line, line_num=line_num
        )

    # Numbered chapter: "1. Title" or "1.  TITLE" or "1—Title" or "1—Point Eight: TITLE"
    # This pattern handles em-dash (U+2014), en-dash (U+2013), and regular dash
    match = re.match(r'^(\d+)\s*[\.\u2014\u2013\-]\s*(.+)$', line)
    if match and len(match.group(2)) > 2:
        return TOCEntry(
            level=2, type='chapter', number=match.group(1),
            title=match.group(2).strip(), full_title=line, line_num=line_num
        )

    # Section heading (ALL CAPS, short) - lower priority
    if line.isupper() and len(line) < 60 and len(line.split()) <= 8:
        # Could be book subtitle or major section
        return TOCEntry(
            level=1, type='section', number=None,
            title=line.title(), full_title=line, line_num=line_num
        )

    # Unnumbered subsection: "Title text 123" (title followed by page number)
    # Must have at least 3 words and end with a number
    match = re.match(r'^(.+?)\s+(\d+)\s*$', line)
    if match and len(match.group(1).split()) >= 3:
        title = match.group(1).strip()
        # Avoid matching things that look like dates or other patterns
        if not re.match(r'^\d', title) and len(title) > 10:
            return TOCEntry(
                level=3, type='section', number=None,
                title=title, full_title=line, line_num=line_num
            )

    return None


def parse_toc(lines: list[str], toc_start: int, toc_end: int) -> list[TOCEntry]:
    """Parse the TOC section into structured entries."""
    entries = []

    for i in range(toc_start, toc_end):
        entry = parse_toc_entry(lines[i], i)
        if entry:
            entries.append(entry)

    return entries


def find_section_in_content(
    lines: list[str],
    entry: TOCEntry,
    search_start: int
) -> Optional[int]:
    """
    Find where a TOC entry's content actually starts in the document.

    Returns:
        Line number where section starts, or None if not found
    """
    # Search patterns in order of specificity
    patterns = []

    # Pattern 1: "chapter X" or "Chapter X" on its own line (content format)
    if entry.type == 'chapter' and entry.number:
        patterns.append((rf'^chapter\s+{entry.number}\s*$', True))  # (pattern, case_insensitive)
        # Also try just the number: "1" or "1."
        patterns.append((rf'^{entry.number}\s*\.?\s*$', False))
        # Pattern: "{number} {title}" on same line (e.g., "7 Impressionability of Soul")
        if entry.title:
            title_start = re.escape(entry.title.split()[0]) if entry.title.split() else ""
            if title_start:
                patterns.append((rf'^{entry.number}\s+{title_start}', True))

    # Pattern 2: "Part X" or "part X" standalone
    if entry.type == 'part' and entry.number:
        patterns.append((rf'^part\s+{entry.number}\s*$', True))
        # Also "Part One" etc.
        num_to_word = {'1': 'one', '2': 'two', '3': 'three', '4': 'four',
                       '5': 'five', '6': 'six', '7': 'seven', '8': 'eight'}
        if entry.number in num_to_word:
            patterns.append((rf'^part\s+{num_to_word[entry.number]}\s*$', True))

    # Pattern 3: "BOOK ONE" or similar
    if entry.type == 'book' and entry.number:
        patterns.append((rf'^BOOK\s+{entry.number}\b', False))

    # Pattern 4: "Appendix A" standalone
    if entry.type == 'appendix' and entry.number:
        patterns.append((rf'^appendix\s+{entry.number}\s*$', True))

    # Pattern 5: Title exactly as standalone heading
    if entry.title and len(entry.title) > 5:
        # Escape and match as whole line or significant portion
        escaped_title = re.escape(entry.title)
        patterns.append((rf'^{escaped_title}\s*$', True))

    # Search through document
    for i in range(search_start, len(lines)):
        line = lines[i].strip()
        if not line:
            continue

        for pattern, case_insensitive in patterns:
            flags = re.I if case_insensitive else 0
            if re.match(pattern, line, flags):
                # For "chapter X" or numbered format, verify with title on next line
                if entry.type in ('chapter', 'part', 'appendix') and entry.number:
                    # Find the title line (skip empty lines)
                    for j in range(i + 1, min(i + 5, len(lines))):
                        next_line = lines[j].strip()
                        if next_line:
                            # Verify this matches the expected title
                            if entry.title:
                                # Check for partial match (first few words)
                                title_words = entry.title.lower().split()[:3]
                                next_words = next_line.lower().split()[:3]
                                if title_words == next_words or entry.title.lower() in next_line.lower():
                                    return i
                            # Or just accept if it's a short line (heading)
                            if len(next_line) < 80:
                                return i
                            break
                else:
                    return i

    # Fallback: try to find title alone (for numbered chapters without prefix)
    if entry.title and len(entry.title) > 5:
        title_lower = entry.title.lower().strip()
        title_words = title_lower.split()[:4]  # First 4 words
        for i in range(search_start, len(lines)):
            line = lines[i].strip().lower()
            if line == title_lower:
                return i
            # Partial match on first words
            line_words = line.split()[:4]
            if title_words and line_words == title_words:
                return i

    return None


def extract_sections_from_caps(lines: list[str], caps_entries: list[TOCEntry]) -> list[Section]:
    """
    Extract sections when we have ALL CAPS entries with known line numbers.
    Simpler than extract_sections since we already know exact positions.
    """
    sections = []

    for i, entry in enumerate(caps_entries):
        start_line = entry.line_num

        # End is next section or end of document
        if i + 1 < len(caps_entries):
            end_line = caps_entries[i + 1].line_num
        else:
            end_line = len(lines)

        # Extract content (skip the header line itself)
        content_lines = lines[start_line + 1:end_line]
        content = '\n'.join(content_lines)

        # Calculate char positions
        start_char = sum(len(lines[j]) + 1 for j in range(start_line))
        end_char = sum(len(lines[j]) + 1 for j in range(end_line))

        section = Section(
            level=entry.level,
            type=entry.type,
            number=entry.number,
            title=entry.title,
            full_title=entry.full_title,
            parent_titles=[],
            content=content,
            start_char=start_char,
            end_char=end_char
        )

        if len(content.strip()) > 100:
            sections.append(section)

    return sections


def extract_sections(lines: list[str], toc_entries: list[TOCEntry], toc_end: int = 0) -> list[Section]:
    """
    Extract content sections based on TOC entries.

    Args:
        lines: Document lines
        toc_entries: Parsed TOC entries
        toc_end: Line number where TOC ends
    """
    sections = []

    # Content starts after TOC
    content_start = toc_end if toc_end > 0 else 100

    # Track hierarchy
    current_book = None
    current_book_num = None
    current_part = None
    current_part_num = None

    # Build hierarchy for each TOC entry FIRST
    # Track current book/part while iterating through all TOC entries
    entry_hierarchy = {}  # Maps entry -> (book_num, book_name, part_num, part_title)
    current_book = None
    current_book_num = None
    current_part = None
    current_part_num = None

    for entry in toc_entries:
        if entry.type == 'book':
            current_book = entry.title or entry.full_title
            current_book_num = entry.number
            current_part = None
            current_part_num = None
        elif entry.type == 'part':
            current_part = entry.title
            current_part_num = entry.number
            # Parts belong to current book, no parent part
            entry_hierarchy[id(entry)] = (current_book_num, current_book, None, None)
        elif entry.type in ('chapter', 'appendix'):
            entry_hierarchy[id(entry)] = (current_book_num, current_book, current_part_num, current_part)

    # Filter to content-bearing entries
    content_entries = [e for e in toc_entries if e.type in ('chapter', 'part', 'appendix', 'introduction', 'preface', 'section')]

    # Find each section's location - search ALL from content_start, don't advance search_pos
    # This handles documents where content is not in TOC order
    located_entries = []

    for entry in content_entries:
        location = find_section_in_content(lines, entry, content_start)
        if location:
            located_entries.append((entry, location))

    # Sort by line number to get correct content order
    located_entries.sort(key=lambda x: x[1])

    # Extract content between sections
    for i, (entry, start_line) in enumerate(located_entries):
        # Get hierarchy from stored mapping
        if id(entry) in entry_hierarchy:
            current_book_num, current_book, current_part_num, current_part = entry_hierarchy[id(entry)]
        else:
            current_book_num, current_book, current_part_num, current_part = None, None, None, None

        # Find end (next section or end of document)
        if i + 1 < len(located_entries):
            end_line = located_entries[i + 1][1]
        else:
            end_line = len(lines)

        # Build parent titles
        parent_titles = []
        if current_book:
            parent_titles.append(f"Book {current_book_num}: {current_book}" if current_book_num else current_book)
        if current_part and entry.type not in ('book', 'part'):
            parent_titles.append(f"Part {current_part_num}: {current_part}" if current_part_num else current_part)

        # Extract content
        content_lines = lines[start_line + 1:end_line]
        content = '\n'.join(content_lines)

        # Calculate char positions
        start_char = sum(len(lines[j]) + 1 for j in range(start_line))
        end_char = sum(len(lines[j]) + 1 for j in range(end_line))

        # Create section
        section = Section(
            level=entry.level,
            type=entry.type,
            number=entry.number,
            title=entry.title or entry.full_title,
            full_title=entry.full_title,
            parent_titles=parent_titles,
            content=content,
            start_char=start_char,
            end_char=end_char
        )

        # Only add if has substantial content
        if len(content.strip()) > 100:
            sections.append(section)

    return sections


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
    """
    Split text at sentence boundaries, respecting max_chars.

    Splits at: . ! ? followed by space or end of text.
    """
    if len(text) <= max_chars:
        return [text]

    # Find sentence boundaries (position after the punctuation)
    sentence_ends = []
    for i, char in enumerate(text):
        if char in '.!?' and (i + 1 >= len(text) or text[i + 1] in ' \n'):
            sentence_ends.append(i + 1)

    if not sentence_ends:
        # No sentence boundaries found, split at max_chars (last resort)
        return [text[:max_chars].strip(), text[max_chars:].strip()]

    # Build chunks: accumulate sentences until approaching max_chars
    chunks = []
    chunk_start = 0
    prev_end = 0

    for end in sentence_ends:
        current_len = end - chunk_start
        if current_len > max_chars and prev_end > chunk_start:
            # Adding this sentence exceeds max, save previous chunk
            chunks.append(text[chunk_start:prev_end].strip())
            chunk_start = prev_end
        prev_end = end

    # Add remaining text
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
            # If buffer exceeds max, split on sentences
            if len(buffer) > MAX_CHUNK_CHARS:
                chunks = split_on_sentence(buffer, MAX_CHUNK_CHARS)
                result.extend(chunks[:-1])  # Add all but last
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


def section_to_chunks(
    section: Section,
    book_title: str,
    book_file: str,
    book_slug: str,
    chunk_counter: list  # Mutable counter [int]
) -> Iterator[Chunk]:
    """Convert a section into chunks."""

    paragraphs = split_into_paragraphs(section.content)
    chunks = merge_short_paragraphs(paragraphs)

    # Extract hierarchy info from parent_titles
    book_num = None
    book_name = None
    part_num = None
    part_title = None

    for pt in section.parent_titles:
        if pt.startswith('Book'):
            match = re.match(r'Book\s+(\w+):\s*(.+)', pt)
            if match:
                book_num = match.group(1)
                book_name = match.group(2)
        elif pt.startswith('Part'):
            match = re.match(r'Part\s+(\d+):\s*(.+)', pt)
            if match:
                part_num = int(match.group(1))
                part_title = match.group(2)

    # Set chapter_num or part_num based on section type
    chapter_num = None
    if section.type == 'chapter':
        chapter_num = int(section.number) if section.number and section.number.isdigit() else None
    elif section.type == 'part':
        # For parts, the section itself IS the part
        part_num = int(section.number) if section.number and section.number.isdigit() else None
        part_title = section.title
    elif section.type == 'appendix':
        chapter_num = None  # Appendices use letter numbering stored in section_type

    for para_num, chunk_text in enumerate(chunks, 1):
        chunk_counter[0] += 1

        page_start = estimate_page(section.start_char)
        page_end = estimate_page(section.start_char + len(chunk_text))

        # Build chunk ID
        type_prefix = section.type[:2]  # ch, pa, ap, bo, se
        num_part = section.number or "00"
        chunk_id = f"{book_slug}-{type_prefix}{num_part}-p{page_start:03d}-{chunk_counter[0]:04d}"

        yield Chunk(
            id=chunk_id,
            book_title=book_title,
            book_file=book_file,
            book_slug=book_slug,
            book_num=book_num,
            book_name=book_name,
            part_num=part_num,
            part_title=part_title,
            chapter_num=chapter_num,
            chapter_title=section.title,
            section_type=section.type,
            page_start=page_start,
            page_end=page_end,
            paragraph=para_num,
            content=chunk_text,
            content_chars=len(chunk_text),
            content_hash=content_hash(chunk_text)
        )


def parse_markdown_with_toc(md_path: Path, metadata: dict) -> Iterator[Chunk]:
    """
    Parse a markdown file using TOC-aware extraction.

    Falls back to simple parsing if no TOC is found.
    """
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    book_title = extract_title_from_filename(metadata.get('source_file', md_path.stem))
    book_file = metadata.get('source_file', '')
    book_slug = metadata.get('book_slug', slugify(book_title))

    # Try to find TOC
    toc_start, toc_end = find_toc_section(lines)

    if toc_start == -1:
        # Try to detect ALL CAPS section headers as virtual TOC
        caps_sections = detect_caps_sections(lines)
        if caps_sections:
            print(f"    No TOC found, but detected {len(caps_sections)} ALL CAPS sections")
            sections = extract_sections_from_caps(lines, caps_sections)
            print(f"    Sections extracted: {len(sections)}")
            chunk_counter = [0]
            for section in sections:
                yield from section_to_chunks(section, book_title, book_file, book_slug, chunk_counter)
            return

        # Try to detect *** separated sections
        sep_sections = detect_separator_sections(lines)
        if sep_sections:
            print(f"    No TOC found, but detected {len(sep_sections)} *** separated sections")
            sections = extract_sections_from_caps(lines, sep_sections)  # Same extraction logic
            print(f"    Sections extracted: {len(sections)}")
            chunk_counter = [0]
            for section in sections:
                yield from section_to_chunks(section, book_title, book_file, book_slug, chunk_counter)
            return

        print(f"    No TOC found, using fallback parser")
        # Import and use fallback
        from src.parser import parse_markdown_file
        yield from parse_markdown_file(md_path, metadata)
        return

    print(f"    TOC found: lines {toc_start}-{toc_end}")

    # Parse TOC
    toc_entries = parse_toc(lines, toc_start, toc_end)
    print(f"    TOC entries: {len(toc_entries)}")

    # Show structure
    for entry in toc_entries[:10]:
        indent = "  " * entry.level
        print(f"      {indent}{entry.type}: {entry.title or entry.full_title}")
    if len(toc_entries) > 10:
        print(f"      ... and {len(toc_entries) - 10} more")

    # Extract sections
    sections = extract_sections(lines, toc_entries, toc_end)
    print(f"    Sections extracted: {len(sections)}")

    # If TOC parsing yielded no sections, fall back to simple parser
    if not sections:
        print(f"    TOC parsing failed, using fallback parser")
        from src.parser import parse_markdown_file
        yield from parse_markdown_file(md_path, metadata)
        return

    # Convert to chunks
    chunk_counter = [0]
    for section in sections:
        yield from section_to_chunks(section, book_title, book_file, book_slug, chunk_counter)


def parse_book_toc(book_dir: Path, output_dir: Optional[Path] = None) -> Path:
    """
    Parse a single book using TOC-aware extraction.
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
        for chunk in parse_markdown_with_toc(md_path, metadata):
            f.write(json.dumps(asdict(chunk), ensure_ascii=False) + '\n')
            chunk_count += 1
            total_chars += chunk.content_chars

    print(f"  Output: {output_path}")
    print(f"  Chunks: {chunk_count}, Total chars: {total_chars:,}")

    return output_path


def parse_all_books_toc(
    input_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None
) -> list[Path]:
    """Parse all books using TOC-aware extraction."""
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
            output_path = parse_book_toc(book_dir, output_dir)
            results.append(output_path)

            with open(output_path) as f:
                total_chunks += sum(1 for _ in f)
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
        print()

    print(f"=== Summary ===")
    print(f"Books parsed: {len(results)}")
    print(f"Total chunks: {total_chunks}")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parse Markdown with TOC detection")
    parser.add_argument("input", nargs="?", help="Book directory or markdown dir")
    parser.add_argument("-o", "--output", help="Output directory")

    args = parser.parse_args()

    if args.input:
        input_path = Path(args.input)
        if input_path.is_dir():
            if (input_path / 'metadata.json').exists() or list(input_path.glob('*.md')):
                parse_book_toc(input_path, args.output)
            else:
                parse_all_books_toc(input_path, args.output)
    else:
        parse_all_books_toc()
