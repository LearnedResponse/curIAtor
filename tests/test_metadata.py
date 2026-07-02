"""Repository metadata files used by release/archival workflows."""
from __future__ import annotations

import json
from pathlib import Path
import tomllib

import yaml


def test_citation_cff_has_release_metadata():
    data = yaml.safe_load(Path("CITATION.cff").read_text())
    assert data["cff-version"] == "1.2.0"
    assert data["title"].startswith("curIAtor")
    assert data["authors"][0]["family-names"] == "Guetz"
    assert data["license"] == "Apache-2.0"
    assert data["repository-code"] == "https://github.com/LearnedResponse/curiator"


def test_zenodo_json_has_archive_metadata():
    data = json.loads(Path(".zenodo.json").read_text())
    citation = yaml.safe_load(Path("CITATION.cff").read_text())

    assert data["upload_type"] == "software"
    assert data["access_right"] == "open"
    assert data["license"] == "Apache-2.0"
    assert data["title"] == citation["title"]
    assert data["version"] == citation["version"]
    assert data["publication_date"] == citation["date-released"]
    assert data["creators"][0]["name"] == "Guetz, Adam"


def test_runtime_version_matches_release_metadata():
    import curiator

    project = tomllib.loads(Path("pyproject.toml").read_text())
    citation = yaml.safe_load(Path("CITATION.cff").read_text())
    zenodo = json.loads(Path(".zenodo.json").read_text())

    version = project["project"]["version"]
    assert curiator.__version__ == version
    assert citation["version"] == version
    assert zenodo["version"] == version


def test_issue_templates_are_valid_yaml():
    template_dir = Path(".github/ISSUE_TEMPLATE")
    files = sorted(template_dir.glob("*.yml"))
    assert {p.name for p in files} >= {
        "bug_report.yml",
        "example_collection.yml",
        "feature_request.yml",
    }
    for path in files:
        data = yaml.safe_load(path.read_text())
        assert isinstance(data, dict), path
        assert data, path


def test_labels_cover_issue_templates_and_good_first_issues():
    labels = yaml.safe_load(Path(".github/labels.yml").read_text())
    names = {item["name"] for item in labels}
    assert {"bug", "enhancement", "needs-triage", "example-collection", "good first issue"} <= names

    issue_seed = Path("docs/GOOD_FIRST_ISSUES.md").read_text()
    assert "No ready-to-file good-first issue seeds remain right now" in issue_seed
    assert "add new entries here when a scoped starter issue is identified" in issue_seed


def test_release_evidence_target_writes_ignored_artifacts():
    makefile = Path("Makefile").read_text()
    gitignore = Path(".gitignore").read_text()

    assert "release-evidence:" in makefile
    assert "release-evidence/release-preflight.json" in makefile
    assert "release-evidence/case-study-stats.json" in makefile
    assert "release-evidence/" in gitignore


def test_release_workflow_publishes_with_version_guard():
    data = yaml.safe_load(Path(".github/workflows/release.yml").read_text())
    jobs = data["jobs"]
    assert "publish-pypi" in jobs
    assert jobs["publish-pypi"]["needs"] == "build"
    assert jobs["publish-pypi"]["permissions"]["id-token"] == "write"
    assert any(
        step.get("uses") == "pypa/gh-action-pypi-publish@release/v1"
        for step in jobs["publish-pypi"]["steps"]
    )

    build_runs = "\n".join(step.get("run", "") for step in jobs["build"]["steps"])
    assert "GITHUB_REF_NAME#v" in build_runs
    assert "pyproject.toml" in build_runs
