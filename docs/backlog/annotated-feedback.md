# Backlog — annotated screen captures (point the agent at the element)

> **Status:** scoped, not started. A core feedback-overlay upgrade: draw on the
> captured screenshot so feedback points at exactly the element it means.
> **Recommended shape: v1 burn-in first, v2 DOM-mapped as the follow-on.**
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

1. **Freeze-then-draw.** After capture, freeze the `html2canvas` image in the overlay and
   show a small annotation toolbar: **box · arrow · numbered pin (①②③) · redact · undo ·
   clear**. Keep it dismissible — annotation is optional; the plain-screenshot path stays.
2. **Composite to one PNG.** Render the annotation layer onto the captured image and
   export a single PNG (the mark is *in* the pixels the model reads). Numbered pins let
   the comment say "① move this, ② too small" with the numbers on the image.
3. **Redact burns in *before* the PNG leaves the browser.** The redact tool paints an
   opaque rectangle into the export, so nothing sensitive ever reaches the ledger or git.
4. **Store as the screenshot.** The composited PNG replaces/augments the current
   screenshot field — **no change to `_shot_path`, the task bundle, or the loop.**
5. **Element-relative coordinates.** Store draw coords relative to the *captured element*,
   not the viewport, so they survive re-render/replay.
6. **Verify by running.** A marked-up feedback item round-trips; the agent's reply
   references the marked element correctly (diff a "fix the ①-marked legend" item).

## v2 — DOM-mapped annotations (follow-on)

1. **At draw-time, resolve the target.** For each annotation, `document.elementFromPoint`
   under it → capture `{selector, tag, nearest id/data-testid, component hint}`.
2. **Structured annotations in the ledger** alongside the burned PNG (provenance + replay).
3. **A small "Annotations" block in the task bundle**, e.g.
   *"① box → `#revenue-chart .recharts-legend`: too cramped."* Agent gets the marked image
   **and** the code anchor; numbered pins ↔ per-pin comment lines.
4. **Graceful fallback.** Same-origin only (already the screenshot moat's requirement); for
   a cross-origin proxy iframe, fall back to burn-in-only for that mount.

## Guardrails

- **Burned image stays the primary channel.** The vision model reads it directly;
  structured annotations are provenance + DOM anchor, never a replacement for the mark.
- **Redaction happens client-side, pre-export.** The ledger and git are durable — sensitive
  pixels must never leave the browser.
- **Element-relative coords** (survive re-render/replay); don't pin to the viewport.
- **Additive, not a regression.** The existing plain-screenshot feedback path must keep
  working untouched; annotation is opt-in.
- **Same-origin gate for v2** — degrade to burn-in for cross-origin mounts, don't error.

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
