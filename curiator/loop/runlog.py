"""runlog — per-feedback task/reply artifacts and live agent output capture."""
from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def feedback_dir(cfg: dict) -> Path:
    return Path(cfg.get("repo_root", ".")) / (cfg.get("feedback", {}).get("dir", "feedback"))


def tasks_dir(cfg: dict) -> Path:
    return feedback_dir(cfg) / "tasks"


def replies_dir(cfg: dict) -> Path:
    return feedback_dir(cfg) / "replies"


def task_path(cfg: dict, feedback_id: str) -> Path:
    return tasks_dir(cfg) / f"{feedback_id}.md"


def reply_path(cfg: dict, feedback_id: str) -> Path:
    return replies_dir(cfg) / f"{feedback_id}.md"


def append(path: str | Path, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def init_trace(task, adapter_name: str) -> None:
    eid = task.entry.get("id")
    p = Path(task.reply_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "\n".join([
            "# curIAtor Agent Trace",
            "",
            f"- feedback id: `{eid}`",
            f"- app: `{task.key}`",
            f"- adapter: `{adapter_name}`",
            f"- source: `{task.source or ''}`",
            f"- task: `{task.task_file}`",
            f"- started: `{_now()}`",
            "",
            "## Output",
            "",
        ]),
        encoding="utf-8",
    )


def note(task, text: str) -> None:
    append(task.reply_file, f"\n[{_now()}] {text}\n")


@dataclass
class RunResult:
    returncode: int
    tail: str


class AgentInterrupted(BaseException):
    """Raised when the watcher is shutting down while an agent subprocess is running."""


def _tail_push(parts: list[str], chunk: str, limit: int = 8000) -> None:
    parts.append(chunk)
    total = sum(len(p) for p in parts)
    while parts and total > limit:
        total -= len(parts.pop(0))


def _terminate_process_group(proc: subprocess.Popen, sig: int = signal.SIGTERM) -> None:
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        return
    except OSError:
        try:
            proc.terminate() if sig == signal.SIGTERM else proc.kill()
        except OSError:
            return


def run_streamed(
    task,
    cmd: list[str],
    *,
    cwd: str | Path,
    timeout: int,
    label: str,
    display_cmd: list[str] | None = None,
    stdin=None,
) -> RunResult:
    """Run a command while streaming stdout/stderr into the task's markdown trace."""
    shown = display_cmd or cmd
    note(task, f"running `{label}`")
    append(task.reply_file, "```text\n$ " + " ".join(shown) + "\n")
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=stdin,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    previous_handlers = {
        sig: signal.getsignal(sig)
        for sig in (signal.SIGINT, signal.SIGTERM)
    }

    def _handle_shutdown(signum, _frame):
        append(task.reply_file, f"\n[interrupted by signal {signum}; terminating agent subprocess]\n")
        _terminate_process_group(proc, signal.SIGTERM)
        raise AgentInterrupted(f"agent interrupted by signal {signum}")

    for sig in previous_handlers:
        signal.signal(sig, _handle_shutdown)
    deadline = time.monotonic() + timeout if timeout else None
    tail: list[str] = []
    sel = selectors.DefaultSelector()
    if proc.stdout is not None:
        sel.register(proc.stdout, selectors.EVENT_READ)
    timed_out = False
    try:
        while True:
            if deadline is not None and time.monotonic() > deadline:
                timed_out = True
                _terminate_process_group(proc, signal.SIGKILL)
                break
            events = sel.select(timeout=0.2)
            for key, _ in events:
                line = key.fileobj.readline()
                if line:
                    append(task.reply_file, line)
                    _tail_push(tail, line)
            if proc.poll() is not None:
                break
        if proc.stdout is not None:
            rest = proc.stdout.read()
            if rest:
                append(task.reply_file, rest)
                _tail_push(tail, rest)
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        sel.close()
    rc = proc.wait()
    if timed_out:
        append(task.reply_file, f"\n[timeout after {timeout}s]\n")
        append(task.reply_file, "```\n")
        note(task, "timed out")
        raise subprocess.TimeoutExpired(cmd, timeout, output="".join(tail))
    append(task.reply_file, f"\n[exit {rc}]\n```\n")
    note(task, f"finished `{label}` with exit {rc}")
    return RunResult(returncode=rc, tail="".join(tail))
