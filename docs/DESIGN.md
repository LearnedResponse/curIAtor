# curIAtor — AI-maintained app gallery (OSS design sketch)

> **Name LOCKED 2026-06-28: `curIAtor`** (curator + IA; also *creator + curator*) · repo `LearnedResponse/curIAtor` · `pip install curiator` · skill `curiator`. Extraction receipt: [`docs/EXTRACTION_SCOPE.md`](EXTRACTION_SCOPE.md).

> ⚠️ **Orthogonal to the math program.** This started as a design note for extracting the viewer
> shell + feedback + loop into a standalone open-source project. It has
> nothing to do with the positive-geometry research; it's parked here because the code it
> describes lives in this directory. Captured 2026-06-26 · updated 2026-06-28 (agent-adapter / deployment modes; graphify as complementary knowledge store).

## The idea (one line)

A self-hosted gallery for a team's interactive web apps, with **in-context feedback that an AI
coding agent acts on** — comment (+ screenshot) on the live app, the agent fixes the deployed
thing and replies. *AI-maintained app collections.*

**The product is the overlay, not the framework.** The feedback chrome wraps an app in a same-origin
iframe and acts on ★/comment/screenshot — so it works for *any* app (Dash, React, Svelte, static — anything
served same-origin). **Dash is the first supported mount, not curiator's identity.** Keep the
overlay/feedback/loop framework-agnostic; the only framework-specific seam is the *mount* (`dash-inproc`
today, `proxy` the universal one). See `backlog/general-app-hosting.md`.

## Why OSS, not a company

The two hardest "product" problems both **dissolve** in the self-hosted single-tenant framing:
- **Isolation / multi-tenancy** — non-issue: you run it on your own box, your own trusted apps.
- **Trust in the auto-edit loop** — it's *your* code, *your* agent, *your* blast radius.
Those are only scary when a SaaS must do it for strangers, safely. OSS sidesteps both. It's also
naturally **BYO-everything**: bring your apps, your coding agent (Claude Code / aider / Cursor CLI
/ a script), your API key. The project is the *harness that wires a live-app feedback collection
to whatever agent you already have* — thin to maintain, thin to adopt.

## Architecture (generalized from what we built)

1. **Shell / mount.** Serve every app at one origin under `/app/<name>`. The overlay shell is
   Flask + React; `dash-inproc` is just one mount adapter using the `DASH_REQUESTS_PATHNAME_PREFIX`
   env trick (edit-free), while `proxy` is the framework-neutral path.
   *generic* version is a reverse-proxy (or iframe) to an arbitrary port/command — framework-agnostic.
