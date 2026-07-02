# curIAtor OSS — extraction scope (hack → shippable v0)

> Companion to `AI_GALLERY_OSS_DESIGN.md` (the *what/why*). This is the *how/sequence*: a
> concrete plan to lift the shell + feedback + loop out of this research repo into a minimal
> standalone OSS project. Grounded in an inventory of the actual files (2026-06-28).

> **Name — LOCKED 2026-06-28: `curIAtor`** (curator + IA; also reads as *creator + curator* — the IA
> both *creates* the fix and *curates* the collection). Identifiers: brand **curIAtor** · repo
> `LearnedResponse/curiator` · PyPI `pip install curiator` (free) · CLI `curiator` · skill `curiator`.
> Easter egg: the deliberately-broken demo app the curator has to rescue is named **`aviato`**.

## The v0 bet (definition of done)

A standalone repo that, fresh-cloned, does this in one `make demo`:

> launch a gallery of **2–3 deliberately-imperfect toy Dash apps** → in the browser, leave a
> **★ + comment + screenshot** on one ("axis labels missing", "this is cramped") → the
> **`headless-cc` agent** reads it, fixes the app's source, restarts it, and **replies in-panel** →
> you refresh and the fix is live.

That end-to-end loop **is the product and the demo**. v0 ships exactly that and nothing more —
the goal is to learn *whether the loop lands*, before investing in the `api` adapter, multi-framework
mounts, auth, or rollback. **Scope = prove the wedge, cheaply.**

## What we KEEP nearly as-is (the ~95% that already works)

Inventory confirms the heavy lifting is done and **generic**:

| piece | file(s) | LOC | coupling | action |
|---|---|---|---|---|
| **the shell** (mount + catalog + iframe + feedback panel) | `app_shell.py` | 666 | **0 QCRS strings** | lift; cut 1 seam (below) |
| same-origin **screenshot capture** (the moat) | `shell_assets/capture.js` + `html2canvas.min.js` | ~199 KB | none | lift verbatim |
| shell CSS + mobile collapse | `shell_assets/shell.css`, `assets/mobile_responsive.js` | small | none | lift verbatim |
| **feedback API** (the agent-adapter surface) | `app_shell.py`: `load_feedback / save_entry / add_system_note / set_status / record_action / _parse_actions` | — | none | keep; it's already the contract |
| status state machine + ledger | SQLite ledger payload schema (`new → awaiting_approval → done`) | — | content only | keep schema, ship empty ledger |
| **task template / guardrails** | `feedback_loop_task.md` | 54 | references `feedback_watch.sh` only | keep content; the loop refs move to the adapter |

## What we CHANGE / ADD (the real work — 4 items)

1. **Swap the registry seam.** `app_shell.py:56` is `import all_apps_index as REG` and reads
   `REG.ALL_APPS`. Replace `all_apps_index.py` (1068 lines, 95% QCRS app data) with a tiny
   **`registry.py` loader** that reads a `gallery.yaml` (the schema already sketched in the design
   doc: `apps: [{name, mount, source, tags}]`). The shell's `load_registry()` already normalizes
   records — only its *source* changes.

2. **Generalize the mount.** Today the mount is **in-process Dash import**
   (`app_shell.py:390`: set `DASH_REQUESTS_PATHNAME_PREFIX`, `importlib.import_module(key)`,
   take `.build_app().server`). Keep that as `mount.kind: dash-inproc` (zero-config for Dash users),
   and add **`mount.kind: proxy`** (reverse-proxy/iframe to an arbitrary `cmd`+`port`) so v0 can
   honestly claim framework-agnostic even if the demo apps are Dash. (Streamlit/Gradio example is a
   *stretch* goal, not v0 gating.)

3. **Replace the watcher with the pluggable adapter.** Drop `feedback_watch.sh` (the live-CC-session
   re-invoke we're explicitly not shipping — see the design doc's mode table). Ship a small
   **`loop.py`** that watches the ledger and, on new feedback, invokes the configured adapter:
   - **`headless-cc`** (default): `claude -p` against the task template + the app's `source` path +
     the feedback bundle (comment/stars/screenshot). Subscription billing, full project context, robust one-shot.
   - **`api`** (stub interface only in v0): the Agent-SDK path + `CONTEXT.md`/knowledge-store bundle —
     **defined but not built** until the wedge is proven.
   The adapter contract is exactly the design doc's: hand it `{name, source, comment, stars, screenshot}`
   + the task template; it edits, smoke-tests, replies via `add_system_note`, returns; `loop.py` re-arms.

