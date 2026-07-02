"""Release-doc gate: SECURITY.md and launch docs stay aligned."""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_release_docs.py"
ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    spec = importlib.util.spec_from_file_location("check_release_docs", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_release_doc_fixture(tmp_path: Path) -> None:
    (tmp_path / "docs" / "backlog").mkdir(parents=True)
    (tmp_path / "docs" / "paper").mkdir(parents=True)
    shutil.copyfile(ROOT / "README.md", tmp_path / "README.md")
    shutil.copyfile(ROOT / "SECURITY.md", tmp_path / "SECURITY.md")
    shutil.copyfile(ROOT / "docs" / "RELEASE.md", tmp_path / "docs" / "RELEASE.md")
    shutil.copyfile(ROOT / "docs" / "backlog" / "public-release.md",
                    tmp_path / "docs" / "backlog" / "public-release.md")
    shutil.copyfile(ROOT / "docs" / "demo.gif", tmp_path / "docs" / "demo.gif")


def test_release_docs_current_repo_pass():
    module = _load_script()

    assert module.check_release_docs(ROOT) == []


def test_release_docs_detect_missing_security_language(tmp_path):
    module = _load_script()
    (tmp_path / "docs" / "backlog").mkdir(parents=True)
    shutil.copyfile(ROOT / "README.md", tmp_path / "README.md")
    shutil.copyfile(ROOT / "docs" / "backlog" / "public-release.md",
                    tmp_path / "docs" / "backlog" / "public-release.md")
    (tmp_path / "SECURITY.md").write_text("# Security Policy\n\nToo vague.\n")

    failures = module.check_release_docs(tmp_path)

    assert "SECURITY.md missing required phrase: feedback is prompt input" in failures
    assert "SECURITY.md missing required phrase: does not solve prompt injection" in failures


def test_release_docs_detect_draft_paper_placeholders(tmp_path):
    module = _load_script()
    (tmp_path / "docs" / "backlog").mkdir(parents=True)
    (tmp_path / "docs" / "paper").mkdir(parents=True)
    shutil.copyfile(ROOT / "README.md", tmp_path / "README.md")
    shutil.copyfile(ROOT / "SECURITY.md", tmp_path / "SECURITY.md")
    shutil.copyfile(ROOT / "docs" / "backlog" / "public-release.md",
                    tmp_path / "docs" / "backlog" / "public-release.md")
    (tmp_path / "docs" / "paper" / "curiator-paper.md").write_text(
        "# Paper\n\nTODO(draft): unresolved related work.\n"
    )

    failures = module.check_release_docs(tmp_path)

    assert "docs/paper/curiator-paper.md still has TODO(draft) placeholders" in failures


def test_release_docs_rejects_stale_never_commits_claim(tmp_path):
    module = _load_script()
    _copy_release_doc_fixture(tmp_path)
    (tmp_path / "docs" / "USING_CURIATOR.md").write_text(
        "Edits land uncommitted in your working tree; the curator never commits.\n"
    )

    failures = module.check_release_docs(tmp_path)

    assert "docs/USING_CURIATOR.md still says the curator never commits" in failures


def test_release_docs_default_allows_release_paper_placeholders(tmp_path):
    module = _load_script()
    _copy_release_doc_fixture(tmp_path)
    (tmp_path / "docs" / "paper" / "curiator-paper.md").write_text(
        "# Paper\n\nTODO(release): waits for public evidence.\n"
    )

    assert module.check_release_docs(tmp_path) == []


def test_release_docs_default_requires_demo_gif(tmp_path):
    module = _load_script()
    _copy_release_doc_fixture(tmp_path)
    (tmp_path / "docs" / "demo.gif").unlink()

    failures = module.check_release_docs(tmp_path)

    assert "docs/demo.gif missing; run make demo-gif or record the real browser demo before release" in failures


def test_release_docs_strict_launch_detects_storyboard_demo_gif(tmp_path):
    module = _load_script()
    _copy_release_doc_fixture(tmp_path)
    (tmp_path / "docs" / "demo.gif").write_bytes(
        b"GIF89a" + module.PLACEHOLDER_DEMO_MARKER + b"\x3b"
    )

    failures = module.check_release_docs(tmp_path, strict_launch=True)

    assert (
        "docs/demo.gif is still the generated storyboard placeholder; "
        "record the real browser demo before public launch"
    ) in failures


def test_release_docs_strict_launch_detects_release_paper_placeholders(tmp_path):
    module = _load_script()
    _copy_release_doc_fixture(tmp_path)
    (tmp_path / "docs" / "demo.gif").write_bytes(b"GIF89a browser capture bytes \x3b")
    (tmp_path / "docs" / "paper" / "curiator-paper.md").write_text(
        "# Paper\n\nTODO(release): waits for public evidence.\n"
    )

    failures = module.check_release_docs(tmp_path, strict_launch=True)

    assert (
        "docs/paper/curiator-paper.md still has TODO(release) placeholders; "
        "replace them with command-backed release evidence before publishing the paper"
    ) in failures


def test_release_docs_strict_launch_accepts_unmarked_demo_gif(tmp_path):
    module = _load_script()
    _copy_release_doc_fixture(tmp_path)
    (tmp_path / "docs" / "demo.gif").write_bytes(b"GIF89a browser capture bytes \x3b")

    assert module.check_release_docs(tmp_path, strict_launch=True) == []


def test_release_docs_main_reports_failures(tmp_path, capsys):
    module = _load_script()
    (tmp_path / "README.md").write_text("# Demo\n")

    assert module.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "release doc check FAILED" in out
    assert "missing SECURITY.md" in out
    assert "README.md does not link to SECURITY.md" in out
