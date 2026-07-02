"""Refresh the companion paper's case-study stats block from curIAtor stats output."""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "docs" / "paper" / "curiator-paper.md"
DEFAULT_GALLERIES = (
    "galleries/curiator-aviato",
    "galleries/curiator-ot",
    "galleries/curiator-geometry",
)
START = "<!-- curiator:case-study-stats:start -->"
END = "<!-- curiator:case-study-stats:end -->"
DIRTY_RUNNER_RE = re.compile(r"^_Runner:\s+.+,\s+dirty\._$", re.MULTILINE)


def _stats_body(markdown: str) -> str:
    lines = markdown.strip().splitlines()
    if lines[:1] == ["# curIAtor Stats Compare"]:
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines).strip()


def build_block(markdown: str, *, command: str, date: str) -> str:
    body = _stats_body(markdown)
    return (
        f"{START}\n"
        f"The current case-study table was generated on {date} with:\n\n"
        "```bash\n"
        f"{command}\n"
        "```\n\n"
        f"{body}\n"
        f"{END}"
    )


def replace_block(text: str, block: str) -> str:
    if START not in text or END not in text:
        raise ValueError(f"paper is missing {START!r} / {END!r} markers")
    before, rest = text.split(START, 1)
    _old, after = rest.split(END, 1)
    return before.rstrip() + "\n\n" + block + after


def _run_stats(galleries: list[str]) -> str:
    cmd = [sys.executable, "-m", "curiator.cli", "stats", "compare", *galleries, "--markdown"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        raise SystemExit(f"curiator: stats compare failed: {detail}")
    return proc.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper", type=Path, default=PAPER, help="paper Markdown file to update")
    parser.add_argument("--stats-file", type=Path, default=None,
                        help="read precomputed curiator stats compare Markdown instead of running stats")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="snapshot date to write")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="allow a stats snapshot that reports the runner git tree as dirty")
    parser.add_argument("galleries", nargs="*", default=list(DEFAULT_GALLERIES),
                        help="gallery roots or gallery.yaml files for curiator stats compare")
    args = parser.parse_args(argv)

    markdown = (
        args.stats_file.read_text(encoding="utf-8")
        if args.stats_file else
        _run_stats(args.galleries)
    )
    if DIRTY_RUNNER_RE.search(markdown) and not args.allow_dirty:
        raise SystemExit("curiator: refusing to write paper stats from a dirty runner tree; commit/stash first")
    command = "curiator stats compare " + " ".join(args.galleries) + " --markdown"
    paper = args.paper if args.paper.is_absolute() else (ROOT / args.paper).resolve()
    updated = replace_block(
        paper.read_text(encoding="utf-8"),
        build_block(markdown, command=command, date=args.date),
    )
    paper.write_text(updated, encoding="utf-8")
    print(f"curiator: updated {paper.relative_to(ROOT) if paper.is_relative_to(ROOT) else paper}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
