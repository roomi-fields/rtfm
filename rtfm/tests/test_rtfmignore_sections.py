"""Saying "index this, but keep no history of it".

RTFM keeps a full copy of a file's text every time it changes, capped at
fifty versions per file. Fifty is right for a source file of a few
kilobytes. It is ruinous for a log or a mailbox: measured on one workshop,
a 24 MB mailbox appended to every few minutes held fifty near-identical
copies of itself — 740 MB for one file — and six such files accounted for
two thirds of a 3.2 GB archive.

The cap counts versions, not bytes, and nothing inside it can tell an
appended log from an edited document. The project can, and it already has a
file for saying what RTFM should treat differently. So ``.rtfmignore`` grows
a second section: what is above the first header keeps meaning "do not index
this", and ``[versions]`` means "index it, keep no history".

A file written before sections existed has no header, so every one of its
lines is still an indexing rule — the reading it has always had.
"""
from __future__ import annotations

import pytest

from rtfm.core.sync import (
    _load_rtfmignore_spec, history_is_wanted, load_version_ignore_spec,
)

pytest.importorskip("pathspec")


def _ignore(tmp_path, text):
    (tmp_path / ".rtfmignore").write_text(text)
    return tmp_path


class TestAFileWithNoSections:
    """Every ``.rtfmignore`` in the wild is one of these."""

    def test_its_patterns_still_mean_do_not_index(self, tmp_path):
        root = _ignore(tmp_path, "dist/\n*.tmp.md\n")
        spec = _load_rtfmignore_spec(root)
        assert spec.match_file("dist/out.py")
        assert spec.match_file("notes.tmp.md")
        assert not spec.match_file("docs/guide.md")

    def test_it_asks_for_no_history_of_anything(self, tmp_path):
        root = _ignore(tmp_path, "dist/\n")
        assert load_version_ignore_spec(root) is None
        assert history_is_wanted(root, "courrier/hub.md")

    def test_no_file_at_all_is_not_an_error(self, tmp_path):
        assert _load_rtfmignore_spec(tmp_path) is None
        assert history_is_wanted(tmp_path, "quoi-que-ce-soit.md")


class TestTheVersionsSection:

    @pytest.fixture
    def root(self, tmp_path):
        return _ignore(tmp_path, """# hors de l'index
dist/
*.tmp.md

[versions]
# indexe, mais sans historique
courrier/*.md
*.log
""")

    def test_a_listed_file_keeps_no_history(self, root):
        assert not history_is_wanted(root, "courrier/hub.md")
        assert not history_is_wanted(root, "rtfm.log")

    def test_it_is_still_indexed(self, root):
        """The whole point: the mailbox stays searchable."""
        assert not _load_rtfmignore_spec(root).match_file("courrier/hub.md")

    def test_everything_else_keeps_its_history(self, root):
        assert history_is_wanted(root, "docs/guide.md")
        assert history_is_wanted(root, "src/moteur.py")

    def test_the_first_section_still_governs_indexing(self, root):
        spec = _load_rtfmignore_spec(root)
        assert spec.match_file("dist/out.py")
        assert not spec.match_file("courrier/hub.md"), (
            "a pattern under [versions] must not exclude the file from the index")

    def test_an_explicit_index_header_reads_the_same(self, tmp_path):
        root = _ignore(tmp_path, "[index]\ndist/\n\n[versions]\n*.log\n")
        assert _load_rtfmignore_spec(root).match_file("dist/out.py")
        assert not history_is_wanted(root, "rtfm.log")

    def test_a_misspelt_header_excludes_nothing(self, tmp_path):
        """A typo must not silently make a directory called [versons]
        disappear from the index."""
        root = _ignore(tmp_path, "dist/\n[versons]\ncourrier/*.md\n")
        spec = _load_rtfmignore_spec(root)
        assert spec.match_file("dist/out.py")
        assert not spec.match_file("courrier/hub.md")
        assert history_is_wanted(root, "courrier/hub.md")

    def test_windows_separators_are_matched(self, tmp_path):
        root = _ignore(tmp_path, "[versions]\ncourrier/*.md\n")
        assert not history_is_wanted(root, "courrier\\hub.md")


