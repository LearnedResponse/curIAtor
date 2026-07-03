# Backlog — OT / HMI-maintenance example collection (flagship demo)

> **Status:** scaffolded 2026-07-01 in nested repo `galleries/curiator-ot`. A flagship cross-domain
> example and one of the three collections in the [public release](../public-release.md). Captured
> 2026-06-29. **v1 scope cut (2026-07-01): no MING
> stack in v1.** The sim writes straight to a lightweight local historian (SQLite/parquet); the full
> Mosquitto → Telegraf → InfluxDB compose moves to v2. Rationale: the curator never touches the data
> path — the entire rainbow→ISA-101 story lives in the Dash layer, so four infrastructure containers buy
> OT authenticity, not story, and must not gate the release. Sequence AFTER v0.2.0 ships — building this
> collection dogfoods the interactive `link/work/done` workflow in that batch.

## The pitch

A rough, "rainbow" HMI over a simulated process that curiator drags toward **High-Performance-HMI /
ISA-101** from operator feedback — *the git log is the HMI going from alarm-flood clutter to
situational-awareness-first.* MING substrate, Dash as the HMI the agent edits, fully
open-source/reproducible. Reuses the seeded-feedback / self-building / git-as-receipt mechanism from
the finance collection.

Why it's the flagship: HMI design quality is an **acute, underserved, expensive** OT pain (rainbow
mimics, alarm floods, no situational awareness — the exact thing ISA-101 / High-Performance-HMI exists
to fix and most plants never get to). "An agent that drags your HMI toward HP-HMI from operator
feedback" is a pitch the OT crowd feels in their bones.

## Work-order

1. **Scaffold `galleries/curiator-ot`** via `curiator init galleries/curiator-ot --git` — done: standalone collection, `runner.mode: pinned`
   for public-clone portability, **`git: {commit: true}`** (the build story is the deliverable),
   `auth:` set so operator feedback is
   attributed, and repo-local `.agents/skills/curiator/SKILL.md` / `.claude/commands/curiator.md`
   installed for interactive agent sessions. Linked from the curiator README as the flagship demo.
2. **The process sim** (`sim/process.py`) — a canonical **tank-level control loop**: a tank with inlet
   valve + outlet pump under a **PID level controller**, plus temperature/flow tags. A ~1 Hz loop
   writing tags (`level`, `flow_in`, `flow_out`, `temp`, `pump_status`, `valve_pct`, alarm states)
   **straight to a lightweight local historian (SQLite/parquet)**, with **seeded + scripted
   disturbances** so trends move *deterministically* — done for SQLite historian v1.
3. **The data path — v1 is deliberately boring:** sim → local historian → HMI, plain processes, no
   brokers, no compose. **v2 = the MING compose** (Mosquitto → Telegraf → InfluxDB; Node-RED optional as
   the alarm-logic glue; Grafana replaced by the curiator-maintained HMI) for full OT authenticity once
   the story is proven — the demo narrative is byte-identical either way, so infrastructure never gates
   the release.
4. **The HMI** (`apps/overview.py`, Dash, reading from the historian) — **deliberately the "rainbow"
   anti-pattern**: saturated colors everywhere, a busy P&ID-ish mimic, gauges with no normal-band, no
   setpoint markers, an unprioritized alarm list, tiny status dots — done as the rough baseline.
5. **Seeded operator feedback** (`seed/feedback.yaml`, authored as an operator/control-engineer) —
   ~8–12 items that drag it to **HP-HMI/ISA-101**: *"everything's brightly colored — I can't see what's
   abnormal; make the screen grey, reserve color for alarms," "the level gauge needs a setpoint marker +
   a shaded normal-operating band," "embed a 1-hour sparkline next to level and outlet flow," "prioritize
   the alarm list, banner the highs, suppress the chattering lows," "pump status should be a clear state
   indicator, not a green dot," "declutter — this is a Level-2 operating display, not an engineering
   drawing."* **This is where Adam's domain expertise plugs in — must read like a real operator.**
   Initial 10-item queue is present.
6. **Run the loop to generate the story** — `curiator seed && curiator watch`: the curator evolves the
   HMI fix-by-fix, **committing per fix** with `Feedback-From` trailers → an HP-HMI **and** a git log
   that *is* the rainbow→ISA-101 trajectory.
7. **Verify by running** (not asserting): the sim produces live data; the HMI mounts + reads from the
   historian; the seeded feedback actually transforms it (diff rough→improved); the git log shows the arc
   with provenance; a fresh `curiator up` serves the improved HMI.

## Current checks

- `curiator status` / `curiator context --app overview` work against `galleries/curiator-ot/gallery.yaml`.
- `curiator doctor` against `galleries/curiator-ot/gallery.yaml`: passing, no errors or warnings.
- `curiator smoke` against `galleries/curiator-ot/gallery.yaml`: passing; smoke regenerates deterministic
  historian data and imports/builds the Dash HMI.
- Direct import/build check: `overview.build_app()` exposes a layout and reads historian rows.
- `galleries/curiator-ot` is initialized as a git repo on `main` with seed commit `6c5e2d6`; the current
  `curiator/auto` head is `36e21cf`, which migrates the Codex shim from `.codex/skills` to
  `.agents/skills` and switches the public collection to `runner.mode: pinned`.
- Seeded feedback loop is complete on `curiator/auto`: 10 curator commits (`6e587f2`, `a7009b1`,
  `3296486`, `92ab145`, `278d058`, `c158f24`, `d802b8d`, `41bdc43`, `2fecda4`, `ba71d88`) cover the
  meta git-log receipt item plus all nine HMI cleanups (neutral color discipline, setpoint/normal band,
  prioritized alarms, one-hour sparklines, pump-state indicator, Level-2 operating state, alarm
  rationalization, historian freshness, trend palette). No seeded operator feedback remains open.
- `curiator release-preflight --gallery curiator-ot --fresh-clone --json`: passing at `36e21cf`; the
  temp clone runs `python scripts/smoke.py`, regenerates deterministic historian data, and imports/builds
  the HMI cleanly.
- Reading the OT feedback history no longer dirties the committed SQLite ledger after the core
  read-only ledger-open fix.

## Guardrails

Reproducible only (seeded sim, no flaky feeds); open-source stack (**no Ignition/WinCC licensing** in
the public demo); it's a *simulation* — no real control/PLC/safety claims; `git: commit:true` (the
history is the product) but **never push**; scope = sim+Dash (v1; MING compose in v2), one process, an
overview screen (+ maybe one detail).

## Platform spectrum (roadmap, not scope)

- **Sim + Dash (v1) → MING + Dash (v2)** — this demo (public, reproducible).
- **Ignition (Perspective)** — later: the agent edits *JSON view configs* instead of code, more credible
  to real SCADA shops, demo-able on the Maker/trial edition.
- **WinCC OA** — Adam's *credibility/narrative* asset (he dockerized it at Siemens), not a shippable
  public demo.

## Dogfood payoff

Different from finance: this is the first **live-data, real-time** app (the HMI reads a ticking
historian at ~1 Hz) — it stress-tests curiator's shell-cache/reload-on-edit semantics against a
live-updating app in v1, and the Docker/sandbox multi-container model at v2. Expect it to *find*
curiator bugs; that's the point.
