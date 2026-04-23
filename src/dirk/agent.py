"""The Dirk agent — orchestrates skills end to end.

The agent is the thing that *runs* the pipeline. The Markdown sibling at
``.github/agents/dirk.md`` describes the same role from the LLM-prompt
perspective; this module is the deterministic Python plumbing the prompt
delegates to.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dirk.config import Config, RepoSource, load_repos
from dirk.skills import SKILL_ORDER, SKILL_REGISTRY, SkillContext, SkillResult
from dirk.storage import GraphStore
from dirk.writers import GraphWriter, ReportWriter


@dataclass
class AgentRunSummary:
    skill_results: list[SkillResult]
    nodes_added: int
    edges_added: int
    findings_path: Path | None
    delta_path: Path | None
    graph_paths: dict[str, Path]


class DirkAgent:
    """Holistic research agent. Stateless — all state lives in the graph store."""

    def __init__(self, config: Config):
        self.config = config

    # -- scope -----------------------------------------------------------

    def resolve_repos(self) -> list["RepoSource"]:
        scope_path = self.config.root / self.config.scope.source
        sources = list(load_repos(scope_path))
        # Auto-discovery from a GitHub user/org happens here in a future phase.
        # For now scope.source is authoritative.
        return sorted(sources, key=lambda s: s.slug)

    # -- run -------------------------------------------------------------

    def run(self, *, only: list[str] | None = None) -> AgentRunSummary:
        repos = self.resolve_repos()
        previous_snapshot = self._load_previous_snapshot()

        with GraphStore(self.config.db_path) as store:
            ctx = SkillContext(config=self.config, store=store, repos=repos)

            skills_to_run = [
                name for name in SKILL_ORDER
                if (only is None and self.config.is_skill_enabled(name))
                or (only is not None and name in only)
            ]
            run_id = store.start_run(self.config.depth, skills_to_run)

            results: list[SkillResult] = []
            for name in skills_to_run:
                cls = SKILL_REGISTRY[name]
                skill = cls()
                results.append(skill.run(ctx))

            # Persist artefacts.
            graph_writer = GraphWriter(self.config, store)
            graph_paths = graph_writer.write()

            report_writer = ReportWriter(self.config, store)
            findings_path = report_writer.write_findings()
            delta_path = report_writer.write_delta(previous_snapshot)

            store.finish_run(run_id, notes=f"skills={skills_to_run}")

            return AgentRunSummary(
                skill_results=results,
                nodes_added=store.nodes_added,
                edges_added=store.edges_added,
                findings_path=findings_path,
                delta_path=delta_path,
                graph_paths=graph_paths,
            )

    # -- helpers ---------------------------------------------------------

    def _load_previous_snapshot(self) -> dict[str, Any] | None:
        prior = self.config.graph_dir / "graph.json"
        if not prior.exists():
            return None
        try:
            return json.loads(prior.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
