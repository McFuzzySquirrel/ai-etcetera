"""Tests for the Phase 3 ``origin_tracer`` skill."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import yaml

from dirk.agent import DirkAgent
from dirk.config import load_config
from dirk.ollama import OllamaMotivation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(tmp_path: Path, *, extra_skills: dict | None = None) -> None:
    skills = {
        "repo_inventory": True,
        "dependency_mapper": False,
        "interface_extractor": False,
        "concept_extractor": False,
        "origin_tracer": True,
        "semantic_linker": False,
        "connection_curator": False,
    }
    if extra_skills:
        skills.update(extra_skills)
    (tmp_path / "dirk.config.yml").write_text(
        yaml.safe_dump({
            "scope": {"source": "repos.yml"},
            "depth": "quick",
            "connection_threshold": 0.0,
            "skills": skills,
        }),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Motivation extraction
# ---------------------------------------------------------------------------

def test_origin_tracer_extracts_explicit_why_section(tmp_path, monkeypatch):
    """A repo with a ## Why heading should produce a Motivation node."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)

    repo_root = tmp_path / "checkouts" / "demo-app"
    repo_root.mkdir(parents=True)
    (repo_root / "README.md").write_text(
        "\n".join([
            "# Demo App",
            "",
            "A demonstration application.",
            "",
            "## Why",
            "",
            "This project was built because existing tools were too complex.",
            "We wanted something simpler that developers could pick up in minutes.",
        ]),
        encoding="utf-8",
    )

    _write_config(tmp_path)
    (tmp_path / "repos.yml").write_text(
        yaml.safe_dump({"repos": [{"slug": "acme/demo-app", "path": "checkouts/demo-app"}]}),
        encoding="utf-8",
    )

    cfg = load_config(root=tmp_path)
    summary = DirkAgent(cfg).run(only=["repo_inventory", "origin_tracer"])

    origin_results = [r for r in summary.skill_results if r.skill == "origin_tracer"]
    assert origin_results
    r = origin_results[0]
    assert r.nodes_added >= 1  # Motivation node
    assert r.edges_added >= 1  # MOTIVATED_BY edge

    graph = json.loads((tmp_path / "graph" / "graph.json").read_text(encoding="utf-8"))
    nodes = {el["data"]["id"]: el["data"] for el in graph["elements"] if "source" not in el["data"]}
    edges = [el["data"] for el in graph["elements"] if "source" in el["data"]]

    assert "motivation:acme/demo-app" in nodes
    mot_node = nodes["motivation:acme/demo-app"]
    assert mot_node["kind"] == "Motivation"

    motivated_by = [
        e for e in edges
        if e["kind"] == "MOTIVATED_BY" and e["source"] == "repo:acme/demo-app"
    ]
    assert len(motivated_by) == 1
    assert motivated_by[0]["target"] == "motivation:acme/demo-app"
    assert motivated_by[0]["confidence"] >= 0.8


def test_origin_tracer_falls_back_to_intro_paragraph(tmp_path, monkeypatch):
    """When there is no explicit Why section, the intro paragraph is used."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)

    repo_root = tmp_path / "checkouts" / "intro-app"
    repo_root.mkdir(parents=True)
    (repo_root / "README.md").write_text(
        "\n".join([
            "# Intro App",
            "",
            "Intro App is a lightweight toolkit for processing event streams.",
            "It focuses on low-latency handling without external dependencies.",
            "",
            "## Installation",
            "Run `pip install intro-app`.",
        ]),
        encoding="utf-8",
    )

    _write_config(tmp_path)
    (tmp_path / "repos.yml").write_text(
        yaml.safe_dump({"repos": [{"slug": "acme/intro-app", "path": "checkouts/intro-app"}]}),
        encoding="utf-8",
    )

    cfg = load_config(root=tmp_path)
    summary = DirkAgent(cfg).run(only=["repo_inventory", "origin_tracer"])

    origin_results = [r for r in summary.skill_results if r.skill == "origin_tracer"]
    assert origin_results[0].nodes_added >= 1

    graph = json.loads((tmp_path / "graph" / "graph.json").read_text(encoding="utf-8"))
    nodes = {el["data"]["id"]: el["data"] for el in graph["elements"] if "source" not in el["data"]}
    assert "motivation:acme/intro-app" in nodes


def test_origin_tracer_no_motivation_for_bare_repo(tmp_path, monkeypatch):
    """A repo with just a title and no body should not produce a Motivation node."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)

    repo_root = tmp_path / "checkouts" / "bare-repo"
    repo_root.mkdir(parents=True)
    (repo_root / "README.md").write_text("# Bare Repo\n", encoding="utf-8")

    _write_config(tmp_path)
    (tmp_path / "repos.yml").write_text(
        yaml.safe_dump({"repos": [{"slug": "acme/bare-repo", "path": "checkouts/bare-repo"}]}),
        encoding="utf-8",
    )

    cfg = load_config(root=tmp_path)
    summary = DirkAgent(cfg).run(only=["repo_inventory", "origin_tracer"])

    origin_results = [r for r in summary.skill_results if r.skill == "origin_tracer"]
    assert origin_results[0].nodes_added == 0


