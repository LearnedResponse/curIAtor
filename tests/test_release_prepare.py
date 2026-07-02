"""Release metadata preparation helper."""
from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_release.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("prepare_release", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_release_fixture(root: Path, *, existing_release: bool = False) -> None:
    (root / "pyproject.toml").write_text(textwrap.dedent("""\
        [build-system]
        requires = ["setuptools>=77"]

        [project]
        name = "curiator"
        version = "0.1.0"

        [project.scripts]
        curiator = "curiator.cli:main"
    """))
    (root / "CITATION.cff").write_text(textwrap.dedent("""\
        cff-version: 1.2.0
        title: "curIAtor"
        version: "0.1.0"
        date-released: "2026-06-29"
    """))
    release_block = "## [0.2.0] \u2014 2026-07-02\n\n" if existing_release else ""
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        f"{release_block}"
        "### Added\n"
        "- Something new.\n\n"
        "## [0.1.0] \u2014 2026-06-29\n\n"
        "First public release.\n\n"
        "[Unreleased]: https://github.com/LearnedResponse/curiator/compare/v0.1.0...HEAD\n"
        "[0.1.0]: https://github.com/LearnedResponse/curiator/releases/tag/v0.1.0\n"
    )


def test_prepare_release_updates_version_citation_and_changelog(tmp_path):
    module = _load_script()
    _write_release_fixture(tmp_path)

    changed = module.prepare_release(tmp_path, "0.2.0", "2026-07-02")

    assert [path.name for path in changed] == ["pyproject.toml", "CITATION.cff", "CHANGELOG.md"]
    assert 'version = "0.2.0"' in (tmp_path / "pyproject.toml").read_text()
    citation = (tmp_path / "CITATION.cff").read_text()
    assert 'version: "0.2.0"' in citation
    assert 'date-released: "2026-07-02"' in citation

    changelog = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [Unreleased]\n\n## [0.2.0] \u2014 2026-07-02\n\n### Added" in changelog
    assert "[Unreleased]: https://github.com/LearnedResponse/curiator/compare/v0.2.0...HEAD" in changelog
    assert "[0.2.0]: https://github.com/LearnedResponse/curiator/releases/tag/v0.2.0" in changelog
    assert "[0.1.0]: https://github.com/LearnedResponse/curiator/releases/tag/v0.1.0" in changelog


def test_prepare_release_dry_run_validates_without_writing(tmp_path):
    module = _load_script()
    _write_release_fixture(tmp_path)

    changed = module.prepare_release(tmp_path, "0.2.0", "2026-07-02", write=False)

    assert len(changed) == 3
    assert 'version = "0.1.0"' in (tmp_path / "pyproject.toml").read_text()
    assert "## [0.2.0]" not in (tmp_path / "CHANGELOG.md").read_text()


def test_prepare_release_refuses_existing_changelog_section(tmp_path):
    module = _load_script()
    _write_release_fixture(tmp_path, existing_release=True)

    with pytest.raises(module.ReleasePrepareError, match="already has"):
        module.prepare_release(tmp_path, "0.2.0", "2026-07-02")


def test_prepare_release_validates_version_and_date(tmp_path):
    module = _load_script()
    _write_release_fixture(tmp_path)

    with pytest.raises(module.ReleasePrepareError, match="version must be"):
        module.prepare_release(tmp_path, "v0.2.0", "2026-07-02")
    with pytest.raises(module.ReleasePrepareError, match="date must be"):
        module.prepare_release(tmp_path, "0.2.0", "July 2, 2026")
