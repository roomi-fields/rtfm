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

- **Extensions**: `.html`
- **Strategy**: French tax doctrine paragraphs

### SQLite (`rtfm/parsers/sqlite_parser.py`)

- **Extensions**: `.sqlite`, `.sqlite3`, `.db`
- **Strategy**: Read-only URI connection. Emits an overview chunk (tables, views, indexes, triggers + row counts), then per-table schema + sample chunks. Views and triggers as separate chunks. FTS5 shadow tables filtered.
- **Edges**: Foreign keys → `EdgeCandidate(relation_type="fk")`
- **`.db` guard**: validated by SQLite magic bytes (`SQLite format 3\x00`) to avoid false positives on unrelated `.db` files

### Jupyter (`rtfm/parsers/jupyter.py`)

- **Extensions**: `.ipynb`
- **Strategy**: Walk cells in order, group by markdown heading. Each section = one chunk containing markdown narration + following code cells (fenced as ```python). Cell outputs are dropped.

### CSV / TSV (`rtfm/parsers/csv_parser.py`)

- **Extensions**: `.csv`, `.tsv`
- **Strategy**: Sniff dialect (delimiter), emit overview chunk (column names + lightweight type inference: int/float/bool/text + row count) and sample chunk (first N rows formatted as a table). Big files are not fully read into memory.

### XLSX (`rtfm/parsers/xlsx.py`)

- **Extensions**: `.xlsx`
- **Strategy**: Per-workbook overview + per-sheet schema + per-sheet sample. Uses `read_only=True` so massive workbooks don't load fully in memory.
- **Optional dependency**: `pip install rtfm-ai[xlsx]` (openpyxl)

### Plain text (`rtfm/parsers/plaintext.py`)

- **Extensions**: `.js`, `.ts`, `.rs`, `.go`, `.java`, `.c`, `.cpp`, `.rb`, `.php`, `.css`, `.cfg`, `.txt` (also acts as fallback for `.toml` when `tomllib`/`tomli` is unavailable)
- **Strategy**: Line-boundary chunks (~500 chars)

## Writing a Custom Parser

See [[CONTRIBUTING|Contributing Guide]] for the full walkthrough. The key contract:

1. Extend `BaseParser`
2. Set `extensions` and `name`
3. Implement `parse(path, metadata)` → yields `Chunk` objects
4. Optionally implement `extract_edges(path, metadata)` → returns `list[EdgeCandidate]`
5. Decorate with `@ParserRegistry.register`

The parser is automatically discovered — no configuration needed.
