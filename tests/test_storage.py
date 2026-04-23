"""Smoke tests for the SQLite knowledge store."""

from __future__ import annotations

from dirk.storage import Edge, GraphStore, Node


def test_upsert_node_and_edge_roundtrip(tmp_path):
    db = tmp_path / "graph.db"
    with GraphStore(db) as store:
        assert store.upsert_node(Node(id="repo:o/a", kind="Repo", name="o/a"))
        assert store.upsert_node(Node(id="repo:o/b", kind="Repo", name="o/b"))
        # Same id again → update, not insert.
        assert not store.upsert_node(Node(id="repo:o/a", kind="Repo", name="o/a", properties={"x": 1}))

        assert store.upsert_edge(Edge(
            src="repo:o/a", dst="repo:o/b", kind="MENTIONS",
            confidence=0.4, evidence=[{"ref": "x", "note": "n"}],
            discovered_by="test",
        ))
        # Re-inserting merges evidence and keeps max confidence.
        assert not store.upsert_edge(Edge(
            src="repo:o/a", dst="repo:o/b", kind="MENTIONS",
            confidence=0.7, evidence=[{"ref": "y", "note": "n2"}],
            discovered_by="test",
        ))

        nodes = list(store.iter_nodes())
        assert {n.id for n in nodes} == {"repo:o/a", "repo:o/b"}

        edges = list(store.iter_edges())
        assert len(edges) == 1
        assert edges[0]["confidence"] == 0.7
        refs = {e["ref"] for e in edges[0]["evidence"]}
        assert refs == {"x", "y"}


def test_invalid_kinds_raise(tmp_path):
    with GraphStore(tmp_path / "g.db") as store:
        try:
            store.upsert_node(Node(id="x", kind="Bogus", name="x"))
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for bad node kind")

        store.upsert_node(Node(id="repo:o/a", kind="Repo", name="o/a"))
        store.upsert_node(Node(id="repo:o/b", kind="Repo", name="o/b"))
        try:
            store.upsert_edge(Edge(src="repo:o/a", dst="repo:o/b", kind="BOGUS"))
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for bad edge kind")


def test_cytoscape_export_shape(tmp_path):
    with GraphStore(tmp_path / "g.db") as store:
        store.upsert_node(Node(id="repo:o/a", kind="Repo", name="o/a"))
        store.upsert_node(Node(id="repo:o/b", kind="Repo", name="o/b"))
        store.upsert_edge(Edge(src="repo:o/a", dst="repo:o/b", kind="MENTIONS",
                               confidence=0.5, discovered_by="t"))
        export = store.to_cytoscape()
    nodes = [el for el in export["elements"] if "source" not in el["data"]]
    edges = [el for el in export["elements"] if "source" in el["data"]]
    assert len(nodes) == 2
    assert len(edges) == 1
    assert edges[0]["data"]["kind"] == "MENTIONS"


def test_runs_lifecycle(tmp_path):
    with GraphStore(tmp_path / "g.db") as store:
        run_id = store.start_run("standard", ["repo_inventory"])
        store.upsert_node(Node(id="repo:o/a", kind="Repo", name="o/a"))
        store.finish_run(run_id, notes="ok")
        rows = store.latest_runs()
        assert rows
        assert rows[0]["finished_at"] is not None
