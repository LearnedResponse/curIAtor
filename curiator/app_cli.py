"""CLI handlers for app scaffolding, imports, and templates."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .config import app_spec, load_config, load_config_at


def _cli_shared():
    from . import cli as cli_mod

    return cli_mod


def _is_relative_to(path: Path, parent: Path) -> bool:
    return _cli_shared()._is_relative_to(path, parent)


def _looks_like_hmr_dev_server(command: str | None) -> bool:
    return _cli_shared()._looks_like_hmr_dev_server(command)


def _doctor_warn_proxy_base_path(issues: list[dict], *, name: str, root: Path, mount: dict) -> None:
    _cli_shared()._doctor_warn_proxy_base_path(issues, name=name, root=root, mount=mount)


def _doctor_warn_missing_manifests(issues: list[dict], *, name: str, root: Path, commands: list[str | None]) -> None:
    _cli_shared()._doctor_warn_missing_manifests(issues, name=name, root=root, commands=commands)


_APP_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_TOP_LEVEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*:\s*(?:#.*)?$")


def _app_names(cfg: dict) -> set[str]:
    names: set[str] = set()
    for app in cfg.get("apps") or []:
        if app.get("name"):
            names.add(str(app["name"]))
        for mount in app.get("mounts") or []:
            name = mount.get("name") or (mount.get("mount") or {}).get("name")
            if name:
                names.add(str(name))
    return names


def _title_from_name(name: str) -> str:
    return name.replace("_", " ").strip().title() or name


def _tags_arg(raw: str | None, default: str) -> list[str]:
    tags = [t.strip() for t in (raw or "").split(",") if t.strip()]
    return tags or [default]


def _yaml_list(items: list[str]) -> str:
    return "[" + ", ".join(json.dumps(str(item)) for item in items) + "]"


def _next_proxy_port(cfg: dict, start: int = 8700) -> int:
    ports: set[int] = set()
    for app in cfg.get("apps") or []:
        if app.get("port"):
            ports.add(int(app["port"]))
        mount = app.get("mount") or {}
        if mount.get("port"):
            ports.add(int(mount["port"]))
        for child in app.get("mounts") or []:
            cmount = child.get("mount") or child
            if child.get("port"):
                ports.add(int(child["port"]))
            if cmount.get("port"):
                ports.add(int(cmount["port"]))
    port = start
    while port in ports:
        port += 1
    return port


_APP_TEMPLATE_CHOICES = (
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
)
_PROXY_APP_TEMPLATES = frozenset(t for t in _APP_TEMPLATE_CHOICES if t != "dash")
_JS_APP_TEMPLATES = frozenset({"react", "svelte", "vue", "next"})
_JS_PACKAGE_MANAGERS = ("npm", "pnpm", "yarn", "bun")
_APP_TEMPLATE_INFO = {
    "dash": {
        "mount": "dash-inproc",
        "toolchain": "python+dash",
        "summary": "in-process Dash app directory",
    },
    "static": {
        "mount": "proxy",
        "toolchain": "python stdlib",
        "summary": "static HTML via python -m http.server",
    },
    "python": {
        "mount": "proxy",
        "toolchain": "python stdlib",
        "summary": "dependency-light Python HTTP server",
    },
    "node": {
        "mount": "proxy",
        "toolchain": "node stdlib",
        "summary": "dependency-light Node HTTP server",
    },
    "flask": {
        "mount": "proxy",
        "toolchain": "flask",
        "summary": "server-rendered Flask app",
    },
    "fastapi": {
        "mount": "proxy",
        "toolchain": "fastapi+uvicorn",
        "summary": "ASGI app with root-path support",
    },
    "rust": {
        "mount": "proxy",
        "toolchain": "cargo",
        "summary": "dependency-light Rust HTTP server",
    },
    "react": {
        "mount": "proxy",
        "toolchain": "vite+react",
        "summary": "Vite React app with CURIATOR_APP base path",
    },
    "svelte": {
        "mount": "proxy",
        "toolchain": "vite+svelte",
        "summary": "Vite Svelte app with CURIATOR_APP base path",
    },
    "vue": {
        "mount": "proxy",
        "toolchain": "vite+vue",
        "summary": "Vite Vue app with CURIATOR_APP base path",
    },
    "next": {
        "mount": "proxy preserve-prefix",
        "toolchain": "next",
        "summary": "Next.js App Router with basePath from CURIATOR_APP",
    },
    "streamlit": {
        "mount": "proxy preserve-prefix",
        "toolchain": "streamlit",
        "summary": "Streamlit app with server.baseUrlPath",
    },
    "gradio": {
        "mount": "proxy preserve-prefix",
        "toolchain": "gradio",
        "summary": "Gradio app with root_path",
    },
}


def _template_choices_help() -> str:
    return " | ".join(_APP_TEMPLATE_CHOICES)


def _detect_package_manager(repo: Path) -> str:
    for lockfile, manager in (
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"),
        ("bun.lock", "bun"),
        ("package-lock.json", "npm"),
        ("npm-shrinkwrap.json", "npm"),
    ):
        if (repo / lockfile).exists():
            return manager
    return "npm"


def _resolve_package_manager(repo: Path, requested: str | None) -> str:
    if not requested or requested == "auto":
        return _detect_package_manager(repo)
    return requested


def _looks_like_git_source(source: str) -> bool:
    return bool(
        re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", source)
        or source.startswith("git@")
        or re.match(r"^[^@\s]+@[^:\s]+:.+", source)
        or source.endswith(".git")
    )


def _copy_or_clone_app_source(source_arg: str, dest: Path) -> tuple[str, Path | str]:
    source = Path(source_arg).expanduser()
    if source.exists():
        source = source.resolve()
        if not source.is_dir():
            raise ValueError(f"source is not a directory: {source}")
        if source == dest.resolve() or _is_relative_to(dest.resolve(), source):
            raise ValueError(f"refusing to import into a destination inside the source: {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, dest)
        return "copied", source

    if not _looks_like_git_source(source_arg):
        raise ValueError(f"source directory not found: {source_arg}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["git", "clone", "--quiet", source_arg, str(dest)], capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"git clone exited {result.returncode}").strip()
        raise ValueError(f"git clone failed for {source_arg}: {detail}")
    return "cloned", source_arg


def _js_run_command(manager: str, script: str, args: str = "") -> str:
    if not args:
        return f"{manager} run {script}"
    if manager in {"npm", "pnpm", "bun"}:
        return f"{manager} run {script} -- {args}"
    return f"yarn run {script} {args}"


def _rust_string(value: str) -> str:
    text = str(value)
    return '"' + (
        text
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    ) + '"'


def _append_app_entry(text: str, entry: str) -> str:
    """Append an app item under the top-level `apps:` block while preserving the rest of gallery.yaml."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^apps:\s*\[\s*\]\s*(?:#.*)?$", line):
            lines[i:i + 1] = ["apps:", *entry.rstrip().splitlines()]
            return "\n".join(lines) + "\n"
        if re.match(r"^apps:\s*(?:#.*)?$", line):
            j = i + 1
            while j < len(lines):
                if lines[j] and not lines[j].startswith((" ", "\t", "#")) and _TOP_LEVEL_RE.match(lines[j]):
                    break
                j += 1
            insert = entry.rstrip().splitlines()
            if j > i + 1 and lines[j - 1].strip():
                insert = ["", *insert]
            lines[j:j] = insert
            return "\n".join(lines) + "\n"
    prefix = ["apps:", *entry.rstrip().splitlines(), ""]
    return "\n".join(prefix + lines) + ("\n" if text.endswith("\n") else "")


