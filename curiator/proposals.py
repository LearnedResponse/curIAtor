"""Git worktree backed proposals for the opt-in ``git.branch: per-run`` mode.

The accepted branch stays mounted from the canonical checkout. Each feedback run gets a
``curiator/run/<feedback_id>`` branch and an ignored worktree. A completed run is represented by
Git refs under ``refs/curiator/proposals/``; the shell derives its preview from those refs and the
matching worktree, so there is no second database of proposal state.
"""
from __future__ import annotations

import copy
import fnmatch
import re
import shlex
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import ledger
from .config import app_spec, app_specs, mount_entries


class ProposalError(RuntimeError):
    """A proposal operation cannot be completed without risking accepted state."""


_STATES = ("working", "open", "accepted", "rejected", "superseded")
_BRANCH_PREFIX = "curiator/run/"
_REF_PREFIX = "refs/curiator/proposals"
_FEEDBACK_TRAILER = "Curiator-Feedback"
_APP_TRAILER = "Curiator-App"
_DEFAULT_ALSO_COMMIT = [
    "requirements.txt", "requirements/*.txt", "constraints.txt",
    "pyproject.toml", "setup.cfg", "setup.py",
    "Pipfile", "Pipfile.lock", "poetry.lock",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
]


def enabled(cfg: dict, app: str | None = None) -> bool:
    return (cfg.get("git") or {}).get("branch") == "per-run" and app != "__general__"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ProposalError(f"git {' '.join(args)} failed in {repo}: {detail}")
    return result


def _ref_app(app: str) -> str:
    return urllib.parse.quote(str(app), safe="._-")


def _unref_app(value: str) -> str:
    return urllib.parse.unquote(value)


def branch_name(feedback_id: str) -> str:
    if not re.fullmatch(r"[0-9A-Za-z._-]+", str(feedback_id or "")):
        raise ProposalError(f"invalid feedback id for a proposal branch: {feedback_id!r}")
    return f"{_BRANCH_PREFIX}{feedback_id}"


def action_items(feedback_id: str) -> list[list[str]]:
    return [
        ["Approve", f"curiator-proposal:approve:{feedback_id}"],
        ["Reject", f"curiator-proposal:reject:{feedback_id}"],
    ]


def _state_ref(state: str, app: str, feedback_id: str) -> str:
    if state not in _STATES:
        raise ProposalError(f"unknown proposal state {state!r}")
    return f"{_REF_PREFIX}/{state}/{_ref_app(app)}/{feedback_id}"


def _base_ref(app: str, feedback_id: str) -> str:
    return f"{_REF_PREFIX}/base/{_ref_app(app)}/{feedback_id}"


