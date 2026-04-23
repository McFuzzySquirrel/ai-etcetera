"""Command-line interface for Dirk.

::

    dirk init        # write default config + scope files
    dirk scan        # run the inventory + dependency-mapping skills
    dirk connect     # run linker + curator skills
    dirk report      # write findings + delta (no graph mutation)
    dirk run --all   # everything in one shot
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from dirk import __version__
from dirk.agent import DirkAgent
from dirk.config import DEFAULT_CONFIG_PATH, DEFAULT_REPOS_PATH, load_config


SCAN_SKILLS = ["repo_inventory", "dependency_mapper", "interface_extractor"]
CONNECT_SKILLS = ["concept_extractor", "semantic_linker", "connection_curator"]


@click.group()
@click.version_option(__version__, prog_name="dirk")
@click.option(
    "--config", "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help=f"Path to {DEFAULT_CONFIG_PATH} (default: cwd).",
)
@click.option(
    "--root",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Project root directory (default: cwd).",
)
@click.pass_context
def main(ctx: click.Context, config_path: Path | None, root: Path | None) -> None:
    """Dirk — a holistic research agent for repository collections."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(path=config_path, root=root)


@main.command()
@click.option("--force", is_flag=True, help="Overwrite existing files.")
@click.pass_context
def init(ctx: click.Context, force: bool) -> None:
    """Write default ``dirk.config.yml`` and ``repos.yml`` into the current directory."""
    cfg = ctx.obj["config"]
    root = cfg.root
    targets = {
        DEFAULT_CONFIG_PATH: _DEFAULT_CONFIG,
        DEFAULT_REPOS_PATH: _DEFAULT_REPOS,
    }
    for name, content in targets.items():
        path = root / name
        if path.exists() and not force:
            click.echo(f"skip {name} (already exists, pass --force to overwrite)")
            continue
        path.write_text(content, encoding="utf-8")
        click.echo(f"wrote {name}")


@main.command()
@click.pass_context
def scan(ctx: click.Context) -> None:
    """Inventory repos and map explicit dependencies."""
    _run_with(ctx, only=[s for s in SCAN_SKILLS if ctx.obj["config"].is_skill_enabled(s)])


@main.command()
@click.pass_context
def connect(ctx: click.Context) -> None:
    """Run the latent-connection and curation skills."""
    _run_with(ctx, only=[s for s in CONNECT_SKILLS if ctx.obj["config"].is_skill_enabled(s)])


@main.command()
@click.pass_context
def report(ctx: click.Context) -> None:
    """Re-render findings + delta from the existing graph (no skill execution)."""
    _run_with(ctx, only=[])


@main.command()
@click.option("--all", "all_skills", is_flag=True, help="Run every enabled skill in order.")
@click.option("--only", multiple=True, help="Run only these skill names.")
@click.pass_context
def run(ctx: click.Context, all_skills: bool, only: tuple[str, ...]) -> None:
    """Run skills, then write graph + findings."""
    if only:
        _run_with(ctx, only=list(only))
    elif all_skills:
        _run_with(ctx, only=None)  # use enabled set from config
    else:
        click.echo("Pass --all or --only <skill> ...", err=True)
        sys.exit(2)


# -- helpers --------------------------------------------------------------

def _run_with(ctx: click.Context, only: list[str] | None) -> None:
    agent = DirkAgent(ctx.obj["config"])
    summary = agent.run(only=only)
    click.echo("Dirk completed:")
    for r in summary.skill_results:
        notes = f" — {r.notes}" if r.notes else ""
        click.echo(f"  · {r.skill}: +{r.nodes_added} nodes, +{r.edges_added} edges{notes}")
    if summary.findings_path:
        click.echo(f"  findings: {summary.findings_path}")
    if summary.delta_path:
        click.echo(f"  delta:    {summary.delta_path}")
    for label, path in summary.graph_paths.items():
        click.echo(f"  graph.{label}: {path}")


_DEFAULT_CONFIG = """\
# Dirk configuration — see README for full schema.
scope:
  source: repos.yml
depth: standard
connection_threshold: 0.35
serendipity: 0.5
output:
  graph_dir: graph
  findings_dir: findings
model_preferences:
  embedding: local
  curation: hosted
skills:
  repo_inventory: true
  dependency_mapper: true
  interface_extractor: true
  concept_extractor: true
  semantic_linker: true
  connection_curator: true
"""


_DEFAULT_REPOS = """\
# Repositories Dirk should consider. One `owner/name` per line.
repos: []
"""


if __name__ == "__main__":  # pragma: no cover
    main()
