"""loop.py — the feedback → fix loop (standalone).

In the research prototype, `feedback_watch.sh` polled the ledger and EXITED on new feedback so
the *live* Claude Code session would be re-invoked. CurIAtor is self-contained: this watcher
polls the ledger and, on new feedback, **invokes a headless agent itself** via the configured
adapter — no live session required.

Flow per new feedback item:
  1. mark it `working` in the ledger (the UI badge flips)
  2. build a task bundle: the task template + this comment/stars/screenshot + the app's source path
  3. dispatch to the adapter (headless-cc / api / command)
  4. the agent edits the source, smoke-tests, restarts the app, and replies via the ledger
     (the protocol is spelled out in loop/task_template.md)

Run:  curiator watch     (or: python -m curiator.loop.loop)
"""
from __future__ import annotations

import time
from pathlib import Path

from . import adapters
from .. import ledger      # tiny ledger read/write (status, replies) — see curiator/ledger.py

POLL_SECONDS = 5


def _gallery_mtime(cfg: dict):
    gp = (cfg or {}).get("gallery_path")
    try:
        return Path(gp).stat().st_mtime if gp else None
    except OSError:
        return None


def reload_if_changed(cfg: dict, last_mtime) -> tuple[dict, float | None, bool]:
    """Hot-reload gallery.yaml when it changes on disk, so edits (e.g. `agent.elevated`, autonomy) take
    effect WITHOUT restarting the loop — no need to kill/restart the shell or watcher. Returns
    (cfg, mtime, reloaded). On a parse error the old cfg is kept (the loop never dies on a bad edit)."""
    from ..config import load_config
    mtime = _gallery_mtime(cfg)
    if mtime is not None and mtime != last_mtime:
        try:
            return load_config(), mtime, True
        except Exception:                                 # a half-saved / invalid YAML — keep running on the old cfg
            return cfg, mtime, False
    return cfg, mtime, False


def _new_items(led: dict) -> list[tuple[str, dict]]:
    """Entries that are user feedback (not a system/agent note) and still status:'new'."""
    out = []
    for key, entries in (led or {}).items():
        for e in entries if isinstance(entries, list) else []:
            if e.get("status") == "new" and e.get("kind") != "system" and e.get("author") != "claude":
                out.append((key, e))
    return out


def _label(key: str) -> str:
    return "◆ General" if key == adapters.GENERAL_KEY else key


def _outcome(cfg: dict, key: str, eid: str) -> tuple[str, str]:
    """The item's status + the first line of the agent's reply, after a run (for the ✓ line)."""
    items = ledger.load(cfg).get(key, [])
    st = next((e.get("status") for e in items if e.get("id") == eid), "?")
    notes = [e for e in items if e.get("author") == "claude" and eid in (e.get("reply_to") or [])]
    reply = (notes[-1].get("comment") or "").strip().splitlines()[0] if notes else ""
    return st, reply


def run_once(cfg: dict) -> int:
    """One pass: handle every new feedback item, one at a time. Returns how many were dispatched.

    Dispatch is SERIAL (and gitmem holds a commit lock): with git-as-memory on, each agent run becomes
    one atomic commit via `curiator reply`, so items must never race the shared ledger / git index."""
    led = ledger.load(cfg)
    items = _new_items(led)
    adapter = adapters.get(cfg)
    adapter_name = (cfg.get("agent", {}) or {}).get("adapter", "headless-cc")
    for key, entry in items:
        eid = entry.get("id")
        who = (entry.get("user") or {}).get("name") or "anonymous"
        snippet = " ".join((entry.get("comment") or "").split())[:80] or f"★{entry.get('stars')}"
        print(f"curiator: ● new feedback on {_label(key)} by {who} — {snippet!r}", flush=True)
        ledger.set_status(cfg, key, [eid], "working")
        task = adapters.build_task(cfg, key, entry)     # writes a task file, returns its path + bundle
        prof = task.agent or {}
        elevated = "  ⚡ELEVATED" if prof.get("elevated") else ""
        print(f"curiator:   ▶ launching {adapter_name} on {key}/{eid} "
              f"(autonomy={prof.get('autonomy', 'auto-small')}){elevated}", flush=True)
        try:
            adapter.run(task)                            # the agent edits + smoke-tests + replies
            st, reply = _outcome(cfg, key, eid)
            tail = f' · "{reply[:72]}"' if reply else ""
            print(f"curiator:   {'✓' if st != 'working' else '⚠'} {key}/{eid} → {st}{tail}", flush=True)
        except Exception as exc:                          # never leave an item stuck on 'working'
            print(f"curiator:   ✗ {key}/{eid} failed: {exc}", flush=True)
            ledger.add_system_note(cfg, key, f"⚙ loop error: {exc}", reply_to=[eid])
            ledger.set_status(cfg, key, [eid], "new")
    return len(items)


def watch(cfg: dict) -> None:
    """Long-running poll loop. Ctrl-C to stop. Re-reads gallery.yaml when it changes, so config edits
    (autonomy, `agent.elevated`, …) apply live — no restart needed."""
    print(f"curiator: watching {ledger.path(cfg)} every {POLL_SECONDS}s "
          f"(adapter={cfg.get('agent', {}).get('adapter')}, "
          f"autonomy={cfg.get('agent', {}).get('autonomy')}) — Ctrl-C to stop", flush=True)
    mtime = _gallery_mtime(cfg)
    while True:
        try:
            cfg, mtime, reloaded = reload_if_changed(cfg, mtime)
            if reloaded:
                print(f"curiator: ⟳ reloaded gallery.yaml (autonomy={cfg.get('agent', {}).get('autonomy')}, "
                      f"elevated={'yes' if (cfg.get('agent', {}) or {}).get('elevated') else 'no'})", flush=True)
            run_once(cfg)                                 # prints ● new / ▶ launching / ✓ outcome per item
        except Exception as exc:
            print(f"curiator: poll error (continuing): {exc}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    from ..config import load_config
    watch(load_config())
