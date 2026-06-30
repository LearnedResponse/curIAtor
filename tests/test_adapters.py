"""adapters: the task bundle (app + runner routing), the M2 screenshot-path regression, LESSONS load,
and the `command` adapter's {task_file}/{source} substitution."""
from __future__ import annotations

from pathlib import Path

from curiator.loop import adapters
from curiator.loop.adapters import GENERAL_KEY, Task, build_task, command


def _entry(**kw):
    base = {"id": "f1", "stars": 2, "comment": "legend covers the chart",
            "screenshot": None, "status": "new", "kind": "comment", "author": "user"}
    base.update(kw)
    return base


def test_app_bundle_paths_and_commands(cfg, collection):
    t = build_task(cfg, "sample", _entry(screenshot="shots/sample_f1.png"))
    body = Path(t.task_file).read_text()
    assert t.source == str((collection / "apps" / "sample.py").resolve())
    assert "feedback/shots/sample_f1.png" in body          # screenshot path joined ONCE
    assert "shots/shots/" not in body                       # M2 double-join regression guard
    assert "curiator reply sample f1" in body               # ready-to-run reply
    assert "SMOKE OK" in body                               # smoke-test recipe


def test_runner_routing_checkout_vs_pinned(cfg):
    g = build_task(cfg, GENERAL_KEY, _entry(id="g1", comment="the shell chrome is ugly"))
    body = Path(g.task_file).read_text()
    assert "checkout" in body.lower() and g.source is not None    # cfg runner.mode == checkout

    cfg2 = {**cfg, "runner": {"mode": "pinned"}}
    p = build_task(cfg2, GENERAL_KEY, _entry(id="g2", comment="same"))
    pbody = Path(p.task_file).read_text()
    assert "pinned" in pbody.lower() and "upstream" in pbody.lower() and p.source is None


def test_general_new_app_request_routes_to_collection(cfg, collection):
    entry = _entry(id="g3", comment="create a new curiator app as an explainer/overview")
    t = build_task(cfg, GENERAL_KEY, entry)
    body = Path(t.task_file).read_text()
    assert t.source == str(collection.resolve())
    assert "General collection feedback" in body
    assert "Do NOT edit the runner checkout" in body
    assert "gallery.yaml" in body and "curiator reply __general__ g3" in body
    assert adapters.general_targets_collection(entry)
    assert not adapters.general_targets_collection(_entry(comment="make the shell chrome clearer"))


def test_bundle_loads_lessons_when_present(cfg, collection):
    (collection / "LESSONS.md").write_text("# LESSONS.md\n\n## sample\n- ✓ stuck · `abc1234` · curator(sample): tidy\n")
    body = Path(build_task(cfg, "sample", _entry()).task_file).read_text()
    assert "Prior lessons for `sample`" in body and "abc1234" in body


def test_command_adapter_substitutes(cfg, monkeypatch):
    captured = {}
    monkeypatch.setattr(command.subprocess, "run", lambda c, **k: captured.update(cmd=c))
    cfg2 = {**cfg, "agent": {"adapter": "command", "cmd": "mytool {task_file} {source}"}}
    command.run(Task(key="sample", entry={"id": "x"}, source="apps/sample.py",
                     task_file="/tmp/task.md", cfg=cfg2))
    assert captured["cmd"] == ["mytool", "/tmp/task.md", "apps/sample.py"]


def test_get_adapter_by_name(cfg):
    assert adapters.get(cfg) is adapters.headless_cc           # gallery's agent.adapter == headless-cc
    assert adapters.get({**cfg, "agent": {"adapter": "command"}}) is command
    assert adapters.get({**cfg, "agent": {"adapter": "codex"}}) is adapters.codex


def test_codex_adapter_maps_profile_to_exec_flags(monkeypatch, tmp_path):
    """The codex adapter maps the unified agent profile onto `codex exec` flags — model, sandbox, and the
    full-trust bypass for elevated — with the bundle passed as the prompt after `--`."""
    from curiator.loop.adapters import Task, codex

    cap = {}

    class _Proc:
        returncode, stdout, stderr = 0, "ok", ""

    def fake_run(c, **k):
        cap["cmd"] = c
        return _Proc()

    monkeypatch.setattr(codex, "available", lambda: True)
    monkeypatch.setattr(codex.subprocess, "run", fake_run)
    tf = tmp_path / "task.md"
    tf.write_text("the bundle")

    # normal profile → sandboxed workspace-write, model passed, prompt last after --
    codex.run(Task(key="sample", entry={"id": "x"}, source="apps/sample.py", task_file=str(tf),
                   cfg={"repo_root": str(tmp_path)},
                   agent={"model": "gpt-5-codex", "permission_mode": "acceptEdits"}))
    cmd = cap["cmd"]
    assert cmd[:2] == ["codex", "exec"]
    assert cmd[cmd.index("-m") + 1] == "gpt-5-codex"
    assert cmd[cmd.index("-s") + 1] == "workspace-write"
    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd
    assert cmd[-2] == "--" and cmd[-1] == "the bundle"

    # elevated → full-trust bypass, no -s sandbox flag
    codex.run(Task(key="sample", entry={"id": "y"}, source="apps/sample.py", task_file=str(tf),
                   cfg={"repo_root": str(tmp_path)},
                   agent={"permission_mode": "bypassPermissions", "elevated": True}))
    cmd2 = cap["cmd"]
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd2 and "-s" not in cmd2


# ── elevated (trusted-group) agent profile ─────────────────────────────────
_ELEV_CFG = {"agent": {"autonomy": "auto-small", "permission_mode": "acceptEdits",
                       "elevated": {"groups": ["admin"], "autonomy": "auto",
                                    "permission_mode": "bypassPermissions",
                                    "disallowed_tools": ["Bash(git push:*)"]}}}


def test_effective_agent_merges_elevated_for_trusted_group():
    base = adapters.effective_agent(_ELEV_CFG, {"user": {"groups": ["analysts"]}})
    assert base["elevated"] is False and base["autonomy"] == "auto-small"

    elev = adapters.effective_agent(_ELEV_CFG, {"user": {"groups": ["admin", "x"]}})
    assert elev["elevated"] is True and elev["autonomy"] == "auto"
    assert elev["permission_mode"] == "bypassPermissions"
    assert elev["disallowed_tools"] == ["Bash(git push:*)"]

    assert adapters.effective_agent(_ELEV_CFG, {})["elevated"] is False        # no user → base


def test_elevated_bundle_grants_install_scope(cfg):
    cfg2 = {**cfg, "agent": _ELEV_CFG["agent"]}
    admin = {"id": "f9", "comment": "live quotes via yfinance", "status": "new", "kind": "comment",
             "author": "user", "user": {"groups": ["admin"]}}
    t = build_task(cfg2, "sample", admin)
    body = Path(t.task_file).read_text()
    assert t.agent["elevated"] is True
    assert "ELEVATED" in body and "pip install" in body and "requirements.txt" in body
    # a non-admin author still gets the restricted, one-file bundle
    t2 = build_task(cfg2, "sample", {**admin, "id": "f10", "user": {"groups": ["analysts"]}})
    assert "Edit ONLY the source above" in Path(t2.task_file).read_text()
