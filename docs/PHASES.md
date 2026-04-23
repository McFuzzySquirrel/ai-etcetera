# Dirk — Phase 3 & 4 implementation guide

This document is a forward-looking spec for the two remaining "smart" phases
of Dirk. Phases 1, 2, and 5 are already implemented (see the [README status
table](../README.md#status)); Phases 3 and 4 are stubbed and intentionally
deferred until the deterministic core has been exercised on a real
collection of repos.

The point of writing this down now is so that, once the current pipeline
has been used a few times and we know which signals actually matter, the
implementation can begin from a stable plan rather than a blank page.

---

## Guiding decision: agent-as-runtime

The "smart" skills (`concept_extractor`, `semantic_linker`,
`connection_curator`) **do not own a model**. They run inside whatever agent
session the user has already chosen — GitHub Copilot CLI, the Copilot
coding agent, Claude in an IDE, etc. — and that host is the runtime for
the reasoning steps.

This has three consequences that drive the design below:

1. **No hosted-model dependency, no API keys, no cost-ceiling logic in
   this repo.** `model_preferences` and `cost_ceiling_usd` in
   `dirk.config.yml` will be removed (or reduced to a single optional
   `embedding:` knob — see Phase 3).
2. **The Phase 3/4 skills are CLI verbs, not autonomous Python.** Their
   job is to give the host agent a small, well-typed surface for writing
   into the graph (`Concept` nodes, `SIMILAR_TO` edges,
   `COULD_COMPOSE_WITH` edges with rationale). The agent does the
   noticing; the CLI does the writing.
3. **`.github/agents/dirk.md` becomes the orchestrator** for these
   phases. It tells the host agent the order of operations, what to
   read, and which CLI verbs to call. No prompt logic lives in Python.

Short version of the trade-off: simpler, cheaper, and the intelligence
lives where it is already paid for and already governed. The cost is
that the fully-autonomous "weekly cron writes a PR with new
connections" loop now requires an agent runtime to be wired into the
schedule (Copilot coding agent or equivalent) — see
[Periodic execution](#periodic-execution-phase-5-follow-up) below.

---

## Phase 3 — Latent connections (concepts + semantic linker)

### Goal

Move beyond "these two repos share a dependency" into "these two repos
are about the same thing, even though they share no code." Two skills
collaborate:

- `concept_extractor` — names the domain concepts each repo is about.
- `semantic_linker` — proposes `SIMILAR_TO` edges between repos whose
  concept sets overlap meaningfully.

### Inputs the skills can rely on

By the time Phase 3 runs, the graph already contains:

- `Repo` nodes with `properties.readme_excerpt`, `topics`, `languages`
  (from `repo_inventory`).
- `Technology` nodes + `DEPENDS_ON` edges (from `dependency_mapper`).
- `Interface` nodes + `EXPOSES` edges (from `interface_extractor`).

Repos with a local `path` also let the host agent read full READMEs,
top-level docs, and module/package names directly from disk.

### `concept_extractor` — design

**Output schema (no new node/edge kinds needed):**

- `Concept` node — `id: concept:<slug>`, `name: <human label>`,
  `properties: { aliases: [...], domain: <optional Domain id> }`.
- `MENTIONS` edge — `Repo → Concept`, with:
  - `confidence` ∈ [0.4, 0.9]
  - `evidence: [{ ref: "<file>:<line?>", note: "<short quote or paraphrase>" }]`
  - `discovered_by: "concept_extractor"`

**CLI surface (the writer verbs the host agent calls):**

```
dirk concept add \
  --slug <kebab-slug> \
  --name "<Human Name>" \
  [--alias "<other phrasing>" ...] \
  [--domain <domain-slug>]

dirk mention add \
  --repo <owner/name> \
  --concept <concept-slug> \
  --confidence <0..1> \
  --evidence "<file_or_url>::<short note>" \
  [--evidence ... ]
```

Both verbs are upserts (idempotent on `id` / `(src, dst, kind)`), so the
host agent can re-run safely.

**Prompting contract (lives in `.github/agents/dirk.md`):**

For each repo with a local path:

1. Read `README*`, `docs/`, top-level package names, and recent commit
   subjects.
2. Produce 3–10 concepts that describe *what the repo is for*, not
   *what it is built with*. (Tech belongs in `Technology` nodes.)
3. For each concept, call `dirk concept add` (creating it if new) and
   `dirk mention add` with at least one evidence string pointing at a
   file or line.
4. Prefer existing concepts. The agent should `dirk concept list` first
   and reuse a slug whenever the meaning matches, even if phrasing
   differs.

**Concept normalisation rules** (enforced by the CLI, not the agent):

- Slug is lowercase kebab-case, ≤40 chars, ASCII.
- `name` is title-case human form.
- Aliases are deduped case-insensitively.
- Reject slugs that collide with `Technology` ids (no `concept:python`
  if `tech:pypi:python` already exists).

**Optional embedding hook (Phase 3.5, not required):**

If — and only if — the user opts in via:

```yaml
embedding:
  provider: local      # local | none
  model: all-MiniLM-L6-v2
```

…then `concept_extractor` (run as `dirk concept embed`) will compute a
vector for each concept's `name + aliases` and store it in the existing
`vectors` table. This is what makes large-N similarity tractable
without spending agent tokens. Default is `none`; everything else still
works.

### `semantic_linker` — design

**Output:** `SIMILAR_TO` edges between `Repo` nodes.

- `confidence` ∈ [0.3, 0.95]
- `evidence` lists the overlapping concepts (and, if embeddings are on,
  the cosine score per pair).
- The `serendipity` config knob (already in `dirk.config.yml`) scales
  the lower bound: `serendipity=0` keeps only edges ≥ 0.7;
  `serendipity=1` keeps everything ≥ 0.3.

**Two implementations, same output:**

1. **Agent-driven (default).** The host agent enumerates repo pairs,
   inspects their `MENTIONS` edges (and, optionally, READMEs), and
   calls:

   ```
   dirk link add \
     --src <owner/name> --dst <owner/name> \
     --kind SIMILAR_TO \
     --confidence <0..1> \
     --evidence "shared concept: <slug>" [--evidence ...]
   ```

   For N repos this is O(N²) prompts in the worst case; for the
   single-digit collections this repo is built for, that is fine. The
   agent should skip pairs that share zero concepts before reasoning.

2. **Embedding-driven (opt-in).** If concept embeddings exist, a pure
   Python pass computes cosine similarity over per-repo concept
   centroids and emits `SIMILAR_TO` edges directly, no agent needed.
   This is what makes a 100+ repo collection viable.

The two paths are not exclusive: embeddings can pre-filter candidate
pairs, the agent can then add nuance to the top-K.

### Acceptance criteria for Phase 3

- A run on a 3–5 repo collection (with local checkouts) produces:
  - At least 1 `Concept` node per repo.
  - At least 1 `SIMILAR_TO` edge with non-empty `evidence`.
  - No edges with `confidence` outside [0, 1].
  - No `Concept` slug collisions with existing `Technology` ids.
- `dirk run --all` succeeds with the agent skipped (i.e. the
  deterministic Phases 1, 2, 5 keep working when no agent is present).
- New unit tests cover: slug normalisation, upsert idempotence,
  evidence parsing, and the embedding cosine path (with a tiny
  fixture vector — no real model invoked in CI).

### What is *out* of scope for Phase 3

- No automatic concept extraction from issues/PRs — too noisy for the
  first cut.
- No multilingual concept handling.
- No concept hierarchies (parent/child). `Domain` nodes already exist
  in the schema for this; using them is a Phase 3.5 stretch goal.

---

## Phase 4 — Synthesis (curator + composition proposals)

### Goal

Turn the graph into something a human reads and acts on:

> *"`owner/parser-lib`'s AST + `owner/storage-kv`'s blob layer +
> `owner/cli-toolkit`'s command framework would give you the offline
> indexer described in `owner/notes-ideas#42`."*

This is the moment Dirk stops being a graph and starts being useful.

### Current state (carry-over from Phase 2)

`connection_curator` already produces `COULD_COMPOSE_WITH` edges from
two heuristics: shared edge kinds (≥2) and shared `Technology` /
`Interface` neighbors (≥2). Phase 4 keeps those as a floor and adds an
agent-driven layer on top.

### Output schema

- `COULD_COMPOSE_WITH` edges, as today, but with an additional
  `properties.rationale` Markdown blurb (1–3 sentences) written by the
  host agent.
- Optional `EVOLVED_FROM` edges where the agent identifies that one
  repo is a successor / fork-in-spirit of another.
- The `report_writer` already renders edges into findings; the only
  change there is to prefer edges with a `rationale` and surface that
  blurb verbatim under each suggestion.

### CLI surface

```
dirk curate add \
  --src <owner/name> --dst <owner/name> \
  --confidence <0..1> \
  --rationale "<1–3 sentence Markdown>" \
  [--evidence "<ref>::<note>" ...]

dirk curate list \
  [--min-confidence 0.5] \
  [--since <iso-date>]
```

`dirk curate add` upserts on `(src, dst, COULD_COMPOSE_WITH)`. If the
heuristic curator already created the edge, the agent's call replaces
the rationale and merges evidence rather than duplicating.

### Prompting contract

The host agent, after Phase 3 has run:

1. Calls `dirk curate list --min-confidence 0.4` to see the heuristic
   pairs already in the graph.
2. For each pair, reads the connecting evidence
   (`dirk graph neighbors <repo>` — see CLI additions below) and
   decides: *promote*, *demote*, or *ignore*.
3. Writes a rationale via `dirk curate add` for promoted pairs.
4. Optionally proposes pairs the heuristics missed by re-reading the
   `Concept` overlap from Phase 3.

The agent prompt explicitly forbids:

- Inventing repos, files, or symbols not present in the graph.
- Rationales longer than 3 sentences.
- Confidence > 0.9 without at least two pieces of distinct evidence.

### Supporting CLI additions

These are tiny read-only helpers that exist so the agent does not have
to parse the SQLite file directly:

```
dirk graph neighbors <node-id> [--kind <NodeKind>] [--edge <EdgeKind>]
dirk graph pairs --min-shared-neighbors 2
dirk concept list [--repo <owner/name>]
```

Each prints stable JSON to stdout. They are pure reads; no mutation.

### Acceptance criteria for Phase 4

- Findings document contains a "Suggested compositions" section where
  each item has: the two repos, the rationale blurb, and the evidence
  refs as a footnote.
- Delta report flags newly-added rationales between runs, not just
  newly-added edges.
- Heuristic-only runs (no agent) still produce the section, just
  without rationales — same shape, fewer words.
- New tests cover: rationale upsert/replace, evidence merge,
  `dirk graph neighbors` JSON shape.

### What is *out* of scope for Phase 4

- No automatic PR opening into the proposed-composition repos.
- No "build me the composed thing" code generation. Dirk surfaces; it
  does not synthesise software.
- No ranking model. Confidence + recency is the ordering.

---

## Configuration changes that come with Phases 3 & 4

When Phase 3 lands, `dirk.config.yml` becomes:

```yaml
scope:
  source: repos.yml
depth: standard
connection_threshold: 0.35
serendipity: 0.5
output:
  graph_dir: graph
  findings_dir: findings

# Optional, default off. When 'none', semantic_linker uses agent-driven
# pairwise reasoning only. When 'local', concept embeddings are computed
# in-process for large-N collections.
embedding:
  provider: none      # none | local
  # model: all-MiniLM-L6-v2     # required when provider != none

skills:
  repo_inventory: true
  dependency_mapper: true
  interface_extractor: true
  concept_extractor: true
  semantic_linker: true
  connection_curator: true
```

Removed: `model_preferences`, `cost_ceiling_usd`. The agent runtime is
the user's existing agent session; this repo no longer pretends to
manage models.

---

## Periodic execution (Phase 5 follow-up)

The current `dirk-scan.yml` workflow runs the deterministic skills on a
schedule and opens a PR. Once Phases 3 & 4 land, the recommended
two-step pattern is:

1. **Scheduled job** runs `dirk run --all` (deterministic only — Phases
   1, 2, the heuristic part of 4, and 5). It commits any graph deltas
   and opens an issue tagged `dirk:needs-curation` *if* the delta
   contains new repo pairs without a rationale.
2. **Copilot coding agent** picks up the issue (or a human kicks it
   off manually), runs the Phase 3/4 prompt from
   `.github/agents/dirk.md`, calls the writer CLI verbs, and pushes a
   follow-up commit on the same PR.

This keeps the cron lane fully unattended and the reasoning lane fully
auditable in PR review, without coupling the two.

---

## Implementation order (recommended)

1. **Use the current pipeline on a real collection for ≥2 weekly
   runs.** Confirm that the Phase 2 signal (deps + interfaces) is
   actually useful before adding more layers. Adjust thresholds.
2. **Land the writer CLI verbs** (`dirk concept add`, `dirk mention
   add`, `dirk link add`, `dirk curate add`) with full unit tests but
   no agent prompt yet. These are pure storage wrappers and can be
   exercised by hand.
3. **Land the read-only helpers** (`dirk graph neighbors`, `pairs`,
   `concept list`). Same: mechanical, fully testable.
4. **Write the agent prompt** in `.github/agents/dirk.md` referencing
   the verbs above. Test it once interactively in a Copilot CLI
   session against the real graph.
5. **Wire it into the workflow** as the "needs-curation" follow-up
   step. Keep the deterministic cron path unchanged.
6. **Optional: add the `embedding:` path** only if the collection
   grows past the point where agent-pairwise reasoning is comfortable.

Each step is independently shippable and independently revertable —
which is the whole point of doing it in this order.
