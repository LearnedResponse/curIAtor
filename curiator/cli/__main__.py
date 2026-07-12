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
    curiator playground-backup-smoke # restore-copy a hosted playground and preflight the copy
    curiator reset-demo # rewind the demo: re-break aviato, clear the ledger
    curiator demo-up    # reset-demo, then serve — one command, record-ready
    curiator demo       # print the demo walkthrough
    curiator stats      # summarize ledger + git-as-memory case-study numbers
    curiator init <dir> # scaffold a fresh collection repo; add --git for a nested subrepo

`up` and `watch` are two processes — run them in two terminals, or use `curiator serve` / `make demo`.
"""
from __future__ import annotations

import argparse
import os
import shutil  # noqa: F401 - kept as curiator.cli.shutil for compatibility with CLI tests/extensions
import shlex
import subprocess
from pathlib import Path

from .. import ledger
from ..config import (
    set_agent_adapter_override,
    set_agent_autonomy_override,
    set_agent_model_override,
    set_agent_network_override,
    set_agent_sandbox_override,
    set_gallery_override,
    set_state_dir_override,
    set_workspace_mode,
)
from ..app_cli import (
    _APP_TEMPLATE_CHOICES,
    _JS_PACKAGE_MANAGERS,
    _app_names,
    _template_choices_help,
    cmd_app_create,
    cmd_app_import,
    cmd_app_templates,
)
from ..auth_cli import cmd_auth, cmd_user
from ..capability_cli import cmd_capability
from ..collection_cli import (
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
from ..galleries_cli import cmd_galleries, cmd_galleries_adopt, cmd_galleries_clone
from ..serve_cli import (
    _child_env,  # noqa: F401 - compatibility export for runtime shell extensions
    _reload_in_shell,  # noqa: F401 - compatibility export used by workflow_cli
    _reset_demo,  # noqa: F401 - compatibility export for demo tooling
    _serve,  # noqa: F401 - compatibility export for runtime shell tooling
    _shell_path,  # noqa: F401 - compatibility export for shell tooling
    cmd_demo,
    cmd_demo_up,
    cmd_open,
    cmd_reload,
    cmd_reset_demo,
    cmd_serve,
    cmd_up,
    cmd_watch,
)
from ..release_cli import (
    _PUBLIC_RELEASE_OWNER,
    _clone_gallery as _clone_gallery,
    cmd_playground_backup_smoke,
    cmd_playground_preflight,
    cmd_release_preflight,
)
from ..proposal_cli import add_proposal_parser
from ..replay_cli import add_replay_parser
from ..run_cli import cmd_run
from ..stats_cli import cmd_stats
from ..voice.cli import cmd_voice
from ..workspace_cli import add_workspace_parser
from ..workflow_cli import (
    _parse_actions_arg,  # noqa: F401 - compatibility export for workflow tooling
    _post_reply,  # noqa: F401 - compatibility export for workflow tooling
    _print_feedback_items,  # noqa: F401 - compatibility export for feedback tooling
    _queue_entries,  # noqa: F401 - compatibility export used by playground preflight
    _queue_row_payload,  # noqa: F401 - compatibility export used by playground preflight
    cmd_context,
    cmd_done,
    cmd_feedback,
    cmd_queue,
    cmd_reflect,
    cmd_reply,
    cmd_revert,
    cmd_seed,
    cmd_work,
)


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
    from ..loop.adapters import GENERAL_KEY
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
    from ..web_paths import local_shell_url

    return local_shell_url(cfg, app=app)


def _curiator_env_cmd(cfg: dict, *parts: str) -> str:
    gallery = shlex.quote(str(Path(cfg["gallery_path"]).resolve()))
    state = f" --state-dir {shlex.quote(str(Path(cfg['state_dir']).resolve()))}" if cfg.get("state_dir") else ""
    workspace = " --workspace-mode" if cfg.get("workspace_mode") else ""
    args = " ".join(shlex.quote(str(part)) for part in parts)
    return f"curiator --gallery {gallery}{state}{workspace} {args}"


def _cli_user(cfg: dict) -> dict | None:
    from .. import auth
    user = auth.current_user(cfg.get("auth") or {})
    if not user:
        # header/oidc/local modes have no request context on the CLI — record the local git identity
        # (or $USER) instead of dropping provenance. No groups ⇒ never grants an elevated agent run.
        root = Path(cfg["repo_root"])
        email = _git_output(root, "config", "user.email") or f"{os.environ.get('USER') or 'anonymous'}@local"
        name = _git_output(root, "config", "user.name")
        user = {"id": email, "email": email, "name": name or email.split("@")[0], "groups": []}
    return auth.stamp(user)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="curiator", description="curIAtor — an AI-maintained app gallery.")
    p.add_argument("--gallery", dest="gallery_override",
                   help="path to gallery.yaml or a collection directory; scoped to this command")
    p.add_argument("--state-dir", dest="state_dir_override",
                   help="runtime feedback/task/artifact directory; scoped to this command")
    p.add_argument("--agent-adapter", choices=["headless-cc", "codex", "api", "command"],
                   help="agent adapter override for this command; does not edit gallery.yaml")
    p.add_argument("--agent-model", help="agent model override for this command; does not edit gallery.yaml")
    p.add_argument("--agent-autonomy", choices=["propose-only", "auto-small", "auto"],
                   help="agent autonomy override for this command; does not edit gallery.yaml")
    p.add_argument("--agent-network", choices=["on", "off"],
                   help="agent network override for this command; does not edit gallery.yaml")
    p.add_argument("--agent-sandbox", choices=["read-only", "workspace-write", "danger-full-access"],
                   help="Codex sandbox override for this command; does not edit gallery.yaml")
    p.add_argument("--workspace-mode", action="store_true", help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up", help="serve the gallery")
    up.add_argument("--legacy-dash-shell", action="store_true", help="serve the old Dash overlay shell")
    up.set_defaults(func=cmd_up)
    sub.add_parser("watch", help="arm the feedback→fix loop").set_defaults(func=cmd_watch)
    add_workspace_parser(sub)
    add_replay_parser(sub)
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
    dr = sub.add_parser("doctor", help="check collection config portability, app paths, and optional agent tooling")
    dr.add_argument("--agent", action="store_true", help="also report local tools that gate agent capabilities")
    dr.add_argument("--json", action="store_true", help="emit machine-readable diagnostics")
    dr.set_defaults(func=cmd_doctor)
    cap = sub.add_parser("capability", help="record or clear a local provider capability receipt")
    cap.add_argument("action", choices=["verify", "unavailable", "clear"])
    cap.add_argument("name", choices=["figma"])
    cap.add_argument("--provider", choices=["codex", "headless-cc"],
                     help="agent adapter whose connector was verified (default: gallery adapter)")
    cap.add_argument("--write-design", action="store_true",
                     help="also attest explicit write authorization for this machine")
    cap.add_argument("--code-connect", action="store_true",
                     help="also attest working Code Connect access")
    cap.add_argument("--reason", default="provider unavailable",
                     help="provider-side reason for `capability unavailable`")
    cap.add_argument("--retry-hours", type=int, default=24,
                     help="hours before an unavailable receipt expires (default: 24; max: 168)")
    cap.set_defaults(func=cmd_capability)
    sm = sub.add_parser("smoke", help="run configured app smoke commands for this collection")
    sm.add_argument("--app", help="limit smoke checks to one app")
    sm.add_argument("--jobs", type=int, default=1, help="run up to N smoke checks concurrently (default: 1)")
    sm.add_argument("--http", action="store_true", help="also start proxy apps briefly and verify HTTP response")
    sm.add_argument("--browser", action="store_true", help="also open each app through the shell in headless Brave")
    sm.add_argument("--browser-bin", help="Brave/Chromium executable for --browser (default: brave-browser on PATH)")
    sm.add_argument("--viewport", help="browser viewport as WIDTHxHEIGHT, for example 390x844")
    sm.add_argument("--artifact-dir", help="write browser-smoke screenshots and console logs under this directory")
    sm.add_argument("--output", help="write the JSON smoke payload to a file")
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
    rp.add_argument("--prepare-dependencies", action="store_true",
                    help="run each app's explicit commands.bootstrap before smoke checks")
    rp.add_argument("--no-smoke", action="store_true", help="skip per-app smoke checks")
    rp.add_argument("--http-smoke", "--http", action="store_true", dest="http_smoke",
                    help="also start proxy apps briefly and verify configured HTTP smoke paths")
    rp.add_argument("--browser-smoke", action="store_true", dest="browser_smoke",
                    help="also open apps through the shell in headless Brave during smoke checks")
    rp.add_argument("--browser-bin", help="Brave/Chromium executable for --browser-smoke")
    rp.add_argument("--strict", action="store_true", help="fail when doctor warnings are present")
    rp.add_argument("--require-public-remotes", action="store_true",
                    help="also require each gallery's origin remote to match its expected public GitHub repo")
    rp.add_argument("--require-published-head", action="store_true",
                    help="also require each gallery's exact HEAD commit to be present on origin")
    rp.add_argument("--require-runner-public-remote", action="store_true",
                    help="also require this runner checkout's origin to match its expected public GitHub repo")
    rp.add_argument("--require-runner-published-head", action="store_true",
                    help="also require this runner checkout's exact HEAD commit to be present on origin")
    rp.add_argument("--require-release-tag",
                    help="also require the named local release tag to be present on this runner checkout's origin")
    rp.add_argument("--public-remote-owner", default=_PUBLIC_RELEASE_OWNER,
                    help=f"GitHub owner/org for --require-public-remotes (default: {_PUBLIC_RELEASE_OWNER})")
    rp.add_argument("--output", help="write the JSON preflight payload to a file")
    rp.add_argument("--json", action="store_true", help="emit machine-readable diagnostics")
    rp.set_defaults(func=cmd_release_preflight)
    pp = sub.add_parser("playground-preflight", help="check hosted public-playground readiness")
    pp.add_argument("--no-smoke", action="store_true", help="skip per-app smoke checks")
    pp.add_argument("--http-smoke", "--http", action="store_true", dest="http_smoke",
                    help="also start proxy apps briefly and verify configured HTTP smoke paths")
    pp.add_argument("--browser-smoke", action="store_true", dest="browser_smoke",
                    help="also open apps through the shell in headless Brave during smoke checks")
    pp.add_argument("--browser-bin", help="Brave/Chromium executable for --browser-smoke")
    pp.add_argument("--strict", action="store_true", help="fail when posture or doctor warnings are present")
    pp.add_argument("--output", help="write the JSON preflight payload to a file")
    pp.add_argument("--json", action="store_true", help="emit machine-readable diagnostics")
    pp.set_defaults(func=cmd_playground_preflight)
    pb = sub.add_parser("playground-backup-smoke", help="restore-copy a hosted playground and preflight it")
    pb.add_argument("--restore-root", help="directory where the temporary restore run should be created")
    pb.add_argument("--keep-restore", action="store_true", help="keep the restored collection for inspection")
    pb.add_argument("--no-smoke", action="store_true", help="skip per-app smoke checks on the restored copy")
    pb.add_argument("--http-smoke", "--http", action="store_true", dest="http_smoke",
                    help="also start proxy apps briefly and verify configured HTTP smoke paths")
    pb.add_argument("--browser-smoke", action="store_true", dest="browser_smoke",
                    help="also open apps through the shell in headless Brave during smoke checks")
    pb.add_argument("--browser-bin", help="Brave/Chromium executable for --browser-smoke")
    pb.add_argument("--strict", action="store_true", help="fail when restored posture or doctor warnings are present")
    pb.add_argument("--output", help="write the JSON restore/preflight payload to a file")
    pb.add_argument("--json", action="store_true", help="emit machine-readable diagnostics")
    pb.set_defaults(func=cmd_playground_backup_smoke)
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
    run = sub.add_parser("run", help="inspect or recover an interrupted agent run")
    run_sub = run.add_subparsers(dest="run_action", required=True)
    recovery = run_sub.add_parser("recovery", help="show source deltas and available recovery actions")
    recovery.add_argument("feedback_id")
    recovery.add_argument("--json", action="store_true", help="emit the recovery report as JSON")
    recovery.set_defaults(func=cmd_run)
    resume = run_sub.add_parser("resume", help="accept partial source as the next run baseline and requeue")
    resume.add_argument("feedback_id")
    resume.set_defaults(func=cmd_run)
    preserve = run_sub.add_parser("preserve", help="preserve partial source on recovery branches")
    preserve.add_argument("feedback_id")
    preserve.add_argument("--branch", help="branch name (default: curiator/recovery/<feedback-id>)")
    preserve.set_defaults(func=cmd_run)
    restore = run_sub.add_parser("restore", help="restore the exact checkpointed source baseline and requeue")
    restore.add_argument("feedback_id")
    restore.set_defaults(func=cmd_run)
    discard = run_sub.add_parser(
        "discard-checkpoint", help="retire recovery data while leaving current source untouched"
    )
    discard.add_argument("feedback_id")
    discard.set_defaults(func=cmd_run)
    dn = sub.add_parser("done", help="reply done for interactive work (reload + git-as-memory)")
    dn.add_argument("feedback_id", nargs="?",
                    help="feedback id (defaults to the latest working item); a non-id word here is "
                         "treated as the start of the summary text")
    dn.add_argument("text", nargs="*", help="summary text")
    dn.add_argument("--app", help="override linked/current app")
    dn.set_defaults(func=cmd_done)
    add_proposal_parser(sub)
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
    fb = sub.add_parser("feedback", help="inspect, add, or compact SQLite feedback")
    fb.add_argument("action", choices=["show", "dump", "add", "compact"], nargs="?", default="show")
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
    fb.add_argument("--design-ref", action="append", default=[],
                    help="attach a node-specific Figma URL (repeat up to five times)")
    fb.add_argument("--design-label", action="append", default=[],
                    help="optional label paired by position with --design-ref")
    fb.add_argument("--writable-component", action="append", default=[],
                    help="grant this feedback write access to a declared shared component (repeatable)")
    fb.add_argument("--limit", type=int, default=20)
    fb.add_argument("--json", action="store_true", help="emit machine-readable compact evidence")
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
    set_gallery_override(getattr(args, "gallery_override", None))
    set_state_dir_override(getattr(args, "state_dir_override", None))
    set_agent_adapter_override(getattr(args, "agent_adapter", None))
    set_agent_model_override(getattr(args, "agent_model", None))
    set_agent_autonomy_override(getattr(args, "agent_autonomy", None))
    network_override = getattr(args, "agent_network", None)
    set_agent_network_override(None if network_override is None else network_override == "on")
    set_agent_sandbox_override(getattr(args, "agent_sandbox", None))
    set_workspace_mode(bool(getattr(args, "workspace_mode", False)))
    try:
        return args.func(args)
    finally:
        set_gallery_override(None)
        set_state_dir_override(None)
        set_agent_adapter_override(None)
        set_agent_model_override(None)
        set_agent_autonomy_override(None)
        set_agent_network_override(None)
        set_agent_sandbox_override(None)
        set_workspace_mode(False)


if __name__ == "__main__":
    raise SystemExit(main())
