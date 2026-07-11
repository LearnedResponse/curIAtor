"""Dependency bootstrap policy for isolated workspaces."""
import inspect
from pathlib import Path

from curiator import workspace_bootstrap
from curiator.workspace_bootstrap import _npm_env, _requirement_files


def test_npm_environment_uses_workspace_cache_and_noninteractive_https_git(tmp_path: Path):
    env = _npm_env(tmp_path)

    assert env["npm_config_cache"] == str(tmp_path / "cache" / "npm")
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_COUNT"] == "4"
    values = {env[f"GIT_CONFIG_VALUE_{index}"] for index in range(4)}
    assert values == {
        "ssh://git@github.com/", "git+ssh://git@github.com/", "git@github.com:", "git://github.com/",
    }
    assert {env[f"GIT_CONFIG_KEY_{index}"] for index in range(4)} == {
        "url.https://github.com/.insteadOf",
    }


def test_python_workspace_venv_inherits_image_curiator_package():
    source = inspect.getsource(workspace_bootstrap.main)
    assert '"--system-site-packages"' in source
    assert "curIAtor self-requirements stay offline" in source


def test_requirements_include_collection_root_and_shared_app_root(tmp_path: Path):
    collection = tmp_path / "collection"
    shared_root = collection / "apps" / "dash_suite"
    shared_root.mkdir(parents=True)
    collection_requirement = collection / "requirements.txt"
    app_requirement = shared_root / "requirements.txt"
    collection_requirement.write_text("dash\n")
    app_requirement.write_text("plotly\n")

    requirements = _requirement_files(
        {"repo_root": str(collection)},
        [shared_root, shared_root],
    )

    assert requirements == [collection_requirement, app_requirement]
