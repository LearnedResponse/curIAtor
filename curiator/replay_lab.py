"""Replay groups backed by independent Docker workspaces."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import ledger, workspace_store
from .config import app_spec
from .replay import ReplayError, inspect
from .workspaces import DEFAULT_IMAGE, WorkspaceError, WorkspaceManager


REPLAY_GROUP_VERSION = 1
_GROUP_ID_RE = re.compile(r"^[a-f0-9]{10}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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


def replays_dir(cfg: dict) -> Path:
    feedback = str((cfg.get("feedback") or {}).get("dir", "feedback"))
    return Path(cfg["repo_root"]) / feedback / "replays"


def group_path(cfg: dict, group_id: str) -> Path:
    return replays_dir(cfg) / group_id / "manifest.json"


def _feedback(cfg: dict, feedback_id: str) -> tuple[str, dict]:
    for key, entries in ledger.load(cfg).items():
        for entry in entries if isinstance(entries, list) else []:
            if entry.get("id") == feedback_id and entry.get("kind") != "system":
                return key, entry
    raise ReplayError(f"feedback id {feedback_id!r} not found")


def _thread(cfg: dict, key: str, entry: dict) -> list[dict]:
    from .loop.adapters import _related_thread_entries

    return [*_related_thread_entries(cfg, key, entry, limit=50), entry]


def _task_record(report: dict) -> dict:
    if report.get("manifest_source") == "recorded":
        return dict((report.get("manifest") or {}).get("task") or {})
    return dict(report.get("task") or {})


def _source_refs(cfg: dict, report: dict) -> tuple[str, str]:
    if report.get("manifest_source") == "reconstructed":
        source = report.get("source") or {}
        return str(source.get("owning_repo_base_sha") or ""), str(source.get("collection_base_sha") or "")
    manifest = report.get("manifest") or {}
    collection = str((manifest.get("collection") or {}).get("base_sha") or "")
    owners = ((manifest.get("source") or {}).get("owning_repos") or [])
    spec = app_spec(cfg, str(report.get("app_key"))) or {}
    source_path = Path(spec.get("source") or spec.get("root") or cfg["repo_root"]).resolve()
    owner = next(
        (item for item in owners if item.get("repo") and source_path.is_relative_to(Path(item["repo"]).resolve())),
        owners[0] if owners else {},
    )
    return str(owner.get("base_sha") or ""), collection


def _profile(cfg: dict, name: str) -> dict:
    configured = (((cfg.get("agent") or {}).get("replay_profiles") or {}).get(name) or {})
    if configured and not isinstance(configured, dict):
        raise ReplayError(f"agent.replay_profiles.{name} must be a mapping")
    base = cfg.get("agent") or {}
    if name == "codex":
        adapter = "codex"
    elif name == "claude":
        adapter = "headless-cc"
    else:
        adapter = configured.get("adapter") or base.get("adapter") or "headless-cc"
    return {
        "name": name,
        "adapter": str(adapter),
        "model": configured.get("model", base.get("model")),
        "autonomy": configured.get("autonomy", base.get("autonomy", "auto-small")),
        "capabilities": list(configured.get("capabilities") or []),
    }


def profile_names(cfg: dict) -> list[str]:
    """Return built-in and collection-declared replay profile names in stable order."""
    configured = ((cfg.get("agent") or {}).get("replay_profiles") or {})
    names = ["baseline", "codex", "claude", *(configured.keys() if isinstance(configured, dict) else [])]
    return list(dict.fromkeys(str(name) for name in names if str(name)))


def _credentials(profile: dict, requested: str) -> str:
    expected = "codex" if profile["adapter"] == "codex" else "claude" if profile["adapter"] == "headless-cc" else None
    selected = expected if requested == "auto" else requested
    if selected == "none":
        raise ReplayError("replay run needs --credentials auto|codex|claude to dispatch an agent")
    if expected and selected != expected:
        raise ReplayError(
            f"profile {profile['name']!r} uses {profile['adapter']}; expected --credentials {expected}, got {selected}"
        )
    return selected


def _copy_input(cfg: dict, group_id: str, report: dict, key: str, entry: dict) -> dict:
    root = replays_dir(cfg) / group_id
    root.mkdir(parents=True, exist_ok=True)
    task = _task_record(report)
    source = Path(str(task.get("path") or ""))
    copied_task = root / "original-task.md"
    thread = _thread(cfg, key, entry)
    if source.is_file():
        shutil.copy2(source, copied_task)
        task_source = "recorded"
    else:
        comments = []
        for item in thread:
            author = item.get("author") or ((item.get("user") or {}).get("name")) or "unknown"
            comments.append(
                f"## {author} [{item.get('id') or 'unknown'}]\n\n{item.get('comment') or ''}\n"
            )
        copied_task.write_text(
            "# Reconstructed replay input\n\n"
            "The original generated task bundle was not retained. This source-exact replay uses the "
            "preserved feedback thread below and regenerates the executable task with the current runner.\n\n"
            + "\n".join(comments),
            encoding="utf-8",
        )
        task_source = "reconstructed-thread"
    thread_path = root / "thread.json"
    thread_path.write_text(json.dumps(thread, indent=2) + "\n", encoding="utf-8")
    evidence = {
        "task": str(copied_task),
        "task_source": task_source,
        "task_sha256": _hash_text(copied_task.read_bytes()),
        "thread": str(thread_path),
        "thread_sha256": _hash_text(thread_path.read_bytes()),
        "media": [],
    }
    feedback = Path(cfg["repo_root"]) / str((cfg.get("feedback") or {}).get("dir", "feedback"))
    media = root / "input"
    for field in ("screenshot", "audio"):
        rel = entry.get(field)
        source_media = feedback / str(rel) if rel else None
        if source_media and source_media.is_file():
            media.mkdir(parents=True, exist_ok=True)
            destination = media / source_media.name
            shutil.copy2(source_media, destination)
            evidence["media"].append({
                "kind": field,
                "path": str(destination),
                "sha256": _hash_text(destination.read_bytes()),
            })
    return evidence


def _hash_text(value: str | bytes | None) -> str | None:
    if value is None:
        return None
    data = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _write_group(cfg: dict, group: dict) -> dict:
    _atomic_json(group_path(cfg, group["id"]), group)
    return group


def load_group(cfg: dict, group_id: str) -> dict:
    try:
        payload = json.loads(group_path(cfg, group_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError(f"replay group {group_id!r} not found or unreadable") from exc
    if payload.get("replay_group_version") != REPLAY_GROUP_VERSION:
        raise ReplayError(f"unsupported replay group version for {group_id}")
    return payload


def list_groups(cfg: dict) -> list[dict]:
    groups = []
    if not replays_dir(cfg).exists():
        return groups
    for path in sorted(replays_dir(cfg).glob("*/manifest.json"), reverse=True):
        try:
            groups.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return groups


def _variant_result(manager: WorkspaceManager, workspace_id: str, feedback_id: str) -> dict:
    row = manager.get(workspace_id)
    entries = manager.feedback(workspace_id) if row.get("status") == "running" else []
    entry = next((item for item in entries if item.get("id") == feedback_id), None)
    task = manager.state_file(workspace_id, f"tasks/{feedback_id}.md") if row.get("status") == "running" else None
    browser = manager.state_file(
        workspace_id, f"replies/{feedback_id}-browser-smoke/result.json",
    ) if row.get("status") == "running" else None
    browser_payload = None
    if browser:
        try:
            browser_payload = json.loads(browser.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            browser_payload = {"ok": False, "error": "browser result unreadable"}
    comparison = manager.diff(workspace_id) if row.get("status") not in {"deleted", "creating", "building"} else None
    descriptor = row.get("descriptor") or {}
    return {
        "workspace_status": row.get("status"),
        "feedback_status": (entry or {}).get("status"),
        "task_bundle_sha256": _hash_text(task),
        "browser": browser_payload,
        "diff": comparison,
        "url": manager.open_url(workspace_id) if row.get("host_port") else None,
        "image_digest": row.get("image_digest"),
        "runner_version": row.get("runner_version"),
        "effective_profile": {
            "adapter": descriptor.get("agent_adapter"),
            "model": descriptor.get("agent_model"),
            "autonomy": descriptor.get("agent_autonomy"),
        },
    }


def _record_evidence_consistency(group: dict) -> None:
    variants = group.get("variants") or []
    digests = [((item.get("result") or {}).get("task_bundle_sha256")) for item in variants]
    present = [value for value in digests if value]
    group["evidence_consistency"] = {
        "task_bundle_sha256": present[0] if present and len(set(present)) == 1 else None,
        "byte_identical_across_variants": bool(variants) and len(present) == len(variants) and len(set(present)) == 1,
        "variant_task_sha256": {item.get("id"): digest for item, digest in zip(variants, digests)},
    }


def redacted_group(group: dict) -> dict:
    """Return an export-safe replay summary without paths, URLs, source patches, or credentials."""
    variants = []
    for item in group.get("variants") or []:
        result = item.get("result") or {}
        browser = result.get("browser") or {}
        comparison = result.get("diff") or {}
        variants.append({
            "id": item.get("id"),
            "status": item.get("status"),
            "profile": dict(item.get("profile") or {}),
            "effective_profile": dict(result.get("effective_profile") or {}),
            "feedback_status": result.get("feedback_status"),
            "browser_ok": browser.get("ok"),
            "changed": bool(comparison.get("dirty") or comparison.get("commits") or comparison.get("patch")),
            "duration_seconds": item.get("duration_seconds"),
        })
    return {
        "id": group.get("id"),
        "feedback_id": group.get("feedback_id"),
        "app_key": group.get("app_key"),
        "status": group.get("status"),
        "exactness": group.get("exactness"),
        "completeness_reasons": list(group.get("completeness_reasons") or []),
        "evidence_consistency": dict(group.get("evidence_consistency") or {}),
        "review": dict(group.get("review") or {}),
        "variants": variants,
    }


def refresh_group(cfg: dict, group_id: str) -> dict:
    group = load_group(cfg, group_id)
    manager = WorkspaceManager(cfg)
    terminal = True
    for variant in group.get("variants") or []:
        try:
            variant["result"] = _variant_result(manager, variant["workspace_id"], group["feedback_id"])
            status = (variant["result"] or {}).get("feedback_status")
            variant["status"] = status or (variant["result"] or {}).get("workspace_status")
            if status in {None, "new", "working"}:
                terminal = False
        except (WorkspaceError, ReplayError) as exc:
            variant["status"] = "failed"
            variant["error"] = str(exc)
    group["status"] = "complete" if terminal else "running"
    _record_evidence_consistency(group)
    group["updated_at"] = _now()
    return _write_group(cfg, group)


def run_group(
    cfg: dict,
    feedback_id: str,
    *,
    profiles: list[str],
    credentials: str,
    image: str = DEFAULT_IMAGE,
    build_if_missing: bool = True,
    wait_agent: bool = True,
    timeout: float = 900,
    agent_network: bool = True,
    agent_sandbox: str = "container",
    group_id: str | None = None,
) -> dict:
    report = inspect(cfg, feedback_id)
    if report.get("exactness") not in {"exact", "source-exact"} or not report.get("workspace_ready"):
        raise ReplayError(
            f"feedback {feedback_id} is {report.get('exactness')}; source-exact workspace replay is unavailable"
        )
    key, entry = _feedback(cfg, feedback_id)
    if key == "__general__":
        raise ReplayError("collection-wide General replay is not implemented; use an app-scoped feedback item")
    source_ref, collection_ref = _source_refs(cfg, report)
    if not source_ref or not collection_ref:
        raise ReplayError("replay manifest does not contain both owning-repo and collection base SHAs")
    group_id = group_id or uuid.uuid4().hex[:10]
    if not _GROUP_ID_RE.fullmatch(group_id):
        raise ReplayError("replay group id must be ten lowercase hexadecimal characters")
    if group_path(cfg, group_id).exists():
        raise ReplayError(f"replay group {group_id!r} already exists")
    evidence = _copy_input(cfg, group_id, report, key, entry)
    group = {
        "replay_group_version": REPLAY_GROUP_VERSION,
        "id": group_id,
        "feedback_id": feedback_id,
        "app_key": key,
        "status": "creating",
        "created_at": _now(),
        "updated_at": _now(),
        "exactness": report.get("exactness"),
        "completeness_reasons": list(report.get("reasons") or []),
        "source": {"owning_repo_base_sha": source_ref, "collection_base_sha": collection_ref},
        "original_task_sha256": _task_record(report).get("sha256"),
        "input_evidence": evidence,
        "variants": [],
        "review": {"decision": None, "variant_id": None, "note": None},
    }
    _write_group(cfg, group)
    manager = WorkspaceManager(cfg)
    for index, name in enumerate(profiles, start=1):
        profile = _profile(cfg, name)
        provider_credentials = _credentials(profile, credentials)
        variant_id = f"v{index}-{uuid.uuid4().hex[:6]}"
        variant = {
            "id": variant_id,
            "profile": profile,
            "credentials": provider_credentials,
            "status": "creating",
            "workspace_id": None,
            "created_at": _now(),
            "started_at": _now(),
        }
        group["variants"].append(variant)
        _write_group(cfg, group)
        before_ids = {row["id"] for row in workspace_store.list_all(cfg, include_deleted=True)}
        started = time.monotonic()
        try:
            row = manager.create(
                key,
                ref=source_ref,
                collection_ref=collection_ref,
                name=f"replay-{feedback_id}-{name}",
                image=image,
                build_if_missing=build_if_missing,
                credentials=provider_credentials,
                feedback_id=feedback_id,
                dispatch_feedback=True,
                agent_network=agent_network,
                agent_sandbox=agent_sandbox,
                agent_adapter=profile["adapter"],
                agent_model=profile.get("model"),
                agent_autonomy=profile.get("autonomy"),
                wait=True,
            )
            replay_meta = {
                "group_id": group_id,
                "variant_id": variant_id,
                "feedback_id": feedback_id,
                "profile": profile,
                "original_task_sha256": group["original_task_sha256"],
            }
            descriptor = dict(row.get("descriptor") or {})
            descriptor["replay"] = replay_meta
            row = workspace_store.update(cfg, row["id"], descriptor=descriptor)
            workspace_store.event(cfg, row["id"], "replay", replay_meta)
            variant["workspace_id"] = row["id"]
            variant["status"] = "running"
            if wait_agent:
                finished = manager.wait_feedback(row["id"], feedback_id, timeout=timeout)
                variant["status"] = str(finished.get("status") or "unknown")
            variant["result"] = _variant_result(manager, row["id"], feedback_id)
        except (WorkspaceError, ReplayError) as exc:
            created = [
                row for row in workspace_store.list_all(cfg, include_deleted=True)
                if row["id"] not in before_ids and row.get("app_key") == key
            ]
            if created:
                variant["workspace_id"] = created[0]["id"]
            variant["status"] = "failed"
            variant["error"] = str(exc)
        variant["finished_at"] = _now()
        variant["duration_seconds"] = round(time.monotonic() - started, 3)
        group["updated_at"] = _now()
        _write_group(cfg, group)
    terminal = all(item.get("status") not in {"creating", "running", "new", "working"}
                   for item in group["variants"])
    group["status"] = "complete" if terminal else "running"
    _record_evidence_consistency(group)
    group["updated_at"] = _now()
    return _write_group(cfg, group)


def keep_variant(cfg: dict, group_id: str, variant_id: str) -> dict:
    group = load_group(cfg, group_id)
    variant = next((item for item in group.get("variants") or [] if item.get("id") == variant_id), None)
    if not variant or not variant.get("workspace_id"):
        raise ReplayError(f"variant {variant_id!r} not found in replay group {group_id}")
    review = group.get("review") or {}
    if review.get("decision") == "accepted":
        if review.get("variant_id") == variant_id:
            return group
        raise ReplayError(
            f"replay group {group_id} already preserved variant {review.get('variant_id')}; only one may be kept"
        )
    manager = WorkspaceManager(cfg)
    row = manager.keep(variant["workspace_id"])
    group["review"] = {"decision": "accepted", "variant_id": variant_id, "note": None}
    variant["status"] = "preserved"
    variant["preserved_ref"] = row.get("preserved_ref")
    group["updated_at"] = _now()
    return _write_group(cfg, group)


def delete_group(cfg: dict, group_id: str, *, force: bool = False) -> dict:
    group = load_group(cfg, group_id)
    manager = WorkspaceManager(cfg)
    for variant in group.get("variants") or []:
        workspace_id = variant.get("workspace_id")
        if not workspace_id:
            continue
        try:
            row = manager.get(workspace_id)
            if row.get("status") != "deleted":
                manager.delete(workspace_id, force=force)
            variant["status"] = "deleted"
        except WorkspaceError as exc:
            variant["delete_error"] = str(exc)
            if not force:
                raise ReplayError(str(exc)) from exc
    group["status"] = "deleted"
    group["deleted_at"] = _now()
    group["updated_at"] = _now()
    return _write_group(cfg, group)
