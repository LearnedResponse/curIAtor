<!-- internal: the recording guide for docs/demo.gif. Not the public README. -->

# 30-second demo — recording script (internal; not part of the public README)

**Goal:** the GIF at the top of the README. One unbroken take, no terminal on screen (or a tiny
corner overlay). The arc is *broken → point at it → curator fixes → fixed.* Keep it under 30s.

**Setup before recording:** `aviato.py` is a real Dash chart with three planted flaws — (1) no axis
titles, (2) the legend overlaps the plot, (3) cramped margins. `curiator up` + `curiator watch`
running. Autonomy = `auto-small`. Browser at the gallery, `aviato` selected.

| time | shot | on screen |
|---|---|---|
| 0:00–0:03 | **The gallery.** Sidebar of apps; `aviato` loaded in the center, visibly ugly. | sets the scene: "a gallery of real apps" |
| 0:03–0:09 | **Drop the note.** Click into the ★ panel, type *"axis labels are missing and the legend covers the chart — clean up the layout,"* click 📷 (screenshot flashes), Submit. Entry appears, badge = **`new`**. | the human gesture — point at the live thing |
| 0:09–0:13 | **The curator wakes.** Badge flips **`new` → `working`**. (Optional tiny corner overlay: `curiator · claude -p · editing aviato.py`.) | the magic moment |
| 0:13–0:22 | **The reply.** A ⚙ note appears in the panel: *"Added axis titles, moved the legend outside the plot, widened the margins. Restarted aviato."* Badge → **`done`**. | proof it understood + acted |
| 0:22–0:27 | **Refresh.** Iframe reloads; `aviato` now renders clean — labeled axes, tidy legend, breathing room. A subtle before/after wipe if you can. | the payoff |
| 0:27–0:30 | **Card.** `CurIAtor — your Dash apps have a curator now.` · `pip install curiator` | the close |

**Notes for the take:**
- The *screenshot* step is the signature gesture — make it visible (a flash / shutter). It's the
  thing competitors literally can't do (cross-origin), so it should read as the "wow."
- Keep the agent reply terse and concrete (what it changed) — credibility comes from specificity.
- If a clean ~10s agent turn is hard to capture live, pre-warm and trim; the *story* (point → fix)
  is what has to land, not the wall-clock.
- Title-card music optional; the SV crowd will catch `aviato` with zero help.
