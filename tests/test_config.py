"""config: gallery resolution + runner.mode / git defaults (additive + backward-compatible),
and the comment-preserving in-place writer the settings page uses."""
from __future__ import annotations

import textwrap

from curiator.config import load_config, set_block_key


def test_loads_gallery_under_collection(cfg, collection):
    assert cfg["repo_root"] == str(collection.resolve())          # repo_root = the gallery's dir
    assert cfg["gallery_path"] == str((collection / "gallery.yaml").resolve())
    assert [a["name"] for a in cfg["apps"]] == ["sample"]


def test_load_config_searches_parent_directories(collection, monkeypatch):
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)
    monkeypatch.chdir(collection / "apps")
    cfg = load_config()
    assert cfg["repo_root"] == str(collection.resolve())
    assert cfg["gallery_path"] == str((collection / "gallery.yaml").resolve())


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
    assert cfg["git"]["include_ledger"] is False
    assert cfg["auth"]["admin_groups"] == ["admin"]   # who may change agent settings (mode != none)
    assert cfg["voice"]["transcribe_cmd"] is None
    assert cfg["voice"]["transcribe_timeout"] == 60


def test_infer_current_app_requires_an_unambiguous_match(tmp_path):
    from curiator.config import infer_current_app
    (tmp_path / "apps" / "alpha").mkdir(parents=True)
    (tmp_path / "apps" / "beta").mkdir(parents=True)
    cfg = {"repo_root": str(tmp_path), "apps": [
        {"name": "alpha", "source": "apps/alpha", "mount": {"kind": "dash-inproc", "module": "alpha"}},
        {"name": "beta", "source": "apps/beta", "mount": {"kind": "dash-inproc", "module": "beta"}},
    ]}
    # inside one app's source scope → that app
    assert infer_current_app(cfg, cwd=tmp_path / "apps" / "alpha") == "alpha"
    # the collection root — every app ties → None (never silently the first app in the gallery)
    assert infer_current_app(cfg, cwd=tmp_path) is None


def test_app_spec_is_the_shared_schema_home(cfg, collection):
    from curiator.config import app_spec
    spec = app_spec(cfg, "sample")
    assert spec["source"] == str((collection / "apps" / "sample.py").resolve())
    assert spec["root"] == str(collection.resolve())
    assert app_spec(cfg, "nope") is None


def test_app_spec_carries_mount_smoke_timeout(collection, monkeypatch):
    from curiator.config import app_spec

    (collection / "gallery.yaml").write_text(textwrap.dedent('''\
        apps:
          - name: suite
            root: apps/suite
            smoke_timeout: 5
            mounts:
              - name: api
                source: .
                smoke: python -m compileall -q .
                smoke_timeout: 1.5
                mount: { kind: proxy, cmd: "python server.py --port {port}", port: 8811 }
    '''))
    monkeypatch.setenv("CURIATOR_GALLERY", str(collection / "gallery.yaml"))
    cfg = load_config()
    spec = app_spec(cfg, "api")
    assert spec["smoke"] == "python -m compileall -q ."
    assert spec["smoke_timeout"] == 1.5


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
    # replace the whole scalar, not just the first shell token
    tv = "voice:\n  transcribe_cmd: scripts/custom-transcribe {audio}  # local\n"
    assert "transcribe_cmd: python -m curiator.voice.faster_whisper {audio}  # local" in set_block_key(
        tv, "voice", "transcribe_cmd", "python -m curiator.voice.faster_whisper {audio}"
    )
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
