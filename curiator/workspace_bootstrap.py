"""Install app dependencies into persistent workspace source/state volumes."""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from .config import app_specs, load_config, set_gallery_override, set_state_dir_override


def _run(command: list[str], *, cwd: Path, log) -> None:
    log.write(f"\n$ {' '.join(command)}  # cwd={cwd}\n")
    log.flush()
    result = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, text=True)
    if result.returncode:
        raise SystemExit(f"workspace bootstrap failed ({result.returncode}): {' '.join(command)}")


def _npm_env(state: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["npm_config_cache"] = str(state / "cache" / "npm")
    env["GIT_TERMINAL_PROMPT"] = "0"
    rewrites = (
        ("url.https://github.com/.insteadOf", "ssh://git@github.com/"),
        ("url.https://github.com/.insteadOf", "git+ssh://git@github.com/"),
        ("url.https://github.com/.insteadOf", "git@github.com:"),
        ("url.https://github.com/.insteadOf", "git://github.com/"),
    )
    env["GIT_CONFIG_COUNT"] = str(len(rewrites))
    for index, (key, value) in enumerate(rewrites):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env


def _requirement_files(cfg: dict, roots: list[Path]) -> list[Path]:
    """Return collection- and app-local Python requirements once each."""
    candidates = [Path(cfg["repo_root"]).resolve(), *roots]
    requirements: list[Path] = []
    seen: set[Path] = set()
    for root in candidates:
        requirement = root / "requirements.txt"
        if requirement.is_file() and requirement not in seen:
            requirements.append(requirement)
            seen.add(requirement)
    return requirements


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gallery", required=True)
    parser.add_argument("--state-dir", required=True)
    args = parser.parse_args(argv)
    set_gallery_override(args.gallery)
    set_state_dir_override(args.state_dir)
    try:
        cfg = load_config()
        state = Path(args.state_dir).resolve()
        state.mkdir(parents=True, exist_ok=True)
        env_path = state / "venv"
        roots = sorted({Path(spec["root"]).resolve() for spec in app_specs(cfg)})
        log_path = state / "workspace-bootstrap.log"
        with log_path.open("a", encoding="utf-8") as log:
            requirements = _requirement_files(cfg, roots)
            if requirements:
                if not (env_path / "bin" / "python").exists():
                    # The workspace image already carries the exact curIAtor control-plane package.
                    # Let app environments see it so collection requirements such as
                    # ``curiator>=0.1`` are satisfied without reaching a package index.
                    _run(
                        ["python", "-m", "venv", "--system-site-packages", str(env_path)],
                        cwd=Path(cfg["repo_root"]),
                        log=log,
                    )
                    log.write("workspace venv inherits image packages; curIAtor self-requirements stay offline\n")
                    log.flush()
                for requirement in requirements:
                    _run([
                        str(env_path / "bin" / "python"), "-m", "pip", "install", "-r", str(requirement),
                    ], cwd=requirement.parent, log=log)
            for root in roots:
                package = root / "package.json"
                if package.is_file() and not (root / "node_modules").exists():
                    command = ["npm", "ci"] if (root / "package-lock.json").is_file() else ["npm", "install"]
                    env = _npm_env(state)
                    log.write(f"\n$ {' '.join(command)}  # cwd={root}\n")
                    log.flush()
                    result = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
                    if result.returncode:
                        raise SystemExit(f"workspace bootstrap failed ({result.returncode}): {' '.join(command)}")
                if (root / "Cargo.toml").is_file():
                    env = dict(os.environ)
                    env["CARGO_HOME"] = str(state / "cache" / "cargo")
                    log.write(f"\n$ cargo fetch  # cwd={root}\n")
                    log.flush()
                    result = subprocess.run(
                        ["cargo", "fetch"], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, text=True
                    )
                    if result.returncode:
                        raise SystemExit("workspace bootstrap failed: cargo fetch")
    finally:
        set_gallery_override(None)
        set_state_dir_override(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
