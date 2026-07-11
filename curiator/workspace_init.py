"""Initialize named Docker volumes for a curIAtor workspace.

This module runs inside the maintained workspace image as root. All destructive
operations are constrained to ``/workspace`` volume paths supplied by the host
manager; canonical repositories are mounted read-only.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path


def _run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(list(args), cwd=cwd, check=True)


def _git(repo: Path, *args: str) -> None:
    _run("git", "-c", f"safe.directory={repo}", *args, cwd=repo)


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _checkout(repo: Path, sha: str, branch: str | None) -> None:
    if branch:
        _git(repo, "switch", "-c", branch, sha)
    else:
        _git(repo, "checkout", "--detach", sha)
    _git(repo, "config", "user.name", "curIAtor Workspace")
    _git(repo, "config", "user.email", "workspace@curiator.local")


def initialize(args) -> None:
    source = Path(args.source).resolve()
    state = Path(args.state).resolve()
    workspace_root = Path("/workspace").resolve()
    if not _inside(source, workspace_root) or not _inside(state, workspace_root):
        raise SystemExit("workspace init paths must stay under /workspace")
    if any(source.iterdir()) if source.exists() else False:
        raise SystemExit(f"workspace source volume is not empty: {source}")
    source.parent.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    _run("git", "clone", "--no-hardlinks", "--no-checkout", args.collection, str(source))
    collection_branch = args.branch if not args.owning_rel else None
    _checkout(source, args.collection_sha, collection_branch)

    if args.owning_rel:
        destination = (source / args.owning_rel).resolve()
        if not _inside(destination, source):
            raise SystemExit("nested owning repository path escapes workspace source")
        if destination.exists() or destination.is_symlink():
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run("git", "clone", "--no-hardlinks", "--no-checkout", args.owning, str(destination))
        _checkout(destination, args.owning_sha, args.branch)

    for raw_dependency in args.dependency:
        try:
            dependency = json.loads(raw_dependency)
            dependency_source = Path(dependency["source"]).resolve()
            dependency_sha = str(dependency["sha"])
            dependency_rel = str(dependency["rel"])
            readonly_target = Path(dependency["readonly_target"]).resolve()
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(f"invalid --dependency descriptor: {raw_dependency}") from exc
        destination = (source / dependency_rel).resolve()
        if not _inside(destination, source):
            raise SystemExit("nested dependency repository path escapes workspace source")
        if destination.exists() or destination.is_symlink():
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        destination.parent.mkdir(parents=True, exist_ok=True)
        _run("git", "clone", "--no-hardlinks", "--no-checkout", str(dependency_source), str(destination))
        _checkout(destination, dependency_sha, None)
        if not _inside(readonly_target, workspace_root):
            raise SystemExit("nested dependency read-only target escapes /workspace")
        if any(readonly_target.iterdir()) if readonly_target.exists() else False:
            raise SystemExit(f"nested dependency volume is not empty: {readonly_target}")
        readonly_target.parent.mkdir(parents=True, exist_ok=True)
        _run(
            "git",
            "clone",
            "--no-hardlinks",
            "--no-checkout",
            str(dependency_source),
            str(readonly_target),
        )
        _checkout(readonly_target, dependency_sha, None)

    for root, dirs, files in os.walk(workspace_root):
        os.chown(root, args.uid, args.gid)
        for name in dirs:
            os.chown(Path(root) / name, args.uid, args.gid)
        for name in files:
            os.chown(Path(root) / name, args.uid, args.gid)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="/workspace/source")
    parser.add_argument("--state", default="/workspace/state")
    parser.add_argument("--collection", required=True)
    parser.add_argument("--collection-sha", required=True)
    parser.add_argument("--owning")
    parser.add_argument("--owning-sha")
    parser.add_argument("--owning-rel")
    parser.add_argument("--branch")
    parser.add_argument("--dependency", action="append", default=[])
    parser.add_argument("--uid", type=int, default=1000)
    parser.add_argument("--gid", type=int, default=1000)
    args = parser.parse_args(argv)
    if bool(args.owning_rel) != bool(args.owning and args.owning_sha):
        parser.error("--owning-rel requires --owning and --owning-sha")
    initialize(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