def _gallery_entry(
    name: str,
    template: str,
    title: str,
    tags: list[str],
    port: int | None,
    package_manager: str = "npm",
) -> str:
    root = f"apps/{name}"
    if template == "dash":
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: python -m compileall -q .\n"
            f"    mount: {{ kind: dash-inproc, module: {name} }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "static":
        preview = f"python -m http.server {port} --bind 127.0.0.1"
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: python -m compileall -q .\n"
            f"    commands:\n"
            f"      preview: {json.dumps(preview)}\n"
            f"    mount: {{ kind: proxy, cmd: \"{preview}\", port: {port} }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template in {"react", "svelte", "vue"}:
        smoke = _js_run_command(package_manager, "build")
        serve = _js_run_command(package_manager, "dev", f"--host 127.0.0.1 --port {port}")
        preview = _js_run_command(package_manager, "preview", f"--host 127.0.0.1 --port {port}")
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: {smoke}\n"
            f"    commands:\n"
            f"      preview: {json.dumps(preview)}\n"
            f"    mount: {{ kind: proxy, cmd: \"{serve}\", port: {port} }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "next":
        smoke = _js_run_command(package_manager, "build")
        serve = _js_run_command(package_manager, "dev", f"-H 127.0.0.1 -p {port}")
        preview = _js_run_command(package_manager, "start", f"-H 127.0.0.1 -p {port}")
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: {smoke}\n"
            f"    commands:\n"
            f"      preview: {json.dumps(preview)}\n"
            f"    mount: {{ kind: proxy, cmd: \"{serve}\", port: {port}, preserve_prefix: true }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "node":
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: node --check server.js\n"
            f"    commands:\n"
            f"      preview: {json.dumps(f'node server.js --port {port}')}\n"
            f"    mount: {{ kind: proxy, cmd: \"node server.js --port {port}\", port: {port} }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "flask":
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: python -m py_compile app.py\n"
            f"    commands:\n"
            f"      preview: {json.dumps(f'python app.py --port {port}')}\n"
            f"    mount: {{ kind: proxy, cmd: \"python app.py --port {port}\", port: {port} }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "fastapi":
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: python -m py_compile main.py\n"
            f"    commands:\n"
            f"      preview: {json.dumps(f'python main.py --port {port} --root-path /app/{name}')}\n"
            f"    mount: {{ kind: proxy, cmd: \"python main.py --port {port} --root-path /app/{{app}}\", "
            f"port: {port} }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "rust":
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: cargo check --quiet\n"
            f"    commands:\n"
            f"      preview: {json.dumps(f'cargo run --quiet -- --port {port}')}\n"
            f"    mount: {{ kind: proxy, cmd: \"cargo run --quiet -- --port {port}\", port: {port} }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "gradio":
        preview = f"python app.py --port {port} --root-path /app/{name}"
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: python -m py_compile app.py\n"
            f"    commands:\n"
            f"      preview: {json.dumps(preview)}\n"
            f"    mount: {{ kind: proxy, cmd: \"python app.py --port {port} --root-path /app/{{app}}\", "
            f"port: {port}, preserve_prefix: true }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    if template == "streamlit":
        preview = (
            f"streamlit run app.py --server.address 127.0.0.1 --server.port {port} "
            f"--server.headless true --server.baseUrlPath app/{name} --browser.gatherUsageStats false"
        )
        return (
            f"  - name: {name}\n"
            f"    title: {json.dumps(title)}\n"
            f"    root: {root}\n"
            f"    source: .\n"
            f"    smoke: python -m py_compile app.py\n"
            f"    commands:\n"
            f"      preview: {json.dumps(preview)}\n"
            f"    mount: {{ kind: proxy, cmd: \"streamlit run app.py --server.address 127.0.0.1 "
            f"--server.port {port} --server.headless true --server.baseUrlPath app/{{app}} "
            f"--browser.gatherUsageStats false\", port: {port}, preserve_prefix: true }}\n"
            f"    tags: {_yaml_list(tags)}\n"
        )
    preview = f"python server.py --port {port}"
    return (
        f"  - name: {name}\n"
        f"    title: {json.dumps(title)}\n"
        f"    root: {root}\n"
        f"    source: .\n"
        f"    smoke: python -m py_compile server.py\n"
        f"    commands:\n"
        f"      preview: {json.dumps(preview)}\n"
        f"    mount: {{ kind: proxy, cmd: \"{preview}\", port: {port} }}\n"
        f"    tags: {_yaml_list(tags)}\n"
    )


def _app_import_postcheck_issues(gallery: Path, name: str) -> list[dict]:
    """Doctor-style warnings for an imported app, scoped to issues import can reveal immediately."""
    try:
        spec = app_spec(load_config_at(gallery), name) or {}
    except SystemExit:
        return []
    root = Path(spec.get("root") or gallery.parent)
    mount = spec.get("mount") or {}
    issues: list[dict] = []
    if mount.get("kind") == "proxy":
        cmd = str(mount.get("cmd") or "")
        if _looks_like_hmr_dev_server(cmd):
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": (
                    "proxy command looks like a framework dev server that may use WebSocket/HMR; "
                    "curIAtor's built-in proxy will show a diagnostic for upgrade requests, so use "
                    "commands.preview or a full reverse proxy when live HMR is required"
                ),
            })
        _doctor_warn_proxy_base_path(issues, name=name, root=root, mount=mount)
    _doctor_warn_missing_manifests(
        issues,
        name=name,
        root=root,
        commands=[spec.get("smoke"), mount.get("cmd")],
    )
    return issues


