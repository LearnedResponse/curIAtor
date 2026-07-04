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
