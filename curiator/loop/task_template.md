# Feedback loop — the standing task (what to do on each wake)

The loop: `feedback_watch.sh` runs in the background and **exits when there is new
feedback** (a `status:"new"` non-system entry in `feedback/app_feedback.json`). The
harness then re-invokes Claude. On each wake, do the following, then **relaunch the
watcher** (`run_in_background: ./feedback_watch.sh`) so the loop re-arms.

## On each wake

1. **Read the new feedback.** Load `feedback/app_feedback.json`; for each entry with
   `status:"new"` and `kind != "system"`, read the comment, stars, and any
   `screenshot` (Read the PNG under `feedback/shots/`).
   - **Quick-approval macros:** a bare reply of `A`/`B`/`C`/`Yes`/`No` (or `yes`/`no`) on a thread
     whose latest ⚙ note is `awaiting_approval` came from the approval BUTTONS in the feedback UI —
     treat it as selecting that option of the pending plan (same as a typed "let's try A").
   - When you post an `awaiting_approval` ⚙ note offering options, pass `actions=[["A","A"],["B","B"],…]`
     (or `["Yes","yes"],["No","no"]`) to `app_shell.add_system_note(...)` so the buttons render
     reliably; if omitted, the UI parses A/B/C or Yes/No from the note text as a fallback.

2. **Triage each comment:**
   - **Positive / no-action** ("nice", ★5, "favorite") → mark `done`, post a brief `⚙` ack.
   - **Clear + small + low-risk** (an unambiguous, well-scoped tweak) → in **auto-small
     mode** only: make the change, **smoke-test** (import/build + HTTP 200 + render the
     touched views), restart the app + the shell, mark `done`, post a `⚙` note of what
     changed. In **propose-only mode**: instead post a `⚙` plan and set `awaiting_approval`.
   - **Substantive / ambiguous / multi-option** → **never auto-execute.** Post a `⚙`
     proposed plan (with options + a recommendation), set `awaiting_approval`.

3. **Always:**
   - Post the `⚙` reply via `app_shell.add_system_note(key, text, reply_to=[id])`.
   - Update status via `app_shell.set_status(key, [id], status)`.
   - **Leave code changes UNCOMMITTED** (for review).
   - If an app's code changed, restart it + the shell (8200) so the change is live.

4. **Relaunch the watcher** and stop (the turn ends; next wake is the next new feedback).

## Guardrails (do not skip)

- **Plan-then-approve for anything substantive** — the user approves before a real
  code change. Auto-execute only clearly-scoped low-risk fixes, and only in auto-small mode.
- **Smoke-test before declaring done** — a failed build/HTTP/ render ⟹ revert + report,
  never leave an app broken.
- **No auto-commit.**
- **Verify, don't assert** — actually run the check; green code you wrote ≠ green code that ran.

## Modes

- **propose-only** (default for unattended): execute nothing; propose plans for all
  actionable items, ack positives. Safest.
- **auto-small**: additionally auto-execute clearly-scoped low-risk fixes (+ smoke-test).

## Stop

Kill the `feedback_watch.sh` background task. It just stops re-arming; nothing else changes.
