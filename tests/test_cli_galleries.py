from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import yaml


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_gallery(tmp_path: Path, name: str = "curiator-demo") -> Path:
    repo = tmp_path / "galleries" / name
    (repo / "apps").mkdir(parents=True)
    (repo / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            mount: { kind: dash-inproc, module: sample }
            source: apps/sample.py
    """))
    (repo / "apps" / "sample.py").write_text("app = object()\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test Curator")
    _git(repo, "config", "user.email", "curator@test.local")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _make_sibling_gallery(base: Path, project: Path, name: str = "curiator-demo") -> Path:
    repo = base / name
    (repo / "apps").mkdir(parents=True)
    (repo / "gallery.yaml").write_text(textwrap.dedent(f"""\
        apps:
          - name: sample
            title: Sample
            mount: {{ kind: dash-inproc, module: sample }}
            source: apps/sample.py
        runner:
          mode: checkout
          path: ../{project.name}
    """))
    (repo / "apps" / "sample.py").write_text("app = object()\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test Curator")
    _git(repo, "config", "user.email", "curator@test.local")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_galleries_lists_nested_collection_repos(tmp_path, monkeypatch, capsys):
    from curiator import cli

    repo = _make_gallery(tmp_path)
    (repo / "apps" / "sample.py").write_text("app = object()\nVALUE = 2\n")
    (tmp_path / "galleries" / "notes").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["galleries", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["root"] == str((tmp_path / "galleries").resolve())
    assert [g["name"] for g in payload["galleries"]] == ["curiator-demo"]
    gallery = payload["galleries"][0]
    assert gallery["git"] is True
    assert gallery["head"]
    assert gallery["dirty"] == [" M apps/sample.py"]


def test_galleries_prints_target_command(tmp_path, monkeypatch, capsys):
    from curiator import cli

    _make_gallery(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["galleries"]) == 0
    out = capsys.readouterr().out

    assert "curiator-demo" in out
    assert "CURIATOR_GALLERY=galleries/curiator-demo/gallery.yaml curiator status" in out


def test_galleries_adopt_moves_sibling_repo_and_rewrites_runner_path(tmp_path, monkeypatch, capsys):
    from curiator import cli

    project = tmp_path / "curiator"
    project.mkdir()
    source = _make_sibling_gallery(tmp_path, project)
    monkeypatch.chdir(project)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["galleries", "adopt", str(source), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    dest = project / "galleries" / "curiator-demo"
    assert payload["ok"] is True
    assert payload["action"] == "move"
    assert payload["destination"] == str(dest.resolve())
    assert payload["runner_rewrites"] == [{
        "field": "runner.path",
        "from": f"../{project.name}",
        "to": "../..",
        "reason": "source runner.path resolved to this curIAtor checkout before adoption",
    }]
    assert not source.exists()
    data = yaml.safe_load((dest / "gallery.yaml").read_text())
    assert data["runner"] == {"mode": "checkout", "path": "../.."}

    assert cli.main(["galleries", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [g["name"] for g in listed["galleries"]] == ["curiator-demo"]


def test_galleries_adopt_copy_keeps_source_and_can_skip_runner_rewrite(tmp_path, monkeypatch, capsys):
    from curiator import cli

    project = tmp_path / "curiator"
    project.mkdir()
    source = _make_sibling_gallery(tmp_path, project)
    monkeypatch.chdir(project)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["galleries", "adopt", str(source), "--copy", "--no-rewrite-runner", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    dest = project / "galleries" / "curiator-demo"
    assert payload["ok"] is True
    assert payload["action"] == "copy"
    assert payload["runner_rewrites"] == []
    assert source.exists()
    assert dest.exists()
    assert yaml.safe_load((source / "gallery.yaml").read_text())["runner"]["path"] == f"../{project.name}"
    assert yaml.safe_load((dest / "gallery.yaml").read_text())["runner"]["path"] == f"../{project.name}"


def test_galleries_adopt_refuses_existing_destination(tmp_path, monkeypatch, capsys):
    from curiator import cli

    project = tmp_path / "curiator"
    project.mkdir()
    _make_gallery(project)
    source = _make_sibling_gallery(tmp_path, project)
    monkeypatch.chdir(project)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["galleries", "adopt", str(source), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is False
    assert "destination already exists" in payload["error"]
    assert source.exists()
