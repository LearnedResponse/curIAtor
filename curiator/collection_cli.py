"""CLI handlers for collection lifecycle, doctor, smoke, and local command shims."""
from __future__ import annotations

import ast
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

from .agent_capabilities import agent_report
from .app_cli import _app_names
from .config import LINK_REL, app_spec, app_specs, load_config, load_config_at


def _cli_shared():
    from . import cli as cli_mod

    return cli_mod


def _git_output(cwd: Path, *args: str) -> str | None:
    return _cli_shared()._git_output(cwd, *args)


def _project_root(cwd: Path | None = None) -> Path:
    return _cli_shared()._project_root(cwd)


def _is_git_toplevel(repo: Path) -> bool:
    return _cli_shared()._is_git_toplevel(repo)


def _feedback_counts(cfg: dict, app: str) -> tuple[int, int]:
    return _cli_shared()._feedback_counts(cfg, app)


def _shell_url(cfg: dict, app: str | None = None) -> str:
    return _cli_shared()._shell_url(cfg, app)


def _portable_gallery_link(gallery: Path, root: Path) -> str:
    """Path written to .curiator/app.yaml. Prefer relative links for clone portability."""
    try:
        return os.path.relpath(gallery.resolve(), root.resolve())
    except ValueError:  # pragma: no cover - different Windows drives
        return str(gallery.resolve())


def cmd_link(args) -> int:
    """Link the current app repo/directory to a collection gallery + app key."""
    import yaml

    gallery = Path(args.gallery).expanduser().resolve() if args.gallery else Path(load_config()["gallery_path"]).resolve()
    if not gallery.exists():
        raise SystemExit(f"curIAtor: gallery not found: {gallery}")
    cfg = load_config_at(gallery)
    app = args.app or cfg.get("current_app")
    if not app:
        raise SystemExit("curIAtor: pass --app <key> for this link.")
    if app not in _app_names(cfg):
        raise SystemExit(f"curIAtor: app {app!r} is not in {gallery}")
    root = Path(args.root).expanduser().resolve() if args.root else _project_root()
    link_path = root / LINK_REL
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.write_text(yaml.safe_dump({"gallery": _portable_gallery_link(gallery, root), "app": app}, sort_keys=False))
    print(f"curiator: linked {root} → {gallery} app={app}")
    print(f"  wrote {link_path}")
    if args.commands:
        _install_command_files(root)
    return 0


def cmd_status(args) -> int:
    cfg = load_config()
    app = args.app or cfg.get("current_app")
    root = Path(cfg["repo_root"])
    branch = _git_output(root, "branch", "--show-current") or "not a git repo"
    dirty = _git_output(root, "status", "--porcelain")
    git = cfg.get("git", {}) or {}
    print("curIAtor status")
    print(f"  gallery: {cfg['gallery_path']}")
    if cfg.get("link_path"):
        print(f"  link:    {cfg['link_path']}")
    print(f"  shell:   {_shell_url(cfg, app)}")
    print(f"  git:     commit={git.get('commit')} branch={git.get('branch') or branch} include_ledger={git.get('include_ledger')}")
    print(f"  repo:    {root} [{branch}{', dirty' if dirty else ', clean'}]")
    if app:
        spec = app_spec(cfg, app) or {}
        total, open_n = _feedback_counts(cfg, app)
        print(f"  app:     {app}")
        print(f"  root:    {spec.get('root') or 'unknown'}")
        print(f"  source:  {spec.get('source') or 'unknown'}")
        app_root = Path(spec.get("root") or "")
        if app_root and app_root.resolve() != root.resolve() and _is_git_toplevel(app_root):
            app_branch = _git_output(app_root, "branch", "--show-current") or "detached"
            app_dirty = _git_output(app_root, "status", "--porcelain")
            print(f"  app git: {app_root} [{app_branch}{', dirty' if app_dirty else ', clean'}]")
        if spec.get("smoke"):
            print(f"  smoke:   {spec['smoke']}")
        commands = spec.get("commands") if isinstance(spec.get("commands"), dict) else {}
        if commands.get("preview"):
            print(f"  preview: {commands['preview']}")
        print(f"  feedback:{open_n} open / {total} total")
        print(f"  next:    curiator work --app {app}")
    else:
        print("  app:     none selected (pass --app or run curiator link)")
    return 0


