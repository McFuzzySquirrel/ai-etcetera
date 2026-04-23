-- Dirk knowledge-graph schema.
--
-- A simple, diffable node/edge model in SQLite. Every edge carries
-- confidence and an evidence trail so the agent can show *why* it thinks
-- two things are connected.

CREATE TABLE IF NOT EXISTS nodes (
    id            TEXT PRIMARY KEY,            -- stable id, e.g. "repo:owner/name" or "concept:nlp"
    kind          TEXT NOT NULL,               -- Repo | Concept | Technology | Interface | Person | Domain | Artifact
    name          TEXT NOT NULL,               -- human-readable label
    properties    TEXT NOT NULL DEFAULT '{}',  -- JSON blob for kind-specific fields
    first_seen    TEXT NOT NULL,               -- ISO8601 UTC
    last_seen     TEXT NOT NULL                -- ISO8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);

CREATE TABLE IF NOT EXISTS edges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    src             TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    dst             TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,             -- DEPENDS_ON | MENTIONS | EXPOSES | SIMILAR_TO | COULD_COMPOSE_WITH | AUTHORED_BY | EVOLVED_FROM
    confidence      REAL NOT NULL DEFAULT 1.0, -- 0..1
    evidence        TEXT NOT NULL DEFAULT '[]',-- JSON array of {ref, note}
    discovered_at   TEXT NOT NULL,             -- ISO8601 UTC
    discovered_by   TEXT NOT NULL,             -- skill name
    UNIQUE(src, dst, kind)
);

CREATE INDEX IF NOT EXISTS idx_edges_src   ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst   ON edges(dst);
CREATE INDEX IF NOT EXISTS idx_edges_kind  ON edges(kind);

-- Optional embeddings table for the semantic skills (Phase 3+).
CREATE TABLE IF NOT EXISTS vectors (
    node_id   TEXT PRIMARY KEY REFERENCES nodes(id) ON DELETE CASCADE,
    model     TEXT NOT NULL,                   -- which embedding model produced it
    dim       INTEGER NOT NULL,
    vector    BLOB NOT NULL,                   -- raw float32s
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
