"""Explicit shared-component scope, verification, history, and workspace snapshots."""
from __future__ import annotations

import argparse
import json
import subprocess
import textwrap
from pathlib import Path

import pytest
import yaml

from curiator import dependencies, gitmem, ledger
from curiator.config import load_config_at
from curiator.loop.adapters import build_task
from curiator.workspaces import WorkspaceManager, resolve_snapshot


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_repo(path: Path, name: str = "Dependency Test") -> None:
    _git(path, "init", "-q")
    _git(path, "config", "user.name", name)
    _git(path, "config", "user.email", "dependencies@test.local")


def _collection(tmp_path: Path, monkeypatch, *, commit: bool = False) -> tuple[Path, dict]:
    shared = tmp_path / "packages" / "shared"
    app_a = tmp_path / "apps" / "a"
    app_b = tmp_path / "apps" / "b"
    shared.mkdir(parents=True)
    app_a.mkdir(parents=True)
    app_b.mkdir(parents=True)
    (shared / "value.py").write_text("VALUE = 'initial'\n")
    (shared / "smoke.py").write_text(textwrap.dedent("""\
        from pathlib import Path
        log = Path(__file__).resolve().parents[2] / "events.log"
        log.write_text(log.read_text() + "component\\n" if log.exists() else "component\\n")
    """))
    for name, app_root in (("a", app_a), ("b", app_b)):
        (app_root / "app.py").write_text(f"NAME = {name!r}\n")
        (app_root / "smoke.py").write_text(textwrap.dedent(f"""\
            from pathlib import Path
            root = Path(__file__).resolve().parents[2]
            log = root / "events.log"
            assert log.exists() and log.read_text().startswith("component\\n")
            (root / {f'{name}.passed'!r}).write_text("passed\\n")
        """))
    (tmp_path / "gallery.yaml").write_text(textwrap.dedent(f"""\
        components:
          - key: shared
            root: packages/shared
            source: .
            smoke: python smoke.py
        apps:
          - name: a
            root: apps/a
            source: .
            smoke: python smoke.py
            depends_on: [shared]
            mount: {{kind: dash-inproc, module: app}}
          - name: b
            root: apps/b
            source: .
            smoke: python smoke.py
            depends_on: [shared]
            mount: {{kind: dash-inproc, module: app}}
        feedback: {{dir: feedback}}
        git:
          commit: {str(commit).lower()}
          include_ledger: true
          signoff: false
        shell: {{port: 8399}}
    """))
    _init_repo(tmp_path)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.setenv("CURIATOR_GALLERY", str(tmp_path / "gallery.yaml"))
    return tmp_path, load_config_at(tmp_path)


def test_task_context_grants_only_explicit_component_scope(tmp_path, monkeypatch):
    root, cfg = _collection(tmp_path, monkeypatch)
    read_only = build_task(cfg, "a", {"id": "read", "comment": "inspect it", "status": "new"})
    read_text = Path(read_only.task_file).read_text()
    assert "`shared`: `packages/shared` - **READ-ONLY**" in read_text
    assert read_only.writable_sources == []

    writable = build_task(cfg, "a", {
        "id": "write",
        "comment": "change the shared value",
        "status": "new",
        "writable_components": ["shared"],
    })
    write_text = Path(writable.task_file).read_text()
    assert "`shared`: `packages/shared` - **WRITABLE for this feedback**" in write_text
    assert writable.writable_sources == [str(root / "packages" / "shared")]
    assert "`a`, `b`" in write_text


def test_component_verification_is_first_and_covers_both_consumers(tmp_path, monkeypatch):
    root, cfg = _collection(tmp_path, monkeypatch)
    (root / "packages" / "shared" / "value.py").write_text("VALUE = 'changed'\n")

    with pytest.raises(dependencies.DependencyError, match="read-only shared component changed"):
        dependencies.verify_done(cfg, "a", {})

    receipt = dependencies.verify_done(cfg, "a", {"writable_components": ["shared"]})
    assert receipt["changed_components"] == ["shared"]
    assert [row["key"] for row in receipt["components"]] == ["shared"]
    assert {row["key"] for row in receipt["apps"]} == {"a", "b"}
    assert receipt["reload_apps"] == ["a", "b"]
    events = (root / "events.log").read_text().splitlines()
    assert events == ["component"]
    assert (root / "a.passed").exists()
    assert (root / "b.passed").exists()

    (root / "events.log").unlink()
    cfg["apps"][1]["smoke"] = "python -c \"raise SystemExit('consumer b failed')\""
    with pytest.raises(dependencies.DependencyError, match="dependent app smoke failed for b"):
        dependencies.verify_done(cfg, "a", {"writable_components": ["shared"]})


