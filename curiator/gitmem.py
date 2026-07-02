"""gitmem.py — git as the curator's memory.

Every agent run becomes ONE atomic commit that captures the whole state transition — the source edit
(if any) AND the feedback-ledger update (the ⚙ reply + status) ride in the same commit. The git log
then is the durable, queryable, revertible record of every curator action. See docs/DESIGN.md →
"Git as the memory".

Policy comes from gallery.yaml `git:` (config.py fills defaults):
    commit          # false (default) = leave-uncommitted (today's behavior) | true = git-as-memory
    branch          # the sandbox/env branch commits land on (null/empty = current HEAD)
    signoff         # add Signed-off-by (DCO) via `git commit -s`
    include_ledger  # optionally bundle feedback/app_feedback.sqlite in the same commit

Binding practices (enforced here + in task_template.md): one item → one atomic commit; smoke-test
before commit (fail ⇒ revert + report, no commit); structured message + trailers; commit only —
never push/merge/force/rewrite; undo via `revert`, never reset.
"""
from __future__ import annotations

import contextlib
import fcntl
import fnmatch
import os
import importlib.util
import re
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import ledger

_FEEDBACK_TRAILER = "Curiator-Feedback"
_APP_TRAILER = "Curiator-App"
_MEMORY_TRAILER = "Curiator-Memory"
_GENERAL_KEY = "__general__"

# Files that ride in the SAME atomic commit as a source edit when an agent changed them — dependency
# manifests, so an elevated run that `pip install`s a package + adds it here isn't left dangling outside
# the commit. Override per-collection via `git.also_commit` (a list of globs; [] disables).
_DEFAULT_ALSO_COMMIT = [
    "requirements.txt", "requirements/*.txt", "constraints.txt",
    "pyproject.toml", "setup.cfg", "setup.py",
    "Pipfile", "Pipfile.lock", "poetry.lock",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
]
_GENERAL_COLLECTION_GLOBS = [
    "apps/**",
    "assets/**", "data/**",
]


# ───────────────────────────── low-level git ─────────────────────────────
def _git_in(repo: Path, *args: str, check: bool = True):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo}: {(r.stderr or r.stdout).strip()}")
    return r


def _git(cfg: dict, *args: str, check: bool = True):
    return _git_in(Path(cfg["repo_root"]), *args, check=check)


def is_repo(cfg: dict) -> bool:
    return _git(cfg, "rev-parse", "--git-dir", check=False).returncode == 0


