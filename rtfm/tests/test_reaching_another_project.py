"""Answering from an index that is not the one you are standing in.

RTFM resolves its database from the working directory. That is right for
the ordinary case and wrong for the one that matters most in a workshop of
several repositories: the knowledge that binds them together lives in none
of them. A rule that governs sixteen repositories is kept once, somewhere
shared, and an agent inside one of them cannot reach it — its search
resolves to its own index, the shared one is not in it, the query comes
back empty, and an empty answer reads as "there is no such rule".

Measured on 2026-09-06: an agent asked whether a project rule settled a
technical question, found nothing, concluded that nothing settled it, and
came within a step of deciding alone what had been decided a week earlier.

The rule that keeps this safe is that a visit is a read. A neighbour's index
has its own worker, and a reader that queues work into it is a second writer
under another name.
"""
from __future__ import annotations

import json

import pytest

from rtfm.core.projects import (
    UnknownProject, candidates, known_projects, resolve_project_db,
)


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    """Three projects enrolled, two of them sharing a name."""
    from rtfm.core.library import Library

    made = {}
    for rel, text in (
        ("hub", "# La table\n\nUne regle qui tranche la question.\n" * 20),
        ("atelier/kanopi", "# Kanopi\n\nLe moteur de scenes.\n" * 20),
        ("atelier/.publie/kanopi", "# Kanopi publie\n\nLa copie lisible.\n" * 20),
    ):
        root = tmp_path / rel
        (root / ".rtfm").mkdir(parents=True)
        doc = root / "doc.md"
        doc.write_text(text)
        lib = Library(root / ".rtfm" / "library.db")
        lib.ingest(doc, corpus="default",
                   metadata={"book_slug": f"{root.name}-doc", "source_file": "doc.md"})
        lib.set_sync_root("default", str(root))
        lib.update_indexed_file("doc.md", "h", "default", f"{root.name}-doc",
                                file_size=doc.stat().st_size)
        lib.close()
        made[rel] = root

    registry = tmp_path / "workers.json"
    registry.write_text(json.dumps(
        {"projects": [str(r / ".rtfm") for r in made.values()]}))
    monkeypatch.setattr("rtfm.core.supervisor.REGISTRY_PATH", registry)
    return made


class TestNamingAnIndex:

    def test_a_name_is_enough(self, fleet):
        assert resolve_project_db("hub") == fleet["hub"] / ".rtfm" / "library.db"

    def test_every_enrolled_project_is_listed(self, fleet):
        assert set(known_projects()) == {"hub", "kanopi"}

    def test_a_name_two_projects_answer_to_is_refused(self, fleet):
        """A working tree and its published copy hold different content.
        Picking one is worse than saying there are two."""
        with pytest.raises(UnknownProject) as exc:
            resolve_project_db("kanopi")
        assert "kanopi" in str(exc.value)
        assert str(fleet["atelier/kanopi"]) in str(exc.value)
        assert str(fleet["atelier/.publie/kanopi"]) in str(exc.value)

    def test_a_path_settles_what_a_name_cannot(self, fleet):
        chosen = fleet["atelier/.publie/kanopi"]
        assert resolve_project_db(str(chosen)) == chosen / ".rtfm" / "library.db"
        assert len(candidates("kanopi")) == 2

    def test_an_unknown_name_lists_the_reachable_ones(self, fleet):
        with pytest.raises(UnknownProject) as exc:
            resolve_project_db("kronos")
        assert "hub" in str(exc.value), "a dead end must name the way out"

    def test_an_enrolled_project_with_no_index_is_not_listed(
            self, fleet, tmp_path, monkeypatch):
        registry = tmp_path / "w2.json"
        registry.write_text(json.dumps(
            {"projects": [str(tmp_path / "parti" / ".rtfm")]}))
        monkeypatch.setattr("rtfm.core.supervisor.REGISTRY_PATH", registry)
        assert known_projects() == {}

    def test_no_registry_at_all_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("rtfm.core.supervisor.REGISTRY_PATH",
                            tmp_path / "absent.json")
        assert known_projects() == {}
        with pytest.raises(UnknownProject):
            resolve_project_db("hub")


