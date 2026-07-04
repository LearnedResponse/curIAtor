# curIAtor — one container per collection.
#
# The container is the blast-radius boundary: the curator auto-EDITS and RUNS your app code, so each
# collection gets its own sandbox. The collection (apps + gallery.yaml + the feedback ledger) is a
# mounted volume, so history + the agent's accumulated context survive restarts.
#
#   docker build -t curiator .
#   docker compose up            # see docker-compose.yml (mounts ./collection, exposes the gallery)
FROM python:3.12-slim

# git: the curator stages edits / patches the runner in checkout mode.
# nodejs: the `claude` CLI (the headless-cc adapter) is a Node app — keep it at runtime.
# Skip Node entirely if you only use the `api` adapter (pass ANTHROPIC_API_KEY instead).
RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates nodejs npm \
 && npm install -g @anthropic-ai/claude-code \
 && npm cache clean --force \
 && rm -rf /var/lib/apt/lists/*

# The runner, pinned. For a local / pre-PyPI build, override the spec, e.g.:
#   docker build --build-arg CURIATOR_PIP="curiator==0.0.1" -t curiator .
# or build from a checkout you COPY into the context (--build-arg CURIATOR_PIP=/src + a COPY line).
ARG CURIATOR_PIP=curiator
RUN pip install --no-cache-dir ${CURIATOR_PIP}

# The collection mounts here: apps + gallery.yaml + feedback/ (the ledger) + an optional LESSONS.md
# (the context bundle the api adapter reads). The entrypoint passes the gallery explicitly so the
# selector is scoped to this process invocation instead of ambiently granted to every child tool.
WORKDIR /collection
ENV SHELL_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1

EXPOSE 8300

# `serve` = `up` (gallery) + `watch` (the fix loop) in one process, against the mounted collection.
ENTRYPOINT ["curiator", "--gallery", "/collection/gallery.yaml", "serve"]
