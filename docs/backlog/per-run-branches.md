# Backlog — per-run branches + in-app approval (an example)

> **Status:** implemented and dogfooded locally 2026-07-10, with runner implementation committed as
> `a3f64f4`; retirement remains gated on publishing and off-machine materialization of the example's two
> repositories. This remains an **opt-in example**, not a change to the default
> flow. The default is now `git.branch: null` — commit straight to `main`, use the log (see
> [DESIGN.md -> "The default gate and opt-in per-run proposals"](../DESIGN.md)). This item is the "grown-up
> app" tier: a per-run feature-branch flow with an **Approve** button *in the app*, for the case where a
> collection has a real accepted-state boundary worth gating. Realizes the "branching/merging UI"
> deferred in DESIGN.md.

## The flow (as proposed)

1. Each agent run works on its own **feature branch off `main`** (`git.branch: per-run` → a fresh
   `curiator/run/<feedback_id>` per task).
2. When the run finishes, the live app shows **that branch's** version, with an **Approve** button in
   the feedback panel.
3. **Approve → merge the branch into `main`** → it becomes the canonical/live state.
4. If a new task starts before approval, it **also branches off `main`** (not off the pending branch).
   The live preview follows the newest branch, so the earlier un-approved branch is **backgrounded**
   (shelved, not visible) — effectively reverted from the live view without being lost.
5. Approving a backgrounded branch later **merges it into `main`**, and its changes reappear.

This is, cleanly stated: **each run is a PR against `main`; `main` is the accepted state; approval is
async and happens in-app; the live view previews the latest open PR.** That's coherent and a natural fit
for the "propose, don't auto-apply" posture.

## Does it make sense? Yes — with one rule nailed down first

The make-or-break detail is **what happens when two open branches touch the same app** — curIAtor's most
common pattern is iterating *one* app across successive feedback.

- **Independent runs (different apps/files):** clean. Both merge fine, order-independent. The flow works
  exactly as described.
- **Same app, overlapping edits (the hazard):** because each run forks from `main` (not from the previous
  open branch), branch 2 does not contain branch 1's work. Two consequences:
  - The "backgrounding" is **lossy by construction** — while branch 1 is pending and branch 2 (off
    `main`) is live, branch 1's edits are invisible. Fine as a *preview* semantic.
  - The bite is at **merge, not reappearance**: if branch 2 is approved first (so `main` now holds
    branch 2's version of the file), approving branch 1 later is a **merge conflict**, not a clean
    "it shows up again" — git can't reapply divergent edits to the same lines from a common base.

So "approve the old one later" is only well-defined once you pick a **same-app policy**:

- **(a) Supersede (recommended default):** a new run on an app auto-closes older *open* proposals for
  that same app. "Backgrounded" = rejected. Matches the intuition that the newest agent take wins; simple;
  right for UI iteration. This is the flow as the user described it.
- **(b) Rebase-and-reconcile:** approving a proposal rebases it onto current `main`; on conflict, re-run
  the agent to reconcile (it has the feedback + both diffs). Keeps both, at the cost of a reconcile step.
- **(c) Stack:** new runs branch off the *latest open branch*, not `main`, so they build on pending work.
  No divergence, but there's no "backgrounding" — the opposite of the proposed flow.

**Sweet spots** where the flow shines regardless: independent parallel proposals, and **pick-one-of-N**
(generate 3 variants of one app, preview each live, approve one — the losers are discarded branches).

## What it needs (the real build cost)

- **Per-branch live preview** — the shell must render an app from an *arbitrary branch*, not just the
  working tree. That means **git worktrees** (one per open proposal) and the mount serving a selected
  worktree, keyed by proposal. This is the heavy lift; everything else is bookkeeping.
- **Approve → merge** wired to the existing approval buttons (`awaiting_approval` + `actions` already
  exist in the panel) — the button triggers a fast-forward/merge into `main` instead of a status flip.
- **Proposal registry** — track open proposal branches per app (branch, base SHA, status), derived from
  refs, not a side store (keep dbt's principle: git is the record).
- **Conflict surfacing** — on a non-FF merge, apply the same-app policy: auto-reject (supersede) or
  re-dispatch the agent to reconcile; never silently clobber.

## Scope / guardrails

- **This is the "grown-up app" tier**, not the default. Throwaway/research apps stay `git.branch: null`
  on `main`. Reach for per-run branches when an app has a defended accepted-state (a versioned artifact,
  external dependents, or an atomic-rollback need) — i.e. an app that has **graduated to its own subrepo**
  (`curiator app import` preserves its `.git`; git-as-memory already commits inside nested repos).
- Build it as a third `git.branch` mode (`per-run`) so it's opt-in and composes with the existing policy
  block; don't special-case the loop.
- Ship it as a **public example collection** demonstrating the approve-in-app loop before promoting the
  mode to a documented feature.

## Landed evidence

- `curiator/proposals.py` owns worktree preparation, source-scope checks, Git-ref state, smoke-gated
  finish, superseding, approval, rejection, and conflict aborts. No proposal table was added to SQLite.
- The task builder remaps only the selected app to its worktree and pins the canonical `--gallery`
  reply path. Shared-component writes are refused in this mode rather than escaping branch isolation.
- The React shell exposes a compact Proposal preview banner. Its existing action channel recognizes
  proposal actions separately from ordinary reply macros and requires an admin identity.
- `curiator proposal list|approve|reject` exposes the same lifecycle for CLI operators; doctor verifies
  `git.commit`, the accepted branch, and app Git ownership.
- The recommended **supersede** policy is implemented: a successfully prepared newer same-app run
  rejects the older open proposal while retaining its branch. Tests also prove that proposals in two
  independent app repositories remain live simultaneously.
- `galleries/curiator-proposals@8515e44` and its nested counter app at `b41c57dd` contain the real
  dogfood thread `d5a3e1e7`: accepted `898f66d`, proposal `8f71a955`, zero-console branch preview,
  one safely aborted approval that exposed missing Git identity, then successful in-shell merge and a
  second zero-console browser proof from canonical state.

## Remaining publication gate

The local collection intentionally uses a nested app repository/gitlink to exercise the grown-up app
case. The collection repo and nested app repo must both be published, and clone/materialization wiring
must be validated from a different machine before this work-order is retired as a public example. This
is release operations, not missing proposal behavior; do not flatten or hide the two-repository proof.
