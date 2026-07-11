"""Explicit shared-source dependency graph, verification, and task scope."""
from __future__ import annotations

import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .config import app_specs


class DependencyError(RuntimeError):
    """The declared dependency graph or requested component scope is invalid."""


def _strings(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in value if str(item)]


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True)


def _git_owner(path: Path) -> Path | None:
    probe = path if path.is_dir() else path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    result = _git(probe, "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def _relative(path: Path, root: Path) -> str | None:
    try:
        value = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    return value or "."


def _component_cycle(components: dict[str, dict]) -> list[str] | None:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(key: str) -> list[str] | None:
        if state.get(key) == 2:
            return None
        if state.get(key) == 1:
            start = stack.index(key)
            return [*stack[start:], key]
        state[key] = 1
        stack.append(key)
        for dependency in components[key]["depends_on"]:
            if dependency in components:
                cycle = visit(dependency)
                if cycle:
                    return cycle
        stack.pop()
        state[key] = 2
        return None

    for key in components:
        cycle = visit(key)
        if cycle:
            return cycle
    return None


def normalize(cfg: dict, *, strict: bool = True) -> dict:
    """Normalize declared components/apps and return structural diagnostics."""
    repo = Path(cfg.get("repo_root") or ".").resolve()
    errors: list[str] = []
    warnings: list[str] = []
    components: dict[str, dict] = {}
    raw_components = cfg.get("components") or []
    if not isinstance(raw_components, list):
        errors.append("components must be a list")
        raw_components = []
    for index, raw in enumerate(raw_components):
        if not isinstance(raw, dict):
            errors.append(f"components[{index}] must be a mapping")
            continue
        key = str(raw.get("key") or raw.get("name") or "").strip()
        if not key:
            errors.append(f"components[{index}] needs key or name")
            continue
        if key in components:
            errors.append(f"duplicate component {key!r}")
            continue
        root_value = raw.get("root")
        if not root_value:
            errors.append(f"component {key!r} needs root")
            continue
        root = (repo / str(root_value)).resolve() if not Path(str(root_value)).is_absolute() else Path(str(root_value)).resolve()
        source_value = raw.get("source", ".")
        source = (root / str(source_value)).resolve() if not Path(str(source_value)).is_absolute() else Path(str(source_value)).resolve()
        derived_owner = _git_owner(source)
        owner_value = raw.get("owner_repo")
        owner = (
            ((repo / str(owner_value)).resolve() if not Path(str(owner_value)).is_absolute()
             else Path(str(owner_value)).resolve())
            if owner_value else derived_owner
        )
        if not root.exists():
            errors.append(f"component {key!r} root does not exist: {root}")
        if not source.exists():
            errors.append(f"component {key!r} source does not exist: {source}")
        if owner is None:
            errors.append(f"component {key!r} is not owned by a Git repository: {source}")
        elif not owner.exists() or _git_owner(owner) != owner:
            errors.append(f"component {key!r} owner_repo is not a Git repository root: {owner}")
        elif derived_owner != owner:
            errors.append(
                f"component {key!r} source is owned by {derived_owner or 'no Git repository'}, "
                f"not declared owner_repo {owner}"
            )
        if _relative(source, root) is None:
            errors.append(f"component {key!r} source must be inside its root: {source}")
        if owner is not None and _relative(owner, repo) is None:
            errors.append(f"component {key!r} owning repository must be inside the collection: {owner}")
        elif owner is not None and owner != repo:
            owner_rel = _relative(owner, repo)
            tracked = _git(repo, "ls-files", "--stage", "--", str(owner_rel)).stdout.split()
            if not tracked or tracked[0] != "160000":
                errors.append(
                    f"component {key!r} nested owner must be tracked as a Git subrepo: {owner_rel}"
                )
        if not raw.get("smoke"):
            warnings.append(f"component {key!r} has no smoke command")
        components[key] = {
            "key": key,
            "root": str(root),
            "root_rel": _relative(root, repo),
            "source": str(source),
            "source_rel": _relative(source, owner) if owner else None,
            "collection_rel": _relative(source, repo),
            "owner_repo": str(owner) if owner else None,
            "owner_repo_rel": _relative(owner, repo) if owner else None,
            "depends_on": _strings(raw.get("depends_on")),
            "smoke": str(raw.get("smoke") or "") or None,
            "smoke_timeout": int(raw.get("smoke_timeout") or 60),
        }
    for key, component in components.items():
        for dependency in component["depends_on"]:
            if dependency not in components:
                errors.append(f"component {key!r} depends on unknown component {dependency!r}")
    cycle = _component_cycle(components)
    if cycle:
        errors.append("component dependency cycle: " + " -> ".join(cycle))

    app_dependencies: dict[str, list[str]] = {}
    for spec in app_specs(cfg):
        key = str(spec.get("name") or spec.get("app_name") or spec.get("module") or "")
        if not key:
            continue
        declared = _strings(spec.get("depends_on"))
        app_dependencies[key] = list(dict.fromkeys(declared))
        for dependency in declared:
            if dependency not in components:
                errors.append(f"app {key!r} depends on unknown component {dependency!r}")
    graph = {
        "components": components,
        "apps": app_dependencies,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
    }
    if strict and graph["errors"]:
        raise DependencyError("; ".join(graph["errors"]))
    return graph


def component_order(graph: dict, selected: list[str] | set[str] | tuple[str, ...]) -> list[str]:
    """Return dependency-first transitive closure for selected components."""
    components = graph["components"]
    ordered: list[str] = []
    seen: set[str] = set()

    def visit(key: str) -> None:
        if key in seen:
            return
        if key not in components:
            raise DependencyError(f"unknown component {key!r}")
        seen.add(key)
        for dependency in components[key]["depends_on"]:
            visit(dependency)
        ordered.append(key)

    for key in selected:
        visit(str(key))
    return ordered


def app_closure(graph: dict, app: str) -> list[str]:
    if app not in graph["apps"]:
        return []
    return component_order(graph, graph["apps"][app])


def writable_components(graph: dict, app: str, entry: dict) -> list[str]:
    requested = list(dict.fromkeys(_strings(entry.get("writable_components"))))
    closure = set(app_closure(graph, app))
    outside = [key for key in requested if key not in closure]
    if outside:
        raise DependencyError(
            f"feedback requests component(s) outside the dependency closure for {app!r}: "
            + ", ".join(outside)
        )
    return [key for key in component_order(graph, requested) if key in requested]


def changed_components(graph: dict, selected: list[str] | set[str] | tuple[str, ...]) -> list[str]:
    """Return selected component keys whose owned source scope differs from HEAD."""
    ordered = component_order(graph, selected)
    return [key for key in ordered if _component_changed(graph["components"][key])]


def affected_components(graph: dict, changed: list[str] | set[str]) -> list[str]:
    changed_set = set(changed)
    affected = [
        key for key in graph["components"]
        if changed_set.intersection(component_order(graph, [key]))
    ]
    return [key for key in component_order(graph, affected) if key in set(affected)]


def affected_apps(graph: dict, changed: list[str] | set[str]) -> list[str]:
    changed_set = set(changed)
    return sorted(
        app for app in graph["apps"]
        if changed_set.intersection(app_closure(graph, app))
    )


def _component_changed(component: dict) -> bool:
    owner = Path(str(component.get("owner_repo") or ""))
    scope = component.get("source_rel")
    if not owner.is_dir() or not scope:
        return False
    result = _git(owner, "status", "--porcelain=v1", "--", str(scope))
    return bool(result.stdout.strip()) if result.returncode == 0 else False


def _source_changed(source: Path) -> bool:
    owner = _git_owner(source)
    if owner is None:
        return False
    scope = _relative(source, owner)
    if not scope:
        return False
    result = _git(owner, "status", "--porcelain=v1", "--", scope)
    return bool(result.stdout.strip()) if result.returncode == 0 else False


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _run_component(component: dict) -> dict:
    command = component.get("smoke")
    if not command:
        return {"kind": "component", "key": component["key"], "ok": False, "message": "no smoke configured"}
    try:
        result = subprocess.run(
            shlex.split(str(command)),
            cwd=component["root"],
            capture_output=True,
            text=True,
            timeout=int(component.get("smoke_timeout") or 60),
        )
    except subprocess.TimeoutExpired:
        return {"kind": "component", "key": component["key"], "ok": False, "message": "smoke timed out"}
    return {
        "kind": "component",
        "key": component["key"],
        "ok": result.returncode == 0,
        "message": "passed" if result.returncode == 0 else (result.stderr or result.stdout or "failed").strip()[:500],
    }


def verify_done(cfg: dict, app: str, entry: dict) -> dict:
    """Gate a component edit on dependency-first component and affected-app smokes."""
    graph = normalize(cfg)
    closure = app_closure(graph, app)
    if not closure:
        return {"changed_components": [], "components": [], "apps": [], "reload_apps": [app]}
    writable = writable_components(graph, app, entry)
    changed = changed_components(graph, closure)
    unauthorized = [key for key in changed if key not in writable]
    if unauthorized:
        raise DependencyError(
            "read-only shared component changed without explicit feedback scope: " + ", ".join(unauthorized)
        )
    if not changed:
        return {"changed_components": [], "components": [], "apps": [], "reload_apps": [app]}

    component_results = [_run_component(graph["components"][key]) for key in affected_components(graph, changed)]
    failed_components = [row for row in component_results if not row["ok"]]
    if failed_components:
        row = failed_components[0]
        raise DependencyError(f"component smoke failed for {row['key']}: {row['message']}")

    from . import gitmem

    apps = affected_apps(graph, changed)
    changed_sources = [Path(graph["components"][key]["source"]) for key in changed]
    selected_spec = next((item for item in app_specs(cfg) if item.get("name") == app), None) or {}
    selected_source = Path(selected_spec["source"]) if selected_spec.get("source") else None
    read_only_app_edits = []
    for key in apps:
        if key == app:
            continue
        spec = next((item for item in app_specs(cfg) if item.get("name") == key), None) or {}
        source_value = spec.get("source")
        if not source_value:
            continue
        source = Path(source_value)
        if selected_source and (_contains(source, selected_source) or _contains(selected_source, source)):
            continue
        if any(_contains(source, component_source) for component_source in changed_sources):
            continue
        if _source_changed(source):
            read_only_app_edits.append(key)
    if read_only_app_edits:
        raise DependencyError(
            "dependent app source changed without explicit write scope: "
            + ", ".join(read_only_app_edits)
        )

    dependency_settings = cfg.get("dependency_verification") or {}
    jobs = max(1, min(int(dependency_settings.get("jobs") or 2), len(apps) or 1))

    def smoke_app(key: str) -> dict:
        spec = next((item for item in app_specs(cfg) if item.get("name") == key), None) or {}
        details = gitmem.smoke_app_details(cfg, key, spec.get("source"))
        return {"kind": "app", "key": key, "ok": bool(details["ok"]), "message": str(details["message"])}

    by_key: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(smoke_app, key): key for key in apps}
        for future in as_completed(futures):
            by_key[futures[future]] = future.result()
    app_results = [by_key[key] for key in apps]
    failed_apps = [row for row in app_results if not row["ok"]]
    if failed_apps:
        row = failed_apps[0]
        raise DependencyError(f"dependent app smoke failed for {row['key']}: {row['message']}")
    return {
        "changed_components": changed,
        "components": component_results,
        "apps": app_results,
        "reload_apps": apps,
    }


