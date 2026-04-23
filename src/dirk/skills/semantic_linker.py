"""Phase 3 skill stub: ``semantic-linker``.

Will use the embeddings produced by ``concept-extractor`` (plus an optional
LLM pass) to propose ``SIMILAR_TO`` edges between repos that share *purpose*
or *shape* without sharing any explicit dependency. This is where Dirk earns
his name.

The ``serendipity`` config knob will scale how willing this skill is to
propose loose connections.

Currently a no-op placeholder.
"""

from __future__ import annotations

from dataclasses import dataclass

from dirk.skills import SkillContext, SkillResult


@dataclass
class SemanticLinker:
    name: str = "semantic_linker"

    def run(self, ctx: SkillContext) -> SkillResult:
        return SkillResult(
            skill=self.name,
            nodes_added=0,
            edges_added=0,
            notes="not yet implemented (Phase 3)",
        )
