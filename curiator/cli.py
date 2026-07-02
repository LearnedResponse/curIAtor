"""cli.py — the `curiator` command.

    curiator up         # serve the gallery (the shell) at the configured port
    curiator watch      # arm the feedback → fix loop (headless agent)
    curiator serve      # up + watch together, one process (the container entrypoint)
    curiator reply      # (used by the agent) post a ⚙ note + set status (+ commit the run if git.commit)
    curiator reload     # drop a running shell's cached build of an app (make an edit live)
    curiator revert     # (git-as-memory) undo a curator commit; the record + thread stay intact
    curiator reflect    # (git-as-memory) summarize curator git history into LESSONS.md
    curiator link       # link an app repo/directory to a gallery app
    curiator work       # open a feedback item for interactive CLI work
    curiator done       # finish interactive work via the same reply/reload/git path
    curiator queue      # review held feedback before dispatch
    curiator smoke      # run configured app smoke checks across the collection
    curiator galleries  # list nested curiator-* collection repos under ./galleries
    curiator galleries clone https://github.com/org/curiator-demo.git # clone a collection under ./galleries
    curiator galleries adopt ../curiator-demo # move an existing collection repo under ./galleries
    curiator app templates # list supported scaffold/import templates
    curiator app import <repo-or-url> <name> # copy/clone an existing app repo into apps/<name>
    curiator voice setup # configure local voice transcription
    curiator release-preflight # run doctor/smoke/path checks across release galleries or fresh clones
    curiator playground-preflight # check hosted public-playground posture
    curiator reset-demo # rewind the demo: re-break aviato, clear the ledger
    curiator demo-up    # reset-demo, then serve — one command, record-ready
    curiator demo       # print the demo walkthrough
    curiator stats      # summarize ledger + git-as-memory case-study numbers
    curiator init <dir> # scaffold a fresh collection repo; add --git for a nested subrepo

`up` and `watch` are two processes — run them in two terminals, or use `curiator serve` / `make demo`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil  # noqa: F401 - kept as curiator.cli.shutil for compatibility with CLI tests/extensions
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import agent_label, app_spec, app_specs, load_config
from . import ledger
from .app_cli import (
    _APP_TEMPLATE_CHOICES,
    _JS_PACKAGE_MANAGERS,
    _app_names,
    _template_choices_help,
    cmd_app_create,
    cmd_app_import,
    cmd_app_templates,
)
from .auth_cli import cmd_auth, cmd_user
from .collection_cli import (
    _doctor_issues,  # noqa: F401 - compatibility export used by release/preflight callers
    _doctor_warn_missing_manifests,  # noqa: F401 - compatibility export used by app_cli
    _doctor_warn_proxy_base_path,  # noqa: F401 - compatibility export used by app_cli
    _legacy_command_markdown,  # noqa: F401 - compatibility export used by tests/extensions
    _looks_like_hmr_dev_server,  # noqa: F401 - compatibility export used by app_cli
    _repo_path,  # noqa: F401 - compatibility export used by release/preflight callers
    _smoke_results,  # noqa: F401 - compatibility export used by release/preflight callers
    cmd_commands,
    cmd_doctor,
    cmd_init,
    cmd_link,
    cmd_smoke,
    cmd_status,
)
from .galleries_cli import cmd_galleries, cmd_galleries_adopt, cmd_galleries_clone
from .release_cli import (
    _PUBLIC_RELEASE_OWNER,
    _clone_gallery as _clone_gallery,
    cmd_playground_preflight,
    cmd_release_preflight,
)
from .stats_cli import cmd_stats
from .voice.cli import cmd_voice


def _shell_path(kind: str | None = None) -> Path:
    """The overlay shell entrypoint. React/Flask is the default; Dash remains as a legacy fallback."""
    selected = (kind or os.environ.get("CURIATOR_SHELL") or "react").lower()
    name = "app_shell.py" if selected in {"dash", "legacy", "legacy-dash"} else "web_shell.py"
    return Path(__file__).resolve().parent / "shell" / name


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
    kind = "legacy-dash" if getattr(args, "legacy_dash_shell", False) else None
    return subprocess.run([sys.executable, str(_shell_path(kind))], cwd=cfg["repo_root"],
                          env=_child_env(cfg)).returncode


def cmd_watch(args) -> int:
    from .loop import loop
    loop.watch(load_config())
    return 0


def _serve(cfg: dict, *, reset: bool = False, shell_kind: str | None = None) -> int:
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
        return subprocess.run([sys.executable, str(_shell_path(shell_kind))], cwd=cfg["repo_root"], env=env).returncode
    finally:
        watcher.terminate()
        try:
            watcher.wait(timeout=5)
        except Exception:
            watcher.kill()


def cmd_serve(args) -> int:
    kind = "legacy-dash" if getattr(args, "legacy_dash_shell", False) else None
    return _serve(load_config(), reset=False, shell_kind=kind)


def cmd_demo_up(args) -> int:
    kind = "legacy-dash" if getattr(args, "legacy_dash_shell", False) else None
    return _serve(load_config(), reset=True, shell_kind=kind)


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


def _post_reply(cfg: dict, app: str, feedback_id: str, text: str, status: str | None, actions: str | None = None) -> int:
    ts = datetime.now(timezone.utc).isoformat()
    ledger.add_system_note(cfg, app, text, reply_to=[feedback_id],
                           status="update", ts=ts, actions=_parse_actions_arg(actions),
                           agent=agent_label(cfg))   # WHICH provider answered (Codex / Claude / …)
    if status:
        ledger.set_status(cfg, app, [feedback_id], status)
    print(f"curiator: replied on {app}/{feedback_id} (status={status or 'unchanged'})")
    # Git as the memory: when enabled, this run becomes ONE atomic commit (source edit + ledger).
    # The commit SHA is printed and queryable from git; do not mutate the ledger after commit, or
    # the collection is immediately dirty again.
    if (cfg.get("git", {}) or {}).get("commit"):
        from . import gitmem
        try:
            res = gitmem.commit_run(cfg, app, feedback_id,
                                    status=status or "update", note_text=text)
        except Exception as exc:  # noqa: BLE001 — a git hiccup must never break the reply / loop
            res = {"committed": False, "reason": str(exc)}
        if res.get("committed"):
            for app_commit in res.get("app_commits") or []:
                repo = Path(app_commit.get("repo", "")).name or "app repo"
                print(f"curiator: committed nested app {repo}@{app_commit['sha']} on {app_commit.get('branch','')}")
            for memory_commit in res.get("memory_commits") or []:
                memory = memory_commit.get("memory") or Path(memory_commit.get("repo", "")).name or "memory"
                print(f"curiator: committed memory {memory}@{memory_commit['sha']} on {memory_commit.get('branch','')}")
            if res.get("sha"):
                print(f"curiator: committed {res['sha']} on {res.get('branch','')}")
        else:
            print(f"curiator: not committed ({res.get('reason')})")
    # On `done`, the agent has just edited the app — make the fix live in a running shell.
    if status == "done":
        msg = _reload_in_shell(cfg, app)
        print(f"curiator: {msg}" if msg else "curiator: shell not reachable — reload skipped "
              "(the fix shows once `curiator up` reloads the app).")
    return 0


def cmd_reply(args) -> int:
    """Agent reply path: `curiator reply <app> <feedback_id> "<text>" --status done`.
    When offering options, pass `--actions "A,B,C"` so the approval buttons match the text exactly."""
    return _post_reply(load_config(), args.app, args.feedback_id, args.text, args.status, args.actions)


def _git_output(cwd: Path, *args: str) -> str | None:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def _git_text(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def _project_root(cwd: Path | None = None) -> Path:
    here = (cwd or Path.cwd()).resolve()
    out = _git_output(here, "rev-parse", "--show-toplevel")
    return Path(out).resolve() if out else here


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _is_git_toplevel(repo: Path) -> bool:
    top = _git_output(repo, "rev-parse", "--show-toplevel")
    return bool(top) and Path(top).resolve() == repo.resolve()


def _resolve_app(cfg: dict, app: str | None = None) -> str:
    """The app an app-scoped command targets: the explicit --app, else the linked/inferred current
    app, else the only app. Explicit/linked names are validated against the gallery so a typo (or a
    comment swallowed by a positional) can't create ledger entries under a nonexistent key."""
    from .loop.adapters import GENERAL_KEY
    names = _app_names(cfg)
    chosen = app or cfg.get("current_app")
    if chosen:
        chosen = str(chosen)
        if chosen not in names and chosen != GENERAL_KEY:
            raise SystemExit(f"curIAtor: unknown app {chosen!r} (apps: {', '.join(sorted(names))}).")
        return chosen
    if len(names) == 1:
        return next(iter(names))
    raise SystemExit("curIAtor: no app selected. Pass --app <key> or run `curiator link --app <key>`.")


