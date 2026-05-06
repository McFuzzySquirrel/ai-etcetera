"""One-time migration: convert a v1 graph.db (nodes + edges tables) to the
v2 triple-store schema (single ``triples`` table).

Usage::

    python -m dirk.migrate path/to/graph.db

The original database is left untouched; the migrated data is written into
a new file alongside it (``graph.db.v2``), which you can then rename over
the original once you are satisfied.

Migration rules
---------------
* Each v1 **node** becomes a set of property triples:
  - ``(id, "rdf:type", kind)``
  - ``(id, "name",     name)``
  - one triple per key in the ``properties`` JSON blob
* Each v1 **edge** becomes a single relationship triple:
  - ``(src, kind, dst)`` with its ``confidence``, ``evidence``,
    ``discovered_by``, and ``discovered_at`` preserved
* The ``vectors`` and ``runs`` tables are copied verbatim.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path


def migrate(src_path: Path, dst_path: Path | None = None) -> Path:
    """Migrate *src_path* (v1 schema) into a new v2 database.

    Returns the path of the migrated database.
    """
    if dst_path is None:
        dst_path = src_path.with_suffix(".db.v2")

    # Start from the new schema by copying the source and applying schema.
    # Actually we build fresh so we get the v2 schema cleanly.
    if dst_path.exists():
        dst_path.unlink()

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row

    dst = sqlite3.connect(dst_path)

    # Check that the source has the v1 tables.
    tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "triples" in tables:
        print(f"[migrate] {src_path} already uses the v2 schema — nothing to do.", file=sys.stderr)
        src.close()
        dst.close()
        dst_path.unlink()
        return src_path

    if "nodes" not in tables or "edges" not in tables:
        raise ValueError(
            f"{src_path} does not look like a v1 dirk database "
            f"(expected 'nodes' and 'edges' tables; found: {sorted(tables)})"
        )

    # Apply the v2 schema to the destination.
    from importlib import resources
    sql = resources.files("dirk.schema").joinpath("graph.sql").read_text(encoding="utf-8")
    dst.executescript(sql)

    # Migrate nodes → property triples.
    node_rows = src.execute("SELECT * FROM nodes").fetchall()
    for row in node_rows:
        node_id = row["id"]
        kind = row["kind"]
        name = row["name"]
        first_seen = row["first_seen"]

        for predicate, obj in [("rdf:type", kind), ("name", name)]:
            dst.execute(
                "INSERT OR REPLACE INTO triples"
                "(subject, predicate, object, confidence, evidence, discovered_by, discovered_at) "
                "VALUES (?, ?, ?, 1.0, '[]', 'migration', ?)",
                (node_id, predicate, obj, first_seen),
            )

        try:
            props: dict = json.loads(row["properties"] or "{}")
        except (json.JSONDecodeError, TypeError):
            props = {}

        for key, value in props.items():
            val_str = json.dumps(value, sort_keys=True) if not isinstance(value, str) else value
            dst.execute(
                "INSERT OR REPLACE INTO triples"
                "(subject, predicate, object, confidence, evidence, discovered_by, discovered_at) "
                "VALUES (?, ?, ?, 1.0, '[]', 'migration', ?)",
                (node_id, key, val_str, first_seen),
            )

    # Migrate edges → relationship triples.
    edge_rows = src.execute("SELECT * FROM edges").fetchall()
    for row in edge_rows:
        dst.execute(
            "INSERT OR IGNORE INTO triples"
            "(subject, predicate, object, confidence, evidence, discovered_by, discovered_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["src"],
                row["kind"],
                row["dst"],
                row["confidence"],
                row["evidence"] or "[]",
                row["discovered_by"],
                row["discovered_at"],
            ),
        )

    # Copy runs verbatim.
    if "runs" in tables:
        run_rows = src.execute("SELECT * FROM runs").fetchall()
        for row in run_rows:
            dst.execute(
                "INSERT INTO runs(id, started_at, finished_at, depth, skills, nodes_added, edges_added, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["id"],
                    row["started_at"],
                    row["finished_at"],
                    row["depth"],
                    row["skills"],
                    row["nodes_added"],
                    row["edges_added"],
                    row["notes"],
                ),
            )

    # Copy vectors verbatim (no FK on node_id in v2).
    if "vectors" in tables:
        vec_rows = src.execute("SELECT * FROM vectors").fetchall()
        for row in vec_rows:
            dst.execute(
                "INSERT OR IGNORE INTO vectors(node_id, model, dim, vector, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (row["node_id"], row["model"], row["dim"], row["vector"], row["updated_at"]),
            )

    dst.commit()
    src.close()
    dst.close()

    print(
        f"[migrate] {len(node_rows)} node(s) and {len(edge_rows)} edge(s) "
        f"migrated → {dst_path}",
        file=sys.stderr,
    )
    return dst_path


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Migrate a Dirk v1 graph.db (nodes+edges) to the v2 triple-store schema."
    )
    parser.add_argument("db", type=Path, help="Path to the v1 graph.db file.")
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Output path for the migrated database (default: <db>.v2).",
    )
    parser.add_argument(
        "--replace", action="store_true",
        help="Replace the original database with the migrated one.",
    )
    args = parser.parse_args()

    dst = migrate(args.db, args.output)
    if args.replace and dst != args.db:
        shutil.move(str(dst), str(args.db))
        print(f"[migrate] replaced {args.db}", file=sys.stderr)


if __name__ == "__main__":
    main()
