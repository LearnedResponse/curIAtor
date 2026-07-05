"""loop: new-item detection + serialized dispatch (with a stub adapter, so no real agent runs),
and live gallery.yaml reload (config edits apply without restarting the loop)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from curiator import ledger
from curiator.loop import adapters, loop, runlog


def test_new_items_only_user_new(cfg):
    f1 = ledger.save_entry(cfg, "sample", comment="a", ts="t")
    ledger.save_entry(cfg, "sample", comment="b", ts="t")
    ledger.add_system_note(cfg, "sample", "agent note", ts="t")     # system → ignored
    led = ledger.load(cfg)
    led["sample"][0]["status"] = "done"                              # f1 done → ignored
    items = loop._new_items(led)
    keys = {e["comment"] for _, e in items}
    assert keys == {"b"}                                            # only the still-new user comment
    assert all(k == "sample" for k, _ in items)
    _ = f1


def test_run_once_dispatches_serially_in_order(cfg, monkeypatch, capsys):
    ledger.save_entry(cfg, "sample", comment="first", ts="t")
    ledger.save_entry(cfg, "sample", comment="second", ts="t")
    seen = []

    class Stub:
        @staticmethod
        def run(task):
            seen.append(task.entry["comment"])

    monkeypatch.setattr("curiator.loop.adapters.get", lambda _cfg: Stub)
    n = loop.run_once(cfg)
    assert n == 2
    assert seen == ["first", "second"]                              # serial, in order
    # each item flipped new → working before dispatch
    assert all(e["status"] == "working" for e in ledger.load(cfg)["sample"] if e["author"] == "user")
    # the run is visible on stdout: a ● new-feedback + ▶ launching line per item (what `serve` streams)
    out = capsys.readouterr().out
    assert out.count("● new feedback on sample") == 2 and out.count("▶ launching") == 2
    assert "first" in out and "second" in out


def test_run_once_forces_explicit_anonymous_feedback_to_held(cfg, monkeypatch):
    fid = ledger.save_entry(
        cfg,
        "sample",
        comment="public note",
        user={"id": "anonymous", "email": "", "name": "anonymous", "groups": []},
    )
    seen = []

    class Stub:
        @staticmethod
        def run(task):
            seen.append(task.entry["comment"])

    monkeypatch.setattr("curiator.loop.adapters.get", lambda _cfg: Stub)
    assert loop.run_once(cfg) == 0

    data = ledger.load(cfg)["sample"]
    user = next(e for e in data if e["id"] == fid)
    note = next(e for e in data if e.get("kind") == "system" and fid in (e.get("reply_to") or []))
    assert user["status"] == "held"
    assert "anonymous feedback never auto-dispatches" in note["comment"]
    assert seen == []


def test_run_once_holds_feedback_when_global_daily_quota_is_spent(cfg, monkeypatch):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cfg["agent"]["quotas"] = {"global_daily": 1}
    ledger.save_entry(
        cfg,
        "sample",
        comment="already dispatched",
        ts=now,
        user={"email": "a@example.com", "groups": []},
        extra={"status": "done", "dispatched_at": now},
    )
    fid = ledger.save_entry(
        cfg,
        "sample",
        comment="over budget",
        ts=now,
        user={"email": "b@example.com", "groups": []},
    )

    class Stub:
        @staticmethod
        def run(task):  # pragma: no cover - should not dispatch
            raise AssertionError("over-quota feedback should not dispatch")

    monkeypatch.setattr("curiator.loop.adapters.get", lambda _cfg: Stub)
    assert loop.run_once(cfg) == 0

    data = ledger.load(cfg)["sample"]
    user = next(e for e in data if e["id"] == fid)
    note = next(e for e in data if e.get("kind") == "system" and fid in (e.get("reply_to") or []))
    assert user["status"] == "held"
    assert "global_daily=1" in note["comment"]


def test_run_once_holds_account_over_per_user_quota_but_not_trusted(cfg, monkeypatch):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cfg["agent"]["dispatch"] = {"trusted_groups": ["trusted"]}
    cfg["agent"]["quotas"] = {"per_user_daily": 1}
    ledger.save_entry(
        cfg,
        "sample",
        comment="already dispatched",
        ts=now,
        user={"email": "a@example.com", "groups": []},
        extra={"status": "done", "dispatched_at": now},
    )
    held_id = ledger.save_entry(
        cfg,
        "sample",
        comment="same user",
        ts=now,
        user={"email": "a@example.com", "groups": []},
    )
    trusted_id = ledger.save_entry(
        cfg,
        "sample",
        comment="trusted same user",
        ts=now,
        user={"email": "a@example.com", "groups": ["trusted"]},
    )
    seen = []

    class Stub:
        @staticmethod
        def run(task):
            seen.append(task.entry["id"])

    monkeypatch.setattr("curiator.loop.adapters.get", lambda _cfg: Stub)
    assert loop.run_once(cfg) == 1

    data = ledger.load(cfg)["sample"]
    held = next(e for e in data if e["id"] == held_id)
    trusted = next(e for e in data if e["id"] == trusted_id)
    note = next(e for e in data if e.get("kind") == "system" and held_id in (e.get("reply_to") or []))
    assert held["status"] == "held"
    assert "per_user_daily=1" in note["comment"]
    assert trusted["status"] == "working"
    assert trusted.get("dispatched_at")
    assert seen == [trusted_id]


def test_run_once_resets_item_on_adapter_error(cfg, monkeypatch):
    ledger.save_entry(cfg, "sample", comment="boom", ts="t")

    class Boom:
        @staticmethod
        def run(task):
            raise RuntimeError("kaboom")

    monkeypatch.setattr("curiator.loop.adapters.get", lambda _cfg: Boom)
    loop.run_once(cfg)
    data = ledger.load(cfg)
    user = [e for e in data["sample"] if e["author"] == "user"][0]
    assert user["status"] == "new"                                  # reset, not stuck on 'working'
    note = next(e for e in data["sample"] if e["author"] == "claude")
    assert "loop error" in (note.get("comment") or "")
    assert note.get("ts"), "loop-error notes must carry a ts — a null ts crashes render_history's sort"


def test_run_once_resets_and_reraises_on_agent_interruption(cfg, monkeypatch):
    fid = ledger.save_entry(cfg, "sample", comment="restart during fix", ts="t")

    class Interrupted:
        @staticmethod
        def run(task):
            raise runlog.AgentInterrupted("agent interrupted by signal 15")

    monkeypatch.setattr("curiator.loop.adapters.get", lambda _cfg: Interrupted)
    with pytest.raises(runlog.AgentInterrupted):
        loop.run_once(cfg)

    data = ledger.load(cfg)["sample"]
    user = next(e for e in data if e["id"] == fid)
    note = next(e for e in data if e.get("kind") == "system" and fid in (e.get("reply_to") or []))
    assert user["status"] == "new"
    assert "watcher recovery" in note["comment"]
    assert "service shutdown" in note["comment"]


def test_run_once_holds_item_when_stopped_by_user(cfg, monkeypatch):
    fid = ledger.save_entry(cfg, "sample", comment="stop me", ts="t")

    class Cancelled:
        @staticmethod
        def run(task):
            raise runlog.AgentCancelled("run cancelled by user")

    monkeypatch.setattr("curiator.loop.adapters.get", lambda _cfg: Cancelled)
    assert loop.run_once(cfg) == 1

    data = ledger.load(cfg)["sample"]
    user = next(e for e in data if e["id"] == fid)
    note = next(e for e in data if e.get("kind") == "system" and fid in (e.get("reply_to") or []))
    assert user["status"] == "held"                                 # parked, not retried
    assert "Run stopped by user" in note["comment"]


def test_run_once_caps_repeated_timeouts_then_parks(cfg, monkeypatch):
    cfg["agent"]["max_timeouts"] = 2
    fid = ledger.save_entry(cfg, "sample", comment="slow task", ts="t")

    class TimedOut:
        @staticmethod
        def run(task):
            raise runlog.AgentTimeout(900)

    monkeypatch.setattr("curiator.loop.adapters.get", lambda _cfg: TimedOut)

    loop.run_once(cfg)                                              # attempt 1 → requeued to try again
    user = next(e for e in ledger.load(cfg)["sample"] if e["id"] == fid)
    assert user["status"] == "new" and user["timeout_attempts"] == 1

    loop.run_once(cfg)                                              # attempt 2 → cap reached → held
    data = ledger.load(cfg)["sample"]
    user = next(e for e in data if e["id"] == fid)
    assert user["status"] == "held" and user["timeout_attempts"] == 2
    notes = [e for e in data if e.get("kind") == "system" and fid in (e.get("reply_to") or [])]
    assert any("time limit" in n["comment"] for n in notes)
    assert any("Parked as" in n["comment"] for n in notes)


def _bare_task(tmp_path):
    import types
    reply = tmp_path / "replies" / "abc123.md"
    reply.parent.mkdir(parents=True, exist_ok=True)
    return types.SimpleNamespace(reply_file=str(reply))


def test_run_streamed_stops_on_cancel_marker(cfg, tmp_path):
    import sys
    import threading
    import time as _t

    task = _bare_task(tmp_path)
    cancel = Path(task.reply_file).with_suffix(".cancel")
    threading.Thread(target=lambda: (_t.sleep(0.4), cancel.write_text("stop")), daemon=True).start()

    with pytest.raises(runlog.AgentCancelled):
        runlog.run_streamed(task, [sys.executable, "-c", "import time; time.sleep(30)"],
                            cwd=str(tmp_path), timeout=60, label="x", heartbeat=0)
    trace = Path(task.reply_file).read_text()
    assert "cancelled by user" in trace
    assert not cancel.exists()                                      # marker consumed


def test_run_streamed_timeout_raises_agent_timeout(cfg, tmp_path):
    import sys

    task = _bare_task(tmp_path)
    with pytest.raises(runlog.AgentTimeout) as ei:
        runlog.run_streamed(task, [sys.executable, "-c", "import time; time.sleep(30)"],
                            cwd=str(tmp_path), timeout=1, label="x", heartbeat=0)
    assert ei.value.timeout == 1
    assert "time limit" in Path(task.reply_file).read_text()


def test_run_streamed_emits_heartbeat_on_silence(cfg, tmp_path):
    import sys

    task = _bare_task(tmp_path)
    runlog.run_streamed(task, [sys.executable, "-c", "import time; time.sleep(0.8)"],
                        cwd=str(tmp_path), timeout=10, label="x", heartbeat=0.3)
    assert "still working" in Path(task.reply_file).read_text()


def test_recover_interrupted_working_requeues_watcher_claim(cfg):
    fid = ledger.save_entry(cfg, "sample", comment="left working", ts="t")
    entry = next(e for e in ledger.load(cfg)["sample"] if e["id"] == fid)
    ledger.set_status(cfg, "sample", [fid], "working")
    task = adapters.build_task(cfg, "sample", {**entry, "status": "working"})
    runlog.init_trace(task, "codex")
    runlog.note(task, "status set to working; launching codex")

    assert loop.recover_interrupted_working(cfg) == 1

    data = ledger.load(cfg)["sample"]
    user = next(e for e in data if e["id"] == fid)
    note = next(e for e in data if e.get("kind") == "system" and fid in (e.get("reply_to") or []))
    trace = Path(task.reply_file).read_text()
    assert user["status"] == "new"
    assert "stale working claim" in note["comment"]
    assert "requeued for another pass" in trace


def test_recover_interrupted_working_skips_interactive_claim(cfg):
    fid = ledger.save_entry(cfg, "sample", comment="human is working", ts="t")
    entry = next(e for e in ledger.load(cfg)["sample"] if e["id"] == fid)
    ledger.set_status(cfg, "sample", [fid], "working")
    task = adapters.build_task(cfg, "sample", {**entry, "status": "working"})
    runlog.init_trace(task, "interactive")
    runlog.note(task, "opened for interactive CLI work")

    assert loop.recover_interrupted_working(cfg) == 0

    data = ledger.load(cfg)["sample"]
    user = next(e for e in data if e["id"] == fid)
    notes = [e for e in data if e.get("kind") == "system" and fid in (e.get("reply_to") or [])]
    assert user["status"] == "working"
    assert notes == []


def test_reload_if_changed_applies_edits_without_restart(cfg, collection):
    gp = cfg["gallery_path"]
    m0 = os.stat(gp).st_mtime

    # unchanged → no reload, same cfg object
    same, _, reloaded = loop.reload_if_changed(cfg, m0)
    assert reloaded is False and same is cfg

    # edit gallery.yaml (bump autonomy + add an elevated block) and advance its mtime
    txt = Path(gp).read_text().replace("autonomy: auto-small",
                                       "autonomy: auto\n  elevated:\n    groups: [admin]")
    Path(gp).write_text(txt)
    os.utime(gp, (m0 + 5, m0 + 5))

    fresh, m1, reloaded = loop.reload_if_changed(cfg, m0)
    assert reloaded is True and m1 == m0 + 5
    assert fresh["agent"]["autonomy"] == "auto"                     # the edit took effect — no restart
    assert fresh["agent"]["elevated"]["groups"] == ["admin"]
