# ADR-0001: Migrate graph storage from nodes+edges to a triple store

**Date:** 2026-05-06  
**Status:** Accepted  
**Deciders:** Dirk maintainers

---

## Context

Dirk's original SQLite schema stored the knowledge graph as two separate tables:

- **`nodes`** — one row per entity, with columns `id`, `kind`, `name`, and a
  `properties` JSON blob for kind-specific attributes.
- **`edges`** — one row per directed relationship, with columns `src`, `dst`,
  `kind`, `confidence`, `evidence`, `discovered_by`, `discovered_at`.

This worked fine at project start but created several friction points as the
model evolved:

1. **Properties and relationships are fundamentally different things in the
   schema, yet conceptually they are both statements about entities.** Adding a
   new attribute to a node kind required either widening the `properties` blob
   (untyped, hard to query) or adding a column migration.

2. **Foreign-key constraints on `edges` forced `nodes` to be inserted first.**
   This made certain loading orders awkward and prevented streaming pipelines
   that emit relationship triples before their subjects are fully resolved.

3. **Diffing and provenance** were harder than they needed to be: node
   properties had no per-field timestamp or evidence trail.

4. **Schema evolution** — adding new node kinds or property predicates — required
   code changes in multiple places (the SQL DDL, the `Node` dataclass, the skill
   that emits the node, the writer that consumes it).

A *triple store* approach — storing every fact as `(subject, predicate, object)`
— eliminates all of these issues at the cost of slightly more verbose queries.
This pattern is well-established in semantic-web (RDF/SPARQL) and knowledge-graph
literature and is a natural fit for the additive, evidence-carrying knowledge
graph Dirk builds.

---

## Decision

Replace the `nodes` and `edges` tables with a single **`triples`** table:

```sql
CREATE TABLE triples (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject       TEXT NOT NULL,
    predicate     TEXT NOT NULL,
    object        TEXT NOT NULL,
    confidence    REAL NOT NULL DEFAULT 1.0,
    evidence      TEXT NOT NULL DEFAULT '[]',   -- JSON [{ref, note}]
    discovered_by TEXT NOT NULL DEFAULT 'system',
    discovered_at TEXT NOT NULL,
    UNIQUE(subject, predicate, object)
);
```

### Predicate vocabulary

Two classes of predicates coexist in the same table:

| Class | Examples | Semantics |
|---|---|---|
| Property predicates | `rdf:type`, `name`, `description`, `language`, `ecosystem` | `object` is a scalar string or JSON-encoded value |
| Relationship predicates | `DEPENDS_ON`, `MENTIONS`, `EXPOSES`, `SIMILAR_TO`, `COULD_COMPOSE_WITH`, `AUTHORED_BY`, `EVOLVED_FROM` | `object` is the destination node id |

`NODE_KINDS` (`Repo`, `Concept`, `Technology`, …) become values of the
`rdf:type` predicate rather than a column constraint.  `EDGE_KINDS` become
predicate names, indistinguishable from property predicates at the storage
level and differentiated only by the `EDGE_KINDS` set in application code.

### Conflict/merge strategy

- **Property predicates** — uniqueness key is `(subject, predicate)`.
  Upserting replaces the existing value (delete-then-insert).
- **Relationship predicates** — uniqueness key is `(subject, predicate, object)`.
  Upserting merges evidence (de-duplicated) and takes the maximum confidence.

### Compatibility wrappers

`Node` and `Edge` dataclasses are **retained** as convenience types.
`upsert_node(node)` fans out to multiple `upsert_triple()` calls; `upsert_edge(edge)`
emits a single relationship triple.  Existing skills require no changes.

### Migration

A one-time migration script (`src/dirk/migrate.py`, CLI: `dirk migrate`) converts
an existing v1 `graph.db` to the v2 schema:

- Each v1 node → `rdf:type` + `name` + one triple per property key.
- Each v1 edge → a single relationship triple preserving all metadata.
- `runs` and `vectors` tables are copied verbatim.

---

## Consequences

### Positive

- **Single DDL change point.** New node kinds and new property predicates require
  zero schema migrations; they are just new string values in the `predicate`
  column.
- **Per-fact provenance.** Every triple carries its own `confidence`, `evidence`,
  `discovered_by`, and `discovered_at`.  Individual properties can now be traced
  back to the skill that produced them.
- **FK-free node insertion.** Relationship triples can reference subjects that do
  not yet have a corresponding `rdf:type` triple; the store will reconstruct a
  partial node gracefully.
- **Uniform query surface.** "Give me all facts about subject X" is a single
  `WHERE subject = ?` query regardless of whether the facts are properties or
  relationships.
- **Diffable.** `UNIQUE(subject, predicate, object)` means a graph snapshot is
  genuinely set-based; diffs between snapshots are trivially meaningful.

### Negative / trade-offs

- **Node reconstruction is costlier.** `get_node(id)` now executes a
  `WHERE subject = ?` query and groups results in Python instead of returning a
  single row.  This is acceptable given graph sizes today (<10k nodes).
- **Property cardinality is implicit.** Nothing in the schema prevents two
  `name` triples for the same subject; discipline is enforced at the application
  layer by the property-predicate conflict strategy.
- **Existing databases require migration.** Teams with a v1 `graph.db` must run
  `dirk migrate graph/graph.db --replace` once.
- **`EDGE_KINDS` is still a code-level constant.** The distinction between
  relationship predicates and property predicates is not enforced by SQLite; it
  relies on the `EDGE_KINDS` set in `storage.py`.

### Neutral

- `vectors` and `runs` tables are unchanged.
- `to_cytoscape()` output format is unchanged; the export layer reconstructs
  node/edge dicts from triples transparently.
- Indexes on `subject`, `predicate`, and `object` keep common query patterns
  (iterate by kind, iterate by edge kind, look up a subject) efficient.

---

## Alternatives considered

### Keep nodes+edges, add a `properties` side-table

Adds a `node_properties(node_id, key, value)` table for per-property
provenance.  Rejected: two tables still, and relationship edges are still
treated differently from property facts.

### Use a dedicated graph database (DuckDB, Kuzu, Neo4j)

Appropriate for much larger graphs or query workloads that need SPARQL/Cypher.
Rejected for now: SQLite keeps the stack simple, file-based, and embeddable;
the `graph.db` file commits cleanly to git and is trivially diffable.  The
README already documents the upgrade path.

### Strict RDF (subject, predicate, object) with named graphs

Full RDF with named-graph contexts and typed literals would be maximally
correct.  Rejected: unnecessary complexity for a project-scoped knowledge
graph whose query surface is well-understood.

---

## References

- [Original schema](../../src/dirk/schema/graph.sql)
- [Storage implementation](../../src/dirk/storage.py)
- [Migration script](../../src/dirk/migrate.py)
- [Phase status document](../PHASES.md)
