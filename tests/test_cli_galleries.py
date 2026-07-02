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
