# Backlog — general app hosting (any framework, multi-file apps)

> **Status:** design note, not started. A **post-v0 / v1** direction — it deliberately broadens the
> Dash-first stance, so it waits until the Dash v0 ships and demand shows. Captured 2026-06-29.

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

- **This broadens past Dash-first** — so it's **post-v0**, after the niche v0 ships and someone actually
  asks for non-Dash. Don't pre-build the generality; let demand (likely surfaced *by the example demos* —
  finance/OT) prioritize it.
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

Stay Dash-first until v0 has shipped and a real ask appears; then this is the order of operations.
