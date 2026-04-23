"""SQLite-backed knowledge-graph storage for Dirk.

The store is intentionally simple: nodes + edges + optional embeddings.
Every mutation goes through this layer so the graph stays consistent and
runs are reproducible / diffable.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Iterator


# -- node / edge types ---------------------------------------------------

NODE_KINDS = {"Repo", "Concept", "Technology", "Interface", "Person", "Domain", "Artifact"}
EDGE_KINDS = {
    "DEPENDS_ON",
    "MENTIONS",
    "EXPOSES",
    "SIMILAR_TO",
    "COULD_COMPOSE_WITH",
    "AUTHORED_BY",
    "EVOLVED_FROM",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Node:
    id: str
    kind: str
    name: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    src: str
    dst: str
    kind: str
    confidence: float = 1.0
    evidence: list[dict[str, str]] = field(default_factory=list)
    discovered_by: str = "unknown"


# -- store ---------------------------------------------------------------

class GraphStore:
    """Thin wrapper around SQLite with the Dirk schema applied."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA foreign_keys = ON;")
        self._conn.row_factory = sqlite3.Row
        self._apply_schema()
        self.nodes_added = 0
        self.edges_added = 0

    # -- lifecycle -------------------------------------------------------

    def _apply_schema(self) -> None:
        sql = resources.files("dirk.schema").joinpath("graph.sql").read_text(encoding="utf-8")
        self._conn.executescript(sql)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "GraphStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # -- nodes -----------------------------------------------------------

    def upsert_node(self, node: Node) -> bool:
        """Insert or update a node. Returns True if newly inserted."""
        if node.kind not in NODE_KINDS:
            raise ValueError(f"Unknown node kind: {node.kind!r}")
        now = utcnow_iso()
        cur = self._conn.execute("SELECT id FROM nodes WHERE id = ?", (node.id,))
        existing = cur.fetchone()
        props_json = json.dumps(node.properties, sort_keys=True)
        if existing is None:
            self._conn.execute(
                "INSERT INTO nodes(id, kind, name, properties, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (node.id, node.kind, node.name, props_json, now, now),
            )
            self.nodes_added += 1
            return True
        self._conn.execute(
            "UPDATE nodes SET name = ?, properties = ?, last_seen = ? WHERE id = ?",
            (node.name, props_json, now, node.id),
        )
        return False

    def get_node(self, node_id: str) -> Node | None:
        row = self._conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            return None
        return Node(
            id=row["id"],
            kind=row["kind"],
            name=row["name"],
            properties=json.loads(row["properties"] or "{}"),
        )

    def iter_nodes(self, kind: str | None = None) -> Iterator[Node]:
        if kind:
            rows = self._conn.execute("SELECT * FROM nodes WHERE kind = ? ORDER BY id", (kind,))
        else:
            rows = self._conn.execute("SELECT * FROM nodes ORDER BY kind, id")
        for row in rows:
            yield Node(
                id=row["id"],
                kind=row["kind"],
                name=row["name"],
                properties=json.loads(row["properties"] or "{}"),
            )

    # -- edges -----------------------------------------------------------

    def upsert_edge(self, edge: Edge) -> bool:
        """Insert a new edge, or merge evidence into an existing one."""
        if edge.kind not in EDGE_KINDS:
            raise ValueError(f"Unknown edge kind: {edge.kind!r}")
        if not 0.0 <= edge.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        now = utcnow_iso()
        existing = self._conn.execute(
            "SELECT id, confidence, evidence FROM edges WHERE src = ? AND dst = ? AND kind = ?",
            (edge.src, edge.dst, edge.kind),
        ).fetchone()
        if existing is None:
            self._conn.execute(
                "INSERT INTO edges(src, dst, kind, confidence, evidence, discovered_at, discovered_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    edge.src,
                    edge.dst,
                    edge.kind,
                    edge.confidence,
                    json.dumps(edge.evidence, sort_keys=True),
                    now,
                    edge.discovered_by,
                ),
            )
            self.edges_added += 1
            return True
        # Merge: take max confidence, append new evidence (de-duplicated).
        prior_evidence = json.loads(existing["evidence"] or "[]")
        merged: list[dict[str, str]] = list(prior_evidence)
        seen = {(e.get("ref"), e.get("note")) for e in merged}
        for ev in edge.evidence:
            key = (ev.get("ref"), ev.get("note"))
            if key not in seen:
                merged.append(ev)
                seen.add(key)
        new_conf = max(float(existing["confidence"]), edge.confidence)
        self._conn.execute(
            "UPDATE edges SET confidence = ?, evidence = ? WHERE id = ?",
            (new_conf, json.dumps(merged, sort_keys=True), existing["id"]),
        )
        return False

    def iter_edges(self, kind: str | None = None) -> Iterator[dict[str, Any]]:
        if kind:
            rows = self._conn.execute("SELECT * FROM edges WHERE kind = ? ORDER BY src, dst", (kind,))
        else:
            rows = self._conn.execute("SELECT * FROM edges ORDER BY kind, src, dst")
        for row in rows:
            yield {
                "src": row["src"],
                "dst": row["dst"],
                "kind": row["kind"],
                "confidence": row["confidence"],
                "evidence": json.loads(row["evidence"] or "[]"),
                "discovered_at": row["discovered_at"],
                "discovered_by": row["discovered_by"],
            }

    # -- runs ------------------------------------------------------------

    def start_run(self, depth: str, skills: Iterable[str]) -> int:
        cur = self._conn.execute(
            "INSERT INTO runs(started_at, depth, skills) VALUES (?, ?, ?)",
            (utcnow_iso(), depth, json.dumps(list(skills))),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, *, notes: str | None = None) -> None:
        self._conn.execute(
            "UPDATE runs SET finished_at = ?, nodes_added = ?, edges_added = ?, notes = ? WHERE id = ?",
            (utcnow_iso(), self.nodes_added, self.edges_added, notes, run_id),
        )
        self._conn.commit()

    def latest_runs(self, limit: int = 2) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # -- export ----------------------------------------------------------

    def to_cytoscape(self) -> dict[str, Any]:
        """Export the graph as a Cytoscape.js-compatible JSON document."""
        # Cytoscape treats ``data.source`` / ``data.target`` as edge markers,
        # and ``data.id`` / ``data.kind`` / ``data.label`` are structural.
        # Strip those keys from node properties before merging so a property
        # name collision can never corrupt the export.
        reserved = {"id", "label", "kind", "source", "target"}
        elements: list[dict[str, Any]] = []
        for node in self.iter_nodes():
            safe_props = {k: v for k, v in node.properties.items() if k not in reserved}
            elements.append({
                "data": {
                    "id": node.id,
                    "label": node.name,
                    "kind": node.kind,
                    **safe_props,
                }
            })
        for edge in self.iter_edges():
            elements.append({
                "data": {
                    "id": f"{edge['src']}->{edge['dst']}:{edge['kind']}",
                    "source": edge["src"],
                    "target": edge["dst"],
                    "kind": edge["kind"],
                    "confidence": edge["confidence"],
                    "discovered_by": edge["discovered_by"],
                }
            })
        return {"elements": elements, "generated_at": utcnow_iso()}
