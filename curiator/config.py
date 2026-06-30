"""config.py — load gallery.yaml into the cfg dict the loop/adapters/ledger consume.

Lightweight (doesn't import the shell or touch sys.path) so the loop can load config cheaply.
Resolution: $CURIATOR_GALLERY, else <cwd>/gallery.yaml, else the packaged default.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise SystemExit("curIAtor needs PyYAML — `pip install pyyaml`.") from e


def find_gallery() -> Path:
    env = os.environ.get("CURIATOR_GALLERY")
    if env:
        return Path(env)
    cwd = Path.cwd().resolve()
    for base in (cwd, *cwd.parents):
        candidate = base / "gallery.yaml"
        if candidate.exists():
            return candidate
    # repo-root fallback (this file is curiator/config.py)
    return Path(__file__).resolve().parents[1] / "gallery.yaml"


def load_config() -> dict:
    p = find_gallery()
    if not p.exists():
        raise SystemExit(f"curIAtor: no gallery.yaml found (looked at {p}). See docs/DESIGN.md.")
    cfg = yaml.safe_load(p.read_text()) or {}
    cfg["repo_root"] = str(p.resolve().parent)   # everything (feedback/, sources) is relative to here
    cfg["gallery_path"] = str(p.resolve())
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
    # local-login user store (hashed passwords) — resolved against the collection root; gitignored
    auth["users_file"] = str(Path(cfg["repo_root"]) / auth.get("users_file", ".curiator-users.json"))
    cfg["auth"] = auth
    return cfg


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