def current_branch(cfg: dict) -> str:
    return _git(cfg, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


@contextlib.contextmanager
def _lock(cfg: dict):
    """Serialize commits/reverts/reflects so concurrent invocations never race the index/ledger."""
    gitdir = Path(cfg["repo_root"]) / ".git"
    if not gitdir.exists():
        yield
        return
    f = open(gitdir / "curiator-commit.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def ensure_branch(cfg: dict, branch: str | None) -> None:
    """Make `branch` current (the sandbox/env branch), carrying uncommitted changes. Empty ⇒ stay on HEAD."""
    if not branch or current_branch(cfg) == branch:
        return
    exists = _git(cfg, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0
    _git(cfg, "checkout", branch) if exists else _git(cfg, "checkout", "-b", branch)


# ───────────────────────────── helpers ─────────────────────────────
def source_for(cfg: dict, app: str) -> str | None:
    """The app's source scope (relative to repo root — a git pathspec), or None."""
    spec = _app_spec(cfg, app)
    return spec.get("source_rel") if spec else None


def _rel_to_repo(cfg: dict, path: Path | None) -> str | None:
    if not path:
        return None
    try:
        return str(path.resolve().relative_to(Path(cfg["repo_root"]).resolve()))
    except ValueError:
        return None


def _app_spec(cfg: dict, app: str) -> dict | None:
    """config.app_spec + the repo-relative paths gitmem needs for git pathspecs."""
    from .config import app_spec
    spec = app_spec(cfg, app)
    if not spec:
        return None
    root, source = Path(spec["root"]), Path(spec["source"])
    return {
        "root": root,
        "root_rel": _rel_to_repo(cfg, root),
        "source": source,
        "source_rel": _rel_to_repo(cfg, source),
        "smoke": spec.get("smoke"),
        "smoke_timeout": spec.get("smoke_timeout"),
    }


def _is_git_toplevel(repo: Path) -> bool:
    top = _git_in(repo, "rev-parse", "--show-toplevel", check=False).stdout.strip()
    return bool(top) and Path(top).resolve() == repo.resolve()


def _nested_app_repo(cfg: dict, spec: dict) -> Path | None:
    root = Path(spec.get("root") or "")
    collection = Path(cfg["repo_root"]).resolve()
    if not root.exists() or root.resolve() == collection:
        return None
    if _is_git_toplevel(root):
        return root.resolve()
    return None


def _rel_to(path: Path | None, base: Path) -> str | None:
    if not path:
        return None
    try:
        rel = path.resolve().relative_to(base.resolve())
    except ValueError:
        return None
    return str(rel) or "."


def _ledger_relpath(cfg: dict) -> str:
    return f"{(cfg.get('feedback', {}) or {}).get('dir', 'feedback')}/app_feedback.sqlite"


def _add_paths(cfg: dict, paths: list[str], ledger_rel: str | None = None) -> None:
    """Stage normal paths normally, and the ignored SQLite ledger only when explicitly requested."""
    normal = [p for p in paths if p and p != ledger_rel]
    if normal:
        _git(cfg, "add", "--", *normal)
    if ledger_rel and ledger_rel in paths:
        ledger.checkpoint(cfg)
        _git(cfg, "add", "-f", "--", ledger_rel)


def _add_paths_in(repo: Path, paths: list[str]) -> None:
    normal = [p for p in paths if p]
    if normal:
        _git_in(repo, "add", "--", *normal)


def _gallery_relpath(cfg: dict) -> str | None:
    gp = cfg.get("gallery_path")
    if not gp:
        return "gallery.yaml"
    try:
        return str(Path(gp).resolve().relative_to(Path(cfg["repo_root"]).resolve()))
    except ValueError:
        return None


def smoke_source(path: Path) -> tuple[bool, str]:
    """Import the source and build its app — the same gate the agent runs. (ok, message)."""
    try:
        spec = importlib.util.spec_from_file_location("curiator_smoke", str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "build_app"):
            mod.build_app()
        elif not hasattr(mod, "app"):
            return False, "no build_app() or module-level app"
        return True, "passed"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _smoke_timeout(cfg: dict, spec: dict) -> tuple[float | None, str | None]:
    value = spec.get("smoke_timeout")
    global_smoke = cfg.get("smoke") or {}
    if value is None and isinstance(global_smoke, dict):
        value = global_smoke.get("timeout")
    if value in (None, ""):
        return None, None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None, f"invalid smoke timeout: {value!r}"
    if seconds <= 0:
        return None, None
    return seconds, None


def _python_smoke_target(root: Path, command: str | None = None) -> str | None:
    if command:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = str(command).split()
        for token in parts:
            if token.endswith(".py") and (root / token).is_file():
                return token
    for name in ("server.py", "app.py", "main.py"):
        if (root / name).is_file():
            return name
    return None


def inferred_smoke_command(cfg: dict, spec: dict) -> str | None:
    """Return a conservative fallback smoke command for directory/proxy apps without `smoke:`."""
    if spec.get("smoke"):
        return None
    root = Path(spec.get("root") or cfg["repo_root"])
    if not root.exists() or not root.is_dir():
        return None
    mount = spec.get("mount") or {}
    command = str(mount.get("cmd") or "")
    py_target = _python_smoke_target(root, command)
    if py_target:
        return f"python -m py_compile {py_target}"
    for name in ("server.js", "app.js", "main.js"):
        if (root / name).is_file():
            return f"node --check {name}"
    if (root / "Cargo.toml").is_file():
        return "cargo check --quiet"
    return None


def _render_smoke_template(cfg: dict, spec: dict, app: str, src: str | None, command: str) -> str:
    root = spec.get("root") or Path(cfg["repo_root"])
    source = spec.get("source") or (Path(cfg["repo_root"]) / src if src else root)
    mount = spec.get("mount") if isinstance(spec.get("mount"), dict) else {}
    values = {
        "root": str(root),
        "source": str(source),
        "app": app,
        "port": spec.get("port") or mount.get("port") or "",
    }
    return str(command).format(**values)


def smoke_command(cfg: dict, spec: dict, app: str, src: str | None) -> str | None:
    cmd = spec.get("smoke") or inferred_smoke_command(cfg, spec)
    if not cmd:
        return None
    return _render_smoke_template(cfg, spec, app, src, str(cmd))


def _http_smoke_settings(spec: dict, app: str) -> dict | None:
    raw = spec.get("smoke_http")
    if raw is False:
        return None
    mount = spec.get("mount") or {}
    if mount.get("kind") != "proxy":
        return None
    if isinstance(raw, str):
        settings = {"path": raw}
    elif isinstance(raw, dict):
        settings = dict(raw)
    else:
        settings = {}
    path = settings.get("path")
    if not path:
        path = f"/app/{app}/" if mount.get("preserve_prefix") else "/"
    path = str(path).format(app=app)
    if not path.startswith(("http://", "https://", "/")):
        path = "/" + path
    settings["path"] = path
    return settings


def _tail(path: Path, limit: int = 2000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:].strip()
    except OSError:
        return ""


def http_smoke_app(cfg: dict, app: str, src: str | None, spec: dict | None = None) -> dict:
    """Start a proxy app briefly and verify it answers HTTP. Intended for opt-in CLI/runtime smoke."""
    spec = spec or _app_spec(cfg, app) or {}
    settings = _http_smoke_settings(spec, app)
    if not settings:
        return {"ok": None, "message": "no HTTP smoke configured for this app"}
    mount = spec.get("mount") or {}
    port = mount.get("port")
    if not port:
        return {"ok": False, "message": "proxy mount needs a port for HTTP smoke"}

    commands = spec.get("commands") or {}
    command = settings.get("command") or commands.get("preview") or mount.get("cmd")
    if not command:
        return {"ok": False, "message": "proxy mount needs commands.preview or mount.cmd for HTTP smoke"}
    rendered = _render_smoke_template(cfg, spec, app, src, str(command))
    root = Path(spec.get("root") or cfg["repo_root"])
    timeout = float(settings.get("timeout") or 5.0)
    path = settings["path"]
    url = path if path.startswith(("http://", "https://")) else f"http://127.0.0.1:{port}{path}"
    env = {**os.environ, "PORT": str(port), "CURIATOR_APP": app}

    with tempfile.TemporaryDirectory(prefix="curiator-http-smoke-") as tmp:
        out_path = Path(tmp) / "stdout.log"
        err_path = Path(tmp) / "stderr.log"
        with out_path.open("wb") as out, err_path.open("wb") as err:
            try:
                proc = subprocess.Popen(shlex.split(rendered), cwd=root, env=env, stdout=out, stderr=err)
            except OSError as exc:
                return {"ok": False, "message": f"could not start HTTP smoke command: {exc}", "command": rendered}

            try:
                deadline = time.monotonic() + timeout
                last_error = "not attempted"
                while time.monotonic() < deadline:
                    code = proc.poll()
                    if code is not None:
                        last_error = f"process exited with code {code}"
                        break
                    try:
                        with urllib.request.urlopen(url, timeout=0.25) as response:
                            status = getattr(response, "status", 200)
                            if 200 <= int(status) < 400:
                                return {
                                    "ok": True,
                                    "message": f"HTTP {status}",
                                    "url": url,
                                    "command": rendered,
                                }
                            last_error = f"HTTP {status}"
                    except urllib.error.HTTPError as exc:
                        last_error = f"HTTP {exc.code}"
                    except OSError as exc:
                        last_error = str(exc)
                    time.sleep(0.1)
                stderr = _tail(err_path)
                stdout = _tail(out_path)
                detail = last_error
                if stderr:
                    detail += f"; stderr: {stderr}"
                elif stdout:
                    detail += f"; stdout: {stdout}"
                return {
                    "ok": False,
                    "message": detail,
                    "url": url,
                    "command": rendered,
                    "timeout": timeout,
                }
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2)


def smoke_app(cfg: dict, app: str, src: str | None) -> tuple[bool, str]:
    spec = _app_spec(cfg, app) or {}
    rendered = smoke_command(cfg, spec, app, src)
    if rendered:
        root = spec.get("root") or Path(cfg["repo_root"])
        timeout, err = _smoke_timeout(cfg, spec)
        if err:
            return False, err
        try:
            r = subprocess.run(shlex.split(rendered), cwd=root, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            label = int(timeout) if timeout and float(timeout).is_integer() else timeout
            return False, f"timeout after {label}s"
        if r.returncode == 0:
            return True, "passed"
        return False, (r.stderr or r.stdout or f"exit {r.returncode}").strip()[:500]

    if src:
        p = Path(cfg["repo_root"]) / src
        if p.is_file() and p.suffix == ".py":
            return smoke_source(p)
        if p.is_dir():
            return True, "n/a (no smoke configured for directory source)"
    return True, "n/a (no smoke configured)"


def _path_changed_in(repo: Path, rel: str) -> bool:
    if rel in {"", "."}:
        return bool(_dirty_paths_in(repo))
    if _git_in(repo, "diff", "--quiet", "HEAD", "--", rel, check=False).returncode != 0:
        return True
    prefix = rel.rstrip("/") + "/"
    return any(p == rel or p.startswith(prefix) for p in _dirty_paths_in(repo))


def _path_changed(cfg: dict, rel: str) -> bool:
    return _path_changed_in(Path(cfg["repo_root"]), rel)


def _dirty_paths_in(repo: Path) -> list[str]:
    """Every modified / added / untracked path in the working tree (porcelain, rename-aware)."""
    out = []
    for line in _git_in(repo, "status", "--porcelain", check=False).stdout.splitlines():
        rel = line[3:]                                    # strip the 2-char status + its trailing space
        if " -> " in rel:                                 # a rename — take the destination path
            rel = rel.split(" -> ", 1)[1]
        rel = rel.strip().strip('"')
        if rel:
            out.append(rel)
    return out


def _dirty_tracked_paths_in(repo: Path) -> list[str]:
    """Modified/deleted tracked paths only; excludes untracked runtime files by construction."""
    out = []
    for line in _git_in(repo, "status", "--porcelain", "--untracked-files=no", check=False).stdout.splitlines():
        rel = line[3:]
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        rel = rel.strip().strip('"')
        if rel:
            out.append(rel)
    return out


def _dirty_paths(cfg: dict) -> list[str]:
    return _dirty_paths_in(Path(cfg["repo_root"]))


def _extra_paths_in(repo: Path, globs: list[str], exclude: set[str]) -> list[str]:
    """Working-tree changes matching `globs` (dependency manifests by default), so an elevated run that
    also edits e.g. requirements.txt rides in the SAME commit instead of dangling. Excludes the source +
    ledger (staged separately). Returns [] when globs is empty (the strict source+ledger-only policy)."""
    if not globs:
        return []
    out: list[str] = []
    for rel in _dirty_paths_in(repo):
        if rel in exclude or rel in out:
            continue
        if any(fnmatch.fnmatch(rel, g) for g in globs):
            out.append(rel)
    return out


def _extra_paths(cfg: dict, globs: list[str], exclude: set[str]) -> list[str]:
    return _extra_paths_in(Path(cfg["repo_root"]), globs, exclude)


def _general_collection_paths(cfg: dict, fb: dict | None, exclude: set[str]) -> list[str]:
    """Dirty collection files that should ride with a collection-level ◆ General app/gallery run."""
    if not fb:
        return []
    from .loop import adapters
    if not adapters.general_targets_collection(fb):
        return []
    globs = list(_GENERAL_COLLECTION_GLOBS)
    gallery = _gallery_relpath(cfg)
    if gallery:
        globs.append(gallery)
    return _extra_paths(cfg, globs, exclude)


def _trailers(cfg: dict, sha: str) -> dict:
    body = _git(cfg, "show", "-s", "--format=%B", sha).stdout
    out = {}
    for line in body.splitlines():
        m = re.match(r"^([A-Za-z][A-Za-z-]+):\s*(.+)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def _agent_label(cfg: dict) -> str:
    agent = cfg.get("agent", {}) or {}
    return str(agent.get("model") or agent.get("adapter") or "headless-cc")


def _nested_memory_repos(root: Path) -> list[Path]:
    """Independent git repos nested under the current memory, deepest first for gitlink parents."""
    repos: list[Path] = []
    for dirpath, dirnames, _filenames in os.walk(root):
        path = Path(dirpath)
        if path == root:
            dirnames[:] = [d for d in dirnames if d != ".git"]
            continue
        if ".git" in dirnames and _is_git_toplevel(path):
            repos.append(path.resolve())
            dirnames[:] = [d for d in dirnames if d != ".git"]
            continue
        if ".git" in dirnames:
            dirnames.remove(".git")
    return sorted(set(repos), key=lambda p: len(p.relative_to(root).parts), reverse=True)


def _memory_label(root: Path, repo: Path) -> str:
    rel = repo.resolve().relative_to(root.resolve()).as_posix()
    if rel == ".planning":
        return "planning"
    return rel


def _commit_nested_memory_repo(
    cfg: dict,
    app: str,
    feedback_id: str,
    *,
    repo: Path,
    summary: str,
    comment: str,
    stars,
    status: str,
) -> dict:
    root = Path(cfg["repo_root"]).resolve()
    label = _memory_label(root, repo)
    paths = _dirty_tracked_paths_in(repo)
    if not paths:
        return {"committed": False, "reason": "no tracked changes", "repo": str(repo)}

    _git_in(repo, "add", "-u", "--", *paths)
    if _git_in(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return {"committed": False, "reason": "nothing staged in nested memory", "repo": str(repo)}

    changed_desc = f"updated tracked paths in {label}: {', '.join(paths[:8])}"
    if len(paths) > 8:
        changed_desc += f", ... ({len(paths) - 8} more)"
    if status == "awaiting_approval":
        changed_desc = f"planning note in {label}: {', '.join(paths[:8])}"

    msg = _build_message(label, summary, comment, stars, changed_desc, "n/a (memory-only)").replace("{fid}", feedback_id)
    msg += f"{_MEMORY_TRAILER}: {label}\n"
    msg += f"Co-Authored-By: curiator[{_agent_label(cfg)}] <noreply@curiator.dev>\n"
    git = cfg.get("git", {}) or {}
    commit_args = ["commit", "-m", msg] + (["-s"] if git.get("signoff", True) else [])
    _git_in(repo, *commit_args)
    sha = _git_in(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    branch = _git_in(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return {
        "committed": True,
        "sha": sha,
        "branch": branch,
        "repo": str(repo),
        "memory": label,
        "paths": paths,
    }


def _commit_nested_memories(
    cfg: dict,
    app: str,
    feedback_id: str,
    *,
    summary: str,
    comment: str,
    stars,
    status: str,
) -> list[dict]:
    root = Path(cfg["repo_root"]).resolve()
    commits = []
    for repo in _nested_memory_repos(root):
        res = _commit_nested_memory_repo(
            cfg,
            app,
            feedback_id,
            repo=repo,
            summary=summary,
            comment=comment,
            stars=stars,
            status=status,
        )
        if res.get("committed"):
            commits.append(res)
    return commits


def _build_message(app, summary, comment, stars, changed_desc, smoke) -> str:
    star = ("★" * int(stars)) if stars else "—"
    return (
        f"curator({app}): {summary}\n\n"
        f'Feedback: "{(comment or "").strip()}"   ({star})\n'
        f"Changed: {changed_desc}      Smoke-test: {smoke}\n\n"
        f"{_APP_TRAILER}: {app}\n"
        f"{_FEEDBACK_TRAILER}: {{fid}}\n"   # fid filled by caller (kept template-free of the id var)
    )


def _commit_nested_app_repo(
    cfg: dict,
    app: str,
    feedback_id: str,
    *,
    repo: Path,
    source_rel: str,
    summary: str,
    comment: str,
    stars,
    status: str,
    smoke: str,
) -> dict:
    """Commit an imported/nested app repository before the collection ledger commit.

    Collection git can only record the nested repo's gitlink. The app source change must therefore be
    committed inside the app repo first; the collection commit then records the new gitlink plus the
    ledger/reply.
    """
    git = cfg.get("git", {}) or {}
    paths = [source_rel]
    exclude = {source_rel}
    extra = [] if source_rel == "." else _extra_paths_in(repo, git.get("also_commit", _DEFAULT_ALSO_COMMIT), exclude)
    paths.extend(extra)
    _add_paths_in(repo, paths)
    if _git_in(repo, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return {"committed": False, "reason": "nothing staged in nested app repo"}

    changed_desc = f"edited {source_rel}"
    if extra:
        changed_desc += f" (+{', '.join(extra)})"
    if status == "awaiting_approval":
        changed_desc = "plan only" if source_rel == "." and not extra else changed_desc

    msg = _build_message(app, summary, comment, stars, changed_desc, smoke).replace("{fid}", feedback_id)
    from_email = None
    led = ledger.load(cfg)
    for item in led.get(app, []):
        if item.get("id") == feedback_id and item.get("author") != "claude":
            from_email = (item.get("user") or {}).get("email")
            break
    if from_email:
        msg += f"Feedback-From: {from_email}\n"
    msg += f"Co-Authored-By: curiator[{_agent_label(cfg)}] <noreply@curiator.dev>\n"
    commit_args = ["commit", "-m", msg] + (["-s"] if git.get("signoff", True) else [])
    _git_in(repo, *commit_args)
    sha = _git_in(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    branch = _git_in(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return {
        "committed": True,
        "sha": sha,
        "branch": branch,
        "repo": str(repo),
        "paths": paths,
    }


# ───────────────────────────── commit per run ─────────────────────────────
def commit_run(cfg: dict, app: str, feedback_id: str, *, status: str, note_text: str) -> dict:
    """One atomic commit for an agent run: the source edit (if any) + the ledger (the reply + status).
    Smoke-tests a changed source first (fail ⇒ revert the edit, no commit). Returns a result dict with
    `committed` and either `sha` or `reason`."""
    git = cfg.get("git", {}) or {}
    with _lock(cfg):
        if not is_repo(cfg):
            return {"committed": False, "reason": "not a git repo"}
        led = ledger.load(cfg)
        fb = next((e for e in led.get(app, [])
                   if e.get("id") == feedback_id and e.get("author") != "claude"), None)
        comment, stars = (fb or {}).get("comment", ""), (fb or {}).get("stars")

        spec = _app_spec(cfg, app) or {}
        src = spec.get("source_rel")
        nested_repo = _nested_app_repo(cfg, spec) if app != _GENERAL_KEY and spec else None
        nested_source = _rel_to(spec.get("source"), nested_repo) if nested_repo else None
        parent_stage_src = spec.get("root_rel") if nested_repo and nested_source else src
        nested_commit: dict | None = None
        changed = bool(src) and (
            _path_changed_in(nested_repo, nested_source)
            if nested_repo and nested_source
            else _path_changed(cfg, src)
        )
        smoke = "n/a (no source change)"
        summary = (note_text or "").strip().splitlines()[0][:72] if note_text else f"feedback on {app}"
        if changed:
            ok, msg = smoke_app(cfg, app, src)
            if not ok:
                if nested_repo and nested_source:
                    _git_in(nested_repo, "checkout", "--", nested_source)
                else:
                    _git(cfg, "checkout", "--", src)         # never commit a broken app
                return {"committed": False, "reason": f"smoke-test failed, reverted edit: {msg}"}
            smoke = msg
            if nested_repo and nested_source:
                nested_commit = _commit_nested_app_repo(
                    cfg,
                    app,
                    feedback_id,
                    repo=nested_repo,
                    source_rel=nested_source,
                    summary=summary,
                    comment=comment,
                    stars=stars,
                    status=status,
                    smoke=smoke,
                )
                if not nested_commit.get("committed"):
                    return {"committed": False, "reason": nested_commit.get("reason", "nested app repo was not committed")}
        if changed:
            changed_desc = f"edited {src}"
            if nested_commit:
                changed_desc += f" (nested app {Path(nested_commit['repo']).name}@{nested_commit['sha']})"
        else:
            changed_desc = "plan only" if status == "awaiting_approval" else "ack / no source change"

        ledger_rel = _ledger_relpath(cfg)
        exclude = {parent_stage_src or "", ledger_rel}
        general_extra = _general_collection_paths(cfg, fb, exclude) if app == _GENERAL_KEY else []
        exclude.update(general_extra)
        extra = general_extra + _extra_paths(cfg, git.get("also_commit", _DEFAULT_ALSO_COMMIT), exclude)
        if extra:
            changed_desc += f" (+{', '.join(extra)})"     # dependency manifests captured in the same commit

        ensure_branch(cfg, git.get("branch"))
        paths = ([parent_stage_src] if changed and parent_stage_src else []) + (
            [ledger_rel] if git.get("include_ledger", False) else []
        ) + extra
        if paths:
            _add_paths(cfg, paths, ledger_rel)
        root_committed = _git(cfg, "diff", "--cached", "--quiet", check=False).returncode != 0
        result: dict = {"committed": False}
        if root_committed:
            msg = _build_message(app, summary, comment, stars, changed_desc, smoke).replace("{fid}", feedback_id)
            from_email = ((fb or {}).get("user") or {}).get("email")
            if from_email:
                msg += f"Feedback-From: {from_email}\n"       # provenance → the git record (reputation substrate)
            msg += f"Co-Authored-By: curiator[{_agent_label(cfg)}] <noreply@curiator.dev>\n"
            commit_args = ["commit", "-m", msg] + (["-s"] if git.get("signoff", True) else [])
            _git(cfg, *commit_args)
            sha = _git(cfg, "rev-parse", "--short", "HEAD").stdout.strip()
            result.update({"committed": True, "sha": sha, "branch": current_branch(cfg)})
        if nested_commit:
            result["app_commits"] = [nested_commit]
        memory_commits = _commit_nested_memories(
            cfg,
            app,
            feedback_id,
            summary=summary,
            comment=comment,
            stars=stars,
            status=status,
        )
        if memory_commits:
            result["committed"] = True
            result["memory_commits"] = memory_commits
        if not result["committed"]:
            result["reason"] = "nothing staged to commit"
        return result


# ───────────────────────────── revert ─────────────────────────────
def find_commit(cfg: dict, feedback_id: str) -> str | None:
    r = _git(cfg, "log", "--all", f"--grep={_FEEDBACK_TRAILER}: {feedback_id}", "-n", "1", "--format=%H", check=False)
    out = r.stdout.strip().splitlines()
    return out[0] if out else None


def revert_feedback(cfg: dict, target: str, reason: str = "manual revert") -> dict:
    """Undo a curator commit WITHOUT erasing the record: restore the source to its pre-fix state, append
    a fresh ⚙ ledger note (the original reply stays), and commit that as its own `curator(<app>): revert`.
    `target` is a short/long SHA or a feedback id."""
    git = cfg.get("git", {}) or {}
    with _lock(cfg):
        if not is_repo(cfg):
            return {"ok": False, "reason": "not a git repo"}
        sha = target if (re.fullmatch(r"[0-9a-f]{7,40}", target)
                         and _git(cfg, "cat-file", "-e", target, check=False).returncode == 0) else find_commit(cfg, target)
        if not sha:
            return {"ok": False, "reason": f"no curator commit found for '{target}'"}
        tr = _trailers(cfg, sha)
        app, fid = tr.get(_APP_TRAILER), tr.get(_FEEDBACK_TRAILER)
        short = _git(cfg, "rev-parse", "--short", sha).stdout.strip()
        if not app:
            return {"ok": False, "reason": f"{short} is not a curator commit (no {_APP_TRAILER} trailer)"}

        src = source_for(cfg, app)
        files = _git(cfg, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).stdout.split()
        reverted_source = False
        if src and src in files:
            _git(cfg, "checkout", f"{sha}~1", "--", src)     # source as it was BEFORE the fix
            ok, msg = smoke_app(cfg, app, src)
            if not ok:
                _git(cfg, "checkout", "--", src)             # abort: restore working copy
                return {"ok": False, "reason": f"reverted source fails smoke-test: {msg}"}
            reverted_source = True

        note = f"↩ reverted `{short}`" + (f" — {reason}" if reason else "")
        ledger.add_system_note(cfg, app, note, reply_to=[fid] if fid else [])
        if fid:
            ledger.set_status(cfg, app, [fid], "reverted")

        ensure_branch(cfg, git.get("branch"))
        ledger_rel = _ledger_relpath(cfg)
        paths = ([src] if reverted_source else []) + ([ledger_rel] if git.get("include_ledger", False) else [])
        _add_paths(cfg, paths, ledger_rel)
        if _git(cfg, "diff", "--cached", "--quiet", check=False).returncode == 0:
            return {"ok": False, "reason": "nothing to revert/commit"}
        msg = (f"curator({app}): revert {short}\n\n"
               f"Reverted: {short}   Reason: {reason}\n\n"
               f"{_APP_TRAILER}: {app}\n{_FEEDBACK_TRAILER}: {fid or '-'}\n")
        _git(cfg, "commit", "-m", msg, *(["-s"] if git.get("signoff", True) else []))
        newsha = _git(cfg, "rev-parse", "--short", "HEAD").stdout.strip()
        return {"ok": True, "app": app, "feedback": fid, "reverted": short,
                "reverted_source": reverted_source, "sha": newsha}


# ───────────────────────────── reflect → LESSONS.md ─────────────────────────────
def _reflect_repo(repo: Path) -> str:
    """Summarize the curator's git history (curator(*) commits + reverts) into LESSONS.md content,
    grouped by app — what stuck vs what got reverted. Each fresh one-shot loads it (cross-item memory)."""
    fmt = "%H%x1f%s%x1f%b%x1e"
    raw = _git_in(repo, "log", "--all", f"--grep={_APP_TRAILER}:", f"--format={fmt}", check=False).stdout
    reverted_shorts, by_app = set(), {}
    records = []
    for chunk in (c for c in raw.split("\x1e") if c.strip()):
        h, subj, body = (chunk.strip().split("\x1f") + ["", ""])[:3]
        tr = {m.group(1): m.group(2).strip()
              for line in body.splitlines() if (m := re.match(r"^([A-Za-z][A-Za-z-]+):\s*(.+)$", line.strip()))}
        app = tr.get(_APP_TRAILER)
        if not app:
            continue
        is_revert = subj.lower().startswith(f"curator({app}): revert")
        if is_revert and (rm := re.search(r"Reverted:\s*([0-9a-f]{7,40})", body)):
            reverted_shorts.add(rm.group(1))
        records.append((h[:7], app, subj, tr.get(_FEEDBACK_TRAILER, ""), is_revert))
    for short, app, subj, fid, is_revert in records:
        by_app.setdefault(app, []).append((short, subj, fid, is_revert))

    out = ["# LESSONS.md — distilled from the curator's git history", "",
           "Auto-generated by `curiator reflect` from `curator(*)` commits. Each fresh agent run loads "
           "this for cross-item context (what stuck, what got reverted) — memory without a live session.", ""]
    if not by_app:
        out.append("_No curator commits yet._")
    for app in sorted(by_app):
        out.append(f"## {app}")
        for short, subj, fid, is_revert in by_app[app]:
            if is_revert:
                mark = "↩ revert"
            elif short in reverted_shorts:
                mark = "✗ reverted-later"
            else:
                mark = "✓ stuck"
            out.append(f"- {mark} · `{short}` · {subj}" + (f"  _(feedback {fid})_" if fid else ""))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def reflect(cfg: dict) -> str:
    return _reflect_repo(Path(cfg["repo_root"]))


def write_lessons(cfg: dict) -> Path:
    p = Path(cfg["repo_root"]) / "LESSONS.md"
    p.write_text(reflect(cfg))
    return p


def _repo_has_curator_history(repo: Path) -> bool:
    raw = _git_in(repo, "log", "--all", f"--grep={_APP_TRAILER}:", "--format=%H", check=False)
    return bool(raw.stdout.strip())


def write_all_lessons(cfg: dict) -> list[Path]:
    """Write LESSONS.md for the root memory and each nested memory with curator history.

    Existing callers that want the historical single-repo behavior should keep using write_lessons().
    The CLI uses this broader pass so independent memories such as .planning can keep their own
    reflection instead of being folded into the product repo's LESSONS.md.
    """
    root = Path(cfg["repo_root"]).resolve()
    paths = [write_lessons(cfg)]
    for repo in _nested_memory_repos(root):
        p = repo / "LESSONS.md"
        if not p.exists() and not _repo_has_curator_history(repo):
            continue
        p.write_text(_reflect_repo(repo))
        paths.append(p)
    return paths
