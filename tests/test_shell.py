"""shell: boot the Dash gallery shell against the tmp collection via the WSGI test client and exercise
the catalog → iframe → deep-link → feedback paths that have no other coverage. These regression-guard the
two log crashes — render_history on a null `ts`, and the duplicate-output `_route` mis-routing its input.

The shell loads its registry at import time from the shared gallery resolver, so we re-exec the module per
test against the current tmp gallery (and keep `curiator/shell` on sys.path so
`import registry` + Flask's asset root_path both resolve)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SHELL_DIR = Path(__file__).resolve().parents[1] / "curiator" / "shell"


def _seed_feedback(data: dict) -> None:
    from curiator import ledger
    from curiator.config import load_config
    ledger.replace_all(load_config(), data)


@pytest.fixture
def shell_mod(collection, monkeypatch):
    """A freshly-imported app_shell bound to the tmp collection (named 'app_shell' so Flask resolves its
    assets root via sys.path)."""
    import sys

    monkeypatch.syspath_prepend(str(SHELL_DIR))
    for name in ("registry", "app_shell"):
        sys.modules.pop(name, None)
    import importlib.util as u
    spec = u.spec_from_file_location("app_shell", str(SHELL_DIR / "app_shell.py"))
    mod = u.module_from_spec(spec)
    sys.modules["app_shell"] = mod          # so flask.get_root_path('app_shell') finds the assets folder
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def client(shell_mod):
    return shell_mod.build_shell().server.test_client()


def _dispatch_selected(client, search, rows=None, changed=("url.search",)):
    """Drive the single `selected-app` callback (Input url.search + Input approw ALL n_clicks)."""
    body = {"output": "selected-app.data", "outputs": {"id": "selected-app", "property": "data"},
            "inputs": [{"id": "url", "property": "search", "value": search}, rows or []],
            "changedPropIds": list(changed), "state": []}
    r = client.post("/_dash-update-component", json=body)
    assert r.status_code == 200, r.get_data(as_text=True)[:200]
    return r.get_json()["response"]["selected-app"]["data"]


def test_proxy_backend_path_can_preserve_app_prefix(shell_mod):
    assert shell_mod._proxy_backend_path("sample", "", {}) == "/"
    assert shell_mod._proxy_backend_path("sample", "assets/app.js", {}) == "/assets/app.js"
    assert shell_mod._proxy_backend_path("sample", "", {"preserve_prefix": True}) == "/app/sample/"
    assert (
        shell_mod._proxy_backend_path("sample", "_stcore/stream", {"preserve_prefix": True})
        == "/app/sample/_stcore/stream"
    )


def test_proxy_diagnostics_include_command_cwd_port_and_recent_logs(shell_mod, tmp_path):
    out = tmp_path / "proxy.out"
    err = tmp_path / "proxy.err"
    out.write_text("dev server booting\n")
    err.write_text("Error: missing dependency\n")
    shell_mod._PROXY_LOGS["react_board"] = {"stdout": str(out), "stderr": str(err)}
    try:
        body = shell_mod._proxy_diagnostics_html(
            "react_board",
            {"root": str(tmp_path), "mount": {"kind": "proxy", "cmd": "npm run dev", "port": 8700}},
            message="proxy backend did not respond: connection refused",
            url="http://127.0.0.1:8700/",
        )
    finally:
        shell_mod._PROXY_LOGS.pop("react_board", None)

    assert "react_board" in body
    assert "npm run dev" in body
    assert str(tmp_path) in body
    assert "8700" in body
    assert "http://127.0.0.1:8700/" in body
    assert "connection refused" in body
    assert "Error: missing dependency" in body
    assert "dev server booting" in body


def test_proxy_start_interpolates_command_templates(shell_mod, monkeypatch, tmp_path):
    captured = {}

    class FakeProc:
        pid = 456

        def poll(self):
            return None

        def terminate(self):
            return None

    def fake_popen(args, *popen_args, **popen_kwargs):
        captured["args"] = args
        captured["cwd"] = popen_kwargs.get("cwd")
        captured["env"] = popen_kwargs.get("env")
        return FakeProc()

    monkeypatch.setattr(shell_mod.subprocess, "Popen", fake_popen)
    rec = {
        "root": str(tmp_path),
        "source": "apps/proxy_app",
        "mount": {
            "kind": "proxy",
            "cmd": "python server.py --port {port} --root-path /app/{app} --source {source}",
            "cwd": "{root}",
            "port": 8799,
        },
    }
    try:
        ok, err = shell_mod._ensure_proxy("proxy_app", rec)
        assert ok is True and err is None
        assert captured["args"] == [
            "python", "server.py", "--port", "8799",
            "--root-path", "/app/proxy_app", "--source", "apps/proxy_app",
        ]
        assert captured["cwd"] == str(tmp_path)
        assert captured["env"]["PORT"] == "8799"
        assert captured["env"]["CURIATOR_APP"] == "proxy_app"
        assert shell_mod._PROXY_LOGS["proxy_app"]["cmd"] == (
            "python server.py --port 8799 --root-path /app/proxy_app --source apps/proxy_app"
        )
    finally:
        shell_mod._PROXY_PROCS.pop("proxy_app", None)
        shell_mod._discard_proxy_logs("proxy_app")


def test_engine_backed_proxy_starts_engine_and_injects_engine_env(shell_mod, monkeypatch, tmp_path):
    calls = []

    class FakeProc:
        pid = 456

        def poll(self):
            return None

        def terminate(self):
            return None

    class DeadProc:
        pid = 457

        def poll(self):
            return 1

    def fake_popen(args, *popen_args, **popen_kwargs):
        calls.append({"args": args, "cwd": popen_kwargs.get("cwd"), "env": popen_kwargs.get("env")})
        return FakeProc()

    monkeypatch.setattr(shell_mod.subprocess, "Popen", fake_popen)
    rec = {
        "root": str(tmp_path),
        "source": str(tmp_path),
        "mount": {
            "kind": "engine-backed",
            "cmd": "python ui.py --port {port} --engine {engine_url}",
            "port": 8799,
            "engine": "python engine.py --port {engine_port}",
            "engine_port": 8899,
        },
    }
    try:
        ok, err = shell_mod._ensure_proxy("twin", rec)
        assert ok is True and err is None
        assert calls[0]["args"] == ["python", "engine.py", "--port", "8899"]
        assert calls[0]["env"]["PORT"] == "8899"
        assert calls[1]["args"] == [
            "python", "ui.py", "--port", "8799", "--engine", "http://127.0.0.1:8899",
        ]
        assert calls[1]["env"]["CURIATOR_ENGINE_PORT"] == "8899"
        assert calls[1]["env"]["CURIATOR_ENGINE_URL"] == "http://127.0.0.1:8899"
        assert shell_mod._PROXY_LOGS["twin"]["engine_cmd"] == "python engine.py --port 8899"

        shell_mod._PROXY_PROCS["twin"] = DeadProc()
        ok, err = shell_mod._ensure_proxy("twin", rec)
        assert ok is True and err is None
        assert len(calls) == 3
        assert calls[2]["args"] == [
            "python", "ui.py", "--port", "8799", "--engine", "http://127.0.0.1:8899",
        ]
        assert shell_mod._PROXY_LOGS["twin"]["engine_cmd"] == "python engine.py --port 8899"
    finally:
        shell_mod._PROXY_PROCS.pop("twin", None)
        shell_mod._ENGINE_PROCS.pop("twin", None)
        shell_mod._discard_proxy_logs("twin")


def test_engine_backed_proxy_checks_configured_engine_health(shell_mod, monkeypatch, tmp_path):
    calls = []
    health_urls = []

    class FakeProc:
        pid = 456
        terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    class FakeResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_popen(args, *popen_args, **popen_kwargs):
        proc = FakeProc()
        calls.append({"args": args, "proc": proc})
        return proc

    def fake_urlopen(url, timeout=None):
        health_urls.append(url)
        return FakeResponse()

    monkeypatch.setattr(shell_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(shell_mod.urllib.request, "urlopen", fake_urlopen)
    rec = {
        "root": str(tmp_path),
        "source": str(tmp_path),
        "mount": {
            "kind": "engine-backed",
            "cmd": "python ui.py --port {port}",
            "port": 8799,
            "engine": "python engine.py --port {engine_port}",
            "engine_port": 8899,
            "engine_health": "/ready?app={app}",
        },
    }
    try:
        ok, err = shell_mod._ensure_proxy("twin", rec)
        assert ok is True and err is None
        assert health_urls == ["http://127.0.0.1:8899/ready?app=twin"]
        assert calls[0]["args"] == ["python", "engine.py", "--port", "8899"]
        assert calls[1]["args"] == ["python", "ui.py", "--port", "8799"]
        assert shell_mod._PROXY_LOGS["twin"]["engine_health_status"] == "HTTP 204"
    finally:
        shell_mod._PROXY_PROCS.pop("twin", None)
        shell_mod._ENGINE_PROCS.pop("twin", None)
        shell_mod._discard_proxy_logs("twin")


def test_engine_backed_proxy_blocks_when_engine_health_fails(shell_mod, monkeypatch, tmp_path):
    calls = []

    class FakeProc:
        pid = 456

        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    def fake_popen(args, *popen_args, **popen_kwargs):
        proc = FakeProc()
        calls.append({"args": args, "proc": proc})
        return proc

    monkeypatch.setattr(shell_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        shell_mod.urllib.request,
        "urlopen",
        lambda url, timeout=None: (_ for _ in ()).throw(OSError("connection refused")),
    )
    rec = {
        "root": str(tmp_path),
        "source": str(tmp_path),
        "mount": {
            "kind": "engine-backed",
            "cmd": "python ui.py --port {port}",
            "port": 8799,
            "engine": "python engine.py --port {engine_port}",
            "engine_port": 8899,
            "engine_health": "/ready",
            "engine_health_timeout": 0,
        },
    }
    try:
        ok, err = shell_mod._ensure_proxy("twin", rec)
        assert ok is False
        assert "engine health check failed" in err
        assert len(calls) == 1
        assert calls[0]["proc"].terminated is True
        assert shell_mod._PROXY_LOGS["twin"]["engine_health_status"] == "connection refused"
        assert "http://127.0.0.1:8899/ready" in shell_mod._proxy_diagnostics_html(
            "twin",
            rec,
            message=f"proxy could not start: {err}",
        )
    finally:
        shell_mod._PROXY_PROCS.pop("twin", None)
        shell_mod._ENGINE_PROCS.pop("twin", None)
        shell_mod._discard_proxy_logs("twin")


def test_proxy_websocket_falls_back_to_501_without_dev_server_socket(shell_mod, monkeypatch, tmp_path):
    """A WS upgrade is bridged when the built-in server exposes `werkzeug.socket`; without it (behind
    another WSGI server) it degrades to an honest 501 with diagnostics — never hangs."""
    from io import BytesIO

    monkeypatch.setattr(shell_mod, "_ensure_proxy", lambda key, rec: (True, None))
    statuses = []

    def start_response(status, headers):
        statuses.append((status, headers))

    body = b"".join(shell_mod._proxy_call(
        "react_board",
        {"root": str(tmp_path), "mount": {"kind": "proxy", "cmd": "npm run dev", "port": 8700}},
        "/@vite/client",
        {
            "REQUEST_METHOD": "GET",
            "QUERY_STRING": "",
            "HTTP_CONNECTION": "Upgrade",
            "HTTP_UPGRADE": "websocket",
            "wsgi.input": BytesIO(b""),                    # no "werkzeug.socket" → fallback path
        },
        start_response,
    )).decode()

    assert statuses[0][0] == "501 Not Implemented"
    assert "WebSocket upgrades need curIAtor" in body      # apostrophe in the message is HTML-escaped
    assert "npm run dev" in body
    assert "http://127.0.0.1:8700/@vite/client" in body


def test_proxy_forwards_public_origin_and_prefix_headers(shell_mod, monkeypatch, tmp_path):
    from io import BytesIO

    captured = {}
    monkeypatch.setattr(shell_mod, "_ensure_proxy", lambda key, rec: (True, None))

    class FakeResponse:
        status = 200
        reason = "OK"
        headers = {"Content-Type": "text/plain"}

        def __init__(self):
            self._chunks = [b"ok", b""]        # streaming reader: one read1() then EOF

        def read1(self, _n=-1):
            return self._chunks.pop(0)

        def close(self):
            pass

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        return FakeResponse()

    monkeypatch.setattr(shell_mod.urllib.request, "urlopen", fake_urlopen)
    statuses = []

    def start_response(status, headers):
        statuses.append((status, headers))

    body = b"".join(shell_mod._proxy_call(
        "react_board",
        {"root": str(tmp_path), "mount": {"kind": "proxy", "cmd": "npm run dev", "port": 8700}},
        "/assets/app.js",
        {
            "REQUEST_METHOD": "GET",
            "QUERY_STRING": "v=1",
            "HTTP_HOST": "curiator.example.test",
            "HTTP_X_FORWARDED_PROTO": "https",
            "HTTP_X_FORWARDED_FOR": "203.0.113.10",
            "REMOTE_ADDR": "127.0.0.1",
            "wsgi.input": BytesIO(b""),
        },
        start_response,
    ))

    assert statuses[0][0] == "200 OK"
    assert body == b"ok"
    assert captured["url"] == "http://127.0.0.1:8700/assets/app.js?v=1"
    assert captured["headers"]["X-forwarded-host"] == "curiator.example.test"
    assert captured["headers"]["X-forwarded-proto"] == "https"
    assert captured["headers"]["X-forwarded-for"] == "203.0.113.10, 127.0.0.1"
    assert captured["headers"]["X-forwarded-prefix"] == "/app/react_board"
    assert captured["headers"]["X-script-name"] == "/app/react_board"


# ── boot + the pages that crashed ────────────────────────────────────────────
def test_index_and_general_serve(client):
    assert client.get("/").status_code == 200            # the Dash shell index
    assert client.get("/general").status_code == 200     # render_history (the General view)


def test_general_survives_null_ts(collection, client):
    """A loop-error note with ts:null must not crash render_history's sort (the reported /general 500)."""
    _seed_feedback({"sample": [
        {"id": "n1", "author": "claude", "kind": "system", "comment": "⚙ loop error: 529",
         "status": "update", "ts": None, "reply_to": []},
        {"id": "u1", "author": "user", "kind": "comment", "comment": "hi", "stars": 3,
         "status": "new", "ts": "2026-06-29T16:00:00+00:00"},
    ]})
    r = client.get("/general")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "class='ts'" in body and "/assets/localtime.js" in body   # localized timestamps + the converter
    assert "data-ts='None'" not in body                              # the null row emits no broken marker


