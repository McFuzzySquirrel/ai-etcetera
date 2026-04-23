"""Config loader smoke tests."""

from __future__ import annotations

import yaml

from dirk.config import load_config, load_repos


def test_defaults_when_missing(tmp_path):
    cfg = load_config(root=tmp_path)
    assert cfg.depth == "standard"
    assert cfg.connection_threshold == 0.35
    assert cfg.is_skill_enabled("repo_inventory")


def test_overrides_applied(tmp_path):
    (tmp_path / "dirk.config.yml").write_text(yaml.safe_dump({
        "depth": "deep",
        "connection_threshold": 0.5,
        "serendipity": 0.9,
        "skills": {"semantic_linker": False},
    }), encoding="utf-8")
    cfg = load_config(root=tmp_path)
    assert cfg.depth == "deep"
    assert cfg.connection_threshold == 0.5
    assert cfg.serendipity == 0.9
    assert not cfg.is_skill_enabled("semantic_linker")
    assert cfg.is_skill_enabled("repo_inventory")  # unaffected


def test_invalid_depth_rejected(tmp_path):
    (tmp_path / "dirk.config.yml").write_text("depth: galactic\n", encoding="utf-8")
    try:
        load_config(root=tmp_path)
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown depth")


def test_load_repos_filters_garbage(tmp_path):
    p = tmp_path / "repos.yml"
    p.write_text(yaml.safe_dump({"repos": ["good/one", "", "no-slash", 42, "  spaced/two  "]}),
                 encoding="utf-8")
    repos = load_repos(p)
    assert repos == ["good/one", "spaced/two"]
