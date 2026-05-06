# ADR-0002: Add origin_tracer skill to capture conceptual genesis and learning lineage

**Date:** 2026-05-06  
**Status:** Accepted  
**Deciders:** Dirk maintainers

---

## Context

Dirk's original skills pipeline was good at mapping *what* a repository does and
*how* it relates to others through shared dependencies, interfaces, and concept
vocabulary.  What it could not capture was *why* a repository was built or how
it evolved from earlier work.

This gap matters because a body of work produced by a single engineer (or small
team) is rarely a collection of unrelated islands.  Each repository is often the
direct expression of something learned, a problem encountered, or an idea
carried forward from a predecessor.  The invisible connective tissue is
intellectual: the motivation behind building something, the lessons absorbed
from a prior project, the pattern borrowed from an external reference.

Concretely, the graph had no answer for questions such as:

- "Why did this repo get created at all?"
- "Which repo was this forked or evolved from?"
- "What earlier project inspired this new approach?"

Without those answers the holistic picture of an ecosystem is incomplete.  A
graph that only shows *what exists* cannot tell the story of *why it exists* —
and that story is often where the most interesting connections live.

### Existing capability before this ADR

| Phase | Skill | What it captures |
|---|---|---|
| 1 | `repo_inventory` | Existence, ownership, metadata |
| 2 | `dependency_mapper` | Shared technology stack |
| 2 | `interface_extractor` | Public surfaces exposed |
| 3 | `concept_extractor` | Recurring domain vocabulary |
| 3 | `semantic_linker` | Concept-overlap similarity |
| 4 | `connection_curator` | Composition suggestions |

No skill captured motivation or lineage.  The `EVOLVED_FROM` predicate existed
in `EDGE_KINDS` as a placeholder but was never populated.

---

## Decision

Add a new Phase 3 skill — `origin_tracer` — that runs after `concept_extractor`
and before `semantic_linker`.  The skill is built on a deterministic local
foundation (no network, no model required) with an optional Ollama enrichment
layer that activates when `curation.provider = ollama` is set in the config.

### 1. Motivation extraction

`origin_tracer` scans each checked-out repository for a *why this exists*
statement using two strategies in order of confidence:

**Strategy A — explicit section (confidence 0.85).** Looks for a Markdown heading
that matches a curated set of intent-declaring titles: `## Why`, `## Motivation`,
`## Background`, `## Origin`, `## Genesis`, `## Goal`, `## Purpose`,
`## Rationale`, and multi-word variants (`## What and Why`, `## What Is This`).
When found, the text under that heading (up to eight lines, up to 400 characters)
is captured as the motivation statement.

**Strategy B — intro paragraph (confidence 0.55).** If no explicit section is
found and the file is a README, the first substantial body paragraph after the
H1 title is used.  Badge lines and empty lines are skipped.  This is a weaker
signal — the intro might describe *what* rather than *why* — hence the lower
confidence.

The extracted text is stored as a `Motivation` node:

```
subject                              predicate   object
───────────────────────────────────  ─────────   ──────────────────────────
motivation:McFuzzySquirrel/repo-x    rdf:type    Motivation
motivation:McFuzzySquirrel/repo-x    name        repo-x — why
motivation:McFuzzySquirrel/repo-x    text        "This was built because …"
motivation:McFuzzySquirrel/repo-x    source      README.md
motivation:McFuzzySquirrel/repo-x    repo        McFuzzySquirrel/repo-x
```

A `MOTIVATED_BY` edge links the repo to its motivation node:

```
repo:McFuzzySquirrel/repo-x   MOTIVATED_BY   motivation:McFuzzySquirrel/repo-x
```

### 2. Lineage detection

`origin_tracer` also scans for cross-references to *other repositories in scope*
that appear near recognised lineage keywords.  It builds a regex from all known
repo slugs and short names, then for each match checks a ±250-character context
window for lineage signal.

**Strong lineage (→ `EVOLVED_FROM`, confidence 0.75).** Keywords: `evolved from`,
`born from`, `grew out of`, `forked from`, `derived from`, `continuation of`,
`successor to`, `supersedes`, `replaces`, `rewrite of`, `rebuilt from/as`,
`started from/as`.  These indicate a direct ancestry: the current repo is a
successor or rewrite of the referenced one.