def test_component_done_rejects_dependent_source_edits(tmp_path, monkeypatch):
    root, cfg = _collection(tmp_path, monkeypatch)
    (root / "packages" / "shared" / "value.py").write_text("VALUE = 'changed'\n")
    (root / "apps" / "b" / "app.py").write_text("NAME = 'unauthorized change'\n")

    with pytest.raises(dependencies.DependencyError, match="dependent app source changed.*b"):
        dependencies.verify_done(cfg, "a", {"writable_components": ["shared"]})


def test_done_reloads_all_and_only_affected_apps(tmp_path, monkeypatch):
    root, cfg = _collection(tmp_path, monkeypatch)
    feedback_id = ledger.save_entry(
        cfg,
        "a",
        comment="update shared",
        extra={"writable_components": ["shared"]},
    )
    (root / "packages" / "shared" / "value.py").write_text("VALUE = 'changed'\n")
    reloaded = []
    monkeypatch.setattr("curiator.workflow_cli._reload_in_shell", lambda _cfg, app: reloaded.append(app) or "reloaded")

    from curiator.workflow_cli import cmd_reply

    assert cmd_reply(argparse.Namespace(
        app="a",
        feedback_id=feedback_id,
        text="Updated the shared value.",
        status="done",
        actions=None,
    )) == 0
    assert reloaded == ["a", "b"]
    item = next(row for row in ledger.load(cfg)["a"] if row["id"] == feedback_id)
    assert item["status"] == "done"


def test_failed_dependent_smoke_blocks_done_and_writes_trace(tmp_path, monkeypatch):
    root, cfg = _collection(tmp_path, monkeypatch)
    feedback_id = ledger.save_entry(
        cfg,
        "a",
        comment="update shared",
        extra={"writable_components": ["shared"]},
    )
    (root / "packages" / "shared" / "value.py").write_text("VALUE = 'changed'\n")
    gallery = yaml.safe_load((root / "gallery.yaml").read_text())
    gallery["apps"][1]["smoke"] = "python -c \"raise SystemExit('consumer b failed')\""
    (root / "gallery.yaml").write_text(yaml.safe_dump(gallery, sort_keys=False))

    from curiator.workflow_cli import cmd_reply

    with pytest.raises(SystemExit, match="dependent app smoke failed for b"):
        cmd_reply(argparse.Namespace(
            app="a",
            feedback_id=feedback_id,
            text="Updated the shared value.",
            status="done",
            actions=None,
        ))
    item = next(row for row in ledger.load(cfg)["a"] if row["id"] == feedback_id)
    assert item["status"] == "new"
    trace = (root / "feedback" / "replies" / f"{feedback_id}.md").read_text()
    assert "Shared dependency verification blocked done" in trace
    assert "dependent app smoke failed for b" in trace


def test_feedback_cli_records_and_validates_writable_components(tmp_path, monkeypatch):
    _root, cfg = _collection(tmp_path, monkeypatch)
    from curiator import cli

    assert cli.main([
        "feedback",
        "add",
        "a",
        "update shared",
        "--writable-component",
        "shared",
    ]) == 0
    item = ledger.load(cfg)["a"][-1]
    assert item["writable_components"] == ["shared"]

    with pytest.raises(SystemExit, match="outside the dependency closure for 'a'"):
        cli.main([
            "feedback",
            "add",
            "a",
            "bad scope",
            "--writable-component",
            "missing",
        ])


def test_cycle_diagnostic_names_the_path(tmp_path, monkeypatch):
    _root, cfg = _collection(tmp_path, monkeypatch)
    cfg["components"] = [
        {"key": "left", "root": "packages/shared", "depends_on": ["right"]},
        {"key": "right", "root": "packages/shared", "depends_on": ["left"]},
    ]
    cfg["apps"][0]["depends_on"] = ["left"]
    cfg["apps"][1]["depends_on"] = []
    with pytest.raises(dependencies.DependencyError, match="left -> right -> left"):
        dependencies.normalize(cfg)


