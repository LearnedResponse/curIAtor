# Backlog — OT / HMI-maintenance example collection (flagship demo)

> **Status:** scoped, not started. A flagship cross-domain example (the second after `curiator-finance`).
> Captured 2026-06-29.

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

1. **Scaffold `curiator-ot`** via `curiator init` — standalone collection, `runner.mode: checkout`,
   **`git: {commit: true}`** (the build story is the deliverable), `auth:` set so operator feedback is
   attributed. Linked from the curiator README as the flagship demo.
2. **The process sim** (`sim/process.py`) — a canonical **tank-level control loop**: a tank with inlet
   valve + outlet pump under a **PID level controller**, plus temperature/flow tags. A ~1 Hz loop
   publishing tags (`level`, `flow_in`, `flow_out`, `temp`, `pump_status`, `valve_pct`, alarm states) to
   **MQTT (Mosquitto)**, with **seeded + scripted disturbances** so trends move *deterministically* —
   reproducibility is non-negotiable.
3. **The MING data path** — `docker-compose.yml`: **Mosquitto → Telegraf → InfluxDB** (the historian),
   the sim, the Dash HMI, and curiator. *(Node-RED optional as the alarm-logic glue for full-MING
   authenticity; Grafana is replaced here by the curiator-maintained HMI.)* Provide a **no-Docker dev
   path** too (sim as a plain process → a local/lightweight historian → the HMI) so components are
   verifiable without a full stack — the full `docker compose up` is the human's run.
4. **The HMI** (`apps/overview.py`, Dash, reading from InfluxDB) — **deliberately the "rainbow"
   anti-pattern**: saturated colors everywhere, a busy P&ID-ish mimic, gauges with no normal-band, no
   setpoint markers, an unprioritized alarm list, tiny status dots.
5. **Seeded operator feedback** (`seed/feedback.yaml`, authored as an operator/control-engineer) —
   ~8–12 items that drag it to **HP-HMI/ISA-101**: *"everything's brightly colored — I can't see what's
   abnormal; make the screen grey, reserve color for alarms," "the level gauge needs a setpoint marker +
   a shaded normal-operating band," "embed a 1-hour sparkline next to level and outlet flow," "prioritize
   the alarm list, banner the highs, suppress the chattering lows," "pump status should be a clear state
   indicator, not a green dot," "declutter — this is a Level-2 operating display, not an engineering
   drawing."* **This is where Adam's domain expertise plugs in — must read like a real operator.**
6. **Run the loop to generate the story** — `curiator seed && curiator watch`: the curator evolves the
   HMI fix-by-fix, **committing per fix** with `Feedback-From` trailers → an HP-HMI **and** a git log
   that *is* the rainbow→ISA-101 trajectory.
7. **Verify by running** (not asserting): the sim produces live data; the HMI mounts + reads from the
   historian; the seeded feedback actually transforms it (diff rough→improved); the git log shows the arc
   with provenance; a fresh `curiator up` serves the improved HMI.

## Guardrails

Reproducible only (seeded sim, no flaky feeds); open-source stack (Mosquitto/InfluxDB/Telegraf/Dash —
**no Ignition/WinCC licensing** in the public demo); it's a *simulation* — no real control/PLC/safety
claims; `git: commit:true` (the history is the product) but **never push**; scope = MING+Dash, one
process, an overview screen (+ maybe one detail).

## Platform spectrum (roadmap, not scope)

- **MING + Dash** — this demo (public, reproducible).
- **Ignition (Perspective)** — v2: the agent edits *JSON view configs* instead of code, more credible to
  real SCADA shops, demo-able on the Maker/trial edition.
- **WinCC OA** — Adam's *credibility/narrative* asset (he dockerized it at Siemens), not a shippable
  public demo.

## Dogfood payoff

Different from finance: this is the first **live-data, real-time** app (the HMI reads streaming tags) and
the first **multi-container** deployment — so it stress-tests curiator's reload-on-edit against a
live-updating app and the Docker/sandbox model. Expect it to *find* curiator bugs; that's the point.
