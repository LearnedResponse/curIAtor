"""loop: new-item detection + serialized dispatch (with a stub adapter, so no real agent runs),
and live gallery.yaml reload (config edits apply without restarting the loop)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from curiator import ledger
from curiator.loop import loop


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
