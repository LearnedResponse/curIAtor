# Backlog — curiator-ML (import a well-scoped problem as an app)

> **Status:** skipped/deferred as of 2026-07-03. This is a post-release diagnostic-backend direction,
> not an active local work-order; reopening it requires choosing an external/open benchmark or dataset
> and a metric contract. Original scope: import a Kaggle competition — or any **well-scoped problem with a
> clear metric** — as a curiator app whose web surface is **diagnostics / benchmarking / modeling**.
> Feedback on that surface drives the *modeling backend*. The purest instance of the diagnostic-driven
> backend, and the strongest single proof of the whole thesis. Post-release direction. Captured
> 2026-07-03.

## The pitch (and why it's the best proof)

Most curiator feedback is subjective ("this legend's cramped"). ML is different: the app has an
**objective metric** (the competition score / CV loss). So a curiator-ML demo can *graph the score
climbing across feedback rounds* — **"watch the loop climb a leaderboard from human diagnostic
feedback."** That's the most undeniable demonstration curiator can make: not "the UI got prettier," but
"the model measurably got better, and a human steered it by commenting on diagnostics." It's also the
rung that proves curiator does **serious backend work**, in a domain where backend work is the *entire*
point — there's no UI to hide behind.

## What the loop maintains vs. what it drives

- **The loop maintains** the diagnostic/benchmarking dashboard: score + leaderboard delta, learning
  curves, confusion matrix, calibration, feature importance, per-slice error analysis, ablation table.
- **Feedback on that surface drives the modeling backend**: *"the train/val gap says you're overfitting —
  regularize," "class 3 is systematically misclassified — look at these features," "add interaction
  terms," "try gradient boosting," "handle the imbalance."* Screenshot-able feedback on a metric →
  changes to features / model / loss / hyperparameters. The dashboard is the loop's *handle on the model*.

This is exactly the standard data-science workflow (look at diagnostics → change the model → re-measure),
which is why the loop fit is natural — and it's squarely in Adam's wheelhouse (a former data-science
lead), so the demos will be credible.

## Engine-backed, with the metric as the enforced artifact

curiator-ML is an **engine-backed app** (see `general-app-hosting.md`): the dashboard is the front-end
the loop iterates; the **training/inference process is the engine** (substrate). And it's the ideal
proving ground for the **agent-capabilities artifact contract** (`.planning/backlog/agent-capabilities.md`):
here the artifact is a **measured CV score + diagnostics**, and *"reject `done` without a measured
score"* is the contract's teeth in a domain where the metric is unambiguous. No "compile passed"
hand-waving is even possible — the score is the ground truth.

## Work-order

1. **Problem import** — a `curiator ml import` that pulls a well-scoped problem (dataset + metric +
   splits) into an app directory with a baseline pipeline and a scored dashboard. Prefer **open
   benchmarks** first (OpenML tasks, classic datasets, a self-hosted problem); wire live Kaggle only
   within its rules (see guardrails).
2. **Diagnostic dashboard** — score/leaderboard delta, learning curves, error analysis, feature
   importance; the front-end the loop iterates.
3. **One feedback round that moves the metric** — a diagnostic comment → a modeling-backend change → a
   *measured* score improvement, surfaced as the artifact. This is the demo.
4. **Async training** — the loop edits code fast; training runs in the background; the dashboard updates
   from the last completed run. Don't block the feedback cadence on a multi-hour fit.

## Guardrails

- **Compute cadence.** Training is slow; the loop's tight cadence isn't. Scope public demos to **fast,
  checkpointable problems**; iterate code synchronously, run training async, refresh the dashboard from
  the latest checkpoint. Reserve heavy runs for explicit long-budget rounds.
- **Kaggle ToS + data licensing.** Live competitions have automation rules, submission limits, and
  no-redistribution data. For a *public* collection, default to **open/permissively-licensed benchmarks**
  ("or other well-scoped problem"); use Kaggle only within ToS and never bundle competition data.
- **Augmentation, not AutoML.** The human's diagnostic feedback *steers*; the loop *executes* (features,
  models, sweeps, error analysis). Frame it as data-scientist augmentation, not a leaderboard-farming
  bot — which is also the ToS-safe posture.
- **The metric is the gate.** `done` requires a real measured score, not a green unit test — the domain
  makes the artifact contract's teeth natural.

## Why curiator

It's the cleanest proof that the feedback loop drives *measurable backend improvement*, it exercises the
engine-backed mount and the artifact-with-teeth in the domain where both are least fakeable, and it
lands in a community (Kaggle/ML) that lives and breathes exactly this diagnostic-driven iteration.