def task_context(cfg: dict, app: str, entry: dict) -> tuple[str, list[str]]:
    graph = normalize(cfg)
    closure = app_closure(graph, app)
    if not closure:
        return "", []
    writable = set(writable_components(graph, app, entry))
    affected = affected_apps(graph, writable) if writable else []
    lines = [
        "## Shared dependency context",
        "",
        "Dependency context does not imply write authority. Only components marked **WRITABLE** below may be edited.",
    ]
    writable_paths = []
    for key in closure:
        component = graph["components"][key]
        access = "WRITABLE for this feedback" if key in writable else "READ-ONLY"
        source = component.get("collection_rel") or component["source"]
        lines.append(f"- `{key}`: `{source}` - **{access}**")
        if component.get("smoke"):
            lines.append(f"  - component smoke: `{component['smoke']}` (cwd `{component['root_rel'] or component['root']}`)")
        if key in writable:
            writable_paths.append(component["source"])
    if affected:
        lines.extend([
            "",
            "If a writable component changes, curIAtor will block `done` until these dependent apps pass smoke:",
            "- " + ", ".join(f"`{key}`" for key in affected),
            "Dependent app sources remain read-only unless separately scoped.",
        ])
    return "\n".join(lines), writable_paths


def public_graph(graph: dict) -> dict:
    """JSON/doctor view with collection-relative paths and ownership, not runtime objects."""
    def closure_for(app: str) -> list[str]:
        try:
            return app_closure(graph, app)
        except DependencyError:
            return []

    return {
        "components": [
            {
                "key": component["key"],
                "source": component.get("collection_rel") or component["source"],
                "owner_repo": component.get("owner_repo_rel") or ".",
                "depends_on": component["depends_on"],
                "smoke": component.get("smoke"),
            }
            for component in graph["components"].values()
        ],
        "apps": [
            {"app": app, "depends_on": direct, "closure": closure_for(app)}
            for app, direct in sorted(graph["apps"].items())
            if direct
        ],
        "errors": graph["errors"],
        "warnings": graph["warnings"],
    }
