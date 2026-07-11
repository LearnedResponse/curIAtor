"""Write workspace identity metadata into the state volume."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--payload", required=True)
    args = parser.parse_args(argv)
    state = Path(args.state_dir).resolve()
    state.mkdir(parents=True, exist_ok=True)
    destination = state / "workspace.json"
    temp = state / f".workspace.{os.getpid()}.tmp"
    temp.write_text(args.payload + "\n", encoding="utf-8")
    json.loads(temp.read_text(encoding="utf-8"))
    os.replace(temp, destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
