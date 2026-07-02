# Good First Issue Seeds

These are ready-to-file issues for the public launch. After the repo is published, create them as
GitHub issues, label them `good first issue`, and pin 2-3 that best match the current release focus.

## Add Dependency Checks To `curiator doctor`

Labels: `good first issue`, `portability`, `release`

Why: the release gate is a fresh clone on a different machine. `curiator doctor` should catch cheap
environment mistakes before that expensive manual check.

Scope:
- Add optional warnings for app smoke commands whose executable is not on `PATH`.
- For common templates, warn when expected dependency manifests are missing (`requirements.txt`,
  `package.json`, etc.).
- Keep missing paths and machine-absolute paths as errors; dependency checks should be warnings.
- Preserve `--json` output shape.

Done when:
- Existing `doctor` tests still pass.
- New tests cover missing executable/dependency warnings separately from errors.

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

## Document Native Screenshot Capture Options

Labels: `good first issue`, `documentation`, `security`

Why: `html2canvas` is useful but imperfect for canvas/WebGL and modern CSS. The release docs already
call this out; a short technical note would make the tradeoff explicit.

Scope:
- Add `docs/SCREENSHOT_CAPTURE.md`.
- Explain the current same-origin `html2canvas` approach and upload fallback.
- Compare browser `getDisplayMedia`, Playwright/server-side capture, and extension/native-helper
  options.
- Include privacy/security notes for each option.

Done when:
- The README or `docs/USING_CURIATOR.md` links the note from the screenshot section.