_PORTABLE_PATH_KEYS = {"path", "root", "source", "cwd", "dir", "users_file", "gallery", "gallery_path"}
_USER_ABS_PATH_RE = re.compile(r"(?<![\w.-])(?:/[A-Za-z0-9_.-]+)?/(?:home|Users)/[^\s'\"`]+|[A-Za-z]:[\\/]+Users[\\/]+[^\s'\"`]+")


def _looks_absolute_path(value: str) -> bool:
    return value.startswith("/") or bool(re.match(r"^[A-Za-z]:[\\/]", value))


def _repo_path(cfg: dict, path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    try:
        return str(p.resolve().relative_to(Path(cfg["repo_root"]).resolve())) or "."
    except ValueError:
        return str(p)


def _doctor_scan_portability(node, where: str, issues: list[dict], needles: tuple[str, ...]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            loc = f"{where}.{key}" if where else str(key)
            if isinstance(value, str):
                if str(key) in _PORTABLE_PATH_KEYS and _looks_absolute_path(value):
                    issues.append({
                        "severity": "error",
                        "where": loc,
                        "message": f"absolute path breaks clone portability: {value}",
                    })
                for needle in needles:
                    if needle and needle in value:
                        issues.append({
                            "severity": "error",
                            "where": loc,
                            "message": f"contains machine-local path {needle}",
                        })
                if _USER_ABS_PATH_RE.search(value):
                    issues.append({
                        "severity": "error",
                        "where": loc,
                        "message": "contains a user-home absolute path",
                    })
            else:
                _doctor_scan_portability(value, loc, issues, needles)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _doctor_scan_portability(value, f"{where}[{i}]", issues, needles)


def _command_executable(command: str | None) -> str | None:
    if not command:
        return None
    try:
        parts = shlex.split(str(command))
    except ValueError:
        return None
    if not parts:
        return None
    if parts[0] == "env":
        parts = parts[1:]
    while parts and "=" in parts[0] and not parts[0].startswith(("/", "./", "../")):
        key, _, _ = parts[0].partition("=")
        if not key.replace("_", "").isalnum():
            break
        parts = parts[1:]
    return parts[0] if parts else None


def _executable_exists(executable: str, cwd: Path) -> bool:
    p = Path(executable)
    if p.is_absolute():
        return p.exists()
    if any(sep in executable for sep in ("/", "\\")):
        return (cwd / p).exists()
    return _cli_shared().shutil.which(executable) is not None


def _doctor_warn_missing_executable(
    issues: list[dict],
    *,
    where: str,
    command: str | None,
    cwd: Path,
    label: str,
) -> None:
    executable = _command_executable(command)
    if not executable or _executable_exists(executable, cwd):
        return
    issues.append({
        "severity": "warning",
        "where": where,
        "message": f"{label} executable not found on PATH: {executable}",
    })


def _doctor_warn_voice_config(issues: list[dict], cfg: dict, repo: Path) -> None:
    command = str((cfg.get("voice") or {}).get("transcribe_cmd") or "")
    if not command:
        return
    _doctor_warn_missing_executable(
        issues,
        where="voice.transcribe_cmd",
        command=command,
        cwd=repo,
        label="voice transcribe command",
    )
    if "curiator.voice.faster_whisper" in command:
        import importlib.util
        if importlib.util.find_spec("faster_whisper") is None:
            issues.append({
                "severity": "warning",
                "where": "voice.transcribe_cmd",
                "message": "faster-whisper is not installed; install `pip install 'curiator[voice]'` "
                           "in the collection environment",
            })


def _manifest_expectations(command: str | None) -> dict[str, list[str]]:
    executable = (_command_executable(command) or "").lower()
    command_text = str(command or "").lower()
    if executable in {"npm", "pnpm", "yarn", "bun", "node"}:
        return {"Node app": ["package.json"]}
    if executable == "streamlit" or "streamlit run" in command_text:
        return {"Python/Streamlit app": ["requirements.txt", "pyproject.toml", "environment.yml", "environment.yaml"]}
    if executable == "cargo":
        return {"Rust app": ["Cargo.toml"]}
    return {}


_OPTIONAL_PYTHON_FRAMEWORKS = {
    "fastapi": "Python/FastAPI app",
    "gradio": "Python/Gradio app",
    "streamlit": "Python/Streamlit app",
}
_PYTHON_DEP_MANIFESTS = ["requirements.txt", "pyproject.toml", "environment.yml", "environment.yaml"]


def _python_import_roots(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0].lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0].lower())
    return roots


