"""Skill framework for Dirk.

A *skill* is a small unit of "noticing": it inspects some slice of the world
and writes nodes/edges into the knowledge graph. Skills are intentionally
narrow so they can be composed and reasoned about individually.

Every skill produces edges that carry an **evidence trail** — the source
references that justify the connection — so the agent can show *why* it
believes two things are linked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from dirk.config import Config, RepoSource
from dirk.storage import GraphStore


@dataclass
class SkillContext:
    """Everything a skill needs to do its job."""
    config: Config
    store: GraphStore
    repos: list["RepoSource"]


@dataclass
class SkillResult:
    skill: str
    nodes_added: int
    edges_added: int
    notes: str = ""


class Skill(Protocol):
    name: str

    def run(self, ctx: SkillContext) -> SkillResult:  # pragma: no cover - protocol
        ...


# -- registry ------------------------------------------------------------

from dirk.skills.repo_inventory import RepoInventory
from dirk.skills.dependency_mapper import DependencyMapper
from dirk.skills.interface_extractor import InterfaceExtractor
from dirk.skills.concept_extractor import ConceptExtractor
from dirk.skills.semantic_linker import SemanticLinker
from dirk.skills.connection_curator import ConnectionCurator


SKILL_REGISTRY: dict[str, type] = {
    "repo_inventory": RepoInventory,
    "dependency_mapper": DependencyMapper,
    "interface_extractor": InterfaceExtractor,
    "concept_extractor": ConceptExtractor,
    "semantic_linker": SemanticLinker,
    "connection_curator": ConnectionCurator,
}


# Order matters: each phase builds on the previous one.
SKILL_ORDER: list[str] = [
    "repo_inventory",
    "dependency_mapper",
    "interface_extractor",
    "concept_extractor",
    "semantic_linker",
    "connection_curator",
]


__all__ = [
    "Skill",
    "SkillContext",
    "SkillResult",
    "RepoSource",
    "SKILL_REGISTRY",
    "SKILL_ORDER",
]
