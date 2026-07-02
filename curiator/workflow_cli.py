"""CLI handlers for feedback, agent workflow, and moderation queue commands."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ledger
from .app_cli import _app_names
from .config import agent_label, app_spec, app_specs, load_config


OPEN_FEEDBACK_STATUSES = {"new", "working", "awaiting_approval", "held"}


def _cli_shared():
    from . import cli as cli_mod

    return cli_mod


def _git_output(cwd: Path, *args: str) -> str | None:
    return _cli_shared()._git_output(cwd, *args)


def _resolve_app(cfg: dict, app: str | None = None) -> str:
    return _cli_shared()._resolve_app(cfg, app)


def _lookup_feedback(cfg: dict, feedback_id: str, app: str | None = None) -> tuple[str, dict] | None:
    return _cli_shared()._lookup_feedback(cfg, feedback_id, app)


def _find_feedback(cfg: dict, feedback_id: str, app: str | None = None) -> tuple[str, dict]:
    return _cli_shared()._find_feedback(cfg, feedback_id, app)


def _choose_feedback(cfg: dict, app: str, statuses: tuple[str, ...] = ("new", "awaiting_approval", "working")) -> dict | None:
    return _cli_shared()._choose_feedback(cfg, app, statuses)


def _feedback_counts(cfg: dict, app: str) -> tuple[int, int]:
    return _cli_shared()._feedback_counts(cfg, app)


def _shell_url(cfg: dict, app: str | None = None) -> str:
    return _cli_shared()._shell_url(cfg, app)


def _curiator_env_cmd(cfg: dict, *parts: str) -> str:
    return _cli_shared()._curiator_env_cmd(cfg, *parts)


def _cli_user(cfg: dict) -> dict | None:
    return _cli_shared()._cli_user(cfg)


def _reload_in_shell(cfg: dict, app: str) -> str | None:
    return _cli_shared()._reload_in_shell(cfg, app)
def _parse_actions_arg(s):
    """`--actions "A,B,C"` or `"Yes:yes,No:no"` → [[label, value], …] for quick-approval buttons."""
    out = []
    for item in (s or "").split(","):
        item = item.strip()
        if not item:
            continue
        lbl, _, val = item.partition(":")
        out.append([lbl.strip(), (val.strip() or lbl.strip())])
    return out or None


def _post_reply(cfg: dict, app: str, feedback_id: str, text: str, status: str | None, actions: str | None = None) -> int:
    ts = datetime.now(timezone.utc).isoformat()
    ledger.add_system_note(cfg, app, text, reply_to=[feedback_id],
                           status="update", ts=ts, actions=_parse_actions_arg(actions),
                           agent=agent_label(cfg))   # WHICH provider answered (Codex / Claude / …)
    if status:
        ledger.set_status(cfg, app, [feedback_id], status)
    print(f"curiator: replied on {app}/{feedback_id} (status={status or 'unchanged'})")
    # Git as the memory: when enabled, this run becomes ONE atomic commit (source edit + ledger).
    # The commit SHA is printed and queryable from git; do not mutate the ledger after commit, or
    # the collection is immediately dirty again.
    if (cfg.get("git", {}) or {}).get("commit"):
        from . import gitmem
        try:
            res = gitmem.commit_run(cfg, app, feedback_id,
                                    status=status or "update", note_text=text)
        except Exception as exc:  # noqa: BLE001 — a git hiccup must never break the reply / loop
            res = {"committed": False, "reason": str(exc)}
        if res.get("committed"):
            for app_commit in res.get("app_commits") or []:
                repo = Path(app_commit.get("repo", "")).name or "app repo"
                print(f"curiator: committed nested app {repo}@{app_commit['sha']} on {app_commit.get('branch','')}")
            for memory_commit in res.get("memory_commits") or []:
                memory = memory_commit.get("memory") or Path(memory_commit.get("repo", "")).name or "memory"
                print(f"curiator: committed memory {memory}@{memory_commit['sha']} on {memory_commit.get('branch','')}")
            if res.get("sha"):
                print(f"curiator: committed {res['sha']} on {res.get('branch','')}")
        else:
            print(f"curiator: not committed ({res.get('reason')})")
    # On `done`, the agent has just edited the app — make the fix live in a running shell.
    if status == "done":
        msg = _reload_in_shell(cfg, app)
        print(f"curiator: {msg}" if msg else "curiator: shell not reachable — reload skipped "
              "(the fix shows once `curiator up` reloads the app).")
    return 0


def cmd_reply(args) -> int:
    """Agent reply path: `curiator reply <app> <feedback_id> "<text>" --status done`.
    When offering options, pass `--actions "A,B,C"` so the approval buttons match the text exactly."""
    return _post_reply(load_config(), args.app, args.feedback_id, args.text, args.status, args.actions)


def cmd_context(args) -> int:
    cfg = load_config()
    try:
        app = _resolve_app(cfg, args.app)
    except SystemExit:
        if args.app or cfg.get("current_app") or len(_app_names(cfg)) <= 1:
            raise
        return _print_collection_context(cfg, args.limit)
    spec = app_spec(cfg, app) or {}
    total, open_n = _feedback_counts(cfg, app)
    print(f"# curIAtor Context: {app}")
    print("")
    print(f"- gallery: `{cfg['gallery_path']}`")
    print(f"- shell: `{_shell_url(cfg, app)}`")
    print(f"- app root: `{spec.get('root') or ''}`")
    print(f"- source scope: `{spec.get('source') or ''}`")
    print(f"- smoke: `{spec.get('smoke') or 'none configured'}`")
    commands = spec.get("commands") if isinstance(spec.get("commands"), dict) else {}
    if commands.get("preview"):
        print(f"- preview: `{commands['preview']}`")
    print(f"- feedback: {open_n} open / {total} total")
    print("")
    print("## Ready Commands")
    print("")
    print(f"- work next item: `{_curiator_env_cmd(cfg, 'work', '--app', app)}`")
    print(f"- show history: `{_curiator_env_cmd(cfg, 'feedback', 'show', app, '--limit', str(args.limit))}`")
    print(f"- add feedback: `{_curiator_env_cmd(cfg, 'feedback', 'add', app, '<comment>')}`")
    print(f"- open URL: `{_shell_url(cfg, app)}`")
    print("")
    print("## Recent Feedback")
    print("")
    _print_feedback_items(cfg, app, limit=args.limit)
    return 0


def _print_collection_context(cfg: dict, limit: int) -> int:
    from .loop.adapters import GENERAL_KEY
    specs = app_specs(cfg)
    data = ledger.load(cfg)
    app_names = [str(spec.get("name") or spec.get("app_name") or "") for spec in specs if spec.get("name")]
    total = sum(len(data.get(name, [])) for name in app_names)
    open_n = sum(
        1
        for name in app_names
        for entry in data.get(name, [])
        if entry.get("kind") != "system" and entry.get("status") in OPEN_FEEDBACK_STATUSES
    )
    general_total, general_open = _feedback_counts(cfg, GENERAL_KEY)
    if general_total:
        total += general_total
        open_n += general_open

    print("# curIAtor Context: collection")
    print("")
    print(f"- gallery: `{cfg['gallery_path']}`")
    print(f"- shell: `{_shell_url(cfg)}`")
    print(f"- apps: {len(specs)}")
    print(f"- feedback: {open_n} open / {total} total")
    print("- selected app: none")
    print("")
    print("## Ready Commands")
    print("")
    print(f"- select an app: `{_curiator_env_cmd(cfg, 'context', '--app', '<app>')}`")
    print(f"- show all feedback: `{_curiator_env_cmd(cfg, 'feedback', 'show', '--limit', str(limit))}`")
    print(f"- add General feedback: `{_curiator_env_cmd(cfg, 'feedback', 'add', GENERAL_KEY, '<comment>')}`")
    print(f"- list app templates: `{_curiator_env_cmd(cfg, 'app', 'templates')}`")
    print(f"- open gallery: `{_shell_url(cfg)}`")
    print("")
    print("## Apps")
    print("")
    if not specs:
        print("- no apps configured")
    for spec in specs:
        name = str(spec.get("name") or spec.get("app_name") or "")
        total_i, open_i = _feedback_counts(cfg, name)
        smoke = spec.get("smoke") or "none configured"
        print(f"- `{name}`: {open_i} open / {total_i} total; smoke `{smoke}`; root `{spec.get('root') or ''}`")
    print("")
    print("## Recent General Feedback")
    print("")
    _print_feedback_items(cfg, GENERAL_KEY, limit=limit)
    return 0


def cmd_work(args) -> int:
    cfg = load_config()
    app = args.app or cfg.get("current_app")
    if args.feedback_id:
        app, entry = _find_feedback(cfg, args.feedback_id, app)
        if entry.get("kind") == "system":
            raise SystemExit(f"curIAtor: {args.feedback_id} is a ⚙ agent note — "
                             "work the user feedback item it replies to instead.")
    else:
        app = _resolve_app(cfg, app)
        entry = _choose_feedback(cfg, app)
        if not entry:
            raise SystemExit(f"curIAtor: no open feedback for {app}.")
    if not args.no_claim:
        ledger.set_status(cfg, app, [entry["id"]], "working")
        entry = {**entry, "status": "working"}
    from .loop import adapters, runlog
    task = adapters.build_task(cfg, app, entry)
    reply_file = Path(task.reply_file)
    if reply_file.exists() and reply_file.stat().st_size:
        runlog.note(task, "opened for interactive CLI work")
    else:
        runlog.init_trace(task, "interactive")
        runlog.note(task, "opened for interactive CLI work")
    print(f"curiator: working {app}/{entry['id']}")
    print(f"task: {task.task_file}")
    print(f"trace: {task.reply_file}")
    if args.print:
        print("")
        print(Path(task.task_file).read_text())
    return 0


def cmd_done(args) -> int:
    cfg = load_config()
    app = args.app or cfg.get("current_app")
    words = list(args.text or [])
    feedback_id = args.feedback_id
    found = _lookup_feedback(cfg, feedback_id, app) if feedback_id else None
    if feedback_id and not found:
        # `curiator done "fixed the axis labels"` — a first word that isn't a known id (and doesn't
        # look like one) is message text, not a typo'd id; fall through to the latest-open-item path.
        if re.fullmatch(r"[0-9a-f]{8}", feedback_id):
            raise SystemExit(f"curIAtor: feedback id {feedback_id!r} not found.")
        words.insert(0, feedback_id)
        feedback_id = None
    if found:
        app = found[0]
    else:
        app = _resolve_app(cfg, app)
        entry = (_choose_feedback(cfg, app, statuses=("working",))              # prefer the claimed item
                 or _choose_feedback(cfg, app, statuses=("new", "awaiting_approval")))
        if not entry:
            raise SystemExit(f"curIAtor: no open feedback for {app}.")
        feedback_id = entry["id"]
    text = " ".join(words).strip() or "Done."
    return _post_reply(cfg, app, feedback_id, text, "done", None)


def cmd_revert(args) -> int:
    """Undo a curator commit without erasing the record: revert the source + append a ⚙ note, as its own
    `curator(<app>): revert` commit. `target` is a feedback id or a commit SHA."""
    cfg = load_config()
    from . import gitmem
    res = gitmem.revert_feedback(cfg, args.target, reason=args.reason or "manual revert")
    if not res.get("ok"):
        print(f"curiator: revert failed — {res.get('reason')}")
        return 1
    scope = "source + ledger" if res.get("reverted_source") else "ledger note only (was plan/ack — no source)"
    print(f"curiator: reverted {res['reverted']} → {res['sha']} ({scope}); thread on {res.get('app')} intact")
    if res.get("reverted_source"):
        msg = _reload_in_shell(cfg, res["app"])
        print(f"curiator: {msg}" if msg else "curiator: shell not reachable — reload skipped.")
    return 0


def cmd_reflect(args) -> int:
    """Summarize the curator's git history (curator(*) commits + reverts) into LESSONS.md."""
    cfg = load_config()
    from . import gitmem
    paths = gitmem.write_all_lessons(cfg)
    for p in paths:
        print(f"curiator: wrote {p} — loaded into that memory's agent context.")
    return 0


