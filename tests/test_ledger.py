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


def test_system_note_actions_normalized(cfg):
    nid = ledger.add_system_note(cfg, "sample", "Pick one", ts="t",
                                 actions=["A", ["B", "b"]])
    note = [e for e in ledger.load(cfg)["sample"] if e["id"] == nid][0]
    assert note["actions"] == [["A", "A"], ["B", "b"]]          # bare string → [label, label]; pair kept


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
