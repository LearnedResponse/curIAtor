"""Stage one opted-in provider credential in a private workspace state volume."""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


def stage(kind: str, source: Path, state: Path, *, uid: int, gid: int) -> Path:
    if not source.is_file():
        raise SystemExit(f"workspace credential file is unavailable: {source}")
    state = state.resolve()
    relative = (
        Path("provider/codex/auth.json")
        if kind == "codex"
        else Path("provider/claude-home/.claude/.credentials.json")
    )
    destination = (state / relative).resolve()
    try:
        destination.relative_to(state)
    except ValueError as exc:
        raise SystemExit("workspace credential destination escapes state directory") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(0o600)
    os.chown(destination, uid, gid)
    current = destination.parent
    while current != state:
        os.chown(current, uid, gid)
        current.chmod(0o700)
        current = current.parent
    return destination


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["codex", "claude"], required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--uid", type=int, default=1000)
    parser.add_argument("--gid", type=int, default=1000)
    args = parser.parse_args(argv)
    stage(
        args.kind, Path(args.source), Path(args.state_dir), uid=args.uid, gid=args.gid,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
