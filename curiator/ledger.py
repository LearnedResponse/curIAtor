"""ledger.py — minimal read/write for the feedback ledger (feedback/app_feedback.json).

Factored out of the Dash shell so the loop + adapters can touch the ledger without importing
the whole UI module. Same on-disk shape the shell uses:

    { "<app_key>": [ {id, author, kind, comment, stars, status, ts, screenshot, reply_to?}, ... ] }

Statuses: "new" → "working" → "awaiting_approval" → "done" (+ system notes use status "update").
A system/agent note has author="claude", kind="system".
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path


def path(cfg: dict) -> Path:
    d = Path(cfg.get("repo_root", ".")) / (cfg.get("feedback", {}).get("dir", "feedback"))
    return d / "app_feedback.json"


def load(cfg: dict) -> dict:
    p = path(cfg)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def _save(cfg: dict, data: dict) -> None:
    p = path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2))


def set_status(cfg: dict, key: str, ids: list[str], status: str) -> None:
    data = load(cfg)
    for e in data.get(key, []):
        if e.get("id") in ids:
            e["status"] = status
    _save(cfg, data)


def add_system_note(cfg: dict, key: str, text: str, reply_to: list[str] | None = None,
                    status: str = "update", ts: str | None = None) -> str:
    """Append an agent/⚙ note. Caller should pass a timestamp (ledger stays clock-free)."""
    data = load(cfg)
    nid = uuid.uuid4().hex[:8]
    data.setdefault(key, []).append({
        "id": nid, "author": "claude", "kind": "system", "comment": text,
        "status": status, "reply_to": reply_to or [], "ts": ts,
    })
    _save(cfg, data)
    return nid


def save_entry(cfg: dict, key: str, *, stars=None, comment="", screenshot=None, ts=None) -> str:
    """Append a user feedback entry (used by the shell UI; here for completeness/tests)."""
    data = load(cfg)
    eid = uuid.uuid4().hex[:8]
    data.setdefault(key, []).append({
        "id": eid, "author": "user", "kind": "comment", "comment": comment,
        "stars": stars, "status": "new", "screenshot": screenshot, "ts": ts,
    })
    _save(cfg, data)
    return eid