**Weak lineage (→ `INSPIRED_BY`, confidence 0.55).** Keywords: `inspired by`,
`influenced by`, `motivated by`, `learned from`, `builds on`, `based on`,
`grew from`, `following the ideas/pattern of`.  These indicate an intellectual
debt without a direct code or structural inheritance.

Self-references (a repo matching its own slug) are always ignored.

### 3. Storage changes

Two new predicates added to `EDGE_KINDS` in `storage.py`:

| Predicate | Source | Destination | Meaning |
|---|---|---|---|
| `MOTIVATED_BY` | `Repo` node | `Motivation` node | Repo has this origin story |
| `INSPIRED_BY` | `Repo` node | `Repo` node | Repo was intellectually inspired by another |

`EVOLVED_FROM` was already in `EDGE_KINDS` (placeholder); `origin_tracer` now
populates it.

One new entry added to `NODE_KINDS`:

| Kind | Represents |
|---|---|
| `Motivation` | The captured origin story of a repository |

### 4. Optional Ollama motivation enrichment

When `curation.provider = ollama` is configured, `origin_tracer` reuses the
same `OllamaClient` already used by `connection_curator` (same `base_url`,
`model`, `timeout_sec`, and `fallback` settings — no new config keys).

**Enrichment flow:**

1. The heuristic extraction always runs first and produces a raw motivation
   statement.
2. If Ollama is configured, `OllamaClient.health()` is called once per run.
   - If healthy: `enrich_motivation(repo, excerpt)` is called for each repo
     that has a heuristic motivation.  The model receives the repo slug and the
     raw excerpt and returns a single-sentence summary (≤ 200 characters) and a
     confidence score as JSON.
   - If unhealthy and `fallback = heuristic`: the heuristic text is stored as-is
     and a note is added to the skill result.
   - If unhealthy and `fallback = fail`: a `RuntimeError` is raised.
3. When enrichment succeeds, the `text` property on the `Motivation` node is
   replaced by the model-produced summary.  The `MOTIVATED_BY` edge's confidence
   is updated to `max(heuristic_confidence, ollama_confidence)`.  An additional
   evidence item is appended: `{"ref": "ollama:{model}", "note": "motivation
   enriched by LLM"}`.
4. When enrichment fails at request time (network/timeout), the same fallback
   policy applies as for health check failure.

The heuristic result is **always computed before the Ollama call**.  Ollama is
a quality enhancement layer, not a hard dependency.  The graph is always
populated even when a model is unavailable.

### 5. Report changes

The findings document gains a **"Conceptual genesis"** section that renders:

- A `### Why each repo exists` subsection listing each `Motivation` node with
  its extracted text and source reference.
- A `### Evolution and inspiration` subsection listing all `EVOLVED_FROM` and
  `INSPIRED_BY` edges above the confidence threshold.

`MOTIVATED_BY` is added to the direct-connections section; `INSPIRED_BY` is
added to the latent-connections section.

### 6. Pipeline position

```
Phase 3 ──── concept_extractor   (Concept nodes + MENTIONS edges)
         │
         ├── origin_tracer       (Motivation nodes + MOTIVATED_BY, EVOLVED_FROM,
         │                        INSPIRED_BY edges)
         │
         └── semantic_linker     (SIMILAR_TO edges from concept overlap)
```

`origin_tracer` runs after `concept_extractor` because the report section for
conceptual genesis is most useful immediately after concept vocabulary has been
established.  It runs before `semantic_linker` so that `INSPIRED_BY` and
`EVOLVED_FROM` edges are available to the curator in Phase 4.

---

## Consequences

### Positive

- **The graph now captures the human story**, not just the technical one.  A
  reader of the findings document can understand *why* each repository was
  created and trace its intellectual ancestry.
- **Lineage edges are evidence-backed.**  Every `EVOLVED_FROM` and `INSPIRED_BY`
  edge carries an evidence note quoting the context snippet from the source file.
- **Zero new runtime dependencies.**  The heuristic path uses only `re` and
  `pathlib` from the standard library.  The Ollama path reuses the
  `OllamaClient` already present in the codebase — no new library is needed.
