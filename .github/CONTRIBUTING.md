# Contributing to RTFM

## The easiest way to contribute: write a parser

RTFM's real power comes from its parser ecosystem. If you work in a domain with specific file formats — medical (HL7/FHIR), financial (XBRL), scientific (NetCDF), music (MusicXML), architecture (AsciiDoc), or anything else — writing a parser is the most impactful contribution you can make.

A parser is typically 30-80 lines of Python. See `rtfm/parsers/markdown.py` for the simplest example.

### Parser template

```python
from rtfm.parsers.base import BaseParser, ParserRegistry
from rtfm.core.models import Chunk

@ParserRegistry.register
class MyFormatParser(BaseParser):
    extensions = ['.myext']
    name = "myformat"

    def parse(self, path, metadata=None):
        metadata = metadata or {}
        content = path.read_text()
        # Your parsing logic here
        yield Chunk(
            id="unique-chunk-id",
            content=content,
            book_title=metadata.get('title', path.stem),
            book_slug=path.stem.lower(),
            page_start=1,
            page_end=1,
        )
```

Submit a PR with your parser + tests, and your domain's AI agents get superpowers.

## Quick Setup

```bash
git clone https://github.com/roomi-fields/rtfm.git
cd rtfm
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev,mcp]"
pytest rtfm/tests/ -v
```

## Adding a Parser

RTFM's parser system is extensible. To add support for a new file type:

1. Create `rtfm/parsers/your_parser.py`
2. Extend `BaseParser` from `rtfm/parsers/base.py`
3. Register with `@ParserRegistry.register`
4. Import in `rtfm/parsers/__init__.py` (before `plaintext` — order matters)
5. Add tests in `rtfm/tests/test_smart_parsers.py` or a dedicated test file

See existing parsers for examples — `markdown.py` is the simplest reference, `python.py` shows AST-based chunking.

## Running Tests

```bash
pytest rtfm/tests/ -v
pytest rtfm/tests/ -v -k "test_search"  # run specific tests
```

## Code Style

- Python 3.10+
- Type hints encouraged
- Docstrings for public methods

## Reporting Issues

Please include:
- RTFM version (`rtfm --version`)
- Python version
- OS
- Steps to reproduce
- Expected vs actual behavior
