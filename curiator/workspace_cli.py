"""CLI surface for trusted/local Docker fork workspaces."""
from __future__ import annotations

import json

from .config import load_config
from .workspaces import DEFAULT_IMAGE, WorkspaceError, WorkspaceManager


def _print_row(row: dict) -> None:
    url = f"http://127.0.0.1:{row['host_port']}/?app={row['app_key']}" if row.get("host_port") else "-"
    branch = row.get("branch") or f"detached@{row['owning_repo_base_sha'][:10]}"
    print(f"{row['id']}  {row['status']:<10} {row['mode']:<7} {row['app_key']:<20} {branch}  {url}")


def cmd_workspace(args) -> int:
    cfg = load_config()
    manager = WorkspaceManager(cfg)
    try:
        if args.workspace_action == "create":
            row = manager.create(
                args.app,
                ref=args.from_ref,
                collection_ref=args.collection_from,
                name=args.name,
                preview=args.preview,
                image=args.image,
                build_if_missing=not args.no_build,
                credentials=args.credentials,
                feedback_id=args.feedback_id,
                dispatch_feedback=args.dispatch_feedback,
                agent_network=args.agent_network == "on",
                agent_sandbox=args.agent_sandbox,
                agent_adapter=args.agent_adapter,
                agent_model=args.agent_model,
                agent_autonomy=args.agent_autonomy,
                wait=not args.no_wait,
            )
            if args.json:
                print(json.dumps(row, indent=2, sort_keys=True))
            else:
                _print_row(row)
                print(manager.open_url(row["id"]))
            return 0
        if args.workspace_action == "list":
            rows = manager.list(include_deleted=args.all)
            if args.json:
                print(json.dumps(rows, indent=2, sort_keys=True))
            elif not rows:
                print("curiator: no workspaces")
            else:
                for row in rows:
                    _print_row(row)
            return 0
        if args.workspace_action == "compact":
            from . import workspace_store

            payload = workspace_store.compact_deleted(cfg)
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(
                    f"curiator: sanitized {payload['sanitized_workspaces']} deleted workspace receipt(s); "
                    f"ledger {payload['before_bytes']} -> {payload['after_bytes']} bytes"
                )
            return 0
        if args.workspace_action == "open":
            print(manager.open_url(args.workspace_id))
            return 0
        if args.workspace_action == "start":
            row = manager.start(args.workspace_id)
        elif args.workspace_action == "stop":
            row = manager.stop(args.workspace_id)
        elif args.workspace_action == "edit":
            row = manager.start_editing(args.workspace_id, args.branch)
        elif args.workspace_action == "diff":
            payload = manager.diff(args.workspace_id)
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"workspace {payload['id']} vs {payload['base_sha']}")
                print(payload["status"].rstrip() or "clean")
                if payload["commits"]:
                    print("\ncommits:")
                    print("\n".join(payload["commits"]))
                if payload["patch"]:
                    print("\ndiff:")
                    print(payload["patch"].rstrip())
            return 0
        elif args.workspace_action == "keep":
            row = manager.keep(args.workspace_id, args.branch)
        elif args.workspace_action == "apply":
            row = manager.apply(args.workspace_id)
        elif args.workspace_action == "delete":
            row = manager.delete(args.workspace_id, force=args.force)
        elif args.workspace_action == "logs":
            print(manager.logs(args.workspace_id, tail=args.tail), end="")
            return 0
        elif args.workspace_action == "smoke":
            payload = manager.smoke(args.workspace_id, app=args.app, browser=not args.no_browser)
            print(json.dumps(payload, indent=2, sort_keys=True) if args.json else
                  f"curiator: workspace smoke {'passed' if payload.get('ok') else 'failed'}")
            return 0 if payload.get("ok") else 1
        elif args.workspace_action == "doctor":
            payload = manager.doctor(args.workspace_id)
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(f"Docker workspaces: {'ready' if payload['ok'] else 'unavailable'}")
                print(f"  daemon: {payload['docker'].get('daemon_reason')}")
                print(f"  image: {payload['default_image']} "
                      f"({'available' if payload['image_available'] else 'missing'})")
                print("  child Docker socket: never mounted")
            return 0 if payload["ok"] else 1
        else:
            raise WorkspaceError(f"unknown workspace action {args.workspace_action!r}")
    except WorkspaceError as exc:
        print(f"curiator: workspace {args.workspace_action} failed - {exc}")
        return 1
    if getattr(args, "json", False):
        print(json.dumps(row, indent=2, sort_keys=True))
    else:
        _print_row(row)
    return 0


