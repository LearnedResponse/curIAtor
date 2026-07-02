# Screenshot capture options

curIAtor's feedback panel needs a picture of the app at the moment a user leaves feedback. That image
is part of the task bundle an agent reads, so capture fidelity matters. The current implementation is
deliberately simple and local-first.

## Default path: same-origin `html2canvas`

The gallery mounts every app under the same origin, `/app/<name>/...`, then the browser calls
`html2canvas` against the app iframe's document body. This is why curIAtor uses same-origin proxying
instead of pointing iframes directly at random ports: without same-origin access, the shell cannot read
the iframe DOM to capture it.

Strengths:

- no desktop permissions prompt
- no server-side browser process
- captures normal DOM/CSS dashboards well enough for contextual feedback
- keeps the screenshot in the same feedback submission flow

Limits:

- canvas/WebGL/Plotly internals, video, maps, and some modern CSS can render incompletely
- cross-origin images/fonts may be missing unless the app serves them with compatible CORS headers
- the capture is of the browser-rendered DOM, not the operating-system window
- any sensitive state visible in the iframe can be stored in `feedback/shots/`

The **Native** button is the first fallback: if DOM capture fidelity is bad, a signed-in reviewer can
use browser screen capture to grab the rendered tab/window pixels. The upload button remains the final
manual fallback for attaching a cropped screenshot. Anonymous-held feedback only gets same-origin
**Capture view**; upload and native screen capture are disabled and rejected server-side because they
can attach arbitrary pixels.

Captured or uploaded screenshots can be annotated before saving. The current v1 tools burn boxes,
arrows, numbered pins, and redaction rectangles into the PNG in the browser, before it is posted to
the feedback ledger. That keeps the existing task-bundle path unchanged while letting the agent read
a marked-up image directly. In the React shell, non-redaction marks also store sanitized normalized
coordinates, per-mark notes, and same-origin DOM target hints when available. Redactions and unreadable
or cross-origin app frames intentionally save without DOM targets. Prior feedback threads can reopen
saved annotated entries as a scrollable preview of the marked screenshot and structured mark list, or
load a copy of that screenshot and mark set into a reply draft for further markup.

## Browser screen capture: `getDisplayMedia`

The React shell includes an opt-in **Native** button that calls
`navigator.mediaDevices.getDisplayMedia()` and captures the selected tab/window/screen into the same
annotation/save flow. It is the best browser-native candidate for canvas/WebGL fidelity because it
captures pixels after rendering.

Tradeoffs:

- the browser must show a permission picker every time
- users can accidentally share the wrong window or extra sensitive content
- automation and headless use are awkward
- the UX is heavier than one-click DOM capture

Best fit: signed-in/trusted reviewers working on apps with canvas/WebGL-heavy views. It is intentionally
not the default path for every feedback item.

## Server-side browser capture: Playwright

A server-side Playwright/Chromium worker can open `/app/<name>/...` and take a screenshot from the
runner side.

Tradeoffs:

- better pixel fidelity for many complex apps
- can be made deterministic for release demos and regression artifacts
- adds a browser dependency, more CPU/memory, and more sandboxing responsibility
- must authenticate as the right user/session to see private app state
- increases the blast radius if public feedback can trigger captures of sensitive internal pages

Best fit: trusted deployments that want a higher-fidelity optional capture service, or release/demo
automation. Keep it behind explicit config and the collection containment boundary.

## Extension or native helper

A browser extension or small native helper can capture the tab with stronger pixel fidelity and fewer
same-origin constraints.

Tradeoffs:

- best access to the actual rendered tab
- installation and update burden for every reviewer
- a much larger trust surface than a normal web page
- browser-store review or local enterprise deployment may be required

Best fit: controlled internal environments where reviewers can install a managed helper and screenshot
fidelity is more important than zero-install feedback.

## Default recommendation

Keep `html2canvas` as the default because it preserves curIAtor's low-friction loop. Use native capture
as the browser-native fallback for specific collections where screenshot fidelity is a known blocker;
treat server-side capture or helper extensions as heavier deployment-specific options.

Security rule: screenshots are data. Before publishing a collection or sharing a ledger, review
`feedback/shots/` just like source, task bundles, replies, and git history.