def _lookup_feedback(cfg: dict, feedback_id: str, app: str | None = None) -> tuple[str, dict] | None:
    """Find a feedback id — the given/linked app first, then every other app (incl. ◆ General)."""
    data = ledger.load(cfg)
    keys = [app, *(k for k in data if k != app)] if app else list(data)
    for key in keys:
        for entry in data.get(key, []):
            if entry.get("id") == feedback_id:
                return key, entry
    return None


def _find_feedback(cfg: dict, feedback_id: str, app: str | None = None) -> tuple[str, dict]:
    found = _lookup_feedback(cfg, feedback_id, app)
    if not found:
        raise SystemExit(f"curIAtor: feedback id {feedback_id!r} not found.")
    return found


OPEN_FEEDBACK_STATUSES = {"new", "working", "awaiting_approval", "held"}


def _choose_feedback(cfg: dict, app: str, statuses: tuple[str, ...] = ("new", "awaiting_approval", "working")) -> dict | None:
    items = ledger.load(cfg).get(app, [])
    for entry in reversed(items):
        if entry.get("kind") != "system" and entry.get("status") in statuses:
            return entry
    return None


def _feedback_counts(cfg: dict, app: str) -> tuple[int, int]:
    items = ledger.load(cfg).get(app, [])
    return len(items), sum(1 for e in items if e.get("kind") != "system" and e.get("status") in OPEN_FEEDBACK_STATUSES)


def _shell_url(cfg: dict, app: str | None = None) -> str:
    port = (cfg.get("shell", {}) or {}).get("port", 8200)
    base = f"http://127.0.0.1:{port}"
    return f"{base}/?app={app}" if app else base


def _curiator_env_cmd(cfg: dict, *parts: str) -> str:
    gallery = shlex.quote(str(Path(cfg["gallery_path"]).resolve()))
    args = " ".join(shlex.quote(str(part)) for part in parts)
    return f"CURIATOR_GALLERY={gallery} curiator {args}"


def _cli_user(cfg: dict) -> dict | None:
    from . import auth
    user = auth.current_user(cfg.get("auth") or {})
    if not user:
        # header/oidc/local modes have no request context on the CLI — record the local git identity
        # (or $USER) instead of dropping provenance. No groups ⇒ never grants an elevated agent run.
        root = Path(cfg["repo_root"])
        email = _git_output(root, "config", "user.email") or f"{os.environ.get('USER') or 'anonymous'}@local"
        name = _git_output(root, "config", "user.name")
        user = {"id": email, "email": email, "name": name or email.split("@")[0], "groups": []}
    return auth.stamp(user)


