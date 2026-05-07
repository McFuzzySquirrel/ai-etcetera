# How Dirk Works: Surfacing the Interconnectedness of Your Repositories

*Published: 2026-05-06*

---

> *"I may not have gone where I intended to go, but I think I have ended up where I needed to be."*
> — Douglas Adams, *The Long Dark Tea-Time of the Soul*

Most engineering organisations own many repositories. Most of the time, those
repositories are islands. Developers know their own island well. They might
know the names of a few others. But the relationships between them — shared
dependencies, overlapping problem domains, interfaces that fit together,
concepts that recur in different contexts — are invisible.

**Dirk** exists to make that invisible structure visible. This post walks
through the key concepts behind how it works: knowledge graphs, triple stores,
a staged skills pipeline, and local-first semantic linking. No hosting required,
no API key needed, and the whole thing commits cleanly to git.

> Update (2026-05-08): Phase 4 now includes a two-stage curation flow with an
> explicit Ollama review budget. See [ADR-0003](../adr/ADR-0003-two-stage-curation-review-budget.md).

---

## 1. The core idea: everything is a graph

When you look at a collection of repositories, you are really looking at a
web of relationships. Repository A uses library X. Repository B also uses
library X. That makes A and B related — not in a deep way, but in a real way.
If A also exposes an HTTP API that B's README references, the connection is
much stronger.

Dirk maps these relationships as a **knowledge graph**: a network of *nodes*
(repos, technologies, concepts, interfaces, people) and *edges* (depends on,
mentions, exposes, similar to, could compose with).

Once the graph exists, it can be queried, visualised, and reasoned over. The
findings documents Dirk produces are essentially the result of asking
"what is interesting in this graph?" and writing the answers as Markdown.

### Nodes

| Kind | What it represents |
|---|---|
| `Repo` | A GitHub repository |
| `Technology` | A package, library, or runtime (e.g. `click`, `react`, `sqlite3`) |
| `Concept` | A recurring domain term extracted from docs (e.g. `knowledge-graph`, `delta-tracking`) |
| `Interface` | A public surface: HTTP route, CLI command, exported symbol, schema file |
| `Person` | A repository author or contributor |
| `Motivation` | The conceptual origin story behind a repo — *why* it was built |
| `Domain` | A high-level problem area |
| `Artifact` | A generated output (report, model file, etc.) |

### Edges

| Relationship | Meaning |
|---|---|
| `DEPENDS_ON` | Repo or entity depends on a Technology |
| `MENTIONS` | Repo's docs mention a Concept |
| `EXPOSES` | Repo exposes an Interface |
| `MOTIVATED_BY` | Repo was built for this purpose (links to a Motivation node) |
| `EVOLVED_FROM` | Repo is a direct successor or rewrite of another |
| `INSPIRED_BY` | Repo was influenced or inspired by another (looser than `EVOLVED_FROM`) |
| `SIMILAR_TO` | Two repos share enough concepts to be semantically related |
| `COULD_COMPOSE_WITH` | Two repos could be composed into something larger |
| `AUTHORED_BY` | Repo was written by a Person |

Every edge carries a **confidence score** (0–1) and an **evidence trail** — a
list of references that say why Dirk believes the edge exists. This makes the
graph auditable, not a black box.

### A quick look at the graph UI

The interactive graph view makes these inferred and explicit connections easier
to inspect during curation.

![Dirk Graph UI overview (dark mode)](../../frontend/showcase/01-overview.png)

---

## 2. Storing the graph: why a triple store?

The naive way to store a knowledge graph is two tables: one for nodes, one for
edges. That works — until you need to add provenance to individual node
properties, or your pipeline emits a relationship before both its endpoints
are fully described, or you want to diff two graph snapshots meaningfully.

Dirk uses a **triple store**: every single fact lives as a
`(subject, predicate, object)` row in one table.

```
subject          predicate       object
──────────────   ─────────────   ────────────────────────
repo:org/api     rdf:type        Repo
repo:org/api     name            api
repo:org/api     language        Python
repo:org/api     DEPENDS_ON      tech:click
repo:org/api     EXPOSES         interface:GET /healthz
```

Node properties and relationships are *the same kind of thing* at the storage
level. The only distinction is in the set of known relationship predicates
(`DEPENDS_ON`, `MENTIONS`, etc.) vs property predicates (`name`, `language`,
etc.).

### Why this matters

**Schema-free evolution.** Adding a new property to `Repo` nodes means emitting
a new predicate string. There is no `ALTER TABLE` and no migration.

**Per-fact provenance.** Every row carries its own `confidence`, `evidence`,
`discovered_by`, and `discovered_at`. You can trace exactly which skill emitted
exactly which fact and when.

**Diffable snapshots.** Because the uniqueness constraint is
`(subject, predicate, object)`, a graph snapshot is a genuine set. The diff
between two snapshots is a set difference — additions and deletions — which is
what Dirk's delta reports show.

**FK-free insertion order.** A relationship triple can be written before its
destination node has been described. The store reconstructs a partial node
gracefully, which matters in streaming or parallel pipelines.

The detailed design rationale is in
[ADR-0001](../adr/ADR-0001-triple-store-storage.md).

