"""Workspace entry runs the control plane in the bootstrapped app environment."""
import os
import sys
from pathlib import Path

from curiator import workspace_entry


def test_entry_uses_app_venv_python_when_available(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    (state / "venv" / "bin").mkdir(parents=True)
    venv_python = state / "venv" / "bin" / "python"
    venv_python.write_text("")
    seen = {}

    def fake_exec(executable, command):
        seen["executable"] = executable
        seen["command"] = command
        raise RuntimeError("exec captured")

    monkeypatch.setattr(os, "execvp", fake_exec)
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    monkeypatch.setenv("VIRTUAL_ENV", "")
    try:
        workspace_entry.main([
            "--gallery", "/workspace/source/gallery.yaml",
            "--state-dir", str(state),
        ])
    except RuntimeError as exc:
        assert str(exc) == "exec captured"
    else:
        raise AssertionError("workspace entry did not exec the runner")

    assert seen["executable"] == str(venv_python)
    assert seen["command"][:4] == [str(venv_python), "-I", "-m", "curiator.cli"]
    assert os.environ["PATH"].split(os.pathsep)[0] == str(state / "venv" / "bin")


def test_entry_falls_back_to_image_python_without_venv(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    seen = {}

    def fake_exec(executable, command):
        seen["executable"] = executable
        seen["command"] = command
        raise RuntimeError("exec captured")

    monkeypatch.setattr(os, "execvp", fake_exec)
    try:
        workspace_entry.main([
            "--gallery", "/workspace/source/gallery.yaml",
            "--state-dir", str(state),
        ])
    except RuntimeError:
        pass

    assert seen["executable"] == sys.executable
    assert seen["command"][:4] == [sys.executable, "-I", "-m", "curiator.cli"]


def test_selected_credentials_choose_workspace_agent_adapter(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    auth = state / "provider" / "codex" / "auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text("secret")
    seen = {}

    def fake_exec(executable, command):
        seen["command"] = command
        raise RuntimeError("exec captured")

    monkeypatch.setattr(os, "execvp", fake_exec)
    monkeypatch.setenv("CODEX_HOME", "")
    try:
        workspace_entry.main([
            "--gallery", "/workspace/source/gallery.yaml",
            "--state-dir", str(state),
            "--credentials", "codex",
        ])
    except RuntimeError:
        pass

    assert seen["command"][-8:] == [
        "--agent-adapter", "codex", "--agent-network", "on",
        "--agent-sandbox", "danger-full-access", "--workspace-mode", "serve",
    ]


def test_replay_profile_overrides_reach_workspace_runner(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    seen = {}

    def fake_exec(_executable, command):
        seen["command"] = command
        raise RuntimeError("exec captured")

    monkeypatch.setattr(os, "execvp", fake_exec)
    try:
        workspace_entry.main([
            "--gallery", "/workspace/source/gallery.yaml",
            "--state-dir", str(state),
            "--agent-adapter", "codex",
            "--agent-model", "gpt-test",
            "--agent-autonomy", "auto",
        ])
    except RuntimeError:
        pass

    assert seen["command"][-8:] == [
        "--agent-adapter", "codex", "--agent-model", "gpt-test",
        "--agent-autonomy", "auto", "--workspace-mode", "serve",
    ]