def _python_project_imports(root: Path) -> set[str]:
    if not root.exists() or not root.is_dir():
        return set()
    imports: set[str] = set()
    for path in sorted(root.glob("*.py")):
        imports.update(_python_import_roots(path))
    return imports


def _project_text(root: Path, patterns: tuple[str, ...]) -> str:
    if not root.exists() or not root.is_dir():
        return ""
    chunks: list[str] = []
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return "\n".join(chunks)


def _first_config_text(root: Path, names: tuple[str, ...]) -> str:
    for name in names:
        path = root / name
        if not path.exists():
            continue
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    return ""


def _python_framework_manifest_expectations(root: Path) -> dict[str, list[str]]:
    """Return optional Python framework dependency manifests implied by top-level app imports."""
    imports = _python_project_imports(root)
    return {
        label: _PYTHON_DEP_MANIFESTS
        for module, label in _OPTIONAL_PYTHON_FRAMEWORKS.items()
        if module in imports
    }


def _command_tokens(command: str | None) -> list[str]:
    if not command:
        return []
    try:
        parts = shlex.split(str(command))
    except ValueError:
        parts = str(command).split()
    if parts and parts[0] == "env":
        parts = parts[1:]
    while parts and "=" in parts[0] and not parts[0].startswith(("/", "./", "../")):
        key, _, _ = parts[0].partition("=")
        if not key.replace("_", "").isalnum():
            break
        parts = parts[1:]
    return [p.lower() for p in parts]


def _looks_like_hmr_dev_server(command: str | None) -> bool:
    parts = _command_tokens(command)
    if not parts:
        return False
    text = " ".join(parts)
    if parts[0] == "vite" or (parts[0] == "npx" and len(parts) > 1 and parts[1] == "vite"):
        return True
    if text.startswith(("next dev", "npx next dev", "webpack serve", "npx webpack serve")):
        return True
    for manager in ("npm", "pnpm", "yarn", "bun"):
        if text.startswith((f"{manager} run dev", f"{manager} dev")):
            return True
    return False


def _doctor_warn_missing_manifests(
    issues: list[dict],
    *,
    name: str,
    root: Path,
    commands: list[str | None],
) -> None:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    expectation_sets = [_manifest_expectations(command) for command in commands]
    expectation_sets.append(_python_framework_manifest_expectations(root))
    for expectations in expectation_sets:
        for label, filenames in expectations.items():
            key = (label, tuple(filenames))
            if key in seen:
                continue
            seen.add(key)
            if any((root / filename).exists() for filename in filenames):
                continue
            issues.append({
                "severity": "warning",
                "where": f"app {name} dependencies",
                "message": f"{label} is missing dependency manifest ({' or '.join(filenames)}) in {root}",
            })


