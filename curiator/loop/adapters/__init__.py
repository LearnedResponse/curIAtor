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

import json
from dataclasses import dataclass
from pathlib import Path

from . import headless_cc, api as api_adapter, command as command_adapter


@dataclass
class Task:
    key: str
    entry: dict
    source: str | None
    task_file: str
    cfg: dict


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


def build_task(cfg: dict, key: str, entry: dict) -> Task:
    repo = Path(cfg["repo_root"])
    template = (Path(__file__).resolve().parents[1] / "task_template.md").read_text()
    source = _source_for(cfg, key)
    shot = entry.get("screenshot")
    # `shot` already carries its dir relative to the feedback dir (e.g. "shots/aviato_ab12.png"),
    # so join it ONCE — don't re-insert "shots/".
    fb_dir = cfg.get("feedback", {}).get("dir", "feedback")
    shot_path = str(repo / fb_dir / shot) if shot else None
    eid = entry.get("id")
    mode = (cfg.get("agent", {}) or {}).get("autonomy", "auto-small")

    body = [
        template, "\n\n---\n\n# This wake — the new feedback to act on\n",
        f"- app: **{key}**",
        f"- source to edit: `{source}`" if source else "- source: (none registered — propose only)",
        f"- autonomy mode: **{mode}**",
        f"- stars: {entry.get('stars')}",
        f"- comment: {entry.get('comment')!r}",
        f"- screenshot (Read this PNG): `{shot_path}`" if shot_path else "- screenshot: (none)",
        f"- feedback id (reply_to this): `{eid}`",
        "\n## Ready-to-run (fill in the message text)",
    ]
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
        "\nEdit ONLY the source above, smoke-test before `done`, and DO NOT commit.",
    ]
    tf = repo / cfg.get("feedback", {}).get("dir", "feedback") / f"task_{entry.get('id')}.md"
    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text("\n".join(body))
    return Task(key=key, entry=entry, source=source, task_file=str(tf), cfg=cfg)