def test_general_history_supports_practical_activity_ranges(collection, client):
    now = datetime.now(timezone.utc)
    ten_min = (now - timedelta(minutes=10)).isoformat(timespec="seconds")
    two_hour = (now - timedelta(hours=2)).isoformat(timespec="seconds")
    two_day = (now - timedelta(days=2)).isoformat(timespec="seconds")
    ten_day = (now - timedelta(days=10)).isoformat(timespec="seconds")
    forty_day = (now - timedelta(days=40)).isoformat(timespec="seconds")
    _seed_feedback({
        "__general__": [
            {"id": "recent", "author": "user", "kind": "comment", "comment": "ten-minute item",
             "status": "done", "ts": ten_min},
            {"id": "hour", "author": "user", "kind": "comment", "comment": "two-hour item",
             "status": "done", "ts": two_hour},
            {"id": "day", "author": "user", "kind": "comment", "comment": "two-day item",
             "status": "done", "ts": two_day},
            {"id": "month", "author": "user", "kind": "comment", "comment": "ten-day item",
             "status": "done", "ts": ten_day},
            {"id": "old", "author": "user", "kind": "comment", "comment": "forty-day item",
             "status": "done", "ts": forty_day},
        ],
    })

    all_body = client.get("/general").get_data(as_text=True)
    assert all(label in all_body for label in ("Past hour", "Past 24 hours", "Past 7 days", "Past 30 days"))
    assert all(item in all_body for item in
               ("ten-minute item", "two-hour item", "two-day item", "ten-day item", "forty-day item"))

    hour_body = client.get("/general?range=1h").get_data(as_text=True)
    assert "ten-minute item" in hour_body and "two-hour item" not in hour_body

    day_body = client.get("/general?range=24h").get_data(as_text=True)
    assert "ten-minute item" in day_body and "two-hour item" in day_body
    assert "two-day item" not in day_body

    week_body = client.get("/general?range=7d").get_data(as_text=True)
    assert "two-day item" in week_body and "ten-day item" not in week_body

    month_body = client.get("/general?range=30d").get_data(as_text=True)
    assert "ten-day item" in month_body and "forty-day item" not in month_body


