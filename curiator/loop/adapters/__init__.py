"""adapters — pluggable agent backends + the task-bundle builder.

`get(cfg)` returns the adapter selected by `gallery.yaml: agent.adapter`:
  - headless-cc : `claude -p` one-shot (subscription billing, full project context). DEFAULT.
  - codex       : `codex exec` one-shot (your OpenAI Codex subscription — same one-shot model).
  - api         : Anthropic API / Agent SDK (per-token, scales to teams). v1 — stub for now.
  - command     : run an arbitrary `agent.cmd` (BYO: aider / a script).

`build_task(cfg, key, entry)` writes a task file (the template + this feedback + the app's source
path + the screenshot path) and returns a Task the adapter runs. The task file is what the agent
reads; loop/task_template.md is the standing protocol (triage / smoke-test / reply / runner-owned git).
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from ...agent_capabilities import browser_smoke_contract
from ... import ledger
from ...config import app_spec as _app_spec   # the gallery.yaml schema logic lives in config.py
from ...narrative import display_narrative_rows
from .. import runlog
from . import headless_cc, codex, api as api_adapter, command as command_adapter

# The library/shell-wide feedback bucket (mirrors app_shell.GENERAL_KEY). Most General feedback is
# runner/shell feedback, but collection-level asks like "create a new app" need to stay in the
# collection repo instead of being misrouted to the runner checkout.
GENERAL_KEY = "__general__"

_COLLECTION_GENERAL_RE = re.compile(
    r"\b(create|add|build|scaffold|implement|make|do)\b"
    r"(?:(?!\brunner\b|\bshell\b|\bcuriator itself\b).){0,80}"
    r"\b(new\s+)?(curiator\s+)?(app|dashboard|explainer|overview)\b",
    re.I | re.S,
)

_GENERAL_APPROVAL_REPLY_RE = re.compile(
    r"\b(ok(?:ay)?|yes|approved?|go ahead|do it|proceed|please do|sounds good)\b",
    re.I,
)


@dataclass
class Task:
    key: str
    entry: dict
    source: str | None
    task_file: str
    reply_file: str
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
    "codex": codex,
    "api": api_adapter,
    "command": command_adapter,
}


def get(cfg: dict):
    name = (cfg.get("agent", {}) or {}).get("adapter", "headless-cc")
    if name not in _ADAPTERS:
        raise SystemExit(f"curIAtor: unknown agent.adapter '{name}' "
                         f"(choose: {', '.join(_ADAPTERS)})")
    return _ADAPTERS[name]


def _source_for(cfg: dict, key: str) -> str | None:
    spec = _app_spec(cfg, key)
    if spec:
        return spec.get("source")
    return None




def _repo_display(cfg: dict, path: str | Path | None) -> str | None:
    """Prompt-facing path. Prefer repo-relative paths so task bundles survive fresh clones."""
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        return p.as_posix()
    root = Path(cfg["repo_root"]).resolve()
    try:
        rel = p.resolve().relative_to(root)
    except ValueError:
        return str(p.resolve())
    return "." if str(rel) == "." else rel.as_posix()


def _feedback_rel(cfg: dict, *parts: str) -> str:
    fb_dir = (cfg.get("feedback", {}) or {}).get("dir", "feedback")
    return str(Path(fb_dir, *parts)).replace("\\", "/")


def _lessons_for(cfg: dict, app: str) -> str:
    """The `## <app>` section of LESSONS.md (written by `curiator reflect`), or "" — cross-item memory
    the cold one-shot loads so it starts informed by what stuck / got reverted for this app."""
    p = Path(cfg["repo_root"]) / "LESSONS.md"
    if not p.exists():
        return ""
    m = re.search(rf"(?ms)^## {re.escape(app)}\s*$(.*?)(?=^## |\Z)", p.read_text())
    return m.group(1).strip() if m else ""


def _shot_path(cfg: dict, entry: dict) -> str | None:
    """Prompt-facing screenshot path, or None.

    `entry['screenshot']` already carries its dir relative to the feedback dir (e.g.
    'shots/aviato_ab12.png'), so join it ONCE. Keep it repo-relative in task bundles for portability.
    """
    shot = entry.get("screenshot")
    if not shot:
        return None
    fb_dir = cfg.get("feedback", {}).get("dir", "feedback")
    return str(Path(fb_dir) / shot).replace("\\", "/")


def _audio_path(cfg: dict, entry: dict) -> str | None:
    """Prompt-facing retained-audio path, or None."""
    audio = entry.get("audio")
    if not audio:
        return None
    fb_dir = cfg.get("feedback", {}).get("dir", "feedback")
    return str(Path(fb_dir) / audio).replace("\\", "/")


def _audio_block(cfg: dict, entry: dict) -> str:
    audio = _audio_path(cfg, entry)
    if not audio:
        return ""
    return ("\n## Retained voice audio\n"
            f"- audio clip (local runtime media): `{audio}`\n"
            "- Use the transcript and narrated-feedback blocks as the primary task instructions; "
            "listen to the clip only when the transcript is ambiguous.")


def _annotation_block(entry: dict) -> str:
    """Prompt-facing structured annotation hints, if the screenshot was marked up."""
    marks = entry.get("annotations") or []
    if not isinstance(marks, list):
        return ""
    rows = []
    for idx, mark in enumerate(marks[:50], start=1):
        if not isinstance(mark, dict):
            continue
        tool = mark.get("tool") or "mark"
        label = f"pin {mark.get('n')}" if tool == "pin" and mark.get("n") else f"mark {idx}"
        coords = []
        for field in ("x1", "y1", "x2", "y2"):
            if isinstance(mark.get(field), (int, float)):
                coords.append(f"{field}={mark[field]:.3f}")
        line = f"- {label}: `{tool}`"
        if coords:
            line += " at " + ", ".join(coords)
        times = []
        if isinstance(mark.get("start_ms"), (int, float)):
            times.append(f"start={mark['start_ms']:.0f}ms")
        if isinstance(mark.get("end_ms"), (int, float)):
            times.append(f"end={mark['end_ms']:.0f}ms")
        if times:
            line += " [" + ", ".join(times) + "]"
        target = mark.get("target") if isinstance(mark.get("target"), dict) else {}
        if tool == "redact":
            line += " (target omitted for redaction)"
        elif target:
            bits = []
            selector = target.get("selector")
            if selector:
                bits.append(f"selector `{selector}`")
            tag = target.get("tag")
            if tag:
                bits.append(f"tag `{tag}`")
            testid = target.get("data_testid")
            if testid:
                bits.append(f"data-testid `{testid}`")
            role = target.get("role")
            if role:
                bits.append(f"role `{role}`")
            if bits:
                line += " -> " + "; ".join(bits)
        note = mark.get("note")
        if note:
            line += f" — {note}"
        rows.append(line)
    if not rows:
        return ""
    return "\n## Screenshot annotations\n" + "\n".join(rows)


def _transcript_block(entry: dict) -> str:
    """Prompt-facing transcript timing hints for voice feedback."""
    segments = entry.get("transcript_segments") or []
    if not isinstance(segments, list):
        return ""
    rows = []
    for idx, seg in enumerate(segments[:200], start=1):
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        bits = []
        if isinstance(seg.get("start_ms"), (int, float)):
            bits.append(f"start={seg['start_ms']:.0f}ms")
        if isinstance(seg.get("end_ms"), (int, float)):
            bits.append(f"end={seg['end_ms']:.0f}ms")
        prefix = f"- segment {idx}"
        if bits:
            prefix += " [" + ", ".join(bits) + "]"
        rows.append(f"{prefix}: {text}")
    if not rows:
        return ""
    return "\n## Voice transcript segments\n" + "\n".join(rows)


def _narrative_block(entry: dict) -> str:
    """Prompt-facing ordered tour that pairs timed marks with overlapping speech."""
    rows = []
    for idx, row in enumerate(display_narrative_rows(entry), start=1):
        times = f"[start={row['start_ms']:.0f}ms, end={row['end_ms']:.0f}ms]"
        line = f"- {idx}. {row['label']}: `{row['tool']}` {times}"
        target = row.get("target") if isinstance(row.get("target"), dict) else {}
        bits = []
        selector = target.get("selector")
        if selector:
            bits.append(f"selector `{selector}`")
        tag = target.get("tag")
        if tag:
            bits.append(f"tag `{tag}`")
        testid = target.get("data_testid")
        if testid:
            bits.append(f"data-testid `{testid}`")
        role = target.get("role")
        if role:
            bits.append(f"role `{role}`")
        if bits:
            line += " -> " + "; ".join(bits)
        text = row.get("text")
        note = row.get("note")
        if text:
            line += f": {text}"
        elif note:
            line += f": mark note: {note}"
        if text and note:
            line += f" (mark note: {note})"
        rows.append(line)
    if not rows:
        return ""
    return "\n## Narrated feedback\n" + "\n".join(rows)


def _entry_label(entry: dict) -> str:
    who = "agent" if entry.get("kind") == "system" or entry.get("author") == "claude" else "user"
    status = entry.get("status") or "?"
    ts = entry.get("ts") or "?"
    return f"{entry.get('id')} · {who} · {status} · {ts}"


def _related_thread_entries(cfg: dict, key: str, entry: dict, limit: int = 10) -> list[dict]:
    """Prior thread entries relevant to this wake."""
    items = ledger.load(cfg).get(key, [])
    if not items:
        return []
    current = entry.get("id")
    related = {current} if current else set()
    related.update(entry.get("reply_to") or [])
    changed = True
    while changed:
        changed = False
        for item in items:
            iid = item.get("id")
            links = set(item.get("reply_to") or [])
            if iid in related or (links & related):
                before = len(related)
                if iid:
                    related.add(iid)
                related.update(links)
                changed = changed or len(related) != before
    selected = [e for e in items if e.get("id") in related and e.get("id") != current]
    short_unlinked = not entry.get("reply_to") and len((entry.get("comment") or "").strip()) <= 12
    if len(selected) <= 1 or short_unlinked:
        idx = next((i for i, e in enumerate(items) if e.get("id") == current), len(items))
        recent = items[max(0, idx - limit):idx]
        seen = {e.get("id") for e in recent}
        selected = [*recent, *[e for e in selected if e.get("id") not in seen]]
    selected = selected[-limit:]
    return selected


def _thread_context(cfg: dict, key: str, entry: dict, limit: int = 10) -> str:
    """Relevant prior context for this wake.

    Primary path: traverse explicit reply links (`reply_to`) so quick-approval replies see the plan,
    original user request, and screenshot. Fallback: include recent entries for short unlinked replies
    (older ledgers did not link action buttons).
    """
    selected = _related_thread_entries(cfg, key, entry, limit=limit)
    if not selected:
        return ""
    lines = ["## Feedback thread context", "",
             "The current item may be an approval/reply. Use this context before deciding what to edit."]
    for item in selected:
        lines.append("")
        lines.append(f"- {_entry_label(item)}")
        if item.get("reply_to"):
            lines.append(f"  replies to: {', '.join(item.get('reply_to') or [])}")
        if item.get("stars"):
            lines.append(f"  stars: {item.get('stars')}")
        comment = (item.get("comment") or "").strip()
        if comment:
            lines.append(f"  comment: {comment!r}")
        shot = _shot_path(cfg, item)
        if shot:
            lines.append(f"  screenshot: `{shot}`")
    return "\n".join(lines)


def _feedback_tooling(cfg: dict, key: str) -> str:
    fb_key = key or GENERAL_KEY
    return "\n".join([
        "## Feedback ledger and tooling",
        "",
        f"- SQLite source of truth: `{_feedback_rel(cfg, 'app_feedback.sqlite')}`",
        f"- inspect recent history: `{_curiator_cmd(cfg, 'feedback', 'show', fb_key, '--limit', '20')}`",
        f"- dump history as JSON to stdout: `{_curiator_cmd(cfg, 'feedback', 'dump', fb_key)}`",
        "- Do not edit the SQLite file directly. Use `curiator reply` to add notes/status updates.",
        "- `feedback/app_feedback.json` is legacy import-only; any future web cache belongs under `feedback/cache/`.",
    ])


def _curiator_cmd(cfg: dict, *parts: str) -> str:
    args = " ".join(shlex.quote(str(part)) for part in parts)
    return f"curiator {args}"


def _reply_cmd(cfg: dict, key: str, eid: str, message: str, status: str) -> str:
    return f"{_curiator_cmd(cfg, 'reply', key, eid)} \"{message}\" --status {status}"


def _app_request_block(cfg: dict, entry: dict) -> tuple[str, str | None]:
    request = entry.get("app_request")
    if not isinstance(request, dict) or request.get("kind") != "new_app":
        return "", None
    app_key = str(request.get("app_key") or "<app_key>")
    title = str(request.get("title") or app_key)
    template = str(request.get("template") or "dash")
    app_type = str(request.get("app_type_label") or request.get("app_type") or template)
    raw_app_type = str(request.get("app_type") or "")
    prompt = str(request.get("prompt") or "").strip()
    notes = str(request.get("notes") or "").strip()
    repo_url = str(request.get("repo_url") or "").strip()
    guidance = str(request.get("guidance") or "").strip()
    dockerize = bool(request.get("dockerize"))
    if repo_url:
        tag_parts = ["imported"]
    elif raw_app_type == "pyodide_wasm":
        tag_parts = ["pyodide", "static"]
    else:
        tag_parts = [template]
    if dockerize and "docker" not in tag_parts:
        tag_parts.append("docker")
    tags = ",".join(tag_parts)
    lines = [
        "## New app wizard request",
        f"- suggested app key: `{app_key}`",
        f"- title: {title!r}",
        f"- app type: {app_type}",
        f"- scaffold/register template: `{template}`",
    ]
    if guidance:
        lines.append(f"- guidance: {guidance}")
    if dockerize:
        lines.append(
            "- packaging: Docker requested; add a Dockerfile and compose/run documentation when it helps, "
            "especially if the app needs extra services or non-Python components."
        )
    if repo_url:
        lines.append(f"- source repo: `{repo_url}`")
        lines.append("- import mode: clone/copy the repo under `apps/` as a nested app repo/subrepo.")
        ready = _curiator_cmd(
            cfg, "app", "import", repo_url, app_key, "--template", template, "--title", title, "--tags", tags
        )
    else:
        if raw_app_type == "pyodide_wasm":
            lines.append(
                "- runtime: keep compute browser-side with Pyodide/WASM; avoid adding a backend server "
                "unless the brief explicitly requires one."
            )
        if raw_app_type == "other":
            lines.append(
                "- template choice: choose the closest supported template from the brief; "
                f"`{template}` is only the fallback."
            )
        ready = _curiator_cmd(
            cfg, "app", "create", app_key, "--template", template, "--title", title, "--tags", tags
        )
    if prompt:
        lines += ["", "Brief:", prompt]
    if notes:
        lines += ["", "Notes:", notes]
    return "\n".join(lines), ready


def _runner_root(cfg: dict) -> str:
    """Where the runner (curiator) source lives, for checkout-mode patching: `runner.path` if set,
    else the package's own checkout root (works for an editable `pip install -e`)."""
    rpath = (cfg.get("runner") or {}).get("path")
    if rpath:
        return str((Path(cfg["repo_root"]) / rpath).resolve())
    import curiator
    return str(Path(curiator.__file__).resolve().parent.parent)


