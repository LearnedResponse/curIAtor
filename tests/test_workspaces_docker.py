"""Opt-in real-Docker acceptance test for disposable fork workspaces."""
from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from curiator.config import load_config_at
from curiator.workspaces import DEFAULT_IMAGE, WorkspaceManager


pytestmark = pytest.mark.skipif(
    os.environ.get("CURIATOR_DOCKER_INTEGRATION") != "1",
    reason="set CURIATOR_DOCKER_INTEGRATION=1 to run the real-Docker workspace test",
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_real_docker_workspace_overlay_smoke_restart_and_delete(tmp_path: Path):
    (tmp_path / "apps").mkdir()
    (tmp_path / "apps" / "sample.py").write_text(textwrap.dedent("""\
        import dash
        from dash import html

        def build_app():
            app = dash.Dash(__name__)
            app.layout = html.Main([html.H1("Docker workspace proof"), html.P("ready")])
            return app
    """))
    (tmp_path / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            source: apps/sample.py
            mount: {kind: dash-inproc, module: sample}
        feedback: {dir: feedback}
        shell: {port: 8399}
        git: {commit: false, include_ledger: false}
    """))
    (tmp_path / ".gitignore").write_text("__pycache__/\n*.py[cod]\nfeedback/\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Workspace Test")
    _git(tmp_path, "config", "user.email", "workspace@test.local")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "fixture")

    manager = WorkspaceManager(load_config_at(tmp_path / "gallery.yaml"))
    assert manager.doctor()["image_available"] is True, f"build {DEFAULT_IMAGE} before this test"
    row = manager.create("sample", name="docker-integration", build_if_missing=False)
    try:
        assert row["status"] == "running"
        assert manager.smoke(row["id"], app="sample", browser=True)["ok"] is True
        assert manager.stop(row["id"])["status"] == "stopped"
        restarted = manager.start(row["id"])
        assert restarted["status"] == "running"
        assert restarted["host_port"] == row["host_port"]
        assert manager.diff(row["id"])["dirty"] is False
        workspace_repo = manager._workspace_repo(row)
        manager._volume_exec(
            row, "python", "-c",
            "from pathlib import Path; p=Path('/workspace/source/apps/sample.py'); "
            "p.write_text(p.read_text() + '\\n# accepted from workspace\\n')",
        )
        manager._volume_exec(row, "git", "-C", workspace_repo, "add", "apps/sample.py")
        manager._volume_exec(
            row, "git", "-C", workspace_repo, "commit", "-q", "-m", "workspace acceptance proof",
        )
        assert manager.diff(row["id"])["commits"]
        kept = manager.keep(row["id"])
        assert kept["preserved_ref"] == row["branch"]
        applied = manager.apply(row["id"])
        assert applied["status"] == "applied"
        assert "accepted from workspace" in (tmp_path / "apps" / "sample.py").read_text()
    finally:
        deleted = manager.delete(row["id"], force=True)
    assert deleted["status"] == "deleted"
    assert manager.docker.inspect("container", row["container_name"]) is None
    assert manager.docker.inspect("volume", row["source_volume"]) is None
    assert manager.docker.inspect("volume", row["state_volume"]) is None