def cmd_seed(args) -> int:
    """Load canned feedback (a YAML file) into the ledger as new entries — the self-building-demo
    build queue. Each item becomes a status:new entry, attributed to the seed's `user:` (provenance),
    so the loop services it like any feedback. Format: `user: {…}` +
    `items: [{app, comment, stars?, user?, annotations?}]`."""
    import yaml
    from .annotations import clean_annotations

    cfg = load_config()
    spec = yaml.safe_load(Path(args.file).read_text()) or {}
    default_user = spec.get("user")
    ts = datetime.now(timezone.utc).isoformat()
    n = 0
    for it in (spec.get("items") or []):
        extra = {}
        annotations = clean_annotations(it.get("annotations"))
        if annotations:
            extra["annotations"] = annotations
        ledger.save_entry(cfg, it["app"], stars=it.get("stars"), comment=it.get("comment", ""),
                          ts=ts, user=it.get("user", default_user), extra=extra or None)
        n += 1
    who = (default_user or {}).get("name") or "—"
    print(f"curiator: seeded {n} feedback item(s) from {args.file} (author: {who}) — `curiator watch` to build.")
    return 0


def _print_feedback_items(cfg: dict, app: str, limit: int = 20) -> None:
    from .loop import runlog
    items = ledger.load(cfg).get(app, [])
    shown = items[-limit:] if limit else items
    if not shown:
        print(f"{app}: no feedback")
        return
    print(f"{app}:")
    for e in shown:
        who = e.get("agent") if e.get("author") == "claude" else ((e.get("user") or {}).get("name") or "user")
        flags = []
        if e.get("reply_to"):
            flags.append("reply_to=" + ",".join(e.get("reply_to") or []))
        if e.get("screenshot"):
            flags.append("screenshot=" + e.get("screenshot"))
        trace = runlog.reply_path(cfg, e.get("id"))
        if trace.exists():
            flags.append("trace=" + str(trace.relative_to(Path(cfg["repo_root"]))))
        extra = f" [{' · '.join(flags)}]" if flags else ""
        comment = " ".join((e.get("comment") or "").split())
        print(f"  {e.get('id')} {e.get('status')} {e.get('kind')} {who}: {comment[:160]}{extra}")