4. **Ship the demo + docs.** 2–3 toy Dash apps with **intentional small flaws** (cramped layout,
   missing axis label, a jarring color) so the demo has something to fix; a `make demo`; a README with
   the one-line pitch + the config schema + the autonomy/adapter dials; and a **~30-second screen capture**
   of the loop (this is the marketing artifact — it's the part people share).

## Proposed repo layout

```
curiator/
  gallery.yaml                 # the registry (apps + agent adapter + autonomy)
  shell/app_shell.py           # lifted, registry seam swapped
  shell/registry.py            # NEW — yaml loader (replaces all_apps_index.py)
  shell/assets/                # capture.js, html2canvas.min.js, shell.css, mobile_responsive.js
  loop/loop.py                 # NEW — watcher + adapter dispatch (replaces feedback_watch.sh)
  loop/adapters/headless_cc.py # NEW — `claude -p` adapter (default)
  loop/adapters/api.py         # NEW — interface + stub (Agent SDK; v1)
  loop/task_template.md        # generalized feedback_loop_task.md
  examples/dash/{aviato,app_b,app_c}.py  # toy imperfect apps for the demo (aviato = the headline broken one)
  feedback/                    # empty ledger + .gitignore for shots
  README.md  Makefile  LICENSE  pyproject.toml  # pip name: curiator
```

## Milestones (sequence + rough effort)

- **M0 — lift & strip** (½ day): copy the keep-list into the layout; delete QCRS app entries; ledger → empty; confirm the shell still boots with an empty registry.
- **M1 — generic registry + mount** (1 day): `registry.py` + `gallery.yaml`; keep `dash-inproc`, add `proxy` kind; shell reads the new seam.
- **M2 — `headless-cc` adapter** (1 day): `loop.py` watch→dispatch; `headless_cc.py` invokes `claude -p` with the task template + bundle; re-arm. **This is the risk-bearing milestone** — it's the loop.
- **M3 — demo apps + the 30-sec capture** (½–1 day): 2–3 flawed toy apps; `make demo`; record the loop. **Ship v0 here.**
- **(later) M4 — `api` adapter + generality** (multi-day): Agent-SDK path, `CONTEXT.md`/knowledge-store (graphify) bundle, propose-only+PR default, a non-Dash example, auth. *Only after the wedge is validated.*

**v0 = M0–M3, ≈ 3–4 focused days.** The pieces exist and are proven end-to-end (this session ran ~8 feedback→fix cycles), so the work is *de-coupling and packaging*, not invention.

## Explicit non-goals for v0 (deferred to M4+)

`api` adapter (built); multi-framework mounts beyond the proxy stub; auth / multi-tenant; versioning /
rollback / PR-review; a hosted offering. The design doc lists these as the obvious next layers — they
are **not** what the wedge test needs.

## Clean separation (private research stays private)

Only **generic infra** leaves: the shell, the assets, the loop, the task template, toy apps. **Nothing
QCRS** travels — the registry data, the 65 research apps, the feedback ledger content, and every brief
stay in this repo. The shell never needed to know what it displays (0 coupling), so the cut is clean.

## Decisions — RESOLVED 2026-06-28

1. ~~Name~~ → **curIAtor** (`curiator`). ~~License~~ → **Apache-2.0** (`LICENSE` + `NOTICE`).
2. ~~Dash-first vs framework-agnostic~~ → **Dash-first** (own the niche; `proxy` mount kind keeps the door open).
3. ~~Where it lives~~ → **fresh public repo `LearnedResponse/curiator`**, separate from Kwisatz.
4. ~~Distribution~~ → **both** — standalone repo (the shell) **and** Claude Code / Codex interactive shims (the loop), per the Graphify channel.

No open extraction-scope knobs remain; the standalone package has shipped under Apache-2.0.

If this scope looks right, say go and I'll start at **M0** (lift & strip into a scratch layout) — read-only on the live shell, building the standalone copy beside it.