def _doctor_warn_proxy_base_path(issues: list[dict], *, name: str, root: Path, mount: dict) -> None:
    """Warn when a known framework proxy app is missing the path-prefix config curIAtor needs."""
    cmd = str(mount.get("cmd") or "")
    command_text = cmd.lower()
    package_text = _first_config_text(root, ("package.json",)).lower()
    python_imports = _python_project_imports(root)
    python_text = _project_text(root, ("*.py",)).lower()

    vite_config = _first_config_text(root, ("vite.config.js", "vite.config.mjs", "vite.config.ts"))
    is_vite = bool(vite_config) or "vite" in package_text or "vite" in command_text
    if is_vite:
        compact = vite_config.lower().replace(" ", "")
        if not vite_config:
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Vite app has no vite.config.*; set base from CURIATOR_APP so assets resolve under /app/<name>/",
            })
        elif "base" not in compact or ("curiator_app" not in compact and "/app/${" not in compact and "/app/" not in compact):
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Vite config does not appear to set an /app/<name>/ base path from CURIATOR_APP",
            })

    next_config = _first_config_text(root, ("next.config.mjs", "next.config.js", "next.config.ts"))
    is_next = bool(next_config) or '"next"' in package_text or "next dev" in command_text or "next start" in command_text
    if is_next:
        if not mount.get("preserve_prefix"):
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Next.js proxy mount should set preserve_prefix: true so its basePath routes reach the app",
            })
        compact = next_config.lower().replace(" ", "")
        if not next_config or "basepath" not in compact or ("curiator_app" not in compact and "/app/" not in compact):
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Next.js config does not appear to set basePath from CURIATOR_APP for /app/<name>/",
            })

    if "streamlit" in python_imports or "streamlit run" in command_text:
        if not mount.get("preserve_prefix"):
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Streamlit proxy mount should set preserve_prefix: true with server.baseUrlPath",
            })
        if "--server.baseurlpath" not in command_text:
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Streamlit command does not set --server.baseUrlPath app/{app}",
            })

    if "gradio" in python_imports:
        if not mount.get("preserve_prefix"):
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Gradio proxy mount should set preserve_prefix: true with a root_path",
            })
        if "--root-path" not in command_text and "root_path" not in python_text:
            issues.append({
                "severity": "warning",
                "where": f"app {name} proxy",
                "message": "Gradio app does not appear to configure root_path for /app/<name>/",
            })

    if "fastapi" in python_imports and "--root-path" not in command_text and "root_path" not in python_text:
        issues.append({
            "severity": "warning",
            "where": f"app {name} proxy",
            "message": "FastAPI app does not appear to configure root_path for /app/<name>/",
        })


def _doctor_issues(cfg: dict) -> list[dict]:
    import yaml

    issues: list[dict] = []
    gallery = Path(cfg["gallery_path"])
    repo = Path(cfg["repo_root"]).resolve()
    raw = yaml.safe_load(gallery.read_text()) or {}
    needles = tuple({str(repo), str(Path.home())} - {"", "/"})
    _doctor_scan_portability(raw, "gallery.yaml", issues, needles)
    _doctor_warn_voice_config(issues, cfg, repo)

    link = cfg.get("link") or {}
    if link:
        gallery_link = str(link.get("gallery") or link.get("gallery_path") or "")
        if gallery_link and _looks_absolute_path(gallery_link):
            issues.append({
                "severity": "error",
                "where": cfg.get("link_path") or ".curiator/app.yaml",
                "message": f"linked gallery is absolute; rerun `curiator link` to write a relative link: {gallery_link}",
            })

    seen_specs: set[tuple[str, str, str]] = set()
    for spec in app_specs(cfg):
        name = str(spec.get("name") or spec.get("app_name") or "<unknown>")
        mount = spec.get("mount") or {}
        root_path = Path(spec.get("root") or repo)
        source_path = Path(spec.get("source") or "")
        for label in ("root", "source"):
            raw_path = spec.get(label)
            if not raw_path:
                continue
            path = Path(raw_path)
            key = (name, label, str(path))
            if key in seen_specs:
                continue
            seen_specs.add(key)
            if not path.exists():
                issues.append({
                    "severity": "error",
                    "where": f"app {name} {label}",
                    "message": f"configured path does not exist: {path}",
                })
        if not spec.get("smoke") and (mount.get("kind") == "proxy" or source_path.is_dir()):
            issues.append({
                "severity": "warning",
                "where": f"app {name} smoke",
                "message": "no smoke command configured; release preflight will use only a weak fallback",
            })
        if spec.get("smoke"):
            _doctor_warn_missing_executable(
                issues,
                where=f"app {name} smoke",
                command=str(spec.get("smoke") or ""),
                cwd=root_path,
                label="smoke command",
            )
        if mount.get("kind") == "proxy":
            cmd = str(mount.get("cmd") or "")
            port = mount.get("port")
            _doctor_warn_missing_executable(
                issues,
                where=f"app {name} proxy",
                command=cmd,
                cwd=root_path,
                label="proxy command",
            )
            if port is not None and "{port}" not in cmd and str(port) not in cmd:
                issues.append({
                    "severity": "warning",
                    "where": f"app {name} proxy",
                    "message": f"proxy command does not mention configured port {port}",
                })
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
            _doctor_warn_proxy_base_path(issues, name=name, root=root_path, mount=mount)
        _doctor_warn_missing_manifests(
            issues,
            name=name,
            root=root_path,
            commands=[spec.get("smoke"), mount.get("cmd")],
        )
    return issues


