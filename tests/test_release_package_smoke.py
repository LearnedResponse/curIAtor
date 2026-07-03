"""Installed-wheel release smoke helper."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "smoke_release_package.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("smoke_release_package", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_latest_wheel_prefers_newest(tmp_path):
    module = _load_script()
    old = tmp_path / "curiator-0.1.0-py3-none-any.whl"
    new = tmp_path / "curiator-0.2.0-py3-none-any.whl"
    old.write_text("old")
    new.write_text("new")
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))

    assert module._latest_wheel(tmp_path) == new


def test_release_package_smoke_runs_installed_quickstart(monkeypatch, tmp_path):
    module = _load_script()
    wheel = tmp_path / "curiator-0.2.0-py3-none-any.whl"
    wheel.write_text("wheel")
    calls = []

    def fake_run(cmd, *, cwd=None):
        call = {"cmd": [str(part) for part in cmd], "cwd": str(cwd) if cwd else None,
                "returncode": 0, "stdout": "", "stderr": ""}
        calls.append(call)
        return call

    def fake_import(python, *, cwd):
        calls.append({"cmd": [str(python), "import-check"], "cwd": str(cwd)})
        return {"version": "0.2.0", "module": str(python), "purelib": str(cwd), "ok": True}

    monkeypatch.setattr(module, "_run", fake_run)
    monkeypatch.setattr(module, "_assert_venv_import", fake_import)

    payload = module.smoke_release_package(wheel)

    assert payload["ok"] is True
    commands = [" ".join(call["cmd"]) for call in calls]
    assert commands[0].startswith(f"{sys.executable} -m venv --system-site-packages ")
    assert " -m pip install --no-deps --force-reinstall " in commands[1]
    assert commands[2].endswith(" import-check")
    assert commands[3].endswith("curiator --help")
    assert "curiator init" in commands[4] and commands[4].endswith(" --git")
    assert commands[5].endswith("curiator app templates")
    assert commands[6].endswith("curiator smoke --json")
    assert commands[7].endswith("curiator playground-backup-smoke --no-smoke --json")
