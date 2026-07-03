"""Smoke-test the built curIAtor wheel in a temporary installed environment."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _latest_wheel(dist: Path) -> Path:
    wheels = sorted(dist.glob("curiator-*.whl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not wheels:
        raise SystemExit("curiator: no built wheel found in dist/; run make release-check first")
    return wheels[0]


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _venv_curiator(venv: Path) -> Path:
    return venv / ("Scripts/curiator.exe" if os.name == "nt" else "bin/curiator")


def _run(cmd: list[str | Path], *, cwd: Path | None = None) -> dict:
    proc = subprocess.run(
        [str(part) for part in cmd],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    result = {
        "cmd": [str(part) for part in cmd],
        "cwd": str(cwd) if cwd else None,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }
    if proc.returncode:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise RuntimeError(f"{' '.join(result['cmd'])} failed: {detail}")
    return result


def _assert_venv_import(python: Path, *, cwd: Path) -> dict:
    code = (
        "from pathlib import Path\n"
        "import json, sysconfig\n"
        "import curiator\n"
        "purelib = Path(sysconfig.get_paths()['purelib']).resolve()\n"
        "module = Path(curiator.__file__).resolve()\n"
        "ok = purelib == module.parent or purelib in module.parents\n"
        "print(json.dumps({'version': curiator.__version__, 'module': str(module), "
        "'purelib': str(purelib), 'ok': ok}))\n"
        "raise SystemExit(0 if ok else 1)\n"
    )
    result = _run([python, "-c", code], cwd=cwd)
    return json.loads(result["stdout"])


def _write_phase0_playground_config(collection: Path) -> None:
    collection.mkdir(parents=True, exist_ok=True)
    (collection / "apps").mkdir(exist_ok=True)
    (collection / "feedback").mkdir(exist_ok=True)
    (collection / "apps" / "sample.py").write_text(
        "from dash import Dash, html\n\n"
        "app = Dash(__name__)\n"
        "app.layout = html.Div('sample')\n",
        encoding="utf-8",
    )
    (collection / "gallery.yaml").write_text(
        "\n".join([
            "apps:",
            "  - name: sample",
            "    title: Sample",
            "    mount: { kind: dash-inproc, module: sample }",
            "    source: apps/sample.py",
            "runner:",
            "  mode: pinned",
            "git:",
            "  commit: true",
            "auth:",
            "  mode: local",
            "  users_file: .curiator-users.json",
            "  admin_groups: [admin]",
            "agent:",
            "  autonomy: propose-only",
            "  dispatch:",
            "    trusted_groups: [trusted]",
            "  quotas:",
            "    per_user_daily: 3",
            "    global_daily: 25",
            "",
        ]),
        encoding="utf-8",
    )
    gitignore = collection / ".gitignore"
    current_ignore = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if ".curiator-users.json" not in current_ignore.splitlines():
        gitignore.write_text(
            current_ignore + ("\n" if current_ignore and not current_ignore.endswith("\n") else "")
            + ".curiator-users.json\n",
            encoding="utf-8",
        )
    users_file = collection / ".curiator-users.json"
    users_file.write_text(
        json.dumps({
            "admin@example.com": {
                "name": "Admin",
                "groups": ["admin"],
                "password_hash": "package-smoke-test-hash",
            }
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    users_file.chmod(0o600)


def smoke_release_package(wheel: Path) -> dict:
    wheel = wheel.resolve()
    if not wheel.exists():
        raise SystemExit(f"curiator: wheel not found: {wheel}")
    with tempfile.TemporaryDirectory(prefix="curiator-package-smoke-") as tmpdir:
        tmp = Path(tmpdir)
        venv = tmp / "venv"
        collection = tmp / "collection"
        _run([sys.executable, "-m", "venv", "--system-site-packages", venv])
        python = _venv_python(venv)
        curiator = _venv_curiator(venv)
        steps = [
            _run([python, "-m", "pip", "install", "--no-deps", "--force-reinstall", wheel]),
        ]
        installed = _assert_venv_import(python, cwd=tmp)
        steps.extend([
            _run([curiator, "--help"], cwd=tmp),
            _run([curiator, "init", collection, "--git"], cwd=tmp),
            _run([curiator, "app", "templates"], cwd=collection),
            _run([curiator, "smoke", "--json"], cwd=collection),
        ])
        _write_phase0_playground_config(collection)
        steps.append(_run([curiator, "playground-backup-smoke", "--no-smoke", "--json"], cwd=collection))
        return {
            "ok": True,
            "wheel": str(wheel),
            "installed": installed,
            "collection": str(collection),
            "steps": steps,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, default=None, help="wheel to install; defaults to newest dist/curiator-*.whl")
    parser.add_argument("--output", type=Path, default=None, help="write JSON evidence to this path")
    args = parser.parse_args(argv)

    wheel = args.wheel or _latest_wheel(ROOT / "dist")
    try:
        payload = smoke_release_package(wheel)
    except Exception as exc:  # noqa: BLE001
        payload = {"ok": False, "wheel": str(wheel), "error": str(exc)}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"curiator: release package smoke FAILED: {exc}", file=sys.stderr)
        return 1

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"curiator: release package smoke OK ({Path(payload['wheel']).name})")
    print(f"  installed: curIAtor {payload['installed']['version']} from {payload['installed']['module']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
