"""ledger: feedback save, agent notes, status transitions, and SHA amend."""
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