---

## 3. The skills pipeline

Dirk is organised as a **staged pipeline of skills**. Each skill does one kind
of noticing. They run in order, each building on what the previous one wrote
into the graph.

```
Phase 1 ── repo-inventory
               │
Phase 2 ──────┼── dependency-mapper
               │── interface-extractor
               │
Phase 3 ──────┼── concept-extractor
               │── origin-tracer
               │── semantic-linker
               │
Phase 4 ──────┼── connection-curator
               │
always ────────┼── graph-writer
               └── report-writer
```

### Phase 1 — Inventory

`repo-inventory` reads each repository in your `repos.yml` and records the
basic facts: what language it uses, what its topics are, who wrote it, when it
was last active. If you have authenticated with GitHub, it enriches these facts
from the API. The result is a set of `Repo` and `Person` nodes with
`AUTHORED_BY` edges.

This phase runs even for repositories you have not cloned locally. You get at
least the shape of each repo in the graph, even if later phases cannot read
inside it.

### Phase 2 — Explicit connections

Two skills run in parallel to map the concrete, verifiable connections.

**`dependency-mapper`** reads `pyproject.toml`, `package.json`, `go.mod`, and
similar manifests to emit `Technology` nodes and `DEPENDS_ON` edges. If repo A
and repo B both list `fastapi` as a dependency, that shows up as two
`DEPENDS_ON` edges pointing at the same `tech:fastapi` node — and therefore a
shared-technology connection between A and B.

**`interface-extractor`** looks at what each repository exposes to the outside
world: HTTP routes (from FastAPI/Flask/Express route decorators), CLI commands
(from `click` or `argparse` definitions), exported symbols, and schema files
(OpenAPI, JSON Schema, Avro). These become `Interface` nodes with `EXPOSES`
edges.

Explicit connections are the high-confidence backbone of the graph. If two
repos share a direct dependency or reference each other's interface, that is an
observable fact, not an inference.

### Phase 3 — Latent connections

This is where Dirk starts to notice things a human might miss.

**`concept-extractor`** reads READMEs, doc files, and manifest descriptions.
It extracts recurring noun-ish phrases, normalises them, filters out generic
terms ("api", "cli", "tool"), and records the survivors as `Concept` nodes with
`MENTIONS` edges. The extraction is entirely local and deterministic — no model
call, no embeddings, no network traffic.

For example, a repository whose README repeatedly mentions "knowledge graph",
"triple store", and "delta tracking" will end up with `Concept` nodes for those
terms, each carrying evidence pointing at the specific file and position where
the term appeared.

**`origin-tracer`** asks a different question: *why does this repository exist,
and what came before it?* It works in two passes.

*Motivation extraction.* The skill scans each repository's README and docs for
a section that answers the "why" question — headings like `## Why`, `## Motivation`,
`## Background`, `## Rationale`, `## Origin`, and several other intent-declaring
variants. When it finds one, it captures the text beneath it (up to roughly
400 characters) as a `Motivation` node and emits a `MOTIVATED_BY` edge. If no
explicit section exists, it falls back to the first substantial paragraph in the
README, at a lower confidence score. Either way, the result is a human-readable
statement, in the author's own words, explaining the repo's purpose.

When a local **Ollama** model is configured (`curation.provider: ollama`), the
skill optionally enriches the extracted motivation text: the raw heuristic
excerpt is sent to the model, which returns a single-sentence summary that
replaces the verbose original. The heuristic pass always runs first; the Ollama
enrichment is a quality layer, not a hard dependency. If the model is
unavailable, Dirk falls back to the heuristic text automatically.

*Lineage detection.* The skill then scans for cross-references to other repositories
in scope (by slug or short name) that appear alongside recognised lineage keywords.
Two strength levels are distinguished:

- **`EVOLVED_FROM`** (confidence 0.75) — strong keywords like *evolved from*,
  *forked from*, *rewrite of*, *successor to*. These indicate direct ancestry:
  the current repo picks up where another left off.
- **`INSPIRED_BY`** (confidence 0.55) — softer keywords like *inspired by*,
  *based on*, *builds on*, *learned from*. These capture an intellectual debt
  without direct code inheritance.

Both passes are fully offline. No model is involved. Every edge carries an
evidence note quoting the context snippet from the source document, so the
rationale is always traceable.

**`semantic-linker`** then takes those `MENTIONS` edges and asks: which
repositories share concept overlap? If repo A mentions `knowledge-graph` and
`semantic-linking`, and repo B also mentions those concepts, a `SIMILAR_TO`
edge is emitted between them. The confidence is proportional to the overlap
ratio. A `serendipity` configuration knob controls how aggressively weak
overlaps are included — higher serendipity surfaces more speculative
connections.

The serendipity-adjusted minimum confidence threshold is:

```
min_confidence = max(0.35, 0.55 − (0.2 × serendipity))
```

At `serendipity=0` you only see strong links. At `serendipity=1` you see
everything Dirk thinks might be worth investigating.

### Phase 4 — Synthesis and curation

