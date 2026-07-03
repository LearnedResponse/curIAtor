"""Companion-paper stats table refresh helper."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update_paper_stats.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("update_paper_stats", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_update_paper_stats_replaces_only_marked_block():
    module = _load_script()
    original = (
        "# Paper\n\n"
        "before\n\n"
        f"{module.START}\n"
        "old table\n"
        f"{module.END}\n\n"
        "after\n"
    )
    markdown = (
        "# curIAtor Stats Compare\n\n"
        "_Runner: curIAtor 0.2.0, main@abc1234, clean._\n\n"
        "| Collection | Git head | Cycles | Direct fixes | Proposals | No dispatch | "
        "Human intervention | Replied | Reply rate | Median reply | Agent notes | Curator commits |\n"
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        "| demo | main@def5678 | 1 | 1 (100.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | "
        "1 | 100.0% | 1m 2s | 1 | 1 |\n\n"
        "_Totals: 1 collections, 1 cycles, 1 replied (100.0%), "
        "1 direct fixes (100.0%), 0 proposals (0.0%), "
        "0 human intervention (0.0%), 1 curator commits._\n"
    )

    block = module.build_block(markdown, command="curiator stats compare demo --markdown", date="2026-07-02")
    updated = module.replace_block(original, block)

    assert "before" in updated
    assert "after" in updated
    assert "old table" not in updated
    assert "_Runner: curIAtor 0.2.0, main@abc1234, clean._" in updated
    assert "The current case-study summary was generated on 2026-07-02 with:" in updated
    assert (
        "- `demo` (`main@def5678`): 1 cycles; direct/proposal/human "
        "1 (100.0%) / 0 (0.0%) / 0 (0.0%); median reply 1m 2s; 1 curator commits."
    ) in updated
    assert "release-evidence/case-study-stats.md" in updated
    assert "curiator stats compare demo --markdown" in updated


def test_update_paper_stats_rejects_dirty_runner_snapshot(tmp_path):
    module = _load_script()
    paper = tmp_path / "paper.md"
    stats = tmp_path / "stats.md"
    paper.write_text(f"{module.START}\nold\n{module.END}\n", encoding="utf-8")
    stats.write_text(
        "# curIAtor Stats Compare\n\n"
        "_Runner: curIAtor 0.2.0, main@abc1234, dirty._\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="dirty runner tree"):
        module.main(["--paper", str(paper), "--stats-file", str(stats)])

    assert "old" in paper.read_text(encoding="utf-8")
