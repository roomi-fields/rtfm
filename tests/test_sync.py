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
    _path_to_slug,
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
        assert diff.moved == []
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
        assert diff.moved == []
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
        assert diff.moved == []
        assert diff.unchanged == len(files)

    def test_move_detected(self, tmp_path):
        """A file that moved (same hash, different path) is detected as move."""
        # Create file at new location
        (tmp_path / "new_dir").mkdir()
        f = tmp_path / "new_dir" / "moved.txt"
        f.write_text("same content")
        file_hash = compute_file_hash(f)

        # Simulate old location in DB with same hash
        indexed = {
            "old_dir/moved.txt": {"file_hash": file_hash},
        }

        diff = compute_diff([f], indexed, tmp_path)
        assert len(diff.moved) == 1
        assert diff.moved[0][0] == "old_dir/moved.txt"  # old path
        assert diff.moved[0][1] == f  # new Path
        assert diff.added == []  # NOT treated as added
        assert diff.removed == []  # NOT treated as removed

    def test_move_vs_different_content(self, tmp_path):
        """If hash differs, it's a remove + add, not a move."""
        f = tmp_path / "new.txt"
        f.write_text("new content")

        indexed = {
            "old.txt": {"file_hash": "different_hash_entirely"},
        }

        diff = compute_diff([f], indexed, tmp_path)
        assert diff.moved == []
        assert len(diff.added) == 1
        assert diff.removed == ["old.txt"]


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
        assert result.moved == 0
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
        assert result.moved == 0
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

    def test_incremental_moved(self, sync_db, project_dir):
        """Moving a file should be detected and handled without re-ingesting."""
        sync(sync_db, project_dir, corpus="test", generate_embeddings=False)

        # Get stats before move
        stats_before = sync_db.get_stats()

        # Move notes.txt to docs/notes.txt
        docs = project_dir / "docs"
        docs.mkdir()
        (project_dir / "notes.txt").rename(docs / "notes.txt")

        result = sync(
            sync_db, project_dir,
            corpus="test",
            generate_embeddings=False,
        )
        assert result.moved == 1
        assert result.added == 0
        assert result.removed == 0

        # Chunk count should be unchanged (no re-ingestion)
        stats_after = sync_db.get_stats()
        assert stats_after["chunks"] == stats_before["chunks"]

        # New path should be tracked
        indexed = sync_db.list_indexed_files(corpus="test")
        assert "notes.txt" not in indexed
        assert "docs/notes.txt" in indexed

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

    def test_on_progress_callback(self, sync_db, project_dir):
        """on_progress is called for each file processed."""
        events = []

        def recorder(action, filepath, detail):
            events.append((action, filepath, detail))

        result = sync(
            sync_db, project_dir,
            corpus="test",
            generate_embeddings=False,
            on_progress=recorder,
        )
        # Should have one event per added file
        assert len(events) == result.added
        for action, filepath, detail in events:
            assert action == "add"
            assert filepath  # non-empty path
            assert "chunks" in detail

    def test_force_reindex(self, sync_db, project_dir):
        """--force re-indexes files even if hash unchanged."""
        # First sync
        r1 = sync(sync_db, project_dir, corpus="test", generate_embeddings=False)
        assert r1.added > 0

        # Normal second sync: everything unchanged
        r2 = sync(sync_db, project_dir, corpus="test", generate_embeddings=False)
        assert r2.modified == 0
        assert r2.unchanged > 0

        # Force sync: everything re-processed as modified
        r3 = sync(sync_db, project_dir, corpus="test", generate_embeddings=False, force=True)
        assert r3.modified == r2.unchanged
        assert r3.unchanged == 0

    def test_move_progress_callback(self, sync_db, project_dir):
        """on_progress reports move events."""
        sync(sync_db, project_dir, corpus="test", generate_embeddings=False)

        events = []
        def recorder(action, filepath, detail):
            events.append((action, filepath, detail))

        # Move a file
        docs = project_dir / "docs"
        docs.mkdir()
        (project_dir / "notes.txt").rename(docs / "notes.txt")

        sync(
            sync_db, project_dir,
            corpus="test",
            generate_embeddings=False,
            on_progress=recorder,
        )
        move_events = [e for e in events if e[0] == "move"]
        assert len(move_events) == 1
        assert "notes.txt" in move_events[0][1]


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
        f = tmp_path / "empty.txt"
        f.write_text("")

        parser = PlainTextParser()
        chunks = list(parser.parse(f))
        assert chunks == []

    def test_extract_metadata(self, tmp_path):
        f = tmp_path / "utils.cfg"
        f.write_text("# utility code\n")

        parser = PlainTextParser()
        meta = parser.extract_metadata(f)
        assert meta["title"] == "utils.cfg"
        assert "book_slug" in meta

    def test_can_parse(self):
        parser = PlainTextParser()
        assert parser.can_parse(Path("test.js"))
        assert parser.can_parse(Path("test.txt"))
        assert not parser.can_parse(Path("test.pdf"))
        assert not parser.can_parse(Path("test.md"))  # handled by MarkdownParser
        assert not parser.can_parse(Path("test.py"))  # handled by PythonParser
        assert not parser.can_parse(Path("test.sh"))  # handled by ShellParser
        assert not parser.can_parse(Path("test.yaml"))  # handled by YAMLParser
        assert not parser.can_parse(Path("test.json"))  # handled by JSONParser