- **Fully offline by default.**  No model, no API, no embeddings — consistent
  with the local-first design constraint.  Ollama enrichment is opt-in.
- **Additive and graceful.**  Repos without a detectable origin story simply
  produce no `Motivation` node.  Repos with no cross-references produce no
  lineage edges.  The skill never raises an error for sparse input.
- **`EVOLVED_FROM` placeholder is now used.**  The predicate has been in
  `EDGE_KINDS` since the triple-store migration; `origin_tracer` gives it its
  first real population path.

### Negative / trade-offs

- **Signal quality depends on README discipline.**  Repos whose READMEs say
  nothing about purpose or history will produce no motivation or lineage signal.
  The skill cannot infer intent from code alone.
- **Short-name matching can over-match.**  A short repo name like `agent` would
  match the word "agent" anywhere in the text.  The skill mitigates this with
  word-boundary anchors (`\b`) and a requirement for a co-located lineage
  keyword, but false positives are possible for very common short names.
- **Lineage is one-directional from the source file.**  If repo B says
  "inspired by repo A" but repo A says nothing, only the edge `B → INSPIRED_BY
  → A` is emitted.  The reverse is not inferred.
- **`Motivation` nodes are per-repo, not shared.**  Two repos with similar
  motivations produce two separate `Motivation` nodes.  The `semantic_linker`
  does not currently link `Motivation` nodes to shared `Concept` nodes; that
  would require a further extension.

### Neutral

- All existing tests pass unchanged; the 37-test suite grew by 9 new tests
  specific to `origin_tracer` (7 heuristic path, 2 Ollama path).
- The skills pipeline order in `SKILL_ORDER` is updated; existing consumers of
  `SKILL_ORDER` are unaffected because the list is only iterated, never indexed
  by position.
- The Cytoscape.js graph export is unchanged; `Motivation` nodes and the new
  edge kinds are serialised by the existing generic export path.

---

## Alternatives considered

### Store motivation text directly on the Repo node as a property

Simpler schema: emit `repo:X  motivation  "text…"` as a property triple rather
than a separate `Motivation` node.

Rejected because:
1. It conflates the *content* (the text) with the *relationship* (the fact that
   a repo has an origin story).  A separate node enables richer metadata: source
   file, confidence, discovered_at — all per the triple-store provenance model.
2. A future skill could extract multiple motivation statements per repo (from
   different files or sections) and relate them with confidence scores.  A
   single property triple cannot represent that.
3. Consistent with how `Concept` nodes work: the concept is a first-class node;
   the `MENTIONS` edge carries confidence and evidence.  `Motivation` follows
   the same pattern with `MOTIVATED_BY`.

### Use an LLM to replace heuristic extraction entirely

Ask Ollama to read each README cold and return a motivation statement, without
any heuristic pre-pass.

Rejected because:
1. LLM output is non-deterministic: the same README can produce slightly
   different summaries on different runs, making diffs harder to interpret.
2. A model call is a network round-trip with a real failure mode.  The
   heuristic-first design means Dirk always produces a result, regardless
   of model availability.
3. The heading-based approach captures the author's own words verbatim when a
   good `## Why` section exists — these are more trustworthy than a model
   paraphrase.

The implemented approach combines both: heuristics first, Ollama as an
*optional refinement* when a model is available (same fallback logic as
`connection_curator`).  This gives the best of both worlds: reproducible
baseline plus quality uplift when configured.

### Infer lineage from git history (`git log --follow`)

Walk the commit history to find the original repository a branch was created
from, or look for merge commits referencing external repos.

Rejected because:
1. Git history is not always present (shallow clones, archived repos).
2. Cross-repo lineage is rarely expressed in git metadata; it lives in prose.
3. The prose-detection approach generalises to "soft" inspiration relationships
   that have no git trace at all.

---

## References

- [origin_tracer skill implementation](../../src/dirk/skills/origin_tracer.py)
- [storage module — NODE_KINDS and EDGE_KINDS](../../src/dirk/storage.py)
- [report writer — conceptual genesis section](../../src/dirk/writers.py)
- [Phase status document](../PHASES.md)
- [ADR-0001: Triple Store Storage](ADR-0001-triple-store-storage.md)