def _app_template_files(name: str, template: str, title: str, package_manager: str = "npm") -> dict[str, str]:
    js_smoke = _js_run_command(package_manager, "build")
    if template == "dash":
        return {f"{name}.py": _APP_DASH_TEMPLATE.format(name=name, title=title)}
    if template == "static":
        return {"index.html": _APP_STATIC_TEMPLATE.format(name=name, title=title)}
    if template == "react":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title), js_smoke=js_smoke)
                for rel, content in _APP_REACT_TEMPLATE.items()}
    if template == "svelte":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title), js_smoke=js_smoke)
                for rel, content in _APP_SVELTE_TEMPLATE.items()}
    if template == "vue":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title), js_smoke=js_smoke)
                for rel, content in _APP_VUE_TEMPLATE.items()}
    if template == "next":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title), js_smoke=js_smoke)
                for rel, content in _APP_NEXT_TEMPLATE.items()}
    if template == "node":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title))
                for rel, content in _APP_NODE_TEMPLATE.items()}
    if template == "flask":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title))
                for rel, content in _APP_FLASK_TEMPLATE.items()}
    if template == "fastapi":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title))
                for rel, content in _APP_FASTAPI_TEMPLATE.items()}
    if template == "rust":
        return _app_rust_template_files(name, title)
    if template == "streamlit":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title))
                for rel, content in _APP_STREAMLIT_TEMPLATE.items()}
    if template == "gradio":
        return {rel: content.format(name=name, title=title, title_json=json.dumps(title))
                for rel, content in _APP_GRADIO_TEMPLATE.items()}
    return {"server.py": _APP_PYTHON_TEMPLATE.format(name=name, title=title)}


def cmd_app_templates(args) -> int:
    """List supported app scaffold/import templates."""
    rows = [
        {
            "name": name,
            **_APP_TEMPLATE_INFO[name],
        }
        for name in _APP_TEMPLATE_CHOICES
    ]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"curiator: {len(rows)} app templates")
    name_w = max(len(row["name"]) for row in rows)
    mount_w = max(len(row["mount"]) for row in rows)
    tool_w = max(len(row["toolchain"]) for row in rows)
    for row in rows:
        print(
            f"  {row['name']:<{name_w}}  {row['mount']:<{mount_w}}  "
            f"{row['toolchain']:<{tool_w}}  {row['summary']}"
        )
    print("use:")
    print("  curiator app create <name> --template <template>")
    print("  curiator app import <repo-or-dir> <name> --template <template>")
    return 0


def cmd_app_create(args) -> int:
    """Create an app directory and register it in gallery.yaml."""
    cfg = load_config()
    name = args.name.strip()
    if not _APP_NAME_RE.match(name):
        print("curiator: app name must be a Python-safe identifier: letters, numbers, underscores; start with a letter")
        return 1
    if name in _app_names(cfg):
        print(f"curiator: app '{name}' already exists in gallery.yaml")
        return 1
    template = args.template
    repo = Path(cfg["repo_root"])
    root = repo / "apps" / name
    if root.exists() and not args.force:
        print(f"curiator: {root} already exists; pass --force to add missing scaffold files")
        return 1
    title = args.title or _title_from_name(name)
    tags = _tags_arg(args.tags, template)
    port = args.port if args.port is not None else (_next_proxy_port(cfg) if template in _PROXY_APP_TEMPLATES else None)
    package_manager = _resolve_package_manager(repo, args.package_manager) if template in _JS_APP_TEMPLATES else "npm"

    created, skipped = [], []
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in _app_template_files(name, template, title, package_manager).items():
        p = root / rel
        if p.exists():
            skipped.append(str(p.relative_to(repo)))
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        created.append(str(p.relative_to(repo)))

    gallery = Path(cfg["gallery_path"])
    entry = _gallery_entry(name, template, title, tags, port, package_manager)
    gallery.write_text(_append_app_entry(gallery.read_text(), entry))
    created.append(str(gallery.relative_to(repo)))

    print(f"curiator: created {template} app '{name}' in {root.relative_to(repo)}")
    for f in created:
        print(f"  + {f}")
    for f in skipped:
        print(f"  · {f} (exists — left as-is)")
    print("next:")
    print(f"  curiator reload {name}   # if the shell is already running")
    print(f"  open /app/{name}/")
    return 0


def cmd_app_import(args) -> int:
    """Copy/clone an existing app repo or directory and register it in gallery.yaml."""
    cfg = load_config()
    name = args.name.strip()
    if not _APP_NAME_RE.match(name):
        print("curiator: app name must be a Python-safe identifier: letters, numbers, underscores; start with a letter")
        return 1
    if name in _app_names(cfg):
        print(f"curiator: app '{name}' already exists in gallery.yaml")
        return 1

    template = args.template
    repo = Path(cfg["repo_root"])
    root = repo / "apps" / name
    if root.exists():
        print(f"curiator: {root} already exists; choose a new app name or remove the existing directory")
        return 1

    title = args.title or _title_from_name(name)
    tags = _tags_arg(args.tags, template)
    port = args.port if args.port is not None else (_next_proxy_port(cfg) if template in _PROXY_APP_TEMPLATES else None)

    try:
        action, source = _copy_or_clone_app_source(args.source, root)
    except ValueError as exc:
        print(f"curiator: app import FAILED — {exc}")
        return 1

    package_manager = _resolve_package_manager(root, args.package_manager) if template in _JS_APP_TEMPLATES else "npm"
    gallery = Path(cfg["gallery_path"])
    entry = _gallery_entry(name, template, title, tags, port, package_manager)
    gallery.write_text(_append_app_entry(gallery.read_text(), entry))

    print(f"curiator: {action} app source '{source}' into {root.relative_to(repo)}")
    print(f"  + {root.relative_to(repo)}/")
    print(f"  + {gallery.relative_to(repo)}")
    for issue in _app_import_postcheck_issues(gallery, name):
        print(f"  ! {issue['severity'].upper()} {issue['where']}: {issue['message']}")
    print("next:")
    print(f"  curiator reload {name}   # if the shell is already running")
    print(f"  open /app/{name}/")
    return 0


