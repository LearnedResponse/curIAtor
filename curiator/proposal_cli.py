"""CLI surface for inspecting and resolving per-run Git proposals."""
from __future__ import annotations

import json

from . import ledger, proposals
from .config import load_config


def _feedback_app(cfg: dict, feedback_id: str, requested: str | None = None) -> str:
    if requested:
        return requested
    for app, rows in ledger.load(cfg).items():
        if any(row.get("id") == feedback_id and row.get("kind") != "system" for row in rows):
            return app
    raise SystemExit(f"curIAtor: feedback id {feedback_id!r} not found")


def cmd_proposal(args) -> int:
    cfg = load_config()
    if args.proposal_action == "list":
        rows = proposals.list_proposals(cfg, app=args.app)
        if args.json:
            print(json.dumps({"proposals": rows}, indent=2))
            return 0
        if not rows:
            print("curiator: no proposal refs found")
            return 0
        for row in rows:
            short = str(row.get("sha") or "")[:8]
            location = f" worktree={row['worktree']}" if row.get("worktree") else ""
            print(
                f"{row['state']:10} {row['app']}/{row['feedback_id']} "
                f"{row['branch']}@{short}{location}"
            )
        return 0

    app = _feedback_app(cfg, args.feedback_id, args.app)
    actor = "curiator CLI"
    try:
        if args.proposal_action == "approve":
            result = proposals.approve(cfg, app, args.feedback_id, actor=actor)
        else:
            result = proposals.reject(
                cfg,
                app,
                args.feedback_id,
                actor=actor,
                reason=" ".join(args.reason or []).strip(),
            )
    except proposals.ProposalError as exc:
        raise SystemExit(f"curIAtor: proposal {args.proposal_action} failed: {exc}") from exc
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"curiator: proposal {args.feedback_id} {result['action']} "
            f"({result['branch']})"
        )
    return 0


def add_proposal_parser(subparsers) -> None:
    proposal = subparsers.add_parser("proposal", help="inspect or resolve per-run branch proposals")
    actions = proposal.add_subparsers(dest="proposal_action", required=True)
    listing = actions.add_parser("list", help="list proposal refs and worktrees")
    listing.add_argument("--app", help="limit to one app")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_proposal)
    approve = actions.add_parser("approve", help="merge an open proposal into the accepted branch")
    approve.add_argument("feedback_id")
    approve.add_argument("--app", help="disambiguate the feedback id")
    approve.add_argument("--json", action="store_true")
    approve.set_defaults(func=cmd_proposal)
    reject = actions.add_parser("reject", help="reject a proposal while retaining its branch")
    reject.add_argument("feedback_id")
    reject.add_argument("reason", nargs="*")
    reject.add_argument("--app", help="disambiguate the feedback id")
    reject.add_argument("--json", action="store_true")
    reject.set_defaults(func=cmd_proposal)
