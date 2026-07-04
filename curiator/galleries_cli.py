"""CLI handlers for nested gallery repo discovery, adoption, and cloning."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path


def _cli_shared():
    from . import cli as cli_mod

    return cli_mod


def _git_output(cwd: Path, *args: str) -> str | None:
    return _cli_shared()._git_output(cwd, *args)


def _git_text(repo: Path, *args: str) -> str:
    return _cli_shared()._git_text(repo, *args)


def _project_root(cwd: Path | None = None) -> Path:
    return _cli_shared()._project_root(cwd)


def _is_relative_to(path: Path, parent: Path) -> bool:
    return _cli_shared()._is_relative_to(path, parent)


def _is_git_toplevel(repo: Path) -> bool:
    return _cli_shared()._is_git_toplevel(repo)


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


def _rel_cmd_path(path: str) -> str:
    try:
        return os.path.relpath(Path(path), Path.cwd())
    except ValueError:  # pragma: no cover - different Windows drives
        return path


def _sibling_gallery_candidates(root: Path) -> list[dict]:
    """Find legacy sibling curiator-* collection paths next to the runner checkout.

    The canonical local workspace is now ./galleries/curiator-*/. Sibling aliases are easy for agents
    to follow back outside the writable runner root, so surface them in `curiator galleries`.
    """
    project = _project_root()
    parent = project.parent
    if not parent.exists():
        return []
    rows: list[dict] = []
    for p in sorted(parent.iterdir(), key=lambda x: x.name):
        if not p.name.startswith("curiator-"):
            continue
        resolved = p.resolve()
        if resolved == project:
            continue
        if not (resolved / "gallery.yaml").exists():
            continue
        nested = (root / p.name).resolve()
        relation = "alias-to-nested" if nested.exists() and resolved == nested else "sibling-checkout"
        row = {
            "name": p.name,
            "path": str(p),
            "resolved": str(resolved),
            "is_symlink": p.is_symlink(),
            "relation": relation,
        }
        if relation == "sibling-checkout":
            row["adopt_command"] = f"curiator galleries adopt {_rel_cmd_path(str(p))}"
        rows.append(row)
    return rows


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


def cmd_galleries(args) -> int:
    root = _galleries_root(args.root)
    galleries = [_gallery_summary(repo) for repo in _discover_galleries(root)]
    siblings = _sibling_gallery_candidates(root)
    payload = {
        "root": str(root),
        "count": len(galleries),
        "galleries": galleries,
        "sibling_galleries": siblings,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"curiator: {len(galleries)} nested galleries under {root}")
    if not galleries:
        print("  none found; create one with `curiator init galleries/curiator-my-topic --git`")
    else:
        for g in galleries:
            git = "not-git"
            if g["git"]:
                branch = g.get("branch") or "detached"
                head = g.get("head") or "no-head"
                git = f"{branch}@{head}"
            dirty = f"{len(g['dirty'])} dirty" if g["dirty"] else "clean"
            gallery = _rel_cmd_path(g["gallery"])
            print(f"  {g['name']}: {git}, {dirty}")
            print(f"    use: curiator --gallery {shlex.quote(gallery)} status")
    if siblings:
        print("")
        print("curiator: sibling curiator-* gallery paths found next to this checkout")
        print("  canonical local workspace: ./galleries/curiator-*/")
        for s in siblings:
            if s["relation"] == "alias-to-nested":
                print(f"  {s['name']}: alias -> {_rel_cmd_path(s['resolved'])}")
                print("    archive or remove the alias so agents stay inside ./galleries/")
            else:
                print(f"  {s['name']}: {_rel_cmd_path(s['path'])}")
                print(f"    adopt: {s['adopt_command']}")
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


def _maybe_rewrite_nested_runner_path(gallery: Path, *, old_repo: Path, project: Path) -> list[dict]:
    """Rewrite only the safe, common checkout-runner path when adopting a sibling gallery."""
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
        "use": f"curiator --gallery {_rel_cmd_path(str(dest / 'gallery.yaml'))} status",
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
        "use": f"curiator --gallery {_rel_cmd_path(str(dest / 'gallery.yaml'))} status",
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
