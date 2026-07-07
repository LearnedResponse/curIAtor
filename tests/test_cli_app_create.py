"""CLI app scaffolding: create app directories and update gallery.yaml."""
from __future__ import annotations

import json
import subprocess

import yaml


def _gallery(collection):
    return yaml.safe_load((collection / "gallery.yaml").read_text())


def _git(cwd, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _node_app_repo(path, *, pnpm_lock: bool = False):
    path.mkdir()
    (path / "server.js").write_text(
        "import http from 'node:http';\n"
        "const port = Number(process.argv.at(-1)) || 8700;\n"
        "http.createServer((req, res) => res.end('ok')).listen(port, '127.0.0.1');\n"
    )
    (path / "package.json").write_text(
        '{\n'
        '  "type": "module",\n'
        '  "scripts": {\n'
        '    "build": "node --check server.js",\n'
        '    "dev": "node server.js",\n'
        '    "preview": "node server.js"\n'
        "  }\n"
        "}\n"
    )
    (path / "README.md").write_text("# imported app\n")
    if pnpm_lock:
        (path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "Test Curator")
    _git(path, "config", "user.email", "curator@test.local")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init app")
    return path


def _next_app_repo(path):
    path.mkdir()
    (path / "package.json").write_text(
        '{\n'
        '  "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},\n'
        '  "dependencies": {"next": "^14.2.0", "react": "^18.3.1", "react-dom": "^18.3.1"}\n'
        "}\n"
    )
    (path / "app").mkdir()
    (path / "app" / "page.jsx").write_text('export default function Page() { return "ok"; }\n')
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "Test Curator")
    _git(path, "config", "user.email", "curator@test.local")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init next app")
    return path