_APP_DASH_TEMPLATE = '''\
"""Dash app scaffold generated by `curiator app create {name}`."""
from __future__ import annotations

import dash
from dash import dcc, html
import plotly.graph_objects as go


def build_app() -> dash.Dash:
    app = dash.Dash(__name__)
    app.title = "{title}"

    fig = go.Figure(
        go.Bar(
            x=["alpha", "beta", "gamma", "delta"],
            y=[12, 19, 8, 15],
            marker_color="#8e44ad",
        )
    )
    fig.update_layout(
        margin=dict(l=48, r=20, t=28, b=42),
        plot_bgcolor="white",
        paper_bgcolor="white",
        height=360,
        xaxis_title="category",
        yaxis_title="value",
    )

    app.layout = html.Div(
        style={{"fontFamily": "system-ui, sans-serif", "padding": "24px", "maxWidth": "860px"}},
        children=[
            html.H2("{title}", style={{"margin": "0 0 8px", "color": "#333"}}),
            html.P(
                "This app was scaffolded by curIAtor. Use feedback in the right rail to shape it.",
                style={{"color": "#666", "margin": "0 0 18px"}},
            ),
            dcc.Graph(figure=fig, config={{"displayModeBar": False}}),
        ],
    )
    return app


app = build_app()


if __name__ == "__main__":
    app.run(debug=False, port=8050)
'''

_APP_STATIC_TEMPLATE = """\
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
      body {{
        margin: 0;
        font-family: system-ui, sans-serif;
        color: #2f3337;
        background: #f7f7f5;
      }}
      main {{
        max-width: 860px;
        padding: 32px;
      }}
      h1 {{
        margin: 0 0 8px;
        color: #8e44ad;
      }}
      p {{
        color: #5f666d;
        line-height: 1.5;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>{title}</h1>
      <p>This static app was scaffolded by curIAtor. Use feedback in the right rail to shape it.</p>
    </main>
  </body>
</html>
"""

_APP_REACT_TEMPLATE = {
    "package.json": """\
{{
  "name": "{name}",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {{
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  }},
  "dependencies": {{
    "@vitejs/plugin-react": "^4.3.0",
    "vite": "^5.4.0",
    "typescript": "^5.5.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  }},
  "devDependencies": {{}}
}}
""",
    "index.html": """\
<!doctype html>
<html>
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
""",
    "vite.config.js": """\
import {{ defineConfig }} from "vite";
import react from "@vitejs/plugin-react";

const app = process.env.CURIATOR_APP || "";
const base = app ? `/app/${{app}}/` : "/";

export default defineConfig({{
  base,
  plugins: [react()],
  server: {{
    host: "127.0.0.1",
  }},
}});
""",
    "src/main.jsx": """\
import React from "react";
import {{ createRoot }} from "react-dom/client";
import App from "./App.jsx";
import "./style.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
""",
    "src/App.jsx": """\
export default function App() {{
  const title = {title_json};
  return (
    <main className="surface">
      <p className="eyebrow">curIAtor React scaffold</p>
      <h1>{{title}}</h1>
      <p>
        This React app is served through a same-origin proxy mount. Use the feedback rail to shape the
        interface; the curator edits files in this directory and smoke-tests with <code>{js_smoke}</code>.
      </p>
      <section className="metricGrid" aria-label="demo metrics">
        <div><b>4</b><span>signals</span></div>
        <div><b>12m</b><span>review window</span></div>
        <div><b>98%</b><span>uptime</span></div>
      </section>
    </main>
  );
}}
""",
    "src/style.css": """\
:root {{
  color: #22272e;
  background: #f6f7f8;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}

body {{
  margin: 0;
}}

.surface {{
  max-width: 880px;
  padding: 32px;
}}

.eyebrow {{
  margin: 0 0 8px;
  color: #8e44ad;
  font-size: 13px;
  font-weight: 700;
}}

h1 {{
  margin: 0 0 12px;
  font-size: 32px;
}}

p {{
  color: #5e6670;
  line-height: 1.55;
}}

.metricGrid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(120px, 1fr));
  gap: 12px;
  margin-top: 24px;
  max-width: 620px;
}}

.metricGrid div {{
  border: 1px solid #d9dde2;
  border-radius: 8px;
  background: white;
  padding: 14px;
}}

.metricGrid b {{
  display: block;
  font-size: 24px;
}}

.metricGrid span {{
  color: #6c747d;
  font-size: 13px;
}}
""",
}

_APP_SVELTE_TEMPLATE = {
    "package.json": """\
{{
  "name": "{name}",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {{
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  }},
  "dependencies": {{
    "@sveltejs/vite-plugin-svelte": "^3.1.0",
    "vite": "^5.4.0",
    "svelte": "^4.2.0"
  }},
  "devDependencies": {{}}
}}
""",
    "index.html": """\
<!doctype html>
<html>
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
""",
    "vite.config.js": """\
import {{ defineConfig }} from "vite";
import {{ svelte }} from "@sveltejs/vite-plugin-svelte";

const app = process.env.CURIATOR_APP || "";
const base = app ? `/app/${{app}}/` : "/";

export default defineConfig({{
  base,
  plugins: [svelte()],
  server: {{
    host: "127.0.0.1",
  }},
}});
""",
    "src/main.js": """\
import App from "./App.svelte";

const app = new App({{
  target: document.getElementById("app"),
}});

export default app;
""",
    "src/App.svelte": """\
<script>
  const title = {title_json};
  const metrics = [
    ["3", "states"],
    ["18m", "iteration"],
    ["7", "notes"],
  ];
</script>

<main class="surface">
  <p class="eyebrow">curIAtor Svelte scaffold</p>
  <h1>{{title}}</h1>
  <p>
    This Svelte app is served through a same-origin proxy mount. Use the feedback rail to shape the
    interface; the curator edits files in this directory and smoke-tests with <code>{js_smoke}</code>.
  </p>
  <section class="metricGrid" aria-label="demo metrics">
    {{#each metrics as metric}}
      <div><b>{{metric[0]}}</b><span>{{metric[1]}}</span></div>
    {{/each}}
  </section>
</main>

<style>
  :global(body) {{
    margin: 0;
    color: #22272e;
    background: #f6f7f8;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }}

  .surface {{
    max-width: 880px;
    padding: 32px;
  }}

  .eyebrow {{
    margin: 0 0 8px;
    color: #8e44ad;
    font-size: 13px;
    font-weight: 700;
  }}

  h1 {{
    margin: 0 0 12px;
    font-size: 32px;
  }}

  p {{
    color: #5e6670;
    line-height: 1.55;
  }}

  .metricGrid {{
    display: grid;
    grid-template-columns: repeat(3, minmax(120px, 1fr));
    gap: 12px;
    margin-top: 24px;
    max-width: 620px;
  }}

  .metricGrid div {{
    border: 1px solid #d9dde2;
    border-radius: 8px;
    background: white;
    padding: 14px;
  }}

  .metricGrid b {{
    display: block;
    font-size: 24px;
  }}

  .metricGrid span {{
    color: #6c747d;
    font-size: 13px;
  }}
</style>
""",
}

