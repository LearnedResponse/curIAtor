# Backlog — public playground (hosted collections, trust-tiered dispatch)

> **Status:** skipped/external as of 2026-07-03. Local moderation, quota, preflight, and backup-restore
> primitives are present; remaining work is an actual hosted pilot/deployment. The original scoped plan
> follows for provenance. Scoped 2026-07-01; phase-2 moderation primitive landed (`held` status,
> `auth.allow_anonymous` held intake for `local`/`oidc`, admin `/queue` shell view, and
> `curiator queue list|approve|reject|sweep` CLI, per-IP anonymous submission limits, and
> watcher-enforced account/global dispatch quotas, plus anonymous-upload suppression in the React shell).
> Sequences AFTER
> [public-release](public-release.md): the
> static example repos are the pitch; this is the live complement — **a hosted public collection where
> anyone can leave feedback and watch the curator work**, without handing an autonomous agent to the
> open internet. It is the mechanism behind SECURITY.md's "Public Internet Use" policy (queue + human
> review for unauthenticated feedback), now backed by the runner's held queue and dispatch quotas.
> **Rollout starts velvet-gated (2026-07-01):** an invite-only hosted collection needs ~zero new runner
> features — `auth.mode: local|oidc` already gates feedback behind login, and the invite list is both
> the rate limit and the trust vetting. A phase-0 deployment runbook, `curiator playground-preflight`
> posture gate, and `curiator playground-backup-smoke` restore-copy gate with `--output` evidence
> snapshots now exist in
> [`docs/PUBLIC_PLAYGROUND_DEPLOYMENT.md`](../../PUBLIC_PLAYGROUND_DEPLOYMENT.md); the actual hosted pilot
> remains to run. The anonymous tier + held pool is a later phase, built only after the velvet phase
> teaches us what hosted moderation actually costs.
> Local-auth hosted preflight now also rejects inline `auth.users` password hashes plus tracked,
> unignored, outside-root, or group/world-readable `.curiator-users.json` files, keeping invite
> credentials in the gitignored owner-only store. OIDC hosted preflight now also rejects missing
> `auth.issuer`, `auth.client_id`, and unset `auth.client_secret_env` secret variables while keeping
> secret values out of the JSON evidence report. Header-auth deployments now also fail closed at the
> feedback boundary: if the trusted edge proxy does not supply identity headers, feedback, quick
> replies, transcription, and retained audio are rejected instead of entering the dispatch queue.

## The idea

Public collections allow **anonymous browsing and feedback**, and offer **accounts**. What changes per
tier is not what you can *say* — it's **when the agent acts on it**:

| tier | who | dispatch |
|---|---|---|
| **anonymous** | no login | **held** — collected into a review pool; a human approves before any agent run |
| **account** | logged in (local/OIDC) | **auto, within quota** — the normal loop, budgeted |
| **trusted** | account in a trusted group | auto + the existing `agent.elevated` profile may apply |
| **admin** | account in `auth.admin_groups` | reviews the pool, reverts, promotes, revokes |

This is not a new system — it's **rungs below the ladder that already exists**. Groups on users,
group-gated elevation, `admin_groups`, the login rate-limiter, quotas, the held-queue CLI/shell, stale
queue sweep, and `curiator revert` are all in the runner today; what's left is public deployment
hardening and operating a real pilot.

## Rollout phases (each phase gates the next)

