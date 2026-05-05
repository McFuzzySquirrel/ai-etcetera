"""The Dirk agent — orchestrates skills end to end.

The agent is the thing that *runs* the pipeline. The Markdown sibling at
``.github/agents/dirk.md`` describes the same role from the LLM-prompt
perspective; this module is the deterministic Python plumbing the prompt
delegates to.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

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
        discovered = self._discover_scope_repos()

        # Merge with source repos as canonical for local paths.
        by_slug: dict[str, RepoSource] = {s.slug: s for s in sources}
        for repo in discovered:
            if repo.slug in by_slug:
                continue
            by_slug[repo.slug] = repo
        return sorted(by_slug.values(), key=lambda s: s.slug)

    def _discover_scope_repos(self) -> list[RepoSource]:
        github_user = self.config.scope.github_user
        github_org = self.config.scope.github_org
        if not github_user and not github_org:
            return []

        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("DIRK_GITHUB_TOKEN")
        if not token:
            return []

        try:
            import requests
        except ImportError:
            return []

        session = requests.Session()
        session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

        include_private = self.config.scope.include_private
        out: dict[str, RepoSource] = {}

        if github_user:
            for slug in self._list_user_repos(session, github_user, include_private):
                out.setdefault(slug, RepoSource(slug=slug, path=None))

        if github_org:
            for slug in self._list_org_repos(session, github_org, include_private):
                out.setdefault(slug, RepoSource(slug=slug, path=None))

        return list(out.values())

    def _list_user_repos(self, session: Any, user: str, include_private: bool) -> list[str]:
        # For the authenticated user we can include private repos when requested.
        token_user = self._get_authenticated_login(session)
        if include_private and token_user and token_user.lower() == user.lower():
            params = {
                "visibility": "all",
                "affiliation": "owner",
                "per_page": 100,
                "sort": "updated",
            }
            return self._paginate_repo_full_names(session, "https://api.github.com/user/repos", params)

        params = {"per_page": 100, "type": "owner", "sort": "updated"}
        return self._paginate_repo_full_names(session, f"https://api.github.com/users/{user}/repos", params)

    def _list_org_repos(self, session: Any, org: str, include_private: bool) -> list[str]:
        params: dict[str, Any] = {"per_page": 100, "type": "public"}
        if include_private:
            params["type"] = "all"
        return self._paginate_repo_full_names(session, f"https://api.github.com/orgs/{org}/repos", params)

    def _get_authenticated_login(self, session: Any) -> str | None:
        try:
            resp = session.get("https://api.github.com/user", timeout=20)
            if resp.status_code != 200:
                return None
            data = resp.json()
            login = data.get("login") if isinstance(data, dict) else None
            return str(login) if isinstance(login, str) and login else None
        except Exception:
            return None

    def _paginate_repo_full_names(self, session: Any, url: str, params: dict[str, Any]) -> list[str]:
        out: list[str] = []
        next_url = url
        next_params: dict[str, Any] | None = dict(params)

        while next_url:
            try:
                resp = session.get(next_url, params=next_params, timeout=30)
            except Exception:
                break
            if resp.status_code != 200:
                break

            body = resp.json()
            if not isinstance(body, list):
                break
            for item in body:
                if not isinstance(item, dict):
                    continue
                full_name = item.get("full_name")
                if isinstance(full_name, str) and "/" in full_name:
                    out.append(full_name)

            link = resp.headers.get("Link", "")
            parsed_next = self._parse_next_link(link)
            if parsed_next is None:
                break
            next_url = parsed_next[0]
            next_params = parsed_next[1]

        # Preserve order while removing duplicates.
        seen: set[str] = set()
        deduped: list[str] = []
        for slug in out:
            if slug in seen:
                continue
            seen.add(slug)
            deduped.append(slug)
        return deduped

    def _parse_next_link(self, link_header: str) -> tuple[str, dict[str, str]] | None:
        if not link_header:
            return None
        for part in link_header.split(","):
            section = part.strip()
            if 'rel="next"' not in section:
                continue
            if not section.startswith("<"):
                continue
            end = section.find(">")
            if end <= 1:
                continue
            next_url = section[1:end]
            parsed = urlparse(next_url)
            params = {k: v[-1] for k, v in parse_qs(parsed.query).items() if v}
            clean_url = parsed._replace(query="").geturl()
            return clean_url, params
        return None

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
