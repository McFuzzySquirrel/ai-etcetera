"""Phase 3 skill: deterministic local ``concept-extractor``.

This first cut stays fully local and explainable: it scans each repo's README,
selected docs, and lightweight metadata files, extracts repeated noun-ish
phrases, normalises them into stable concept ids, and records ``Concept``
nodes plus ``MENTIONS`` edges with evidence.

Embeddings are intentionally deferred to a later iteration so this skill stays
offline-safe and testable.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

try:  # Python 3.11+
    import tomllib as _tomllib
except ImportError:  # pragma: no cover - 3.10 fallback
    _tomllib = None  # type: ignore[assignment]

from dirk.skills import SkillContext, SkillResult
from dirk.storage import Edge, Node


_MAX_CONCEPTS_PER_REPO = 8
_MIN_SCORE = 3.0
_MAX_DOC_DEPTH = 3
_MAX_TEXT_BYTES = 50_000
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+_.-]*")
_PHRASE_STOPWORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "how", "in", "into", "of", "on",
    "or", "the", "to", "with",
}
_GENERIC_CONCEPTS = {
    "api", "app", "application", "apps", "cli", "code", "config", "configuration", "data",
    "demo", "dependency", "dependencies", "docs", "documentation", "library", "local", "project",
    "python", "repo", "repository", "script", "scripts", "service", "services", "system", "tool",
    "tools", "workflow", "workflows",
}
_EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", "target", "vendor", "__pycache__"}
_MANIFEST_NAMES = ("pyproject.toml", "package.json")


@dataclass(frozen=True)
class _Candidate:
    text: str
    source: str
    score: float


@dataclass(frozen=True)
class _ConceptMention:
    slug: str
    label: str
    sources: tuple[str, ...]
    score: float


@dataclass
class ConceptExtractor:
    name: str = "concept_extractor"

    def run(self, ctx: SkillContext) -> SkillResult:
        before_nodes = ctx.store.nodes_added
        before_edges = ctx.store.edges_added

        scanned = 0
        with ctx.store.transaction():
            for source in ctx.repos:
                if source.path is None:
                    continue
                mentions = _extract_repo_concepts(source.path)
                if not mentions:
                    continue
                scanned += 1
                repo_id = f"repo:{source.slug}"
                for mention in mentions:
                    concept_id = f"concept:{mention.slug}"
                    ctx.store.upsert_node(Node(
                        id=concept_id,
                        kind="Concept",
                        name=mention.label,
                        properties={
                            "slug": mention.slug,
                            "aliases": [mention.label],
                        },
                    ))
                    evidence = [
                        {"ref": ref, "note": f"concept mention via {ref}"}
                        for ref in mention.sources
                    ]
                    ctx.store.upsert_edge(Edge(
                        src=repo_id,
                        dst=concept_id,
                        kind="MENTIONS",
                        confidence=min(0.95, 0.45 + (mention.score / 12.0)),
                        evidence=evidence,
                        discovered_by=self.name,
                    ))

        notes = (
            f"extracted concepts from {scanned} repo(s)"
            if scanned else
            "no local checkouts in scope; nothing to extract"
        )
        return SkillResult(
            skill=self.name,
            nodes_added=ctx.store.nodes_added - before_nodes,
            edges_added=ctx.store.edges_added - before_edges,
            notes=notes,
        )


def _extract_repo_concepts(root: Path) -> list[_ConceptMention]:
    candidates = _collect_candidates(root)
    if not candidates:
        return []

    bucketed: dict[str, dict[str, object]] = {}
    for candidate in candidates:
        slug = _slugify(candidate.text)
        if not _is_viable_concept_slug(slug):
            continue
        entry = bucketed.setdefault(slug, {
            "label": _display_label(candidate.text),
            "score": 0.0,
            "sources": set(),
        })
        entry["score"] = float(entry["score"]) + candidate.score
        cast_sources = entry["sources"]
        assert isinstance(cast_sources, set)
        cast_sources.add(candidate.source)

    mentions: list[_ConceptMention] = []
    for slug, data in bucketed.items():
        score = float(data["score"])
        sources = tuple(sorted(str(s) for s in data["sources"]))
        if score < _MIN_SCORE or not sources:
            continue
        mentions.append(_ConceptMention(
            slug=slug,
            label=str(data["label"]),
            sources=sources,
            score=score + max(0.0, len(sources) - 1),
        ))

    mentions.sort(key=lambda item: (-item.score, item.label))
    return mentions[:_MAX_CONCEPTS_PER_REPO]


def _collect_candidates(root: Path) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    candidates.extend(_readme_candidates(root))
    candidates.extend(_docs_heading_candidates(root))
    candidates.extend(_manifest_candidates(root))
    return candidates


def _readme_candidates(root: Path) -> list[_Candidate]:
    for name in ("README.md", "README.rst", "README.txt", "readme.md"):
        path = root / name
        if not path.is_file():
            continue
        text = _safe_read_text(path)
        if not text:
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        limited = "\n".join(lines[:16])
        return _phrase_candidates(limited, source=path.name, base_weight=1.8)
    return []


def _docs_heading_candidates(root: Path) -> list[_Candidate]:
    docs_dir = root / "docs"
    if not docs_dir.is_dir():
        return []
    candidates: list[_Candidate] = []
    for path in _walk_docs_files(docs_dir, max_depth=_MAX_DOC_DEPTH):
        text = _safe_read_text(path)
        if not text:
            continue
        rel = path.relative_to(root).as_posix()
        for line in text.splitlines()[:80]:
            stripped = line.strip()
            if not stripped:
                continue
            heading = _markdown_heading_text(stripped)
            if heading is None:
                continue
            candidates.extend(_phrase_candidates(heading, source=rel, base_weight=1.4))
    return candidates


def _manifest_candidates(root: Path) -> list[_Candidate]:
    candidates: list[_Candidate] = []

    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and _tomllib is not None:
        try:
            data = _tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        project = data.get("project") if isinstance(data, dict) else {}
        if isinstance(project, dict):
            description = project.get("description")
            if isinstance(description, str) and description.strip():
                candidates.extend(_phrase_candidates(description, source="pyproject.toml", base_weight=1.2))

    package_json = root / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            description = data.get("description")
            if isinstance(description, str) and description.strip():
                candidates.extend(_phrase_candidates(description, source="package.json", base_weight=1.2))

    return candidates


def _phrase_candidates(text: str, *, source: str, base_weight: float) -> list[_Candidate]:
    tokens = _TOKEN_RE.findall(text)
    if not tokens:
        return []

    lowered = [token.lower() for token in tokens]
    candidates: list[_Candidate] = []
    counts: Counter[str] = Counter()

    max_len = min(3, len(lowered))
    for size in range(1, max_len + 1):
        for idx in range(len(lowered) - size + 1):
            window = lowered[idx: idx + size]
            if any(token in _PHRASE_STOPWORDS for token in window):
                continue
            phrase = " ".join(window)
            if not _is_phrase_candidate(phrase):
                continue
            counts[phrase] += 1

    for phrase, repeats in counts.items():
        score = base_weight * repeats
        if repeats > 1:
            score += 0.5
        candidates.append(_Candidate(text=phrase, source=source, score=score))
    return candidates


def _markdown_heading_text(line: str) -> str | None:
    if line.startswith("#"):
        return line.lstrip("#").strip()
    if line.endswith(":") and len(line) < 80:
        return line[:-1].strip()
    return None


def _walk_docs_files(root: Path, *, max_depth: int):
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if depth >= max_depth or entry.name in _EXCLUDED_DIRS or entry.name.startswith("."):
                    continue
                stack.append((entry, depth + 1))
            elif entry.is_file() and entry.suffix.lower() in {".md", ".rst", ".txt"}:
                yield entry


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:_MAX_TEXT_BYTES]
    except OSError:
        return ""


def _display_label(text: str) -> str:
    return " ".join(part.capitalize() for part in _slugify(text).split("-") if part)


def _slugify(text: str) -> str:
    lowered = text.lower().replace("_", " ").replace("-", " ")
    parts = [part for part in _TOKEN_RE.findall(lowered) if part and part not in _PHRASE_STOPWORDS]
    return "-".join(parts)


def _is_phrase_candidate(phrase: str) -> bool:
    if not phrase or phrase in _GENERIC_CONCEPTS:
        return False
    words = phrase.split()
    if len(words) == 1:
        word = words[0]
        if len(word) < 4 or word.isdigit():
            return False
        if word in _GENERIC_CONCEPTS:
            return False
    else:
        if len(words) > 3:
            return False
        if all(word in _GENERIC_CONCEPTS for word in words):
            return False
    return True


def _is_viable_concept_slug(slug: str) -> bool:
    if not slug:
        return False
    if slug in _GENERIC_CONCEPTS:
        return False
    parts = slug.split("-")
    if any(len(part) < 3 for part in parts):
        return False
    if all(part.isdigit() for part in parts):
        return False
    if any(part in _GENERIC_CONCEPTS for part in parts) and len(parts) == 1:
        return False
    return True
