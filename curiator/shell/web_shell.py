"""web_shell.py — Flask + React overlay shell.

The overlay UI is framework-neutral; Dash remains an app mount type (`dash-inproc`), not the shell
framework. This module reuses the app/proxy supervisor and ledger helpers from app_shell while serving
a React UI and JSON API from plain Flask.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import shlex
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, jsonify, redirect, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from curiator.shell import app_shell as core
from curiator import auth, ledger
from curiator.agent_capabilities import agent_report
from curiator.design_refs import DesignReferenceError
from curiator.transcripts import bounded_text, clean_transcript_segments
from curiator.web_paths import PrefixMiddleware, normalize_base_path, public_path


BASE_PATH = normalize_base_path(core.REG.SHELL_CFG.get("base_path"))
_PREVIEW_SUFFIXES = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


def _url(path: str = "/") -> str:
    return public_path(BASE_PATH, path)


def _dash_deps_dir() -> Path:
    import dash
    return Path(dash.__file__).resolve().parent / "deps"


def _safe_entry(entry: dict) -> dict:
    out = dict(entry)
    if entry.get("screenshot"):
        out["shot_url"] = _url(f"/feedback-shot/{Path(entry['screenshot']).name}")
    if entry.get("audio"):
        out["audio_url"] = _url(f"/feedback-audio/{Path(entry['audio']).name}")
    trace = core._trace_path(entry.get("id"))
    if trace and trace.exists():
        out["trace_url"] = _url(f"/feedback-trace/{entry.get('id')}")
    out["replay_eligible"] = bool(
        entry.get("id") and entry.get("kind") != "system" and entry.get("status") == "done"
    )
    return out


def _anonymous_entry(entry: dict) -> bool:
    user = entry.get("user") or {}
    identities = {
        str(value or "").strip().lower()
        for value in (user.get("id"), user.get("email"), entry.get("author"))
    }
    return bool(
        identities & {"anonymous", "anonymous@local"}
        or str(user.get("name") or "").strip().lower() == "anonymous"
    )


def _visible_feedback_items(items: list[dict]) -> list[dict]:
    """Hide unpromoted anonymous threads from every non-admin response surface."""
    user = auth.current_user(core.REG.AUTH_CFG)
    if auth.is_admin(core.REG.AUTH_CFG, user):
        return list(items)
    hidden_ids = {
        entry["id"]
        for entry in items
        if entry.get("id")
        and _anonymous_entry(entry)
        and not entry.get("moderation_approved_at")
    }
    changed = True
    while changed:
        changed = False
        for entry in items:
            entry_id = entry.get("id")
            if entry_id and entry_id not in hidden_ids and any(
                parent in hidden_ids for parent in (entry.get("reply_to") or [])
            ):
                hidden_ids.add(entry_id)
                changed = True
    return [entry for entry in items if entry.get("id") not in hidden_ids]


def _metrics(key: str) -> dict:
    avg, n_open, n_total = core.metrics_from(
        _visible_feedback_items(core.load_feedback().get(key, []))
    )
    return {"avg_stars": avg, "open": n_open, "total": n_total}


def _plain_text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _preview_path(rec: dict) -> Path | None:
    raw = rec.get("preview")
    if not raw:
        return None
    root = Path(core.REG.COLLECTION_ROOT).resolve()
    path = Path(str(raw)).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    if path.suffix.lower() not in _PREVIEW_SUFFIXES or not path.is_file():
        return None
    return path


def _home_payload() -> dict:
    raw = core.REG.CONFIG.get("home") or {}
    known = [rec["key"] for rec in core.REGISTRY]
    requested = raw.get("featured") or []
    if isinstance(requested, str):
        requested = [requested]
    featured = []
    for key in requested if isinstance(requested, (list, tuple)) else []:
        key = str(key)
        if key in known and key not in featured:
            featured.append(key)
    if not featured:
        featured = known[:4]
    try:
        activity_limit = int(raw.get("activity_limit", 8))
    except (TypeError, ValueError):
        activity_limit = 8
    return {
        "kicker": _plain_text(raw.get("kicker") or "Collection home", 60),
        "description": _plain_text(
            raw.get("description") or f"Apps, feedback, and recent work in {core.COLLECTION_NAME}.",
            360,
        ),
        "featured": featured[:8],
        "activity_limit": max(3, min(activity_limit, 24)),
    }


def _activity_actor(entry: dict) -> str:
    if entry.get("kind") == "system" or entry.get("author") == "claude":
        return _plain_text(entry.get("agent") or "Agent", 80)
    user = entry.get("user") or {}
    return _plain_text(user.get("name") or user.get("email") or entry.get("author") or "user", 80)


def _activity_excerpt(entry: dict, limit: int = 210) -> str:
    text = _plain_text(entry.get("comment"), limit)
    if not text and entry.get("stars"):
        text = "★" * int(entry.get("stars") or 0)
    return text


def _activity_payload(limit: int = 50) -> dict:
    rows = []
    data = core.load_feedback()
    for key, raw_entries in data.items():
        entries = _visible_feedback_items(raw_entries)
        roots, children, order = core._thread_tree(entries)
        rec = core.BY_KEY.get(key, {})

        def collect(entry: dict) -> list[dict]:
            thread = [entry]
            for child in children.get(entry.get("id"), []):
                thread.extend(collect(child))
            return thread

        for root in roots:
            thread = collect(root)
            latest = max(
                thread,
                key=lambda entry: (
                    core._parse_history_ts(entry.get("ts")) or datetime.min.replace(tzinfo=timezone.utc),
                    order.get(entry.get("id"), -1),
                ),
            )
            statuses = {
                entry.get("status") for entry in thread
                if entry.get("kind") != "system" and entry.get("status")
            }
            root_excerpt = _activity_excerpt(root)
            latest_excerpt = _activity_excerpt(latest, 150) if latest is not root else ""
            rows.append({
                "id": root.get("id"),
                "app_key": key,
                "app_title": "General feedback" if key == core.GENERAL_KEY else rec.get("title", key),
                "app_color": rec.get("color", core.PURPLE if key == core.GENERAL_KEY else "#777"),
                "port": rec.get("port"),
                "status": root.get("status"),
                "comment": root_excerpt or latest_excerpt,
                "latest_comment": latest_excerpt if latest_excerpt != root_excerpt else "",
                "author": _activity_actor(root),
                "latest_author": _activity_actor(latest),
                "updated_at": latest.get("ts") or root.get("ts"),
                "reply_count": max(len(thread) - 1, 0),
                "stars": root.get("stars"),
                "is_general": key == core.GENERAL_KEY,
                "active": bool(statuses & core.ACTIVE_STATUSES),
                "open": bool(statuses & core.OPEN_STATUSES),
            })
    rows.sort(
        key=lambda row: core._parse_history_ts(row.get("updated_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return {
        "items": rows[:max(1, min(limit, 50))],
        "counts": {
            "total": len(rows),
            "active": sum(1 for row in rows if row["active"]),
            "open": sum(1 for row in rows if row["open"]),
        },
    }


def _apps_payload() -> list[dict]:
    core.refresh_changed_app_sources()
    feedback = core.load_feedback()               # one ledger read for all apps' metrics + updated ts
    apps = []
    for rec in core.REGISTRY:
        items = _visible_feedback_items(feedback.get(rec["key"], []))
        avg, n_open, n_total = core.metrics_from(items)
        apps.append({
            "key": rec["key"],
            "title": rec.get("title", rec["key"]),
            "summary": _plain_text(rec.get("summary"), 320),
            "preview_url": _url(f"/app-preview/{quote(rec['key'], safe='')}") if _preview_path(rec) else None,
            "tags": rec.get("tags") or [],
            "color": rec.get("color", "#888"),
            "kind": rec.get("kind"),
            "port": rec.get("port"),
            "source": rec.get("source") or rec.get("file"),
            "root": rec.get("root"),
            "proposal": rec.get("proposal"),
            "metrics": {"avg_stars": avg, "open": n_open, "total": n_total},
            "updated": core.app_updated(rec, items),
            "revision": core.APP_REVISIONS.get(rec["key"], 0),
        })
    return apps


def _general_payload() -> dict:
    return {
        "key": core.GENERAL_KEY,
        "title": "Collection feedback",
        "tags": [],
        "color": "#8e44ad",
        "kind": "general",
        "metrics": _metrics(core.GENERAL_KEY),
    }


def _feedback_payload(key: str) -> dict:
    items = [_safe_entry(e) for e in _visible_feedback_items(core.load_feedback().get(key, []))]
    tb = core.thread_buttons(items)
    actions = {"target": tb[0], "items": tb[1]} if tb else None
    return {"key": key, "items": items, "actions": actions}


def _queue_actor(user: dict | None) -> str:
    user = user or {}
    return user.get("email") or user.get("name") or user.get("id") or "shell admin"


def _queue_action_url(feedback_id: str, action: str) -> str:
    return _url(f"/queue/{quote(str(feedback_id), safe='')}/{action}")


def _queue_find(feedback_id: str) -> tuple[str, dict] | None:
    for key, items in core.load_feedback().items():
        for entry in items:
            if entry.get("id") == feedback_id:
                return key, entry
    return None


class ModerationError(RuntimeError):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def _valid_feedback_id(feedback_id: object) -> bool:
    value = str(feedback_id or "")
    return value not in {".", ".."} and bool(re.fullmatch(r"[0-9A-Za-z._-]+", value))


def _held_entry(key: str, feedback_id: str) -> dict:
    if not _valid_feedback_id(feedback_id):
        raise ModerationError("feedback not found", 404)
    entry = next(
        (item for item in core.load_feedback().get(key, []) if item.get("id") == feedback_id),
        None,
    )
    if entry is None:
        raise ModerationError("feedback not found", 404)
    if entry.get("kind") == "system" or entry.get("status") != "held":
        raise ModerationError("only held user feedback can be moderated")
    return entry


def _awaiting_approval_entry(key: str, feedback_id: str) -> dict:
    if not _valid_feedback_id(feedback_id):
        raise ModerationError("feedback not found", 404)
    entry = next(
        (item for item in core.load_feedback().get(key, []) if item.get("id") == feedback_id),
        None,
    )
    if entry is None:
        raise ModerationError("feedback not found", 404)
    if entry.get("kind") == "system" or entry.get("status") != "awaiting_approval":
        raise ModerationError("only user feedback awaiting approval can be reviewed")
    return entry


def _approval_plan_entry(key: str, feedback_id: str) -> dict | None:
    """Newest agent note in this approval subtree, independent of ledger row order."""
    items = core.load_feedback().get(key, [])
    related = {feedback_id}
    changed = True
    while changed:
        changed = False
        for item in items:
            item_id = item.get("id")
            if item_id and item_id not in related and related.intersection(item.get("reply_to") or []):
                related.add(item_id)
                changed = True
    candidates = [
        item for item in items
        if item.get("id") in related
        and item.get("id") != feedback_id
        and (item.get("kind") == "system" or item.get("author") == "claude")
        and not str(item.get("agent") or "").startswith("curiator ")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: str(item.get("ts") or ""))


def _plan_uses_proposal_actions(plan: dict | None) -> bool:
    return any(
        str(row[1] if isinstance(row, (list, tuple)) and len(row) > 1 else "").startswith(
            "curiator-proposal:"
        )
        for row in ((plan or {}).get("actions") or [])
    )


def _dispatch_approved_plan(
    key: str,
    entry: dict,
    user: dict | None,
    *,
    amendment: str | None = None,
) -> dict:
    feedback_id = entry["id"]
    _moderation_checkpoint_guard([feedback_id])
    plan = _approval_plan_entry(key, feedback_id)
    if _plan_uses_proposal_actions(plan):
        raise ModerationError("use the proposal Approve/Reject actions for this branch proposal")

    text = str(amendment or "").strip()
    if amendment is not None and not text:
        raise ModerationError("enter an amendment before replying", 400)
    if len(text) > 10000:
        raise ModerationError("amendment is too long", 400)

    actor = _queue_actor(user)
    approved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    dispatch_id = uuid.uuid4().hex[:8]
    plan_id = (plan or {}).get("id") or feedback_id
    resolution = "amended" if amendment is not None else "approved"
    dispatch_comment = text or f"Approved by {actor}."

    # Keep the dispatch held until the approval decision, audit note, and reply link are durable.
    ledger.save_entry(
        core.LEDGER_CFG,
        key,
        entry_id=dispatch_id,
        comment=dispatch_comment,
        user=auth.stamp(user),
        extra={
            "status": "held",
            "reply_to": [plan_id],
            "approval_of": feedback_id,
            "approval_plan_id": plan_id,
            "approval_scope": "collection",
            "approval_resolution": resolution,
            "approval_authorized_at": approved_at,
            "approval_authorized_by": actor,
        },
    )
    ledger.add_system_note(
        core.LEDGER_CFG,
        key,
        (
            f"Approval review: approved with an amendment by {actor}; dispatching the authorized reply."
            if amendment is not None else
            f"Approval review: approved by {actor}; dispatching the authorized plan."
        ),
        reply_to=[feedback_id],
        agent="curiator approvals",
    )
    ledger.update_entry(core.LEDGER_CFG, key, feedback_id, {
        "status": "done",
        "approval_resolution": resolution,
        "approval_dispatch_id": dispatch_id,
        "approval_authorized_at": approved_at,
        "approval_authorized_by": actor,
    })
    ledger.update_entry(core.LEDGER_CFG, key, dispatch_id, {"status": "new"})
    return next(item for item in core.load_feedback()[key] if item.get("id") == dispatch_id)


def _reject_approved_plan(key: str, entry: dict, user: dict | None) -> dict:
    feedback_id = entry["id"]
    _moderation_checkpoint_guard([feedback_id])
    actor = _queue_actor(user)
    rejected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ledger.add_system_note(
        core.LEDGER_CFG,
        key,
        f"Approval review: rejected by {actor}; closed without agent dispatch.",
        reply_to=[feedback_id],
        agent="curiator approvals",
    )
    ledger.update_entry(core.LEDGER_CFG, key, feedback_id, {
        "status": "rejected",
        "approval_resolution": "rejected",
        "approval_authorized_at": rejected_at,
        "approval_authorized_by": actor,
    })
    return next(item for item in core.load_feedback()[key] if item.get("id") == feedback_id)


def _moderation_checkpoint_guard(feedback_ids: list[str]) -> None:
    from curiator import run_recovery

    if any(not _valid_feedback_id(feedback_id) for feedback_id in feedback_ids):
        raise ModerationError("thread contains an invalid feedback id")
    blocked = [
        feedback_id
        for feedback_id in feedback_ids
        if run_recovery.checkpoint_path(core.LEDGER_CFG, feedback_id).exists()
    ]
    if blocked:
        raise ModerationError(
            "resolve interrupted run recovery before moderating this item"
        )


def _approve_held(key: str, entry: dict, user: dict | None) -> dict:
    feedback_id = entry["id"]
    _moderation_checkpoint_guard([feedback_id])
    actor = _queue_actor(user)
    approved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ledger.add_system_note(
        core.LEDGER_CFG,
        key,
        f"Moderation queue: approved by {actor}; dispatching to the agent.",
        reply_to=[feedback_id],
        agent="curiator queue",
    )
    ledger.update_entry(core.LEDGER_CFG, key, feedback_id, {
        "status": "new",
        "moderation_approved_at": approved_at,
        "moderation_approved_by": actor,
        "moderation_resolution": "approved",
    })
    return next(item for item in core.load_feedback()[key] if item.get("id") == feedback_id)


def _amend_held(key: str, entry: dict, user: dict | None, comment: str) -> dict:
    amendment = str(comment or "").strip()
    if not amendment:
        raise ModerationError("enter an amendment before replying", 400)
    if len(amendment) > 10000:
        raise ModerationError("amendment is too long", 400)

    feedback_id = entry["id"]
    _moderation_checkpoint_guard([feedback_id])
    actor = _queue_actor(user)
    approved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    amendment_id = uuid.uuid4().hex[:8]

    ledger.update_entry(core.LEDGER_CFG, key, feedback_id, {
        "status": "done",
        "moderation_approved_at": approved_at,
        "moderation_approved_by": actor,
        "moderation_resolution": "amended",
        "moderation_amendment_id": amendment_id,
    })
    ledger.add_system_note(
        core.LEDGER_CFG,
        key,
        f"Moderation queue: approved with an amendment by {actor}; dispatching the admin reply.",
        reply_to=[feedback_id],
        agent="curiator queue",
    )
    # Insert as held, then promote only after the original and moderation note are durable. This keeps
    # the watcher from claiming the amendment before its thread context is complete.
    ledger.save_entry(
        core.LEDGER_CFG,
        key,
        entry_id=amendment_id,
        comment=amendment,
        user=auth.stamp(user),
        extra={
            "status": "held",
            "reply_to": [feedback_id],
            "moderation_amends": feedback_id,
        },
    )
    ledger.update_entry(core.LEDGER_CFG, key, amendment_id, {
        "status": "new",
        "moderation_approved_at": approved_at,
        "moderation_approved_by": actor,
        "moderation_resolution": "amendment",
    })
    return next(item for item in core.load_feedback()[key] if item.get("id") == amendment_id)


def _feedback_subtree(key: str, feedback_id: str) -> tuple[list[str], list[dict]]:
    items = core.load_feedback().get(key, [])
    ids = {feedback_id}
    changed = True
    while changed:
        changed = False
        for item in items:
            item_id = item.get("id")
            if item_id and item_id not in ids and any(
                parent in ids for parent in (item.get("reply_to") or [])
            ):
                ids.add(item_id)
                changed = True
    selected = [item for item in items if item.get("id") in ids]
    return [item.get("id") for item in selected if item.get("id")], selected


def _feedback_artifact_path(ref: object) -> Path | None:
    raw = str(ref or "").strip()
    if not raw or "://" in raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = core.FEEDBACK_DIR / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(core.FEEDBACK_DIR.resolve())
    except (OSError, ValueError):
        return None
    return resolved


def _delete_feedback_artifacts(entries: list[dict]) -> None:
    from curiator import run_recovery
    from curiator.loop import runlog

    remaining_refs = {
        str(entry.get(field))
        for items in core.load_feedback().values()
        for entry in items
        for field in ("screenshot", "audio")
        if entry.get(field)
    }
    for entry in entries:
        for field in ("screenshot", "audio"):
            ref = entry.get(field)
            path = _feedback_artifact_path(ref)
            if path is not None and str(ref) not in remaining_refs:
                try:
                    path.unlink()
                except OSError:
                    pass
        feedback_id = entry.get("id")
        if not _valid_feedback_id(feedback_id):
            continue
        for path in (
            runlog.task_path(core.LEDGER_CFG, feedback_id),
            runlog.reply_path(core.LEDGER_CFG, feedback_id),
            runlog.cancel_path(core.LEDGER_CFG, feedback_id),
        ):
            try:
                path.unlink()
            except OSError:
                pass
        shutil.rmtree(run_recovery.run_dir(core.LEDGER_CFG, feedback_id), ignore_errors=True)


def _delete_held(key: str, entry: dict) -> dict:
    feedback_ids, entries = _feedback_subtree(key, entry["id"])
    active = [
        item.get("id")
        for item in entries
        if item.get("id") != entry["id"]
        and item.get("kind") != "system"
        and item.get("status") in {"new", "working", "awaiting_approval"}
    ]
    if active:
        raise ModerationError(
            "cannot delete a held thread with active descendant work"
        )
    _moderation_checkpoint_guard(feedback_ids)
    deleted = ledger.delete_entries(core.LEDGER_CFG, key, feedback_ids)
    _delete_feedback_artifacts(entries)
    # SQLite free pages can retain deleted payload bytes. A UI delete is a privacy boundary, so purge
    # those pages instead of waiting for a later maintenance command.
    ledger.compact(core.LEDGER_CFG)
    return {"deleted": deleted, "ids": feedback_ids}


def _queue_rows() -> list[tuple[str, dict]]:
    rows = []
    for key, items in core.load_feedback().items():
        for entry in items:
            if entry.get("kind") != "system" and entry.get("status") == "held":
                rows.append((key, entry))
    return rows


def _queue_app_title(key: str) -> str:
    if key == core.GENERAL_KEY:
        return "General"
    rec = next((item for item in core.REGISTRY if item.get("key") == key), {})
    return rec.get("title") or key


def _queue_page_html(message: str = "") -> str:
    rows = _queue_rows()
    msg = (f"<p style='color:{core.GREEN};font-size:13px'>{core._esc(message)}</p>" if message else "")
    if not rows:
        return msg + "<p style='color:#777;font-size:13px'>No held feedback is waiting for review.</p>"
    cards = []
    for key, entry in rows:
        from curiator import run_recovery

        user = entry.get("user") or {}
        author = user.get("email") or user.get("name") or entry.get("author") or "user"
        stars = "★" * int(entry.get("stars") or 0)
        shot = ""
        if entry.get("screenshot"):
            shot_url = _url(f"/feedback-shot/{quote(Path(entry['screenshot']).name)}")
            shot = (f"<img src='{shot_url}' "
                    "style='display:block;max-width:420px;margin-top:8px;border:1px solid #ddd;"
                    "border-radius:4px'>")
        feedback_id = entry.get("id") or ""
        recovery = None
        if run_recovery.checkpoint_path(core.LEDGER_CFG, feedback_id).exists():
            try:
                recovery = run_recovery.recovery_report(core.LEDGER_CFG, feedback_id)
            except run_recovery.CheckpointError:
                recovery = {"restore_safe": False, "reason": "checkpoint is unreadable"}
        if recovery:
            changed = recovery.get("agent_run_paths") or []
            conflicts = recovery.get("post_interruption_paths") or []
            restore_disabled = "" if recovery.get("restore_safe") else " disabled title='Source changed after process end'"
            recovery_controls = (
                "<div style='margin-top:9px;padding-top:8px;border-top:1px solid #ddd'>"
                "<div style='font-size:12px;font-weight:700;color:#6f42c1'>Interrupted run recovery</div>"
                f"<div style='font-size:12px;color:#666;margin:3px 0 7px'>{len(changed)} run path(s) · "
                f"{len(conflicts)} post-interruption path(s) · restore "
                f"{'available' if recovery.get('restore_safe') else 'disabled'}</div>"
                f"<form method='post' action='{_queue_action_url(feedback_id, 'resume')}' style='display:inline'>"
                "<button style='margin-right:5px'>Resume</button></form>"
                f"<form method='post' action='{_queue_action_url(feedback_id, 'preserve')}' style='display:inline'>"
                "<button style='margin-right:5px'>Preserve branch</button></form>"
                f"<form method='post' action='{_queue_action_url(feedback_id, 'restore')}' style='display:inline'>"
                f"<button style='margin-right:5px'{restore_disabled}>Restore baseline</button></form>"
                f"<form method='post' action='{_queue_action_url(feedback_id, 'discard-checkpoint')}' "
                "style='display:inline'><button>Keep files</button></form></div>"
            )
            approve = ""
            delete = ""
        else:
            recovery_controls = ""
            approve = (
                f"<form method='post' action='{_queue_action_url(feedback_id, 'approve')}' "
                "style='display:inline-block;margin-top:8px;margin-right:8px'>"
                "<button style='background:#1f9d55;color:white;border:none;border-radius:5px;"
                "padding:6px 13px;font-weight:700;cursor:pointer'>Approve</button></form>"
            )
            delete = (
                f"<form method='post' action='{_queue_action_url(feedback_id, 'delete')}' "
                "style='display:inline-block;margin-top:8px;margin-right:8px' "
                "onsubmit=\"return confirm('Delete this held thread permanently?')\">"
                "<button style='background:white;color:#a33;border:1px solid #d9b3b3;border-radius:5px;"
                "padding:5px 13px;font-weight:700;cursor:pointer'>Delete</button></form>"
            )
        cards.append(
            "<section style='border-left:4px solid #6f42c1;background:#fafafa;"
            "padding:10px 12px;margin:0 0 12px;border-radius:4px'>"
            f"<div style='font-size:12px;color:#777'><b>{core._esc(_queue_app_title(key))}</b> "
            f"<code>{core._esc(key)}</code> · <code>{core._esc(entry.get('id') or '')}</code> · "
            f"{core._esc(entry.get('ts') or '')}</div>"
            f"<div style='font-size:12px;color:#777;margin-top:2px'>{core._esc(author)} "
            f"<span style='color:#cc7a00'>{stars}</span></div>"
            f"<p style='font-size:14px;white-space:pre-wrap'>{core._esc(entry.get('comment') or '')}</p>"
            f"{shot}"
            f"{recovery_controls}{approve}{delete}"
            f"<form method='post' action='{_queue_action_url(entry.get('id') or '', 'reject')}' "
            "style='display:inline-flex;gap:6px;align-items:center;margin-top:8px'>"
            "<input name='reason' placeholder='optional rejection reason' "
            "style='font:inherit;font-size:12px;border:1px solid #ccc;border-radius:5px;padding:6px;width:220px'>"
            "<button style='background:#555;color:white;border:none;border-radius:5px;"
            "padding:6px 13px;font-weight:700;cursor:pointer'>Reject</button></form>"
            "</section>"
        )
    return msg + "".join(cards)


def _feedback_user_and_status(rate_limit_key: str | None = None) -> tuple[dict | None, str, str | None, int]:
    u = core._current_user()
    if auth.feedback_requires_identity(core.REG.AUTH_CFG) and not u:
        if not auth.allow_anonymous_feedback(core.REG.AUTH_CFG):
            return None, "new", "sign in required", 401
        key = rate_limit_key or request.remote_addr or "?"
        blocked, retry = auth.anonymous_feedback_rate_limit_status(core.REG.AUTH_CFG, key)
        if blocked:
            return None, "new", f"too many anonymous submissions; try again in {retry}s", 429
        auth.record_anonymous_feedback(core.REG.AUTH_CFG, key)
        return auth.anonymous_user(), "held", None, 0
    return u, "new", None, 0


def _voice_cfg() -> dict:
    cfg = getattr(core.REG, "VOICE_CFG", None)
    if not isinstance(cfg, dict):
        cfg = (getattr(core.REG, "CONFIG", {}) or {}).get("voice") or {}
    return cfg if isinstance(cfg, dict) else {}


def _voice_int(key: str, default: int, *, low: int, high: int) -> int:
    try:
        value = int(_voice_cfg().get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _voice_payload() -> dict:
    cfg = _voice_cfg()
    return {
        "local_transcribe": bool(cfg.get("transcribe_cmd")),
        "web_speech": bool(cfg.get("web_speech")),
        "web_speech_lang": str(cfg.get("web_speech_lang") or ""),
        "retain_audio": bool(cfg.get("retain_audio")),
        "max_bytes": _voice_int("transcribe_max_bytes", 25 * 1024 * 1024, low=1, high=200 * 1024 * 1024),
        "timeout": _voice_int("transcribe_timeout", 60, low=1, high=600),
    }


def _workspace_payload(row: dict) -> dict:
    payload = dict(row)
    if row.get("host_port"):
        payload["url"] = f"http://127.0.0.1:{row['host_port']}/?app={row['app_key']}"
    return payload


def _workspace_admin():
    user = auth.current_user(core.REG.AUTH_CFG)
    return user if auth.is_admin(core.REG.AUTH_CFG, user) else None


def _workspace_runtime_payload() -> dict | None:
    payload = None
    state_dir = (core.LEDGER_CFG.get("state_dir") or
                 (core.LEDGER_CFG.get("feedback") or {}).get("dir"))
    if state_dir:
        path = Path(state_dir) / "workspace.json"
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
            payload = candidate if isinstance(candidate, dict) else None
        except (OSError, json.JSONDecodeError):
            pass
    if payload is not None:
        return payload
    if not os.environ.get("CURIATOR_WORKSPACE_ID"):
        return None
    return {
        "id": os.environ.get("CURIATOR_WORKSPACE_ID"),
        "name": os.environ.get("CURIATOR_WORKSPACE_NAME"),
        "mode": os.environ.get("CURIATOR_WORKSPACE_MODE"),
        "base_sha": os.environ.get("CURIATOR_WORKSPACE_BASE_SHA"),
        "branch": os.environ.get("CURIATOR_WORKSPACE_BRANCH"),
        "control_url": os.environ.get("CURIATOR_WORKSPACE_CONTROL_URL"),
    }


def _transcribe_args(command, audio_path: Path) -> list[str]:
    sentinel = "__CURIATOR_AUDIO_PATH__"
    if isinstance(command, list):
        parts = [str(part) for part in command if str(part)]
        if not parts:
            return []
        has_audio = any("{audio}" in part for part in parts)
        args = [part.replace("{audio}", str(audio_path)) for part in parts]
        return args if has_audio else [*args, str(audio_path)]
    if not isinstance(command, str) or not command.strip():
        return []
    text = command.strip()
    if "{audio}" in text:
        return [part.replace(sentinel, str(audio_path))
                for part in shlex.split(text.replace("{audio}", sentinel))]
    return [*shlex.split(text), str(audio_path)]


def _parse_transcript(stdout: str) -> dict:
    raw = stdout.strip()
    if not raw:
        return {"text": "", "segments": []}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"text": bounded_text(raw, 10000), "segments": []}
    if isinstance(data, list):
        segments = clean_transcript_segments(data)
        return {"text": bounded_text(" ".join(s["text"] for s in segments), 10000), "segments": segments}
    if not isinstance(data, dict):
        return {"text": bounded_text(raw, 10000), "segments": []}
    segments = clean_transcript_segments(data.get("segments"))
    text = bounded_text(data.get("text"), 10000)
    if not text and segments:
        text = bounded_text(" ".join(s["text"] for s in segments), 10000)
    return {"text": text, "segments": segments}


def _transcribe_allowed() -> tuple[str | None, int]:
    if auth.feedback_requires_identity(core.REG.AUTH_CFG) and not core._current_user():
        if not auth.allow_anonymous_feedback(core.REG.AUTH_CFG):
            return "sign in required", 401
    return None, 0


NEW_APP_TYPES = {
    "dash": {
        "label": "Dash",
        "template": "dash",
        "guidance": "Use for Python-first research dashboards and Plotly/Dash interaction loops.",
    },
    "react_node": {
        "label": "React + Node",
        "template": "react",
        "guidance": "Use for component-heavy frontends or server-rendered JavaScript experiments.",
    },
    "rust": {
        "label": "Rust server",
        "template": "rust",
        "guidance": "Use for small compiled HTTP services, algorithm demos, or backend-first prototypes.",
    },
    "react_rust": {
        "label": "React + Rust",
        "template": "react",
        "guidance": "Start with a React app and add a Rust service/proxy only if the request needs one.",
    },
    "github_repo": {
        "label": "GitHub repo",
        "template": "react",
        "guidance": "Import an existing repository with `curiator app import`, then adapt its host settings.",
    },
    "pyodide_wasm": {
        "label": "Pyodide / WASM",
        "template": "static",
        "guidance": "Use a static app that offloads Python or compute-heavy work to Pyodide/WASM in the browser.",
    },
    "static": {
        "label": "Static HTML",
        "template": "static",
        "guidance": "Use for lightweight single-file explainers with no runtime server.",
    },
    "other": {
        "label": "Other (will try to accommodate)",
        "template": "python",
        "guidance": "Use the brief to choose the closest supported host; Python is only the fallback.",
    },
}


def _clean_wizard_text(value, limit: int) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()[:limit]


def _wizard_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _slug_app_key(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    text = re.sub(r"_+", "_", text)
    if not text or not re.match(r"^[a-z]", text):
        text = f"app_{text}" if text else "new_app"
    return text[:60].strip("_") or "new_app"


def _available_app_key(seed: str) -> str:
    base = _slug_app_key(seed)
    if base not in core.BY_KEY:
        return base
    for idx in range(2, 100):
        key = f"{base}_{idx}"
        if key not in core.BY_KEY:
            return key
    return f"{base}_{uuid.uuid4().hex[:4]}"


def _new_app_request(body: dict) -> tuple[dict | None, str | None]:
    if not isinstance(body, dict):
        return None, "invalid request"
    app_type = str(body.get("app_type") or "dash")
    spec = NEW_APP_TYPES.get(app_type)
    if not spec:
        return None, "unknown app type"
    title = _clean_wizard_text(body.get("title"), 120)
    prompt = _clean_wizard_text(body.get("prompt"), 5000)
    notes = _clean_wizard_text(body.get("notes"), 2000)
    repo_url = _clean_wizard_text(body.get("repo_url"), 500)
    raw_key = _clean_wizard_text(body.get("app_key"), 80)
    dockerize = _wizard_bool(body.get("dockerize"))
    if app_type == "github_repo" and not repo_url:
        return None, "enter a GitHub repo URL"
    if not prompt and app_type != "github_repo":
        return None, "describe the app to create"
    seed = raw_key or title or Path(repo_url.rstrip("/")).stem.replace(".git", "") or prompt.splitlines()[0][:80]
    title = title or seed.replace("_", " ").replace("-", " ").strip().title() or spec["label"] + " app"
    app_key = _available_app_key(seed)
    request = {
        "kind": "new_app",
        "app_key": app_key,
        "title": title,
        "app_type": app_type,
        "app_type_label": spec["label"],
        "template": spec["template"],
        "prompt": prompt,
        "notes": notes,
        "repo_url": repo_url,
        "dockerize": dockerize,
        "guidance": spec["guidance"],
        "source": "new_app_wizard",
    }
    return request, None


def _new_app_comment(request: dict) -> str:
    lines = [
        "Create a new curIAtor app.",
        "",
        "Wizard selections:",
        f"- suggested app key: `{request['app_key']}`",
        f"- title: {request['title']}",
        f"- app type: {request['app_type_label']}",
        f"- scaffold template: `{request['template']}`",
        f"- guidance: {request['guidance']}",
    ]
    if request.get("repo_url"):
        lines.append(f"- source repo: {request['repo_url']}")
    if request.get("dockerize"):
        lines.append("- packaging: Dockerize requested")
    lines += [
        "",
        "App brief:",
        request["prompt"] or "Import the source repo, inspect its stack, and host it as a curIAtor app.",
    ]
    if request.get("notes"):
        lines += ["", "Implementation notes:", request["notes"]]
    lines.append("")
    if request.get("repo_url"):
        lines.append(
            "Please start with `curiator app import` so the repo is cloned under `apps/` as a nested "
            "app repo/subrepo, proxy/smoke metadata is registered in `gallery.yaml`, and future edits "
            "stay scoped to that imported app."
        )
    else:
        lines.append(
            "Please start with `curiator app create` so app directories, proxy commands, smoke hooks, "
            "and `gallery.yaml` are created consistently; then customize the scaffold for this brief."
        )
    return "\n".join(lines)


def _index() -> str:
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{core._esc(core.TITLE)}</title>
    <link rel="icon" href="{_url('/assets/favicon.ico')}">
    <link rel="stylesheet" href="{_url('/assets/shell.css')}">
    <link rel="stylesheet" href="{_url('/assets/react_shell.css')}">
  </head>
  <body>
    <div id="react-entry-point"></div>
    <script>window.CURIATOR_BASE_PATH = {json.dumps(BASE_PATH)};</script>
    <script src="{_url('/vendor/react@18.3.1.min.js')}"></script>
    <script src="{_url('/vendor/react-dom@18.3.1.min.js')}"></script>
    <script src="{_url('/assets/html2canvas.min.js')}"></script>
    <script src="{_url('/assets/capture.js')}"></script>
    <script src="{_url('/assets/localtime.js')}"></script>
    <script src="{_url('/assets/react_shell.js')}"></script>
  </body>
</html>"""


