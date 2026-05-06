"""Phase 3 skill: ``origin-tracer``.

Surfaces the conceptual origin and learning lineage behind each repository:

* **Motivation** — *why* the repo was built. Scans README files for
  ``## Why``, ``## Motivation``, ``## Background`` (and similar) headings and
  intro text, creating a ``Motivation`` node and a ``MOTIVATED_BY`` edge for
  each repo that has a discernible origin story.

* **Lineage** — *how* repos evolved from or were inspired by each other.
  Scans for lineage keywords (``evolved from``, ``inspired by``, etc.) that
  appear near cross-references to other repos in scope (slug mentions or
  GitHub URLs), emitting ``EVOLVED_FROM`` edges for direct ancestry and
  ``INSPIRED_BY`` edges for looser inspirational connections.

This skill is fully local-first and offline-safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from dirk.skills import SkillContext, SkillResult
from dirk.storage import Edge, Node


_MAX_TEXT_BYTES = 50_000
_MAX_MOTIVATION_CHARS = 400
_CONTEXT_WINDOW = 250  # chars to search on each side of a repo mention
_EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}

# Markdown heading that signals a "why this repo exists" section.
_WHY_HEADING_RE = re.compile(
    r"^#{1,4}\s*(?:why|motivation|background|origin|genesis|goal|purpose|"
    r"what\s+(?:is\s+this|and\s+why)|about|rationale)\s*$",
    re.IGNORECASE,
)

# Direct lineage patterns → EVOLVED_FROM (higher confidence).
_EVOLVED_RE = re.compile(
    r"\b(?:evolved?\s+from|born?\s+from|grew?\s+out\s+of|forked?\s+from|"
    r"derived?\s+from|continuation\s+of|successor\s+to|supersedes?|replaces?|"
    r"rewrite\s+of|rebuilt?\s+(?:from|as)|started\s+(?:from|as))\b",
    re.IGNORECASE,
)

# Inspirational lineage patterns → INSPIRED_BY (lower confidence).
_INSPIRED_RE = re.compile(
    r"\b(?:inspired?\s+by|influenced?\s+by|motivated?\s+by|learned?\s+from|"
    r"builds?\s+on|based?\s+on|grew?\s+from|following\s+(?:the\s+)?(?:ideas?|pattern)\s+"
    r"(?:of|from))\b",
    re.IGNORECASE,
)

# GitHub URL slug capture (e.g. github.com/owner/name).
_GITHUB_URL_RE = re.compile(
    r"github\.com/([A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*)",
    re.IGNORECASE,
)


@dataclass
class OriginTracer:
    name: str = "origin_tracer"

    def run(self, ctx: SkillContext) -> SkillResult:
        before_nodes = ctx.store.nodes_added
        before_edges = ctx.store.edges_added

        # Build lookup tables for cross-reference detection.
        all_slugs = {s.slug for s in ctx.repos}
        short_to_slug: dict[str, str] = {}
        for s in ctx.repos:
            short = s.name.lower().replace("_", "-")
            short_to_slug.setdefault(short, s.slug)

        slug_pattern = _build_slug_pattern(all_slugs, short_to_slug)

        scanned_motivation = 0
        scanned_lineage = 0

        with ctx.store.transaction():
            for source in ctx.repos:
                if source.path is None or not source.path.is_dir():
                    continue

                texts = list(_read_source_texts(source.path))
                if not texts:
                    continue

                repo_id = f"repo:{source.slug}"

                # 1. Motivation extraction
                motivation = _extract_motivation(texts)
                if motivation:
                    mot_id = f"motivation:{source.slug}"
                    ctx.store.upsert_node(Node(
                        id=mot_id,
                        kind="Motivation",
                        name=f"{source.name} — why",
                        properties={
                            "text": motivation["text"],
                            "source": motivation["source"],
                            "repo": source.slug,
                        },
                    ))
                    ctx.store.upsert_edge(Edge(
                        src=repo_id,
                        dst=mot_id,
                        kind="MOTIVATED_BY",
                        confidence=motivation["confidence"],
                        evidence=[{
                            "ref": motivation["source"],
                            "note": f"motivation extracted from {motivation['source']}",
                        }],
                        discovered_by=self.name,
                    ))
                    scanned_motivation += 1

                # 2. Lineage detection across repos in scope
                if slug_pattern is None:
                    continue

                full_text = "\n".join(text for _, text in texts)
                for other_slug, edge_kind, confidence, context_note in _find_lineage(
                    full_text, source.slug, all_slugs, short_to_slug, slug_pattern
                ):
                    ctx.store.upsert_edge(Edge(
                        src=repo_id,
                        dst=f"repo:{other_slug}",
                        kind=edge_kind,
                        confidence=confidence,
                        evidence=[{"ref": "README/docs", "note": context_note}],
                        discovered_by=self.name,
                    ))
                    scanned_lineage += 1

        notes_parts: list[str] = []
        if scanned_motivation:
            notes_parts.append(f"extracted motivation from {scanned_motivation} repo(s)")
        if scanned_lineage:
            notes_parts.append(f"found {scanned_lineage} lineage signal(s)")
        if not notes_parts:
            notes_parts.append("no motivation or lineage signals found in local checkouts")

        return SkillResult(
            skill=self.name,
            nodes_added=ctx.store.nodes_added - before_nodes,
            edges_added=ctx.store.edges_added - before_edges,
            notes="; ".join(notes_parts),
        )


# -- helpers -----------------------------------------------------------------


def _build_slug_pattern(
    all_slugs: set[str], short_to_slug: dict[str, str]
) -> re.Pattern[str] | None:
    """Build a compiled regex that matches any known repo reference."""
    options: set[str] = set()
    for slug in all_slugs:
        # Full slug: "McFuzzySquirrel/agent-forge-local"
        options.add(re.escape(slug))
        # Short name: "agent-forge-local"
        short = slug.partition("/")[2].lower().replace("_", "-")
        if short:
            options.add(re.escape(short))
    for short in short_to_slug:
        options.add(re.escape(short))
    if not options:
        return None
    return re.compile(
        r"(?i)\b(" + "|".join(sorted(options, key=len, reverse=True)) + r")\b"
    )


def _read_source_texts(root: Path) -> Iterator[tuple[str, str]]:
    """Yield (relative_path_str, text) for README and docs text files."""
    for name in ("README.md", "README.rst", "README.txt", "readme.md"):
        p = root / name
        if p.is_file():
            text = _safe_read(p)
            if text:
                yield name, text
            break

    docs = root / "docs"
    if docs.is_dir():
        for path in _walk_text_files(docs):
            text = _safe_read(path)
            if text:
                yield path.relative_to(root).as_posix(), text


def _walk_text_files(root: Path, max_depth: int = 3) -> Iterator[Path]:
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if (
                    depth < max_depth
                    and entry.name not in _EXCLUDED_DIRS
                    and not entry.name.startswith(".")
                ):
                    stack.append((entry, depth + 1))
            elif entry.is_file() and entry.suffix.lower() in {".md", ".rst", ".txt"}:
                yield entry


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:_MAX_TEXT_BYTES]
    except OSError:
        return ""


def _extract_motivation(texts: list[tuple[str, str]]) -> dict | None:
    """
    Return a dict with ``text``, ``source``, ``confidence``, or ``None``.

    Strategy (in order of preference):
    1. Explicit ``## Why / Motivation / Background`` heading section.
    2. First substantial paragraph after the H1 title in the README.
    """
    for rel_path, text in texts:
        result = _scan_for_why_section(text, rel_path)
        if result:
            return result

    for rel_path, text in texts:
        if rel_path.lower().startswith("readme"):
            result = _extract_intro_paragraph(text, rel_path)
            if result:
                return result

    return None


def _scan_for_why_section(text: str, source: str) -> dict | None:
    """Find a ``Why / Motivation`` heading and extract the following paragraph."""
    lines = text.splitlines()
    in_section = False
    section_lines: list[str] = []
    section_level = 0

    for line in lines:
        stripped = line.strip()
        if not in_section:
            if _WHY_HEADING_RE.match(stripped):
                in_section = True
                section_level = len(stripped) - len(stripped.lstrip("#"))
        else:
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                if level <= section_level:
                    break
            if stripped:
                section_lines.append(stripped)
            if len(section_lines) >= 8:
                break

    if not section_lines:
        return None

    snippet = " ".join(section_lines)[:_MAX_MOTIVATION_CHARS]
    if len(snippet) < 30:
        return None

    return {"text": snippet, "source": source, "confidence": 0.85}


def _extract_intro_paragraph(text: str, source: str) -> dict | None:
    """Extract the first substantial paragraph after the H1 heading."""
    lines = text.splitlines()
    past_title = False
    para_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not past_title:
            if stripped.startswith("# "):
                past_title = True
            continue
        # Skip badges and purely empty lines before content starts.
        if not stripped or stripped.startswith("![") or stripped.startswith("[!["):
            if para_lines:
                break
            continue
        # Stop at a sub-heading.
        if stripped.startswith("#"):
            if para_lines:
                break
            continue
        para_lines.append(stripped)
        if len(para_lines) >= 5:
            break

    if not para_lines:
        return None

    snippet = " ".join(para_lines)[:_MAX_MOTIVATION_CHARS]
    if len(snippet) < 30:
        return None

    return {"text": snippet, "source": source, "confidence": 0.55}


def _find_lineage(
    full_text: str,
    self_slug: str,
    all_slugs: set[str],
    short_to_slug: dict[str, str],
    slug_pattern: re.Pattern[str],
) -> list[tuple[str, str, float, str]]:
    """
    Scan text for lineage signals. Returns list of
    ``(other_slug, edge_kind, confidence, note)``.
    """
    results: list[tuple[str, str, float, str]] = []
    seen: set[tuple[str, str]] = set()

    for match in slug_pattern.finditer(full_text):
        matched_text = match.group(0).lower().replace("_", "-")
        other_slug = _resolve_slug(matched_text, all_slugs, short_to_slug)
        if other_slug is None or other_slug == self_slug:
            continue

        start = max(0, match.start() - _CONTEXT_WINDOW)
        end = min(len(full_text), match.end() + _CONTEXT_WINDOW)
        context = full_text[start:end]

        if _EVOLVED_RE.search(context):
            key = (other_slug, "EVOLVED_FROM")
            if key not in seen:
                seen.add(key)
                snippet = _excerpt(context, 120)
                results.append((other_slug, "EVOLVED_FROM", 0.75,
                                f"lineage signal near '{matched_text}': {snippet}"))
        elif _INSPIRED_RE.search(context):
            key = (other_slug, "INSPIRED_BY")
            if key not in seen:
                seen.add(key)
                snippet = _excerpt(context, 120)
                results.append((other_slug, "INSPIRED_BY", 0.55,
                                f"inspiration signal near '{matched_text}': {snippet}"))

    return results


def _resolve_slug(
    matched: str, all_slugs: set[str], short_to_slug: dict[str, str]
) -> str | None:
    """Turn a matched string into a canonical slug, or ``None``."""
    lower = matched.lower()
    for slug in all_slugs:
        if slug.lower() == lower or slug.lower().replace("_", "-") == lower:
            return slug
        short = slug.partition("/")[2].lower().replace("_", "-")
        if short == lower:
            return slug
    return short_to_slug.get(lower)


def _excerpt(text: str, max_len: int) -> str:
    t = " ".join(text.split())
    return (t[:max_len] + "…") if len(t) > max_len else t
