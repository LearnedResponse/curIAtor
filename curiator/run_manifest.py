"""Versioned, durable run manifests shared by recovery, workspaces, and replay."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .agent_capabilities import agent_report
from .config import app_spec


RUN_MANIFEST_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_record(path: Path | None, *, root: Path) -> dict | None:
    if not path:
        return None
    candidate = path if path.is_absolute() else root / path
    record = {"path": str(path).replace("\\", "/"), "exists": candidate.is_file()}
    if candidate.is_file():
        data = candidate.read_bytes()
        record.update({"sha256": _sha256_bytes(data), "bytes": len(data)})
    return record


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except OSError:
            pass


def manifests_dir(cfg: dict) -> Path:
    feedback = (cfg.get("feedback") or {}).get("dir", "feedback")
    return Path(cfg.get("repo_root", ".")) / str(feedback) / "runs"


def manifest_path(cfg: dict, feedback_id: str) -> Path:
    return manifests_dir(cfg) / feedback_id / "manifest.json"


def task_copy_path(cfg: dict, feedback_id: str) -> Path:
    return manifests_dir(cfg) / feedback_id / "task.md"


def _git_text(repo: Path, *args: str) -> str | None:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def _runner_identity() -> dict:
    root = Path(__file__).resolve().parents[1]
    return {
        "version": __version__,
        "repo": str(root),
        "git_sha": _git_text(root, "rev-parse", "HEAD"),
    }


def _thread_entries(cfg: dict, key: str, entry: dict) -> list[dict]:
    from .loop.adapters import _related_thread_entries

    return [*_related_thread_entries(cfg, key, entry, limit=50), entry]


def _input_evidence(cfg: dict, key: str, entry: dict) -> dict:
    root = Path(cfg["repo_root"])
    feedback = Path(str((cfg.get("feedback") or {}).get("dir", "feedback")))
    screenshot = feedback / str(entry["screenshot"]) if entry.get("screenshot") else None
    audio = feedback / str(entry["audio"]) if entry.get("audio") else None
    return {
        "thread_context_ids": [str(item.get("id")) for item in _thread_entries(cfg, key, entry) if item.get("id")],
        "screenshot": _file_record(screenshot, root=root),
        "audio": _file_record(audio, root=root),
        "annotations": json.loads(json.dumps(entry.get("annotations") or [])),
        "transcript_segments": json.loads(json.dumps(entry.get("transcript_segments") or [])),
        "design_refs": json.loads(json.dumps(entry.get("design_refs") or [])),
    }


def _commands(cfg: dict, app_key: str) -> dict:
    spec = app_spec(cfg, app_key) or {}
    mount = spec.get("mount") or {}
    commands = spec.get("commands") or {}
    return {
        "smoke": spec.get("smoke"),
        "preview": commands.get("preview") or mount.get("cmd"),
        "browser": f"curiator smoke --app {app_key} --browser",
    }


def create(task, adapter_name: str, checkpoint: dict) -> dict:
    """Persist the immutable prompt/evidence/source identity before agent launch."""
    feedback_id = str(task.entry.get("id") or "")
    source = Path(task.task_file)
    task_bytes = source.read_bytes()
    copied = task_copy_path(task.cfg, feedback_id)
    copied.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, copied)
    gallery = Path(task.cfg["gallery_path"])
    gallery_bytes = gallery.read_bytes()
    capabilities = agent_report(task.cfg).get("capabilities", {})
    owning = []
    for owner in checkpoint.get("owning_repos") or []:
        baseline = owner.get("baseline") or {}
        owning.append({
            "repo": owner.get("path"),
            "base_sha": baseline.get("head"),
            "branch": baseline.get("branch"),
            "scopes": list(owner.get("scopes") or []),
            "baseline_digest": baseline.get("fingerprint"),
            "preexisting": {
                "staged": list(baseline.get("staged") or []),
                "unstaged": list(baseline.get("unstaged") or []),
                "untracked": list(baseline.get("untracked") or []),
            },
        })
    profile = json.loads(json.dumps(checkpoint.get("agent_profile") or {}))
    manifest = {
        "run_manifest_version": RUN_MANIFEST_VERSION,
        "run_id": checkpoint.get("run_id"),
        "feedback_id": feedback_id,
        "app_key": task.key,
        "recorded_at": _now(),
        "state": "dispatching",
        "task": {
            "path": str(copied),
            "sha256": _sha256_bytes(task_bytes),
            "bytes": len(task_bytes),
            "original_path": task.task_file,
        },
        "collection": {
            "repo": checkpoint.get("collection_repo"),
            "base_sha": checkpoint.get("collection_head"),
            "branch": checkpoint.get("collection_branch"),
            "gallery_path": task.cfg.get("gallery_path"),
            "gallery_sha256": _sha256_bytes(gallery_bytes),
        },
        "source": {"owning_repos": owning},
        "runner": _runner_identity(),
        "workspace": {
            "image": f"curiator-workspace:{__version__}",
            "image_digest": None,
            "reason": "normal canonical dispatch; no workspace image was used",
        },
        "agent": {
            "adapter": adapter_name,
            "provider": adapter_name,
            "model": profile.get("model"),
            "autonomy": profile.get("autonomy"),
            "effective_profile": profile,
            "capabilities": capabilities,
            "skill_plugin_identifiers": [],
        },
        "commands": _commands(task.cfg, task.key),
        "input": _input_evidence(task.cfg, task.key, task.entry),
        "timing": {"started_at": checkpoint.get("started_at"), "finished_at": None},
        "output": {
            "status": None,
            "commits": [],
            "trace": None,
            "browser_artifacts": [],
            "smoke_artifacts": [],
            "turns": None,
            "tokens": None,
            "cost": None,
        },
    }
    _atomic_json(manifest_path(task.cfg, feedback_id), manifest)
    return manifest


def load(cfg: dict, feedback_id: str) -> dict | None:
    try:
        payload = json.loads(manifest_path(cfg, feedback_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("run_manifest_version") != RUN_MANIFEST_VERSION:
        return None
    return payload


def update(cfg: dict, feedback_id: str, fields: dict) -> dict | None:
    payload = load(cfg, feedback_id)
    if payload is None:
        return None
    payload.update(fields)
    _atomic_json(manifest_path(cfg, feedback_id), payload)
    return payload


def mark_process_end(cfg: dict, feedback_id: str, process_end: dict) -> None:
    payload = load(cfg, feedback_id)
    if payload is None:
        return
    payload["state"] = "process-ended"
    payload["process_end"] = {
        "observed_at": process_end.get("observed_at"),
        "reason": process_end.get("reason"),
        "repos": [
            {"repo": row.get("path"), "head": (row.get("state") or {}).get("head")}
            for row in process_end.get("repos") or []
        ],
    }
    _atomic_json(manifest_path(cfg, feedback_id), payload)


def _artifact_records(cfg: dict, feedback_id: str) -> list[dict]:
    feedback = Path(cfg["repo_root"]) / str((cfg.get("feedback") or {}).get("dir", "feedback"))
    root = feedback / "replies" / f"{feedback_id}-browser-smoke"
    if not root.exists():
        return []
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        records.append(_file_record(path, root=Path("/")))
    return [record for record in records if record]


def finalize(cfg: dict, feedback_id: str, *, status: str, decision: str) -> None:
    payload = load(cfg, feedback_id)
    if payload is None:
        return
    from . import gitmem
    from .loop import runlog

    root = Path(cfg["repo_root"])
    trace = _file_record(runlog.reply_path(cfg, feedback_id), root=root)
    commit = gitmem.find_commit(cfg, feedback_id)
    payload["state"] = decision
    payload["timing"]["finished_at"] = _now()
    payload["output"].update({
        "status": status,
        "commits": [commit] if commit else [],
        "trace": trace,
        "browser_artifacts": _artifact_records(cfg, feedback_id),
    })
    _atomic_json(manifest_path(cfg, feedback_id), payload)
