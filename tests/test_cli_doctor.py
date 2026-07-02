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


def test_doctor_warns_for_framework_base_path_misconfiguration(collection, capsys, monkeypatch):
    from curiator import cli

    monkeypatch.setattr(cli.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    (collection / "apps" / "vite_bad").mkdir()
    (collection / "apps" / "vite_bad" / "package.json").write_text('{"dependencies":{"vite":"^5.4.0"}}\n')
    (collection / "apps" / "vite_bad" / "vite.config.js").write_text("export default { plugins: [] };\n")
    (collection / "apps" / "next_bad").mkdir()
    (collection / "apps" / "next_bad" / "package.json").write_text('{"dependencies":{"next":"^14.2.0"}}\n')
    (collection / "apps" / "next_bad" / "next.config.mjs").write_text("export default {};\n")
    (collection / "apps" / "fastapi_bad").mkdir()
    (collection / "apps" / "fastapi_bad" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (collection / "apps" / "fastapi_bad" / "requirements.txt").write_text("fastapi>=0.115\n")
    (collection / "apps" / "gradio_bad").mkdir()
    (collection / "apps" / "gradio_bad" / "app.py").write_text("import gradio as gr\n")
    (collection / "apps" / "gradio_bad" / "requirements.txt").write_text("gradio>=4.44\n")
    (collection / "apps" / "streamlit_bad").mkdir()
    (collection / "apps" / "streamlit_bad" / "app.py").write_text("import streamlit as st\n")
    (collection / "apps" / "streamlit_bad" / "requirements.txt").write_text("streamlit>=1.36\n")
    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: vite_bad
            root: apps/vite_bad
            source: .
            smoke: npm run build
            mount: { kind: proxy, cmd: "npm run dev -- --host 127.0.0.1 --port 8800", port: 8800 }
          - name: next_bad
            root: apps/next_bad
            source: .
            smoke: npm run build
            mount: { kind: proxy, cmd: "npm run dev -- -H 127.0.0.1 -p 8801", port: 8801 }
          - name: fastapi_bad
            root: apps/fastapi_bad
            source: .
            smoke: python -m py_compile main.py
            mount: { kind: proxy, cmd: "python main.py --port 8802", port: 8802 }
          - name: gradio_bad
            root: apps/gradio_bad
            source: .
            smoke: python -m py_compile app.py
            mount: { kind: proxy, cmd: "python app.py --port 8803", port: 8803 }
          - name: streamlit_bad
            root: apps/streamlit_bad
            source: .
            smoke: python -m py_compile app.py
            mount: { kind: proxy, cmd: "streamlit run app.py --server.port 8804", port: 8804 }
    """))

    assert cli.main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["errors"] == 0
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert "Vite config does not appear to set an /app/<name>/ base path from CURIATOR_APP" in messages
    assert "Next.js proxy mount should set preserve_prefix: true" in messages
    assert "Next.js config does not appear to set basePath from CURIATOR_APP" in messages
    assert "FastAPI app does not appear to configure root_path for /app/<name>/" in messages
    assert "Gradio proxy mount should set preserve_prefix: true" in messages
    assert "Gradio app does not appear to configure root_path for /app/<name>/" in messages
    assert "Streamlit proxy mount should set preserve_prefix: true" in messages
    assert "Streamlit command does not set --server.baseUrlPath app/{app}" in messages


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
    (collection / "apps" / "fastapi_panel").mkdir()
    (collection / "apps" / "fastapi_panel" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (collection / "apps" / "gradio_panel").mkdir()
    (collection / "apps" / "gradio_panel" / "app.py").write_text("import gradio as gr\n")
    (collection / "apps" / "fastapi_ok").mkdir()
    (collection / "apps" / "fastapi_ok" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (collection / "apps" / "fastapi_ok" / "requirements.txt").write_text("fastapi>=0.115\n")
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
          - name: fastapi_panel
            root: apps/fastapi_panel
            source: .
            smoke: python -m py_compile main.py
            mount: { kind: proxy, cmd: "python main.py --port 8802 --root-path /app/{app}", port: 8802 }
          - name: gradio_panel
            root: apps/gradio_panel
            source: .
            smoke: python -m py_compile app.py
            mount: { kind: proxy, cmd: "python app.py --port 8803 --root-path /app/{app}", port: 8803 }
          - name: fastapi_ok
            root: apps/fastapi_ok
            source: .
            smoke: python -m py_compile main.py
            mount: { kind: proxy, cmd: "python main.py --port 8804 --root-path /app/{app}", port: 8804 }
    """))

    assert cli.main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["errors"] == 0
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert "Node app is missing dependency manifest (package.json)" in messages
    assert "Python/Streamlit app is missing dependency manifest" in messages
    assert "Python/FastAPI app is missing dependency manifest" in messages
    assert "Python/Gradio app is missing dependency manifest" in messages
    assert "requirements.txt or pyproject.toml" in messages
    assert all(issue["where"] != "app fastapi_ok dependencies" for issue in payload["issues"])
