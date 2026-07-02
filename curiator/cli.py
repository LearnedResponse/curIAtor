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
    curiator app import <repo-or-url> <name> # copy/clone an existing app repo into apps/<name>
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
import ast
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import LINK_REL, agent_label, app_spec, app_specs, load_config, load_config_at
from . import ledger


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


def _project_root(cwd: Path | None = None) -> Path:
    here = (cwd or Path.cwd()).resolve()
    out = _git_output(here, "rev-parse", "--show-toplevel")
    return Path(out).resolve() if out else here


def _galleries_root(root_arg: str | None) -> Path:
    project = _project_root()
    raw = Path(root_arg or "galleries").expanduser()
    return raw.resolve() if raw.is_absolute() else (project / raw).resolve()


def _discover_galleries(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        p for p in root.iterdir()
        if p.is_dir() and p.name.startswith("curiator-") and (p / "gallery.yaml").exists()
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _gallery_summary(repo: Path) -> dict:
    is_git = _git_output(repo, "rev-parse", "--is-inside-work-tree") == "true"
    dirty = _git_text(repo, "status", "--porcelain", "--untracked-files=all").splitlines() if is_git else []
    return {
        "name": repo.name,
        "path": str(repo),
        "gallery": str(repo / "gallery.yaml"),
        "git": is_git,
        "branch": _git_output(repo, "branch", "--show-current") if is_git else None,
        "head": _git_output(repo, "rev-parse", "--short", "HEAD") if is_git else None,
        "dirty": dirty,
    }


def _rel_cmd_path(path: str) -> str:
    try:
        return os.path.relpath(Path(path), Path.cwd())
    except ValueError:  # pragma: no cover - different Windows drives
        return path


def cmd_galleries(args) -> int:
    root = _galleries_root(args.root)
    galleries = [_gallery_summary(repo) for repo in _discover_galleries(root)]
    payload = {"root": str(root), "count": len(galleries), "galleries": galleries}
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"curiator: {len(galleries)} nested galleries under {root}")
    if not galleries:
        print("  none found; create one with `curiator init galleries/curiator-my-topic --git`")
        return 0
    for g in galleries:
        git = "not-git"
        if g["git"]:
            branch = g.get("branch") or "detached"
            head = g.get("head") or "no-head"
            git = f"{branch}@{head}"
        dirty = f"{len(g['dirty'])} dirty" if g["dirty"] else "clean"
        gallery = _rel_cmd_path(g["gallery"])
        print(f"  {g['name']}: {git}, {dirty}")
        print(f"    use: CURIATOR_GALLERY={shlex.quote(gallery)} curiator status")
    return 0


def _gallery_name_from_source(source: str) -> str:
    raw = source.rstrip("/")
    name = Path(raw).name or raw.rsplit("/", 1)[-1] or "gallery"
    if name.endswith(".git"):
        name = name[:-4]
    return name


def _safe_gallery_name(name: str) -> str:
    return name if name.startswith("curiator-") else f"curiator-{name}"


def _valid_gallery_dir_name(name: str) -> bool:
    return name.startswith("curiator-") and Path(name).name == name and name not in {"curiator-", ".", ".."}


def _is_git_toplevel(repo: Path) -> bool:
    top = _git_output(repo, "rev-parse", "--show-toplevel")
    return bool(top) and Path(top).resolve() == repo.resolve()


def _maybe_rewrite_nested_runner_path(gallery: Path, *, old_repo: Path, project: Path) -> list[dict]:
    """After adopting a sibling checkout under galleries/, rewrite only the safe, common case:
    runner.mode=checkout and runner.path used to resolve to this runner checkout. Public/pinned
    galleries and custom runner targets are left untouched."""
    import yaml

    raw = yaml.safe_load(gallery.read_text()) or {}
    if not isinstance(raw, dict):
        return []
    runner = raw.get("runner")
    if not isinstance(runner, dict) or runner.get("mode") != "checkout":
        return []
    path = runner.get("path")
    if not path:
        return []
    old_target = (old_repo / str(path)).resolve()
    if old_target != project:
        return []
    new_path = os.path.relpath(project, gallery.parent)
    if str(path) == new_path:
        return []
    runner["path"] = new_path
    gallery.write_text(yaml.safe_dump(raw, sort_keys=False))
    return [{
        "field": "runner.path",
        "from": str(path),
        "to": new_path,
        "reason": "source runner.path resolved to this curIAtor checkout before adoption",
    }]


def _adopt_gallery_payload(args) -> dict:
    project = _project_root()
    root = _galleries_root(args.root)
    source = Path(args.source).expanduser()
    source = source.resolve() if source.is_absolute() else (Path.cwd() / source).resolve()
    name = _safe_gallery_name(args.name or source.name)
    dest = (root / name).resolve()
    payload = {
        "ok": False,
        "action": "copy" if args.copy else "move",
        "source": str(source),
        "destination": str(dest),
        "gallery": str(dest / "gallery.yaml"),
        "runner_rewrites": [],
        "use": f"CURIATOR_GALLERY={_rel_cmd_path(str(dest / 'gallery.yaml'))} curiator status",
    }
    if not source.exists() or not source.is_dir():
        payload["error"] = f"source directory not found: {source}"
        return payload
    if not (source / "gallery.yaml").exists():
        payload["error"] = f"source is not a curIAtor gallery (missing gallery.yaml): {source}"
        return payload
    if not _is_git_toplevel(source):
        payload["error"] = f"source must be its own git repository: {source}"
        return payload
    if not _valid_gallery_dir_name(name):
        payload["error"] = f"destination name must be a single curiator-* directory: {name}"
        return payload
    if source == dest:
        payload["ok"] = True
        payload["already_nested"] = True
        return payload
    if _is_relative_to(root, source):
        payload["error"] = f"refusing to adopt into a root inside the source directory: {root}"
        return payload
    if dest.exists():
        payload["error"] = f"destination already exists: {dest}"
        return payload

    root.mkdir(parents=True, exist_ok=True)
    if args.copy:
        shutil.copytree(source, dest)
    else:
        shutil.move(str(source), str(dest))
    if not args.no_rewrite_runner:
        payload["runner_rewrites"] = _maybe_rewrite_nested_runner_path(
            dest / "gallery.yaml",
            old_repo=source,
            project=project,
        )
    payload["ok"] = True
    return payload


def _clone_gallery_payload(args) -> dict:
    project = _project_root()
    root = _galleries_root(args.root)
    source_arg = args.source
    source_path = Path(source_arg).expanduser()
    local_source = None
    if source_path.exists():
        local_source = source_path.resolve()
    name = _safe_gallery_name(args.name or _gallery_name_from_source(source_arg))
    dest = (root / name).resolve()
    payload = {
        "ok": False,
        "action": "clone",
        "source": source_arg,
        "destination": str(dest),
        "gallery": str(dest / "gallery.yaml"),
        "runner_rewrites": [],
        "use": f"CURIATOR_GALLERY={_rel_cmd_path(str(dest / 'gallery.yaml'))} curiator status",
    }
    if not _valid_gallery_dir_name(name):
        payload["error"] = f"destination name must be a single curiator-* directory: {name}"
        return payload
    if dest.exists():
        payload["error"] = f"destination already exists: {dest}"
        return payload

    root.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["git", "clone", "--quiet", source_arg, str(dest)], capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"git clone exited {result.returncode}").strip()
        payload["error"] = f"git clone failed: {detail}"
        return payload
    if not (dest / "gallery.yaml").exists():
        shutil.rmtree(dest)
        payload["error"] = f"cloned repo is not a curIAtor gallery (missing gallery.yaml): {source_arg}"
        return payload
    if not _is_git_toplevel(dest):
        shutil.rmtree(dest)
        payload["error"] = f"cloned repo is not its own git repository: {source_arg}"
        return payload
    if local_source is not None and not args.no_rewrite_runner:
        payload["runner_rewrites"] = _maybe_rewrite_nested_runner_path(
            dest / "gallery.yaml",
            old_repo=local_source,
            project=project,
        )
    payload["ok"] = True
    return payload


def cmd_galleries_adopt(args) -> int:
    payload = _adopt_gallery_payload(args)
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1
    if not payload["ok"]:
        print(f"curiator: galleries adopt FAILED — {payload.get('error', 'unknown error')}")
        return 1
    verb = "copied" if payload["action"] == "copy" else "moved"
    if payload.get("already_nested"):
        print(f"curiator: gallery is already nested at {payload['destination']}")
    else:
        print(f"curiator: {verb} {payload['source']} -> {payload['destination']}")
    for rewrite in payload["runner_rewrites"]:
        print(f"  rewrote {rewrite['field']}: {rewrite['from']} -> {rewrite['to']}")
    print(f"  use: {payload['use']}")
    return 0


def cmd_galleries_clone(args) -> int:
    payload = _clone_gallery_payload(args)
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1
    if not payload["ok"]:
        print(f"curiator: galleries clone FAILED — {payload.get('error', 'unknown error')}")
        return 1
    print(f"curiator: cloned {payload['source']} -> {payload['destination']}")
    for rewrite in payload["runner_rewrites"]:
        print(f"  rewrote {rewrite['field']}: {rewrite['from']} -> {rewrite['to']}")
    print(f"  use: {payload['use']}")
    return 0


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


def _portable_gallery_link(gallery: Path, root: Path) -> str:
    """Path written to .curiator/app.yaml. Prefer relative links for clone portability."""
    try:
        return os.path.relpath(gallery.resolve(), root.resolve())
    except ValueError:  # pragma: no cover - different Windows drives
        return str(gallery.resolve())


def cmd_link(args) -> int:
    """Link the current app repo/directory to a collection gallery + app key."""
    import yaml

    gallery = Path(args.gallery).expanduser().resolve() if args.gallery else Path(load_config()["gallery_path"]).resolve()
    if not gallery.exists():
        raise SystemExit(f"curIAtor: gallery not found: {gallery}")
    old_gallery = os.environ.get("CURIATOR_GALLERY")
    os.environ["CURIATOR_GALLERY"] = str(gallery)
    try:
        cfg = load_config()
    finally:
        if old_gallery is None:
            os.environ.pop("CURIATOR_GALLERY", None)
        else:
            os.environ["CURIATOR_GALLERY"] = old_gallery
    app = args.app or cfg.get("current_app")
    if not app:
        raise SystemExit("curIAtor: pass --app <key> for this link.")
    if app not in _app_names(cfg):
        raise SystemExit(f"curIAtor: app {app!r} is not in {gallery}")
    root = Path(args.root).expanduser().resolve() if args.root else _project_root()
    link_path = root / LINK_REL
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.write_text(yaml.safe_dump({"gallery": _portable_gallery_link(gallery, root), "app": app}, sort_keys=False))
    print(f"curiator: linked {root} → {gallery} app={app}")
    print(f"  wrote {link_path}")
    if args.commands:
        _install_command_files(root)
    return 0


def cmd_status(args) -> int:
    cfg = load_config()
    app = args.app or cfg.get("current_app")
    root = Path(cfg["repo_root"])
    branch = _git_output(root, "branch", "--show-current") or "not a git repo"
    dirty = _git_output(root, "status", "--porcelain")
    git = cfg.get("git", {}) or {}
    print("curIAtor status")
    print(f"  gallery: {cfg['gallery_path']}")
    if cfg.get("link_path"):
        print(f"  link:    {cfg['link_path']}")
    print(f"  shell:   {_shell_url(cfg, app)}")
    print(f"  git:     commit={git.get('commit')} branch={git.get('branch') or branch} include_ledger={git.get('include_ledger')}")
    print(f"  repo:    {root} [{branch}{', dirty' if dirty else ', clean'}]")
    if app:
        spec = app_spec(cfg, app) or {}
        total, open_n = _feedback_counts(cfg, app)
        print(f"  app:     {app}")
        print(f"  root:    {spec.get('root') or 'unknown'}")
        print(f"  source:  {spec.get('source') or 'unknown'}")
        if spec.get("smoke"):
            print(f"  smoke:   {spec['smoke']}")
        commands = spec.get("commands") if isinstance(spec.get("commands"), dict) else {}
        if commands.get("preview"):
            print(f"  preview: {commands['preview']}")
        print(f"  feedback:{open_n} open / {total} total")
        print(f"  next:    curiator work --app {app}")
    else:
        print("  app:     none selected (pass --app or run curiator link)")
    return 0


_PORTABLE_PATH_KEYS = {"path", "root", "source", "cwd", "dir", "users_file", "gallery", "gallery_path"}
_USER_ABS_PATH_RE = re.compile(r"(?<![\w.-])(?:/[A-Za-z0-9_.-]+)?/(?:home|Users)/[^\s'\"`]+|[A-Za-z]:[\\/]+Users[\\/]+[^\s'\"`]+")


def _looks_absolute_path(value: str) -> bool:
    return value.startswith("/") or bool(re.match(r"^[A-Za-z]:[\\/]", value))


