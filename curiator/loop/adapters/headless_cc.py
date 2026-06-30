"""headless_cc — the DEFAULT adapter: a one-shot `claude -p` invocation.

Subscription billing (your Claude Max/Pro login) + full project context (it runs in the repo,
so it loads CLAUDE.md, memories, skills) + robust (a one-shot, no live session to die).

Reply path (M2): the task bundle tells the agent to call
    curiator reply <app> <id> "<what changed>" --status done
after it edits + smoke-tests. That CLI posts the ⚙ note, sets status, and reloads the app in the
shell so the fix goes live (see curiator/cli.py + the shell's /reload route). The agent reads the
feedback screenshot (its path is in the bundle) with its own Read tool.

Flags are read from gallery.yaml `agent:` (all optional, with working defaults):
    model            → claude --model (null = your CLI default, e.g. sonnet / opus)
    permission_mode  → acceptEdits (auto-apply edits; default) | bypassPermissions | default
    allowed_tools    → tools pre-approved without a prompt (must cover Bash for the smoke-test + reply)
    timeout          → seconds before the one-shot is killed (default 900)
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# Enough to edit one app, smoke-test it, and run `curiator reply` — but not the whole toolbox.
_DEFAULT_TOOLS = ["Read", "Edit", "Write", "Bash", "Glob", "Grep"]


def available() -> bool:
    return shutil.which("claude") is not None


def run(task) -> None:
    if not available():
        raise RuntimeError("`claude` CLI not on PATH — install Claude Code, or set agent.adapter: command")

    # the EFFECTIVE profile for this item (base agent, or `agent.elevated` when the author's group qualifies)
    agent = getattr(task, "agent", None) or task.cfg.get("agent", {}) or {}
    prompt = Path(task.task_file).read_text()        # the bundle: protocol + this feedback + paths
    allowed = agent.get("allowed_tools") or _DEFAULT_TOOLS
    denied = agent.get("disallowed_tools") or []     # the blacklist — never allowed, even when elevated

    cmd = ["claude", "-p", prompt, "--permission-mode", agent.get("permission_mode", "acceptEdits")]
    if agent.get("model"):
        cmd += ["--model", str(agent["model"])]
    if denied:                                        # before the variadic --allowedTools
        cmd += ["--disallowedTools", *denied]
    cmd += ["--allowedTools", *allowed]               # variadic — keep LAST (consumes args until the next flag)

    try:
        proc = subprocess.run(cmd, cwd=task.cfg["repo_root"], capture_output=True, text=True,
                              timeout=int(agent.get("timeout", 900)))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"claude -p timed out after {agent.get('timeout', 900)}s") from exc

    out, err = (proc.stdout or "").strip(), (proc.stderr or "").strip()
    if out:
        print(f"[headless-cc] {task.key}/{task.entry.get('id')}:\n{out[-2000:]}")
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p exited {proc.returncode}: {(err or out)[-800:]}")
