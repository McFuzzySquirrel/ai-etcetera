"""SQLite-backed knowledge-graph storage for Dirk.

The store is intentionally simple: a single ``triples`` table holds both
node properties and relationships as ``(subject, predicate, object)``
statements.  Every mutation goes through this layer so the graph stays
consistent and runs are reproducible / diffable.

Public API
----------
* :class:`Triple` — the atomic storage unit.
* :class:`Node` / :class:`Edge` — convenience types kept for compatibility;
  ``upsert_node`` fans out to multiple triples, ``upsert_edge`` emits one.
* :class:`GraphStore` — the main interface.

Predicate vocabulary
--------------------
* ``"rdf:type"`` — node kind (Repo, Concept, …).
* ``"name"``     — human-readable label.
* Any other non-EDGE_KINDS predicate — arbitrary node property.
* Any predicate in ``EDGE_KINDS`` — a directed relationship whose ``object``
  is the destination node id.
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


# -- predicate vocabulary -----------------------------------------------

NODE_KINDS = {"Repo", "Concept", "Technology", "Interface", "Person", "Domain", "Artifact", "Motivation"}
EDGE_KINDS = {
    "DEPENDS_ON",
    "MENTIONS",
    "EXPOSES",
    "SIMILAR_TO",
    "COULD_COMPOSE_WITH",
    "AUTHORED_BY",
    "EVOLVED_FROM",
    "MOTIVATED_BY",
    "INSPIRED_BY",
}

# Predicates that are intrinsic to every node and managed by upsert_node.
_NODE_CORE_PREDICATES = {"rdf:type", "name"}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- data classes --------------------------------------------------------

@dataclass
class Triple:
    """Atomic triple: (subject, predicate, object) plus provenance."""
    subject: str
    predicate: str
    object: str
    confidence: float = 1.0
    evidence: list[dict[str, str]] = field(default_factory=list)
    discovered_by: str = "system"
    discovered_at: str = field(default_factory=utcnow_iso)


@dataclass
class Node:
    """Convenience type for node operations; fans out to triples internally."""
    id: str
    kind: str
    name: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    """Convenience type for edge operations; stored as a single triple internally."""
    src: str
    dst: str
    kind: str
    confidence: float = 1.0
    evidence: list[dict[str, str]] = field(default_factory=list)
    discovered_by: str = "unknown"


# -- store ---------------------------------------------------------------

class GraphStore:
    """Thin wrapper around SQLite with the Dirk triple-store schema applied."""

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

    # -- triples (low-level) ---------------------------------------------

    def upsert_triple(self, triple: Triple) -> bool:
        """Insert or update a triple.

        * For **relationship** predicates (those in ``EDGE_KINDS``): the
          uniqueness key is ``(subject, predicate, object)``.  On conflict
          the confidence is raised to the maximum and evidence lists are
          merged (de-duplicated).
        * For **property** predicates (everything else): the uniqueness key
          is effectively ``(subject, predicate)`` — any existing triple for
          the same subject/predicate is deleted before the new one is
          inserted, ensuring each subject carries at most one value per
          property predicate.

        Returns ``True`` if a new row was created, ``False`` otherwise.
        """
        now = triple.discovered_at or utcnow_iso()

        if triple.predicate in EDGE_KINDS:
            # Relationship triple: merge evidence on conflict.
            existing = self._conn.execute(
                "SELECT id, confidence, evidence FROM triples "
                "WHERE subject = ? AND predicate = ? AND object = ?",
                (triple.subject, triple.predicate, triple.object),
            ).fetchone()
            if existing is None:
                self._conn.execute(
                    "INSERT INTO triples"
                    "(subject, predicate, object, confidence, evidence, discovered_by, discovered_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        triple.subject,
                        triple.predicate,
                        triple.object,
                        triple.confidence,
                        json.dumps(triple.evidence, sort_keys=True),
                        triple.discovered_by,
                        now,
                    ),
                )
                return True
            # Merge: take max confidence, append new evidence (de-duplicated).
            prior_evidence = json.loads(existing["evidence"] or "[]")
            merged: list[dict[str, str]] = list(prior_evidence)
            seen = {(e.get("ref"), e.get("note")) for e in merged}
            for ev in triple.evidence:
                key = (ev.get("ref"), ev.get("note"))
                if key not in seen:
                    merged.append(ev)
                    seen.add(key)
            new_conf = max(float(existing["confidence"]), triple.confidence)
            self._conn.execute(
                "UPDATE triples SET confidence = ?, evidence = ? WHERE id = ?",
                (new_conf, json.dumps(merged, sort_keys=True), existing["id"]),
            )
            return False

        # Property triple: replace any existing value for this subject+predicate.
        self._conn.execute(
            "DELETE FROM triples WHERE subject = ? AND predicate = ?",
            (triple.subject, triple.predicate),
        )
        self._conn.execute(
            "INSERT INTO triples"
            "(subject, predicate, object, confidence, evidence, discovered_by, discovered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                triple.subject,
                triple.predicate,
                triple.object,
                triple.confidence,
                json.dumps(triple.evidence, sort_keys=True),
                triple.discovered_by,
                now,
            ),
        )
        return True

    # -- nodes (convenience layer) ----------------------------------------

    def upsert_node(self, node: Node) -> bool:
        """Insert or update a node.

        Fans out to one ``rdf:type`` triple, one ``name`` triple, and one
        triple per extra property.  Returns ``True`` if the node is new
        (i.e. no ``rdf:type`` triple existed for this subject yet).
        """
        if node.kind not in NODE_KINDS:
            raise ValueError(f"Unknown node kind: {node.kind!r}")
        now = utcnow_iso()

        # Determine whether this subject already exists.
        existing = self._conn.execute(
            "SELECT 1 FROM triples WHERE subject = ? AND predicate = 'rdf:type'",
            (node.id,),
        ).fetchone()
        is_new = existing is None

        # Core triples: type and name (property semantics — replace on update).
        self.upsert_triple(Triple(
            subject=node.id, predicate="rdf:type", object=node.kind,
            discovered_by="system", discovered_at=now,
        ))
        self.upsert_triple(Triple(
            subject=node.id, predicate="name", object=node.name,
            discovered_by="system", discovered_at=now,
        ))

        # Extra property triples.
        for key, value in node.properties.items():
            val_str = json.dumps(value, sort_keys=True) if not isinstance(value, str) else value
            self.upsert_triple(Triple(
                subject=node.id, predicate=key, object=val_str,
                discovered_by="system", discovered_at=now,
            ))

        if is_new:
            self.nodes_added += 1
        return is_new

    def get_node(self, node_id: str) -> Node | None:
        """Reconstruct a :class:`Node` from all property triples for *node_id*."""
        rows = self._conn.execute(
            "SELECT predicate, object FROM triples WHERE subject = ?",
            (node_id,),
        ).fetchall()
        kind: str | None = None
        name: str | None = None
        properties: dict[str, Any] = {}
        for pred, obj in rows:
            if pred == "rdf:type":
                kind = obj
            elif pred == "name":
                name = obj
            elif pred not in EDGE_KINDS:
                try:
                    properties[pred] = json.loads(obj)
                except (json.JSONDecodeError, ValueError):
                    properties[pred] = obj
        if kind is None or name is None:
            return None
        return Node(id=node_id, kind=kind, name=name, properties=properties)

    def iter_nodes(self, kind: str | None = None) -> Iterator[Node]:
        """Iterate over nodes, optionally filtered by kind."""
        if kind:
            rows = self._conn.execute(
                "SELECT subject FROM triples "
                "WHERE predicate = 'rdf:type' AND object = ? ORDER BY subject",
                (kind,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT subject FROM triples "
                "WHERE predicate = 'rdf:type' ORDER BY object, subject"
            ).fetchall()
        for (subject,) in rows:
            node = self.get_node(subject)
            if node is not None:
                yield node

    # -- edges (convenience layer) ----------------------------------------

    def upsert_edge(self, edge: Edge) -> bool:
        """Insert a new edge, or merge evidence into an existing one.

        Stored as a single triple ``(src, kind, dst)``.
        Returns ``True`` if a new edge was created.
        """
        if edge.kind not in EDGE_KINDS:
            raise ValueError(f"Unknown edge kind: {edge.kind!r}")
        if not 0.0 <= edge.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        triple = Triple(
            subject=edge.src,
            predicate=edge.kind,
            object=edge.dst,
            confidence=edge.confidence,
            evidence=edge.evidence,
            discovered_by=edge.discovered_by,
            discovered_at=utcnow_iso(),
        )
        is_new = self.upsert_triple(triple)
        if is_new:
            self.edges_added += 1
        return is_new

    def iter_edges(self, kind: str | None = None) -> Iterator[dict[str, Any]]:
        """Iterate over relationship triples as edge dicts."""
        if kind:
            rows = self._conn.execute(
                "SELECT * FROM triples WHERE predicate = ? ORDER BY subject, object",
                (kind,),
            )
        else:
            placeholders = ", ".join("?" * len(EDGE_KINDS))
            rows = self._conn.execute(
                f"SELECT * FROM triples "
                f"WHERE predicate IN ({placeholders}) ORDER BY predicate, subject, object",
                tuple(sorted(EDGE_KINDS)),
            )
        for row in rows:
            yield {
                "src": row["subject"],
                "dst": row["object"],
                "kind": row["predicate"],
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
        # Strip reserved Cytoscape keys from node properties so a property
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
