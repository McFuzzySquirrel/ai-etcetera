"""Phase 2 skill stub: ``interface-extractor``.

Will surface the **public surface area** of each repository so that other
skills (curator especially) can spot repos that "could plug into each other":

* HTTP routes (Express / FastAPI / Flask / Spring / ASP.NET / Rails).
* CLI commands (Click / argparse / Cobra / commander).
* Exported functions / classes / types from index modules.
* Schema / IDL files (``*.proto``, ``*.graphql``, ``*.openapi.yaml``).
* Event names emitted to message buses.

Currently a no-op that exists so the pipeline shape is honest about what's
implemented vs. what's planned.
"""

from __future__ import annotations

from dataclasses import dataclass

from dirk.skills import SkillContext, SkillResult


@dataclass
class InterfaceExtractor:
    name: str = "interface_extractor"

    def run(self, ctx: SkillContext) -> SkillResult:
        return SkillResult(
            skill=self.name,
            nodes_added=0,
            edges_added=0,
            notes="not yet implemented (Phase 2)",
        )
