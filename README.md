<div align="center">

<h1 align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
    <img src="docs/logo.svg" alt="curIAtor" height="56">
  </picture>
</h1>

### Your Dash apps have a curator now.

A self-hosted gallery for your team's Dash apps — **star, comment, and screenshot** any of them
right in the browser, and an **AI coding agent reads the note, fixes the app, and replies.**
The feedback loop your dashboards never had.

`pip install curiator`

[![CI](https://github.com/LearnedResponse/curiator/actions/workflows/ci.yml/badge.svg)](https://github.com/LearnedResponse/curiator/actions/workflows/ci.yml)
&nbsp;[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
&nbsp;![Python](https://img.shields.io/badge/python-3.10%E2%80%933.12-blue)

[Quickstart](#quickstart) · [How it works](#how-it-works) · [Where the AI runs](#the-agent-and-where-it-runs) · [Why not just…?](#why-not-just-)

</div>

---

<!-- docs/demo.gif is recorded per docs/DEMO_SCRIPT.md (`curiator demo-up`, then hit record). Drop the file at docs/demo.gif. -->
![demo](docs/demo.gif)

> *Above: `aviato` loads in the gallery — cramped, no axis labels. You drop a comment + screenshot
> ("clean up the layout"). The curator edits the source, reloads the app, and replies. You refresh;
> it's fixed. ~20 seconds, no terminal.*

## The problem

You have a pile of internal dashboards — Dash apps for the sales team, a cohort explorer, three
one-off analyses someone built last quarter. They're scattered across a dozen ports, half of them
are a little broken, and there's **no channel for "hey, this axis is unlabeled"** that doesn't end
in a Slack thread and a context-switch. Feedback dies; the apps rot.

Coding agents can fix this stuff in seconds now — but they're wired to your *editor*, not to the
**live app someone is looking at.** curIAtor wires those two ends together.

## How it works

```
   ┌───────────────────────────────────────────────────────────────┐
   │  one origin · /app/<name>                                     │
   │  ┌────────────┐   ┌──────────────────┐   ┌────────────────┐   │
   │  │  catalog   │   │   the live app   │   │    feedback    │   │
   │  │ (sidebar)  │   │  (in an iframe)  │   │ rate·shot·note │   │
   │  └────────────┘   └──────────────────┘   └───────┬────────┘   │
   └──────────────────────────────────────────────────┼────────────┘
                                                      │ new feedback
                                                      ▼
                                          watcher ──> agent (claude -p / API)
                                                      │ reads note + screenshot + source
                                                      │ edits → smoke-tests → reloads
                                                      ▼
                                                * replies in the panel
```

1. **One gallery, one origin.** Every app mounts at `/app/<name>` behind a single server. (That
   same-origin trick is also what makes the next part possible — you can't screenshot a cross-origin
   iframe.)
2. **Feedback lives in the chrome, not the app.** The ★ / comment / **one-click screenshot** panel
   wraps *around* each app — so you never touch an app's source to collect feedback on it. It lands
   in a JSON ledger.
3. **The curator acts.** New feedback wakes an AI coding agent with the comment, the screenshot, and
   the app's source path. It triages, makes the fix (or proposes a plan), smoke-tests it, reloads
   the app, and **replies right in the feedback panel.** You refresh and see it live.

## Quickstart

```bash
pip install curiator
curiator init my-collection      # scaffold a collection repo (gallery.yaml + apps/ + a sample app)
```

…or point it at existing apps in `gallery.yaml`:

```yaml
apps:
  - name: aviato                       # your app's URL becomes /app/aviato
    mount: { kind: dash-inproc, module: aviato }   # or kind: proxy, cmd/port for anything
    source: ./apps/aviato.py           # what the curator edits
    tags: [sales]

agent:
  adapter: headless-cc                 # headless-cc (default) | api | command
  autonomy: auto-small                 # auto-small (fix small things) | propose-only (plan first)

feedback: { dir: ./feedback, screenshots: true }
```

```bash
curiator up           # serves the gallery at http://127.0.0.1:8300
curiator watch        # arms the feedback→fix loop  (or `curiator serve` to run both at once)
```

Open the gallery, star/comment/screenshot an app, and watch the curator reply. To run it in a
container (one sandbox per collection), see [`docs/USING_CURIATOR.md`](docs/USING_CURIATOR.md).

## The agent, and where it runs

curIAtor is **bring-your-own-agent** — it's the harness that wires live-app feedback to whatever
coding agent you already have. Pick the adapter that fits your setup:

| adapter | billing | project context | scales to a team? | best for |
|---|---|---|---|---|
| **`headless-cc`** *(default)* | your Claude subscription | full — loads `CLAUDE.md` + memories + skills | no (one machine) | **solo / small, self-hosted** |
| **`api`** | per-token (Anthropic API / Agent SDK) | inject a `CONTEXT.md` / knowledge store | **yes** | **shared teams / hosted** |
| **`command`** | whatever you wire | yours | depends | aider / Codex / a script |

> **Model- and provider-agnostic.** curIAtor is the harness, not the brain — you bring the agent CLI,
> and it holds the model/provider choice. Run Claude Code on Anthropic, Bedrock, Vertex, or an
> Anthropic-compatible gateway; or `command`-adapter into Codex / aider / any CLI pointed at
> OpenAI-compatible or local models (Ollama, vLLM, LM Studio, LiteLLM). Nothing in curIAtor to change.

…and the **autonomy dial** decides how much it does on its own:

- **`auto-small`** — auto-applies clearly-scoped low-risk fixes (after a smoke-test); proposes a plan
  for anything substantive. Great on your own box.
- **`propose-only`** — never edits unprompted; every change is a plan you approve (and, on the `api`
  adapter, a PR you review). The right default for a shared team.

> **Teams:** pair the `api` adapter with a project knowledge store (e.g. [Graphify](https://github.com/shamsi/graphify))
> so the cold agent fixes with *fresh* repo context instead of a stale snapshot. curIAtor collects the
> feedback and runs the loop; the knowledge store supplies the context. They compose; they don't overlap.

## Why not just…?

- **…Streamlit Cloud / HF Spaces / Posit Connect / Retool?** Those are galleries — they host and
  share apps. None of them has an **AI-maintenance loop**: point at a flaw, get a fix.
- **…aider / Claude Code / v0 / Bolt?** Those are coding agents — they're **build-time**, wired to
  your editor. None of them is wired to a **live-app feedback collection** your whole team can drop
  notes into.

curIAtor is the **wiring + the convention** between the two. That's the whole idea — thin to adopt,
thin to maintain.

## Status

**v0 (Dash-first).** Shipping: the gallery shell + same-origin screenshot feedback + the
`headless-cc` loop + the `aviato` demo. The `api`/team adapter, non-Dash mounts beyond the proxy
stub, auth, and PR-review/rollback are on the roadmap — once the loop has earned it. Self-hosted,
single-tenant: your box, your apps, your agent, your blast radius.

## The name

**curIAtor** = **curator + IA** (*inteligencia artificial*) — and, if you say it out loud,
**creator + curator**, which is exactly what it is: the IA both **creates** the fix and **curates**
the collection.

> The deliberately-broken app in the demo is named **`aviato`**. If you know, you know. 🛩️

## License

**Apache-2.0** (see `LICENSE` + `NOTICE`). Contributions are accepted under the
[DCO](https://developercertificate.org/) — sign off your commits with `git commit -s`. See
[`CONTRIBUTING.md`](CONTRIBUTING.md).

---

*Recording the launch demo? See [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) for the 30-second beat-sheet.*
