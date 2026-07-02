"""Repository metadata files used by release/archival workflows."""
from __future__ import annotations

from pathlib import Path

import yaml


def test_citation_cff_has_release_metadata():
    data = yaml.safe_load(Path("CITATION.cff").read_text())
    assert data["cff-version"] == "1.2.0"
    assert data["title"].startswith("curIAtor")
    assert data["authors"][0]["family-names"] == "Guetz"
    assert data["license"] == "Apache-2.0"
    assert data["repository-code"] == "https://github.com/LearnedResponse/curiator"


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
    assert "## Add Dependency Checks To `curiator doctor`" in issue_seed
    assert "Labels: `good first issue`" in issue_seed
    assert "Done when:" in issue_seed


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