def _print_agent_report(report: dict) -> None:
    print("Agent capabilities:")
    for name, capability in report.get("capabilities", {}).items():
        status = "available" if capability.get("available") else "missing"
        print(f"  {name}: {status} — {capability.get('reason')}")
    tools = report.get("tools") or {}
    for name in ("browser", "playwright", "docker", "git", "gh", "sqlite"):
        tool = tools.get(name) or {}
        status = "available" if tool.get("available") else "missing"
        detail = tool.get("path") or tool.get("command") or ""
        print(f"  tool.{name}: {status}{(' — ' + str(detail)) if detail else ''}")


def cmd_doctor(args) -> int:
    cfg = load_config()
    issues = _doctor_issues(cfg)
    errors = [i for i in issues if i.get("severity") == "error"]
    warnings = [i for i in issues if i.get("severity") == "warning"]
    agent = agent_report(cfg) if getattr(args, "agent", False) else None
    if args.json:
        payload = {"ok": not errors, "errors": len(errors), "warnings": len(warnings), "issues": issues}
        if agent is not None:
            payload["agent"] = agent
        print(json.dumps(payload, indent=2))
        return 1 if errors else 0
    if not issues:
        print("curiator: doctor OK — no portability/config issues found.")
    else:
        print(f"curiator: doctor found {len(errors)} error(s), {len(warnings)} warning(s):")
        for issue in issues:
            print(f"  {issue['severity'].upper()} {issue['where']}: {issue['message']}")
    if agent is not None:
        _print_agent_report(agent)
    return 1 if errors else 0


def _smoke_specs(cfg: dict, app: str | None = None) -> list[dict]:
    specs = app_specs(cfg)
    if app:
        matches = [s for s in specs if app in {s.get("name"), s.get("app_name"), s.get("module")}]
        if not matches:
            raise SystemExit(f"curIAtor: unknown app {app!r}.")
        return matches
    return specs


def _smoke_work_specs(cfg: dict, app: str | None = None) -> list[dict]:
    specs = []
    seen: set[str] = set()
    for spec in _smoke_specs(cfg, app):
        name = str(spec.get("name") or spec.get("app_name") or spec.get("module"))
        if not name or name in seen:
            continue
        seen.add(name)
        specs.append(spec)
    return specs


def _smoke_result_metadata(cfg: dict, spec: dict) -> dict:
    from . import gitmem

    name = str(spec.get("name") or spec.get("app_name") or spec.get("module"))
    return {
        "app": name,
        "smoke": gitmem.smoke_command(cfg, spec, name, spec.get("source")),
        "smoke_timeout": spec.get("smoke_timeout") or ((cfg.get("smoke") or {}).get("timeout")
                                                       if isinstance(cfg.get("smoke"), dict) else None),
        "root": _repo_path(cfg, spec.get("root")),
        "source": _repo_path(cfg, spec.get("source")),
    }


def _smoke_result_for_spec(cfg: dict, spec: dict, *, http: bool = False) -> dict:
    from . import gitmem

    result = _smoke_result_metadata(cfg, spec)
    try:
        name = result["app"]
        ok, message = gitmem.smoke_app(cfg, name, spec.get("source"))
        if ok and http:
            http_result = gitmem.http_smoke_app(cfg, name, spec.get("source"), spec)
            result["http_smoke"] = http_result
            if http_result.get("ok") is False:
                ok = False
                message = f"{message}; HTTP smoke failed: {http_result.get('message')}"
    except Exception as exc:  # noqa: BLE001
        ok, message = False, f"{type(exc).__name__}: {exc}"
    result.update({"ok": ok, "message": message})
    return result


