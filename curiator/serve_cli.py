"""CLI handlers for serving the shell, hot reload, and demo resets."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import ledger
from .config import load_config


def _cli_shared():
    from . import cli as cli_mod

    return cli_mod


def _shell_url(cfg: dict, app: str | None = None) -> str:
    return _cli_shared()._shell_url(cfg, app)
def _shell_path(kind: str | None = None) -> Path:
    """The overlay shell entrypoint. React/Flask is the default; Dash remains as a legacy fallback."""
    selected = (kind or os.environ.get("CURIATOR_SHELL") or "react").lower()
    name = "app_shell.py" if selected in {"dash", "legacy", "legacy-dash"} else "web_shell.py"
    return Path(__file__).resolve().parent / "shell" / name


def _child_env(cfg: dict) -> dict:
    """Env for child processes.

    Gallery authority is passed as `--gallery`, not as inherited ambient environment. Strip the legacy
    fallback so a parent shell's CURIATOR_GALLERY cannot silently retarget children.
    """
    env = dict(os.environ)
    env.pop("CURIATOR_GALLERY", None)
    return env


def _gallery_cli_args(cfg: dict) -> list[str]:
    return ["--gallery", str(Path(cfg["gallery_path"]).resolve())]


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
    return subprocess.run([sys.executable, str(_shell_path(kind)), *_gallery_cli_args(cfg)], cwd=cfg["repo_root"],
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
    watcher = subprocess.Popen([sys.executable, "-u", "-m", "curiator.cli", *_gallery_cli_args(cfg), "watch"],
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
        return subprocess.run([sys.executable, str(_shell_path(shell_kind)), *_gallery_cli_args(cfg)],
                              cwd=cfg["repo_root"], env=env).returncode
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


def cmd_open(args) -> int:
    cfg = load_config()
    app = args.app or cfg.get("current_app")
    print(_shell_url(cfg, app))
    return 0


def cmd_reload(args) -> int:
    """Drop a running shell's cached build of <app> so its edited source rebuilds on the next view."""
    cfg = load_config()
    msg = _reload_in_shell(cfg, args.app)
    print(f"curiator: {msg}" if msg else "curiator: shell not reachable on the configured port "
          "(a running React shell also picks up changed app sources on its poll).")
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


def cmd_reset_demo(args) -> int:
    _reset_demo(load_config())
    print("curiator: demo reset — aviato re-broken, ledger cleared, shots/ + task files wiped.")
    return 0


def cmd_demo(args) -> int:
    print(Path(__file__).resolve().parents[1].joinpath("docs", "DEMO_SCRIPT.md").read_text())
    return 0
