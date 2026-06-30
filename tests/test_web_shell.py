"""web_shell: Flask/React overlay shell API + same-origin app mounting."""
from __future__ import annotations

from pathlib import Path

import pytest

SHELL_DIR = Path(__file__).resolve().parents[1] / "curiator" / "shell"


@pytest.fixture
def web_mod(collection, monkeypatch):
    import importlib.util as u
    import sys

    monkeypatch.syspath_prepend(str(SHELL_DIR))
    for name in ("registry", "curiator.shell.app_shell", "curiator.shell.web_shell"):
        sys.modules.pop(name, None)
    import curiator.shell as shell_pkg
    for attr in ("app_shell", "web_shell"):
        if hasattr(shell_pkg, attr):
            delattr(shell_pkg, attr)
    spec = u.spec_from_file_location("curiator.shell.web_shell", str(SHELL_DIR / "web_shell.py"))
    mod = u.module_from_spec(spec)
    sys.modules["curiator.shell.web_shell"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def web_client(web_mod):
    app = web_mod.build_flask_app()
    return app.test_client()


def test_react_shell_index_and_bootstrap(web_client):
    body = web_client.get("/").get_data(as_text=True)
    assert "react_shell.js" in body
    assert "_dash" not in body
    data = web_client.get("/api/bootstrap").get_json()
    assert data["general_key"] == "__general__"
    assert data["general"]["key"] == "__general__"
    assert data["auth"]["is_admin"] is True
    sample = next(a for a in data["apps"] if a["key"] == "sample")
    assert sample["revision"] == 0


def test_react_shell_general_iframe_src_is_stable(web_client):
    body = web_client.get("/assets/react_shell.js").get_data(as_text=True)
    assert "function appSrc(key, generalKey, revision)" in body
    assert 'return "/general";' in body
    assert "/general?t=" not in body
    assert '?v=' in body
    assert "selectedApp && selectedApp.revision" in body


def test_react_shell_pins_general_and_restores_auth_menu(web_client):
    body = web_client.get("/assets/react_shell.js").get_data(as_text=True)
    assert "function AccountMenu" in body
    assert "Settings" in body and "Profile" in body and "Log in" in body
    assert '.filter((a) => a.kind !== "general")' in body
    assert "rshell-general-row" in body


def test_react_shell_side_rails_are_collapsible(web_client):
    js = web_client.get("/assets/react_shell.js").get_data(as_text=True)
    css = web_client.get("/assets/react_shell.css").get_data(as_text=True)
    assert "catCollapsed" in js and "fbCollapsed" in js
    assert "rshell-edge-tab left" in js and "rshell-edge-tab right" in js
    assert "rshell-collapse-btn" in js
    assert ".rshell-catalog.collapsed" in css
    assert ".rshell-feedback.collapsed" in css
    assert ".rshell-edge-tab" in css


def test_react_shell_profile_settings_and_collection_home(web_client):
    web_client.post("/api/feedback/sample", json={"comment": "app activity", "stars": 3})
    home = web_client.get("/general").get_data(as_text=True)
    assert "collection home" in home
    assert home.index("General feedback") < home.index("Latest activity")
    assert "app activity" in home
    assert "selectApp(&quot;sample&quot;)" in home
    assert 'selectApp("sample")' not in home
    assert web_client.get("/profile").status_code == 200
    settings = web_client.get("/settings")
    assert settings.status_code == 200
    assert "Provider (adapter)" in settings.get_data(as_text=True)


def test_react_shell_feedback_api_threads_replies(web_client):
    r1 = web_client.post("/api/feedback/sample", json={"comment": "original", "stars": 2})
    assert r1.status_code == 200
    parent = r1.get_json()["entry"]["id"]
    r2 = web_client.post("/api/feedback/sample", json={"comment": "reply", "reply_to": [parent]})
    assert r2.status_code == 200
    child = r2.get_json()["entry"]
    assert child["reply_to"] == [parent]
    data = web_client.get("/api/feedback/sample").get_json()
    assert [e["comment"] for e in data["items"]] == ["original", "reply"]


def test_react_shell_trace_and_app_mount(collection, web_mod):
    from werkzeug.test import Client
    from werkzeug.wrappers import Response

    trace = collection / "feedback" / "replies" / "abc123.md"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text("# trace\nhello\n")
    application, _flask = web_mod.build_application()
    client = Client(application, Response)
    raw = client.get("/feedback-trace/abc123.md")
    assert raw.status_code == 200 and "hello" in raw.get_data(as_text=True)
    mounted = client.get("/app/sample/")
    assert mounted.status_code == 200


def test_reload_refreshes_registry_for_newly_created_app(collection, web_mod):
    from werkzeug.test import Client
    from werkzeug.wrappers import Response

    from curiator import cli

    application, flask_app = web_mod.build_application()
    api_client = flask_app.test_client()
    assert all(a["key"] != "orange_picker" for a in api_client.get("/api/bootstrap").get_json()["apps"])

    assert cli.main([
        "app", "create", "orange_picker",
        "--template", "dash",
        "--title", "Orange Picker",
    ]) == 0

    reload_data = api_client.post("/reload/orange_picker").get_json()
    assert reload_data["registered"] is True
    assert reload_data["registry_count"] == 2
    assert reload_data["revision"] == 1
    orange = next(a for a in api_client.get("/api/bootstrap").get_json()["apps"] if a["key"] == "orange_picker")
    assert orange["revision"] == 1

    client = Client(application, Response)
    mounted = client.get("/app/orange_picker/")
    assert mounted.status_code == 200
    assert "Orange Picker" in mounted.get_data(as_text=True)
