"""
Parser for BOFiP (Bulletin Officiel des Finances Publiques) HTML files.

Handles HTML exports from:
- bofip.impots.gouv.fr
- Open Data archives (TGZ with document.xml + HTML content)

Structure:
- Archives contain document.xml (metadata) + content.html
- HTML content has paragraphs, references to CGI articles
- Identifiers follow pattern: BOI-{SERIE}-{DIVISION}-{...}-{DATE}

Sources:
- Site: https://bofip.impots.gouv.fr/
- Open Data: https://data.economie.gouv.fr/explore/dataset/bofip-impots/
- Doc: https://www.data.economie.gouv.fr/api/datasets/1.0/bofip-impots/attachments/bofip_documentation_pdf/
"""

import re
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator, Optional
from html.parser import HTMLParser
from datetime import datetime

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')[:50]


def content_hash(text: str) -> str:
    """Generate a short hash of content."""
    return hashlib.md5(text.encode()).hexdigest()[:12]


class HTMLTextExtractor(HTMLParser):
    """Extract text content from HTML, preserving structure."""

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.current_section = None
        self.sections = []  # List of (title, content) tuples
        self.in_heading = False
        self.heading_text = ""
        self.skip_tags = {'script', 'style', 'nav', 'footer', 'header'}
        self.skip_depth = 0
        self.current_content = []

    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            self.skip_depth += 1
            return

        if tag in ('h1', 'h2', 'h3', 'h4'):
            self.in_heading = True
            self.heading_text = ""
            # Save previous section
            if self.current_section and self.current_content:
                self.sections.append((
                    self.current_section,
                    ' '.join(self.current_content)
                ))
                self.current_content = []

        if tag == 'p':
            self.text_parts.append('\n\n')
        elif tag == 'br':
            self.text_parts.append('\n')
        elif tag in ('li',):
            self.text_parts.append('\n- ')

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.skip_depth = max(0, self.skip_depth - 1)
            return

        if tag in ('h1', 'h2', 'h3', 'h4'):
            self.in_heading = False
            self.current_section = self.heading_text.strip()

    def handle_data(self, data):
        if self.skip_depth > 0:
            return

        text = data.strip()
        if not text:
            return

        if self.in_heading:
            self.heading_text += ' ' + text
        else:
            self.text_parts.append(text)
            self.current_content.append(text)

    def get_text(self) -> str:
        """Get full text content."""
        return ' '.join(self.text_parts)

    def get_sections(self) -> list:
        """Get sections as (title, content) tuples."""
        # Don't forget the last section
        if self.current_section and self.current_content:
            self.sections.append((
                self.current_section,
                ' '.join(self.current_content)
            ))
        return self.sections


def extract_cgi_references(text: str) -> list[str]:
    """Extract CGI article references from text."""
    # Patterns for CGI article references
    # Match: "article 39 decies A", "art. 44 quinquies", etc.
    # Suffixes: bis, ter, quater, quinquies, sexies, septies, octies, nonies, decies
    # Optional letter suffix: A, B, C...
    # Use word boundary to avoid capturing "du", "de", etc.
    patterns = [
        r"article\s+(\d+\s*(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies)?(?:\s+[A-Z])?)(?:\s+du|\s+de|\s|$|,)",
        r"art\.\s*(\d+\s*(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies)?(?:\s+[A-Z])?)(?:\s+du|\s+de|\s|$|,)",
        r"CGI,?\s*art\.\s*(\d+\s*(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies)?(?:\s+[A-Z])?)(?:\s+du|\s+de|\s|$|,)",
    ]

    references = set()
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            # Normalize: remove extra spaces, strip trailing
            ref = re.sub(r'\s+', ' ', match).strip()
            if ref:
                references.add(ref)

    return sorted(references)


