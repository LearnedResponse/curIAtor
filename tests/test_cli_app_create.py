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


def test_app_create_react_svelte_and_vue_proxy_templates(collection):
    from curiator import cli

    assert cli.main(["app", "create", "react_board", "--template", "react"]) == 0
    assert cli.main(["app", "create", "svelte_panel", "--template", "svelte"]) == 0
    assert cli.main(["app", "create", "vue_view", "--template", "vue"]) == 0

    react_root = collection / "apps" / "react_board"
    svelte_root = collection / "apps" / "svelte_panel"
    vue_root = collection / "apps" / "vue_view"
    assert (react_root / "package.json").exists()
    assert (react_root / "src" / "App.jsx").exists()
    assert (svelte_root / "package.json").exists()
    assert (svelte_root / "src" / "App.svelte").exists()
    assert (vue_root / "package.json").exists()
    assert (vue_root / "src" / "App.vue").exists()
    assert "base = app ? `/app/${app}/` : \"/\"" in (react_root / "vite.config.js").read_text()
    assert "base = app ? `/app/${app}/` : \"/\"" in (svelte_root / "vite.config.js").read_text()
    assert "base = app ? `/app/${app}/` : \"/\"" in (vue_root / "vite.config.js").read_text()

    data = _gallery(collection)
    react = next(a for a in data["apps"] if a["name"] == "react_board")
    svelte = next(a for a in data["apps"] if a["name"] == "svelte_panel")
    vue = next(a for a in data["apps"] if a["name"] == "vue_view")
    assert react["mount"]["kind"] == "proxy"
    assert react["mount"]["port"] == 8700
    assert react["mount"]["cmd"] == "npm run dev -- --host 127.0.0.1 --port 8700"
    assert react["smoke"] == "npm run build"
    assert svelte["mount"]["port"] == 8701
    assert svelte["smoke"] == "npm run build"
    assert vue["mount"]["port"] == 8702
    assert vue["smoke"] == "npm run build"
    assert "npm run build" in (react_root / "src" / "App.jsx").read_text()
    assert "npm run build" in (vue_root / "src" / "App.vue").read_text()


def test_app_create_js_package_manager_detection_and_override(collection):
    from curiator import cli

    (collection / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    assert cli.main(["app", "create", "react_pnpm", "--template", "react"]) == 0
    assert cli.main([
        "app", "create", "svelte_yarn",
        "--template", "svelte",
        "--package-manager", "yarn",
    ]) == 0
    assert cli.main([
        "app", "create", "vue_bun",
        "--template", "vue",
        "--package-manager", "bun",
    ]) == 0

    data = _gallery(collection)
    react = next(a for a in data["apps"] if a["name"] == "react_pnpm")
    svelte = next(a for a in data["apps"] if a["name"] == "svelte_yarn")
    vue = next(a for a in data["apps"] if a["name"] == "vue_bun")
    assert react["smoke"] == "pnpm run build"
    assert react["mount"]["cmd"] == "pnpm run dev -- --host 127.0.0.1 --port 8700"
    assert svelte["smoke"] == "yarn run build"
    assert svelte["mount"]["cmd"] == "yarn run dev --host 127.0.0.1 --port 8701"
    assert vue["smoke"] == "bun run build"
    assert vue["mount"]["cmd"] == "bun run dev -- --host 127.0.0.1 --port 8702"
    assert "pnpm run build" in (collection / "apps" / "react_pnpm" / "src" / "App.jsx").read_text()
    assert "yarn run build" in (collection / "apps" / "svelte_yarn" / "src" / "App.svelte").read_text()
    assert "bun run build" in (collection / "apps" / "vue_bun" / "src" / "App.vue").read_text()


def test_app_create_streamlit_proxy_template(collection):
    from curiator import cli

    assert cli.main(["app", "create", "demo_streamlit", "--template", "streamlit"]) == 0

    root = collection / "apps" / "demo_streamlit"
    assert (root / "app.py").exists()
    assert (root / "requirements.txt").read_text() == "streamlit>=1.36\n"
    readme = (root / "README.md").read_text()
    assert "--server.baseUrlPath app/demo_streamlit" in readme
    assert "preserve_prefix: true" in readme
    assert "WebSocket or production reverse-proxy behavior" in readme

    data = _gallery(collection)
    app = next(a for a in data["apps"] if a["name"] == "demo_streamlit")
    assert app["mount"]["kind"] == "proxy"
    assert app["mount"]["port"] == 8700
    assert app["mount"]["preserve_prefix"] is True
    assert "streamlit run app.py" in app["mount"]["cmd"]
    assert "--server.baseUrlPath app/{app}" in app["mount"]["cmd"]
    assert app["smoke"] == "python -m py_compile app.py"
    assert app["tags"] == ["streamlit"]


def test_app_create_rejects_duplicate_or_invalid_name(collection):
    from curiator import cli

    assert cli.main(["app", "create", "sample"]) == 1
    assert cli.main(["app", "create", "bad-name"]) == 1