def _repo_path(cfg: dict, path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    try:
        return str(p.resolve().relative_to(Path(cfg["repo_root"]).resolve())) or "."
    except ValueError:
        return str(p)


def _doctor_scan_portability(node, where: str, issues: list[dict], needles: tuple[str, ...]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            loc = f"{where}.{key}" if where else str(key)
            if isinstance(value, str):
                if str(key) in _PORTABLE_PATH_KEYS and _looks_absolute_path(value):
                    issues.append({
                        "severity": "error",
                        "where": loc,
                        "message": f"absolute path breaks clone portability: {value}",
                    })
                for needle in needles:
                    if needle and needle in value:
                        issues.append({
                            "severity": "error",
                            "where": loc,
                            "message": f"contains machine-local path {needle}",
                        })
                if _USER_ABS_PATH_RE.search(value):
                    issues.append({
                        "severity": "error",
                        "where": loc,
                        "message": "contains a user-home absolute path",
                    })
            else:
                _doctor_scan_portability(value, loc, issues, needles)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _doctor_scan_portability(value, f"{where}[{i}]", issues, needles)


def _command_executable(command: str | None) -> str | None:
    if not command:
        return None
    try:
        parts = shlex.split(str(command))
    except ValueError:
        return None
    if not parts:
        return None
    if parts[0] == "env":
        parts = parts[1:]
    while parts and "=" in parts[0] and not parts[0].startswith(("/", "./", "../")):
        key, _, _ = parts[0].partition("=")
        if not key.replace("_", "").isalnum():
            break
        parts = parts[1:]
    return parts[0] if parts else None


def _executable_exists(executable: str, cwd: Path) -> bool:
    p = Path(executable)
    if p.is_absolute():
        return p.exists()
    if any(sep in executable for sep in ("/", "\\")):
        return (cwd / p).exists()
    return shutil.which(executable) is not None


def _doctor_warn_missing_executable(
    issues: list[dict],
    *,
    where: str,
    command: str | None,
    cwd: Path,
    label: str,
) -> None:
    executable = _command_executable(command)
    if not executable or _executable_exists(executable, cwd):
        return
    issues.append({
        "severity": "warning",
        "where": where,
        "message": f"{label} executable not found on PATH: {executable}",
    })


def _manifest_expectations(command: str | None) -> dict[str, list[str]]:
    executable = (_command_executable(command) or "").lower()
    command_text = str(command or "").lower()
    if executable in {"npm", "pnpm", "yarn", "bun", "node"}:
        return {"Node app": ["package.json"]}
    if executable == "streamlit" or "streamlit run" in command_text:
        return {"Python/Streamlit app": ["requirements.txt", "pyproject.toml", "environment.yml", "environment.yaml"]}
    if executable == "cargo":
        return {"Rust app": ["Cargo.toml"]}
    return {}


_OPTIONAL_PYTHON_FRAMEWORKS = {
    "fastapi": "Python/FastAPI app",
    "gradio": "Python/Gradio app",
    "streamlit": "Python/Streamlit app",
}
_PYTHON_DEP_MANIFESTS = ["requirements.txt", "pyproject.toml", "environment.yml", "environment.yaml"]


def _python_import_roots(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0].lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0].lower())
    return roots


def _python_project_imports(root: Path) -> set[str]:
    if not root.exists() or not root.is_dir():
        return set()
    imports: set[str] = set()
    for path in sorted(root.glob("*.py")):
        imports.update(_python_import_roots(path))
    return imports


def _project_text(root: Path, patterns: tuple[str, ...]) -> str:
    if not root.exists() or not root.is_dir():
        return ""
    chunks: list[str] = []
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return "\n".join(chunks)


def _first_config_text(root: Path, names: tuple[str, ...]) -> str:
    for name in names:
        path = root / name
        if not path.exists():
            continue
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    return ""


def _python_framework_manifest_expectations(root: Path) -> dict[str, list[str]]:
    """Return optional Python framework dependency manifests implied by top-level app imports."""
    imports = _python_project_imports(root)
    return {
        label: _PYTHON_DEP_MANIFESTS
        for module, label in _OPTIONAL_PYTHON_FRAMEWORKS.items()
        if module in imports
    }


def _command_tokens(command: str | None) -> list[str]:
    if not command:
        return []
    try:
        parts = shlex.split(str(command))
    except ValueError:
        parts = str(command).split()
    if parts and parts[0] == "env":
        parts = parts[1:]
    while parts and "=" in parts[0] and not parts[0].startswith(("/", "./", "../")):
        key, _, _ = parts[0].partition("=")
        if not key.replace("_", "").isalnum():
            break
        parts = parts[1:]
    return [p.lower() for p in parts]


def _looks_like_hmr_dev_server(command: str | None) -> bool:
    parts = _command_tokens(command)
    if not parts:
        return False
    text = " ".join(parts)
    if parts[0] == "vite" or (parts[0] == "npx" and len(parts) > 1 and parts[1] == "vite"):
        return True
    if text.startswith(("next dev", "npx next dev", "webpack serve", "npx webpack serve")):
        return True
    for manager in ("npm", "pnpm", "yarn", "bun"):
        if text.startswith((f"{manager} run dev", f"{manager} dev")):
            return True
    return False


def _doctor_warn_missing_manifests(
    issues: list[dict],
    *,
    name: str,
    root: Path,
    commands: list[str | None],
) -> None:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    expectation_sets = [_manifest_expectations(command) for command in commands]
    expectation_sets.append(_python_framework_manifest_expectations(root))
    for expectations in expectation_sets:
        for label, filenames in expectations.items():
            key = (label, tuple(filenames))
            if key in seen:
                continue
            seen.add(key)
            if any((root / filename).exists() for filename in filenames):
                continue
            issues.append({
                "severity": "warning",
                "where": f"app {name} dependencies",
                "message": f"{label} is missing dependency manifest ({' or '.join(filenames)}) in {root}",
            })


def _doctor_warn_proxy_base_path(issues: list[dict], *, name: str, root: Path, mount: dict) -> None:
    """Warn when a known framework proxy app is missing the path-prefix config curIAtor needs."""
    cmd = str(mount.get("cmd") or "")
    command_text = cmd.lower()
    package_text = _first_config_text(root, ("package.json",)).lower()
    python_imports = _python_project_imports(root)
    python_text = _project_text(root, ("*.py",)).lower()

    vite_config = _first_config_text(root, ("vite.config.js", "vite.config.mjs", "vite.config.ts"))
    is_vite = bool(vite_config) or "vite" in package_text or "vite" in command_text
    if is_vite:
        compact = vite_config.lower().replace(" ", "")
        if not vite_config:
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Vite app has no vite.config.*; set base from CURIATOR_APP so assets resolve under /app/<name>/",
            })
        elif "base" not in compact or ("curiator_app" not in compact and "/app/${" not in compact and "/app/" not in compact):
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Vite config does not appear to set an /app/<name>/ base path from CURIATOR_APP",
            })

    next_config = _first_config_text(root, ("next.config.mjs", "next.config.js", "next.config.ts"))
    is_next = bool(next_config) or '"next"' in package_text or "next dev" in command_text or "next start" in command_text
    if is_next:
        if not mount.get("preserve_prefix"):
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Next.js proxy mount should set preserve_prefix: true so its basePath routes reach the app",
            })
        compact = next_config.lower().replace(" ", "")
        if not next_config or "basepath" not in compact or ("curiator_app" not in compact and "/app/" not in compact):
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Next.js config does not appear to set basePath from CURIATOR_APP for /app/<name>/",
            })

    if "streamlit" in python_imports or "streamlit run" in command_text:
        if not mount.get("preserve_prefix"):
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Streamlit proxy mount should set preserve_prefix: true with server.baseUrlPath",
            })
        if "--server.baseurlpath" not in command_text:
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Streamlit command does not set --server.baseUrlPath app/{app}",
            })

    if "gradio" in python_imports:
        if not mount.get("preserve_prefix"):
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Gradio proxy mount should set preserve_prefix: true with a root_path",
            })
        if "--root-path" not in command_text and "root_path" not in python_text:
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Gradio app does not appear to configure root_path for /app/<name>/",
            })

    if "fastapi" in python_imports and "--root-path" not in command_text and "root_path" not in python_text:
        issues.append({
            "severity": "warning",
            "where": f"app {name} proxy",
            "message": "FastAPI app does not appear to configure root_path for /app/<name>/",
        })


def _doctor_issues(cfg: dict) -> list[dict]:
    import yaml

    issues: list[dict] = []
    gallery = Path(cfg["gallery_path"])
    repo = Path(cfg["repo_root"]).resolve()
    raw = yaml.safe_load(gallery.read_text()) or {}
    needles = tuple({str(repo), str(Path.home())} - {"", "/"})
    _doctor_scan_portability(raw, "gallery.yaml", issues, needles)

    link = cfg.get("link") or {}
    if link:
        gallery_link = str(link.get("gallery") or link.get("gallery_path") or "")
        if gallery_link and _looks_absolute_path(gallery_link):
            issues.append({
                "severity": "error",
                "where": cfg.get("link_path") or ".curiator/app.yaml",
                "message": f"linked gallery is absolute; rerun `curiator link` to write a relative link: {gallery_link}",
            })

    seen_specs: set[tuple[str, str, str]] = set()
    for spec in app_specs(cfg):
        name = str(spec.get("name") or spec.get("app_name") or "<unknown>")
        mount = spec.get("mount") or {}
        root_path = Path(spec.get("root") or repo)
        source_path = Path(spec.get("source") or "")
        for label in ("root", "source"):
            raw_path = spec.get(label)
            if not raw_path:
                continue
            path = Path(raw_path)
            key = (name, label, str(path))
            if key in seen_specs:
                continue
            seen_specs.add(key)
            if not path.exists():
                issues.append({
                    "severity": "error",
                    "where": f"app {name} {label}",
                    "message": f"configured path does not exist: {path}",
                })
        if not spec.get("smoke") and (mount.get("kind") == "proxy" or source_path.is_dir()):
            issues.append({
                "severity": "warning",
                "where": f"app {name} smoke",
                "message": "no smoke command configured; release preflight will use only a weak fallback",
            })
        if spec.get("smoke"):
            _doctor_warn_missing_executable(
                issues,
                where=f"app {name} smoke",
                command=str(spec.get("smoke") or ""),
                cwd=root_path,
                label="smoke command",
            )
        if mount.get("kind") == "proxy":
            cmd = str(mount.get("cmd") or "")
            port = mount.get("port")
            _doctor_warn_missing_executable(
                issues,
                where=f"app {name} proxy",
                command=cmd,
                cwd=root_path,
                label="proxy command",
            )
            if port is not None and "{port}" not in cmd and str(port) not in cmd:
                issues.append({
                    "severity": "warning",
                    "where": f"app {name} proxy",
                    "message": f"proxy command does not mention configured port {port}",
                })
            if _looks_like_hmr_dev_server(cmd):
                issues.append({
                    "severity": "warning",
                    "where": f"app {name} proxy",
                    "message": (
                        "proxy command looks like a framework dev server that may use WebSocket/HMR; "
                        "curIAtor's built-in proxy will show a diagnostic for upgrade requests, so use "
                        "commands.preview or a full reverse proxy when live HMR is required"
                    ),
                })
            _doctor_warn_proxy_base_path(issues, name=name, root=root_path, mount=mount)
        _doctor_warn_missing_manifests(
            issues,
            name=name,
            root=root_path,
            commands=[spec.get("smoke"), mount.get("cmd")],
        )
    return issues


def cmd_doctor(args) -> int:
    cfg = load_config()
    issues = _doctor_issues(cfg)
    errors = [i for i in issues if i.get("severity") == "error"]
    warnings = [i for i in issues if i.get("severity") == "warning"]
    if args.json:
        print(json.dumps({"ok": not errors, "errors": len(errors), "warnings": len(warnings), "issues": issues}, indent=2))
        return 1 if errors else 0
    if not issues:
        print("curiator: doctor OK — no portability/config issues found.")
        return 0
    print(f"curiator: doctor found {len(errors)} error(s), {len(warnings)} warning(s):")
    for issue in issues:
        print(f"  {issue['severity'].upper()} {issue['where']}: {issue['message']}")
    return 1 if errors else 0


def _smoke_specs(cfg: dict, app: str | None = None) -> list[dict]:
    specs = app_specs(cfg)
    if app:
        matches = [s for s in specs if app in {s.get("name"), s.get("app_name"), s.get("module")}]
        if not matches:
            raise SystemExit(f"curIAtor: unknown app {app!r}.")
        return matches
    return specs


def _smoke_work_specs(cfg: dict, app: str | None = None) -> list[dict]:
    specs = []
    seen: set[str] = set()
    for spec in _smoke_specs(cfg, app):
        name = str(spec.get("name") or spec.get("app_name") or spec.get("module"))
        if not name or name in seen:
            continue
        seen.add(name)
        specs.append(spec)
    return specs


def _smoke_result_metadata(cfg: dict, spec: dict) -> dict:
    return {
        "app": str(spec.get("name") or spec.get("app_name") or spec.get("module")),
        "smoke": spec.get("smoke"),
        "smoke_timeout": spec.get("smoke_timeout") or ((cfg.get("smoke") or {}).get("timeout")
                                                       if isinstance(cfg.get("smoke"), dict) else None),
        "root": _repo_path(cfg, spec.get("root")),
        "source": _repo_path(cfg, spec.get("source")),
    }


def _smoke_result_for_spec(cfg: dict, spec: dict) -> dict:
    from . import gitmem

    result = _smoke_result_metadata(cfg, spec)
    try:
        name = result["app"]
        ok, message = gitmem.smoke_app(cfg, name, spec.get("source"))
    except Exception as exc:  # noqa: BLE001
        ok, message = False, f"{type(exc).__name__}: {exc}"
    result.update({"ok": ok, "message": message})
    return result


def _smoke_results(cfg: dict, app: str | None = None, jobs: int = 1) -> list[dict]:
    specs = _smoke_work_specs(cfg, app)
    if jobs <= 1 or len(specs) <= 1:
        return [_smoke_result_for_spec(cfg, spec) for spec in specs]

    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[dict | None] = [None] * len(specs)
    with ThreadPoolExecutor(max_workers=min(jobs, len(specs))) as pool:
        futures = {
            pool.submit(_smoke_result_for_spec, cfg, spec): index
            for index, spec in enumerate(specs)
        }
        for future in as_completed(futures):
            index = futures[future]
            results[index] = future.result()
    return [result for result in results if result is not None]


