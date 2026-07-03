"""Release-doc gate: SECURITY.md and launch docs stay aligned."""
from __future__ import annotations

import importlib.util
import re
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
    shutil.copyfile(ROOT / "Makefile", tmp_path / "Makefile")
    shutil.copyfile(ROOT / "README.md", tmp_path / "README.md")
    shutil.copyfile(ROOT / "SECURITY.md", tmp_path / "SECURITY.md")
    shutil.copyfile(ROOT / "docs" / "RELEASE.md", tmp_path / "docs" / "RELEASE.md")
    shutil.copyfile(ROOT / "docs" / "backlog" / "public-release.md",
                    tmp_path / "docs" / "backlog" / "public-release.md")
    shutil.copyfile(ROOT / "docs" / "paper" / "reproducibility.md",
                    tmp_path / "docs" / "paper" / "reproducibility.md")
    shutil.copyfile(ROOT / "docs" / "paper" / "curiator-paper.md",
                    tmp_path / "docs" / "paper" / "curiator-paper.md")
    shutil.copyfile(ROOT / "docs" / "demo.gif", tmp_path / "docs" / "demo.gif")


def test_release_docs_current_repo_pass():
    module = _load_script()

    assert module.check_release_docs(ROOT) == []


def test_public_backlog_markdown_links_resolve():
    missing = []
    for path in (ROOT / "docs" / "backlog").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)#]+\.md)(?:#[^)]+)?\)", text):
            if target.startswith(("http://", "https://")):
                continue
            if not (path.parent / target).resolve().exists():
                missing.append(f"{path.relative_to(ROOT)} -> {target}")

    assert missing == []


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


def test_release_docs_requires_standard_release_evidence_commands(tmp_path):
    module = _load_script()
    _copy_release_doc_fixture(tmp_path)
    (tmp_path / "docs" / "paper" / "reproducibility.md").write_text(
        "# Reproducibility\n\ncuriator release-preflight --fresh-clone\n"
    )

    failures = module.check_release_docs(tmp_path)

    assert (
        "docs/paper/reproducibility.md missing required phrase: "
        "--output release-evidence/release-preflight.json"
    ) in failures
    assert (
        "docs/paper/reproducibility.md missing required phrase: "
        "--output release-evidence/release-preflight-optional.json"
    ) in failures
    assert (
        "docs/paper/reproducibility.md missing required phrase: "
        "--output release-evidence/case-study-stats.json"
    ) in failures
    assert (
        "docs/paper/reproducibility.md missing required phrase: "
        "make paper-stats"
    ) in failures
    assert (
        "docs/paper/reproducibility.md missing required phrase: "
        "make paper-pdf"
    ) in failures


def test_release_docs_requires_paper_targets(tmp_path):
    module = _load_script()
    _copy_release_doc_fixture(tmp_path)
    makefile = tmp_path / "Makefile"
    makefile.write_text(
        makefile.read_text()
        .replace("paper-stats:", "paper-stats-missing:")
        .replace("paper-pdf:", "paper-pdf-missing:")
    )

    failures = module.check_release_docs(tmp_path)

    assert "Makefile missing required phrase: paper-stats:" in failures
    assert "Makefile missing required phrase: paper-pdf:" in failures


def test_release_docs_requires_paper_stats_markers(tmp_path):
    module = _load_script()
    _copy_release_doc_fixture(tmp_path)
    paper = tmp_path / "docs" / "paper" / "curiator-paper.md"
    paper.write_text(paper.read_text().replace("<!-- curiator:case-study-stats:start -->\n", ""))

    failures = module.check_release_docs(tmp_path)

    assert (
        "docs/paper/curiator-paper.md missing required marker: "
        "<!-- curiator:case-study-stats:start -->"
    ) in failures


def test_release_docs_requires_optional_preflight_artifact_in_runbook(tmp_path):
    module = _load_script()
    _copy_release_doc_fixture(tmp_path)
    release = tmp_path / "docs" / "RELEASE.md"
    release.write_text(
        release.read_text()
        .replace("release-evidence/release-preflight-optional.json", "release-evidence/optional.json")
        .replace("release-evidence/release-package-smoke.json", "release-evidence/package.json")
        .replace("make release-package-smoke", "make package-smoke")
        .replace("playground-backup-smoke", "playground-backup-missing")
    )

    failures = module.check_release_docs(tmp_path)

    assert (
        "docs/RELEASE.md missing required phrase: "
        "release-evidence/release-preflight-optional.json"
    ) in failures
    assert (
        "docs/RELEASE.md missing required phrase: "
        "release-evidence/release-package-smoke.json"
    ) in failures
    assert (
        "docs/RELEASE.md missing required phrase: "
        "make release-package-smoke"
    ) in failures
    assert (
        "docs/RELEASE.md missing required phrase: "
        "playground-backup-smoke"
    ) in failures


def test_release_docs_rejects_tracked_raw_paper_evidence(tmp_path):
    module = _load_script()
    _copy_release_doc_fixture(tmp_path)
    (tmp_path / "docs" / "paper" / "reproducibility.md").write_text(
        "# Reproducibility\n\n"
        "make release-evidence\n"
        "curiator release-preflight --fresh-clone --json "
        "--output release-evidence/release-preflight.json\n"
        "curiator release-preflight --include-optional --fresh-clone --json "
        "--output release-evidence/release-preflight-optional.json\n"
        "curiator stats compare galleries/curiator-aviato galleries/curiator-ot "
        "galleries/curiator-geometry --json "
        "--output release-evidence/case-study-stats.json\n"
        "curiator stats compare galleries/curiator-aviato galleries/curiator-ot "
        "galleries/curiator-geometry --json "
        "--output docs/paper/figures/case-study-stats.json\n"
    )

    failures = module.check_release_docs(tmp_path)

    assert (
        "docs/paper/reproducibility.md writes raw evidence to tracked paper assets: "
        "docs/paper/figures/case-study-stats.json"
    ) in failures


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
    paper = tmp_path / "docs" / "paper" / "curiator-paper.md"
    paper.write_text(paper.read_text() + "\nTODO(release): waits for public evidence.\n")

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