# ---------------------------------------------------------------------------
# Lineage detection
# ---------------------------------------------------------------------------

def test_origin_tracer_detects_evolved_from(tmp_path, monkeypatch):
    """A repo that says 'evolved from X' should emit an EVOLVED_FROM edge."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)

    ancestor = tmp_path / "checkouts" / "old-tool"
    successor = tmp_path / "checkouts" / "new-tool"
    ancestor.mkdir(parents=True)
    successor.mkdir(parents=True)

    (ancestor / "README.md").write_text("# Old Tool\nThe original toolkit.\n", encoding="utf-8")
    (successor / "README.md").write_text(
        "\n".join([
            "# New Tool",
            "",
            "New Tool evolved from old-tool after we outgrew its limitations.",
            "It keeps the same core ideas but adds a plugin architecture.",
        ]),
        encoding="utf-8",
    )

    _write_config(tmp_path)
    (tmp_path / "repos.yml").write_text(
        yaml.safe_dump({"repos": [
            {"slug": "acme/old-tool", "path": "checkouts/old-tool"},
            {"slug": "acme/new-tool", "path": "checkouts/new-tool"},
        ]}),
        encoding="utf-8",
    )

    cfg = load_config(root=tmp_path)
    summary = DirkAgent(cfg).run(only=["repo_inventory", "origin_tracer"])

    graph = json.loads((tmp_path / "graph" / "graph.json").read_text(encoding="utf-8"))
    edges = [el["data"] for el in graph["elements"] if "source" in el["data"]]

    evolved_edges = [
        e for e in edges
        if e["kind"] == "EVOLVED_FROM"
        and e["source"] == "repo:acme/new-tool"
        and e["target"] == "repo:acme/old-tool"
    ]
    assert len(evolved_edges) == 1
    assert evolved_edges[0]["confidence"] >= 0.7


def test_origin_tracer_detects_inspired_by(tmp_path, monkeypatch):
    """A repo that says 'inspired by X' should emit an INSPIRED_BY edge."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)

    source_repo = tmp_path / "checkouts" / "ref-impl"
    derived_repo = tmp_path / "checkouts" / "my-impl"
    source_repo.mkdir(parents=True)
    derived_repo.mkdir(parents=True)

    (source_repo / "README.md").write_text("# Ref Impl\nThe reference implementation.\n", encoding="utf-8")
    (derived_repo / "README.md").write_text(
        "\n".join([
            "# My Impl",
            "",
            "This project was inspired by ref-impl but takes a different approach.",
        ]),
        encoding="utf-8",
    )

    _write_config(tmp_path)
    (tmp_path / "repos.yml").write_text(
        yaml.safe_dump({"repos": [
            {"slug": "acme/ref-impl", "path": "checkouts/ref-impl"},
            {"slug": "acme/my-impl", "path": "checkouts/my-impl"},
        ]}),
        encoding="utf-8",
    )

    cfg = load_config(root=tmp_path)
    summary = DirkAgent(cfg).run(only=["repo_inventory", "origin_tracer"])

    graph = json.loads((tmp_path / "graph" / "graph.json").read_text(encoding="utf-8"))
    edges = [el["data"] for el in graph["elements"] if "source" in el["data"]]

    inspired_edges = [
        e for e in edges
        if e["kind"] == "INSPIRED_BY"
        and e["source"] == "repo:acme/my-impl"
        and e["target"] == "repo:acme/ref-impl"
    ]
    assert len(inspired_edges) == 1


