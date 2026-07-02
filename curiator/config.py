"""config.py — load gallery.yaml into the cfg dict the loop/adapters/ledger consume.

Lightweight (doesn't import the shell or touch sys.path) so the loop can load config cheaply.
Resolution: $CURIATOR_GALLERY, else <cwd>/gallery.yaml, else a `.curiator/app.yaml` link,
else the packaged default.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise SystemExit("curIAtor needs PyYAML — `pip install pyyaml`.") from e


LINK_REL = Path(".curiator") / "app.yaml"


def find_link(start: Path | None = None) -> Path | None:
    """Find a local app→gallery link written by `curiator link`."""
    cwd = (start or Path.cwd()).resolve()
    for base in (cwd, *cwd.parents):
        candidate = base / LINK_REL
        if candidate.exists():
            return candidate
    return None


def load_link(start: Path | None = None) -> dict:
    p = find_link(start)
    if not p:
        return {}
    data = yaml.safe_load(p.read_text()) or {}
    if not isinstance(data, dict):
        return {}
    data["_path"] = str(p.resolve())
    return data


def find_gallery() -> Path:
    env = os.environ.get("CURIATOR_GALLERY")
    if env:
        return Path(env)
    cwd = Path.cwd().resolve()
    for base in (cwd, *cwd.parents):
        candidate = base / "gallery.yaml"
        if candidate.exists():
            return candidate
    link = load_link(cwd)
    gallery = link.get("gallery") or link.get("gallery_path")
    if gallery:
        gp = Path(gallery)
        if gp.is_absolute():
            return gp
        link_path = Path(link["_path"])
        return (link_path.parent.parent / gp).resolve()
    # repo-root fallback (this file is curiator/config.py)
    return Path(__file__).resolve().parents[1] / "gallery.yaml"


def _gallery_file(path: str | Path) -> Path:
    p = Path(path).expanduser()
    return p / "gallery.yaml" if p.is_dir() else p


def _load_config_from_path(path: str | Path, *, link: dict | None = None) -> dict:
    p = _gallery_file(path)
    if not p.exists():
        raise SystemExit(f"curIAtor: no gallery.yaml found (looked at {p}). See docs/DESIGN.md.")
    cfg = yaml.safe_load(p.read_text()) or {}
    cfg["repo_root"] = str(p.resolve().parent)   # everything (feedback/, sources) is relative to here
    cfg["gallery_path"] = str(p.resolve())
    link = link or {}
    if link:
        cfg["link"] = {k: v for k, v in link.items() if not k.startswith("_")}
        cfg["link_path"] = link["_path"]
    # How General-channel feedback on the RUNNER itself is handled. Additive + backward-compatible:
    # absent `runner:` ⇒ pinned (the safe consumer default — drafts an upstream PR, never edits the package).
    runner = cfg.get("runner") or {}
    runner.setdefault("mode", "pinned")          # pinned | checkout
    cfg["runner"] = runner
    # Git-as-memory policy (docs/DESIGN.md → "Git as the memory"). Additive + backward-compatible:
    # absent/`commit:false` ⇒ today's leave-uncommitted behavior. `commit:true` ⇒ one commit per run.
    git = cfg.get("git") or {}
    git.setdefault("commit", False)              # false = leave uncommitted | true = git-as-memory
    git.setdefault("branch", "curiator/auto")    # sandbox/env branch (empty/null ⇒ current HEAD)
    git.setdefault("signoff", True)              # add Signed-off-by (DCO) via `git commit -s`
    git.setdefault("include_ledger", False)      # opt in to bundling the SQLite ledger in commits
    cfg["git"] = git
    # Identity / provenance (docs: who gave each piece of feedback). Additive: absent ⇒ mode none
    # (a fixed default_user — provenance even solo, today's anonymous single-tenant behavior).
    auth = cfg.get("auth") or {}
    auth.setdefault("mode", "none")              # none | header | oidc | local
    auth.setdefault("default_user", "anonymous@local")
    auth.setdefault("admin_groups", ["admin"])   # groups that may change agent settings (mode != none)
    auth.setdefault("anonymous_feedback_max", 20)
    auth.setdefault("anonymous_feedback_window_seconds", 86400)
    # local-login user store (hashed passwords) — resolved against the collection root; gitignored
    auth["users_file"] = str(Path(cfg["repo_root"]) / auth.get("users_file", ".curiator-users.json"))
    cfg["auth"] = auth
    cfg["current_app"] = (link.get("app") if link else None) or infer_current_app(cfg)
    return cfg


def load_config() -> dict:
    return _load_config_from_path(find_gallery(), link=load_link())


def load_config_at(path: str | Path) -> dict:
    """Load an explicit gallery path or collection directory without consulting local app links."""
    return _load_config_from_path(path, link={})


def _resolve(base: Path, value: str | None) -> Path | None:
    if not value:
        return None
    p = Path(value)
    return p if p.is_absolute() else (base / p).resolve()


# ── the ONE home of `gallery.yaml` app/mount normalization ──
# The shell registry, the loop adapters, gitmem, and the CLI all consume these helpers. The schema
# semantics (mount/mounts merge, root/source resolution) live HERE — don't re-derive them per consumer.
MOUNT_MERGE_KEYS = (
    "source", "title", "tags", "color", "smoke", "smoke_timeout", "smoke_http", "cwd", "port", "cmd"
)


def mount_entries(app_cfg: dict) -> list[tuple[str, dict]]:
    """A config item is one endpoint (`mount:`) or several endpoints (`mounts:`) sharing a root.
    Returns (name, mount) pairs with app-level keys merged down into each mount."""
    if app_cfg.get("mounts"):
        out = []
        for m in app_cfg.get("mounts") or []:
            mount = dict(m.get("mount") or m)
            if m.get("mount"):
                for k in MOUNT_MERGE_KEYS:
                    if k in m and k not in mount:
                        mount[k] = m[k]
            name = m.get("name") or mount.get("name") or app_cfg.get("name")
            out.append((name, mount))
        return out
    return [(app_cfg.get("name"), dict(app_cfg.get("mount") or {}))]


def app_specs(cfg: dict) -> list[dict]:
    """Normalized endpoint metadata for every configured app/mount entry (paths as absolute strings)."""
    repo = Path(cfg.get("repo_root", ".")).resolve()
    specs: list[dict] = []
    for a in (cfg.get("apps") or []):
        root = _resolve(repo, a.get("root")) or repo
        for name, mount in mount_entries(a):
            source = mount.get("source", a.get("source", "." if a.get("root") else None))
            source_base = root if a.get("root") else repo
            specs.append({
                "name": name,
                "app_name": a.get("name"),
                "root": str(root),
                "source": str(_resolve(source_base, source) or root),
                "smoke": mount.get("smoke", a.get("smoke")),
                "smoke_timeout": mount.get("smoke_timeout", a.get("smoke_timeout")),
                "smoke_http": mount.get("smoke_http", a.get("smoke_http")),
                "commands": mount.get("commands", a.get("commands") or {}),
                "module": mount.get("module"),
                "mount": mount,
            })
    return specs


def app_spec(cfg: dict, key: str) -> dict | None:
    """The normalized spec for one app key (matched by mount name, app name, or module)."""
    for spec in app_specs(cfg):
        if key in {spec["name"], spec["app_name"], spec["module"]}:
            return spec
    return None


def infer_current_app(cfg: dict, cwd: Path | None = None) -> str | None:
    """Best-effort app inference for commands run inside a collection/app tree. Ambiguity — several
    apps scoring the same, e.g. the collection root where every rootless app ties — returns None, so
    callers ask for an explicit --app instead of silently picking the first app in the gallery."""
    here = (cwd or Path.cwd()).resolve()
    scored: list[tuple[int, str]] = []
    for spec in app_specs(cfg):
        name = spec.get("name") or spec.get("app_name") or spec.get("module")
        if not name:
            continue
        score = 0
        for weight, path in ((2, spec.get("source")), (1, spec.get("root"))):
            if not path:
                continue
            p = Path(path).resolve()
            try:
                rel = here.relative_to(p)
            except ValueError:
                continue
            score = max(score, weight * 1000 + len(p.parts) * 10 - len(rel.parts))
        if score:
            scored.append((score, str(name)))
    if not scored:
        return None
    best = max(s for s, _ in scored)
    names = {n for s, n in scored if s == best}
    return names.pop() if len(names) == 1 else None


_AGENT_NAMES = {"headless-cc": "Claude", "codex": "Codex", "api": "Claude"}


def agent_label(cfg: dict) -> str:
    """A human label for the agent that produces ⚙ replies — recorded on each agent message so the
    panel shows WHICH provider answered (Codex vs Claude), not a hardcoded name. Derived from
    agent.adapter (+ model): headless-cc/api → Claude, codex → Codex, command → the cmd's binary."""
    a = (cfg or {}).get("agent", {}) or {}
    adapter = a.get("adapter", "headless-cc")
    if adapter == "command":
        cmd = (a.get("cmd") or "").strip().split()
        base = Path(cmd[0]).name if cmd else "Agent"
    else:
        base = _AGENT_NAMES.get(adapter, adapter)
    model = a.get("model")
    return f"{base} ({model})" if model else base


