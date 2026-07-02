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