def test_general_history_status_counts_are_clickable_thread_filters(collection, client):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _seed_feedback({
        "sample": [
            {"id": "working", "author": "user", "kind": "comment", "comment": "working ticket",
             "status": "working", "ts": now},
            {"id": "working-note", "author": "claude", "kind": "system", "comment": "working context",
             "status": "update", "reply_to": ["working"], "ts": now},
            {"id": "held", "author": "user", "kind": "comment", "comment": "held ticket",
             "status": "held", "ts": now},
            {"id": "done", "author": "user", "kind": "comment", "comment": "done ticket",
             "status": "done", "ts": now},
        ],
    })

    body = client.get("/general?range=24h").get_data(as_text=True)
    assert "1 active thread" in body and "2 open threads" in body
    assert "href='/general?range=24h&amp;filter=active'" in body
    assert "href='/general?range=24h&amp;filter=open'" in body

    active = client.get("/general?range=24h&filter=active").get_data(as_text=True)
    assert "working ticket" in active and "working context" in active
    assert "held ticket" not in active and "done ticket" not in active
    assert "aria-pressed='true'" in active

    open_threads = client.get("/general?range=24h&filter=open").get_data(as_text=True)
    assert "working ticket" in open_threads and "working context" in open_threads
    assert "held ticket" in open_threads and "done ticket" not in open_threads
    assert "value='/general?range=7d&amp;filter=open'" in open_threads


