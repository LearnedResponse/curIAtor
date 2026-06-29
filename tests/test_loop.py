"""loop: new-item detection + serialized dispatch (with a stub adapter, so no real agent runs)."""
from __future__ import annotations

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


def test_run_once_dispatches_serially_in_order(cfg, monkeypatch):
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
    assert any("loop error" in (e.get("comment") or "") for e in data["sample"] if e["author"] == "claude")