_APP_VUE_TEMPLATE = {
    "package.json": """\
{{
  "name": "{name}",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {{
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  }},
  "dependencies": {{
    "@vitejs/plugin-vue": "^5.1.0",
    "vite": "^5.4.0",
    "vue": "^3.5.0"
  }},
  "devDependencies": {{}}
}}
""",
    "index.html": """\
<!doctype html>
<html>
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
""",
    "vite.config.js": """\
import {{ defineConfig }} from "vite";
import vue from "@vitejs/plugin-vue";

const app = process.env.CURIATOR_APP || "";
const base = app ? `/app/${{app}}/` : "/";

export default defineConfig({{
  base,
  plugins: [vue()],
  server: {{
    host: "127.0.0.1",
  }},
}});
""",
    "src/main.js": """\
import {{ createApp }} from "vue";
import App from "./App.vue";
import "./style.css";

createApp(App).mount("#app");
""",
    "src/App.vue": """\
<script setup>
const title = {title_json};
const metrics = [
  ["5", "views"],
  ["9m", "review"],
  ["14", "signals"],
];
</script>

<template>
  <main class="surface">
    <p class="eyebrow">curIAtor Vue scaffold</p>
    <h1>{{{{ title }}}}</h1>
    <p>
      This Vue app is served through a same-origin proxy mount. Use the feedback rail to shape the
      interface; the curator edits files in this directory and smoke-tests with <code>{js_smoke}</code>.
    </p>
    <section class="metricGrid" aria-label="demo metrics">
      <div v-for="metric in metrics" :key="metric[1]">
        <b>{{{{ metric[0] }}}}</b><span>{{{{ metric[1] }}}}</span>
      </div>
    </section>
  </main>
</template>
""",
    "src/style.css": """\
:root {{
  color: #22272e;
  background: #f6f7f8;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}

body {{
  margin: 0;
}}

.surface {{
  max-width: 880px;
  padding: 32px;
}}

.eyebrow {{
  margin: 0 0 8px;
  color: #8e44ad;
  font-size: 13px;
  font-weight: 700;
}}

h1 {{
  margin: 0 0 12px;
  font-size: 32px;
}}

p {{
  color: #5e6670;
  line-height: 1.55;
}}

.metricGrid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(120px, 1fr));
  gap: 12px;
  margin-top: 24px;
  max-width: 620px;
}}

.metricGrid div {{
  border: 1px solid #d9dde2;
  border-radius: 8px;
  background: white;
  padding: 14px;
}}

.metricGrid b {{
  display: block;
  font-size: 24px;
}}

.metricGrid span {{
  color: #6c747d;
  font-size: 13px;
}}
""",
}

_APP_NEXT_TEMPLATE = {
    "package.json": """\
{{
  "name": "{name}",
  "private": true,
  "version": "0.0.0",
  "scripts": {{
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  }},
  "dependencies": {{
    "next": "^14.2.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  }},
  "devDependencies": {{}}
}}
""",
    "next.config.mjs": """\
const app = process.env.CURIATOR_APP || "";
const basePath = app ? `/app/${{app}}` : "";

/** @type {{import("next").NextConfig}} */
const nextConfig = {{
  basePath,
}};

export default nextConfig;
""",
    "app/layout.jsx": """\
import "./globals.css";

export const metadata = {{
  title: {title_json},
}};

export default function RootLayout({{ children }}) {{
  return (
    <html lang="en">
      <body>{{children}}</body>
    </html>
  );
}}
""",
    "app/page.jsx": """\
const title = {title_json};

async function loadStatus() {{
  return {{
    routes: ["/", "/api/status"],
    mode: "server component",
    feedback: "ready",
  }};
}}

export default async function Page() {{
  const status = await loadStatus();
  return (
    <main className="surface">
      <p className="eyebrow">curIAtor Next.js scaffold</p>
      <h1>{{title}}</h1>
      <p>
        This Next.js app is served through a prefix-preserving same-origin proxy mount. Use the feedback
        rail to shape the server-rendered view; the curator edits files in this directory and
        smoke-tests with <code>{js_smoke}</code>.
      </p>
      <section className="metricGrid" aria-label="demo metrics">
        <div><b>{{status.routes.length}}</b><span>routes</span></div>
        <div><b>RSC</b><span>{{status.mode}}</span></div>
        <div><b>OK</b><span>{{status.feedback}}</span></div>
      </section>
    </main>
  );
}}
""",
    "app/api/status/route.js": """\
export function GET() {{
  return Response.json({{
    ok: true,
    app: "{name}",
    runtime: "next",
  }});
}}
""",
    "app/globals.css": """\
:root {{
  color: #22272e;
  background: #f6f7f8;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}

body {{
  margin: 0;
}}

.surface {{
  max-width: 900px;
  padding: 32px;
}}

.eyebrow {{
  margin: 0 0 8px;
  color: #8e44ad;
  font-size: 13px;
  font-weight: 700;
}}

h1 {{
  margin: 0 0 12px;
  font-size: 32px;
}}

p {{
  color: #5e6670;
  line-height: 1.55;
}}

.metricGrid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(120px, 1fr));
  gap: 12px;
  margin-top: 24px;
  max-width: 620px;
}}

.metricGrid div {{
  border: 1px solid #d9dde2;
  border-radius: 8px;
  background: white;
  padding: 14px;
}}

.metricGrid b {{
  display: block;
  font-size: 24px;
}}

.metricGrid span {{
  color: #6c747d;
  font-size: 13px;
}}
""",
    "README.md": """\
# {title}

This Next.js app was scaffolded by curIAtor. It uses the App Router, a server-rendered page, and a
small JSON route while staying behind the same-origin gallery proxy.

Run it through the gallery:

```bash
npm install
curiator up
```

The generated `gallery.yaml` entry runs:

```bash
npm run dev -- -H 127.0.0.1 -p <port>
```

curIAtor sets `preserve_prefix: true` for this proxy mount and exports `CURIATOR_APP={name}`. The
generated `next.config.mjs` turns that into `basePath: "/app/{name}"`, so routes and framework assets
stay under the gallery path.

The scaffold smoke test is:

```bash
npm run build
```

Next's development server may use WebSocket/HMR. curIAtor's built-in proxy keeps the app same-origin
and shows a diagnostic for upgrade requests; use `commands.preview` after a build or a full reverse
proxy when live HMR is required.
""",
}