def _merge_browser_smoke_results(
    cfg: dict,
    results: list[dict],
    *,
    browser_bin: str | None = None,
    artifact_dir: str | None = None,
) -> list[dict]:
    from .browser_smoke import browser_smoke_apps

    by_app = browser_smoke_apps(
        cfg,
        [str(r["app"]) for r in results],
        browser_bin=browser_bin,
        artifact_dir=artifact_dir,
    )
    for result in results:
        browser = by_app.get(str(result["app"])) or {"ok": False, "message": "browser smoke result missing"}
        result["browser_smoke"] = browser
        if browser.get("ok") is False:
            result["ok"] = False
            prior = result.get("message") or ""
            detail = f"browser smoke failed: {browser.get('message')}"
            result["message"] = f"{prior}; {detail}" if prior else detail
    return results


def _smoke_results(
    cfg: dict,
    app: str | None = None,
    jobs: int = 1,
    *,
    http: bool = False,
    browser: bool = False,
    browser_bin: str | None = None,
    artifact_dir: str | None = None,
) -> list[dict]:
    specs = _smoke_work_specs(cfg, app)
    if jobs <= 1 or len(specs) <= 1:
        results = [_smoke_result_for_spec(cfg, spec, http=http) for spec in specs]
        return _merge_browser_smoke_results(
            cfg,
            results,
            browser_bin=browser_bin,
            artifact_dir=artifact_dir,
        ) if browser else results

    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[dict | None] = [None] * len(specs)
    with ThreadPoolExecutor(max_workers=min(jobs, len(specs))) as pool:
        futures = {
            pool.submit(_smoke_result_for_spec, cfg, spec, http=http): index
            for index, spec in enumerate(specs)
        }
        for future in as_completed(futures):
            index = futures[future]
            results[index] = future.result()
    merged = [result for result in results if result is not None]
    return _merge_browser_smoke_results(
        cfg,
        merged,
        browser_bin=browser_bin,
        artifact_dir=artifact_dir,
    ) if browser else merged


def cmd_smoke(args) -> int:
    cfg = load_config()
    if args.jobs < 1:
        print("curiator: smoke --jobs must be >= 1")
        return 2
    results = _smoke_results(
        cfg,
        args.app,
        jobs=args.jobs,
        http=args.http,
        browser=args.browser,
        browser_bin=args.browser_bin,
        artifact_dir=args.artifact_dir,
    )
    ok = all(r["ok"] for r in results)
    payload = {"ok": ok, "results": results}
    if getattr(args, "output", None):
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if ok else 1
    for r in results:
        status = "OK" if r["ok"] else "FAIL"
        detail = f" — {r['message']}" if r.get("message") else ""
        if r.get("http_smoke"):
            http_smoke = r["http_smoke"]
            if http_smoke.get("ok") is None:
                http_status = "SKIP"
            else:
                http_status = "OK" if http_smoke.get("ok") else "FAIL"
            detail += f" — http {http_status} {http_smoke.get('url') or ''}: {http_smoke.get('message')}"
        if r.get("browser_smoke"):
            browser_smoke = r["browser_smoke"]
            browser_status = "OK" if browser_smoke.get("ok") else "FAIL"
            detail += f" — browser {browser_status} {browser_smoke.get('url') or ''}: {browser_smoke.get('message')}"
        command = f" [{r['smoke']}]" if r.get("smoke") else ""
        print(f"curiator: smoke {status} {r['app']}{command}{detail}")
    print(f"curiator: smoke {'OK' if ok else 'FAILED'} ({sum(1 for r in results if r['ok'])}/{len(results)} passed)")
    return 0 if ok else 1

def _command_markdown() -> str:
    return """---
name: curiator
description: Use when working in a repo linked to a curIAtor gallery, handling curIAtor feedback IDs, opening task bundles, posting replies, or finishing app changes through curIAtor's ledger, reload, and git-as-memory workflow.
---

# curIAtor

You are working inside a repo or directory linked to a curIAtor gallery.

Use the `curiator` CLI as the source of truth:
- `curiator status` shows the linked gallery/app and git-as-memory state.
- `curiator context` prints source scope, smoke test, recent feedback, and ready commands.
- `curiator work [feedback_id]` prints the exact task bundle a headless curator would receive and marks the item `working`.
- After edits and smoke tests, use `curiator done <feedback_id> "<summary>"`.
- For proposals, use `curiator reply <app> <feedback_id> "<plan>" --status awaiting_approval`.
- Do not edit `feedback/app_feedback.sqlite` directly.
- Do not run git commit/push/rewrite commands for curator work; `curiator done`/`reply --status done` handles git-as-memory.

When the user invokes this shim:
1. If they provide no arguments, run `curiator status` and `curiator context`.
2. If they provide `work` or a feedback id, run `curiator work ...`, read the printed task bundle, and follow it.
3. If they provide `done`, help formulate and run the appropriate `curiator done ...` command after verifying the change.
"""


