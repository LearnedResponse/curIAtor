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


def test_release_docs_main_reports_failures(tmp_path, capsys):
    module = _load_script()
    (tmp_path / "README.md").write_text("# Demo\n")

    assert module.main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "release doc check FAILED" in out
    assert "missing SECURITY.md" in out
    assert "README.md does not link to SECURITY.md" in out
