"""CLI for historical feedback replay audits and experiments."""
from __future__ import annotations

import json

from .config import load_config
from .replay import ReplayError, inspect, inspect_all, redacted_report
from .replay_lab import delete_group, keep_variant, list_groups, redacted_group, refresh_group, run_group
from .workspaces import DEFAULT_IMAGE, WorkspaceError


def _print(report: dict) -> None:
    print(f"{report['feedback_id']}  {report['app_key']}  {report['exactness']}  status={report.get('status')}")
    for reason in report.get("reasons") or []:
        print(f"  - {reason}")
    print(f"  workspace ready: {'yes' if report.get('workspace_ready') else 'no'}")


def cmd_replay(args) -> int:
    cfg = load_config()
    try:
        if args.replay_action == "inspect":
            report = inspect(cfg, args.feedback_id)
            payload = redacted_report(report) if args.redacted else report
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                _print(payload)
            return 0 if report.get("exactness") != "unreplayable" else 1
        if args.replay_action == "list":
            if args.groups:
                reports = list_groups(cfg)
            else:
                reports = inspect_all(cfg)
            if args.redacted:
                reports = [redacted_group(report) for report in reports] if args.groups else [
                    redacted_report(report) for report in reports
                ]
            if args.json:
                print(json.dumps(reports, indent=2, sort_keys=True))
            else:
                for report in reports:
                    _print(report)
            return 0
        if args.replay_action == "run":
            profiles = args.profile or ["baseline"]
            if len(profiles) > 1 and not args.yes:
                raise ReplayError("multi-variant replay requires --yes to confirm provider cost and Docker resources")
            group = run_group(
                cfg,
                args.feedback_id,
                profiles=profiles,
                credentials=args.credentials,
                image=args.image,
                build_if_missing=not args.no_build,
                wait_agent=not args.no_wait_agent,
                timeout=args.timeout,
                agent_network=args.agent_network == "on",
                agent_sandbox=args.agent_sandbox,
            )
            print(json.dumps(group, indent=2, sort_keys=True) if args.json else group["id"])
            return 0 if all(item.get("status") != "failed" for item in group["variants"]) else 1
        if args.replay_action == "show":
            group = refresh_group(cfg, args.group_id)
            print(json.dumps(group, indent=2, sort_keys=True) if args.json else group["id"])
            return 0
        if args.replay_action == "keep":
            group = keep_variant(cfg, args.group_id, args.variant_id)
            print(json.dumps(group, indent=2, sort_keys=True) if args.json else
                  f"curiator: preserved {args.group_id}/{args.variant_id}")
            return 0
        if args.replay_action == "delete":
            group = delete_group(cfg, args.group_id, force=args.force)
            print(json.dumps(group, indent=2, sort_keys=True) if args.json else
                  f"curiator: deleted replay resources for {args.group_id}")
            return 0
        raise ReplayError(f"unknown replay action {args.replay_action!r}")
    except (ReplayError, WorkspaceError) as exc:
        print(f"curiator: replay {args.replay_action} failed - {exc}")
        return 1


def add_replay_parser(sub) -> None:
    replay = sub.add_parser("replay", help="inspect and run historical feedback in isolated workspaces")
    actions = replay.add_subparsers(dest="replay_action", required=True)
    inspect_cmd = actions.add_parser("inspect", help="audit one feedback item's replay completeness")
    inspect_cmd.add_argument("feedback_id")
    inspect_cmd.add_argument("--json", action="store_true")
    inspect_cmd.add_argument("--redacted", action="store_true", help="omit private paths and design references")
    inspect_cmd.set_defaults(func=cmd_replay)
    listing = actions.add_parser("list", help="audit every user feedback item")
    listing.add_argument("--groups", action="store_true", help="list replay groups instead of feedback eligibility")
    listing.add_argument("--json", action="store_true")
    listing.add_argument("--redacted", action="store_true", help="emit compact export-safe fields")
    listing.set_defaults(func=cmd_replay)
    run = actions.add_parser("run", help="launch one or more source-exact workspace variants")
    run.add_argument("feedback_id")
    run.add_argument("--profile", action="append",
                     help="declared replay profile (repeat for explicit variants)")
    run.add_argument("--credentials", choices=["none", "auto", "codex", "claude"], default="none",
                     help="explicitly stage provider credentials; auto follows each profile adapter")
    run.add_argument("--image", default=DEFAULT_IMAGE)
    run.add_argument("--no-build", action="store_true")
    run.add_argument("--no-wait-agent", action="store_true", help="return once the workspace shell is healthy")
    run.add_argument("--timeout", type=float, default=900)
    run.add_argument("--agent-network", choices=["on", "off"], default="on")
    run.add_argument("--agent-sandbox", choices=["container", "workspace-write"], default="container")
    run.add_argument("--yes", action="store_true", help="confirm provider cost/resources for multiple variants")
    run.add_argument("--json", action="store_true")
    run.set_defaults(func=cmd_replay)
    show = actions.add_parser("show", help="refresh and show a replay group")
    show.add_argument("group_id")
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_replay)
    keep = actions.add_parser("keep", help="preserve one replay variant through the workspace Git-bundle path")
    keep.add_argument("group_id")
    keep.add_argument("variant_id")
    keep.add_argument("--json", action="store_true")
    keep.set_defaults(func=cmd_replay)
    delete = actions.add_parser("delete", help="delete replay containers/volumes but retain the compact manifest")
    delete.add_argument("group_id")
    delete.add_argument("--force", action="store_true")
    delete.add_argument("--json", action="store_true")
    delete.set_defaults(func=cmd_replay)
