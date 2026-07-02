"""CLI handlers for release and hosted-playground preflight checks."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import load_config


_PUBLIC_RELEASE_GALLERIES = ("curiator-aviato", "curiator-ot", "curiator-geometry")
_OPTIONAL_RELEASE_GALLERIES = ("curiator-finance", "curiator-phylogenetics")
_PUBLIC_RELEASE_OWNER = "LearnedResponse"
_USER_ABS_PATH_RE = re.compile(
    r"(?<![\w.-])(?:/[A-Za-z0-9_.-]+)?/(?:home|Users)/[^\s'\"`]+|[A-Za-z]:[\\/]+Users[\\/]+[^\s'\"`]+"
)


def _cli_shared():
    from . import cli as cli_mod

    return cli_mod


def _git_output(cwd: Path, *args: str) -> str | None:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def _project_root(cwd: Path | None = None) -> Path:
    here = (cwd or Path.cwd()).resolve()
    out = _git_output(here, "rev-parse", "--show-toplevel")
    return Path(out).resolve() if out else here


def _git_text(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def _normalize_github_remote(url: str) -> str:
    raw = (url or "").strip()
    if raw.endswith(".git"):
        raw = raw[:-4]
    if raw.startswith("git@github.com:"):
        raw = "github.com/" + raw.split(":", 1)[1]
    elif raw.startswith("ssh://git@github.com/"):
        raw = "github.com/" + raw.split("ssh://git@github.com/", 1)[1]
    elif raw.startswith("https://github.com/"):
        raw = "github.com/" + raw.split("https://github.com/", 1)[1]
    elif raw.startswith("http://github.com/"):
        raw = "github.com/" + raw.split("http://github.com/", 1)[1]
    return raw.rstrip("/").lower()


def _origin_urls(repo: Path) -> list[str]:
    out = _git_text(repo, "remote", "get-url", "--all", "origin")
    return [line.strip() for line in out.splitlines() if line.strip()]


def _public_remote_result(repo: Path, name: str, owner: str) -> dict:
    expected = f"github.com/{owner}/{name}".lower()
    urls = _origin_urls(repo)
    normalized = [_normalize_github_remote(url) for url in urls]
    ok = expected in normalized
    if ok:
        message = "origin points at expected public repository"
    elif not urls:
        message = f"missing origin remote; expected github.com/{owner}/{name}"
    else:
        message = f"origin remote does not match expected github.com/{owner}/{name}"
    return {
        "ok": ok,
        "expected": f"github.com/{owner}/{name}",
        "origin": urls,
        "message": message,
    }


def _published_head_result(repo: Path) -> dict:
    head = _git_output(repo, "rev-parse", "HEAD") or ""
    short = _git_output(repo, "rev-parse", "--short", "HEAD") or head[:7]
    r = subprocess.run(["git", "ls-remote", "origin"], cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        detail = " ".join((r.stderr or r.stdout or f"git ls-remote exited {r.returncode}").split())
        return {
            "ok": False,
            "head": head,
            "short": short,
            "ref_count": 0,
            "matching_refs": [],
            "message": f"origin is not readable: {detail}",
        }
    matches = []
    ref_count = 0
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        ref_count += 1
        if parts[0] == head:
            matches.append(parts[1])
    ok = bool(matches)
    return {
        "ok": ok,
        "head": head,
        "short": short,
        "ref_count": ref_count,
        "matching_refs": matches,
        "message": (
            f"origin contains HEAD {short} at {', '.join(matches)}"
            if ok else
            f"origin is readable but does not contain HEAD {short}; push this gallery before release"
        ),
    }


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
_PUBLISH_RUNTIME_PREFIXES = ("feedback/shots/", "feedback/audio/", "feedback/tasks/", "feedback/replies/")
_PUBLISH_SQLITE_SIDECARS = ("feedback/app_feedback.sqlite-wal", "feedback/app_feedback.sqlite-shm")
_PUBLISH_CACHE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".cache"}
_PUBLISH_ENV_DIRS = {".venv", "venv", ".env"}
_PUBLISH_DEPENDENCY_DIRS = {"node_modules"}
_PUBLISH_LOCAL_FILES = {".DS_Store", ".coverage", "coverage.xml"}
_PUBLISH_LOG_FILES = {"npm-debug.log", "yarn-error.log", "pnpm-debug.log"}
_REQUIREMENTS_FILE_RE = re.compile(r"(^|/)(requirements[^/]*\.txt|constraints\.txt)$")
_REMOTE_DEPENDENCY_PREFIXES = (
    "bzr+",
    "git+",
    "hg+",
    "svn+",
    "git://",
    "http://",
    "https://",
    "ssh://",
)
_LOCAL_DEPENDENCY_PREFIXES = ("./", "../", "/", "file:")


def _looks_local_dependency_target(target: str) -> bool:
    return target.lower().startswith(_LOCAL_DEPENDENCY_PREFIXES)


def _is_local_dependency_reference(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    lower = stripped.lower()
    for option in ("-e", "--editable", "-f", "--find-links"):
        if lower.startswith(f"{option} "):
            parts = stripped.split(maxsplit=1)
            target = parts[1].strip() if len(parts) > 1 else ""
            lower_target = target.lower()
            if option in ("-e", "--editable"):
                return not lower_target.startswith(_REMOTE_DEPENDENCY_PREFIXES)
            return _looks_local_dependency_target(target)
        if lower.startswith(f"{option}="):
            target = stripped.split("=", 1)[1].strip()
            lower_target = target.lower()
            if option in ("-e", "--editable"):
                return not lower_target.startswith(_REMOTE_DEPENDENCY_PREFIXES)
            return _looks_local_dependency_target(target)
    if lower.startswith("-f") and len(stripped) > 2:
        return _looks_local_dependency_target(stripped[2:].strip())
    if " @ file:" in lower:
        return True
    if re.search(r"\s@\s*(?:\.\.?/|/|file:)", stripped):
        return True
    return _looks_local_dependency_target(stripped)


def _publish_artifact_message(rel: str) -> str | None:
    rel = rel.replace("\\", "/")
    parts = [p for p in rel.split("/") if p]
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
    if any(part in _PUBLISH_CACHE_DIRS for part in parts) or name.endswith((".pyc", ".pyo")):
        return "tracked interpreter/test cache; remove generated cache files before publishing examples"
    if any(part in _PUBLISH_ENV_DIRS for part in parts):
        return "tracked virtual environment directory; publish dependency manifests, not installed environments"
    if any(part in _PUBLISH_DEPENDENCY_DIRS for part in parts):
        return "tracked dependency install directory; publish manifests/locks, not node_modules"
    if name in _PUBLISH_LOCAL_FILES or name in _PUBLISH_LOG_FILES:
        return "tracked local generated file; remove local cache, coverage, or debug artifacts before publishing"
    return None


def _publish_artifact_hits(repo: Path) -> list[dict]:
    hits: list[dict] = []
    for rel in _tracked_files(repo):
        message = _publish_artifact_message(rel)
        if message:
            hits.append({"file": rel, "message": message})
        if _REQUIREMENTS_FILE_RE.search(rel.replace("\\", "/")):
            path = repo / rel
            if not path.is_file():
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for line_no, line in enumerate(lines, start=1):
                if _is_local_dependency_reference(line):
                    hits.append({
                        "file": rel,
                        "line": line_no,
                        "message": (
                            "tracked local editable/path dependency; public examples should depend on "
                            "published packages or VCS URLs"
                        ),
                    })
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
        "public_remote": None,
        "published_head": None,
        "doctor": {"ok": False, "errors": 0, "warnings": 0, "issues": []},
        "smoke": {"ok": None, "results": []},
    }


def _release_preflight_one(
    gallery: Path,
    *,
    run_smoke: bool,
    http_smoke: bool,
    allow_dirty: bool,
    needles: tuple[str, ...],
    strict: bool,
    require_public_remotes: bool = False,
    public_remote_owner: str = _PUBLIC_RELEASE_OWNER,
    require_published_head: bool = False,
) -> dict:
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
    if require_public_remotes:
        result["public_remote"] = _public_remote_result(repo, repo.name, public_remote_owner)
    if require_published_head:
        result["published_head"] = _published_head_result(repo)

    try:
        cfg = _load_config_for_gallery(gallery)
        cli_mod = _cli_shared()
        issues = cli_mod._doctor_issues(cfg)
        errors = [i for i in issues if i.get("severity") == "error"]
        warnings = [i for i in issues if i.get("severity") == "warning"]
        result["doctor"] = {
            "ok": not errors,
            "errors": len(errors),
            "warnings": len(warnings),
            "issues": issues,
        }
        if run_smoke:
            smoke = cli_mod._smoke_results(cfg, http=http_smoke)
            result["smoke"] = {"ok": all(r["ok"] for r in smoke), "results": smoke}
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"

    result["ok"] = (
        not result.get("error")
        and result["doctor"]["ok"]
        and (not strict or result["doctor"]["warnings"] == 0)
        and not result["path_hits"]
        and not result["publish_artifact_hits"]
        and (not require_public_remotes or (result.get("public_remote") or {}).get("ok"))
        and (not require_published_head or (result.get("published_head") or {}).get("ok"))
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


def _clone_gallery_for_cli(source: Path, clone_parent: Path) -> tuple[Path | None, str | None]:
    return _cli_shared()._clone_gallery(source, clone_parent)


def _release_preflight_source_result(
    source_gallery: Path,
    *,
    allow_dirty: bool,
    require_public_remotes: bool = False,
    public_remote_owner: str = _PUBLIC_RELEASE_OWNER,
    require_published_head: bool = False,
) -> dict | None:
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
    if require_public_remotes:
        result["public_remote"] = _public_remote_result(source_repo, source_repo.name, public_remote_owner)
        if not result["public_remote"]["ok"]:
            result["error"] = result["public_remote"]["message"]
            return result
    if require_published_head:
        result["published_head"] = _published_head_result(source_repo)
        if not result["published_head"]["ok"]:
            result["error"] = result["published_head"]["message"]
            return result
    if dirty and not allow_dirty:
        result["error"] = "source repo is dirty; commit, stash, or pass --allow-dirty before fresh-clone preflight"
        return result
    return None


def _release_preflight_paths(args) -> tuple[Path, list[str], tuple[str, ...]]:
    project = _project_root()
    root_arg = Path(args.root).expanduser()
    root = root_arg if root_arg.is_absolute() else (project / root_arg).resolve()
    if args.gallery:
        names = list(args.gallery)
    else:
        names = list(_PUBLIC_RELEASE_GALLERIES)
        if args.include_optional:
            names.extend(_OPTIONAL_RELEASE_GALLERIES)
    needles = tuple(sorted({str(Path.home()), str(project)} | set(args.path_needle or [])))
    return root, names, needles


def _release_preflight_payload_for_root(args) -> dict:
    root, names, needles = _release_preflight_paths(args)
    galleries = [
        _release_preflight_one(
            (root / name / "gallery.yaml").resolve(),
            run_smoke=not args.no_smoke,
            http_smoke=args.http_smoke,
            allow_dirty=args.allow_dirty,
            needles=needles,
            strict=args.strict,
            require_public_remotes=args.require_public_remotes,
            public_remote_owner=args.public_remote_owner,
            require_published_head=args.require_published_head,
        )
        for name in names
    ]
    return {
        "ok": all(g["ok"] for g in galleries),
        "root": str(root),
        "galleries": galleries,
        "checks": {
            "smoke": not args.no_smoke,
            "http_smoke": bool(args.http_smoke),
            "allow_dirty": args.allow_dirty,
            "strict": args.strict,
            "path_needles": list(needles),
            "include_optional": bool(args.include_optional),
            "require_public_remotes": bool(args.require_public_remotes),
            "public_remote_owner": args.public_remote_owner,
            "require_published_head": bool(args.require_published_head),
        },
    }


def _release_preflight_payload_for_clones(args, clone_base: Path) -> dict:
    root, names, needles = _release_preflight_paths(args)
    clone_base.mkdir(parents=True, exist_ok=True)
    galleries = []
    for name in names:
        source_gallery = (root / name / "gallery.yaml").resolve()
        source_repo = source_gallery.parent
        source_error = _release_preflight_source_result(
            source_gallery,
            allow_dirty=args.allow_dirty,
            require_public_remotes=args.require_public_remotes,
            public_remote_owner=args.public_remote_owner,
            require_published_head=args.require_published_head,
        )
        if source_error:
            source_error["mode"] = "fresh-clone"
            source_error["source_path"] = str(source_repo)
            galleries.append(source_error)
            continue
        clone_gallery, clone_error = _clone_gallery_for_cli(source_repo, clone_base)
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
            http_smoke=args.http_smoke,
            allow_dirty=False,
            needles=needles,
            strict=args.strict,
        )
        if args.require_public_remotes:
            result["public_remote"] = _public_remote_result(source_repo, source_repo.name, args.public_remote_owner)
        if args.require_published_head:
            result["published_head"] = _published_head_result(source_repo)
        if args.require_public_remotes and not (result.get("public_remote") or {}).get("ok"):
            result["ok"] = False
        if args.require_published_head and not (result.get("published_head") or {}).get("ok"):
            result["ok"] = False
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
            "http_smoke": bool(args.http_smoke),
            "allow_dirty": args.allow_dirty,
            "strict": args.strict,
            "fresh_clone": True,
            "path_needles": list(needles),
            "include_optional": bool(args.include_optional),
            "require_public_remotes": bool(args.require_public_remotes),
            "public_remote_owner": args.public_remote_owner,
            "require_published_head": bool(args.require_published_head),
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


def _write_json_artifact(payload: dict, output: str) -> None:
    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"curiator: wrote {path}", file=sys.stderr)


def cmd_release_preflight(args) -> int:
    if args.no_smoke and args.http_smoke:
        print("curiator: release-preflight --http-smoke requires smoke checks; remove --no-smoke")
        return 2
    payload = _release_preflight_payload(args)
    if args.output:
        _write_json_artifact(payload, args.output)
    if args.json:
        if not args.output:
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
            + (f" remote={'OK' if (g.get('public_remote') or {}).get('ok') else 'FAIL'}"
               if payload.get("checks", {}).get("require_public_remotes") else "")
            + (f" published={'OK' if (g.get('published_head') or {}).get('ok') else 'FAIL'}"
               if payload.get("checks", {}).get("require_published_head") else "")
        )
        remote = g.get("public_remote") or {}
        published = g.get("published_head") or {}
        if g.get("error") and g.get("error") not in {remote.get("message"), published.get("message")}:
            print(f"    error: {g['error']}")
        for issue in g["doctor"]["issues"]:
            print(f"    doctor {issue['severity'].upper()} {issue['where']}: {issue['message']}")
        if payload.get("checks", {}).get("strict") and g["doctor"].get("warnings"):
            print("    strict=true: doctor warnings block this gallery")
        for hit in g["path_hits"]:
            print(f"    path {hit['file']}:{hit['line']}: {hit['message']}")
        for hit in g.get("publish_artifact_hits") or []:
            loc = f"{hit['file']}:{hit['line']}" if hit.get("line") else hit["file"]
            print(f"    artifact {loc}: {hit['message']}")
        if payload.get("checks", {}).get("require_public_remotes") and not remote.get("ok"):
            print(f"    remote: {remote.get('message')}")
            for url in remote.get("origin") or []:
                print(f"    remote origin {url}")
        if payload.get("checks", {}).get("require_published_head") and not published.get("ok"):
            print(f"    published: {published.get('message')}")
        if payload.get("checks", {}).get("require_published_head") and published.get("ok"):
            refs = ", ".join(published.get("matching_refs") or [])
            print(f"    published: HEAD {published.get('short')} found at {refs}")
        for line in g["dirty"][:8]:
            print(f"    dirty {line}")
        if len(g["dirty"]) > 8:
            print(f"    dirty ... {len(g['dirty']) - 8} more")
        for r in smoke_results:
            if not r["ok"]:
                print(f"    smoke FAIL {r['app']}: {r['message']}")
    return 0 if payload["ok"] else 1


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


def _playground_git_file_state(repo: Path, path: str | None) -> dict:
    state = {"inside_repo": None, "tracked": None, "ignored": None, "rel": None}
    if not path:
        return state
    repo = repo.resolve()
    p = Path(path).resolve()
    try:
        rel = p.relative_to(repo).as_posix()
    except ValueError:
        state["inside_repo"] = False
        return state
    state["inside_repo"] = True
    state["rel"] = rel
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", rel],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--", rel],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    state["tracked"] = tracked.returncode == 0
    state["ignored"] = ignored.returncode == 0
    return state


def _playground_user_summary(cfg: dict) -> dict:
    from . import auth

    auth_cfg = cfg.get("auth") or {}
    users: dict = {}
    inline_users = list(auth_cfg.get("users") or [])
    if auth_cfg.get("mode") == "local":
        users.update(auth.load_users_file(auth_cfg.get("users_file")))
        for user in inline_users:
            email = user.get("email")
            if email:
                users[email] = user
    admin_groups = set(auth_cfg.get("admin_groups") or ["admin"])
    active = [u for u in users.values() if not u.get("disabled")]
    users_file = auth_cfg.get("users_file")
    users_file_mode = None
    users_file_owner_only = None
    git_state = _playground_git_file_state(Path(cfg["repo_root"]), users_file)
    if users_file and Path(users_file).exists():
        try:
            mode = stat.S_IMODE(Path(users_file).stat().st_mode)
        except OSError:
            mode = None
        if mode is not None:
            users_file_mode = oct(mode)
            users_file_owner_only = (mode & 0o077) == 0
    return {
        "users_file": users_file,
        "users_file_mode": users_file_mode,
        "users_file_owner_only": users_file_owner_only,
        "users_file_inside_repo": git_state["inside_repo"],
        "users_file_rel": git_state["rel"],
        "users_file_tracked": git_state["tracked"],
        "users_file_ignored": git_state["ignored"],
        "inline_users": len(inline_users),
        "total": len(users),
        "active": len(active),
        "disabled": sum(1 for u in users.values() if u.get("disabled")),
        "admins": sum(1 for u in active if set(u.get("groups") or []) & admin_groups),
    }


def _playground_oidc_summary(cfg: dict) -> dict:
    auth_cfg = cfg.get("auth") or {}
    raw_secret_env = auth_cfg.get("client_secret_env")
    secret_env = str(raw_secret_env).strip() if raw_secret_env is not None else "CURIATOR_OIDC_SECRET"
    issuer = str(auth_cfg.get("issuer") or "").strip()
    client_id = str(auth_cfg.get("client_id") or "").strip()
    return {
        "issuer_configured": bool(issuer),
        "client_id_configured": bool(client_id),
        "client_secret_env": secret_env or None,
        "client_secret_set": bool(secret_env and os.environ.get(secret_env)),
        "scope": auth_cfg.get("scope") or "openid email profile",
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
        if user_summary["inline_users"]:
            issues.append(_playground_issue(
                "error",
                "auth.users",
                "hosted local-auth playgrounds should store password hashes in auth.users_file, not inline auth.users",
            ))
        if user_summary["users_file_mode"] and user_summary["users_file_owner_only"] is False:
            issues.append(_playground_issue(
                "error",
                "auth.users_file",
                "local-auth users_file contains password hashes and must be owner-only (0600)",
            ))
        if user_summary["users_file_inside_repo"] is False:
            issues.append(_playground_issue(
                "error",
                "auth.users_file",
                "local-auth users_file should live under the mounted collection root for backup/preflight coverage",
            ))
        if user_summary["users_file_tracked"]:
            issues.append(_playground_issue(
                "error",
                "auth.users_file",
                "local-auth users_file contains password hashes and must not be tracked by git",
            ))
        if user_summary["users_file_mode"] and user_summary["users_file_ignored"] is False:
            issues.append(_playground_issue(
                "error",
                "auth.users_file",
                "local-auth users_file must be gitignored so password hashes do not appear as untracked publish drift",
            ))
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

    if auth_mode == "oidc":
        oidc_summary = _playground_oidc_summary(cfg)
        if not oidc_summary["issuer_configured"]:
            issues.append(_playground_issue(
                "error",
                "auth.issuer",
                "OIDC playgrounds need auth.issuer so curiator can discover the provider metadata",
            ))
        if not oidc_summary["client_id_configured"]:
            issues.append(_playground_issue(
                "error",
                "auth.client_id",
                "OIDC playgrounds need auth.client_id for the hosted client registration",
            ))
        if not oidc_summary["client_secret_env"]:
            issues.append(_playground_issue(
                "error",
                "auth.client_secret_env",
                "OIDC playgrounds need auth.client_secret_env or the default CURIATOR_OIDC_SECRET",
            ))
        elif not oidc_summary["client_secret_set"]:
            issues.append(_playground_issue(
                "error",
                "auth.client_secret_env",
                f"OIDC client secret env var {oidc_summary['client_secret_env']} must be set before hosted preflight can pass",
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
    cli_mod = _cli_shared()
    doctor_issues = cli_mod._doctor_issues(cfg)
    doctor_errors = [i for i in doctor_issues if i.get("severity") == "error"]
    doctor_warnings = [i for i in doctor_issues if i.get("severity") == "warning"]
    smoke = {"ok": None, "results": []}
    if not args.no_smoke:
        results = cli_mod._smoke_results(cfg, http=args.http_smoke)
        smoke = {"ok": all(r["ok"] for r in results), "results": results}
    held = [cli_mod._queue_row_payload(key, entry) for key, entry in cli_mod._queue_entries(cfg)]
    errors = [i for i in issues if i.get("severity") == "error"]
    warnings = [i for i in issues if i.get("severity") == "warning"]
    strict = bool(getattr(args, "strict", False))
    strict_warnings = warnings + doctor_warnings
    auth_cfg = cfg.get("auth") or {}
    auth_payload = {
        "mode": auth_cfg.get("mode"),
        "allow_anonymous": bool(auth_cfg.get("allow_anonymous")),
        "admin_groups": auth_cfg.get("admin_groups") or [],
    }
    if auth_payload["mode"] == "oidc":
        auth_payload["oidc"] = _playground_oidc_summary(cfg)
    return {
        "ok": (
            not errors
            and not doctor_errors
            and (not strict or not strict_warnings)
            and (args.no_smoke or smoke["ok"] is True)
        ),
        "strict": strict,
        "checks": {
            "smoke": not args.no_smoke,
            "http_smoke": bool(args.http_smoke),
        },
        "gallery": cfg.get("gallery_path"),
        "auth": auth_payload,
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
        "warnings": len(strict_warnings),
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
    if args.no_smoke and args.http_smoke:
        print("curiator: playground-preflight --http-smoke requires smoke checks; remove --no-smoke")
        return 2
    payload = _playground_preflight_payload(args)
    if args.output:
        _write_json_artifact(payload, args.output)
    if args.json:
        if not args.output:
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
    if payload["strict"] and payload["warnings"]:
        print(f"  strict=true: {payload['warnings']} warning(s) block this gate")
    for issue in payload["issues"]:
        print(f"  {issue['severity'].upper()} {issue['where']}: {issue['message']}")
    for issue in payload["doctor"]["issues"]:
        print(f"  doctor {issue['severity'].upper()} {issue['where']}: {issue['message']}")
    for r in smoke_results:
        if not r["ok"]:
            print(f"  smoke FAIL {r['app']}: {r['message']}")
    return 0 if payload["ok"] else 1
