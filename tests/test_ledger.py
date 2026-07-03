"""ledger: feedback save, agent notes, status transitions, and SQLite read behavior."""
from __future__ import annotations

from curiator import ledger


def test_save_entry_is_new_user_comment(cfg):
    fid = ledger.save_entry(cfg, "sample", stars=2, comment="axis labels missing", ts="t0")
    data = ledger.load(cfg)
    e = data["sample"][0]
    assert e["id"] == fid and e["author"] == "user" and e["kind"] == "comment"
    assert e["status"] == "new" and e["stars"] == 2


def test_system_note_and_status_transition(cfg):
    fid = ledger.save_entry(cfg, "sample", comment="fix it", ts="t0")
    nid = ledger.add_system_note(cfg, "sample", "Done.", reply_to=[fid], ts="t1")
    ledger.set_status(cfg, "sample", [fid], "done")
    data = ledger.load(cfg)
    user = [e for e in data["sample"] if e["author"] == "user"][0]
    note = [e for e in data["sample"] if e["id"] == nid][0]
    assert user["status"] == "done"
    assert note["author"] == "claude" and note["kind"] == "system" and note["reply_to"] == [fid]


def test_amend_note_appends(cfg):
    fid = ledger.save_entry(cfg, "sample", comment="x", ts="t0")
    nid = ledger.add_system_note(cfg, "sample", "Fixed.", reply_to=[fid], ts="t1")
    ledger.amend_note(cfg, "sample", nid, "  committed abc1234")
    note = [e for e in ledger.load(cfg)["sample"] if e["id"] == nid][0]
    assert note["comment"] == "Fixed.  committed abc1234"


def test_system_note_actions_normalized(cfg):
    nid = ledger.add_system_note(cfg, "sample", "Pick one", ts="t",
                                 actions=["A", ["B", "b"]])
    note = [e for e in ledger.load(cfg)["sample"] if e["id"] == nid][0]
    assert note["actions"] == [["A", "A"], ["B", "b"]]          # bare string → [label, label]; pair kept


def test_add_system_note_records_agent(cfg):
    nid = ledger.add_system_note(cfg, "sample", "fixed it", agent="Codex")
    note = next(e for e in ledger.load(cfg)["sample"] if e["id"] == nid)
    assert note["agent"] == "Codex" and note["author"] == "claude"
    nid2 = ledger.add_system_note(cfg, "sample", "x")            # omitted → None (UI falls back to 'Claude')
    assert next(e for e in ledger.load(cfg)["sample"] if e["id"] == nid2)["agent"] is None


def test_cmd_reply_stamps_the_configured_provider(cfg, collection):
    """`curiator reply` records the agent that answered, so the panel attributes it (the tmp gallery is
    headless-cc → 'Claude')."""
    import argparse

    from curiator.cli import cmd_reply
    fid = ledger.save_entry(cfg, "sample", comment="fix it", ts="t0")
    cmd_reply(argparse.Namespace(app="sample", feedback_id=fid, text="Done.", status="done", actions=None))
    note = [e for e in ledger.load(cfg)["sample"] if e["author"] == "claude"][-1]
    assert note["agent"] == "Claude"


def test_cmd_reply_done_rejects_missing_browser_smoke_artifacts(cfg, collection, monkeypatch):
    import argparse

    import pytest

    from curiator import agent_capabilities
    from curiator.cli import cmd_reply
    from curiator.loop.adapters import build_task

    monkeypatch.delenv("CURIATOR_BROWSER", raising=False)
    monkeypatch.setattr(
        agent_capabilities.shutil,
        "which",
        lambda name: "/usr/bin/brave-browser" if name == "brave-browser" else None,
    )

    fid = ledger.save_entry(cfg, "sample", comment="fix the chart", ts="t0")
    entry = next(e for e in ledger.load(cfg)["sample"] if e["id"] == fid)
    build_task(cfg, "sample", entry)

    with pytest.raises(SystemExit, match="required browser-smoke artifacts"):
        cmd_reply(argparse.Namespace(app="sample", feedback_id=fid, text="Done.", status="done", actions=None))

    items = ledger.load(cfg)["sample"]
    assert next(e for e in items if e["id"] == fid)["status"] == "new"
    assert not [e for e in items if e["author"] == "claude" and fid in (e.get("reply_to") or [])]


