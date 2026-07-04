# Backlog — OT v2: a physics digital twin under the HMI

> **Status:** active dogfood target as of 2026-07-04. Build as much local engine-backed/digital-twin
> proof as possible before public release, then mark only true toolchain/substrate blockers such as
> OpenModelica/FMU availability or licensed Simscape dependencies. OT **v1 shipped** (deterministic tank
> sim + SQLite historian + Dash
> HMI, `curiator-ot@36e21cf`). The runner now has a minimal local `engine-backed` mount primitive
> (`engine`, `engine_port`, `{engine_url}`, and engine diagnostics), so the next dogfood step is the
> OpenModelica/FMU substrate itself. v2 deepens the *substrate*: replace the hand-coded ODE with a credible
> **physics digital twin (OpenModelica)** under the same HMI the loop iterates — and turn that HMI into a
> **diagnostics/KPI surface** so feedback drives real backend work, not just layout. Captured 2026-07-04.

## The pitch

The OT flagship's credibility rests on the process *behind* the HMI. A hand-coded tank ODE is a toy; a
Modelica physics model is a real digital twin. Swap the backend, keep the loop maintaining the surface on
top — and because that surface is instrumentation, feedback on it drives the twin and the control logic,
not just pixels.

## Tech choice: OpenModelica (open) over Simscape (licensed)

**OpenModelica** — open, physics-first (acausal, equation-based), exports **FMU** for co-simulation; a
Dash/web HMI drives the FMU as the live process. Prefer it over **Simscape** (MATLAB/Simulink-licensed)
for a public/OSS collection — reach for Simscape only if a specific MATLAB-shop customer demands it. (The
enterprise/customer angle lives in `.planning/strategy/engine-backed-apps.md`, not here.) **Unity** (the
WinterWinds NASA-SBIR heritage) stays a pedigree hero-artifact, not a loop-maintained app — heavy
non-web, minute-long WebGL rebuilds.

## The reframe: the loop drives *backend* work here

The HMI isn't just a UI — it's a **diagnostics/KPI surface** over the twin. So feedback like *"the tank
level response lags reality,"* *"add a KPI for pump cavitation margin,"* or *"this alarm threshold is
wrong"* is **visual, screenshot-able feedback that drives changes to the twin or the control logic behind
it.** The web surface is the loop's *handle on the backend*. That's how curiator does serious backend
work through the same feedback→fix loop — the front-end is geared toward backend diagnostics.

## What's there (OT v1, shipped)

Deterministic tank sim + SQLite historian + Dash HMI + a 10-item feedback-to-fix arc + fresh-clone
preflight (`curiator-ot@36e21cf`). v2 keeps all of it and swaps the process model underneath.

## Work-order

1. **OpenModelica model** of the tank/process; export an **FMU**.
2. **FMU co-sim driver** feeding the existing historian + HMI — a pure backend swap, HMI unchanged first.
3. **Extend the HMI into a diagnostics/KPI surface** — twin-fidelity KPIs, control-margin indicators,
   alarm rationale — so feedback can reach the *backend*, not only the layout.
4. **A feedback round that drives a backend change** (twin fidelity or control logic) via a KPI-surface
   comment — the proof that the loop drives backend work, not just UI.
5. This is the **first FMU-backed dogfood of the `engine-backed` mount** — the minimal runner lifecycle is
   available, but this still needs the real OpenModelica/FMU substrate and a feedback round that exercises
   it.

## Guardrails

- **OpenModelica default; Simscape only customer-driven.** Don't take a MATLAB dependency into a public
  collection by default.
- **Loop maintains the HMI/KPI surface (and drives the backend through it); the FMU is substrate** — the
  loop doesn't hand-edit solver internals.
- **Keep OT v1 shippable throughout** — v2 is additive; the demo never goes dark.
- **Deterministic + seedable** — the twin must be reproducible for the demo/preflight, same as v1.

## Why curiator

The OT suite is the *serious/enterprise* flagship. A real physics twin plus "feedback on KPIs drives
backend work" is the enterprise story (WinterWinds' digital-twin heritage — see the strategy note), and
it's the same engine-backed pattern as the games collection, so the mount work is shared, not duplicated.
