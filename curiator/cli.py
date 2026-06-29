"""cli.py — the `curiator` command.

    curiator up         # serve the gallery (the shell) at the configured port
    curiator watch      # arm the feedback → fix loop (headless agent)
    curiator serve      # up + watch together, one process (the container entrypoint)
    curiator reply      # (used by the agent) post a ⚙ note + set status (+ commit the run if git.commit)
    curiator reload     # drop a running shell's cached build of an app (make an edit live)
    curiator revert     # (git-as-memory) undo a curator commit; the record + thread stay intact
    curiator reflect    # (git-as-memory) summarize curator git history into LESSONS.md
    curiator reset-demo # rewind the demo: re-break aviato, clear the ledger
    curiator demo-up    # reset-demo, then serve — one command, record-ready
    curiator demo       # print the demo walkthrough
    curiator init <dir> # scaffold a fresh collection repo

`up` and `watch` are two processes — run them in two terminals, or use `curiator serve` / `make demo`.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from . import ledger


def _shell_path() -> Path:
    return Path(__file__).resolve().parent / "shell" / "app_shell.py"


def _child_env(cfg: dict) -> dict:
    """Env for child processes (the shell, the watcher): pin CURIATOR_GALLERY so the shell's registry
    resolves the SAME gallery — and therefore the same collection root for app sources + the ledger —
    that config.py resolved here. Without this, running from a collection dir mounts nothing."""
    return {**os.environ, "CURIATOR_GALLERY": cfg["gallery_path"]}


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
    return subprocess.run([sys.executable, str(_shell_path())], cwd=cfg["repo_root"],
                          env=_child_env(cfg)).returncode


def cmd_watch(args) -> int:
    from .loop import loop
    loop.watch(load_config())
    return 0


def _serve(cfg: dict, *, reset: bool = False) -> int:
    """Run the gallery (foreground) + the fix loop (background) together. Ctrl-C / SIGTERM stops both.
    Used by `curiator serve` (the container entrypoint) and `curiator demo-up` (reset=True)."""
    if reset:
        _reset_demo(cfg)
    port = (cfg.get("shell", {}) or {}).get("port", 8200)
    url = f"http://127.0.0.1:{port}"
    # the watcher is its own process so the foreground shell owns the terminal; we reap it on exit.
    env = _child_env(cfg)
    watcher = subprocess.Popen([sys.executable, "-m", "curiator.cli", "watch"], cwd=cfg["repo_root"], env=env)
    bar = "─" * 56
    print(f"\n{bar}\n  ◆ curIAtor is up")
    print(f"    gallery : {url}")
    print(f"    watcher : armed — feedback→fix loop "
          f"(adapter={(cfg.get('agent', {}) or {}).get('adapter', 'headless-cc')}, "
          f"autonomy={(cfg.get('agent', {}) or {}).get('autonomy', 'auto-small')})")
    if reset:
        print(f"    record  : open {url}, select aviato, drop a comment + 📷, watch the curator")
    print(f"    stop    : Ctrl-C\n{bar}\n")
    sys.stdout.flush()   # the shell child writes straight to fd1; flush so our banner isn't buffered behind it
    try:
        return subprocess.run([sys.executable, str(_shell_path())], cwd=cfg["repo_root"], env=env).returncode
    finally:
        watcher.terminate()
        try:
            watcher.wait(timeout=5)
        except Exception:
            watcher.kill()


def cmd_serve(args) -> int:
    return _serve(load_config(), reset=False)


def cmd_demo_up(args) -> int:
    return _serve(load_config(), reset=True)


def cmd_reply(args) -> int:
    """Agent reply path: `curiator reply <app> <feedback_id> "<text>" --status done`."""
    cfg = load_config()
    ts = datetime.now(timezone.utc).isoformat()
    nid = ledger.add_system_note(cfg, args.app, args.text, reply_to=[args.feedback_id],
                                 status="update", ts=ts)
    if args.status:
        ledger.set_status(cfg, args.app, [args.feedback_id], args.status)
    print(f"curiator: replied on {args.app}/{args.feedback_id} (status={args.status or 'unchanged'})")
    # Git as the memory: when enabled, this run becomes ONE atomic commit (source edit + ledger). The
    # SHA is stamped back onto this ⚙ note so the conversation points at the history.
    if (cfg.get("git", {}) or {}).get("commit"):
        from . import gitmem
        try:
            res = gitmem.commit_run(cfg, args.app, args.feedback_id,
                                    status=args.status or "update", note_text=args.text)
        except Exception as exc:  # noqa: BLE001 — a git hiccup must never break the reply / loop
            res = {"committed": False, "reason": str(exc)}
        if res.get("committed"):
            ledger.amend_note(cfg, args.app, nid, f"\n\ncommitted `{res['sha']}` on `{res.get('branch','')}`")
            print(f"curiator: committed {res['sha']} on {res.get('branch','')}")
        else:
            print(f"curiator: not committed ({res.get('reason')})")
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


def _reset_demo(cfg: dict) -> None:
    """Idempotent rewind: re-break the demo apps (restore tracked source), clear the ledger to {},
    wipe screenshots + task bundles. The 'another take' button for the demo recording."""
    repo = Path(cfg["repo_root"])
    sources = [a["source"] for a in (cfg.get("apps") or []) if a.get("source") and (repo / a["source"]).exists()]
    if sources:
        r = subprocess.run(["git", "checkout", "--", *sources], cwd=repo, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"curiator: reset-demo: skipped git checkout ({(r.stderr or '').strip() or 'not a git repo?'})")
    fb = repo / (cfg.get("feedback", {}).get("dir", "feedback"))
    (fb / "app_feedback.json").write_text("{}\n")
    shots = fb / "shots"
    if shots.is_dir():
        for f in shots.iterdir():
            if f.is_file() and not f.name.startswith("."):   # keep .gitignore / .gitkeep
                f.unlink()
    for t in fb.glob("task_*.md"):
        t.unlink()


def cmd_revert(args) -> int:
    """Undo a curator commit without erasing the record: revert the source + append a ⚙ note, as its own
    `curator(<app>): revert` commit. `target` is a feedback id or a commit SHA."""
    cfg = load_config()
    from . import gitmem
    res = gitmem.revert_feedback(cfg, args.target, reason=args.reason or "manual revert")
    if not res.get("ok"):
        print(f"curiator: revert failed — {res.get('reason')}")
        return 1
    scope = "source + ledger" if res.get("reverted_source") else "ledger note only (was plan/ack — no source)"
    print(f"curiator: reverted {res['reverted']} → {res['sha']} ({scope}); thread on {res.get('app')} intact")
    if res.get("reverted_source"):
        msg = _reload_in_shell(cfg, res["app"])
        print(f"curiator: {msg}" if msg else "curiator: shell not reachable — reload skipped.")
    return 0


def cmd_reflect(args) -> int:
    """Summarize the curator's git history (curator(*) commits + reverts) into LESSONS.md."""
    cfg = load_config()
    from . import gitmem
    p = gitmem.write_lessons(cfg)
    print(f"curiator: wrote {p} — loaded into each agent run's task bundle.")
    return 0


