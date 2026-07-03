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


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _compact_stats_body(markdown: str) -> str:
    body = _stats_body(markdown)
    lines = body.splitlines()
    runner = next((line for line in lines if line.startswith("_Runner:")), "")
    totals = next((line for line in lines if line.startswith("_Totals:")), "")
    try:
        header_idx = next(idx for idx, line in enumerate(lines) if line.startswith("| Collection |"))
    except StopIteration:
        return body
    headers = _table_cells(lines[header_idx])
    rows = []
    for line in lines[header_idx + 2:]:
        if not line.startswith("|"):
            break
        cells = _table_cells(line)
        rows.append(dict(zip(headers, cells)))
    required = {
        "Collection",
        "Git head",
        "Cycles",
        "Direct fixes",
        "Proposals",
        "Human intervention",
        "Median reply",
        "Curator commits",
    }
    if not rows or any(not required <= set(row) for row in rows):
        return body
    out = []
    if runner:
        out.extend([runner, ""])
    out.extend(["Compact manuscript summary:", ""])
    for row in rows:
        out.append(
            "- `{collection}` (`{head}`): {cycles} cycles; direct/proposal/human "
            "{direct} / {proposals} / {human}; median reply {median}; {commits} curator commits.".format(
                collection=row["Collection"],
                head=row["Git head"],
                cycles=row["Cycles"],
                direct=row["Direct fixes"],
                proposals=row["Proposals"],
                human=row["Human intervention"],
                median=row["Median reply"],
                commits=row["Curator commits"],
            )
        )
    if totals:
        out.extend(["", totals])
    out.extend([
        "",
        "The full command output, including reply-rate, no-dispatch, and agent-note columns, is kept in "
        "`release-evidence/case-study-stats.md` and `release-evidence/case-study-stats.json`.",
    ])
    return "\n".join(out).strip()


def build_block(markdown: str, *, command: str, date: str) -> str:
    body = _compact_stats_body(markdown)
    return (
        f"{START}\n"
        f"The current case-study summary was generated on {date} with:\n\n"
        "```bash\n"
        f"{_format_command(command)}\n"
        "```\n\n"
        f"{body}\n"
        f"{END}"
    )


def _format_command(command: str) -> str:
    prefix = "curiator stats compare "
    suffix = " --markdown"
    if len(command) <= 88 or not (command.startswith(prefix) and command.endswith(suffix)):
        return command
    galleries = command[len(prefix):-len(suffix)].split()
    return "curiator stats compare \\\n  " + " \\\n  ".join(galleries) + " \\\n  --markdown"


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
