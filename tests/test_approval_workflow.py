"""Structured admin approval dispatch, task authority, and collection-wide git memory."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


SHELL_DIR = Path(__file__).resolve().parents[1] / "curiator" / "shell"


def _load_web_mod(monkeypatch):
    monkeypatch.syspath_prepend(str(SHELL_DIR))
    for name in ("registry", "curiator.shell.app_shell", "curiator.shell.web_shell"):
        sys.modules.pop(name, None)
    import curiator.shell as shell_pkg

    for attr in ("app_shell", "web_shell"):
        if hasattr(shell_pkg, attr):
            delattr(shell_pkg, attr)
    spec = importlib.util.spec_from_file_location(
        "curiator.shell.web_shell", str(SHELL_DIR / "web_shell.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["curiator.shell.web_shell"] = mod
    spec.loader.exec_module(mod)
    return mod


def _pending_plan(cfg, *, actions=None):
    from curiator import ledger

    feedback_id = ledger.save_entry(
        cfg,
        "sample",
        comment="Rename the app directory and registration.",
        user={"id": "admin", "email": "admin@example.com", "name": "Admin", "groups": ["admin"]},
        extra={"status": "awaiting_approval"},
    )
    plan_id = ledger.add_system_note(
        cfg,
        "sample",
        "Plan: move the app, update gallery.yaml, and replace the old internal name.",
        reply_to=[feedback_id],
        actions=actions,
        agent="Codex",
    )
    return feedback_id, plan_id


def test_admin_approval_dispatches_structured_collection_task(collection, cfg, monkeypatch):
    from curiator import ledger
    from curiator.loop import loop
    from curiator.loop.adapters import build_task

    mod = _load_web_mod(monkeypatch)
    client = mod.build_flask_app().test_client()
    feedback_id, plan_id = _pending_plan(cfg)

    response = client.post(
        f"/api/feedback/sample/{feedback_id}/approval",
        json={"action": "approve"},
    )

    assert response.status_code == 200
    result = response.get_json()["approval"]
    assert result["action"] == "approved"
    dispatch_id = result["entry"]["id"]
    items = ledger.load(cfg)["sample"]
    original = next(item for item in items if item["id"] == feedback_id)
    dispatch = next(item for item in items if item["id"] == dispatch_id)
    assert original["status"] == "done"
    assert original["approval_dispatch_id"] == dispatch_id
    assert dispatch["status"] == "new"
    assert dispatch["reply_to"] == [plan_id]
    assert dispatch["approval_of"] == feedback_id
    assert dispatch["approval_plan_id"] == plan_id
    assert dispatch["approval_scope"] == "collection"
    assert dispatch["approval_resolution"] == "approved"
    assert [entry["id"] for _key, entry in loop._new_items(ledger.load(cfg))] == [dispatch_id]

    task = build_task(cfg, "sample", dispatch)
    body = Path(task.task_file).read_text(encoding="utf-8")
    assert task.source == str(collection.resolve())
    assert "ADMIN-APPROVED EXECUTION" in body
    assert "supersedes the protocol's substantive-work triage" in body
    assert "admin-approved collection scope" in body
    assert "gallery.yaml" in body
    assert "Plan: move the app" in body
    assert "## Browser-smoke capability" not in body


def test_general_admin_approval_inherits_app_rename_as_collection_work(collection, cfg, monkeypatch):
    from curiator import ledger
    from curiator.loop import adapters
    from curiator.loop.adapters import GENERAL_KEY, build_task

    mod = _load_web_mod(monkeypatch)
    client = mod.build_flask_app().test_client()
    feedback_id = ledger.save_entry(
        cfg,
        GENERAL_KEY,
        comment='Change the name of the "Cairn" app and directory to "Sietch".',
        extra={"status": "awaiting_approval"},
    )
    plan_id = ledger.add_system_note(
        cfg,
        GENERAL_KEY,
        "Plan: rename the app key, directory, gallery registration, and internal references.",
        reply_to=[feedback_id],
        agent="Codex",
    )

    response = client.post(
        f"/api/feedback/{GENERAL_KEY}/{feedback_id}/approval",
        json={"action": "approve"},
    )

    assert response.status_code == 200
    dispatch = response.get_json()["approval"]["entry"]
    assert dispatch["reply_to"] == [plan_id]
    assert adapters.general_targets_collection(dispatch, cfg)
    task = build_task(cfg, GENERAL_KEY, dispatch)
    body = Path(task.task_file).read_text(encoding="utf-8")
    assert task.source == str(collection.resolve())
    assert "General collection feedback" in body
    assert "APPROVAL/FOLLOW-UP RUN" in body
    assert "perform that app work now" in body
    assert "Mode: pinned" not in body
    assert not adapters.general_targets_collection({"comment": "change the app shell layout"}, cfg)


def test_admin_can_amend_or_reject_awaiting_approval(collection, cfg, monkeypatch):
    from curiator import ledger

    mod = _load_web_mod(monkeypatch)
    client = mod.build_flask_app().test_client()
    amend_id, plan_id = _pending_plan(cfg)
    amended = client.post(
        f"/api/feedback/sample/{amend_id}/approval",
        json={"action": "amend", "comment": "Keep an alias for the old public URL."},
    )
    assert amended.status_code == 200
    amendment = amended.get_json()["approval"]["entry"]
    assert amendment["comment"] == "Keep an alias for the old public URL."
    assert amendment["reply_to"] == [plan_id]
    assert amendment["approval_resolution"] == "amended"

    reject_id, _plan_id = _pending_plan(cfg)
    rejected = client.post(
        f"/api/feedback/sample/{reject_id}/approval",
        json={"action": "reject"},
    )
    assert rejected.status_code == 200
    assert rejected.get_json()["approval"]["action"] == "rejected"
    row = next(item for item in ledger.load(cfg)["sample"] if item["id"] == reject_id)
    assert row["status"] == "rejected"
    assert row["approval_resolution"] == "rejected"


def test_generic_approval_refuses_per_run_branch_proposal(collection, cfg, monkeypatch):
    mod = _load_web_mod(monkeypatch)
    client = mod.build_flask_app().test_client()
    feedback_id, _plan_id = _pending_plan(
        cfg,
        actions=[["Approve", "curiator-proposal:approve:abc12345"]],
    )

    response = client.post(
        f"/api/feedback/sample/{feedback_id}/approval",
        json={"action": "approve"},
    )

    assert response.status_code == 409
    assert "proposal Approve/Reject" in response.get_json()["error"]


def test_react_shell_exposes_admin_approval_review(collection, monkeypatch):
    mod = _load_web_mod(monkeypatch)
    js = mod.build_flask_app().test_client().get("/assets/react_shell.js").get_data(as_text=True)
    assert "function ApprovalReview" in js
    assert '"Admin approval"' in js
    assert '"Reply & approve"' in js
    assert '"Reject"' in js
    assert ' + encodeURIComponent(entry.id) + "/approval"' in js


def test_approved_collection_commit_tracks_app_key_and_directory_rename(collection, cfg):
    from curiator import gitmem, ledger

    request_id, plan_id = _pending_plan(cfg)
    dispatch_id = ledger.save_entry(
        cfg,
        "sample",
        comment="Approved by admin@example.com.",
        user={"id": "admin", "email": "admin@example.com", "name": "Admin", "groups": ["admin"]},
        extra={
            "status": "done",
            "reply_to": [plan_id],
            "approval_of": request_id,
            "approval_plan_id": plan_id,
            "approval_scope": "collection",
            "approval_resolution": "approved",
            "approval_authorized_by": "admin@example.com",
        },
    )
    ledger.add_system_note(cfg, "sample", "Renamed the app.", reply_to=[dispatch_id], agent="Codex")

    old_source = collection / "apps" / "sample.py"
    new_source = collection / "apps" / "renamed.py"
    old_source.rename(new_source)
    gallery = collection / "gallery.yaml"
    gallery.write_text(
        gallery.read_text(encoding="utf-8")
        .replace("- name: sample", "- name: renamed")
        .replace("source: apps/sample.py", "source: apps/renamed.py"),
        encoding="utf-8",
    )

    result = gitmem.commit_run(
        cfg,
        "sample",
        dispatch_id,
        status="done",
        note_text="Renamed the app registration and directory.",
    )

    assert result["committed"], result
    changed = subprocess.run(
        ["git", "show", "--no-renames", "--name-only", "--format=", "HEAD"],
        cwd=collection,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert {"apps/sample.py", "apps/renamed.py", "gallery.yaml", "feedback/app_feedback.sqlite"} <= set(changed)


def test_general_approved_rename_inherits_collection_git_scope(collection, cfg):
    from curiator import gitmem, ledger
    from curiator.loop.adapters import GENERAL_KEY

    request_id = ledger.save_entry(
        cfg,
        GENERAL_KEY,
        comment='Change the name of the "Cairn" app and directory to "Sietch".',
        extra={"status": "done"},
    )
    plan_id = ledger.add_system_note(
        cfg,
        GENERAL_KEY,
        "Plan: rename the app key, directory, gallery registration, and internal references.",
        reply_to=[request_id],
        agent="Codex",
    )
    dispatch_id = ledger.save_entry(
        cfg,
        GENERAL_KEY,
        comment="Approved by admin@example.com.",
        extra={
            "status": "done",
            "reply_to": [plan_id],
            "approval_of": request_id,
            "approval_plan_id": plan_id,
            "approval_scope": "collection",
            "approval_resolution": "approved",
            "approval_authorized_by": "admin@example.com",
        },
    )
    ledger.add_system_note(cfg, GENERAL_KEY, "Renamed the app.", reply_to=[dispatch_id], agent="Codex")
    (collection / "apps" / "sample.py").rename(collection / "apps" / "sietch.py")
    gallery = collection / "gallery.yaml"
    gallery.write_text(
        gallery.read_text(encoding="utf-8")
        .replace("- name: sample", "- name: sietch")
        .replace("source: apps/sample.py", "source: apps/sietch.py"),
        encoding="utf-8",
    )

    result = gitmem.commit_run(
        cfg,
        GENERAL_KEY,
        dispatch_id,
        status="done",
        note_text="Renamed the approved collection app.",
    )

    assert result["committed"], result
    changed = subprocess.run(
        ["git", "show", "--no-renames", "--name-only", "--format=", "HEAD"],
        cwd=collection,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert {"apps/sample.py", "apps/sietch.py", "gallery.yaml", "feedback/app_feedback.sqlite"} <= set(changed)
