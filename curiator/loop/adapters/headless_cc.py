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

import json
import shutil
from pathlib import Path

from .. import runlog

# Enough to edit one app, smoke-test it, run `curiator reply`, and do read-only web research (verify a
# paper/link) — but not the whole toolbox. Headless `claude -p` can't prompt, so a tool the agent uses
# MUST be pre-approved here or it errors mid-run. WebFetch fetches arbitrary URLs: drop it (or add it to
# `agent.disallowed_tools`) for collections that take UNTRUSTED public feedback — see SECURITY.md.
_DEFAULT_TOOLS = ["Read", "Edit", "Write", "Bash", "Glob", "Grep", "WebSearch", "WebFetch"]


def available() -> bool:
    return shutil.which("claude") is not None


def _fmt_tool_use(block: dict) -> str:
    """One line for a tool_use event — enough to see WHAT the agent is doing, not a full dump."""
    name = block.get("name", "tool")
    inp = block.get("input") or {}
    if name == "Bash":
        cmd = " ".join((inp.get("command") or "").split())
        return f"▸ Bash: {cmd[:200]}"
    if name in ("Read", "Edit", "Write", "NotebookEdit"):
        return f"▸ {name}({inp.get('file_path') or inp.get('notebook_path') or ''})"
    if name in ("Glob", "Grep"):
        scope = inp.get("pattern") or inp.get("path") or ""
        return f"▸ {name}({scope})"
    keys = ", ".join(f"{k}={str(v)[:40]}" for k, v in list(inp.items())[:2])
    return f"▸ {name}({keys})"


def _format_stream_event(line: str) -> str | None:
    """Map one `claude -p --output-format stream-json` JSONL event → a readable trace line (or None to
    drop it). Turns silent one-shot runs into live progress: session start, each message/tool use, result."""
    line = line.strip()
    if not line:
        return None
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return line                                   # stray non-JSON output — surface it raw
    kind = ev.get("type")
    if kind == "system" and ev.get("subtype") == "init":
        names = ev.get("tools") or []
        shown = ", ".join(names) if len(names) <= 8 else f"{len(names)} available"
        return f"● session started · model {ev.get('model', '?')} · tools: {shown}"
    if kind == "assistant":
        out = []
        for block in (ev.get("message") or {}).get("content") or []:
            if block.get("type") == "text":
                text = (block.get("text") or "").strip()
                if text:
                    out.append(text)
            elif block.get("type") == "tool_use":
                out.append(_fmt_tool_use(block))
        return "\n".join(out) or None
    if kind == "user":                                # tool results — keep only failures, drop the noise
        for block in (ev.get("message") or {}).get("content") or []:
            if block.get("type") == "tool_result" and block.get("is_error"):
                return "  ✗ tool returned an error"
        return None
    if kind == "result":
        bits = [f"● result: {'error' if ev.get('is_error') else ev.get('subtype', 'done')}"]
        if ev.get("num_turns") is not None:
            bits.append(f"{ev['num_turns']} turns")
        if ev.get("duration_ms") is not None:
            bits.append(f"{ev['duration_ms'] / 1000:.1f}s")
        if ev.get("total_cost_usd") is not None:
            bits.append(f"${ev['total_cost_usd']:.4f}")
        return " · ".join(bits)
    return None


def run(task) -> None:
    if not available():
        raise RuntimeError("`claude` CLI not on PATH — install Claude Code, or set agent.adapter: command")

    # the EFFECTIVE profile for this item (base agent, or `agent.elevated` when the author's group qualifies)
    agent = getattr(task, "agent", None) or task.cfg.get("agent", {}) or {}
    prompt = Path(task.task_file).read_text()        # the bundle: protocol + this feedback + paths
    allowed = agent.get("allowed_tools") or _DEFAULT_TOOLS
    denied = agent.get("disallowed_tools") or []     # the blacklist — never allowed, even when elevated

    cmd = ["claude", "-p", prompt, "--permission-mode", agent.get("permission_mode", "acceptEdits")]
    # Stream the run as JSONL events so the trace shows live progress (session start, each tool use,
    # result) instead of sitting silent until `--output-format text` dumps everything at the end.
    # `stream-json` requires `--verbose` in print mode. Opt out with `agent.stream: false`.
    stream = agent.get("stream", True)
    if stream:
        cmd += ["--verbose", "--output-format", "stream-json"]
    if agent.get("model"):
        cmd += ["--model", str(agent["model"])]
    if denied:                                        # before the variadic --allowedTools
        cmd += ["--disallowedTools", *denied]
    cmd += ["--allowedTools", *allowed]               # variadic — keep LAST (consumes args until the next flag)

    display = ["claude", "-p", "<task bundle>"] + (["--verbose", "--output-format", "stream-json"] if stream else []) + ["..."]
    # A timeout raises runlog.AgentTimeout and a Stop raises runlog.AgentCancelled; the loop handles both.
    proc = runlog.run_streamed(task, cmd, cwd=task.cfg["repo_root"], timeout=int(agent.get("timeout", 900)),
                               label="claude -p", display_cmd=display,
                               line_formatter=_format_stream_event if stream else None)

    if proc.tail.strip():
        print(f"[headless-cc] {task.key}/{task.entry.get('id')}:\n{proc.tail[-2000:]}")
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p exited {proc.returncode}: {proc.tail[-800:]}")