`connection-curator` has the hardest job: take the raw accumulation of edges
and distil it into things worth telling a human. It emits `COULD_COMPOSE_WITH`
edges for repository pairs that look complementary, using two heuristics:

1. **Shared edge kinds.** If two repos are connected by two or more *different*
   relationship types (e.g. both `SIMILAR_TO` and `DEPENDS_ON` the same
   technology), that is a stronger signal than a single connection.
2. **Shared neighbours.** If two repos both depend on the same library *or*
   both expose the same kind of interface, they likely live in the same problem
   space and could plausibly compose.

When a local **Ollama** model is configured, the curator optionally asks it to
review each candidate pair: accept, reject, or adjust confidence, and add a
rationale note. The heuristic result is always produced first; the model result
replaces it only when the model responds within the timeout. If the model is
unavailable, Dirk falls back to heuristic mode automatically.

This design means Dirk is always *runnable* — you get a result whether or not
a model is available — and the model layer is a quality enhancement, not a
hard dependency.

### Always — graph-writer and report-writer

`graph-writer` serialises the in-memory graph to:
- `graph/graph.db` — the SQLite triple store (persistent, diffable)
- `graph/graph.json` — a portable JSON export
- `graph/graph.html` — a self-contained interactive node-link diagram

`report-writer` renders the findings as Markdown:
- `findings/YYYY-MM-DD-findings.md` — the full narrative
- `findings/latest.md` — a pointer to the most recent run
- `findings/delta-YYYY-MM-DD.md` — what changed since the prior run

The delta report is generated by comparing the current `graph.json` to the
previous run's snapshot. New nodes and new edges are highlighted, so you can
see at a glance what Dirk newly discovered.

---

## 4. Local-first design

A deliberate design constraint runs through every phase: **Dirk should work
without a network call or a hosted model**.

- `concept-extractor`, `origin-tracer` (heuristic path), and `semantic-linker`
  are fully offline. They use frequency analysis, heading recognition, keyword
  matching, and set intersection — not embeddings or LLM calls.
- `origin-tracer` can optionally use Ollama to enrich motivation summaries when
  `curation.provider: ollama` is set. Like `connection-curator`, it falls back
  to the heuristic result if the model is unavailable.
- `connection-curator` defaults to heuristic mode. Ollama support is opt-in.
- `repo-inventory` enriches from GitHub when authenticated, but falls back to
  what it can read from local checkouts.
- The graph store is SQLite — a single file, no server, no credentials.

This makes Dirk:
- **Reproducible.** The same repos and config produce the same graph.
- **Auditable.** Every edge has evidence pointing at the source file and the
  skill that produced it.
- **CI-friendly.** You can run `dirk run --all` in a GitHub Actions workflow
  and commit the resulting `graph.db` and findings to the repository.
- **Private-by-default.** Nothing leaves your machine unless you explicitly
  authenticate with GitHub or enable Ollama.

---

## 5. The serendipity knob

The `serendipity` configuration parameter (0–1) is worth calling out
specifically because it captures an important design philosophy.

Knowledge graph tools often err on one of two sides: they are either so
conservative they only show you things you already know, or so permissive they
drown you in noise. Serendipity is a tunable dial between those extremes.

At `serendipity=0`, Dirk behaves like a strict dependency analyser: it only
surfaces connections with high confidence, backed by direct evidence.

At `serendipity=1`, Dirk is in full *Holistic Discovery* mode: it surfaces any
connection that might be interesting, even weak concept overlaps, because
sometimes the most valuable insight is the one you would never have searched
for.

The default (`serendipity=0.5`) tries to balance both: confident connections
always appear; weaker ones appear when there is at least some corroborating
signal.

---

## 6. Putting it all together

A typical Dirk run looks like this:

```bash
# One-time setup
dirk init
# edit repos.yml to point at your repositories

# Run everything
dirk run --all

# Open the graph viewer
open graph/graph.html

# Read the narrative
cat findings/latest.md
```

The output of a run over a real collection of repositories might reveal:

- Three repos that all depend on the same message-queue library and expose
  compatible event schemas — suggesting they could share an integration layer.
- Two repos with almost no shared dependencies but highly overlapping concept
  mentions — suggesting their authors are solving similar problems in isolation.
- A CLI tool repo that exposes exactly the interface a pipeline repo is
  documented to consume — suggesting they should be formally linked.
- A repo whose README says "this evolved from my earlier prototype" — surfacing
  an explicit ancestry link to a sibling repository.
- A repo with a `## Why` section explaining the problem it was built to solve —
  providing the human context that makes every other connection in the graph
  make sense.

None of these connections are invented by Dirk. They exist in the code and
documentation already. Dirk just reads carefully and writes it all down.

---

## Further reading

- [README](../../README.md) — installation, quick start, configuration reference
- [PHASES.md](../PHASES.md) — current implementation status and roadmap
- [ADR-0001: Triple Store Storage](../adr/ADR-0001-triple-store-storage.md) — why the graph uses a triple store instead of nodes+edges tables
- [ADR-0002: Origin Tracer — Conceptual Genesis and Learning Lineage](../adr/ADR-0002-origin-tracer-conceptual-genesis.md) — why and how `origin_tracer` captures the human story behind each repository