def parse_boi_identifier(identifier: str) -> dict:
    """
    Parse a BOI identifier into components.

    Format: BOI-{SERIE}-{DIVISION}-{TITRE}-{CHAPITRE}-{SECTION}-{DATE}
    Example: BOI-TVA-CHAMP-30-10-20-10-20130523
    """
    parts = identifier.split('-')
    result = {
        'identifiant': identifier,
        'serie': '',
        'division': '',
        'date_publication': '',
    }

    if len(parts) >= 2 and parts[0] == 'BOI':
        result['serie'] = parts[1] if len(parts) > 1 else ''
        result['division'] = parts[2] if len(parts) > 2 else ''

        # Last part is usually the date (YYYYMMDD)
        if parts[-1].isdigit() and len(parts[-1]) == 8:
            try:
                date_str = parts[-1]
                result['date_publication'] = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            except:
                pass

    return result


@ParserRegistry.register
class HTMLBOFiPParser(BaseParser):
    """
    Parser for BOFiP HTML files.

    Supports:
    - Standalone HTML files from bofip.impots.gouv.fr
    - HTML content from Open Data TGZ archives
    - Associated document.xml metadata files
    """

    extensions = ['.html', '.htm']
    name = "bofip"

    # Chunk sizing
    TARGET_CHARS = 1500
    MIN_CHARS = 200
    MAX_CHARS = 3000

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None
    ) -> Iterator[Chunk]:
        """Parse a BOFiP HTML file into chunks."""
        metadata = metadata or {}
        path = Path(path)

        # Read HTML content
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            html_content = f.read()

        # Try to find associated document.xml for metadata
        doc_meta = self._load_document_xml(path)
        doc_meta.update(metadata)

        # Extract document info.
        #
        # The identity comes from the caller, like every other parser here.
        # This one used to recompute it from the document's <title>, which
        # is not an identity: the catalogue entry then carried a
        # title-derived slug while the file tracking carried a path-derived
        # one, so the two never matched and every HTML document showed up as
        # an untracked book for ever. Worse, two pages sharing a <title> —
        # ordinary in a docs tree or a set of mockups — collapsed onto one
        # identity and the second was refused. A parser proposes a *title*;
        # what a document is called is not who it is.
        doc_title = doc_meta.get('titre', path.stem)
        doc_slug = doc_meta.get('book_slug') or self._path_to_slug(path)
        boi_id = doc_meta.get('identifiant', '')

        # Parse BOI identifier
        boi_info = parse_boi_identifier(boi_id) if boi_id else {}

        # Parse HTML
        parser = HTMLTextExtractor()
        parser.feed(html_content)

        sections = parser.get_sections()

        if not sections:
            # No sections found, treat whole content as one section
            full_text = parser.get_text()
            if full_text.strip():
                sections = [(doc_title, full_text)]

        # Generate chunks from sections
        chunk_idx = 0
        for section_title, section_content in sections:
            section_content = self._clean_text(section_content)

            if not section_content.strip():
                continue

            # Split large sections into smaller chunks
            text_chunks = self._split_into_chunks(section_content)

            for para_idx, chunk_text in enumerate(text_chunks):
                chunk_idx += 1

                # Extract CGI references from this chunk
                cgi_refs = extract_cgi_references(chunk_text)

                # Build metadata
                chunk_metadata = {
                    "legal_fr": {
                        "identifiant_boi": boi_id,
                        "serie": boi_info.get('serie', ''),
                        "division": boi_info.get('division', ''),
                        "date_publication": boi_info.get('date_publication', ''),
                        "type": doc_meta.get('type', 'commentaire'),
                        "references_cgi": cgi_refs,
                    }
                }

                yield Chunk(
                    id=f"{doc_slug}-{chunk_idx:04d}",
                    content=chunk_text,
                    book_title=doc_title,
                    book_slug=doc_slug,
                    book_file=path.name,
                    chapter_title=section_title or doc_title,
                    chapter_num=chunk_idx,
                    page_start=chunk_idx,
                    page_end=chunk_idx,
                    paragraph=para_idx + 1,
                    section_type="doctrine",
                    content_chars=len(chunk_text),
                    content_hash=content_hash(chunk_text),
                    metadata=chunk_metadata,
                )

    @staticmethod
    def _path_to_slug(path: Path) -> str:
        return str(path).replace("/", "-").replace("\\", "-").lstrip("-")

    def _load_document_xml(self, html_path: Path) -> dict:
        """Load metadata from associated document.xml file."""
        # Try common locations for document.xml
        possible_paths = [
            html_path.parent / 'document.xml',
            html_path.with_suffix('.xml'),
            html_path.parent / 'meta.xml',
        ]

        for xml_path in possible_paths:
            if xml_path.exists():
                try:
                    tree = ET.parse(xml_path)
                    root = tree.getroot()
                    return self._parse_document_xml(root)
                except ET.ParseError:
                    continue

        return {}

    def _parse_document_xml(self, root: ET.Element) -> dict:
        """Parse BOFiP document.xml metadata."""
        meta = {}

        # Common element paths in BOFiP document.xml
        mappings = {
            'titre': ['.//titre', './/title', './/TITRE'],
            'identifiant': ['.//identifiant', './/dataRef', './/ID'],
            'type': ['.//dataType', './/type', './/TYPE'],
            'date_publication': ['.//datePublication', './/date', './/DATE'],
            'serie': ['.//serie', './/SERIE'],
        }

        for key, paths in mappings.items():
            for path in paths:
                elem = root.find(path)
                if elem is not None and elem.text:
                    meta[key] = elem.text.strip()
                    break

        return meta

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text content."""
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove common artifacts
        text = re.sub(r'\s*\|\s*', ' ', text)
        return text.strip()

    def _split_into_chunks(self, text: str) -> list[str]:
        """Split text into appropriately sized chunks."""
        if len(text) <= self.MAX_CHARS:
            return [text]

        chunks = []
        paragraphs = text.split('\n\n')

        current_chunk = ""
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) + 2 <= self.MAX_CHARS:
                current_chunk += ("\n\n" if current_chunk else "") + para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                # Handle very long paragraphs
                if len(para) > self.MAX_CHARS:
                    # Split on sentences
                    sentences = re.split(r'(?<=[.!?])\s+', para)
                    current_chunk = ""
                    for sent in sentences:
                        if len(current_chunk) + len(sent) + 1 <= self.MAX_CHARS:
                            current_chunk += (" " if current_chunk else "") + sent
                        else:
                            if current_chunk:
                                chunks.append(current_chunk)
                            current_chunk = sent
                else:
                    current_chunk = para

        if current_chunk:
            chunks.append(current_chunk)

        return chunks if chunks else [text]

    def extract_metadata(self, path: Path) -> dict:
        """Extract metadata without full parsing."""
        doc_meta = self._load_document_xml(path)

        # Try to extract title from HTML if not in XML
        if 'titre' not in doc_meta:
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    html = f.read(5000)
                match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
                if match:
                    doc_meta['titre'] = match.group(1).strip()
            except:
                pass

        return {
            "source_file": path.name,
            # Path-derived, like the rest of the parsers: a fallback for a
            # direct ``Library.ingest(path)`` with no identity supplied.
            # Never the title — see :meth:`parse`.
            "book_slug": self._path_to_slug(path),
            "title": doc_meta.get('titre', path.stem),
            **doc_meta
        }


def lien_bofip(identifiant: str) -> str:
    """
    Generate a BOFiP URL for a document identifier.

    Args:
        identifiant: BOI identifier (e.g., "BOI-TVA-CHAMP-30-10-20-10-20130523")

    Returns:
        URL string for BOFiP
    """
    # Remove BOI- prefix if present for the URL
    clean_id = identifiant.replace('BOI-', '')
    return f"https://bofip.impots.gouv.fr/bofip/{clean_id}"
