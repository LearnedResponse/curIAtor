"""Transactional agent-run checkpoints and explicit source recovery."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from curiator import ledger, run_recovery
from curiator.loop import adapters


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True).stdout


def _task(cfg: dict, source: Path):
    fid = ledger.save_entry(cfg, "sample", comment="transactional edit", ts="t")
    entry = next(item for item in ledger.load(cfg)["sample"] if item["id"] == fid)
    task = adapters.build_task(cfg, "sample", entry)
    task.source = str(source)
    return fid, task


def _path_state(root: Path, paths: list[str]) -> dict[str, tuple]:
    state = {}
    for rel in paths:
        path = root / rel
        if path.is_symlink():
            state[rel] = ("symlink", os.readlink(path))
        elif path.is_file():
            state[rel] = ("file", path.read_bytes(), path.stat().st_mode & 0o777)
        else:
            state[rel] = ("missing",)
    return state


def test_checkpoint_restores_dirty_index_worktree_untracked_and_binary(cfg, collection):
    apps = collection / "apps"
    (apps / "delete_me.txt").write_text("tracked delete\n")
    (apps / "rename_me.txt").write_text("tracked rename\n")
    (apps / "tracked.bin").write_bytes(b"\x00tracked\xff")
    _git(collection, "add", "apps")
    _git(collection, "commit", "-q", "-m", "recovery fixtures")

    (apps / "sample.py").write_text("# preexisting unstaged\n")
    (apps / "delete_me.txt").unlink()
    _git(collection, "mv", "apps/rename_me.txt", "apps/renamed.txt")
    (apps / "staged.txt").write_text("preexisting staged\n")
    _git(collection, "add", "apps/staged.txt")
    (apps / "untracked.bin").write_bytes(b"\x00preexisting\xfe")

    watched = [
        "apps/sample.py", "apps/delete_me.txt", "apps/rename_me.txt", "apps/renamed.txt",
        "apps/staged.txt", "apps/untracked.bin", "apps/tracked.bin", "apps/agent-new.txt",
    ]
    baseline_status = _git(collection, "status", "--porcelain=v1", "-z", "--", "apps")
    baseline_index = _git(collection, "ls-files", "--stage", "-z", "--", "apps")
    baseline_paths = _path_state(collection, watched)

    fid, task = _task(cfg, apps)
    manifest = run_recovery.create_checkpoint(task, "codex")
    assert manifest["feedback_id"] == fid
    assert manifest["checkpoint_version"] == 1
    assert manifest["source_scope"][0]["path"] == "apps"
    assert manifest["owning_repos"][0]["baseline"]["staged"] == ["apps/renamed.txt", "apps/staged.txt"]
    assert "apps/untracked.bin" in manifest["owning_repos"][0]["baseline"]["untracked"]

    (apps / "sample.py").write_text("agent partial\n")
    (apps / "delete_me.txt").write_text("agent recreated\n")
    (apps / "renamed.txt").write_text("agent changed rename\n")
    (apps / "staged.txt").write_text("agent changed staged\n")
    (apps / "untracked.bin").write_bytes(b"agent binary")
    (apps / "tracked.bin").write_bytes(b"\x00agent\xfd")
    (apps / "agent-new.txt").write_text("remove me\n")
    run_recovery.record_process_end(cfg, fid, "test interruption")
    report = run_recovery.recovery_report(cfg, fid)
    assert report["source_delta"] is True
    assert report["restore_safe"] is True
    assert any(path.endswith(":apps/tracked.bin") for path in report["agent_run_paths"])

    result = run_recovery.restore_baseline(cfg, fid)
    assert result["status"] == "new"
    assert _git(collection, "status", "--porcelain=v1", "-z", "--", "apps") == baseline_status
    assert _git(collection, "ls-files", "--stage", "-z", "--", "apps") == baseline_index
    assert _path_state(collection, watched) == baseline_paths
    assert not run_recovery.checkpoint_path(cfg, fid).exists()


def test_collection_scope_excludes_feedback_runtime_even_without_gitignore(cfg, collection):
    fid, task = _task(cfg, collection)
    manifest = run_recovery.create_checkpoint(task, "codex")
    owner = manifest["owning_repos"][0]
    assert owner["scopes"] == ["."]
    assert owner["excludes"] == ["feedback"]
    assert not any(item["path"].startswith("feedback/") for item in owner["baseline"]["files"])
    run_recovery.record_process_end(cfg, fid, "clean collection fixture")
    assert run_recovery.recovery_report(cfg, fid)["source_delta"] is False


def test_restore_refuses_post_interruption_change(cfg, collection):
    fid, task = _task(cfg, collection / "apps" / "sample.py")
    run_recovery.create_checkpoint(task, "codex")
    Path(task.source).write_text("agent partial\n")
    run_recovery.record_process_end(cfg, fid, "agent stopped")
    Path(task.source).write_text("human edit after stop\n")

    report = run_recovery.recovery_report(cfg, fid)
    assert report["restore_safe"] is False
    assert report["post_interruption_paths"]
    with pytest.raises(run_recovery.CheckpointError, match="changed after process end"):
        run_recovery.restore_baseline(cfg, fid)
    assert Path(task.source).read_text() == "human edit after stop\n"


def test_resume_accepts_partial_state_as_next_baseline(cfg):
    fid, task = _task(cfg, Path(cfg["repo_root"]) / "apps" / "sample.py")
    run_recovery.create_checkpoint(task, "codex")
    Path(task.source).write_text("partial to resume\n")
    run_recovery.record_process_end(cfg, fid, "agent stopped")

    assert run_recovery.resume_partial(cfg, fid)["status"] == "new"
    assert Path(task.source).read_text() == "partial to resume\n"
    assert not run_recovery.checkpoint_path(cfg, fid).exists()
    assert list((run_recovery.run_dir(cfg, fid) / "history").glob("*.json"))


def test_preserve_creates_branch_without_switching_or_marking_done(cfg, collection):
    fid, task = _task(cfg, collection / "apps" / "sample.py")
    branch_before = _git(collection, "branch", "--show-current").decode().strip()
    run_recovery.create_checkpoint(task, "codex")
    Path(task.source).write_text("preserved partial\n")
    run_recovery.record_process_end(cfg, fid, "agent stopped")

    result = run_recovery.preserve_partial(cfg, fid)
    row = result["branches"][0]
    assert row["branch"] == f"curiator/recovery/{fid}"
    assert _git(collection, "branch", "--show-current").decode().strip() == branch_before
    assert _git(collection, "show", f"{row['branch']}:apps/sample.py") == b"preserved partial\n"
    entry = next(item for item in ledger.load(cfg)["sample"] if item["id"] == fid)
    assert entry["status"] == "held"
    assert Path(task.source).read_text() == "preserved partial\n"


def test_nested_app_repo_is_checkpointed_and_restored_independently(cfg, collection):
    nested = collection / "apps" / "nested"
    nested.mkdir()
    (nested / "app.py").write_text("baseline\n")
    _git(nested, "init", "-q")
    _git(nested, "config", "user.name", "Nested Test")
    _git(nested, "config", "user.email", "nested@test.local")
    _git(nested, "add", "app.py")
    _git(nested, "commit", "-q", "-m", "init nested")

    fid, task = _task(cfg, nested)
    manifest = run_recovery.create_checkpoint(task, "codex")
    assert [row["path"] for row in manifest["owning_repos"]] == [str(nested)]
    (nested / "app.py").write_text("partial nested\n")
    run_recovery.record_process_end(cfg, fid, "nested interruption")
    run_recovery.restore_baseline(cfg, fid)
    assert (nested / "app.py").read_text() == "baseline\n"
    assert _git(nested, "status", "--porcelain") == b""


def test_run_recovery_cli_reports_and_resumes(cfg, collection, monkeypatch, capsys):
    from curiator import cli

    fid, task = _task(cfg, collection / "apps" / "sample.py")
    run_recovery.create_checkpoint(task, "codex")
    Path(task.source).write_text("cli partial\n")
    run_recovery.record_process_end(cfg, fid, "cli fixture")
    ledger.set_status(cfg, "sample", [fid], "held")
    monkeypatch.chdir(collection)

    assert cli.main(["run", "recovery", fid]) == 0
    report = capsys.readouterr().out
    assert f"Recovery for sample/{fid}" in report
    assert "restore safe: yes" in report
    assert cli.main(["run", "resume", fid]) == 0
    assert "recovery resume completed" in capsys.readouterr().out
    assert next(item for item in ledger.load(cfg)["sample"] if item["id"] == fid)["status"] == "new"
