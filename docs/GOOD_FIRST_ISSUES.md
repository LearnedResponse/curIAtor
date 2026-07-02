# Good First Issue Seeds

These are ready-to-file issues for the public launch. After the repo is published, create them as
GitHub issues, label them `good first issue`, and pin 2-3 that best match the current release focus.

## Add Parallel Smoke Execution

Labels: `good first issue`, `release`, `example-collection`

Why: `curiator smoke` gives every public collection the same release preflight. Larger collections will
benefit from running independent app checks concurrently while still reporting a stable summary.

Scope:
- Add `curiator smoke --jobs N` with a conservative default of serial execution.
- Preserve deterministic output ordering by app name or gallery order.
- Keep git-as-memory commit smoke checks serial; this is only for collection preflight.
- Include timeouts and failures clearly in human and `--json` output.

Done when:
- Two deliberately slow smoke commands complete faster with `--jobs 2` than serially.
- Failure reporting remains stable and identifies each app.