2. **Catalog.** A registry → a sortable/filterable list (by tag · rating · recency · open-feedback).
3. **Feedback in the SHELL CHROME, not the app.** The key framework-agnostic insight: the
   ★/comment/**same-origin screenshot** panel wraps *around* the app in the iframe, so you never
   touch an app's source to collect feedback on it. Works for Dash / Streamlit / Gradio / React /
   a notebook / anything. Persist to a SQLite ledger (+ screenshots, task bundles, and run traces).
4. **Watcher → agent adapter.** A file-watcher fires when new feedback lands and invokes a
   **configured agent command** with a task template: read the feedback (text + screenshot + which
   app + its source dir) → propose-or-fix → smoke-test → reply in-panel → leave a diff. The only
   app-specific step is the *edit*, which is the agent's job against the source — so the harness
   stays generic.

## Config / registry schema (sketch)

```yaml
apps:
  - name: snc-explainer
    mount: { kind: command, cmd: "python snc_explainer.py", port: 8111 }   # or kind: proxy/url
    source: ./snc_explainer.py        # what the agent edits
    tags: [genus, explainer]
agent:
  adapter: headless-cc                 # headless-cc | api | command (BYO) — see "Agent adapter / deployment modes"
  cmd: "claude -p {task_file}"         # for adapter: command — receives the task template + context paths
  autonomy: auto-small                 # auto-small | propose-only — default keyed to adapter (below)
  context:
    bundle: ./CONTEXT.md               # required for api (cold start); optional for headless-cc
    knowledge_store: graphify          # optional: a live index (e.g. graphify) → keeps the bundle FRESH
feedback: { dir: ./feedback, screenshots: true }
```

## Agent-adapter contract

On each new-feedback fire, the harness hands the agent: the app `name`, its `source` path(s), the
feedback `comment` + `stars` + `screenshot` path, and a **task template** encoding the guardrails
now shipped as `curiator/loop/task_template.md`: triage → auto-do clearly-scoped low-risk fixes
(+ smoke-test + restart) / propose plans for substantive ones (`awaiting_approval`) / ack positives;
post a reply via the ledger; leave a diff or a git-as-memory commit according to the collection's
`git:` policy; never push. The agent returns; the harness re-arms the watcher.

## Agent adapter / deployment modes

How the loop *powers* the agent is the main deployment axis — and it's not the binary it looks
like. There are **three** points, and the one we prototyped (a live attended Claude Code session
re-invoked by `feedback_watch.sh`) is the **worst to ship**: it's tied to a live session's
lifecycle (the watcher-reaping fragility this very build hit — `exec`-detach got the tracked task
reaped on idle), it's single-user, and it's harness-specific. Ship the other two.

| adapter | billing | context (memory / CLAUDE.md / skills) | robustness | fits |
|---|---|---|---|---|
| ~~live attended CC session~~ | subscription | full | **fragile** (session can die; single-user) | prototype only — don't ship |
| **`headless-cc`** (`claude -p`) | subscription | full — loads CLAUDE.md + memories + skills (one-shot, *in the project dir*) | robust one-shot | **solo / small self-hosted** |
| **`api`** (Anthropic API / Agent SDK) | per-token | **cold** — none unless injected | robust, scales, multi-user | **large shared team / hosted** |

**The middle dominates the live session.** `claude -p` headless keeps the subscription economics
*and* the auto-loaded project context, with none of the live-session fragility — so it's the
**default** adapter and the frictionless "free with your Max sub" adoption story.

**Scale picks the adapter AND the autonomy default together:**
- **Solo / small, self-hosted** → `headless-cc` + `auto-small` (your box, your trusted apps, your blast radius).
- **Large shared team** → `api` + `propose-only` + **PR-for-review** — routing a team's feedback
  through one personal Max sub is both rate-limited and ToS-shaky, so a team wants its own API
  billing, per-request permissions, and human-reviewed diffs instead of auto-edit.

**The context-bundle convention (the `api` cold-start tax) — where graphify composes in.** A cold
API agent has no memories, so the `api` adapter must be handed a context bundle per fix: the target
app's source + a curated `CONTEXT.md` / `LESSONS.md` + the task template. A **static** bundle goes
stale fast (the same snapshot-rot the rest of this design avoids), so for teams the bundle should be
backed by a **live project knowledge store** — e.g. **graphify as a complementary skill**: the agent
queries the graph for the relevant slice of repo/docs *at fix-time* instead of reading a frozen file.
The two projects compose cleanly and don't overlap:
- **gallery shell** = collects the *feedback* + runs the *loop* + makes the *edit*;
- **graphify (or any indexer)** = supplies the *fresh project context* the cold agent needs;
- the `headless-cc` path gets context for free (it's already in the repo); the `api`/team path leans
  on the knowledge store so the agent isn't fixing blind.

This is also where graphify's own "reflect → `LESSONS.md`" pattern lands: the loop's accumulated
"this fix worked / that one was a dead end" feeds back into the store, so the agent stops repeating
mistakes across runs — the team-scale substitute for the per-session memory the headless path enjoys.

## How a collection consumes the runner

The runner (this package) is generic; **your apps are content in a separate "collection" repo** — a
`gallery.yaml` + an `apps/` dir + a pinned `curiator`. The `examples/dash/` apps here are demo content
only; real apps never live in the generic repo (that's what keeps it generic).

**Three ways a collection consumes the runner:**

| model | how | generic stays clean? | PR-back |
|---|---|---|---|
| **A — dependency** *(default)* | collection pins `curiator`; `curiator up/watch` read your `gallery.yaml` | ✅ zero runner code in your repo | runner PRs made in a separate checkout — clean diffs |
| **B — clone & run** | sandbox clones curiator, drops apps inside | ⚠️ apps+runner share a repo; upstream pulls conflict | needs a strict `apps/`-only convention |
| **C — template + upstream** | create-from-template, merge upstream for updates | ✅ at start, drifts | merge/cherry-pick friction |

**Recommend A + an editable escape hatch.** Default: pin the package. To improve the runner while
dogfooding, either `pip install -e ../curiator` from a sibling checkout or keep the collection as a
nested repo under `curiator/galleries/<collection>` with `runner: {mode: checkout, path: ../..}`.
Both layouts keep the apps repo's git history separate while letting runner edits land as tracked
diffs against the generic repo. A runner improvement is then always a self-contained diff against the
generic repo, never entangled with anyone's apps. **Keep the public surface small + stable** (the
`gallery.yaml` schema + the adapter interface + the CLI) so configs survive runner upgrades and runner
PRs need know nothing about apps.

**The sandbox (Docker / VM + persistent storage).** The reason to sandbox is the core safety story:
*the curator auto-edits AND runs code.* So the unit is **one container per collection**:
- image = `python + curiator` (pinned) + the `claude` CLI (headless-cc) or API creds (api);
- mounted volume (persistent) = the collection repo — apps, `gallery.yaml`, the `feedback/` ledger
  (history survives restarts), and a `LESSONS.md` the agent accumulates about *your* apps (the context
  bundle the `api` adapter needs);
- two processes: `curiator up` + `curiator watch`; expose the gallery port.

This maps onto the deployment modes above: a **personal container** (headless-cc, `auto-small`) vs a
**shared/hosted container** (api, `propose-only` + PR). The container *is* "a team's collection."

**Runner-aware General channel — the "suggest improvements to the tool itself" loop.** Feedback splits
in two: feedback on an *app* → the curator edits your app source (always works); feedback on the
*runner* (the `◆ General` / `__general__` bucket, or on the shell chrome itself) → the curator would
edit curiator's own code. That only yields a *tracked, contributable* change when curiator is a **git
checkout** — Python's `site-packages` source is mutable but **untracked and blown away on upgrade**, so
patching it there is a dead end. So the General channel's *action* keys off the install mode:

| runner install | General-channel feedback on the runner → |
|---|---|
| **editable checkout** (early / contributor) | curator **patches the runner locally** (tracked) → you PR it upstream |
| **pinned package** (mature / consumer) | curator **drafts an upstream issue/PR** — the feedback becomes a *contribution*, not a local edit |

`gallery.yaml` can carry `runner: { mode: checkout|pinned, path: ../curiator }` for sibling layouts or
`runner: { mode: checkout, path: ../.. }` for nested `galleries/<collection>` layouts, so the channel
knows which behavior to use. It **degrades gracefully**: early you run the checkout and the runner is
fair game; as it stabilizes you pin the package and the *same gesture* switches from "local patch" to
"file upstream" — no up-front decision about whether you'll ever need generic mutability. Bonus: with
the checkout, **curiator maintains curiator** — feedback on the shell chrome patches the shell. Good
dev loop, good README story.

## Git as the memory

The lineage here is Karpathy's **autoresearch** (a human steers via a markdown prompt; a headless agent
edits the *real source* and **commits successful tweaks via git** — the commit log *is* the record of
what was tried) and, before it, **dbt** (analytics-as-code-in-git; the DAG is *derived from `ref()`
links*, never hand-maintained; `dbt test` is the gate; `dbt docs` renders the graph *for humans*). Same
shape every time: **declarative source-of-truth in git → a derived view for humans → an eval gate → the
git history as the record.** curiator should sit in that lineage.

Concretely, flip the default from "leave the fix uncommitted" to **every agent run → one commit** — and
the commit captures the *whole* state transition: the **source edit (if any) *and* the feedback-ledger
update ride in the same commit**, so even a `propose-only` plan or a positive-feedback ack produces a
(ledger-only) commit. Nothing the curator does is off the record. The **git log becomes the durable,
queryable, revertible memory** of every action. The branch these land on is your **sandbox/dev
environment** (dbt-style); promotion to dev/main is a later CI/CD step (see below). Three layers, not
one:
- **git = episodic memory** — the diffs: *what* changed and *why*, one commit per fix.
- **the ledger = the conversation** — the ★/comment/⚙ thread. The linked git history carries the
  commit IDs so the ledger does not need a self-referential post-commit mutation.
- **`LESSONS.md` = distilled memory** — a `curiator reflect` step summarizing recent `curator(*)`
  commits, which each fresh one-shot then loads (cross-item learning without a live session).

**The commit *is* the record** — structured + machine-queryable:
```
curator(<app>): <one-line summary>

Feedback: "<comment>"   (★<n>)
Changed: <what was edited>      Smoke-test: <result>

Curiator-App: <app>
Curiator-Feedback: <id>
Co-Authored-By: <agent model>
```
The trailers make the log a query surface: `git log --grep "Curiator-App: aviato"` = everything the
curator ever did to that app; `git revert <sha>` = undo with the record intact.

### Binding practices for the curator agent

These are **not optional** — they live in `task_template.md` and every adapter enforces them. They are
what make "commit freely" safe and keep the memory trustworthy:

1. **One feedback item → one atomic commit.** No batching unrelated changes, no drive-by edits.
2. **Edit only the feedback's target source.** Nothing else in the tree.
3. **Smoke-test *before* committing.** Never commit a broken app; a failed test ⇒ revert + report, no commit.
4. **Structured message + trailers** (above) + attribution (`Co-Authored-By`, and `Signed-off-by` where the project uses the DCO).
5. **Commit only — never `push`, never merge to main, never force-push, never rewrite published history** (no `amend`/`rebase` of commits you didn't just make).
6. **Undo with `git revert`, never `reset --hard` / force** — preserve the record.
7. **Keep the ledger clean after committing.** The SHA is printed and queryable from git trailers; do
   not mutate the SQLite ledger after the commit just to stamp the hash back into the reply.

### The gate (now) and branching (deferred)

The safety gate is **the human reviews the git log and merges to main** — *merge-to-main is always a
human action.* For now that review happens in plain git (outside the UI): commits land on
`git.branch` (default a `curiator/auto` branch; `HEAD` for the trusting your-own-box case), and you
`merge`/`cherry-pick` what's good. A `git:` block in `gallery.yaml` carries the policy
(`commit: bool` — default `false` = today's leave-uncommitted; `branch`; `signoff`), so it's **opt-in
per collection** (a standalone collection runs `commit: true`; the QCRS instance, living in a repo with
its own conventions, keeps `commit: false`).

**Deferred to a later milestone:** a *branching/merging UI* — review/approve/merge curator commits from
the gallery itself, per-app branches, one-click PR creation. We don't need that machinery yet; the
binding practices above are exactly what make it safe to build on later. The principle stays dbt's:
**never maintain the graph — derive it from the refs; git is the record, not a separate store.**

## Scaling: serving and curation are two independent tiers

The deployment-modes table above (personal / team / hosted) flattens a thing that's actually **2-D**.
The real architecture has **two tiers that scale on different axes:**

- **The serving tier** scales with *users*. It can be as cheap as **static / CDN** (Pyodide-exported
  apps, infinite scale, near-zero cost, and — the part that matters — **no backend to attack**). The
  only public-facing backend is a thin **feedback-ingest** endpoint that drops items on a queue.
- **The curation tier** is a **bounded pool of agents** (private infra) draining that queue
  *asynchronously*. It scales with *how much improvement you want to buy* — **not** with traffic.

Between them: the **feedback ledger is the work queue**, and **git-as-memory is the deploy pipeline**
(agents commit to the sandbox/dev branch → prioritized changes merge to main → CI redeploys the serving
tier, static export or server). Read path and write path, cleanly decoupled.

**The pool is an optimizer, not a help desk.** It doesn't FIFO-drain every ticket — it **triages the
backlog** (dedup similar requests, weight by frequency/recency/authority) and spends its fixed capacity
on the **highest-value** changes; it can even search *proactively* (autoresearch-style, with feedback as
the objective signal). So the same loop that fixes one axis label is, at scale, a bounded improvement
engine pointed at a public app's UX.

**Why this is the whole point — cost decouples from traffic.** A viral demo does **not** explode your
agent bill: traffic scales the *cheap* tier (CDN/stateless servers) and lengthens the *queue*; the
expensive thing — agents — stays a **flat curation budget** (N agents, M improvements/day). You size the
pool to *"how fast do I want this to get better,"* not *"how many users do I have."* The naive
"one agent per request" design conflates those two; decoupling them is the win. So the deployment knobs
are independent: **serving tier (static ↔ scaled servers) × curation tier (off ↔ bounded pool).**

*(The Pyodide static-export **mechanism** is deferred — it's app-specific, leans on a converter recipe,
not one-click. But the architecture above is the target; static serving + a private bounded pool means
a public app can quietly improve over time without ever exposing an agent.)*

### Identity, reputation, and access (IAM) — the curation tier's input

"Pick the highest-value change" needs a **trust signal**, and that signal is *who* gave the feedback.
So once you go multi-user, feedback must be **tied to an authenticated identity**, and identities carry
**weight** — by role/authority and by track record. Three layers:

- **Authentication: delegate it** (the BYO philosophy again — bring your IdP: OAuth/SSO/GitHub/Google,
  or a token allowlist for self-hosted). curiator should not build a login system.
- **Authorization: curiator's** — roles gate *who can do what* (owner/maintainer can approve+merge and
  set priorities; contributor can suggest; public can only file feedback).
- **Reputation: derived, not maintained** (dbt again) — a per-user weight **computed from the
  git-as-memory record**: how many of their suggestions became commits, and of those, how many were
  **kept vs reverted** (a kept-rate / value score), plus static priors (role, and *domain match* — your
  feedback on the app whose data you own weighs more). The curation pool's prioritization is then
  `weight(user) × signal(frequency, recency, stars)` — a **trust-weighted objective**, which is just a
  better-aimed version of the autoresearch loss.

**How to delegate it (when the time comes): OIDC, not a vendor.** Standardize on the **protocol**
(OpenID Connect) and every IdP plugs in — Keycloak, AD/Entra, Okta, Auth0, Google, GitHub — so the IdP
is a config detail, not a choice baked into curiator. **Keycloak is the reference default**: open-source,
self-hostable, and an identity *broker* (it federates to AD/LDAP/Google/GitHub upstream), so "Keycloak in
front of AD" covers the enterprise case through one integration. And the cleanest integration builds
**zero auth code in curiator** — put an **auth proxy at the edge** (`oauth2-proxy` / your ingress /
Keycloak's gatekeeper, a sidecar in the Docker model) that runs the OIDC dance and passes a **trusted
identity header** (`X-Auth-Request-User` + groups); curiator just reads it and stays auth-agnostic. A
`gallery.yaml: auth:` block (`mode: none | header | oidc`, default `none`) selects it; direct OIDC via a
library is the fallback for those who don't want a proxy. The three layers then map onto it cleanly:
**authN** = the IdP (verified identity), **authZ** = curiator roles **driven by IdP group claims**
(AD/Keycloak groups → roles, so access is managed in the directory, not the app), **reputation** =
curiator's, derived from the git-as-memory record on top of that identity.

**Scale-gated, like the other modes:** the **self-hosted single-tenant v0 needs none of this** (it's
you, your box — identity is implicit), which is a feature, not a gap. IAM + reputation land exactly when
the curation tier goes multi-user/public — same boundary as the `api` adapter and the static-export
target. Build it then; the git-as-memory record is what makes reputation *computable* rather than
hand-curated when you do.

## Extraction status (our hack → shippable v0)

The original extraction checklist is now mostly landed:

- [x] Decoupled from the math repo and from Dash as identity: the default shell is Flask + React,
      `proxy` is the universal mount, and `dash-inproc` is one adapter.
- [x] Made the loop **agent-pluggable** through configured adapters and task templates:
      `headless-cc`, `codex`, `command`, and `api` are separate paths, with repo-local skill/command
      install for interactive work.
- [x] Added a registry schema + loader and public-shaped non-Dash proofs: React/Node SSR, Rust HTTP,
      Vite-family scaffolds, Streamlit, Gradio, FastAPI, Flask, static, and Dash app directories.
- [x] Kept the same-origin capture model while replacing the legacy JSON ledger with a SQLite runtime
      source of truth plus screenshots, task bundles, replies, threaded feedback, run traces, the
      General/history view, and collapsible overlay drawers.
- [x] Added README, task template, autonomy/security docs, release runbook, and app/galleries CLIs.
- [ ] Before public launch: publish the example collection repos, configure PyPI/Zenodo, refresh paper
      evidence from those published repos, and rerun the loop from a machine that is not this one.
- [ ] Future layers: branch/merge/PR UI, heavier Docker/Compose orchestration, team-scale API context
      bundles, reputation/trust automation, and higher-fidelity capture options beyond the current
      browser-native fallback.

## Landscape / differentiation

Galleries (Streamlit Cloud, HF Spaces, Posit Connect, Hex, Retool) have **no AI-maintenance loop**.
Coding agents (aider, Claude Code, v0, Lovable, Bolt) are **build-time**, not wired to a live-app
feedback collection. The novelty is the **wiring + convention**, not any single piece — exactly the
shape of a good small infra project. Honest wedge: narrow it (one framework + one audience, e.g.
"AI-maintained data-team dashboards") and nail the feedback→fix loop with great safety, rather than
going horizontal.

## Honest gaps / risks

- The harness is generic; the **agent's ability to turn "this is cramped" + a screenshot into the
  right edit** is the real capability bet (BYO-agent punts this to the user's agent, fairly).
- Restart/redeploy orchestration per app (we hand-restart processes) needs a clean supervisor.
- Versioning / rollback / PR-review of agent changes is the obvious next layer for any real use.
- Source artifacts are now package code rather than session-local files: `curiator/shell/`,
  `curiator/shell/assets/`, `curiator/loop/`, `curiator/ledger.py`, and `curiator/cli.py`.
