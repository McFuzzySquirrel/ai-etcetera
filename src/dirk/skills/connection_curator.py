"""Phase 4 skill stub: ``connection-curator``.

Takes the raw edges accumulated by the other skills, ranks them by
``confidence`` and recency, and writes ``COULD_COMPOSE_WITH`` edges where
two repos look complementary (e.g. one exposes an interface the other
consumes, or one's domain is a subset of the other's).

Curation is the moment Dirk turns "edges in a graph" into "things a human
might want to know". The Markdown blurbs it writes onto each suggestion
land in the findings document.

Today it combines two conservative heuristics:

* Repo pairs that already share **two or more direct edge kinds** (e.g.
  both ``MENTIONS`` and ``EXPOSES``).
* Repo pairs that share **two or more common neighbors** of kind
  ``Technology`` or ``Interface`` (i.e. they depend on the same libraries
  or expose the same kind of surface).

LLM-driven synthesis (the "real" Phase 4 work) is still pending — but with
real Phase 2 signal feeding this, the suggestions are no longer vacuous.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from dirk.skills import SkillContext, SkillResult
from dirk.storage import Edge


_SHARED_NEIGHBOR_KINDS = {"Technology", "Interface"}
_SELF_KIND = "COULD_COMPOSE_WITH"


@dataclass
class ConnectionCurator:
    name: str = "connection_curator"

    def run(self, ctx: SkillContext) -> SkillResult:
        before_nodes = ctx.store.nodes_added
        before_edges = ctx.store.edges_added

        # Index everything we'll need in a single pass over edges.
        repo_edge_kinds: dict[tuple[str, str], set[str]] = defaultdict(set)
        # For each non-repo neighbor, which repos point at it (and how).
        neighbor_to_repos: dict[str, set[str]] = defaultdict(set)
        neighbor_kind: dict[str, str] = {}

        for node in ctx.store.iter_nodes():
            if node.kind in _SHARED_NEIGHBOR_KINDS:
                neighbor_kind[node.id] = node.kind

        for edge in ctx.store.iter_edges():
            if edge["kind"] == _SELF_KIND:
                continue
            src, dst = edge["src"], edge["dst"]
            if src.startswith("repo:") and dst.startswith("repo:"):
                a, b = sorted([src, dst])
                repo_edge_kinds[(a, b)].add(edge["kind"])
            elif src.startswith("repo:") and dst in neighbor_kind:
                neighbor_to_repos[dst].add(src)
            elif dst.startswith("repo:") and src in neighbor_kind:
                neighbor_to_repos[src].add(dst)

        # Tally shared neighbors per repo pair.
        shared_neighbors: dict[tuple[str, str], list[str]] = defaultdict(list)
        for neighbor, repos in neighbor_to_repos.items():
            if len(repos) < 2:
                continue
            ordered = sorted(repos)
            for i, a in enumerate(ordered):
                for b in ordered[i + 1:]:
                    shared_neighbors[(a, b)].append(neighbor)

        all_pairs = set(repo_edge_kinds) | set(shared_neighbors)

        with ctx.store.transaction():
            for pair in all_pairs:
                kinds = repo_edge_kinds.get(pair, set())
                neighbors = shared_neighbors.get(pair, [])

                kind_signal = len(kinds) >= 2
                neighbor_signal = len(neighbors) >= 2
                if not (kind_signal or neighbor_signal):
                    continue

                # Confidence grows with both signals, capped at 0.9.
                score = 0.4 + 0.1 * len(kinds) + 0.05 * len(neighbors)
                confidence = min(score, 0.9)

                evidence: list[dict[str, str]] = []
                if kinds:
                    evidence.append({
                        "ref": ",".join(sorted(kinds)),
                        "note": "shared edge kinds: " + ", ".join(sorted(kinds)),
                    })
                if neighbors:
                    sample = sorted(neighbors)[:5]
                    evidence.append({
                        "ref": ",".join(sample),
                        "note": (
                            f"shared neighbors ({len(neighbors)}): "
                            + ", ".join(_short(n) for n in sample)
                            + (" …" if len(neighbors) > len(sample) else "")
                        ),
                    })

                a, b = pair
                ctx.store.upsert_edge(Edge(
                    src=a,
                    dst=b,
                    kind=_SELF_KIND,
                    confidence=confidence,
                    evidence=evidence,
                    discovered_by=self.name,
                ))

        return SkillResult(
            skill=self.name,
            nodes_added=ctx.store.nodes_added - before_nodes,
            edges_added=ctx.store.edges_added - before_edges,
            notes="heuristic curation (shared edge kinds + shared neighbors); LLM synthesis pending",
        )


def _short(node_id: str) -> str:
    """Trim a node id to its trailing identifier for human-friendly evidence."""
    return node_id.rsplit(":", 1)[-1]
