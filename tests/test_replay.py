from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from curiator import ledger, replay, run_manifest, run_recovery
from curiator.loop.adapters import build_task


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _entry(cfg: dict, feedback_id: str) -> dict:
    return next(item for item in ledger.load(cfg)["sample"] if item["id"] == feedback_id)


def test_checkpoint_records_durable_exact_run_manifest(cfg, collection):
    fid = ledger.save_entry(cfg, "sample", comment="move the legend", user={"email": "test@example.com"})
    task = build_task(cfg, "sample", _entry(cfg, fid))
    checkpoint = run_recovery.create_checkpoint(task, "headless-cc")

    manifest = run_manifest.load(cfg, fid)
    assert manifest is not None
    assert manifest["run_manifest_version"] == 1
    assert manifest["run_id"] == checkpoint["run_id"]
    assert manifest["task"]["sha256"]
    assert Path(manifest["task"]["path"]).read_text() == Path(task.task_file).read_text()
    assert manifest["collection"]["base_sha"] == _git(collection, "rev-parse", "HEAD")
    assert manifest["source"]["owning_repos"][0]["preexisting"] == {
        "staged": [], "unstaged": [], "untracked": [],
    }
    assert manifest["input"]["thread_context_ids"] == [fid]

    report = replay.inspect(cfg, fid)
    assert report["exactness"] == "exact"
    assert report["workspace_ready"] is True
    assert report["manifest_source"] == "recorded"


def test_run_manifest_redacts_agent_secrets_and_finalizes(cfg):
    cfg["agent"]["api_token"] = "do-not-store-this"
    fid = ledger.save_entry(cfg, "sample", comment="safe profile")
    task = build_task(cfg, "sample", _entry(cfg, fid))
    run_recovery.create_checkpoint(task, "headless-cc")
    serialized = run_manifest.manifest_path(cfg, fid).read_text()
    assert "do-not-store-this" not in serialized
    assert "<redacted>" in serialized

    ledger.set_status(cfg, "sample", [fid], "done")
    run_recovery.complete_checkpoint(cfg, fid, "done")
    manifest = run_manifest.load(cfg, fid)
    assert manifest["state"] == "completed"
    assert manifest["output"]["status"] == "done"
    assert manifest["timing"]["finished_at"]
    assert run_recovery.checkpoint_path(cfg, fid).exists() is False
    assert run_manifest.manifest_path(cfg, fid).exists()


def test_replay_inspect_reconstructs_old_source_exact_base(cfg, collection):
    fid = ledger.save_entry(cfg, "sample", comment="historical fix")
    build_task(cfg, "sample", _entry(cfg, fid))
    base = _git(collection, "rev-parse", "HEAD")
    source = collection / "apps" / "sample.py"
    source.write_text(source.read_text() + "\n# historical fix\n")
    _git(collection, "add", "apps/sample.py")
    _git(collection, "commit", "-m", f"curator(sample): historical fix\n\nCuriator-Feedback: {fid}")
    accepted = _git(collection, "rev-parse", "HEAD")

    report = replay.inspect(cfg, fid)
    assert report["manifest_source"] == "reconstructed"
    assert report["exactness"] == "source-exact"
    assert report["source"]["owning_accepted_commit"] == accepted
    assert report["source"]["owning_repo_base_sha"] == base
    assert report["source"]["collection_base_sha"] == base
    assert report["task"]["exists"] is True
    assert report["workspace_ready"] is True


def test_replay_inspect_reports_context_partial_without_feedback_commit(cfg):
    fid = ledger.save_entry(cfg, "sample", comment="never committed")
    build_task(cfg, "sample", _entry(cfg, fid))
    report = replay.inspect(cfg, fid)
    assert report["exactness"] == "context-partial"
    assert report["workspace_ready"] is False
    assert any("no feedback-linked source commit" in reason for reason in report["reasons"])