def test_origin_tracer_no_self_reference(tmp_path, monkeypatch):
    """A repo should not emit lineage edges pointing at itself."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)

    repo_root = tmp_path / "checkouts" / "self-ref"
    repo_root.mkdir(parents=True)
    (repo_root / "README.md").write_text(
        "# Self Ref\nself-ref evolved from its early prototypes.\n",
        encoding="utf-8",
    )

    _write_config(tmp_path)
    (tmp_path / "repos.yml").write_text(
        yaml.safe_dump({"repos": [{"slug": "acme/self-ref", "path": "checkouts/self-ref"}]}),
        encoding="utf-8",
    )

    cfg = load_config(root=tmp_path)
    DirkAgent(cfg).run(only=["repo_inventory", "origin_tracer"])

    graph = json.loads((tmp_path / "graph" / "graph.json").read_text(encoding="utf-8"))
    edges = [el["data"] for el in graph["elements"] if "source" in el["data"]]

    self_loops = [
        e for e in edges
        if e.get("kind") in {"EVOLVED_FROM", "INSPIRED_BY"}
        and e["source"] == e["target"]
    ]
    assert not self_loops


def test_origin_tracer_no_lineage_without_keyword(tmp_path, monkeypatch):
    """A bare mention of another repo without a lineage keyword should not emit lineage edges."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)

    repo_a = tmp_path / "checkouts" / "repo-a"
    repo_b = tmp_path / "checkouts" / "repo-b"
    repo_a.mkdir(parents=True)
    repo_b.mkdir(parents=True)

    (repo_a / "README.md").write_text("# Repo A\nSee also repo-b for related tooling.\n", encoding="utf-8")
    (repo_b / "README.md").write_text("# Repo B\nA related toolkit.\n", encoding="utf-8")

    _write_config(tmp_path)
    (tmp_path / "repos.yml").write_text(
        yaml.safe_dump({"repos": [
            {"slug": "acme/repo-a", "path": "checkouts/repo-a"},
            {"slug": "acme/repo-b", "path": "checkouts/repo-b"},
        ]}),
        encoding="utf-8",
    )

    cfg = load_config(root=tmp_path)
    DirkAgent(cfg).run(only=["repo_inventory", "origin_tracer"])

    graph = json.loads((tmp_path / "graph" / "graph.json").read_text(encoding="utf-8"))
    edges = [el["data"] for el in graph["elements"] if "source" in el["data"]]

    lineage_edges = [e for e in edges if e.get("kind") in {"EVOLVED_FROM", "INSPIRED_BY"}]
    assert not lineage_edges


# ---------------------------------------------------------------------------
# Ollama enrichment
# ---------------------------------------------------------------------------

