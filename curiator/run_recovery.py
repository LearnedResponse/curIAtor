"""Source checkpoints and explicit recovery for interrupted agent runs.

The checkpoint is runtime state under ``feedback/runs``. It records the exact
index and worktree content inside the task's writable source scope without
touching the canonical Git index. Recovery is deliberately source-scoped: it
never resets a repository or removes unrelated files.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import ledger
from .config import app_specs


CHECKPOINT_VERSION = 1


class CheckpointError(RuntimeError):
    """A checkpoint cannot be created or safely recovered."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def runs_dir(cfg: dict) -> Path:
    feedback = (cfg.get("feedback") or {}).get("dir", "feedback")
    return Path(cfg.get("repo_root", ".")) / feedback / "runs"


def run_dir(cfg: dict, feedback_id: str) -> Path:
    return runs_dir(cfg) / feedback_id


def checkpoint_path(cfg: dict, feedback_id: str) -> Path:
    return run_dir(cfg, feedback_id) / "checkpoint.json"


def _objects_dir(cfg: dict, feedback_id: str) -> Path:
    return run_dir(cfg, feedback_id) / "objects"


def _history_dir(cfg: dict, feedback_id: str) -> Path:
    return run_dir(cfg, feedback_id) / "history"


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


def _run(cmd: list[str], *, cwd: Path, data: bytes | None = None, check: bool = True,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(cmd, cwd=cwd, input=data, capture_output=True, env=env)
    if check and result.returncode:
        detail = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        raise CheckpointError(f"{' '.join(cmd)} failed in {cwd}: {detail or f'exit {result.returncode}'}")
    return result


def _git(repo: Path, *args: str, data: bytes | None = None, check: bool = True,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    return _run(["git", *args], cwd=repo, data=data, check=check, env=env)


def _git_text(repo: Path, *args: str) -> str | None:
    result = _git(repo, *args, check=False)
    if result.returncode:
        return None
    return result.stdout.decode("utf-8", "replace").strip()


def _git_root(path: Path) -> Path | None:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if probe.is_file():
        probe = probe.parent
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=probe, check=False)
    if result.returncode:
        return None
    return Path(os.fsdecode(result.stdout).strip()).resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _task_targets(task) -> list[Path]:
    """Return source targets the task bundle authorizes the agent to edit."""
    writable_sources = getattr(task, "writable_sources", None) or []
    if not task.source and not writable_sources:
        return []
    cfg = task.cfg
    targets = [Path(task.source).resolve()] if task.source else []
    targets.extend(Path(path).resolve() for path in writable_sources)
    collection_wide = False
    if task.key == "__general__":
        from .loop.adapters import general_targets_collection

        collection_wide = general_targets_collection(task.entry, cfg)
    elif (task.agent or {}).get("elevated"):
        collection_wide = True
    if collection_wide:
        targets = [Path(cfg["repo_root"]).resolve(), *targets]
        targets.extend(Path(spec["source"]).resolve() for spec in app_specs(cfg) if spec.get("source"))
    seen: set[Path] = set()
    return [path for path in targets if not (path in seen or seen.add(path))]


def _source_owners(task) -> list[dict]:
    """Group writable targets by their nearest owning Git repository."""
    grouped: dict[tuple[bool, str], dict] = {}
    for target in _task_targets(task):
        repo = _git_root(target)
        if repo is not None:
            try:
                rel = target.relative_to(repo).as_posix() or "."
            except ValueError as exc:
                raise CheckpointError(f"source target {target} is outside owning repository {repo}") from exc
            key = (True, str(repo))
            owner = grouped.setdefault(key, {"path": str(repo), "git": True, "scopes": []})
        else:
            root = target if target.is_dir() else target.parent
            root = root.resolve()
            rel = "." if target == root else target.relative_to(root).as_posix()
            key = (False, str(root))
            owner = grouped.setdefault(key, {"path": str(root), "git": False, "scopes": []})
        if rel not in owner["scopes"]:
            owner["scopes"].append(rel)

    # A collection-wide parent scope contains gitlinks, not the nested app's files. Registered app
    # targets above add those child repositories independently. Remove redundant child scopes only
    # inside the same owning repository.
    feedback_root = (
        Path(task.cfg["repo_root"]) / (task.cfg.get("feedback") or {}).get("dir", "feedback")
    ).resolve()
    for owner in grouped.values():
        scopes = sorted(owner["scopes"])
        if "." in scopes:
            owner["scopes"] = ["."]
        else:
            kept: list[str] = []
            for scope in scopes:
                if any(scope == parent or scope.startswith(parent.rstrip("/") + "/") for parent in kept):
                    continue
                kept.append(scope)
            owner["scopes"] = kept
        owner_root = Path(owner["path"])
        owner["excludes"] = []
        if _is_relative_to(feedback_root, owner_root):
            owner["excludes"].append(feedback_root.relative_to(owner_root).as_posix())
    return sorted(grouped.values(), key=lambda row: row["path"])


def _zpaths(raw: bytes) -> list[str]:
    return [os.fsdecode(value) for value in raw.split(b"\0") if value]


def _scope_args(scopes: list[str]) -> list[str]:
    return ["--", *scopes]


def _store_object(objects: Path, content: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(content).hexdigest()
    destination = objects / digest
    if not destination.exists():
        objects.mkdir(parents=True, exist_ok=True)
        temp = destination.with_name(f".{digest}.{os.getpid()}.tmp")
        try:
            with temp.open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.replace(temp, destination)
            except OSError:
                if not destination.exists():
                    raise
        finally:
            try:
                temp.unlink()
            except OSError:
                pass
    return digest, f"objects/{digest}"


def _path_excluded(path: str, excludes: list[str]) -> bool:
    return any(path == excluded or path.startswith(excluded.rstrip("/") + "/") for excluded in excludes)


def _index_entries(repo: Path, scopes: list[str], excludes: list[str] | None = None) -> list[dict]:
    excludes = excludes or []
    raw = _git(repo, "ls-files", "-z", "--stage", *_scope_args(scopes)).stdout
    entries: list[dict] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, separator, raw_path = record.partition(b"\t")
        if not separator:
            raise CheckpointError(f"unexpected git index record in {repo}: {record!r}")
        try:
            mode, oid, stage = meta.decode("ascii").split(" ")
        except ValueError as exc:
            raise CheckpointError(f"unexpected git index metadata in {repo}: {meta!r}") from exc
        path = os.fsdecode(raw_path)
        if not _path_excluded(path, excludes):
            entries.append({"path": path, "mode": mode, "oid": oid, "stage": int(stage)})
    return sorted(entries, key=lambda row: (row["path"], row["stage"]))


def _file_record(path: Path, rel: str, objects: Path | None, *, gitlink: bool = False) -> dict:
    if gitlink:
        child_head = _git_text(path, "rev-parse", "HEAD") if path.is_dir() else None
        return {"path": rel, "type": "gitlink", "head": child_head}
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"path": rel, "type": "missing"}
    mode = stat.S_IMODE(info.st_mode)
    if stat.S_ISLNK(info.st_mode):
        content = os.fsencode(os.readlink(path))
        kind = "symlink"
    elif stat.S_ISREG(info.st_mode):
        content = path.read_bytes()
        kind = "file"
    elif stat.S_ISDIR(info.st_mode):
        return {"path": rel, "type": "directory", "mode": mode}
    else:
        raise CheckpointError(f"unsupported source file type: {path}")
    digest = hashlib.sha256(content).hexdigest()
    record = {"path": rel, "type": kind, "mode": mode, "digest": digest, "size": len(content)}
    if objects is not None:
        _, record["object"] = _store_object(objects, content)
    return record


def _git_file_paths(repo: Path, scopes: list[str], excludes: list[str] | None = None) -> list[str]:
    raw = _git(
        repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard", *_scope_args(scopes)
    ).stdout
    return sorted(path for path in set(_zpaths(raw)) if not _path_excluded(path, excludes or []))


def _walk_filesystem(root: Path, scopes: list[str], excludes: list[str] | None = None) -> list[str]:
    out: list[str] = []
    ignored_dirs = {".git", ".pytest_cache", ".ruff_cache", "__pycache__", "node_modules", "target"}
    for scope in scopes:
        start = root if scope == "." else root / scope
        if start.is_file() or start.is_symlink():
            out.append(start.relative_to(root).as_posix())
            continue
        if not start.exists():
            continue
        for base, dirs, files in os.walk(start):
            dirs[:] = [name for name in dirs if name not in ignored_dirs]
            base_path = Path(base)
            out.extend((base_path / name).relative_to(root).as_posix() for name in files)
    return sorted(path for path in set(out) if not _path_excluded(path, excludes or []))


def _dirty_paths(repo: Path, kind: str, scopes: list[str], excludes: list[str] | None = None) -> list[str]:
    if kind == "staged":
        args = ["diff", "--cached", "--name-only", "-z"]
    elif kind == "unstaged":
        args = ["diff", "--name-only", "-z"]
    elif kind == "untracked":
        args = ["ls-files", "--others", "--exclude-standard", "-z"]
    else:
        raise ValueError(kind)
    return sorted(
        path for path in set(_zpaths(_git(repo, *args, *_scope_args(scopes)).stdout))
        if not _path_excluded(path, excludes or [])
    )


def _fingerprint_payload(state: dict) -> dict:
    files = []
    for item in state.get("files") or []:
        files.append({key: value for key, value in item.items() if key != "object"})
    return {
        "head": state.get("head"),
        "branch": state.get("branch"),
        "files": files,
        "index": state.get("index") or [],
        "staged": state.get("staged") or [],
        "unstaged": state.get("unstaged") or [],
        "untracked": state.get("untracked") or [],
    }


def _with_fingerprint(state: dict) -> dict:
    encoded = json.dumps(_fingerprint_payload(state), sort_keys=True, separators=(",", ":")).encode()
    state["fingerprint"] = hashlib.sha256(encoded).hexdigest()
    return state


def _capture_state(owner: dict, objects: Path | None = None) -> dict:
    root = Path(owner["path"])
    scopes = owner["scopes"]
    excludes = owner.get("excludes") or []
    if owner.get("git"):
        index = _index_entries(root, scopes, excludes)
        gitlinks = {item["path"] for item in index if item["mode"] == "160000"}
        files = [_file_record(root / rel, rel, objects, gitlink=rel in gitlinks)
                 for rel in _git_file_paths(root, scopes, excludes)]
        state = {
            "observed_at": _now(),
            "head": _git_text(root, "rev-parse", "HEAD"),
            "branch": _git_text(root, "symbolic-ref", "--quiet", "--short", "HEAD"),
            "files": files,
            "index": index,
            "staged": _dirty_paths(root, "staged", scopes, excludes),
            "unstaged": _dirty_paths(root, "unstaged", scopes, excludes),
            "untracked": _dirty_paths(root, "untracked", scopes, excludes),
        }
    else:
        files = [_file_record(root / rel, rel, objects) for rel in _walk_filesystem(root, scopes, excludes)]
        state = {
            "observed_at": _now(),
            "head": None,
            "branch": None,
            "files": files,
            "index": [],
            "staged": [],
            "unstaged": [item["path"] for item in files],
            "untracked": [item["path"] for item in files],
        }
    return _with_fingerprint(state)


def _sanitize_profile(value: Any, key: str = "") -> Any:
    if any(token in key.lower() for token in ("token", "secret", "password", "api_key", "apikey")):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): _sanitize_profile(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_profile(item, key) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _collection_identity(cfg: dict) -> dict:
    root = Path(cfg["repo_root"]).resolve()
    repo = _git_root(root)
    return {
        "collection_repo": str(repo or root),
        "collection_head": _git_text(repo, "rev-parse", "HEAD") if repo else None,
        "collection_branch": _git_text(repo, "symbolic-ref", "--quiet", "--short", "HEAD") if repo else None,
    }


def create_checkpoint(task, adapter_name: str) -> dict:
    """Create and verify an atomic baseline before the watcher claims the item."""
    feedback_id = str(task.entry.get("id") or "")
    if not feedback_id:
        raise CheckpointError("feedback item has no id")
    destination = checkpoint_path(task.cfg, feedback_id)
    if destination.exists():
        raise CheckpointError(
            f"an unresolved checkpoint already exists for {feedback_id}; inspect it with "
            f"`curiator run recovery {feedback_id}`"
        )
    owners = _source_owners(task)
    objects = _objects_dir(task.cfg, feedback_id)
    run_id = uuid.uuid4().hex
    try:
        captured = []
        for owner in owners:
            baseline = _capture_state(owner, objects)
            captured.append({
                **owner,
                "head": baseline.get("head"),
                "branch": baseline.get("branch"),
                "dirty_fingerprint": baseline["fingerprint"],
                "baseline": baseline,
            })
        # A second pass closes the race between reading content objects and publishing the manifest.
        for owner in captured:
            verified = _capture_state(owner)
            if verified["fingerprint"] != owner["baseline"]["fingerprint"]:
                raise CheckpointError(f"source changed while checkpointing {owner['path']}; dispatch refused")
        source_scope = [
            {
                "repo": owner["path"],
                "path": scope,
                "type": "git" if owner.get("git") else "filesystem",
                "baseline_digest": owner["baseline"]["fingerprint"],
            }
            for owner in captured
            for scope in owner["scopes"]
        ]
        manifest = {
            "checkpoint_version": CHECKPOINT_VERSION,
            "run_id": run_id,
            "feedback_id": feedback_id,
            "app_key": task.key,
            "task_file": task.task_file,
            "reply_file": task.reply_file,
            "started_at": _now(),
            "agent_adapter": adapter_name,
            "agent_profile": _sanitize_profile(task.agent or {}),
            "watcher_pid": os.getpid(),
            "recovery_status": "active",
            "source_scope": source_scope,
            "owning_repos": captured,
            **_collection_identity(task.cfg),
        }
        _atomic_json(destination, manifest)
        from . import run_manifest

        run_manifest.create(task, adapter_name, manifest)
        return manifest
    except Exception:
        shutil.rmtree(run_dir(task.cfg, feedback_id), ignore_errors=True)
        raise


def load_checkpoint(cfg: dict, feedback_id: str) -> dict:
    path = checkpoint_path(cfg, feedback_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CheckpointError(f"no active checkpoint for {feedback_id}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckpointError(f"checkpoint for {feedback_id} is unreadable: {exc}") from exc
    if payload.get("checkpoint_version") != CHECKPOINT_VERSION:
        raise CheckpointError(
            f"unsupported checkpoint version {payload.get('checkpoint_version')!r} for {feedback_id}"
        )
    if payload.get("feedback_id") != feedback_id or not isinstance(payload.get("owning_repos"), list):
        raise CheckpointError(f"checkpoint for {feedback_id} is malformed")
    return payload


def record_process_end(cfg: dict, feedback_id: str, reason: str, *, overwrite: bool = False) -> dict:
    manifest = load_checkpoint(cfg, feedback_id)
    if manifest.get("process_end") and not overwrite:
        return manifest
    states = []
    for owner in manifest["owning_repos"]:
        states.append({"path": owner["path"], "state": _capture_state(owner)})
    manifest["process_end"] = {"observed_at": _now(), "reason": reason, "repos": states}
    manifest["recovery_status"] = "interrupted"
    _atomic_json(checkpoint_path(cfg, feedback_id), manifest)
    from . import run_manifest

    run_manifest.mark_process_end(cfg, feedback_id, manifest["process_end"])
    return manifest


def _entry_map(items: list[dict], keys: tuple[str, ...]) -> dict[tuple, dict]:
    return {tuple(item.get(key) for key in keys): item for item in items}


def _state_diff(before: dict, after: dict) -> list[str]:
    changed: set[str] = set()
    before_files = _entry_map(before.get("files") or [], ("path",))
    after_files = _entry_map(after.get("files") or [], ("path",))
    for key in set(before_files) | set(after_files):
        left = {k: v for k, v in before_files.get(key, {}).items() if k != "object"}
        right = {k: v for k, v in after_files.get(key, {}).items() if k != "object"}
        if left != right:
            changed.add(str(key[0]))
    before_index = _entry_map(before.get("index") or [], ("path", "stage"))
    after_index = _entry_map(after.get("index") or [], ("path", "stage"))
    for key in set(before_index) | set(after_index):
        if before_index.get(key) != after_index.get(key):
            changed.add(str(key[0]))
    for field in ("staged", "unstaged", "untracked"):
        changed.update(set(before.get(field) or []) ^ set(after.get(field) or []))
    if before.get("head") != after.get("head"):
        changed.add("<HEAD>")
    if before.get("branch") != after.get("branch"):
        changed.add("<branch>")
    return sorted(changed)


def _states_by_repo(process_end: dict) -> dict[str, dict]:
    return {str(row.get("path")): row.get("state") or {} for row in process_end.get("repos") or []}


def recovery_report(cfg: dict, feedback_id: str, *, capture_end_if_missing: bool = False,
                    end_reason: str = "stale watcher run observed during recovery") -> dict:
    manifest = load_checkpoint(cfg, feedback_id)
    if not manifest.get("process_end") and capture_end_if_missing:
        manifest = record_process_end(cfg, feedback_id, end_reason)
    end = manifest.get("process_end")
    end_states = _states_by_repo(end or {})
    repos = []
    all_agent: list[str] = []
    all_post: list[str] = []
    preexisting: dict[str, dict[str, list[str]]] = {}
    for owner in manifest["owning_repos"]:
        repo_path = owner["path"]
        baseline = owner["baseline"]
        current = _capture_state(owner)
        ended = end_states.get(repo_path)
        agent_paths = _state_diff(baseline, ended) if ended else []
        post_paths = _state_diff(ended, current) if ended else []
        label = Path(repo_path).name or repo_path
        all_agent.extend(f"{label}:{path}" for path in agent_paths)
        all_post.extend(f"{label}:{path}" for path in post_paths)
        preexisting[label] = {
            "staged": list(baseline.get("staged") or []),
            "unstaged": list(baseline.get("unstaged") or []),
            "untracked": list(baseline.get("untracked") or []),
        }
        repos.append({
            "path": repo_path,
            "scopes": owner["scopes"],
            "baseline_head": baseline.get("head"),
            "process_end_head": ended.get("head") if ended else None,
            "current_head": current.get("head"),
            "agent_run_paths": agent_paths,
            "post_interruption_paths": post_paths,
        })
    source_delta = bool(all_agent)
    report = {
        "feedback_id": feedback_id,
        "app_key": manifest.get("app_key"),
        "run_id": manifest.get("run_id"),
        "status": manifest.get("recovery_status"),
        "started_at": manifest.get("started_at"),
        "process_ended_at": end.get("observed_at") if end else None,
        "interruption_reason": end.get("reason") if end else None,
        "source_delta": source_delta if end else None,
        "restore_safe": bool(end) and not all_post,
        "preexisting": preexisting,
        "agent_run_paths": sorted(all_agent),
        "post_interruption_paths": sorted(all_post),
        "repos": repos,
    }
    if not end:
        report["restore_safe"] = False
        report["reason"] = "the agent process-end state has not been captured"
    elif all_post:
        report["reason"] = "source changed after the agent process ended"
    elif not source_delta:
        report["reason"] = "the run made no source changes"
    else:
        report["reason"] = "partial source changes are isolated and recoverable"
    return report


def format_report(report: dict) -> str:
    lines = [
        f"Recovery for {report['app_key']}/{report['feedback_id']}",
        f"run: {report.get('run_id') or '-'}",
        f"status: {report.get('status') or '-'}",
        f"interruption: {report.get('interruption_reason') or 'not captured'}",
        f"source delta: {report.get('source_delta')}",
        f"restore safe: {'yes' if report.get('restore_safe') else 'no'}",
    ]
    if report.get("agent_run_paths"):
        lines.append("agent-run paths:")
        lines.extend(f"  - {path}" for path in report["agent_run_paths"])
    if report.get("post_interruption_paths"):
        lines.append("post-interruption paths:")
        lines.extend(f"  - {path}" for path in report["post_interruption_paths"])
    if not report.get("agent_run_paths") and report.get("source_delta") is False:
        lines.append("agent-run paths: none")
    lines.append(f"classification: {report.get('reason') or '-'}")
    return "\n".join(lines)


def _find_feedback(cfg: dict, feedback_id: str) -> tuple[str, dict]:
    for app_key, entries in ledger.load(cfg).items():
        for entry in entries if isinstance(entries, list) else []:
            if entry.get("id") == feedback_id and entry.get("kind") != "system":
                return app_key, entry
    raise CheckpointError(f"feedback id {feedback_id!r} was not found in the ledger")


def append_trace(cfg: dict, feedback_id: str, text: str) -> None:
    from .loop import runlog

    runlog.append(runlog.reply_path(cfg, feedback_id), f"\n[{_now()}] {text}\n")


def _record_decision(cfg: dict, feedback_id: str, text: str, *, status: str | None = None) -> None:
    app_key, _ = _find_feedback(cfg, feedback_id)
    ledger.add_system_note(
        cfg, app_key, text, reply_to=[feedback_id], agent="curiator recovery"
    )
    if status:
        ledger.set_status(cfg, app_key, [feedback_id], status)
    append_trace(cfg, feedback_id, text)


def retire_checkpoint(cfg: dict, feedback_id: str, decision: str, *, note: str | None = None) -> Path:
    manifest = load_checkpoint(cfg, feedback_id)
    manifest["recovery_status"] = decision
    manifest["retired_at"] = _now()
    if note:
        manifest["retirement_note"] = note
    from . import run_manifest

    current_status = decision
    for entries in ledger.load(cfg).values():
        matched = next((item for item in entries if item.get("id") == feedback_id), None)
        if matched:
            current_status = str(matched.get("status") or decision)
            break

    run_manifest.finalize(
        cfg,
        feedback_id,
        status=current_status,
        decision=decision,
    )
    history = _history_dir(cfg, feedback_id) / f"{manifest['run_id']}.json"
    _atomic_json(history, manifest)
    shutil.rmtree(_objects_dir(cfg, feedback_id), ignore_errors=True)
    try:
        checkpoint_path(cfg, feedback_id).unlink()
    except OSError as exc:
        raise CheckpointError(f"could not retire checkpoint for {feedback_id}: {exc}") from exc
    return history


def _validate_objects(cfg: dict, manifest: dict) -> None:
    root = run_dir(cfg, manifest["feedback_id"])
    for owner in manifest["owning_repos"]:
        for item in owner["baseline"].get("files") or []:
            obj = item.get("object")
            if obj and not (root / obj).is_file():
                raise CheckpointError(f"baseline object is missing for {owner['path']}:{item['path']}")


def _restore_index(repo: Path, scopes: list[str], baseline: list[dict], excludes: list[str] | None = None) -> None:
    current = _index_entries(repo, scopes, excludes)
    for path in sorted({item["path"] for item in current}):
        _git(repo, "update-index", "--force-remove", "--", path)
    records = []
    for item in baseline:
        record = f"{item['mode']} {item['oid']} {item['stage']}\t".encode("ascii")
        records.append(record + os.fsencode(item["path"]) + b"\0")
    if records:
        _git(repo, "update-index", "-z", "--index-info", data=b"".join(records))


def _restore_owner(cfg: dict, feedback_id: str, owner: dict) -> None:
    root = Path(owner["path"])
    baseline = owner["baseline"]
    current = _capture_state(owner)
    baseline_files = {item["path"]: item for item in baseline.get("files") or []}
    current_files = {item["path"]: item for item in current.get("files") or []}
    for rel, item in sorted(current_files.items(), reverse=True):
        baseline_item = baseline_files.get(rel)
        if (baseline_item and baseline_item.get("type") != "missing") or item.get("type") == "gitlink":
            continue
        path = root / rel
        if path.is_symlink() or path.is_file():
            path.unlink()
    object_root = run_dir(cfg, feedback_id)
    for rel, item in baseline_files.items():
        if item.get("type") in {"gitlink", "missing"}:
            continue
        path = root / rel
        if item.get("type") == "directory":
            path.mkdir(parents=True, exist_ok=True)
            os.chmod(path, int(item.get("mode", 0o755)))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.is_file():
            path.unlink()
        content = (object_root / item["object"]).read_bytes()
        if item["type"] == "symlink":
            os.symlink(os.fsdecode(content), path)
        else:
            temp = path.with_name(f".{path.name}.{os.getpid()}.restore")
            temp.write_bytes(content)
            os.chmod(temp, int(item.get("mode", 0o644)))
            os.replace(temp, path)
    if owner.get("git"):
        _restore_index(root, owner["scopes"], baseline.get("index") or [], owner.get("excludes") or [])


def restore_baseline(cfg: dict, feedback_id: str) -> dict:
    manifest = load_checkpoint(cfg, feedback_id)
    report = recovery_report(cfg, feedback_id)
    if not report.get("restore_safe"):
        changed = ", ".join(report.get("post_interruption_paths") or [])
        detail = f": {changed}" if changed else ""
        raise CheckpointError(f"restore refused because source changed after process end{detail}")
    _validate_objects(cfg, manifest)
    for owner in manifest["owning_repos"]:
        _restore_owner(cfg, feedback_id, owner)
    failures = []
    for owner in manifest["owning_repos"]:
        current = _capture_state(owner)
        if current["fingerprint"] != owner["baseline"]["fingerprint"]:
            failures.append(owner["path"])
    if failures:
        raise CheckpointError(f"baseline verification failed after restore in: {', '.join(failures)}")
    text = "Restored the checkpointed source scope to its exact pre-run baseline; requeued for a fresh run."
    _record_decision(cfg, feedback_id, text, status="new")
    retire_checkpoint(cfg, feedback_id, "restored", note=text)
    return {"ok": True, "feedback_id": feedback_id, "status": "new"}


def resume_partial(cfg: dict, feedback_id: str) -> dict:
    report = recovery_report(cfg, feedback_id)
    if report.get("post_interruption_paths"):
        changed = ", ".join(report["post_interruption_paths"])
        raise CheckpointError(f"resume refused because source changed after process end: {changed}")
    text = "Accepted the current partial source state as the next run baseline; requeued with the original task context."
    _record_decision(cfg, feedback_id, text, status="new")
    retire_checkpoint(cfg, feedback_id, "resumed", note=text)
    return {"ok": True, "feedback_id": feedback_id, "status": "new"}


def _branch_name(repo: Path, requested: str, run_id: str) -> str:
    candidate = requested
    check = _git(repo, "check-ref-format", "--branch", candidate, check=False)
    if check.returncode:
        raise CheckpointError(f"invalid recovery branch name {candidate!r}")
    if _git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}", check=False).returncode == 0:
        candidate = f"{requested}-{run_id[:8]}"
    return candidate


def _preserve_owner(owner: dict, feedback_id: str, requested: str, run_id: str) -> dict:
    if not owner.get("git"):
        raise CheckpointError(f"cannot preserve non-Git source as a branch: {owner['path']}")
    repo = Path(owner["path"])
    head = _git_text(repo, "rev-parse", "HEAD")
    if not head:
        raise CheckpointError(f"repository has no commit to branch from: {repo}")
    branch = _branch_name(repo, requested, run_id)
    descriptor, index_path = tempfile.mkstemp(prefix="curiator-index-")
    os.close(descriptor)
    os.unlink(index_path)
    try:
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = index_path
        _git(repo, "read-tree", head, env=env)
        _git(repo, "add", "-A", *_scope_args(owner["scopes"]), env=env)
        if owner.get("excludes"):
            _git(repo, "reset", "-q", head, "--", *owner["excludes"], env=env)
        changed = _git(repo, "diff-index", "--cached", "--quiet", head, check=False, env=env).returncode != 0
        if not changed:
            return {"repo": str(repo), "branch": None, "commit": None, "changed": False}
        tree = _git(repo, "write-tree", env=env).stdout.decode("ascii").strip()
    finally:
        try:
            Path(index_path).unlink()
        except OSError:
            pass
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "curIAtor Recovery")
    env.setdefault("GIT_AUTHOR_EMAIL", "recovery@curiator.local")
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    message = f"curiator recovery({feedback_id}): preserve interrupted source state\n"
    commit = _git(repo, "commit-tree", tree, "-p", head, data=message.encode(), env=env).stdout.decode("ascii").strip()
    _git(repo, "update-ref", f"refs/heads/{branch}", commit)
    return {"repo": str(repo), "branch": branch, "commit": commit, "changed": True}


def preserve_partial(cfg: dict, feedback_id: str, branch: str | None = None) -> dict:
    manifest = load_checkpoint(cfg, feedback_id)
    report = recovery_report(cfg, feedback_id)
    if report.get("source_delta") is not True:
        raise CheckpointError("there is no partial source delta to preserve")
    requested = branch or f"curiator/recovery/{feedback_id}"
    preserved = [
        _preserve_owner(owner, feedback_id, requested, manifest["run_id"])
        for owner in manifest["owning_repos"]
    ]
    created = [row for row in preserved if row["changed"]]
    summary = ", ".join(f"{Path(row['repo']).name}:{row['branch']}@{row['commit'][:8]}" for row in created)
    text = f"Preserved interrupted source state on recovery branch(es): {summary}. Ticket remains held."
    _record_decision(cfg, feedback_id, text, status="held")
    retire_checkpoint(cfg, feedback_id, "preserved", note=text)
    return {"ok": True, "feedback_id": feedback_id, "status": "held", "branches": created}


def discard_checkpoint(cfg: dict, feedback_id: str) -> dict:
    text = "Discarded the recovery checkpoint by explicit choice; current source files were left untouched."
    _record_decision(cfg, feedback_id, text, status="held")
    retire_checkpoint(cfg, feedback_id, "discarded", note=text)
    return {"ok": True, "feedback_id": feedback_id, "status": "held"}


def complete_checkpoint(cfg: dict, feedback_id: str, status: str) -> None:
    """Retire runtime objects once the normal reply/status path completed durably."""
    try:
        record_process_end(cfg, feedback_id, f"agent returned with ledger status {status}")
        retire_checkpoint(cfg, feedback_id, "completed", note=f"ledger status {status}")
    except CheckpointError:
        # Completion already made the ledger authoritative. Recovery artifacts must not turn a
        # successful agent reply into a retry; stale artifacts remain available for manual cleanup.
        return