def cmd_context(args) -> int:
    cfg = load_config()
    try:
        app = _resolve_app(cfg, args.app)
    except SystemExit:
        if args.app or cfg.get("current_app") or len(_app_names(cfg)) <= 1:
            raise
        return _print_collection_context(cfg, args.limit)
    spec = app_spec(cfg, app) or {}
    total, open_n = _feedback_counts(cfg, app)
    print(f"# curIAtor Context: {app}")
    print("")
    print(f"- gallery: `{cfg['gallery_path']}`")
    print(f"- shell: `{_shell_url(cfg, app)}`")
    print(f"- app root: `{spec.get('root') or ''}`")
    print(f"- source scope: `{spec.get('source') or ''}`")
    print(f"- smoke: `{spec.get('smoke') or 'none configured'}`")
    commands = spec.get("commands") if isinstance(spec.get("commands"), dict) else {}
    if commands.get("preview"):
        print(f"- preview: `{commands['preview']}`")
    print(f"- feedback: {open_n} open / {total} total")
    print("")
    print("## Ready Commands")
    print("")
    print(f"- work next item: `{_curiator_env_cmd(cfg, 'work', '--app', app)}`")
    print(f"- show history: `{_curiator_env_cmd(cfg, 'feedback', 'show', app, '--limit', str(args.limit))}`")
    print(f"- add feedback: `{_curiator_env_cmd(cfg, 'feedback', 'add', app, '<comment>')}`")
    print(f"- open URL: `{_shell_url(cfg, app)}`")
    print("")
    print("## Recent Feedback")
    print("")
    _print_feedback_items(cfg, app, limit=args.limit)
    return 0


def _print_collection_context(cfg: dict, limit: int) -> int:
    from .loop.adapters import GENERAL_KEY
    specs = app_specs(cfg)
    data = ledger.load(cfg)
    app_names = [str(spec.get("name") or spec.get("app_name") or "") for spec in specs if spec.get("name")]
    total = sum(len(data.get(name, [])) for name in app_names)
    open_n = sum(
        1
        for name in app_names
        for entry in data.get(name, [])
        if entry.get("kind") != "system" and entry.get("status") in OPEN_FEEDBACK_STATUSES
    )
    general_total, general_open = _feedback_counts(cfg, GENERAL_KEY)
    if general_total:
        total += general_total
        open_n += general_open

    print("# curIAtor Context: collection")
    print("")
    print(f"- gallery: `{cfg['gallery_path']}`")
    print(f"- shell: `{_shell_url(cfg)}`")
    print(f"- apps: {len(specs)}")
    print(f"- feedback: {open_n} open / {total} total")
    print("- selected app: none")
    print("")
    print("## Ready Commands")
    print("")
    print(f"- select an app: `{_curiator_env_cmd(cfg, 'context', '--app', '<app>')}`")
    print(f"- show all feedback: `{_curiator_env_cmd(cfg, 'feedback', 'show', '--limit', str(limit))}`")
    print(f"- add General feedback: `{_curiator_env_cmd(cfg, 'feedback', 'add', GENERAL_KEY, '<comment>')}`")
    print(f"- list app templates: `{_curiator_env_cmd(cfg, 'app', 'templates')}`")
    print(f"- open gallery: `{_shell_url(cfg)}`")
    print("")
    print("## Apps")
    print("")
    if not specs:
        print("- no apps configured")
    for spec in specs:
        name = str(spec.get("name") or spec.get("app_name") or "")
        total_i, open_i = _feedback_counts(cfg, name)
        smoke = spec.get("smoke") or "none configured"
        print(f"- `{name}`: {open_i} open / {total_i} total; smoke `{smoke}`; root `{spec.get('root') or ''}`")
    print("")
    print("## Recent General Feedback")
    print("")
    _print_feedback_items(cfg, GENERAL_KEY, limit=limit)
    return 0


def cmd_work(args) -> int:
    cfg = load_config()
    app = args.app or cfg.get("current_app")
    if args.feedback_id:
        app, entry = _find_feedback(cfg, args.feedback_id, app)
        if entry.get("kind") == "system":
            raise SystemExit(f"curIAtor: {args.feedback_id} is a ⚙ agent note — "
                             "work the user feedback item it replies to instead.")
    else:
        app = _resolve_app(cfg, app)
        entry = _choose_feedback(cfg, app)
        if not entry:
            raise SystemExit(f"curIAtor: no open feedback for {app}.")
    if not args.no_claim:
        ledger.set_status(cfg, app, [entry["id"]], "working")
        entry = {**entry, "status": "working"}
    from .loop import adapters, runlog
    task = adapters.build_task(cfg, app, entry)
    reply_file = Path(task.reply_file)
    if reply_file.exists() and reply_file.stat().st_size:
        runlog.note(task, "opened for interactive CLI work")
    else:
        runlog.init_trace(task, "interactive")
        runlog.note(task, "opened for interactive CLI work")
    print(f"curiator: working {app}/{entry['id']}")
    print(f"task: {task.task_file}")
    print(f"trace: {task.reply_file}")
    if args.print:
        print("")
        print(Path(task.task_file).read_text())
    return 0


def cmd_done(args) -> int:
    cfg = load_config()
    app = args.app or cfg.get("current_app")
    words = list(args.text or [])
    feedback_id = args.feedback_id
    found = _lookup_feedback(cfg, feedback_id, app) if feedback_id else None
    if feedback_id and not found:
        # `curiator done "fixed the axis labels"` — a first word that isn't a known id (and doesn't
        # look like one) is message text, not a typo'd id; fall through to the latest-open-item path.
        if re.fullmatch(r"[0-9a-f]{8}", feedback_id):
            raise SystemExit(f"curIAtor: feedback id {feedback_id!r} not found.")
        words.insert(0, feedback_id)
        feedback_id = None
    if found:
        app = found[0]
    else:
        app = _resolve_app(cfg, app)
        entry = (_choose_feedback(cfg, app, statuses=("working",))              # prefer the claimed item
                 or _choose_feedback(cfg, app, statuses=("new", "awaiting_approval")))
        if not entry:
            raise SystemExit(f"curIAtor: no open feedback for {app}.")
        feedback_id = entry["id"]
    text = " ".join(words).strip() or "Done."
    return _post_reply(cfg, app, feedback_id, text, "done", None)


