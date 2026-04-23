"""Integration tests for the Phase 2 skills against fixture repos on disk."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from dirk.agent import DirkAgent
from dirk.config import load_config


_HAS_TOMLLIB = sys.version_info >= (3, 11)


def _bootstrap(tmp_path: Path) -> tuple[Path, Path]:
    """Lay out two repos, one Python and one Node, plus a schema file."""
    repos_root = tmp_path / "checkouts"
    repo_a = repos_root / "alpha-svc"
    repo_b = repos_root / "beta-cli"
    repo_a.mkdir(parents=True)
    repo_b.mkdir(parents=True)

    (repo_a / "pyproject.toml").write_text(
        "\n".join([
            "[project]",
            'name = "alpha-svc"',
            'dependencies = ["click>=8.1", "PyYAML>=6.0"]',
            "",
            "[project.scripts]",
            'alpha = "alpha_svc.cli:main"',
        ]),
        encoding="utf-8",
    )
    (repo_a / "openapi.yaml").write_text("openapi: 3.0.0\n", encoding="utf-8")
    schema_dir = repo_a / "schemas"
    schema_dir.mkdir()
    (schema_dir / "user.proto").write_text("syntax = \"proto3\";\n", encoding="utf-8")

    (repo_b / "package.json").write_text(json.dumps({
        "name": "beta-cli",
        "bin": {"beta": "./bin/beta.js"},
        "dependencies": {"react": "^18.0.0"},
        "devDependencies": {"jest": "^29.0.0"},
    }), encoding="utf-8")

    # A second Python repo that shares a dependency with alpha-svc — this
    # gives the curator a real "shared neighbor" signal to act on.
    repo_c = repos_root / "gamma-tools"
    repo_c.mkdir()
    (repo_c / "requirements.txt").write_text(
        "click>=8.1\nPyYAML>=6.0\nrequests==2.31.0\n", encoding="utf-8",
    )

    (tmp_path / "dirk.config.yml").write_text(yaml.safe_dump({
        "scope": {"source": "repos.yml"},
        "depth": "quick",
        "connection_threshold": 0.1,
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
        "repos": [
            {"slug": "acme/alpha-svc", "path": "checkouts/alpha-svc"},
            {"slug": "acme/beta-cli", "path": "checkouts/beta-cli"},
            {"slug": "acme/gamma-tools", "path": "checkouts/gamma-tools"},
        ],
    }), encoding="utf-8")

    return repos_root, repo_a


@pytest.mark.skipif(not _HAS_TOMLLIB, reason="tomllib (used by pyproject parser) requires 3.11+")
def test_dependency_mapper_emits_technology_nodes(tmp_path, monkeypatch):
    _bootstrap(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)
    cfg = load_config(root=tmp_path)
    summary = DirkAgent(cfg).run()

    # dependency_mapper should report it parsed at least one repo.
    dep_results = [r for r in summary.skill_results if r.skill == "dependency_mapper"]
    assert dep_results and dep_results[0].nodes_added >= 3  # click + pyyaml + react etc.

    # Inspect the graph.
    graph = json.loads((tmp_path / "graph" / "graph.json").read_text(encoding="utf-8"))
    nodes = [el["data"] for el in graph["elements"] if "source" not in el["data"]]
    edges = [el["data"] for el in graph["elements"] if "source" in el["data"]]

    tech_names = {n["label"] for n in nodes if n.get("kind") == "Technology"}
    assert {"click", "pyyaml", "react"} <= tech_names

    # The shared dep (click) should be DEPENDS_ON-linked from both Python repos.
    click_deps = [
        e for e in edges
        if e["kind"] == "DEPENDS_ON" and e["target"].endswith(":click")
    ]
    sources = {e["source"] for e in click_deps}
    assert "repo:acme/alpha-svc" in sources
    assert "repo:acme/gamma-tools" in sources


@pytest.mark.skipif(not _HAS_TOMLLIB, reason="tomllib (used by pyproject parser) requires 3.11+")
def test_interface_extractor_records_cli_and_schemas(tmp_path, monkeypatch):
    _bootstrap(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)
    cfg = load_config(root=tmp_path)
    DirkAgent(cfg).run()

    graph = json.loads((tmp_path / "graph" / "graph.json").read_text(encoding="utf-8"))
    ifaces = [el["data"] for el in graph["elements"]
              if "source" not in el["data"] and el["data"].get("kind") == "Interface"]
    by_kind: dict[str, set[str]] = {}
    for iface in ifaces:
        by_kind.setdefault(iface.get("interface_kind", "?"), set()).add(iface["label"])

    # CLI entry points from both pyproject + package.json.
    assert "alpha" in by_kind.get("cli", set())
    assert "beta" in by_kind.get("cli", set())
    # Schema files from both proto and openapi.
    schemas = by_kind.get("schema", set())
    assert "user.proto" in schemas
    assert "openapi.yaml" in schemas

    # EXPOSES edges link the repo to its interfaces.
    edges = [el["data"] for el in graph["elements"] if "source" in el["data"]]
    exposes = [e for e in edges if e["kind"] == "EXPOSES"]
    assert any(e["source"] == "repo:acme/alpha-svc" for e in exposes)
    assert any(e["source"] == "repo:acme/beta-cli" for e in exposes)


@pytest.mark.skipif(not _HAS_TOMLLIB, reason="tomllib (used by pyproject parser) requires 3.11+")
def test_curator_uses_shared_dependencies(tmp_path, monkeypatch):
    _bootstrap(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("DIRK_GITHUB_TOKEN", raising=False)
    cfg = load_config(root=tmp_path)
    DirkAgent(cfg).run()

    graph = json.loads((tmp_path / "graph" / "graph.json").read_text(encoding="utf-8"))
    edges = [el["data"] for el in graph["elements"] if "source" in el["data"]]
    compose = [e for e in edges if e["kind"] == "COULD_COMPOSE_WITH"]
    pairs = {tuple(sorted([e["source"], e["target"]])) for e in compose}
    # alpha-svc and gamma-tools share at least one dependency (click) and same
    # owner — that's two signals, enough for the curator to pair them.
    assert ("repo:acme/alpha-svc", "repo:acme/gamma-tools") in pairs
