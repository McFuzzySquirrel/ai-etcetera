"""Phase 3 skill: deterministic local ``semantic-linker``.

This first cut links repositories that share extracted concepts. It emits one
canonical ``SIMILAR_TO`` edge per repo pair, using a confidence score derived
from concept overlap and the configured serendipity level.

Embeddings are intentionally deferred to a later iteration.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from dirk.skills import SkillContext, SkillResult
from dirk.storage import Edge


def _is_repo_id(node_id: str) -> bool:
    return node_id.startswith("repo:")


def _is_concept_id(node_id: str) -> bool:
    return node_id.startswith("concept:")


@dataclass
class SemanticLinker:
    name: str = "semantic_linker"

    def run(self, ctx: SkillContext) -> SkillResult:
        before_nodes = ctx.store.nodes_added
        before_edges = ctx.store.edges_added

        repo_concepts = _repo_concepts(ctx)
        repos = sorted(repo_concepts)
        if len(repos) < 2:
            return SkillResult(
                skill=self.name,
                nodes_added=ctx.store.nodes_added - before_nodes,
                edges_added=ctx.store.edges_added - before_edges,
                notes="not enough concept-bearing repos to link",
            )

        serendipity = max(0.0, min(1.0, float(ctx.config.serendipity)))
        min_confidence = max(0.35, 0.55 - (0.2 * serendipity))

        pairs_linked = 0
        with ctx.store.transaction():
            for idx, left in enumerate(repos):
                left_concepts = repo_concepts[left]
                if not left_concepts:
                    continue
                for right in repos[idx + 1:]:
                    right_concepts = repo_concepts[right]
                    if not right_concepts:
                        continue
                    shared = sorted(left_concepts & right_concepts)
                    if not shared:
                        continue

                    overlap = len(shared) / max(len(left_concepts), len(right_concepts))
                    confidence = min(0.95, 0.4 + (0.45 * overlap) + (0.15 * serendipity))
                    if confidence < min_confidence:
                        continue

                    evidence = []
                    for concept_id in shared[:3]:
                        concept = ctx.store.get_node(concept_id)
                        label = concept.name if concept else concept_id.removeprefix("concept:")
                        evidence.append({
                            "ref": concept_id,
                            "note": f"shared concept: {label}",
                        })

                    src, dst = sorted((left, right))
                    ctx.store.upsert_edge(Edge(
                        src=src,
                        dst=dst,
                        kind="SIMILAR_TO",
                        confidence=confidence,
                        evidence=evidence,
                        discovered_by=self.name,
                    ))
                    pairs_linked += 1

        notes = f"linked {pairs_linked} repo pair(s) via shared concepts"
        return SkillResult(
            skill=self.name,
            nodes_added=ctx.store.nodes_added - before_nodes,
            edges_added=ctx.store.edges_added - before_edges,
            notes=notes,
        )


def _repo_concepts(ctx: SkillContext) -> dict[str, set[str]]:
    by_repo: dict[str, set[str]] = defaultdict(set)
    for edge in ctx.store.iter_edges("MENTIONS"):
        src = str(edge.get("src") or "")
        dst = str(edge.get("dst") or "")
        if not _is_repo_id(src) or not _is_concept_id(dst):
            continue
        by_repo[src].add(dst)
    return by_repo
