<!-- internal: the recording guide for docs/demo.gif. Not the public README. -->

# 30-second demo — recording script (internal; not part of the public README)

**Goal:** the GIF at the top of the README. One unbroken take, no terminal on screen (or a tiny
corner overlay). The arc is *broken → point at it → curator fixes → fixed.* Keep it under 30s.

**Setup before recording — one command:**

```bash
curiator demo-up        # re-breaks aviato, clears the ledger, starts the gallery + the watcher
# → gallery at http://127.0.0.1:8300   (auto-fix loop armed)
```

`demo-up` calls `reset-demo` first, so `aviato.py` starts with its three planted flaws — (1) no axis
titles, (2) the legend overlaps the plot, (3) cramped margins — and the ledger is empty. Autonomy is
`auto-small`. Open the gallery, select `aviato`. **Need another take?** Ctrl-C, then `curiator demo-up`
again (or just `curiator reset-demo` while it's running) — it's idempotent.

| time | shot | on screen |
|---|---|---|
| 0:00–0:03 | **The gallery.** Sidebar of apps; `aviato` loaded in the center, visibly ugly. | sets the scene: "a gallery of real apps" |
| 0:03–0:09 | **Drop the note.** Click into the ★ panel, type *"axis labels missing, legend covers the chart, clean up the layout,"* click 📷 (screenshot flashes), Save. Entry appears, badge = **`new`**. | the human gesture — point at the live thing |
| 0:09–0:13 | **The curator wakes.** Badge flips **`new` → `working`**. (Optional tiny corner overlay: `curiator · claude -p · editing aviato.py`.) | the magic moment |
| 0:13–0:22 | **The reply.** A ⚙ note appears in the panel — concrete and specific, e.g. *"Added axis titles (Month / Amount $k), moved the legend out to a horizontal bar above the chart, and widened the margins. Smoke-tested clean."* Badge → **`done`**. | proof it understood + acted |
| 0:22–0:27 | **Refresh.** The reply already reloaded the app server-side; refresh the browser (or re-select `aviato`) and the iframe renders clean — labeled axes, tidy legend above the bars, breathing room. A subtle before/after wipe if you can. | the payoff |
| 0:27–0:30 | **Card.** `curIAtor — your Dash apps have a curator now.` · `pip install curiator` | the close |

**Notes for the take:**
- The *screenshot* step is the signature gesture — make it visible (a flash / shutter). It's the
  thing competitors literally can't do (cross-origin), so it should read as the "wow."
- The agent reply is **auto-generated and varies run-to-run** — the wording above is representative.
  Credibility comes from its specificity (it names what it changed), so let the real text show.
- The fix goes live without a restart: `curiator reply … --status done` pokes the shell's `/reload`
  endpoint, which rebuilds `aviato` from the edited source. The human just **refreshes** to see it.
- A clean agent turn is ~20–60s. If that's long for a live take, pre-warm and trim; the *story*
  (point → fix) is what has to land, not the wall-clock.
- Title-card music optional; the SV crowd will catch `aviato` with zero help.