def _scalar(v) -> str:
    """Render a Python value as a YAML scalar for in-place gallery.yaml edits."""
    if v is None or v == "":
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def set_block_key(text: str, block: str, key: str, value) -> str:
    """Set `<block>.<key>` in a gallery.yaml STRING, preserving comments + the rest of the file. Updates
    the value in place if present (keeping any inline comment), inserts the key under an existing block
    header, or appends a new block. Scalar keys only (the `agent:` knobs the settings page edits — not
    lists/nested maps). The body matcher tolerates blank + comment lines but stops at the next top-level
    key, so it can't bleed into another block."""
    import re
    repl = _scalar(value)
    body = r"(?:(?:[ \t]+[^\n]*)?\n)*?"                      # indented/blank lines, not a col-0 key
    pat = re.compile(rf"(?ms)^({re.escape(block)}:[^\n]*\n{body}[ \t]+{re.escape(key)}:[ \t]*)(\S+)")
    if pat.search(text):
        return pat.sub(lambda m: m.group(1) + repl, text, count=1)
    bpat = re.compile(rf"(?m)^{re.escape(block)}:[^\n]*$")
    if bpat.search(text):
        return bpat.sub(lambda m: m.group(0) + f"\n  {key}: {repl}", text, count=1)
    sep = "" if text.endswith("\n") else "\n"
    return text + f"{sep}\n{block}:\n  {key}: {repl}\n"