def cmd_reset_demo(args) -> int:
    _reset_demo(load_config())
    print("curiator: demo reset — aviato re-broken, ledger cleared, shots/ + task files wiped.")
    return 0


def cmd_demo(args) -> int:
    print(Path(__file__).resolve().parents[1].joinpath("docs", "DEMO_SCRIPT.md").read_text())
    return 0


def cmd_init(args) -> int:
    """Scaffold a fresh collection repo: gallery.yaml + apps/sample.py + requirements.txt + feedback/ + README."""
    dest = Path(args.dir).resolve()
    files = _scaffold_files()
    created, skipped = [], []
    for rel, content in files.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            skipped.append(rel)
        else:
            p.write_text(content)
            created.append(rel)
    (dest / "feedback" / "shots").mkdir(parents=True, exist_ok=True)
    print(f"curiator: scaffolded a collection in {dest}")
    for f in created:
        print(f"  + {f}")
    for f in skipped:
        print(f"  · {f} (exists — left as-is)")
    print(f"\nnext:\n  cd {dest}\n  pip install -r requirements.txt\n"
          f"  curiator up        # gallery (then `curiator watch` in a second terminal, or `curiator serve`)")
    return 0


def _scaffold_files() -> dict[str, str]:
    return {
        "gallery.yaml": _SCAFFOLD_GALLERY,
        "apps/sample.py": _SCAFFOLD_SAMPLE_APP,
        "requirements.txt": _SCAFFOLD_REQUIREMENTS,
        "README.md": _SCAFFOLD_README,
        "feedback/app_feedback.json": "{}\n",
        ".gitignore": _SCAFFOLD_GITIGNORE,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="curiator", description="CurIAtor — an AI-maintained app gallery.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("up", help="serve the gallery").set_defaults(func=cmd_up)
    sub.add_parser("watch", help="arm the feedback→fix loop").set_defaults(func=cmd_watch)
    sub.add_parser("serve", help="gallery + fix loop together (one process; the container entrypoint)"
                   ).set_defaults(func=cmd_serve)
    sub.add_parser("demo", help="print the demo walkthrough").set_defaults(func=cmd_demo)
    sub.add_parser("reset-demo", help="rewind the demo: re-break aviato, clear the ledger"
                   ).set_defaults(func=cmd_reset_demo)
    sub.add_parser("demo-up", help="reset-demo, then serve — one command, record-ready"
                   ).set_defaults(func=cmd_demo_up)
    ip = sub.add_parser("init", help="scaffold a new collection repo in <dir>")
    ip.add_argument("dir"); ip.set_defaults(func=cmd_init)
    r = sub.add_parser("reply", help="(agent) post a ⚙ note + set status")
    r.add_argument("app"); r.add_argument("feedback_id"); r.add_argument("text")
    r.add_argument("--status", choices=["done", "awaiting_approval", "working", "new"])
    r.set_defaults(func=cmd_reply)
    rl = sub.add_parser("reload", help="drop a running shell's cached build of an app (make an edit live)")
    rl.add_argument("app"); rl.set_defaults(func=cmd_reload)
    rv = sub.add_parser("revert", help="(git-as-memory) undo a curator commit; record + thread stay intact")
    rv.add_argument("target", help="a feedback id or a commit SHA")
    rv.add_argument("--reason", default=None, help="why (recorded in the ⚙ note + revert commit)")
    rv.set_defaults(func=cmd_revert)
    sub.add_parser("reflect", help="(git-as-memory) summarize curator history into LESSONS.md"
                   ).set_defaults(func=cmd_reflect)
    args = p.parse_args(argv)
    return args.func(args)


# ───────────────────────── collection scaffold templates (curiator init) ─────────────────────────

_SCAFFOLD_GALLERY = """\
# CurIAtor collection — your apps (apps/) + how the curator runs.
# Add one entry per app; the curator edits each app's `source` when you give feedback on it.

apps:
  - name: sample
    title: Sample app
    mount: { kind: dash-inproc, module: sample }   # import & mount in-process (Dash); or kind: proxy {cmd, port}
    source: apps/sample.py                          # what the curator edits
    tags: [demo]

agent:
  adapter: headless-cc        # headless-cc (your Claude sub) | api (teams) | command (BYO)
  autonomy: auto-small        # auto-small (fix small things) | propose-only (plan first)

# How feedback on the RUNNER itself (the ◆ General channel) is handled:
runner:
  mode: pinned                # pinned (consumer): drafts an upstream issue/PR; never edits the package
  # mode: checkout            # contributor: patches the runner locally (set `path` to a curiator checkout)
  # path: ../curiator

feedback:
  dir: feedback               # JSON ledger + shots/ live here
  screenshots: true

shell:
  port: 8300
"""

_SCAFFOLD_SAMPLE_APP = '''\
"""sample.py — a starter Dash app. Star/comment/screenshot it in the gallery and the curator edits THIS file.

Every CurIAtor app exposes `build_app()` returning a `dash.Dash`, plus a module-level `app` so the
shell can mount it either way.
"""
from __future__ import annotations

import dash
from dash import dcc, html
import plotly.graph_objects as go


def build_app() -> dash.Dash:
    app = dash.Dash(__name__)
    app.title = "Sample"
    fig = go.Figure(go.Bar(x=["A", "B", "C", "D"], y=[4, 7, 3, 8], marker_color="#2980b9"))
    fig.update_layout(title="Sample metric", xaxis_title="category", yaxis_title="value",
                      margin=dict(l=60, r=20, t=40, b=40), plot_bgcolor="white", height=420)
    app.layout = html.Div(
        style={"fontFamily": "system-ui, sans-serif", "margin": "12px 20px"},
        children=[
            html.H3("Sample app"),
            html.P("Leave a comment in the gallery and the curator will edit this file."),
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
        ],
    )
    return app


app = build_app()

if __name__ == "__main__":
    app.run(debug=False, port=8401)
'''

_SCAFFOLD_REQUIREMENTS = """\
curiator>=0.1.0   # pin exact (curiator==X.Y.Z) for a reproducible collection
"""

_SCAFFOLD_README = """\
# My CurIAtor collection

Apps live in `apps/`; `gallery.yaml` is the registry. CurIAtor serves every app in one gallery and an
AI curator fixes them from in-browser feedback (star / comment / screenshot).

## Run

    pip install -r requirements.txt
    curiator up        # gallery at http://127.0.0.1:8300
    curiator watch     # (second terminal) arm the feedback→fix loop
    # …or both at once:  curiator serve

Open the gallery, star/comment/screenshot an app, and watch the curator reply in the panel.

## Add an app

Drop `apps/<name>.py` (exposing `build_app()`), add an entry to `gallery.yaml`, reload the gallery.

See the consumer guide: https://github.com/LearnedResponse/curiator/blob/main/docs/USING_CURIATOR.md
"""

_SCAFFOLD_GITIGNORE = """\
feedback/shots/
feedback/task_*.md
__pycache__/
*.pyc
"""


if __name__ == "__main__":
    raise SystemExit(main())
