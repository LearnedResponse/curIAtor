# Using CurIAtor — the consumer guide

CurIAtor is a **runner** (this package) that serves *your* apps and runs an AI curator over them.
Your apps live in a separate **collection** repo: a `gallery.yaml` + an `apps/` dir + a pinned
`curiator`. This guide is task-oriented — commands, not prose. (For the *why*, see
[`DESIGN.md` → "How a collection consumes the runner"](DESIGN.md#how-a-collection-consumes-the-runner).)

---

## 1. Start a collection

```bash
pip install curiator
curiator init my-collection      # scaffolds gallery.yaml + apps/sample.py + requirements.txt + feedback/
cd my-collection
```

Layout:

```
my-collection/
  gallery.yaml          # the registry: your apps + how the curator runs
  apps/sample.py        # a starter Dash app (exposes build_app())
  requirements.txt      # pins curiator
  feedback/             # the JSON ledger + screenshots (history; survives restarts)
  README.md
```

**Add an app:** drop `apps/<name>.py` (exposing `build_app() -> dash.Dash`, plus a module-level
`app`), then add an entry to `gallery.yaml`:

```yaml
apps:
  - name: revenue
    title: Revenue dashboard
    mount: { kind: dash-inproc, module: revenue }   # in-process Dash mount; or kind: proxy {cmd, port}
    source: apps/revenue.py                          # what the curator edits
    tags: [finance]
```

## 2. Run it

```bash
curiator up        # the gallery at http://127.0.0.1:8300
curiator watch     # (second terminal) arm the feedback→fix loop
# …or both in one process:
curiator serve
```

Open the gallery, **★ / 💬 / 📷** an app, and the curator reads the note + screenshot + source, makes
the fix (auto-small) or proposes a plan (propose-only), smoke-tests, reloads the app, and replies in
the panel. Edits land **uncommitted** in your working tree for review — the curator never commits.

## 3. Two install profiles

| profile | install | `gallery.yaml` | who |
|---|---|---|---|
| **Pinned package** *(default)* | `pip install curiator` | `runner: { mode: pinned }` | consumers — you just use the runner |
| **Editable checkout** | `pip install -e ../curiator` (a sibling git checkout) | `runner: { mode: checkout, path: ../curiator }` | contributors — you also improve the runner |

Both keep your apps repo clean: the runner is a dependency, never entangled with your app code. The
public surface (the `gallery.yaml` schema, the adapter interface, the CLI) is small and stable, so
configs survive runner upgrades.

## 4. The `runner:` field + the ◆ General channel

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
curiator up        # click the account corner (top-right) → "Log in" → the built-in form
```

Passwords are stored only as **hashes** (`werkzeug`) in a gitignored `.curiator-users.json` (perms `600`)
— no plaintext, no extra dependency. The `header` / `oidc` settings live in the same `auth:` block; see
the `gallery.yaml` comments. `oidc` needs the `[oidc]` extra (`pip install 'curiator[oidc]'`).

## 5. Run it in a container (one sandbox per collection)

The curator **auto-edits and runs** your code, so the safety unit is **one container per collection** —
that's the blast-radius boundary.

```bash
curiator init collection         # scaffold the mounted collection (apps + gallery.yaml + ledger)
docker compose up                # gallery at http://127.0.0.1:8300, watcher armed
```

What the provided `docker-compose.yml` wires:

- **`./collection` → `/collection`** — a persistent, host-editable mount: your apps, `gallery.yaml`,
  the `feedback/` ledger (history survives restarts), and a `LESSONS.md` the agent accumulates about
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

## 6. Adapters & autonomy (recap)

```yaml
agent:
  adapter: headless-cc     # headless-cc (your Claude sub) | api (per-token, teams) | command (BYO: aider/Codex/script)
  autonomy: auto-small     # auto-small (auto-apply small low-risk fixes) | propose-only (plan first; right for teams)
```

See the [README](../README.md#the-agent-and-where-it-runs) for the full adapter / autonomy matrix.

## 7. Providers & local models

CurIAtor doesn't manage models or API keys — **your agent CLI does**. The provider lives in that CLI's
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
- **Future `api` adapter** (M4 — no CLI in the loop): target an OpenAI- or Anthropic-compatible gateway
  (LiteLLM / a vendor proxy) to stay provider-agnostic.

**Rule of thumb: CurIAtor is the harness; you bring the brain.**
