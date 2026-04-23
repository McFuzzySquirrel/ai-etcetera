# ai-etcetera

> *"I may not have gone where I intended to go, but I think I have ended up where I needed to be."*
> — Douglas Adams, *The Long Dark Tea-Time of the Soul*

This repository hosts **Dirk** — a holistic research agent and a set of skills
that surface the **fundamental interconnectedness of all things** across a
collection of GitHub repositories.

The project is also referred to as **Holistic Discovery** in docs and config.

## What it does

Dirk periodically (or on demand) reads a configured collection of repositories
and produces:

1. A **knowledge graph** of repos and the entities inside them — concepts,
   technologies, domains, data shapes, APIs, authors, problem spaces.
2. A **findings document** (Markdown) calling out:
   - **Direct** connections — shared dependencies, shared APIs, shared data,
     cross-references.
   - **Latent / holistic** connections — semantic similarity of purpose,
     overlapping problem domains, complementary capabilities, repos that
     *could* compose into something larger.
   - **Suggested compositions** — *"Repo A's parser + Repo B's storage layer +
     Repo C's UI = X."*
3. A **delta report** on each periodic run showing what is newly connected
   since the prior run.

## Architecture

```
                        ┌──────────────────────┐
                        │   .github/agents/    │
                        │       dirk.md        │  ← system prompt (the agent)
                        └──────────┬───────────┘
                                   │ orchestrates
              ┌────────────────────┼─────────────────────┐
              ▼                    ▼                     ▼
      ┌───────────────┐    ┌───────────────┐     ┌───────────────┐
      │ repo-inventory│    │ dependency-   │     │ interface-    │
      │               │    │  mapper       │     │  extractor    │
      └───────┬───────┘    └───────┬───────┘     └───────┬───────┘
              │                    │                     │
              ▼                    ▼                     ▼
      ┌───────────────┐    ┌───────────────┐     ┌───────────────┐
      │ concept-      │    │ semantic-     │     │ connection-   │
      │  extractor    │    │  linker       │     │  curator      │
      └───────┬───────┘    └───────┬───────┘     └───────┬───────┘
              └────────────────────┼─────────────────────┘
                                   ▼
                        ┌──────────────────────┐
                        │     graph-writer     │   →  graph/graph.db
                        │     report-writer    │   →  graph/graph.json
                        └──────────────────────┘   →  graph/graph.html
                                                   →  findings/*.md
```

### The skills (each does one kind of "noticing")

| Skill | Phase | Purpose |
|---|---|---|
| `repo-inventory` | 1 | Refresh repos; extract languages, deps, entry points, READMEs, topics, owners, last-touched dates. |
| `dependency-mapper` | 2 | Explicit edges: package deps, submodules, cross-repo imports, doc/issue references. |
| `interface-extractor` | 2 | Public surface area: HTTP routes, CLI commands, exported symbols, schema files, event names. |
| `concept-extractor` | 3 | Pulls domain concepts from READMEs/docs/comments/commits; embeds them. |
| `semantic-linker` | 3 | Proposes latent connections via embeddings + LLM pass. |
| `connection-curator` | 4 | Synthesises raw edges into ranked, human-readable findings and composition proposals. |
| `graph-writer` | always | Persists the graph and emits the visual viewer. |
| `report-writer` | always | Renders findings + delta Markdown. |

### Knowledge graph

- **Storage:** SQLite (`graph/graph.db`) — file-based, diffable, commits cleanly.
  Upgrade path: DuckDB / Kuzu / Neo4j.
- **Embeddings:** stored alongside concept nodes in a `vectors` table.
- **Schema:**
  - **Nodes:** `Repo`, `Concept`, `Technology`, `Interface`, `Person`,
    `Domain`, `Artifact`.
  - **Edges:** `DEPENDS_ON`, `MENTIONS`, `EXPOSES`, `SIMILAR_TO`,
    `COULD_COMPOSE_WITH`, `AUTHORED_BY`, `EVOLVED_FROM`.
  - Every edge carries: `confidence` (0–1), `evidence` (source refs),
    `discovered_at`, `discovered_by`.

## Quick start

### Install

```bash
pip install -e .
```

### Initialise

```bash
dirk init                    # writes default dirk.config.yml + repos.yml
```

Edit `repos.yml` to list the repositories you want Dirk to consider.

### Run a scan

```bash
dirk scan                    # inventory + dependency mapping
dirk connect                 # run linkers + curator
dirk report                  # write findings markdown + delta
```

Or do it all in one go:

```bash
dirk run --all
```

### Outputs

- `graph/graph.db`    — SQLite knowledge store
- `graph/graph.json`  — portable export
- `graph/graph.html`  — static interactive viewer (open in a browser)
- `findings/YYYY-MM-DD-findings.md` — full report
- `findings/latest.md`              — pointer to most recent
- `findings/delta-YYYY-MM-DD.md`    — what changed since the prior run

## Configuration

`dirk.config.yml` controls behaviour:

```yaml
scope:
  source: repos.yml          # or: github_user: <login> / github_org: <org>
depth: standard              # quick | standard | deep
connection_threshold: 0.35   # weak edges still stored, just not in findings
serendipity: 0.5             # 0 = only confident links, 1 = full Dirk mode
output:
  graph_dir: graph
  findings_dir: findings
model_preferences:
  embedding: local           # local | hosted
  curation: hosted           # local | hosted
```

`repos.yml` is the hand-maintained scope file. Each entry is either a plain
`owner/name` slug or a mapping that also points at a local checkout — the
file-scanning skills (`dependency-mapper`, `interface-extractor`) only have
something to read when a `path` is provided:

```yaml
repos:
  - owner/repo-one                     # slug only — appears in graph, no scan
  - slug: owner/repo-two               # slug + local checkout
    path: ./checkouts/repo-two         # relative to repos.yml's directory
```

## Periodic execution

A scheduled GitHub Actions workflow (`.github/workflows/dirk-scan.yml`) runs
weekly, opens a PR with the updated graph + findings, and keeps the human in
the loop on what Dirk has noticed.

## Status

| Phase | Status |
|---|---|
| 1 — Skeleton + repo-inventory + SQLite + trivial findings | ✅ implemented |
| 2 — Explicit connections (deps + interfaces) + viewer    | ✅ manifest parsing + CLI/schema extraction |
| 3 — Latent connections (concepts + semantic linker)      | 🟡 stubs in place |
| 4 — Synthesis (curator)                                  | 🟡 heuristic curator (LLM synthesis pending) |
| 5 — Periodic + delta + PR loop                           | ✅ workflow + delta implemented |

## Licence

See [LICENSE](LICENSE).