def _repo_top(path: Path) -> Path:
    result = _git(path, "rev-parse", "--show-toplevel", check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise ProposalError(f"per-run mode requires app source inside a Git repository: {path}")
    return Path(result.stdout.strip()).resolve()


def _current_branch(repo: Path) -> str:
    result = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    return result.stdout.strip() or "HEAD"


def _dirty_paths(repo: Path) -> list[str]:
    result = _git(repo, "status", "--porcelain=v1", "-z")
    paths: list[str] = []
    fields = result.stdout.split("\0")
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        status = field[:2]
        path = field[3:] if len(field) > 3 else ""
        if status[0] in {"R", "C"} and index < len(fields):
            path = fields[index]
            index += 1
        if path:
            paths.append(path)
    return paths


def _repo_context(cfg: dict, app: str) -> dict:
    spec = app_spec(cfg, app)
    if not spec:
        raise ProposalError(f"unknown app {app!r}")
    root = Path(spec.get("root") or cfg["repo_root"]).resolve()
    source = Path(spec.get("source") or root).resolve()
    repo = _repo_top(root if root.exists() else source.parent)
    try:
        source_rel = source.relative_to(repo).as_posix() or "."
    except ValueError as exc:
        raise ProposalError(f"app {app!r} source is outside its owning Git repository: {source}") from exc
    collection = Path(cfg["repo_root"]).resolve()
    accepted = str((cfg.get("git") or {}).get("accepted_branch") or "main")
    try:
        parent_rel = repo.relative_to(collection).as_posix() or "."
    except ValueError:
        parent_rel = None
    return {
        "app": app,
        "spec": spec,
        "repo": repo,
        "source": source,
        "source_rel": source_rel,
        "collection": collection,
        "parent_rel": parent_rel,
        "accepted_branch": accepted,
    }


def _app_group(cfg: dict, app: str) -> str:
    spec = app_spec(cfg, app) or {}
    return str(spec.get("app_name") or spec.get("name") or app)


def _worktree_base(cfg: dict) -> Path:
    if cfg.get("state_dir"):
        return Path(cfg["state_dir"]).resolve() / "proposal-worktrees"
    return Path(cfg["repo_root"]).resolve() / ".curiator" / "worktrees"


def worktree_path(cfg: dict, app: str, feedback_id: str) -> Path:
    safe_app = re.sub(r"[^A-Za-z0-9._-]+", "_", app).strip("._") or "app"
    return _worktree_base(cfg) / safe_app / feedback_id


def _exclude_runtime(cfg: dict) -> None:
    """Keep in-collection worktrees out of the accepted checkout without editing tracked files."""
    collection = Path(cfg["repo_root"]).resolve()
    git_dir = _git(collection, "rev-parse", "--git-dir", check=False)
    if git_dir.returncode != 0:
        return
    runtime = _worktree_base(cfg)
    try:
        rel = runtime.relative_to(collection).as_posix().rstrip("/") + "/"
    except ValueError:
        return
    raw_git_dir = Path(git_dir.stdout.strip())
    if not raw_git_dir.is_absolute():
        raw_git_dir = collection / raw_git_dir
    exclude = raw_git_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    lines = {line.strip() for line in existing.splitlines()}
    if rel not in lines:
        with exclude.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(rel + "\n")


def _worktrees(repo: Path) -> list[dict]:
    result = _git(repo, "worktree", "list", "--porcelain")
    rows: list[dict] = []
    current: dict = {}
    for line in [*result.stdout.splitlines(), ""]:
        if not line:
            if current:
                rows.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return rows


def _branch_worktree(repo: Path, branch: str) -> Path | None:
    full = f"refs/heads/{branch}"
    for row in _worktrees(repo):
        if row.get("branch") == full and row.get("worktree"):
            return Path(row["worktree"]).resolve()
    return None


def _ref_sha(repo: Path, ref: str) -> str | None:
    result = _git(repo, "rev-parse", "--verify", "--quiet", ref, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _delete_ref(repo: Path, ref: str) -> None:
    _git(repo, "update-ref", "-d", ref, check=False)


def _set_state(repo: Path, app: str, feedback_id: str, state: str, sha: str) -> None:
    for old in _STATES:
        _delete_ref(repo, _state_ref(old, app, feedback_id))
    _git(repo, "update-ref", _state_ref(state, app, feedback_id), sha)


def _state_rows(repo: Path, state: str | None = None) -> list[dict]:
    states = [state] if state else list(_STATES)
    rows: list[dict] = []
    for name in states:
        prefix = f"{_REF_PREFIX}/{name}/"
        result = _git(
            repo,
            "for-each-ref",
            "--format=%(refname)%00%(objectname)%00%(creatordate:unix)",
            prefix,
        )
        for line in result.stdout.splitlines():
            ref, sha, created = (line.split("\0") + ["", ""])[:3]
            suffix = ref[len(prefix):]
            app_part, sep, feedback_id = suffix.rpartition("/")
            if not sep:
                continue
            rows.append({
                "state": name,
                "app": _unref_app(app_part),
                "feedback_id": feedback_id,
                "sha": sha,
                "created": int(created or 0),
                "ref": ref,
            })
    return rows


def _remove_worktree(repo: Path, branch: str) -> None:
    path = _branch_worktree(repo, branch)
    if not path:
        return
    if _dirty_paths(path):
        raise ProposalError(f"refusing to remove dirty proposal worktree: {path}")
    _git(repo, "worktree", "remove", str(path))


def _notify_shell(cfg: dict, app: str) -> None:
    from .web_paths import local_shell_url

    url = local_shell_url(cfg, path=f"/reload/{urllib.parse.quote(app, safe='')}")
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=1).close()
    except (urllib.error.URLError, OSError):
        pass


def _transition_ledger(cfg: dict, app: str, feedback_id: str, status: str, note: str) -> None:
    items = ledger.load(cfg).get(app, [])
    if not any(row.get("id") == feedback_id and row.get("kind") != "system" for row in items):
        return
    ledger.add_system_note(cfg, app, note, reply_to=[feedback_id], agent="curiator proposals")
    ledger.set_status(cfg, app, [feedback_id], status)


def _supersede_open(cfg: dict, context: dict, feedback_id: str) -> list[str]:
    superseded: list[str] = []
    group = _app_group(cfg, context["app"])
    for row in _state_rows(context["repo"], "open"):
        if row["feedback_id"] == feedback_id or _app_group(cfg, row["app"]) != group:
            continue
        _set_state(context["repo"], row["app"], row["feedback_id"], "superseded", row["sha"])
        _remove_worktree(context["repo"], branch_name(row["feedback_id"]))
        _transition_ledger(
            cfg,
            row["app"],
            row["feedback_id"],
            "rejected",
            f"Proposal superseded by newer same-app run `{feedback_id}`; branch retained for inspection.",
        )
        superseded.append(row["feedback_id"])
    return superseded


def _overlay_config(cfg: dict, app: str, worktree: Path) -> dict:
    overlay = copy.deepcopy(cfg)
    matched = False
    for app_cfg in overlay.get("apps") or []:
        names = {name for name, _mount in mount_entries(app_cfg)}
        if app in names or app == app_cfg.get("name"):
            app_cfg["root"] = str(worktree)
            matched = True
            break
    if not matched:
        raise ProposalError(f"cannot map app {app!r} into its proposal worktree")
    return overlay


def _assert_accepted_checkout(context: dict) -> str:
    repo = context["repo"]
    accepted = context["accepted_branch"]
    accepted_ref = f"refs/heads/{accepted}"
    accepted_sha = _ref_sha(repo, accepted_ref)
    if not accepted_sha:
        raise ProposalError(f"accepted branch {accepted!r} does not exist in {repo}")
    current = _current_branch(repo)
    if current != accepted:
        raise ProposalError(
            f"accepted checkout must be on {accepted!r} before per-run work (currently {current!r} in {repo})"
        )
    dirty = _dirty_paths(repo)
    if dirty:
        shown = ", ".join(dirty[:8])
        raise ProposalError(f"accepted checkout is dirty; commit or stash before per-run work: {shown}")
    return accepted_sha


def prepare_task_config(cfg: dict, app: str, entry: dict) -> tuple[dict, dict | None]:
    """Create/reuse a run worktree and return a task-only config that points this app at it."""
    if not enabled(cfg, app):
        return cfg, None
    if not (cfg.get("git") or {}).get("commit"):
        raise ProposalError("git.branch: per-run requires git.commit: true")
    if (cfg.get("git") or {}).get("include_ledger"):
        raise ProposalError(
            "git.branch: per-run requires git.include_ledger: false; proposal refs and the live SQLite "
            "ledger advance independently until approval"
        )
    from . import dependencies

    try:
        graph = dependencies.normalize(cfg)
    except dependencies.DependencyError as exc:
        raise ProposalError(f"cannot prepare proposal with an invalid dependency graph: {exc}") from exc
    if dependencies.writable_components(graph, app, entry):
        raise ProposalError(
            "per-run app proposals cannot grant writes to shared components; split the component change "
            "into its own accepted-state task first"
        )
    feedback_id = str(entry.get("id") or "")
    context = _repo_context(cfg, app)
    _exclude_runtime(cfg)
    accepted_sha = _assert_accepted_checkout(context)
    branch = branch_name(feedback_id)
    worktree = _branch_worktree(context["repo"], branch)
    branch_sha = _ref_sha(context["repo"], f"refs/heads/{branch}")
    target = worktree_path(cfg, app, feedback_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if worktree is None:
        if target.exists() and any(target.iterdir()):
            raise ProposalError(f"proposal worktree path already exists and is not registered: {target}")
        if branch_sha:
            _git(context["repo"], "worktree", "add", str(target), branch)
        else:
            _git(context["repo"], "worktree", "add", "-b", branch, str(target), context["accepted_branch"])
        worktree = target.resolve()
        branch_sha = _ref_sha(context["repo"], f"refs/heads/{branch}")
    if not branch_sha:
        raise ProposalError(f"proposal branch {branch!r} has no commit")
    if not _ref_sha(context["repo"], _base_ref(app, feedback_id)):
        _git(context["repo"], "update-ref", _base_ref(app, feedback_id), accepted_sha)
    superseded = _supersede_open(cfg, context, feedback_id)
    _set_state(context["repo"], app, feedback_id, "working", branch_sha)
    overlay = _overlay_config(cfg, app, worktree)
    proposal_spec = app_spec(overlay, app) or {}
    _notify_shell(cfg, app)
    return overlay, {
        "app": app,
        "feedback_id": feedback_id,
        "branch": branch,
        "base_sha": _ref_sha(context["repo"], _base_ref(app, feedback_id)),
        "repo": str(context["repo"]),
        "worktree": str(worktree),
        "root": proposal_spec.get("root"),
        "source": proposal_spec.get("source"),
        "superseded": superseded,
        "state": "working",
    }


def _allowed_path(path: str, source_rel: str, patterns: list[str]) -> bool:
    source = source_rel.rstrip("/")
    if source in {"", "."} or path == source or path.startswith(source + "/"):
        return True
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _run_smoke(cfg: dict, app: str) -> str:
    from . import gitmem

    spec = app_spec(cfg, app) or {}
    command = gitmem.smoke_command(cfg, spec, app, spec.get("source"))
    if not command:
        source = Path(spec.get("source") or "")
        if source.is_file() and source.suffix == ".py":
            ok, message = gitmem.smoke_source(source)
            if not ok:
                raise ProposalError(f"proposal smoke failed: {message}")
            return message
        return "n/a (no smoke configured)"
    raw_timeout = spec.get("smoke_timeout")
    if raw_timeout in (None, ""):
        raw_timeout = (cfg.get("smoke") or {}).get("timeout")
    timeout = float(raw_timeout) if raw_timeout not in (None, "") else None
    try:
        result = subprocess.run(
            shlex.split(command),
            cwd=spec.get("root") or cfg["repo_root"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProposalError(f"proposal smoke timed out after {exc.timeout}s") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"exit {result.returncode}").strip()[:500]
        raise ProposalError(f"proposal smoke failed: {detail}")
    return "passed"


def _cleanup_new_smoke_caches(worktree: Path, before: set[str]) -> None:
    """Remove only cache paths created by the smoke command, never pre-existing agent output."""
    after = set(_dirty_paths(worktree))
    cache_names = {"__pycache__", ".pytest_cache", ".ruff_cache"}
    for rel in sorted(after - before, key=lambda value: len(Path(value).parts), reverse=True):
        path = worktree / rel
        if not any(part in cache_names for part in Path(rel).parts) and path.suffix not in {".pyc", ".pyo"}:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def finish(cfg: dict, app: str, feedback_id: str, note_text: str) -> dict:
    """Smoke, commit, and publish a run branch as the current live proposal."""
    if not enabled(cfg, app):
        raise ProposalError("per-run proposal mode is not enabled")
    context = _repo_context(cfg, app)
    branch = branch_name(feedback_id)
    worktree = _branch_worktree(context["repo"], branch)
    if not worktree:
        raise ProposalError(f"proposal worktree is missing for {branch}")
    overlay = _overlay_config(cfg, app, worktree)
    proposal_spec = app_spec(overlay, app) or {}
    source = Path(proposal_spec.get("source") or worktree)
    source_rel = source.relative_to(worktree).as_posix() or "."
    dirty = _dirty_paths(worktree)
    if not dirty:
        raise ProposalError("proposal has no source changes to commit")
    patterns = list((cfg.get("git") or {}).get("also_commit", _DEFAULT_ALSO_COMMIT))
    outside = [path for path in dirty if not _allowed_path(path, source_rel, patterns)]
    if outside:
        raise ProposalError(
            "proposal changed paths outside its app source/manifest scope: " + ", ".join(outside[:8])
        )
    before_smoke = set(dirty)
    smoke = _run_smoke(overlay, app)
    _cleanup_new_smoke_caches(worktree, before_smoke)
    after_smoke = _dirty_paths(worktree)
    smoke_extra = [path for path in after_smoke if path not in before_smoke]
    if smoke_extra:
        raise ProposalError(
            "proposal smoke created uncommitted artifacts outside the run baseline: " + ", ".join(smoke_extra[:8])
        )
    from . import gitmem

    commit = gitmem._commit_nested_app_repo(  # noqa: SLF001 - shared commit schema, different worktree
        cfg,
        app,
        feedback_id,
        repo=worktree,
        source_rel=source_rel,
        summary=(note_text or "Proposal ready").strip().splitlines()[0][:72],
        comment=next(
            (
                row.get("comment", "") for row in ledger.load(cfg).get(app, [])
                if row.get("id") == feedback_id and row.get("kind") != "system"
            ),
            "",
        ),
        stars=next(
            (
                row.get("stars") for row in ledger.load(cfg).get(app, [])
                if row.get("id") == feedback_id and row.get("kind") != "system"
            ),
            None,
        ),
        status="awaiting_approval",
        smoke=smoke,
    )
    if not commit.get("committed"):
        raise ProposalError(commit.get("reason") or "proposal commit was not created")
    full_sha = _ref_sha(context["repo"], f"refs/heads/{branch}")
    if not full_sha:
        raise ProposalError("proposal commit exists but its branch ref is missing")
    _set_state(context["repo"], app, feedback_id, "open", full_sha)
    return {
        "ok": True,
        "app": app,
        "feedback_id": feedback_id,
        "branch": branch,
        "sha": commit["sha"],
        "base_sha": _ref_sha(context["repo"], _base_ref(app, feedback_id)),
        "worktree": str(worktree),
        "state": "open",
        "smoke": smoke,
    }


def abandon_empty(cfg: dict, app: str, feedback_id: str) -> None:
    """Retire the empty worktree created for a plan-only response."""
    if not enabled(cfg, app):
        return
    context = _repo_context(cfg, app)
    branch = branch_name(feedback_id)
    worktree = _branch_worktree(context["repo"], branch)
    if worktree and _dirty_paths(worktree):
        raise ProposalError("this per-run worktree has edits; finish it with --status done instead of a plan reply")
    sha = _ref_sha(context["repo"], f"refs/heads/{branch}")
    if sha:
        _set_state(context["repo"], app, feedback_id, "rejected", sha)
    _remove_worktree(context["repo"], branch)
    _notify_shell(cfg, app)


def preview_for_app(cfg: dict, app: str) -> dict | None:
    """Return the newest open proposal that should back this app/mount, derived from Git refs."""
    if not enabled(cfg, app):
        return None
    try:
        context = _repo_context(cfg, app)
    except ProposalError:
        return None
    group = _app_group(cfg, app)
    candidates = [
        row for row in _state_rows(context["repo"], "open")
        if _app_group(cfg, row["app"]) == group
    ]
    candidates.sort(key=lambda row: (row["created"], row["feedback_id"]), reverse=True)
    for row in candidates:
        branch = branch_name(row["feedback_id"])
        worktree = _branch_worktree(context["repo"], branch)
        if not worktree:
            continue
        head = _git(worktree, "rev-parse", "HEAD", check=False).stdout.strip()
        if head != row["sha"]:
            continue
        canonical_root = Path(context["spec"].get("root") or context["repo"]).resolve()
        canonical_source = Path(context["spec"].get("source") or canonical_root).resolve()
        try:
            root_rel = canonical_root.relative_to(context["repo"])
            source_rel = canonical_source.relative_to(context["repo"])
        except ValueError:
            continue
        return {
            **row,
            "branch": branch,
            "base_sha": _ref_sha(context["repo"], _base_ref(row["app"], row["feedback_id"])),
            "repo": str(context["repo"]),
            "worktree": str(worktree),
            "root": str((worktree / root_rel).resolve()),
            "source": str((worktree / source_rel).resolve()),
        }
    return None


def list_proposals(cfg: dict, app: str | None = None) -> list[dict]:
    """List proposal state from refs across configured owning repositories."""
    repos: dict[Path, set[str]] = {}
    for spec in app_specs(cfg):
        key = str(spec.get("name") or spec.get("app_name") or "")
        if not key or (app and key != app and spec.get("app_name") != app):
            continue
        try:
            context = _repo_context(cfg, key)
        except ProposalError:
            continue
        repos.setdefault(context["repo"], set()).add(key)
    rows: list[dict] = []
    for repo in repos:
        for row in _state_rows(repo):
            if app and row["app"] != app and _app_group(cfg, row["app"]) != _app_group(cfg, app):
                continue
            branch = branch_name(row["feedback_id"])
            worktree = _branch_worktree(repo, branch)
            rows.append({
                **row,
                "repo": str(repo),
                "branch": branch,
                "worktree": str(worktree) if worktree else None,
                "base_sha": _ref_sha(repo, _base_ref(row["app"], row["feedback_id"])),
            })
    rows.sort(key=lambda row: (row["created"], row["feedback_id"]), reverse=True)
    return rows


def _find_open(cfg: dict, app: str, feedback_id: str) -> tuple[dict, dict]:
    context = _repo_context(cfg, app)
    sha = _ref_sha(context["repo"], _state_ref("open", app, feedback_id))
    if not sha:
        raise ProposalError(f"no open proposal for {app}/{feedback_id}")
    return context, {
        "app": app,
        "feedback_id": feedback_id,
        "branch": branch_name(feedback_id),
        "sha": sha,
        "base_sha": _ref_sha(context["repo"], _base_ref(app, feedback_id)),
    }


def _commit_message(app: str, feedback_id: str, action: str) -> str:
    return (
        f"curator({app}): {action} proposal {feedback_id}\n\n"
        f"{_APP_TRAILER}: {app}\n"
        f"{_FEEDBACK_TRAILER}: {feedback_id}\n"
    )


def _smoke_canonical(cfg: dict, app: str) -> str:
    return _run_smoke(cfg, app)


def _commit_parent_gitlink(cfg: dict, context: dict, app: str, feedback_id: str) -> str | None:
    parent_rel = context.get("parent_rel")
    collection = context["collection"]
    if context["repo"] == collection or not parent_rel:
        return None
    if _git(collection, "diff", "--cached", "--quiet", check=False).returncode != 0:
        raise ProposalError("collection index already has staged changes; refusing to mix them with approval")
    _git(collection, "add", "--", parent_rel)
    paths = [parent_rel]
    if (cfg.get("git") or {}).get("include_ledger"):
        from . import gitmem

        ledger_rel = gitmem._ledger_relpath(cfg)  # noqa: SLF001 - same git-as-memory policy
        ledger.checkpoint(cfg)
        _git(collection, "add", "-f", "--", ledger_rel)
        paths.append(ledger_rel)
    if _git(collection, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return None
    args = ["commit", "-m", _commit_message(app, feedback_id, "approve")]
    if (cfg.get("git") or {}).get("signoff", True):
        args.append("-s")
    from .gitmem import _commit_identity_prefix  # noqa: PLC0415, SLF001

    _git(collection, *_commit_identity_prefix(collection), *args)
    return _git(collection, "rev-parse", "--short", "HEAD").stdout.strip()


def approve(cfg: dict, app: str, feedback_id: str, *, actor: str = "shell admin") -> dict:
    """Merge an open proposal into the accepted branch, aborting cleanly on conflict/smoke failure."""
    context, proposal = _find_open(cfg, app, feedback_id)
    _exclude_runtime(cfg)
    accepted_before = _assert_accepted_checkout(context)
    parent = context["collection"]
    if context["repo"] != parent and _git(parent, "diff", "--cached", "--quiet", check=False).returncode != 0:
        raise ProposalError("collection index already has staged changes; refusing proposal approval")
    message = _commit_message(app, feedback_id, "approve")
    from .gitmem import _commit_identity_prefix  # noqa: PLC0415, SLF001

    identity = _commit_identity_prefix(context["repo"])
    merge = _git(
        context["repo"],
        *identity, "merge", "--no-ff", "--no-commit", proposal["branch"],
        check=False,
    )
    if merge.returncode != 0:
        detail = (merge.stderr or merge.stdout).strip()[:700]
        conflicts = _git(
            context["repo"], "diff", "--name-only", "--diff-filter=U", check=False
        ).stdout.splitlines()
        _git(context["repo"], "merge", "--abort", check=False)
        failure = (
            f"conflicts with `{context['accepted_branch']}` in {', '.join(conflicts[:8])}"
            if conflicts
            else f"could not be merged into `{context['accepted_branch']}`"
        )
        ledger.add_system_note(
            cfg,
            app,
            f"Approval {failure}; Git aborted without changing accepted state. "
            f"Resolve or supersede the proposal. {detail}",
            reply_to=[feedback_id],
            actions=action_items(feedback_id),
            agent="curiator proposals",
        )
        raise ProposalError(f"proposal merge aborted without changing accepted state: {detail}")
    try:
        smoke = _smoke_canonical(cfg, app)
    except Exception as exc:
        _git(context["repo"], "merge", "--abort", check=False)
        ledger.add_system_note(
            cfg,
            app,
            f"Approval merged cleanly in a temporary index but the accepted-state smoke failed; "
            f"Git aborted without committing: {exc}",
            reply_to=[feedback_id],
            actions=action_items(feedback_id),
            agent="curiator proposals",
        )
        raise
    args = ["commit", "-m", message]
    if (cfg.get("git") or {}).get("signoff", True):
        args.append("-s")
    _git(context["repo"], *identity, *args)
    accepted_sha = _git(context["repo"], "rev-parse", "HEAD").stdout.strip()
    _set_state(context["repo"], app, feedback_id, "accepted", accepted_sha)
    _remove_worktree(context["repo"], proposal["branch"])
    note = (
        f"Proposal `{proposal['branch']}` approved by {actor} and merged into "
        f"`{context['accepted_branch']}` at `{accepted_sha[:8]}`."
    )
    ledger.add_system_note(cfg, app, note, reply_to=[feedback_id], agent="curiator proposals")
    ledger.set_status(cfg, app, [feedback_id], "done")
    parent_sha = _commit_parent_gitlink(cfg, context, app, feedback_id)
    _notify_shell(cfg, app)
    return {
        "ok": True,
        "action": "approved",
        "app": app,
        "feedback_id": feedback_id,
        "branch": proposal["branch"],
        "base_sha": proposal["base_sha"],
        "accepted_before": accepted_before,
        "accepted_sha": accepted_sha,
        "diverged": bool(proposal["base_sha"] and proposal["base_sha"] != accepted_before),
        "parent_sha": parent_sha,
        "smoke": smoke,
    }


def reject(
    cfg: dict,
    app: str,
    feedback_id: str,
    *,
    actor: str = "shell admin",
    reason: str = "",
) -> dict:
    context, proposal = _find_open(cfg, app, feedback_id)
    _set_state(context["repo"], app, feedback_id, "rejected", proposal["sha"])
    _remove_worktree(context["repo"], proposal["branch"])
    note = f"Proposal `{proposal['branch']}` rejected by {actor}; branch retained for inspection."
    if reason:
        note += f" Reason: {reason}"
    ledger.add_system_note(cfg, app, note, reply_to=[feedback_id], agent="curiator proposals")
    ledger.set_status(cfg, app, [feedback_id], "rejected")
    _notify_shell(cfg, app)
    return {
        "ok": True,
        "action": "rejected",
        "app": app,
        "feedback_id": feedback_id,
        "branch": proposal["branch"],
        "sha": proposal["sha"],
    }


def doctor_issues(cfg: dict) -> list[dict]:
    if not enabled(cfg):
        return []
    issues: list[dict] = []
    git = cfg.get("git") or {}
    if not git.get("commit"):
        issues.append({
            "severity": "error",
            "where": "git.branch",
            "message": "per-run mode requires git.commit: true",
        })
    if git.get("include_ledger"):
        issues.append({
            "severity": "error",
            "where": "git.include_ledger",
            "message": "per-run mode requires git.include_ledger: false",
        })
    accepted = str(git.get("accepted_branch") or "main")
    seen: set[Path] = set()
    for spec in app_specs(cfg):
        app = str(spec.get("name") or spec.get("app_name") or "<unknown>")
        try:
            context = _repo_context(cfg, app)
        except ProposalError as exc:
            issues.append({"severity": "error", "where": f"app {app} proposal", "message": str(exc)})
            continue
        if context["repo"] in seen:
            continue
        seen.add(context["repo"])
        if not _ref_sha(context["repo"], f"refs/heads/{accepted}"):
            issues.append({
                "severity": "error",
                "where": f"app {app} proposal",
                "message": f"accepted branch {accepted!r} does not exist in {context['repo']}",
            })
        elif _current_branch(context["repo"]) != accepted:
            issues.append({
                "severity": "warning",
                "where": f"app {app} proposal",
                "message": f"accepted checkout is not currently on {accepted!r}",
            })
    return issues


def proposal_note(result: dict) -> str:
    return (
        f"{result['branch']} is ready at {result['sha']} and is now the live preview. "
        "Approve to merge it into the accepted branch, or reject it while retaining the branch."
    )


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
