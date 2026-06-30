"""adapters — pluggable agent backends + the task-bundle builder.

`get(cfg)` returns the adapter selected by `gallery.yaml: agent.adapter`:
  - headless-cc : `claude -p` one-shot (subscription billing, full project context). DEFAULT.
  - api         : Anthropic API / Agent SDK (per-token, scales to teams). v1 — stub for now.
  - command     : run an arbitrary `agent.cmd` (BYO: aider / Codex / a script).

`build_task(cfg, key, entry)` writes a task file (the template + this feedback + the app's source
path + the screenshot path) and returns a Task the adapter runs. The task file is what the agent
reads; loop/task_template.md is the standing protocol (triage / smoke-test / reply / no auto-commit).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import headless_cc, api as api_adapter, command as command_adapter

# The library/shell-wide feedback bucket (mirrors app_shell.GENERAL_KEY) — feedback on the RUNNER
# itself, routed by `runner.mode` rather than to an app source.
GENERAL_KEY = "__general__"


@dataclass
class Task:
    key: str
    entry: dict
    source: str | None
    task_file: str
    cfg: dict
    agent: dict | None = None        # the EFFECTIVE agent profile for this item (base, or elevated)


def effective_agent(cfg: dict, entry: dict) -> dict:
    """The agent profile for THIS feedback item. Normally the base `agent:` block; but if the feedback
    author's groups intersect `agent.elevated.groups`, the `elevated` overrides are merged on top — a
    trusted group (e.g. `admin`) gets fuller rights (autonomy / permissions / scope). Safe because each
    collection runs in its own sandbox (one container per collection); a deny-list still applies."""
    base = {k: v for k, v in (cfg.get("agent") or {}).items() if k != "elevated"}
    elev = (cfg.get("agent") or {}).get("elevated") or {}
    groups = set((entry.get("user") or {}).get("groups") or [])
    if elev and groups & set(elev.get("groups") or []):
        return {**base, **{k: v for k, v in elev.items() if k != "groups"}, "elevated": True}
    return {**base, "elevated": False}


_ADAPTERS = {
    "headless-cc": headless_cc,
    "api": api_adapter,
    "command": command_adapter,
}


def get(cfg: dict):
    name = (cfg.get("agent", {}) or {}).get("adapter", "headless-cc")
    if name not in _ADAPTERS:
        raise SystemExit(f"CurIAtor: unknown agent.adapter '{name}' "
                         f"(choose: {', '.join(_ADAPTERS)})")
    return _ADAPTERS[name]


def _source_for(cfg: dict, key: str) -> str | None:
    for a in (cfg.get("apps") or []):
        if a.get("name") == key or (a.get("mount", {}) or {}).get("module") == key:
            src = a.get("source")
            return str(Path(cfg["repo_root"]) / src) if src else None
    return None


def _lessons_for(cfg: dict, app: str) -> str:
    """The `## <app>` section of LESSONS.md (written by `curiator reflect`), or "" — cross-item memory
    the cold one-shot loads so it starts informed by what stuck / got reverted for this app."""
    p = Path(cfg["repo_root"]) / "LESSONS.md"
    if not p.exists():
        return ""
    m = re.search(rf"(?ms)^## {re.escape(app)}\s*$(.*?)(?=^## |\Z)", p.read_text())
    return m.group(1).strip() if m else ""


def _shot_path(cfg: dict, entry: dict) -> str | None:
    """Absolute path to the feedback screenshot, or None. `entry['screenshot']` already carries its dir
    relative to the feedback dir (e.g. 'shots/aviato_ab12.png'), so join it ONCE."""
    shot = entry.get("screenshot")
    if not shot:
        return None
    fb_dir = cfg.get("feedback", {}).get("dir", "feedback")
    return str(Path(cfg["repo_root"]) / fb_dir / shot)


def _runner_root(cfg: dict) -> str:
    """Where the runner (curiator) source lives, for checkout-mode patching: `runner.path` if set,
    else the package's own checkout root (works for an editable `pip install -e`)."""
    rpath = (cfg.get("runner") or {}).get("path")
    if rpath:
        return str((Path(cfg["repo_root"]) / rpath).resolve())
    import curiator
    return str(Path(curiator.__file__).resolve().parent.parent)


