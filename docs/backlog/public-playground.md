# Backlog — public playground (hosted collections, trust-tiered dispatch)

> **Status:** scoped 2026-07-01; phase-2 moderation primitive partly landed (`held` status +
> `curiator queue list|approve|reject` CLI), hosted anonymous intake still not started. Sequences AFTER
> [public-release](public-release.md): the
> static example repos are the pitch; this is the live complement — **a hosted public collection where
> anyone can leave feedback and watch the curator work**, without handing an autonomous agent to the
> open internet. It is the mechanism behind SECURITY.md's "Public Internet Use" policy (queue + human
> review for unauthenticated feedback), which today is stated but not enforced by the runner.
> **Rollout starts velvet-gated (2026-07-01):** an invite-only hosted collection needs ~zero new runner
> features — `auth.mode: local|oidc` already gates feedback behind login, and the invite list is both
> the rate limit and the trust vetting. The anonymous tier + held pool is a later phase, built only
> after the velvet phase teaches us what hosted moderation actually costs.

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
group-gated elevation, `admin_groups`, the login rate-limiter, and `curiator revert` are all in the
runner today; what's missing is the bottom of the ladder (anonymous-but-held) and the budget.

## Rollout phases (each phase gates the next)

**Phase 0 — the velvet rope (deployable with today's runner).** One hosted collection, feedback gated
behind login (`auth.mode: local`, accounts created per invite with `curiator user add` — or
`auth.mode: header` behind oauth2-proxy with an email/org allowlist, which is a velvet rope with zero
password management). Everyone inside the rope is effectively the "account" tier; the invite list *is*
the rate limit, the vetting, and the abuse policy. `curiator user disable|enable` now gives local-login
deployments a non-destructive revocation lever. Remaining phase-0 work is deployment: a container +
TLS reverse proxy, ledger/shots backups, and someone watching `curiator stats` weekly. **What it
answers before phase 1:** real hosting cost per feedback→fix cycle,
how often reverts are actually needed, and whether strangers' feedback breaks the task-bundle
assumptions.

**Phase 1 — self-serve accounts + quotas.** Open signup (or "Sign in with GitHub" via the existing
OIDC mode — identity dedupe plus a free reputation prior), and the quota knobs become real
(`per_user_daily`, `global_daily`). The rope is gone but every author is still identified.

**Phase 2 — anonymous + the held pool.** The full ladder below: anonymous browsing + feedback that is
**always held** for human review, the moderation queue in the shell + `curiator queue` CLI, per-IP
submission limits. Core moderation status/CLI is now present; the hosted anonymous intake, admin shell
queue view, per-IP limits, and quota degradation still remain.

## Design (each piece lands on an existing seam)

1. **Mixed anonymity** — `auth.allow_anonymous: true` alongside `mode: local|oidc`: browsing + feedback
   work logged-out (recorded as anonymous), login upgrades identity. Today `local`/`oidc` gate feedback
   entirely; this relaxes the gate without losing provenance for those who do sign in.
2. **The dispatch ladder** — a per-tier policy the loop consults before waking the agent:
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
   Over-quota items degrade to `held` with an honest ⚙ note ("queued — the daily agent budget is
   spent"), not a silent drop.
3. **The moderation pool** — ledger status `held` and the headless CLI are landed:
   `curiator queue list|approve|reject` reviews held items; approve → `new` (dispatches normally),
   reject → `rejected` with an audit note. Remaining: a shell queue view (admin-gated, like /settings)
   and the hosted anonymous-feedback path that creates held items automatically. Approval is admission
   control, distinct from the existing `awaiting_approval` (which is the *agent* asking a human about a
   *plan*).
4. **Admin operations** — `curiator revert` already exists (git-as-memory makes every run one
   revertible commit). `curiator user disable <email>` / `enable` now toggles a `disabled` flag in the
   local store; header/OIDC revocation belongs to the IdP. Still to add for later anonymous phases:
   per-IP submission rate limiting for anonymous feedback (same sliding-window pattern as the login
   limiter).
5. **Trust promotion** — v1 is manual: an admin adds an account to the trusted group
   (`curiator user add <email> --groups trusted` is already an upsert). v2 can *derive* "established"
   from the ledger — account age + accepted-fix count, which `curiator stats` already computes the
   material for — rather than storing a reputation score anywhere.
6. **Anonymous screenshots: capture only.** The 📷 capture of the live app is fine (it renders the
   app's own DOM); the arbitrary-file **upload** button is disabled for anonymous users — uploads are
   a separate abuse/injection channel and the pool reviewers shouldn't have to moderate images.

## Deployment shape — a pattern, not a rearchitecture

curIAtor stays single-tenant: the unit is still **one container per public collection** (SECURITY.md's
blast-radius boundary), the agent inside it on `auto-small` or `propose-only`, `git: {commit: true}` so
admins hold a working revert lever, deny-lists on. The playground is that same unit plus the dispatch
ladder — not a multi-tenant SaaS. If several collections go public, "agent pools" = one shared worker
budget across their loops (fairness + a global cap); that's v2, per-collection quotas are v1.

## v1 scope

**One velvet-gated playground collection**: [`galleries/curiator-geometry`](math-geometry-collection.md)
(now scaffolded) — deterministic, dataless, zero-toolchain, the cheapest to babysit, and its audience
(researchers/educators) is exactly who to invite first. `curiator-aviato` or `curiator-ot` as a second
playground only after the moderation load is understood. Phases 1–2 follow the rollout above; nothing
in phase 2 gets built until phase 0 has run with real invitees.

## Honest risks

- **Moderation labor is the real cost.** The pool needs humans; for anonymous users the reply latency
  *is* the reviewer, not the agent — say so in the UI ("queued for review"). Per-IP rate limits keep
  the pool small enough to review daily.
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
