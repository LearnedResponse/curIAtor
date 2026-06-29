"""Shared fixtures: an isolated, git-initialized **collection** in a tmp dir, so the whole stack
(config → registry → ledger → gitmem → adapters → loop) is testable without the real repo or a live
agent. The `collection` fixture points CURIATOR_GALLERY at the tmp gallery; `cfg` is its loaded config.
"""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

SAMPLE_APP = textwrap.dedent('''\
    import dash
    from dash import html

    def build_app():
        app = dash.Dash(__name__)
        app.layout = html.Div("sample")
        return app

    app = build_app()
''')

GALLERY = textwrap.dedent('''\
    apps:
      - name: sample
        title: Sample
        mount: { kind: dash-inproc, module: sample }
        source: apps/sample.py
        tags: [demo]
    agent:
      adapter: headless-cc
      autonomy: auto-small
    runner:
      mode: checkout
      path: .
    feedback:
      dir: feedback
      screenshots: true
    shell:
      port: 8399
    git:
      commit: true
      branch:
      signoff: true
      include_ledger: true
''')


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def collection(tmp_path: Path, monkeypatch) -> Path:
    """A self-contained collection repo: gallery.yaml + apps/sample.py + feedback/ + an initial commit."""
    (tmp_path / "apps").mkdir()
    (tmp_path / "feedback" / "shots").mkdir(parents=True)
    (tmp_path / "apps" / "sample.py").write_text(SAMPLE_APP)
    (tmp_path / "gallery.yaml").write_text(GALLERY)
    (tmp_path / "feedback" / "app_feedback.json").write_text("{}\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "Test Curator")
    _git(tmp_path, "config", "user.email", "curator@test.local")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    monkeypatch.setenv("CURIATOR_GALLERY", str(tmp_path / "gallery.yaml"))
    return tmp_path


@pytest.fixture
def cfg(collection: Path) -> dict:
    from curiator.config import load_config
    return load_config()
