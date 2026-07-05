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


def cancel_path(cfg: dict, feedback_id: str) -> Path:
    """A cancel marker the shell drops to ask the watcher to stop an in-flight agent run (the Stop
    button). The watcher's run loop polls for it; sits next to the trace so both processes agree."""
    return replies_dir(cfg) / f"{feedback_id}.cancel"


def request_cancel(cfg: dict, feedback_id: str) -> Path:
    p = cancel_path(cfg, feedback_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_now(), encoding="utf-8")
    return p


def clear_cancel(cfg: dict, feedback_id: str) -> None:
    try:
        cancel_path(cfg, feedback_id).unlink()
    except OSError:
        pass


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


class AgentCancelled(Exception):
    """Raised when a user asked to stop this run (the trace-view Stop button dropped a cancel marker)."""


class AgentTimeout(Exception):
    """Raised when an agent run exceeded its time limit and was stopped."""

    def __init__(self, timeout: int, tail: str = "") -> None:
        super().__init__(f"stopped at the {timeout}s time limit")
        self.timeout = timeout
        self.tail = tail


# Emit a "still working" heartbeat into the trace after this many seconds with no agent output, so a
# long-but-healthy run visibly says "taking a while" instead of looking frozen.
HEARTBEAT_SECONDS = 45


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


def _elapsed_str(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


def run_streamed(
    task,
    cmd: list[str],
    *,
    cwd: str | Path,
    timeout: int,
    label: str,
    display_cmd: list[str] | None = None,
    stdin=None,
    line_formatter=None,
    heartbeat: float = HEARTBEAT_SECONDS,
) -> RunResult:
    """Run a command while streaming stdout/stderr into the task's markdown trace.

    `line_formatter`, if given, maps each raw output line to a human-readable trace line (return None
    to drop a line). Used to turn `claude -p --output-format stream-json` JSONL events into readable
    progress instead of dumping raw JSON — or nothing, as plain `--output-format text` does until it
    finishes. Without it, raw output is streamed verbatim (the default; codex/command adapters).

    After `heartbeat` seconds with no output a "still working" line is emitted so a slow-but-healthy run
    reads as "taking a while", not frozen. A cancel marker (the Stop button — see `cancel_path`) stops
    the run with `AgentCancelled`; exceeding `timeout` stops it with `AgentTimeout`."""
    shown = display_cmd or cmd
    note(task, f"running `{label}`")
    append(task.reply_file, "```text\n$ " + " ".join(shown) + "\n")

    def _emit(raw: str) -> None:
        if line_formatter is None:
            append(task.reply_file, raw)
            _tail_push(tail, raw)
            return
        for chunk in raw.splitlines():
            shown_line = line_formatter(chunk)
            if shown_line is None:
                continue
            text = shown_line if shown_line.endswith("\n") else shown_line + "\n"
            append(task.reply_file, text)
            _tail_push(tail, text)
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
    start = time.monotonic()
    deadline = start + timeout if timeout else None
    cancel_marker = Path(task.reply_file).with_suffix(".cancel")
    tail: list[str] = []
    sel = selectors.DefaultSelector()
    if proc.stdout is not None:
        sel.register(proc.stdout, selectors.EVENT_READ)
    timed_out = False
    cancelled = False
    last_activity = start
    try:
        while True:
            now = time.monotonic()
            if deadline is not None and now > deadline:
                timed_out = True
                _terminate_process_group(proc, signal.SIGKILL)
                break
            if cancel_marker.exists():                    # the Stop button dropped a cancel marker
                cancelled = True
                _terminate_process_group(proc, signal.SIGKILL)
                break
            events = sel.select(timeout=0.2)
            got = False
            for key, _ in events:
                line = key.fileobj.readline()
                if line:
                    _emit(line)
                    got = True
            if got:
                last_activity = now
            elif heartbeat and (now - last_activity) >= heartbeat:
                append(task.reply_file, f"… still working ({_elapsed_str(now - start)} elapsed)\n")
                last_activity = now
            if proc.poll() is not None:
                break
        if proc.stdout is not None:
            rest = proc.stdout.read()
            if rest:
                _emit(rest)
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        sel.close()
    rc = proc.wait()
    if cancelled:
        append(task.reply_file, "\n[stopped — cancelled by user]\n```\n")
        note(task, "cancelled by user")
        try:
            cancel_marker.unlink()
        except OSError:
            pass
        raise AgentCancelled("run cancelled by user")
    if timed_out:
        append(task.reply_file, f"\n[stopped at the {timeout}s time limit]\n```\n")
        note(task, f"stopped at the {timeout}s time limit")
        raise AgentTimeout(timeout, "".join(tail))
    append(task.reply_file, f"\n[exit {rc}]\n```\n")
    note(task, f"finished `{label}` with exit {rc}")
    return RunResult(returncode=rc, tail="".join(tail))
