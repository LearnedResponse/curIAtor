from __future__ import annotations

import textwrap
import sys
from types import SimpleNamespace
from pathlib import Path


def _write_gallery(root: Path, name: str, port: int) -> None:
    (root / "apps").mkdir(parents=True)
    (root / "gallery.yaml").write_text(textwrap.dedent(f"""\
        apps:
          - name: {name}
            title: {name}
            mount: {{ kind: dash-inproc, module: {name} }}
            source: apps/{name}.py
        shell:
          port: {port}
    """))
    (root / "apps" / f"{name}.py").write_text("app = object()\n")


def test_global_gallery_argument_overrides_env(tmp_path, monkeypatch, capsys):
    from curiator import cli

    env_gallery = tmp_path / "env-gallery"
    cli_gallery = tmp_path / "cli-gallery"
    _write_gallery(env_gallery, "env_app", 8101)
    _write_gallery(cli_gallery, "cli_app", 8102)
    monkeypatch.setenv("CURIATOR_GALLERY", str(env_gallery / "gallery.yaml"))

    assert cli.main(["--gallery", str(cli_gallery / "gallery.yaml"), "status", "--app", "cli_app"]) == 0
    out = capsys.readouterr().out

    assert f"gallery: {cli_gallery / 'gallery.yaml'}" in out
    assert "cli_app" in out
    assert "env_app" not in out

    assert cli.main(["status", "--app", "env_app"]) == 0
    out = capsys.readouterr().out

    assert f"gallery: {env_gallery / 'gallery.yaml'}" in out
    assert "env_app" in out
    assert "cli_app" not in out


def test_up_passes_gallery_to_child_as_cli_arg_not_env(tmp_path, monkeypatch):
    from curiator import cli, serve_cli

    env_gallery = tmp_path / "env-gallery"
    cli_gallery = tmp_path / "cli-gallery"
    _write_gallery(env_gallery, "env_app", 8101)
    _write_gallery(cli_gallery, "cli_app", 8102)
    monkeypatch.setenv("CURIATOR_GALLERY", str(env_gallery / "gallery.yaml"))
    monkeypatch.setattr(serve_cli, "_shell_path", lambda _kind=None: tmp_path / "web_shell.py")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(serve_cli.subprocess, "run", fake_run)

    assert cli.main(["--gallery", str(cli_gallery / "gallery.yaml"), "up"]) == 0

    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd == [
        sys.executable,
        str(tmp_path / "web_shell.py"),
        "--gallery",
        str((cli_gallery / "gallery.yaml").resolve()),
    ]
    assert "CURIATOR_GALLERY" not in kwargs["env"]


def test_up_propagates_process_scoped_state_dir_to_child(tmp_path, monkeypatch):
    from curiator import cli, serve_cli

    gallery = tmp_path / "gallery"
    state = tmp_path / "state"
    _write_gallery(gallery, "sample", 8103)
    monkeypatch.setattr(serve_cli, "_shell_path", lambda _kind=None: tmp_path / "web_shell.py")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(serve_cli.subprocess, "run", fake_run)
    assert cli.main([
        "--gallery", str(gallery / "gallery.yaml"),
        "--state-dir", str(state),
        "up",
    ]) == 0
    assert calls[0][0][-4:] == [
        "--gallery", str((gallery / "gallery.yaml").resolve()),
        "--state-dir", str(state.resolve()),
    ]


def test_workspace_watcher_uses_installed_runner_in_isolated_mode(tmp_path):
    from curiator import serve_cli

    cfg = {
        "gallery_path": str(tmp_path / "source" / "gallery.yaml"),
        "state_dir": str(tmp_path / "state"),
    }
    assert serve_cli._watcher_command(cfg) == [
        sys.executable, "-I", "-u", "-m", "curiator.cli",
        "--gallery", str((tmp_path / "source" / "gallery.yaml").resolve()),
        "--state-dir", str((tmp_path / "state").resolve()),
        "watch",
    ]


def test_process_scoped_agent_override_propagates_to_watcher(tmp_path):
    from curiator import serve_cli

    cfg = {
        "gallery_path": str(tmp_path / "gallery.yaml"),
        "agent_adapter_override": "codex",
        "agent_model_override": "gpt-test",
        "agent_autonomy_override": "auto",
        "agent_network_override": "on",
        "agent_sandbox_override": "danger-full-access",
    }
    assert serve_cli._watcher_command(cfg)[-11:] == [
        "--agent-adapter", "codex", "--agent-model", "gpt-test",
        "--agent-autonomy", "auto", "--agent-network", "on",
        "--agent-sandbox", "danger-full-access", "watch",
    ]
