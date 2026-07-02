"""CLI release preflight: validate nested gallery repos before publishing."""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_gallery(tmp_path: Path, name: str = "curiator-demo") -> Path:
    repo = tmp_path / "galleries" / name
    (repo / "apps").mkdir(parents=True)
    (repo / "feedback").mkdir()
    (repo / "apps" / "sample.py").write_text("app = object()\n")
    (repo / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            mount: { kind: dash-inproc, module: sample }
            source: apps/sample.py
        runner:
          mode: pinned
        feedback:
          dir: feedback
        shell:
          port: 8399
    """))
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test Curator")
    _git(repo, "config", "user.email", "curator@test.local")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_release_preflight_checks_nested_gallery(tmp_path, monkeypatch, capsys):
    from curiator import cli

    _make_gallery(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["galleries"][0]["doctor"]["ok"] is True
    assert payload["galleries"][0]["smoke"]["ok"] is True


def test_release_preflight_fails_dirty_gallery_by_default(tmp_path, monkeypatch, capsys):
    from curiator import cli

    repo = _make_gallery(tmp_path)
    (repo / "apps" / "sample.py").write_text("app = object()\nVALUE = 2\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["galleries"][0]["dirty"]

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--allow-dirty", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_release_preflight_flags_tracked_machine_paths(tmp_path, monkeypatch, capsys):
    from curiator import cli

    repo = _make_gallery(tmp_path)
    (repo / "README.md").write_text("Do not publish /Users/alice/private/curiator checkout paths.\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "add bad path")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["galleries"][0]["path_hits"][0]["file"] == "README.md"


def test_release_preflight_can_check_a_fresh_clone(tmp_path, monkeypatch, capsys):
    from curiator import cli

    _make_gallery(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main([
        "release-preflight",
        "--gallery", "curiator-demo",
        "--fresh-clone",
        "--clone-root", "clones",
        "--keep-clones",
        "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    gallery = payload["galleries"][0]
    assert payload["checks"]["fresh_clone"] is True
    assert Path(payload["clone_root"]).exists()
    assert gallery["mode"] == "fresh-clone"
    assert gallery["source_path"].endswith("galleries/curiator-demo")
    assert gallery["path"].startswith(str(tmp_path / "clones"))
    assert gallery["ok"] is True


def test_release_preflight_fresh_clone_fails_dirty_source_by_default(tmp_path, monkeypatch, capsys):
    from curiator import cli

    repo = _make_gallery(tmp_path)
    (repo / "apps" / "sample.py").write_text("app = object()\nVALUE = 2\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--fresh-clone", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    gallery = payload["galleries"][0]
    assert payload["ok"] is False
    assert gallery["mode"] == "fresh-clone"
    assert gallery["dirty"]
    assert "source repo is dirty" in gallery["error"]
