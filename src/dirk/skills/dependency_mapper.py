"""Phase 2 skill stub: ``dependency-mapper``.

Will produce explicit ``DEPENDS_ON`` edges between repos based on:

* Package manifests (``package.json``, ``pyproject.toml``, ``go.mod``,
  ``Cargo.toml``, ``pom.xml``, ``Gemfile``, etc.).
* Git submodules.
* Cross-repo imports detected via simple grep of source files.
* Explicit references in READMEs / issue bodies.

For now it inspects only the **already-recorded ``Repo`` nodes** and emits a
weak ``MENTIONS`` edge between repos sharing the same owner — a placeholder
edge so the rest of the pipeline (curator, viewer) has something to render
during the Phase 1 → Phase 2 transition.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from dirk.skills import SkillContext, SkillResult
from dirk.storage import Edge


@dataclass
class DependencyMapper:
    name: str = "dependency_mapper"

    def run(self, ctx: SkillContext) -> SkillResult:
        before_nodes = ctx.store.nodes_added
        before_edges = ctx.store.edges_added

        by_owner: dict[str, list[str]] = defaultdict(list)
        for node in ctx.store.iter_nodes("Repo"):
            owner = node.properties.get("owner")
            if owner:
                by_owner[owner].append(node.id)

        with ctx.store.transaction():
            for owner, repo_ids in by_owner.items():
                if len(repo_ids) < 2:
                    continue
                for i, src in enumerate(repo_ids):
                    for dst in repo_ids[i + 1:]:
                        ctx.store.upsert_edge(Edge(
                            src=src,
                            dst=dst,
                            kind="MENTIONS",
                            confidence=0.2,  # weak — same-owner is a hint, not proof
                            evidence=[{"ref": owner, "note": "shared owner"}],
                            discovered_by=self.name,
                        ))

        return SkillResult(
            skill=self.name,
            nodes_added=ctx.store.nodes_added - before_nodes,
            edges_added=ctx.store.edges_added - before_edges,
            notes="placeholder: same-owner heuristic only; full manifest parsing pending",
        )