def test_general_history_live_refresh_uses_content_versions(collection, client):
    from curiator import ledger
    from curiator.config import load_config

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _seed_feedback({"sample": [
        {"id": "work", "author": "user", "kind": "comment", "comment": "status changes live",
         "status": "working", "ts": now},
    ]})

    before = client.get("/general").get_data(as_text=True)
    before_version = before.split("data-version='", 1)[1].split("'", 1)[0]
    assert "window.setInterval(refresh" in before
    assert "current.dataset.version !== next.dataset.version" in before
    unchanged = client.get("/general").get_data(as_text=True)
    assert unchanged.split("data-version='", 1)[1].split("'", 1)[0] == before_version

    ledger.set_status(load_config(), "sample", ["work"], "done")
    after = client.get("/general").get_data(as_text=True)
    after_version = after.split("data-version='", 1)[1].split("'", 1)[0]
    assert before_version != after_version
    assert ">done</" in after


def test_trace_route_and_status_badge_link(collection, shell_mod, client):
    _seed_feedback({"sample": [
        {"id": "u1", "author": "user", "kind": "comment", "comment": "fix it",
         "status": "working", "ts": "2026-06-29T16:00:00+00:00"},
    ]})
    trace = collection / "feedback" / "replies" / "u1.md"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text("# curIAtor Agent Trace\n\nline one\n")

    body = client.get("/general").get_data(as_text=True)
    assert "/feedback-trace/u1" in body and "open agent trace" in body
    raw = client.get("/feedback-trace/u1.md")
    assert raw.status_code == 200 and "line one" in raw.get_data(as_text=True)
    page = client.get("/feedback-trace/u1")
    assert page.status_code == 200 and "setInterval(refresh" in page.get_data(as_text=True)

    panel = shell_mod.feedback_list("sample")
    hrefs = []

    def walk(c):
        href = getattr(c, "href", None)
        if href:
            hrefs.append(href)
        ch = getattr(c, "children", None)
        if isinstance(ch, (list, tuple)):
            for x in ch:
                walk(x)
        elif ch is not None and hasattr(ch, "_prop_names"):
            walk(ch)

    walk(panel)
    assert "/feedback-trace/u1" in hrefs