def _cli_annotations(args) -> list[dict]:
    raw_text = args.annotations_json
    if args.annotations_file:
        raw_text = Path(args.annotations_file).read_text()
    if not raw_text:
        return []
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"curIAtor: invalid annotation JSON: {exc}") from exc
    from .annotations import clean_annotations
    marks = clean_annotations(raw)
    if not marks:
        raise SystemExit("curIAtor: annotation JSON did not contain any valid marks.")
    return marks


def cmd_feedback(args) -> int:
    """Inspect the SQLite feedback ledger. This is intentionally CLI-level tooling so headless agents can
    inspect history without treating the SQLite file format as a private API."""
    import json
    cfg = load_config()
    if args.action == "add":
        app = _resolve_app(cfg, args.app)
        comment = (args.comment_text or " ".join(args.comment or [])).strip()
        if not comment and not args.stars:
            raise SystemExit("curIAtor: feedback add needs a comment and/or --stars.")
        extra = {}
        if args.reply_to:
            extra["reply_to"] = [args.reply_to]
        if args.status and args.status != "new":
            extra["status"] = args.status
        annotations = _cli_annotations(args)
        if annotations:
            extra["annotations"] = annotations
        eid = ledger.save_entry(cfg, app, stars=args.stars, comment=comment, user=_cli_user(cfg),
                                extra=extra or None)
        suffix = f" with {len(annotations)} annotation(s)" if annotations else ""
        print(f"curiator: added feedback {app}/{eid}{suffix}")
        return 0
    data = ledger.load(cfg)
    if args.app:
        data = {args.app: data.get(args.app, [])}
    if args.action == "dump":
        print(json.dumps(data if args.app is None else data.get(args.app, []), indent=2))
        return 0
    for app, items in data.items():
        if items:
            _print_feedback_items(cfg, app, args.limit)
    return 0


