# Completed backlog items

Retired work-orders, kept for provenance. The backlog previously had no way to *retire* an item - the
loop advances items but nothing marks them done, so shipped work sat next to unstarted work
indefinitely. This folder is that missing mechanism.

## When an item retires here

An item lands here when its work-order is **fully delivered and verified** - not merely started, not
"core landed" with follow-ons still open. Retiring is a **deliberate act** (an editor, or the loop when
it can verify the whole work-order is met), which is the point: it forces a decision that the work is
actually done.

## Convention (so the loop can follow it)

1. **Move the file here unchanged** - keep its Status blockquote as the final record of what shipped.
2. **Move its index line** in `../README.md` from its section to the **## Shipped** list, appending
   `- shipped <short-commit>`.
3. **Don't delete.** Retirement is not deletion. The git log is curIAtor's build story, but a commit says
   *what changed*, not *what we were trying to do*; these files are the intent behind the history - the
   "why" the `reflect` summaries point back to.

## Not yet done (don't retire prematurely)

An item that's "core landed" but still has open follow-ons stays in the live backlog with its status
updated. Examples as of 2026-07-02: `annotated-feedback` and `voice-feedback` have shipped cores but
open follow-ons; `cli-modularization` is started (4 of 8 seams). None retire yet.
