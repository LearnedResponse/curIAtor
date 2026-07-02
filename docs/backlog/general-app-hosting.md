# Backlog — general app hosting (any framework, multi-file apps)

> **Status: core landed & proven in the wild (2026-07-01) — what's left is ergonomics + visibility.**
> App directories, multi-endpoint `mounts:`, the same-origin `proxy` mount, and `curiator app create`
> scaffolds (dash/static/python/node/flask/fastapi/rust/react/svelte/vue/next/streamlit/gradio) are in the runner, and the **non-Dash proof now exists**:
> `curiator-aviato` runs a React/Node SSR app and a Rust HTTP server through `proxy` mounts next to
> Dash, with per-root smoke commands — the loop closed on all of them. Remaining backlog: framework
> template hardening beyond the first React/Svelte/Vue/Next/Flask/FastAPI/Rust/Streamlit/Gradio scaffolds, heavier Docker/Compose
> orchestration — and **surfacing the proof**, which is now the cheapest highest-leverage step: the
> proof is private/local until [public-release](public-release.md) publishes `curiator-aviato` and links
> it from the README. **Reframed 2026-06-29 — this is *not* an expansion past Dash; it *realizes* what
> the overlay already is.**

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
actually worth building is **scaffolding templates**, not plugins. The initial command is:

```
curiator app create pnl-board --template dash     # scaffolds apps/pnl-board/ + the gallery.yaml entry
curiator app import https://github.com/me/lab-viewer.git lab_viewer --template react
```

i.e. a thin `create-vite`-style scaffolder per framework (currently dash / static / python / node /
flask / fastapi / rust / react / svelte / vue / next / streamlit / gradio), each emitting a directory + the right `mount`
block. Existing repos follow the same template contract via `app import`: the source is copied/cloned
into `apps/<name>` with its own `.git/` intact, while the template registers only the mount/smoke/preview
metadata. When git-as-memory handles a source-changing run against one of those imported app repos, it
commits the app repo first and then records the collection ledger plus updated gitlink. Plugins =
lock-in + maintenance; templates + the generic proxy = leverage. Stay generic at the mount, opinionated
only at scaffold/import time.

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
- **Screenshot fidelity beyond Dash** — the ★/📷 moat rides on html2canvas, which struggles with
  canvas/WebGL and some modern CSS that JS frameworks reach for. The browser-native `getDisplayMedia`
  fallback now exists for signed-in reviewers, and upload remains the manual fallback; server-side
  Playwright/Chromium capture is still the heavier deployment-specific option. Do not patch fidelity
  per framework.
- **Smoke-test for a build step** — `auto-small` "smoke-test before commit" means more than "this
  Python module imports." Scaffolded apps carry explicit per-template smoke commands, and no-smoke
  proxy directories now get conservative inferred checks for obvious Python/Node/Rust servers.
  `curiator smoke --http` can also start proxy apps briefly and verify an HTTP response, using
  `smoke_http` when a collection pins a health path. Full browser-level "the app renders" smoke
  remains a heavier, demand-paced check.
- **Static-export synergy** — JS apps are *already* static-buildable, so this direction and the deferred
  static-publish target reinforce each other (a built React app **is** the static export).
- **Where does it stop?** Hosting arbitrary processes is powerful but widens the security/sandbox surface
  (the curation tier already auto-runs code; arbitrary frameworks widen it). Keep the
  one-container-per-collection blast-radius model.

## Recommended path (when the time comes)

1. **Directories-per-app first** (landed).
2. **The `proxy` mount + same-origin reverse-proxy** (landed as a lightweight localhost proxy; still needs
   framework-specific templates/build ergonomics).
3. **Scaffold/import templates** (`curiator init-app --template …`, `curiator app import … --template …`) — Node's dependency-light HTTP scaffold,
   Flask's server-rendered scaffold, FastAPI's API-backed ASGI scaffold, and Rust's dependency-light HTTP scaffold are available for small server-side prototypes; first pass landed
   for React/Svelte/Vue via Vite proxy mounts and for Next.js via a prefix-preserving proxy mount,
   including build smoke hooks, `CURIATOR_APP` base-path config, and npm/pnpm/yarn/bun package-manager
   detection/override.
   Streamlit also has a first scaffold using `server.baseUrlPath`, a prefix-preserving proxy mount,
   and a generated note about the lightweight proxy's WebSocket/production limits.
   Gradio has the same first-pass shape using `root_path` and a prefix-preserving proxy mount.
4. JS/framework-specific niceties beyond the first scaffold pass: `curiator app templates` now exposes
   the scaffold/import menu with mount kind, toolchain, and intended use so users and agents do not
   need to scrape parser help or docs. `commands.preview` now lands in every generated proxy scaffold,
   including static/Python, Node, Flask, FastAPI, Rust, JS, Streamlit, and Gradio entries, and appears
   in `curiator status` / `curiator context`; proxy failures now render a diagnostic page with
   command/cwd/port/target/process state plus recent stdout/stderr. WebSocket/HMR
   upgrade requests now get an explicit lightweight-proxy diagnostic instead of falling through the
   HTTP proxy path, and `curiator doctor` warns when proxy commands look like HMR-oriented framework dev
   servers or when Vite/Next/FastAPI/Gradio/Streamlit mounts are missing the base-path/root-path config
   needed under `/app/<name>/`. Doctor also warns when optional Python framework apps such as FastAPI,
   Gradio, or Streamlit lack a dependency manifest, which keeps proxy scaffolds portable before
   publication. `curiator smoke` now reports and runs cheap inferred fallback checks for no-smoke
   proxy directories when an obvious `server.py`/`app.py`/`main.py`, Node server file, or `Cargo.toml`
   is present, `curiator smoke --http` adds an opt-in proxy process + HTTP response check, and
   `curiator release-preflight --http-smoke` carries that check across nested or dependency-prepared
   publication candidates.
   `curiator app import` now surfaces the same visible warnings immediately after registering an
   existing repo, before the user first loads a broken mount. Full live-HMR reverse proxying remains
   demand-paced per framework.

Dash-first is the *launch wedge* (ship fast, own the data/HMI audience), **not the identity** — the
overlay stayed framework-agnostic and the non-Dash proof now runs (`curiator-aviato`: React SSR + Rust +
multi-mount Dash behind one shell). The fast-follow is no longer building the proof but **publishing**
it ([public-release](public-release.md)) — a private proof shows nothing.
