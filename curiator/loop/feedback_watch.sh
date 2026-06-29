#!/usr/bin/env bash
# feedback_watch.sh — block until there is NEW (unprocessed) feedback, then exit.
#
# Run via the harness's run_in_background: it polls cheaply in bash and EXITS the
# moment app_feedback.json has a status:"new" non-system entry. The harness then
# re-invokes Claude, who processes the feedback (plan-then-approve, leaving code
# changes uncommitted) and relaunches this watcher. Because the watcher fires only
# on "new" entries — and processing moves them off "new" — Claude's own writes
# (statuses, ⚙ notes) do NOT re-trigger it, so there are no wasted wake-ups.
#
# Stop the loop by killing this background task (it just stops re-arming).
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
F="$DIR/feedback/app_feedback.json"
INTERVAL="${1:-5}"   # poll seconds

count_new() {
  python3 - "$F" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print(0); raise SystemExit
print(sum(1 for v in d.values() for e in v
          if e.get("kind") != "system" and e.get("status") == "new"))
PY
}

while true; do
  n="$(count_new)"
  if [ "${n:-0}" -gt 0 ] 2>/dev/null; then
    echo "NEW_FEEDBACK=$n  ($(date '+%H:%M:%S'))"
    exit 0
  fi
  sleep "$INTERVAL"
done
