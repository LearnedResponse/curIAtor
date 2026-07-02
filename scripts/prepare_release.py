"""Prepare release metadata for a tagged curIAtor release."""
from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ReleasePrepareError(ValueError):
    """Raised when release metadata cannot be updated safely."""


def validate_version(version: str) -> str:
    if not SEMVER_RE.fullmatch(version):
        raise ReleasePrepareError(f"version must be X.Y.Z, got {version!r}")
    return version


def validate_date(value: str) -> str:
    try:
        dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ReleasePrepareError(f"date must be YYYY-MM-DD, got {value!r}") from exc
    return value


def replace_project_version(text: str, version: str) -> str:
    lines = text.splitlines(keepends=True)
    in_project = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if in_project and stripped.startswith("[") and stripped.endswith("]"):
            break
        if in_project and line.startswith("version = "):
            lines[index] = f'version = "{version}"\n'
            return "".join(lines)
    raise ReleasePrepareError("pyproject.toml is missing [project] version")


def replace_citation_metadata(text: str, version: str, release_date: str) -> str:
    text, version_count = re.subn(r'^version: ".*"$', f'version: "{version}"', text, count=1, flags=re.MULTILINE)
    text, date_count = re.subn(
        r'^date-released: ".*"$',
        f'date-released: "{release_date}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if version_count != 1 or date_count != 1:
        raise ReleasePrepareError("CITATION.cff is missing version or date-released")
    return text


def cut_changelog(text: str, version: str, release_date: str) -> str:
    heading = f"## [{version}]"
    if re.search(rf"^## \[{re.escape(version)}\](?:\s|$)", text, flags=re.MULTILINE):
        raise ReleasePrepareError(f"CHANGELOG.md already has a {heading} section")

    unreleased = "## [Unreleased]"
    if unreleased not in text:
        raise ReleasePrepareError("CHANGELOG.md is missing ## [Unreleased]")
    release_heading = f"## [{version}] \u2014 {release_date}"
    text = text.replace(unreleased, f"{unreleased}\n\n{release_heading}", 1)

    link_match = re.search(
        r"^\[Unreleased\]: (?P<repo>https://github\.com/[^/]+/[^/]+)/compare/v(?P<previous>[^.]+\.[^.]+\.[^.\s]+)\.\.\.HEAD$",
        text,
        flags=re.MULTILINE,
    )
    if not link_match:
        raise ReleasePrepareError("CHANGELOG.md is missing a standard [Unreleased] compare link")

    repo_url = link_match.group("repo")
    old_unreleased = link_match.group(0)
    new_links = "\n".join(
        [
            f"[Unreleased]: {repo_url}/compare/v{version}...HEAD",
            f"[{version}]: {repo_url}/releases/tag/v{version}",
        ]
    )
    return text.replace(old_unreleased, new_links, 1)


def prepare_release(root: Path, version: str, release_date: str, *, write: bool = True) -> list[Path]:
    version = validate_version(version)
    release_date = validate_date(release_date)
    paths = [
        root / "pyproject.toml",
        root / "CITATION.cff",
        root / "CHANGELOG.md",
    ]
    pyproject, citation, changelog = paths
    updates = {
        pyproject: replace_project_version(pyproject.read_text(encoding="utf-8"), version),
        citation: replace_citation_metadata(citation.read_text(encoding="utf-8"), version, release_date),
        changelog: cut_changelog(changelog.read_text(encoding="utf-8"), version, release_date),
    }
    if write:
        for path, text in updates.items():
            path.write_text(text, encoding="utf-8")
    return paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Release version, for example 0.2.0")
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Release date as YYYY-MM-DD; defaults to today",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root containing pyproject.toml, CITATION.cff, and CHANGELOG.md",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate and print changed files without writing")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        paths = prepare_release(root, args.version, args.date, write=not args.dry_run)
    except ReleasePrepareError as exc:
        parser.error(str(exc))
    action = "would update" if args.dry_run else "updated"
    for path in paths:
        print(f"{action} {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