_APP_STREAMLIT_TEMPLATE = {
    "app.py": '''\
"""Streamlit app scaffold generated by `curiator app create {name} --template streamlit`."""
from __future__ import annotations

import streamlit as st


st.set_page_config(page_title={title_json}, layout="wide")

st.title({title_json})
st.caption("curIAtor Streamlit scaffold")

st.write(
    "This Streamlit app is served through a same-origin proxy mount. "
    "Use the feedback rail to shape the interface; the curator edits files in this directory."
)

left, middle, right = st.columns(3)
left.metric("Signals", "4", "+1")
middle.metric("Review window", "12 min", "-3 min")
right.metric("Ready", "98%", "+2%")

st.subheader("Notes")
st.text_area("What should this prototype show next?", height=120)
''',
    "requirements.txt": """\
streamlit>=1.36
""",
    "README.md": """\
# {title}

This Streamlit app was scaffolded by curIAtor.

Run it through the gallery:

```bash
pip install -r requirements.txt
curiator up
```

The generated `gallery.yaml` entry runs:

```bash
streamlit run app.py --server.address 127.0.0.1 --server.port <port> --server.headless true --server.baseUrlPath app/{name}
```

curIAtor sets `preserve_prefix: true` for this proxy mount so Streamlit receives paths under
`/app/{name}/`. The built-in curIAtor proxy is intentionally lightweight; if a Streamlit component needs
WebSocket or production reverse-proxy behavior beyond this local scaffold, keep this app directory and
put nginx, Caddy, or another full reverse proxy in front of the same command.

The scaffold smoke test is:

```bash
python -m py_compile app.py
```
""",
}

_APP_GRADIO_TEMPLATE = {
    "app.py": '''\
"""Gradio app scaffold generated by `curiator app create {name} --template gradio`."""
from __future__ import annotations

import argparse

import gradio as gr

TITLE = {title_json}


def respond(prompt: str) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        return "Add a prompt, then use the curIAtor feedback rail to shape this prototype."
    return f"Prototype response for: {{prompt}}"


with gr.Blocks(title=TITLE) as demo:
    gr.Markdown(f"# {{TITLE}}")
    gr.Markdown("curIAtor Gradio scaffold served through a same-origin proxy mount.")
    prompt = gr.Textbox(label="Prompt", placeholder="What should this prototype answer?")
    output = gr.Textbox(label="Output", interactive=False)
    run = gr.Button("Run")
    run.click(respond, inputs=prompt, outputs=output)
    prompt.submit(respond, inputs=prompt, outputs=output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--root-path", default="")
    args = parser.parse_args()
    demo.launch(
        server_name="127.0.0.1",
        server_port=args.port,
        root_path=args.root_path or None,
        share=False,
    )


if __name__ == "__main__":
    main()
''',
    "requirements.txt": """\
gradio>=4.44
""",
    "README.md": """\
# {title}

This Gradio app was scaffolded by curIAtor.

Run it through the gallery:

```bash
pip install -r requirements.txt
curiator up
```

The generated `gallery.yaml` entry runs:

```bash
python app.py --port <port> --root-path /app/{name}
```

curIAtor sets `preserve_prefix: true` for this proxy mount so Gradio receives paths under
`/app/{name}/` and can build URLs with the matching `root_path`. The built-in curIAtor proxy is
intentionally lightweight; if a Gradio component needs production reverse-proxy behavior beyond this
local scaffold, keep this app directory and put nginx, Caddy, or another full reverse proxy in front
of the same command.

The scaffold smoke test is:

```bash
python -m py_compile app.py
```
""",
}

_APP_NODE_TEMPLATE = {
    "package.json": """\
{{
  "name": "{name}",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {{
    "start": "node server.js",
    "check": "node --check server.js"
  }}
}}
""",
    "server.js": """\
import http from "node:http";

const TITLE = {title_json};

function optionValue(flag) {{
  const index = process.argv.indexOf(flag);
  return index >= 0 ? process.argv[index + 1] : undefined;
}}

const port = Number(optionValue("--port") || process.env.PORT || 8700);

function page() {{
  return `<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>${{TITLE}}</title>
    <style>
      body {{
        margin: 0;
        font-family: system-ui, sans-serif;
        color: #22272e;
        background: #f6f7f8;
      }}
      main {{
        max-width: 880px;
        padding: 32px;
      }}
      h1 {{
        margin: 0 0 12px;
        color: #8e44ad;
      }}
      p {{
        color: #5e6670;
        line-height: 1.55;
      }}
      .metricGrid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(120px, 1fr));
        gap: 12px;
        margin-top: 24px;
        max-width: 620px;
      }}
      .metricGrid div {{
        border: 1px solid #d9dde2;
        border-radius: 8px;
        background: white;
        padding: 14px;
      }}
      .metricGrid b {{
        display: block;
        font-size: 24px;
      }}
      .metricGrid span {{
        color: #6c747d;
        font-size: 13px;
      }}
    </style>
  </head>
  <body>
    <main>
      <p style="margin:0 0 8px;color:#8e44ad;font-size:13px;font-weight:700">curIAtor Node scaffold</p>
      <h1>${{TITLE}}</h1>
      <p>
        This dependency-light Node app is served through a same-origin proxy mount. Use the feedback
        rail to shape the server-rendered HTML; the curator edits files in this directory and
        smoke-tests with <code>node --check server.js</code>.
      </p>
      <section class="metricGrid" aria-label="demo metrics">
        <div><b>3</b><span>routes</span></div>
        <div><b>0</b><span>dependencies</span></div>
        <div><b>1</b><span>server file</span></div>
      </section>
    </main>
  </body>
</html>`;
}}

const server = http.createServer((req, res) => {{
  if (req.url === "/healthz") {{
    const body = JSON.stringify({{ ok: true, app: "{name}" }});
    res.writeHead(200, {{
      "content-type": "application/json; charset=utf-8",
      "content-length": Buffer.byteLength(body),
    }});
    res.end(body);
    return;
  }}
  const body = page();
  res.writeHead(200, {{
    "content-type": "text/html; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  }});
  res.end(body);
}});

server.listen(port, "127.0.0.1", () => {{
  console.log(`${{TITLE}} listening on http://127.0.0.1:${{port}}`);
}});
""",
    "README.md": """\
# {title}

This Node app was scaffolded by curIAtor. It has no npm dependencies: `server.js` uses Node's built-in
HTTP server and renders HTML on the server side.

Run it through the gallery:

```bash
curiator up
```

The generated `gallery.yaml` entry runs:

```bash
node server.js --port <port>
```

The scaffold smoke test is:

```bash
node --check server.js
```

Use this template for small server-side prototypes, lightweight API-backed views, or as a base before
promoting to a heavier framework.
""",
}