def _legacy_command_markdown() -> str:
    return _command_markdown().replace(
        "When the user invokes this shim:",
        "When the user invokes this command:",
    )


def _prune_empty_dirs(path: Path, stop: Path) -> None:
    while path != stop and path.exists():
        try:
            path.rmdir()
        except OSError:
            return
        path = path.parent


def _install_command_files(root: Path) -> list[Path]:
    paths = [
        root / ".claude" / "commands" / "curiator.md",
        root / ".agents" / "skills" / "curiator" / "SKILL.md",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_command_markdown())
    return paths


def _cleanup_legacy_codex_skill(root: Path) -> tuple[Path, str] | None:
    legacy = root / ".codex" / "skills" / "curiator" / "SKILL.md"
    if not legacy.exists():
        return None
    generated = {_command_markdown(), _legacy_command_markdown()}
    try:
        text = legacy.read_text()
    except OSError:
        return legacy, "kept"
    if text not in generated:
        return legacy, "kept"
    legacy.unlink()
    _prune_empty_dirs(legacy.parent, root / ".codex")
    _prune_empty_dirs(root / ".codex", root)
    return legacy, "removed"


def cmd_commands(args) -> int:
    root = Path(args.root).expanduser().resolve() if args.root else _project_root()
    paths = _install_command_files(root)
    legacy = _cleanup_legacy_codex_skill(root)
    print(f"curiator: installed interactive command shims in {root}")
    for path in paths:
        print(f"  + {path.relative_to(root)}")
    if legacy:
        legacy_path, action = legacy
        if action == "removed":
            print(f"  - {legacy_path.relative_to(root)} (legacy Codex skill path)")
        else:
            print(f"  ! kept customized legacy file: {legacy_path.relative_to(root)}")
    return 0


def cmd_init(args) -> int:
    """Scaffold a fresh collection repo: gallery.yaml + apps/sample.py + requirements.txt + feedback/ + README."""
    dest = Path(args.dir).resolve()
    files = _scaffold_files()
    created, skipped = [], []
    for rel, content in files.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            skipped.append(rel)
        else:
            p.write_text(content)
            created.append(rel)
    (dest / "feedback" / "shots").mkdir(parents=True, exist_ok=True)

    git_status = None
    if args.git:
        if (dest / ".git").exists():
            git_status = "exists"
        else:
            result = subprocess.run(["git", "init", "-q"], cwd=dest, capture_output=True, text=True)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or f"git init exited {result.returncode}").strip()
                print(f"curiator: git init failed for {dest}: {detail}")
                return result.returncode or 1
            git_status = "created"

    print(f"curiator: scaffolded a collection in {dest}")
    for f in created:
        print(f"  + {f}")
    for f in skipped:
        print(f"  · {f} (exists — left as-is)")
    if git_status == "created":
        print("  + .git/ (initialized)")
    elif git_status == "exists":
        print("  · .git/ (exists — left as-is)")
    print(f"\nnext:\n  cd {dest}\n  pip install -r requirements.txt\n"
          f"  curiator up        # gallery (then `curiator watch` in a second terminal, or `curiator serve`)")
    return 0


def _scaffold_files() -> dict[str, str]:
    return {
        "gallery.yaml": _SCAFFOLD_GALLERY,
        "apps/sample.py": _SCAFFOLD_SAMPLE_APP,
        "requirements.txt": _SCAFFOLD_REQUIREMENTS,
        "README.md": _SCAFFOLD_README,
        ".gitignore": _SCAFFOLD_GITIGNORE,
    }


# ───────────────────────── collection scaffold templates (curiator init) ─────────────────────────

