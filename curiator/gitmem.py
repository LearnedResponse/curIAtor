"""gitmem.py — git as the curator's memory.

Every agent run becomes ONE atomic commit that captures the whole state transition — the source edit
(if any) AND the feedback-ledger update (the ⚙ reply + status) ride in the same commit. The git log
then is the durable, queryable, revertible record of every curator action. See docs/DESIGN.md →
"Git as the memory".

Policy comes from gallery.yaml `git:` (config.py fills defaults):
    commit          # false (default) = leave-uncommitted (today's behavior) | true = git-as-memory
    branch          # the sandbox/env branch commits land on (null/empty = current HEAD)
    signoff         # add Signed-off-by (DCO) via `git commit -s`
    include_ledger  # bundle feedback/app_feedback.json in the same commit

Binding practices (enforced here + in task_template.md): one item → one atomic commit; smoke-test
before commit (fail ⇒ revert + report, no commit); structured message + trailers; commit only —
never push/merge/force/rewrite; undo via `revert`, never reset.
"""
from __future__ import annotations

import contextlib
import fcntl
import importlib.util
import re
import subprocess
from pathlib import Path

from . import ledger

_FEEDBACK_TRAILER = "Curiator-Feedback"
_APP_TRAILER = "Curiator-App"


# ───────────────────────────── low-level git ─────────────────────────────
def _git(cfg: dict, *args: str, check: bool = True):
    r = subprocess.run(["git", *args], cwd=cfg["repo_root"], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip()}")
    return r


def is_repo(cfg: dict) -> bool:
    return _git(cfg, "rev-parse", "--git-dir", check=False).returncode == 0


