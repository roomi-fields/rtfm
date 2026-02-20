# Contributing to RTFM

## Quick Setup

```bash
git clone https://github.com/roomi-fields/rtfm.git
cd rtfm
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev,mcp]"
pytest tests/ -v
```

## Adding a Parser

RTFM's parser system is extensible. To add support for a new file type:

1. Create `rtfm/parsers/your_parser.py`
2. Extend `BaseParser` from `rtfm/parsers/base.py`
3. Register with `@ParserRegistry.register`
4. Import in `rtfm/parsers/__init__.py` (before `plaintext` — order matters)
5. Add tests in `tests/test_smart_parsers.py` or a dedicated test file

See existing parsers for examples — `markdown.py` is the simplest reference, `python.py` shows AST-based chunking.

## Running Tests

```bash
pytest tests/ -v
pytest tests/ -v -k "test_search"  # run specific tests
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