# ── Library file tracking ────────────────────────────────────────────────

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
            book_slug="test-txt",
        )

        # Verify it's there
        assert sync_db.get_stats()["chunks"] > 0

        # Remove
        result = sync_db.remove_file("test.txt")
        assert result is True

        # Tracking should be gone
        indexed = sync_db.list_indexed_files()
        assert "test.txt" not in indexed

    def test_move_file(self, sync_db, tmp_path):
        """Test move_file updates tracking and book slug."""
        f = tmp_path / "test.txt"
        f.write_text("Some content for the test file to index properly.\n" * 5)

        # Ingest and track (pass book_slug so parser uses it)
        sync_db.ingest(f, corpus="test", metadata={"book_slug": "test-txt"})
        sync_db.update_indexed_file(
            filepath="test.txt",
            file_hash="abc",
            corpus="test",
            book_slug="test-txt",
        )

        # Move
        result = sync_db.move_file("test.txt", "docs/test.txt", "docs--test-txt")
        assert result is True

        # Old path gone, new path tracked
        indexed = sync_db.list_indexed_files()
        assert "test.txt" not in indexed
        assert "docs/test.txt" in indexed
        assert indexed["docs/test.txt"]["book_slug"] == "docs--test-txt"

        # Book slug should be updated
        books = sync_db.list_books()
        slugs = {b["slug"] for b in books}
        assert "docs--test-txt" in slugs
        assert "test-txt" not in slugs


# ── _path_to_slug ────────────────────────────────────────────────────────