def general_targets_collection(entry: dict, cfg: dict | None = None) -> bool:
    """Whether a ◆ General item is asking to change the collection, not the runner package."""
    comment = entry.get("comment") or ""
    if _COLLECTION_GENERAL_RE.search(comment):
        return True
    if not cfg or not _GENERAL_APPROVAL_REPLY_RE.search(comment):
        return False
    return any(
        _COLLECTION_GENERAL_RE.search(item.get("comment") or "")
        for item in _related_thread_entries(cfg, GENERAL_KEY, entry)
    )


def _collection_bundle(cfg: dict, entry: dict, eid: str, shot_path: str | None, agent: dict) -> tuple[str, str]:
    """Bundle for ◆ General feedback that asks for collection-level work, such as adding a new app."""
    root = str(Path(cfg["repo_root"]).resolve())
    root_display = _repo_display(cfg, root)
    autonomy = agent.get("autonomy", "auto-small")
    elevated = agent.get("elevated")
    approval_followup = bool(_GENERAL_APPROVAL_REPLY_RE.search(entry.get("comment") or "")
                             and _related_thread_entries(cfg, GENERAL_KEY, entry))
    app_request, app_request_cmd = _app_request_block(cfg, entry)
    body = [
        "# curIAtor — General collection feedback",
        "",
        "This feedback came through **◆ General**, but it asks for gallery/app work in this collection,",
        "not a patch to the curIAtor runner package. You are non-interactive, in the collection repo.",
        "",
        f"- collection root: `{root_display}`",
        f"- autonomy mode: **{autonomy}**" + ("  ·  ELEVATED run (trusted group)" if elevated else ""),
        f"- comment: {entry.get('comment')!r}",
        f"- stars: {entry.get('stars')}",
        (f"- screenshot (Read this PNG): `{shot_path}`" if shot_path else "- screenshot: (none)"),
        f"- feedback id (reply_to this): `{eid}`",
        "",
        "## Scope",
        "- Work inside the collection repo only: add/edit `apps/`, update `gallery.yaml`, and update",
        "  dependency manifests when needed.",
        "- Do NOT edit the runner checkout for this item.",
        "- If this is an approval/follow-up, execute the underlying collection request from the thread",
        "  context now. Do not spend this run improving curIAtor routing/classification.",
        "- For new apps, start with `curiator app create <app_key> --template dash|static|python|node|flask|fastapi|rust|react|svelte|vue|next|streamlit|gradio` so",
        "  app directories, proxy commands, smoke hooks, and `gallery.yaml` stay consistent; then edit the generated files.",
        "- For existing repos, start with `curiator app import <repo-or-url> <app_key> --template <template>` so",
        "  the cloned source lands under `apps/` and is registered in `gallery.yaml` consistently.",
        "- Smoke-test changed or newly added apps before replying.",
        "",
        "## Ready-to-run (fill in the message text)",
        (f"- wizard app command: `{app_request_cmd}`" if app_request_cmd
         else f"- create an app scaffold: `{_curiator_cmd(cfg, 'app', 'create', '<app_key>', '--template', 'dash', '--title', '<title>', '--tags', 'dash')}`"),
        "- quick smoke option: `python -m compileall -q apps`",
        f"- reply after a fix:  `{_reply_cmd(cfg, GENERAL_KEY, eid, '<what changed + why>', 'done')}`",
        f"- reply with a plan:  `{_reply_cmd(cfg, GENERAL_KEY, eid, '<plan + recommendation>', 'awaiting_approval')}`",
    ]
    if app_request:
        body.append(app_request)
        app_key = (entry.get("app_request") or {}).get("app_key") if isinstance(entry.get("app_request"), dict) else None
        if app_key:
            browser_contract = browser_smoke_contract(cfg, str(app_key), eid)
            if browser_contract:
                body.append(browser_contract)
    annotations = _annotation_block(entry)
    if annotations:
        body.append(annotations)
    transcript = _transcript_block(entry)
    if transcript:
        body.append(transcript)
    narrative = _narrative_block(entry)
    if narrative:
        body.append(narrative)
    audio = _audio_block(cfg, entry)
    if audio:
        body.append(audio)
    if approval_followup:
        body.append(
            "\n**APPROVAL/FOLLOW-UP RUN** — the user has replied to a prior collection/app request. "
            "Use the feedback thread context as the request of record and perform that app work now. "
            "A new app is allowed: use `curiator app create`, then customize the scaffold, smoke-test, "
            "and reply `--status done`.")
    elif elevated:
        deny = ", ".join(f"`{d}`" for d in (agent.get("disallowed_tools") or [])) \
            or "the runner's own config, `git push`/history rewrites, destructive commands"
        body.append(
            "\n**ELEVATED run** — the feedback author is in a trusted group, so you may add files, "
            "edit `gallery.yaml`, and add/install dependencies needed by the new app or gallery change. "
            f"Off-limits: {deny}. Still don't run git yourself — the runner commits.")
    else:
        body.append(
            "\nIf the request needs a new app, new dependencies, or broad multi-file work, reply with "
            "`--status awaiting_approval` and a concise plan; otherwise keep the edit small and smoke-test it.")
    context = _thread_context(cfg, GENERAL_KEY, entry)
    if context:
        body.append("\n" + context)
    body.append("\n" + _feedback_tooling(cfg, GENERAL_KEY))
    return "\n".join(body) + "\n", root


