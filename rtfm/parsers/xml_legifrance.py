"""
Parser for Légifrance XML files (LEGI format).

Handles XML exports from:
- LEGI database (codes, laws, regulations)
- echanges.dila.gouv.fr/OPENDATA/LEGI/

XML Structure (based on DTD LEGIFRANCE):
- TEXTE_VERSION: Root element for a text version
- ARTICLE: Individual articles with content
- META: Metadata (dates, identifiers, references)

Sources:
- DTD: https://echanges.dila.gouv.fr/OPENDATA/DTD_LEGIFRANCE/
- Data: https://echanges.dila.gouv.fr/OPENDATA/LEGI/
- API: https://api.gouv.fr/les-api/DILA_api_Legifrance
"""

import re
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator, Optional
from datetime import datetime

from rtfm.core.models import Chunk
from rtfm.parsers.base import BaseParser, ParserRegistry


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')[:50]


def make_article_ref(code: str, article_num: str) -> str:
    """
    Create a stable article reference for versioning.

    Examples:
        make_article_ref("cgi", "39 decies A") -> "CGI-39-decies-A"
        make_article_ref("code civil", "1234") -> "CODE-CIVIL-1234"
    """
    code_clean = re.sub(r'[^\w\s]', '', code).strip().upper()
    code_clean = re.sub(r'\s+', '-', code_clean)
    art_clean = re.sub(r'[^\w\s]', '', article_num).strip()
    art_clean = re.sub(r'\s+', '-', art_clean)
    return f"{code_clean}-{art_clean}"


def content_hash(text: str) -> str:
    """Generate a short hash of content."""
    return hashlib.md5(text.encode()).hexdigest()[:12]


def clean_text(text: str) -> str:
    """Clean and normalize text content."""
    if not text:
        return ""
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_text_recursive(element: ET.Element) -> str:
    """Extract all text content from an element and its children."""
    texts = []
    if element.text:
        texts.append(element.text)
    for child in element:
        texts.append(extract_text_recursive(child))
        if child.tail:
            texts.append(child.tail)
    return ' '.join(texts)


