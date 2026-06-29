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
