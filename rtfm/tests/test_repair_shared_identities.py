"""Fixing the code is not fixing the index.

A scan acts on the difference between what is on disk and what it recorded
last time. A record that is wrong but *stable* produces no difference, so
the scan skips it for ever — and correcting the code that wrote it changes
nothing for the files already carrying it.

That is what happened to identities. They used to stop at the first dot, so
``-se.Alan`` and ``-se.Alarm`` both became ``-se`` and the second overwrote
the first. The derivation was fixed; the files indexed before the fix kept
their colliding identity, because an identity is never recomputed for a path
already tracked. Weeks after the fix shipped, 910 files across two projects
were still readable as a handful of documents.

So the repair has to be a pass of its own, it has to run without anyone
asking for it — an upgrade is the only moment every install passes through,
whoever started it — and it has to be safe to run every time.
"""
from __future__ import annotations

import sqlite3

import pytest

from rtfm.core.repair import find_shared_identities, repair_shared_identities
from rtfm.core.supervisor import _Slot


@pytest.fixture
def index(tmp_path):
    """A real index with three files collapsed onto one identity."""
    from rtfm.core.library import Library
    root = tmp_path / "projet"
    (root / ".rtfm").mkdir(parents=True)
    db = root / ".rtfm" / "library.db"
    lib = Library(db)

    names = ["-se.Alan", "-se.Alarm", "-se.Ames"]
    for n in names:
        f = root / n
        f.write_text(f"contenu de {n}\n" * 20)
    # Index them the way the old derivation did: one shared identity. Each
    # ingest overwrites the last catalogue entry; each file is tracked as
    # done. Three files in, one document out, and nothing said so.
    for n in names:
        lib.ingest(root / n, corpus="default",
                   metadata={"book_slug": "projet--se", "source_file": n})
        lib.update_indexed_file(n, f"hash-{n}", "default", "projet--se",
                                file_size=(root / n).stat().st_size)
    lib.close()
    return root, db, names


def _counts(db):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    n = (c.execute("SELECT COUNT(*) FROM indexed_files").fetchone()[0],
         c.execute("SELECT COUNT(*) FROM books").fetchone()[0])
    c.close()
    return n


class TestSeeingTheDamage:

    def test_every_file_in_the_group_is_named(self, index):
        _, db, names = index
        conn = sqlite3.connect(db)
        affected = find_shared_identities(conn)
        conn.close()
        assert sorted(p for _, p in affected) == sorted(names), (
            "the readable one is affected too — its identity is wrong as well")

    def test_the_index_looked_healthy(self, index):
        """Three files tracked, three files done, one readable."""
        _, db, _ = index
        assert _counts(db) == (3, 1)


class TestTheRepair:

    def test_the_files_are_handed_back_to_the_scan(self, index):
        _, db, names = index
        assert repair_shared_identities(db) == len(names)
        assert _counts(db) == (0, 0), "nothing tracked, nothing catalogued"

    def test_the_files_are_still_on_disk(self, index):
        root, db, names = index
        repair_shared_identities(db)
        assert all((root / n).exists() for n in names)

    def test_a_second_run_finds_nothing(self, index):
        _, db, _ = index
        repair_shared_identities(db)
        assert repair_shared_identities(db) == 0

    def test_a_healthy_index_is_left_alone(self, tmp_path):
        from rtfm.core.library import Library
        root = tmp_path / "sain"
        (root / ".rtfm").mkdir(parents=True)
        db = root / ".rtfm" / "library.db"
        lib = Library(db)
        for n in ("guide.md", "notes.md"):
            (root / n).write_text("du texte\n" * 20)
            slug = n.replace(".", "-")
            lib.ingest(root / n, corpus="default",
                       metadata={"book_slug": slug, "source_file": n})
            lib.update_indexed_file(n, f"hash-{n}", "default", slug,
                                    file_size=(root / n).stat().st_size)
        lib.close()
        before = _counts(db)
        assert repair_shared_identities(db) == 0
        assert _counts(db) == before

    def test_the_same_path_in_two_corpora_is_not_a_collision(self, tmp_path):
        db = tmp_path / "library.db"
        c = sqlite3.connect(db)
        c.execute("""CREATE TABLE indexed_files (
            filepath TEXT, book_slug TEXT, corpus TEXT)""")
        c.executemany("INSERT INTO indexed_files VALUES (?,?,?)", [
            ("guide.md", "guide", "un"), ("guide.md", "guide", "deux")])
        c.commit()
        assert find_shared_identities(c) == []
        c.close()

    def test_an_index_with_no_tracking_is_not_an_error(self, tmp_path):
        db = tmp_path / "library.db"
        sqlite3.connect(db).execute("CREATE TABLE t (x)")
        assert repair_shared_identities(db) == 0

    def test_a_missing_index_is_not_an_error(self, tmp_path):
        assert repair_shared_identities(tmp_path / "rien.db") == 0


class TestItRunsWithoutBeingAskedTo:

    def test_opening_a_project_repairs_it(self, index):
        """The upgrade path: nobody types anything, an agent may have
        started RTFM, and the index comes back correct."""
        root, db, names = index
        slot = _Slot(root / ".rtfm")
        lines: list[str] = []
        slot.open(lines.append)
        try:
            assert _counts(db) == (0, 0)
            assert any("shared an identity" in ln for ln in lines)
        finally:
            slot.close()

    def test_a_repaired_project_scans_at_once(self, index):
        """Handing files back is only half of it — they have to be picked
        up now, not on a staggered tick a scan interval away."""
        root, _, _ = index
        slot = _Slot(root / ".rtfm")
        try:
            assert slot.open(lambda m: None) is True
        finally:
            slot.close()

    def test_opening_a_healthy_project_says_nothing(self, tmp_path):
        root = tmp_path / "sain"
        (root / ".rtfm").mkdir(parents=True)
        slot = _Slot(root / ".rtfm")
        lines: list[str] = []
        try:
            slot.open(lines.append)
        finally:
            slot.close()
        assert not [ln for ln in lines if "identity" in ln]

    def test_a_repair_that_fails_does_not_keep_a_project_down(
            self, index, monkeypatch):
        root, _, _ = index
        import rtfm.core.repair as repair_mod
        monkeypatch.setattr(repair_mod, "repair_shared_identities",
                            lambda *a, **k: 1 / 0)
        slot = _Slot(root / ".rtfm")
        lines: list[str] = []
        try:
            slot.open(lines.append)
            assert slot.queue is not None, "the project must still be served"
        finally:
            slot.close()
        assert any("skipped" in ln for ln in lines)
