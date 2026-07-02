"""Validate release-critical public docs before cutting a release."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

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


def check_release_docs(root: Path = ROOT) -> list[str]:
    """Return release-doc failures; an empty list means the public release docs are coherent enough."""
    failures: list[str] = []
    readme = root / "README.md"
    security = root / "SECURITY.md"
    public_release = root / "docs" / "backlog" / "public-release.md"

    if not readme.exists():
        failures.append("missing README.md")
    if not security.exists():
        failures.append("missing SECURITY.md")
    if not public_release.exists():
        failures.append("missing docs/backlog/public-release.md")

    readme_text = readme.read_text(encoding="utf-8") if readme.exists() else ""
    security_text = security.read_text(encoding="utf-8") if security.exists() else ""
    public_release_text = public_release.read_text(encoding="utf-8") if public_release.exists() else ""

    if "[SECURITY.md](SECURITY.md)" not in readme_text:
        failures.append("README.md does not link to SECURITY.md")
    if "SECURITY.md" not in public_release_text:
        failures.append("public-release backlog does not mention SECURITY.md")

    for phrase in SECURITY_REQUIRED_PHRASES:
        if not _contains(security_text, phrase):
            failures.append(f"SECURITY.md missing required phrase: {phrase}")

    return failures


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0]).resolve() if argv else ROOT
    failures = check_release_docs(root)
    if failures:
        print("curiator: release doc check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("curiator: release doc check OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
