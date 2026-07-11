"""Seed one provenance-stamped feedback thread into workspace-local state."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from . import ledger
from .config import load_config, set_gallery_override, set_state_dir_override


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gallery", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--canonical-state")
    args = parser.parse_args(argv)
    set_gallery_override(args.gallery)
    set_state_dir_override(args.state_dir)
    try:
        cfg = load_config()
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        app_key = str(payload["app_key"])
        entries = payload.get("entries") or []
        if not isinstance(entries, list):
            raise SystemExit("workspace seed entries must be a list")
        if args.canonical_state:
            canonical = Path(args.canonical_state).resolve()
            state = Path(args.state_dir).resolve()
            for entry in entries:
                for field in ("screenshot", "audio"):
                    rel = entry.get(field)
                    if not rel:
                        continue
                    source = (canonical / rel).resolve()
                    destination = (state / rel).resolve()
                    try:
                        source.relative_to(canonical)
                        destination.relative_to(state)
                    except ValueError:
                        continue
                    if source.is_file():
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, destination)
        ledger.replace_all(cfg, {app_key: entries})
    finally:
        set_gallery_override(None)
        set_state_dir_override(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