def cmd_smoke(args) -> int:
    cfg = load_config()
    if args.jobs < 1:
        print("curiator: smoke --jobs must be >= 1")
        return 2
    results = _smoke_results(cfg, args.app, jobs=args.jobs)
    ok = all(r["ok"] for r in results)
    if args.json:
        print(json.dumps({"ok": ok, "results": results}, indent=2))
        return 0 if ok else 1
    for r in results:
        status = "OK" if r["ok"] else "FAIL"
        detail = f" — {r['message']}" if r.get("message") else ""
        command = f" [{r['smoke']}]" if r.get("smoke") else ""
        print(f"curiator: smoke {status} {r['app']}{command}{detail}")
    print(f"curiator: smoke {'OK' if ok else 'FAILED'} ({sum(1 for r in results if r['ok'])}/{len(results)} passed)")
    return 0 if ok else 1


_PUBLIC_RELEASE_GALLERIES = ("curiator-aviato", "curiator-ot", "curiator-geometry")


def _load_config_for_gallery(gallery: Path) -> dict:
    """Load exactly this gallery, insulated from a caller's linked-app cwd."""
    old_gallery = os.environ.get("CURIATOR_GALLERY")
    old_cwd = Path.cwd()
    os.environ["CURIATOR_GALLERY"] = str(gallery)
    try:
        os.chdir(gallery.parent)
        return load_config()
    finally:
        os.chdir(old_cwd)
        if old_gallery is None:
            os.environ.pop("CURIATOR_GALLERY", None)
        else:
            os.environ["CURIATOR_GALLERY"] = old_gallery


