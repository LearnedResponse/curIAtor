"""Docker workspace descriptors, registry, lifecycle, and safety policy."""
from __future__ import annotations

import base64
import subprocess
import textwrap
from pathlib import Path

import pytest

from curiator import ledger, workspace_store
from curiator.config import load_config_at
from curiator.workspaces import WorkspaceError, WorkspaceManager, resolve_snapshot


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


class FakeDocker:
    binary = "/usr/bin/docker"

    def __init__(self, *, daemon: bool = True):
        self.calls: list[tuple[str, ...]] = []
        self.daemon = daemon
        self.running = False
        self.container_exists = False

    def runtime(self):
        return {
            "daemon_available": self.daemon,
            "daemon_reason": "fake daemon ready" if self.daemon else "fake daemon unavailable",
            "inside_container": False,
            "mounted_socket": None,
            "unsafe_socket_inside_container": False,
            "workspace_orchestration_available": self.daemon,
        }

    def inspect(self, kind: str, name: str):
        if kind == "image":
            return {"Id": "sha256:workspace-image"}
        if kind == "container" and self.container_exists:
            return {
                "State": {"Running": self.running, "Status": "running" if self.running else "exited"},
                "NetworkSettings": {"Ports": {"8399/tcp": [{"HostPort": "49177"}]}},
            }
        return None

    def run(self, *args: str, check: bool = True, timeout: int | None = None):
        self.calls.append(tuple(args))
        if args[:1] == ("create",):
            self.container_exists = True
            return subprocess.CompletedProcess(args, 0, "container-id\n", "")
        if args[:1] == ("start",):
            self.running = True
        elif args[:1] == ("stop",):
            self.running = False
        elif args[:2] == ("rm", "--force"):
            self.running = False
            self.container_exists = False
        return subprocess.CompletedProcess(args, 0, "", "")


def test_snapshot_resolves_historical_collection_ref_without_checkout(cfg, collection):
    original_branch = _git(collection, "branch", "--show-current")
    original_head = _git(collection, "rev-parse", "HEAD")
    (collection / "apps" / "sample.py").write_text("app = object()\n")
    _git(collection, "add", "apps/sample.py")
    _git(collection, "commit", "-q", "-m", "new app revision")
    current_head = _git(collection, "rev-parse", "HEAD")

    descriptor = resolve_snapshot(cfg, "sample", original_head, preview=True, name="Old Sample")
    assert descriptor["mode"] == "preview"
    assert descriptor["branch"] is None
    assert descriptor["collection_base_sha"] == original_head
    assert descriptor["owning_repo_base_sha"] == original_head
    assert descriptor["mounts"] == ["sample"]
    assert descriptor["name"] == "old-sample"
    assert _git(collection, "rev-parse", "HEAD") == current_head
    assert _git(collection, "branch", "--show-current") == original_branch


