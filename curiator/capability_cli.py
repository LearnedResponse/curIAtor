"""Local capability receipts recorded after an external provider probe succeeds."""
from __future__ import annotations

from .agent_capabilities import clear_capability_receipt, record_figma_receipt, record_figma_unavailable
from .config import load_config


def cmd_capability(args) -> int:
    cfg = load_config()
    if args.name != "figma":
        raise SystemExit(f"curIAtor: unsupported capability {args.name!r}.")
    if args.action == "clear":
        cleared = clear_capability_receipt(cfg, "figma")
        print(f"curiator: Figma capability receipt {'cleared' if cleared else 'was not present'}")
        return 0
    if args.action == "unavailable":
        receipt = record_figma_unavailable(
            cfg,
            reason=args.reason,
            provider=args.provider,
            retry_hours=args.retry_hours,
        )
        print(
            "curiator: recorded temporary Figma unavailability "
            f"(retry after {receipt['expires_at']}: {receipt['reason']})"
        )
        return 0
    receipt = record_figma_receipt(
        cfg,
        read_context=True,
        render_reference=True,
        write_design=bool(args.write_design),
        code_connect=bool(args.code_connect),
        provider=args.provider,
    )
    states = ["read", "render"]
    if receipt["capabilities"]["write_design"] == "available":
        states.append("write")
    if receipt["capabilities"]["code_connect"] == "available":
        states.append("code-connect")
    print(
        "curiator: recorded local Figma capability receipt "
        f"({', '.join(states)}; expires {receipt['expires_at']})"
    )
    return 0
