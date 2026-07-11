"""SQLite lifecycle registry for Docker fork workspaces."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from . import ledger


WORKSPACE_FIELDS = (
    "id", "name", "app_key", "owner_id", "mode", "status", "collection_repo",
    "collection_base_sha", "owning_repo", "owning_repo_base_sha", "owning_repo_rel", "branch",
    "container_id", "container_name", "source_volume", "state_volume", "host_port", "container_port",
    "image", "image_digest", "runner_version", "created_at", "last_activity_at", "expires_at",
    "preserved_ref", "promoted_at", "failure_reason", "descriptor_json",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(cfg: dict) -> sqlite3.Connection:
    path = ledger.db_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger.ensure_schema(cfg)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workspaces (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            app_key TEXT NOT NULL,
            owner_id TEXT,
            mode TEXT NOT NULL,
            status TEXT NOT NULL,
            collection_repo TEXT NOT NULL,
            collection_base_sha TEXT NOT NULL,
            owning_repo TEXT NOT NULL,
            owning_repo_base_sha TEXT NOT NULL,
            owning_repo_rel TEXT,
            branch TEXT,
            container_id TEXT,
            container_name TEXT,
            source_volume TEXT NOT NULL,
            state_volume TEXT NOT NULL,
            host_port INTEGER,
            container_port INTEGER NOT NULL,
            image TEXT NOT NULL,
            image_digest TEXT,
            runner_version TEXT,
            created_at TEXT NOT NULL,
            last_activity_at TEXT NOT NULL,
            expires_at TEXT,
            preserved_ref TEXT,
            promoted_at TEXT,
            failure_reason TEXT,
            descriptor_json TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_workspaces_status ON workspaces(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_workspaces_app ON workspaces(app_key)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_workspace_events_id ON workspace_events(workspace_id, event_id)")
    return conn


def _decode(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    payload = dict(row)
    try:
        payload["descriptor"] = json.loads(payload.pop("descriptor_json"))
    except (TypeError, json.JSONDecodeError):
        payload["descriptor"] = {}
    return payload


def create(cfg: dict, payload: dict) -> dict:
    row = dict(payload)
    now_value = now()
    row.setdefault("created_at", now_value)
    row.setdefault("last_activity_at", now_value)
    row.setdefault("owner_id", None)
    row.setdefault("expires_at", None)
    row.setdefault("preserved_ref", None)
    row.setdefault("promoted_at", None)
    row.setdefault("failure_reason", None)
    row.setdefault("container_id", None)
    row.setdefault("host_port", None)
    row.setdefault("image_digest", None)
    row.setdefault("runner_version", None)
    row["descriptor_json"] = json.dumps(row.pop("descriptor", {}), sort_keys=True)
    missing = [field for field in WORKSPACE_FIELDS if field not in row]
    if missing:
        raise ValueError(f"workspace row missing fields: {', '.join(missing)}")
    with closing(_connect(cfg)) as conn:
        conn.execute(
            f"INSERT INTO workspaces ({', '.join(WORKSPACE_FIELDS)}) VALUES "
            f"({', '.join('?' for _ in WORKSPACE_FIELDS)})",
            [row[field] for field in WORKSPACE_FIELDS],
        )
        conn.execute(
            "INSERT INTO workspace_events(workspace_id, ts, kind, payload) VALUES (?, ?, ?, ?)",
            (row["id"], now_value, "created", json.dumps({"status": row["status"]}, sort_keys=True)),
        )
        conn.commit()
    return get(cfg, row["id"]) or {}


def update(cfg: dict, workspace_id: str, **changes) -> dict:
    if not changes:
        return get(cfg, workspace_id) or {}
    allowed = set(WORKSPACE_FIELDS) - {"id", "created_at", "descriptor_json"}
    unknown = set(changes) - allowed - {"descriptor"}
    if unknown:
        raise ValueError(f"unknown workspace fields: {', '.join(sorted(unknown))}")
    if "descriptor" in changes:
        changes["descriptor_json"] = json.dumps(changes.pop("descriptor"), sort_keys=True)
    changes.setdefault("last_activity_at", now())
    assignments = ", ".join(f"{field} = ?" for field in changes)
    with closing(_connect(cfg)) as conn:
        result = conn.execute(
            f"UPDATE workspaces SET {assignments} WHERE id = ?",
            [*changes.values(), workspace_id],
        )
        if result.rowcount != 1:
            raise KeyError(workspace_id)
        conn.commit()
    return get(cfg, workspace_id) or {}


def event(cfg: dict, workspace_id: str, kind: str, payload: dict | None = None) -> None:
    with closing(_connect(cfg)) as conn:
        conn.execute(
            "INSERT INTO workspace_events(workspace_id, ts, kind, payload) VALUES (?, ?, ?, ?)",
            (workspace_id, now(), kind, json.dumps(payload or {}, sort_keys=True)),
        )
        conn.commit()


def get(cfg: dict, workspace_id: str) -> dict | None:
    with closing(_connect(cfg)) as conn:
        row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
    return _decode(row)


def list_all(cfg: dict, *, include_deleted: bool = False) -> list[dict]:
    where = "" if include_deleted else "WHERE status != 'deleted'"
    with closing(_connect(cfg)) as conn:
        rows = conn.execute(f"SELECT * FROM workspaces {where} ORDER BY created_at DESC").fetchall()
    return [_decode(row) or {} for row in rows]


def events(cfg: dict, workspace_id: str) -> list[dict]:
    with closing(_connect(cfg)) as conn:
        rows = conn.execute(
            "SELECT event_id, workspace_id, ts, kind, payload FROM workspace_events "
            "WHERE workspace_id = ? ORDER BY event_id",
            (workspace_id,),
        ).fetchall()
    out = []
    for row in rows:
        payload = dict(row)
        try:
            payload["payload"] = json.loads(payload["payload"])
        except json.JSONDecodeError:
            pass
        out.append(payload)
    return out


def _portable_value(value, replacements: list[tuple[str, str]]):
    if isinstance(value, dict):
        return {key: _portable_value(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable_value(item, replacements) for item in value]
    if isinstance(value, str):
        for absolute, portable in replacements:
            if absolute:
                value = value.replace(absolute, portable)
    return value


def sanitize_deleted(cfg: dict, workspace_id: str) -> dict:
    """Remove host-absolute paths from a terminal workspace receipt while retaining replay metrics."""
    row = get(cfg, workspace_id)
    if not row:
        raise KeyError(workspace_id)
    if row.get("status") != "deleted":
        raise ValueError(f"workspace {workspace_id} is not deleted")
    owning_portable = row.get("owning_repo_rel") or "."
    replacements = sorted(
        [
            (str(row.get("owning_repo") or ""), str(owning_portable)),
            (str(row.get("collection_repo") or ""), "."),
        ],
        key=lambda item: len(item[0]),
        reverse=True,
    )
    descriptor = _portable_value(row.get("descriptor") or {}, replacements)
    failure_reason = _portable_value(row.get("failure_reason"), replacements)
    with closing(_connect(cfg)) as conn:
        conn.execute(
            "UPDATE workspaces SET collection_repo = ?, owning_repo = ?, failure_reason = ?, "
            "descriptor_json = ? WHERE id = ?",
            (".", owning_portable, failure_reason, json.dumps(descriptor, sort_keys=True), workspace_id),
        )
        event_rows = conn.execute(
            "SELECT event_id, payload FROM workspace_events WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchall()
        for event_row in event_rows:
            try:
                payload = json.loads(event_row["payload"])
            except json.JSONDecodeError:
                payload = event_row["payload"]
            portable_payload = _portable_value(payload, replacements)
            encoded = (
                json.dumps(portable_payload, sort_keys=True)
                if not isinstance(portable_payload, str)
                else portable_payload
            )
            conn.execute(
                "UPDATE workspace_events SET payload = ? WHERE event_id = ?",
                (encoded, event_row["event_id"]),
            )
        conn.commit()
    return get(cfg, workspace_id) or {}


def compact_deleted(cfg: dict) -> dict:
    """Sanitize every deleted receipt and VACUUM the shared ledger/registry file."""
    with closing(_connect(cfg)) as conn:
        ids = [row["id"] for row in conn.execute("SELECT id FROM workspaces WHERE status = 'deleted'")]
    for workspace_id in ids:
        sanitize_deleted(cfg, workspace_id)
    compacted = ledger.compact(cfg)
    return {"sanitized_workspaces": len(ids), **compacted}