def test_app_templates_lists_supported_template_contract(capsys):
    from curiator import cli

    assert cli.main(["app", "templates"]) == 0
    out = capsys.readouterr().out
    assert "curiator: 13 app templates" in out
    assert "dash" in out and "dash-inproc" in out
    assert "react" in out and "vite+react" in out
    assert "next" in out and "proxy preserve-prefix" in out
    assert "curiator app create <name> --template <template>" in out

    assert cli.main(["app", "templates", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["name"] for row in rows] == list(cli._APP_TEMPLATE_CHOICES)
    assert {row["name"] for row in rows} == {
        "dash",
        "static",
        "python",
        "node",
        "flask",
        "fastapi",
        "rust",
        "react",
        "svelte",
        "vue",
        "next",
        "streamlit",
        "gradio",
    }
    assert next(row for row in rows if row["name"] == "dash")["mount"] == "dash-inproc"
    assert next(row for row in rows if row["name"] == "gradio")["mount"] == "proxy preserve-prefix"


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


def test_app_create_matches_column_zero_app_indentation(collection):
    """Regression: galleries whose app list items sit at column 0 (e.g. generated ones like Kwisatz's)
    must get a new entry at the SAME indent — a hardcoded 2-space entry lands nested under the previous
    app and corrupts the YAML."""
    from curiator import cli

    (collection / "gallery.yaml").write_text(
        "apps:\n"
        "- name: sample\n"                          # dash at column 0, keys at 2 (all_apps_index style)
        "  title: Sample\n"
        "  source: apps/sample.py\n"
        "  mount: { kind: dash-inproc, module: sample }\n"
        "  tags: [demo]\n"
        "shell:\n"
        "  port: 8399\n"
    )

    assert cli.main(["app", "create", "second_app", "--template", "dash", "--title", "Second"]) == 0

    text = (collection / "gallery.yaml").read_text()
    data = _gallery(collection)                      # must still parse
    assert [a["name"] for a in data["apps"]] == ["sample", "second_app"]
    assert "\n- name: second_app\n" in text          # new item at column 0, matching the existing ones
    assert "\n  - name: second_app\n" not in text     # NOT over-indented under `sample`


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
    assert landing["commands"]["preview"] == "python -m http.server 8700 --bind 127.0.0.1"
    assert status["mount"]["kind"] == "proxy"
    assert status["mount"]["port"] == 8701
    assert status["mount"]["cmd"] == "python server.py --port 8701"
    assert status["smoke"] == "python -m py_compile server.py"
    assert status["commands"]["preview"] == "python server.py --port 8701"
    assert "argparse" in (collection / "apps" / "status_server" / "server.py").read_text()


def test_app_create_node_proxy_template(collection, capsys):
    from curiator import cli
    from curiator.config import app_spec, load_config

    assert cli.main(["app", "create", "node_status", "--template", "node"]) == 0

    root = collection / "apps" / "node_status"
    assert (root / "server.js").exists()
    assert (root / "package.json").exists()
    assert (root / "README.md").exists()
    server_js = (root / "server.js").read_text()
    assert "import http from \"node:http\"" in server_js
    assert "node --check server.js" in server_js
    assert "server.listen(port, \"127.0.0.1\"" in server_js

    data = _gallery(collection)
    app = next(a for a in data["apps"] if a["name"] == "node_status")
    assert app["mount"] == {"kind": "proxy", "cmd": "node server.js --port 8700", "port": 8700}
    assert app["smoke"] == "node --check server.js"
    assert app["commands"]["preview"] == "node server.js --port 8700"
    assert app["tags"] == ["node"]
    assert app_spec(load_config(), "node_status")["commands"]["preview"] == "node server.js --port 8700"

    assert cli.main(["context", "--app", "node_status", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "- smoke: `node --check server.js`" in out
    assert "- preview: `node server.js --port 8700`" in out


def test_app_create_flask_proxy_template(collection, capsys):
    import importlib.util
    import py_compile

    from curiator import cli
    from curiator.config import app_spec, load_config

    assert cli.main(["app", "create", "flask_panel", "--template", "flask"]) == 0

    root = collection / "apps" / "flask_panel"
    assert (root / "app.py").exists()
    assert (root / "README.md").exists()
    app_py = (root / "app.py").read_text()
    assert "from flask import Flask, jsonify, render_template_string" in app_py
    assert "def create_app() -> Flask:" in app_py
    assert "@app.get(\"/healthz\")" in app_py
    assert "python -m py_compile app.py" in app_py
    py_compile.compile(str(root / "app.py"), doraise=True)
    spec = importlib.util.spec_from_file_location("generated_flask_panel", root / "app.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    assert module.create_app().test_client().get("/healthz").get_json() == {"ok": True, "app": "flask_panel"}

    data = _gallery(collection)
    app = next(a for a in data["apps"] if a["name"] == "flask_panel")
    assert app["mount"] == {"kind": "proxy", "cmd": "python app.py --port 8700", "port": 8700}
    assert app["smoke"] == "python -m py_compile app.py"
    assert app["commands"]["preview"] == "python app.py --port 8700"
    assert app["tags"] == ["flask"]
    assert app_spec(load_config(), "flask_panel")["commands"]["preview"] == "python app.py --port 8700"

    assert cli.main(["context", "--app", "flask_panel", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "- smoke: `python -m py_compile app.py`" in out
    assert "- preview: `python app.py --port 8700`" in out


def test_app_create_fastapi_proxy_template(collection, capsys):
    import py_compile

    from curiator import cli
    from curiator.config import app_spec, load_config

    assert cli.main(["app", "create", "api_panel", "--template", "fastapi"]) == 0

    root = collection / "apps" / "api_panel"
    assert (root / "main.py").exists()
    assert (root / "README.md").exists()
    assert (root / "requirements.txt").read_text() == "fastapi>=0.115\nuvicorn[standard]>=0.30\n"
    main_py = (root / "main.py").read_text()
    assert "from fastapi import FastAPI" in main_py
    assert "@app.get(\"/api/status\")" in main_py
    assert "uvicorn.run(app, host=\"127.0.0.1\", port=args.port, root_path=args.root_path)" in main_py
    assert "python -m py_compile main.py" in main_py
    py_compile.compile(str(root / "main.py"), doraise=True)

    readme = (root / "README.md").read_text()
    assert "--root-path /app/api_panel" in readme
    assert "OpenAPI/docs URLs" in readme

    data = _gallery(collection)
    app = next(a for a in data["apps"] if a["name"] == "api_panel")
    assert app["mount"] == {
        "kind": "proxy",
        "cmd": "python main.py --port 8700 --root-path /app/{app}",
        "port": 8700,
    }
    assert app["smoke"] == "python -m py_compile main.py"
    assert app["commands"]["preview"] == "python main.py --port 8700 --root-path /app/api_panel"
    assert app["tags"] == ["fastapi"]
    assert app_spec(load_config(), "api_panel")["commands"]["preview"] == "python main.py --port 8700 --root-path /app/api_panel"

    assert cli.main(["context", "--app", "api_panel", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "- smoke: `python -m py_compile main.py`" in out
    assert "- preview: `python main.py --port 8700 --root-path /app/api_panel`" in out


def test_app_create_rust_proxy_template(collection, capsys):
    import shutil
    import subprocess

    from curiator import cli
    from curiator.config import app_spec, load_config

    assert cli.main(["app", "create", "rust_status", "--template", "rust"]) == 0

    root = collection / "apps" / "rust_status"
    assert (root / "Cargo.toml").exists()
    assert (root / "src" / "main.rs").exists()
    assert (root / "README.md").exists()
    cargo_toml = (root / "Cargo.toml").read_text()
    main_rs = (root / "src" / "main.rs").read_text()
    assert 'name = "rust_status"' in cargo_toml
    assert "std::net::{TcpListener, TcpStream}" in main_rs
    assert "cargo check --quiet" in main_rs
    assert 'path == "/healthz"' in main_rs
    if shutil.which("cargo"):
        subprocess.run(["cargo", "check", "--quiet"], cwd=root, check=True)

    data = _gallery(collection)
    app = next(a for a in data["apps"] if a["name"] == "rust_status")
    assert app["mount"] == {"kind": "proxy", "cmd": "cargo run --quiet -- --port 8700", "port": 8700}
    assert app["smoke"] == "cargo check --quiet"
    assert app["commands"]["preview"] == "cargo run --quiet -- --port 8700"
    assert app["tags"] == ["rust"]
    assert app_spec(load_config(), "rust_status")["commands"]["preview"] == "cargo run --quiet -- --port 8700"

    assert cli.main(["context", "--app", "rust_status", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "- smoke: `cargo check --quiet`" in out
    assert "- preview: `cargo run --quiet -- --port 8700`" in out


def test_app_create_react_svelte_and_vue_proxy_templates(collection, capsys):
    from curiator import cli
    from curiator.config import app_spec, load_config

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
    assert react["commands"]["preview"] == "npm run preview -- --host 127.0.0.1 --port 8700"
    assert svelte["mount"]["port"] == 8701
    assert svelte["smoke"] == "npm run build"
    assert svelte["commands"]["preview"] == "npm run preview -- --host 127.0.0.1 --port 8701"
    assert vue["mount"]["port"] == 8702
    assert vue["smoke"] == "npm run build"
    assert vue["commands"]["preview"] == "npm run preview -- --host 127.0.0.1 --port 8702"
    assert app_spec(load_config(), "react_board")["commands"]["preview"] == react["commands"]["preview"]
    assert "npm run build" in (react_root / "src" / "App.jsx").read_text()
    assert "npm run build" in (vue_root / "src" / "App.vue").read_text()

    assert cli.main(["status", "--app", "react_board"]) == 0
    assert cli.main(["context", "--app", "react_board", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "preview: npm run preview -- --host 127.0.0.1 --port 8700" in out
    assert "- preview: `npm run preview -- --host 127.0.0.1 --port 8700`" in out


def test_app_create_next_proxy_template(collection, capsys):
    from curiator import cli
    from curiator.config import app_spec, load_config

    assert cli.main(["app", "create", "next_board", "--template", "next"]) == 0

    root = collection / "apps" / "next_board"
    assert (root / "package.json").exists()
    assert (root / "next.config.mjs").exists()
    assert (root / "app" / "layout.jsx").exists()
    assert (root / "app" / "page.jsx").exists()
    assert (root / "app" / "api" / "status" / "route.js").exists()
    config = (root / "next.config.mjs").read_text()
    assert "const basePath = app ? `/app/${app}` : \"\"" in config
    assert "basePath," in config
    page = (root / "app" / "page.jsx").read_text()
    assert "server component" in page
    assert "npm run build" in page
    readme = (root / "README.md").read_text()
    assert "preserve_prefix: true" in readme
    assert 'basePath: "/app/next_board"' in readme
    assert "WebSocket/HMR" in readme

    data = _gallery(collection)
    app = next(a for a in data["apps"] if a["name"] == "next_board")
    assert app["mount"] == {
        "kind": "proxy",
        "cmd": "npm run dev -- -H 127.0.0.1 -p 8700",
        "port": 8700,
        "preserve_prefix": True,
    }
    assert app["smoke"] == "npm run build"
    assert app["commands"]["preview"] == "npm run start -- -H 127.0.0.1 -p 8700"
    assert app["tags"] == ["next"]
    assert app_spec(load_config(), "next_board")["commands"]["preview"] == "npm run start -- -H 127.0.0.1 -p 8700"

    assert cli.main(["context", "--app", "next_board", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "- smoke: `npm run build`" in out
    assert "- preview: `npm run start -- -H 127.0.0.1 -p 8700`" in out


def test_app_create_js_package_manager_detection_and_override(collection):
    from curiator import cli

    (collection / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    assert cli.main(["app", "create", "react_pnpm", "--template", "react"]) == 0
    assert cli.main(["app", "create", "next_pnpm", "--template", "next"]) == 0
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
    next_app = next(a for a in data["apps"] if a["name"] == "next_pnpm")
    svelte = next(a for a in data["apps"] if a["name"] == "svelte_yarn")
    vue = next(a for a in data["apps"] if a["name"] == "vue_bun")
    assert react["smoke"] == "pnpm run build"
    assert react["mount"]["cmd"] == "pnpm run dev -- --host 127.0.0.1 --port 8700"
    assert react["commands"]["preview"] == "pnpm run preview -- --host 127.0.0.1 --port 8700"
    assert next_app["smoke"] == "pnpm run build"
    assert next_app["mount"]["cmd"] == "pnpm run dev -- -H 127.0.0.1 -p 8701"
    assert next_app["mount"]["preserve_prefix"] is True
    assert next_app["commands"]["preview"] == "pnpm run start -- -H 127.0.0.1 -p 8701"
    assert svelte["smoke"] == "yarn run build"
    assert svelte["mount"]["cmd"] == "yarn run dev --host 127.0.0.1 --port 8702"
    assert svelte["commands"]["preview"] == "yarn run preview --host 127.0.0.1 --port 8702"
    assert vue["smoke"] == "bun run build"
    assert vue["mount"]["cmd"] == "bun run dev -- --host 127.0.0.1 --port 8703"
    assert vue["commands"]["preview"] == "bun run preview -- --host 127.0.0.1 --port 8703"
    assert "pnpm run build" in (collection / "apps" / "react_pnpm" / "src" / "App.jsx").read_text()
    assert "pnpm run build" in (collection / "apps" / "next_pnpm" / "app" / "page.jsx").read_text()
    assert "yarn run build" in (collection / "apps" / "svelte_yarn" / "src" / "App.svelte").read_text()
    assert "bun run build" in (collection / "apps" / "vue_bun" / "src" / "App.vue").read_text()


def test_app_create_streamlit_proxy_template(collection, capsys):
    from curiator import cli
    from curiator.config import app_spec, load_config

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
    assert app["commands"]["preview"] == (
        "streamlit run app.py --server.address 127.0.0.1 --server.port 8700 "
        "--server.headless true --server.baseUrlPath app/demo_streamlit --browser.gatherUsageStats false"
    )
    assert app["tags"] == ["streamlit"]
    assert app_spec(load_config(), "demo_streamlit")["commands"]["preview"] == app["commands"]["preview"]

    assert cli.main(["context", "--app", "demo_streamlit", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "- preview: `streamlit run app.py --server.address 127.0.0.1 --server.port 8700" in out


def test_app_create_gradio_proxy_template(collection, capsys):
    from curiator import cli
    from curiator.config import app_spec, load_config

    assert cli.main(["app", "create", "demo_gradio", "--template", "gradio"]) == 0

    root = collection / "apps" / "demo_gradio"
    assert (root / "app.py").exists()
    assert (root / "requirements.txt").read_text() == "gradio>=4.44\n"
    app_py = (root / "app.py").read_text()
    assert "root_path=args.root_path or None" in app_py
    assert "server_name=\"127.0.0.1\"" in app_py
    readme = (root / "README.md").read_text()
    assert "--root-path /app/demo_gradio" in readme
    assert "preserve_prefix: true" in readme

    data = _gallery(collection)
    app = next(a for a in data["apps"] if a["name"] == "demo_gradio")
    assert app["mount"]["kind"] == "proxy"
    assert app["mount"]["port"] == 8700
    assert app["mount"]["preserve_prefix"] is True
    assert "python app.py --port 8700 --root-path /app/{app}" == app["mount"]["cmd"]
    assert app["smoke"] == "python -m py_compile app.py"
    assert app["commands"]["preview"] == "python app.py --port 8700 --root-path /app/demo_gradio"
    assert app["tags"] == ["gradio"]
    assert app_spec(load_config(), "demo_gradio")["commands"]["preview"] == "python app.py --port 8700 --root-path /app/demo_gradio"

    assert cli.main(["context", "--app", "demo_gradio", "--limit", "1"]) == 0
    out = capsys.readouterr().out
    assert "- preview: `python app.py --port 8700 --root-path /app/demo_gradio`" in out


def test_app_create_rejects_duplicate_or_invalid_name(collection):
    from curiator import cli

    assert cli.main(["app", "create", "sample"]) == 1
    assert cli.main(["app", "create", "bad-name"]) == 1


def test_app_import_copies_local_repo_and_registers_proxy(collection, tmp_path):
    from curiator import cli
    from curiator.config import app_spec, load_config

    source = _node_app_repo(tmp_path / "external_node")

    assert cli.main([
        "app", "import", str(source), "imported_node",
        "--template", "node",
        "--title", "Imported Node",
        "--tags", "node,external",
        "--port", "8788",
    ]) == 0

    dest = collection / "apps" / "imported_node"
    assert (dest / ".git").exists()
    assert (dest / "server.js").read_text() == (source / "server.js").read_text()
    assert _git(dest, "rev-parse", "--is-inside-work-tree") == "true"

    data = _gallery(collection)
    app = next(a for a in data["apps"] if a["name"] == "imported_node")
    assert app["root"] == "apps/imported_node"
    assert app["source"] == "."
    assert app["mount"] == {"kind": "proxy", "cmd": "node server.js --port 8788", "port": 8788}
    assert app["smoke"] == "node --check server.js"
    assert app["commands"]["preview"] == "node server.js --port 8788"
    assert app["tags"] == ["node", "external"]
    assert app_spec(load_config(), "imported_node")["commands"]["preview"] == "node server.js --port 8788"


def test_app_import_clones_git_url_and_detects_package_manager(collection, tmp_path, capsys):
    from curiator import cli

    source = _node_app_repo(tmp_path / "external_vite", pnpm_lock=True)

    assert cli.main([
        "app", "import", source.as_uri(), "imported_react",
        "--template", "react",
        "--port", "8790",
    ]) == 0

    dest = collection / "apps" / "imported_react"
    assert (dest / ".git").exists()
    assert (dest / "pnpm-lock.yaml").exists()
    assert _git(dest, "rev-parse", "--is-inside-work-tree") == "true"

    data = _gallery(collection)
    app = next(a for a in data["apps"] if a["name"] == "imported_react")
    assert app["smoke"] == "pnpm run build"
    assert app["mount"] == {"kind": "proxy", "cmd": "pnpm run dev -- --host 127.0.0.1 --port 8790", "port": 8790}
    assert app["commands"]["preview"] == "pnpm run preview -- --host 127.0.0.1 --port 8790"
    assert app["tags"] == ["react"]
    out = capsys.readouterr().out
    assert "framework dev server" in out
    assert "WebSocket/HMR" in out


def test_app_import_warns_for_framework_prefix_mismatch(collection, tmp_path, capsys):
    from curiator import cli

    source = _next_app_repo(tmp_path / "external_next")

    assert cli.main([
        "app", "import", str(source), "imported_next",
        "--template", "next",
        "--port", "8791",
    ]) == 0

    data = _gallery(collection)
    app = next(a for a in data["apps"] if a["name"] == "imported_next")
    assert app["mount"]["preserve_prefix"] is True
    out = capsys.readouterr().out
    assert "Next.js config does not appear to set basePath from CURIATOR_APP" in out
