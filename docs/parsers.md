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

### Plain text (`rtfm/parsers/plaintext.py`)

- **Extensions**: `.js`, `.ts`, `.rs`, `.go`, `.java`, `.c`, `.cpp`, `.rb`, `.php`, `.css`, `.toml`, `.cfg`, `.txt`
- **Strategy**: Line-boundary chunks (~500 chars)

## Writing a Custom Parser

See [[CONTRIBUTING|Contributing Guide]] for the full walkthrough. The key contract:

1. Extend `BaseParser`
2. Set `extensions` and `name`
3. Implement `parse(path, metadata)` → yields `Chunk` objects
4. Optionally implement `extract_edges(path, metadata)` → returns `list[EdgeCandidate]`
5. Decorate with `@ParserRegistry.register`

The parser is automatically discovered — no configuration needed.
