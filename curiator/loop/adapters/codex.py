"""codex — OpenAI Codex CLI adapter: a one-shot `codex exec` invocation.

Use your Codex subscription (`codex login`) instead of (or alongside) Claude — set `agent.adapter: codex`
in gallery.yaml. Same one-shot model as headless-cc: the task bundle IS the prompt; the agent edits the
source, smoke-tests, and replies via `curiator reply` (which posts the ⚙ note + commits the run).

The SAME unified `agent:` block maps onto Codex flags, so switching providers needs no rewrite:
    model            → codex -m            (null = your Codex default)
    sandbox          → codex -s            read-only | workspace-write (default) | danger-full-access
    permission_mode  → bypassPermissions ⇒ --dangerously-bypass-approvals-and-sandbox (full trust — no
                       sandbox, no approvals; what the `elevated` profile uses so an admin run can
                       pip-install). acceptEdits / unset ⇒ -s workspace-write (edit + run inside the
                       workspace, no network).

Caveat vs headless-cc: Codex has no per-tool `--disallowedTools`, so the elevated `disallowed_tools`
deny-list is NOT enforced here — an elevated Codex run is full-trust. Keep it to sandboxed collections,
or use Codex execpolicy `.rules` for denies.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .. import runlog

_SANDBOXES = ("read-only", "workspace-write", "danger-full-access")


def available() -> bool:
    return shutil.which("codex") is not None


def _full_access(agent: dict) -> bool:
    """Elevated / full trust → skip the sandbox + approvals (what an admin pip-install needs). Intended
    only inside our per-collection container (the blast-radius boundary)."""
    return (agent.get("permission_mode") == "bypassPermissions"
            or agent.get("sandbox") == "danger-full-access")


def _sandbox(agent: dict) -> str:
    s = agent.get("sandbox")
    return s if s in _SANDBOXES else "workspace-write"


def run(task) -> None:
    if not available():
        raise RuntimeError("`codex` CLI not on PATH — install OpenAI Codex (and run `codex login`), "
                           "or set agent.adapter: headless-cc / command")

    # the EFFECTIVE profile for this item (base agent, or `agent.elevated` when the author qualifies)
    agent = getattr(task, "agent", None) or task.cfg.get("agent", {}) or {}
    prompt = Path(task.task_file).read_text()          # the bundle: protocol + this feedback + paths
    repo_root = str(task.cfg["repo_root"])

    cmd = ["codex", "exec", "-C", repo_root, "--skip-git-repo-check"]
    if agent.get("model"):
        cmd += ["-m", str(agent["model"])]
    if _full_access(agent):
        cmd += ["--dangerously-bypass-approvals-and-sandbox"]   # no sandbox/approvals (elevated)
    else:
        sandbox = _sandbox(agent)
        cmd += ["-s", sandbox]
        state_dir = task.cfg.get("state_dir")
        if sandbox == "workspace-write" and state_dir:
            cmd += ["--add-dir", str(Path(state_dir).resolve())]
            if agent.get("network_access") is True:
                cmd += ["-c", "sandbox_workspace_write.network_access=true"]
    cmd += ["--", prompt]                              # terminate options so the bundle is the PROMPT

    # stdin=DEVNULL: codex exec reads stdin even with a positional prompt ("Reading additional input
    # from stdin…") — give it immediate EOF so it can't block the loop waiting on a non-existent TTY.
    # A timeout raises runlog.AgentTimeout (handled by the loop); no local catch needed.
    proc = runlog.run_streamed(task, cmd, cwd=repo_root, timeout=int(agent.get("timeout", 900)),
                               label="codex exec", display_cmd=["codex", "exec", "<task bundle>", "..."],
                               stdin=subprocess.DEVNULL)

    if proc.tail.strip():
        print(f"[codex] {task.key}/{task.entry.get('id')}:\n{proc.tail[-2000:]}")
    if proc.returncode != 0:
        raise RuntimeError(f"codex exec exited {proc.returncode}: {proc.tail[-800:]}")