def test_feedback_threads_are_nested_and_replyable(collection, shell_mod, client):
    _seed_feedback({"sample": [
        {"id": "u1", "author": "user", "kind": "comment", "comment": "original request",
         "status": "awaiting_approval", "ts": "2026-06-29T16:00:00+00:00"},
        {"id": "n1", "author": "claude", "kind": "system", "comment": "agent option",
         "status": "update", "reply_to": ["u1"], "ts": "2026-06-29T16:01:00+00:00", "agent": "Codex"},
        {"id": "u2", "author": "user", "kind": "comment", "comment": "clarifying reply",
         "status": "new", "reply_to": ["n1"], "ts": "2026-06-29T16:02:00+00:00"},
    ]})

    body = client.get("/general").get_data(as_text=True)
    assert "original request" in body and "agent option" in body and "clarifying reply" in body
    assert "margin:4px 0 4px 40px" in body          # agent note nested under the original user item
    assert "margin:4px 0 4px 36px" in body          # user reply nested under the agent note
    assert "set_props(&#x27;fb-reply-to&#x27;" in body

    panel = shell_mod.feedback_list("sample")
    reply_ids = []
    margins = []

    def walk(c):
        cid = getattr(c, "id", None)
        if isinstance(cid, dict) and cid.get("type") == "fbreply":
            reply_ids.append(cid)
        style = getattr(c, "style", None)
        if isinstance(style, dict) and style.get("marginLeft"):
            margins.append(style.get("marginLeft"))
        ch = getattr(c, "children", None)
        if isinstance(ch, (list, tuple)):
            for x in ch:
                walk(x)
        elif ch is not None and hasattr(ch, "_prop_names"):
            walk(ch)

    walk(panel)
    assert {"type": "fbreply", "key": "sample", "target": "n1"} in reply_ids
    assert "14px" in margins and "28px" in margins

    saved = shell_mod.save_entry("sample", None, "typed follow-up", None, reply_to=["n1"])
    assert saved["reply_to"] == ["n1"]


