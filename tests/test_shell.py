"""shell: boot the Dash gallery shell against the tmp collection via the WSGI test client and exercise
the catalog → iframe → deep-link → feedback paths that have no other coverage. These regression-guard the
two log crashes — render_history on a null `ts`, and the duplicate-output `_route` mis-routing its input.

The shell loads its registry at import time from CURIATOR_GALLERY (set by the `collection` fixture), so we
re-exec the module per test against the current tmp gallery (and keep `curiator/shell` on sys.path so
`import registry` + Flask's asset root_path both resolve)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

SHELL_DIR = Path(__file__).resolve().parents[1] / "curiator" / "shell"


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


# ── boot + the pages that crashed ────────────────────────────────────────────
def test_index_and_general_serve(client):
    assert client.get("/").status_code == 200            # the Dash shell index
    assert client.get("/general").status_code == 200     # render_history (the General view)


def test_general_survives_null_ts(collection, client):
    """A loop-error note with ts:null must not crash render_history's sort (the reported /general 500)."""
    led = collection / "feedback" / "app_feedback.json"
    led.write_text(json.dumps({"sample": [
        {"id": "n1", "author": "claude", "kind": "system", "comment": "⚙ loop error: 529",
         "status": "update", "ts": None, "reply_to": []},
        {"id": "u1", "author": "user", "kind": "comment", "comment": "hi", "stars": 3,
         "status": "new", "ts": "2026-06-29T16:00:00+00:00"},
    ]}))
    r = client.get("/general")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "class='ts'" in body and "/assets/localtime.js" in body   # localized timestamps + the converter
    assert "data-ts='None'" not in body                              # the null row emits no broken marker


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


def test_share_and_fbshare_callbacks_are_clientside(shell_mod):
    shell = shell_mod.build_shell()
    cs_outputs = {c.get("clientside_function") and str(c.get("output"))
                  for c in getattr(shell, "_callback_list", []) if c.get("clientside_function")}
    cs_outputs.discard(None)
    blob = " ".join(cs_outputs)
    assert "share-toast.children" in blob       # per-row 🔗 copy-link
    assert "fb-share-msg.children" in blob       # panel "🔗 Share" button