def cmd_open(args) -> int:
    cfg = load_config()
    app = args.app or cfg.get("current_app")
    print(_shell_url(cfg, app))
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
    ledger.replace_all(cfg, {})
    for name in ("app_feedback.sqlite", "app_feedback.sqlite-wal", "app_feedback.sqlite-shm"):
        p = fb / name
        if p.exists():
            p.unlink()
    legacy = fb / "app_feedback.json"
    if legacy.exists():
        legacy.unlink()
    shots = fb / "shots"
    if shots.is_dir():
        for f in shots.iterdir():
            if f.is_file() and not f.name.startswith("."):   # keep .gitignore / .gitkeep
                f.unlink()
    for t in fb.glob("task_*.md"):                         # legacy pre-feedback/tasks layout
        t.unlink()
    for subdir in ("tasks", "replies"):
        d = fb / subdir
        if d.is_dir():
            for f in d.glob("*.md"):
                f.unlink()


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
    paths = gitmem.write_all_lessons(cfg)
    for p in paths:
        print(f"curiator: wrote {p} — loaded into that memory's agent context.")
    return 0


def cmd_reset_demo(args) -> int:
    _reset_demo(load_config())
    print("curiator: demo reset — aviato re-broken, ledger cleared, shots/ + task files wiped.")
    return 0


def cmd_seed(args) -> int:
    """Load canned feedback (a YAML file) into the ledger as new entries — the self-building-demo
    build queue. Each item becomes a status:new entry, attributed to the seed's `user:` (provenance),
    so the loop services it like any feedback. Format: `user: {…}` +
    `items: [{app, comment, stars?, user?, annotations?}]`."""
    import yaml
    from .annotations import clean_annotations

    cfg = load_config()
    spec = yaml.safe_load(Path(args.file).read_text()) or {}
    default_user = spec.get("user")
    ts = datetime.now(timezone.utc).isoformat()
    n = 0
    for it in (spec.get("items") or []):
        extra = {}
        annotations = clean_annotations(it.get("annotations"))
        if annotations:
            extra["annotations"] = annotations
        ledger.save_entry(cfg, it["app"], stars=it.get("stars"), comment=it.get("comment", ""),
                          ts=ts, user=it.get("user", default_user), extra=extra or None)
        n += 1
    who = (default_user or {}).get("name") or "—"
    print(f"curiator: seeded {n} feedback item(s) from {args.file} (author: {who}) — `curiator watch` to build.")
    return 0


def _print_feedback_items(cfg: dict, app: str, limit: int = 20) -> None:
    from .loop import runlog
    items = ledger.load(cfg).get(app, [])
    shown = items[-limit:] if limit else items
    if not shown:
        print(f"{app}: no feedback")
        return
    print(f"{app}:")
    for e in shown:
        who = e.get("agent") if e.get("author") == "claude" else ((e.get("user") or {}).get("name") or "user")
        flags = []
        if e.get("reply_to"):
            flags.append("reply_to=" + ",".join(e.get("reply_to") or []))
        if e.get("screenshot"):
            flags.append("screenshot=" + e.get("screenshot"))
        trace = runlog.reply_path(cfg, e.get("id"))
        if trace.exists():
            flags.append("trace=" + str(trace.relative_to(Path(cfg["repo_root"]))))
        extra = f" [{' · '.join(flags)}]" if flags else ""
        comment = " ".join((e.get("comment") or "").split())
        print(f"  {e.get('id')} {e.get('status')} {e.get('kind')} {who}: {comment[:160]}{extra}")


def _cli_annotations(args) -> list[dict]:
    raw_text = args.annotations_json
    if args.annotations_file:
        raw_text = Path(args.annotations_file).read_text()
    if not raw_text:
        return []
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"curIAtor: invalid annotation JSON: {exc}") from exc
    from .annotations import clean_annotations
    marks = clean_annotations(raw)
    if not marks:
        raise SystemExit("curIAtor: annotation JSON did not contain any valid marks.")
    return marks


def cmd_feedback(args) -> int:
    """Inspect the SQLite feedback ledger. This is intentionally CLI-level tooling so headless agents can
    inspect history without treating the SQLite file format as a private API."""
    import json
    cfg = load_config()
    if args.action == "add":
        app = _resolve_app(cfg, args.app)
        comment = (args.comment_text or " ".join(args.comment or [])).strip()
        if not comment and not args.stars:
            raise SystemExit("curIAtor: feedback add needs a comment and/or --stars.")
        extra = {}
        if args.reply_to:
            extra["reply_to"] = [args.reply_to]
        if args.status and args.status != "new":
            extra["status"] = args.status
        annotations = _cli_annotations(args)
        if annotations:
            extra["annotations"] = annotations
        eid = ledger.save_entry(cfg, app, stars=args.stars, comment=comment, user=_cli_user(cfg),
                                extra=extra or None)
        suffix = f" with {len(annotations)} annotation(s)" if annotations else ""
        print(f"curiator: added feedback {app}/{eid}{suffix}")
        return 0
    data = ledger.load(cfg)
    if args.app:
        data = {args.app: data.get(args.app, [])}
    if args.action == "dump":
        print(json.dumps(data if args.app is None else data.get(args.app, []), indent=2))
        return 0
    for app, items in data.items():
        if items:
            _print_feedback_items(cfg, app, args.limit)
    return 0


def _queue_actor(cfg: dict) -> str:
    root = Path(cfg["repo_root"])
    git_email = _git_output(root, "config", "user.email")
    if git_email:
        return git_email
    user = _cli_user(cfg) or {}
    return user.get("email") or user.get("name") or user.get("id") or "local CLI"


def _queue_entries(cfg: dict, app: str | None = None) -> list[tuple[str, dict]]:
    data = ledger.load(cfg)
    keys = [app] if app else list(data)
    rows: list[tuple[str, dict]] = []
    for key in keys:
        for entry in data.get(key, []):
            if entry.get("kind") != "system" and entry.get("status") == "held":
                rows.append((key, entry))
    return rows


def _parse_entry_ts(entry: dict) -> datetime | None:
    raw = entry.get("ts")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _queue_older_than(rows: list[tuple[str, dict]], days: float, *, now: datetime | None = None) -> list[tuple[str, dict]]:
    if days <= 0:
        raise SystemExit("curIAtor: --older-than must be greater than 0 days.")
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    return [(app, entry) for app, entry in rows if (ts := _parse_entry_ts(entry)) is not None and ts <= cutoff]


