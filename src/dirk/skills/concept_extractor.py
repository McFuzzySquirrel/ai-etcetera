"""Phase 3 skill stub: ``concept-extractor``.

Will pull domain concepts (and their embeddings) out of READMEs, docs,
comments, commit messages and issue titles, normalise them, and write
``Concept`` nodes plus ``MENTIONS`` edges from each repo to the concepts
it talks about.

Currently a no-op placeholder.
"""

from __future__ import annotations

from dataclasses import dataclass

from dirk.skills import SkillContext, SkillResult


@dataclass
class ConceptExtractor:
    name: str = "concept_extractor"

    def run(self, ctx: SkillContext) -> SkillResult:
        return SkillResult(
            skill=self.name,
            nodes_added=0,
            edges_added=0,
            notes="not yet implemented (Phase 3)",
        )