@ParserRegistry.register
class XMLLegiFranceParser(BaseParser):
    """
    Parser for Légifrance XML files.

    Supports LEGI format used by:
    - Code Général des Impôts (CGI)
    - Other French codes and laws
    - Legislative texts from data.gouv.fr

    The parser handles multiple XML structures:
    1. TEXTE_VERSION format (consolidated texts)
    2. ARTICLE format (individual articles)
    3. CODE format (full code with sections)
    """

    extensions = ['.xml']
    name = "legifrance"

    # XML namespaces commonly used
    NAMESPACES = {
        'default': '',
    }

    def parse(
        self,
        path: Path,
        metadata: Optional[dict] = None
    ) -> Iterator[Chunk]:
        """
        Parse a Légifrance XML file into chunks.

        Each article becomes one chunk with rich metadata.
        """
        metadata = metadata or {}
        path = Path(path)

        try:
            tree = ET.parse(path)
            root = tree.getroot()
        except ET.ParseError as e:
            raise ValueError(f"Invalid XML file: {e}")

        # Detect format and delegate
        root_tag = root.tag.split('}')[-1]  # Remove namespace prefix

        if root_tag in ('TEXTE_VERSION', 'TEXTELR'):
            yield from self._parse_texte_version(root, path, metadata)
        elif root_tag == 'ARTICLE':
            yield from self._parse_single_article(root, path, metadata)
        elif root_tag in ('CODE', 'LEGI'):
            yield from self._parse_code(root, path, metadata)
        else:
            # Generic fallback: find all ARTICLE elements
            yield from self._parse_generic(root, path, metadata)

    def _parse_texte_version(
        self,
        root: ET.Element,
        path: Path,
        metadata: dict
    ) -> Iterator[Chunk]:
        """Parse TEXTE_VERSION format (consolidated text with articles)."""

        # Extract document metadata
        doc_meta = self._extract_meta(root)
        doc_title = doc_meta.get('titre', path.stem)
        doc_slug = slugify(doc_title)

        # Find all articles
        articles = root.findall('.//ARTICLE') or root.findall('.//article')

        for idx, article in enumerate(articles):
            chunk = self._article_to_chunk(
                article=article,
                index=idx,
                doc_title=doc_title,
                doc_slug=doc_slug,
                doc_meta=doc_meta,
                path=path,
                metadata=metadata
            )
            if chunk:
                yield chunk

    def _parse_single_article(
        self,
        root: ET.Element,
        path: Path,
        metadata: dict
    ) -> Iterator[Chunk]:
        """Parse a single ARTICLE element."""
        doc_title = metadata.get('title', path.stem)
        doc_slug = slugify(doc_title)
        doc_meta = self._extract_meta(root)

        chunk = self._article_to_chunk(
            article=root,
            index=0,
            doc_title=doc_title,
            doc_slug=doc_slug,
            doc_meta=doc_meta,
            path=path,
            metadata=metadata
        )
        if chunk:
            yield chunk

    def _parse_code(
        self,
        root: ET.Element,
        path: Path,
        metadata: dict
    ) -> Iterator[Chunk]:
        """Parse CODE format (full code with hierarchical sections)."""

        # Extract code metadata
        doc_meta = self._extract_meta(root)
        doc_title = doc_meta.get('titre', path.stem)
        doc_slug = slugify(doc_title)

        # Track section hierarchy
        current_section = []

        def process_element(elem: ET.Element, depth: int = 0):
            """Recursively process elements."""
            tag = elem.tag.split('}')[-1].upper()

            # Section elements
            if tag in ('SECTION_TA', 'SECTION', 'TITRE', 'CHAPITRE', 'PARTIE'):
                section_title = self._get_element_text(elem, 'TITRE_TA') or \
                               self._get_element_text(elem, 'INTITULE') or \
                               elem.get('titre', '')
                if section_title:
                    while len(current_section) > depth:
                        current_section.pop()
                    current_section.append(section_title)

            # Article elements
            elif tag == 'ARTICLE':
                yield from [self._article_to_chunk(
                    article=elem,
                    index=0,  # Will be set properly
                    doc_title=doc_title,
                    doc_slug=doc_slug,
                    doc_meta=doc_meta,
                    path=path,
                    metadata=metadata,
                    section_path=list(current_section)
                )]

            # Recurse into children
            for child in elem:
                yield from process_element(child, depth + 1)

        idx = 0
        for chunk in process_element(root):
            if chunk:
                # Update index
                chunk_dict = chunk.to_dict()
                chunk_dict['id'] = f"{doc_slug}-art-{idx:04d}"
                idx += 1
                yield Chunk(**{k: v for k, v in chunk_dict.items()})

    def _parse_generic(
        self,
        root: ET.Element,
        path: Path,
        metadata: dict
    ) -> Iterator[Chunk]:
        """Generic parser for unknown XML structures."""
        doc_title = metadata.get('title', path.stem)
        doc_slug = slugify(doc_title)
        doc_meta = self._extract_meta(root)

        # Find all article-like elements
        for tag in ['ARTICLE', 'article', 'Article', 'ART', 'art']:
            articles = root.findall(f'.//{tag}')
            for idx, article in enumerate(articles):
                chunk = self._article_to_chunk(
                    article=article,
                    index=idx,
                    doc_title=doc_title,
                    doc_slug=doc_slug,
                    doc_meta=doc_meta,
                    path=path,
                    metadata=metadata
                )
                if chunk:
                    yield chunk

    def _article_to_chunk(
        self,
        article: ET.Element,
        index: int,
        doc_title: str,
        doc_slug: str,
        doc_meta: dict,
        path: Path,
        metadata: dict,
        section_path: Optional[list] = None
    ) -> Optional[Chunk]:
        """Convert an ARTICLE element to a Chunk."""

        # Extract article number/identifier
        art_num = (
            article.get('num') or
            article.get('NUM') or
            self._get_element_text(article, 'NUM') or
            self._get_element_text(article, 'NUMERO') or
            article.get('id', '').replace('LEGIARTI', '') or
            str(index + 1)
        )

        # Extract article content
        content = (
            self._get_element_text(article, 'BLOC_TEXTUEL/CONTENU') or
            self._get_element_text(article, 'CONTENU') or
            self._get_element_text(article, 'TEXTE') or
            self._get_element_text(article, 'contenu') or
            extract_text_recursive(article)
        )

        content = clean_text(content)

        if not content or not content.strip():
            return None

        # Extract article metadata
        art_meta = self._extract_article_meta(article)

        # Build chapter title from section path or article number
        if section_path:
            chapter_title = " > ".join(section_path)
        else:
            chapter_title = f"Article {art_num}"

        # Build extended metadata for legal_fr namespace
        code_name = doc_meta.get('code') or metadata.get('code', '')
        article_ref = make_article_ref(code_name, art_num) if code_name else None

        legal_metadata = {
            "legal_fr": {
                "numero_article": art_num,
                "article_ref": article_ref,  # Stable ID for versioning
                "code": code_name,
                "date_debut": art_meta.get('date_debut'),
                "date_fin": art_meta.get('date_fin'),
                "date_publication": doc_meta.get('date_publi') or art_meta.get('date_publication'),
                "etat": art_meta.get('etat', 'VIGUEUR'),
                "texte_modificateur": art_meta.get('texte_modificateur'),  # "Loi 2023-1322..."
                "cid": art_meta.get('cid', ''),
                "id_article": art_meta.get('id', ''),
            }
        }

        # Merge with user-provided metadata
        if metadata.get('extended'):
            legal_metadata.update(metadata['extended'])

        return Chunk(
            id=f"{doc_slug}-art{art_num}-{index:04d}",
            content=content,
            book_title=doc_title,
            book_slug=doc_slug,
            book_file=path.name,
            chapter_title=chapter_title,
            chapter_num=index + 1,
            page_start=index + 1,  # No real page numbers in XML
            page_end=index + 1,
            paragraph=1,
            section_type="article",
            content_chars=len(content),
            content_hash=content_hash(content),
            metadata=legal_metadata,
        )

    def _extract_meta(self, root: ET.Element) -> dict:
        """Extract document-level metadata."""
        meta = {}

        # Try common metadata paths
        meta_elem = root.find('.//META')
        if meta_elem is None:
            meta_elem = root.find('.//meta')
        if meta_elem is not None:
            meta['titre'] = self._get_element_text(meta_elem, 'META_SPEC/META_TEXTE_VERSION/TITRE') or \
                           self._get_element_text(meta_elem, 'TITRE') or \
                           self._get_element_text(root, 'TITRE')

            meta['code'] = self._get_element_text(meta_elem, 'META_SPEC/META_TEXTE_VERSION/TITREFULL') or \
                          root.get('nature', '')

            meta['date_publi'] = self._get_element_text(meta_elem, 'META_COMMUN/DATE_PUBLI')
            meta['date_texte'] = self._get_element_text(meta_elem, 'META_COMMUN/DATE_TEXTE')

        # Fallback to root attributes
        if not meta.get('titre'):
            meta['titre'] = root.get('titre') or root.get('TITRE') or ''

        return meta

    def _extract_article_meta(self, article: ET.Element) -> dict:
        """Extract article-level metadata."""
        meta = {}

        # ID and CID
        meta['id'] = article.get('id', '')
        meta['cid'] = (
            self._get_element_text(article, 'META/META_COMMUN/ID') or
            article.get('cid', '')
        )

        # Dates
        meta['date_debut'] = (
            self._get_element_text(article, 'META/META_SPEC/META_ARTICLE/DATE_DEBUT') or
            article.get('debut', '')
        )
        meta['date_fin'] = (
            self._get_element_text(article, 'META/META_SPEC/META_ARTICLE/DATE_FIN') or
            article.get('fin', '')
        )
        meta['date_publication'] = (
            self._get_element_text(article, 'META/META_SPEC/META_ARTICLE/DATE_PUBLI') or
            self._get_element_text(article, 'META/META_COMMUN/DATE_PUBLI') or
            ''
        )

        # State (VIGUEUR, ABROGE, etc.)
        meta['etat'] = (
            self._get_element_text(article, 'META/META_SPEC/META_ARTICLE/ETAT') or
            article.get('etat', 'VIGUEUR')
        )

        # Modification text (law/decree that modified this article)
        meta['texte_modificateur'] = (
            self._get_element_text(article, 'META/META_SPEC/META_ARTICLE/ORIGINE_PUBLI') or
            self._get_element_text(article, 'NOTA') or  # Often contains modification info
            ''
        )

        # References to other articles
        liens = article.findall('.//LIEN') or article.findall('.//lien')
        meta['references'] = [
            lien.get('cidtexte') or lien.get('id') or lien.text
            for lien in liens
            if lien.get('cidtexte') or lien.get('id') or lien.text
        ]

        return meta

    def _get_element_text(self, parent: ET.Element, path: str) -> str:
        """Get text content of a nested element by path."""
        elem = parent.find(path)
        if elem is not None:
            return clean_text(extract_text_recursive(elem))
        # Try case variations
        for variant in [path.lower(), path.upper()]:
            elem = parent.find(variant)
            if elem is not None:
                return clean_text(extract_text_recursive(elem))
        return ""

    def extract_metadata(self, path: Path) -> dict:
        """Extract metadata from XML file without full parsing."""
        try:
            # Parse only the beginning of the file
            for event, elem in ET.iterparse(path, events=['start']):
                if elem.tag.endswith('META') or elem.tag == 'META':
                    meta = self._extract_meta(elem)
                    return {
                        "source_file": path.name,
                        "book_slug": slugify(meta.get('titre', path.stem)),
                        "title": meta.get('titre', path.stem),
                    }
                # Don't parse the whole file
                if elem.tag.endswith('ARTICLE') or elem.tag == 'ARTICLE':
                    break
        except ET.ParseError:
            pass

        return {
            "source_file": path.name,
            "book_slug": slugify(path.stem),
        }


# Utility function for generating Légifrance links
def lien_legifrance(article: str, code: str = "cgi") -> str:
    """
    Generate a Légifrance search URL for an article.

    Args:
        article: Article number (e.g., "39 decies A")
        code: Code identifier (default: "cgi" for Code Général des Impôts)

    Returns:
        URL string for Légifrance search
    """
    from urllib.parse import quote
    code_names = {
        "cgi": "code général des impôts",
        "cc": "code civil",
        "cp": "code pénal",
        "ct": "code du travail",
        "ccom": "code de commerce",
    }
    code_name = code_names.get(code.lower(), code)
    query = f"article {article} {code_name}"
    return f"https://www.legifrance.gouv.fr/search/all?tab_selection=all&searchField=ALL&query={quote(query)}"