# ── the router: one writer, defaults to General, deep-links, click wins ───────
def test_selected_app_has_single_writer(shell_mod):
    """Exactly one callback owns selected-app.data — a duplicate output mis-routes inputs (the _route 500)."""
    keys = [k for k in shell_mod.build_shell().callback_map if k.split("@")[0] == "selected-app.data"]
    assert keys == ["selected-app.data"]


def test_router_defaults_deeplinks_and_click(shell_mod, client):
    G = shell_mod.GENERAL_KEY
    assert _dispatch_selected(client, "") == G                  # no query → land on General, not blank
    assert _dispatch_selected(client, "?app=sample") == "sample"
    assert _dispatch_selected(client, "?app=general") == G      # friendly alias
    assert _dispatch_selected(client, "?app=bogus") == G        # unknown key → safe default
    assert _dispatch_selected(client, None) == G                # None search → no crash
    # the reported crash shape: search delivered as a LIST must not 500
    assert _dispatch_selected(client, ["?app=sample"]) == "sample"
    # a catalog row click wins over the URL
    click = [{"id": {"type": "approw", "key": "sample"}, "property": "n_clicks", "value": 1}]
    assert _dispatch_selected(client, "?app=general", rows=click,
                              changed=['{"key":"sample","type":"approw"}.n_clicks']) == "sample"


