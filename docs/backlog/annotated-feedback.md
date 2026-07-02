# Backlog — annotated screen captures (point the agent at the element)

> **Status:** v1 burn-in landed 2026-07-01; core v2 structured annotation metadata/replay/editing
> landed 2026-07-02. Headless marked-feedback seeding via `curiator feedback add
> --annotations-json|--annotations-file` and YAML `curiator seed` is available; broader browser→agent
> dogfood validation is still open.
> A core feedback-overlay upgrade: draw on the captured screenshot so feedback points at exactly the
> element it means.
> Captured 2026-06-30.

## The pitch

Today a feedback item is **★ + a text comment + a full-page `html2canvas` shot**, and
the agent has to *infer* which element "the legend is cramped" refers to. Spatial
ambiguity is the single biggest source of the agent fixing the wrong thing. Let the
reviewer **draw on the frozen capture** — box, arrow, numbered pin, redact — and the
feedback points at the element it means. It's how humans already hand off design
feedback (Figma comments, marked-up screenshots), brought inside the feedback→agent loop.

Two tiers, and the second is the one only curiator can do:

- **v1 — burn-in (front-end only).** Composite the drawing into the PNG. The vision
  model reads a marked-up image directly and unambiguously, and the task bundle already
  says *"screenshot (Read this PNG)"* — so annotation **rides the existing pipeline with
  zero backend/loop change**.
- **v2 — DOM-mapped (the differentiator).** Because the overlay is **same-origin** with
  the app, resolve each annotation back to the DOM element under it
  (`document.elementFromPoint`) → selector + component hint. The agent then gets a
  **code-locating** pointer, not just a visual one — the thing a standalone screenshot
  annotator (Markup, CleanShot) fundamentally cannot produce.

## What's there today (the pipeline it rides)

- The overlay captures with `html2canvas` (shell = `curiator/shell/app_shell.py`).
- The shot lands in the feedback ledger and its path flows into the task bundle via
  `_shot_path` / `_app_bundle` in `curiator/loop/adapters/__init__.py`, which tells the
  agent: *"screenshot (Read this PNG): `<path>`"*.
- The agent Reads that PNG. **v1 changes only what the PNG contains** — not how it flows.

## Work-order — v1 (burn-in)

1. **Freeze-then-draw** — landed. After capture/upload, the feedback panel shows a small annotation
   toolbar: **box · arrow · numbered pin · redact · undo · clear**. Annotation is optional; a plain
   screenshot still saves normally.
2. **Composite to one PNG** — landed. `composeShot` renders annotations onto the captured image before
   the POST, so the mark is *in* the pixels the model reads.
3. **Redact burns in *before* the PNG leaves the browser** — landed. The redact tool paints an opaque
   rectangle into the exported PNG.
4. **Store as the screenshot** — landed. The composited PNG uses the existing `screenshot` field, so
   `_shot_path`, task bundles, and loop code stay unchanged.
5. **Element-relative coordinates** — landed for v1. Draw coordinates are normalized against the
   captured image/canvas, not the viewport.
6. **Verify by running** — partially covered by asset/parser tests and a repeatable headless seeding
   path (`curiator feedback add ... --annotations-json`, or `curiator seed` with `annotations:`).
   Still dogfood with a real browser-marked feedback item such as "fix the ①-marked legend" before
   calling the broader v2 item complete.

## v2 — DOM-mapped annotations (follow-on)

1. **At draw-time, resolve the target** — first pass landed for the React shell. For non-redaction
   annotations, `document.elementFromPoint` under the mark captures a sanitized target hint
   (`selector`, `tag`, nearest `id`/`data-testid`, `role`, classes). Same-origin failures degrade to
   a mark without a target.
2. **Structured annotations in the ledger** — first pass landed. The saved entry carries sanitized
   normalized coordinates plus optional target metadata alongside the burned PNG; redaction marks
   intentionally omit targets.
3. **A small "Annotations" block in the task bundle** — landed for app, General collection, and runner
   feedback bundles, including optional per-mark notes, e.g.
   *"① box → `#revenue-chart .recharts-legend`: too cramped."* Agent gets the marked image
   **and** the code anchor.
4. **Per-mark note lines** — first pass landed: every mark gets a compact optional note input, and
   non-empty notes ride with the structured annotation into the ledger/task bundle.
5. **Richer annotation replay/editing** — second replay surface landed: prior-feedback threads and the
   General collection home show compact structured annotation summaries with per-mark notes and
   DOM targets, and saved annotated entries can open a scrollable preview modal showing the burned
   screenshot plus the structured mark list. A replay overlay now redraws saved boxes, arrows,
   redactions, and pins from normalized coordinates on top of the preview image. The modal can switch
   into an editable-copy view, then load that screenshot and adjusted mark set into the reply composer;
   historical ledger entries stay immutable.
6. **Graceful fallback** — landed in the React shell. Same-origin DOM lookup is attempted only when
   the mounted iframe document is readable and exposes `elementFromPoint`; redactions, uploads, and
   unreadable/cross-origin mounts still save burned-in marks and structured coordinates, just without a
   DOM target.

## Guardrails

- **Burned image stays the primary channel.** The vision model reads it directly;
  structured annotations are provenance + DOM anchor, never a replacement for the mark.
- **Redaction happens client-side, pre-export.** The ledger and git are durable — sensitive
  pixels must never leave the browser.
- **Element-relative coords** (survive re-render/replay); don't pin to the viewport.
- **Additive, not a regression.** The existing plain-screenshot feedback path must keep
  working untouched; annotation is opt-in.
- **Same-origin gate for v2** — degrade to burn-in/coordinates-only for cross-origin mounts, don't
  error.

## Why curiator (the differentiator)

The DOM-mapping is uniquely enabled by **same-origin** — turning a pixel-pointer into a
code-pointer is exactly what a generic screenshot annotator can't do, and it's "the
product is the overlay" paying off again. It's also the shortest path to a more accurate
fix: the agent stops guessing which element you meant.

## Dogfood payoff

This is a **core overlay feature, not a per-collection one** — every collection
(`curiator-finance`, `curiator-ot`, `curiator-phylogenetics`, the demos) benefits the
moment it lands. First test: use it on the finance apps ("① this axis label, ② move the
legend here") and watch whether the agent's fix lands on the right element on the first
try. Expect it to sharply cut the "fixed the wrong thing" rate — the metric to watch.