def current_branch(cfg: dict) -> str:
    return _git(cfg, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


@contextlib.contextmanager
def _lock(cfg: dict):
    """Serialize commits/reverts/reflects so concurrent invocations never race the index/ledger."""
    gitdir = Path(cfg["repo_root"]) / ".git"
    if not gitdir.exists():
        yield
        return
    f = open(gitdir / "curiator-commit.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def ensure_branch(cfg: dict, branch: str | None) -> None:
    """Make `branch` current (the sandbox/env branch), carrying uncommitted changes. Empty ⇒ stay on HEAD."""
    if not branch or current_branch(cfg) == branch:
        return
    exists = _git(cfg, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0
    _git(cfg, "checkout", branch) if exists else _git(cfg, "checkout", "-b", branch)


# ───────────────────────────── helpers ─────────────────────────────
def source_for(cfg: dict, app: str) -> str | None:
    """The app's `source:` path (relative to repo root — a git pathspec), or None."""
    for a in (cfg.get("apps") or []):
        if a.get("name") == app or (a.get("mount", {}) or {}).get("module") == app:
            return a.get("source")
    return None


def _ledger_relpath(cfg: dict) -> str:
    return f"{(cfg.get('feedback', {}) or {}).get('dir', 'feedback')}/app_feedback.json"


def smoke_source(path: Path) -> tuple[bool, str]:
    """Import the source and build its app — the same gate the agent runs. (ok, message)."""
    try:
        spec = importlib.util.spec_from_file_location("curiator_smoke", str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "build_app"):
            mod.build_app()
        elif not hasattr(mod, "app"):
            return False, "no build_app() or module-level app"
        return True, "passed"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _path_changed(cfg: dict, rel: str) -> bool:
    return _git(cfg, "diff", "--quiet", "HEAD", "--", rel, check=False).returncode != 0


def _trailers(cfg: dict, sha: str) -> dict:
    body = _git(cfg, "show", "-s", "--format=%B", sha).stdout
    out = {}
    for line in body.splitlines():
        m = re.match(r"^([A-Za-z][A-Za-z-]+):\s*(.+)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def _agent_label(cfg: dict) -> str:
    agent = cfg.get("agent", {}) or {}
    return str(agent.get("model") or agent.get("adapter") or "headless-cc")


def _build_message(app, summary, comment, stars, changed_desc, smoke) -> str:
    star = ("★" * int(stars)) if stars else "—"
    return (
        f"curator({app}): {summary}\n\n"
        f'Feedback: "{(comment or "").strip()}"   ({star})\n'
        f"Changed: {changed_desc}      Smoke-test: {smoke}\n\n"
        f"{_APP_TRAILER}: {app}\n"
        f"{_FEEDBACK_TRAILER}: {{fid}}\n"   # fid filled by caller (kept template-free of the id var)
    )


# ───────────────────────────── commit per run ─────────────────────────────
def commit_run(cfg: dict, app: str, feedback_id: str, *, status: str, note_text: str) -> dict:
    """One atomic commit for an agent run: the source edit (if any) + the ledger (the reply + status).
    Smoke-tests a changed source first (fail ⇒ revert the edit, no commit). Returns a result dict with
    `committed` and either `sha` or `reason`."""
    git = cfg.get("git", {}) or {}
    with _lock(cfg):
        if not is_repo(cfg):
            return {"committed": False, "reason": "not a git repo"}
        led = ledger.load(cfg)
        fb = next((e for e in led.get(app, [])
                   if e.get("id") == feedback_id and e.get("author") != "claude"), None)
        comment, stars = (fb or {}).get("comment", ""), (fb or {}).get("stars")

        src = source_for(cfg, app)
        changed = bool(src) and _path_changed(cfg, src)
        smoke = "n/a (no source change)"
        if changed:
            ok, msg = smoke_source(Path(cfg["repo_root"]) / src)
            if not ok:
                _git(cfg, "checkout", "--", src)             # never commit a broken app
                return {"committed": False, "reason": f"smoke-test failed, reverted edit: {msg}"}
            smoke = "passed"
        changed_desc = f"edited {src}" if changed else ("plan only" if status == "awaiting_approval" else "ack / no source change")

        ensure_branch(cfg, git.get("branch"))
        paths = ([src] if changed else []) + ([_ledger_relpath(cfg)] if git.get("include_ledger", True) else [])
        if paths:
            _git(cfg, "add", "--", *paths)
        if _git(cfg, "diff", "--cached", "--quiet", check=False).returncode == 0:
            return {"committed": False, "reason": "nothing staged to commit"}

        summary = (note_text or "").strip().splitlines()[0][:72] if note_text else f"feedback on {app}"
        msg = _build_message(app, summary, comment, stars, changed_desc, smoke).replace("{fid}", feedback_id)
        from_email = ((fb or {}).get("user") or {}).get("email")
        if from_email:
            msg += f"Feedback-From: {from_email}\n"       # provenance → the git record (reputation substrate)
        msg += f"Co-Authored-By: curiator[{_agent_label(cfg)}] <noreply@curiator.dev>\n"
        commit_args = ["commit", "-m", msg] + (["-s"] if git.get("signoff", True) else [])
        _git(cfg, *commit_args)
        sha = _git(cfg, "rev-parse", "--short", "HEAD").stdout.strip()
        return {"committed": True, "sha": sha, "branch": current_branch(cfg)}


# ───────────────────────────── revert ─────────────────────────────
def find_commit(cfg: dict, feedback_id: str) -> str | None:
    r = _git(cfg, "log", "--all", f"--grep={_FEEDBACK_TRAILER}: {feedback_id}", "-n", "1", "--format=%H", check=False)
    out = r.stdout.strip().splitlines()
    return out[0] if out else None


def revert_feedback(cfg: dict, target: str, reason: str = "manual revert") -> dict:
    """Undo a curator commit WITHOUT erasing the record: restore the source to its pre-fix state, append
    a fresh ⚙ ledger note (the original reply stays), and commit that as its own `curator(<app>): revert`.
    `target` is a short/long SHA or a feedback id."""
    git = cfg.get("git", {}) or {}
    with _lock(cfg):
        if not is_repo(cfg):
            return {"ok": False, "reason": "not a git repo"}
        sha = target if (re.fullmatch(r"[0-9a-f]{7,40}", target)
                         and _git(cfg, "cat-file", "-e", target, check=False).returncode == 0) else find_commit(cfg, target)
        if not sha:
            return {"ok": False, "reason": f"no curator commit found for '{target}'"}
        tr = _trailers(cfg, sha)
        app, fid = tr.get(_APP_TRAILER), tr.get(_FEEDBACK_TRAILER)
        short = _git(cfg, "rev-parse", "--short", sha).stdout.strip()
        if not app:
            return {"ok": False, "reason": f"{short} is not a curator commit (no {_APP_TRAILER} trailer)"}

        src = source_for(cfg, app)
        files = _git(cfg, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).stdout.split()
        reverted_source = False
        if src and src in files:
            _git(cfg, "checkout", f"{sha}~1", "--", src)     # source as it was BEFORE the fix
            ok, msg = smoke_source(Path(cfg["repo_root"]) / src)
            if not ok:
                _git(cfg, "checkout", "--", src)             # abort: restore working copy
                return {"ok": False, "reason": f"reverted source fails smoke-test: {msg}"}
            reverted_source = True

        note = f"↩ reverted `{short}`" + (f" — {reason}" if reason else "")
        ledger.add_system_note(cfg, app, note, reply_to=[fid] if fid else [])
        if fid:
            ledger.set_status(cfg, app, [fid], "reverted")

        ensure_branch(cfg, git.get("branch"))
        paths = ([src] if reverted_source else []) + [_ledger_relpath(cfg)]
        _git(cfg, "add", "--", *paths)
        if _git(cfg, "diff", "--cached", "--quiet", check=False).returncode == 0:
            return {"ok": False, "reason": "nothing to revert/commit"}
        msg = (f"curator({app}): revert {short}\n\n"
               f"Reverted: {short}   Reason: {reason}\n\n"
               f"{_APP_TRAILER}: {app}\n{_FEEDBACK_TRAILER}: {fid or '-'}\n")
        _git(cfg, "commit", "-m", msg, *(["-s"] if git.get("signoff", True) else []))
        newsha = _git(cfg, "rev-parse", "--short", "HEAD").stdout.strip()
        return {"ok": True, "app": app, "feedback": fid, "reverted": short,
                "reverted_source": reverted_source, "sha": newsha}


# ───────────────────────────── reflect → LESSONS.md ─────────────────────────────
def reflect(cfg: dict) -> str:
    """Summarize the curator's git history (curator(*) commits + reverts) into LESSONS.md content,
    grouped by app — what stuck vs what got reverted. Each fresh one-shot loads it (cross-item memory)."""
    fmt = "%H%x1f%s%x1f%b%x1e"
    raw = _git(cfg, "log", "--all", f"--grep={_APP_TRAILER}:", f"--format={fmt}", check=False).stdout
    reverted_shorts, by_app = set(), {}
    records = []
    for chunk in (c for c in raw.split("\x1e") if c.strip()):
        h, subj, body = (chunk.strip().split("\x1f") + ["", ""])[:3]
        tr = {m.group(1): m.group(2).strip()
              for line in body.splitlines() if (m := re.match(r"^([A-Za-z][A-Za-z-]+):\s*(.+)$", line.strip()))}
        app = tr.get(_APP_TRAILER)
        if not app:
            continue
        is_revert = subj.lower().startswith(f"curator({app}): revert")
        if is_revert and (rm := re.search(r"Reverted:\s*([0-9a-f]{7,40})", body)):
            reverted_shorts.add(rm.group(1))
        records.append((h[:7], app, subj, tr.get(_FEEDBACK_TRAILER, ""), is_revert))
    for short, app, subj, fid, is_revert in records:
        by_app.setdefault(app, []).append((short, subj, fid, is_revert))

    out = ["# LESSONS.md — distilled from the curator's git history", "",
           "Auto-generated by `curiator reflect` from `curator(*)` commits. Each fresh agent run loads "
           "this for cross-item context (what stuck, what got reverted) — memory without a live session.", ""]
    if not by_app:
        out.append("_No curator commits yet._")
    for app in sorted(by_app):
        out.append(f"## {app}")
        for short, subj, fid, is_revert in by_app[app]:
            if is_revert:
                mark = "↩ revert"
            elif short in reverted_shorts:
                mark = "✗ reverted-later"
            else:
                mark = "✓ stuck"
            out.append(f"- {mark} · `{short}` · {subj}" + (f"  _(feedback {fid})_" if fid else ""))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def write_lessons(cfg: dict) -> Path:
    p = Path(cfg["repo_root"]) / "LESSONS.md"
    p.write_text(reflect(cfg))
    return p
