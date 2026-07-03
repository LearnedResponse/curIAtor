"""Provider-neutral agent capability probes and task-bundle contracts."""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import sqlite3
from pathlib import Path


_BROWSER_CANDIDATES = (
    "brave-browser",
    "brave-browser-stable",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)


def _which_any(names: tuple[str, ...]) -> tuple[str | None, str | None]:
    for name in names:
        path = shutil.which(name)
        if path:
            return name, path
    return None, None


def _tool(name: str, *, names: tuple[str, ...] | None = None) -> dict:
    label, path = _which_any(names or (name,))
    return {
        "available": bool(path),
        "command": label or name,
        "path": path,
    }


def _browser_tool() -> dict:
    env_browser = os.environ.get("CURIATOR_BROWSER")
    if env_browser:
        p = Path(env_browser)
        exists = p.exists() if p.is_absolute() or any(sep in env_browser for sep in ("/", "\\")) else bool(shutil.which(env_browser))
        return {
            "available": exists,
            "command": "CURIATOR_BROWSER",
            "path": env_browser,
            "source": "CURIATOR_BROWSER",
        }
    tool = _tool("browser", names=_BROWSER_CANDIDATES)
    tool["source"] = "PATH"
    return tool


def _playwright_tool() -> dict:
    package = importlib.util.find_spec("playwright") is not None
    cli = shutil.which("playwright")
    return {
        "available": bool(package or cli),
        "package": package,
        "path": cli,
    }


def agent_report(cfg: dict | None = None) -> dict:
    """Return machine-readable local agent tooling availability.

    Missing optional tools are not doctor errors. This report gates which capability instructions
    appear in task bundles, so agents don't get commands for tools that are not present.
    """
    browser = _browser_tool()
    docker = _tool("docker")
    git = _tool("git")
    gh = _tool("gh")
    sqlite_cli = _tool("sqlite3")
    sqlite_python = bool(sqlite3.sqlite_version)
    browser_available = bool(browser.get("available"))
    docker_available = bool(docker.get("available"))
    return {
        "tools": {
            "browser": browser,
            "playwright": _playwright_tool(),
            "docker": docker,
            "git": git,
            "gh": gh,
            "sqlite": {
                "available": bool(sqlite_cli.get("available") or sqlite_python),
                "path": sqlite_cli.get("path"),
                "python_module": sqlite_python,
            },
        },
        "capabilities": {
            "browser_smoke": {
                "available": browser_available,
                "reason": "Brave/Chromium available" if browser_available
                else "Brave/Chromium not found; set CURIATOR_BROWSER or install a supported browser",
                "command": "curiator smoke --browser",
            },
            "docker_packaging": {
                "available": docker_available,
                "reason": "Docker CLI available" if docker_available else "Docker CLI not found",
                "command": "docker",
            },
        },
    }


def browser_smoke_available(cfg: dict | None = None) -> bool:
    return bool(agent_report(cfg)["capabilities"]["browser_smoke"]["available"])


def safe_artifact_label(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "app")).strip("_")
    return text or "app"


def browser_smoke_artifacts(cfg: dict, feedback_id: str, app: str) -> dict:
    feedback_dir = str((cfg.get("feedback") or {}).get("dir") or "feedback").strip("/") or "feedback"
    base = Path(feedback_dir) / "replies" / f"{feedback_id}-browser-smoke"
    label = safe_artifact_label(app)
    return {
        "dir": base.as_posix(),
        "result": (base / "result.json").as_posix(),
        "screenshot": (base / f"{label}.png").as_posix(),
        "console": (base / f"{label}.console.json").as_posix(),
    }


def browser_smoke_contract(cfg: dict, app: str, feedback_id: str) -> str:
    if not browser_smoke_available(cfg):
        return ""
    artifacts = browser_smoke_artifacts(cfg, feedback_id, app)
    command = (
        f"curiator smoke --app {app} --browser --artifact-dir {artifacts['dir']} "
        f"--output {artifacts['result']} --json"
    )
    return "\n".join([
        "## Browser-smoke capability",
        "Doctor found a local Brave/Chromium-compatible browser. For UI-affecting work, return a rendered-app artifact.",
        "",
        "Run after the edit:",
        f"- browser smoke + artifacts: `{command}`",
        "",
        "Expected artifacts:",
        f"- result JSON: `{artifacts['result']}`",
        f"- screenshot: `{artifacts['screenshot']}`",
        f"- console log: `{artifacts['console']}`",
        "",
        "Before replying `--status done`, confirm: server reachable; page non-blank; no obvious console errors; "
        "screenshot captured; and what was not verified.",
    ])