def _queue_row_payload(app: str, entry: dict) -> dict:
    user = entry.get("user") or {}
    comment = " ".join((entry.get("comment") or "").split())
    return {
        "app": app,
        "id": entry.get("id"),
        "ts": entry.get("ts"),
        "author": user.get("email") or user.get("name") or entry.get("author"),
        "stars": entry.get("stars"),
        "comment": comment,
    }


def _queue_sweep_payload(app: str, entry: dict, *, now: datetime | None = None) -> dict:
    payload = _queue_row_payload(app, entry)
    ts = _parse_entry_ts(entry)
    if ts:
        age_days = ((now or datetime.now(timezone.utc)) - ts).total_seconds() / 86400
        payload["age_days"] = round(max(age_days, 0.0), 2)
    else:
        payload["age_days"] = None
    return payload


def _print_queue_rows(rows: list[tuple[str, dict]]) -> None:
    if not rows:
        print("curiator: held queue is empty")
        return
    print(f"curiator: {len(rows)} held feedback item(s)")
    for app, entry in rows:
        payload = _queue_row_payload(app, entry)
        stars = f" ★{payload['stars']}" if payload.get("stars") else ""
        author = payload.get("author") or "user"
        comment = payload.get("comment") or "(no comment)"
        print(f"  {payload['id']} {app}{stars} {payload.get('ts') or '-'} {author}: {comment[:160]}")


def _queue_reject(cfg: dict, app: str, entry: dict, *, actor: str, reason: str = "", prefix: str = "rejected") -> None:
    text = f"Moderation queue: {prefix} by {actor}; closed without agent dispatch."
    if reason:
        text += f" Reason: {reason}"
    ledger.add_system_note(cfg, app, text, reply_to=[entry["id"]], agent="curiator queue")
    ledger.set_status(cfg, app, [entry["id"]], "rejected")


def cmd_queue(args) -> int:
    """Review feedback held out of agent dispatch.

    `held` is admission control for anonymous/over-quota/public submissions. The watcher only dispatches
    status:new entries, so approve is a narrow held→new transition and reject closes the thread as
    rejected with a ledger note.
    """
    cfg = load_config()
    if args.action == "list":
        app = _resolve_app(cfg, args.app) if args.app else None
        rows = _queue_entries(cfg, app)
        if args.limit:
            rows = rows[:args.limit]
        if args.json:
            print(json.dumps([_queue_row_payload(key, entry) for key, entry in rows], indent=2))
        else:
            _print_queue_rows(rows)
        return 0

    if args.action == "sweep":
        app = _resolve_app(cfg, args.app) if args.app else None
        rows = _queue_older_than(_queue_entries(cfg, app), args.older_than)
        if args.limit:
            rows = rows[:args.limit]
        actor = _queue_actor(cfg)
        reason = " ".join(args.reason or []).strip()
        if args.apply:
            for key, entry in rows:
                sweep_reason = reason or f"stale held feedback older than {args.older_than:g} day(s)"
                _queue_reject(
                    cfg,
                    key,
                    entry,
                    actor=actor,
                    reason=sweep_reason,
                    prefix="stale held item rejected",
                )
        result = {
            "ok": True,
            "action": "sweep",
            "applied": bool(args.apply),
            "matched": len(rows),
            "older_than_days": args.older_than,
            "rows": [_queue_sweep_payload(key, entry) for key, entry in rows],
        }
        if args.json:
            print(json.dumps(result, indent=2))
        elif args.apply:
            print(f"curiator: rejected {len(rows)} held feedback item(s) older than {args.older_than:g} day(s)")
            _print_queue_rows(rows)
        else:
            print(
                f"curiator: sweep dry-run found {len(rows)} held feedback item(s) older than "
                f"{args.older_than:g} day(s); pass --apply to reject them"
            )
            _print_queue_rows(rows)
        return 0

    app, entry = _find_feedback(cfg, args.feedback_id, args.app)
    if entry.get("kind") == "system":
        raise SystemExit(f"curIAtor: {args.feedback_id} is a system note, not a held feedback item.")
    if entry.get("status") != "held":
        raise SystemExit(f"curIAtor: {args.feedback_id} is status={entry.get('status')!r}, not held.")

    actor = _queue_actor(cfg)
    if args.action == "approve":
        ledger.add_system_note(
            cfg,
            app,
            f"Moderation queue: approved by {actor}; dispatching to the agent.",
            reply_to=[entry["id"]],
            agent="curiator queue",
        )
        ledger.set_status(cfg, app, [entry["id"]], "new")
        result = {"app": app, "id": entry["id"], "status": "new", "action": "approved"}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"curiator: approved {app}/{entry['id']} → new")
        return 0

    reason = " ".join(args.reason or []).strip()
    _queue_reject(cfg, app, entry, actor=actor, reason=reason)
    result = {"app": app, "id": entry["id"], "status": "rejected", "action": "rejected", "reason": reason}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"curiator: rejected {app}/{entry['id']} → rejected")
    return 0