def build_flask_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.secret_key = os.environ.get("CURIATOR_SECRET_KEY") or os.urandom(24)
    cookie_suffix = re.sub(r"[^a-z0-9]+", "_", BASE_PATH.lower()).strip("_")
    app.config.update(
        SESSION_COOKIE_NAME="curiator_session" + (f"_{cookie_suffix}" if cookie_suffix else ""),
        SESSION_COOKIE_PATH=(BASE_PATH + "/") if BASE_PATH else "/",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=bool(core.REG.SHELL_CFG.get("secure_cookies", False)),
    )

    mode = core.REG.AUTH_CFG.get("mode", "none")
    if mode == "oidc":
        auth.register_oidc(core.REG.AUTH_CFG, app)
    elif mode == "local":
        @app.route("/login", methods=["GET", "POST"])
        def _local_login():
            from flask import session
            ip = request.remote_addr or "?"
            err = ""
            blocked, retry = auth.rate_limit_status(core.REG.AUTH_CFG, ip)
            if request.method == "POST" and not blocked:
                u = auth.verify_local(core.REG.AUTH_CFG, request.form.get("email", ""), request.form.get("password", ""))
                if u:
                    auth.clear_login_failures(ip)
                    session[auth.SESSION_KEY] = u
                    return redirect(_url("/"))
                auth.record_login_failure(core.REG.AUTH_CFG, ip)
                blocked, retry = auth.rate_limit_status(core.REG.AUTH_CFG, ip)
                err = "" if blocked else "<p style='color:#c0392b;font-size:13px;margin:0 0 8px'>Invalid email or password.</p>"
            if blocked:
                err = f"<p style='color:#c0392b;font-size:13px;margin:0 0 8px'>Too many attempts — try again in {retry}s.</p>"
            return core._page("Sign in", err + ("" if blocked else core._LOGIN_FORM))

        @app.route("/logout")
        def _local_logout():
            from flask import session
            session.pop(auth.SESSION_KEY, None)
            return redirect(_url("/"))
    else:
        @app.route("/login")
        def _login_info():
            return core._page("Sign in", f"<p>Sign-in is not enabled for this gallery (<code>auth.mode: {mode}</code>).</p>")

        @app.route("/logout")
        def _logout_noop():
            return redirect(_url("/"))

    @app.route("/")
    def _root():
        return _index()

    @app.route("/vendor/<path:name>")
    def _vendor(name):
        allowed = {"react@18.3.1.min.js", "react-dom@18.3.1.min.js"}
        if name not in allowed:
            return ("not found", 404)
        return send_from_directory(_dash_deps_dir(), name)

    @app.route("/assets/<path:name>")
    def _assets(name):
        return send_from_directory(core.HERE / "assets", name, max_age=0)

    @app.route("/app-preview/<key>")
    def _app_preview(key):
        rec = core.BY_KEY.get(key)
        path = _preview_path(rec or {})
        if path is None:
            return ("not found", 404)
        return send_from_directory(path.parent, path.name, max_age=3600)

    @app.route("/api/bootstrap")
    def _bootstrap():
        u = auth.current_user(core.REG.AUTH_CFG)
        return jsonify({
            "title": core.TITLE,
            "collection": core.COLLECTION_NAME,
            "base_path": BASE_PATH,
            "general_key": core.GENERAL_KEY,
            "general": _general_payload(),
            "home": _home_payload(),
            "poll_ms": max(core.POLL_MS, 1000) if core.POLL_MS > 0 else 0,
            "apps": _apps_payload(),
            "tags": [{"name": k, "color": v} for k, v in core.TAG_META],
            "user": u or {"authenticated": False},
            "auth": {
                "mode": core.REG.AUTH_CFG.get("mode", "none"),
                "is_admin": auth.is_admin(core.REG.AUTH_CFG, u),
                "allow_anonymous": auth.allow_anonymous_feedback(core.REG.AUTH_CFG),
                "anonymous_feedback_max": core.REG.AUTH_CFG.get("anonymous_feedback_max"),
                "anonymous_feedback_window_seconds": core.REG.AUTH_CFG.get("anonymous_feedback_window_seconds"),
            },
            "voice": _voice_payload(),
            "agent_capabilities": agent_report(core.LEDGER_CFG).get("capabilities", {}),
            "workspace": _workspace_runtime_payload(),
        })

    @app.route("/api/apps")
    def _apps():
        return jsonify({"apps": _apps_payload(), "general": _general_payload()})

    @app.route("/api/activity")
    def _activity():
        try:
            limit = int(request.args.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        return jsonify(_activity_payload(limit))

    @app.route("/api/workspaces", methods=["GET", "POST"])
    def _workspaces():
        if not _workspace_admin():
            return jsonify({"error": "admin access required"}), 403
        from curiator.workspaces import WorkspaceError, WorkspaceManager

        manager = WorkspaceManager(core.LEDGER_CFG)
        if request.method == "GET":
            try:
                return jsonify({"workspaces": [_workspace_payload(row) for row in manager.list()]})
            except WorkspaceError as exc:
                return jsonify({"error": str(exc)}), 503
        body = request.get_json(silent=True) or {}
        try:
            row = manager.create(
                str(body.get("app") or ""),
                ref=str(body.get("ref") or "HEAD"),
                name=str(body.get("name") or "") or None,
                preview=bool(body.get("preview")),
                credentials=str(body.get("credentials") or "none"),
                agent_network=body.get("agent_network") is not False,
                agent_sandbox=str(body.get("agent_sandbox") or "container"),
                feedback_id=str(body.get("feedback_id") or "") or None,
                dispatch_feedback=bool(body.get("dispatch_feedback")),
                background=True,
            )
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"workspace": _workspace_payload(row)}), 202

    @app.route("/api/workspaces/<workspace_id>")
    def _workspace_detail(workspace_id):
        if not _workspace_admin():
            return jsonify({"error": "admin access required"}), 403
        from curiator.workspaces import WorkspaceError, WorkspaceManager

        manager = WorkspaceManager(core.LEDGER_CFG)
        try:
            row = manager.get(workspace_id)
            comparison = manager.diff(workspace_id) if request.args.get("diff") == "1" else None
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"workspace": _workspace_payload(row), "diff": comparison})

    @app.route("/api/workspaces/<workspace_id>/<action>", methods=["POST"])
    def _workspace_action(workspace_id, action):
        if not _workspace_admin():
            return jsonify({"error": "admin access required"}), 403
        from curiator.workspaces import WorkspaceError, WorkspaceManager

        manager = WorkspaceManager(core.LEDGER_CFG)
        body = request.get_json(silent=True) or {}
        try:
            if action == "start":
                row = manager.start(workspace_id)
            elif action == "stop":
                row = manager.stop(workspace_id)
            elif action == "edit":
                row = manager.start_editing(workspace_id, body.get("branch"))
            elif action == "keep":
                row = manager.keep(workspace_id, body.get("branch"))
            elif action == "apply":
                row = manager.apply(workspace_id)
            elif action == "delete":
                row = manager.delete(workspace_id, force=bool(body.get("force")))
            else:
                return jsonify({"error": "unknown workspace action"}), 404
        except WorkspaceError as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"workspace": _workspace_payload(row)})

    @app.route("/api/replays/inspect/<feedback_id>")
    def _replay_inspect(feedback_id):
        if not _workspace_admin():
            return jsonify({"error": "admin access required"}), 403
        from curiator.replay import ReplayError, inspect, redacted_report
        from curiator.replay_lab import profile_names

        try:
            report = redacted_report(inspect(core.LEDGER_CFG, feedback_id))
        except ReplayError as exc:
            return jsonify({"error": str(exc)}), 404
        report["profiles"] = profile_names(core.LEDGER_CFG)
        return jsonify({"replay": report})

    @app.route("/api/replays", methods=["GET", "POST"])
    def _replays():
        if not _workspace_admin():
            return jsonify({"error": "admin access required"}), 403
        from curiator.replay import ReplayError, inspect
        from curiator.replay_lab import list_groups, profile_names, redacted_group, run_group

        if request.method == "GET":
            return jsonify({"replays": [redacted_group(group) for group in list_groups(core.LEDGER_CFG)]})
        body = request.get_json(silent=True) or {}
        feedback_id = str(body.get("feedback_id") or "")
        profiles = body.get("profiles") or ["baseline"]
        if not isinstance(profiles, list) or not profiles or len(profiles) > 3:
            return jsonify({"error": "choose one to three replay profiles"}), 400
        profiles = [str(name) for name in profiles]
        unknown = sorted(set(profiles) - set(profile_names(core.LEDGER_CFG)))
        if unknown:
            return jsonify({"error": f"unknown replay profile(s): {', '.join(unknown)}"}), 400
        if len(profiles) > 1 and body.get("confirm_resources") is not True:
            return jsonify({"error": "confirm provider cost and Docker resources for multiple variants"}), 400
        try:
            report = inspect(core.LEDGER_CFG, feedback_id)
            if report.get("exactness") not in {"exact", "source-exact"} or not report.get("workspace_ready"):
                raise ReplayError(
                    f"feedback {feedback_id} is {report.get('exactness')}; source-exact replay is unavailable"
                )
        except ReplayError as exc:
            return jsonify({"error": str(exc)}), 400
        group_id = uuid.uuid4().hex[:10]
        thread = threading.Thread(
            target=run_group,
            kwargs={
                "cfg": core.LEDGER_CFG,
                "feedback_id": feedback_id,
                "profiles": profiles,
                "credentials": "auto",
                "wait_agent": True,
                "agent_network": body.get("agent_network") is not False,
                "agent_sandbox": str(body.get("agent_sandbox") or "container"),
                "group_id": group_id,
            },
            name=f"curiator-replay-{group_id}",
            daemon=True,
        )
        thread.start()
        return jsonify({"group_id": group_id, "status": "starting"}), 202

    @app.route("/api/replays/<group_id>")
    def _replay_detail(group_id):
        if not _workspace_admin():
            return jsonify({"error": "admin access required"}), 403
        from curiator.replay import ReplayError
        from curiator.replay_lab import refresh_group

        try:
            return jsonify({"replay": refresh_group(core.LEDGER_CFG, group_id)})
        except ReplayError as exc:
            return jsonify({"error": str(exc)}), 404

    @app.route("/api/replays/<group_id>/<action>", methods=["POST"])
    def _replay_action(group_id, action):
        if not _workspace_admin():
            return jsonify({"error": "admin access required"}), 403
        from curiator.replay import ReplayError
        from curiator.replay_lab import delete_group, keep_variant
        from curiator.workspaces import WorkspaceError

        body = request.get_json(silent=True) or {}
        try:
            if action == "keep":
                group = keep_variant(core.LEDGER_CFG, group_id, str(body.get("variant_id") or ""))
            elif action == "delete":
                group = delete_group(core.LEDGER_CFG, group_id, force=bool(body.get("force")))
            else:
                return jsonify({"error": "unknown replay action"}), 404
        except (ReplayError, WorkspaceError) as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"replay": group})

    @app.route("/api/replays/<group_id>/<variant_id>/screenshot")
    def _replay_screenshot(group_id, variant_id):
        if not _workspace_admin():
            return jsonify({"error": "admin access required"}), 403
        from curiator.replay import ReplayError
        from curiator.replay_lab import load_group
        from curiator.workspaces import WorkspaceError, WorkspaceManager

        try:
            group = load_group(core.LEDGER_CFG, group_id)
            variant = next(
                item for item in group.get("variants") or [] if item.get("id") == variant_id
            )
            results = (((variant.get("result") or {}).get("browser") or {}).get("results") or [])
            smoke = next(
                (item.get("browser_smoke") or {} for item in results if item.get("browser_smoke")), {}
            )
            path = str(smoke.get("screenshot") or "")
            prefix = "/workspace/state/"
            if not path.startswith(prefix):
                raise ReplayError("variant screenshot is unavailable")
            data = WorkspaceManager(core.LEDGER_CFG).state_file(
                str(variant.get("workspace_id") or ""), path[len(prefix):],
            )
            if not data:
                raise ReplayError("variant screenshot is unavailable")
        except (StopIteration, ReplayError, WorkspaceError) as exc:
            return jsonify({"error": str(exc)}), 404
        return Response(data, mimetype="image/png")

    @app.route("/profile")
    def _profile():
        u = auth.current_user(core.REG.AUTH_CFG) or {}
        mode = core.REG.AUTH_CFG.get("mode", "none")
        btn = (f"display:inline-block;background:{core.PURPLE};color:white;text-decoration:none;"
               "padding:6px 14px;border-radius:6px;font-weight:600;font-size:13px")
        info = (f"<p style='font-size:15px'><b>{core._esc(u.get('name') or 'anonymous')}</b> &nbsp;"
                f"<span style='color:#777'>{core._esc(u.get('email') or '—')}</span></p>"
                f"<p style='color:#777;font-size:12.5px'>groups: "
                f"{core._esc(', '.join(u.get('groups') or []) or '—')} · auth mode: "
                f"<code>{mode}</code></p>")
        if mode == "oidc":
            action = (f"<a href='{_url('/logout')}' target='_top' style='{btn}'>Sign out</a>" if u
                      else f"<a href='{_url('/login')}' target='_top' style='{btn}'>Sign in</a>")
        elif mode == "local":
            action = (f"<a href='{_url('/logout')}' target='_top' style='{btn}'>Sign out</a>" if u
                      else f"<a href='{_url('/login')}' target='_top' style='{btn}'>Sign in</a>")
        elif mode == "header":
            action = ("<p style='color:#777;font-size:13px'>Authenticated via your gateway — "
                      "sign out through your identity provider.</p>")
        else:
            du = core._esc(core.REG.AUTH_CFG.get("default_user") or "anonymous@local")
            action = (f"<p style='color:#777;font-size:13px'>Anonymous mode — everyone is "
                      f"<code>{du}</code>. Enable sign-in by setting <code>auth.mode: local</code> "
                      "or <code>auth.mode: oidc</code> in <code>gallery.yaml</code>.</p>")
        return core._page("Your profile", info + action)

    @app.route("/settings", methods=["GET", "POST"])
    def _settings():
        from curiator.config import load_config, set_block_key

        cfg = load_config()
        acfg = cfg["auth"]
        if not auth.is_admin(acfg, auth.current_user(acfg)):
            return core._page("Agent settings", "<p style='color:#a33;font-size:13px'>Admins only — your "
                             "account isn't in <code>auth.admin_groups</code>.</p>"), 403
        gallery = Path(cfg["gallery_path"])
        if request.method == "POST":
            text = gallery.read_text()
            for key in ("adapter", "autonomy", "permission_mode", "sandbox", "timeout", "model"):
                if key in request.form:
                    text = set_block_key(text, "agent", key, request.form.get(key))
            gallery.write_text(text)
            return redirect(_url("/settings?saved=1"))
        return core._page("Agent settings",
                          core._settings_html(cfg.get("agent") or {}, cfg["gallery_path"],
                                              saved=request.args.get("saved") == "1"))

    @app.route("/queue")
    def _queue_page():
        u = auth.current_user(core.REG.AUTH_CFG)
        if not auth.is_admin(core.REG.AUTH_CFG, u):
            return core._page("Held feedback queue", "<p style='color:#a33;font-size:13px'>Admins only — your "
                             "account isn't in <code>auth.admin_groups</code>.</p>"), 403
        return core._page("Held feedback queue", _queue_page_html(request.args.get("msg", "")))

    @app.route("/queue/<feedback_id>/<action>", methods=["POST"])
    def _queue_action(feedback_id, action):
        u = auth.current_user(core.REG.AUTH_CFG)
        if not auth.is_admin(core.REG.AUTH_CFG, u):
            return core._page("Held feedback queue", "<p style='color:#a33;font-size:13px'>Admins only.</p>"), 403
        if action not in {
            "approve", "delete", "reject", "resume", "preserve", "restore", "discard-checkpoint"
        }:
            return core._page("Held feedback queue", "<p style='color:#a33;font-size:13px'>Unknown queue action.</p>"), 400
        found = _queue_find(feedback_id)
        if not found:
            return core._page("Held feedback queue", "<p style='color:#a33;font-size:13px'>Feedback not found.</p>"), 404
        key, entry = found
        if entry.get("kind") == "system" or entry.get("status") != "held":
            return core._page("Held feedback queue", "<p style='color:#a33;font-size:13px'>Only held user feedback can be reviewed here.</p>"), 400

        from curiator import run_recovery

        if action in {"resume", "preserve", "restore", "discard-checkpoint"}:
            try:
                if action == "resume":
                    run_recovery.resume_partial(core.LEDGER_CFG, feedback_id)
                elif action == "preserve":
                    run_recovery.preserve_partial(core.LEDGER_CFG, feedback_id)
                elif action == "restore":
                    run_recovery.restore_baseline(core.LEDGER_CFG, feedback_id)
                else:
                    run_recovery.discard_checkpoint(core.LEDGER_CFG, feedback_id)
            except run_recovery.CheckpointError as exc:
                return redirect(_url(f"/queue?msg={quote('Recovery failed: ' + str(exc))}"))
            return redirect(_url(f"/queue?msg={quote('Recovery ' + action + ' completed')}"))
        if action == "approve":
            try:
                _approve_held(key, entry, u)
            except ModerationError as exc:
                return redirect(_url(f"/queue?msg={quote(str(exc))}"))
            return redirect(_url("/queue?msg=Approved"))
        if action == "delete":
            try:
                result = _delete_held(key, entry)
            except ModerationError as exc:
                return redirect(_url(f"/queue?msg={quote(str(exc))}"))
            message = f"Deleted {result['deleted']} thread item(s)"
            return redirect(_url(f"/queue?msg={quote(message)}"))

        actor = _queue_actor(u)
        reason = (request.form.get("reason") or "").strip()
        text = f"Moderation queue: rejected by {actor}; closed without agent dispatch."
        if reason:
            text += f" Reason: {reason}"
        ledger.add_system_note(core.LEDGER_CFG, key, text, reply_to=[entry["id"]], agent="curiator queue")
        ledger.set_status(core.LEDGER_CFG, key, [entry["id"]], "rejected")
        if run_recovery.checkpoint_path(core.LEDGER_CFG, feedback_id).exists():
            run_recovery.retire_checkpoint(core.LEDGER_CFG, feedback_id, "closed", note=text)
            run_recovery.append_trace(core.LEDGER_CFG, feedback_id,
                                      "Recovery checkpoint retired; source left untouched.")
        return redirect(_url("/queue?msg=Rejected"))

    @app.route("/api/feedback/<key>/<feedback_id>/moderate", methods=["POST"])
    def _moderate_feedback(key, feedback_id):
        user = auth.current_user(core.REG.AUTH_CFG)
        if not auth.is_admin(core.REG.AUTH_CFG, user):
            return jsonify({"error": "admin account required"}), 403
        body = request.get_json(silent=True) or {}
        action = str(body.get("action") or "")
        if action not in {"approve", "delete", "amend"}:
            return jsonify({"error": "unknown moderation action"}), 400
        try:
            entry = _held_entry(key, feedback_id)
            if action == "approve":
                result = {"action": "approved", "entry": _safe_entry(_approve_held(key, entry, user))}
            elif action == "amend":
                amendment = _amend_held(key, entry, user, body.get("comment"))
                result = {"action": "amended", "entry": _safe_entry(amendment)}
            else:
                result = {"action": "deleted", **_delete_held(key, entry)}
        except ModerationError as exc:
            return jsonify({"error": str(exc)}), exc.status_code
        return jsonify({"moderation": result, **_feedback_payload(key)})

    @app.route("/api/feedback/<key>/<feedback_id>/approval", methods=["POST"])
    def _review_approval(key, feedback_id):
        user = auth.current_user(core.REG.AUTH_CFG)
        if not auth.is_admin(core.REG.AUTH_CFG, user):
            return jsonify({"error": "admin account required"}), 403
        body = request.get_json(silent=True) or {}
        action = str(body.get("action") or "")
        if action not in {"approve", "amend", "reject"}:
            return jsonify({"error": "unknown approval action"}), 400
        try:
            entry = _awaiting_approval_entry(key, feedback_id)
            if action == "approve":
                result = {"action": "approved", "entry": _safe_entry(
                    _dispatch_approved_plan(key, entry, user)
                )}
            elif action == "amend":
                result = {"action": "amended", "entry": _safe_entry(
                    _dispatch_approved_plan(key, entry, user, amendment=body.get("comment"))
                )}
            else:
                result = {"action": "rejected", "entry": _safe_entry(
                    _reject_approved_plan(key, entry, user)
                )}
        except ModerationError as exc:
            return jsonify({"error": str(exc)}), exc.status_code
        return jsonify({"approval": result, **_feedback_payload(key)})

    @app.route("/api/feedback/<key>", methods=["GET", "POST"])
    def _feedback(key):
        if request.method == "POST":
            u, status, auth_error, code = _feedback_user_and_status()
            if auth_error:
                return jsonify({"error": auth_error}), code or 401
            body = request.get_json(silent=True) or {}
            screenshot = body.get("screenshot")
            if status == "held" and screenshot and body.get("screenshot_source") != "capture":
                return jsonify({"error": "anonymous uploaded/native screenshots are disabled; use Capture view"}), 400
            if status == "held" and body.get("audio_ref"):
                return jsonify({"error": "anonymous retained audio is disabled; sign in to attach audio"}), 400
            reply_to = body.get("reply_to") or []
            if isinstance(reply_to, str):
                reply_to = [reply_to]
            try:
                entry = core.save_entry(
                    key,
                    body.get("stars"),
                    body.get("comment", ""),
                    screenshot,
                    user=u,
                    reply_to=reply_to,
                    status=status,
                    annotations=body.get("annotations"),
                    annotation_targets=body.get("screenshot_source") == "capture",
                    transcript_segments=body.get("transcript_segments"),
                    audio_ref=body.get("audio_ref"),
                    design_refs=body.get("design_refs"),
                )
            except DesignReferenceError as exc:
                return jsonify({"error": f"invalid design reference: {exc}"}), 400
            return jsonify({"entry": _safe_entry(entry), **_feedback_payload(key)})
        return jsonify(_feedback_payload(key))

    @app.route("/api/feedback")
    def _all_feedback():
        return jsonify({key: _feedback_payload(key) for key in core.load_feedback()})

    @app.route("/api/new-app", methods=["POST"])
    def _new_app():
        u, status, auth_error, code = _feedback_user_and_status("new-app")
        if auth_error:
            return jsonify({"error": auth_error}), code or 401
        body = request.get_json(silent=True) or {}
        app_request, error = _new_app_request(body)
        if error:
            return jsonify({"error": error}), 400
        entry_id = ledger.save_entry(
            core.LEDGER_CFG,
            core.GENERAL_KEY,
            comment=_new_app_comment(app_request),
            user=u,
            extra={"status": status, "app_request": app_request},
        )
        entry = next(e for e in core.load_feedback().get(core.GENERAL_KEY, []) if e.get("id") == entry_id)
        return jsonify({"entry": _safe_entry(entry), **_feedback_payload(core.GENERAL_KEY)})

    @app.route("/api/transcribe", methods=["POST"])
    def _transcribe():
        voice = _voice_cfg()
        command = voice.get("transcribe_cmd")
        if not command:
            return jsonify({"error": "local transcription is not configured"}), 404
        auth_error, code = _transcribe_allowed()
        if auth_error:
            return jsonify({"error": auth_error}), code

        max_bytes = _voice_int("transcribe_max_bytes", 25 * 1024 * 1024, low=1, high=200 * 1024 * 1024)
        if request.content_length and request.content_length > max_bytes:
            return jsonify({"error": "audio clip is too large"}), 413
        upload = request.files.get("audio")
        if not upload:
            return jsonify({"error": "missing audio file"}), 400

        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in {".webm", ".ogg", ".mp3", ".m4a", ".mp4", ".wav", ".flac"}:
            suffix = ".webm"
        timeout = _voice_int("transcribe_timeout", 60, low=1, high=600)
        with tempfile.TemporaryDirectory(prefix="curiator-audio-") as tmp:
            audio_path = Path(tmp) / f"clip{suffix}"
            upload.save(audio_path)
            if audio_path.stat().st_size == 0:
                return jsonify({"error": "audio clip is empty"}), 400
            if audio_path.stat().st_size > max_bytes:
                return jsonify({"error": "audio clip is too large"}), 413
            args = _transcribe_args(command, audio_path)
            if not args:
                return jsonify({"error": "local transcription command is empty"}), 500
            env = {
                **os.environ,
                "CURIATOR_AUDIO": str(audio_path),
                "CURIATOR_COLLECTION_ROOT": str(core.REG.COLLECTION_ROOT),
            }
            try:
                proc = subprocess.run(
                    args,
                    cwd=core.REG.COLLECTION_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except FileNotFoundError:
                return jsonify({"error": f"transcriber not found: {args[0]}"}), 502
            except subprocess.TimeoutExpired:
                return jsonify({"error": f"transcription timed out after {timeout}s"}), 504
            if proc.returncode != 0:
                detail = bounded_text(proc.stderr or proc.stdout, 500) or f"exit {proc.returncode}"
                return jsonify({"error": "transcription failed", "detail": detail}), 502
            payload = _parse_transcript(proc.stdout)
            retain_audio = bool(voice.get("retain_audio")) and not (
                auth.feedback_requires_identity(core.REG.AUTH_CFG) and not core._current_user()
            )
            if retain_audio:
                core.PENDING_AUDIO.mkdir(parents=True, exist_ok=True)
                retained = core.PENDING_AUDIO / f"{uuid.uuid4().hex}{suffix}"
                shutil.copyfile(audio_path, retained)
                payload["audio_ref"] = f"audio/pending/{retained.name}"
        return jsonify(payload)

    @app.route("/api/action", methods=["POST"])
    def _action():
        body = request.get_json(silent=True) or {}
        key = body.get("key")
        value = body.get("value")
        if not key or value is None:
            return jsonify({"error": "missing key/value"}), 400
        proposal_match = re.fullmatch(r"curiator-proposal:(approve|reject):([0-9A-Za-z._-]+)", str(value))
        if proposal_match:
            user = core._current_user()
            if not auth.is_admin(core.REG.AUTH_CFG, user):
                return jsonify({"error": "proposal approval and rejection require an admin account"}), 403
            from curiator import proposals

            action, feedback_id = proposal_match.groups()
            actor = _queue_actor(user)
            try:
                result = (
                    proposals.approve(core.LEDGER_CFG, key, feedback_id, actor=actor)
                    if action == "approve"
                    else proposals.reject(core.LEDGER_CFG, key, feedback_id, actor=actor)
                )
            except proposals.ProposalError as exc:
                return jsonify({"error": str(exc)}), 409
            core.reload_app(key)
            return jsonify({"proposal_result": result, **_feedback_payload(key)})
        u, status, auth_error, code = _feedback_user_and_status()
        if auth_error:
            return jsonify({"error": auth_error}), code or 401
        entry = core.record_action(key, value, body.get("reply_to"), user=u, status=status)
        return jsonify({"entry": _safe_entry(entry), **_feedback_payload(key)})

    @app.route("/feedback-shot/<path:fname>")
    def _shot(fname):
        return send_from_directory(core.SHOTS, fname)

    @app.route("/feedback-audio/<path:fname>")
    def _audio(fname):
        return send_from_directory(core.AUDIO, fname)

    @app.route("/feedback-trace/<feedback_id>.md")
    def _trace_raw(feedback_id):
        p = core._trace_path(feedback_id)
        if not p or not p.exists():
            return ("trace not found", 404)
        return Response(p.read_text(encoding="utf-8", errors="replace"), mimetype="text/markdown; charset=utf-8")

    @app.route("/feedback-trace/<feedback_id>")
    def _trace(feedback_id):
        p = core._trace_path(feedback_id)
        if not p or not p.exists():
            return core._page("Agent trace", "<p style='color:#777;font-size:13px'>No trace file for this feedback.</p>"), 404
        return core._trace_page(feedback_id, p.read_text(encoding="utf-8", errors="replace"))

    @app.route("/feedback-trace/<feedback_id>/stop", methods=["POST"])
    def _trace_stop(feedback_id):
        """The trace-view Stop button: drop a cancel marker the watcher polls for. Only meaningful while
        the item is `working`; the watcher terminates the agent and parks the item as `held`."""
        from curiator.loop import runlog as _runlog
        found = _queue_find(feedback_id)
        if not found:
            return jsonify({"ok": False, "error": "feedback not found"}), 404
        _key, entry = found
        if entry.get("status") != "working":
            return jsonify({"ok": False, "error": "no active run", "status": entry.get("status")}), 409
        _runlog.request_cancel(core.LEDGER_CFG, feedback_id)
        return jsonify({"ok": True})

    @app.route("/static-app/<path:fname>")
    def _static_app(fname):
        return send_from_directory(core.HERE, fname)

    @app.route("/general")
    def _general():
        visible = {
            key: _visible_feedback_items(items)
            for key, items in core.load_feedback().items()
        }
        return core.render_history(
            request.args.get("range"),
            request.args.get("filter"),
            data=visible,
        )

    @app.route("/reload/<key>", methods=["POST", "GET"])
    def _reload(key):
        return jsonify(core.reload_app(key))

    @app.route("/whoami")
    def _whoami():
        return jsonify(auth.current_user(core.REG.AUTH_CFG) or {"authenticated": False})

    @app.route("/fb-action", methods=["POST", "GET"])
    def _fb_action_route():
        key = request.args.get("key")
        value = request.args.get("value")
        reply_to = request.args.get("reply_to")
        if key and value is not None:
            u, status, auth_error, code = _feedback_user_and_status()
            if auth_error:
                return (auth_error, code or 401)
            core.record_action(key, value, reply_to, user=u, status=status)
            return ("ok", 200)
        return ("missing key/value", 400)

    return app


def build_application():
    flask_app = build_flask_app()
    core._DISPATCHER = core.LazyDispatcher(flask_app)
    application = PrefixMiddleware(core._DISPATCHER, BASE_PATH)
    proxy_hops = int(core.REG.SHELL_CFG.get("proxy_hops") or 0)
    if proxy_hops > 0:
        application = ProxyFix(application, x_for=proxy_hops, x_proto=proxy_hops, x_host=proxy_hops)
    return application, flask_app


if __name__ == "__main__":
    import logging
    from werkzeug.serving import run_simple
    if os.environ.get("CURIATOR_HTTP_LOG") != "1":
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
    host = os.environ.get("SHELL_HOST", "0.0.0.0")
    application, _app = build_application()
    run_simple(host, core.PORT, application, threaded=True)