_APP_FLASK_TEMPLATE = {
    "app.py": '''\
"""Flask app scaffold generated by `curiator app create {name} --template flask`."""
from __future__ import annotations

import argparse

from flask import Flask, jsonify, render_template_string

TITLE = {title_json}

HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{{{ title }}}}</title>
    <style>
      body {{
        margin: 0;
        font-family: system-ui, sans-serif;
        color: #22272e;
        background: #f6f7f8;
      }}
      main {{
        max-width: 900px;
        padding: 32px;
      }}
      .eyebrow {{
        margin: 0 0 8px;
        color: #8e44ad;
        font-size: 13px;
        font-weight: 700;
      }}
      h1 {{
        margin: 0 0 12px;
        font-size: 32px;
      }}
      p {{
        color: #5e6670;
        line-height: 1.55;
      }}
      .metricGrid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(120px, 1fr));
        gap: 12px;
        margin-top: 24px;
        max-width: 620px;
      }}
      .metricGrid div {{
        border: 1px solid #d9dde2;
        border-radius: 8px;
        background: white;
        padding: 14px;
      }}
      .metricGrid b {{
        display: block;
        font-size: 24px;
      }}
      .metricGrid span {{
        color: #6c747d;
        font-size: 13px;
      }}
    </style>
  </head>
  <body>
    <main>
      <p class="eyebrow">curIAtor Flask scaffold</p>
      <h1>{{{{ title }}}}</h1>
      <p>
        This Flask app is served through a same-origin proxy mount. Use the feedback rail to shape the
        server-rendered view; the curator edits files in this directory and smoke-tests with
        <code>python -m py_compile app.py</code>.
      </p>
      <section class="metricGrid" aria-label="demo metrics">
        <div><b>3</b><span>routes</span></div>
        <div><b>1</b><span>Flask app</span></div>
        <div><b>0</b><span>extra deps</span></div>
      </section>
    </main>
  </body>
</html>
"""


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template_string(HTML, title=TITLE)

    @app.get("/healthz")
    def healthz():
        return jsonify({{"ok": True, "app": "{name}"}})

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8700)
    args = parser.parse_args()
    create_app().run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
''',
    "README.md": """\
# {title}

This Flask app was scaffolded by curIAtor. It uses Flask, which is already installed with curIAtor,
and renders HTML on the server side.

Run it through the gallery:

```bash
curiator up
```

The generated `gallery.yaml` entry runs:

```bash
python app.py --port <port>
```

The scaffold smoke test is:

```bash
python -m py_compile app.py
```

Use this template for lightweight server-rendered views, tiny API-backed panels, or prototypes that
should stay Python-native without becoming Dash apps.
""",
}

_APP_FASTAPI_TEMPLATE = {
    "main.py": '''\
"""FastAPI app scaffold generated by `curiator app create {name} --template fastapi`."""
from __future__ import annotations

import argparse

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

TITLE = {title_json}

HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
      body {{
        margin: 0;
        font-family: system-ui, sans-serif;
        color: #22272e;
        background: #f6f7f8;
      }}
      main {{
        max-width: 900px;
        padding: 32px;
      }}
      .eyebrow {{
        margin: 0 0 8px;
        color: #8e44ad;
        font-size: 13px;
        font-weight: 700;
      }}
      h1 {{
        margin: 0 0 12px;
        font-size: 32px;
      }}
      p {{
        color: #5e6670;
        line-height: 1.55;
      }}
      .metricGrid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(120px, 1fr));
        gap: 12px;
        margin-top: 24px;
        max-width: 620px;
      }}
      .metricGrid div {{
        border: 1px solid #d9dde2;
        border-radius: 8px;
        background: white;
        padding: 14px;
      }}
      .metricGrid b {{
        display: block;
        font-size: 24px;
      }}
      .metricGrid span {{
        color: #6c747d;
        font-size: 13px;
      }}
    </style>
  </head>
  <body>
    <main>
      <p class="eyebrow">curIAtor FastAPI scaffold</p>
      <h1>{title}</h1>
      <p>
        This FastAPI app is served through a same-origin proxy mount. Use the feedback rail to shape
        the API-backed view; the curator edits files in this directory and smoke-tests with
        <code>python -m py_compile main.py</code>.
      </p>
      <section class="metricGrid" aria-label="demo metrics">
        <div><b>3</b><span>routes</span></div>
        <div><b>1</b><span>ASGI app</span></div>
        <div><b>JSON</b><span>status API</span></div>
      </section>
    </main>
  </body>
</html>
"""

app = FastAPI(title=TITLE)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.get("/api/status")
def status() -> dict[str, object]:
    return {{"ok": True, "app": "{name}", "routes": ["/", "/api/status", "/docs"]}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8700)
    parser.add_argument("--root-path", default="")
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, root_path=args.root_path)


if __name__ == "__main__":
    main()
''',
    "requirements.txt": """\
fastapi>=0.115
uvicorn[standard]>=0.30
""",
    "README.md": """\
# {title}

This FastAPI app was scaffolded by curIAtor. It serves a small HTML view plus a JSON status endpoint
through the same-origin proxy mount.

Run it through the gallery:

```bash
pip install -r requirements.txt
curiator up
```

The generated `gallery.yaml` entry runs:

```bash
python main.py --port <port> --root-path /app/{name}
```

curIAtor strips `/app/{name}/` before proxying to the app. The generated `--root-path` keeps FastAPI's
OpenAPI/docs URLs anchored under the gallery path, so `/app/{name}/docs` can find its schema and assets.

The scaffold smoke test is:

```bash
python -m py_compile main.py
```

Use this template for lightweight JSON APIs, API-backed HTML views, or prototypes that may later grow
into a larger ASGI service.
""",
}

