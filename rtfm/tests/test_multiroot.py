"""A corpus may gather several directories, and a file may live in two corpora.

Both were allowed by `rtfm add` and used in real projects, and both put the
indexer into a permanent loop:

* Two directories in one corpus — a stored path is relative to whichever one
  it came from, so scanning one saw the other's files as deleted, removed
  them, and the next scan re-indexed them. One project here reached 515 000
  removal jobs.
* The same content in two corpora — matching bytes alone counted as a
  cross-corpus move, so each corpus stole the file back from the other on
  every pass. The same project logged 932 000 re-ingestions, 82 000 of them
  for a single README.

Together they are why the daemon held three cores around the clock.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rtfm.core.library import Library
from rtfm.core.sync import (
    build_disk_check,
    compute_diff,
    confirm_removals,
    sync,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestSeveralDirectoriesInOneCorpus:
    def test_a_file_under_a_sibling_directory_is_not_a_deletion(self, tmp_path):
        docs, src = tmp_path / "docs", tmp_path / "src"
        _write(docs / "guide.md", "# guide")
        _write(src / "main.py", "x = 1")

        # Scanning `docs`, the index still holds src's file under its own
        # relative path. It is present — just not here.
        confirmed, kept = confirm_removals(
            docs, ["main.py"], sibling_roots=[src])
        assert confirmed == []
        assert kept == ["main.py"]

    def test_a_genuinely_deleted_file_is_still_removed(self, tmp_path):
        docs, src = tmp_path / "docs", tmp_path / "src"
        docs.mkdir()
        src.mkdir()
        confirmed, kept = confirm_removals(
            docs, ["gone.md"], sibling_roots=[src])
        assert confirmed == ["gone.md"]
        assert kept == []

    def test_an_unreadable_sibling_holds_the_removal_back(self, tmp_path):
        """A mount that went dark proves nothing — and absence elsewhere is
        not absence here. Keep the file until every directory can be read."""
        docs = tmp_path / "docs"
        docs.mkdir()
        confirmed, kept = confirm_removals(
            docs, ["maybe.md"], sibling_roots=[Path("/nonexistent-mount")])
        assert kept == ["maybe.md"]

    def test_the_scan_records_every_directory_of_a_corpus(self, tmp_path):
        """One row per directory — the key used to be the corpus alone, so a
        second directory overwrote the first and nothing knew where those
        files lived."""
        lib = Library(str(tmp_path / "library.db"))
        try:
            lib.set_sync_root("papers", "/a/docs")
            lib.set_sync_root("papers", "/a/src")
            assert set(lib.list_sync_roots("papers")) == {"/a/docs", "/a/src"}
            # Re-recording one is not a duplicate.
            lib.set_sync_root("papers", "/a/docs")
            assert len(lib.list_sync_roots("papers")) == 2
        finally:
            lib.close()

    def test_an_older_database_keeps_its_root_and_gains_the_others(
            self, tmp_path):
        """Databases written before the fix carry the narrow key. Opening one
        must widen it without losing the root it had."""
        db = tmp_path / "library.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE sync_roots (
                corpus TEXT PRIMARY KEY,
                root_path TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            );
            INSERT INTO sync_roots (corpus, root_path) VALUES ('c', '/old/root');
        """)
        conn.commit()
        conn.close()

        lib = Library(str(db))
        try:
            assert lib.list_sync_roots("c") == ["/old/root"]
            lib.set_sync_root("c", "/new/root")
            assert set(lib.list_sync_roots("c")) == {"/old/root", "/new/root"}
        finally:
            lib.close()


class TestTheSameFileInTwoCorpora:
    def test_identical_content_in_two_places_is_not_a_move(self, tmp_path):
        """The shared-document case: a README copied into two indexed trees.
        Each scan used to claim it from the other, for ever."""
        here, elsewhere = tmp_path / "here", tmp_path / "elsewhere"
        _write(here / "README.md", "same bytes")
        _write(elsewhere / "README.md", "same bytes")

        lib = Library(str(tmp_path / "library.db"))
        try:
            lib.set_sync_root("other", str(elsewhere))
            sync(library=lib, root=elsewhere, corpus="other",
                 extensions={".md"}, generate_embeddings=False)

            result = sync(library=lib, root=here, corpus="mine",
                          extensions={".md"}, generate_embeddings=False)
            assert result.moved == 0, "the other corpus still holds its copy"
            assert result.added == 1

            # And the first corpus kept its file.
            assert lib.list_indexed_files(corpus="other")
        finally:
            lib.close()

    def test_a_file_that_really_left_is_still_transferred(self, tmp_path):
        """The move must survive: embeddings and tags ride on it."""
        old, new = tmp_path / "old", tmp_path / "new"
        _write(old / "note.md", "unique content here")

        lib = Library(str(tmp_path / "library.db"))
        try:
            sync(library=lib, root=old, corpus="before",
                 extensions={".md"}, generate_embeddings=False)
            (old / "note.md").unlink()
            _write(new / "note.md", "unique content here")

            result = sync(library=lib, root=new, corpus="after",
                          extensions={".md"}, generate_embeddings=False)
            assert result.moved == 1
            assert result.added == 0
        finally:
            lib.close()

    def test_the_directory_being_scanned_never_counts_as_elsewhere(
            self, tmp_path):
        """Renaming a corpus keeps the same directory. Its files are all still
        there, and that must not block the transfer — see the in-place rename
        test in test_cross_corpus_move.py."""
        lib = Library(str(tmp_path / "library.db"))
        try:
            _write(tmp_path / "root" / "a.md", "x")
            lib.set_sync_root("old", str(tmp_path / "root"))
            check = build_disk_check(lib, tmp_path / "root")
            assert check("a.md", "old") is False
        finally:
            lib.close()

    def test_an_unreadable_root_reads_as_present(self, tmp_path):
        """Never hand a book away because a mount blinked."""
        lib = Library(str(tmp_path / "library.db"))
        try:
            lib.set_sync_root("far", "/nonexistent-mount")
            check = build_disk_check(lib, tmp_path)
            # Nothing readable there, and nothing found: absence is not proof,
            # but a plain missing path is. This root simply holds no file.
            assert check("a.md", "far") is False
        finally:
            lib.close()

    def test_without_the_check_the_old_behaviour_stands(self, tmp_path):
        """compute_diff is called from tests and tools that have no library;
        the gate is opt-in so those callers are unaffected."""
        f = _write(tmp_path / "x.md", "content")
        indexed_global = {
            "x.md": {"file_hash": _hash(f), "corpus": "other"},
        }
        diff = compute_diff([f], {}, tmp_path,
                            indexed_global=indexed_global,
                            current_corpus="mine")
        assert len(diff.cross_moved) == 1


def _hash(path: Path) -> str:
    from rtfm.core.sync import compute_file_hash
    return compute_file_hash(path)