def test_cmd_reply_done_accepts_passing_browser_smoke_artifacts(cfg, collection, monkeypatch):
    import argparse
    import json

    from curiator import agent_capabilities
    from curiator.cli import cmd_reply
    from curiator.loop.adapters import build_task

    monkeypatch.delenv("CURIATOR_BROWSER", raising=False)
    monkeypatch.setattr(
        agent_capabilities.shutil,
        "which",
        lambda name: "/usr/bin/brave-browser" if name == "brave-browser" else None,
    )

    fid = ledger.save_entry(cfg, "sample", comment="fix the chart", ts="t0")
    entry = next(e for e in ledger.load(cfg)["sample"] if e["id"] == fid)
    build_task(cfg, "sample", entry)

    artifact_dir = collection / "feedback" / "replies" / f"{fid}-browser-smoke"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "sample.png").write_bytes(b"png")
    (artifact_dir / "sample.console.json").write_text("[]")
    (artifact_dir / "result.json").write_text(json.dumps({
        "ok": True,
        "results": [{"app": "sample", "ok": True, "browser_smoke": {"ok": True}}],
    }))

    cmd_reply(argparse.Namespace(app="sample", feedback_id=fid, text="Done.", status="done", actions=None))
    items = ledger.load(cfg)["sample"]
    assert next(e for e in items if e["id"] == fid)["status"] == "done"
    assert [e for e in items if e["author"] == "claude" and fid in (e.get("reply_to") or [])]


def test_reply_actions_arg_parsing():
    from curiator.cli import _parse_actions_arg
    assert _parse_actions_arg("A,B,C") == [["A", "A"], ["B", "B"], ["C", "C"]]
    assert _parse_actions_arg("Yes:yes, No:no") == [["Yes", "yes"], ["No", "no"]]
    assert _parse_actions_arg("") is None


def test_ts_defaults_to_utc_when_omitted(cfg):
    """No caller can store a null ts (a null breaks the history sort). Omitted ⇒ UTC, tz-aware."""
    fid = ledger.save_entry(cfg, "sample", comment="hi")            # no ts
    nid = ledger.add_system_note(cfg, "sample", "auto note")        # no ts (the loop/revert path)
    d = ledger.load(cfg)
    user = next(e for e in d["sample"] if e["id"] == fid)
    note = next(e for e in d["sample"] if e["id"] == nid)
    assert user["ts"] and user["ts"].endswith("+00:00")            # tz-aware UTC → client localizes it
    assert note["ts"] and note["ts"].endswith("+00:00")
    assert ledger.save_entry(cfg, "sample", comment="x", ts="t9") and \
        next(e for e in ledger.load(cfg)["sample"] if e["comment"] == "x")["ts"] == "t9"  # explicit wins


def test_sqlite_is_primary_and_json_snapshot_is_not_exported(cfg):
    fid = ledger.save_entry(cfg, "sample", comment="sqlite-backed", ts="t0")
    assert ledger.db_path(cfg).exists()
    assert not ledger.json_path(cfg).exists()
    assert ledger.load(cfg)["sample"][0]["id"] == fid


def test_load_does_not_dirty_committed_sqlite_ledger(cfg, collection):
    import subprocess

    ledger.save_entry(cfg, "sample", comment="read-only load", ts="t0")
    ledger.checkpoint(cfg)
    subprocess.run(["git", "add", "-f", "feedback/app_feedback.sqlite"], cwd=collection, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "ledger"], cwd=collection, check=True)

    assert ledger.load(cfg)["sample"][0]["comment"] == "read-only load"
    r = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", "feedback/app_feedback.sqlite"],
        cwd=collection,
        check=False,
    )
    assert r.returncode == 0


def test_legacy_json_ledger_migrates_into_sqlite(cfg):
    import json

    ledger.db_path(cfg).unlink(missing_ok=True)
    ledger.json_path(cfg).write_text(json.dumps({"sample": [
        {"id": "old1", "author": "user", "kind": "comment", "comment": "from json",
         "status": "new", "ts": "t0"}
    ]}))
    data = ledger.load(cfg)
    assert data["sample"][0]["id"] == "old1"
    assert ledger.db_path(cfg).exists()
    ledger.save_entry(cfg, "sample", comment="after migration", ts="t1")
    legacy = json.loads(ledger.json_path(cfg).read_text())
    assert len(legacy["sample"]) == 1