def test_replay_cli_inspect_and_redacted_list(cfg, collection, monkeypatch, capsys):
    from curiator import cli

    fid = ledger.save_entry(cfg, "sample", comment="inspect me")
    build_task(cfg, "sample", _entry(cfg, fid))
    monkeypatch.chdir(collection)
    assert cli.main(["replay", "inspect", fid, "--json", "--redacted"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["feedback_id"] == fid
    assert "manifest" not in payload and "source" not in payload

    assert cli.main(["replay", "list", "--json", "--redacted"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert any(row["feedback_id"] == fid for row in rows)


def test_replay_group_launches_source_exact_workspace_and_records_result(cfg, collection, monkeypatch):
    from curiator import replay_lab

    fid = ledger.save_entry(cfg, "sample", comment="replay this")
    task = build_task(cfg, "sample", _entry(cfg, fid))
    base = _git(collection, "rev-parse", "HEAD")
    source = collection / "apps" / "sample.py"
    source.write_text(source.read_text() + "\n# accepted original\n")
    _git(collection, "add", "apps/sample.py")
    _git(collection, "commit", "-m", f"accepted original\n\nCuriator-Feedback: {fid}")
    calls = []

    class FakeManager:
        def __init__(self, _cfg):
            self.row = {
                "id": "workspace1", "status": "running", "host_port": 49152,
                "app_key": "sample", "descriptor": {},
            }

        def create(self, app, **kwargs):
            calls.append({"app": app, **kwargs})
            return dict(self.row)

        def wait_feedback(self, workspace_id, feedback_id, *, timeout):
            assert workspace_id == "workspace1" and feedback_id == fid and timeout == 30
            return {"id": fid, "status": "done"}

        def get(self, _workspace_id):
            return dict(self.row)

        def feedback(self, _workspace_id):
            return [{"id": fid, "status": "done"}]

        def state_file(self, _workspace_id, relative_path):
            if relative_path == f"tasks/{fid}.md":
                return Path(task.task_file).read_bytes()
            if relative_path.endswith("result.json"):
                return b'{"ok": true}'
            return None

        def diff(self, _workspace_id):
            return {"dirty": False, "commits": ["abc fix"], "patch": "diff", "status": ""}

        def open_url(self, _workspace_id):
            return "http://127.0.0.1:49152/?app=sample"

    monkeypatch.setattr(replay_lab, "WorkspaceManager", FakeManager)
    monkeypatch.setattr(
        replay_lab.workspace_store,
        "update",
        lambda _cfg, _wid, **changes: {**FakeManager(_cfg).row, **changes},
    )
    monkeypatch.setattr(replay_lab.workspace_store, "event", lambda *_args, **_kwargs: None)

    group = replay_lab.run_group(
        cfg,
        fid,
        profiles=["codex"],
        credentials="auto",
        build_if_missing=False,
        timeout=30,
    )
    assert group["status"] == "complete"
    assert group["variants"][0]["status"] == "done"
    assert group["variants"][0]["profile"]["adapter"] == "codex"
    assert group["variants"][0]["result"]["browser"]["ok"] is True
    assert group["variants"][0]["result"]["task_bundle_sha256"]
    assert group["variants"][0]["duration_seconds"] >= 0
    assert group["evidence_consistency"]["byte_identical_across_variants"] is True
    assert calls[0]["ref"] == base
    assert calls[0]["collection_ref"] == base
    assert calls[0]["feedback_id"] == fid
    assert calls[0]["dispatch_feedback"] is True
    assert calls[0]["agent_adapter"] == "codex"
    assert calls[0]["agent_autonomy"] == "auto-small"
    assert Path(group["input_evidence"]["task"]).read_text() == Path(task.task_file).read_text()
    assert group["input_evidence"]["task_sha256"] == group["original_task_sha256"]


def test_source_exact_replay_reconstructs_missing_task_from_thread(cfg, collection, monkeypatch):
    from curiator import replay_lab

    fid = ledger.save_entry(cfg, "sample", comment="compute the deterministic metric")
    base = _git(collection, "rev-parse", "HEAD")
    source = collection / "apps" / "sample.py"
    source.write_text(source.read_text() + "\n# accepted metric\n")
    _git(collection, "add", "apps/sample.py")
    _git(collection, "commit", "-m", f"accepted metric\n\nCuriator-Feedback: {fid}")

    class FakeManager:
        def __init__(self, _cfg):
            self.row = {"id": "ws-metric", "status": "running", "host_port": 49153,
                        "app_key": "sample", "descriptor": {}}

        def create(self, _app, **kwargs):
            assert kwargs["ref"] == base
            return dict(self.row)

        def wait_feedback(self, _workspace_id, _feedback_id, *, timeout):
            return {"status": "done"}

        def get(self, _workspace_id):
            return dict(self.row)

        def feedback(self, _workspace_id):
            return [{"id": fid, "status": "done"}]

        def state_file(self, _workspace_id, relative_path):
            return b"regenerated task" if relative_path.endswith(f"tasks/{fid}.md") else None

        def diff(self, _workspace_id):
            return {"dirty": False, "commits": ["abc metric"], "patch": "diff", "status": ""}

        def open_url(self, _workspace_id):
            return "http://127.0.0.1:49153/?app=sample"

    monkeypatch.setattr(replay_lab, "WorkspaceManager", FakeManager)
    monkeypatch.setattr(replay_lab.workspace_store, "update",
                        lambda _cfg, _wid, **changes: {**FakeManager(_cfg).row, **changes})
    monkeypatch.setattr(replay_lab.workspace_store, "event", lambda *_args, **_kwargs: None)

    group = replay_lab.run_group(
        cfg, fid, profiles=["codex"], credentials="auto", build_if_missing=False, timeout=10,
    )

    assert group["exactness"] == "source-exact"
    assert group["original_task_sha256"] is None
    assert group["input_evidence"]["task_source"] == "reconstructed-thread"
    task_text = Path(group["input_evidence"]["task"]).read_text()
    assert "original generated task bundle was not retained" in task_text
    assert "compute the deterministic metric" in task_text


def test_replay_group_redaction_removes_private_paths_urls_and_patches():
    from curiator.replay_lab import redacted_group

    payload = redacted_group({
        "id": "group1", "feedback_id": "feedback1", "app_key": "sample",
        "status": "complete", "exactness": "source-exact", "completeness_reasons": [],
        "input_evidence": {"task": "/private/task.md"},
        "source": {"collection_repo": "/private/repo"},
        "review": {"decision": None},
        "variants": [{
            "id": "v1", "status": "done", "credentials": "codex",
            "profile": {"adapter": "codex", "model": "gpt-test"},
            "result": {
                "url": "http://127.0.0.1:49152/?app=sample",
                "effective_profile": {"adapter": "codex", "model": "gpt-test"},
                "feedback_status": "done", "browser": {"ok": True, "screenshot": "/private/a.png"},
                "diff": {"dirty": False, "commits": ["abc"], "patch": "secret source"},
            },
        }],
    })

    serialized = json.dumps(payload)
    assert "/private" not in serialized
    assert "127.0.0.1" not in serialized
    assert "secret source" not in serialized
    assert "credentials" not in serialized
    assert payload["variants"][0]["changed"] is True


def test_replay_group_preserves_at_most_one_variant(cfg, monkeypatch):
    from curiator import replay_lab

    group = {
        "replay_group_version": 1,
        "id": "abcde12345",
        "feedback_id": "feedback",
        "app_key": "sample",
        "status": "complete",
        "review": {"decision": None, "variant_id": None, "note": None},
        "variants": [
            {"id": "v1", "workspace_id": "ws1", "status": "done"},
            {"id": "v2", "workspace_id": "ws2", "status": "done"},
        ],
    }
    replay_lab._write_group(cfg, group)

    class FakeManager:
        def __init__(self, _cfg):
            pass

        def keep(self, workspace_id):
            return {"preserved_ref": f"curiator/workspace/{workspace_id}"}

    monkeypatch.setattr(replay_lab, "WorkspaceManager", FakeManager)
    first = replay_lab.keep_variant(cfg, group["id"], "v1")
    assert first["review"] == {"decision": "accepted", "variant_id": "v1", "note": None}
    assert replay_lab.keep_variant(cfg, group["id"], "v1")["review"]["variant_id"] == "v1"
    with pytest.raises(replay.ReplayError, match="only one may be kept"):
        replay_lab.keep_variant(cfg, group["id"], "v2")


def test_replay_cli_requires_explicit_confirmation_for_variants(collection, monkeypatch, capsys):
    from curiator import cli

    monkeypatch.chdir(collection)
    assert cli.main([
        "replay", "run", "missing",
        "--profile", "codex", "--profile", "claude",
        "--credentials", "auto",
    ]) == 1
    assert "multi-variant replay requires --yes" in capsys.readouterr().out
