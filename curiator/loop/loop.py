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

import json
import time
from pathlib import Path

from . import adapters
from .. import ledger      # tiny ledger read/write (status, replies) — see curiator/ledger.py

POLL_SECONDS = 5


def _new_items(led: dict) -> list[tuple[str, dict]]:
    """Entries that are user feedback (not a system/agent note) and still status:'new'."""
    out = []
    for key, entries in (led or {}).items():
        for e in entries if isinstance(entries, list) else []:
            if e.get("status") == "new" and e.get("kind") != "system" and e.get("author") != "claude":
                out.append((key, e))
    return out


def run_once(cfg: dict) -> int:
    """One pass: handle every new feedback item. Returns how many were dispatched."""
    led = ledger.load(cfg)
    items = _new_items(led)
    adapter = adapters.get(cfg)
    for key, entry in items:
        eid = entry.get("id")
        ledger.set_status(cfg, key, [eid], "working")
        task = adapters.build_task(cfg, key, entry)     # writes a task file, returns its path + bundle
        try:
            adapter.run(task)                            # the agent edits + smoke-tests + replies
        except Exception as exc:                          # never leave an item stuck on 'working'
            ledger.add_system_note(cfg, key, f"⚙ loop error: {exc}", reply_to=[eid])
            ledger.set_status(cfg, key, [eid], "new")
    return len(items)


def watch(cfg: dict) -> None:
    """Long-running poll loop. Ctrl-C to stop."""
    print(f"curiator: watching {ledger.path(cfg)} every {POLL_SECONDS}s "
          f"(adapter={cfg.get('agent', {}).get('adapter')}, "
          f"autonomy={cfg.get('agent', {}).get('autonomy')}) — Ctrl-C to stop")
    while True:
        try:
            n = run_once(cfg)
            if n:
                print(f"curiator: dispatched {n} feedback item(s)")
        except Exception as exc:
            print(f"curiator: poll error (continuing): {exc}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    from ..config import load_config
    watch(load_config())
