"""ledger.py — SQLite-backed feedback ledger.

Runtime state lives in ``feedback/app_feedback.sqlite``.  ``app_feedback.json`` is read only as a
legacy import source when a collection has no SQLite DB yet; curIAtor does not keep a second live copy.

Public shape is unchanged:

    { "<app_key>": [ {id, author, kind, comment, stars, status, ts, screenshot, reply_to?}, ... ] }

Statuses: "new" → "working" → "awaiting_approval" → "done"; public/moderation flows may hold
feedback as "held" or close it as "rejected" (+ system notes use status "update").
A system/agent note has author="claude", kind="system".
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    """UTC, tz-aware (e.g. 2026-06-29T17:06:15+00:00)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def feedback_dir(cfg: dict) -> Path:
    return Path(cfg.get("repo_root", ".")) / (cfg.get("feedback", {}).get("dir", "feedback"))


def json_path(cfg: dict) -> Path:
    return feedback_dir(cfg) / "app_feedback.json"


def db_path(cfg: dict) -> Path:
    return feedback_dir(cfg) / "app_feedback.sqlite"


def path(cfg: dict) -> Path:
    """Primary runtime ledger path. Kept for callers that print/watch the ledger location."""
    return db_path(cfg)


def storage_mtime(cfg: dict) -> float:
    """Newest mtime across SQLite runtime files."""
    paths = [db_path(cfg), db_path(cfg).with_name(db_path(cfg).name + "-wal")]
    mtimes = []
    for p in paths:
        try:
            mtimes.append(p.stat().st_mtime)
        except OSError:
            pass
    return max(mtimes, default=0)


def _read_json_snapshot(cfg: dict) -> dict:
    p = json_path(cfg)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _init_schema(cfg: dict, conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
            app_key TEXT NOT NULL,
            id TEXT NOT NULL,
            ts TEXT,
            author TEXT,
            kind TEXT,
            status TEXT,
            payload TEXT NOT NULL,
            PRIMARY KEY (app_key, id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_status ON entries(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_entries_app ON entries(app_key)")
    _migrate_json_if_empty(cfg, conn)


def _connect(cfg: dict) -> sqlite3.Connection:
    p = db_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30)
    conn.row_factory = sqlite3.Row
    _init_schema(cfg, conn)
    return conn


def _connect_for_load(cfg: dict) -> sqlite3.Connection | None:
    """Open an existing SQLite ledger without write-time setup.

    `curiator status/context/feedback show` are read paths. Re-running schema setup and
    `PRAGMA journal_mode=WAL` on every read dirties git-tracked ledgers, which breaks the
    git-as-memory story for collections that inspect history between commits.
    """
    p = db_path(cfg)
    if not p.exists():
        # Legacy JSON import is intentionally a one-time write; otherwise a missing ledger is just empty.
        return _connect(cfg) if json_path(cfg).exists() else None
    uri = f"file:{p.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_json_if_empty(cfg: dict, conn: sqlite3.Connection) -> None:
    """Import a legacy JSON ledger once for old collections or tests that seed only JSON."""
    n = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    if n:
        return
    data = _read_json_snapshot(cfg)
    if not data:
        return
    with conn:
        for app_key, entries in data.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict) and entry.get("id"):
                    _insert_payload(conn, app_key, entry)


def _insert_payload(conn: sqlite3.Connection, app_key: str, payload: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO entries(app_key, id, ts, author, kind, status, payload)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            app_key,
            payload.get("id"),
            payload.get("ts"),
            payload.get("author"),
            payload.get("kind"),
            payload.get("status"),
            json.dumps(payload, separators=(",", ":")),
        ),
    )


