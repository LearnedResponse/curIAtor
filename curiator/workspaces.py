"""Host-native Docker fork workspaces for trusted/local experimentation."""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import __version__, ledger, workspace_store
from .config import app_spec, app_specs


DEFAULT_IMAGE = f"curiator-workspace:{__version__}"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class WorkspaceError(RuntimeError):
    """Workspace creation or lifecycle operation failed safely."""


def _slug(value: str) -> str:
    return _SLUG_RE.sub("-", value.lower()).strip("-")[:36] or "workspace"


def _run(cmd: list[str], *, cwd: Path | None = None, check: bool = True,
         timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise WorkspaceError(f"{' '.join(cmd)} failed: {detail or f'exit {result.returncode}'}")
    return result


def _git(repo: Path, *args: str, check: bool = True) -> str:
    return _run(["git", *args], cwd=repo, check=check).stdout.strip()


def _git_root(path: Path) -> Path:
    probe = path if path.is_dir() else path.parent
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=probe, check=False)
    if result.returncode:
        raise WorkspaceError(f"workspace source is not in a Git repository: {path}")
    return Path(result.stdout.strip()).resolve()


def _relative(path: Path, root: Path, label: str) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise WorkspaceError(f"{label} {path} is outside collection repository {root}") from exc
    return rel.as_posix() or "."


