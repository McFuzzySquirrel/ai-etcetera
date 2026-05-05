"""End-to-end test of the Dirk agent pipeline in offline mode."""

from __future__ import annotations

from pathlib import Path

import yaml

from dirk.agent import DirkAgent
from dirk.config import load_config


def _bootstrap(tmp_path: Path) -> None:
    (tmp_path / "dirk.config.yml").write_text(yaml.safe_dump({
        "scope": {"source": "repos.yml"},
        "depth": "quick",
        "connection_threshold": 0.1,
        "serendipity": 0.3,
        "output": {"graph_dir": "graph", "findings_dir": "findings"},
        "skills": {
            "repo_inventory": True,
            "dependency_mapper": True,
            "interface_extractor": True,
            "concept_extractor": False,
            "semantic_linker": False,
            "connection_curator": True,
        },
    }), encoding="utf-8")
    (tmp_path / "repos.yml").write_text(yaml.safe_dump({
        "repos": ["alpha/one", "alpha/two", "beta/three"],
    }), encoding="utf-8")


def test_full_pipeline_offline(tmp_path, monkeypatch):
    _bootstrap(tmp_path)
    # Force offline mode for repo_inventory.
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)

    cfg = load_config(root=tmp_path)
    agent = DirkAgent(cfg)
    summary = agent.run()

    # Repo + Person nodes were created.
    assert summary.nodes_added >= 5  # 3 repos + at least 2 distinct owners
    # Same-owner heuristic links alpha/one ↔ alpha/two.
    assert any(r.skill == "dependency_mapper" and r.edges_added >= 1 for r in summary.skill_results)
    # Curator promoted that into a COULD_COMPOSE_WITH because two edge kinds exist.
    assert any(r.skill == "connection_curator" for r in summary.skill_results)

    # Outputs landed on disk.
    assert summary.findings_path is not None and summary.findings_path.exists()
    assert summary.graph_paths["json"].exists()
    assert summary.graph_paths["html"].exists()
    assert summary.graph_paths["db"].exists()

    body = summary.findings_path.read_text(encoding="utf-8")
    assert "Holistic Discovery" in body
    assert "alpha/one" in body
    assert "alpha/two" in body

    # Latest pointer was written.
    assert (tmp_path / "findings" / "latest.md").exists()


def test_second_run_emits_delta(tmp_path, monkeypatch):
    _bootstrap(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)
    cfg = load_config(root=tmp_path)

    DirkAgent(cfg).run()

    # Add a new repo and run again — delta should mention it.
    (tmp_path / "repos.yml").write_text(yaml.safe_dump({
        "repos": ["alpha/one", "alpha/two", "beta/three", "gamma/four"],
    }), encoding="utf-8")

    summary = DirkAgent(cfg).run()
    assert summary.delta_path is not None and summary.delta_path.exists()
    delta = summary.delta_path.read_text(encoding="utf-8")
    assert "gamma/four" in delta


def test_resolve_repos_merges_source_and_discovery(tmp_path, monkeypatch):
    (tmp_path / "dirk.config.yml").write_text(yaml.safe_dump({
        "scope": {
            "source": "repos.yml",
            "github_user": "McFuzzySquirrel",
            "github_org": "eZansiEdgeAI",
            "include_private": True,
        },
    }), encoding="utf-8")
    (tmp_path / "repos.yml").write_text(yaml.safe_dump({
        "repos": [
            {"slug": "alpha/one", "path": "./alpha-one"},
            "beta/two",
        ],
    }), encoding="utf-8")

    cfg = load_config(root=tmp_path)
    agent = DirkAgent(cfg)

    from dirk.config import RepoSource

    monkeypatch.setattr(
        agent,
        "_discover_scope_repos",
        lambda: [
            RepoSource("beta/two", None),
            RepoSource("gamma/three", None),
        ],
    )

    repos = agent.resolve_repos()
    slugs = [r.slug for r in repos]
    assert slugs == ["alpha/one", "beta/two", "gamma/three"]

    # Keep local path from repos.yml when the slug already exists.
    alpha = next(r for r in repos if r.slug == "alpha/one")
    assert alpha.path is not None


def test_discovery_returns_empty_without_token(tmp_path, monkeypatch):
    (tmp_path / "dirk.config.yml").write_text(yaml.safe_dump({
        "scope": {
            "source": "repos.yml",
            "github_user": "McFuzzySquirrel",
        },
    }), encoding="utf-8")
    (tmp_path / "repos.yml").write_text("repos: []\n", encoding="utf-8")

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)

    cfg = load_config(root=tmp_path)
    agent = DirkAgent(cfg)
    assert agent._discover_scope_repos() == []
