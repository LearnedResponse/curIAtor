#!/usr/bin/env bash
# feedback_watch.sh — block until there is NEW (unprocessed) feedback, then exit.
#
# Run via the harness's run_in_background: it polls cheaply in bash and EXITS the
# moment the SQLite ledger has a status:"new" non-system entry. The harness then
# re-invokes Claude, who processes the feedback (plan-then-approve, leaving code
# changes uncommitted) and relaunches this watcher. Because the watcher fires only
# on "new" entries — and processing moves them off "new" — Claude's own writes
# (statuses, ⚙ notes) do NOT re-trigger it, so there are no wasted wake-ups.
#
# Stop the loop by killing this background task (it just stops re-arming).
set -u
ROOT="${CURIATOR_REPO_ROOT:-$(pwd)}"
DB="${CURIATOR_FEEDBACK_DB:-$ROOT/feedback/app_feedback.sqlite}"
INTERVAL="${1:-5}"   # poll seconds

count_new() {
  python3 - "$DB" <<'PY' 2>/dev/null
import json, sqlite3, sys
from pathlib import Path

db = Path(sys.argv[1])
if not db.exists():
    print(0)
    raise SystemExit
try:
    con = sqlite3.connect(str(db))
    rows = con.execute("SELECT payload FROM entries WHERE status = 'new'").fetchall()
except Exception:
    print(0)
    raise SystemExit
print(sum(1 for (raw,) in rows
          if (json.loads(raw) or {}).get("kind") != "system"))
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
