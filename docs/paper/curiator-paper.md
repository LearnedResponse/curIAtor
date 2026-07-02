---
title: "curIAtor: An AI-Maintained Web App Feedback Overlay"
author: "Adam Guetz"
date: "TODO(release)"
---

# Abstract

curIAtor puts a feedback affordance inside a running web application gallery: users rate, comment on,
annotate, and screenshot the live app; a coding agent receives the feedback, local context, and source
scope; the agent edits, smoke-tests, reloads, and replies in the same thread. The system treats the
feedback ledger and git history as the durable record of maintenance work. This draft describes the
overlay design, the agent loop, and the evidence expected from three public example collections.

TODO(release): replace this abstract with one paragraph that includes the final public collection count,
cycle count, and DOI.

# 1. Motivation

Users experience software in the running interface, while maintainers usually receive feedback through
issue trackers, chat, or screenshots detached from the application state. Coding agents make small
interface and data-app fixes cheap enough that the bottleneck shifts to capturing the right feedback in
context. curIAtor addresses that bottleneck by placing feedback capture around the app itself.

The core claim is narrow: contextual app feedback plus a coding-agent loop can turn maintenance into a
conversation, and a git log can serve as the durable memory of that conversation.

# 2. System Design

curIAtor is a same-origin gallery shell. Each app is mounted under `/app/<name>/...`, either in-process
for Dash apps or through a same-origin proxy for any local HTTP server. The same-origin constraint is
load-bearing: the shell can capture screenshots, annotate them, and attach the result to feedback
without changing each app's source code.

Feedback is stored in a SQLite ledger. A feedback entry can include a star rating, comment, screenshot,
burned-in annotations, structured annotation metadata, author identity, status, and reply-thread links.
Per-feedback task bundles live under `feedback/tasks/`; live agent traces live under
`feedback/replies/`.

The watcher turns eligible feedback into an agent task. The task bundle includes the thread context,
source scope, screenshot path, app-specific smoke command, collection instructions, and prior lessons.
The agent can run in several modes: a local CLI adapter, an API adapter, or a custom command adapter.
The autonomy setting determines whether the agent applies small fixes directly or drafts a proposal.

When git-as-memory is enabled, each accepted agent run becomes one commit with provenance trailers. The
commit, ledger entry, and reply thread remain linked, making the history inspectable and revertible.
The end-to-end loop is summarized in [Figure 1](figures/feedback-loop.mmd), which is kept as a
repo-native Mermaid source until the release PDF export. A concrete commit excerpt is kept in
[Figure 2](figures/provenance-log-excerpt.md), showing how feedback text, app scope, smoke-test
status, feedback id, author, and agent co-author ride in the git history.

# 3. Case Studies

The release paper should report three public collections:

- `curiator-aviato`: mixed-framework app hosting, including Dash, React/Node, and Rust proxy mounts.
- `curiator-ot`: an OT/HMI maintenance example where feedback moves a rough process display toward
  higher-performance HMI conventions.
- `curiator-geometry`: a low-friction public math/geometry quickstart collection.

TODO(release): insert the `curiator stats compare` table generated from fresh clones of the public
collection repositories.

TODO(release): include one short paragraph for each collection that references the exact repository URL,
release commit, feedback-cycle count, and smoke/preflight result.

The private origin collection may be discussed only in aggregate, and only with an explicit caveat that
its ledger and research apps are not part of the public evidence set.

# 4. Lessons and Limitations

The overlay makes feedback more precise, especially when screenshots and annotations are available, but
it does not remove the need for review. Public feedback is untrusted prompt input to an agent with edit
permissions. curIAtor's mitigations are operational controls: authentication, held queues, quotas,
propose-only mode, least-privilege credentials, and one collection per containment boundary.

The same-origin capture path uses `html2canvas`, which is lightweight and zero-install but imperfect for
canvas/WebGL, video, cross-origin assets, and some modern CSS. Upload, browser-native capture, or
server-side capture can be added for deployments that need higher fidelity.

The proxy mount intentionally keeps the built-in reverse proxy lightweight. Development-server HMR and
WebSocket upgrades receive diagnostics rather than full live-HMR support. Production-style deployments
can put a full reverse proxy such as nginx or Caddy in front.

The work is a system/tooling paper, not an agent-model benchmark. The relevant evidence is whether the
loop closes on realistic app feedback with traceable commits, not which model wins a synthetic task.

# 5. Related Work

TODO(draft): cover agentic coding CLIs, in-context visual feedback tools, ChatOps workflows, research
software engineering, JOSS-style tool papers, and app-hosting/gallery platforms.

# 6. Availability

curIAtor is released under Apache-2.0.

TODO(release): add GitHub, PyPI, Zenodo DOI, documentation URL, and the exact version used for the paper.

# Acknowledgements

TODO(draft).