# ── share affordances + the localizer asset ──────────────────────────────────
def test_localtime_asset_served(client):
    r = client.get("/assets/localtime.js")
    assert r.status_code == 200
    assert "toLocaleString" in r.get_data(as_text=True)         # the local-tz conversion ships


def test_catalog_has_share_buttons_and_general_row(shell_mod):
    rows = shell_mod.catalog_rows("", "id", None, False)
    types = []

    def walk(c):
        cid = getattr(c, "id", None)
        if isinstance(cid, dict):
            types.append(cid.get("type"))
        ch = getattr(c, "children", None)
        if isinstance(ch, (list, tuple)):
            for x in ch:
                walk(x)
        elif ch is not None and hasattr(ch, "_prop_names"):
            walk(ch)

    for r in rows:
        walk(r)
    assert types.count("approw") == 2          # ◆ General + the one sample app
    assert types.count("share") == 1           # a per-app share button (General row has none)


def test_agent_label_attributes_the_reply(collection, client):
    """An agent note carries `agent` (the provider) → the panel shows '⚙ Codex', not a hardcoded Claude."""
    _seed_feedback({"sample": [
        {"id": "u1", "author": "user", "kind": "comment", "comment": "fix it", "status": "new",
         "ts": "2026-06-29T16:00:00+00:00"},
        {"id": "n1", "author": "claude", "kind": "system", "comment": "fixed it", "status": "update",
         "reply_to": ["u1"], "ts": "2026-06-29T16:05:00+00:00", "agent": "Codex"},
    ]})
    body = client.get("/general").get_data(as_text=True)
    assert "⚙ Codex" in body and "⚙ Claude" not in body


def test_settings_page_renders_and_writes_back(collection, client):
    """GET renders the agent form (auth.mode none ⇒ admin); POST writes gallery.yaml + redirects, and
    config then loads the new values — the loop hot-reloads them, no restart."""
    r = client.get("/settings")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Provider (adapter)" in body and "codex" in body and "Codex sandbox" in body

    r2 = client.post("/settings", data={"adapter": "codex", "autonomy": "propose-only",
                                        "permission_mode": "acceptEdits", "sandbox": "danger-full-access",
                                        "timeout": "600", "model": "gpt-5-codex"})
    assert r2.status_code in (302, 303)                # redirect to ?saved=1
    gtext = (collection / "gallery.yaml").read_text()
    assert "adapter: codex" in gtext and "autonomy: propose-only" in gtext
    assert "sandbox: danger-full-access" in gtext and "model: gpt-5-codex" in gtext

    from curiator.config import load_config
    cfg = load_config()
    assert cfg["agent"]["adapter"] == "codex" and cfg["agent"]["model"] == "gpt-5-codex"


def test_share_and_fbshare_callbacks_are_clientside(shell_mod):
    shell = shell_mod.build_shell()
    cs_outputs = {c.get("clientside_function") and str(c.get("output"))
                  for c in getattr(shell, "_callback_list", []) if c.get("clientside_function")}
    cs_outputs.discard(None)
    blob = " ".join(cs_outputs)
    assert "share-toast.children" in blob       # per-row 🔗 copy-link
    assert "fb-share-msg.children" in blob       # panel "🔗 Share" button


def test_record_action_links_to_system_note(shell_mod):
    shell_mod.record_action("sample", "A", reply_to="n1")
    item = shell_mod.load_feedback()["sample"][0]
    assert item["comment"] == "A"
    assert item["reply_to"] == ["n1"]
