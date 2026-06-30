# Backlog — general app hosting (any framework, multi-file apps)

> **Status:** design note. **Reframed 2026-06-29 — this is *not* an expansion past Dash; it *realizes*
> what the overlay already is.** Near-term: build the **one non-Dash proof** (it's what shows what
> curiator actually is). v1: full generality + scaffold templates.

## The reframe: the overlay *is* the product

The **feedback overlay** — the gallery chrome that wraps an app in a same-origin iframe and collects
★/comment/**screenshot** + drives the loop — **doesn't care what's inside the iframe.** It already works
for Dash, React, Svelte, static HTML — anything served same-origin. So "works for designing *any* app"
isn't a feature to add; it's what the overlay **already is.** *Dash is content, not the product.*

That leaves exactly **one framework-specific seam: the mount** (how an app is served under the shell's
origin). `dash-inproc` is a convenience for one content type; **`proxy` is the universal mount.** Design
guardrail: **keep the overlay / feedback / loop 100% framework-agnostic; isolate every framework-specific
line in the mount.** (Mostly already true — the shell is generic; the Dash-coupling lives in the in-process
mount.)

And **Dash is a *ceiling*** for general app design: server round-trips for interaction, the Plotly/Dash
component library (custom UI ⇒ writing React anyway), constrained styling, no full web platform. Great for
data/HMI dashboards; a hard ceiling for *designed, interactive* apps, where React/Svelte blow past it. So a
Dash-only product **undersells what curiator is** ("AI-maintained *Dash* gallery" vs "AI-maintained *app*
gallery, any framework").

## The goal

Today an app is a **single Python module** mounted **in-process** (`dash-inproc`). That's perfect for the
Dash niche, but it caps two things people will want:

1. **Framework flexibility** — let agents build/maintain **React / Svelte / Vue / plain static** apps,
   not just Dash. Dash is great for data/analysis/HMI dashboards; JS frameworks open the full
   interactive-UI design space.
2. **Multi-file apps** — drop the single-file constraint; an app can be a **directory** (components,
   assets, a build, data). Single-file works for simple Dash; it breaks immediately for React/Svelte
   (inherently multi-file project) and for any non-trivial app.

These are one direction: **curiator as an "AI-maintained *web app* gallery," not an "AI-maintained *Dash*
gallery."**

## The design (both fall out of pieces already foreshadowed)

**Framework flexibility = the `proxy` mount** (already deferred in `DESIGN.md`). JS apps aren't
Python-importable; they're built/dev-served. So curiator **reverse-proxies** `/app/<name>/*` to the app's
own server — a Vite dev server, a static build, any process:

```yaml
apps:
  - name: pnl-board
    mount: { kind: proxy, cmd: "npm run dev -- --port {port}", port: 8700 }
    source: apps/pnl-board/          # a DIRECTORY, not a file
```

**The load-bearing constraint:** the proxy must preserve **same-origin** (path-mounted under the shell's
origin, *not* an iframe to a different host) — otherwise the html2canvas screenshot, the whole feedback
moat, breaks. Same-origin reverse-proxy is the requirement; iframe-to-another-port is not acceptable.

**Multi-file = `source` accepts a directory.** The registry/mount already resolve a `source`; let it be a
dir. For `dash-inproc`, point at the entrypoint module within the dir; for `proxy`, run `cmd` with the dir
as cwd. The agent's **task bundle gets the app directory** (it can edit any file inside), and
**git-as-memory groups by app**: one feedback → one commit, even if it touches several files in the dir.

## The "React/Svelte plugin/wrapper" question — answer: don't build per-framework plugins

The instinct to add a "React plugin" / "Svelte wrapper" is the wrong shape. The generic **`proxy` mount +
a directory + a `cmd`** already hosts *any* framework — there's nothing React-specific to integrate. What's
actually worth building is **scaffolding templates**, not plugins:

```
curiator init-app pnl-board --framework svelte    # scaffolds apps/pnl-board/ + the gallery.yaml entry
```

i.e. a thin `create-vite`-style scaffolder per framework (dash / static / react / svelte / gradio /
streamlit), each emitting a directory + the right `mount` block. Plugins = lock-in + maintenance; templates
+ the generic proxy = leverage. Stay generic at the mount, opinionated only at scaffold time.

## Honest scoping & sequencing

- **This realizes the thesis; it doesn't expand it.** The overlay is already general — so the *one
  non-Dash proof* (a Svelte/static app in the frame) is a **near-term fast-follow**, not far-backlog,
  because it's what demonstrates what curiator actually *is* (a Dash-only demo undersells it). *Full*
  generality (all frameworks + templates) is v1, demand-paced — the example demos (finance/OT) will
  surface the asks.
- **Directories-per-app can land earlier and cheaper** than full JS support — even Dash apps benefit from a
  multi-file dir (helpers, assets, data). That's a small registry/mount/task-bundle change with no new
  toolchain, and it's the prerequisite for everything else. Reasonable to do *first*, independent of
  React/Svelte.
- **Full JS support is the heavier lift** — it pulls in a Node/npm build toolchain, the proxy mount, and a
  different agent edit/smoke-test loop (the agent edits `src/`, runs the build/dev server; smoke-test = the
  build succeeds + renders, not Python import-and-render). The agent has the JS competence; the *loop
  plumbing* is the work.

## Tradeoffs / open questions

- **Same-origin under proxy** with framework dev servers (HMR websockets, base-path handling) — Vite/Next
  need the public base path set so assets resolve under `/app/<name>/`. Solvable, but per-framework
  fiddly; the scaffold templates should bake in the right base-path config.
- **Smoke-test for a build step** — `auto-small` "smoke-test before commit" means *the build passes + the
  app renders*; needs a per-mount-kind smoke hook (Python import vs `npm run build`).
- **Static-export synergy** — JS apps are *already* static-buildable, so this direction and the deferred
  static-publish target reinforce each other (a built React app **is** the static export).
- **Where does it stop?** Hosting arbitrary processes is powerful but widens the security/sandbox surface
  (the curation tier already auto-runs code; arbitrary frameworks widen it). Keep the
  one-container-per-collection blast-radius model.

## Recommended path (when the time comes)

1. **Directories-per-app first** (cheap, no toolchain; unblocks everything).
2. **The `proxy` mount + same-origin reverse-proxy** (the framework-agnostic substrate; also proves the
   "any framework" claim with one non-Dash example).
3. **Scaffold templates** (`curiator init-app --framework …`) — the ergonomic layer, generic not plugin.
4. JS-specific niceties (HMR base-path, build smoke-test) per framework as demand warrants.

Dash-first is the *launch wedge* (ship fast, own the data/HMI audience), **not the identity** — keep the
overlay framework-agnostic from day one and treat the non-Dash proof (steps 1–2) as a near-term
fast-follow once v0 ships, since it's what shows curiator is an *app* gallery, not a Dash gallery.
