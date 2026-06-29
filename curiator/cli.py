"""cli.py — the `curiator` command.

    curiator up       # serve the gallery (the shell) at the configured port (default 8200)
    curiator watch    # arm the feedback → fix loop (headless agent)
    curiator reply    # (used by the agent) post a ⚙ note to the ledger and set status
    curiator demo     # print the demo walkthrough

`up` and `watch` are two processes — run them in two terminals (or `make demo`).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from . import ledger


def _shell_path() -> Path:
    return Path(__file__).resolve().parent / "shell" / "app_shell.py"


def _reload_in_shell(cfg: dict, app: str) -> str | None:
    """Best-effort: tell a running shell to drop its cached build of `app` so an edit goes live.
    Non-fatal — the shell may be down or on another host. Returns a status line, or None."""
    import urllib.error
    import urllib.request
    port = (cfg.get("shell", {}) or {}).get("port", 8200)
    url = f"http://127.0.0.1:{port}/reload/{app}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=3) as r:
            return f"reloaded {app} in shell :{port} (HTTP {r.status})"
    except (urllib.error.URLError, OSError):
        return None


def cmd_up(args) -> int:
    cfg = load_config()
    port = (cfg.get("shell", {}) or {}).get("port", 8200)
    print(f"curiator: serving the gallery at http://127.0.0.1:{port}  (Ctrl-C to stop)")
    # running the script directly puts shell/ on sys.path[0], so `import registry` resolves.
    return subprocess.run([sys.executable, str(_shell_path())], cwd=cfg["repo_root"]).returncode


def cmd_watch(args) -> int:
    from .loop import loop
    loop.watch(load_config())
    return 0


def cmd_reply(args) -> int:
    """Agent reply path: `curiator reply <app> <feedback_id> "<text>" --status done`."""
    cfg = load_config()
    ts = datetime.now(timezone.utc).isoformat()
    ledger.add_system_note(cfg, args.app, args.text, reply_to=[args.feedback_id],
                           status="update", ts=ts)
    if args.status:
        ledger.set_status(cfg, args.app, [args.feedback_id], args.status)
    print(f"curiator: replied on {args.app}/{args.feedback_id} (status={args.status or 'unchanged'})")
    # On `done`, the agent has just edited the app — make the fix live in a running shell.
    if args.status == "done":
        msg = _reload_in_shell(cfg, args.app)
        print(f"curiator: {msg}" if msg else "curiator: shell not reachable — reload skipped "
              "(the fix shows once `curiator up` reloads the app).")
    return 0


def cmd_reload(args) -> int:
    """Drop a running shell's cached build of <app> so its edited source rebuilds on the next view."""
    cfg = load_config()
    msg = _reload_in_shell(cfg, args.app)
    print(f"curiator: {msg}" if msg else "curiator: shell not reachable on the configured port.")
    return 0


def cmd_demo(args) -> int:
    print(Path(__file__).resolve().parents[1].joinpath("docs", "DEMO_SCRIPT.md").read_text())
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="curiator", description="CurIAtor — an AI-maintained app gallery.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up", help="serve the gallery").set_defaults(func=cmd_up)
    sub.add_parser("watch", help="arm the feedback→fix loop").set_defaults(func=cmd_watch)
    sub.add_parser("demo", help="print the demo walkthrough").set_defaults(func=cmd_demo)
    r = sub.add_parser("reply", help="(agent) post a ⚙ note + set status")
    r.add_argument("app"); r.add_argument("feedback_id"); r.add_argument("text")
    r.add_argument("--status", choices=["done", "awaiting_approval", "working", "new"])
    r.set_defaults(func=cmd_reply)
    rl = sub.add_parser("reload", help="drop a running shell's cached build of an app (make an edit live)")
    rl.add_argument("app"); rl.set_defaults(func=cmd_reload)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
