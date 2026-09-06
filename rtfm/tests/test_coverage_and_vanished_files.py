"""Two numbers that were lying, in opposite directions.

**Coverage.** People measure it by hand — books over files in the tree —
because nothing authoritative existed. That denominator counts logs, lock
files, state files and build output the scan never looks at, so a project
reads as far more full of holes than it is, and sixteen agents are shown a
figure that is wrong in the alarming direction.

**Failures.** A file listed by a scan and deleted before its turn came was
counted as a failed job. On a repository people work in that is not a
failure, it is the ordinary race between listing and reading — and the right
answer is the one the deletion already implies. Measured on a repository
that deleted 420 documents in a day: every resulting job failure described a
file its author had meant to delete, and a failure count full of
non-events is one nobody reads.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rtfm.core.coverage import measure


@pytest.fixture
def project(tmp_path):
    """A project with real content, and the debris a scan ignores."""
    from rtfm.core.library import Library

    root = tmp_path / "projet"
    (root / ".rtfm").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "node_modules" / "paquet").mkdir(parents=True)

    indexed = []
    for rel in ("README.md", "docs/guide.md", "docs/api.md"):
        f = root / rel
        f.write_text(f"# {rel}\n\nDu contenu qui vaut d'etre indexe.\n" * 10)
        indexed.append(rel)
    # Debris: excluded by rule, or living in .rtfm itself.
    (root / "node_modules" / "paquet" / "index.js").write_text("module.exports={}\n")
    (root / ".rtfm" / "rtfm.log").write_text("des lignes de journal\n" * 100)

    lib = Library(root / ".rtfm" / "library.db")
    for rel in indexed:
        lib.ingest(root / rel, corpus="default",
                   metadata={"book_slug": rel.replace("/", "-").replace(".", "-"),
                             "source_file": rel})
        lib.update_indexed_file(rel, f"h-{rel}", "default",
                                rel.replace("/", "-").replace(".", "-"),
                                file_size=(root / rel).stat().st_size)
    lib.set_sync_root("default", str(root))
    lib.close()
    return root


class TestWhatCountsAsAGap:

    def test_a_complete_index_measures_complete(self, project):
        cov = measure(project)
        assert cov.readable == cov.indexable
        assert cov.ratio == 1.0

    def test_debris_is_not_counted_as_missing(self, project):
        """The hand-made denominator counted these and reported holes."""
        cov = measure(project)
        assert cov.indexable == 3, (
            "the scan's own list is the denominator, not the directory")

    def test_a_file_never_indexed_is_a_gap(self, project):
        (project / "docs" / "nouveau.md").write_text("Du texte neuf.\n" * 10)
        cov = measure(project)
        assert cov.indexable == 4
        assert cov.readable == 3
        assert cov.sources[0].missing == 1

    def test_a_file_tracked_with_nothing_behind_it_is_a_gap(self, project):
        """The worst kind: it looks done, so nothing retries it."""
        from rtfm.core.library import Library
        lib = Library(project / ".rtfm" / "library.db")
        lib.update_indexed_file("docs/muet.md", "h", "default", "muet")
        lib.close()
        (project / "docs" / "muet.md").write_text("Du texte.\n" * 10)

        cov = measure(project)
        assert cov.sources[0].tracked_not_readable == 1
        assert "nothing readable" in cov.one_line()

    def test_a_file_from_a_source_no_longer_configured_is_named(self, project):
        from rtfm.core.library import Library
        lib = Library(project / ".rtfm" / "library.db")
        lib.update_indexed_file("ailleurs/vieux.md", "h", "default", "vieux")
        lib.close()
        assert measure(project).unaccounted == 1

    def test_the_one_line_is_the_sentence_to_show(self, project):
        line = measure(project).one_line()
        assert "coverage:" in line and "100.0%" in line


class TestAFileDeletedBeforeItsTurn:

    def _job(self, root, rel):
        from rtfm.core.queue import Job
        return Job(id=1, type="ingest", priority=10,
                   payload={"root": str(root), "corpus": "default",
                            "filepath": rel},
                   status="running", created_at="", started_at=None,
                   finished_at=None, error=None, attempts=1)

    def _worker(self, root, logged):
        class _W:
            db_path = root / ".rtfm" / "library.db"

            def _log(self, msg):
                logged.append(msg)
        return _W()

    def test_it_is_taken_out_of_the_index_not_counted_as_a_failure(self, project):
        from rtfm.core.handlers import handle_ingest
        from rtfm.core.library import Library

        (project / "docs" / "guide.md").unlink()
        logged: list[str] = []
        handle_ingest(self._job(project, "docs/guide.md"),
                      self._worker(project, logged))

        lib = Library(project / ".rtfm" / "library.db", create=False)
        try:
            assert "docs/guide.md" not in lib.list_indexed_files()
        finally:
            lib.close()
        assert any("deleted before it could be read" in m for m in logged)

    def test_an_unreachable_directory_still_raises(self, project):
        """An unmounted volume makes every file under it look deleted.
        Emptying an index on that evidence is worse than a noisy counter."""
        from rtfm.core.handlers import handle_ingest

        with pytest.raises(FileNotFoundError):
            handle_ingest(self._job(project / "pas-la", "docs/guide.md"),
                          self._worker(project, []))

    def test_a_file_that_is_there_is_indexed_as_before(self, project):
        from rtfm.core.handlers import handle_ingest
        from rtfm.core.library import Library

        (project / "docs" / "neuf.md").write_text("# Neuf\n\nDu texte.\n" * 10)
        handle_ingest(self._job(project, "docs/neuf.md"),
                      self._worker(project, []))
        lib = Library(project / ".rtfm" / "library.db", create=False)
        try:
            assert "docs/neuf.md" in lib.list_indexed_files()
        finally:
            lib.close()
