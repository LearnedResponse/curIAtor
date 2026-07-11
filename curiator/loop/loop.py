"""loop.py — the feedback → fix loop (standalone).

In the research prototype, `feedback_watch.sh` polled the ledger and EXITED on new feedback so
the *live* Claude Code session would be re-invoked. curIAtor is self-contained: this watcher
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
from datetime import datetime, timezone
from pathlib import Path

from . import adapters, runlog
from .. import ledger, run_recovery
from ..agent_capabilities import figma_dispatch_hold_reason
from ..design_refs import DesignReferenceError, thread_design_refs

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


def _working_items(led: dict) -> list[tuple[str, dict]]:
    """User feedback items claimed by the watcher but not closed by an agent reply."""
    out = []
    for key, entries in (led or {}).items():
        for e in entries if isinstance(entries, list) else []:
            if e.get("status") == "working" and e.get("kind") != "system" and e.get("author") != "claude":
                out.append((key, e))
    return out


def _label(key: str) -> str:
    return "◆ General" if key == adapters.GENERAL_KEY else key


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _day(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc).date().isoformat()
    except ValueError:
        return None


def _quota_value(raw) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _user_key(entry: dict) -> str:
    user = entry.get("user") or {}
    for field in ("email", "id", "name"):
        value = (user.get(field) or "").strip()
        if value:
            return value.lower()
    return "anonymous"


def _explicit_anonymous(entry: dict) -> bool:
    """Only the hosted anonymous user is forced held here.

    Older tests/imports may have no `user` stamp at all; those are not enough to prove the author was
    a logged-out public visitor, so they keep the historical dispatch behavior.
    """
    if entry.get("moderation_approved_at"):
        return False
    user = entry.get("user") or {}
    if not user:
        return False
    uid = str(user.get("id") or "").lower()
    email = str(user.get("email") or "").strip()
    name = str(user.get("name") or "").lower()
    return not email and (uid == "anonymous" or name == "anonymous")


def _trusted_user(cfg: dict, entry: dict) -> bool:
    groups = set((entry.get("user") or {}).get("groups") or [])
    trusted = set(((cfg.get("agent") or {}).get("dispatch") or {}).get("trusted_groups") or [])
    return bool(groups & trusted)


def _dispatch_day(entry: dict) -> str | None:
    if entry.get("dispatched_at"):
        return _day(entry.get("dispatched_at"))
    if entry.get("status") in {"working", "awaiting_approval", "done"}:
        return _day(entry.get("ts"))
    return None


def _today_dispatches(led: dict, today: str) -> list[dict]:
    out = []
    for entries in (led or {}).values():
        for entry in entries if isinstance(entries, list) else []:
            if entry.get("kind") == "system":
                continue
            if _dispatch_day(entry) == today:
                out.append(entry)
    return out


def _hold_feedback(cfg: dict, key: str, entry: dict, text: str) -> None:
    eid = entry.get("id")
    ledger.set_status(cfg, key, [eid], "held")
    ledger.add_system_note(cfg, key, text, reply_to=[eid], agent="curiator dispatch")


def _trace_mentions_interactive(cfg: dict, entry: dict) -> bool:
    eid = entry.get("id")
    if not eid:
        return False
    try:
        text = runlog.reply_path(cfg, eid).read_text(encoding="utf-8", errors="replace")[:1000]
    except OSError:
        return False
    return "- adapter: `interactive`" in text


def _recovery_note(cfg: dict, key: str, entry: dict, text: str, *, status: str) -> None:
    eid = entry.get("id")
    if not eid:
        return
    ledger.add_system_note(cfg, key, text, reply_to=[eid], agent="curiator watcher")
    ledger.set_status(cfg, key, [eid], status)
    runlog.append(runlog.reply_path(cfg, eid), f"\n[{_now()}] {text}\n")


def _classify_ended_run(
    cfg: dict,
    key: str,
    entry: dict,
    reason: str,
    *,
    hold_even_if_unchanged: bool = False,
) -> tuple[str, dict | None]:
    """Capture process-end state and choose retry vs explicit recovery.

    Only a byte/index-identical source scope may be retried automatically. A missing or corrupt
    checkpoint is ambiguous and therefore held without touching source files.
    """
    eid = entry.get("id")
    if not eid:
        return "held", None
    try:
        run_recovery.record_process_end(cfg, eid, reason)
        report = run_recovery.recovery_report(cfg, eid)
    except run_recovery.CheckpointError as exc:
        text = (
            f"watcher recovery held this item because its source checkpoint is unavailable or invalid ({exc}). "
            "Source files were left untouched; inspect the working tree before closing or retrying."
        )
        _recovery_note(cfg, key, entry, text, status="held")
        return "held", None

    formatted = run_recovery.format_report(report)
    runlog.append(runlog.reply_path(cfg, eid), f"\n```text\n{formatted}\n```\n")
    if report.get("source_delta") is False:
        status = "held" if hold_even_if_unchanged else "new"
        action = "parked by the Stop request" if hold_even_if_unchanged else "safely requeued"
        prefix = "Run stopped by user. " if hold_even_if_unchanged else ""
        text = (
            f"{prefix}watcher recovery {action}: {reason}. The checkpoint proves the writable source scope "
            "is unchanged from its pre-run baseline."
        )
        _recovery_note(cfg, key, entry, text, status=status)
        run_recovery.retire_checkpoint(cfg, eid, "held-unchanged" if hold_even_if_unchanged else "requeued-unchanged",
                                       note=text)
        return status, report

    changed = ", ".join(report.get("agent_run_paths") or []) or "unclassified source state"
    conflict = report.get("post_interruption_paths") or []
    conflict_text = (
        " Changes after process end also exist, so Restore is disabled: " + ", ".join(conflict)
        if conflict else ""
    )
    text = (
        f"watcher recovery parked this item as held: {reason}. Partial source changes were preserved "
        f"({changed}).{conflict_text} Inspect with `curiator run recovery {eid}`; then choose "
        f"`curiator run resume {eid}`, `curiator run preserve {eid}`, or `curiator run restore {eid}`."
    )
    _recovery_note(cfg, key, entry, text, status="held")
    return "held", report


def recover_interrupted_working(
    cfg: dict, reason: str = "watcher started with a stale working claim",
) -> dict[str, int]:
    """Recover watcher-owned `working` items left behind by a prior crashed/restarted watcher.

    Interactive `curiator work` claims are deliberately skipped: those are human-owned and should stay
    claimed until the human runs `curiator done` or explicitly changes the status. Automatic retry is
    allowed only when the source checkpoint proves that no source content or index state changed.
    """
    recovered = {"total": 0, "requeued": 0, "held": 0}
    for key, entry in _working_items(ledger.load(cfg)):
        if _trace_mentions_interactive(cfg, entry):
            continue
        status, _ = _classify_ended_run(cfg, key, entry, reason)
        recovered["total"] += 1
        recovered["requeued" if status == "new" else "held"] += 1
    return recovered


def _dispatch_hold_reason(cfg: dict, led: dict, key: str, entry: dict) -> str | None:
    if _explicit_anonymous(entry):
        return "Queued for review - anonymous feedback never auto-dispatches."

    try:
        design_refs = thread_design_refs(led, key, entry)
    except DesignReferenceError as exc:
        return f"Queued for review - the attached design reference is invalid ({exc})."
    figma_reason = figma_dispatch_hold_reason(cfg, design_refs)
    if figma_reason:
        return figma_reason

    quotas = ((cfg.get("agent") or {}).get("quotas") or {})
    global_daily = _quota_value(quotas.get("global_daily"))
    per_user_daily = _quota_value(quotas.get("per_user_daily"))
    if global_daily is None and per_user_daily is None:
        return None

    today = datetime.now(timezone.utc).date().isoformat()
    dispatched = _today_dispatches(led, today)
    if global_daily is not None and len(dispatched) >= global_daily:
        return f"Queued for review - the daily agent budget is spent (global_daily={global_daily})."

    if per_user_daily is not None and not _trusted_user(cfg, entry):
        user = _user_key(entry)
        used = sum(1 for e in dispatched if _user_key(e) == user)
        if used >= per_user_daily:
            return f"Queued for review - this account's daily agent budget is spent (per_user_daily={per_user_daily})."

    return None


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
    dispatched = 0
    for key, entry in items:
        eid = entry.get("id")
        who = (entry.get("user") or {}).get("name") or "anonymous"
        snippet = " ".join((entry.get("comment") or "").split())[:80] or f"★{entry.get('stars')}"
        print(f"curiator: ● new feedback on {_label(key)} by {who} — {snippet!r}", flush=True)
        reason = _dispatch_hold_reason(cfg, ledger.load(cfg), key, entry)
        if reason:
            _hold_feedback(cfg, key, entry, reason)
            print(f"curiator:   • {key}/{eid} → held · {reason}", flush=True)
            continue
        try:
            task = adapters.build_task(cfg, key, entry)  # writes a task file, returns its path + bundle
        except Exception as exc:
            from ..proposals import ProposalError

            if not isinstance(exc, ProposalError):
                raise
            text = f"Agent dispatch held because a per-run proposal workspace could not be prepared: {exc}"
            _hold_feedback(cfg, key, entry, text)
            print(f"curiator:   ! {key}/{eid} -> held (proposal setup failed: {exc})", flush=True)
            continue
        prof = task.agent or {}
        elevated = "  ⚡ELEVATED" if prof.get("elevated") else ""
        runlog.init_trace(task, adapter_name)
        runlog.note(task, "task bundle written; checkpointing writable source scope")
        try:
            checkpoint = run_recovery.create_checkpoint(task, adapter_name)
        except Exception as exc:
            text = (
                f"Agent dispatch refused because a trustworthy source checkpoint could not be created: {exc}. "
                "Source files were left untouched."
            )
            runlog.note(task, text)
            _recovery_note(cfg, key, entry, text, status="held")
            print(f"curiator:   ! {key}/{eid} -> held (checkpoint failed: {exc})", flush=True)
            continue
        runlog.note(task, f"source checkpoint {checkpoint['run_id']} written; setting status to working")
        ledger.update_entry(cfg, key, eid, {"status": "working", "dispatched_at": _now()})
        print(f"curiator:   ▶ launching {adapter_name} on {key}/{eid} "
              f"(autonomy={prof.get('autonomy', 'auto-small')}){elevated}", flush=True)
        runlog.note(task, f"status set to working; launching {adapter_name}")
        runlog.clear_cancel(cfg, eid)                    # drop any stale Stop marker before a fresh run
        dispatched += 1
        try:
            adapter.run(task)                            # the agent edits + smoke-tests + replies
            st, reply = _outcome(cfg, key, eid)
            run_recovery.record_process_end(cfg, eid, f"adapter returned with ledger status {st}")
            tail = f' · "{reply[:72]}"' if reply else ""
            runlog.note(task, f"ledger status after run: {st}")
            if reply:
                runlog.note(task, f"agent reply: {reply}")
            if st == "working":
                st, _ = _classify_ended_run(cfg, key, entry, "adapter exited without a completion reply")
            else:
                run_recovery.complete_checkpoint(cfg, eid, st)
            print(f"curiator:   {'✓' if st != 'working' else '⚠'} {key}/{eid} → {st}{tail}", flush=True)
        except runlog.AgentInterrupted as exc:
            print(f"curiator:   ✗ {key}/{eid} interrupted: {exc}", flush=True)
            runlog.note(task, f"agent interrupted: {exc}")
            _classify_ended_run(cfg, key, entry, f"agent interrupted by service shutdown ({exc})")
            raise
        except runlog.AgentCancelled:                     # the Stop button — park it, don't retry
            runlog.clear_cancel(cfg, eid)
            runlog.note(task, "cancelled by user; parked as held")
            _classify_ended_run(cfg, key, entry, "run stopped by user", hold_even_if_unchanged=True)
            print(f"curiator:   ⏹ {key}/{eid} → held (stopped by user)", flush=True)
        except runlog.AgentTimeout as exc:                # taking a while — cap the retries, then park
            attempts = int(entry.get("timeout_attempts") or 0) + 1
            cap = _quota_value((cfg.get("agent") or {}).get("max_timeouts"))
            cap = 2 if cap is None else cap
            runlog.note(task, f"{exc} (attempt {attempts}/{cap})")
            _, report = _classify_ended_run(cfg, key, entry, str(exc))
            if report is None:
                ledger.update_entry(cfg, key, eid, {"status": "held", "timeout_attempts": attempts})
                print(f"curiator:   ⏱ {key}/{eid} → held (checkpoint unavailable after timeout)", flush=True)
            elif report.get("source_delta"):
                ledger.update_entry(cfg, key, eid, {"status": "held", "timeout_attempts": attempts})
                print(f"curiator:   ⏱ {key}/{eid} → held (partial source after timeout)", flush=True)
            elif attempts >= cap:
                ledger.add_system_note(
                    cfg, key,
                    f"⏱ Stopped at the {exc.timeout}s time limit again (attempt {attempts}/{cap}). Parked as "
                    "**held** — raise `agent.timeout` for longer runs or narrow the request, then re-run from "
                    "the queue.", reply_to=[eid], agent="curiator watcher")
                ledger.update_entry(cfg, key, eid, {"status": "held", "timeout_attempts": attempts})
                print(f"curiator:   ⏱ {key}/{eid} → held (hit the {exc.timeout}s limit {attempts}×)", flush=True)
            else:
                ledger.add_system_note(
                    cfg, key,
                    f"⏱ Taking longer than the {exc.timeout}s limit — stopped and requeued to try again "
                    f"(attempt {attempts}/{cap}). Raise `agent.timeout` to allow longer runs.",
                    reply_to=[eid], agent="curiator watcher")
                ledger.update_entry(cfg, key, eid, {"status": "new", "timeout_attempts": attempts})
                print(f"curiator:   ⏱ {key}/{eid} → requeued (hit the {exc.timeout}s limit, attempt {attempts}/{cap})", flush=True)
        except Exception as exc:                          # never leave an item stuck on 'working'
            print(f"curiator:   ✗ {key}/{eid} failed: {exc}", flush=True)
            runlog.note(task, f"loop error: {exc}")
            status, _ = _classify_ended_run(cfg, key, entry, f"loop error: {exc}")
            ledger.add_system_note(cfg, key, f"⚙ loop error: {exc}; recovery status: {status}", reply_to=[eid])
    return dispatched


def watch(cfg: dict) -> None:
    """Long-running poll loop. Ctrl-C to stop. Re-reads gallery.yaml when it changes, so config edits
    (autonomy, `agent.elevated`, …) apply live — no restart needed."""
    print(f"curiator: watching {ledger.path(cfg)} every {POLL_SECONDS}s "
          f"(adapter={cfg.get('agent', {}).get('adapter')}, "
          f"autonomy={cfg.get('agent', {}).get('autonomy')}) — Ctrl-C to stop", flush=True)
    recovered = recover_interrupted_working(cfg)
    if recovered["total"]:
        print(
            f"curiator: recovered {recovered['total']} interrupted working item(s); "
            f"{recovered['requeued']} safely requeued, {recovered['held']} held for recovery",
            flush=True,
        )
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
