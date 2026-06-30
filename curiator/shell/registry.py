"""registry.py — gallery.yaml → the app registry the shell consumes.

Drop-in replacement for the research repo's `all_apps_index` module: it exposes the same
`ALL_APPS` (a flat list of app dicts) and `TAG_META` that `app_shell.load_registry()` reads,
but sourced from a declarative `gallery.yaml` instead of a hand-maintained Python list.

It also registers each app's source directory on `sys.path` so the shell's in-process Dash
mount (`importlib.import_module(<module>)`) can find the demo apps under `examples/dash/`.

CONFIG RESOLUTION: `$CURIATOR_GALLERY`, else `<repo_root>/gallery.yaml`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise SystemExit("CurIAtor needs PyYAML — `pip install pyyaml` (or `pip install curiator`).") from e

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
        raise SystemExit(f"CurIAtor: no gallery config at {GALLERY_YAML} "
                         f"(set $CURIATOR_GALLERY or create gallery.yaml — see docs/DESIGN.md).")
    return yaml.safe_load(GALLERY_YAML.read_text()) or {}


CONFIG = _load_yaml()
AGENT = CONFIG.get("agent", {}) or {}
FEEDBACK_CFG = CONFIG.get("feedback", {}) or {}
SHELL_CFG = CONFIG.get("shell", {}) or {}
AUTH_CFG = CONFIG.get("auth", {}) or {}        # identity / provenance (none | header | oidc | local)
AUTH_CFG.setdefault("mode", "none")
AUTH_CFG["users_file"] = str(COLLECTION_ROOT / AUTH_CFG.get("users_file", ".curiator-users.json"))

# the directories that hold app source — added to sys.path so in-process import works.
APP_SOURCE_DIRS: list[Path] = []


def _build_all_apps() -> list[dict]:
    apps = []
    for i, a in enumerate(CONFIG.get("apps", []) or []):
        name = a["name"]
        mount = a.get("mount", {}) or {}
        source = a.get("source")
        src_path = (COLLECTION_ROOT / source).resolve() if source else None
        if src_path and src_path.parent not in APP_SOURCE_DIRS:
            APP_SOURCE_DIRS.append(src_path.parent)
        apps.append({
            # the shell reads these keys (see app_shell.load_registry):
            "key": mount.get("module", name),            # the import name for dash-inproc mount
            "file": str(src_path) if src_path else None,  # absolute source path (M1: shell must resolve abs paths)
            "port": a.get("port", _DEFAULT_PORT_BASE + i),  # reference id only
            "title": a.get("title", name.replace("_", " ")),
            "tags": list(a.get("tags") or []),
            "color": a.get("color", "#888"),
            # extra (CurIAtor-native) fields the generalized shell/loop use:
            "name": name,
            "mount": mount,
            "source": str(src_path) if src_path else None,
        })
    # make demo apps importable for the in-process Dash mount
    for d in APP_SOURCE_DIRS:
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))
    return apps


ALL_APPS = _build_all_apps()

# tag → color, for the catalog chips (optional; app_shell does getattr(REG, "TAG_META", []))
TAG_META = list((CONFIG.get("tags") or {}).items())

# CurIAtor-native exports the generalized shell + loop consume:
APPS_ROOT = APP_SOURCE_DIRS[0] if APP_SOURCE_DIRS else REPO_ROOT   # primary source dir
BY_NAME = {a["name"]: a for a in ALL_APPS}