def resolve_snapshot(
    cfg: dict,
    app_key: str,
    ref: str = "HEAD",
    *,
    collection_ref: str | None = None,
    preview: bool = False,
    name: str | None = None,
) -> dict:
    spec = app_spec(cfg, app_key)
    if not spec:
        raise WorkspaceError(f"unknown app {app_key!r}")
    collection_root = Path(cfg["repo_root"]).resolve()
    collection_repo = _git_root(collection_root)
    source = Path(spec.get("source") or spec.get("root") or collection_root).resolve()
    owning_repo = _git_root(source)
    owning_sha = _git(owning_repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    collection_sha = owning_sha if owning_repo == collection_repo else _git(
        collection_repo, "rev-parse", "--verify", f"{collection_ref or 'HEAD'}^{{commit}}",
    )
    owning_rel = None if owning_repo == collection_repo else _relative(owning_repo, collection_repo, "owning repo")
    gallery_rel = _relative(Path(cfg["gallery_path"]), collection_repo, "gallery")
    collection_rel = _relative(collection_root, collection_repo, "collection root")
    workspace_id = uuid.uuid4().hex[:12]
    workspace_name = _slug(name or f"{app_key}-fork")
    branch = None if preview else f"curiator/workspace/{workspace_name}-{workspace_id[:6]}"
    mounts = []
    for candidate in app_specs(cfg):
        candidate_source = Path(candidate.get("source") or candidate.get("root") or collection_root)
        try:
            owner = _git_root(candidate_source)
        except WorkspaceError:
            continue
        if owner == owning_repo:
            mounts.append(str(candidate.get("name") or candidate.get("app_name")))
    from .dependencies import app_closure, normalize

    dependency_graph = normalize(cfg)
    dependency_closure = app_closure(dependency_graph, app_key)
    dependency_rows = []
    dependency_repositories: dict[str, dict] = {}
    for component_key in dependency_closure:
        component = dependency_graph["components"][component_key]
        component_owner = Path(component["owner_repo"]).resolve()
        if component_owner == owning_repo:
            component_sha = owning_sha
        elif component_owner == collection_repo:
            component_sha = collection_sha
        else:
            component_owner_rel = _relative(component_owner, collection_repo, "component owning repo")
            try:
                component_sha = _git(
                    collection_repo,
                    "rev-parse",
                    "--verify",
                    f"{collection_sha}:{component_owner_rel}",
                )
            except WorkspaceError as exc:
                raise WorkspaceError(
                    f"cannot resolve component {component_key!r} owner {component_owner_rel} "
                    f"at collection snapshot {collection_sha}"
                ) from exc
            dependency_repositories.setdefault(
                str(component_owner),
                {
                    "repo": str(component_owner),
                    "repo_rel": component_owner_rel,
                    "sha": component_sha,
                },
            )
        dependency_rows.append({
            "key": component_key,
            "source": component.get("collection_rel") or component["source"],
            "owner_repo": str(component_owner),
            "owner_repo_rel": None if component_owner == collection_repo else _relative(
                component_owner,
                collection_repo,
                "component owning repo",
            ),
            "owner_sha": component_sha,
            "depends_on": component["depends_on"],
            "writable": False,
        })
    dependency_repo_rows = list(dependency_repositories.values())
    for index, dependency_repo in enumerate(dependency_repo_rows):
        dependency_repo["volume"] = f"curiator-ws-{workspace_id}-dependency-{index}"
    return {
        "id": workspace_id,
        "name": workspace_name,
        "app_key": app_key,
        "mode": "preview" if preview else "branch",
        "branch": branch,
        "requested_ref": ref,
        "requested_collection_ref": collection_ref,
        "collection_repo": str(collection_repo),
        "collection_base_sha": collection_sha,
        "collection_dirty": bool(_git(collection_repo, "status", "--porcelain", check=False)),
        "collection_rel": collection_rel,
        "gallery_rel": gallery_rel,
        "owning_repo": str(owning_repo),
        "owning_repo_base_sha": owning_sha,
        "owning_repo_rel": owning_rel,
        "owning_dirty": bool(_git(owning_repo, "status", "--porcelain", check=False)),
        "source_rel": _relative(source, owning_repo, "app source"),
        "mounts": sorted(set(mounts)),
        "dependency_closure": dependency_closure,
        "dependencies": dependency_rows,
        "dependency_repositories": dependency_repo_rows,
        "container_port": int((cfg.get("shell") or {}).get("port", 8200)),
    }


class DockerClient:
    def __init__(self, binary: str | None = None):
        self.binary = binary or shutil.which("docker") or "docker"

    def run(self, *args: str, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        try:
            return _run([self.binary, *args], check=check, timeout=timeout)
        except FileNotFoundError as exc:
            raise WorkspaceError("Docker CLI not found; run `curiator workspace doctor`") from exc

    def inspect(self, kind: str, name: str) -> dict | None:
        result = self.run(kind, "inspect", name, check=False)
        if result.returncode:
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise WorkspaceError(f"cannot parse Docker {kind} inspect output for {name}") from exc
        return payload[0] if isinstance(payload, list) and payload else None

    def image_exists(self, image: str) -> bool:
        return self.inspect("image", image) is not None

    def runtime(self) -> dict:
        result = self.run("info", "--format", "{{json .}}", check=False, timeout=10)
        inside = Path("/.dockerenv").exists() or bool(os.environ.get("container"))
        mounted = next((str(path) for path in (Path("/var/run/docker.sock"), Path("/run/docker.sock"))
                        if path.exists()), None)
        unsafe = bool(inside and mounted)
        return {
            "daemon_available": result.returncode == 0,
            "daemon_reason": "Docker daemon reachable" if result.returncode == 0 else (
                (result.stderr or result.stdout or "Docker daemon unavailable").strip().splitlines()[-1]
            ),
            "inside_container": inside,
            "mounted_socket": mounted,
            "unsafe_socket_inside_container": unsafe,
            "workspace_orchestration_available": result.returncode == 0 and not unsafe,
        }


class WorkspaceManager:
    def __init__(self, cfg: dict, docker: DockerClient | None = None):
        self.cfg = cfg
        self.docker = docker or DockerClient()

    def doctor(self, workspace_id: str | None = None) -> dict:
        docker = {
            "available": bool(shutil.which(self.docker.binary) or Path(self.docker.binary).exists()),
            "path": self.docker.binary,
            **self.docker.runtime(),
        }
        payload = {
            "ok": docker.get("workspace_orchestration_available") is True,
            "docker": docker,
            "default_image": DEFAULT_IMAGE,
            "image_available": self.docker.image_exists(DEFAULT_IMAGE) if docker.get("daemon_available") else False,
            "control_plane": "host-native",
            "child_docker_socket": "never mounted",
        }
        if workspace_id:
            row = self.get(workspace_id)
            payload["workspace"] = row
            payload["runtime"] = self.docker.inspect("container", row["container_name"])
        return payload

    def ensure_image(self, image: str, *, build_if_missing: bool = True) -> dict:
        found = self.docker.inspect("image", image)
        if found:
            return found
        if not build_if_missing:
            raise WorkspaceError(f"workspace image {image!r} is missing")
        root = Path(__file__).resolve().parents[1]
        dockerfile = root / "Dockerfile.workspace"
        if not dockerfile.exists():
            raise WorkspaceError(
                f"workspace image {image!r} is missing and Dockerfile.workspace is unavailable; build/pull it first"
            )
        self.docker.run(
            "build", "--file", str(dockerfile), "--tag", image, str(root),
            timeout=1800,
        )
        found = self.docker.inspect("image", image)
        if not found:
            raise WorkspaceError(f"Docker reported a successful build but image {image!r} is unavailable")
        return found

    @staticmethod
    def _resource_names(workspace_id: str) -> tuple[str, str, str]:
        return (
            f"curiator-ws-{workspace_id}",
            f"curiator-ws-{workspace_id}-source",
            f"curiator-ws-{workspace_id}-state",
        )

    def _volume(self, workspace_id: str, name: str, role: str) -> None:
        self.docker.run(
            "volume", "create",
            "--label", f"curiator.workspace={workspace_id}",
            "--label", f"curiator.role={role}",
            name,
        )

    def _initialize_volumes(self, descriptor: dict, image: str, source_volume: str, state_volume: str) -> None:
        args = [
            "run", "--rm", "--user", "0:0",
            "--security-opt", "label=disable",
            "--label", f"curiator.workspace={descriptor['id']}",
            "--mount", f"type=volume,source={source_volume},target=/workspace/source",
            "--mount", f"type=volume,source={state_volume},target=/workspace/state",
            "--volume", f"{descriptor['collection_repo']}:/canonical:ro",
        ]
        if descriptor.get("owning_repo_rel"):
            args += ["--volume", f"{descriptor['owning_repo']}:/owning:ro"]
        dependency_args = []
        for index, dependency in enumerate(descriptor.get("dependency_repositories") or []):
            mount_path = f"/dependency-{index}"
            readonly_target = f"/workspace/dependency-volumes/{index}"
            args += ["--volume", f"{dependency['repo']}:{mount_path}:ro"]
            args += [
                "--mount",
                f"type=volume,source={dependency['volume']},target={readonly_target}",
            ]
            dependency_args.append(json.dumps({
                "source": mount_path,
                "sha": dependency["sha"],
                "rel": dependency["repo_rel"],
                "readonly_target": readonly_target,
            }, separators=(",", ":")))
        args += [
            image, "python", "-I", "-m", "curiator.workspace_init",
            "--collection", "/canonical",
            "--collection-sha", descriptor["collection_base_sha"],
        ]
        if descriptor.get("owning_repo_rel"):
            args += [
                "--owning", "/owning",
                "--owning-sha", descriptor["owning_repo_base_sha"],
                "--owning-rel", descriptor["owning_repo_rel"],
            ]
        if descriptor.get("branch"):
            args += ["--branch", descriptor["branch"]]
        for dependency_arg in dependency_args:
            args += ["--dependency", dependency_arg]
        self.docker.run(*args, timeout=300)

    def _seed_payload(self, descriptor: dict, feedback_id: str, *, dispatch: bool) -> dict:
        data = ledger.load(self.cfg)
        found = None
        for key, entries in data.items():
            for entry in entries if isinstance(entries, list) else []:
                if entry.get("id") == feedback_id:
                    found = (key, entry)
                    break
            if found:
                break
        if not found:
            raise WorkspaceError(f"feedback id {feedback_id!r} not found")
        key, entry = found
        if key != descriptor["app_key"]:
            raise WorkspaceError(f"feedback {feedback_id} belongs to {key}, not {descriptor['app_key']}")
        from .loop.adapters import _related_thread_entries

        selected = [*_related_thread_entries(self.cfg, key, entry, limit=50), entry]
        provenance = {
            "parent_collection": self.cfg["gallery_path"],
            "parent_app_key": key,
            "parent_feedback_id": feedback_id,
            "workspace_id": descriptor["id"],
            "base_sha": descriptor["owning_repo_base_sha"],
        }
        entries = json.loads(json.dumps(selected))
        for item in entries:
            item["workspace_provenance"] = provenance
            if item.get("id") == feedback_id and item.get("kind") != "system":
                item["status"] = "new" if dispatch else "held"
        return {"app_key": key, "entries": entries, "provenance": provenance}

    def _seed_feedback(self, descriptor: dict, image: str, source_volume: str, state_volume: str,
                       feedback_id: str, *, dispatch: bool) -> None:
        payload = self._seed_payload(descriptor, feedback_id, dispatch=dispatch)
        canonical_state = ledger.feedback_dir(self.cfg).resolve()
        with tempfile.TemporaryDirectory(prefix="curiator-workspace-seed-") as temp:
            seed_file = Path(temp) / "seed.json"
            seed_file.write_text(json.dumps(payload), encoding="utf-8")
            gallery = f"/workspace/source/{descriptor['gallery_rel']}"
            args = [
                "run", "--rm", "--user", "1000:1000",
                "--security-opt", "label=disable",
                "--mount", f"type=volume,source={source_volume},target=/workspace/source",
                "--mount", f"type=volume,source={state_volume},target=/workspace/state",
                "--volume", f"{seed_file}:/seed/seed.json:ro",
                "--volume", f"{canonical_state}:/canonical-state:ro",
                image, "python", "-I", "-m", "curiator.workspace_seed",
                "--gallery", gallery,
                "--state-dir", "/workspace/state",
                "--payload", "/seed/seed.json",
                "--canonical-state", "/canonical-state",
            ]
            self.docker.run(*args, timeout=120)

    def _write_meta(self, row: dict) -> None:
        payload = {
            "id": row["id"], "name": row["name"], "mode": row["mode"],
            "base_sha": row["owning_repo_base_sha"], "branch": row.get("branch"),
            "control_url": f"http://127.0.0.1:{int((self.cfg.get('shell') or {}).get('port', 8200))}",
        }
        self.docker.run(
            "run", "--rm", "--user", "1000:1000",
            "--mount", f"type=volume,source={row['state_volume']},target=/workspace/state",
            row["image"], "python", "-I", "-m", "curiator.workspace_meta",
            "--state-dir", "/workspace/state", "--payload", json.dumps(payload, sort_keys=True),
            timeout=120,
        )

    def _bootstrap_source(self, descriptor: dict, image: str, source_volume: str, state_volume: str) -> None:
        gallery = f"/workspace/source/{descriptor['gallery_rel']}"
        self.docker.run(
            "run", "--rm", "--user", "1000:1000",
            "--mount", f"type=volume,source={source_volume},target=/workspace/source",
            "--mount", f"type=volume,source={state_volume},target=/workspace/state",
            image, "python", "-I", "-m", "curiator.workspace_bootstrap",
            "--gallery", gallery, "--state-dir", "/workspace/state",
            timeout=1800,
        )

    @staticmethod
    def _credential_source(kind: str) -> Path | None:
        if kind == "none":
            return None
        source = Path.home() / (".claude/.credentials.json" if kind == "claude" else ".codex/auth.json")
        if not source.is_file():
            raise WorkspaceError(f"{kind} credentials were requested but {source} does not exist")
        return source

    def _stage_credentials(self, kind: str, image: str, state_volume: str) -> None:
        source = self._credential_source(kind)
        if source is None:
            return
        self.docker.run(
            "run", "--rm", "--user", "0:0",
            "--security-opt", "label=disable",
            "--mount", f"type=volume,source={state_volume},target=/workspace/state",
            "--volume", f"{source}:/run/curiator-credential:ro",
            image, "python", "-I", "-m", "curiator.workspace_credential",
            "--kind", kind, "--source", "/run/curiator-credential",
            "--state-dir", "/workspace/state", "--uid", "1000", "--gid", "1000",
            timeout=120,
        )

    def _create_container(self, descriptor: dict, image: str, container_name: str,
                          source_volume: str, state_volume: str, credentials: str,
                          agent_network: bool = True, agent_sandbox: str = "container",
                          agent_adapter: str | None = None, agent_model: str | None = None,
                          agent_autonomy: str | None = None) -> str:
        workdir = "/workspace/source"
        if descriptor["collection_rel"] != ".":
            workdir += "/" + descriptor["collection_rel"]
        gallery = f"/workspace/source/{descriptor['gallery_rel']}"
        port = str(descriptor["container_port"])
        args = [
            "create", "--name", container_name,
            "--label", f"curiator.workspace={descriptor['id']}",
            "--label", "curiator.managed=true",
            "--user", "1000:1000",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--security-opt", "label=disable",
            "--memory", "2g", "--cpus", "2", "--pids-limit", "512", "--shm-size", "512m",
            "--network", "bridge",
            "--mount", f"type=volume,source={source_volume},target=/workspace/source",
            "--mount", f"type=volume,source={state_volume},target=/workspace/state",
            "--workdir", workdir,
            "--publish", f"127.0.0.1::{port}",
            "--env", "SHELL_HOST=0.0.0.0",
            "--env", f"CURIATOR_WORKSPACE_ID={descriptor['id']}",
            "--env", f"CURIATOR_WORKSPACE_NAME={descriptor['name']}",
            "--env", f"CURIATOR_WORKSPACE_MODE={descriptor['mode']}",
            "--env", f"CURIATOR_WORKSPACE_BASE_SHA={descriptor['owning_repo_base_sha']}",
            "--env", f"CURIATOR_WORKSPACE_BRANCH={descriptor.get('branch') or ''}",
            "--env", (
                "CURIATOR_WORKSPACE_CONTROL_URL=http://127.0.0.1:"
                f"{int((self.cfg.get('shell') or {}).get('port', 8200))}"
            ),
        ]
        for dependency in descriptor.get("dependency_repositories") or []:
            target = f"/workspace/source/{dependency['repo_rel']}"
            args += [
                "--mount",
                f"type=volume,source={dependency['volume']},target={target},readonly",
            ]
        args += [
            image,
            "python", "-I", "-m", "curiator.workspace_entry",
            "--gallery", gallery, "--state-dir", "/workspace/state", "--credentials", credentials,
            "--agent-network", "on" if agent_network else "off",
            "--agent-sandbox", agent_sandbox,
        ]
        if agent_adapter:
            args += ["--agent-adapter", agent_adapter]
        if agent_model:
            args += ["--agent-model", agent_model]
        if agent_autonomy:
            args += ["--agent-autonomy", agent_autonomy]
        return self.docker.run(*args, timeout=120).stdout.strip()

    def _host_port(self, container_name: str, container_port: int) -> int:
        info = self.docker.inspect("container", container_name)
        if not info:
            raise WorkspaceError(f"workspace container disappeared: {container_name}")
        ports = ((info.get("NetworkSettings") or {}).get("Ports") or {}).get(f"{container_port}/tcp") or []
        if not ports:
            # Podman may expose the allocated binding only through HostConfig before first start.
            ports = ((info.get("HostConfig") or {}).get("PortBindings") or {}).get(f"{container_port}/tcp") or []
        try:
            return int(ports[0]["HostPort"])
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise WorkspaceError(f"Docker did not allocate a host port for {container_name}") from exc

    @staticmethod
    def _wait_http(port: int, timeout: float = 60) -> None:
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{port}/api/bootstrap"
        last = "not reachable"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, OSError) as exc:
                last = str(exc)
            time.sleep(0.5)
        raise WorkspaceError(f"workspace shell did not become healthy at {url}: {last}")

    def create(self, app_key: str, *, ref: str = "HEAD", collection_ref: str | None = None,
               name: str | None = None,
               preview: bool = False, image: str = DEFAULT_IMAGE, build_if_missing: bool = True,
               credentials: str = "none", feedback_id: str | None = None,
               dispatch_feedback: bool = False, agent_network: bool = True,
               agent_sandbox: str = "container", agent_adapter: str | None = None,
               agent_model: str | None = None, agent_autonomy: str | None = None,
               wait: bool = True, background: bool = False) -> dict:
        descriptor = resolve_snapshot(
            self.cfg, app_key, ref, collection_ref=collection_ref, preview=preview, name=name,
        )
        descriptor["agent_provider"] = credentials
        descriptor["agent_network"] = agent_network
        descriptor["agent_sandbox"] = agent_sandbox
        descriptor["agent_adapter"] = agent_adapter
        descriptor["agent_model"] = agent_model
        descriptor["agent_autonomy"] = agent_autonomy
        container_name, source_volume, state_volume = self._resource_names(descriptor["id"])
        row = workspace_store.create(self.cfg, {
            "id": descriptor["id"], "name": descriptor["name"], "app_key": app_key,
            "owner_id": None, "mode": descriptor["mode"], "status": "creating",
            "collection_repo": descriptor["collection_repo"],
            "collection_base_sha": descriptor["collection_base_sha"],
            "owning_repo": descriptor["owning_repo"],
            "owning_repo_base_sha": descriptor["owning_repo_base_sha"],
            "owning_repo_rel": descriptor["owning_repo_rel"], "branch": descriptor["branch"],
            "container_id": None, "container_name": container_name,
            "source_volume": source_volume, "state_volume": state_volume,
            "host_port": None, "container_port": descriptor["container_port"],
            "image": image, "image_digest": None, "runner_version": __version__,
            "descriptor": descriptor,
        })
        provision_args = (
            descriptor, image, container_name, source_volume, state_volume, build_if_missing,
            credentials, feedback_id, dispatch_feedback, agent_network, agent_sandbox,
            agent_adapter, agent_model, agent_autonomy, wait,
        )
        if background:
            thread = threading.Thread(
                target=self._provision,
                args=provision_args,
                kwargs={"raise_errors": False},
                name=f"curiator-workspace-{descriptor['id']}",
                daemon=True,
            )
            thread.start()
            return row
        return self._provision(*provision_args, raise_errors=True)

    def _provision(self, descriptor: dict, image: str, container_name: str,
                   source_volume: str, state_volume: str, build_if_missing: bool,
                   credentials: str, feedback_id: str | None, dispatch_feedback: bool,
                   agent_network: bool, agent_sandbox: str, agent_adapter: str | None,
                   agent_model: str | None, agent_autonomy: str | None, wait: bool,
                   *, raise_errors: bool) -> dict:
        container_id = None
        host_port = None
        try:
            runtime = self.docker.runtime()
            if runtime.get("unsafe_socket_inside_container"):
                raise WorkspaceError(
                    "workspace creation refused: the control plane is inside a collection container with "
                    "the host Docker socket mounted"
                )
            if runtime.get("daemon_available") is not True:
                raise WorkspaceError(runtime.get("daemon_reason") or "Docker daemon unavailable")
            workspace_store.update(self.cfg, descriptor["id"], status="building")
            workspace_store.event(self.cfg, descriptor["id"], "building", {"image": image})
            image_info = self.ensure_image(image, build_if_missing=build_if_missing)
            self._volume(descriptor["id"], source_volume, "source")
            self._volume(descriptor["id"], state_volume, "state")
            for dependency in descriptor.get("dependency_repositories") or []:
                self._volume(descriptor["id"], dependency["volume"], "dependency")
            self._initialize_volumes(descriptor, image, source_volume, state_volume)
            self._write_meta(workspace_store.get(self.cfg, descriptor["id"]) or {})
            self._bootstrap_source(descriptor, image, source_volume, state_volume)
            if feedback_id:
                self._seed_feedback(
                    descriptor, image, source_volume, state_volume, feedback_id, dispatch=dispatch_feedback
                )
            self._stage_credentials(credentials, image, state_volume)
            container_id = self._create_container(
                descriptor, image, container_name, source_volume, state_volume, credentials,
                agent_network, agent_sandbox, agent_adapter, agent_model, agent_autonomy,
            )
            self.docker.run("start", container_name, timeout=120)
            host_port = self._host_port(container_name, descriptor["container_port"])
            if wait:
                self._wait_http(host_port)
            row = workspace_store.update(
                self.cfg, descriptor["id"], status="running", container_id=container_id,
                host_port=host_port, image_digest=image_info.get("Id") or image_info.get("ID"),
                failure_reason=None,
            )
            workspace_store.event(self.cfg, descriptor["id"], "running", {"host_port": host_port})
            return row
        except (Exception, KeyboardInterrupt) as exc:
            detail = "workspace creation interrupted" if isinstance(exc, KeyboardInterrupt) else str(exc)
            workspace_store.update(
                self.cfg, descriptor["id"], status="failed", failure_reason=detail,
                container_id=container_id, host_port=host_port,
            )
            workspace_store.event(self.cfg, descriptor["id"], "failed", {"error": detail})
            if not raise_errors:
                return workspace_store.get(self.cfg, descriptor["id"]) or {}
            if isinstance(exc, KeyboardInterrupt):
                raise
            if isinstance(exc, WorkspaceError):
                raise
            raise WorkspaceError(str(exc)) from exc

    def get(self, workspace_id: str) -> dict:
        row = workspace_store.get(self.cfg, workspace_id)
        if not row:
            raise WorkspaceError(f"unknown workspace {workspace_id!r}")
        return row

    def reconcile(self) -> list[dict]:
        rows = workspace_store.list_all(self.cfg)
        for row in rows:
            if row["status"] in {"deleted", "preserved"}:
                continue
            info = self.docker.inspect("container", row["container_name"])
            if not info:
                if row["status"] not in {"creating", "building", "failed"}:
                    workspace_store.update(
                        self.cfg, row["id"], status="failed", failure_reason="managed container is missing"
                    )
                continue
            state = info.get("State") or {}
            running = bool(state.get("Running") or str(state.get("Status", "")).lower() == "running")
            target = "running" if running else "stopped"
            if row["status"] != target and row["status"] not in {"creating", "building", "failed"}:
                workspace_store.update(self.cfg, row["id"], status=target)
        return workspace_store.list_all(self.cfg)

    def list(self, *, include_deleted: bool = False) -> list[dict]:
        self.reconcile()
        return workspace_store.list_all(self.cfg, include_deleted=include_deleted)

    def start(self, workspace_id: str) -> dict:
        row = self.get(workspace_id)
        self.docker.run("start", row["container_name"], timeout=120)
        port = self._host_port(row["container_name"], row["container_port"])
        self._wait_http(port)
        workspace_store.event(self.cfg, workspace_id, "started", {"host_port": port})
        return workspace_store.update(self.cfg, workspace_id, status="running", host_port=port, failure_reason=None)

    def stop(self, workspace_id: str) -> dict:
        row = self.get(workspace_id)
        self.docker.run("stop", "--time", "15", row["container_name"], timeout=60)
        workspace_store.event(self.cfg, workspace_id, "stopped")
        return workspace_store.update(self.cfg, workspace_id, status="stopped")

    def open_url(self, workspace_id: str) -> str:
        row = self.get(workspace_id)
        if not row.get("host_port"):
            raise WorkspaceError(f"workspace {workspace_id} has no allocated host port")
        return f"http://127.0.0.1:{row['host_port']}/?app={row['app_key']}"

    @staticmethod
    def _workspace_repo(row: dict) -> str:
        rel = row.get("owning_repo_rel")
        return "/workspace/source" if not rel else f"/workspace/source/{rel}"

    def _volume_exec(self, row: dict, *cmd: str, user: str = "1000:1000",
                     extra: list[str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        args = [
            "run", "--rm", "--user", user,
            "--security-opt", "label=disable",
            "--mount", f"type=volume,source={row['source_volume']},target=/workspace/source",
            "--mount", f"type=volume,source={row['state_volume']},target=/workspace/state",
            *(extra or []), row["image"], *cmd,
        ]
        return self.docker.run(*args, check=check, timeout=300)

    def diff(self, workspace_id: str) -> dict:
        row = self.get(workspace_id)
        repo = self._workspace_repo(row)
        base = row["owning_repo_base_sha"]
        status = self._volume_exec(row, "git", "-C", repo, "status", "--porcelain=v1").stdout
        commits = self._volume_exec(row, "git", "-C", repo, "log", "--oneline", f"{base}..HEAD").stdout
        patch = self._volume_exec(row, "git", "-C", repo, "diff", "--binary", base).stdout
        return {
            "id": workspace_id,
            "base_sha": base,
            "branch": row.get("branch"),
            "dirty": bool(status.strip()),
            "status": status,
            "commits": [line for line in commits.splitlines() if line],
            "patch": patch,
        }

    def start_editing(self, workspace_id: str, branch: str | None = None) -> dict:
        row = self.get(workspace_id)
        if row["mode"] != "preview":
            raise WorkspaceError(f"workspace {workspace_id} is already editable")
        branch = branch or f"curiator/workspace/{row['name']}-{workspace_id[:6]}"
        repo = self._workspace_repo(row)
        self._volume_exec(row, "git", "-C", repo, "switch", "-c", branch, row["owning_repo_base_sha"])
        descriptor = dict(row.get("descriptor") or {})
        descriptor.update({"mode": "branch", "branch": branch})
        workspace_store.event(self.cfg, workspace_id, "editing", {"branch": branch})
        updated = workspace_store.update(
            self.cfg, workspace_id, mode="branch", branch=branch, descriptor=descriptor
        )
        self._write_meta(updated)
        return updated

    def keep(self, workspace_id: str, branch: str | None = None) -> dict:
        row = self.get(workspace_id)
        if row["mode"] != "branch" or not row.get("branch"):
            raise WorkspaceError("preview workspace must use `workspace edit` before it can be kept")
        comparison = self.diff(workspace_id)
        if comparison["dirty"]:
            raise WorkspaceError("workspace has uncommitted source; commit it before keeping the branch")
        destination = branch or row["branch"]
        owning = Path(row["owning_repo"])
        result = _run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{destination}"],
            cwd=owning, check=False,
        )
        if result.returncode == 0:
            raise WorkspaceError(f"canonical branch already exists: {destination}")
        repo = self._workspace_repo(row)
        with tempfile.TemporaryDirectory(prefix="curiator-workspace-bundle-") as temp:
            export = Path(temp)
            os.chmod(export, 0o777)
            extra = ["--volume", f"{export}:/export"]
            self._volume_exec(
                row, "git", "-C", repo, "bundle", "create", "/export/workspace.bundle",
                f"refs/heads/{row['branch']}", extra=extra,
            )
            bundle = export / "workspace.bundle"
            if not bundle.exists():
                raise WorkspaceError("workspace bundle export did not produce an artifact")
            _run([
                "git", "fetch", str(bundle),
                f"refs/heads/{row['branch']}:refs/heads/{destination}",
            ], cwd=owning)
        workspace_store.event(self.cfg, workspace_id, "preserved", {"ref": destination})
        return workspace_store.update(
            self.cfg, workspace_id, status="preserved", preserved_ref=destination,
            promoted_at=workspace_store.now(),
        )

    def apply(self, workspace_id: str) -> dict:
        """Fast-forward an explicitly preserved workspace branch into its canonical checkout.

        This is intentionally stricter than a merge: canonical HEAD and every path changed by the
        workspace must still match the immutable base. Unrelated staged and unstaged files are left
        untouched.
        """
        row = self.get(workspace_id)
        preserved = row.get("preserved_ref")
        if not preserved:
            raise WorkspaceError("keep the workspace branch before applying it to the canonical checkout")
        owning = Path(row["owning_repo"])
        base = row["owning_repo_base_sha"]
        target_result = _run(
            ["git", "rev-parse", "--verify", f"refs/heads/{preserved}^{{commit}}"],
            cwd=owning, check=False,
        )
        if target_result.returncode:
            raise WorkspaceError(f"preserved canonical branch is missing: {preserved}")
        target = target_result.stdout.strip()
        head = _git(owning, "rev-parse", "HEAD")
        if head != base:
            raise WorkspaceError(
                f"canonical baseline moved: expected {base[:12]}, found {head[:12]}; rebase or create a new workspace"
            )
        if target == base:
            raise WorkspaceError("preserved workspace branch has no commits to apply")
        ancestor = _run(["git", "merge-base", "--is-ancestor", base, target], cwd=owning, check=False)
        if ancestor.returncode:
            raise WorkspaceError("preserved workspace branch is not a descendant of its recorded base")
        branch_result = _run(["git", "symbolic-ref", "-q", "HEAD"], cwd=owning, check=False)
        if branch_result.returncode:
            raise WorkspaceError("canonical checkout is detached; switch to the target branch before applying")
        canonical_ref = branch_result.stdout.strip()
        changed_result = _run(
            ["git", "diff", "--name-only", "--no-renames", "-z", base, target], cwd=owning,
        )
        changed = [path for path in changed_result.stdout.split("\0") if path]
        if not changed:
            raise WorkspaceError("preserved workspace commits do not change source files")
        dirty = _run(
            ["git", "status", "--porcelain=v1", "-z", "--", *changed], cwd=owning,
        ).stdout
        if dirty:
            raise WorkspaceError(
                "canonical files changed since the workspace baseline: " + ", ".join(changed)
            )

        restore_target = ["git", "restore", "--source", target, "--staged", "--worktree", "--", *changed]
        restore_base = ["git", "restore", "--source", base, "--staged", "--worktree", "--", *changed]
        restored = _run(restore_target, cwd=owning, check=False)
        if restored.returncode:
            _run(restore_base, cwd=owning, check=False)
            detail = (restored.stderr or restored.stdout).strip()
            raise WorkspaceError(f"accepted workspace files could not be applied: {detail or 'git restore failed'}")
        moved = _run(["git", "update-ref", canonical_ref, target, base], cwd=owning, check=False)
        if moved.returncode:
            _run(restore_base, cwd=owning, check=False)
            detail = (moved.stderr or moved.stdout).strip()
            raise WorkspaceError(f"canonical branch changed during apply: {detail or 'atomic ref update failed'}")
        remaining = _run(
            ["git", "status", "--porcelain=v1", "-z", "--", *changed], cwd=owning,
        ).stdout
        if remaining:
            raise WorkspaceError("canonical ref advanced but accepted paths are not clean; inspect the checkout")
        workspace_store.event(
            self.cfg, workspace_id, "applied",
            {"canonical_ref": canonical_ref, "commit": target, "paths": changed},
        )
        descriptor = dict(row.get("descriptor") or {})
        descriptor["applied_commit"] = target
        descriptor["applied_ref"] = canonical_ref
        return workspace_store.update(
            self.cfg, workspace_id, status="applied", descriptor=descriptor,
            promoted_at=workspace_store.now(), failure_reason=None,
        )

    def delete(self, workspace_id: str, *, force: bool = False) -> dict:
        row = self.get(workspace_id)
        comparison = (
            {"dirty": False, "commits": []}
            if force and row["status"] in {"creating", "building", "failed"}
            else self.diff(workspace_id)
        )
        unexported = bool(comparison["commits"] and not row.get("preserved_ref"))
        if not force and (comparison["dirty"] or unexported):
            reasons = []
            if comparison["dirty"]:
                reasons.append("uncommitted source")
            if unexported:
                reasons.append("commits not preserved in the canonical repo")
            raise WorkspaceError(
                f"refusing to delete {workspace_id}: {', '.join(reasons)}; keep it or pass --force"
            )
        workspace_store.update(self.cfg, workspace_id, status="deleting")
        workspace_store.event(
            self.cfg, workspace_id, "deleting", {"force": force, "dirty": comparison["dirty"], "unexported": unexported}
        )
        self.docker.run("rm", "--force", row["container_name"], check=False, timeout=60)
        self.docker.run("volume", "rm", "--force", row["source_volume"], check=False, timeout=60)
        self.docker.run("volume", "rm", "--force", row["state_volume"], check=False, timeout=60)
        for dependency in (row.get("descriptor") or {}).get("dependency_repositories") or []:
            if dependency.get("volume"):
                self.docker.run("volume", "rm", "--force", dependency["volume"], check=False, timeout=60)
        workspace_store.event(self.cfg, workspace_id, "deleted", {"force": force})
        deleted = workspace_store.update(
            self.cfg, workspace_id, status="deleted", container_id=None, host_port=None,
        )
        workspace_store.compact_deleted(self.cfg)
        return workspace_store.get(self.cfg, workspace_id) or deleted

    def logs(self, workspace_id: str, *, tail: int = 200) -> str:
        row = self.get(workspace_id)
        if self.docker.inspect("container", row["container_name"]):
            result = self.docker.run("logs", "--tail", str(tail), row["container_name"], check=False)
            return result.stdout + result.stderr
        result = self._volume_exec(
            row, "tail", "-n", str(max(1, tail)), "/workspace/state/workspace-bootstrap.log", check=False,
        )
        if result.returncode:
            return f"curiator: no workspace log is available yet ({row['status']})\n"
        return result.stdout + result.stderr

    def feedback(self, workspace_id: str, *, app: str | None = None) -> list[dict]:
        row = self.get(workspace_id)
        descriptor = row.get("descriptor") or {}
        gallery = f"/workspace/source/{descriptor.get('gallery_rel') or 'gallery.yaml'}"
        key = app or row["app_key"]
        result = self.docker.run(
            "exec", row["container_name"],
            "curiator", "--gallery", gallery, "--state-dir", "/workspace/state",
            "--workspace-mode", "feedback", "dump", key,
            timeout=60,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise WorkspaceError(f"workspace feedback did not return JSON: {result.stdout[-500:]}") from exc
        return payload if isinstance(payload, list) else []

    def wait_feedback(self, workspace_id: str, feedback_id: str, *, timeout: float = 900) -> dict:
        deadline = time.monotonic() + max(1, timeout)
        last = None
        while time.monotonic() < deadline:
            entries = self.feedback(workspace_id)
            last = next((entry for entry in entries if entry.get("id") == feedback_id), None)
            if last and last.get("status") not in {"new", "working"}:
                return last
            time.sleep(2)
        raise WorkspaceError(
            f"workspace feedback {feedback_id} did not finish within {timeout:g}s "
            f"(last status: {(last or {}).get('status') or 'missing'})"
        )

    def state_file(self, workspace_id: str, relative_path: str) -> bytes | None:
        row = self.get(workspace_id)
        rel = str(relative_path or "").lstrip("/")
        if not rel or ".." in Path(rel).parts:
            raise WorkspaceError("workspace state path must be a safe relative path")
        result = self.docker.run(
            "exec", row["container_name"], "base64", "-w", "0", f"/workspace/state/{rel}",
            check=False, timeout=60,
        )
        if result.returncode:
            return None
        try:
            return base64.b64decode(result.stdout, validate=True)
        except (ValueError, TypeError) as exc:
            raise WorkspaceError(f"workspace state file {rel!r} did not return valid base64") from exc

    def smoke(self, workspace_id: str, *, app: str | None = None, browser: bool = True) -> dict:
        row = self.get(workspace_id)
        descriptor = row.get("descriptor") or {}
        gallery = f"/workspace/source/{descriptor.get('gallery_rel') or 'gallery.yaml'}"
        artifact_dir = f"/workspace/state/replies/workspace-{workspace_id}-browser-smoke"
        output = f"{artifact_dir}/result.json"
        args = [
            "exec", row["container_name"],
            "curiator", "--gallery", gallery, "--state-dir", "/workspace/state",
            "--workspace-mode", "smoke",
        ]
        if app:
            args += ["--app", app]
        if browser:
            args += ["--browser", "--artifact-dir", artifact_dir, "--output", output]
        args += ["--json"]
        result = self.docker.run(*args, timeout=300)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise WorkspaceError(f"workspace smoke did not return JSON: {result.stdout[-500:]}") from exc
        workspace_store.event(self.cfg, workspace_id, "smoke", {"ok": payload.get("ok"), "browser": browser})
        return payload