def add_workspace_parser(sub) -> None:
    ws = sub.add_parser("workspace", help="create and manage isolated Docker fork workspaces")
    actions = ws.add_subparsers(dest="workspace_action", required=True)

    create = actions.add_parser("create", help="fork an app into an isolated workspace")
    create.add_argument("app")
    create.add_argument("--from", dest="from_ref", default="HEAD", help="owning-repo Git ref (default: HEAD)")
    create.add_argument("--collection-from",
                        help="collection-repo Git ref when the app is a nested repo (default: collection HEAD)")
    create.add_argument("--name")
    create.add_argument("--preview", action="store_true", help="immutable detached preview; use edit to branch")
    create.add_argument("--image", default=DEFAULT_IMAGE)
    create.add_argument("--no-build", action="store_true", help="fail instead of building a missing default image")
    create.add_argument("--no-wait", action="store_true", help="return after container start without HTTP health wait")
    create.add_argument("--credentials", choices=["none", "claude", "codex"], default="none",
                        help="opt-in read-only agent credential mount")
    create.add_argument("--agent-network", choices=["on", "off"], default="on",
                        help="allow or deny network access for a sandboxed workspace agent")
    create.add_argument("--agent-sandbox", choices=["container", "workspace-write"], default="container",
                        help="use the Docker container boundary or an additional Codex filesystem sandbox")
    create.add_argument("--agent-adapter", choices=["headless-cc", "codex", "api", "command"])
    create.add_argument("--agent-model")
    create.add_argument("--agent-autonomy", choices=["propose-only", "auto-small", "auto"])
    create.add_argument("--feedback-id", help="seed one originating feedback thread with provenance")
    create.add_argument("--dispatch-feedback", action="store_true",
                        help="mark seeded feedback new so the workspace watcher acts on it")
    create.add_argument("--json", action="store_true")
    create.set_defaults(func=cmd_workspace)

    listing = actions.add_parser("list", help="list registered workspaces")
    listing.add_argument("--all", action="store_true", help="include deleted registry rows")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_workspace)

    compact = actions.add_parser("compact", help="sanitize deleted workspace receipts and VACUUM the registry")
    compact.add_argument("--json", action="store_true")
    compact.set_defaults(func=cmd_workspace)

    for action, help_text in (
        ("open", "print a workspace overlay URL"),
        ("start", "start a stopped workspace"),
        ("stop", "stop while preserving source and state volumes"),
    ):
        parser = actions.add_parser(action, help=help_text)
        parser.add_argument("workspace_id")
        parser.add_argument("--json", action="store_true")
        parser.set_defaults(func=cmd_workspace)

    edit = actions.add_parser("edit", help="turn a historical preview into an editable branch")
    edit.add_argument("workspace_id")
    edit.add_argument("--branch")
    edit.add_argument("--json", action="store_true")
    edit.set_defaults(func=cmd_workspace)

    diff = actions.add_parser("diff", help="compare source and commits to the immutable base SHA")
    diff.add_argument("workspace_id")
    diff.add_argument("--json", action="store_true")
    diff.set_defaults(func=cmd_workspace)

    keep = actions.add_parser("keep", help="import the workspace branch into the canonical owning repo")
    keep.add_argument("workspace_id")
    keep.add_argument("--branch", help="destination branch name (default: workspace branch)")
    keep.add_argument("--json", action="store_true")
    keep.set_defaults(func=cmd_workspace)

    apply = actions.add_parser(
        "apply", help="fast-forward a kept workspace branch when the canonical baseline still matches",
    )
    apply.add_argument("workspace_id")
    apply.add_argument("--json", action="store_true")
    apply.set_defaults(func=cmd_workspace)

    delete = actions.add_parser("delete", help="delete container and volumes after a source-loss check")
    delete.add_argument("workspace_id")
    delete.add_argument("--force", action="store_true", help="discard dirty or unexported source explicitly")
    delete.add_argument("--json", action="store_true")
    delete.set_defaults(func=cmd_workspace)

    logs = actions.add_parser("logs", help="show child shell/watcher logs")
    logs.add_argument("workspace_id")
    logs.add_argument("--tail", type=int, default=200)
    logs.set_defaults(func=cmd_workspace)

    smoke = actions.add_parser("smoke", help="run app and browser smoke inside the workspace")
    smoke.add_argument("workspace_id")
    smoke.add_argument("--app")
    smoke.add_argument("--no-browser", action="store_true")
    smoke.add_argument("--json", action="store_true")
    smoke.set_defaults(func=cmd_workspace)

    doctor = actions.add_parser("doctor", help="check Docker daemon, image, and workspace runtime state")
    doctor.add_argument("workspace_id", nargs="?")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_workspace)
