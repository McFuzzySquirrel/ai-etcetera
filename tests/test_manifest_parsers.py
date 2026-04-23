"""Tests for the Phase 2 manifest-parsing helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from dirk.skills._manifest import (
    Dependency,
    discover_dependencies,
    parse_cargo_toml,
    parse_go_mod,
    parse_package_json,
    parse_pyproject,
    parse_requirements_txt,
)


_HAS_TOMLLIB = sys.version_info >= (3, 11)


@pytest.mark.skipif(not _HAS_TOMLLIB, reason="tomllib requires Python 3.11+")
def test_parse_pyproject_extracts_dependencies(tmp_path: Path) -> None:
    p = tmp_path / "pyproject.toml"
    p.write_text(
        "\n".join([
            "[project]",
            'name = "thing"',
            "dependencies = [",
            '  "click>=8.1",',
            '  "PyYAML>=6.0",',
            "]",
            "",
            "[project.optional-dependencies]",
            'dev = ["pytest>=7.4", "pytest-cov>=4.1"]',
            "",
            "[tool.something]",
            'value = "ignored"',
        ]),
        encoding="utf-8",
    )
    deps = parse_pyproject(p)
    names = {d.name for d in deps}
    assert {"click", "pyyaml", "pytest", "pytest-cov"} <= names
    assert all(d.ecosystem == "pypi" for d in deps)


def test_parse_requirements_txt_handles_comments(tmp_path: Path) -> None:
    p = tmp_path / "requirements.txt"
    p.write_text(
        "\n".join([
            "# top-level comment",
            "requests==2.31.0  # pinned",
            "",
            "click>=8.1",
            "-e .",
            "--index-url https://example.com",
        ]),
        encoding="utf-8",
    )
    deps = parse_requirements_txt(p)
    assert {d.name for d in deps} == {"requests", "click"}


def test_parse_package_json_collects_all_sections(tmp_path: Path) -> None:
    p = tmp_path / "package.json"
    p.write_text(json.dumps({
        "name": "thing",
        "dependencies": {"react": "^18.0.0"},
        "devDependencies": {"jest": "^29.0.0"},
        "peerDependencies": {"react": "^18.0.0"},
    }), encoding="utf-8")
    deps = parse_package_json(p)
    assert {d.name for d in deps} == {"react", "jest"}
    assert all(d.ecosystem == "npm" for d in deps)


def test_parse_go_mod_handles_block_and_single(tmp_path: Path) -> None:
    p = tmp_path / "go.mod"
    p.write_text(
        "\n".join([
            "module example.com/thing",
            "",
            "go 1.21",
            "",
            "require github.com/spf13/cobra v1.8.0",
            "",
            "require (",
            "    github.com/stretchr/testify v1.9.0",
            "    golang.org/x/sync v0.7.0 // indirect",
            ")",
        ]),
        encoding="utf-8",
    )
    deps = parse_go_mod(p)
    names = {d.name for d in deps}
    assert names == {
        "github.com/spf13/cobra",
        "github.com/stretchr/testify",
        "golang.org/x/sync",
    }
    assert all(d.ecosystem == "go" for d in deps)


@pytest.mark.skipif(not _HAS_TOMLLIB, reason="tomllib requires Python 3.11+")
def test_parse_cargo_toml(tmp_path: Path) -> None:
    p = tmp_path / "Cargo.toml"
    p.write_text(
        "\n".join([
            "[package]",
            'name = "thing"',
            "",
            "[dependencies]",
            'serde = "1.0"',
            'tokio = { version = "1", features = ["full"] }',
            "",
            "[dev-dependencies]",
            'proptest = "1.0"',
        ]),
        encoding="utf-8",
    )
    deps = parse_cargo_toml(p)
    assert {d.name for d in deps} == {"serde", "tokio", "proptest"}


def test_discover_dependencies_walks_shallowly(tmp_path: Path) -> None:
    # Top-level package.json
    (tmp_path / "package.json").write_text(json.dumps({
        "dependencies": {"react": "^18.0.0"},
    }), encoding="utf-8")
    # Nested go.mod inside a packages/* dir.
    nested = tmp_path / "packages" / "api"
    nested.mkdir(parents=True)
    (nested / "go.mod").write_text(
        "module example.com/api\nrequire github.com/spf13/cobra v1.8.0\n",
        encoding="utf-8",
    )
    # node_modules should be skipped even if it contains a manifest.
    nm = tmp_path / "node_modules" / "evil"
    nm.mkdir(parents=True)
    (nm / "package.json").write_text(json.dumps({
        "dependencies": {"should-not-appear": "^1"},
    }), encoding="utf-8")

    deps = discover_dependencies(tmp_path)
    by_eco = {(d.ecosystem, d.name) for d in deps}
    assert ("npm", "react") in by_eco
    assert ("go", "github.com/spf13/cobra") in by_eco
    assert all(d.name != "should-not-appear" for d in deps)


def test_discover_dependencies_returns_empty_for_missing_root(tmp_path: Path) -> None:
    assert discover_dependencies(tmp_path / "nope") == []


def test_dependency_dataclass_is_hashable() -> None:
    a = Dependency("pypi", "click", "pyproject.toml")
    b = Dependency("pypi", "click", "pyproject.toml")
    assert {a, b} == {a}