_SCAFFOLD_GALLERY = """\
# curIAtor collection — your apps (apps/) + how the curator runs.
# Add one entry per app; the curator edits each app's `source` when you give feedback on it.

apps:
  - name: sample
    title: Sample app
    mount: { kind: dash-inproc, module: sample }   # import & mount in-process (Dash); or kind: proxy {cmd, port}
    source: apps/sample.py                          # what the curator edits
    tags: [demo]

  # App-directory shape: one folder can expose multiple endpoints that share the same source scope.
  # - name: lab_suite
  #   root: apps/lab_suite
  #   source: .
  #   smoke: python -m compileall -q .
  #   mounts:
  #     - name: overview
  #       mount: { kind: dash-inproc, module: overview, source: overview.py }
  #     - name: node_ssr
  #       mount: { kind: proxy, cmd: "npm start -- --port {port}", port: 8710 }

agent:
  adapter: headless-cc        # headless-cc (your Claude sub) | api (teams) | command (BYO)
  autonomy: auto-small        # auto-small (fix small things) | propose-only (plan first)

# How feedback on the RUNNER itself (the ◆ General channel) is handled:
runner:
  mode: pinned                # pinned (consumer): drafts an upstream issue/PR; never edits the package
  # mode: checkout            # contributor: patches the runner locally (set `path` to a curiator checkout)
  # path: ../curiator

feedback:
  dir: feedback               # SQLite ledger source of truth + shots/ live here
  screenshots: true

shell:
  port: 8300
"""

_SCAFFOLD_SAMPLE_APP = '''\
"""sample.py — a starter Dash app. Star/comment/screenshot it in the gallery and the curator edits THIS file.

Every curIAtor app exposes `build_app()` returning a `dash.Dash`, plus a module-level `app` so the
shell can mount it either way.
"""
from __future__ import annotations

import dash
from dash import dcc, html
import plotly.graph_objects as go


def build_app() -> dash.Dash:
    app = dash.Dash(__name__)
    app.title = "Sample"
    fig = go.Figure(go.Bar(x=["A", "B", "C", "D"], y=[4, 7, 3, 8], marker_color="#2980b9"))
    fig.update_layout(title="Sample metric", xaxis_title="category", yaxis_title="value",
                      margin=dict(l=60, r=20, t=40, b=40), plot_bgcolor="white", height=420)
    app.layout = html.Div(
        style={"fontFamily": "system-ui, sans-serif", "margin": "12px 20px"},
        children=[
            html.H3("Sample app"),
            html.P("Leave a comment in the gallery and the curator will edit this file."),
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
        ],
    )
    return app


app = build_app()

if __name__ == "__main__":
    app.run(debug=False, port=8401)
'''

_SCAFFOLD_REQUIREMENTS = """\
curiator>=0.1.0   # pin exact (curiator==X.Y.Z) for a reproducible collection
"""

_SCAFFOLD_README = """\
# My curIAtor collection

Apps live in `apps/`; `gallery.yaml` is the registry. curIAtor serves every app in one gallery and an
AI curator fixes them from in-browser feedback (star / comment / screenshot).

## Run

    pip install -r requirements.txt
    curiator up        # gallery at http://127.0.0.1:8300
    curiator watch     # (second terminal) arm the feedback→fix loop
    # …or both at once:  curiator serve

Open the gallery, star/comment/screenshot an app, and watch the curator reply in the panel.

## Add an app

Use the scaffold command; it creates `apps/<name>/` and updates `gallery.yaml`:

    curiator app create revenue --template dash --title "Revenue dashboard"

Templates: `dash`, `static`, `python`, `node`, `flask`, `fastapi`, `rust`, `react`, `svelte`, `vue`, `next`, `streamlit`, `gradio`.
Node, Flask, FastAPI, and Rust use lightweight server scaffolds behind same-origin proxy mounts.
React/Svelte/Vue use Vite; React/Svelte/Vue/Next can auto-detect npm/pnpm/yarn/bun. Next, Streamlit, and Gradio use prefix-preserving proxy mounts.
You can still edit `gallery.yaml` manually for existing apps.

See the consumer guide: https://github.com/LearnedResponse/curIAtor/blob/main/docs/USING_CURIATOR.md
"""

_SCAFFOLD_GITIGNORE = """\
feedback/shots/
feedback/audio/
feedback/tasks/
feedback/replies/
feedback/app_feedback.sqlite*
feedback/app_feedback.json
.curiator-users.json
__pycache__/
*.pyc
"""
