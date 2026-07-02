# Backlog — carve `cli.py` into a `curiator/cli/` package

> **Status:** started 2026-07-02. A **maintainability** item surfaced by the git-history audit, not a
> product feature. Shape: **incremental, seam-by-seam, behavior-preserving** — the CLI surface
> (`curiator <cmd> …`) and the test suite are frozen contracts. First seams landed: `curiator voice`
> moved to `curiator/voice/cli.py`, `curiator user|auth` moved to `curiator/auth_cli.py`, and
> `curiator stats` moved to `curiator/stats_cli.py`, leaving `curiator.cli:main` and parser wiring
> stable. The real constraint isn't the refactor, it's **timing it around the live feedback loop**,
> which edits `cli.py` constantly. Captured 2026-07-02.

## The problem

`curiator/cli.py` is **5,259 lines / ~200KB** after the first three command-group extractions — still the
single largest source file, ~26% of all tracked Python (5,259 of 19,955). The git audit found it
appears **~8× in the ten largest blobs in history**:
it's been rewritten so often it dominates the repo's history weight. It holds **148 top-level
defs/classes** and **~40 subcommands**, and carries a structural tell — **four repeated
`import argparse` blocks deep in the file** (lines 4758 / 4982 / 5120 / 5465), the signature of sections
appended over time rather than composed.

None of this is a bug today. It's a **friction tax that compounds**: every feedback-fix that touches a
command reopens a 5.5k-line file, every loop edit rewrites a 200KB blob, and merge/attribution noise
grows with each pass. Left alone it gets worse monotonically — the loop is the most active editor of
this exact file.

## What's in `cli.py` today (the seams are already there)

The subcommands cluster cleanly — these groups *are* the module boundaries:

| Group | Subcommands |
|---|---|
| **serve / demo** | `up`, `watch`, `serve`, `demo`, `reset-demo`, `demo-up`, `open`, `reload` |
| **collection lifecycle** | `init`, `link`, `status`, `doctor`, `smoke`, `commands` |
| **galleries + app scaffolding** | `galleries` (`adopt`/`clone`), `app` (`templates`/`create`/`import`), `init-app` |
| **release** | `release-preflight`, `playground-preflight` |
| **feedback / agent workflow** | `context`, `work`, `done`, `queue` (`list`/`approve`/`reject`/`sweep`), `reply`, `seed`, `revert`, `reflect` |
| **stats / ledger** | `stats`, `feedback` |
| **auth / users** | `user`, `auth` |
| **voice** | `voice` (`show`/`setup`/`web-speech`/`retain-audio`) |

Handlers already follow a `cmd_*` naming convention and the parser is built group-by-group, so this is
a **move, not a redesign**.

## Proposed shape

End state: turn the module into a package with a thin dispatcher:

```
curiator/cli/
  __init__.py        # re-exports main() so `curiator.cli:main` entrypoint is unchanged
  __main__.py        # main(): build root parser, register groups, dispatch
  _parser.py         # shared parser helpers / common args
  serve.py           # up/watch/serve/demo/reset-demo/demo-up/open/reload
  collection.py      # init/link/status/doctor/smoke/commands
  galleries.py       # galleries + app scaffolding + init-app
  release.py         # release-preflight/playground-preflight
  workflow.py        # context/work/done/queue*/reply/seed/revert/reflect
  stats.py           # stats/feedback
  auth.py            # user/auth
  voice.py           # voice*
```

Each group module exposes a `register(subparsers)` that adds its parsers + sets `func=`; `__main__.py`
just calls each `register()` and dispatches. The console-script entrypoint stays `curiator.cli:main`,
so `pyproject`/packaging and every `curiator <cmd>` invocation are untouched.

Important import constraint: `curiator/cli.py` and a `curiator/cli/` package cannot both safely expose
`curiator.cli`; the package shadows the module. Until the final cut-over can remove/rename `cli.py`,
use existing domain packages for behavior-preserving seam extraction, or make the package switch as one
reviewed cut-over commit.

## Work-order (incremental — one seam per commit)

1. **Extract the most independent groups first** — landed for `voice`, `auth/user`, and `stats`:
   handlers moved to `curiator/voice/cli.py`, `curiator/auth_cli.py`, and `curiator/stats_cli.py`;
   `cli.py` imports the command handlers while keeping the existing parser wiring. This is the
   template while `curiator.cli` remains a module.
2. **Then the rest, one group per commit**, easiest→hardest: `release` → `galleries`
   → `collection` → `serve` → `workflow` (biggest, do last). Each commit is a pure move + green tests.
3. **Collapse the appended blocks** — fold the four stray `import argparse` sections into their target
   modules as you go; the file shrinks to the dispatcher.
4. **Switch to the final `curiator/cli/` package** once `cli.py` is small enough to remove in one
   reviewed cut-over. At that point `cli/__init__.py` re-exports `main`, `cli/__main__.py` can own the
   root parser, and the console-script entrypoint stays `curiator.cli:main`.

Each step is independently shippable and revertable. No step changes behavior or the command surface.

## Guardrails

- **Behavior-preserving, full stop.** `curiator <cmd> …` output, exit codes, and flags are identical
  before/after. The existing CLI tests (`test_cli_*.py`) are the contract — they must pass unchanged at
  **every** commit, no test edits to "make it fit."
- **Don't fight the loop.** `cli.py` is the loop's most-edited file (it was touched 17 min into the
  audit). A big-bang move will collide head-on with in-flight feedback-fixes. Do this in a **loop-quiet
  window** (or pause the loop), land it fast in small commits, and rebase rather than merge.
- **Move, don't refactor.** Resist "improve it while I'm in here." Relocation and logic-change in the
  same commit is what makes a refactor unreviewable and a regression un-bisectable. Behavior changes are
  a separate follow-up once the seams exist.
- **Keep the entrypoint stable** — `curiator.cli:main` must resolve throughout, so packaging and shims
  never break mid-migration.

## Why now (and the cost of waiting)

The audit flagged this as the one *structural* thing that will fight future work — and the loop edits
this file more than any other, so the tax is paid on nearly every fix. Doing it early is cheap (the
seams are clean, handlers already grouped, tests already cover the surface); doing it after another
1,000 lines and a public release is not. It also **directly reduces history weight**: the ~200KB blob
stops being rewritten wholesale on every touch, shrinking diffs, attribution noise, and merge friction
for exactly the workflow curiator runs most.
