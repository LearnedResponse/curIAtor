# Public playground deployment runbook

This is the phase-0 "velvet rope" deployment shape from
[`docs/backlog/public-playground.md`](backlog/public-playground.md): one hosted collection, invited
users only, and one container as the blast-radius boundary. It is a runbook, not proof that a hosted
instance exists.

## 1. Pick the collection and runner mode

Use a public/example collection that can tolerate external feedback. For the first hosted pilot,
`curiator-geometry` is the safest default: deterministic, no private data, and a small dependency
surface.

In `gallery.yaml`, hosted examples should run the released runner, not a development checkout:

```yaml
runner:
  mode: pinned

git:
  commit: true
```

Before deployment:

```bash
curiator doctor
curiator smoke
curiator playground-preflight
curiator playground-preflight --strict
curiator playground-preflight --http-smoke
curiator playground-preflight --strict --json --output release-evidence/playground-preflight.json
```

For release collections from the runner checkout:

```bash
curiator release-preflight --gallery curiator-geometry --fresh-clone
```

`curiator playground-preflight` is the hosted-posture gate: it combines `doctor`/`smoke` with checks
for `runner.mode: pinned`, `git.commit: true`, sign-in, local invite/admin readiness, anonymous-held
policy, dispatch quotas, and the current held queue count. It does not replace a real hosted pilot or
backup-restore test. Use `--strict` for CI or the final pre-pilot check; it keeps warnings visible as
warnings but makes any posture or doctor warning fail the command. Use `--http-smoke` when app
dependencies are installed in the mounted collection and you want the gate to start proxy apps briefly
and poll their configured HTTP smoke paths or default app URLs. Use `--output` to write the full JSON
posture report under gitignored `release-evidence/` for pre-pilot review notes.

## 2. Gate feedback behind sign-in

Phase 0 is invite-only. Use local accounts for the smallest deployment, or `header`/`oidc` behind an
identity provider if one is already available.

Minimal local-auth configuration:

```yaml
auth:
  mode: local
  admin_groups: [admin]
```

Create invited users inside the mounted collection:

```bash
CURIATOR_GALLERY=/collection/gallery.yaml curiator user add alice@example.com --name Alice --groups admin
CURIATOR_GALLERY=/collection/gallery.yaml curiator user add bob@example.com --name Bob
CURIATOR_GALLERY=/collection/gallery.yaml curiator user list
```

Revoke access without deleting the audit trail:

```bash
CURIATOR_GALLERY=/collection/gallery.yaml curiator user disable bob@example.com
```

For `auth.mode: local`, keep password hashes in the gitignored `auth.users_file`
(`.curiator-users.json` by default), not inline `auth.users` in `gallery.yaml`. `curiator user add`
writes the file with owner-only permissions, and `curiator playground-preflight` rejects hosted-local
configs whose users file is tracked by git, not ignored, outside the collection root, or
group/world-readable.

Do not enable `auth.allow_anonymous` for phase 0 unless a human is actively reviewing the held queue.
Anonymous public feedback is never allowed to dispatch directly, but it still creates moderation work.

## 3. Bound the agent

For a first hosted pilot, prefer `propose-only` unless the collection is intentionally low-risk.

```yaml
agent:
  adapter: api
  autonomy: propose-only
  dispatch:
    anonymous: hold
    user: auto
    trusted_groups: [trusted]
  quotas:
    per_user_daily: 3
    global_daily: 25
```

If the pilot uses `auto-small`, keep the collection dataless and make sure `git.commit: true` is on so
admins have a revert handle for every run.

## 4. Run one container per collection

The stock `Dockerfile` and `docker-compose.yml` are suitable for a single collection. A hosted
deployment should mount a persistent collection directory and bind the shell only to localhost or a
private Docker network. Put TLS and public routing in front of it.

Example compose override for a host-local service:

```yaml
services:
  curiator:
    image: curiator:latest
    ports:
      - "127.0.0.1:8300:8300"
    volumes:
      - /srv/curiator/geometry:/collection
    environment:
      CURIATOR_GALLERY: /collection/gallery.yaml
      SHELL_HOST: "0.0.0.0"
    restart: unless-stopped
```

For the API adapter, set the provider key through the host's secret mechanism rather than committing it
to the collection.

## 5. Terminate TLS at the edge

Use whatever reverse proxy the host already operates. The proxy should forward normal HTTP requests and
preserve the host/proto headers. Keep curIAtor itself private to the host or internal network.

Minimal Caddy shape:

```caddyfile
curiator.example.org {
  reverse_proxy 127.0.0.1:8300
}
```

Minimal nginx shape:

```nginx
server {
    listen 443 ssl http2;
    server_name curiator.example.org;

    location / {
        proxy_pass http://127.0.0.1:8300;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

If using `auth.mode: header`, terminate authentication at this edge and only trust headers from that
proxy.

## 6. Back up the durable state

Back up the mounted collection directory, not the container image. The important state is:

- `gallery.yaml`
- `apps/`
- `feedback/app_feedback.sqlite`
- `feedback/shots/`
- `feedback/tasks/`
- `feedback/replies/`
- `.curiator-users.json` for local auth
- `.git/` and commits created by git-as-memory

SQLite sidecars can exist while the shell is running. Prefer a filesystem snapshot, or stop the
container before copying `feedback/app_feedback.sqlite*`.

## 7. Operate the pilot

Daily:

```bash
CURIATOR_GALLERY=/collection/gallery.yaml curiator queue list
git -C /collection status --short
```

Weekly:

```bash
CURIATOR_GALLERY=/collection/gallery.yaml curiator stats --markdown
CURIATOR_GALLERY=/collection/gallery.yaml curiator smoke
CURIATOR_GALLERY=/collection/gallery.yaml curiator playground-preflight --http-smoke
CURIATOR_GALLERY=/collection/gallery.yaml curiator playground-preflight
CURIATOR_GALLERY=/collection/gallery.yaml curiator queue sweep --older-than 30
```

Only close stale held feedback after reviewing the dry-run list:

```bash
CURIATOR_GALLERY=/collection/gallery.yaml curiator queue sweep --older-than 30 --apply --reason stale
```

Before widening the invite list, review:

- how many feedback items reached `done`, `awaiting_approval`, `held`, or `rejected`
- median first-reply latency from `curiator stats`
- curator commits and any `curiator revert` use
- prompt-injection or off-scope feedback patterns
- whether backups restore on a fresh machine

Only after that should phase 1 self-serve accounts or phase 2 anonymous feedback be enabled.
