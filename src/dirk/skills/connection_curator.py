"""Phase 4 skill: ``connection-curator``.

Takes the raw edges accumulated by the other skills, ranks them by
``confidence`` and recency, and writes ``COULD_COMPOSE_WITH`` edges where
two repos look complementary (e.g. one exposes an interface the other
consumes, or one's domain is a subset of the other's).

Curation is the moment Dirk turns "edges in a graph" into "things a human
might want to know". Today the skill writes `COULD_COMPOSE_WITH` edges with
heuristic evidence and can optionally ask a local Ollama model to accept,
reject, or strengthen candidate pairs.

Today it combines two conservative heuristics:

* Repo pairs that already share **two or more direct edge kinds** (e.g.
  both ``MENTIONS`` and ``EXPOSES``).
* Repo pairs that share **two or more common neighbors** of kind
  ``Technology`` or ``Interface`` (i.e. they depend on the same libraries
  or expose the same kind of surface).

The richer Phase 4 workflow is still incomplete, but the current
implementation is already useful: heuristic-first, local-model assisted when
configured, and resilient to model unavailability via fallback.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from dirk.ollama import OllamaClient
from dirk.skills import SkillContext, SkillResult
from dirk.storage import Edge


_SHARED_NEIGHBOR_KINDS = {"Technology", "Interface"}
_SELF_KIND = "COULD_COMPOSE_WITH"


@dataclass
class ConnectionCurator:
    name: str = "connection_curator"

    def run(self, ctx: SkillContext) -> SkillResult:
        before_nodes = ctx.store.nodes_added
        before_edges = ctx.store.edges_added

        # Index everything we'll need in a single pass over edges.
        repo_edge_kinds: dict[tuple[str, str], set[str]] = defaultdict(set)
        # For each non-repo neighbor, which repos point at it (and how).
        neighbor_to_repos: dict[str, set[str]] = defaultdict(set)
        neighbor_kind: dict[str, str] = {}

        for node in ctx.store.iter_nodes():
            if node.kind in _SHARED_NEIGHBOR_KINDS:
                neighbor_kind[node.id] = node.kind

        for edge in ctx.store.iter_edges():
            if edge["kind"] == _SELF_KIND:
                continue
            src, dst = edge["src"], edge["dst"]
            if src.startswith("repo:") and dst.startswith("repo:"):
                a, b = sorted([src, dst])
                repo_edge_kinds[(a, b)].add(edge["kind"])
            elif src.startswith("repo:") and dst in neighbor_kind:
                neighbor_to_repos[dst].add(src)
            elif dst.startswith("repo:") and src in neighbor_kind:
                neighbor_to_repos[src].add(dst)

        # Tally shared neighbors per repo pair.
        shared_neighbors: dict[tuple[str, str], list[str]] = defaultdict(list)
        for neighbor, repos in neighbor_to_repos.items():
            if len(repos) < 2:
                continue
            ordered = sorted(repos)
            for i, a in enumerate(ordered):
                for b in ordered[i + 1:]:
                    shared_neighbors[(a, b)].append(neighbor)

        all_pairs = set(repo_edge_kinds) | set(shared_neighbors)

        candidates: list[tuple[tuple[str, str], set[str], list[str], float]] = []
        for pair in all_pairs:
            kinds = repo_edge_kinds.get(pair, set())
            neighbors = shared_neighbors.get(pair, [])

            kind_signal = len(kinds) >= 2
            neighbor_signal = len(neighbors) >= 2
            if not (kind_signal or neighbor_signal):
                continue

            score = 0.4 + 0.1 * len(kinds) + 0.05 * len(neighbors)
            heuristic_conf = min(score, 0.9)
            candidates.append((pair, kinds, neighbors, heuristic_conf))

        candidates.sort(key=lambda item: (-item[3], item[0][0], item[0][1]))
        candidates = candidates[: ctx.config.curation.max_candidates]

        notes: list[str] = []
        llm_client: OllamaClient | None = None
        use_llm = ctx.config.curation.provider == "ollama"
        if use_llm:
            llm_client = OllamaClient(
                base_url=ctx.config.curation.base_url,
                model=ctx.config.curation.model,
                timeout_sec=ctx.config.curation.timeout_sec,
            )
            ok, reason = llm_client.health()
            if not ok:
                if ctx.config.curation.fallback == "fail":
                    raise RuntimeError(f"Ollama curation unavailable: {reason}")
                notes.append(f"ollama unavailable ({reason}); used heuristic fallback")
                llm_client = None
            else:
                notes.append(f"ollama curation enabled ({ctx.config.curation.model})")

        with ctx.store.transaction():
            written = 0
            for pair, kinds, neighbors, heuristic_conf in candidates:
                if written >= ctx.config.curation.max_suggestions:
                    break

                confidence = heuristic_conf

                evidence: list[dict[str, str]] = []
                if kinds:
                    evidence.append({
                        "ref": ",".join(sorted(kinds)),
                        "note": "shared edge kinds: " + ", ".join(sorted(kinds)),
                    })
                if neighbors:
                    sample = sorted(neighbors)[:5]
                    evidence.append({
                        "ref": ",".join(sample),
                        "note": (
                            f"shared neighbors ({len(neighbors)}): "
                            + ", ".join(_short(n) for n in sample)
                            + (" …" if len(neighbors) > len(sample) else "")
                        ),
                    })

                accepted = True
                if llm_client is not None:
                    repo_a = pair[0].replace("repo:", "", 1)
                    repo_b = pair[1].replace("repo:", "", 1)
                    llm_signals: dict[str, Any] = {
                        "shared_edge_kinds": sorted(kinds),
                        "shared_neighbor_count": len(neighbors),
                        "shared_neighbors_sample": sorted(neighbors)[:6],
                        "heuristic_confidence": heuristic_conf,
                    }
                    try:
                        suggestion = llm_client.curate_pair(
                            repo_a=repo_a,
                            repo_b=repo_b,
                            signals=llm_signals,
                        )
                    except Exception as exc:  # pragma: no cover - network/runtime guard
                        if ctx.config.curation.fallback == "fail":
                            raise RuntimeError(f"ollama curation request failed: {exc}") from exc
                        notes.append(f"ollama request failed ({exc}); switched to heuristic fallback")
                        llm_client = None
                        suggestion = None
                    if suggestion is None:
                        if ctx.config.curation.fallback == "fail":
                            raise RuntimeError("ollama returned invalid curation response")
                        accepted = True
                    else:
                        accepted = suggestion.accept and suggestion.confidence >= ctx.config.connection_threshold
                        confidence = max(heuristic_conf, suggestion.confidence)
                        if suggestion.supporting_signals:
                            evidence.append({
                                "ref": f"ollama:{ctx.config.curation.model}",
                                "note": "llm signals: " + "; ".join(suggestion.supporting_signals[:5]),
                            })
                        if suggestion.rationale:
                            evidence.append({
                                "ref": f"ollama:{ctx.config.curation.model}",
                                "note": "rationale: " + suggestion.rationale,
                            })

                if not accepted:
                    continue

                a, b = pair
                ctx.store.upsert_edge(Edge(
                    src=a,
                    dst=b,
                    kind=_SELF_KIND,
                    confidence=confidence,
                    evidence=evidence,
                    discovered_by=self.name,
                ))
                written += 1

        return SkillResult(
            skill=self.name,
            nodes_added=ctx.store.nodes_added - before_nodes,
            edges_added=ctx.store.edges_added - before_edges,
            notes="; ".join(notes) if notes else "heuristic curation (shared edge kinds + shared neighbors)",
        )


def _short(node_id: str) -> str:
    """Trim a node id to its trailing identifier for human-friendly evidence."""
    return node_id.rsplit(":", 1)[-1]
