"""Dirk — a holistic research agent for repository collections.

Named after Dirk Gently, this package surfaces the *fundamental
interconnectedness* of all things across a configured set of repositories,
producing a knowledge graph and a findings document on each run.
"""

__version__ = "0.1.0"

from dirk.config import Config, load_config

__all__ = ["Config", "load_config", "__version__"]
