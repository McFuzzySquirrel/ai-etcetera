# Dirk — Phase Status And Roadmap

This document reflects the current implementation state of Dirk, not the
original speculative plan.

For architectural decisions see [`docs/adr/`](adr/README.md).
For conceptual background see [`docs/blog/`](blog/README.md).

## Current phase status

| Phase | Status | Notes |
|---|---|---|
| 1 — Inventory + graph store | Complete | Repo inventory, SQLite storage, graph and findings writers are active. |
| 2 — Explicit connections | Complete | Dependency and interface extraction are implemented. Coverage depends on local checkouts. |
| 3 — Latent connections | Complete | `concept_extractor`, `origin_tracer`, and `semantic_linker` are implemented with deterministic local-first behaviour. |
| 4 — Synthesis / curation | Partial | `connection_curator` is implemented with heuristics by default and optional Ollama-assisted scoring. The full curator CLI and richer rationale model are still pending. |
| 5 — Delta tracking | Complete | Findings delta is generated between runs. |

## What is implemented today

### Phase 1

- `repo_inventory` creates `Repo` and `Person` nodes plus `AUTHORED_BY` edges.
- GitHub metadata enrichment is used when authentication is available.
- The agent can now resolve scope from both `repos.yml` and GitHub discovery
  via `scope.github_user` / `scope.github_org`.
- **Storage (v2):** the graph store was migrated from a `nodes`+`edges` schema
  to a single `triples` table (subject–predicate–object).  `Node` and `Edge`
  types are retained as convenience wrappers; no skill changes were required.
  See [`docs/adr/ADR-0001-triple-store-storage.md`](adr/ADR-0001-triple-store-storage.md)
  for the full rationale.  Use `dirk migrate` to upgrade an existing v1 database.

### Phase 2

- `dependency_mapper` emits `Technology` nodes and `DEPENDS_ON` edges.
- `interface_extractor` emits `Interface` nodes and `EXPOSES` edges.
- These phases work best when repositories have local checkout paths in
  `repos.yml`.

### Phase 3

- `concept_extractor` deterministically derives `Concept` nodes and `MENTIONS`
  edges from local README/docs/manifests.
- `origin_tracer` extracts the conceptual origin story behind each repo:
  - Scans for `## Why`, `## Motivation`, `## Background` (and similar) sections
    to create `Motivation` nodes and `MOTIVATED_BY` edges.
  - Detects cross-references to other repos in scope paired with lineage
    keywords (`evolved from`, `inspired by`, etc.) to emit `EVOLVED_FROM` and
    `INSPIRED_BY` edges, capturing learning and evolution lineage.
  - Optionally enriches the motivation summary via Ollama when
    `curation.provider: ollama` is configured — the heuristic extract always
    runs first and Ollama refines it into a single clear sentence.  Falls back
    to the heuristic text when the model is unavailable.
- `semantic_linker` emits `SIMILAR_TO` edges from shared concept overlap.
- The heuristic path is local-first and does not require a hosted model.

### Phase 4

- `connection_curator` generates `COULD_COMPOSE_WITH` edges from conservative
  heuristics:
  - shared direct edge kinds
  - shared `Technology` / `Interface` neighbors
- Optional Ollama support (shared `curation.*` config with `origin_tracer`) can:
  - accept or reject candidate pairs
  - adjust confidence
  - add rationale text and supporting signals into edge evidence
- The current CLI supports runtime checking through `dirk ollama-check`.
- Heuristic fallback is supported when Ollama is unavailable or times out and
  `curation.fallback` is `heuristic`.

### Phase 5

- `report_writer.write_delta()` reports new nodes and edges relative to the
  previous `graph.json` snapshot.

## Are we done with Phase 4?

No.

Phase 4 is functionally useful, but not finished according to the richer
workflow Dirk still wants.

### What is done

- Repo-to-repo composition suggestions are generated.
- Ollama-assisted local curation works in normal runs.
- Findings include suggested compositions from `COULD_COMPOSE_WITH` edges.

### What is still missing

- A dedicated rationale field on curated edges instead of storing rationale in
  generic evidence notes.
- Read-only curator support CLI such as graph neighbor/pair inspection helpers.
- Stronger ranking and pruning of noisy graph state.
- A clean-state/pruning workflow so removed repos do not linger in the additive
  graph store across runs.

Because of those gaps, Phase 4 should be treated as **partial** rather than
complete.

## Recommended next work

### 1. Finish Phase 4 data model

- Add explicit edge properties for curated rationale.
- Teach report rendering to prefer structured rationale over freeform evidence.

### 2. Add curator inspection helpers

- Add CLI read helpers for neighbor inspection and candidate review.
- Make it easier to debug why a composition suggestion exists.

### 3. Reduce graph noise

- Filter low-value concept mentions.
- Improve concept normalization.
- Add pruning or clean rebuild support for stale repos and edges.

### 4. Improve clean-run ergonomics

- Add a supported command or flag for rebuilding from a clean graph store.
- Avoid historical noise when evaluating scope changes.

## Practical guidance today

- If you want the best current graph quality, keep `repos.yml` canonical and
  point as many entries as possible at real local checkouts.
- Use `scope.github_user` / `scope.github_org` for discovery, but rely on local
  paths for the deepest phases.
- Treat Ollama curation as an enhancement layer over the deterministic graph,
  not a replacement for good local source coverage.