class TestSearchingTheNeighbour:

    def test_the_shared_rule_is_findable_from_elsewhere(self, fleet, monkeypatch):
        """The measured failure, in the shape it had."""
        import rtfm.mcp as mcp_mod
        monkeypatch.setenv(
            "RTFM_DB", str(fleet["atelier/kanopi"] / ".rtfm" / "library.db"))
        monkeypatch.setattr(mcp_mod, "_library", None)
        monkeypatch.setattr(mcp_mod, "_foreign", {})
        search = getattr(mcp_mod.rtfm_search, "fn", mcp_mod.rtfm_search)

        local = search("regle tranche question", limit=3)
        assert "No results" in local, (
            "the shared rule must be out of reach without the parameter — "
            "that is the failure being fixed")
        found = search("regle tranche question", limit=3, project="hub")
        assert "doc.md" in found

    def test_the_answer_carries_paths_of_the_project_it_came_from(
            self, fleet, monkeypatch):
        """Resolved against our own roots, a neighbour's files land on paths
        that do not exist — and read, correctly and uselessly, as deleted."""
        import rtfm.mcp as mcp_mod
        monkeypatch.setenv(
            "RTFM_DB", str(fleet["atelier/kanopi"] / ".rtfm" / "library.db"))
        monkeypatch.setattr(mcp_mod, "_library", None)
        monkeypatch.setattr(mcp_mod, "_foreign", {})
        search = getattr(mcp_mod.rtfm_search, "fn", mcp_mod.rtfm_search)

        found = search("regle tranche question", limit=3, project="hub")
        assert str(fleet["hub"] / "doc.md") in found
        assert "deleted since indexing" not in found

    def test_an_unknown_project_says_which_ones_exist(self, fleet, monkeypatch):
        import rtfm.mcp as mcp_mod
        monkeypatch.setenv(
            "RTFM_DB", str(fleet["hub"] / ".rtfm" / "library.db"))
        monkeypatch.setattr(mcp_mod, "_library", None)
        monkeypatch.setattr(mcp_mod, "_foreign", {})
        search = getattr(mcp_mod.rtfm_search, "fn", mcp_mod.rtfm_search)
        with pytest.raises(Exception) as exc:
            search("quoi que ce soit", project="kronos")
        assert "hub" in str(exc.value)


class TestAVisitIsARead:

    def test_nothing_is_queued_into_the_neighbour(self, fleet, monkeypatch):
        """Its own worker owns its queue; a reader that writes there is a
        second writer under another name."""
        import rtfm.mcp as mcp_mod
        from rtfm.core.queue import Queue

        monkeypatch.setenv(
            "RTFM_DB", str(fleet["atelier/kanopi"] / ".rtfm" / "library.db"))
        monkeypatch.setattr(mcp_mod, "_library", None)
        monkeypatch.setattr(mcp_mod, "_foreign", {})
        # The neighbour's file goes away between indexing and reading.
        (fleet["hub"] / "doc.md").unlink()

        search = getattr(mcp_mod.rtfm_search, "fn", mcp_mod.rtfm_search)
        search("regle tranche question", limit=3, project="hub")

        q = Queue(str(fleet["hub"] / ".rtfm" / "library.db"))
        try:
            assert q.dequeue() is None, "a visit queued work into a neighbour"
        finally:
            q.close()

    def test_a_deletion_in_the_neighbour_is_reported_not_hidden(
            self, fleet, monkeypatch):
        """We may not repair it, so we must not silently drop it either —
        that would leave the reader with no answer and no reason."""
        import rtfm.mcp as mcp_mod
        monkeypatch.setenv(
            "RTFM_DB", str(fleet["atelier/kanopi"] / ".rtfm" / "library.db"))
        monkeypatch.setattr(mcp_mod, "_library", None)
        monkeypatch.setattr(mcp_mod, "_foreign", {})
        (fleet["hub"] / "doc.md").unlink()

        search = getattr(mcp_mod.rtfm_search, "fn", mcp_mod.rtfm_search)
        found = search("regle tranche question", limit=3, project="hub")
        assert "deleted since indexing" in found
