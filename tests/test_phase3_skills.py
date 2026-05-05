"""Integration tests for the initial Phase 3 deterministic skills."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from dirk.agent import DirkAgent
from dirk.config import load_config


def _bootstrap(tmp_path: Path) -> None:
    repo_root = tmp_path / "checkouts" / "signal-lab"
    repo_root.mkdir(parents=True)

    (repo_root / "README.md").write_text(
        "\n".join([
            "# Signal Lab",
            "",
            "Signal Lab explores semantic linking for agent orchestration.",
            "The semantic linking workflow keeps agent orchestration explainable.",
            "",
            "## Agent Orchestration",
            "Agent orchestration coordinates local tools and graph evidence.",
            "",
            "## Semantic Linking",
            "Semantic linking highlights related repositories through shared concepts.",
        ]),
        encoding="utf-8",
    )

    docs_dir = repo_root / "docs"
    docs_dir.mkdir()
    (docs_dir / "architecture.md").write_text(
        "\n".join([
            "# Agent Orchestration",
            "",
            "## Semantic Linking",
            "",
            "## Graph Evidence",
        ]),
        encoding="utf-8",
    )

    (repo_root / "pyproject.toml").write_text(
        "\n".join([
            "[project]",
            'name = "signal-lab"',
            'description = "Semantic linking workspace for agent orchestration and graph evidence"',
        ]),
        encoding="utf-8",
    )

    (tmp_path / "dirk.config.yml").write_text(yaml.safe_dump({
        "scope": {"source": "repos.yml"},
        "depth": "quick",
        "skills": {
            "repo_inventory": True,
            "dependency_mapper": False,
            "interface_extractor": False,
            "concept_extractor": True,
            "semantic_linker": False,
            "connection_curator": False,
        },
    }), encoding="utf-8")

    (tmp_path / "repos.yml").write_text(yaml.safe_dump({
        "repos": [{"slug": "acme/signal-lab", "path": "checkouts/signal-lab"}],
    }), encoding="utf-8")


def test_concept_extractor_emits_concepts_and_mentions(tmp_path, monkeypatch):
    _bootstrap(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)

    cfg = load_config(root=tmp_path)
    summary = DirkAgent(cfg).run(only=["repo_inventory", "concept_extractor"])

    concept_results = [r for r in summary.skill_results if r.skill == "concept_extractor"]
    assert concept_results
    assert concept_results[0].nodes_added >= 2
    assert concept_results[0].edges_added >= 2

    graph = json.loads((tmp_path / "graph" / "graph.json").read_text(encoding="utf-8"))
    nodes = [el["data"] for el in graph["elements"] if "source" not in el["data"]]
    edges = [el["data"] for el in graph["elements"] if "source" in el["data"]]

    concept_nodes = {
        node["id"]: node
        for node in nodes
        if node.get("kind") == "Concept"
    }
    assert "concept:semantic-linking" in concept_nodes
    assert "concept:agent-orchestration" in concept_nodes

    mention_targets = {
        edge["target"]
        for edge in edges
        if edge["kind"] == "MENTIONS" and edge["source"] == "repo:acme/signal-lab"
    }
    assert "concept:semantic-linking" in mention_targets
    assert "concept:agent-orchestration" in mention_targets


def _bootstrap_linking(tmp_path: Path) -> None:
    alpha = tmp_path / "checkouts" / "alpha-link"
    beta = tmp_path / "checkouts" / "beta-link"
    gamma = tmp_path / "checkouts" / "gamma-other"
    alpha.mkdir(parents=True)
    beta.mkdir(parents=True)
    gamma.mkdir(parents=True)

    (alpha / "README.md").write_text(
        "\n".join([
            "# Alpha Link",
            "Semantic linking for graph orchestration.",
            "Agent orchestration coordinates concept graph evidence.",
        ]),
        encoding="utf-8",
    )
    (beta / "README.md").write_text(
        "\n".join([
            "# Beta Link",
            "This repo improves semantic linking in graph workflows.",
            "Agent orchestration uses graph evidence for recommendations.",
        ]),
        encoding="utf-8",
    )
    (gamma / "README.md").write_text(
        "\n".join([
            "# Gamma Other",
            "Image rendering utilities and shader playground.",
        ]),
        encoding="utf-8",
    )

    (tmp_path / "dirk.config.yml").write_text(yaml.safe_dump({
        "scope": {"source": "repos.yml"},
        "depth": "quick",
        "serendipity": 0.6,
        "skills": {
            "repo_inventory": True,
            "dependency_mapper": False,
            "interface_extractor": False,
            "concept_extractor": True,
            "semantic_linker": True,
            "connection_curator": False,
        },
    }), encoding="utf-8")
    (tmp_path / "repos.yml").write_text(yaml.safe_dump({
        "repos": [
            {"slug": "acme/alpha-link", "path": "checkouts/alpha-link"},
            {"slug": "acme/beta-link", "path": "checkouts/beta-link"},
            {"slug": "acme/gamma-other", "path": "checkouts/gamma-other"},
        ],
    }), encoding="utf-8")


def test_semantic_linker_emits_single_canonical_edge(tmp_path, monkeypatch):
    _bootstrap_linking(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)

    cfg = load_config(root=tmp_path)
    summary = DirkAgent(cfg).run(only=["repo_inventory", "concept_extractor", "semantic_linker"])

    link_results = [r for r in summary.skill_results if r.skill == "semantic_linker"]
    assert link_results
    assert link_results[0].edges_added >= 1

    graph = json.loads((tmp_path / "graph" / "graph.json").read_text(encoding="utf-8"))
    edges = [el["data"] for el in graph["elements"] if "source" in el["data"]]

    similar_edges = [edge for edge in edges if edge["kind"] == "SIMILAR_TO"]
    assert similar_edges

    pair = tuple(sorted(["repo:acme/alpha-link", "repo:acme/beta-link"]))
    canonical_edge = [
        edge for edge in similar_edges
        if tuple(sorted([edge["source"], edge["target"]])) == pair
    ]
    assert len(canonical_edge) == 1

    reverse_edge = [
        edge for edge in similar_edges
        if edge["source"] == "repo:acme/beta-link" and edge["target"] == "repo:acme/alpha-link"
    ]
    assert not reverse_edge