def test_snapshot_records_collection_and_nested_app_shas_separately(collection):
    nested = collection / "apps" / "nested"
    nested.mkdir()
    (nested / "server.py").write_text("print('nested')\n")
    _git(nested, "init", "-q")
    _git(nested, "config", "user.name", "Nested")
    _git(nested, "config", "user.email", "nested@example.com")
    _git(nested, "add", "server.py")
    _git(nested, "commit", "-q", "-m", "nested init")
    nested_sha = _git(nested, "rev-parse", "HEAD")
    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: nested
            root: apps/nested
            source: .
            mount: { kind: proxy, cmd: "python server.py", port: 8765 }
        shell: { port: 8399 }
    """))
    _git(collection, "add", "gallery.yaml", "apps/nested")
    _git(collection, "commit", "-q", "-m", "register nested")
    collection_sha = _git(collection, "rev-parse", "HEAD")
    cfg = load_config_at(collection)

    descriptor = resolve_snapshot(cfg, "nested", "HEAD", name="nested experiment")
    assert descriptor["collection_base_sha"] == collection_sha
    assert descriptor["owning_repo_base_sha"] == nested_sha
    assert descriptor["owning_repo_rel"] == "apps/nested"
    assert descriptor["branch"].startswith("curiator/workspace/nested-experiment-")


def test_snapshot_can_pin_collection_and_nested_app_history_independently(collection):
    nested = collection / "apps" / "nested-history"
    nested.mkdir()
    (nested / "server.py").write_text("print('v1')\n")
    _git(nested, "init", "-q")
    _git(nested, "config", "user.name", "Nested")
    _git(nested, "config", "user.email", "nested@example.com")
    _git(nested, "add", "server.py")
    _git(nested, "commit", "-q", "-m", "nested v1")
    nested_v1 = _git(nested, "rev-parse", "HEAD")
    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: nested_history
            root: apps/nested-history
            source: .
            mount: { kind: proxy, cmd: "python server.py", port: 8765 }
        shell: { port: 8399 }
    """))
    _git(collection, "add", "gallery.yaml", "apps/nested-history")
    _git(collection, "commit", "-q", "-m", "register nested v1")
    collection_v1 = _git(collection, "rev-parse", "HEAD")
    (nested / "server.py").write_text("print('v2')\n")
    _git(nested, "add", "server.py")
    _git(nested, "commit", "-q", "-m", "nested v2")
    _git(collection, "add", "apps/nested-history")
    _git(collection, "commit", "-q", "-m", "register nested v2")
    cfg = load_config_at(collection)

    descriptor = resolve_snapshot(
        cfg,
        "nested_history",
        nested_v1,
        collection_ref=collection_v1,
    )
    assert descriptor["owning_repo_base_sha"] == nested_v1
    assert descriptor["collection_base_sha"] == collection_v1
    assert descriptor["requested_collection_ref"] == collection_v1


def test_workspace_registry_shares_sqlite_without_breaking_feedback(cfg):
    ledger.save_entry(cfg, "sample", comment="before workspace", ts="t")
    docker = FakeDocker()
    manager = WorkspaceManager(cfg, docker=docker)
    manager._wait_http = lambda _port: None

    row = manager.create("sample", build_if_missing=False, wait=True)
    assert row["status"] == "running"
    assert row["host_port"] == 49177
    assert workspace_store.get(cfg, row["id"])["source_volume"].endswith("-source")
    assert [event["kind"] for event in workspace_store.events(cfg, row["id"])] == [
        "created", "building", "running",
    ]
    assert ledger.load(cfg)["sample"][0]["comment"] == "before workspace"

    container_create = next(call for call in docker.calls if call and call[0] == "create")
    joined = " ".join(container_create)
    assert "/var/run/docker.sock" not in joined
    assert "--cap-drop ALL" in joined
    assert "--state-dir /workspace/state" in joined
    assert "127.0.0.1::8399" in joined

    stopped = manager.stop(row["id"])
    assert stopped["status"] == "stopped"
    started = manager.start(row["id"])
    assert started["status"] == "running"


def test_workspace_seed_copies_only_relevant_thread_media(collection, tmp_path):
    import json
    from curiator import workspace_seed

    canonical_state = collection / "feedback"
    (canonical_state / "shots").mkdir(exist_ok=True)
    (canonical_state / "shots" / "thread.png").write_bytes(b"png")
    payload = {
        "app_key": "sample",
        "entries": [{
            "id": "source-id", "author": "user", "kind": "comment", "status": "held",
            "comment": "seed me", "screenshot": "shots/thread.png",
            "workspace_provenance": {"workspace_id": "ws-seed", "base_sha": "abc"},
        }],
    }
    payload_file = tmp_path / "seed.json"
    payload_file.write_text(json.dumps(payload))
    state = tmp_path / "workspace-state"
    assert workspace_seed.main([
        "--gallery", str(collection / "gallery.yaml"),
        "--state-dir", str(state),
        "--payload", str(payload_file),
        "--canonical-state", str(canonical_state),
    ]) == 0
    workspace_cfg = load_config_at(collection)
    workspace_cfg["feedback"]["dir"] = str(state)
    seeded = ledger.load(workspace_cfg)["sample"][0]
    assert seeded["workspace_provenance"]["workspace_id"] == "ws-seed"
    assert (state / "shots" / "thread.png").read_bytes() == b"png"