def test_nested_component_commits_before_parent_and_snapshot_pins_sha(tmp_path, monkeypatch):
    app_root = tmp_path / "apps" / "consumer"
    component_root = tmp_path / "packages" / "nested-shared"
    app_root.mkdir(parents=True)
    component_root.mkdir(parents=True)
    (app_root / "app.py").write_text("VALUE = 'consumer'\n")
    (component_root / "shared.py").write_text("VALUE = 'v1'\n")
    _init_repo(component_root, "Nested Component")
    _git(component_root, "add", "shared.py")
    _git(component_root, "commit", "-q", "-m", "component v1")
    (tmp_path / "gallery.yaml").write_text(textwrap.dedent("""\
        components:
          - key: nested_shared
            root: packages/nested-shared
            source: .
            smoke: python -m py_compile shared.py
        apps:
          - name: consumer
            root: apps/consumer
            source: .
            smoke: python -m py_compile app.py
            depends_on: [nested_shared]
            mount: {kind: dash-inproc, module: app}
        feedback: {dir: feedback}
        git: {commit: true, include_ledger: true, signoff: false}
        shell: {port: 8399}
    """))
    _init_repo(tmp_path)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "register component")
    monkeypatch.setenv("CURIATOR_GALLERY", str(tmp_path / "gallery.yaml"))
    cfg = load_config_at(tmp_path)
    feedback_id = ledger.save_entry(
        cfg,
        "consumer",
        comment="update library",
        extra={"writable_components": ["nested_shared"]},
    )
    (component_root / "shared.py").write_text("VALUE = 'v2'\n")
    receipt = dependencies.verify_done(
        cfg,
        "consumer",
        {"writable_components": ["nested_shared"]},
    )
    assert receipt["reload_apps"] == ["consumer"]
    ledger.add_system_note(cfg, "consumer", "Updated library.", reply_to=[feedback_id])
    ledger.set_status(cfg, "consumer", [feedback_id], "done")

    result = gitmem.commit_run(
        cfg,
        "consumer",
        feedback_id,
        status="done",
        note_text="Updated library.",
    )
    assert result["committed"], result
    assert result["component_commits"][0]["components"] == ["nested_shared"]
    nested_sha = _git(component_root, "rev-parse", "HEAD")
    assert _git(tmp_path, "rev-parse", "HEAD:packages/nested-shared") == nested_sha
    assert _git(component_root, "status", "--porcelain") == ""

    descriptor = resolve_snapshot(cfg, "consumer")
    assert descriptor["dependency_closure"] == ["nested_shared"]
    assert descriptor["dependencies"][0]["owner_sha"] == nested_sha
    assert descriptor["dependencies"][0]["writable"] is False
    assert descriptor["dependency_repositories"] == [{
        "repo": str(component_root),
        "repo_rel": "packages/nested-shared",
        "sha": nested_sha,
        "volume": f"curiator-ws-{descriptor['id']}-dependency-0",
    }]

    class RecordingDocker:
        def __init__(self):
            self.calls = []

        def run(self, *args, **_kwargs):
            self.calls.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

    docker = RecordingDocker()
    WorkspaceManager(cfg, docker=docker)._initialize_volumes(
        descriptor,
        "curiator-workspace:test",
        "source-volume",
        "state-volume",
    )
    init_call = docker.calls[-1]
    assert f"{component_root}:/dependency-0:ro" in init_call
    dependency_arg = init_call[init_call.index("--dependency") + 1]
    assert json.loads(dependency_arg) == {
        "source": "/dependency-0",
        "sha": nested_sha,
        "rel": "packages/nested-shared",
        "readonly_target": "/workspace/dependency-volumes/0",
    }

    docker.calls.clear()
    WorkspaceManager(cfg, docker=docker)._create_container(
        descriptor,
        "curiator-workspace:test",
        "dependency-runtime",
        "source-volume",
        "state-volume",
        "none",
    )
    runtime_call = docker.calls[-1]
    assert (
        f"type=volume,source={descriptor['dependency_repositories'][0]['volume']},"
        "target=/workspace/source/packages/nested-shared,readonly"
    ) in runtime_call


def test_doctor_json_exposes_normalized_dependency_graph(tmp_path, monkeypatch, capsys):
    _root, _cfg = _collection(tmp_path, monkeypatch)
    from curiator import cli

    assert cli.main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dependencies"]["components"][0]["key"] == "shared"
    assert {row["app"] for row in payload["dependencies"]["apps"]} == {"a", "b"}