def _runner_bundle(cfg: dict, entry: dict, eid: str, shot_path: str | None) -> tuple[str, str | None]:
    """Bundle for ◆ General (runner) feedback — feedback on CurIAtor itself. The action keys off
    `runner.mode`: checkout ⇒ patch the runner locally (tracked, PR-able); pinned ⇒ draft an upstream
    issue/PR (never edit site-packages, which is untracked + blown away on upgrade)."""
    mode = (cfg.get("runner") or {}).get("mode", "pinned")
    head = [
        "# CurIAtor — feedback on the RUNNER itself (the ◆ General channel)",
        "",
        "This feedback is about **CurIAtor (the runner / shell), not one of your apps**. You are",
        f"non-interactive, in the repo. Reply to feedback id `{eid}`.",
        "",
        f"- comment: {entry.get('comment')!r}",
        f"- stars: {entry.get('stars')}",
        (f"- screenshot (Read this PNG): `{shot_path}`" if shot_path else "- screenshot: (none)"),
        f"- runner mode: **{mode}**",
        "",
    ]
    if mode == "checkout":
        root = _runner_root(cfg)
        body = head + [
            "## Mode: checkout — patch the runner locally (tracked, PR-able)",
            f"The runner is an editable git checkout at `{root}`. Make the change there:",
            "1. Locate the relevant source (shell = `curiator/shell/app_shell.py`, loop = `curiator/loop/`,",
            "   CLI = `curiator/cli.py`, config = `curiator/config.py`).",
            "2. Edit it, then smoke-test what you touched (import it / run a quick check).",
            "3. Reply (leave the diff UNCOMMITTED for a human to PR):",
            f"   `curiator reply {GENERAL_KEY} {eid} \"<what you changed + why>\" --status done`",
            "",
            "Edit ONLY within the runner checkout. **Do NOT git commit** — a human reviews + PRs the diff.",
        ]
        return "\n".join(body) + "\n", root
    # pinned (default)
    body = head + [
        "## Mode: pinned — draft an upstream contribution (do NOT edit the installed package)",
        "The runner is a pinned, installed package; its `site-packages` source is untracked and is",
        "**blown away on upgrade**, so editing it is a dead end. Turn this feedback into a contribution:",
        "1. Draft a crisp upstream **issue / PR**: a one-line title, the problem, the proposed change,",
        "   and the likely area in curiator (shell / loop / cli / docs).",
        "2. Post the draft as your reply (a human files it upstream):",
        f"   `curiator reply {GENERAL_KEY} {eid} \"<title + problem + proposed change>\" --status awaiting_approval`",
        "",
        "Make **no code edits**. The deliverable is the drafted contribution text.",
    ]
    return "\n".join(body) + "\n", None


def _app_bundle(cfg: dict, key: str, entry: dict, eid: str, shot_path: str | None, agent: dict) -> tuple[str, str | None]:
    """Bundle for app feedback — the standing protocol + this item + ready-to-run smoke-test/reply."""
    template = (Path(__file__).resolve().parents[1] / "task_template.md").read_text()
    source = _source_for(cfg, key)
    autonomy = agent.get("autonomy", "auto-small")
    elevated = agent.get("elevated")
    body = [
        template, "\n\n---\n\n# This wake — the new feedback to act on\n",
        f"- app: **{key}**",
        f"- source to edit: `{source}`" if source else "- source: (none registered — propose only)",
        f"- autonomy mode: **{autonomy}**" + ("  ·  ELEVATED run (trusted group)" if elevated else ""),
        f"- stars: {entry.get('stars')}",
        f"- comment: {entry.get('comment')!r}",
        f"- screenshot (Read this PNG): `{shot_path}`" if shot_path else "- screenshot: (none)",
        f"- feedback id (reply_to this): `{eid}`",
    ]
    lessons = _lessons_for(cfg, key)
    if lessons:
        body.append(f"\n## Prior lessons for `{key}` (curator git history — what stuck / got reverted)\n{lessons}")
    body.append("\n## Ready-to-run (fill in the message text)")
    if source:
        body.append(
            "- smoke-test the edit: "
            f"`python -c \"import importlib.util as u; s=u.spec_from_file_location('m', r'{source}'); "
            "m=u.module_from_spec(s); s.loader.exec_module(m); "
            "(m.build_app() if hasattr(m,'build_app') else m.app); print('SMOKE OK')\"`"
        )
    body += [
        f"- reply after a fix:  `curiator reply {key} {eid} \"<what changed + why>\" --status done`",
        f"- reply with a plan:  `curiator reply {key} {eid} \"<plan + recommendation>\" --status awaiting_approval`",
    ]
    if elevated:
        deny = ", ".join(f"`{d}`" for d in (agent.get("disallowed_tools") or [])) \
            or "the runner's own config, `git push`/history rewrites, destructive commands"
        body.append(
            "\n**ELEVATED run** — the feedback author is in a trusted group, so you may go beyond a single "
            "file: edit any source in this collection AND **add/install dependencies** (e.g. add to "
            "`requirements.txt`, then `pip install <pkg>`) to fully service the request. Install BEFORE you "
            "reply `--status done` so the gallery hot-reload doesn't crash. Smoke-test before `done`. "
            f"Off-limits: {deny}. Still don't run git yourself — the runner commits.")
    else:
        body.append(
            "\nEdit ONLY the source above, smoke-test before `done`; the runner handles git — don't run git yourself.")
    return "\n".join(body), source


def build_task(cfg: dict, key: str, entry: dict) -> Task:
    """Write the task bundle for one feedback item and return the Task the adapter runs. App feedback
    routes to the app's source; ◆ General (runner) feedback routes by `runner.mode`."""
    eid = entry.get("id")
    shot_path = _shot_path(cfg, entry)
    agent = effective_agent(cfg, entry)
    if key == GENERAL_KEY:
        text, source = _runner_bundle(cfg, entry, eid, shot_path)
    else:
        text, source = _app_bundle(cfg, key, entry, eid, shot_path, agent)
    tf = Path(cfg["repo_root"]) / cfg.get("feedback", {}).get("dir", "feedback") / f"task_{eid}.md"
    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text(text)
    return Task(key=key, entry=entry, source=source, task_file=str(tf), cfg=cfg, agent=agent)