class TestTheSnapshotIsActuallySkipped:

    def _project(self, tmp_path, ignore_text=None):
        from rtfm.core.library import Library
        root = tmp_path / "projet"
        (root / ".rtfm").mkdir(parents=True)
        (root / "courrier").mkdir()
        if ignore_text:
            (root / ".rtfmignore").write_text(ignore_text)
        doc = root / "courrier" / "hub.md"
        doc.write_text("# Boite\n\nUn premier message.\n" * 10)
        lib = Library(root / ".rtfm" / "library.db")
        lib.ingest(doc, corpus="default",
                   metadata={"book_slug": "courrier-hub-md", "source_file": "courrier/hub.md"})
        lib.set_sync_root("default", str(root))
        lib.update_indexed_file("courrier/hub.md", "h1", "default",
                                "courrier-hub-md", file_size=doc.stat().st_size)
        lib.close()
        return root, doc

    def _reingest(self, root, rel):
        from rtfm.core.handlers import handle_ingest
        from rtfm.core.queue import Job

        class _W:
            db_path = root / ".rtfm" / "library.db"

            def _log(self, msg):
                pass
        handle_ingest(Job(id=1, type="ingest", priority=10,
                          payload={"root": str(root), "corpus": "default",
                                   "filepath": rel},
                          status="running", created_at="", started_at=None,
                          finished_at=None, error=None, attempts=1), _W())

    def _versions(self, root):
        import sqlite3
        conn = sqlite3.connect(
            f"file:{root / '.rtfm' / 'library.db'}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT COUNT(*) FROM file_versions").fetchone()[0]
        finally:
            conn.close()

    def test_without_the_section_the_copy_is_kept(self, tmp_path):
        root, doc = self._project(tmp_path)
        doc.write_text(doc.read_text() + "\nUn second message.\n")
        self._reingest(root, "courrier/hub.md")
        assert self._versions(root) == 1

    def test_with_the_section_no_copy_is_kept(self, tmp_path):
        root, doc = self._project(tmp_path, "[versions]\ncourrier/*.md\n")
        doc.write_text(doc.read_text() + "\nUn second message.\n")
        self._reingest(root, "courrier/hub.md")
        assert self._versions(root) == 0

    def test_it_is_still_searchable_afterwards(self, tmp_path):
        from rtfm.core.library import Library
        root, doc = self._project(tmp_path, "[versions]\ncourrier/*.md\n")
        doc.write_text(doc.read_text() + "\nUn second message tres precis.\n")
        self._reingest(root, "courrier/hub.md")
        lib = Library(root / ".rtfm" / "library.db", create=False)
        try:
            assert lib.search("precis", limit=3)
        finally:
            lib.close()


class TestThePurgeOfWhatWasAlreadyStored:
    """Declaring ``[versions]`` stops the next copy; it cannot undo the ones
    already made. On the index that prompted the section, six mailboxes held
    fifty near-identical copies each — two thirds of a 3.2 GB archive
    standing beside a 300 MB index. This is the other half."""

    @pytest.fixture
    def archived(self, tmp_path):
        from rtfm.core.library import Library
        root = tmp_path / "projet"
        (root / ".rtfm").mkdir(parents=True)
        (root / "courrier").mkdir()
        db = root / ".rtfm" / "library.db"
        lib = Library(db)
        lib.set_sync_root("default", str(root))
        for rel in ("courrier/hub.md", "docs.md"):
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("Du contenu.\n" * 50)
            slug = rel.replace("/", "-").replace(".", "-")
            lib.ingest(f, corpus="default",
                       metadata={"book_slug": slug, "source_file": rel})
            lib.update_indexed_file(rel, "h", "default", slug,
                                    file_size=f.stat().st_size)
            for _ in range(3):
                lib.save_file_version(slug, "h")
        lib.close()
        return root, db

    def _reconcile(self, db):
        from rtfm.core.handlers import handle_reconcile
        from rtfm.core.queue import Job

        class _W:
            db_path = db

            def __init__(self):
                self.lines = []

            def _log(self, msg):
                self.lines.append(msg)
        w = _W()
        handle_reconcile(Job(id=1, type="reconcile", priority=40, payload={},
                             status="running", created_at="", started_at=None,
                             finished_at=None, error=None, attempts=1), w)
        return w

    def _snapshots(self, db, slug=None):
        import sqlite3
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            if slug is None:
                return c.execute("SELECT COUNT(*) FROM file_versions").fetchone()[0]
            return c.execute(
                "SELECT COUNT(*) FROM file_versions v JOIN books b "
                "ON b.id = v.book_id WHERE b.slug = ?", (slug,)).fetchone()[0]
        finally:
            c.close()

    def test_without_the_section_nothing_is_dropped(self, archived):
        root, db = archived
        before = self._snapshots(db)
        assert before > 0
        self._reconcile(db)
        assert self._snapshots(db) == before

    def test_the_declared_files_lose_their_archive(self, archived):
        root, db = archived
        (root / ".rtfmignore").write_text("[versions]\ncourrier/*.md\n")
        w = self._reconcile(db)
        assert self._snapshots(db, "courrier-hub-md") == 0
        assert any("keeps no history" in ln for ln in w.lines)

    def test_the_others_keep_theirs(self, archived):
        root, db = archived
        (root / ".rtfmignore").write_text("[versions]\ncourrier/*.md\n")
        self._reconcile(db)
        assert self._snapshots(db, "docs-md") == 3

    def test_the_file_itself_is_untouched(self, archived):
        root, db = archived
        (root / ".rtfmignore").write_text("[versions]\ncourrier/*.md\n")
        self._reconcile(db)
        assert (root / "courrier" / "hub.md").exists()
        from rtfm.core.library import Library
        lib = Library(db, create=False)
        try:
            assert "courrier/hub.md" in lib.list_indexed_files()
        finally:
            lib.close()

    def test_a_second_pass_finds_nothing_left(self, archived):
        root, db = archived
        (root / ".rtfmignore").write_text("[versions]\ncourrier/*.md\n")
        self._reconcile(db)
        w = self._reconcile(db)
        assert not any("keeps no history" in ln for ln in w.lines)
