# Using curIAtor — the consumer guide

curIAtor is a **runner** (this package) that serves *your* apps and runs an AI curator over them.
Your apps live in a separate **collection** repo: a `gallery.yaml` + an `apps/` dir + a pinned
`curiator`. This guide is task-oriented — commands, not prose. (For the *why*, see
[`DESIGN.md` → "How a collection consumes the runner"](DESIGN.md#how-a-collection-consumes-the-runner).)

---

## 1. Start a collection

```bash
pip install curiator
curiator init my-collection --git # scaffolds gallery.yaml + apps/sample.py + requirements.txt + feedback/
cd my-collection
```

Layout:

```
my-collection/
  gallery.yaml          # the registry: your apps + how the curator runs
  apps/sample.py        # a starter Dash app (exposes build_app())
  requirements.txt      # pins curiator
  feedback/             # SQLite ledger source of truth + generated run artifacts
    shots/              # captured screenshots
    audio/              # optional retained voice clips for replay
    tasks/              # per-feedback task bundles: <feedback_id>.md
    replies/            # live agent stdout/stderr traces: <feedback_id>.md
  README.md
```

For dogfooding multiple collections from a runner checkout, keep each collection as an independent
nested repo under `galleries/`. This is the canonical local workspace shape: each collection keeps
its own `.git/`, while the parent runner repo ignores `galleries/curiator-*/`, so agents launched
from the runner checkout can edit collection code without needing write access outside the checkout.

```
curiator/
  galleries/
    curiator-aviato/      # independent git repo, ignored by the parent runner repo
    curiator-ot/          # independent git repo
```

Create new dogfood collections in that shape from the start:

```bash
curiator init galleries/curiator-my-topic --git
git -C galleries/curiator-my-topic add -A
git -C galleries/curiator-my-topic commit -m "chore: initialize collection"
```

List the colocated collection repos and get the exact command for targeting one:

```bash
curiator galleries
CURIATOR_GALLERY=galleries/curiator-my-topic/gallery.yaml curiator status
```

If `curiator galleries` sees old `../curiator-*` paths next to the runner checkout, it reports them.
Real sibling checkouts should be moved with `curiator galleries adopt`; old symlink aliases that
already point into `./galleries/` should be archived or removed so agents stay inside the writable
workspace root.

Clone a public/example collection directly into the nested workspace:

```bash
curiator galleries clone https://github.com/LearnedResponse/curiator-geometry.git
```

Adopt an existing sibling collection repo into that workspace without collapsing its git history:

```bash
curiator galleries adopt ../curiator-aviato
```

`galleries clone` uses `git clone`, requires the result to contain `gallery.yaml`, and infers the
`curiator-*` destination name from the repo basename unless you pass `--name`. `galleries adopt` moves
the repo to `galleries/curiator-aviato/`, refuses non-gallery or non-git sources, and rewrites the safe
sibling-runner case from `runner: {mode: checkout, path: ../curiator}` to the nested equivalent
`runner: {mode: checkout, path: ../..}`. Use `adopt --copy` to leave the sibling checkout in place
while testing the migration.

From a nested gallery, use `runner: { mode: checkout, path: ../.. }` when ◆ General feedback should
patch the parent runner checkout. Public/example collections that should work after `pip install
curiator` should stay on `runner: { mode: pinned }`.

**Add an app with the CLI:** this creates an app directory and updates `gallery.yaml`:

```bash
curiator app templates
curiator app create revenue --template dash --title "Revenue dashboard" --tags finance
# alias: curiator init-app revenue --template dash
```

Import an existing local or GitHub app repo into `apps/<name>` and register it with the same mount
templates:

```bash
curiator app import ../my-react-prototype research_board --template react --port 8710
curiator app import https://github.com/me/lab-viewer.git lab_viewer --template node
```

`app import` copies local directories or runs `git clone` for URL-shaped sources, preserving the
imported app's `.git/` directory inside `apps/<name>`. It does not scaffold or rewrite the app source;
the template only chooses the `gallery.yaml` mount, smoke, preview command, tags, and proxy port. After
registration, import prints doctor-style warnings for issues it can see immediately, such as framework
dev-server/HMR commands, missing dependency manifests, or Vite/Next/FastAPI/Gradio/Streamlit base-path
settings that need source changes before the app will behave correctly under `/app/<name>/`.
When git-as-memory is enabled and an imported app root is its own Git repo, a source-changing
`curiator done`/agent reply first commits inside that app repo, then commits the collection ledger plus
the updated app gitlink. The app keeps its own history, while the collection keeps the feedback thread
and provenance receipt. `curiator status --app <name>` shows the nested app repo branch/dirty state
when that two-repo workflow applies.

`curiator app templates` prints the current scaffold/import menu, including mount kind, toolchain, and
the intended use for each template. Templates today: `dash` (in-process Dash), `static` (same-origin proxy using `http.server`), `python`
(tiny proxy-served Python HTTP app), `node` (dependency-light Node HTTP server), `flask`
(server-rendered Flask app), `fastapi` (API-backed ASGI app), `rust` (dependency-light Rust HTTP
server), `react` (Vite + React), `svelte` (Vite + Svelte), `vue` (Vite + Vue), `next` (Next.js App
Router), `streamlit`, and `gradio`.
The Node, Flask, FastAPI, Rust, and JS templates use `proxy` mounts; Vite templates set their base path
from `CURIATOR_APP`, and the Next template sets `basePath`, so assets resolve under `/app/<name>/`. Pass
`--package-manager pnpm|yarn|bun|npm` to override auto-detection from lockfiles. Every generated proxy
template also adds a concrete standalone `commands.preview` command to `gallery.yaml`, and
`curiator status` / `curiator context` surface it alongside the smoke command. The Next, Streamlit, and
Gradio templates use framework root-path/base-path settings with prefix-preserving proxy mounts and
include generated README notes about the lightweight proxy's production reverse-proxy limits.

When a proxied app cannot start or the backend port never responds, the app iframe shows a proxy
diagnostic page with the configured command, working directory, port, target URL, process state, and
recent stdout/stderr from the launched process. The built-in proxy is intentionally lightweight: if a
framework dev server sends WebSocket upgrade requests for HMR, curIAtor returns an explicit
WebSocket/HMR diagnostic rather than silently failing. Use the scaffold `commands.preview` path or put
a full reverse proxy such as nginx/Caddy in front when live HMR is required.

You can also register an existing app manually: drop `apps/<name>.py` (exposing
`build_app() -> dash.Dash`, plus a module-level `app`), then add an entry to `gallery.yaml`:

```yaml
apps:
  - name: revenue
    title: Revenue dashboard
    mount: { kind: dash-inproc, module: revenue }   # in-process Dash mount; or kind: proxy {cmd, port}
    source: apps/revenue.py                          # what the curator edits
    tags: [finance]
```

**App directories and multiple endpoints:** use `root:` when an app is a folder. `source:` is the
editable scope the curator may touch. `mounts:` lets one folder expose several gallery endpoints:

```yaml
apps:
  - name: lab_suite
    root: apps/lab_suite
    source: .
    smoke: python -m compileall -q .
    smoke_timeout: 30
    mounts:
      - name: overview
        mount: { kind: dash-inproc, module: overview, source: overview.py }
      - name: node_ssr
        mount: { kind: proxy, cmd: "npm start -- --port {port}", port: 8710 }
```

Use a top-level default when most app builds should share a timeout:

```yaml
smoke: { timeout: 60 }
```

`proxy` mounts are still same-origin: the iframe opens `/app/<name>/...`, and curIAtor forwards that
path to the local app process. For heavier deployments you can still put nginx/Kong/Compose in front;
the curIAtor contract stays the same.
`mount.cmd` and `mount.cwd` may use `{port}`, `{app}`, `{root}`, and `{source}` placeholders; the shell
renders them before launching the proxy process and still exports `PORT` and `CURIATOR_APP`.

## 2. Run it

```bash
curiator up        # the gallery at http://127.0.0.1:8300
curiator watch     # (second terminal) arm the feedback→fix loop
# …or both in one process:
curiator serve
```

Open the gallery, **★ / 💬 / 📷** an app, optionally mark up the screenshot with boxes, arrows, pins,
or redaction blocks, and the curator reads the note + screenshot + source, makes the fix (auto-small)
or proposes a plan (propose-only), smoke-tests, reloads the app, and replies in the panel. By default,
edits land **uncommitted** in your working tree for review. When `git.commit: true` is set, each
accepted agent run becomes one git-as-memory commit that captures the source change, ledger update,
and provenance trailers.
The current screenshot path uses same-origin `html2canvas` with upload as the fallback; see
[`SCREENSHOT_CAPTURE.md`](SCREENSHOT_CAPTURE.md) for fidelity, privacy, and native-capture options.
Signed-in reviewers can also use the **Native** capture button for browser screen capture when
canvas/WebGL-heavy views do not render well through `html2canvas`; anonymous feedback is limited to
same-origin **Capture view**.
In the React shell, burned-in annotations also carry sanitized normalized coordinates and same-origin
DOM target hints into the task bundle when available, plus any short per-mark notes you enter and
optional `start_ms` / `end_ms` offsets on the annotation clock; redaction marks, uploads, and
unreadable/cross-origin mounts do not carry DOM targets. Prior feedback threads show those annotation
summaries, and saved annotated entries can be reopened as a scrollable preview from the feedback panel
or loaded as an editable reply draft.

The comment field is a normal textarea, so OS-level dictation works without curIAtor-specific audio
handling. On macOS, use Dictation; on Windows, use Win+H voice typing. Linux desktop dictation depends
on the local environment.

Collections can also opt into local voice transcription. The packaged faster-whisper adapter is the
default setup path:

```bash
pip install 'curiator[voice]'
curiator voice setup
curiator up
```

`curiator voice setup` writes `voice.transcribe_cmd` to `gallery.yaml`. The React shell then shows a
**Record** button, captures microphone audio with `MediaRecorder`, posts it to `/api/transcribe`, and
drops the returned transcript into the comment box.

You can also set `voice.transcribe_cmd` manually to any local command that accepts an audio clip path
either through `{audio}` or as the final argument. The command runs from the collection root with
`CURIATOR_AUDIO`, `CURIATOR_GALLERY`, and `CURIATOR_COLLECTION_ROOT` in the environment. It can print
plain transcript text or JSON:

```yaml
voice:
  transcribe_cmd: "python -m curiator.voice.faster_whisper {audio}"
  transcribe_timeout: 60
  transcribe_max_bytes: 26214400
```

```json
{"text": "move the legend up", "segments": [{"start": 0.25, "end": 1.1, "text": "move the legend up"}]}
```

This is the private/default path: use a local Whisper or `whisper.cpp` wrapper for zero-egress review
audio. Browser Web Speech is intentionally not used for private collections. Returned `segments`
timestamps are sanitized, stored with the feedback entry, and included in the agent task bundle as a
`Voice transcript segments` block. If screenshot annotations also carry `start_ms` / `end_ms`,
curIAtor stores `narrative` rows that pair each timed mark with overlapping speech; prior feedback
threads show the same compact narrative summary, falling back to a `Voice transcript` summary when
there are segments but no timed marks. Older entries without stored narrative rows are derived from the
saved annotations and transcript segments. Saved annotated entries with timed marks can also open a
transcript-timed **Narrative replay** in the annotation preview: each step highlights the saved mark and
shows the overlapping transcript phrase. When you annotate while recording, the React shell uses the
recording start as the shared clock zero, so mark timestamps and transcript segments line up in the UI
and task bundle. Audio clips are not retained by default; replay uses the saved transcript timing.
Enable retained audio only when you want audio-backed replay and are prepared to audit local media:

```bash
curiator voice retain-audio on
curiator voice setup
curiator up
```

Retained clips are stored under `feedback/audio/`, referenced from the feedback ledger, and ignored by
generated collection `.gitignore` files. Treat them like screenshots before sharing or publishing a
collection.

For public or hosted collections that can accept browser-provider speech services, enable the optional
Web Speech dictation button explicitly:

```bash
curiator voice web-speech on --lang en-US
curiator up
```

This adds a **Dictate** button that streams final browser speech-recognition phrases into the comment
box. It does not produce reliable segment timestamps and therefore does not replace local Whisper for
narrated feedback.

## 3. Work Interactively From An App Repo

If you are already inside Claude Code, Codex, or another coding agent in an app repo, use the same
curIAtor loop without spawning a separate headless agent:

```bash
curiator link --gallery ../my-collection/gallery.yaml --app revenue --commands
curiator status
curiator context
curiator work <feedback_id>       # prints the same task bundle a headless agent would receive
# edit + smoke-test in the current CLI session
curiator done <feedback_id> "Changed X and smoke-tested with Y"
```

`curiator link` writes `.curiator/app.yaml`, using a relative gallery path when possible, so commands
run from a separate app repo can still find the collection's gallery, ledger, smoke command, and app
source scope after the repos move together. `--commands` installs lightweight Claude/Codex shims
(`.claude/commands/curiator.md` and `.agents/skills/curiator/SKILL.md`) so Claude `/curiator`
or Codex `$curiator` can call `curiator status`, `curiator context`, and `curiator work`. If no app
is selected and the collection has multiple apps, `curiator context` prints a collection-level summary
with app counts, General feedback, and ready commands instead of failing.

This is not a second memory system. `curiator work` marks the feedback `working` and writes
`feedback/tasks/<id>.md`; `curiator done` posts the ⚙ reply, reloads the app, and uses the same
git-as-memory commit path as the watcher when `git.commit: true`.

You can also add feedback from the terminal:

```bash
curiator feedback add revenue "the filter panel needs a reset button"
curiator feedback add revenue "fix the marked legend" \
  --annotations-json '[{"tool":"pin","x1":0.72,"y1":0.18,"n":1,"note":"legend overlaps chart","target":{"selector":"#chart .legend"}}]'
curiator feedback add revenue "use these saved marks" --annotations-file marks.json
```

The annotation options use the same sanitized mark format the React shell stores after screenshot
markup, so terminal-seeded dogfood items still render a `Screenshot annotations` block in the agent
task bundle. `curiator seed seed/feedback.yaml` also accepts an `annotations:` list on each item.

For feedback that should not wake an agent yet, add or review it through the held queue:

```bash
curiator feedback add revenue "anonymous/public suggestion" --status held
curiator queue list
curiator queue approve <feedback_id>         # held -> new; the watcher can dispatch it
curiator queue reject <feedback_id> "spam"   # held -> rejected; records a thread note
curiator queue sweep --older-than 30         # dry-run stale held-item cleanup
curiator queue sweep --older-than 30 --apply --reason stale
```

Admins can also open **Queue** from the account menu in the React shell; it shows the same held pool
and uses the same ledger transitions.

`held` is admission control for public or over-quota feedback. It is distinct from
`awaiting_approval`, which means the agent has already looked at a task and is asking a human to
approve a plan. `queue sweep` is intentionally dry-run unless `--apply` is present; applied sweeps
reject matching held items and write the same per-item audit notes as `queue reject`.

And summarize the collection's feedback history for release notes or case studies:

```bash
curiator stats                 # human-readable ledger + git-as-memory summary
curiator stats --json --app revenue
curiator stats --markdown      # paper/release-note tables
curiator stats --csv           # app-level spreadsheet/plotting rows
curiator stats --markdown --output docs/paper/figures/collection-stats.md
curiator stats compare galleries/curiator-aviato galleries/curiator-ot galleries/curiator-geometry --markdown
```

Before moving or publishing a collection, run the portability preflight:

```bash
curiator doctor                # errors on absolute/missing paths; warns on weak smoke/proxy/HMR/deps
curiator doctor --json
curiator smoke                 # runs each app's configured smoke command or cheap inferred fallback
curiator smoke --http          # also starts proxy apps briefly and verifies an HTTP response
curiator smoke --app revenue --json
curiator smoke --jobs 4 --json # run independent app checks concurrently, preserving report order
curiator release-preflight     # nested public galleries + publish-unsafe artifacts/local deps
curiator release-preflight --fresh-clone
curiator release-preflight --fresh-clone --strict  # fail on doctor warnings for publication gates
curiator release-preflight --fresh-clone --json --output release-evidence/release-preflight.json
curiator release-preflight --http-smoke  # also start proxy apps and poll HTTP when deps are installed
curiator release-preflight --include-optional --fresh-clone --strict  # add finance + phylogenetics
curiator playground-preflight  # hosted pilot posture: auth, quotas, queue, doctor, smoke
curiator playground-preflight --http-smoke  # also start proxy apps when deps are installed
curiator playground-preflight --strict  # fail on warnings for CI/final pre-pilot gates
curiator playground-preflight --strict --json --output release-evidence/playground-preflight.json
make release-prepare VERSION=0.2.0 DATE=2026-07-02  # updates package, citation, Zenodo, changelog
```

For the runner's own release gate, use the combined local check:

```bash
make release-prepare VERSION=0.2.0 DATE=<release-date>  # only when cutting a release
make release-check
make release-launch-check  # final public launch only: rejects generated demo/paper placeholders
```

The full publication checklist lives in [`RELEASE.md`](RELEASE.md), including PyPI Trusted Publishing,
collection publication, Zenodo, and post-release smoke checks.

For proxy apps that should prove they can answer HTTP, add an optional path:

```yaml
smoke_http: /healthz
```

Then run `curiator smoke --http`. The command starts the app with `commands.preview` when available
(otherwise `mount.cmd`), exports `PORT` and `CURIATOR_APP`, polls `http://127.0.0.1:<port><path>`, and
tears the process down. This is a lightweight server-response check, not a full browser/HMR test.
For publication gates, `curiator release-preflight --http-smoke` applies the same HTTP pass across the
selected nested galleries, or across fresh clones after app dependencies are installed there.

## 4. Two install profiles

| profile | install | `gallery.yaml` | who |
|---|---|---|---|
| **Pinned package** *(default)* | `pip install curiator` | `runner: { mode: pinned }` | consumers — you just use the runner |
| **Editable checkout** | `pip install -e ../curiator` (a sibling git checkout) | `runner: { mode: checkout, path: ../curiator }` | contributors — you also improve the runner |
| **Nested gallery** | run from this checkout | `runner: { mode: checkout, path: ../.. }` | local dogfooding under `galleries/<collection>` |

Both keep your apps repo clean: the runner is a dependency, never entangled with your app code. The
public surface (the `gallery.yaml` schema, the adapter interface, the CLI) is small and stable, so
configs survive runner upgrades.

## 5. The `runner:` field + the ◆ General channel

Feedback splits in two:

- **Feedback on an app** → the curator edits that app's `source`. Always works.
- **Feedback on the runner itself** (the **◆ General** bucket, or the shell chrome) → handled by your
  install profile, because editing an installed package's `site-packages` is a dead end (untracked,
  blown away on upgrade):

```yaml
runner:
  mode: pinned            # consumer: the curator DRAFTS an upstream issue/PR (posted as the ⚙ reply)
  # mode: checkout        # contributor: the curator PATCHES the runner at `path` (tracked → you PR it)
  # path: ../curiator
```

It **degrades gracefully**: early you run the checkout and the runner is fair game (*"curiator
maintains curiator"* — feedback on the chrome patches the shell); as it stabilizes you pin the
package and the *same gesture* switches from "local patch" to "file upstream." `runner:` defaults to
`pinned` if omitted, so existing configs keep working.

**The PR-back loop:** in `pinned` mode the curator's reply *is* a ready-to-file issue/PR description —
your feedback becomes an upstream contribution. (Auto-filing via `gh` is on the roadmap; for now the
draft is posted as the ⚙ reply for a human to file.)

## Identity & sign-in (who gives feedback)

curiator records *who* gave each piece of feedback — it lands on the ledger entry and flows into the
`Feedback-From:` git trailer. Pick an `auth.mode` in `gallery.yaml`:

| mode | how you sign in | best for |
|---|---|---|
| **`none`** *(default)* | nobody — everyone is `default_user` | solo / trusted box (provenance, no login) |
| **`local`** | a built-in username/password form curiator serves | **self-hosted installs with no IdP or proxy** |
| **`header`** | an edge proxy (oauth2-proxy / ingress) sets trusted headers | behind a gateway you already run |
| **`oidc`** | curiator runs the OIDC flow against your IdP (Keycloak, …) | self-hosted SSO |

**Local sign-in — the quick self-hosted option** (no IdP, no proxy):

```bash
# gallery.yaml →  auth: { mode: local }
curiator user add alice@example.com --name Alice    # prompts for a password (or pass --password)
curiator user list
curiator user disable alice@example.com             # revoke without deleting the account record
curiator user enable alice@example.com
curiator up        # click the account corner (top-right) → "Log in" → the built-in form
```

Passwords are stored only as **hashes** (`werkzeug`) in a gitignored `.curiator-users.json` (perms `600`)
— no plaintext, no extra dependency. In `header` mode, the edge proxy is responsible for sign-in and
must supply the configured identity headers; curIAtor rejects feedback if those headers are missing.
The `header` / `oidc` settings live in the same `auth:` block; see the `gallery.yaml` comments. `oidc`
needs the `[oidc]` extra (`pip install 'curiator[oidc]'`) and a provider/client config whose secret
comes from the environment:

```yaml
auth:
  mode: oidc
  issuer: https://idp.example.test/realms/curiator
  client_id: curiator-playground
  client_secret_env: CURIATOR_OIDC_SECRET
```

`curiator playground-preflight` verifies those OIDC launch fields and records only whether the named
secret env var is set, not the secret value.

For a hosted gallery where logged-out visitors may leave feedback, keep sign-in enabled and opt into
held anonymous intake:

```yaml
auth:
  mode: local          # or oidc
  allow_anonymous: true
  anonymous_feedback_max: 20
  anonymous_feedback_window_seconds: 86400
```

Logged-out feedback is always saved as `held`; it will not wake the agent until an admin approves it
from **Queue** or `curiator queue approve`. Logged-in users keep the normal `new` feedback path. The
anonymous feedback limit is per client IP in the running shell process; set
`anonymous_feedback_max: 0` only for a private, already-gated deployment where you intentionally want
no anonymous submission throttle. In the default React shell, logged-out anonymous users can capture
the live app view, but the arbitrary image-upload fallback is hidden and anonymous-held uploads are
rejected by the feedback API.

For hosted self-serve accounts, cap agent dispatch at the watcher:

```yaml
agent:
  dispatch:
    anonymous: hold
    user: auto
    trusted_groups: [trusted]
  quotas:
    per_user_daily: 5
    global_daily: 100
```

The watcher checks these before it marks feedback `working`. Explicit anonymous feedback is forced
to `held` even if it reaches the ledger as `new`; over-quota account feedback is also moved to `held`
with a thread note. Trusted groups bypass the per-user quota, but still count against
`global_daily`.

## 6. Run it in a container (one sandbox per collection)

The curator **auto-edits and runs** your code, so the safety unit is **one container per collection** —
that's the blast-radius boundary.

```bash
curiator init collection --git   # scaffold the mounted collection (apps + gallery.yaml + ledger)
docker compose up                # gallery at http://127.0.0.1:8300, watcher armed
```

What the provided `docker-compose.yml` wires:

- **`./collection` → `/collection`** — a persistent, host-editable mount: your apps, `gallery.yaml`,
  the `feedback/` ledger/snapshot (history survives restarts), and a `LESSONS.md` the agent accumulates about
  *your* apps. Because it's on the host, the curator's diffs stay reviewable / committable / PR-able.
- **creds** — for the default `headless-cc` adapter, your host Claude login is mounted read-only
  (`~/.claude`). For the `api` adapter, drop that mount and set `ANTHROPIC_API_KEY` instead.
- **the port** — `8300:8300` (match `gallery.yaml`'s `shell.port`).
- **the entrypoint** — `curiator serve` (gallery + the fix loop together).

This maps onto the deployment modes: a **personal container** (`headless-cc`, `auto-small`) vs a
**shared/hosted container** (`api`, `propose-only` + PR). The container *is* your team's collection.

> **Building the image:** the `Dockerfile` does `pip install curiator` (from PyPI). For a local or
> pre-release runner, build from a checkout with `--build-arg CURIATOR_PIP=<path-or-spec>` (see the
> comments in the `Dockerfile`).

For a hosted invite-only playground, use the phase-0 deployment runbook in
[`PUBLIC_PLAYGROUND_DEPLOYMENT.md`](PUBLIC_PLAYGROUND_DEPLOYMENT.md): sign-in first, one container per
collection, TLS at the edge, backups of the mounted collection, and weekly `curiator stats` review.

## 7. Adapters & autonomy (recap)

```yaml
agent:
  adapter: headless-cc     # headless-cc (your Claude sub) | api (per-token, teams) | command (BYO: aider/Codex/script)
  autonomy: auto-small     # auto-small (auto-apply small low-risk fixes) | propose-only (plan first; right for teams)
```

See the [README](../README.md#the-agent-and-where-it-runs) for the full adapter / autonomy matrix.

## 8. Providers & local models

curIAtor doesn't manage models or API keys — **your agent CLI does**. The provider lives in that CLI's
own config, so any setup it supports works here unchanged. (Env-var names below are illustrative — they
drift, so follow each tool's own docs, linked, rather than treating these as gospel.)

- **Claude Code** (`headless-cc`): Anthropic, Amazon Bedrock, Google Vertex, or any Anthropic-compatible
  gateway (incl. a local model behind a [LiteLLM](https://docs.litellm.ai) proxy) — selected via Claude
  Code's own env vars (e.g. `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`, `ANTHROPIC_BASE_URL`).
  See the [Claude Code docs](https://docs.claude.com/en/docs/claude-code).
- **Codex / aider / other CLIs** (`command` adapter): set `agent.cmd` and configure the provider in that
  tool — [Codex](https://github.com/openai/codex) supports OpenAI-compatible endpoints (incl. local:
  [Ollama](https://ollama.com), LM Studio, vLLM); [aider](https://aider.chat) is provider-agnostic via
  [LiteLLM](https://docs.litellm.ai). See each tool's docs.
- **Future `api` adapter** (team-scale, no CLI in the loop): target an OpenAI- or
  Anthropic-compatible gateway (LiteLLM / a vendor proxy) to stay provider-agnostic.

**Rule of thumb: curIAtor is the harness; you bring the brain.**