def load(cfg: dict) -> dict:
    conn = _connect_for_load(cfg)
    if conn is None:
        return {}
    with closing(conn):
        data: dict[str, list[dict]] = {}
        try:
            rows = conn.execute("SELECT app_key, payload FROM entries ORDER BY rowid").fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            conn.close()
            with closing(_connect(cfg)) as writable:
                rows = writable.execute("SELECT app_key, payload FROM entries ORDER BY rowid").fetchall()
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except json.JSONDecodeError:
                continue
            data.setdefault(row["app_key"], []).append(payload)
        return data


def replace_all(cfg: dict, data: dict) -> None:
    """Replace the full ledger. Used by demo reset/import paths; normal callers append/update entries."""
    with closing(_connect(cfg)) as conn:
        with conn:
            conn.execute("DELETE FROM entries")
            for app_key, entries in (data or {}).items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if isinstance(entry, dict) and entry.get("id"):
                        _insert_payload(conn, app_key, entry)


def set_status(cfg: dict, key: str, ids: list[str], status: str) -> None:
    ids = set(ids or [])
    with closing(_connect(cfg)) as conn:
        rows = conn.execute(
            "SELECT id, payload FROM entries WHERE app_key = ? AND id IN (%s)" % ",".join("?" for _ in ids),
            [key, *ids],
        ).fetchall() if ids else []
        with conn:
            for row in rows:
                payload = json.loads(row["payload"])
                payload["status"] = status
                _insert_payload(conn, key, payload)


def update_entry(cfg: dict, key: str, entry_id: str, fields: dict) -> None:
    """Merge fields into one entry payload."""
    if not entry_id or not fields:
        return
    with closing(_connect(cfg)) as conn:
        row = conn.execute(
            "SELECT payload FROM entries WHERE app_key = ? AND id = ?", (key, entry_id)
        ).fetchone()
        if not row:
            return
        payload = json.loads(row["payload"])
        payload.update(fields)
        with conn:
            _insert_payload(conn, key, payload)


def amend_note(cfg: dict, key: str, note_id: str, suffix: str) -> None:
    """Append text to an existing note's comment."""
    with closing(_connect(cfg)) as conn:
        row = conn.execute(
            "SELECT payload FROM entries WHERE app_key = ? AND id = ?", (key, note_id)
        ).fetchone()
        if not row:
            return
        payload = json.loads(row["payload"])
        payload["comment"] = (payload.get("comment", "") or "") + suffix
        with conn:
            _insert_payload(conn, key, payload)


def add_system_note(
    cfg: dict,
    key: str,
    text: str,
    reply_to: list[str] | None = None,
    status: str = "update",
    ts: str | None = None,
    actions=None,
    agent: str | None = None,
) -> str:
    """Append an agent/⚙ note."""
    norm = [[a, a] if isinstance(a, str) else list(a) for a in actions] if actions else None
    nid = uuid.uuid4().hex[:8]
    payload = {
        "id": nid,
        "author": "claude",
        "kind": "system",
        "comment": text,
        "status": status,
        "reply_to": reply_to or [],
        "ts": ts or _now(),
        "actions": norm,
        "agent": agent,
    }
    with closing(_connect(cfg)) as conn:
        with conn:
            _insert_payload(conn, key, payload)
    return nid


def save_entry(
    cfg: dict,
    key: str,
    *,
    entry_id: str | None = None,
    stars=None,
    comment="",
    screenshot=None,
    ts=None,
    user=None,
    extra: dict | None = None,
) -> str:
    """Append a user feedback entry. `user` = {id, email, name} provenance."""
    eid = entry_id or uuid.uuid4().hex[:8]
    payload = {
        "id": eid,
        "author": "user",
        "kind": "comment",
        "comment": comment,
        "stars": stars,
        "status": "new",
        "screenshot": screenshot,
        "ts": ts or _now(),
        "user": user,
    }
    if extra:
        payload.update(extra)
    with closing(_connect(cfg)) as conn:
        with conn:
            _insert_payload(conn, key, payload)
    return eid


def checkpoint(cfg: dict) -> None:
    """Flush WAL pages into the main SQLite file, useful before optional git snapshots."""
    with closing(_connect(cfg)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
