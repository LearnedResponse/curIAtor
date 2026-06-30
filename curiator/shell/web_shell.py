"""web_shell.py — Flask + React overlay shell.

The overlay UI is framework-neutral; Dash remains an app mount type (`dash-inproc`), not the shell
framework. This module reuses the app/proxy supervisor and ledger helpers from app_shell while serving
a React UI and JSON API from plain Flask.
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, request, send_from_directory

from curiator.shell import app_shell as core
from curiator import auth


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
            },
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

    @app.route("/api/feedback/<key>", methods=["GET", "POST"])
    def _feedback(key):
        if request.method == "POST":
            u = core._current_user()
            if auth.login_required(core.REG.AUTH_CFG) and not u:
                return jsonify({"error": "sign in required"}), 401
            body = request.get_json(silent=True) or {}
            reply_to = body.get("reply_to") or []
            if isinstance(reply_to, str):
                reply_to = [reply_to]
            entry = core.save_entry(
                key,
                body.get("stars"),
                body.get("comment", ""),
                body.get("screenshot"),
                user=u,
                reply_to=reply_to,
            )
            return jsonify({"entry": _safe_entry(entry), **_feedback_payload(key)})
        return jsonify(_feedback_payload(key))

    @app.route("/api/feedback")
    def _all_feedback():
        return jsonify({key: _feedback_payload(key) for key in core.load_feedback()})

    @app.route("/api/action", methods=["POST"])
    def _action():
        body = request.get_json(silent=True) or {}
        key = body.get("key")
        value = body.get("value")
        if not key or value is None:
            return jsonify({"error": "missing key/value"}), 400
        core.record_action(key, value, body.get("reply_to"))
        return jsonify(_feedback_payload(key))

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
