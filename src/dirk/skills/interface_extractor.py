"""Phase 2 skill: ``interface-extractor`` (minimal cut).

Surfaces the cheapest, most reliable parts of a repo's public surface:

* **CLI entry points** declared in ``pyproject.toml [project.scripts]`` and
  ``package.json bin``.
* **Schema / IDL files** identified by extension: ``*.proto``, ``*.graphql``,
  ``*.gql``, ``*.openapi.{yml,yaml,json}`` (and ``*openapi*.yaml`` patterns).

Each finding is recorded as an ``Interface`` node with an ``EXPOSES`` edge
from the owning repo. HTTP route extraction, exported symbol scraping, and
event-name detection are deliberately deferred — they are the slow,
language-specific work that belongs in a later iteration.

Repos without a local ``path`` in ``repos.yml`` are skipped (no network
fetching here, by design).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

try:  # Python 3.11+
    import tomllib as _tomllib
except ImportError:  # pragma: no cover - 3.10 fallback
    _tomllib = None  # type: ignore[assignment]

from dirk.skills import SkillContext, SkillResult
from dirk.storage import Edge, Node


# Recognised schema-file patterns. Keys are the kind we record on the node.
_SCHEMA_SUFFIXES: tuple[tuple[str, str], ...] = (
    (".proto", "protobuf"),
    (".graphql", "graphql"),
    (".gql", "graphql"),
)

_OPENAPI_NAME_HINTS = ("openapi", "swagger")
_OPENAPI_SUFFIXES = (".yml", ".yaml", ".json")

_SKIP_DIRS = {".git", "node_modules", "vendor", "target", "dist", "build", ".venv", "venv", "__pycache__"}


@dataclass(frozen=True)
class _Finding:
    kind: str       # "cli" | "schema"
    name: str       # short identifier (e.g. "dirk", "user.proto")
    detail: str     # subtype like "protobuf"/"openapi"/"npm"/"pypi"
    source: str     # repo-relative path of the manifest/file


@dataclass
class InterfaceExtractor:
    name: str = "interface_extractor"

    def run(self, ctx: SkillContext) -> SkillResult:
        before_nodes = ctx.store.nodes_added
        before_edges = ctx.store.edges_added

        scanned = 0
        with ctx.store.transaction():
            for source in ctx.repos:
                if source.path is None:
                    continue
                findings = _collect(source.path)
                if not findings:
                    continue
                scanned += 1
                repo_id = f"repo:{source.slug}"
                for finding in findings:
                    iface_id = f"iface:{source.slug}:{finding.kind}:{finding.name}"
                    ctx.store.upsert_node(Node(
                        id=iface_id,
                        kind="Interface",
                        name=finding.name,
                        properties={
                            "interface_kind": finding.kind,
                            "detail": finding.detail,
                            "manifest": finding.source,
                            "repo": source.slug,
                        },
                    ))
                    ctx.store.upsert_edge(Edge(
                        src=repo_id,
                        dst=iface_id,
                        kind="EXPOSES",
                        confidence=0.85,
                        evidence=[{
                            "ref": finding.source,
                            "note": f"{finding.kind} ({finding.detail}) from {finding.source}",
                        }],
                        discovered_by=self.name,
                    ))

        if scanned:
            notes = f"extracted interfaces from {scanned} repo(s)"
        else:
            notes = "no local checkouts in scope; nothing to extract"
        return SkillResult(
            skill=self.name,
            nodes_added=ctx.store.nodes_added - before_nodes,
            edges_added=ctx.store.edges_added - before_edges,
            notes=notes,
        )


# -- collection ----------------------------------------------------------

def _collect(root: Path) -> list[_Finding]:
    findings: list[_Finding] = []
    findings.extend(_cli_entries(root))
    findings.extend(_schema_files(root))
    # Dedup on (kind, name, source) — schema files with the same basename in
    # different folders should still be distinct (path differs).
    seen: set[tuple[str, str, str]] = set()
    unique: list[_Finding] = []
    for f in findings:
        key = (f.kind, f.name, f.source)
        if key in seen:
            continue
        seen.add(key)
        unique.append(f)
    return unique


def _cli_entries(root: Path) -> list[_Finding]:
    findings: list[_Finding] = []

    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and _tomllib is not None:
        try:
            data = _tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        scripts = ((data.get("project") or {}).get("scripts")) or {}
        if isinstance(scripts, dict):
            for name in scripts.keys():
                if isinstance(name, str) and name.strip():
                    findings.append(_Finding("cli", name.strip(), "pypi", "pyproject.toml"))

    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            bin_section = data.get("bin")
            if isinstance(bin_section, str):
                # Shorthand: name = package name.
                pkg_name = data.get("name")
                if isinstance(pkg_name, str) and pkg_name.strip():
                    findings.append(_Finding("cli", pkg_name.strip(), "npm", "package.json"))
            elif isinstance(bin_section, dict):
                for name in bin_section.keys():
                    if isinstance(name, str) and name.strip():
                        findings.append(_Finding("cli", name.strip(), "npm", "package.json"))
    return findings


def _schema_files(root: Path, *, max_depth: int = 4) -> list[_Finding]:
    findings: list[_Finding] = []
    for path in _walk_files(root, max_depth):
        rel = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        # Direct extension match.
        for ext, kind in _SCHEMA_SUFFIXES:
            if suffix == ext:
                findings.append(_Finding("schema", path.name, kind, rel))
                break
        else:
            # OpenAPI/Swagger by filename hint.
            if suffix in _OPENAPI_SUFFIXES:
                lowered = path.name.lower()
                if any(hint in lowered for hint in _OPENAPI_NAME_HINTS):
                    findings.append(_Finding("schema", path.name, "openapi", rel))
    return findings


def _walk_files(root: Path, max_depth: int):
    """Yield files under *root* up to ``max_depth`` directory levels deep."""
    if not root.exists() or not root.is_dir():
        return
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if depth >= max_depth:
                    continue
                if entry.name.startswith(".") and entry.name != ".":
                    continue
                if entry.name in _SKIP_DIRS:
                    continue
                stack.append((entry, depth + 1))
            elif entry.is_file():
                yield entry
