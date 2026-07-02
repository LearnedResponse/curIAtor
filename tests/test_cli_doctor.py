"""CLI doctor: release-preflight checks for collection portability."""
from __future__ import annotations

import json
import textwrap


def test_doctor_ok_for_portable_collection(collection, capsys):
    from curiator import cli

    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "doctor OK" in out


def test_doctor_flags_absolute_paths_and_missing_sources(collection, capsys):
    from curiator import cli

    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            mount: { kind: dash-inproc, module: sample }
            source: apps/missing.py
        runner:
          mode: checkout
          path: /home/adamguetz/projects/curiator
    """))

    assert cli.main(["doctor", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert "absolute path" in messages or "machine-local path" in messages
    assert "configured path does not exist" in messages


def test_doctor_warns_without_failing_for_weak_release_smoke(collection, capsys):
    from curiator import cli

    (collection / "apps" / "proxy_app").mkdir()
    (collection / "apps" / "proxy_app" / "server.py").write_text("print('ok')\n")
    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: proxy_app
            root: apps/proxy_app
            source: .
            mount: { kind: proxy, cmd: "python server.py", port: 8800 }
    """))

    assert cli.main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["errors"] == 0
    assert payload["warnings"] == 2
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert "no smoke command configured" in messages
    assert "does not mention configured port 8800" in messages


def test_doctor_warns_for_hmr_dev_server_proxy_without_failing(collection, capsys, monkeypatch):
    from curiator import cli

    monkeypatch.setattr(cli.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    (collection / "apps" / "react_panel").mkdir()
    (collection / "apps" / "react_panel" / "package.json").write_text('{"scripts":{"dev":"vite"}}\n')
    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: react_panel
            root: apps/react_panel
            source: .
            smoke: npm run build
            mount: { kind: proxy, cmd: "npm run dev -- --host 127.0.0.1 --port 8800", port: 8800 }
    """))

    assert cli.main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["errors"] == 0
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert "framework dev server" in messages
    assert "WebSocket/HMR" in messages


def test_doctor_warns_for_missing_smoke_executable_without_failing(collection, capsys, monkeypatch):
    from curiator import cli

    monkeypatch.setattr(cli.shutil, "which", lambda exe: None if exe == "missing-smoke-tool" else f"/usr/bin/{exe}")
    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            mount: { kind: dash-inproc, module: sample }
            source: apps/sample.py
            smoke: missing-smoke-tool --check apps/sample.py
    """))

    assert cli.main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["errors"] == 0
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert "smoke command executable not found on PATH: missing-smoke-tool" in messages


def test_doctor_warns_for_missing_dependency_manifests_separately(collection, capsys, monkeypatch):
    from curiator import cli

    monkeypatch.setattr(cli.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    (collection / "apps" / "node_panel").mkdir()
    (collection / "apps" / "node_panel" / "server.js").write_text("console.log('ok')\n")
    (collection / "apps" / "streamlit_panel").mkdir()
    (collection / "apps" / "streamlit_panel" / "app.py").write_text("print('ok')\n")
    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: node_panel
            root: apps/node_panel
            source: .
            smoke: npm run build
            mount: { kind: proxy, cmd: "npm run dev -- --port 8800", port: 8800 }
          - name: streamlit_panel
            root: apps/streamlit_panel
            source: .
            smoke: python -m py_compile app.py
            mount: { kind: proxy, cmd: "streamlit run app.py --server.port 8801", port: 8801 }
    """))

    assert cli.main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["errors"] == 0
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert "Node app is missing dependency manifest (package.json)" in messages
    assert "Python/Streamlit app is missing dependency manifest" in messages
    assert "requirements.txt or pyproject.toml" in messages
