"""config: gallery resolution + runner.mode / git defaults (additive + backward-compatible),
and the comment-preserving in-place writer the settings page uses."""
from __future__ import annotations

import textwrap

from curiator.config import load_config, set_block_key


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
    assert cfg["auth"]["admin_groups"] == ["admin"]   # who may change agent settings (mode != none)


def test_agent_label_names_the_provider():
    from curiator.config import agent_label
    assert agent_label({"agent": {"adapter": "headless-cc"}}) == "Claude"
    assert agent_label({"agent": {"adapter": "codex"}}) == "Codex"
    assert agent_label({"agent": {"adapter": "codex", "model": "gpt-5-codex"}}) == "Codex (gpt-5-codex)"
    assert agent_label({"agent": {"adapter": "command", "cmd": "/usr/local/bin/aider {task_file}"}}) == "aider"
    assert agent_label({}) == "Claude"            # default adapter


def test_set_block_key_updates_inserts_appends():
    t = "agent:\n  adapter: headless-cc   # provider\n  autonomy: auto-small\n"
    # update in place, KEEP the inline comment + the other keys
    t2 = set_block_key(t, "agent", "adapter", "codex")
    assert "adapter: codex   # provider" in t2 and "autonomy: auto-small" in t2
    # insert a key the block doesn't have yet
    assert "sandbox: workspace-write" in set_block_key(t2, "agent", "sandbox", "workspace-write")
    # blank / None → null
    assert "model: null" in set_block_key(t, "agent", "model", "")
    # a brand-new block gets appended
    assert "agent:\n  adapter: codex" in set_block_key("apps: []\n", "agent", "adapter", "codex")
    # tolerate a blank line inside the block (don't bleed into the next top-level key)
    tb = "agent:\n  adapter: headless-cc\n\n  autonomy: auto-small\nshell:\n  port: 8300\n"
    out = set_block_key(tb, "agent", "autonomy", "propose-only")
    assert "autonomy: propose-only" in out and "port: 8300" in out
