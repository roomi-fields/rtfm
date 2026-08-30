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
    confirm_removals,
)
from rtfm.parsers.plaintext import PlainTextParser, _chunk_lines


# ── confirm_removals: per-file deletion confirmation ─────────────────────

def test_confirm_removals_confirms_genuinely_absent(tmp_path):
    """File truly gone + readable root → confirmed for removal."""
    (tmp_path / "kept.md").write_text("x")
    confirmed, kept = confirm_removals(tmp_path, ["gone.md"])
    assert confirmed == ["gone.md"] and kept == []


def test_confirm_removals_keeps_file_that_still_exists(tmp_path):
    """File still on disk (transient scan miss) → kept, never removed."""
    (tmp_path / "here.md").write_text("x")
    confirmed, kept = confirm_removals(tmp_path, ["here.md"])
    assert confirmed == [] and kept == ["here.md"]


def test_confirm_removals_keeps_all_when_root_unreadable(tmp_path):
    """Root gone (mount down) → absence is not evidence of deletion; keep."""
    missing_root = tmp_path / "mount" / "gone"
    confirmed, kept = confirm_removals(missing_root, ["a.md", "b.md"])
    assert confirmed == [] and sorted(kept) == ["a.md", "b.md"]


def test_confirm_removals_confirms_deleted_subdirectory(tmp_path):
    """A whole subdir deleted (root still readable) → its files confirmed."""
    (tmp_path / "top.md").write_text("x")   # keeps root non-empty & readable
    confirmed, kept = confirm_removals(tmp_path, ["sub/deep/x.md"])
    assert confirmed == ["sub/deep/x.md"] and kept == []


def test_confirm_removals_force_bypasses_check(tmp_path):
    """force=True removes everything, even a file still present."""
    (tmp_path / "here.md").write_text("x")
    confirmed, kept = confirm_removals(tmp_path, ["here.md"], force=True)
    assert confirmed == ["here.md"] and kept == []


# ── text catch-all: index files with no registered parser ────────────────

def test_ingest_text_fallback_for_unknown_extension(tmp_path):
    """A textual file whose extension no parser claims (BP3 ``-gr.dhati``)
    is indexed as plain text rather than rejected."""
    f = tmp_path / "-gr.dhati"
    f.write_text("gram#1 A --> B\n\nsecond paragraph.\n")
    lib = Library(str(tmp_path / "lib.db"))
    try:
        stats = lib.ingest(f, corpus="t")
        assert stats["chunks"] >= 1
    finally:
        lib.close()


