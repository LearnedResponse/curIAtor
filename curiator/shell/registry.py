"""registry.py — gallery.yaml → the app registry the shell consumes.

This exposes `ALL_APPS` (a flat list of app dicts) and `TAG_META` for the
legacy Dash-compatible shell, sourced from declarative `gallery.yaml` entries.

It also registers each app's source directory on `sys.path` so the shell's in-process Dash
mount (`importlib.import_module(<module>)`) can find the demo apps under `examples/dash/`.

CONFIG RESOLUTION: internal `$CURIATOR_GALLERY` pin from the parent CLI process, else
`<repo_root>/gallery.yaml`. User-facing commands should prefer `curiator --gallery ...`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise SystemExit("curIAtor needs PyYAML — `pip install pyyaml` (or `pip install curiator`).") from e

# the gallery.yaml schema logic lives in config.py; the shell loads this file as a TOP-LEVEL module
# (the old `import registry` seam), so fall back to the absolute import when there's no parent package
try:
    from ..config import mount_entries as _mount_entries
except ImportError:  # pragma: no cover — top-level `import registry`
    from curiator.config import mount_entries as _mount_entries

PACKAGE_ROOT = Path(__file__).resolve().parents[2]   # the curiator package/checkout root (NOT the collection)
GALLERY_YAML = Path(os.environ.get("CURIATOR_GALLERY", PACKAGE_ROOT / "gallery.yaml"))
# The collection root = the directory holding gallery.yaml. App `source:` paths and the feedback/ ledger
# resolve against THIS — so a separate collection (`curiator init`, the Docker /collection mount) works,
# not just the demo repo. Matches config.py's cfg['repo_root']; for the demo repo the two coincide.
COLLECTION_ROOT = GALLERY_YAML.resolve().parent
REPO_ROOT = COLLECTION_ROOT                          # back-compat alias (app_shell feedback dir + source resolution)

_DEFAULT_PORT_BASE = 8201   # reference IDs only (mounts are in-process, no real port is bound)


def _load_yaml() -> dict:
    if not GALLERY_YAML.exists():
        raise SystemExit(f"curIAtor: no gallery config at {GALLERY_YAML} "
                         f"(run `curiator --gallery <path> up` or create gallery.yaml — see docs/DESIGN.md).")
    return yaml.safe_load(GALLERY_YAML.read_text()) or {}


CONFIG = _load_yaml()
AGENT = CONFIG.get("agent", {}) or {}
FEEDBACK_CFG = CONFIG.get("feedback", {}) or {}
SHELL_CFG = CONFIG.get("shell", {}) or {}
AUTH_CFG = CONFIG.get("auth", {}) or {}        # identity / provenance (none | header | oidc | local)
AUTH_CFG.setdefault("mode", "none")
AUTH_CFG["users_file"] = str(COLLECTION_ROOT / AUTH_CFG.get("users_file", ".curiator-users.json"))
VOICE_CFG = CONFIG.get("voice", {}) or {}
VOICE_CFG.setdefault("transcribe_cmd", None)
VOICE_CFG.setdefault("transcribe_timeout", 60)
VOICE_CFG.setdefault("transcribe_max_bytes", 25 * 1024 * 1024)
VOICE_CFG.setdefault("web_speech", False)
VOICE_CFG.setdefault("web_speech_lang", None)
VOICE_CFG.setdefault("retain_audio", False)

# the directories that hold app source — added to sys.path so in-process import works.
APP_SOURCE_DIRS: list[Path] = []


def _resolve_path(base: Path, value: str | None) -> Path | None:
    if not value:
        return None
    p = Path(value)
    return p if p.is_absolute() else (base / p).resolve()




def _build_all_apps() -> list[dict]:
    apps = []
    ordinal = 0
    for a in CONFIG.get("apps", []) or []:
        base_name = a["name"]
        root = _resolve_path(COLLECTION_ROOT, a.get("root")) or COLLECTION_ROOT
        for name, mount in _mount_entries(a):
            source = mount.get("source", a.get("source", "." if a.get("root") else None))
            source_base = root if a.get("root") else COLLECTION_ROOT
            src_path = _resolve_path(source_base, source)
            if src_path:
                syspath = src_path if src_path.is_dir() else src_path.parent
                if syspath not in APP_SOURCE_DIRS:
                    APP_SOURCE_DIRS.append(syspath)
            if root not in APP_SOURCE_DIRS:
                APP_SOURCE_DIRS.append(root)
            if COLLECTION_ROOT not in APP_SOURCE_DIRS:
                APP_SOURCE_DIRS.append(COLLECTION_ROOT)
            port = mount.get("port", a.get("port", _DEFAULT_PORT_BASE + ordinal))
            title = mount.get("title", a.get("title", name.replace("_", " ")))
            tags = list(mount.get("tags", a.get("tags") or []))
            color = mount.get("color", a.get("color", "#888"))
            key = name
            ordinal += 1
            smoke = mount.get("smoke", a.get("smoke"))
            cmd = mount.get("cmd")
            if cmd and port is not None:
                mount["cmd"] = str(cmd).format(port=port, root=str(root), app=key)
            mount.setdefault("kind", "dash-inproc")
            if mount.get("kind") == "dash-inproc":
                mount.setdefault("module", key)
            if port is not None:
                mount["port"] = port
            apps.append({
                # the shell reads these keys (see app_shell.load_registry):
                "key": key,
                "file": str(src_path) if src_path else None,  # absolute source path
                "port": port,  # reference id for dash-inproc; real target for proxy
                "title": title,
                "tags": tags,
                "color": color,
                # extra (curIAtor-native) fields the generalized shell/loop use:
                "name": key,
                "base_name": base_name,
                "mount": mount,
                "root": str(root),
                "source": str(src_path) if src_path else None,
                "smoke": smoke,
            })
    # make demo apps importable for the in-process Dash mount
    for d in APP_SOURCE_DIRS:
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))
    return apps


ALL_APPS = _build_all_apps()

# tag → color, for the catalog chips (optional; app_shell does getattr(REG, "TAG_META", []))
TAG_META = list((CONFIG.get("tags") or {}).items())

# curIAtor-native exports the generalized shell + loop consume:
APPS_ROOT = APP_SOURCE_DIRS[0] if APP_SOURCE_DIRS else REPO_ROOT   # primary source dir
BY_NAME = {a["name"]: a for a in ALL_APPS}