def test_origin_tracer_ollama_enriches_motivation(tmp_path, monkeypatch):
    """When Ollama is enabled and available, motivation text is enriched by the model."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)

    repo_root = tmp_path / "checkouts" / "rich-app"
    repo_root.mkdir(parents=True)
    (repo_root / "README.md").write_text(
        "\n".join([
            "# Rich App",
            "",
            "## Why",
            "",
            "We built this because the old toolkit had too many moving parts.",
        ]),
        encoding="utf-8",
    )

    skills = {
        "repo_inventory": True,
        "dependency_mapper": False,
        "interface_extractor": False,
        "concept_extractor": False,
        "origin_tracer": True,
        "semantic_linker": False,
        "connection_curator": False,
    }
    (tmp_path / "dirk.config.yml").write_text(
        yaml.safe_dump({
            "scope": {"source": "repos.yml"},
            "depth": "quick",
            "connection_threshold": 0.0,
            "curation": {
                "provider": "ollama",
                "model": "test-model",
                "base_url": "http://127.0.0.1:11434",
                "timeout_sec": 10,
                "fallback": "heuristic",
            },
            "skills": skills,
        }),
        encoding="utf-8",
    )
    (tmp_path / "repos.yml").write_text(
        yaml.safe_dump({"repos": [{"slug": "acme/rich-app", "path": "checkouts/rich-app"}]}),
        encoding="utf-8",
    )

    mock_client = MagicMock()
    mock_client.health.return_value = (True, "ok")
    mock_client.enrich_motivation.return_value = OllamaMotivation(
        summary="Built to replace an over-engineered toolkit with a simpler alternative.",
        confidence=0.92,
    )

    monkeypatch.setattr(
        "dirk.skills.origin_tracer.OllamaClient",
        lambda **kwargs: mock_client,
    )

    cfg = load_config(root=tmp_path)
    summary = DirkAgent(cfg).run(only=["repo_inventory", "origin_tracer"])

    origin_results = [r for r in summary.skill_results if r.skill == "origin_tracer"]
    assert origin_results
    assert "ollama enrichment enabled" in origin_results[0].notes

    graph = json.loads((tmp_path / "graph" / "graph.json").read_text(encoding="utf-8"))
    nodes = {el["data"]["id"]: el["data"] for el in graph["elements"] if "source" not in el["data"]}

    assert "motivation:acme/rich-app" in nodes
    mot = nodes["motivation:acme/rich-app"]
    assert mot["text"] == "Built to replace an over-engineered toolkit with a simpler alternative."

    mock_client.enrich_motivation.assert_called_once()


def test_origin_tracer_ollama_falls_back_on_health_fail(tmp_path, monkeypatch):
    """When Ollama health check fails, heuristic motivation text is used without error."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)

    repo_root = tmp_path / "checkouts" / "fallback-app"
    repo_root.mkdir(parents=True)
    (repo_root / "README.md").write_text(
        "\n".join([
            "# Fallback App",
            "",
            "## Motivation",
            "",
            "Needed a simpler way to manage configuration files across environments.",
        ]),
        encoding="utf-8",
    )

    skills = {
        "repo_inventory": True,
        "dependency_mapper": False,
        "interface_extractor": False,
        "concept_extractor": False,
        "origin_tracer": True,
        "semantic_linker": False,
        "connection_curator": False,
    }
    (tmp_path / "dirk.config.yml").write_text(
        yaml.safe_dump({
            "scope": {"source": "repos.yml"},
            "depth": "quick",
            "connection_threshold": 0.0,
            "curation": {
                "provider": "ollama",
                "model": "test-model",
                "base_url": "http://127.0.0.1:11434",
                "timeout_sec": 10,
                "fallback": "heuristic",
            },
            "skills": skills,
        }),
        encoding="utf-8",
    )
    (tmp_path / "repos.yml").write_text(
        yaml.safe_dump({"repos": [{"slug": "acme/fallback-app", "path": "checkouts/fallback-app"}]}),
        encoding="utf-8",
    )

    mock_client = MagicMock()
    mock_client.health.return_value = (False, "model not found")

    monkeypatch.setattr(
        "dirk.skills.origin_tracer.OllamaClient",
        lambda **kwargs: mock_client,
    )

    cfg = load_config(root=tmp_path)
    summary = DirkAgent(cfg).run(only=["repo_inventory", "origin_tracer"])

    origin_results = [r for r in summary.skill_results if r.skill == "origin_tracer"]
    assert origin_results
    assert "ollama unavailable" in origin_results[0].notes

    # Motivation node must still be created from heuristic extraction.
    graph = json.loads((tmp_path / "graph" / "graph.json").read_text(encoding="utf-8"))
    nodes = {el["data"]["id"]: el["data"] for el in graph["elements"] if "source" not in el["data"]}
    assert "motivation:acme/fallback-app" in nodes

    # enrich_motivation must never have been called.
    mock_client.enrich_motivation.assert_not_called()