_APP_RUST_TEMPLATE = {
    "Cargo.toml": """\
[package]
name = "__NAME__"
version = "0.1.0"
edition = "2021"

[dependencies]
""",
    "src/main.rs": r'''
//! Rust HTTP server scaffold generated by `curiator app create __NAME__ --template rust`.

use std::env;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};

const APP: &str = "__NAME__";
const TITLE: &str = __TITLE_LITERAL__;

fn option_value(flag: &str) -> Option<String> {
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        if arg == flag {
            return args.next();
        }
    }
    None
}

fn port() -> u16 {
    option_value("--port")
        .or_else(|| env::var("PORT").ok())
        .and_then(|value| value.parse::<u16>().ok())
        .unwrap_or(8700)
}

fn page() -> String {
    r#"<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>__TITLE_TEXT__</title>
    <style>
      body {
        margin: 0;
        font-family: system-ui, sans-serif;
        color: #22272e;
        background: #f6f7f8;
      }
      main {
        max-width: 900px;
        padding: 32px;
      }
      .eyebrow {
        margin: 0 0 8px;
        color: #8e44ad;
        font-size: 13px;
        font-weight: 700;
      }
      h1 {
        margin: 0 0 12px;
        font-size: 32px;
      }
      p {
        color: #5e6670;
        line-height: 1.55;
      }
      .metricGrid {
        display: grid;
        grid-template-columns: repeat(3, minmax(120px, 1fr));
        gap: 12px;
        margin-top: 24px;
        max-width: 620px;
      }
      .metricGrid div {
        border: 1px solid #d9dde2;
        border-radius: 8px;
        background: white;
        padding: 14px;
      }
      .metricGrid b {
        display: block;
        font-size: 24px;
      }
      .metricGrid span {
        color: #6c747d;
        font-size: 13px;
      }
    </style>
  </head>
  <body>
    <main>
      <p class="eyebrow">curIAtor Rust scaffold</p>
      <h1>__TITLE_TEXT__</h1>
      <p>
        This dependency-light Rust app is served through a same-origin proxy mount. Use the feedback
        rail to shape the server-rendered view; the curator edits files in this directory and
        smoke-tests with <code>cargo check --quiet</code>.
      </p>
      <section class="metricGrid" aria-label="demo metrics">
        <div><b>1</b><span>binary</span></div>
        <div><b>0</b><span>dependencies</span></div>
        <div><b>2</b><span>routes</span></div>
      </section>
    </main>
  </body>
</html>"#.to_string()
}

fn response(status: &str, content_type: &str, body: &str) -> Vec<u8> {
    format!(
        "HTTP/1.1 {status}\r\ncontent-type: {content_type}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
        body.as_bytes().len()
    )
    .into_bytes()
}

fn handle(mut stream: TcpStream) -> std::io::Result<()> {
    let mut buf = [0_u8; 1024];
    let n = stream.read(&mut buf)?;
    let request = String::from_utf8_lossy(&buf[..n]);
    let path = request
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .unwrap_or("/");
    let bytes = if path == "/healthz" {
        let body = format!(r#"{{"ok":true,"app":"{APP}"}}"#);
        response("200 OK", "application/json; charset=utf-8", &body)
    } else {
        response("200 OK", "text/html; charset=utf-8", &page())
    };
    stream.write_all(&bytes)?;
    stream.flush()
}

fn main() -> std::io::Result<()> {
    let port = port();
    let listener = TcpListener::bind(("127.0.0.1", port))?;
    println!("{TITLE} listening on http://127.0.0.1:{port}");
    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                if let Err(err) = handle(stream) {
                    eprintln!("request failed: {err}");
                }
            }
            Err(err) => eprintln!("connection failed: {err}"),
        }
    }
    Ok(())
}
''',
    "README.md": """\
# __TITLE_TEXT__

This Rust app was scaffolded by curIAtor. It has no crate dependencies: `src/main.rs` uses the Rust
standard library to serve HTML plus a `/healthz` JSON endpoint.

Run it through the gallery:

```bash
curiator up
```

The generated `gallery.yaml` entry runs:

```bash
cargo run --quiet -- --port <port>
```

The scaffold smoke test is:

```bash
cargo check --quiet
```

Use this template for small compiled status services, API-backed prototypes, or Rust views that should
stay behind curIAtor's same-origin feedback overlay.
""",
}


def _app_rust_template_files(name: str, title: str) -> dict[str, str]:
    replacements = {
        "__NAME__": name,
        "__TITLE_LITERAL__": _rust_string(title),
        "__TITLE_TEXT__": title,
    }
    out = {}
    for rel, content in _APP_RUST_TEMPLATE.items():
        text = content
        for old, new in replacements.items():
            text = text.replace(old, new)
        out[rel] = text
    return out


_APP_PYTHON_TEMPLATE = '''\
"""Tiny Python web server scaffold generated by `curiator app create {name} --template python`."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
      body {{
        margin: 0;
        font-family: system-ui, sans-serif;
        color: #2f3337;
        background: #f7f7f5;
      }}
      main {{
        max-width: 860px;
        padding: 32px;
      }}
      h1 {{
        margin: 0 0 8px;
        color: #8e44ad;
      }}
      p {{
        color: #5f666d;
        line-height: 1.5;
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>{title}</h1>
      <p>This Python server app was scaffolded by curIAtor. Use feedback in the right rail to shape it.</p>
    </main>
  </body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8700)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
'''