**Phase 0 — the velvet rope (deployable with today's runner).** One hosted collection, feedback gated
behind login (`auth.mode: local`, accounts created per invite with `curiator user add` — or
`auth.mode: header` behind oauth2-proxy with an email/org allowlist, which is a velvet rope with zero
password management). Everyone inside the rope is effectively the "account" tier; the invite list *is*
the rate limit, the vetting, and the abuse policy. `curiator user disable|enable` now gives local-login
deployments a non-destructive revocation lever, and the deployment runbook now spells out the container,
TLS reverse proxy, mounted-state backups, weekly `curiator stats` checks, and
`curiator playground-preflight` for runner/auth/git/queue/quota posture, with `--http-smoke` available
when installed app dependencies should be runtime-checked too, and `--browser-smoke` available when a
local Brave/Chromium binary should prove shell iframe rendering. `curiator playground-backup-smoke`
copies the mounted collection into a temporary restore tree and preflights that restored copy; it
supports the same smoke, HTTP, and browser gates. Both gates support `--output` for pre-pilot JSON
evidence snapshots. Remaining phase-0 work is actually running the hosted pilot. **What it answers
before phase 1:** real hosting cost per feedback→fix cycle, how often reverts are actually needed, and
whether strangers' feedback breaks the task-bundle assumptions.

**Phase 1 — self-serve accounts + quotas.** Open signup (or "Sign in with GitHub" via the existing
OIDC mode — identity dedupe plus a free reputation prior), and the quota knobs become real
(`per_user_daily`, `global_daily`). The watcher now enforces those quota knobs by degrading
over-budget items to `held`. The rope is gone but every author is still identified.

**Phase 2 — anonymous + the held pool.** The full ladder below: anonymous browsing + feedback that is
**always held** for human review, the moderation queue in the shell + `curiator queue` CLI, per-IP
submission limits. Core moderation status, hosted anonymous-held intake for `local`/`oidc`, shell
review view, CLI, stale queue sweep, per-IP anonymous submission limits, and account/global quota
degradation are now present.

## Design (each piece lands on an existing seam)

1. **Mixed anonymity** — `auth.allow_anonymous: true` alongside `mode: local|oidc` is landed: browsing
   + feedback work logged-out (recorded as anonymous and forced to `held`), login upgrades identity
   and keeps the normal `new` path.
2. **The dispatch ladder** — landed: a per-tier policy the loop consults before waking the agent:
   ```yaml
   agent:
     dispatch:
       anonymous: hold          # → status `held`, never auto-dispatched
       user: auto               # logged-in accounts, within quota
       trusted_groups: [trusted]  # these groups dispatch immediately (elevation still per agent.elevated)
     quotas:
       per_user_daily: 5        # account-tier runs per author per day
       global_daily: 100        # the collection's total agent budget — the cost ceiling
   ```
   Explicit anonymous `new` entries are forced to `held`; over-quota items degrade to `held` with an
   honest ⚙ note ("queued — the daily agent budget is spent"), not a silent drop. Trusted groups bypass
   `per_user_daily` but still count against `global_daily`.
3. **The moderation pool** — ledger status `held`, the admin-gated `/queue` shell view, and the
   headless CLI are landed: `curiator queue list|approve|reject` reviews held items; approve → `new`
   (dispatches normally), reject → `rejected` with an audit note, and `curiator queue sweep` dry-runs
   or applies stale-held cleanup with the same per-item audit notes. Approval is admission control,
   distinct from the existing `awaiting_approval` (which is the *agent* asking a human about a *plan*).
4. **Admin operations** — `curiator revert` already exists (git-as-memory makes every run one
   revertible commit). `curiator user disable <email>` / `enable` now toggles a `disabled` flag in the
   local store; header/OIDC revocation belongs to the IdP. Header mode now requires a resolved proxy
   identity before feedback can enter the ledger. Per-IP submission rate limiting for anonymous
   feedback is landed with the same in-memory sliding-window pattern as the login limiter.
5. **Trust promotion** — v1 is manual: an admin adds an account to the trusted group
   (`curiator user add <email> --groups trusted` is already an upsert). v2 can *derive* "established"
   from the ledger — account age + accepted-fix count, which `curiator stats` already computes the
   material for — rather than storing a reputation score anywhere.
6. **Anonymous screenshots: capture only** — landed for the React shell path. The 📷 capture of the
   live app is fine (it renders the app's own DOM); arbitrary-file **upload** and browser-native
   **Native** screen capture are disabled for anonymous users, and the feedback API rejects
   anonymous-held screenshots that are not explicitly marked as same-origin captures by the shell.
   Upload/native images are separate abuse/injection channels and the pool reviewers shouldn't have to
   moderate arbitrary pixels. Retained audio follows the same rule: anonymous reviewers may transcribe
   through the configured local path, but durable audio attachment is disabled until they sign in.

## Deployment shape — a pattern, not a rearchitecture

curIAtor stays single-tenant: the unit is still **one container per public collection** (SECURITY.md's
blast-radius boundary), the agent inside it on `auto-small` or `propose-only`, `git: {commit: true}` so
admins hold a working revert lever, deny-lists on. The playground is that same unit plus the dispatch
ladder — not a multi-tenant SaaS. If several collections go public, "agent pools" = one shared worker
budget across their loops (fairness + a global cap); that's v2, per-collection quotas are v1.

## v1 scope

**One velvet-gated playground collection**: [`galleries/curiator-geometry`](../completed/math-geometry-collection.md)
(now scaffolded) — deterministic, dataless, zero-toolchain, the cheapest to babysit, and its audience
(researchers/educators) is exactly who to invite first. `curiator-aviato` or `curiator-ot` as a second
playground only after the moderation load is understood. Phases 1–2 follow the rollout above; nothing
in phase 2 gets built until phase 0 has run with real invitees.

## Honest risks

- **Moderation labor is the real cost.** The pool needs humans; for anonymous users the reply latency
  *is* the reviewer, not the agent — say so in the UI ("queued for review"). Per-IP rate limits and
  dry-run stale sweeps help keep the pool reviewable, but a public deployment still needs monitoring.
- **Prompt injection doesn't vanish above the anonymous tier** — account feedback still reaches the
  agent. Quotas bound the blast rate; `auto-small`/`propose-only` + deny-lists bound the blast radius;
  the container bounds the box. Keep SECURITY.md's "mitigations, not a solved problem" framing.
- **Compute cost is capped by design**: the global daily quota is the worst-case spend, and it's a
  number in gallery.yaml an admin can read.

## Guardrails

- **Anonymous feedback NEVER auto-dispatches.** No config combination should allow it; `hold` for
  anonymous is enforced, not defaulted.
- Everything moderation does lands in the ledger (who approved/rejected/reverted, when) — the audit
  trail is the same conversation record, not a side system.
- The playground runs released curiator (`runner: {mode: pinned}`) — the public box is not also the
  runner's dev environment.
