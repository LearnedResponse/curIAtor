# Backlog — Node-RED overlay

> **Status:** completed and retired 2026-07-11 in runner commit `a3f64f4` and example collection
> `curiator-nodered@7e964fb`. `curiator app create --template nodered` emits the settings, seed flow,
> structural/HTTP/WebSocket smokes, and preserve-prefix mount. `curiator-nodered@7e964fb` passes strict
> dependency-prepared fresh-clone doctor, HTTP, and browser preflight, while feedback `b9e6c6e8` records
> the uptime/status improvement as git-as-memory commit `c4d5c67`.

## Delivered evidence (2026-07-11)

- The scaffold creates `package.json`/lock-ready Node-RED 5 dependencies, dynamic `CURIATOR_APP`
  `httpAdminRoot` and `httpNodeRoot`, deterministic flow/credential settings, a heartbeat and mounted
  health endpoint, clean first-run telemetry settings, and local security guidance.
- Doctor distinguishes missing `preserve_prefix`, missing settings, incorrect admin/API roots, and a
  missing credential secret. `smoke_http.path` is correctly treated as an HTTP route rather than a
  machine-absolute filesystem path.
- The example collection's health flow returns real process uptime, stable `operational` status, and a
  `fresh-restart`/`steady` phase. Its checked-in WebSocket client toggles runtime state and requires the
  matching `notification/runtime-state` push through `/app/flow_ops/comms`.
- `commands.bootstrap: npm ci --no-audit --no-fund` plus
  `release-preflight --prepare-dependencies` proves the runtime from a clean clone without borrowing the
  canonical checkout's `node_modules` or port. Strict fresh-clone HTTP and browser passes both succeed
  with zero console errors.

## Why it matters

Node-RED is the canonical "the app the user maintains is a flow editor, and the value is the flows/logic
behind it" case — a live, WebSocket-driven editor over a running runtime. It's the strongest proof that
curIAtor overlays *any* interactive web app, not just request/response dashboards, and a natural pairing
with the OT/HMI story (Node-RED is common MING glue).

## The recipe (verified)

Two pieces have to agree on the base path so the editor's absolute asset links + its WebSocket resolve
through the `/app/<name>/` mount:

**1. curIAtor mount** — a prefix-preserving proxy, so `/app/nodered/...` reaches Node-RED verbatim:

```yaml
apps:
  - name: nodered
    root: apps/nodered
    mount: { kind: proxy, cmd: "node-red --settings ./settings.js", port: 1880, preserve_prefix: true }
    smoke: "node --check node_modules/node-red/red.js"   # or a real boot + /settings health poll
```

**2. Node-RED `settings.js`** — serve the editor (and `/comms`) UNDER the mount prefix:

```js
module.exports = {
  uiPort: process.env.PORT || 1880,
  httpAdminRoot: "/app/nodered/",     // editor + the /app/nodered/comms WebSocket
  httpNodeRoot: "/app/nodered/api/",  // http-in / dashboard nodes, also under the prefix
  userDir: __dirname + "/userdir",
  credentialSecret: "…set-me…",
  editorTheme: { tours: false },
};
```

`preserve_prefix: true` makes curIAtor forward `/app/nodered/comms` (etc.) to Node-RED unchanged;
`httpAdminRoot` makes Node-RED emit links + open its comms socket under that same path. Without both, the
editor's `/vendor/**` and `/comms` requests escape the mount and 404 against the shell.

## What was verified (real Node-RED 5.0.1, behind the real proxy)

- `GET /app/nodered/` → the editor HTML loads through the overlay (Node-RED markers present).
- `GET /app/nodered/settings` → real runtime settings (`version 5.0.1`, `httpNodeRoot=/app/nodered/api/`).
- `ws://…/app/nodered/comms` → **bridged**; the client subscribed and received a live Node-RED push
  (`notification/runtime-state → start`). Editor deploy/debug traffic rides this socket.

## To turn into an example (the actual work)

1. **A `nodered` scaffold/import template** — `curiator app create <name> --template nodered` (or
   `curiator app import` a Node-RED project) that emits `apps/<name>/` with `package.json`
   (`node-red` dep), the `settings.js` above (base path pre-filled with the app key), a `userDir/` with a
   seed flow, and the prefix-preserving `gallery.yaml` mount + smoke. This is the one-command payoff.
2. **`curiator doctor` awareness** — it already warns about missing base-path config for proxy mounts;
   add Node-RED to that check (flag a Node-RED mount whose `settings.js` lacks `httpAdminRoot == /app/<name>/`).
3. **An example collection** — `curiator-nodered` (or fold a flow app into `curiator-ot`, since Node-RED
   is MING glue): a rough starter flow + seeded feedback that drives it toward something (naming, error
   handling, a dashboard). The git log becomes the flow's build story, same as the other collections.

## Gotchas / notes

- **`credentialSecret`** must be set or Node-RED warns and rotates a key each boot; pin it for repeatable
  demos (it's not a real secret in a single-tenant local collection, but don't commit a shared one).
- **Editor auth** (`adminAuth`) is off in the recipe for a frictionless demo; a hosted/playground
  deployment should gate it (curIAtor's own auth gates *feedback*, not the proxied app's editor).
- **Screenshot moat**: the Node-RED canvas is exactly where `html2canvas` is weakest — the ★/📷 capture
  will lean on the upload / `getDisplayMedia` fallback for this app (a known general-JS-hosting limit).
- Node-RED boots in a couple seconds; the proxy's cold-start connect-retry (both HTTP and WS paths) covers
  it, but a real `smoke`/health check should poll `/app/<name>/settings` rather than just import.
