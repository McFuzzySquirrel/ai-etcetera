"""Helpers for reading dependency manifests off a local repository checkout.

Each parser is intentionally tolerant: malformed files yield an empty result
rather than raising. The goal is to extract *enough* signal to power the
graph, not to reproduce the full semantics of each ecosystem.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

try:  # Python 3.11+
    import tomllib as _tomllib
except ImportError:  # pragma: no cover - 3.10 fallback
    _tomllib = None  # type: ignore[assignment]


@dataclass(frozen=True)
class Dependency:
    """A single dependency observed in a manifest."""

    ecosystem: str   # "pypi", "npm", "go", "cargo"
    name: str        # canonical package identifier
    source: str      # manifest file path (relative to repo root)


# -- name extraction -----------------------------------------------------

_PEP508_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.\-]*)")


def _pep508_name(spec: str) -> str | None:
    """Extract the package name from a PEP 508 / requirements.txt line."""
    if not spec:
        return None
    line = spec.split("#", 1)[0].strip()
    if not line or line.startswith("-"):
        return None
    m = _PEP508_NAME.match(line)
    if not m:
        return None
    return m.group(1).lower()


def _go_module_path(line: str) -> str | None:
    """Extract a module path from a single ``require`` line in ``go.mod``."""
    line = line.split("//", 1)[0].strip()
    if not line:
        return None
    parts = line.split()
    if not parts:
        return None
    candidate = parts[0]
    # Skip stanza keywords.
    if candidate in {"require", "(", ")", "module", "go", "toolchain", "replace", "exclude"}:
        return None
    return candidate


# -- per-ecosystem parsers -----------------------------------------------

def parse_pyproject(path: Path) -> list[Dependency]:
    if _tomllib is None:
        return []
    try:
        data = _tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    deps: list[Dependency] = []
    project = data.get("project") or {}
    rel = path.name
    for spec in project.get("dependencies") or []:
        if not isinstance(spec, str):
            continue
        name = _pep508_name(spec)
        if name:
            deps.append(Dependency("pypi", name, rel))
    optional = project.get("optional-dependencies") or {}
    if isinstance(optional, dict):
        for group in optional.values():
            if not isinstance(group, list):
                continue
            for spec in group:
                if not isinstance(spec, str):
                    continue
                name = _pep508_name(spec)
                if name:
                    deps.append(Dependency("pypi", name, rel))
    return deps


def parse_requirements_txt(path: Path) -> list[Dependency]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    deps: list[Dependency] = []
    rel = path.name
    for line in text.splitlines():
        name = _pep508_name(line)
        if name:
            deps.append(Dependency("pypi", name, rel))
    return deps


def parse_package_json(path: Path) -> list[Dependency]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    deps: list[Dependency] = []
    rel = path.name
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        section = data.get(key)
        if not isinstance(section, dict):
            continue
        for name in section.keys():
            if isinstance(name, str) and name.strip():
                deps.append(Dependency("npm", name.strip(), rel))
    return deps


def parse_go_mod(path: Path) -> list[Dependency]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    deps: list[Dependency] = []
    rel = path.name
    in_block = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("require ("):
            in_block = True
            continue
        if in_block:
            if stripped.startswith(")"):
                in_block = False
                continue
            mod = _go_module_path(stripped)
            if mod:
                deps.append(Dependency("go", mod, rel))
            continue
        if stripped.startswith("require "):
            mod = _go_module_path(stripped[len("require "):])
            if mod:
                deps.append(Dependency("go", mod, rel))
    return deps


def parse_cargo_toml(path: Path) -> list[Dependency]:
    if _tomllib is None:
        return []
    try:
        data = _tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    deps: list[Dependency] = []
    rel = path.name
    for key in ("dependencies", "dev-dependencies", "build-dependencies"):
        section = data.get(key)
        if not isinstance(section, dict):
            continue
        for name in section.keys():
            if isinstance(name, str) and name.strip():
                deps.append(Dependency("cargo", name.strip(), rel))
    return deps


# -- orchestration -------------------------------------------------------

# Keep the search shallow: top-level + one nested level, so monorepos with
# packages/* still get picked up but we don't recurse into node_modules etc.
_SKIP_DIRS = {".git", "node_modules", "vendor", "target", "dist", "build", ".venv", "venv", "__pycache__"}

_MANIFEST_PARSERS = (
    ("pyproject.toml", parse_pyproject),
    ("requirements.txt", parse_requirements_txt),
    ("package.json", parse_package_json),
    ("go.mod", parse_go_mod),
    ("Cargo.toml", parse_cargo_toml),
)


def discover_dependencies(root: Path, *, max_depth: int = 2) -> list[Dependency]:
    """Walk *root* up to ``max_depth`` levels deep, collecting dependencies."""
    if not root.exists() or not root.is_dir():
        return []
    found: list[Dependency] = []
    for path, depth in _walk(root, max_depth):
        for filename, parser in _MANIFEST_PARSERS:
            candidate = path / filename
            if candidate.is_file():
                found.extend(parser(candidate))
        _ = depth  # currently unused beyond the walk filter
    # Stable de-duplication across (ecosystem, name, source).
    seen: set[tuple[str, str, str]] = set()
    unique: list[Dependency] = []
    for dep in found:
        key = (dep.ecosystem, dep.name, dep.source)
        if key in seen:
            continue
        seen.add(key)
        unique.append(dep)
    return unique


def _walk(root: Path, max_depth: int):
    """Yield ``(directory, depth)`` for *root* and its sub-directories."""
    yield root, 0
    if max_depth <= 0:
        return
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        if depth >= max_depth:
            continue
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            if entry.name.startswith(".") and entry.name != ".":
                continue
            if entry.name in _SKIP_DIRS:
                continue
            yield entry, depth + 1
            stack.append((entry, depth + 1))