class TestPathToSlug:
    def test_root_file_no_corpus(self):
        assert _path_to_slug("README.md") == "readme"

    def test_root_file_with_corpus(self):
        slug = _path_to_slug("README.md", corpus="pub")
        assert slug == "pub--readme"

    def test_subdirectory_with_corpus(self):
        slug = _path_to_slug("_en/B4_Flags.md", corpus="pub")
        assert slug == "pub-en--b4_flags"

    def test_subdirectory_no_corpus(self):
        slug = _path_to_slug("_en/B4_Flags.md")
        assert slug == "en--b4_flags"

    def test_nested_subdirectory(self):
        slug = _path_to_slug("src/utils/helper.py", corpus="proj")
        assert "proj" in slug
        assert "src" in slug
        assert "utils" in slug
        assert "helper" in slug

    def test_same_name_different_dirs(self):
        """Same filename in different dirs → different slugs."""
        slug_fr = _path_to_slug("B4_Flags.md", corpus="pub")
        slug_en = _path_to_slug("_en/B4_Flags.md", corpus="pub")
        assert slug_fr != slug_en

    def test_same_name_different_corpora(self):
        """Same filename in different corpora → different slugs."""
        slug_a = _path_to_slug("B4.md", corpus="blog-fr")
        slug_b = _path_to_slug("B4.md", corpus="blog-en")
        assert slug_a != slug_b

    def test_spaces_in_name(self):
        slug = _path_to_slug("My Document.md")
        assert " " not in slug

    def test_dot_parent(self):
        """Explicit '.' parent should be treated as root."""
        slug = _path_to_slug("./README.md")
        assert _path_to_slug("./README.md") == _path_to_slug("README.md")


# ── Slug collision integration ───────────────────────────────────────────

class TestSlugCollision:
    def test_sync_same_name_different_dirs(self, sync_db, tmp_path):
        """Syncing B4.md and _en/B4.md should create TWO separate books."""
        # Create FR version
        (tmp_path / "B4_Flags.md").write_text(
            "# B4 Flags et Poids\n\n"
            "Cet article traite des flags et poids dans le système BP3.\n"
            "Le système utilise des indicateurs binaires pour marquer les états.\n"
        )
        # Create EN version in subdirectory
        en_dir = tmp_path / "_en"
        en_dir.mkdir()
        (en_dir / "B4_Flags.md").write_text(
            "# B4 Flags and Weights\n\n"
            "This article discusses flags and weights in the BP3 system.\n"
            "The system uses binary indicators to mark states.\n"
        )

        result = sync(
            sync_db, tmp_path,
            corpus="test",
            generate_embeddings=False,
        )
        assert result.added == 2
        assert result.errors == []

        # Both should be tracked as separate files
        indexed = sync_db.list_indexed_files(corpus="test")
        assert "B4_Flags.md" in indexed
        assert "_en/B4_Flags.md" in indexed

        # Both should have different book slugs (corpus is in both)
        slug_fr = indexed["B4_Flags.md"]["book_slug"]
        slug_en = indexed["_en/B4_Flags.md"]["book_slug"]
        assert slug_fr != slug_en
        assert "test" in slug_fr  # corpus prefix
        assert "test" in slug_en

        # Both books should exist in the DB
        books = sync_db.list_books()
        slugs = {b["slug"] for b in books}
        assert len(slugs) >= 2

    def test_sync_same_name_same_content_different_dirs(self, sync_db, tmp_path):
        """Even identical content in different dirs creates separate books."""
        content = "# Same Title\n\nExact same content in both files.\n"
        (tmp_path / "doc.md").write_text(content)
        sub = tmp_path / "archive"
        sub.mkdir()
        (sub / "doc.md").write_text(content)

        result = sync(
            sync_db, tmp_path,
            corpus="test",
            generate_embeddings=False,
        )
        assert result.added == 2
        assert result.errors == []

        indexed = sync_db.list_indexed_files(corpus="test")
        assert indexed["doc.md"]["book_slug"] != indexed["archive/doc.md"]["book_slug"]


class TestSyncResult:
    def test_str(self):
        r = SyncResult(added=3, modified=1, removed=0, unchanged=10)
        assert "+3" in str(r)
        assert "~1" in str(r)
        assert "=10" in str(r)

    def test_str_with_moved(self):
        r = SyncResult(moved=2, unchanged=5)
        assert ">2" in str(r)

    def test_to_dict(self):
        r = SyncResult(added=1, modified=2, removed=3, moved=4, unchanged=5)
        d = r.to_dict()
        assert d["added"] == 1
        assert d["modified"] == 2
        assert d["removed"] == 3
        assert d["moved"] == 4
        assert d["unchanged"] == 5
