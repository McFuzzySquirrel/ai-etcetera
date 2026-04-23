"""Configuration loading for Dirk.

Dirk reads two files:

* ``dirk.config.yml`` — behavioural settings (depth, thresholds, output dirs).
* ``repos.yml`` — the hand-maintained list of repositories in scope.

Both are optional in the sense that the loader will fall back to sane defaults
if the files are missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RepoSource:
    """A repository in scope, optionally with a local checkout to scan.

    ``slug`` is the canonical ``owner/name`` identifier (used for node ids and
    GitHub lookups). ``path`` — when provided — points at a local checkout
    that file-reading skills (``dependency_mapper``, ``interface_extractor``)
    can inspect directly. When ``path`` is ``None``, those skills will simply
    skip the repo.
    """

    slug: str
    path: Path | None = None

    @property
    def owner(self) -> str:
        return self.slug.partition("/")[0]

    @property
    def name(self) -> str:
        return self.slug.partition("/")[2]


DEFAULT_CONFIG_PATH = "dirk.config.yml"
DEFAULT_REPOS_PATH = "repos.yml"


@dataclass
class ScopeConfig:
    source: str = DEFAULT_REPOS_PATH
    github_user: str | None = None
    github_org: str | None = None
    include_private: bool = False


@dataclass
class OutputConfig:
    graph_dir: str = "graph"
    findings_dir: str = "findings"


@dataclass
class ModelPreferences:
    embedding: str = "local"
    curation: str = "hosted"


@dataclass
class Config:
    scope: ScopeConfig = field(default_factory=ScopeConfig)
    depth: str = "standard"
    connection_threshold: float = 0.35
    serendipity: float = 0.5
    output: OutputConfig = field(default_factory=OutputConfig)
    model_preferences: ModelPreferences = field(default_factory=ModelPreferences)
    skills: dict[str, bool] = field(default_factory=lambda: {
        "repo_inventory": True,
        "dependency_mapper": True,
        "interface_extractor": True,
        "concept_extractor": True,
        "semantic_linker": True,
        "connection_curator": True,
    })
    cost_ceiling_usd: float | None = None
    root: Path = field(default_factory=Path.cwd)

    # ---- convenience -----------------------------------------------------

    @property
    def graph_dir(self) -> Path:
        return self.root / self.output.graph_dir

    @property
    def findings_dir(self) -> Path:
        return self.root / self.output.findings_dir

    @property
    def db_path(self) -> Path:
        return self.graph_dir / "graph.db"

    def is_skill_enabled(self, name: str) -> bool:
        return bool(self.skills.get(name, False))


def _coerce(data: dict[str, Any], root: Path) -> Config:
    scope_raw = data.get("scope") or {}
    output_raw = data.get("output") or {}
    models_raw = data.get("model_preferences") or {}
    skills_raw = data.get("skills") or {}

    cfg = Config(
        scope=ScopeConfig(
            source=scope_raw.get("source", DEFAULT_REPOS_PATH),
            github_user=scope_raw.get("github_user"),
            github_org=scope_raw.get("github_org"),
            include_private=bool(scope_raw.get("include_private", False)),
        ),
        depth=data.get("depth", "standard"),
        connection_threshold=float(data.get("connection_threshold", 0.35)),
        serendipity=float(data.get("serendipity", 0.5)),
        output=OutputConfig(
            graph_dir=output_raw.get("graph_dir", "graph"),
            findings_dir=output_raw.get("findings_dir", "findings"),
        ),
        model_preferences=ModelPreferences(
            embedding=models_raw.get("embedding", "local"),
            curation=models_raw.get("curation", "hosted"),
        ),
        skills={**Config().skills, **{k: bool(v) for k, v in skills_raw.items()}},
        cost_ceiling_usd=data.get("cost_ceiling_usd"),
        root=root,
    )
    if cfg.depth not in {"quick", "standard", "deep"}:
        raise ValueError(f"Invalid depth: {cfg.depth!r}")
    if not 0.0 <= cfg.connection_threshold <= 1.0:
        raise ValueError("connection_threshold must be in [0, 1]")
    if not 0.0 <= cfg.serendipity <= 1.0:
        raise ValueError("serendipity must be in [0, 1]")
    return cfg


def load_config(path: str | Path | None = None, root: str | Path | None = None) -> Config:
    """Load Dirk configuration. Missing file → defaults."""
    root_path = Path(root) if root else Path.cwd()
    cfg_path = Path(path) if path else root_path / DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        return Config(root=root_path)
    with cfg_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{cfg_path}: expected a mapping at the top level")
    return _coerce(data, root_path)


def load_repos(path: str | Path) -> list[RepoSource]:
    """Load repositories from ``repos.yml``.

    Supports two entry shapes:

    * ``"owner/name"`` — slug only, no local checkout.
    * ``{slug: "owner/name", path: "./checkouts/name"}`` — slug plus local path
      that file-scanning skills can read.

    Relative ``path`` values are resolved against the directory containing
    ``repos.yml``.
    """
    p = Path(path)
    if not p.exists():
        return []
    base = p.parent
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    repos = data.get("repos") if isinstance(data, dict) else None
    if not repos:
        return []
    cleaned: list[RepoSource] = []
    seen: set[str] = set()
    for entry in repos:
        slug: str | None = None
        local: Path | None = None
        if isinstance(entry, str):
            slug = entry.strip()
        elif isinstance(entry, dict):
            raw_slug = entry.get("slug") or entry.get("repo")
            if isinstance(raw_slug, str):
                slug = raw_slug.strip()
            raw_path = entry.get("path")
            if isinstance(raw_path, str) and raw_path.strip():
                candidate = Path(raw_path.strip())
                if not candidate.is_absolute():
                    candidate = (base / candidate).resolve()
                local = candidate
        if not slug or "/" not in slug:
            continue
        if slug in seen:
            continue
        seen.add(slug)
        cleaned.append(RepoSource(slug=slug, path=local))
    return cleaned
