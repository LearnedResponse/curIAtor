"""web_shell.py — Flask + React overlay shell.

The overlay UI is framework-neutral; Dash remains an app mount type (`dash-inproc`), not the shell
framework. This module reuses the app/proxy supervisor and ledger helpers from app_shell while serving
a React UI and JSON API from plain Flask.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
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
    trace = core._trace_path(entry.get("id"))
    if trace and trace.exists():
        out["trace_url"] = f"/feedback-trace/{entry.get('id')}"
    return out


def _metrics(key: str) -> dict:
    avg, n_open, n_total = core.app_metrics(key)
    return {"avg_stars": avg, "open": n_open, "total": n_total}


def _apps_payload() -> list[dict]:
    apps = []
    for rec in core.REGISTRY:
        apps.append({
            "key": rec["key"],
            "title": rec.get("title", rec["key"]),
            "tags": rec.get("tags") or [],
            "color": rec.get("color", "#888"),
            "kind": rec.get("kind"),
            "port": rec.get("port"),
            "source": rec.get("source") or rec.get("file"),
            "root": rec.get("root"),
            "metrics": _metrics(rec["key"]),
            "revision": core.APP_REVISIONS.get(rec["key"], 0),
        })
    return apps


def _general_payload() -> dict:
    return {
        "key": core.GENERAL_KEY,
        "title": "General — gallery & runner",
        "tags": ["meta"],
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
    if auth.login_required(core.REG.AUTH_CFG) and not u:
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
    if auth.login_required(core.REG.AUTH_CFG) and not core._current_user():
        if not auth.allow_anonymous_feedback(core.REG.AUTH_CFG):
            return "sign in required", 401
    return None, 0


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
                transcript_segments=body.get("transcript_segments"),
            )
            return jsonify({"entry": _safe_entry(entry), **_feedback_payload(key)})
        return jsonify(_feedback_payload(key))

    @app.route("/api/feedback")
    def _all_feedback():
        return jsonify({key: _feedback_payload(key) for key in core.load_feedback()})

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
                "CURIATOR_GALLERY": str(core.REG.GALLERY_YAML),
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
        return jsonify(_parse_transcript(proc.stdout))

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
            core.record_action(key, value, reply_to)
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
