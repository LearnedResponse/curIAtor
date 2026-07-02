---
name: curiator
description: Use when working in a repo linked to a curIAtor gallery, handling curIAtor feedback IDs, opening task bundles, posting replies, or finishing app changes through curIAtor's ledger, reload, and git-as-memory workflow.
---

# curIAtor

You are working inside a repo or directory linked to a curIAtor gallery.

Use the `curiator` CLI as the source of truth:
- `curiator status` shows the linked gallery/app and git-as-memory state.
- `curiator context` prints source scope, smoke test, recent feedback, and ready commands.
- `curiator work [feedback_id]` prints the exact task bundle a headless curator would receive and marks the item `working`.
- After edits and smoke tests, use `curiator done <feedback_id> "<summary>"`.
- For proposals, use `curiator reply <app> <feedback_id> "<plan>" --status awaiting_approval`.
- Do not edit `feedback/app_feedback.sqlite` directly.
- Do not run git commit/push/rewrite commands for curator work; `curiator done`/`reply --status done` handles git-as-memory.

When the user invokes this shim:
1. If they provide no arguments, run `curiator status` and `curiator context`.
2. If they provide `work` or a feedback id, run `curiator work ...`, read the printed task bundle, and follow it.
3. If they provide `done`, help formulate and run the appropriate `curiator done ...` command after verifying the change.
