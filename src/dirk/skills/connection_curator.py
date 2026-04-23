"""Phase 4 skill stub: ``connection-curator``.

Takes the raw edges accumulated by the other skills, ranks them by
``confidence`` and recency, and writes ``COULD_COMPOSE_WITH`` edges where
two repos look complementary (e.g. one exposes an interface the other
consumes, or one's domain is a subset of the other's).

Curation is the moment Dirk turns "edges in a graph" into "things a human
might want to know". The Markdown blurbs it writes onto each suggestion
land in the findings document.

Currently produces ``COULD_COMPOSE_WITH`` edges from any pair of repos that
already share two or more incoming edge kinds — a deliberately conservative
heuristic until the upstream skills are richer.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from dirk.skills import SkillContext, SkillResult
from dirk.storage import Edge


@dataclass
class ConnectionCurator:
    name: str = "connection_curator"

    def run(self, ctx: SkillContext) -> SkillResult:
        before_nodes = ctx.store.nodes_added
        before_edges = ctx.store.edges_added

        # Group edges by unordered repo pair.
        pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
        for edge in ctx.store.iter_edges():
            if not edge["src"].startswith("repo:") or not edge["dst"].startswith("repo:"):
                continue
            if edge["kind"] in {"COULD_COMPOSE_WITH"}:
                continue
            a, b = sorted([edge["src"], edge["dst"]])
            pairs[(a, b)].add(edge["kind"])

        with ctx.store.transaction():
            for (a, b), kinds in pairs.items():
                if len(kinds) < 2:
                    continue
                ctx.store.upsert_edge(Edge(
                    src=a,
                    dst=b,
                    kind="COULD_COMPOSE_WITH",
                    confidence=min(0.4 + 0.1 * len(kinds), 0.9),
                    evidence=[{
                        "ref": ",".join(sorted(kinds)),
                        "note": "shared edge kinds: " + ", ".join(sorted(kinds)),
                    }],
                    discovered_by=self.name,
                ))

        return SkillResult(
            skill=self.name,
            nodes_added=ctx.store.nodes_added - before_nodes,
            edges_added=ctx.store.edges_added - before_edges,
            notes="basic heuristic — replace with LLM-driven curation in Phase 4",
        )
