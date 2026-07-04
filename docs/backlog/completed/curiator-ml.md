# Backlog — curiator-ML (import a well-scoped problem as an app)

> **Status:** retired to completed as of 2026-07-04. First local dogfood proof landed 2026-07-03 in
> `galleries/curiator-ml@a19184c`; seeded diagnostic feedback round closed through
> `galleries/curiator-ml@b297001`; second regression benchmark shape landed at
> `galleries/curiator-ml@508162e`. The collection is credential-free Dash diagnostics over deterministic
> synthetic data: binary classification with validation accuracy/log-loss/Brier, count+rate confusion,
> calibration, slice errors, score history, citeable measured-score summary, and a closed three-item
> diagnostic feedback queue; plus seasonal-demand regression with MAE/RMSE/MAPE, residuals, slice
> diagnostics, and a JSON metric artifact. Strict fresh-clone browser preflight passes at
> `curiator-ml@508162e`. Remaining Kaggle, competition-data, API-key, live-data, and reusable importer
> productization paths are follow-ons, not local blockers for this collection proof. Import a Kaggle
> competition — or any **well-scoped problem with a clear metric** — as a curiator
> app whose web surface is **diagnostics / benchmarking / modeling**. Feedback on that surface drives the
> *modeling backend*. The purest instance of the diagnostic-driven backend, and the strongest single
> proof of the whole thesis. Captured 2026-07-03.

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

curiator-ML is an **engine-backed app** (see [`general-app-hosting.md`](general-app-hosting.md)): the dashboard is the front-end
the loop iterates; the **training/inference process is the engine** (substrate). And it's the ideal
proving ground for the **agent-capabilities artifact contract** (`.planning/completed/agent-capabilities.md`):
here the artifact is a **measured CV score + diagnostics**, and *"reject `done` without a measured
score"* is the contract's teeth in a domain where the metric is unambiguous. No "compile passed"
hand-waving is even possible — the score is the ground truth.

## Work-order

1. **Problem import / local benchmarks — landed.** `galleries/curiator-ml@a19184c` carries a
   deterministic synthetic binary benchmark with fixed seed, train/validation split, and a scored
   baseline-vs-interaction recipe. `galleries/curiator-ml@508162e` adds a second deterministic seasonal
   demand regression benchmark with a scored trend+promotion recipe against a seasonal-naive baseline.
2. **Diagnostic dashboards — landed.** The classification app exposes score delta, count+rate confusion
   matrix, calibration, selected-vs-linear slice deltas, feature recipe, a citeable measured-score
   summary, and a JSON metric artifact. The regression app exposes MAE/RMSE/MAPE, residuals, per-slice
   diagnostics, a citeable measured-score summary, and a JSON metric artifact. Extracting this into a
   reusable `curiator ml import` path is follow-on product work.
3. **Feedback rounds that move and explain the metric — seeded round closed.** The app already shows a measured
   lift from the linear baseline to the interaction model (validation accuracy 79.7% → 88.4%; log loss
   0.623 → 0.339). Feedback `7e3612f4` closed per-slice improvement/regression deltas, `22a0e8ae`
   closed the citeable measured-score summary, and `7407d6ce` closed count+rate confusion diagnostics.
4. **Async training — not needed for the first fast benchmark.** Keep this for larger benchmarks once the
   synchronous metric artifact has been dogfooded.

## Verification

- `python benchmark_dashboard.py --metrics-json`: passing, reports validation accuracy 88.4% and log
  loss 0.339 for the interaction model.
- `python regression_dashboard.py --metrics-json`: passing, reports validation MAE 3.17 for the
  trend+promo model, improving MAE by 0.76 against the seasonal-naive baseline.
- `python smoke.py`: passing, checks both metric artifacts and the expected metric improvements.
- `curiator release-preflight --gallery curiator-ml --fresh-clone --strict --browser-smoke --json`:
  passing at `508162e`, opening both Dash dashboards through the shell in headless Brave with no tracked
  machine-local paths.

## External blockers now explicitly parked

- Kaggle/live competition import: blocked on credentials, ToS review, submission limits, and
  non-redistribution handling for competition data.
- API-key/live-data benchmarks: blocked on provider credentials and data terms.
- Reusable `curiator ml import`: follow-on productization after this collection proof, not a blocker for
  retiring the local dogfood work-order.

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
