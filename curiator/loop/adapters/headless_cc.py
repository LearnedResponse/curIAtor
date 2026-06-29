"""headless_cc — the DEFAULT adapter: a one-shot `claude -p` invocation.

Subscription billing (your Claude Max/Pro login) + full project context (it runs in the repo,
so it loads CLAUDE.md, memories, skills) + robust (a one-shot, no live session to die).

NOTE (M2 wiring): the exact `claude -p` flags + the reply path (how the agent posts ⚙ notes back
to the ledger) are the first thing to finish. Options for the reply path:
  (a) the task file tells the agent to call `curiator reply <app> <id> <text> --status done`
      (a tiny CLI subcommand — recommended, language-agnostic), or
  (b) the agent imports curiator.ledger directly.
Until that's wired, this runs claude headless and leaves the human/agent to update status.
"""
from __future__ import annotations

import shutil
import subprocess


def available() -> bool:
    return shutil.which("claude") is not None


def run(task) -> None:
    if not available():
        raise RuntimeError("`claude` CLI not on PATH — install Claude Code, or set agent.adapter: command")
    # M2: finalize flags (model, --allowedTools for edit+bash, permission mode, output capture).
    cmd = ["claude", "-p", f"@{task.task_file}"]
    subprocess.run(cmd, cwd=task.cfg["repo_root"], check=False)
