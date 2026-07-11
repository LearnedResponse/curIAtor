"""Historical feedback manifest audit and source-base reconstruction."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from . import ledger, run_manifest
from .config import app_spec


class ReplayError(RuntimeError):
    """A requested feedback item cannot be inspected or replayed."""


def _run(repo: Path, *args: str) -> str | None:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    output = result.stdout.strip()
    return output if result.returncode == 0 and output else None


def _git_root(path: Path) -> Path | None:
    probe = path if path.is_dir() else path.parent
    value = _run(probe, "rev-parse", "--show-toplevel")
    return Path(value).resolve() if value else None


def _find_commit(repo: Path, feedback_id: str) -> str | None:
    return _run(
        repo,
        "log", "--all", f"--grep=Curiator-Feedback: {feedback_id}", "-n", "1", "--format=%H",
    )


def _parent(repo: Path, commit: str | None) -> str | None:
    return _run(repo, "rev-parse", f"{commit}^") if commit else None


def _feedback(cfg: dict, feedback_id: str) -> tuple[str, dict]:
    for key, entries in ledger.load(cfg).items():
        for entry in entries if isinstance(entries, list) else []:
            if entry.get("id") == feedback_id and entry.get("kind") != "system":
                return key, entry
    raise ReplayError(f"feedback id {feedback_id!r} not found")


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _forward_manifest_report(cfg: dict, feedback_id: str, app_key: str, entry: dict, manifest: dict) -> dict:
    reasons = []
    task = manifest.get("task") or {}
    task_path = Path(str(task.get("path") or ""))
    task_ok = bool(task_path.is_file() and _digest(task_path) == task.get("sha256"))
    if not task_ok:
        reasons.append("persisted task bundle is missing or its digest changed")
    owners = ((manifest.get("source") or {}).get("owning_repos") or [])
    source_heads = bool(owners) and all(owner.get("base_sha") for owner in owners)
    clean = all(not any((owner.get("preexisting") or {}).get(kind) for kind in ("staged", "unstaged", "untracked"))
                for owner in owners)
    if not source_heads:
        reasons.append("one or more source repositories have no recorded base SHA")
    if not clean:
        reasons.append("the dispatch baseline contained uncommitted source state whose objects were not retained")
    local_inputs = [
        value for value in ((manifest.get("input") or {}).get(name) for name in ("screenshot", "audio"))
        if value
    ]
    inputs_ok = all(record.get("exists") for record in local_inputs)
    if not inputs_ok:
        reasons.append("one or more local input artifacts are missing")
    external = bool((manifest.get("input") or {}).get("design_refs"))
    if external:
        reasons.append("external design content was referenced but not snapshotted")
    exactness = "exact" if task_ok and source_heads and clean and inputs_ok and not external else (
        "source-exact" if source_heads and clean else "context-partial"
    )
    return {
        "feedback_id": feedback_id,
        "app_key": app_key,
        "status": entry.get("status"),
        "exactness": exactness,
        "reasons": reasons,
        "manifest_source": "recorded",
        "manifest_path": str(run_manifest.manifest_path(cfg, feedback_id)),
        "manifest": manifest,
        "workspace_ready": bool(source_heads and clean),
    }


def inspect(cfg: dict, feedback_id: str) -> dict:
    app_key, entry = _feedback(cfg, feedback_id)
    forward = run_manifest.load(cfg, feedback_id)
    if forward:
        return _forward_manifest_report(cfg, feedback_id, app_key, entry, forward)

    reasons = ["no forward run manifest; provider/profile/timing fields are incomplete"]
    if app_key == "__general__":
        collection_repo = _git_root(Path(cfg["repo_root"]))
        commit = _find_commit(collection_repo, feedback_id) if collection_repo else None
        base = _parent(collection_repo, commit) if collection_repo else None
        feedback = str((cfg.get("feedback") or {}).get("dir", "feedback"))
        task_path = Path(cfg["repo_root"]) / feedback / "tasks" / f"{feedback_id}.md"
        task_digest = _digest(task_path)
        reasons.append("collection-wide General replay launch is not implemented")
        if not base:
            reasons.append("no feedback-linked collection commit with a resolvable pre-fix parent")
        if not task_digest:
            reasons.append("original task bundle is missing")
        return {
            "feedback_id": feedback_id,
            "app_key": app_key,
            "status": entry.get("status"),
            "exactness": "source-exact" if base else "context-partial",
            "reasons": reasons,
            "manifest_source": "reconstructed",
            "workspace_ready": False,
            "source": {
                "collection_repo": str(collection_repo) if collection_repo else None,
                "collection_accepted_commit": commit,
                "collection_base_sha": base,
                "owning_repo": str(collection_repo) if collection_repo else None,
                "owning_accepted_commit": commit,
                "owning_repo_base_sha": base,
            },
            "task": {"path": str(task_path), "sha256": task_digest, "exists": bool(task_digest)},
            "input": {
                "screenshot": entry.get("screenshot"),
                "annotations": len(entry.get("annotations") or []),
                "audio": entry.get("audio"),
                "design_refs": len(entry.get("design_refs") or []),
            },
        }
    spec = app_spec(cfg, app_key)
    if not spec:
        return {
            "feedback_id": feedback_id, "app_key": app_key, "status": entry.get("status"),
            "exactness": "unreplayable", "reasons": [*reasons, "app is no longer registered"],
            "manifest_source": "reconstructed", "workspace_ready": False,
        }
    collection_repo = _git_root(Path(cfg["repo_root"]))
    source_path = Path(spec.get("source") or spec.get("root") or cfg["repo_root"])
    owning_repo = _git_root(source_path)
    if not collection_repo or not owning_repo:
        return {
            "feedback_id": feedback_id, "app_key": app_key, "status": entry.get("status"),
            "exactness": "unreplayable", "reasons": [*reasons, "collection or app source is not in Git"],
            "manifest_source": "reconstructed", "workspace_ready": False,
        }
    source_commit = _find_commit(owning_repo, feedback_id)
    source_base = _parent(owning_repo, source_commit)
    collection_commit = _find_commit(collection_repo, feedback_id)
    collection_base = _parent(collection_repo, collection_commit)
    if owning_repo == collection_repo:
        collection_commit = source_commit
        collection_base = source_base
    task_path = Path(cfg["repo_root"]) / str((cfg.get("feedback") or {}).get("dir", "feedback")) / "tasks" / f"{feedback_id}.md"
    task_digest = _digest(task_path)
    if not source_base:
        reasons.append("no feedback-linked source commit with a resolvable pre-fix parent")
    if owning_repo != collection_repo and not collection_base:
        reasons.append("no feedback-linked collection commit with a resolvable pre-fix parent")
    if not task_digest:
        reasons.append("original task bundle is missing")
    exactness = "source-exact" if source_base and collection_base else (
        "context-partial" if task_digest or entry else "unreplayable"
    )
    return {
        "feedback_id": feedback_id,
        "app_key": app_key,
        "status": entry.get("status"),
        "exactness": exactness,
        "reasons": reasons,
        "manifest_source": "reconstructed",
        "workspace_ready": bool(source_base and collection_base),
        "source": {
            "collection_repo": str(collection_repo),
            "collection_accepted_commit": collection_commit,
            "collection_base_sha": collection_base,
            "owning_repo": str(owning_repo),
            "owning_accepted_commit": source_commit,
            "owning_repo_base_sha": source_base,
        },
        "task": {
            "path": str(task_path),
            "sha256": task_digest,
            "exists": bool(task_digest),
        },
        "input": {
            "screenshot": entry.get("screenshot"),
            "annotations": len(entry.get("annotations") or []),
            "audio": entry.get("audio"),
            "design_refs": len(entry.get("design_refs") or []),
        },
    }


def inspect_all(cfg: dict) -> list[dict]:
    rows = []
    for entries in ledger.load(cfg).values():
        for entry in entries if isinstance(entries, list) else []:
            if entry.get("kind") != "system" and entry.get("id"):
                rows.append(inspect(cfg, str(entry["id"])))
    return rows


def redacted_report(report: dict) -> dict:
    """Compact export that never includes private URLs, paths, or provider payloads."""
    return {
        "feedback_id": report.get("feedback_id"),
        "app_key": report.get("app_key"),
        "status": report.get("status"),
        "exactness": report.get("exactness"),
        "reasons": list(report.get("reasons") or []),
        "workspace_ready": bool(report.get("workspace_ready")),
        "manifest_source": report.get("manifest_source"),
    }
