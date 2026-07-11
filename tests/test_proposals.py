from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from curiator import ledger, proposals
from curiator.config import load_config_at
from curiator.loop.adapters import build_task
from curiator.workflow_cli import _post_reply


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Proposal Test")
    _git(repo, "config", "user.email", "proposal@test.local")


def _collection(tmp_path: Path) -> tuple[dict, Path]:
    app_repo = tmp_path / "apps" / "sample"
    app_repo.mkdir(parents=True)
    _init_repo(app_repo)
    (app_repo / "app.py").write_text("VALUE = 'accepted'\n", encoding="utf-8")
    _git(app_repo, "add", "app.py")
    _git(app_repo, "commit", "-q", "-m", "accepted app")

    (tmp_path / "feedback").mkdir()
    (tmp_path / ".gitignore").write_text(
        "feedback/app_feedback.sqlite*\nfeedback/tasks/\nfeedback/replies/\n.curiator/worktrees/\n",
        encoding="utf-8",
    )
    (tmp_path / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            root: apps/sample
            source: app.py
            mount: {kind: dash-inproc, module: app}
            smoke: python -m py_compile app.py
        feedback:
          dir: feedback
        shell:
          port: 65500
        git:
          commit: true
          branch: per-run
          accepted_branch: main
          signoff: false
          include_ledger: false
        """), encoding="utf-8")
    _init_repo(tmp_path)
    _git(tmp_path, "add", ".gitignore", "gallery.yaml", "apps/sample")
    _git(tmp_path, "commit", "-q", "-m", "collection")
    return load_config_at(tmp_path / "gallery.yaml"), app_repo


def _feedback(cfg: dict, comment: str) -> tuple[str, dict]:
    feedback_id = ledger.save_entry(cfg, "sample", comment=comment)
    entry = next(row for row in ledger.load(cfg)["sample"] if row["id"] == feedback_id)
    return feedback_id, entry


def _add_second_app(cfg: dict, tmp_path: Path) -> dict:
    app_repo = tmp_path / "apps" / "other"
    app_repo.mkdir()
    _init_repo(app_repo)
    (app_repo / "app.py").write_text("VALUE = 'other accepted'\n", encoding="utf-8")
    _git(app_repo, "add", "app.py")
    _git(app_repo, "commit", "-q", "-m", "other accepted app")
    gallery = tmp_path / "gallery.yaml"
    gallery.write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            root: apps/sample
            source: app.py
            mount: {kind: dash-inproc, module: app}
            smoke: python -m py_compile app.py
          - name: other
            title: Other
            root: apps/other
            source: app.py
            mount: {kind: dash-inproc, module: app}
            smoke: python -m py_compile app.py
        feedback:
          dir: feedback
        shell:
          port: 65500
        git:
          commit: true
          branch: per-run
          accepted_branch: main
          signoff: false
          include_ledger: false
        """), encoding="utf-8")
    _git(tmp_path, "add", "gallery.yaml", "apps/other")
    _git(tmp_path, "commit", "-q", "-m", "add second app")
    return load_config_at(gallery)


def _finish(monkeypatch, cfg: dict, feedback_id: str, text: str = "Changed the proposal.") -> None:
    monkeypatch.setattr("curiator.workflow_cli._reload_in_shell", lambda *_args: "reloaded")
    _post_reply(cfg, "sample", feedback_id, text, "done")


def test_per_run_proposal_preview_and_approval(tmp_path, monkeypatch):
    cfg, app_repo = _collection(tmp_path)
    feedback_id, entry = _feedback(cfg, "change accepted to proposed")

    task_cfg, proposal = proposals.prepare_task_config(cfg, "sample", entry)
    assert proposal["branch"] == f"curiator/run/{feedback_id}"
    proposal_source = Path(task_cfg["apps"][0]["root"]) / "app.py"
    proposal_source.write_text("VALUE = 'proposed'\n", encoding="utf-8")
    _finish(monkeypatch, cfg, feedback_id)

    original = next(row for row in ledger.load(cfg)["sample"] if row["id"] == feedback_id)
    assert original["status"] == "awaiting_approval"
    preview = proposals.preview_for_app(cfg, "sample")
    assert preview and preview["feedback_id"] == feedback_id
    assert Path(preview["source"]).read_text(encoding="utf-8") == "VALUE = 'proposed'\n"
    assert (app_repo / "app.py").read_text(encoding="utf-8") == "VALUE = 'accepted'\n"
    _git(app_repo, "config", "--unset", "user.name")
    _git(app_repo, "config", "--unset", "user.email")

    result = proposals.approve(cfg, "sample", feedback_id, actor="test admin")

    assert result["action"] == "approved"
    assert (app_repo / "app.py").read_text(encoding="utf-8") == "VALUE = 'proposed'\n"
    assert proposals.preview_for_app(cfg, "sample") is None
    original = next(row for row in ledger.load(cfg)["sample"] if row["id"] == feedback_id)
    assert original["status"] == "done"
    rows = proposals.list_proposals(cfg, app="sample")
    assert any(row["feedback_id"] == feedback_id and row["state"] == "accepted" for row in rows)
    assert not any(row["feedback_id"] == feedback_id and row["state"] == "open" for row in rows)


def test_task_bundle_targets_worktree_and_pins_canonical_gallery(tmp_path):
    cfg, _app_repo = _collection(tmp_path)
    feedback_id, entry = _feedback(cfg, "change through a task bundle")

    task = build_task(cfg, "sample", entry)
    body = Path(task.task_file).read_text(encoding="utf-8")

    assert task.proposal["branch"] == f"curiator/run/{feedback_id}"
    assert task.source.startswith(task.proposal["worktree"])
    assert "## Per-run proposal workspace" in body
    assert f"curiator --gallery {cfg['gallery_path']} reply sample {feedback_id}" in body
    assert "Only an explicit Approve action merges it" in body