def _runner_bundle(cfg: dict, entry: dict, eid: str, shot_path: str | None) -> tuple[str, str | None]:
    """Bundle for ◆ General (runner) feedback — feedback on curIAtor itself. The action keys off
    `runner.mode`: checkout ⇒ patch the runner locally (tracked, PR-able); pinned ⇒ draft an upstream
    issue/PR (never edit site-packages, which is untracked + blown away on upgrade)."""
    mode = (cfg.get("runner") or {}).get("mode", "pinned")
    head = [
        "# curIAtor — feedback on the RUNNER itself (the ◆ General channel)",
        "",
        "This feedback is about **curIAtor (the runner / shell), not one of your apps**. You are",
        f"non-interactive, in the repo. Reply to feedback id `{eid}`.",
        "",
        f"- comment: {entry.get('comment')!r}",
        f"- stars: {entry.get('stars')}",
        (f"- screenshot (Read this PNG): `{shot_path}`" if shot_path else "- screenshot: (none)"),
        f"- runner mode: **{mode}**",
        "",
    ]
    annotations = _annotation_block(entry)
    if annotations:
        head.append(annotations)
    transcript = _transcript_block(entry)
    if transcript:
        head.append(transcript)
    narrative = _narrative_block(entry)
    if narrative:
        head.append(narrative)
    audio = _audio_block(cfg, entry)
    if audio:
        head.append(audio)
    if mode == "checkout":
        root = _runner_root(cfg)
        root_display = _repo_display(cfg, root)
        body = head + [
            "## Mode: checkout — patch the runner locally (tracked, PR-able)",
            f"The runner is an editable git checkout at `{root_display}`. Make the change there:",
            "1. Locate the relevant source (shell = `curiator/shell/app_shell.py`, loop = `curiator/loop/`,",
            "   CLI = `curiator/cli.py`, config = `curiator/config.py`).",
            "2. Edit it, then smoke-test what you touched (import it / run a quick check).",
            "3. Reply (leave the diff UNCOMMITTED for a human to PR):",
            f"   `{_reply_cmd(cfg, GENERAL_KEY, eid, '<what you changed + why>', 'done')}`",
            "",
            "Edit ONLY within the runner checkout. **Do NOT git commit** — a human reviews + PRs the diff.",
        ]
        context = _thread_context(cfg, GENERAL_KEY, entry)
        if context:
            body.append("\n" + context)
        body.append("\n" + _feedback_tooling(cfg, GENERAL_KEY))
        return "\n".join(body) + "\n", root
    # pinned (default)
    body = head + [
        "## Mode: pinned — draft an upstream contribution (do NOT edit the installed package)",
        "The runner is a pinned, installed package; its `site-packages` source is untracked and is",
        "**blown away on upgrade**, so editing it is a dead end. Turn this feedback into a contribution:",
        "1. Draft a crisp upstream **issue / PR**: a one-line title, the problem, the proposed change,",
        "   and the likely area in curiator (shell / loop / cli / docs).",
        "2. Post the draft as your reply (a human files it upstream):",
        f"   `{_reply_cmd(cfg, GENERAL_KEY, eid, '<title + problem + proposed change>', 'awaiting_approval')}`",
        "",
        "Make **no code edits**. The deliverable is the drafted contribution text.",
    ]
    context = _thread_context(cfg, GENERAL_KEY, entry)
    if context:
        body.append("\n" + context)
    body.append("\n" + _feedback_tooling(cfg, GENERAL_KEY))
    return "\n".join(body) + "\n", None


