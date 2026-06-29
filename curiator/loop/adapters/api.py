"""api — the team adapter: Anthropic API / Agent SDK (per-token, scales, multi-user).

v1 — interface only. The cold API agent has no project memory, so this adapter must be handed a
context bundle (the app source + a CONTEXT.md/LESSONS.md, optionally backed by a live knowledge
store like graphify — see docs/DESIGN.md → "Agent adapter / deployment modes"). Defaults to
propose-only + PR-for-review for shared teams.

Build this once the headless-cc wedge is proven (docs/EXTRACTION_SCOPE.md → M4).
"""
from __future__ import annotations


def available() -> bool:
    return False


def run(task) -> None:
    raise NotImplementedError(
        "The `api` adapter is a v1 stub. Use adapter: headless-cc for now "
        "(see docs/EXTRACTION_SCOPE.md → M4 for the build plan)."
    )
