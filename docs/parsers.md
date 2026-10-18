---
title: RTFM Parsers Guide — 24 built-in formats and how to add your own
description: >-
  Complete reference for RTFM's 24 built-in parsers (Markdown, Python AST,
  LaTeX, YAML, JSON, TOML, PDF, XML, HTML, SQLite, Jupyter, CSV, XLSX,
  EPUB, MOBI, FB2, DJVU, DOCX, ODT, RTF, MIDI, audio, Shell, plain text). How to write a custom parser in ~50 lines.
---

# Parsers Guide

## How Parsers Work

Each parser converts a file format into `Chunk` objects — content segments with metadata. The `ParserRegistry` routes files to parsers by extension.

```python
@ParserRegistry.register
class MyParser(BaseParser):
    extensions = ['.xyz']
    name = "xyz"

    def parse(self, path, metadata=None):
        # yield Chunk objects
        ...

    def extract_edges(self, path, metadata=None):
        # return list[EdgeCandidate] (optional)
        ...
```

## Built-in Parsers

### Markdown (`rtfm/parsers/markdown.py`)

- **Extensions**: `.md`, `.markdown`
- **Strategy**: Split by headers (H1-H6), merge/split by size (target 1500 chars)
- **Edges**: Markdown links `[text](path)`, wikilinks `[[target]]`
- **Metadata**: YAML frontmatter extracted and stored in chunk metadata
- **Wikilinks**: Fully supported — `[[Note]]`, `[[folder/Note]]`, `[[Note|display]]`, `[[Note#Section]]`

### Python (`rtfm/parsers/python.py`)

- **Extensions**: `.py`
- **Strategy**: AST-based — each class/function = 1 chunk
- **Edges**: `import x`, `from x import y` → `EdgeCandidate(relation_type="import")`

### LaTeX (`rtfm/parsers/latex.py`)

- **Extensions**: `.tex`, `.latex`
- **Strategy**: Split by `\section`, `\chapter`, `\subsection`
- **Edges**: `\input{}`, `\include{}` → "include"; `\cite{}` → "cite"

### YAML (`rtfm/parsers/yaml_parser.py`)

- **Extensions**: `.yaml`, `.yml`
- **Strategy**: One chunk per top-level key

### JSON (`rtfm/parsers/json_parser.py`)

- **Extensions**: `.json`
- **Strategy**: Top-level keys or array elements

### TOML (`rtfm/parsers/toml_parser.py`)

- **Extensions**: `.toml`
- **Strategy**: One chunk per top-level table; uses stdlib `tomllib` (Python 3.11+) with `tomli` fallback
- **Edges**: Dependencies → `EdgeCandidate(relation_type="depends_on")` for `pyproject.toml` (PEP 621, Poetry, build-system) and `Cargo.toml`

### Shell (`rtfm/parsers/shell.py`)

- **Extensions**: `.sh`, `.bash`, `.zsh`
- **Strategy**: Function-aware chunking

### PDF (`rtfm/parsers/pdf.py`)

- **Extensions**: `.pdf`
- **Strategy**: Page-based (requires `pip install rtfm-ai[pdf]`)

### Legifrance XML (`rtfm/parsers/xml_legifrance.py`)

- **Extensions**: `.xml`
- **Strategy**: French legal codes (LEGI format), article-level chunks

### BOFiP HTML (`rtfm/parsers/html_bofip.py`)

- **Extensions**: `.html`, `.htm`
- **Strategy**: French tax doctrine paragraphs

### SQLite (`rtfm/parsers/sqlite_parser.py`)

- **Extensions**: `.sqlite`, `.sqlite3`, `.db`
- **Strategy**: Read-only URI connection. Emits an overview chunk (tables, views, indexes, triggers + row counts), then per table a schema chunk and data chunks covering **every row**, streamed so a huge table never loads at once. Views and triggers as separate chunks. BLOB columns keep a `<blob NB>` placeholder. FTS5 shadow tables filtered.
- **Edges**: Foreign keys → `EdgeCandidate(relation_type="fk")`
- **`.db` guard**: validated by SQLite magic bytes (`SQLite format 3\x00`) to avoid false positives on unrelated `.db` files

### Jupyter (`rtfm/parsers/jupyter.py`)

