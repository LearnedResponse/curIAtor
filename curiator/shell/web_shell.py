"""web_shell.py — Flask + React overlay shell.

The overlay UI is framework-neutral; Dash remains an app mount type (`dash-inproc`), not the shell
framework. This module reuses the app/proxy supervisor and ledger helpers from app_shell while serving
a React UI and JSON API from plain Flask.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, request, send_from_directory

from curiator.shell import app_shell as core
from curiator import auth, ledger
from curiator.transcripts import bounded_text, clean_transcript_segments


def _dash_deps_dir() -> Path:
    import dash
    return Path(dash.__file__).resolve().parent / "deps"


def _safe_entry(entry: dict) -> dict:
    out = dict(entry)
    if entry.get("screenshot"):
        out["shot_url"] = f"/feedback-shot/{Path(entry['screenshot']).name}"
    if entry.get("audio"):
        out["audio_url"] = f"/feedback-audio/{Path(entry['audio']).name}"
    trace = core._trace_path(entry.get("id"))
    if trace and trace.exists():
        out["trace_url"] = f"/feedback-trace/{entry.get('id')}"
    return out


def _metrics(key: str) -> dict:
    avg, n_open, n_total = core.app_metrics(key)
    return {"avg_stars": avg, "open": n_open, "total": n_total}


def _apps_payload() -> list[dict]:
    core.refresh_changed_app_sources()
    feedback = core.load_feedback()               # one ledger read for all apps' metrics + updated ts
    apps = []
    for rec in core.REGISTRY:
        items = feedback.get(rec["key"], [])
        avg, n_open, n_total = core.metrics_from(items)
        apps.append({
            "key": rec["key"],
            "title": rec.get("title", rec["key"]),
            "tags": rec.get("tags") or [],
            "color": rec.get("color", "#888"),
            "kind": rec.get("kind"),
            "port": rec.get("port"),
            "source": rec.get("source") or rec.get("file"),
            "root": rec.get("root"),
            "metrics": {"avg_stars": avg, "open": n_open, "total": n_total},
            "updated": core.app_updated(rec, items),
            "revision": core.APP_REVISIONS.get(rec["key"], 0),
        })
    return apps


def _general_payload() -> dict:
    return {
        "key": core.GENERAL_KEY,
        "title": "General — gallery & runner",
        "tags": [],
        "color": "#8e44ad",
        "kind": "general",
        "metrics": _metrics(core.GENERAL_KEY),
    }


def _feedback_payload(key: str) -> dict:
    items = [_safe_entry(e) for e in core.load_feedback().get(key, [])]
    tb = core.thread_buttons(items)
    actions = {"target": tb[0], "items": tb[1]} if tb else None
    return {"key": key, "items": items, "actions": actions}


def _queue_actor(user: dict | None) -> str:
    user = user or {}
    return user.get("email") or user.get("name") or user.get("id") or "shell admin"


def _queue_find(feedback_id: str) -> tuple[str, dict] | None:
    for key, items in core.load_feedback().items():
        for entry in items:
            if entry.get("id") == feedback_id:
                return key, entry
    return None


def _queue_rows() -> list[tuple[str, dict]]:
    rows = []
    for key, items in core.load_feedback().items():
        for entry in items:
            if entry.get("kind") != "system" and entry.get("status") == "held":
                rows.append((key, entry))
    return rows


def _queue_app_title(key: str) -> str:
    if key == core.GENERAL_KEY:
        return "General"
    rec = next((item for item in core.REGISTRY if item.get("key") == key), {})
    return rec.get("title") or key


def _queue_page_html(message: str = "") -> str:
    rows = _queue_rows()
    msg = (f"<p style='color:{core.GREEN};font-size:13px'>{core._esc(message)}</p>" if message else "")
    if not rows:
        return msg + "<p style='color:#777;font-size:13px'>No held feedback is waiting for review.</p>"
    cards = []
    for key, entry in rows:
        user = entry.get("user") or {}
        author = user.get("email") or user.get("name") or entry.get("author") or "user"
        stars = "★" * int(entry.get("stars") or 0)
        shot = ""
        if entry.get("screenshot"):
            shot = (f"<img src='/feedback-shot/{core._esc(Path(entry['screenshot']).name)}' "
                    "style='display:block;max-width:420px;margin-top:8px;border:1px solid #ddd;"
                    "border-radius:4px'>")
        cards.append(
            "<section style='border-left:4px solid #6f42c1;background:#fafafa;"
            "padding:10px 12px;margin:0 0 12px;border-radius:4px'>"
            f"<div style='font-size:12px;color:#777'><b>{core._esc(_queue_app_title(key))}</b> "
            f"<code>{core._esc(key)}</code> · <code>{core._esc(entry.get('id') or '')}</code> · "
            f"{core._esc(entry.get('ts') or '')}</div>"
            f"<div style='font-size:12px;color:#777;margin-top:2px'>{core._esc(author)} "
            f"<span style='color:#cc7a00'>{stars}</span></div>"
            f"<p style='font-size:14px;white-space:pre-wrap'>{core._esc(entry.get('comment') or '')}</p>"
            f"{shot}"
            f"<form method='post' action='/queue/{core._esc(entry.get('id') or '')}/approve' "
            "style='display:inline-block;margin-top:8px;margin-right:8px'>"
            "<button style='background:#1f9d55;color:white;border:none;border-radius:5px;"
            "padding:6px 13px;font-weight:700;cursor:pointer'>Approve</button></form>"
            f"<form method='post' action='/queue/{core._esc(entry.get('id') or '')}/reject' "
            "style='display:inline-flex;gap:6px;align-items:center;margin-top:8px'>"
            "<input name='reason' placeholder='optional rejection reason' "
            "style='font:inherit;font-size:12px;border:1px solid #ccc;border-radius:5px;padding:6px;width:220px'>"
            "<button style='background:#555;color:white;border:none;border-radius:5px;"
            "padding:6px 13px;font-weight:700;cursor:pointer'>Reject</button></form>"
            "</section>"
        )
    return msg + "".join(cards)


def _feedback_user_and_status(rate_limit_key: str | None = None) -> tuple[dict | None, str, str | None, int]:
    u = core._current_user()
    if auth.feedback_requires_identity(core.REG.AUTH_CFG) and not u:
        if not auth.allow_anonymous_feedback(core.REG.AUTH_CFG):
            return None, "new", "sign in required", 401
        key = rate_limit_key or request.remote_addr or "?"
        blocked, retry = auth.anonymous_feedback_rate_limit_status(core.REG.AUTH_CFG, key)
        if blocked:
            return None, "new", f"too many anonymous submissions; try again in {retry}s", 429
        auth.record_anonymous_feedback(core.REG.AUTH_CFG, key)
        return auth.anonymous_user(), "held", None, 0
    return u, "new", None, 0


def _voice_cfg() -> dict:
    cfg = getattr(core.REG, "VOICE_CFG", None)
    if not isinstance(cfg, dict):
        cfg = (getattr(core.REG, "CONFIG", {}) or {}).get("voice") or {}
    return cfg if isinstance(cfg, dict) else {}


def _voice_int(key: str, default: int, *, low: int, high: int) -> int:
    try:
        value = int(_voice_cfg().get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _voice_payload() -> dict:
    cfg = _voice_cfg()
    return {
        "local_transcribe": bool(cfg.get("transcribe_cmd")),
        "web_speech": bool(cfg.get("web_speech")),
        "web_speech_lang": str(cfg.get("web_speech_lang") or ""),
        "retain_audio": bool(cfg.get("retain_audio")),
        "max_bytes": _voice_int("transcribe_max_bytes", 25 * 1024 * 1024, low=1, high=200 * 1024 * 1024),
        "timeout": _voice_int("transcribe_timeout", 60, low=1, high=600),
    }


def _transcribe_args(command, audio_path: Path) -> list[str]:
    sentinel = "__CURIATOR_AUDIO_PATH__"
    if isinstance(command, list):
        parts = [str(part) for part in command if str(part)]
        if not parts:
            return []
        has_audio = any("{audio}" in part for part in parts)
        args = [part.replace("{audio}", str(audio_path)) for part in parts]
        return args if has_audio else [*args, str(audio_path)]
    if not isinstance(command, str) or not command.strip():
        return []
    text = command.strip()
    if "{audio}" in text:
        return [part.replace(sentinel, str(audio_path))
                for part in shlex.split(text.replace("{audio}", sentinel))]
    return [*shlex.split(text), str(audio_path)]


def _parse_transcript(stdout: str) -> dict:
    raw = stdout.strip()
    if not raw:
        return {"text": "", "segments": []}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"text": bounded_text(raw, 10000), "segments": []}
    if isinstance(data, list):
        segments = clean_transcript_segments(data)
        return {"text": bounded_text(" ".join(s["text"] for s in segments), 10000), "segments": segments}
    if not isinstance(data, dict):
        return {"text": bounded_text(raw, 10000), "segments": []}
    segments = clean_transcript_segments(data.get("segments"))
    text = bounded_text(data.get("text"), 10000)
    if not text and segments:
        text = bounded_text(" ".join(s["text"] for s in segments), 10000)
    return {"text": text, "segments": segments}


def _transcribe_allowed() -> tuple[str | None, int]:
    if auth.feedback_requires_identity(core.REG.AUTH_CFG) and not core._current_user():
        if not auth.allow_anonymous_feedback(core.REG.AUTH_CFG):
            return "sign in required", 401
    return None, 0


NEW_APP_TYPES = {
    "dash": {
        "label": "Dash",
        "template": "dash",
        "guidance": "Use for Python-first research dashboards and Plotly/Dash interaction loops.",
    },
    "react_node": {
        "label": "React + Node",
        "template": "react",
        "guidance": "Use for component-heavy frontends or server-rendered JavaScript experiments.",
    },
    "rust": {
        "label": "Rust server",
        "template": "rust",
        "guidance": "Use for small compiled HTTP services, algorithm demos, or backend-first prototypes.",
    },
    "react_rust": {
        "label": "React + Rust",
        "template": "react",
        "guidance": "Start with a React app and add a Rust service/proxy only if the request needs one.",
    },
    "github_repo": {
        "label": "GitHub repo",
        "template": "react",
        "guidance": "Import an existing repository with `curiator app import`, then adapt its host settings.",
    },
    "pyodide_wasm": {
        "label": "Pyodide / WASM",
        "template": "static",
        "guidance": "Use a static app that offloads Python or compute-heavy work to Pyodide/WASM in the browser.",
    },
    "static": {
        "label": "Static HTML",
        "template": "static",
        "guidance": "Use for lightweight single-file explainers with no runtime server.",
    },
    "other": {
        "label": "Other (will try to accommodate)",
        "template": "python",
        "guidance": "Use the brief to choose the closest supported host; Python is only the fallback.",
    },
}


def _clean_wizard_text(value, limit: int) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()[:limit]


def _wizard_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _slug_app_key(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    text = re.sub(r"_+", "_", text)
    if not text or not re.match(r"^[a-z]", text):
        text = f"app_{text}" if text else "new_app"
    return text[:60].strip("_") or "new_app"


def _available_app_key(seed: str) -> str:
    base = _slug_app_key(seed)
    if base not in core.BY_KEY:
        return base
    for idx in range(2, 100):
        key = f"{base}_{idx}"
        if key not in core.BY_KEY:
            return key
    return f"{base}_{uuid.uuid4().hex[:4]}"


def _new_app_request(body: dict) -> tuple[dict | None, str | None]:
    if not isinstance(body, dict):
        return None, "invalid request"
    app_type = str(body.get("app_type") or "dash")
    spec = NEW_APP_TYPES.get(app_type)
    if not spec:
        return None, "unknown app type"
    title = _clean_wizard_text(body.get("title"), 120)
    prompt = _clean_wizard_text(body.get("prompt"), 5000)
    notes = _clean_wizard_text(body.get("notes"), 2000)
    repo_url = _clean_wizard_text(body.get("repo_url"), 500)
    raw_key = _clean_wizard_text(body.get("app_key"), 80)
    dockerize = _wizard_bool(body.get("dockerize"))
    if app_type == "github_repo" and not repo_url:
        return None, "enter a GitHub repo URL"
    if not prompt and app_type != "github_repo":
        return None, "describe the app to create"
    seed = raw_key or title or Path(repo_url.rstrip("/")).stem.replace(".git", "") or prompt.splitlines()[0][:80]
    title = title or seed.replace("_", " ").replace("-", " ").strip().title() or spec["label"] + " app"
    app_key = _available_app_key(seed)
    request = {
        "kind": "new_app",
        "app_key": app_key,
        "title": title,
        "app_type": app_type,
        "app_type_label": spec["label"],
        "template": spec["template"],
        "prompt": prompt,
        "notes": notes,
        "repo_url": repo_url,
        "dockerize": dockerize,
        "guidance": spec["guidance"],
        "source": "new_app_wizard",
    }
    return request, None


def _new_app_comment(request: dict) -> str:
    lines = [
        "Create a new curIAtor app.",
        "",
        "Wizard selections:",
        f"- suggested app key: `{request['app_key']}`",
        f"- title: {request['title']}",
        f"- app type: {request['app_type_label']}",
        f"- scaffold template: `{request['template']}`",
        f"- guidance: {request['guidance']}",
    ]
    if request.get("repo_url"):
        lines.append(f"- source repo: {request['repo_url']}")
    if request.get("dockerize"):
        lines.append("- packaging: Dockerize requested")
    lines += [
        "",
        "App brief:",
        request["prompt"] or "Import the source repo, inspect its stack, and host it as a curIAtor app.",
    ]
    if request.get("notes"):
        lines += ["", "Implementation notes:", request["notes"]]
    lines.append("")
    if request.get("repo_url"):
        lines.append(
            "Please start with `curiator app import` so the repo is cloned under `apps/` as a nested "
            "app repo/subrepo, proxy/smoke metadata is registered in `gallery.yaml`, and future edits "
            "stay scoped to that imported app."
        )
    else:
        lines.append(
            "Please start with `curiator app create` so app directories, proxy commands, smoke hooks, "
            "and `gallery.yaml` are created consistently; then customize the scaffold for this brief."
        )
    return "\n".join(lines)


def _index() -> str:
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{core._esc(core.TITLE)}</title>
    <link rel="icon" href="/assets/favicon.ico">
    <link rel="stylesheet" href="/assets/shell.css">
    <link rel="stylesheet" href="/assets/react_shell.css">
  </head>
  <body>
    <div id="react-entry-point"></div>
    <script src="/vendor/react@18.3.1.min.js"></script>
    <script src="/vendor/react-dom@18.3.1.min.js"></script>
    <script src="/assets/html2canvas.min.js"></script>
    <script src="/assets/localtime.js"></script>
    <script src="/assets/react_shell.js"></script>
  </body>
</html>"""


