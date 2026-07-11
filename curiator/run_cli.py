"""CLI handlers for interrupted agent-run recovery."""
from __future__ import annotations

import json

from .config import load_config
from .run_recovery import (
    CheckpointError,
    discard_checkpoint,
    format_report,
    preserve_partial,
    recovery_report,
    restore_baseline,
    resume_partial,
)


def cmd_run(args) -> int:
    cfg = load_config()
    try:
        if args.run_action == "recovery":
            payload = recovery_report(cfg, args.feedback_id)
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(format_report(payload))
            return 0
        if args.run_action == "resume":
            payload = resume_partial(cfg, args.feedback_id)
        elif args.run_action == "preserve":
            payload = preserve_partial(cfg, args.feedback_id, args.branch)
        elif args.run_action == "restore":
            payload = restore_baseline(cfg, args.feedback_id)
        elif args.run_action == "discard-checkpoint":
            payload = discard_checkpoint(cfg, args.feedback_id)
        else:
            raise CheckpointError(f"unknown run action {args.run_action!r}")
    except CheckpointError as exc:
        print(f"curiator: recovery failed - {exc}")
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True) if getattr(args, "json", False)
          else f"curiator: recovery {args.run_action} completed for {args.feedback_id}")
    return 0
