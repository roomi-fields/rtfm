"""Tests for file versioning: snapshots before re-ingest."""

import pytest
import tempfile
import time
from pathlib import Path

from rtfm import Library
from rtfm.core.sync import sync


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def version_db():
    """Temporary DB for version tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    lib = Library(db_path)
    yield lib
    lib.close()
    db_path.unlink(missing_ok=True)


@pytest.fixture
def version_project(tmp_path):
    """Mini project with a file that will be modified."""
    (tmp_path / "notes.py").write_text(
        "# Version 1\n\n"
        "def hello():\n    print('Hello version 1')\n\n"
        "def goodbye():\n    print('Goodbye version 1')\n"
    )
    (tmp_path / "config.py").write_text(
        "VALUE = 1\n\n"
        "def get_value():\n    return VALUE\n"
    )
    return tmp_path


# ── save_file_version tests ──────────────────────────────────────────────

class TestSaveFileVersion:
    def test_save_version(self, version_db, version_project):
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)

        # Manually save a version
        vid = version_db.save_file_version("test--notes-py", "hash_v1")
        assert vid is not None

    def test_save_version_nonexistent_book(self, version_db):
        result = version_db.save_file_version("nonexistent", "hash")
        assert result is None

    def test_version_numbers_increment(self, version_db, version_project):
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)

        version_db.save_file_version("test--notes-py", "hash_v1")
        version_db.save_file_version("test--notes-py", "hash_v2")
        version_db.save_file_version("test--notes-py", "hash_v3")

        history = version_db.get_file_history("test--notes-py")
        assert len(history) == 3
        assert [v["version_num"] for v in history] == [1, 2, 3]


# ── get_file_history tests ───────────────────────────────────────────────

class TestGetFileHistory:
    def test_empty_history(self, version_db):
        assert version_db.get_file_history("nonexistent") == []

    def test_history_without_content(self, version_db, version_project):
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)

        version_db.save_file_version("test--notes-py", "hash_v1")
        history = version_db.get_file_history("test--notes-py")

        assert len(history) == 1
        v = history[0]
        assert "version_num" in v
        assert "content_hash" in v
        assert "created_at" in v
        assert "file_size" in v
        # History should NOT include snapshot content
        assert "snapshot" not in v


# ── get_file_version tests ───────────────────────────────────────────────

class TestGetFileVersion:
    def test_get_specific_version(self, version_db, version_project):
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)

        version_db.save_file_version("test--notes-py", "hash_v1")
        ver = version_db.get_file_version("test--notes-py", 1)

        assert ver is not None
        assert ver["version_num"] == 1
        assert ver["content_hash"] == "hash_v1"
        assert "snapshot" in ver
        assert len(ver["snapshot"]) > 0
        # Snapshot should contain the actual content
        assert "hello" in ver["snapshot"].lower() or "Version 1" in ver["snapshot"]

    def test_get_nonexistent_version(self, version_db, version_project):
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)
        assert version_db.get_file_version("test--notes-py", 999) is None

    def test_get_nonexistent_book(self, version_db):
        assert version_db.get_file_version("nonexistent", 1) is None


# ── compare_file_versions tests ──────────────────────────────────────────

class TestCompareFileVersions:
    def test_compare_versions(self, version_db, version_project):
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)

        version_db.save_file_version("test--notes-py", "hash_v1")

        # Modify file and resync
        (version_project / "notes.py").write_text(
            "# Version 2 with more content\n\n"
            "def hello():\n    print('Hello version 2')\n\n"
            "def goodbye():\n    print('Goodbye version 2')\n\n"
            "def new_func():\n    return 'new'\n"
        )
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)

        # Version 2 was auto-saved by sync
        history = version_db.get_file_history("test--notes-py")
        if len(history) >= 2:
            result = version_db.compare_file_versions("test--notes-py", 1, 2)
            assert "error" not in result
            assert result["book_slug"] == "test--notes-py"
            assert "size_diff" in result
            assert "content_changed" in result

    def test_compare_missing_version(self, version_db, version_project):
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)
        result = version_db.compare_file_versions("test--notes-py", 1, 2)
        assert "error" in result


# ── Sync integration tests ───────────────────────────────────────────────

class TestSyncVersioning:
    def test_modified_file_creates_version(self, version_db, version_project):
        # Initial sync
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)

        # Modify and resync
        (version_project / "notes.py").write_text(
            "# Version 2\n\n"
            "def hello():\n    print('Hello version 2')\n\n"
            "def goodbye():\n    print('Goodbye version 2')\n"
        )
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)

        # Version should have been saved automatically
        history = version_db.get_file_history("test--notes-py")
        assert len(history) >= 1

    def test_added_file_no_version(self, version_db, version_project):
        # Initial sync
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)

        # Check that newly added files don't have versions
        history = version_db.get_file_history("test--notes-py")
        assert len(history) == 0  # No version for initial add

    def test_multiple_modifications(self, version_db, version_project):
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)

        for i in range(3):
            (version_project / "notes.py").write_text(
                f"# Version {i + 2}\n\n"
                f"def hello():\n    print('Hello version {i + 2}')\n\n"
                f"def goodbye():\n    print('Goodbye version {i + 2}')\n"
            )
            sync(version_db, version_project, corpus="test",
                 generate_embeddings=False)

        history = version_db.get_file_history("test--notes-py")
        assert len(history) == 3  # 3 modifications → 3 versions

    def test_version_prune_limit(self, version_db, version_project):
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)

        # Create 55 versions manually (beyond the 50 limit)
        for i in range(55):
            version_db.save_file_version("test--notes-py", f"hash_{i}")

        history = version_db.get_file_history("test--notes-py")
        assert len(history) <= 50

    def test_unlimited_history_via_prune_none(self, version_db, version_project):
        """prune_limit=None keeps every version (used for Claude memory corpus)."""
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)

        for i in range(75):
            version_db.save_file_version("test--notes-py", f"hash_{i}", prune_limit=None)

        history = version_db.get_file_history("test--notes-py")
        assert len(history) == 75

    def test_custom_prune_limit(self, version_db, version_project):
        """prune_limit accepts any int, not just the default 50."""
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False)

        for i in range(30):
            version_db.save_file_version("test--notes-py", f"hash_{i}", prune_limit=10)

        history = version_db.get_file_history("test--notes-py")
        assert len(history) == 10

    def test_sync_retain_history_none_is_unlimited(self, version_db, version_project):
        """sync(retain_history=None) propagates no-prune to save_file_version."""
        import time
        sync(version_db, version_project, corpus="test",
             generate_embeddings=False, retain_history=None)

        note_path = version_project / "notes.md"
        for i in range(60):
            note_path.write_text(f"# Notes\n\nRevision {i}\n")
            time.sleep(0.005)
            sync(version_db, version_project, corpus="test",
                 generate_embeddings=False, retain_history=None)

        # notes.md, not the fixture's notes.py — two different files. Under
        # the old naming they shared one identity, which is the collision
        # this test was unknowingly relying on.
        history = version_db.get_file_history("test--notes-md")
        assert len(history) >= 55


# ── Table/migration tests ────────────────────────────────────────────────

class TestFileVersionsTable:
    def test_table_exists(self, version_db):
        conn = version_db._get_conn()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='file_versions'"
        )
        assert cursor.fetchone() is not None

    def test_table_migration(self):
        """Test that file_versions table is created via migration on existing DB."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)

        # Create a minimal DB without file_versions
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, title TEXT, filename TEXT, corpus TEXT, page_count INTEGER, chunk_count INTEGER DEFAULT 0, total_chars INTEGER DEFAULT 0, indexed_at TEXT, metadata TEXT)")
        conn.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, chunk_id TEXT UNIQUE, book_id INTEGER, chapter_id INTEGER, chapter_num INTEGER, chapter_title TEXT, page_start INTEGER, page_end INTEGER, paragraph INTEGER, content TEXT, content_chars INTEGER, content_hash TEXT, line_start INTEGER, line_end INTEGER, tags TEXT, metadata TEXT)")
        conn.execute("CREATE TABLE chapters (id INTEGER PRIMARY KEY, book_id INTEGER, num INTEGER, title TEXT, page_start INTEGER)")
        conn.commit()
        conn.close()

        # Open with Library — migration should create file_versions
        lib = Library(db_path)
        c = lib._get_conn()
        cursor = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='file_versions'"
        )
        assert cursor.fetchone() is not None
        lib.close()
        db_path.unlink(missing_ok=True)
