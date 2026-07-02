"""CLI app scaffolding: create app directories and update gallery.yaml."""
from __future__ import annotations

import yaml


def _gallery(collection):
    return yaml.safe_load((collection / "gallery.yaml").read_text())


def test_app_create_dash_directory_updates_gallery(collection):
    from curiator import cli

    rc = cli.main([
        "app", "create", "orange_picker",
        "--template", "dash",
        "--title", "Orange Picker",
        "--tags", "dash,vision",
    ])

    assert rc == 0
    assert (collection / "apps" / "orange_picker" / "orange_picker.py").exists()
    data = _gallery(collection)
    app = next(a for a in data["apps"] if a["name"] == "orange_picker")
    assert app["root"] == "apps/orange_picker"
    assert app["source"] == "."
    assert app["smoke"] == "python -m compileall -q ."
    assert app["mount"] == {"kind": "dash-inproc", "module": "orange_picker"}
    assert app["tags"] == ["dash", "vision"]


def test_init_app_alias_static_and_python_proxy_ports(collection):
    from curiator import cli

    assert cli.main(["init-app", "landing_page", "--template", "static"]) == 0
    assert cli.main(["app", "create", "status_server", "--template", "python"]) == 0

    assert (collection / "apps" / "landing_page" / "index.html").exists()
    assert (collection / "apps" / "status_server" / "server.py").exists()
    data = _gallery(collection)
    landing = next(a for a in data["apps"] if a["name"] == "landing_page")
    status = next(a for a in data["apps"] if a["name"] == "status_server")
    assert landing["mount"]["kind"] == "proxy"
    assert landing["mount"]["port"] == 8700
    assert "http.server 8700" in landing["mount"]["cmd"]
    assert status["mount"]["kind"] == "proxy"
    assert status["mount"]["port"] == 8701
    assert status["smoke"] == "python -m py_compile server.py"


def test_app_create_react_and_svelte_proxy_templates(collection):
    from curiator import cli

    assert cli.main(["app", "create", "react_board", "--template", "react"]) == 0
    assert cli.main(["app", "create", "svelte_panel", "--template", "svelte"]) == 0

    react_root = collection / "apps" / "react_board"
    svelte_root = collection / "apps" / "svelte_panel"
    assert (react_root / "package.json").exists()
    assert (react_root / "src" / "App.jsx").exists()
    assert (svelte_root / "package.json").exists()
    assert (svelte_root / "src" / "App.svelte").exists()
    assert "base = app ? `/app/${app}/` : \"/\"" in (react_root / "vite.config.js").read_text()
    assert "base = app ? `/app/${app}/` : \"/\"" in (svelte_root / "vite.config.js").read_text()

    data = _gallery(collection)
    react = next(a for a in data["apps"] if a["name"] == "react_board")
    svelte = next(a for a in data["apps"] if a["name"] == "svelte_panel")
    assert react["mount"]["kind"] == "proxy"
    assert react["mount"]["port"] == 8700
    assert react["mount"]["cmd"] == "npm run dev -- --host 127.0.0.1 --port 8700"
    assert react["smoke"] == "npm run build"
    assert svelte["mount"]["port"] == 8701
    assert svelte["smoke"] == "npm run build"


def test_app_create_rejects_duplicate_or_invalid_name(collection):
    from curiator import cli

    assert cli.main(["app", "create", "sample"]) == 1
    assert cli.main(["app", "create", "bad-name"]) == 1