def cmd_demo(args) -> int:
    print(Path(__file__).resolve().parents[1].joinpath("docs", "DEMO_SCRIPT.md").read_text())
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="curiator", description="curIAtor — an AI-maintained app gallery.")
    sub = p.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up", help="serve the gallery")
    up.add_argument("--legacy-dash-shell", action="store_true", help="serve the old Dash overlay shell")
    up.set_defaults(func=cmd_up)
    sub.add_parser("watch", help="arm the feedback→fix loop").set_defaults(func=cmd_watch)
    serve = sub.add_parser("serve", help="gallery + fix loop together (one process; the container entrypoint)")
    serve.add_argument("--legacy-dash-shell", action="store_true", help="serve the old Dash overlay shell")
    serve.set_defaults(func=cmd_serve)
    sub.add_parser("demo", help="print the demo walkthrough").set_defaults(func=cmd_demo)
    sub.add_parser("reset-demo", help="rewind the demo: re-break aviato, clear the ledger"
                   ).set_defaults(func=cmd_reset_demo)
    demo_up = sub.add_parser("demo-up", help="reset-demo, then serve — one command, record-ready")
    demo_up.add_argument("--legacy-dash-shell", action="store_true", help="serve the old Dash overlay shell")
    demo_up.set_defaults(func=cmd_demo_up)
    ip = sub.add_parser("init", help="scaffold a new collection repo in <dir>")
    ip.add_argument("dir")
    ip.add_argument("--git", action="store_true", help="initialize <dir> as its own git repository")
    ip.set_defaults(func=cmd_init)
    lk = sub.add_parser("link", help="link this app repo/directory to a gallery app")
    lk.add_argument("--gallery", help="path to gallery.yaml")
    lk.add_argument("--app", help="app key in the gallery")
    lk.add_argument("--root", help="where to write .curiator/app.yaml (default: git root or cwd)")
    lk.add_argument("--commands", action="store_true", help="also install local Claude/Codex command shims")
    lk.set_defaults(func=cmd_link)
    st = sub.add_parser("status", help="show linked gallery/app and git-as-memory state")
    st.add_argument("--app", help="override linked/current app")
    st.set_defaults(func=cmd_status)
    dr = sub.add_parser("doctor", help="check collection config portability and app paths")
    dr.add_argument("--json", action="store_true", help="emit machine-readable diagnostics")
    dr.set_defaults(func=cmd_doctor)
    sm = sub.add_parser("smoke", help="run configured app smoke commands for this collection")
    sm.add_argument("--app", help="limit smoke checks to one app")
    sm.add_argument("--jobs", type=int, default=1, help="run up to N smoke checks concurrently (default: 1)")
    sm.add_argument("--http", action="store_true", help="also start proxy apps briefly and verify HTTP response")
    sm.add_argument("--json", action="store_true", help="emit machine-readable results")
    sm.set_defaults(func=cmd_smoke)
    gl = sub.add_parser("galleries", help="list, clone, or adopt nested curiator-* collection repos")
    gl.add_argument("--root", default="galleries", help="directory containing curiator-* gallery repos")
    gl.add_argument("--json", action="store_true", help="emit machine-readable gallery repo status")
    gl.set_defaults(func=cmd_galleries)
    gl_sub = gl.add_subparsers(dest="galleries_action")
    adopt = gl_sub.add_parser("adopt", help="move or copy an existing gallery repo under ./galleries")
    adopt.add_argument("source", help="existing curIAtor gallery repo to adopt, e.g. ../curiator-aviato")
    adopt.add_argument("--root", default=argparse.SUPPRESS, help="directory containing curiator-* gallery repos")
    adopt.add_argument("--name", help="destination directory name; curiator- is added if omitted")
    adopt.add_argument("--copy", action="store_true", help="copy instead of moving the source repo")
    adopt.add_argument("--no-rewrite-runner", action="store_true",
                       help="do not rewrite checkout runner.path when it points at this curIAtor checkout")
    adopt.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                       help="emit machine-readable adoption result")
    adopt.set_defaults(func=cmd_galleries_adopt)
    clone = gl_sub.add_parser("clone", help="clone a curIAtor gallery repo under ./galleries")
    clone.add_argument("source", help="git URL or local git repo to clone, e.g. https://github.com/org/curiator-demo.git")
    clone.add_argument("--root", default=argparse.SUPPRESS, help="directory containing curiator-* gallery repos")
    clone.add_argument("--name", help="destination directory name; curiator- is added if omitted")
    clone.add_argument("--no-rewrite-runner", action="store_true",
                       help="do not rewrite checkout runner.path when cloning from a local sibling repo")
    clone.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                       help="emit machine-readable clone result")
    clone.set_defaults(func=cmd_galleries_clone)
    rp = sub.add_parser("release-preflight", help="run release checks across nested public galleries")
    rp.add_argument("--root", default="galleries", help="directory containing curiator-* gallery repos")
    rp.add_argument("--gallery", action="append",
                    help="gallery directory name under --root; repeatable; default is the public release set")
    rp.add_argument("--include-optional", action="store_true",
                    help="with the default public release set, also check optional public-shaped galleries")
    rp.add_argument("--path-needle", action="append",
                    help="extra machine-local path string to reject in tracked files")
    rp.add_argument("--allow-dirty", action="store_true", help="report dirty nested repos without failing")
    rp.add_argument("--fresh-clone", action="store_true", help="clone each gallery first and preflight the clone")
    rp.add_argument("--clone-root", help="directory for fresh-clone runs; a unique run-* directory is created inside")
    rp.add_argument("--keep-clones", action="store_true", help="do not delete fresh-clone run directories")
    rp.add_argument("--no-smoke", action="store_true", help="skip per-app smoke checks")
    rp.add_argument("--http-smoke", "--http", action="store_true", dest="http_smoke",
                    help="also start proxy apps briefly and verify configured HTTP smoke paths")
    rp.add_argument("--strict", action="store_true", help="fail when doctor warnings are present")
    rp.add_argument("--require-public-remotes", action="store_true",
                    help="also require each gallery's origin remote to match its expected public GitHub repo")
    rp.add_argument("--require-published-head", action="store_true",
                    help="also require each gallery's exact HEAD commit to be present on origin")
    rp.add_argument("--public-remote-owner", default=_PUBLIC_RELEASE_OWNER,
                    help=f"GitHub owner/org for --require-public-remotes (default: {_PUBLIC_RELEASE_OWNER})")
    rp.add_argument("--output", help="write the JSON preflight payload to a file")
    rp.add_argument("--json", action="store_true", help="emit machine-readable diagnostics")
    rp.set_defaults(func=cmd_release_preflight)
    pp = sub.add_parser("playground-preflight", help="check hosted public-playground readiness")
    pp.add_argument("--no-smoke", action="store_true", help="skip per-app smoke checks")
    pp.add_argument("--http-smoke", "--http", action="store_true", dest="http_smoke",
                    help="also start proxy apps briefly and verify configured HTTP smoke paths")
    pp.add_argument("--strict", action="store_true", help="fail when posture or doctor warnings are present")
    pp.add_argument("--output", help="write the JSON preflight payload to a file")
    pp.add_argument("--json", action="store_true", help="emit machine-readable diagnostics")
    pp.set_defaults(func=cmd_playground_preflight)
    cx = sub.add_parser("context", help="print app context and recent feedback for interactive agents")
    cx.add_argument("--app", help="override linked/current app")
    cx.add_argument("--limit", type=int, default=8)
    cx.set_defaults(func=cmd_context)
    wk = sub.add_parser("work", help="claim/open a feedback item and print its task bundle")
    wk.add_argument("feedback_id", nargs="?", help="feedback id; defaults to latest open item for the app")
    wk.add_argument("--app", help="override linked/current app")
    wk.add_argument("--no-claim", action="store_true", help="do not set the feedback status to working")
    wk.add_argument("--no-print", dest="print", action="store_false", default=True,
                    help="write the task file but do not print it")
    wk.set_defaults(func=cmd_work)
    dn = sub.add_parser("done", help="reply done for interactive work (reload + git-as-memory)")
    dn.add_argument("feedback_id", nargs="?",
                    help="feedback id (defaults to the latest working item); a non-id word here is "
                         "treated as the start of the summary text")
    dn.add_argument("text", nargs="*", help="summary text")
    dn.add_argument("--app", help="override linked/current app")
    dn.set_defaults(func=cmd_done)
    qu = sub.add_parser("queue", help="review held feedback before it reaches the agent")
    qu_sub = qu.add_subparsers(dest="action", required=True)
    ql = qu_sub.add_parser("list", help="list held feedback items")
    ql.add_argument("--app", help="limit to one app")
    ql.add_argument("--limit", type=int, default=50, help="maximum held items to show (0 = all)")
    ql.add_argument("--json", action="store_true", help="emit machine-readable held queue rows")
    ql.set_defaults(func=cmd_queue)
    qa = qu_sub.add_parser("approve", help="approve a held item and dispatch it as status:new")
    qa.add_argument("feedback_id")
    qa.add_argument("--app", help="disambiguate the feedback id")
    qa.add_argument("--json", action="store_true", help="emit machine-readable result")
    qa.set_defaults(func=cmd_queue)
    qr = qu_sub.add_parser("reject", help="close a held item without agent dispatch")
    qr.add_argument("feedback_id")
    qr.add_argument("reason", nargs="*", help="optional reason recorded in the thread")
    qr.add_argument("--app", help="disambiguate the feedback id")
    qr.add_argument("--json", action="store_true", help="emit machine-readable result")
    qr.set_defaults(func=cmd_queue)
    qs = qu_sub.add_parser("sweep", help="dry-run or reject stale held feedback items")
    qs.add_argument("--older-than", type=float, default=30.0,
                    help="held feedback age in days required for sweep eligibility (default: 30)")
    qs.add_argument("--app", help="limit sweep to one app")
    qs.add_argument("--limit", type=int, default=0, help="maximum items to sweep (0 = all)")
    qs.add_argument("--reason", nargs="*", help="optional rejection reason for applied sweeps")
    qs.add_argument("--apply", action="store_true", help="actually reject matched held items")
    qs.add_argument("--json", action="store_true", help="emit machine-readable sweep result")
    qs.set_defaults(func=cmd_queue)
    op = sub.add_parser("open", help="print the gallery/app URL")
    op.add_argument("--app", help="override linked/current app")
    op.set_defaults(func=cmd_open)
    cmds = sub.add_parser("commands", help="install local slash-command shims")
    cmds.add_argument("action", choices=["install"], nargs="?", default="install")
    cmds.add_argument("--root", help="where to install shims (default: git root or cwd)")
    cmds.set_defaults(func=cmd_commands)
    app = sub.add_parser("app", help="manage apps in this collection")
    app_sub = app.add_subparsers(dest="action", required=True)
    at = app_sub.add_parser("templates", help="list supported app scaffold/import templates")
    at.add_argument("--json", action="store_true", help="emit machine-readable template metadata")
    at.set_defaults(func=cmd_app_templates)
    ac = app_sub.add_parser("create", help="scaffold an app directory and add it to gallery.yaml")
    ac.add_argument("name", help="app key, e.g. orange_picker")
    ac.add_argument("--template", choices=_APP_TEMPLATE_CHOICES, default="dash",
                    help=f"scaffold template (default: dash; choices: {_template_choices_help()})")
    ac.add_argument("--title", help="display title")
    ac.add_argument("--tags", help="comma-separated tags; default is the template name")
    ac.add_argument("--port", type=int, help="proxy port for non-Dash templates")
    ac.add_argument("--package-manager", choices=["auto", *_JS_PACKAGE_MANAGERS], default="auto",
                    help="JS package manager for react/svelte/vue/next templates (default: auto)")
    ac.add_argument("--force", action="store_true", help="allow an existing apps/<name> directory")
    ac.set_defaults(func=cmd_app_create)
    ai = app_sub.add_parser("import", help="copy/clone an existing app repo and add it to gallery.yaml")
    ai.add_argument("source", help="local app directory or git URL to copy/clone")
    ai.add_argument("name", help="app key, e.g. orange_picker")
    ai.add_argument("--template", choices=_APP_TEMPLATE_CHOICES, required=True,
                    help=f"mount template to register for the imported app; choices: {_template_choices_help()}")
    ai.add_argument("--title", help="display title")
    ai.add_argument("--tags", help="comma-separated tags; default is the template name")
    ai.add_argument("--port", type=int, help="proxy port for non-Dash templates")
    ai.add_argument("--package-manager", choices=["auto", *_JS_PACKAGE_MANAGERS], default="auto",
                    help="JS package manager for react/svelte/vue/next templates (default: auto)")
    ai.set_defaults(func=cmd_app_import)
    ia = sub.add_parser("init-app", help="alias for `curiator app create`")
    ia.add_argument("name", help="app key, e.g. orange_picker")
    ia.add_argument("--template", choices=_APP_TEMPLATE_CHOICES, default="dash",
                    help=f"scaffold template (default: dash; choices: {_template_choices_help()})")
    ia.add_argument("--title", help="display title")
    ia.add_argument("--tags", help="comma-separated tags; default is the template name")
    ia.add_argument("--port", type=int, help="proxy port for non-Dash templates")
    ia.add_argument("--package-manager", choices=["auto", *_JS_PACKAGE_MANAGERS], default="auto",
                    help="JS package manager for react/svelte/vue/next templates (default: auto)")
    ia.add_argument("--force", action="store_true", help="allow an existing apps/<name> directory")
    ia.set_defaults(func=cmd_app_create)
    r = sub.add_parser("reply", help="(agent) post a ⚙ note + set status")
    r.add_argument("app"); r.add_argument("feedback_id"); r.add_argument("text")
    r.add_argument("--status", choices=["done", "awaiting_approval", "working", "new", "held", "rejected"])
    r.add_argument("--actions", help="quick-approval buttons, e.g. \"A,B,C\" or \"Yes:yes,No:no\"")
    r.set_defaults(func=cmd_reply)
    rl = sub.add_parser("reload", help="drop a running shell's cached build of an app (make an edit live)")
    rl.add_argument("app"); rl.set_defaults(func=cmd_reload)
    sd = sub.add_parser("seed", help="load canned feedback (YAML) into the ledger — a self-building demo queue")
    sd.add_argument("file"); sd.set_defaults(func=cmd_seed)
    stt = sub.add_parser("stats", help="summarize ledger + git-as-memory metrics")
    stt.add_argument("mode", nargs="?", choices=["compare"], help="use `compare` for collection-level rows")
    stt.add_argument("galleries", nargs="*", help="gallery.yaml paths or collection directories for `stats compare`")
    stt.add_argument("--app", help="limit metrics to one app")
    stats_out = stt.add_mutually_exclusive_group()
    stats_out.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    stats_out.add_argument("--markdown", action="store_true", help="emit Markdown tables for release notes or papers")
    stats_out.add_argument("--csv", action="store_true", help="emit app-level CSV rows")
    stt.add_argument("--output", help="write the selected stats report to a file instead of stdout")
    stt.add_argument("--no-git", action="store_true", help="skip git log metrics")
    stt.set_defaults(func=cmd_stats)
    fb = sub.add_parser("feedback", help="inspect or add SQLite feedback")
    fb.add_argument("action", choices=["show", "dump", "add"], nargs="?", default="show")
    fb.add_argument("app", nargs="?")
    fb.add_argument("comment", nargs="*")
    fb.add_argument("--comment", dest="comment_text")
    fb.add_argument("--stars", type=int, choices=range(1, 6))
    fb.add_argument("--reply-to")
    fb.add_argument("--status", choices=["new", "held"], default="new",
                    help="initial feedback status; held items wait for `curiator queue approve`")
    annotation_src = fb.add_mutually_exclusive_group()
    annotation_src.add_argument("--annotations-json", help="JSON list of screenshot annotation marks to store")
    annotation_src.add_argument("--annotations-file", help="path to a JSON file containing annotation marks")
    fb.add_argument("--limit", type=int, default=20)
    fb.set_defaults(func=cmd_feedback)
    us = sub.add_parser("user", help="manage local-login users (auth.mode: local)")
    us.add_argument("action", choices=["add", "passwd", "list", "disable", "enable", "remove"],
                    help="add/upsert · passwd · list · disable · enable · remove")
    us.add_argument("email", nargs="?")
    us.add_argument("--name"); us.add_argument("--groups", help="comma-separated")
    us.add_argument("--password", help="non-interactive password (otherwise prompted)")
    us.set_defaults(func=cmd_user)
    at = sub.add_parser("auth", help="show or set auth.mode in gallery.yaml")
    at.add_argument("mode", nargs="?", choices=["none", "local", "header", "oidc"])
    at.set_defaults(func=cmd_auth)
    vc = sub.add_parser("voice", help="show or configure local voice transcription")
    vc_sub = vc.add_subparsers(dest="action", required=True)
    vs = vc_sub.add_parser("show", help="show active voice transcription config")
    vs.set_defaults(func=cmd_voice)
    vsetup = vc_sub.add_parser("setup", help="configure local faster-whisper transcription")
    vsetup.add_argument("--engine", choices=["faster-whisper"], default="faster-whisper",
                        help="local transcription adapter to configure")
    vsetup.add_argument("--timeout", type=int, default=60, help="transcription timeout in seconds")
    vsetup.add_argument("--max-bytes", type=int, default=25 * 1024 * 1024, help="maximum uploaded audio bytes")
    vsetup.add_argument("--force", action="store_true", help="overwrite an existing voice.transcribe_cmd")
    vsetup.set_defaults(func=cmd_voice)
    vweb = vc_sub.add_parser("web-speech", help="enable or disable browser Web Speech dictation")
    vweb.add_argument("state", choices=["on", "off"])
    vweb.add_argument("--lang", default=None, help="optional BCP-47 recognition language, such as en-US")
    vweb.set_defaults(func=cmd_voice)
    vaudio = vc_sub.add_parser("retain-audio", help="enable or disable retained audio clips for replay")
    vaudio.add_argument("state", choices=["on", "off"])
    vaudio.set_defaults(func=cmd_voice)
    rv = sub.add_parser("revert", help="(git-as-memory) undo a curator commit; record + thread stay intact")
    rv.add_argument("target", help="a feedback id or a commit SHA")
    rv.add_argument("--reason", default=None, help="why (recorded in the ⚙ note + revert commit)")
    rv.set_defaults(func=cmd_revert)
    sub.add_parser("reflect", help="(git-as-memory) summarize curator history into LESSONS.md"
                   ).set_defaults(func=cmd_reflect)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