def test_new_same_app_run_supersedes_open_proposal(tmp_path, monkeypatch):
    cfg, _app_repo = _collection(tmp_path)
    first_id, first = _feedback(cfg, "first proposal")
    first_cfg, _ = proposals.prepare_task_config(cfg, "sample", first)
    (Path(first_cfg["apps"][0]["root"]) / "app.py").write_text("VALUE = 'first'\n", encoding="utf-8")
    _finish(monkeypatch, cfg, first_id, "First proposal.")

    second_id, second = _feedback(cfg, "second proposal")
    second_cfg, second_proposal = proposals.prepare_task_config(cfg, "sample", second)

    assert second_proposal["superseded"] == [first_id]
    assert proposals.preview_for_app(cfg, "sample") is None
    first_entry = next(row for row in ledger.load(cfg)["sample"] if row["id"] == first_id)
    assert first_entry["status"] == "rejected"
    rows = proposals.list_proposals(cfg, app="sample")
    assert any(row["feedback_id"] == first_id and row["state"] == "superseded" for row in rows)

    (Path(second_cfg["apps"][0]["root"]) / "app.py").write_text("VALUE = 'second'\n", encoding="utf-8")
    _finish(monkeypatch, cfg, second_id, "Second proposal.")
    assert proposals.preview_for_app(cfg, "sample")["feedback_id"] == second_id


def test_independent_app_proposals_coexist_and_rejection_retires_only_one(tmp_path, monkeypatch):
    cfg, _app_repo = _collection(tmp_path)
    cfg = _add_second_app(cfg, tmp_path)
    sample_id, sample_entry = _feedback(cfg, "sample proposal")
    other_id = ledger.save_entry(cfg, "other", comment="other proposal")
    other_entry = next(row for row in ledger.load(cfg)["other"] if row["id"] == other_id)

    sample_cfg, _ = proposals.prepare_task_config(cfg, "sample", sample_entry)
    (Path(sample_cfg["apps"][0]["root"]) / "app.py").write_text("VALUE = 'sample open'\n", encoding="utf-8")
    _finish(monkeypatch, cfg, sample_id, "Sample proposal.")
    other_cfg, _ = proposals.prepare_task_config(cfg, "other", other_entry)
    other_root = next(item["root"] for item in other_cfg["apps"] if item["name"] == "other")
    (Path(other_root) / "app.py").write_text("VALUE = 'other open'\n", encoding="utf-8")
    monkeypatch.setattr("curiator.workflow_cli._reload_in_shell", lambda *_args: "reloaded")
    _post_reply(cfg, "other", other_id, "Other proposal.", "done")

    assert proposals.preview_for_app(cfg, "sample")["feedback_id"] == sample_id
    assert proposals.preview_for_app(cfg, "other")["feedback_id"] == other_id

    result = proposals.reject(cfg, "sample", sample_id, actor="test admin", reason="choose another variant")

    assert result["action"] == "rejected"
    assert proposals.preview_for_app(cfg, "sample") is None
    assert proposals.preview_for_app(cfg, "other")["feedback_id"] == other_id
    sample = next(row for row in ledger.load(cfg)["sample"] if row["id"] == sample_id)
    assert sample["status"] == "rejected"


def test_conflicting_approval_aborts_without_clobbering_main(tmp_path, monkeypatch):
    cfg, app_repo = _collection(tmp_path)
    feedback_id, entry = _feedback(cfg, "proposal conflict")
    task_cfg, _ = proposals.prepare_task_config(cfg, "sample", entry)
    (Path(task_cfg["apps"][0]["root"]) / "app.py").write_text("VALUE = 'proposal'\n", encoding="utf-8")
    _finish(monkeypatch, cfg, feedback_id)

    (app_repo / "app.py").write_text("VALUE = 'accepted moved'\n", encoding="utf-8")
    _git(app_repo, "add", "app.py")
    _git(app_repo, "commit", "-q", "-m", "move accepted state")

    with pytest.raises(proposals.ProposalError, match="merge aborted"):
        proposals.approve(cfg, "sample", feedback_id, actor="test admin")

    assert _git(app_repo, "branch", "--show-current") == "main"
    assert _git(app_repo, "status", "--porcelain") == ""
    assert (app_repo / "app.py").read_text(encoding="utf-8") == "VALUE = 'accepted moved'\n"
    assert proposals.preview_for_app(cfg, "sample")["feedback_id"] == feedback_id
    original = next(row for row in ledger.load(cfg)["sample"] if row["id"] == feedback_id)
    assert original["status"] == "awaiting_approval"
    assert any(
        row.get("kind") == "system" and "Git aborted without changing accepted state" in row.get("comment", "")
        for row in ledger.load(cfg)["sample"]
    )
    latest_note = [row for row in ledger.load(cfg)["sample"] if row.get("kind") == "system"][-1]
    assert latest_note["actions"] == proposals.action_items(feedback_id)


def test_doctor_rejects_per_run_without_git_commits(tmp_path):
    cfg, _app_repo = _collection(tmp_path)
    cfg["git"]["commit"] = False

    issues = proposals.doctor_issues(cfg)

    assert any(issue["severity"] == "error" and "git.commit" in issue["message"] for issue in issues)

    cfg["git"]["commit"] = True
    cfg["git"]["include_ledger"] = True
    issues = proposals.doctor_issues(cfg)
    assert any(issue["severity"] == "error" and "include_ledger" in issue["message"] for issue in issues)