def test_credentials_are_staged_without_mounting_host_auth_in_runtime(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    auth = tmp_path / ".codex" / "auth.json"
    auth.parent.mkdir()
    auth.write_text("secret")
    docker = FakeDocker()
    manager = WorkspaceManager(cfg, docker=docker)

    manager._stage_credentials("codex", "curiator-workspace:test", "private-state")
    helper = docker.calls[-1]
    assert helper[:4] == ("run", "--rm", "--user", "0:0")
    assert f"{auth}:/run/curiator-credential:ro" in helper
    assert "curiator.workspace_credential" in helper

    descriptor = resolve_snapshot(cfg, "sample")
    manager._create_container(
        descriptor, "curiator-workspace:test", "runtime", "source", "private-state", "codex",
    )
    runtime = docker.calls[-1]
    assert runtime[0] == "create"
    assert not any(str(auth) in arg for arg in runtime)
    assert "--credentials" in runtime
    assert "codex" in runtime
    assert runtime[-4:] == ("--agent-network", "on", "--agent-sandbox", "container")


def test_workspace_container_applies_declared_agent_profile(cfg):
    docker = FakeDocker()
    manager = WorkspaceManager(cfg, docker=docker)
    descriptor = resolve_snapshot(cfg, "sample")

    manager._create_container(
        descriptor, "curiator-workspace:test", "runtime-profile", "source", "state", "codex",
        agent_adapter="codex", agent_model="gpt-test", agent_autonomy="auto",
    )

    runtime = docker.calls[-1]
    assert runtime[-6:] == (
        "--agent-adapter", "codex", "--agent-model", "gpt-test", "--agent-autonomy", "auto",
    )


def test_failed_workspace_creation_stays_inspectable_in_registry(cfg):
    docker = FakeDocker(daemon=False)
    manager = WorkspaceManager(cfg, docker=docker)
    with pytest.raises(WorkspaceError, match="fake daemon unavailable"):
        manager.create("sample", build_if_missing=False)
    rows = workspace_store.list_all(cfg)
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert "fake daemon unavailable" in rows[0]["failure_reason"]


def test_interrupted_workspace_creation_records_failure(cfg):
    manager = WorkspaceManager(cfg, docker=FakeDocker())

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    manager._bootstrap_source = interrupt
    with pytest.raises(KeyboardInterrupt):
        manager.create("sample", build_if_missing=False)

    row = workspace_store.list_all(cfg)[0]
    assert row["status"] == "failed"
    assert row["failure_reason"] == "workspace creation interrupted"
    assert workspace_store.events(cfg, row["id"])[-1]["kind"] == "failed"


def test_building_workspace_logs_read_persistent_bootstrap_log(cfg):
    class BootstrapDocker(FakeDocker):
        def run(self, *args: str, check: bool = True, timeout: int | None = None):
            self.calls.append(tuple(args))
            if any(arg.endswith("workspace-bootstrap.log") for arg in args):
                return subprocess.CompletedProcess(args, 0, "$ npm ci\ninstalled\n", "")
            return subprocess.CompletedProcess(args, 0, "", "")

    docker = BootstrapDocker()
    manager = WorkspaceManager(cfg, docker=docker)
    row = workspace_store.create(cfg, {
        "id": "building-log", "name": "building-log", "app_key": "sample",
        "mode": "branch", "status": "building", "collection_repo": str(cfg["repo_root"]),
        "collection_base_sha": "a" * 40, "owning_repo": str(cfg["repo_root"]),
        "owning_repo_base_sha": "a" * 40, "owning_repo_rel": None,
        "branch": "curiator/workspace/building-log", "container_id": None,
        "container_name": "curiator-ws-building-log", "source_volume": "source-log",
        "state_volume": "state-log", "host_port": None, "container_port": 8399,
        "image": "curiator-workspace:test", "image_digest": None, "runner_version": "test",
        "descriptor": {},
    })

    assert manager.logs(row["id"], tail=25) == "$ npm ci\ninstalled\n"
    helper = docker.calls[-1]
    assert helper[:4] == ("run", "--rm", "--user", "1000:1000")
    assert helper[-4:] == ("tail", "-n", "25", "/workspace/state/workspace-bootstrap.log")


def test_workspace_state_file_uses_binary_safe_base64(cfg):
    payload = b"\x89PNG\r\n\x1a\n\x00binary"

    class StateDocker(FakeDocker):
        def run(self, *args: str, check: bool = True, timeout: int | None = None):
            self.calls.append(tuple(args))
            return subprocess.CompletedProcess(args, 0, base64.b64encode(payload).decode("ascii"), "")

    docker = StateDocker()
    manager = WorkspaceManager(cfg, docker=docker)
    manager.get = lambda _workspace_id: {"container_name": "curiator-ws-binary"}

    assert manager.state_file("binary", "replies/result.png") == payload
    assert docker.calls[-1] == (
        "exec", "curiator-ws-binary", "base64", "-w", "0", "/workspace/state/replies/result.png",
    )


def test_delete_refuses_dirty_or_unexported_workspace_without_force(cfg):
    docker = FakeDocker()
    manager = WorkspaceManager(cfg, docker=docker)
    manager._wait_http = lambda _port: None
    row = manager.create("sample", build_if_missing=False)
    manager.diff = lambda _workspace_id: {
        "dirty": True, "commits": ["abc partial"], "status": " M app.py", "patch": "", "id": row["id"],
        "base_sha": row["owning_repo_base_sha"], "branch": row["branch"],
    }

    with pytest.raises(WorkspaceError, match="refusing to delete"):
        manager.delete(row["id"])
    assert workspace_store.get(cfg, row["id"])["status"] == "running"

    deleted = manager.delete(row["id"], force=True)
    assert deleted["status"] == "deleted"
    assert deleted["collection_repo"] == "."
    assert deleted["owning_repo"] == "."
    assert deleted["descriptor"]["collection_repo"] == "."
    assert str(Path(cfg["repo_root"]).resolve()).encode() not in ledger.db_path(cfg).read_bytes()
    assert any(call[:3] == ("volume", "rm", "--force") for call in docker.calls)


def test_apply_kept_branch_requires_clean_baseline_and_preserves_unrelated_dirt(cfg, collection):
    canonical_branch = _git(collection, "branch", "--show-current")
    base = _git(collection, "rev-parse", "HEAD")
    accepted_ref = "curiator/workspace/accepted"
    _git(collection, "switch", "-q", "-c", accepted_ref)
    sample = collection / "apps" / "sample.py"
    sample.write_text(sample.read_text() + "\n# Accepted workspace\n")
    _git(collection, "add", "apps/sample.py")
    _git(collection, "commit", "-q", "-m", "accepted workspace change")
    accepted = _git(collection, "rev-parse", "HEAD")
    _git(collection, "switch", "-q", canonical_branch)

    row = workspace_store.create(cfg, {
        "id": "apply-kept", "name": "apply-kept", "app_key": "sample",
        "mode": "branch", "status": "preserved", "collection_repo": str(collection),
        "collection_base_sha": base, "owning_repo": str(collection),
        "owning_repo_base_sha": base, "owning_repo_rel": None,
        "branch": accepted_ref, "container_id": None, "container_name": "unused",
        "source_volume": "unused-source", "state_volume": "unused-state", "host_port": None,
        "container_port": 8399, "image": "unused", "image_digest": None,
        "runner_version": "test", "preserved_ref": accepted_ref,
        "promoted_at": workspace_store.now(), "descriptor": {},
    })
    manager = WorkspaceManager(cfg, docker=FakeDocker())

    sample.write_text("human overlap\n")
    with pytest.raises(WorkspaceError, match="canonical files changed"):
        manager.apply(row["id"])
    _git(collection, "restore", "apps/sample.py")

    gallery = collection / "gallery.yaml"
    gallery.write_text(gallery.read_text() + "\n# staged unrelated\n")
    _git(collection, "add", "gallery.yaml")
    gallery.write_text(gallery.read_text() + "# unstaged unrelated\n")
    unrelated_status = _git(collection, "status", "--porcelain=v1")

    applied = manager.apply(row["id"])

    assert applied["status"] == "applied"
    assert applied["descriptor"]["applied_commit"] == accepted
    assert _git(collection, "rev-parse", "HEAD") == accepted
    assert "Accepted workspace" in sample.read_text()
    assert _git(collection, "status", "--porcelain=v1") == unrelated_status
    event = workspace_store.events(cfg, row["id"])[-1]
    assert event["kind"] == "applied"
    assert event["payload"]["canonical_ref"] == f"refs/heads/{canonical_branch}"


def test_apply_kept_branch_refuses_moved_canonical_head(cfg, collection):
    canonical_branch = _git(collection, "branch", "--show-current")
    base = _git(collection, "rev-parse", "HEAD")
    accepted_ref = "curiator/workspace/stale"
    _git(collection, "switch", "-q", "-c", accepted_ref)
    (collection / "apps" / "sample.py").write_text("accepted\n")
    _git(collection, "add", "apps/sample.py")
    _git(collection, "commit", "-q", "-m", "accepted")
    _git(collection, "switch", "-q", canonical_branch)
    (collection / "canonical.txt").write_text("moved\n")
    _git(collection, "add", "canonical.txt")
    _git(collection, "commit", "-q", "-m", "canonical moved")

    row = workspace_store.create(cfg, {
        "id": "apply-stale", "name": "apply-stale", "app_key": "sample",
        "mode": "branch", "status": "preserved", "collection_repo": str(collection),
        "collection_base_sha": base, "owning_repo": str(collection),
        "owning_repo_base_sha": base, "owning_repo_rel": None,
        "branch": accepted_ref, "container_id": None, "container_name": "unused",
        "source_volume": "unused-source", "state_volume": "unused-state", "host_port": None,
        "container_port": 8399, "image": "unused", "image_digest": None,
        "runner_version": "test", "preserved_ref": accepted_ref,
        "promoted_at": workspace_store.now(), "descriptor": {},
    })
    with pytest.raises(WorkspaceError, match="canonical baseline moved"):
        WorkspaceManager(cfg, docker=FakeDocker()).apply(row["id"])


def test_workspace_cli_create_passes_ref_preview_and_credentials(collection, monkeypatch, capsys):
    from curiator import cli, workspace_cli

    seen = {}
    row = {
        "id": "wscli", "status": "running", "mode": "preview", "app_key": "sample",
        "branch": None, "owning_repo_base_sha": "b" * 40, "host_port": 49200,
    }

    class FakeManager:
        def __init__(self, _cfg):
            pass

        def create(self, app, **kwargs):
            seen.update({"app": app, **kwargs})
            return row

        def open_url(self, workspace_id):
            return f"http://127.0.0.1:49200/?app=sample&id={workspace_id}"

        def apply(self, workspace_id):
            seen["applied"] = workspace_id
            return {**row, "status": "applied"}

    monkeypatch.setattr(workspace_cli, "WorkspaceManager", FakeManager)
    monkeypatch.chdir(collection)
    assert cli.main([
        "workspace", "create", "sample", "--from", "HEAD~1", "--name", "old sample",
        "--preview", "--credentials", "codex", "--no-build",
    ]) == 0
    assert seen["app"] == "sample"
    assert seen["ref"] == "HEAD~1"
    assert seen["preview"] is True
    assert seen["credentials"] == "codex"
    assert seen["agent_network"] is True
    assert seen["agent_sandbox"] == "container"
    assert seen["build_if_missing"] is False
    assert "http://127.0.0.1:49200" in capsys.readouterr().out

    assert cli.main(["workspace", "apply", "wscli"]) == 0
    assert seen["applied"] == "wscli"
