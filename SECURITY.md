# Security Policy

curIAtor connects browser feedback to a coding agent that can edit and run code. Treat it as
automation for trusted teams and sandboxed collections, not as a safe way to let anonymous internet
users drive an agent against your source tree.

## Reporting Vulnerabilities

Do not post exploit details, secrets, or private collection data in a public issue. Use GitHub private
vulnerability reporting for this repository if it is available. If it is not available, open a minimal
public issue saying you have a security report and include only enough detail for a maintainer to
establish a private channel.

## Threat Model

curIAtor has three distinct surfaces:

- The gallery shell serves your apps, captures ratings/comments/screenshots, and stores them in the
  collection ledger.
- The app processes are your code. A `proxy` mount may start any local server command configured in
  `gallery.yaml`.
- The curation loop starts a coding agent with the feedback text, screenshot path, source scope,
  task bundle, and configured autonomy/permissions.

The important security fact is that feedback is prompt input. Public or semi-public feedback can
include prompt-injection attempts such as "ignore prior instructions, read secrets, install a package,
or exfiltrate files." curIAtor records identity and controls workflow, but it does not solve prompt
injection.

## What curIAtor Does Not Promise

- It does not make untrusted feedback safe for autonomous code execution.
- It does not sandbox arbitrary app code by itself. Use a container, VM, or other host boundary.
- It does not prevent a fully trusted/elevated agent profile from doing whatever that agent CLI can do.
- It does not make same-origin app content safe; same-origin is used so screenshots and feedback work.
- It does not redact sensitive information from screenshots, comments, logs, traces, or ledgers.

## Recommended Deployment Defaults

For personal/local use:

- Run one collection per container or VM when possible.
- Keep secrets out of the collection directory.
- Use `git.commit: true` for reviewable one-item commits, or review the dirty tree manually before
  promoting changes.
- Keep the default small autonomy profile unless you are actively supervising the run.

For shared/team use:

- Require sign-in with `auth.mode: local`, `header`, or `oidc`; do not accept anonymous public feedback
  into an auto-editing loop.
- Use `agent.autonomy: propose-only` for feedback from broad groups.
- Gate elevated profiles to trusted admin groups only.
- Give the agent least-privilege credentials. Mount provider tokens read-only and avoid host-wide
  secrets in the collection container.
- Treat `danger-full-access`, bypassed approvals, package installation, and shell/network access as
  elevated operations.
- Review git-as-memory commits before merging or deploying them.

## Adapter Notes

- `headless-cc` and `command` adapters inherit the security behavior of the CLI you configure.
- The Codex adapter supports sandbox/permission settings, but an elevated bypass profile is a
  full-trust run. Use it only inside the collection's containment boundary.
- Deny-lists are defense in depth. They are not a complete policy engine and may not be available for
  every adapter.

## Data Handling

The collection ledger and artifacts can contain sensitive user text, screenshots, app state, task
bundles, agent traces, and commit metadata. Before publishing an example collection, audit:

- `feedback/app_feedback.sqlite`
- `feedback/shots/`
- `feedback/tasks/`
- `feedback/replies/`
- git commit messages and trailers
- `.curiator-users.json` and any local auth files

Runtime-only files such as local users, task traces, screenshots, and SQLite sidecars should normally
be gitignored unless you deliberately intend to publish them as part of a sanitized demo.

## Public Internet Use

If the feedback form is exposed to the public internet, use a queue plus human review or
`propose-only` by default. Do not let unauthenticated public comments trigger an autonomous agent with
write access to a repo or credentials.