def _git_text(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def _tracked_files(repo: Path) -> list[str]:
    data = subprocess.run(["git", "ls-files", "-z"], cwd=repo, capture_output=True, text=True)
    if data.returncode != 0:
        return []
    return [p for p in data.stdout.split("\0") if p]


def _machine_path_hits(repo: Path, needles: tuple[str, ...]) -> list[dict]:
    hits: list[dict] = []
    for rel in _tracked_files(repo):
        path = repo / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            label = None
            for needle in needles:
                if needle and needle in line:
                    label = needle
                    break
            if label:
                hits.append({"file": rel, "line": line_no, "message": f"contains machine-local path {label}"})
            elif _USER_ABS_PATH_RE.search(line):
                hits.append({"file": rel, "line": line_no, "message": "contains a user-home absolute path"})
    return hits


_SAFE_ENV_TEMPLATE_NAMES = {".env.example", ".env.sample", ".env.template"}
_PUBLISH_RUNTIME_PREFIXES = ("feedback/shots/", "feedback/tasks/", "feedback/replies/")
_PUBLISH_SQLITE_SIDECARS = ("feedback/app_feedback.sqlite-wal", "feedback/app_feedback.sqlite-shm")


def _publish_artifact_message(rel: str) -> str | None:
    rel = rel.replace("\\", "/")
    name = rel.rsplit("/", 1)[-1]
    if rel == ".curiator-users.json":
        return "tracked local user store; do not publish hosted-login users or password hashes"
    if rel == "feedback/app_feedback.json":
        return "tracked legacy feedback JSON; SQLite is the feedback source of truth"
    if rel in _PUBLISH_SQLITE_SIDECARS:
        return "tracked SQLite sidecar; publish the committed ledger, not live WAL/SHM files"
    if any(rel.startswith(prefix) for prefix in _PUBLISH_RUNTIME_PREFIXES):
        return "tracked runtime feedback artifact; audit and publish intentionally outside release preflight"
    if name == ".env" or (name.startswith(".env.") and name not in _SAFE_ENV_TEMPLATE_NAMES):
        return "tracked environment file; keep secrets and local deployment settings out of public examples"
    return None


def _publish_artifact_hits(repo: Path) -> list[dict]:
    hits: list[dict] = []
    for rel in _tracked_files(repo):
        message = _publish_artifact_message(rel)
        if message:
            hits.append({"file": rel, "message": message})
    return hits


def _empty_preflight_result(name: str, gallery: Path) -> dict:
    return {
        "name": name,
        "path": str(gallery.parent),
        "gallery": str(gallery),
        "ok": False,
        "head": None,
        "dirty": [],
        "path_hits": [],
        "publish_artifact_hits": [],
        "doctor": {"ok": False, "errors": 0, "warnings": 0, "issues": []},
        "smoke": {"ok": None, "results": []},
    }


def _release_preflight_one(gallery: Path, *, run_smoke: bool, allow_dirty: bool, needles: tuple[str, ...]) -> dict:
    repo = gallery.parent
    result = _empty_preflight_result(repo.name, gallery)
    if not gallery.exists():
        result["error"] = f"missing gallery.yaml: {gallery}"
        return result
    if _git_output(repo, "rev-parse", "--is-inside-work-tree") != "true":
        result["error"] = f"not a git repository: {repo}"
        return result

    result["head"] = _git_output(repo, "rev-parse", "--short", "HEAD")
    dirty = _git_text(repo, "status", "--porcelain", "--untracked-files=all").splitlines()
    result["dirty"] = dirty
    result["path_hits"] = _machine_path_hits(repo, needles)
    result["publish_artifact_hits"] = _publish_artifact_hits(repo)

    try:
        cfg = _load_config_for_gallery(gallery)
        issues = _doctor_issues(cfg)
        errors = [i for i in issues if i.get("severity") == "error"]
        warnings = [i for i in issues if i.get("severity") == "warning"]
        result["doctor"] = {
            "ok": not errors,
            "errors": len(errors),
            "warnings": len(warnings),
            "issues": issues,
        }
        if run_smoke:
            smoke = _smoke_results(cfg)
            result["smoke"] = {"ok": all(r["ok"] for r in smoke), "results": smoke}
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"

    result["ok"] = (
        not result.get("error")
        and result["doctor"]["ok"]
        and not result["path_hits"]
        and not result["publish_artifact_hits"]
        and (allow_dirty or not dirty)
        and (not run_smoke or result["smoke"]["ok"] is True)
    )
    return result


def _clone_gallery(source: Path, clone_parent: Path) -> tuple[Path | None, str | None]:
    dest = clone_parent / source.name
    r = subprocess.run(
        ["git", "clone", "--quiet", "--no-local", str(source), str(dest)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None, (r.stderr or r.stdout or f"git clone exited {r.returncode}").strip()
    return dest / "gallery.yaml", None


def _release_preflight_source_result(source_gallery: Path, *, allow_dirty: bool) -> dict | None:
    source_repo = source_gallery.parent
    result = _empty_preflight_result(source_repo.name, source_gallery)
    if not source_gallery.exists():
        result["error"] = f"missing gallery.yaml: {source_gallery}"
        return result
    if _git_output(source_repo, "rev-parse", "--is-inside-work-tree") != "true":
        result["error"] = f"not a git repository: {source_repo}"
        return result
    result["head"] = _git_output(source_repo, "rev-parse", "--short", "HEAD")
    dirty = _git_text(source_repo, "status", "--porcelain", "--untracked-files=all").splitlines()
    result["dirty"] = dirty
    if dirty and not allow_dirty:
        result["error"] = "source repo is dirty; commit, stash, or pass --allow-dirty before fresh-clone preflight"
        return result
    return None


def _release_preflight_paths(args) -> tuple[Path, list[str], tuple[str, ...]]:
    project = _project_root()
    root_arg = Path(args.root).expanduser()
    root = root_arg if root_arg.is_absolute() else (project / root_arg).resolve()
    names = args.gallery or list(_PUBLIC_RELEASE_GALLERIES)
    needles = tuple(sorted({str(Path.home()), str(project)} | set(args.path_needle or [])))
    return root, names, needles


def _release_preflight_payload_for_root(args) -> dict:
    root, names, needles = _release_preflight_paths(args)
    galleries = [
        _release_preflight_one(
            (root / name / "gallery.yaml").resolve(),
            run_smoke=not args.no_smoke,
            allow_dirty=args.allow_dirty,
            needles=needles,
        )
        for name in names
    ]
    return {
        "ok": all(g["ok"] for g in galleries),
        "root": str(root),
        "galleries": galleries,
        "checks": {
            "smoke": not args.no_smoke,
            "allow_dirty": args.allow_dirty,
            "path_needles": list(needles),
        },
    }


def _release_preflight_payload_for_clones(args, clone_base: Path) -> dict:
    root, names, needles = _release_preflight_paths(args)
    clone_base.mkdir(parents=True, exist_ok=True)
    galleries = []
    for name in names:
        source_gallery = (root / name / "gallery.yaml").resolve()
        source_repo = source_gallery.parent
        source_error = _release_preflight_source_result(source_gallery, allow_dirty=args.allow_dirty)
        if source_error:
            source_error["mode"] = "fresh-clone"
            source_error["source_path"] = str(source_repo)
            galleries.append(source_error)
            continue
        clone_gallery, clone_error = _clone_gallery(source_repo, clone_base)
        if clone_error or clone_gallery is None:
            result = _empty_preflight_result(source_repo.name, source_gallery)
            result.update({
                "mode": "fresh-clone",
                "source_path": str(source_repo),
                "head": _git_output(source_repo, "rev-parse", "--short", "HEAD"),
                "error": clone_error or "clone failed",
            })
            galleries.append(result)
            continue
        result = _release_preflight_one(
            clone_gallery.resolve(),
            run_smoke=not args.no_smoke,
            allow_dirty=False,
            needles=needles,
        )
        result.update({
            "mode": "fresh-clone",
            "source_path": str(source_repo),
            "source_head": _git_output(source_repo, "rev-parse", "--short", "HEAD"),
            "cloned_from": str(source_repo),
        })
        galleries.append(result)
    return {
        "ok": all(g["ok"] for g in galleries),
        "root": str(root),
        "clone_root": str(clone_base),
        "galleries": galleries,
        "checks": {
            "smoke": not args.no_smoke,
            "allow_dirty": args.allow_dirty,
            "fresh_clone": True,
            "path_needles": list(needles),
        },
    }


def _release_preflight_payload(args) -> dict:
    if not args.fresh_clone:
        payload = _release_preflight_payload_for_root(args)
        payload["checks"]["fresh_clone"] = False
        return payload

    cleanup = not args.keep_clones
    if args.clone_root:
        clone_parent = Path(args.clone_root).expanduser()
        clone_parent = clone_parent if clone_parent.is_absolute() else (_project_root() / clone_parent).resolve()
        clone_parent.mkdir(parents=True, exist_ok=True)
        clone_base = Path(tempfile.mkdtemp(prefix="run-", dir=clone_parent))
    else:
        clone_base = Path(tempfile.mkdtemp(prefix="curiator-release-preflight-"))
    try:
        return _release_preflight_payload_for_clones(args, clone_base)
    finally:
        if cleanup:
            shutil.rmtree(clone_base, ignore_errors=True)


def cmd_release_preflight(args) -> int:
    payload = _release_preflight_payload(args)
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1

    passed = sum(1 for g in payload["galleries"] if g["ok"])
    total = len(payload["galleries"])
    mode = "fresh-clone" if payload.get("checks", {}).get("fresh_clone") else "nested"
    print(f"curiator: release preflight {'OK' if payload['ok'] else 'FAILED'} [{mode}] ({passed}/{total} galleries)")
    if payload.get("clone_root") and args.keep_clones:
        print(f"  clone root: {payload['clone_root']}")
    for g in payload["galleries"]:
        status = "OK" if g["ok"] else "FAIL"
        smoke = g.get("smoke") or {}
        smoke_results = smoke.get("results") or []
        smoke_label = "skipped" if smoke.get("ok") is None else f"{sum(1 for r in smoke_results if r['ok'])}/{len(smoke_results)}"
        print(
            f"  {status} {g['name']} {g.get('head') or '-'} "
            f"doctor={g['doctor']['errors']}e/{g['doctor']['warnings']}w "
            f"smoke={smoke_label} dirty={len(g['dirty'])} paths={len(g['path_hits'])} "
            f"artifacts={len(g.get('publish_artifact_hits') or [])}"
        )
        if g.get("error"):
            print(f"    error: {g['error']}")
        for issue in g["doctor"]["issues"]:
            print(f"    doctor {issue['severity'].upper()} {issue['where']}: {issue['message']}")
        for hit in g["path_hits"]:
            print(f"    path {hit['file']}:{hit['line']}: {hit['message']}")
        for hit in g.get("publish_artifact_hits") or []:
            print(f"    artifact {hit['file']}: {hit['message']}")
        for line in g["dirty"][:8]:
            print(f"    dirty {line}")
        if len(g["dirty"]) > 8:
            print(f"    dirty ... {len(g['dirty']) - 8} more")
        for r in smoke_results:
            if not r["ok"]:
                print(f"    smoke FAIL {r['app']}: {r['message']}")
    return 0 if payload["ok"] else 1


def cmd_context(args) -> int:
    cfg = load_config()
    app = _resolve_app(cfg, args.app)
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


def _command_markdown() -> str:
    return """---
name: curiator
description: Use when working in a repo linked to a curIAtor gallery, handling curIAtor feedback IDs, opening task bundles, posting replies, or finishing app changes through curIAtor's ledger, reload, and git-as-memory workflow.
---

# curIAtor

You are working inside a repo or directory linked to a curIAtor gallery.

Use the `curiator` CLI as the source of truth:
- `curiator status` shows the linked gallery/app and git-as-memory state.
- `curiator context` prints source scope, smoke test, recent feedback, and ready commands.
- `curiator work [feedback_id]` prints the exact task bundle a headless curator would receive and marks the item `working`.
- After edits and smoke tests, use `curiator done <feedback_id> "<summary>"`.
- For proposals, use `curiator reply <app> <feedback_id> "<plan>" --status awaiting_approval`.
- Do not edit `feedback/app_feedback.sqlite` directly.
- Do not run git commit/push/rewrite commands for curator work; `curiator done`/`reply --status done` handles git-as-memory.

When the user invokes this shim:
1. If they provide no arguments, run `curiator status` and `curiator context`.
2. If they provide `work` or a feedback id, run `curiator work ...`, read the printed task bundle, and follow it.
3. If they provide `done`, help formulate and run the appropriate `curiator done ...` command after verifying the change.
"""


def _legacy_command_markdown() -> str:
    return _command_markdown().replace(
        "When the user invokes this shim:",
        "When the user invokes this command:",
    )


def _prune_empty_dirs(path: Path, stop: Path) -> None:
    while path != stop and path.exists():
        try:
            path.rmdir()
        except OSError:
            return
        path = path.parent


def _install_command_files(root: Path) -> list[Path]:
    paths = [
        root / ".claude" / "commands" / "curiator.md",
        root / ".agents" / "skills" / "curiator" / "SKILL.md",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_command_markdown())
    return paths


def _cleanup_legacy_codex_skill(root: Path) -> tuple[Path, str] | None:
    legacy = root / ".codex" / "skills" / "curiator" / "SKILL.md"
    if not legacy.exists():
        return None
    generated = {_command_markdown(), _legacy_command_markdown()}
    try:
        text = legacy.read_text()
    except OSError:
        return legacy, "kept"
    if text not in generated:
        return legacy, "kept"
    legacy.unlink()
    _prune_empty_dirs(legacy.parent, root / ".codex")
    _prune_empty_dirs(root / ".codex", root)
    return legacy, "removed"


def cmd_commands(args) -> int:
    root = Path(args.root).expanduser().resolve() if args.root else _project_root()
    paths = _install_command_files(root)
    legacy = _cleanup_legacy_codex_skill(root)
    print(f"curiator: installed interactive command shims in {root}")
    for path in paths:
        print(f"  + {path.relative_to(root)}")
    if legacy:
        legacy_path, action = legacy
        if action == "removed":
            print(f"  - {legacy_path.relative_to(root)} (legacy Codex skill path)")
        else:
            print(f"  ! kept customized legacy file: {legacy_path.relative_to(root)}")
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


def _playground_issue(severity: str, where: str, message: str) -> dict:
    return {"severity": severity, "where": where, "message": message}


def _playground_int_value(raw) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _playground_user_summary(cfg: dict) -> dict:
    from . import auth

    auth_cfg = cfg.get("auth") or {}
    users: dict = {}
    if auth_cfg.get("mode") == "local":
        users.update(auth.load_users_file(auth_cfg.get("users_file")))
        for user in auth_cfg.get("users") or []:
            email = user.get("email")
            if email:
                users[email] = user
    admin_groups = set(auth_cfg.get("admin_groups") or ["admin"])
    active = [u for u in users.values() if not u.get("disabled")]
    return {
        "users_file": auth_cfg.get("users_file"),
        "total": len(users),
        "active": len(active),
        "disabled": sum(1 for u in users.values() if u.get("disabled")),
        "admins": sum(1 for u in active if set(u.get("groups") or []) & admin_groups),
    }


def _playground_preflight_issues(cfg: dict, user_summary: dict) -> list[dict]:
    issues: list[dict] = []
    runner = cfg.get("runner") or {}
    git = cfg.get("git") or {}
    auth_cfg = cfg.get("auth") or {}
    agent = cfg.get("agent") or {}
    dispatch = agent.get("dispatch") or {}
    quotas = agent.get("quotas") or {}

    if runner.get("mode") != "pinned":
        issues.append(_playground_issue(
            "error",
            "runner.mode",
            "hosted playgrounds should run the released runner with runner.mode: pinned",
        ))
    if not git.get("commit"):
        issues.append(_playground_issue(
            "error",
            "git.commit",
            "hosted playgrounds need git.commit: true so every agent run has a revert handle",
        ))

    auth_mode = auth_cfg.get("mode", "none")
    if auth_mode not in {"local", "header", "oidc"}:
        issues.append(_playground_issue(
            "error",
            "auth.mode",
            "hosted playgrounds must require sign-in with auth.mode: local, header, or oidc",
        ))
    if auth_mode == "local":
        if user_summary["active"] == 0:
            issues.append(_playground_issue(
                "error",
                "auth.users",
                "local-auth playgrounds need at least one active invited user",
            ))
        if user_summary["admins"] == 0:
            issues.append(_playground_issue(
                "error",
                "auth.admin_groups",
                "local-auth playgrounds need at least one active user in auth.admin_groups",
            ))

    if auth_cfg.get("allow_anonymous"):
        if auth_mode not in {"local", "oidc"}:
            issues.append(_playground_issue(
                "error",
                "auth.allow_anonymous",
                "anonymous held feedback is only supported with auth.mode: local or oidc",
            ))
        if dispatch.get("anonymous") != "hold":
            issues.append(_playground_issue(
                "error",
                "agent.dispatch.anonymous",
                "anonymous public feedback must be explicitly held with agent.dispatch.anonymous: hold",
            ))
        maxn = _playground_int_value(auth_cfg.get("anonymous_feedback_max"))
        window = _playground_int_value(auth_cfg.get("anonymous_feedback_window_seconds"))
        if maxn is None or maxn <= 0 or window is None or window <= 0:
            issues.append(_playground_issue(
                "error",
                "auth.anonymous_feedback_max",
                "anonymous feedback rate limits must stay enabled for public intake",
            ))

    if agent.get("autonomy") != "propose-only":
        issues.append(_playground_issue(
            "warning",
            "agent.autonomy",
            "first hosted pilots should prefer agent.autonomy: propose-only unless the collection is intentionally low-risk",
        ))
    if _playground_int_value(quotas.get("per_user_daily")) is None:
        issues.append(_playground_issue(
            "warning",
            "agent.quotas.per_user_daily",
            "set a per-user daily dispatch quota before widening the invite list",
        ))
    if _playground_int_value(quotas.get("global_daily")) is None:
        issues.append(_playground_issue(
            "warning",
            "agent.quotas.global_daily",
            "set a global daily dispatch quota as the hosted cost ceiling",
        ))
    if not dispatch.get("trusted_groups"):
        issues.append(_playground_issue(
            "warning",
            "agent.dispatch.trusted_groups",
            "declare trusted_groups explicitly if any accounts should bypass per-user quotas",
        ))
    return issues


def _playground_preflight_payload(args) -> dict:
    cfg = load_config()
    user_summary = _playground_user_summary(cfg)
    issues = _playground_preflight_issues(cfg, user_summary)
    doctor_issues = _doctor_issues(cfg)
    doctor_errors = [i for i in doctor_issues if i.get("severity") == "error"]
    doctor_warnings = [i for i in doctor_issues if i.get("severity") == "warning"]
    smoke = {"ok": None, "results": []}
    if not args.no_smoke:
        results = _smoke_results(cfg)
        smoke = {"ok": all(r["ok"] for r in results), "results": results}
    held = [_queue_row_payload(key, entry) for key, entry in _queue_entries(cfg)]
    errors = [i for i in issues if i.get("severity") == "error"]
    return {
        "ok": not errors and not doctor_errors and (args.no_smoke or smoke["ok"] is True),
        "gallery": cfg.get("gallery_path"),
        "auth": {
            "mode": (cfg.get("auth") or {}).get("mode"),
            "allow_anonymous": bool((cfg.get("auth") or {}).get("allow_anonymous")),
            "admin_groups": (cfg.get("auth") or {}).get("admin_groups") or [],
        },
        "runner": {"mode": (cfg.get("runner") or {}).get("mode")},
        "git": {"commit": bool((cfg.get("git") or {}).get("commit"))},
        "agent": {
            "autonomy": (cfg.get("agent") or {}).get("autonomy"),
            "dispatch": (cfg.get("agent") or {}).get("dispatch") or {},
            "quotas": (cfg.get("agent") or {}).get("quotas") or {},
        },
        "user_store": user_summary,
        "held_queue": {"count": len(held), "rows": held},
        "issues": issues,
        "doctor": {
            "ok": not doctor_errors,
            "errors": len(doctor_errors),
            "warnings": len(doctor_warnings),
            "issues": doctor_issues,
        },
        "smoke": smoke,
    }


def cmd_playground_preflight(args) -> int:
    """Check one collection's hosted public-playground posture before an invite-only pilot."""
    payload = _playground_preflight_payload(args)
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1

    status = "OK" if payload["ok"] else "FAILED"
    smoke = payload["smoke"]
    smoke_results = smoke.get("results") or []
    smoke_label = "skipped" if smoke.get("ok") is None else f"{sum(1 for r in smoke_results if r['ok'])}/{len(smoke_results)}"
    print(f"curiator: playground preflight {status}")
    print(
        f"  auth={payload['auth']['mode']} anonymous={payload['auth']['allow_anonymous']} "
        f"runner={payload['runner']['mode']} git.commit={payload['git']['commit']} "
        f"held={payload['held_queue']['count']}"
    )
    print(
        f"  doctor={payload['doctor']['errors']}e/{payload['doctor']['warnings']}w "
        f"smoke={smoke_label} users={payload['user_store']['active']} active/"
        f"{payload['user_store']['admins']} admin"
    )
    for issue in payload["issues"]:
        print(f"  {issue['severity'].upper()} {issue['where']}: {issue['message']}")
    for issue in payload["doctor"]["issues"]:
        print(f"  doctor {issue['severity'].upper()} {issue['where']}: {issue['message']}")
    for r in smoke_results:
        if not r["ok"]:
            print(f"  smoke FAIL {r['app']}: {r['message']}")
    return 0 if payload["ok"] else 1


def _fmt_seconds(seconds) -> str:
    if seconds is None:
        return "n/a"
    seconds = int(round(float(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s" if sec else f"{minutes}m"
    hours, minute = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {minute}m" if minute else f"{hours}h"
    days, hour = divmod(hours, 24)
    return f"{days}d {hour}h" if hour else f"{days}d"


def _fmt_counts(counts: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"


def _fmt_optional_int(value) -> str:
    return "n/a" if value is None else str(value)


def cmd_stats(args) -> int:
    """Emit reproducible collection metrics for release notes and case studies."""
    from . import stats as stats_mod

    if args.mode == "compare":
        if args.app:
            print("curiator: `stats compare` cannot be combined with --app")
            return 2
        if not args.galleries:
            print("curiator: `stats compare` needs at least one gallery path")
            return 2
        configs = [load_config_at(gallery) for gallery in args.galleries]
        report = stats_mod.compare(configs, include_git=not args.no_git)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        if args.markdown:
            print(stats_mod.format_compare_markdown(report), end="")
            return 0
        if args.csv:
            print(stats_mod.format_compare_csv(report), end="")
            return 0
        totals = report["totals"]
        print("curIAtor stats compare")
        print(
            "  totals: "
            f"{totals['collections']} collections, {totals['cycles']} cycles, "
            f"{totals['replied_cycles']} replied ({totals['reply_rate_percent']}%), "
            f"{totals['curator_commits']} curator commits"
        )
        for row in report["collections"]:
            print(
                f"  {row['collection']}: {row['cycles']} cycles, {row['open_cycles']} open, "
                f"{row['replied_cycles']} replied ({row['reply_rate_percent']}%), "
                f"median reply {_fmt_seconds(row['median_reply_seconds'])}, "
                f"curator commits {_fmt_optional_int(row['curator_commits'])}"
            )
        return 0

    cfg = load_config()
    summary = stats_mod.summarize(cfg, app=args.app, include_git=not args.no_git)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    if args.markdown:
        print(stats_mod.format_markdown(summary), end="")
        return 0
    if args.csv:
        print(stats_mod.format_csv(summary), end="")
        return 0

    totals = summary["totals"]
    latency = summary["reply_latency"]
    print("curIAtor stats")
    print(f"  gallery: {summary['gallery']}")
    print(f"  ledger:  {summary['ledger']}")
    print(f"  apps:    {summary['apps_with_feedback']} with feedback")
    print(
        "  cycles:  "
        f"{totals['cycles']} feedback items, {totals['open_cycles']} open, "
        f"{totals['replied_cycles']} replied ({totals['reply_rate_percent']}%)"
    )
    print(f"  notes:   {totals['agent_notes']} agent notes")
    print(f"  media:   {totals['screenshots']} screenshots, {totals['rated_cycles']} rated")
    print(
        "  latency: "
        f"median={_fmt_seconds(latency['median_seconds'])}, "
        f"avg={_fmt_seconds(latency['avg_seconds'])}, n={latency['count']}"
    )
    print(f"  status:  {_fmt_counts(summary['status_counts'])}")
    if "git" in summary:
        git = summary["git"]
        if git.get("available"):
            latest = git.get("latest") or {}
            suffix = f", latest={latest.get('sha')} {latest.get('subject')}" if latest else ""
            print(
                "  git:     "
                f"{git['curator_commits']} curator commits, {git['revert_commits']} reverts, "
                f"{git['feedback_ids']} feedback ids{suffix}"
            )
        else:
            print(f"  git:     unavailable ({git.get('reason')})")
    print("")
    print("per app:")
    for row in summary["apps"]:
        if not row["entries"]:
            continue
        lat = row["reply_latency"]
        print(
            f"  {row['app']}: {row['cycles']} cycles, {row['open_cycles']} open, "
            f"{row['agent_notes']} notes, {row['replied_cycles']} replied, "
            f"median reply {_fmt_seconds(lat['median_seconds'])}, "
            f"status [{_fmt_counts(row['status_counts'])}]"
        )
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
            state = "disabled" if u.get("disabled") else "active"
            print(f"  {email}  ·  {u.get('name') or '—'}  ·  groups={u.get('groups') or []}  ·  {state}")
        return 0
    if not args.email:
        print(f"curiator: `user {args.action}` needs an <email>"); return 1
    if args.action in {"disable", "enable"}:
        existing = users.get(args.email)
        if not existing:
            print(f"curiator: no such user {args.email}"); return 1
        existing["disabled"] = args.action == "disable"
        users[args.email] = existing
        auth.save_users_file(users_file, users)
        print(f"curiator: {args.action}d {args.email}")
        return 0
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
        if existing.get("disabled"):
            rec["disabled"] = True
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

    git_status = None
    if args.git:
        if (dest / ".git").exists():
            git_status = "exists"
        else:
            result = subprocess.run(["git", "init", "-q"], cwd=dest, capture_output=True, text=True)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or f"git init exited {result.returncode}").strip()
                print(f"curiator: git init failed for {dest}: {detail}")
                return result.returncode or 1
            git_status = "created"

    print(f"curiator: scaffolded a collection in {dest}")
    for f in created:
        print(f"  + {f}")
    for f in skipped:
        print(f"  · {f} (exists — left as-is)")
    if git_status == "created":
        print("  + .git/ (initialized)")
    elif git_status == "exists":
        print("  · .git/ (exists — left as-is)")
    print(f"\nnext:\n  cd {dest}\n  pip install -r requirements.txt\n"
          f"  curiator up        # gallery (then `curiator watch` in a second terminal, or `curiator serve`)")
    return 0


_APP_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_TOP_LEVEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*:\s*(?:#.*)?$")


def _app_names(cfg: dict) -> set[str]:
    names: set[str] = set()
    for app in cfg.get("apps") or []:
        if app.get("name"):
            names.add(str(app["name"]))
        for mount in app.get("mounts") or []:
            name = mount.get("name") or (mount.get("mount") or {}).get("name")
            if name:
                names.add(str(name))
    return names


def _title_from_name(name: str) -> str:
    return name.replace("_", " ").strip().title() or name


def _tags_arg(raw: str | None, default: str) -> list[str]:
    tags = [t.strip() for t in (raw or "").split(",") if t.strip()]
    return tags or [default]


def _yaml_list(items: list[str]) -> str:
    return "[" + ", ".join(json.dumps(str(item)) for item in items) + "]"


def _next_proxy_port(cfg: dict, start: int = 8700) -> int:
    ports: set[int] = set()
    for app in cfg.get("apps") or []:
        if app.get("port"):
            ports.add(int(app["port"]))
        mount = app.get("mount") or {}
        if mount.get("port"):
            ports.add(int(mount["port"]))
        for child in app.get("mounts") or []:
            cmount = child.get("mount") or child
            if child.get("port"):
                ports.add(int(child["port"]))
            if cmount.get("port"):
                ports.add(int(cmount["port"]))
    port = start
    while port in ports:
        port += 1
    return port


_JS_PACKAGE_MANAGERS = ("npm", "pnpm", "yarn", "bun")


def _detect_package_manager(repo: Path) -> str:
    for lockfile, manager in (
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"),
        ("bun.lock", "bun"),
        ("package-lock.json", "npm"),
        ("npm-shrinkwrap.json", "npm"),
    ):
        if (repo / lockfile).exists():
            return manager
    return "npm"


def _resolve_package_manager(repo: Path, requested: str | None) -> str:
    if not requested or requested == "auto":
        return _detect_package_manager(repo)
    return requested


def _looks_like_git_source(source: str) -> bool:
    return bool(
        re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", source)
        or source.startswith("git@")
        or re.match(r"^[^@\s]+@[^:\s]+:.+", source)
        or source.endswith(".git")
    )


def _copy_or_clone_app_source(source_arg: str, dest: Path) -> tuple[str, Path | str]:
    source = Path(source_arg).expanduser()
    if source.exists():
        source = source.resolve()
        if not source.is_dir():
            raise ValueError(f"source is not a directory: {source}")
        if source == dest.resolve() or _is_relative_to(dest.resolve(), source):
            raise ValueError(f"refusing to import into a destination inside the source: {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, dest)
        return "copied", source

    if not _looks_like_git_source(source_arg):
        raise ValueError(f"source directory not found: {source_arg}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["git", "clone", "--quiet", source_arg, str(dest)], capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"git clone exited {result.returncode}").strip()
        raise ValueError(f"git clone failed for {source_arg}: {detail}")
    return "cloned", source_arg


def _js_run_command(manager: str, script: str, args: str = "") -> str:
    if not args:
        return f"{manager} run {script}"
    if manager in {"npm", "pnpm", "bun"}:
        return f"{manager} run {script} -- {args}"
    return f"yarn run {script} {args}"


def _rust_string(value: str) -> str:
    text = str(value)
    return '"' + (
        text
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    ) + '"'


def _append_app_entry(text: str, entry: str) -> str:
    """Append an app item under the top-level `apps:` block while preserving the rest of gallery.yaml."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^apps:\s*\[\s*\]\s*(?:#.*)?$", line):
            lines[i:i + 1] = ["apps:", *entry.rstrip().splitlines()]
            return "\n".join(lines) + "\n"
        if re.match(r"^apps:\s*(?:#.*)?$", line):
            j = i + 1
            while j < len(lines):
                if lines[j] and not lines[j].startswith((" ", "\t", "#")) and _TOP_LEVEL_RE.match(lines[j]):
                    break
                j += 1
            insert = entry.rstrip().splitlines()
            if j > i + 1 and lines[j - 1].strip():
                insert = ["", *insert]
            lines[j:j] = insert
            return "\n".join(lines) + "\n"
    prefix = ["apps:", *entry.rstrip().splitlines(), ""]
    return "\n".join(prefix + lines) + ("\n" if text.endswith("\n") else "")


def _gallery_entry(
    name: str,
    template: str,
    title: str,
    tags: list[str],
    port: int | None,
    package_manager: str = "npm",
) -> str:
    root = f"apps/{name}"
    if template == "dash":
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: python -m compileall -q .\n"
            f"    mount: {{ kind: dash-inproc, module: {name} }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "static":
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: python -m compileall -q .\n"
            f"    mount: {{ kind: proxy, cmd: \"python -m http.server {port} --bind 127.0.0.1\", port: {port} }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template in {"react", "svelte", "vue"}:
        smoke = _js_run_command(package_manager, "build")
        serve = _js_run_command(package_manager, "dev", f"--host 127.0.0.1 --port {port}")
        preview = _js_run_command(package_manager, "preview", f"--host 127.0.0.1 --port {port}")
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: {smoke}\n"
            f"    commands:\n"
            f"      preview: {json.dumps(preview)}\n"
            f"    mount: {{ kind: proxy, cmd: \"{serve}\", port: {port} }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "next":
        smoke = _js_run_command(package_manager, "build")
        serve = _js_run_command(package_manager, "dev", f"-H 127.0.0.1 -p {port}")
        preview = _js_run_command(package_manager, "start", f"-H 127.0.0.1 -p {port}")
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: {smoke}\n"
            f"    commands:\n"
            f"      preview: {json.dumps(preview)}\n"
            f"    mount: {{ kind: proxy, cmd: \"{serve}\", port: {port}, preserve_prefix: true }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "node":
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: node --check server.js\n"
            f"    commands:\n"
            f"      preview: {json.dumps(f'node server.js --port {port}')}\n"
            f"    mount: {{ kind: proxy, cmd: \"node server.js --port {port}\", port: {port} }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "flask":
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: python -m py_compile app.py\n"
            f"    commands:\n"
            f"      preview: {json.dumps(f'python app.py --port {port}')}\n"
            f"    mount: {{ kind: proxy, cmd: \"python app.py --port {port}\", port: {port} }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "fastapi":
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: python -m py_compile main.py\n"
            f"    commands:\n"
            f"      preview: {json.dumps(f'python main.py --port {port} --root-path /app/{name}')}\n"
            f"    mount: {{ kind: proxy, cmd: \"python main.py --port {port} --root-path /app/{{app}}\", "
            f"port: {port} }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "rust":
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: cargo check --quiet\n"
            f"    commands:\n"
            f"      preview: {json.dumps(f'cargo run --quiet -- --port {port}')}\n"
            f"    mount: {{ kind: proxy, cmd: \"cargo run --quiet -- --port {port}\", port: {port} }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "gradio":
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: python -m py_compile app.py\n"
            f"    mount: {{ kind: proxy, cmd: \"python app.py --port {port} --root-path /app/{{app}}\", "
            f"port: {port}, preserve_prefix: true }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "streamlit":
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: python -m py_compile app.py\n"
            f"    mount: {{ kind: proxy, cmd: \"streamlit run app.py --server.address 127.0.0.1 "
            f"--server.port {port} --server.headless true --server.baseUrlPath app/{{app}} "
            f"--browser.gatherUsageStats false\", port: {port}, preserve_prefix: true }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    return (
        f"  - name: {name}\n"
        f"    title: {json.dumps(title)}\n"
        f"    root: {root}\n"
        f"    source: .\n"
        f"    smoke: python -m py_compile server.py\n"
        f"    mount: {{ kind: proxy, cmd: \"python server.py\", port: {port} }}\n"
        f"    tags: {_yaml_list(tags)}\n"
    )


def _app_import_postcheck_issues(gallery: Path, name: str) -> list[dict]:
    """Doctor-style warnings for an imported app, scoped to issues import can reveal immediately."""
    try:
        spec = app_spec(load_config_at(gallery), name) or {}
    except SystemExit:
        return []
    root = Path(spec.get("root") or gallery.parent)
    mount = spec.get("mount") or {}
    issues: list[dict] = []
    if mount.get("kind") == "proxy":
        cmd = str(mount.get("cmd") or "")
        if _looks_like_hmr_dev_server(cmd):
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": (
                    "proxy command looks like a framework dev server that may use WebSocket/HMR; "
                    "curIAtor's built-in proxy will show a diagnostic for upgrade requests, so use "
                    "commands.preview or a full reverse proxy when live HMR is required"
                ),
            })
        _doctor_warn_proxy_base_path(issues, name=name, root=root, mount=mount)
    _doctor_warn_missing_manifests(
        issues,
        name=name,
        root=root,
        commands=[spec.get("smoke"), mount.get("cmd")],
    )
    return issues


def _app_template_files(name: str, template: str, title: str, package_manager: str = "npm") -> dict[str, str]:
    js_smoke = _js_run_command(package_manager, "build")
    if template == "dash":
        return {f"{name}.py": _APP_DASH_TEMPLATE.format(name=name, title=title)}
    if template == "static":
        return {"index.html": _APP_STATIC_TEMPLATE.format(name=name, title=title)}
    if template == "react":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title), js_smoke=js_smoke)
                for rel, content in _APP_REACT_TEMPLATE.items()}
    if template == "svelte":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title), js_smoke=js_smoke)
                for rel, content in _APP_SVELTE_TEMPLATE.items()}
    if template == "vue":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title), js_smoke=js_smoke)
                for rel, content in _APP_VUE_TEMPLATE.items()}
    if template == "next":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title), js_smoke=js_smoke)
                for rel, content in _APP_NEXT_TEMPLATE.items()}
    if template == "node":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title))
                for rel, content in _APP_NODE_TEMPLATE.items()}
    if template == "flask":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title))
                for rel, content in _APP_FLASK_TEMPLATE.items()}
    if template == "fastapi":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title))
                for rel, content in _APP_FASTAPI_TEMPLATE.items()}
    if template == "rust":
        return _app_rust_template_files(name, title)
    if template == "streamlit":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title))
                for rel, content in _APP_STREAMLIT_TEMPLATE.items()}
    if template == "gradio":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title))
                for rel, content in _APP_GRADIO_TEMPLATE.items()}
    return {"server.py": _APP_PYTHON_TEMPLATE.format(name=name, title=title)}


def cmd_app_create(args) -> int:
    """Create an app directory and register it in gallery.yaml."""
    cfg = load_config()
    name = args.name.strip()
    if not _APP_NAME_RE.match(name):
        print("curiator: app name must be a Python-safe identifier: letters, numbers, underscores; start with a letter")
        return 1
    if name in _app_names(cfg):
        print(f"curiator: app '{name}' already exists in gallery.yaml")
        return 1
    template = args.template
    repo = Path(cfg["repo_root"])
    root = repo / "apps" / name
    if root.exists() and not args.force:
        print(f"curiator: {root} already exists; pass --force to add missing scaffold files")
        return 1
    title = args.title or _title_from_name(name)
    tags = _tags_arg(args.tags, template)
    proxy_templates = {"static", "python", "node", "flask", "fastapi", "rust", "react", "svelte", "vue", "next", "streamlit", "gradio"}
    port = args.port if args.port is not None else (_next_proxy_port(cfg) if template in proxy_templates else None)
    package_manager = _resolve_package_manager(repo, args.package_manager) if template in {"react", "svelte", "vue", "next"} else "npm"

    created, skipped = [], []
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in _app_template_files(name, template, title, package_manager).items():
        p = root / rel
        if p.exists():
            skipped.append(str(p.relative_to(repo)))
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        created.append(str(p.relative_to(repo)))

    gallery = Path(cfg["gallery_path"])
    entry = _gallery_entry(name, template, title, tags, port, package_manager)
    gallery.write_text(_append_app_entry(gallery.read_text(), entry))
    created.append(str(gallery.relative_to(repo)))

    print(f"curiator: created {template} app '{name}' in {root.relative_to(repo)}")
    for f in created:
        print(f"  + {f}")
    for f in skipped:
        print(f"  · {f} (exists — left as-is)")
    print("next:")
    print(f"  curiator reload {name}   # if the shell is already running")
    print(f"  open /app/{name}/")
    return 0


def cmd_app_import(args) -> int:
    """Copy/clone an existing app repo or directory and register it in gallery.yaml."""
    cfg = load_config()
    name = args.name.strip()
    if not _APP_NAME_RE.match(name):
        print("curiator: app name must be a Python-safe identifier: letters, numbers, underscores; start with a letter")
        return 1
    if name in _app_names(cfg):
        print(f"curiator: app '{name}' already exists in gallery.yaml")
        return 1

    template = args.template
    repo = Path(cfg["repo_root"])
    root = repo / "apps" / name
    if root.exists():
        print(f"curiator: {root} already exists; choose a new app name or remove the existing directory")
        return 1

    title = args.title or _title_from_name(name)
    tags = _tags_arg(args.tags, template)
    proxy_templates = {"static", "python", "node", "flask", "fastapi", "rust", "react", "svelte", "vue", "next", "streamlit", "gradio"}
    port = args.port if args.port is not None else (_next_proxy_port(cfg) if template in proxy_templates else None)

    try:
        action, source = _copy_or_clone_app_source(args.source, root)
    except ValueError as exc:
        print(f"curiator: app import FAILED — {exc}")
        return 1

    package_manager = _resolve_package_manager(root, args.package_manager) if template in {"react", "svelte", "vue", "next"} else "npm"
    gallery = Path(cfg["gallery_path"])
    entry = _gallery_entry(name, template, title, tags, port, package_manager)
    gallery.write_text(_append_app_entry(gallery.read_text(), entry))

    print(f"curiator: {action} app source '{source}' into {root.relative_to(repo)}")
    print(f"  + {root.relative_to(repo)}/")
    print(f"  + {gallery.relative_to(repo)}")
    for issue in _app_import_postcheck_issues(gallery, name):
        print(f"  ! {issue['severity'].upper()} {issue['where']}: {issue['message']}")
    print("next:")
    print(f"  curiator reload {name}   # if the shell is already running")
    print(f"  open /app/{name}/")
    return 0


def _scaffold_files() -> dict[str, str]:
    return {
        "gallery.yaml": _SCAFFOLD_GALLERY,
        "apps/sample.py": _SCAFFOLD_SAMPLE_APP,
        "requirements.txt": _SCAFFOLD_REQUIREMENTS,
        "README.md": _SCAFFOLD_README,
        ".gitignore": _SCAFFOLD_GITIGNORE,
    }


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
    rp.add_argument("--path-needle", action="append",
                    help="extra machine-local path string to reject in tracked files")
    rp.add_argument("--allow-dirty", action="store_true", help="report dirty nested repos without failing")
    rp.add_argument("--fresh-clone", action="store_true", help="clone each gallery first and preflight the clone")
    rp.add_argument("--clone-root", help="directory for fresh-clone runs; a unique run-* directory is created inside")
    rp.add_argument("--keep-clones", action="store_true", help="do not delete fresh-clone run directories")
    rp.add_argument("--no-smoke", action="store_true", help="skip per-app smoke checks")
    rp.add_argument("--json", action="store_true", help="emit machine-readable diagnostics")
    rp.set_defaults(func=cmd_release_preflight)
    pp = sub.add_parser("playground-preflight", help="check hosted public-playground readiness")
    pp.add_argument("--no-smoke", action="store_true", help="skip per-app smoke checks")
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
    ac = app_sub.add_parser("create", help="scaffold an app directory and add it to gallery.yaml")
    ac.add_argument("name", help="app key, e.g. orange_picker")
    ac.add_argument("--template", choices=["dash", "static", "python", "node", "flask", "fastapi", "rust", "react", "svelte", "vue", "next", "streamlit", "gradio"], default="dash",
                    help="scaffold template (default: dash)")
    ac.add_argument("--title", help="display title")
    ac.add_argument("--tags", help="comma-separated tags; default is the template name")
    ac.add_argument("--port", type=int, help="proxy port for static/python/node/flask/fastapi/rust/react/svelte/vue/next/streamlit/gradio templates")
    ac.add_argument("--package-manager", choices=["auto", *_JS_PACKAGE_MANAGERS], default="auto",
                    help="JS package manager for react/svelte/vue/next templates (default: auto)")
    ac.add_argument("--force", action="store_true", help="allow an existing apps/<name> directory")
    ac.set_defaults(func=cmd_app_create)
    ai = app_sub.add_parser("import", help="copy/clone an existing app repo and add it to gallery.yaml")
    ai.add_argument("source", help="local app directory or git URL to copy/clone")
    ai.add_argument("name", help="app key, e.g. orange_picker")
    ai.add_argument("--template", choices=["dash", "static", "python", "node", "flask", "fastapi", "rust", "react", "svelte", "vue", "next", "streamlit", "gradio"], required=True,
                    help="mount template to register for the imported app")
    ai.add_argument("--title", help="display title")
    ai.add_argument("--tags", help="comma-separated tags; default is the template name")
    ai.add_argument("--port", type=int, help="proxy port for static/python/node/flask/fastapi/rust/react/svelte/vue/next/streamlit/gradio templates")
    ai.add_argument("--package-manager", choices=["auto", *_JS_PACKAGE_MANAGERS], default="auto",
                    help="JS package manager for react/svelte/vue/next templates (default: auto)")
    ai.set_defaults(func=cmd_app_import)
    ia = sub.add_parser("init-app", help="alias for `curiator app create`")
    ia.add_argument("name", help="app key, e.g. orange_picker")
    ia.add_argument("--template", choices=["dash", "static", "python", "node", "flask", "fastapi", "rust", "react", "svelte", "vue", "next", "streamlit", "gradio"], default="dash",
                    help="scaffold template (default: dash)")
    ia.add_argument("--title", help="display title")
    ia.add_argument("--tags", help="comma-separated tags; default is the template name")
    ia.add_argument("--port", type=int, help="proxy port for static/python/node/flask/fastapi/rust/react/svelte/vue/next/streamlit/gradio templates")
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
# curIAtor collection — your apps (apps/) + how the curator runs.
# Add one entry per app; the curator edits each app's `source` when you give feedback on it.

apps:
  - name: sample
    title: Sample app
    mount: { kind: dash-inproc, module: sample }   # import & mount in-process (Dash); or kind: proxy {cmd, port}
    source: apps/sample.py                          # what the curator edits
    tags: [demo]

  # App-directory shape: one folder can expose multiple endpoints that share the same source scope.
  # - name: lab_suite
  #   root: apps/lab_suite
  #   source: .
  #   smoke: python -m compileall -q .
  #   mounts:
  #     - name: overview
  #       mount: { kind: dash-inproc, module: overview, source: overview.py }
  #     - name: node_ssr
  #       mount: { kind: proxy, cmd: "npm start -- --port {port}", port: 8710 }

agent:
  adapter: headless-cc        # headless-cc (your Claude sub) | api (teams) | command (BYO)
  autonomy: auto-small        # auto-small (fix small things) | propose-only (plan first)

# How feedback on the RUNNER itself (the ◆ General channel) is handled:
runner:
  mode: pinned                # pinned (consumer): drafts an upstream issue/PR; never edits the package
  # mode: checkout            # contributor: patches the runner locally (set `path` to a curiator checkout)
  # path: ../curiator

feedback:
  dir: feedback               # SQLite ledger source of truth + shots/ live here
  screenshots: true

shell:
  port: 8300
"""

_SCAFFOLD_SAMPLE_APP = '''\
"""sample.py — a starter Dash app. Star/comment/screenshot it in the gallery and the curator edits THIS file.

Every curIAtor app exposes `build_app()` returning a `dash.Dash`, plus a module-level `app` so the
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
# My curIAtor collection

Apps live in `apps/`; `gallery.yaml` is the registry. curIAtor serves every app in one gallery and an
AI curator fixes them from in-browser feedback (star / comment / screenshot).

## Run

    pip install -r requirements.txt
    curiator up        # gallery at http://127.0.0.1:8300
    curiator watch     # (second terminal) arm the feedback→fix loop
    # …or both at once:  curiator serve

Open the gallery, star/comment/screenshot an app, and watch the curator reply in the panel.

## Add an app

Use the scaffold command; it creates `apps/<name>/` and updates `gallery.yaml`:

    curiator app create revenue --template dash --title "Revenue dashboard"

Templates: `dash`, `static`, `python`, `node`, `flask`, `fastapi`, `rust`, `react`, `svelte`, `vue`, `next`, `streamlit`, `gradio`.
Node, Flask, FastAPI, and Rust use lightweight server scaffolds behind same-origin proxy mounts.
React/Svelte/Vue use Vite; React/Svelte/Vue/Next can auto-detect npm/pnpm/yarn/bun. Next, Streamlit, and Gradio use prefix-preserving proxy mounts.
You can still edit `gallery.yaml` manually for existing apps.

See the consumer guide: https://github.com/LearnedResponse/curiator/blob/main/docs/USING_CURIATOR.md
"""

_SCAFFOLD_GITIGNORE = """\
feedback/shots/
feedback/tasks/
feedback/replies/
feedback/app_feedback.sqlite*
feedback/app_feedback.json
.curiator-users.json
__pycache__/
*.pyc
"""

_APP_DASH_TEMPLATE = '''\
"""Dash app scaffold generated by `curiator app create {name}`."""
from __future__ import annotations

import dash
from dash import dcc, html
import plotly.graph_objects as go


def build_app() -> dash.Dash:
    app = dash.Dash(__name__)
    app.title = "{title}"

    fig = go.Figure(
        go.Bar(
            x=["alpha", "beta", "gamma", "delta"],
            y=[12, 19, 8, 15],
            marker_color="#8e44ad",
        )
    )
    fig.update_layout(
        margin=dict(l=48, r=20, t=28, b=42),
        plot_bgcolor="white",
        paper_bgcolor="white",
        height=360,
        xaxis_title="category",
        yaxis_title="value",
    )

    app.layout = html.Div(
        style={{"fontFamily": "system-ui, sans-serif", "padding": "24px", "maxWidth": "860px"}},
        children=[
            html.H2("{title}", style={{"margin": "0 0 8px", "color": "#333"}}),
            html.P(
                "This app was scaffolded by curIAtor. Use feedback in the right rail to shape it.",
                style={{"color": "#666", "margin": "0 0 18px"}},
            ),
            dcc.Graph(figure=fig, config={{"displayModeBar": False}}),
        ],
    )
    return app


app = build_app()


if __name__ == "__main__":
    app.run(debug=False, port=8050)
'''

_APP_STATIC_TEMPLATE = """\
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
      body {{
        margin: 0;
        font-family: system-ui, sans-serif;
        color: #2f3337;
        background: #f7f7f5;
      }}
      main {{
        max-width: 860px;
        padding: 32px;
      }}
      h1 {{
        margin: 0 0 8px;
        color: #8e44ad;
      }}
      p {{
        color: #5f666d;
        line-height: 1.5;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>{title}</h1>
      <p>This static app was scaffolded by curIAtor. Use feedback in the right rail to shape it.</p>
    </main>
  </body>
</html>
"""

_APP_REACT_TEMPLATE = {
    "package.json": """\
{{
  "name": "{name}",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {{
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  }},
  "dependencies": {{
    "@vitejs/plugin-react": "^4.3.0",
    "vite": "^5.4.0",
    "typescript": "^5.5.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  }},
  "devDependencies": {{}}
}}
""",
    "index.html": """\
<!doctype html>
<html>
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
""",
    "vite.config.js": """\
import {{ defineConfig }} from "vite";
import react from "@vitejs/plugin-react";

const app = process.env.CURIATOR_APP || "";
const base = app ? `/app/${{app}}/` : "/";

export default defineConfig({{
  base,
  plugins: [react()],
  server: {{
    host: "127.0.0.1",
  }},
}});
""",
    "src/main.jsx": """\
import React from "react";
import {{ createRoot }} from "react-dom/client";
import App from "./App.jsx";
import "./style.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
""",
    "src/App.jsx": """\
export default function App() {{
  const title = {title_json};
  return (
    <main className="surface">
      <p className="eyebrow">curIAtor React scaffold</p>
      <h1>{{title}}</h1>
      <p>
        This React app is served through a same-origin proxy mount. Use the feedback rail to shape the
        interface; the curator edits files in this directory and smoke-tests with <code>{js_smoke}</code>.
      </p>
      <section className="metricGrid" aria-label="demo metrics">
        <div><b>4</b><span>signals</span></div>
        <div><b>12m</b><span>review window</span></div>
        <div><b>98%</b><span>uptime</span></div>
      </section>
    </main>
  );
}}
""",
    "src/style.css": """\
:root {{
  color: #22272e;
  background: #f6f7f8;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}

body {{
  margin: 0;
}}

.surface {{
  max-width: 880px;
  padding: 32px;
}}

.eyebrow {{
  margin: 0 0 8px;
  color: #8e44ad;
  font-size: 13px;
  font-weight: 700;
}}

h1 {{
  margin: 0 0 12px;
  font-size: 32px;
}}

p {{
  color: #5e6670;
  line-height: 1.55;
}}

.metricGrid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(120px, 1fr));
  gap: 12px;
  margin-top: 24px;
  max-width: 620px;
}}

.metricGrid div {{
  border: 1px solid #d9dde2;
  border-radius: 8px;
  background: white;
  padding: 14px;
}}

.metricGrid b {{
  display: block;
  font-size: 24px;
}}

.metricGrid span {{
  color: #6c747d;
  font-size: 13px;
}}
""",
}

_APP_SVELTE_TEMPLATE = {
    "package.json": """\
{{
  "name": "{name}",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {{
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  }},
  "dependencies": {{
    "@sveltejs/vite-plugin-svelte": "^3.1.0",
    "vite": "^5.4.0",
    "svelte": "^4.2.0"
  }},
  "devDependencies": {{}}
}}
""",
    "index.html": """\
<!doctype html>
<html>
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
""",
    "vite.config.js": """\
import {{ defineConfig }} from "vite";
import {{ svelte }} from "@sveltejs/vite-plugin-svelte";

const app = process.env.CURIATOR_APP || "";
const base = app ? `/app/${{app}}/` : "/";

export default defineConfig({{
  base,
  plugins: [svelte()],
  server: {{
    host: "127.0.0.1",
  }},
}});
""",
    "src/main.js": """\
import App from "./App.svelte";

const app = new App({{
  target: document.getElementById("app"),
}});

export default app;
""",
    "src/App.svelte": """\
<script>
  const title = {title_json};
  const metrics = [
    ["3", "states"],
    ["18m", "iteration"],
    ["7", "notes"],
  ];
</script>

<main class="surface">
  <p class="eyebrow">curIAtor Svelte scaffold</p>
  <h1>{{title}}</h1>
  <p>
    This Svelte app is served through a same-origin proxy mount. Use the feedback rail to shape the
    interface; the curator edits files in this directory and smoke-tests with <code>{js_smoke}</code>.
  </p>
  <section class="metricGrid" aria-label="demo metrics">
    {{#each metrics as metric}}
      <div><b>{{metric[0]}}</b><span>{{metric[1]}}</span></div>
    {{/each}}
  </section>
</main>

<style>
  :global(body) {{
    margin: 0;
    color: #22272e;
    background: #f6f7f8;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }}

  .surface {{
    max-width: 880px;
    padding: 32px;
  }}

  .eyebrow {{
    margin: 0 0 8px;
    color: #8e44ad;
    font-size: 13px;
    font-weight: 700;
  }}

  h1 {{
    margin: 0 0 12px;
    font-size: 32px;
  }}

  p {{
    color: #5e6670;
    line-height: 1.55;
  }}

  .metricGrid {{
    display: grid;
    grid-template-columns: repeat(3, minmax(120px, 1fr));
    gap: 12px;
    margin-top: 24px;
    max-width: 620px;
  }}

  .metricGrid div {{
    border: 1px solid #d9dde2;
    border-radius: 8px;
    background: white;
    padding: 14px;
  }}

  .metricGrid b {{
    display: block;
    font-size: 24px;
  }}

  .metricGrid span {{
    color: #6c747d;
    font-size: 13px;
  }}
</style>
""",
}

_APP_VUE_TEMPLATE = {
    "package.json": """\
{{
  "name": "{name}",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {{
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  }},
  "dependencies": {{
    "@vitejs/plugin-vue": "^5.1.0",
    "vite": "^5.4.0",
    "vue": "^3.5.0"
  }},
  "devDependencies": {{}}
}}
""",
    "index.html": """\
<!doctype html>
<html>
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
""",
    "vite.config.js": """\
import {{ defineConfig }} from "vite";
import vue from "@vitejs/plugin-vue";

const app = process.env.CURIATOR_APP || "";
const base = app ? `/app/${{app}}/` : "/";

export default defineConfig({{
  base,
  plugins: [vue()],
  server: {{
    host: "127.0.0.1",
  }},
}});
""",
    "src/main.js": """\
import {{ createApp }} from "vue";
import App from "./App.vue";
import "./style.css";

createApp(App).mount("#app");
""",
    "src/App.vue": """\
<script setup>
const title = {title_json};
const metrics = [
  ["5", "views"],
  ["9m", "review"],
  ["14", "signals"],
];
</script>

<template>
  <main class="surface">
    <p class="eyebrow">curIAtor Vue scaffold</p>
    <h1>{{{{ title }}}}</h1>
    <p>
      This Vue app is served through a same-origin proxy mount. Use the feedback rail to shape the
      interface; the curator edits files in this directory and smoke-tests with <code>{js_smoke}</code>.
    </p>
    <section class="metricGrid" aria-label="demo metrics">
      <div v-for="metric in metrics" :key="metric[1]">
        <b>{{{{ metric[0] }}}}</b><span>{{{{ metric[1] }}}}</span>
      </div>
    </section>
  </main>
</template>
""",
    "src/style.css": """\
:root {{
  color: #22272e;
  background: #f6f7f8;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}

body {{
  margin: 0;
}}

.surface {{
  max-width: 880px;
  padding: 32px;
}}

.eyebrow {{
  margin: 0 0 8px;
  color: #8e44ad;
  font-size: 13px;
  font-weight: 700;
}}

h1 {{
  margin: 0 0 12px;
  font-size: 32px;
}}

p {{
  color: #5e6670;
  line-height: 1.55;
}}

.metricGrid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(120px, 1fr));
  gap: 12px;
  margin-top: 24px;
  max-width: 620px;
}}

.metricGrid div {{
  border: 1px solid #d9dde2;
  border-radius: 8px;
  background: white;
  padding: 14px;
}}

.metricGrid b {{
  display: block;
  font-size: 24px;
}}

.metricGrid span {{
  color: #6c747d;
  font-size: 13px;
}}
""",
}

_APP_NEXT_TEMPLATE = {
    "package.json": """\
{{
  "name": "{name}",
  "private": true,
  "version": "0.0.0",
  "scripts": {{
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  }},
  "dependencies": {{
    "next": "^14.2.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  }},
  "devDependencies": {{}}
}}
""",
    "next.config.mjs": """\
const app = process.env.CURIATOR_APP || "";
const basePath = app ? `/app/${{app}}` : "";

/** @type {{import("next").NextConfig}} */
const nextConfig = {{
  basePath,
}};

export default nextConfig;
""",
    "app/layout.jsx": """\
import "./globals.css";

export const metadata = {{
  title: {title_json},
}};

export default function RootLayout({{ children }}) {{
  return (
    <html lang="en">
      <body>{{children}}</body>
    </html>
  );
}}
""",
    "app/page.jsx": """\
const title = {title_json};

async function loadStatus() {{
  return {{
    routes: ["/", "/api/status"],
    mode: "server component",
    feedback: "ready",
  }};
}}

export default async function Page() {{
  const status = await loadStatus();
  return (
    <main className="surface">
      <p className="eyebrow">curIAtor Next.js scaffold</p>
      <h1>{{title}}</h1>
      <p>
        This Next.js app is served through a prefix-preserving same-origin proxy mount. Use the feedback
        rail to shape the server-rendered view; the curator edits files in this directory and
        smoke-tests with <code>{js_smoke}</code>.
      </p>
      <section className="metricGrid" aria-label="demo metrics">
        <div><b>{{status.routes.length}}</b><span>routes</span></div>
        <div><b>RSC</b><span>{{status.mode}}</span></div>
        <div><b>OK</b><span>{{status.feedback}}</span></div>
      </section>
    </main>
  );
}}
""",
    "app/api/status/route.js": """\
export function GET() {{
  return Response.json({{
    ok: true,
    app: "{name}",
    runtime: "next",
  }});
}}
""",
    "app/globals.css": """\
:root {{
  color: #22272e;
  background: #f6f7f8;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}

body {{
  margin: 0;
}}

.surface {{
  max-width: 900px;
  padding: 32px;
}}

.eyebrow {{
  margin: 0 0 8px;
  color: #8e44ad;
  font-size: 13px;
  font-weight: 700;
}}

h1 {{
  margin: 0 0 12px;
  font-size: 32px;
}}

p {{
  color: #5e6670;
  line-height: 1.55;
}}

.metricGrid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(120px, 1fr));
  gap: 12px;
  margin-top: 24px;
  max-width: 620px;
}}

.metricGrid div {{
  border: 1px solid #d9dde2;
  border-radius: 8px;
  background: white;
  padding: 14px;
}}

.metricGrid b {{
  display: block;
  font-size: 24px;
}}

.metricGrid span {{
  color: #6c747d;
  font-size: 13px;
}}
""",
    "README.md": """\
# {title}

This Next.js app was scaffolded by curIAtor. It uses the App Router, a server-rendered page, and a
small JSON route while staying behind the same-origin gallery proxy.

Run it through the gallery:

```bash
npm install
curiator up
```

The generated `gallery.yaml` entry runs:

```bash
npm run dev -- -H 127.0.0.1 -p <port>
```

curIAtor sets `preserve_prefix: true` for this proxy mount and exports `CURIATOR_APP={name}`. The
generated `next.config.mjs` turns that into `basePath: "/app/{name}"`, so routes and framework assets
stay under the gallery path.

The scaffold smoke test is:

```bash
npm run build
```

Next's development server may use WebSocket/HMR. curIAtor's built-in proxy keeps the app same-origin
and shows a diagnostic for upgrade requests; use `commands.preview` after a build or a full reverse
proxy when live HMR is required.
""",
}

_APP_STREAMLIT_TEMPLATE = {
    "app.py": '''\
"""Streamlit app scaffold generated by `curiator app create {name} --template streamlit`."""
from __future__ import annotations

import streamlit as st


st.set_page_config(page_title={title_json}, layout="wide")

st.title({title_json})
st.caption("curIAtor Streamlit scaffold")

st.write(
    "This Streamlit app is served through a same-origin proxy mount. "
    "Use the feedback rail to shape the interface; the curator edits files in this directory."
)

left, middle, right = st.columns(3)
left.metric("Signals", "4", "+1")
middle.metric("Review window", "12 min", "-3 min")
right.metric("Ready", "98%", "+2%")

st.subheader("Notes")
st.text_area("What should this prototype show next?", height=120)
''',
    "requirements.txt": """\
streamlit>=1.36
""",
    "README.md": """\
# {title}

This Streamlit app was scaffolded by curIAtor.

Run it through the gallery:

```bash
pip install -r requirements.txt
curiator up
```

The generated `gallery.yaml` entry runs:

```bash
streamlit run app.py --server.address 127.0.0.1 --server.port <port> --server.headless true --server.baseUrlPath app/{name}
```

curIAtor sets `preserve_prefix: true` for this proxy mount so Streamlit receives paths under
`/app/{name}/`. The built-in curIAtor proxy is intentionally lightweight; if a Streamlit component needs
WebSocket or production reverse-proxy behavior beyond this local scaffold, keep this app directory and
put nginx, Caddy, or another full reverse proxy in front of the same command.

The scaffold smoke test is:

```bash
python -m py_compile app.py
```
""",
}

_APP_GRADIO_TEMPLATE = {
    "app.py": '''\
"""Gradio app scaffold generated by `curiator app create {name} --template gradio`."""
from __future__ import annotations

import argparse

import gradio as gr

TITLE = {title_json}


def respond(prompt: str) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        return "Add a prompt, then use the curIAtor feedback rail to shape this prototype."
    return f"Prototype response for: {{prompt}}"


with gr.Blocks(title=TITLE) as demo:
    gr.Markdown(f"# {{TITLE}}")
    gr.Markdown("curIAtor Gradio scaffold served through a same-origin proxy mount.")
    prompt = gr.Textbox(label="Prompt", placeholder="What should this prototype answer?")
    output = gr.Textbox(label="Output", interactive=False)
    run = gr.Button("Run")
    run.click(respond, inputs=prompt, outputs=output)
    prompt.submit(respond, inputs=prompt, outputs=output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--root-path", default="")
    args = parser.parse_args()
    demo.launch(
        server_name="127.0.0.1",
        server_port=args.port,
        root_path=args.root_path or None,
        share=False,
    )


if __name__ == "__main__":
    main()
''',
    "requirements.txt": """\
gradio>=4.44
""",
    "README.md": """\
# {title}

This Gradio app was scaffolded by curIAtor.

Run it through the gallery:

```bash
pip install -r requirements.txt
curiator up
```

The generated `gallery.yaml` entry runs:

```bash
python app.py --port <port> --root-path /app/{name}
```

curIAtor sets `preserve_prefix: true` for this proxy mount so Gradio receives paths under
`/app/{name}/` and can build URLs with the matching `root_path`. The built-in curIAtor proxy is
intentionally lightweight; if a Gradio component needs production reverse-proxy behavior beyond this
local scaffold, keep this app directory and put nginx, Caddy, or another full reverse proxy in front
of the same command.

The scaffold smoke test is:

```bash
python -m py_compile app.py
```
""",
}

_APP_NODE_TEMPLATE = {
    "package.json": """\
{{
  "name": "{name}",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {{
    "start": "node server.js",
    "check": "node --check server.js"
  }}
}}
""",
    "server.js": """\
import http from "node:http";

const TITLE = {title_json};

function optionValue(flag) {{
  const index = process.argv.indexOf(flag);
  return index >= 0 ? process.argv[index + 1] : undefined;
}}

const port = Number(optionValue("--port") || process.env.PORT || 8700);

function page() {{
  return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>${{TITLE}}</title>
    <style>
      body {{
        margin: 0;
        font-family: system-ui, sans-serif;
        color: #22272e;
        background: #f6f7f8;
      }}
      main {{
        max-width: 880px;
        padding: 32px;
      }}
      h1 {{
        margin: 0 0 12px;
        color: #8e44ad;
      }}
      p {{
        color: #5e6670;
        line-height: 1.55;
      }}
      .metricGrid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(120px, 1fr));
        gap: 12px;
        margin-top: 24px;
        max-width: 620px;
      }}
      .metricGrid div {{
        border: 1px solid #d9dde2;
        border-radius: 8px;
        background: white;
        padding: 14px;
      }}
      .metricGrid b {{
        display: block;
        font-size: 24px;
      }}
      .metricGrid span {{
        color: #6c747d;
        font-size: 13px;
      }}
    </style>
  </head>
  <body>
    <main>
      <p style="margin:0 0 8px;color:#8e44ad;font-size:13px;font-weight:700">curIAtor Node scaffold</p>
      <h1>${{TITLE}}</h1>
      <p>
        This dependency-light Node app is served through a same-origin proxy mount. Use the feedback
        rail to shape the server-rendered HTML; the curator edits files in this directory and
        smoke-tests with <code>node --check server.js</code>.
      </p>
      <section class="metricGrid" aria-label="demo metrics">
        <div><b>3</b><span>routes</span></div>
        <div><b>0</b><span>dependencies</span></div>
        <div><b>1</b><span>server file</span></div>
      </section>
    </main>
  </body>
</html>`;
}}

const server = http.createServer((req, res) => {{
  if (req.url === "/healthz") {{
    const body = JSON.stringify({{ ok: true, app: "{name}" }});
    res.writeHead(200, {{
      "content-type": "application/json; charset=utf-8",
      "content-length": Buffer.byteLength(body),
    }});
    res.end(body);
    return;
  }}
  const body = page();
  res.writeHead(200, {{
    "content-type": "text/html; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  }});
  res.end(body);
}});

server.listen(port, "127.0.0.1", () => {{
  console.log(`${{TITLE}} listening on http://127.0.0.1:${{port}}`);
}});
""",
    "README.md": """\
# {title}

This Node app was scaffolded by curIAtor. It has no npm dependencies: `server.js` uses Node's built-in
HTTP server and renders HTML on the server side.

Run it through the gallery:

```bash
curiator up
```

The generated `gallery.yaml` entry runs:

```bash
node server.js --port <port>
```

The scaffold smoke test is:

```bash
node --check server.js
```

Use this template for small server-side prototypes, lightweight API-backed views, or as a base before
promoting to a heavier framework.
""",
}

_APP_FLASK_TEMPLATE = {
    "app.py": '''\
"""Flask app scaffold generated by `curiator app create {name} --template flask`."""
from __future__ import annotations

import argparse

from flask import Flask, jsonify, render_template_string

TITLE = {title_json}

HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{{{ title }}}}</title>
    <style>
      body {{
        margin: 0;
        font-family: system-ui, sans-serif;
        color: #22272e;
        background: #f6f7f8;
      }}
      main {{
        max-width: 900px;
        padding: 32px;
      }}
      .eyebrow {{
        margin: 0 0 8px;
        color: #8e44ad;
        font-size: 13px;
        font-weight: 700;
      }}
      h1 {{
        margin: 0 0 12px;
        font-size: 32px;
      }}
      p {{
        color: #5e6670;
        line-height: 1.55;
      }}
      .metricGrid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(120px, 1fr));
        gap: 12px;
        margin-top: 24px;
        max-width: 620px;
      }}
      .metricGrid div {{
        border: 1px solid #d9dde2;
        border-radius: 8px;
        background: white;
        padding: 14px;
      }}
      .metricGrid b {{
        display: block;
        font-size: 24px;
      }}
      .metricGrid span {{
        color: #6c747d;
        font-size: 13px;
      }}
    </style>
  </head>
  <body>
    <main>
      <p class="eyebrow">curIAtor Flask scaffold</p>
      <h1>{{{{ title }}}}</h1>
      <p>
        This Flask app is served through a same-origin proxy mount. Use the feedback rail to shape the
        server-rendered view; the curator edits files in this directory and smoke-tests with
        <code>python -m py_compile app.py</code>.
      </p>
      <section class="metricGrid" aria-label="demo metrics">
        <div><b>3</b><span>routes</span></div>
        <div><b>1</b><span>Flask app</span></div>
        <div><b>0</b><span>extra deps</span></div>
      </section>
    </main>
  </body>
</html>
"""


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template_string(HTML, title=TITLE)

    @app.get("/healthz")
    def healthz():
        return jsonify({{"ok": True, "app": "{name}"}})

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8700)
    args = parser.parse_args()
    create_app().run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
''',
    "README.md": """\
# {title}

This Flask app was scaffolded by curIAtor. It uses Flask, which is already installed with curIAtor,
and renders HTML on the server side.

Run it through the gallery:

```bash
curiator up
```

The generated `gallery.yaml` entry runs:

```bash
python app.py --port <port>
```

The scaffold smoke test is:

```bash
python -m py_compile app.py
```

Use this template for lightweight server-rendered views, tiny API-backed panels, or prototypes that
should stay Python-native without becoming Dash apps.
""",
}

_APP_FASTAPI_TEMPLATE = {
    "main.py": '''\
"""FastAPI app scaffold generated by `curiator app create {name} --template fastapi`."""
from __future__ import annotations

import argparse

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

TITLE = {title_json}

HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
      body {{
        margin: 0;
        font-family: system-ui, sans-serif;
        color: #22272e;
        background: #f6f7f8;
      }}
      main {{
        max-width: 900px;
        padding: 32px;
      }}
      .eyebrow {{
        margin: 0 0 8px;
        color: #8e44ad;
        font-size: 13px;
        font-weight: 700;
      }}
      h1 {{
        margin: 0 0 12px;
        font-size: 32px;
      }}
      p {{
        color: #5e6670;
        line-height: 1.55;
      }}
      .metricGrid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(120px, 1fr));
        gap: 12px;
        margin-top: 24px;
        max-width: 620px;
      }}
      .metricGrid div {{
        border: 1px solid #d9dde2;
        border-radius: 8px;
        background: white;
        padding: 14px;
      }}
      .metricGrid b {{
        display: block;
        font-size: 24px;
      }}
      .metricGrid span {{
        color: #6c747d;
        font-size: 13px;
      }}
    </style>
  </head>
  <body>
    <main>
      <p class="eyebrow">curIAtor FastAPI scaffold</p>
      <h1>{title}</h1>
      <p>
        This FastAPI app is served through a same-origin proxy mount. Use the feedback rail to shape
        the API-backed view; the curator edits files in this directory and smoke-tests with
        <code>python -m py_compile main.py</code>.
      </p>
      <section class="metricGrid" aria-label="demo metrics">
        <div><b>3</b><span>routes</span></div>
        <div><b>1</b><span>ASGI app</span></div>
        <div><b>JSON</b><span>status API</span></div>
      </section>
    </main>
  </body>
</html>
"""

app = FastAPI(title=TITLE)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.get("/api/status")
def status() -> dict[str, object]:
    return {{"ok": True, "app": "{name}", "routes": ["/", "/api/status", "/docs"]}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8700)
    parser.add_argument("--root-path", default="")
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, root_path=args.root_path)


if __name__ == "__main__":
    main()
''',
    "requirements.txt": """\
fastapi>=0.115
uvicorn[standard]>=0.30
""",
    "README.md": """\
# {title}

This FastAPI app was scaffolded by curIAtor. It serves a small HTML view plus a JSON status endpoint
through the same-origin proxy mount.

Run it through the gallery:

```bash
pip install -r requirements.txt
curiator up
```

The generated `gallery.yaml` entry runs:

```bash
python main.py --port <port> --root-path /app/{name}
```

curIAtor strips `/app/{name}/` before proxying to the app. The generated `--root-path` keeps FastAPI's
OpenAPI/docs URLs anchored under the gallery path, so `/app/{name}/docs` can find its schema and assets.

The scaffold smoke test is:

```bash
python -m py_compile main.py
```

Use this template for lightweight JSON APIs, API-backed HTML views, or prototypes that may later grow
into a larger ASGI service.
""",
}

_APP_RUST_TEMPLATE = {
    "Cargo.toml": """\
[package]
name = "__NAME__"
version = "0.1.0"
edition = "2021"

[dependencies]
""",
    "src/main.rs": r'''
//! Rust HTTP server scaffold generated by `curiator app create __NAME__ --template rust`.

use std::env;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};

const APP: &str = "__NAME__";
const TITLE: &str = __TITLE_LITERAL__;

fn option_value(flag: &str) -> Option<String> {
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        if arg == flag {
            return args.next();
        }
    }
    None
}

fn port() -> u16 {
    option_value("--port")
        .or_else(|| env::var("PORT").ok())
        .and_then(|value| value.parse::<u16>().ok())
        .unwrap_or(8700)
}

fn page() -> String {
    r#"<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>__TITLE_TEXT__</title>
    <style>
      body {
        margin: 0;
        font-family: system-ui, sans-serif;
        color: #22272e;
        background: #f6f7f8;
      }
      main {
        max-width: 900px;
        padding: 32px;
      }
      .eyebrow {
        margin: 0 0 8px;
        color: #8e44ad;
        font-size: 13px;
        font-weight: 700;
      }
      h1 {
        margin: 0 0 12px;
        font-size: 32px;
      }
      p {
        color: #5e6670;
        line-height: 1.55;
      }
      .metricGrid {
        display: grid;
        grid-template-columns: repeat(3, minmax(120px, 1fr));
        gap: 12px;
        margin-top: 24px;
        max-width: 620px;
      }
      .metricGrid div {
        border: 1px solid #d9dde2;
        border-radius: 8px;
        background: white;
        padding: 14px;
      }
      .metricGrid b {
        display: block;
        font-size: 24px;
      }
      .metricGrid span {
        color: #6c747d;
        font-size: 13px;
      }
    </style>
  </head>
  <body>
    <main>
      <p class="eyebrow">curIAtor Rust scaffold</p>
      <h1>__TITLE_TEXT__</h1>
      <p>
        This dependency-light Rust app is served through a same-origin proxy mount. Use the feedback
        rail to shape the server-rendered view; the curator edits files in this directory and
        smoke-tests with <code>cargo check --quiet</code>.
      </p>
      <section class="metricGrid" aria-label="demo metrics">
        <div><b>1</b><span>binary</span></div>
        <div><b>0</b><span>dependencies</span></div>
        <div><b>2</b><span>routes</span></div>
      </section>
    </main>
  </body>
</html>"#.to_string()
}

fn response(status: &str, content_type: &str, body: &str) -> Vec<u8> {
    format!(
        "HTTP/1.1 {status}\r\ncontent-type: {content_type}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
        body.as_bytes().len()
    )
    .into_bytes()
}

fn handle(mut stream: TcpStream) -> std::io::Result<()> {
    let mut buf = [0_u8; 1024];
    let n = stream.read(&mut buf)?;
    let request = String::from_utf8_lossy(&buf[..n]);
    let path = request
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .unwrap_or("/");
    let bytes = if path == "/healthz" {
        let body = format!(r#"{{"ok":true,"app":"{APP}"}}"#);
        response("200 OK", "application/json; charset=utf-8", &body)
    } else {
        response("200 OK", "text/html; charset=utf-8", &page())
    };
    stream.write_all(&bytes)?;
    stream.flush()
}

fn main() -> std::io::Result<()> {
    let port = port();
    let listener = TcpListener::bind(("127.0.0.1", port))?;
    println!("{TITLE} listening on http://127.0.0.1:{port}");
    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                if let Err(err) = handle(stream) {
                    eprintln!("request failed: {err}");
                }
            }
            Err(err) => eprintln!("connection failed: {err}"),
        }
    }
    Ok(())
}
''',
    "README.md": """\
# __TITLE_TEXT__

This Rust app was scaffolded by curIAtor. It has no crate dependencies: `src/main.rs` uses the Rust
standard library to serve HTML plus a `/healthz` JSON endpoint.

Run it through the gallery:

```bash
curiator up
```

The generated `gallery.yaml` entry runs:

```bash
cargo run --quiet -- --port <port>
```

The scaffold smoke test is:

```bash
cargo check --quiet
```

Use this template for small compiled status services, API-backed prototypes, or Rust views that should
stay behind curIAtor's same-origin feedback overlay.
""",
}


def _app_rust_template_files(name: str, title: str) -> dict[str, str]:
    replacements = {
        "__NAME__": name,
        "__TITLE_LITERAL__": _rust_string(title),
        "__TITLE_TEXT__": title,
    }
    out = {}
    for rel, content in _APP_RUST_TEMPLATE.items():
        text = content
        for old, new in replacements.items():
            text = text.replace(old, new)
        out[rel] = text
    return out


_APP_PYTHON_TEMPLATE = '''\
"""Tiny Python web server scaffold generated by `curiator app create {name} --template python`."""
from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
      body {{
        margin: 0;
        font-family: system-ui, sans-serif;
        color: #2f3337;
        background: #f7f7f5;
      }}
      main {{
        max-width: 860px;
        padding: 32px;
      }}
      h1 {{
        margin: 0 0 8px;
        color: #8e44ad;
      }}
      p {{
        color: #5f666d;
        line-height: 1.5;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>{title}</h1>
      <p>This Python server app was scaffolded by curIAtor. Use feedback in the right rail to shape it.</p>
    </main>
  </body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    port = int(os.environ.get("PORT", "8700"))
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
'''


if __name__ == "__main__":
    raise SystemExit(main())
