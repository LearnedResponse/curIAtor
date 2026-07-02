"""Validate release-critical public docs before cutting a release."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER_DEMO_MARKER = b"curiator-demo-gif: generated storyboard placeholder"
TRACKED_RAW_EVIDENCE_RE = re.compile(
    r"(?:--output|>)\s+(docs/paper/figures/[^\s`]+?\.(?:json|csv))\b"
)

SECURITY_REQUIRED_PHRASES = [
    "feedback is prompt input",
    "does not solve prompt injection",
    "does not make untrusted feedback safe for autonomous code execution",
    "auth.mode: none",
    "auto-small",
    "hosted public feedback form",
    "propose-only",
    "human-reviewed queue",
    "Screenshot annotation redaction is client-side",
    "curiator release-preflight --fresh-clone",
    "agent.dispatch.trusted_groups",
    "agent.elevated.groups",
    "runner.mode: pinned",
]


def _contains(text: str, phrase: str) -> bool:
    normalized_text = " ".join(text.lower().split())
    normalized_phrase = " ".join(phrase.lower().split())
    return normalized_phrase in normalized_text


def check_release_docs(root: Path = ROOT, *, strict_launch: bool = False) -> list[str]:
    """Return release-doc failures; an empty list means the public release docs are coherent enough."""
    failures: list[str] = []
    readme = root / "README.md"
    security = root / "SECURITY.md"
    release = root / "docs" / "RELEASE.md"
    public_release = root / "docs" / "backlog" / "public-release.md"
    reproducibility = root / "docs" / "paper" / "reproducibility.md"
    paper = root / "docs" / "paper" / "curiator-paper.md"
    demo_gif = root / "docs" / "demo.gif"
    makefile = root / "Makefile"

    if not readme.exists():
        failures.append("missing README.md")
    if not security.exists():
        failures.append("missing SECURITY.md")
    if not public_release.exists():
        failures.append("missing docs/backlog/public-release.md")
    if not release.exists():
        failures.append("missing docs/RELEASE.md")
    if not reproducibility.exists():
        failures.append("missing docs/paper/reproducibility.md")
    if not makefile.exists():
        failures.append("missing Makefile")

    readme_text = readme.read_text(encoding="utf-8") if readme.exists() else ""
    security_text = security.read_text(encoding="utf-8") if security.exists() else ""
    release_text = release.read_text(encoding="utf-8") if release.exists() else ""
    public_release_text = public_release.read_text(encoding="utf-8") if public_release.exists() else ""
    reproducibility_text = reproducibility.read_text(encoding="utf-8") if reproducibility.exists() else ""
    paper_text = paper.read_text(encoding="utf-8") if paper.exists() else ""
    makefile_text = makefile.read_text(encoding="utf-8") if makefile.exists() else ""

    if "[SECURITY.md](SECURITY.md)" not in readme_text:
        failures.append("README.md does not link to SECURITY.md")
    if "[`docs/RELEASE.md`](docs/RELEASE.md)" not in readme_text:
        failures.append("README.md does not link to docs/RELEASE.md")
    if "SECURITY.md" not in public_release_text:
        failures.append("public-release backlog does not mention SECURITY.md")
    if "docs/RELEASE.md" not in public_release_text:
        failures.append("public-release backlog does not mention docs/RELEASE.md")

    for phrase in SECURITY_REQUIRED_PHRASES:
        if not _contains(security_text, phrase):
            failures.append(f"SECURITY.md missing required phrase: {phrase}")

    for phrase in [
        "make release-check",
        "PyPI Trusted Publishing",
        "GitHub to Zenodo integration",
        "git tag v",
        "docs/DEMO_SCRIPT.md",
        "release-evidence/release-preflight.json",
        "release-evidence/release-preflight-optional.json",
        "release-evidence/case-study-stats.json",
        "make paper-stats",
        "make paper-pdf",
    ]:
        if phrase not in release_text:
            failures.append(f"docs/RELEASE.md missing required phrase: {phrase}")

    for phrase in [
        "make release-evidence",
        "make paper-stats",
        "make paper-pdf",
        "--output release-evidence/release-preflight.json",
        "--output release-evidence/release-preflight-optional.json",
        "--output release-evidence/case-study-stats.json",
    ]:
        if phrase not in reproducibility_text:
            failures.append(f"docs/paper/reproducibility.md missing required phrase: {phrase}")
    for phrase in [
        "paper-stats:",
        "paper-pdf:",
        "scripts/update_paper_stats.py",
    ]:
        if phrase not in makefile_text:
            failures.append(f"Makefile missing required phrase: {phrase}")
    for marker in [
        "<!-- curiator:case-study-stats:start -->",
        "<!-- curiator:case-study-stats:end -->",
    ]:
        if marker not in paper_text:
            failures.append(f"docs/paper/curiator-paper.md missing required marker: {marker}")
    for path in TRACKED_RAW_EVIDENCE_RE.findall(reproducibility_text):
        failures.append(
            f"docs/paper/reproducibility.md writes raw evidence to tracked paper assets: {path}"
        )

    if "TODO(draft)" in paper_text:
        failures.append("docs/paper/curiator-paper.md still has TODO(draft) placeholders")
    using = root / "docs" / "USING_CURIATOR.md"
    using_text = using.read_text(encoding="utf-8") if using.exists() else ""
    if "curator never commits" in using_text.lower():
        failures.append("docs/USING_CURIATOR.md still says the curator never commits")

    if not demo_gif.exists():
        failures.append("docs/demo.gif missing; run make demo-gif or record the real browser demo before release")
    elif strict_launch:
        if PLACEHOLDER_DEMO_MARKER in demo_gif.read_bytes():
            failures.append(
                "docs/demo.gif is still the generated storyboard placeholder; "
                "record the real browser demo before public launch"
            )
        if "TODO(release)" in paper_text:
            failures.append(
                "docs/paper/curiator-paper.md still has TODO(release) placeholders; "
                "replace them with command-backed release evidence before publishing the paper"
            )

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=ROOT,
                        help="repository root to check")
    parser.add_argument("--strict-launch", action="store_true",
                        help="also reject release-time placeholders such as the generated demo GIF")
    args = parser.parse_args(argv)

    failures = check_release_docs(args.root.resolve(), strict_launch=args.strict_launch)
    if failures:
        print("curiator: release doc check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("curiator: release doc check OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
