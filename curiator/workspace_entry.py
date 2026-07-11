"""Prepare narrowly mounted agent credentials, then exec the workspace shell/watcher."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _require_credential(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"workspace credential file is unavailable: {path}")
    path.chmod(0o600)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gallery", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--credentials", choices=["none", "codex", "claude"], default="none")
    parser.add_argument("--agent-adapter", choices=["headless-cc", "codex", "api", "command"])
    parser.add_argument("--agent-model")
    parser.add_argument("--agent-autonomy", choices=["propose-only", "auto-small", "auto"])
    parser.add_argument("--agent-network", choices=["on", "off"], default="on")
    parser.add_argument("--agent-sandbox", choices=["container", "workspace-write"], default="container")
    args = parser.parse_args(argv)
    state = Path(args.state_dir).resolve()
    venv = state / "venv"
    runner_python = Path(sys.executable)
    if (venv / "bin").is_dir():
        os.environ["VIRTUAL_ENV"] = str(venv)
        os.environ["PATH"] = str(venv / "bin") + os.pathsep + os.environ.get("PATH", "")
        candidate = venv / "bin" / "python"
        if candidate.is_file():
            runner_python = candidate
    if args.credentials == "codex":
        codex_home = state / "provider" / "codex"
        _require_credential(codex_home / "auth.json")
        os.environ["CODEX_HOME"] = str(codex_home)
    elif args.credentials == "claude":
        home = state / "provider" / "claude-home"
        _require_credential(home / ".claude" / ".credentials.json")
        os.environ["HOME"] = str(home)
    command = [
        str(runner_python), "-I", "-m", "curiator.cli",
        "--gallery", args.gallery, "--state-dir", str(state),
    ]
    adapter = args.agent_adapter
    if not adapter and args.credentials != "none":
        adapter = "codex" if args.credentials == "codex" else "headless-cc"
    if adapter:
        command += ["--agent-adapter", adapter]
    if args.agent_model:
        command += ["--agent-model", args.agent_model]
    if args.agent_autonomy:
        command += ["--agent-autonomy", args.agent_autonomy]
    if args.credentials != "none":
        command += ["--agent-network", args.agent_network]
        if args.credentials == "codex":
            sandbox = "danger-full-access" if args.agent_sandbox == "container" else "workspace-write"
            command += ["--agent-sandbox", sandbox]
    command += ["--workspace-mode", "serve"]
    os.execvp(command[0], command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
