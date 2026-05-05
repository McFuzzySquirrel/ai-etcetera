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
| `concept-extractor` | 3 | Deterministically extracts concepts from local READMEs/docs/manifests and emits `Concept` + `MENTIONS` edges with evidence. |
| `semantic-linker` | 3 | Deterministically proposes `SIMILAR_TO` repo links from shared concept mentions (serendipity-scaled threshold). |
| `connection-curator` | 4 | Synthesises raw edges into ranked, human-readable findings and composition proposals. |
| `graph-writer` | always | Persists the graph and emits the visual viewer. |
| `report-writer` | always | Renders findings + delta Markdown. |

### Knowledge graph

- **Storage:** SQLite (`graph/graph.db`) — file-based, diffable, commits cleanly.
  Upgrade path: DuckDB / Kuzu / Neo4j.
- **Embeddings:** stored alongside concept nodes in a `vectors` table.
- **Embeddings:** schema/table support exists; runtime embedding generation is optional and can be layered in later.
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
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e .
```

On Debian/Ubuntu, running `pip install -e .` outside a virtual environment may
fail with an `externally-managed-environment` error (PEP 668).

### Initialise

```bash
dirk init                    # writes default dirk.config.yml + repos.yml
```

Edit `repos.yml` to list the repositories you want Dirk to consider locally.
You can also set `scope.github_user` and `scope.github_org` in
`dirk.config.yml` to auto-discover repositories from GitHub; `repos.yml`
remains the place to pin local checkout paths for the deeper phases.

### Authenticate with GitHub (optional)

For richer repository metadata (languages, topics, recent activity), authenticate
with GitHub:

```bash
dirk login                   # interactive GitHub authentication
```

This command will:
- Use the GitHub CLI (`gh`) if already authenticated
- Launch `gh auth login` if not authenticated (opens browser)
- Otherwise, prompt you to paste a personal access token manually
- Automatically save the token to `.env` in your project root
- Load the token for all subsequent `dirk` commands in that project

Once authenticated, the token persists across sessions in `.env` (which is
git-ignored for security). If you skip this step, Dirk runs in offline mode
with minimal metadata.

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

Check local Ollama availability before enabling LLM curation:

```bash
dirk ollama-check
```

### Outputs

- `graph/graph.db`    — SQLite knowledge store
- `graph/graph.json`  — portable export
- `graph/graph.html`  — static interactive viewer (open in a browser)
- `findings/YYYY-MM-DD-findings.md` — full report
- `findings/latest.md`              — pointer to most recent
- `findings/delta-YYYY-MM-DD.md`    — what changed since the prior run

### Run the React UI

There are two ways to run the React-based graph viewer.

1. Generated viewer (recommended for normal use):

```bash
cd frontend
npm install
npm run build
cd ..
dirk run --all
```

Then open `graph/graph.html`.

If your browser is strict about `file://` module loading, serve the repo over HTTP:

```bash
python3 -m http.server 8765
```

Then open `http://127.0.0.1:8765/graph/graph.html`.

2. Frontend development mode:

```bash
cd frontend
npm install
npm run dev
```

For dev mode, ensure `graph/graph.json` exists first (for example, run `dirk run --all`).

## Configuration

`dirk.config.yml` controls behaviour:

```yaml
scope:
  source: repos.yml
  github_user: McFuzzySquirrel   # optional auto-discovery
  github_org: eZansiEdgeAI       # optional auto-discovery
  include_private: true          # requires GitHub auth
depth: standard              # quick | standard | deep
connection_threshold: 0.35   # weak edges still stored, just not in findings
serendipity: 0.5             # 0 = only confident links, 1 = full Dirk mode
output:
  graph_dir: graph
  findings_dir: findings
curation:
  provider: heuristic        # heuristic | ollama
  model: qwen3:8b            # used when provider=ollama
  base_url: http://127.0.0.1:11434
  timeout_sec: 45
  max_candidates: 25
  max_suggestions: 15
  fallback: heuristic        # heuristic | fail
```

> **Model runtime.** Dirk does not require a hosted model to run.
> `curation.provider: heuristic` remains the default. If you want local LLM
> synthesis, set `curation.provider: ollama`; Dirk will call your local
> Ollama server and automatically fall back to heuristic mode when configured
> with `curation.fallback: heuristic`. No API key is required for local mode.
> See [`docs/PHASES.md`](docs/PHASES.md) for roadmap detail.

`repos.yml` is the canonical local-scope file. Each entry is either a plain
`owner/name` slug or a mapping that also points at a local checkout. The
file-scanning skills (`dependency-mapper`, `interface-extractor`,
`concept-extractor`) only have something deep to read when a `path` is
provided, so keeping local clones materially improves graph quality:

```yaml
repos:
  - owner/repo-one                     # slug only — appears in graph, no scan
  - slug: owner/repo-two               # slug + local checkout
    path: ./checkouts/repo-two         # relative to repos.yml's directory
```

## Status

| Phase | Status |
|---|---|
| 1 — Skeleton + repo-inventory + SQLite + trivial findings | ✅ implemented |
| 2 — Explicit connections (deps + interfaces) + viewer    | ✅ manifest parsing + CLI/schema extraction |
| 3 — Latent connections (concepts + semantic linker)      | ✅ deterministic local concepts + semantic links implemented |
| 4 — Synthesis (curator)                                  | 🟡 working heuristic + Ollama-assisted curator; rationale-only evidence today, full curator CLI/workflow still pending |
| 5 — Delta tracking                                       | ✅ delta tracking on local runs |

## Licence

See [LICENSE](LICENSE).
