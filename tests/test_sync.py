"""Tests for rtfm.core.sync and PlainTextParser."""

import pytest
import tempfile
from pathlib import Path

from rtfm import Library
from rtfm.core.sync import (
    compute_file_hash,
    scan_directory,
    compute_diff,
    sync,
    SyncDiff,
    SyncResult,
)
from rtfm.parsers.plaintext import PlainTextParser, _chunk_lines


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def sync_db():
    """Temporary DB for sync tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    lib = Library(db_path)
    yield lib
    lib.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def project_dir(tmp_path):
    """Create a small project directory with mixed file types."""
    # Markdown file
    (tmp_path / "README.md").write_text(
        "# My Project\n\nThis is a test project with some content.\n"
        "It has enough text to be indexed properly by the parser.\n"
        "We need a bit more content here to make sure it meets the minimum.\n"
    )
    # Python file
    (tmp_path / "main.py").write_text(
        "def hello():\n    print('Hello, world!')\n\n"
        "def goodbye():\n    print('Goodbye, world!')\n\n"
        "if __name__ == '__main__':\n    hello()\n    goodbye()\n"
    )
    # Text file
    (tmp_path / "notes.txt").write_text(
        "Some notes about the project.\nLine 2.\nLine 3.\n"
        "More notes to ensure we have enough content for indexing.\n"
    )
    # A file that should be excluded
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "lib.py").write_text("# should be excluded\n")
    # A nested directory
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "utils.py").write_text(
        "def add(a, b):\n    return a + b\n\n"
        "def mul(a, b):\n    return a * b\n"
    )
    return tmp_path


# ── compute_file_hash ─────────────────────────────────────────────────────

class TestComputeFileHash:
    def test_deterministic(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hello world")
        h1 = compute_file_hash(f)
        h2 = compute_file_hash(f)
        assert h1 == h2

    def test_different_content(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello")
        f2.write_text("world")
        assert compute_file_hash(f1) != compute_file_hash(f2)

    def test_md5_format(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("test")
        h = compute_file_hash(f)
        assert len(h) == 32  # MD5 hex digest


# ── scan_directory ────────────────────────────────────────────────────────

class TestScanDirectory:
    def test_finds_files(self, project_dir):
        files = scan_directory(project_dir)
        names = {f.name for f in files}
        assert "README.md" in names
        assert "main.py" in names
        assert "notes.txt" in names
        assert "utils.py" in names

    def test_excludes_venv(self, project_dir):
        files = scan_directory(project_dir)
        names = {f.name for f in files}
        assert "lib.py" not in names

    def test_extension_filter(self, project_dir):
        files = scan_directory(project_dir, extensions={".py"})
        for f in files:
            assert f.suffix == ".py"
        names = {f.name for f in files}
        assert "main.py" in names
        assert "README.md" not in names

    def test_no_dot_prefix(self, project_dir):
        """Extensions without dot prefix should work."""
        files = scan_directory(project_dir, extensions={"py"})
        for f in files:
            assert f.suffix == ".py"


# ── compute_diff ──────────────────────────────────────────────────────────

class TestComputeDiff:
    def test_all_new(self, project_dir):
        files = scan_directory(project_dir)
        diff = compute_diff(files, indexed_files={}, root=project_dir)
        assert len(diff.added) == len(files)
        assert diff.modified == []
        assert diff.removed == []
        assert diff.unchanged == 0

    def test_unchanged(self, project_dir):
        files = scan_directory(project_dir)
        # Simulate all files already indexed with correct hash
        indexed = {}
        for f in files:
            rel = str(f.relative_to(project_dir))
            indexed[rel] = {"file_hash": compute_file_hash(f)}

        diff = compute_diff(files, indexed, project_dir)
        assert diff.added == []
        assert diff.modified == []
        assert diff.removed == []
        assert diff.unchanged == len(files)

    def test_modified(self, project_dir):
        files = scan_directory(project_dir)
        indexed = {}
        for f in files:
            rel = str(f.relative_to(project_dir))
            indexed[rel] = {"file_hash": "old_hash_that_doesnt_match"}

        diff = compute_diff(files, indexed, project_dir)
        assert len(diff.modified) == len(files)
        assert diff.added == []

    def test_removed(self, project_dir):
        files = scan_directory(project_dir)
        indexed = {
            "gone.md": {"file_hash": "abc123"},
        }
        for f in files:
            rel = str(f.relative_to(project_dir))
            indexed[rel] = {"file_hash": compute_file_hash(f)}

        diff = compute_diff(files, indexed, project_dir)
        assert diff.removed == ["gone.md"]
        assert diff.unchanged == len(files)


# ── sync full flow ────────────────────────────────────────────────────────

class TestSync:
    def test_first_sync(self, sync_db, project_dir):
        result = sync(
            sync_db, project_dir,
            corpus="test",
            generate_embeddings=False,
        )
        assert result.added > 0
        assert result.modified == 0
        assert result.removed == 0
        assert result.errors == []

        # DB should have data
        stats = sync_db.get_stats()
        assert stats["chunks"] > 0
        assert stats["books"] > 0

    def test_incremental_no_change(self, sync_db, project_dir):
        """Second sync with no changes should report all unchanged."""
        sync(sync_db, project_dir, corpus="test", generate_embeddings=False)

        result = sync(
            sync_db, project_dir,
            corpus="test",
            generate_embeddings=False,
        )
        assert result.added == 0
        assert result.modified == 0
        assert result.unchanged > 0

    def test_incremental_modified(self, sync_db, project_dir):
        """Modifying a file should be detected on second sync."""
        sync(sync_db, project_dir, corpus="test", generate_embeddings=False)

        # Modify a file
        (project_dir / "main.py").write_text("# modified\nprint('changed')\n")

        result = sync(
            sync_db, project_dir,
            corpus="test",
            generate_embeddings=False,
        )
        assert result.modified == 1

    def test_incremental_removed(self, sync_db, project_dir):
        """Deleting a file should be detected on second sync."""
        sync(sync_db, project_dir, corpus="test", generate_embeddings=False)

        # Remove a file
        (project_dir / "notes.txt").unlink()

        result = sync(
            sync_db, project_dir,
            corpus="test",
            generate_embeddings=False,
        )
        assert result.removed == 1

    def test_dry_run(self, sync_db, project_dir):
        """Dry run should report changes without modifying DB."""
        result = sync(
            sync_db, project_dir,
            corpus="test",
            dry_run=True,
            generate_embeddings=False,
        )
        assert result.added > 0

        # DB should still be empty
        stats = sync_db.get_stats()
        assert stats["chunks"] == 0

    def test_files_list(self, sync_db, project_dir):
        """Sync specific files only (git hook mode)."""
        result = sync(
            sync_db, project_dir,
            corpus="test",
            generate_embeddings=False,
            files=["main.py"],
        )
        assert result.added == 1
        # Only main.py should be indexed
        books = sync_db.list_books()
        assert len(books) == 1


# ── PlainTextParser ───────────────────────────────────────────────────────

class TestPlainTextParser:
    def test_parse_python(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def foo():\n    return 42\n\ndef bar():\n    return 7\n")

        parser = PlainTextParser()
        chunks = list(parser.parse(f))
        assert len(chunks) >= 1
        assert "foo" in chunks[0].content

    def test_parse_txt(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Hello world.\nThis is a text file.\n")

        parser = PlainTextParser()
        chunks = list(parser.parse(f))
        assert len(chunks) >= 1
        assert "Hello" in chunks[0].content

    def test_chunk_lines_respects_target(self):
        """Chunks should be approximately TARGET_CHUNK_CHARS."""
        text = "\n".join(f"Line number {i}: some content here." for i in range(100))
        chunks = _chunk_lines(text)
        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= 1500  # generous upper bound

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")

        parser = PlainTextParser()
        chunks = list(parser.parse(f))
        assert chunks == []

    def test_extract_metadata(self, tmp_path):
        f = tmp_path / "utils.py"
        f.write_text("# utility code\n")

        parser = PlainTextParser()
        meta = parser.extract_metadata(f)
        assert meta["title"] == "utils.py"
        assert "book_slug" in meta

    def test_can_parse(self):
        parser = PlainTextParser()
        assert parser.can_parse(Path("test.py"))
        assert parser.can_parse(Path("test.js"))
        assert parser.can_parse(Path("test.txt"))
        assert not parser.can_parse(Path("test.pdf"))
        assert not parser.can_parse(Path("test.md"))  # handled by MarkdownParser


# ── Library sync method ──────────────────────────────────────────────────

class TestLibraryFileTracking:
    def test_list_indexed_files_empty(self, sync_db):
        result = sync_db.list_indexed_files()
        assert result == {}

    def test_update_and_list(self, sync_db):
        sync_db.update_indexed_file(
            filepath="src/main.py",
            file_hash="abc123",
            corpus="test",
            book_slug="src-main-py",
            file_size=100,
        )
        indexed = sync_db.list_indexed_files()
        assert "src/main.py" in indexed
        assert indexed["src/main.py"]["file_hash"] == "abc123"
        assert indexed["src/main.py"]["corpus"] == "test"

    def test_remove_file(self, sync_db, tmp_path):
        """Test removing a file that was synced."""
        f = tmp_path / "test.txt"
        f.write_text("Some content for the test file to index properly.\n" * 5)

        # Ingest and track
        sync_db.ingest(f, corpus="test")
        sync_db.update_indexed_file(
            filepath="test.txt",
            file_hash="abc",
            corpus="test",
            book_slug="test-txt",  # match the slug from PlainTextParser
        )

        # Verify it's there
        assert sync_db.get_stats()["chunks"] > 0

        # Remove
        result = sync_db.remove_file("test.txt")
        assert result is True

        # Tracking should be gone
        indexed = sync_db.list_indexed_files()
        assert "test.txt" not in indexed


class TestSyncResult:
    def test_str(self):
        r = SyncResult(added=3, modified=1, removed=0, unchanged=10)
        assert "+3" in str(r)
        assert "~1" in str(r)
        assert "=10" in str(r)

    def test_to_dict(self):
        r = SyncResult(added=1, modified=2, removed=3, unchanged=4)
        d = r.to_dict()
        assert d["added"] == 1
        assert d["modified"] == 2
        assert d["removed"] == 3
        assert d["unchanged"] == 4