def _app_bundle(cfg: dict, key: str, entry: dict, eid: str, shot_path: str | None, agent: dict) -> tuple[str, str | None]:
    """Bundle for app feedback — the standing protocol + this item + ready-to-run smoke-test/reply."""
    template = (Path(__file__).resolve().parents[1] / "task_template.md").read_text()
    spec = _app_spec(cfg, key) or {}
    source = spec.get("source")
    root = spec.get("root") or cfg["repo_root"]
    smoke = spec.get("smoke")
    source_is_dir = bool(source and Path(source).is_dir())
    root_display = _repo_display(cfg, root)
    source_display = _repo_display(cfg, source)
    autonomy = agent.get("autonomy", "auto-small")
    elevated = agent.get("elevated")
    body = [
        template, "\n\n---\n\n# This wake — the new feedback to act on\n",
        f"- app: **{key}**",
        f"- app root: `{root_display}`",
        f"- source scope to edit: `{source_display}`" if source else "- source: (none registered — propose only)",
        f"- autonomy mode: **{autonomy}**" + ("  ·  ELEVATED run (trusted group)" if elevated else ""),
        f"- stars: {entry.get('stars')}",
        f"- comment: {entry.get('comment')!r}",
        f"- screenshot (Read this PNG): `{shot_path}`" if shot_path else "- screenshot: (none)",
        f"- feedback id (reply_to this): `{eid}`",
    ]
    annotations = _annotation_block(entry)
    if annotations:
        body.append(annotations)
    transcript = _transcript_block(entry)
    if transcript:
        body.append(transcript)
    narrative = _narrative_block(entry)
    if narrative:
        body.append(narrative)
    audio = _audio_block(cfg, entry)
    if audio:
        body.append(audio)
    lessons = _lessons_for(cfg, key)
    if lessons:
        body.append(f"\n## Prior lessons for `{key}` (curator git history — what stuck / got reverted)\n{lessons}")
    context = _thread_context(cfg, key, entry)
    if context:
        body.append("\n" + context)
    body.append("\n" + _feedback_tooling(cfg, key))
    browser_contract = browser_smoke_contract(cfg, key, eid)
    if browser_contract:
        body.append("\n" + browser_contract)
    body.append("\n## Ready-to-run (fill in the message text)")
    if smoke:
        body.append(f"- smoke-test the edit: `{smoke}`  (run from `{root_display}`)")
    elif source and not source_is_dir:
        body.append(
            "- smoke-test the edit: "
            f"`python -c \"import importlib.util as u; s=u.spec_from_file_location('m', r'{source_display}'); "
            "m=u.module_from_spec(s); s.loader.exec_module(m); "
            "(m.build_app() if hasattr(m,'build_app') else m.app); print('SMOKE OK')\"`"
        )
    elif source_is_dir:
        body.append("- smoke-test the edit: no smoke command configured; run the narrowest available build/import check")
    body += [
        f"- reply after a fix:  `{_reply_cmd(cfg, key, eid, '<what changed + why>', 'done')}`",
        f"- reply with a plan:  `{_reply_cmd(cfg, key, eid, '<plan + recommendation>', 'awaiting_approval')}`",
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
        scope = "files under the source above" if source_is_dir else "the source above"
        body.append(
            f"\nEdit ONLY {scope}, smoke-test before `done`; the runner handles git — don't run git yourself.")
    return "\n".join(body), source


def build_task(cfg: dict, key: str, entry: dict) -> Task:
    """Write the task bundle for one feedback item and return the Task the adapter runs. App feedback
    routes to the app's source; ◆ General (runner) feedback routes by `runner.mode`."""
    eid = entry.get("id")
    shot_path = _shot_path(cfg, entry)
    agent = effective_agent(cfg, entry)
    if key == GENERAL_KEY:
        if general_targets_collection(entry, cfg):
            text, source = _collection_bundle(cfg, entry, eid, shot_path, agent)
        else:
            text, source = _runner_bundle(cfg, entry, eid, shot_path)
    else:
        text, source = _app_bundle(cfg, key, entry, eid, shot_path, agent)
    tf = runlog.task_path(cfg, eid)
    rf = runlog.reply_path(cfg, eid)
    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text(text)
    rf.parent.mkdir(parents=True, exist_ok=True)
    return Task(key=key, entry=entry, source=source, task_file=str(tf), reply_file=str(rf),
                cfg=cfg, agent=agent)
