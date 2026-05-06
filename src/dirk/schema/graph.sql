-- Dirk knowledge-graph schema v2: triple store.
--
-- Everything — node properties AND relationships — lives in a single
-- triples table keyed on (subject, predicate, object).  Property
-- predicates (e.g. "rdf:type", "name") store scalar string objects;
-- relationship predicates (e.g. DEPENDS_ON, MENTIONS) store the
-- destination node id as the object.  This unified model makes the graph
-- fully diffable without separate node and edge tables.

CREATE TABLE IF NOT EXISTS triples (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject       TEXT NOT NULL,               -- stable node id, e.g. "repo:owner/name"
    predicate     TEXT NOT NULL,               -- "rdf:type" | "name" | EDGE_KINDS | custom property
    object        TEXT NOT NULL,               -- literal value, JSON, or destination node id
    confidence    REAL NOT NULL DEFAULT 1.0,   -- 0..1
    evidence      TEXT NOT NULL DEFAULT '[]',  -- JSON array of {ref, note}
    discovered_by TEXT NOT NULL DEFAULT 'system',
    discovered_at TEXT NOT NULL,               -- ISO8601 UTC
    UNIQUE(subject, predicate, object)
);

CREATE INDEX IF NOT EXISTS idx_triples_subject   ON triples(subject);
CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
CREATE INDEX IF NOT EXISTS idx_triples_object    ON triples(object);

-- Optional embeddings table for the semantic skills (Phase 3+).
CREATE TABLE IF NOT EXISTS vectors (
    node_id    TEXT PRIMARY KEY,               -- subject id (no FK so triples can be deleted freely)
    model      TEXT NOT NULL,                  -- which embedding model produced it
    dim        INTEGER NOT NULL,
    vector     BLOB NOT NULL,                  -- raw float32s
    updated_at TEXT NOT NULL
);

-- A run log so periodic execution + delta reporting have a notion of
-- "the previous run". Each invocation of `dirk run` appends a row.
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    depth         TEXT NOT NULL,
    skills        TEXT NOT NULL,               -- JSON list of skills executed
    nodes_added   INTEGER NOT NULL DEFAULT 0,
    edges_added   INTEGER NOT NULL DEFAULT 0,
    notes         TEXT
);
