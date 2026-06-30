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
    # -u: unbuffered, so the watcher's ●/▶/✓ feedback+agent lines stream out immediately (not block-buffered
    # behind the shell when serve's stdout isn't a TTY).
    watcher = subprocess.Popen([sys.executable, "-u", "-m", "curiator.cli", "watch"],
                               cwd=cfg["repo_root"], env=env)
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


def _parse_actions_arg(s):
    """`--actions "A,B,C"` or `"Yes:yes,No:no"` → [[label, value], …] for quick-approval buttons."""
    out = []
    for item in (s or "").split(","):
        item = item.strip()
        if not item:
            continue
        lbl, _, val = item.partition(":")
        out.append([lbl.strip(), (val.strip() or lbl.strip())])
    return out or None


def cmd_reply(args) -> int:
    """Agent reply path: `curiator reply <app> <feedback_id> "<text>" --status done`.
    When offering options, pass `--actions "A,B,C"` so the approval buttons match the text exactly."""
    cfg = load_config()
    ts = datetime.now(timezone.utc).isoformat()
    nid = ledger.add_system_note(cfg, args.app, args.text, reply_to=[args.feedback_id],
                                 status="update", ts=ts, actions=_parse_actions_arg(args.actions))
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


def cmd_seed(args) -> int:
    """Load canned feedback (a YAML file) into the ledger as new entries — the self-building-demo
    build queue. Each item becomes a status:new entry, attributed to the seed's `user:` (provenance),
    so the loop services it like any feedback. Format: `user: {…}` + `items: [{app, comment, stars?, user?}]`."""
    import yaml
    cfg = load_config()
    spec = yaml.safe_load(Path(args.file).read_text()) or {}
    default_user = spec.get("user")
    ts = datetime.now(timezone.utc).isoformat()
    n = 0
    for it in (spec.get("items") or []):
        ledger.save_entry(cfg, it["app"], stars=it.get("stars"), comment=it.get("comment", ""),
                          ts=ts, user=it.get("user", default_user))
        n += 1
    who = (default_user or {}).get("name") or "—"
    print(f"curiator: seeded {n} feedback item(s) from {args.file} (author: {who}) — `curiator watch` to build.")
    return 0


def cmd_user(args) -> int:
    """Manage local-login users (`auth.mode: local`) — hashed passwords in the gitignored users file.
    `add` upserts (re-running it keeps the existing name/groups unless you pass --name/--groups);
    `passwd` changes only the password (so it can't silently wipe the groups that gate elevated runs)."""
    from . import auth
    cfg = load_config()
    users_file = (cfg.get("auth") or {}).get("users_file")
    users = auth.load_users_file(users_file)
    if args.action == "list":
        if not users:
            print("curiator: no local users yet — `curiator user add <email>`")
        for email, u in sorted(users.items()):
            print(f"  {email}  ·  {u.get('name') or '—'}  ·  groups={u.get('groups') or []}")
        return 0
    if not args.email:
        print(f"curiator: `user {args.action}` needs an <email>"); return 1
    if args.action == "remove":
        if users.pop(args.email, None) is None:
            print(f"curiator: no such user {args.email}"); return 1
        auth.save_users_file(users_file, users)
        print(f"curiator: removed {args.email}")
        return 0
    # add (upsert) / passwd (change only the password)
    existing = users.get(args.email) or {}
    if args.action == "passwd" and not existing:
        print(f"curiator: no such user {args.email} — `curiator user add {args.email}` to create it"); return 1
    from werkzeug.security import generate_password_hash
    pw = args.password
    if not pw:
        import getpass
        pw = getpass.getpass("password: ")
        if pw != getpass.getpass("confirm:  "):
            print("curiator: passwords don't match"); return 1
    if not pw:
        print("curiator: empty password"); return 1
    if args.action == "passwd":                          # change ONLY the password — keep name/groups/etc.
        rec = {**existing, "password_hash": generate_password_hash(pw)}
    else:                                                # add: merge — keep existing name/groups unless overridden
        name = args.name if args.name is not None else (existing.get("name") or args.email.split("@")[0])
        groups = ([g.strip() for g in args.groups.split(",") if g.strip()]
                  if args.groups is not None else (existing.get("groups") or []))
        rec = {"name": name, "groups": groups, "password_hash": generate_password_hash(pw)}
    users[args.email] = rec
    auth.save_users_file(users_file, users)
    verb = "changed password for" if args.action == "passwd" else ("updated" if existing else "added")
    print(f"curiator: {verb} local user {args.email} → {users_file}")
    return 0


def cmd_auth(args) -> int:
    """Show or set `auth.mode` in gallery.yaml (none | local | header | oidc), preserving comments."""
    import re
    cfg = load_config()
    gallery = Path(cfg["gallery_path"])
    if not args.mode:
        print(f"curiator: auth.mode = {cfg['auth']['mode']}  ({gallery})")
        return 0
    text = gallery.read_text()
    pat = re.compile(r"(?ms)^(auth:[^\n]*\n(?:[ \t]+[^\n]*\n)*?[ \t]+mode:[ \t]*)(\S+)")
    if pat.search(text):
        text = pat.sub(lambda m: m.group(1) + args.mode, text, count=1)   # keep the inline comment
    else:
        text += ("" if text.endswith("\n") else "\n") + f"\nauth:\n  mode: {args.mode}\n"
    gallery.write_text(text)
    print(f"curiator: auth.mode → {args.mode}  ({gallery})  — restart `curiator up` to apply")
    if args.mode == "local":
        from . import auth
        if not auth.load_users_file(cfg["auth"]["users_file"]):
            print("curiator: no local users yet — create one with `curiator user add <email>`")
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
    r.add_argument("--actions", help="quick-approval buttons, e.g. \"A,B,C\" or \"Yes:yes,No:no\"")
    r.set_defaults(func=cmd_reply)
    rl = sub.add_parser("reload", help="drop a running shell's cached build of an app (make an edit live)")
    rl.add_argument("app"); rl.set_defaults(func=cmd_reload)
    sd = sub.add_parser("seed", help="load canned feedback (YAML) into the ledger — a self-building demo queue")
    sd.add_argument("file"); sd.set_defaults(func=cmd_seed)
    us = sub.add_parser("user", help="manage local-login users (auth.mode: local)")
    us.add_argument("action", choices=["add", "passwd", "list", "remove"],
                    help="add (upsert, keeps name/groups) · passwd (change only the password) · list · remove")
    us.add_argument("email", nargs="?")
    us.add_argument("--name"); us.add_argument("--groups", help="comma-separated")
    us.add_argument("--password", help="non-interactive password (otherwise prompted)")
    us.set_defaults(func=cmd_user)
    at = sub.add_parser("auth", help="show or set auth.mode in gallery.yaml")
    at.add_argument("mode", nargs="?", choices=["none", "local", "header", "oidc"])
    at.set_defaults(func=cmd_auth)
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
.curiator-users.json
__pycache__/
*.pyc
"""


if __name__ == "__main__":
    raise SystemExit(main())
