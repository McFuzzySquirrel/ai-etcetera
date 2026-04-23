"""Phase 1 skill: ``repo-inventory``.

For each repository in scope, record a ``Repo`` node carrying basic metadata.

The skill works in two modes:

* **GitHub mode** — if a ``GITHUB_TOKEN`` is available *and* the optional
  ``requests`` dependency is installed, query the GitHub REST API for each
  repo and capture languages, topics, owner, default branch, last push.

* **Offline mode** — otherwise, create stub nodes with just the owner / name
  so the rest of the pipeline still has something to chew on. This keeps
  Dirk runnable in environments without network access (notably tests and
  local dry-runs).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from dirk.skills import SkillContext, SkillResult
from dirk.storage import Node


@dataclass
class RepoInventory:
    name: str = "repo_inventory"

    def run(self, ctx: SkillContext) -> SkillResult:
        before_nodes = ctx.store.nodes_added
        before_edges = ctx.store.edges_added
        notes: list[str] = []

        client = _maybe_github_client()
        if client is None:
            notes.append("offline mode: no GITHUB_TOKEN or requests not installed")

        with ctx.store.transaction():
            for source in ctx.repos:
                slug = source.slug
                owner, name = source.owner, source.name
                if not owner or not name:
                    continue
                node_id = f"repo:{slug}"
                props: dict[str, Any] = {"owner": owner, "name": name, "slug": slug}
                if source.path is not None:
                    props["local_path"] = str(source.path)
                if client is not None:
                    fetched = client.fetch_repo(slug)
                    if fetched:
                        props.update(fetched)
                ctx.store.upsert_node(Node(
                    id=node_id,
                    kind="Repo",
                    name=slug,
                    properties=props,
                ))
                # Owner as a Person node + AUTHORED_BY edge — cheap, useful later.
                person_id = f"person:{owner}"
                ctx.store.upsert_node(Node(id=person_id, kind="Person", name=owner))
                from dirk.storage import Edge
                ctx.store.upsert_edge(Edge(
                    src=node_id,
                    dst=person_id,
                    kind="AUTHORED_BY",
                    confidence=1.0,
                    evidence=[{"ref": slug, "note": "owner of repository"}],
                    discovered_by=self.name,
                ))

        return SkillResult(
            skill=self.name,
            nodes_added=ctx.store.nodes_added - before_nodes,
            edges_added=ctx.store.edges_added - before_edges,
            notes="; ".join(notes),
        )


# -- optional GitHub client ----------------------------------------------

class _GithubClient:
    """Tiny GitHub REST client. Only used when ``requests`` is installed."""

    def __init__(self, token: str):
        import requests  # local import so the dep stays optional
        self._requests = requests
        self._token = token
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def fetch_repo(self, slug: str) -> dict[str, Any] | None:
        try:
            r = self._session.get(f"https://api.github.com/repos/{slug}", timeout=15)
            if r.status_code != 200:
                return None
            data = r.json()
            return {
                "description": data.get("description"),
                "default_branch": data.get("default_branch"),
                "language": data.get("language"),
                "topics": data.get("topics") or [],
                "pushed_at": data.get("pushed_at"),
                "license": (data.get("license") or {}).get("spdx_id"),
                "private": bool(data.get("private")),
                "archived": bool(data.get("archived")),
                "html_url": data.get("html_url"),
            }
        except Exception:  # pragma: no cover - network failure path
            return None


def _maybe_github_client() -> _GithubClient | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("DIRK_GITHUB_TOKEN")
    if not token:
        return None
    try:
        import requests  # noqa: F401
    except ImportError:
        return None
    return _GithubClient(token)
