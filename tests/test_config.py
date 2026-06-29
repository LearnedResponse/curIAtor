"""config: gallery resolution + runner.mode / git defaults (additive + backward-compatible)."""
from __future__ import annotations

import textwrap

from curiator.config import load_config


def test_loads_gallery_under_collection(cfg, collection):
    assert cfg["repo_root"] == str(collection.resolve())          # repo_root = the gallery's dir
    assert cfg["gallery_path"] == str((collection / "gallery.yaml").resolve())
    assert [a["name"] for a in cfg["apps"]] == ["sample"]


def test_explicit_runner_and_git_from_gallery(cfg):
    assert cfg["runner"] == {"mode": "checkout", "path": "."}
    assert cfg["git"]["commit"] is True
    assert cfg["git"]["signoff"] is True
    assert cfg["git"]["include_ledger"] is True


def test_defaults_when_blocks_absent(tmp_path, monkeypatch):
    # a minimal gallery with no runner: / git: blocks → safe defaults
    (tmp_path / "gallery.yaml").write_text(textwrap.dedent('''\
        apps:
          - name: only
            mount: { kind: dash-inproc, module: only }
            source: apps/only.py
    '''))
    monkeypatch.setenv("CURIATOR_GALLERY", str(tmp_path / "gallery.yaml"))
    cfg = load_config()
    assert cfg["runner"]["mode"] == "pinned"      # safe consumer default
    assert cfg["git"]["commit"] is False          # leave-uncommitted default
    assert cfg["git"]["branch"] == "curiator/auto"
    assert cfg["git"]["signoff"] is True