- **Extensions**: `.ipynb`
- **Strategy**: Walk cells in order, group by markdown heading. Each section = one chunk containing markdown narration + following code cells (fenced as ```python). Cell outputs are dropped.

### CSV / TSV (`rtfm/parsers/csv_parser.py`)

- **Extensions**: `.csv`, `.tsv`
- **Strategy**: Sniff dialect (delimiter), emit an overview chunk (column names + type inference: int/float/bool/text + row count), then data chunks covering **every row**, each repeating the header so a matched value keeps its column. Streamed: memory stays bounded on million-row files.

### XLSX (`rtfm/parsers/xlsx.py`)

- **Extensions**: `.xlsx`
- **Strategy**: Per-workbook overview + per-sheet schema + data chunks covering **every row** of each sheet (header repeated per chunk). Uses `read_only=True` so massive workbooks don't load fully in memory.
- **Optional dependency**: `pip install rtfm-ai[xlsx]` (openpyxl)

### EPUB (`rtfm/parsers/epub.py`)

- **Extensions**: `.epub`
- **Strategy**: Each spine item (chapter) is stripped of its XHTML markup and chunked by paragraph. Title and author read from the OPF metadata.
- **Optional dependency**: `pip install rtfm-ai[epub]` (ebooklib + beautifulsoup4)

### MOBI / AZW (`rtfm/parsers/mobi_parser.py`)

- **Extensions**: `.mobi`, `.azw`, `.azw3`
- **Strategy**: The book is unpacked to HTML, stripped, then chunked by paragraph. DRM-protected files are refused with a clear error; DRM is never bypassed.
- **Optional dependency**: `pip install rtfm-ai[mobi]` (mobi + beautifulsoup4)

### FictionBook (`rtfm/parsers/fb2.py`)

- **Extensions**: `.fb2`
- **Strategy**: Each `<section>` is a unit, headed by its `<title>` when present. Standard library only.

### DJVU (`rtfm/parsers/djvu.py`)

- **Extensions**: `.djvu`, `.djv`
- **Strategy**: Text layer read page by page through the `djvutxt` command, chunked like PDF pages.
- **System dependency**: `djvulibre-bin` (`apt install djvulibre-bin`)

### DOCX (`rtfm/parsers/docx.py`)

- **Extensions**: `.docx`
- **Strategy**: Paragraphs in document order; Heading 1/2/3 styles start a new section. Tables flattened to `cell | cell | …`.
- **Optional dependency**: `pip install rtfm-ai[office]` (python-docx)

### ODT (`rtfm/parsers/odt.py`)

- **Extensions**: `.odt`
- **Strategy**: Headings start sections according to their outline level. Tables flattened to `cell | cell`.
- **Optional dependency**: `pip install rtfm-ai[office]` (odfpy)

### RTF (`rtfm/parsers/rtf.py`)

- **Extensions**: `.rtf`
- **Strategy**: Markup stripped to plain text, chunked on paragraph boundaries (RTF has no standard hierarchy).
- **Optional dependency**: `pip install rtfm-ai[office]` (striprtf)

### MIDI (`rtfm/parsers/midi.py`)

- **Extensions**: `.mid`, `.midi`, `.kar`, `.rmi`
- **Strategy**: One overview chunk (title, tempo, metre, key, duration, instruments per channel) and one chunk per track that carries anything: its range, markers and, in karaoke files, its lyrics. Standard library only; damaged tracks are read up to the damage.

### Audio (`rtfm/parsers/audio.py`)

- **Extensions**: `.mp3`, `.flac`, `.ogg`, `.oga`, `.opus`, `.m4a`, `.m4b`, `.aac`, `.wav`, `.aif`, `.aiff`, `.aifc`, `.wma`, `.ape`, `.wv`, `.mpc`, `.dsf`, `.tta`
- **Strategy**: One chunk of tags (title, artist, album, composer, genre, year, comments) and stream facts (duration, sample rate, channels, bit rate), plus one for the lyrics when present. Speech is not transcribed.
- **Optional dependency**: `pip install rtfm-ai[audio]` (mutagen)

### Plain text (`rtfm/parsers/plaintext.py`)

- **Extensions**: `.js`, `.mjs`, `.cjs`, `.jsx`, `.ts`, `.mts`, `.cts`, `.tsx`, `.rs`, `.go`, `.java`, `.kt`, `.scala`, `.swift`, `.c`, `.h`, `.cpp`, `.hpp`, `.rb`, `.php`, `.pl`, `.lua`, `.r`, `.sql`, `.css`, `.cfg`, `.txt` (also acts as fallback for `.toml` when `tomllib`/`tomli` is unavailable)
- **Strategy**: Line-boundary chunks (~500 chars)

## Writing a Custom Parser

See [[CONTRIBUTING|Contributing Guide]] for the full walkthrough. The key contract:

1. Extend `BaseParser`
2. Set `extensions` and `name`
3. Implement `parse(path, metadata)` → yields `Chunk` objects
4. Optionally implement `extract_edges(path, metadata)` → returns `list[EdgeCandidate]`
5. Decorate with `@ParserRegistry.register`

The parser is automatically discovered — no configuration needed.