def test_ingest_skips_binary_without_failing(tmp_path):
    """A binary file selected by an index-all source is skipped cleanly —
    zero chunks, no raised error (which would fail the queue job)."""
    f = tmp_path / "song.mid"
    f.write_bytes(b"MThd\x00\x00\x00\x06\x00\x01\x00\x00")
    lib = Library(str(tmp_path / "lib.db"))
    try:
        stats = lib.ingest(f, corpus="t")
        assert stats["chunks"] == 0
        assert stats.get("skipped") == "binary"
    finally:
        lib.close()


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

    def test_wildcard_indexes_every_file(self, tmp_path):
        """An explicit ``*`` extension indexes prefix-named and extensionless
        files (same result as the index-all default, kept for compatibility)."""
        (tmp_path / "-gr.dhati").write_text("gram#1 A --> B\n")
        (tmp_path / "-se.tempo").write_text("tempo 120\n")
        (tmp_path / "CHECK_THIS").write_text("no extension\n")
        (tmp_path / "readme.md").write_text("# hi\n")

        allf = {f.name for f in scan_directory(tmp_path, extensions={"*"})}
        assert allf == {"-gr.dhati", "-se.tempo", "CHECK_THIS", "readme.md"}

        # A suffix allow-list still restricts (parser routing / opt-in).
        deff = {f.name for f in scan_directory(tmp_path, extensions={".md"})}
        assert deff == {"readme.md"}

    def test_wildcard_still_honors_rtfmignore(self, tmp_path):
        (tmp_path / "-gr.keep").write_text("x\n")
        (tmp_path / "-gr.drop").write_text("y\n")
        (tmp_path / ".rtfmignore").write_text("-gr.drop\n")
        names = {f.name for f in scan_directory(tmp_path, extensions={"*"})}
        assert "-gr.keep" in names
        assert "-gr.drop" not in names

    def test_default_indexes_all_text(self, tmp_path):
        """With no positive restrictor, every file is a candidate — RTFM
        indexes all text by default; the extension list no longer gates."""
        (tmp_path / "-gr.dhati").write_text("x")     # prefix-typed
        (tmp_path / "CHECK_THIS").write_text("y")    # no extension
        (tmp_path / "app.bps").write_text("z")       # unregistered extension
        (tmp_path / "readme.md").write_text("w")
        names = {f.name for f in scan_directory(tmp_path)}
        assert names == {"-gr.dhati", "CHECK_THIS", "app.bps", "readme.md"}

    def test_include_prefix_and_suffix(self, tmp_path):
        (tmp_path / "-gr.dhati").write_text("x")
        (tmp_path / "-se.tempo").write_text("x")
        (tmp_path / "song.bps").write_text("x")
        (tmp_path / "readme.md").write_text("x")
        names = {f.name for f in scan_directory(
            tmp_path, include=["-gr.*", "*.bps"])}
        assert names == {"-gr.dhati", "song.bps"}

    def test_exclude_patterns(self, tmp_path):
        (tmp_path / "a.md").write_text("x")
        (tmp_path / "app.min.js").write_text("x")
        (tmp_path / "package-lock.json").write_text("x")
        names = {f.name for f in scan_directory(
            tmp_path, exclude=["*.min.js", "package-lock.json"])}
        assert names == {"a.md"}

    def test_include_path_glob(self, tmp_path):
        (tmp_path / "fixtures").mkdir()
        (tmp_path / "fixtures" / "a.bps").write_text("x")
        (tmp_path / "top.bps").write_text("x")
        names = {f.name for f in scan_directory(tmp_path, include=["fixtures/*"])}
        assert names == {"a.bps"}

    def test_excludes_rtfm_state_dir(self, tmp_path):
        """`.rtfm/` must never be scanned — it contains RTFM's own state
        (library.db, logs, locks). Indexing it creates a self-feeding loop
        where the index gets re-ingested as chunks on every sync, which
        once grew some DBs to 8+ GB of pure recursion.
        """
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('ok')\n")
        rtfm = tmp_path / ".rtfm"
        rtfm.mkdir()
        # Plant fake state files that should NOT be scanned.
        (rtfm / "library.db").write_bytes(b"SQLite format 3\x00...")
        (rtfm / "library.db-wal").write_bytes(b"WAL")
        (rtfm / "config.json").write_text("{}")

        files = scan_directory(tmp_path, extensions={"py", "db", "json"})
        names = [str(f.relative_to(tmp_path)) for f in files]
        assert "src/main.py" in names
        for noisy in (".rtfm/library.db", ".rtfm/config.json",
                      ".rtfm/library.db-wal"):
            assert noisy not in names, f"{noisy} leaked into the scan"

    def test_excludes_cache_dir(self, tmp_path):
        """`.cache/` is generic noise (import caches, build caches) and
        should never be scanned by default."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('ok')\n")
        cache = tmp_path / ".cache" / "thing"
        cache.mkdir(parents=True)
        (cache / "blob.json").write_text('{"x":1}')

        files = scan_directory(tmp_path, extensions={"py", "json"})
        names = [str(f.relative_to(tmp_path)) for f in files]
        assert "src/main.py" in names
        assert ".cache/thing/blob.json" not in names

    def test_honors_root_gitignore(self, tmp_path):
        """When a project declares patterns in its `.gitignore`, we treat
        them as RTFM excludes too — the user has already said "this is
        ignored artifact", no point re-asking.
        """
        try:
            import pathspec  # noqa: F401
        except ImportError:
            import pytest
            pytest.skip("pathspec not installed")

        (tmp_path / ".gitignore").write_text(
            "*.log\n"
            "build/\n"
            "secret.txt\n"
        )
        (tmp_path / "main.py").write_text("ok\n")
        (tmp_path / "debug.log").write_text("noise\n")
        (tmp_path / "secret.txt").write_text("shhh\n")
        (tmp_path / "build").mkdir()
        (tmp_path / "build" / "output.py").write_text("generated\n")

        files = scan_directory(tmp_path, extensions={"py", "log", "txt"})
        names = [str(f.relative_to(tmp_path)) for f in files]
        assert "main.py" in names
        assert "debug.log" not in names
        assert "secret.txt" not in names
        assert "build/output.py" not in names

    def test_gitignore_can_be_disabled(self, tmp_path):
        """`honor_gitignore=False` lets callers bypass the .gitignore
        filter when they explicitly want to (e.g., reindex --force)."""
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / "main.py").write_text("ok\n")
        (tmp_path / "debug.log").write_text("noise\n")

        files = scan_directory(tmp_path, extensions={"py", "log"},
                               honor_gitignore=False)
        names = [str(f.relative_to(tmp_path)) for f in files]
        assert "debug.log" in names

    def test_rtfmignore_always_applied(self, tmp_path):
        """`.rtfmignore` is RTFM's own exclude list. Applied whether
        `.gitignore` is honored or not, so users can expose a private
        corpus (honor_gitignore=false) and still keep build outputs out.
        """
        try:
            import pathspec  # noqa: F401
        except ImportError:
            import pytest
            pytest.skip("pathspec not installed")

        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / ".rtfmignore").write_text(
            "dist/\n"
            "*.tmp.md\n"
        )
        (tmp_path / "main.py").write_text("ok\n")
        (tmp_path / "notes.tmp.md").write_text("scratch\n")
        (tmp_path / "dist").mkdir()
        (tmp_path / "dist" / "out.py").write_text("built\n")
        (tmp_path / "debug.log").write_text("noise\n")

        # With honor_gitignore=True, both filters apply.
        files = scan_directory(tmp_path, extensions={"py", "log", "md"},
                               honor_gitignore=True)
        names = [str(f.relative_to(tmp_path)) for f in files]
        assert "main.py" in names
        assert "debug.log" not in names          # .gitignore
        assert "notes.tmp.md" not in names       # .rtfmignore
        assert "dist/out.py" not in names        # .rtfmignore

        # With honor_gitignore=False, .rtfmignore still applies.
        files = scan_directory(tmp_path, extensions={"py", "log", "md"},
                               honor_gitignore=False)
        names = [str(f.relative_to(tmp_path)) for f in files]
        assert "main.py" in names
        assert "debug.log" in names              # .gitignore ignored
        assert "notes.tmp.md" not in names       # .rtfmignore still applies
        assert "dist/out.py" not in names        # .rtfmignore still applies


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


class TestRemovalSafety:
    """Guards that stop a transient/incomplete scan from wiping a corpus.

    Regression: a session hook ran a full sync of every source on every
    prompt while an external process reorganised files on flaky NTFS; an
    incomplete scan flagged ~500 indexed PDFs as 'removed' and deleted
    their books + chunks + (expensive) embeddings.
    """

    def _make_corpus(self, tmp_path, n):
        for i in range(n):
            (tmp_path / f"f{i:03d}.txt").write_text(
                f"Document number {i}.\n"
                "This file has enough text to be indexed by the plaintext "
                "parser so that it produces at least one chunk and book.\n"
            )

    def test_mass_removal_of_genuinely_deleted_files_applies(
            self, sync_db, tmp_path):
        """A large real deletion (files truly unlinked, root readable) is
        applied. The old ratio circuit breaker refused this forever — the
        bug that silently diverged indexes from disk."""
        self._make_corpus(tmp_path, 40)
        sync(sync_db, tmp_path, corpus="t", generate_embeddings=False)
        assert sync_db.get_stats()["books"] == 40

        # 30/40 files genuinely deleted (75%). Root is still readable, so
        # these are confirmed deletions, not a mount glitch.
        for i in range(30):
            (tmp_path / f"f{i:03d}.txt").unlink()

        result = sync(sync_db, tmp_path, corpus="t",
                      generate_embeddings=False)
        assert result.removed == 30
        assert sync_db.get_stats()["books"] == 10

    def test_force_remove_bulk_delete(self, sync_db, tmp_path):
        """force_remove=True applies a deliberate bulk delete."""
        self._make_corpus(tmp_path, 40)
        sync(sync_db, tmp_path, corpus="t", generate_embeddings=False)
        for i in range(30):
            (tmp_path / f"f{i:03d}.txt").unlink()

        result = sync(sync_db, tmp_path, corpus="t",
                      generate_embeddings=False, force_remove=True)
        assert result.removed == 30
        assert sync_db.get_stats()["books"] == 10

    def test_small_delete_still_applies(self, sync_db, tmp_path):
        """A normal small deletion is below the breaker and applies."""
        self._make_corpus(tmp_path, 40)
        sync(sync_db, tmp_path, corpus="t", generate_embeddings=False)
        for i in range(2):  # 2/40 = 5% — well under threshold
            (tmp_path / f"f{i:03d}.txt").unlink()

        result = sync(sync_db, tmp_path, corpus="t",
                      generate_embeddings=False)
        assert result.removed == 2
        assert sync_db.get_stats()["books"] == 38

    def test_file_list_mode_never_removes(self, sync_db, tmp_path):
        """A partial files= list says nothing about unmentioned files,
        so their absence from the list must not delete them."""
        self._make_corpus(tmp_path, 40)
        sync(sync_db, tmp_path, corpus="t", generate_embeddings=False)

        # Touch one file, sync only that one via files=. The other 39 are
        # not in the list but must survive.
        (tmp_path / "f000.txt").write_text("changed content, more text here.\n")
        result = sync(sync_db, tmp_path, corpus="t",
                      generate_embeddings=False, files=["f000.txt"])
        assert result.removed == 0
        assert sync_db.get_stats()["books"] == 40


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
        result = sync_db.remove_file("test.txt", "test")
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
        result = sync_db.move_file("test.txt", "docs/test.txt",
                                   "docs--test-txt", corpus="test")
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
        assert _path_to_slug("README.md") == "readme-md"

    def test_root_file_with_corpus(self):
        slug = _path_to_slug("README.md", corpus="pub")
        assert slug == "pub--readme-md"

    def test_subdirectory_with_corpus(self):
        slug = _path_to_slug("_en/B4_Flags.md", corpus="pub")
        assert slug == "pub-en--b4_flags-md"

    def test_subdirectory_no_corpus(self):
        slug = _path_to_slug("_en/B4_Flags.md")
        assert slug == "en--b4_flags-md"

    def test_same_name_different_extension(self):
        """Two different files. They used to share one identity, and the
        second one never entered the index — 1 750 files across this fleet."""
        assert (_path_to_slug("bp3/timed_events.h", "c")
                != _path_to_slug("bp3/timed_events.c", "c"))

    def test_a_dot_in_the_name_is_not_an_extension(self):
        """`Path.stem` stops at the last dot, so `+sc.Ruwet` and `+sc.tryMe`
        both read as `+sc`."""
        assert (_path_to_slug("scripts/+sc.Ruwet", "bp")
                != _path_to_slug("scripts/+sc.tryMe", "bp"))

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
