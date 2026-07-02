# Backlog — voice + narrated feedback (talk through the fix)

> **Status:** scoped; Tier 0 and annotation mark clock fields landed 2026-07-02. **North star:
> "narrated feedback"** — voice + annotation on a shared clock, so a review is an
> *ordered, intent-per-mark tour* the agent can follow.
> **Recommended shape: local-Whisper default** (moat-consistent, works on Linux), Web-Speech for the
> public tier only, OS dictation as the free stopgap. The comment textarea now exposes a dictation hint,
> `docs/USING_CURIATOR.md` documents OS dictation as the zero-code path, and annotation marks now carry
> optional `start_ms` / `end_ms` offsets for future transcript alignment. Composes with
> `annotated-feedback.md`, not a separate feature. Captured 2026-07-02.

## The pitch

Typing detailed feedback is the friction that keeps reviewers terse — and terse feedback is exactly
what makes the agent guess. **Let the reviewer *talk*.** The endgame isn't "dictate a comment"; it's
**narrated feedback**: hit record, draw a box while saying "this legend's cramped," draw an arrow
while saying "move it up here," and the review becomes a **timed sequence of (mark, spoken-intent)
pairs** — a guided walkthrough — instead of a static marked image plus a text blob. That's the
difference between handing the agent a picture with notes and *walking it through the fix*.

## What's there today (the pipeline + the layer it composes with)

- The feedback overlay already collects **★ + comment + `html2canvas` screenshot**, and the comment
  path flows into the task bundle (`_shot_path` / `_app_bundle` in `curiator/loop/adapters/`).
- **`annotated-feedback` has landed** (v1 burn-in + v2 DOM-mapped): marks (box / arrow / numbered pin
  / redact) with **structured metadata — normalized coords + DOM target (`elementFromPoint` →
  selector) + per-mark notes + optional mark clock offsets** — and a **replay overlay**. Voice slots
  into the *comment* channel; the next data-model step is putting transcript segments on the same
  clock.

## The three tiers (and why the privacy moat decides, not capability)

- **Tier 0 — OS dictation (zero code).** The comment box is a `<textarea>`, so macOS **Dictation** and
  Windows **Win+H** already dictate into it. Document it. Caveat: per-reviewer, OS-dependent, and
  **no turnkey Linux equivalent** — helps mac/Windows reviewers, not a Linux dev box.
- **Tier 1 — Web Speech API (~30 lines).** A 🎤 button → `SpeechRecognition` → live transcript into
  the comment. Chrome/Edge/Safari; **not Firefox**. The catch: **Chrome ships the audio to Google's
  servers** — real network egress. **Public/hosted collections only**; it violates the private/OT
  collections' no-egress stance. Also its timing is too fuzzy for the north star.
- **Tier 2 — local Whisper (the moat-consistent default).** `getUserMedia` + `MediaRecorder` → POST
  the clip to a curiator route running `faster-whisper` / `whisper.cpp` → transcript back. **On-device,
  any browser, works on Linux, zero egress**, and it's the same "a local model does the work" pattern
  curiator already runs (it shells out to a local coding agent). `tiny`/`base` models are fast on CPU
  for short clips; mic access "just works" on `localhost` (a secure context — no HTTPS needed). And it
  gives **per-segment timestamps**, which the north star requires.

## North star: narrated feedback (the shared clock)

The whole thing hinges on **one shared clock**:

1. A **record mode** starts the mic and the annotation-event log at the same instant, timestamping
   both from `t=0` (`performance.now()` zero point; audio and marks on the same timeline).
2. Draw + talk simultaneously. Annotation events already have optional mark timestamps; Whisper
   returns transcript **segments with `[start, end]`** on the same clock.
3. **Merge** the two timelines: each mark at time `t` pairs with the transcript segment(s) overlapping
   `t` → an ordered narrative
   `[(box①, "the legend's cramped"), (arrow②, "move it up here"), (pin③, "this number's wrong")]`.
4. The task bundle gains a **"Narrative" block** — ordered ①②③, each with its mark, its DOM target,
   and the exact phrase spoken while drawing it — so the agent gets **sequence and dependencies**
   ("do this, *then* this"), not a static blob. And the existing annotation **replay overlay** becomes
   a **narrated replay** (marks played back in order with the audio) — a shareable artifact in itself.

**Why Whisper is required here (not Web Speech):** the merge needs reliable per-segment timestamps to
align speech to the mark being drawn. Web Speech's interim timing can't do it. So the north star
*requires* Tier 2.

**Design-now / build-later split:** even if narrated feedback ships last, **put every mark and every
transcript segment on one shared clock in the data model now** — it's cheap to design in and expensive
to retrofit.

## Work-order

1. **Tier 0** — landed. OS dictation is documented, and the shell comment textarea exposes a
   dictation hint for the default React shell and the legacy Dash shell.
2. **Tier 2 (default)** — a curiator `/transcribe` route running `faster-whisper`; a 🎤 button that
   `MediaRecorder`-captures → POSTs → drops the transcript into the comment. Local, any browser.
3. **Tier 1 (optional)** — a Web Speech mic button **gated to public/hosted collections** (a config
   flag), never the private/OT ones.
4. **Shared-clock data model** — annotation mark timestamps landed as optional `start_ms` / `end_ms`
   fields. Transcript segments still need to join the same clock when transcription lands.
5. **Narrated feedback** — record mode → merge timelines → the ordered narrative into the ledger
   (structured) + the task bundle "Narrative" block; upgrade the replay overlay to narrated replay.
6. **Verify by running** — a spoken-while-drawing review round-trips; the agent's reply follows the
   ordered narrative and lands the marks in sequence.

## Accessibility (which wins are real — stated precisely)

- **Motor / typing difficulty → voice input** (the obvious one).
- **Imprecise pointing (tremor, low vision) → the v2 DOM-target snapping.** A coarse gesture resolves
  to the element under it, so you don't need *pixel* precision — gesture roughly, speak, and still get
  an element-precise, machine-readable item. Strongest inclusion lever, and already half-built.
- **Narrated replay → an accessible artifact** — hear the ordered story instead of parsing a marked
  image.
- **Honest boundary:** this helps **low-vision + motor** substantially; a *fully blind* reviewer on a
  visual app is a harder, separate problem (the app itself must be screen-reader-navigable, and the
  feedback would be about semantics, not pixels) — not claimed here.

## Guardrails

- **No egress for private/OT.** Whisper runs **local**; Web Speech (which sends audio to Google) is
  **public-collections-only**, config-gated. Audio for a private collection must never leave the box.
- **Client-side capture on a secure context** — `localhost` qualifies, so mic works without HTTPS;
  prompt for mic permission once.
- **Additive / opt-in** — typing still works; voice and record-mode are optional. Never a regression
  to the plain comment path.
- **Burned image + transcript stay the primary agent channels** — the structured narrative is
  provenance + ordering on top, never a replacement for the marked image or the text.

## Why curiator / dogfood payoff

Narrated feedback is **only possible in a same-origin, self-hosted overlay**: the shared clock across
mic + DOM-targeted annotations, and a *local* transcription model, are exactly what a generic
screenshot/voice tool can't assemble. It's the same "local model does the work" pattern curiator
already has (it shells to a local coding agent — Whisper is its transcription sibling), and it's a
**core overlay feature every collection gets at once**. First test: talk-through a fix on the finance
apps and watch two metrics — the **first-try fix rate** (does ordered intent-per-mark beat a static
blob?) and the **friction of giving detailed feedback** (do reviewers say *more* when they can talk?).