def _queue_actor(cfg: dict) -> str:
    root = Path(cfg["repo_root"])
    git_email = _git_output(root, "config", "user.email")
    if git_email:
        return git_email
    user = _cli_user(cfg) or {}
    return user.get("email") or user.get("name") or user.get("id") or "local CLI"


def _queue_entries(cfg: dict, app: str | None = None) -> list[tuple[str, dict]]:
    data = ledger.load(cfg)
    keys = [app] if app else list(data)
    rows: list[tuple[str, dict]] = []
    for key in keys:
        for entry in data.get(key, []):
            if entry.get("kind") != "system" and entry.get("status") == "held":
                rows.append((key, entry))
    return rows


def _parse_entry_ts(entry: dict) -> datetime | None:
    raw = entry.get("ts")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _queue_older_than(rows: list[tuple[str, dict]], days: float, *, now: datetime | None = None) -> list[tuple[str, dict]]:
    if days <= 0:
        raise SystemExit("curIAtor: --older-than must be greater than 0 days.")
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    return [(app, entry) for app, entry in rows if (ts := _parse_entry_ts(entry)) is not None and ts <= cutoff]


def _queue_row_payload(app: str, entry: dict) -> dict:
    user = entry.get("user") or {}
    comment = " ".join((entry.get("comment") or "").split())
    return {
        "app": app,
        "id": entry.get("id"),
        "ts": entry.get("ts"),
        "author": user.get("email") or user.get("name") or entry.get("author"),
        "stars": entry.get("stars"),
        "comment": comment,
    }


