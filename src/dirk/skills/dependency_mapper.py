"""Phase 2 skill: ``dependency-mapper``.

Reads dependency manifests from each repo's local checkout (when available
via ``repos.yml``) and records the result as ``Technology`` nodes plus
``DEPENDS_ON`` edges.

Supported ecosystems:

* ``pyproject.toml`` and ``requirements.txt`` → ``pypi``
* ``package.json`` → ``npm``
* ``go.mod`` → ``go``
* ``Cargo.toml`` → ``cargo``

Repos in scope without a local ``path`` are skipped for manifest parsing —
fetching files over the network is deliberately deferred to a later phase
so this skill remains deterministic and offline-safe. As a small consolation,
we still emit a weak ``MENTIONS`` edge between repos sharing the same owner
(the original Phase 1 → Phase 2 placeholder), since that signal is cheap and
helps the curator surface candidate compositions even with sparse data.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from dirk.skills import SkillContext, SkillResult
from dirk.skills._manifest import discover_dependencies
from dirk.storage import Edge, Node


@dataclass
class DependencyMapper:
    name: str = "dependency_mapper"

    def run(self, ctx: SkillContext) -> SkillResult:
        before_nodes = ctx.store.nodes_added
        before_edges = ctx.store.edges_added

        manifest_repos = 0
        with ctx.store.transaction():
            for source in ctx.repos:
                if source.path is None:
                    continue
                repo_id = f"repo:{source.slug}"
                deps = discover_dependencies(source.path)
                if not deps:
                    continue
                manifest_repos += 1
                for dep in deps:
                    tech_id = f"tech:{dep.ecosystem}:{dep.name}"
                    ctx.store.upsert_node(Node(
                        id=tech_id,
                        kind="Technology",
                        name=dep.name,
                        properties={"ecosystem": dep.ecosystem},
                    ))
                    ctx.store.upsert_edge(Edge(
                        src=repo_id,
                        dst=tech_id,
                        kind="DEPENDS_ON",
                        confidence=0.9,
                        evidence=[{
                            "ref": dep.source,
                            "note": f"declared in {dep.source}",
                        }],
                        discovered_by=self.name,
                    ))

            # Same-owner heuristic — weak, but keeps the curator interesting
            # when only one or two repos have local checkouts.
            by_owner: dict[str, list[str]] = defaultdict(list)
            for node in ctx.store.iter_nodes("Repo"):
                owner = node.properties.get("owner")
                if owner:
                    by_owner[owner].append(node.id)
            for owner, repo_ids in by_owner.items():
                if len(repo_ids) < 2:
                    continue
                for i, src in enumerate(repo_ids):
                    for dst in repo_ids[i + 1:]:
                        ctx.store.upsert_edge(Edge(
                            src=src,
                            dst=dst,
                            kind="MENTIONS",
                            confidence=0.2,
                            evidence=[{"ref": owner, "note": "shared owner"}],
                            discovered_by=self.name,
                        ))

        notes_parts: list[str] = []
        if manifest_repos:
            notes_parts.append(f"parsed manifests for {manifest_repos} repo(s)")
        else:
            notes_parts.append("no local checkouts in scope; only same-owner heuristic ran")
        return SkillResult(
            skill=self.name,
            nodes_added=ctx.store.nodes_added - before_nodes,
            edges_added=ctx.store.edges_added - before_edges,
            notes="; ".join(notes_parts),
        )
