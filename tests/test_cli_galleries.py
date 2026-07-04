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
    assert "curiator --gallery galleries/curiator-demo/gallery.yaml status" in out


def test_galleries_reports_sibling_checkout_to_adopt(tmp_path, monkeypatch, capsys):
    from curiator import cli

    project = tmp_path / "curiator"
    project.mkdir()
    _make_sibling_gallery(tmp_path, project)
    monkeypatch.chdir(project)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["galleries", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["galleries"] == []
    assert payload["sibling_galleries"] == [{
        "name": "curiator-demo",
        "path": str(tmp_path / "curiator-demo"),
        "resolved": str((tmp_path / "curiator-demo").resolve()),
        "is_symlink": False,
        "relation": "sibling-checkout",
        "adopt_command": "curiator galleries adopt ../curiator-demo",
    }]

    assert cli.main(["galleries"]) == 0
    out = capsys.readouterr().out
    assert "sibling curiator-* gallery paths found" in out
    assert "adopt: curiator galleries adopt ../curiator-demo" in out


def test_galleries_reports_sibling_symlink_alias_to_nested_repo(tmp_path, monkeypatch, capsys):
    from curiator import cli

    project = tmp_path / "curiator"
    project.mkdir()
    nested = _make_gallery(project)
    alias = tmp_path / "curiator-demo"
    alias.symlink_to(nested, target_is_directory=True)
    monkeypatch.chdir(project)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["galleries", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [g["name"] for g in payload["galleries"]] == ["curiator-demo"]
    assert payload["sibling_galleries"] == [{
        "name": "curiator-demo",
        "path": str(alias),
        "resolved": str(nested.resolve()),
        "is_symlink": True,
        "relation": "alias-to-nested",
    }]

    assert cli.main(["galleries"]) == 0
    out = capsys.readouterr().out
    assert "curiator-demo: alias -> galleries/curiator-demo" in out
    assert "archive or remove the alias" in out
    assert "adopt:" not in out


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


def test_galleries_clone_git_url_into_nested_workspace(tmp_path, monkeypatch, capsys):
    from curiator import cli

    source = _make_gallery(tmp_path / "remote", name="curiator-remote")
    project = tmp_path / "curiator"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["galleries", "clone", source.as_uri(), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    dest = project / "galleries" / "curiator-remote"
    assert payload["ok"] is True
    assert payload["action"] == "clone"
    assert payload["destination"] == str(dest.resolve())
    assert payload["runner_rewrites"] == []
    assert source.exists()
    assert (dest / ".git").exists()
    assert (dest / "gallery.yaml").exists()

    assert cli.main(["galleries", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [g["name"] for g in listed["galleries"]] == ["curiator-remote"]


def test_galleries_clone_local_repo_can_rewrite_runner_path(tmp_path, monkeypatch, capsys):
    from curiator import cli

    project = tmp_path / "curiator"
    project.mkdir()
    source = _make_sibling_gallery(tmp_path, project)
    monkeypatch.chdir(project)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["galleries", "clone", str(source), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    dest = project / "galleries" / "curiator-demo"
    assert payload["ok"] is True
    assert payload["runner_rewrites"] == [{
        "field": "runner.path",
        "from": f"../{project.name}",
        "to": "../..",
        "reason": "source runner.path resolved to this curIAtor checkout before adoption",
    }]
    assert source.exists()
    assert yaml.safe_load((source / "gallery.yaml").read_text())["runner"]["path"] == f"../{project.name}"
    assert yaml.safe_load((dest / "gallery.yaml").read_text())["runner"] == {"mode": "checkout", "path": "../.."}


def test_galleries_clone_rejects_non_gallery_and_cleans_destination(tmp_path, monkeypatch, capsys):
    from curiator import cli

    source = tmp_path / "not-gallery"
    source.mkdir()
    (source / "README.md").write_text("# not a curIAtor gallery\n")
    _git(source, "init", "-q")
    _git(source, "config", "user.name", "Test Curator")
    _git(source, "config", "user.email", "curator@test.local")
    _git(source, "add", "-A")
    _git(source, "commit", "-q", "-m", "init")
    project = tmp_path / "curiator"
    project.mkdir()
    monkeypatch.chdir(project)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["galleries", "clone", source.as_uri(), "--name", "broken", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is False
    assert "missing gallery.yaml" in payload["error"]
    assert not (project / "galleries" / "curiator-broken").exists()