def _queue_sweep_payload(app: str, entry: dict, *, now: datetime | None = None) -> dict:
    payload = _queue_row_payload(app, entry)
    ts = _parse_entry_ts(entry)
    if ts:
        age_days = ((now or datetime.now(timezone.utc)) - ts).total_seconds() / 86400
        payload["age_days"] = round(max(age_days, 0.0), 2)
    else:
        payload["age_days"] = None
    return payload


def _print_queue_rows(rows: list[tuple[str, dict]]) -> None:
    if not rows:
        print("curiator: held queue is empty")
        return
    print(f"curiator: {len(rows)} held feedback item(s)")
    for app, entry in rows:
        payload = _queue_row_payload(app, entry)
        stars = f" ★{payload['stars']}" if payload.get("stars") else ""
        author = payload.get("author") or "user"
        comment = payload.get("comment") or "(no comment)"
        print(f"  {payload['id']} {app}{stars} {payload.get('ts') or '-'} {author}: {comment[:160]}")


def _queue_reject(cfg: dict, app: str, entry: dict, *, actor: str, reason: str = "", prefix: str = "rejected") -> None:
    text = f"Moderation queue: {prefix} by {actor}; closed without agent dispatch."
    if reason:
        text += f" Reason: {reason}"
    ledger.add_system_note(cfg, app, text, reply_to=[entry["id"]], agent="curiator queue")
    ledger.set_status(cfg, app, [entry["id"]], "rejected")


def cmd_queue(args) -> int:
    """Review feedback held out of agent dispatch.

    `held` is admission control for anonymous/over-quota/public submissions. The watcher only dispatches
    status:new entries, so approve is a narrow held→new transition and reject closes the thread as
    rejected with a ledger note.
    """
    cfg = load_config()
    if args.action == "list":
        app = _resolve_app(cfg, args.app) if args.app else None
        rows = _queue_entries(cfg, app)
        if args.limit:
            rows = rows[:args.limit]
        if args.json:
            print(json.dumps([_queue_row_payload(key, entry) for key, entry in rows], indent=2))
        else:
            _print_queue_rows(rows)
        return 0

    if args.action == "sweep":
        app = _resolve_app(cfg, args.app) if args.app else None
        rows = _queue_older_than(_queue_entries(cfg, app), args.older_than)
        if args.limit:
            rows = rows[:args.limit]
        actor = _queue_actor(cfg)
        reason = " ".join(args.reason or []).strip()
        if args.apply:
            for key, entry in rows:
                sweep_reason = reason or f"stale held feedback older than {args.older_than:g} day(s)"
                _queue_reject(
                    cfg,
                    key,
                    entry,
                    actor=actor,
                    reason=sweep_reason,
                    prefix="stale held item rejected",
                )
        result = {
            "ok": True,
            "action": "sweep",
            "applied": bool(args.apply),
            "matched": len(rows),
            "older_than_days": args.older_than,
            "rows": [_queue_sweep_payload(key, entry) for key, entry in rows],
        }
        if args.json:
            print(json.dumps(result, indent=2))
        elif args.apply:
            print(f"curiator: rejected {len(rows)} held feedback item(s) older than {args.older_than:g} day(s)")
            _print_queue_rows(rows)
        else:
            print(
                f"curiator: sweep dry-run found {len(rows)} held feedback item(s) older than "
                f"{args.older_than:g} day(s); pass --apply to reject them"
            )
            _print_queue_rows(rows)
        return 0

    app, entry = _find_feedback(cfg, args.feedback_id, args.app)
    if entry.get("kind") == "system":
        raise SystemExit(f"curIAtor: {args.feedback_id} is a system note, not a held feedback item.")
    if entry.get("status") != "held":
        raise SystemExit(f"curIAtor: {args.feedback_id} is status={entry.get('status')!r}, not held.")

    actor = _queue_actor(cfg)
    if args.action == "approve":
        ledger.add_system_note(
            cfg,
            app,
            f"Moderation queue: approved by {actor}; dispatching to the agent.",
            reply_to=[entry["id"]],
            agent="curiator queue",
        )
        ledger.set_status(cfg, app, [entry["id"]], "new")
        result = {"app": app, "id": entry["id"], "status": "new", "action": "approved"}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"curiator: approved {app}/{entry['id']} → new")
        return 0

    reason = " ".join(args.reason or []).strip()
    _queue_reject(cfg, app, entry, actor=actor, reason=reason)
    result = {"app": app, "id": entry["id"], "status": "rejected", "action": "rejected", "reason": reason}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"curiator: rejected {app}/{entry['id']} → rejected")
    return 0