def build_flask_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.secret_key = os.environ.get("CURIATOR_SECRET_KEY") or os.urandom(24)

    mode = core.REG.AUTH_CFG.get("mode", "none")
    if mode == "oidc":
        auth.register_oidc(core.REG.AUTH_CFG, app)
    elif mode == "local":
        @app.route("/login", methods=["GET", "POST"])
        def _local_login():
            from flask import session
            ip = request.remote_addr or "?"
            err = ""
            blocked, retry = auth.rate_limit_status(core.REG.AUTH_CFG, ip)
            if request.method == "POST" and not blocked:
                u = auth.verify_local(core.REG.AUTH_CFG, request.form.get("email", ""), request.form.get("password", ""))
                if u:
                    auth.clear_login_failures(ip)
                    session[auth.SESSION_KEY] = u
                    return redirect("/")
                auth.record_login_failure(core.REG.AUTH_CFG, ip)
                blocked, retry = auth.rate_limit_status(core.REG.AUTH_CFG, ip)
                err = "" if blocked else "<p style='color:#c0392b;font-size:13px;margin:0 0 8px'>Invalid email or password.</p>"
            if blocked:
                err = f"<p style='color:#c0392b;font-size:13px;margin:0 0 8px'>Too many attempts — try again in {retry}s.</p>"
            return core._page("Sign in", err + ("" if blocked else core._LOGIN_FORM))

        @app.route("/logout")
        def _local_logout():
            from flask import session
            session.pop(auth.SESSION_KEY, None)
            return redirect("/")
    else:
        @app.route("/login")
        def _login_info():
            return core._page("Sign in", f"<p>Sign-in is not enabled for this gallery (<code>auth.mode: {mode}</code>).</p>")

        @app.route("/logout")
        def _logout_noop():
            return redirect("/")

    @app.route("/")
    def _root():
        return _index()

    @app.route("/vendor/<path:name>")
    def _vendor(name):
        allowed = {"react@18.3.1.min.js", "react-dom@18.3.1.min.js"}
        if name not in allowed:
            return ("not found", 404)
        return send_from_directory(_dash_deps_dir(), name)

    @app.route("/assets/<path:name>")
    def _assets(name):
        return send_from_directory(core.HERE / "assets", name, max_age=0)

    @app.route("/api/bootstrap")
    def _bootstrap():
        u = auth.current_user(core.REG.AUTH_CFG)
        return jsonify({
            "title": core.TITLE,
            "collection": core.COLLECTION_NAME,
            "general_key": core.GENERAL_KEY,
            "general": _general_payload(),
            "poll_ms": max(core.POLL_MS, 1000) if core.POLL_MS > 0 else 0,
            "apps": _apps_payload(),
            "tags": [{"name": k, "color": v} for k, v in core.TAG_META],
            "user": u or {"authenticated": False},
            "auth": {
                "mode": core.REG.AUTH_CFG.get("mode", "none"),
                "is_admin": auth.is_admin(core.REG.AUTH_CFG, u),
                "allow_anonymous": auth.allow_anonymous_feedback(core.REG.AUTH_CFG),
                "anonymous_feedback_max": core.REG.AUTH_CFG.get("anonymous_feedback_max"),
                "anonymous_feedback_window_seconds": core.REG.AUTH_CFG.get("anonymous_feedback_window_seconds"),
            },
            "voice": _voice_payload(),
        })

    @app.route("/api/apps")
    def _apps():
        return jsonify({"apps": _apps_payload(), "general": _general_payload()})

    @app.route("/profile")
    def _profile():
        u = auth.current_user(core.REG.AUTH_CFG) or {}
        mode = core.REG.AUTH_CFG.get("mode", "none")
        btn = (f"display:inline-block;background:{core.PURPLE};color:white;text-decoration:none;"
               "padding:6px 14px;border-radius:6px;font-weight:600;font-size:13px")
        info = (f"<p style='font-size:15px'><b>{core._esc(u.get('name') or 'anonymous')}</b> &nbsp;"
                f"<span style='color:#777'>{core._esc(u.get('email') or '—')}</span></p>"
                f"<p style='color:#777;font-size:12.5px'>groups: "
                f"{core._esc(', '.join(u.get('groups') or []) or '—')} · auth mode: "
                f"<code>{mode}</code></p>")
        if mode == "oidc":
            action = (f"<a href='/logout' target='_top' style='{btn}'>Sign out</a>" if u
                      else f"<a href='/login' target='_top' style='{btn}'>Sign in</a>")
        elif mode == "local":
            action = (f"<a href='/logout' target='_top' style='{btn}'>Sign out</a>" if u
                      else f"<a href='/login' target='_top' style='{btn}'>Sign in</a>")
        elif mode == "header":
            action = ("<p style='color:#777;font-size:13px'>Authenticated via your gateway — "
                      "sign out through your identity provider.</p>")
        else:
            du = core._esc(core.REG.AUTH_CFG.get("default_user") or "anonymous@local")
            action = (f"<p style='color:#777;font-size:13px'>Anonymous mode — everyone is "
                      f"<code>{du}</code>. Enable sign-in by setting <code>auth.mode: local</code> "
                      "or <code>auth.mode: oidc</code> in <code>gallery.yaml</code>.</p>")
        return core._page("Your profile", info + action)

    @app.route("/settings", methods=["GET", "POST"])
    def _settings():
        from curiator.config import load_config, set_block_key

        cfg = load_config()
        acfg = cfg["auth"]
        if not auth.is_admin(acfg, auth.current_user(acfg)):
            return core._page("Agent settings", "<p style='color:#a33;font-size:13px'>Admins only — your "
                             "account isn't in <code>auth.admin_groups</code>.</p>"), 403
        gallery = Path(cfg["gallery_path"])
        if request.method == "POST":
            text = gallery.read_text()
            for key in ("adapter", "autonomy", "permission_mode", "sandbox", "timeout", "model"):
                if key in request.form:
                    text = set_block_key(text, "agent", key, request.form.get(key))
            gallery.write_text(text)
            return redirect("/settings?saved=1")
        return core._page("Agent settings",
                          core._settings_html(cfg.get("agent") or {}, cfg["gallery_path"],
                                              saved=request.args.get("saved") == "1"))

    @app.route("/queue")
    def _queue_page():
        u = auth.current_user(core.REG.AUTH_CFG)
        if not auth.is_admin(core.REG.AUTH_CFG, u):
            return core._page("Held feedback queue", "<p style='color:#a33;font-size:13px'>Admins only — your "
                             "account isn't in <code>auth.admin_groups</code>.</p>"), 403
        return core._page("Held feedback queue", _queue_page_html(request.args.get("msg", "")))

    @app.route("/queue/<feedback_id>/<action>", methods=["POST"])
    def _queue_action(feedback_id, action):
        u = auth.current_user(core.REG.AUTH_CFG)
        if not auth.is_admin(core.REG.AUTH_CFG, u):
            return core._page("Held feedback queue", "<p style='color:#a33;font-size:13px'>Admins only.</p>"), 403
        if action not in {"approve", "reject"}:
            return core._page("Held feedback queue", "<p style='color:#a33;font-size:13px'>Unknown queue action.</p>"), 400
        found = _queue_find(feedback_id)
        if not found:
            return core._page("Held feedback queue", "<p style='color:#a33;font-size:13px'>Feedback not found.</p>"), 404
        key, entry = found
        if entry.get("kind") == "system" or entry.get("status") != "held":
            return core._page("Held feedback queue", "<p style='color:#a33;font-size:13px'>Only held user feedback can be reviewed here.</p>"), 400

        actor = _queue_actor(u)
        if action == "approve":
            ledger.add_system_note(
                core.LEDGER_CFG,
                key,
                f"Moderation queue: approved by {actor}; dispatching to the agent.",
                reply_to=[entry["id"]],
                agent="curiator queue",
            )
            ledger.set_status(core.LEDGER_CFG, key, [entry["id"]], "new")
            return redirect("/queue?msg=Approved")

        reason = (request.form.get("reason") or "").strip()
        text = f"Moderation queue: rejected by {actor}; closed without agent dispatch."
        if reason:
            text += f" Reason: {reason}"
        ledger.add_system_note(core.LEDGER_CFG, key, text, reply_to=[entry["id"]], agent="curiator queue")
        ledger.set_status(core.LEDGER_CFG, key, [entry["id"]], "rejected")
        return redirect("/queue?msg=Rejected")

    @app.route("/api/feedback/<key>", methods=["GET", "POST"])
    def _feedback(key):
        if request.method == "POST":
            u, status, auth_error, code = _feedback_user_and_status()
            if auth_error:
                return jsonify({"error": auth_error}), code or 401
            body = request.get_json(silent=True) or {}
            screenshot = body.get("screenshot")
            if status == "held" and screenshot and body.get("screenshot_source") != "capture":
                return jsonify({"error": "anonymous uploaded/native screenshots are disabled; use Capture view"}), 400
            if status == "held" and body.get("audio_ref"):
                return jsonify({"error": "anonymous retained audio is disabled; sign in to attach audio"}), 400
            reply_to = body.get("reply_to") or []
            if isinstance(reply_to, str):
                reply_to = [reply_to]
            entry = core.save_entry(
                key,
                body.get("stars"),
                body.get("comment", ""),
                screenshot,
                user=u,
                reply_to=reply_to,
                status=status,
                annotations=body.get("annotations"),
                annotation_targets=body.get("screenshot_source") == "capture",
                transcript_segments=body.get("transcript_segments"),
                audio_ref=body.get("audio_ref"),
            )
            return jsonify({"entry": _safe_entry(entry), **_feedback_payload(key)})
        return jsonify(_feedback_payload(key))

    @app.route("/api/feedback")
    def _all_feedback():
        return jsonify({key: _feedback_payload(key) for key in core.load_feedback()})

    @app.route("/api/new-app", methods=["POST"])
    def _new_app():
        u, status, auth_error, code = _feedback_user_and_status("new-app")
        if auth_error:
            return jsonify({"error": auth_error}), code or 401
        body = request.get_json(silent=True) or {}
        app_request, error = _new_app_request(body)
        if error:
            return jsonify({"error": error}), 400
        entry_id = ledger.save_entry(
            core.LEDGER_CFG,
            core.GENERAL_KEY,
            comment=_new_app_comment(app_request),
            user=u,
            extra={"status": status, "app_request": app_request},
        )
        entry = next(e for e in core.load_feedback().get(core.GENERAL_KEY, []) if e.get("id") == entry_id)
        return jsonify({"entry": _safe_entry(entry), **_feedback_payload(core.GENERAL_KEY)})

    @app.route("/api/transcribe", methods=["POST"])
    def _transcribe():
        voice = _voice_cfg()
        command = voice.get("transcribe_cmd")
        if not command:
            return jsonify({"error": "local transcription is not configured"}), 404
        auth_error, code = _transcribe_allowed()
        if auth_error:
            return jsonify({"error": auth_error}), code

        max_bytes = _voice_int("transcribe_max_bytes", 25 * 1024 * 1024, low=1, high=200 * 1024 * 1024)
        if request.content_length and request.content_length > max_bytes:
            return jsonify({"error": "audio clip is too large"}), 413
        upload = request.files.get("audio")
        if not upload:
            return jsonify({"error": "missing audio file"}), 400

        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in {".webm", ".ogg", ".mp3", ".m4a", ".mp4", ".wav", ".flac"}:
            suffix = ".webm"
        timeout = _voice_int("transcribe_timeout", 60, low=1, high=600)
        with tempfile.TemporaryDirectory(prefix="curiator-audio-") as tmp:
            audio_path = Path(tmp) / f"clip{suffix}"
            upload.save(audio_path)
            if audio_path.stat().st_size == 0:
                return jsonify({"error": "audio clip is empty"}), 400
            if audio_path.stat().st_size > max_bytes:
                return jsonify({"error": "audio clip is too large"}), 413
            args = _transcribe_args(command, audio_path)
            if not args:
                return jsonify({"error": "local transcription command is empty"}), 500
            env = {
                **os.environ,
                "CURIATOR_AUDIO": str(audio_path),
                "CURIATOR_COLLECTION_ROOT": str(core.REG.COLLECTION_ROOT),
            }
            try:
                proc = subprocess.run(
                    args,
                    cwd=core.REG.COLLECTION_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except FileNotFoundError:
                return jsonify({"error": f"transcriber not found: {args[0]}"}), 502
            except subprocess.TimeoutExpired:
                return jsonify({"error": f"transcription timed out after {timeout}s"}), 504
            if proc.returncode != 0:
                detail = bounded_text(proc.stderr or proc.stdout, 500) or f"exit {proc.returncode}"
                return jsonify({"error": "transcription failed", "detail": detail}), 502
            payload = _parse_transcript(proc.stdout)
            retain_audio = bool(voice.get("retain_audio")) and not (
                auth.feedback_requires_identity(core.REG.AUTH_CFG) and not core._current_user()
            )
            if retain_audio:
                core.PENDING_AUDIO.mkdir(parents=True, exist_ok=True)
                retained = core.PENDING_AUDIO / f"{uuid.uuid4().hex}{suffix}"
                shutil.copyfile(audio_path, retained)
                payload["audio_ref"] = f"audio/pending/{retained.name}"
        return jsonify(payload)

    @app.route("/api/action", methods=["POST"])
    def _action():
        body = request.get_json(silent=True) or {}
        key = body.get("key")
        value = body.get("value")
        if not key or value is None:
            return jsonify({"error": "missing key/value"}), 400
        u, status, auth_error, code = _feedback_user_and_status()
        if auth_error:
            return jsonify({"error": auth_error}), code or 401
        entry = core.record_action(key, value, body.get("reply_to"), user=u, status=status)
        return jsonify({"entry": _safe_entry(entry), **_feedback_payload(key)})

    @app.route("/feedback-shot/<path:fname>")
    def _shot(fname):
        return send_from_directory(core.SHOTS, fname)

    @app.route("/feedback-audio/<path:fname>")
    def _audio(fname):
        return send_from_directory(core.AUDIO, fname)

    @app.route("/feedback-trace/<feedback_id>.md")
    def _trace_raw(feedback_id):
        p = core._trace_path(feedback_id)
        if not p or not p.exists():
            return ("trace not found", 404)
        return Response(p.read_text(encoding="utf-8", errors="replace"), mimetype="text/markdown; charset=utf-8")

    @app.route("/feedback-trace/<feedback_id>")
    def _trace(feedback_id):
        p = core._trace_path(feedback_id)
        if not p or not p.exists():
            return core._page("Agent trace", "<p style='color:#777;font-size:13px'>No trace file for this feedback.</p>"), 404
        return core._trace_page(feedback_id, p.read_text(encoding="utf-8", errors="replace"))

    @app.route("/feedback-trace/<feedback_id>/stop", methods=["POST"])
    def _trace_stop(feedback_id):
        """The trace-view Stop button: drop a cancel marker the watcher polls for. Only meaningful while
        the item is `working`; the watcher terminates the agent and parks the item as `held`."""
        from ..loop import runlog as _runlog
        found = _queue_find(feedback_id)
        if not found:
            return jsonify({"ok": False, "error": "feedback not found"}), 404
        _key, entry = found
        if entry.get("status") != "working":
            return jsonify({"ok": False, "error": "no active run", "status": entry.get("status")}), 409
        _runlog.request_cancel(core.LEDGER_CFG, feedback_id)
        return jsonify({"ok": True})

    @app.route("/static-app/<path:fname>")
    def _static_app(fname):
        return send_from_directory(core.HERE, fname)

    @app.route("/general")
    def _general():
        return core.render_history(request.args.get("range"))

    @app.route("/reload/<key>", methods=["POST", "GET"])
    def _reload(key):
        return jsonify(core.reload_app(key))

    @app.route("/whoami")
    def _whoami():
        return jsonify(auth.current_user(core.REG.AUTH_CFG) or {"authenticated": False})

    @app.route("/fb-action", methods=["POST", "GET"])
    def _fb_action_route():
        key = request.args.get("key")
        value = request.args.get("value")
        reply_to = request.args.get("reply_to")
        if key and value is not None:
            u, status, auth_error, code = _feedback_user_and_status()
            if auth_error:
                return (auth_error, code or 401)
            core.record_action(key, value, reply_to, user=u, status=status)
            return ("ok", 200)
        return ("missing key/value", 400)

    return app


def build_application():
    flask_app = build_flask_app()
    core._DISPATCHER = core.LazyDispatcher(flask_app)
    return core._DISPATCHER, flask_app


if __name__ == "__main__":
    import logging
    from werkzeug.serving import run_simple
    if os.environ.get("CURIATOR_HTTP_LOG") != "1":
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
    host = os.environ.get("SHELL_HOST", "0.0.0.0")
    application, _app = build_application()
    run_simple(host, core.PORT, application, threaded=True)
