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
    raise SystemExit("CurIAtor needs PyYAML — `pip install pyyaml`.") from e


def find_gallery() -> Path:
    env = os.environ.get("CURIATOR_GALLERY")
    if env:
        return Path(env)
    cwd = Path.cwd() / "gallery.yaml"
    if cwd.exists():
        return cwd
    # repo-root fallback (this file is curiator/config.py)
    return Path(__file__).resolve().parents[1] / "gallery.yaml"


def load_config() -> dict:
    p = find_gallery()
    if not p.exists():
        raise SystemExit(f"CurIAtor: no gallery.yaml found (looked at {p}). See docs/DESIGN.md.")
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
    git.setdefault("include_ledger", True)       # bundle the feedback ledger in the same commit
    cfg["git"] = git
    # Identity / provenance (docs: who gave each piece of feedback). Additive: absent ⇒ mode none
    # (a fixed default_user — provenance even solo, today's anonymous single-tenant behavior).
    auth = cfg.get("auth") or {}
    auth.setdefault("mode", "none")              # none | header | oidc
    auth.setdefault("default_user", "anonymous@local")
    cfg["auth"] = auth
    return cfg
