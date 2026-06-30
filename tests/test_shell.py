"""shell: boot the Dash gallery shell against the tmp collection via the WSGI test client and exercise
the catalog → iframe → deep-link → feedback paths that have no other coverage. These regression-guard the
two log crashes — render_history on a null `ts`, and the duplicate-output `_route` mis-routing its input.

The shell loads its registry at import time from CURIATOR_GALLERY (set by the `collection` fixture), so we
re-exec the module per test against the current tmp gallery (and keep `curiator/shell` on sys.path so
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


def test_general_history_supports_one_and_five_minute_ranges(collection, client):
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(seconds=30)).isoformat(timespec="seconds")
    three_min = (now - timedelta(minutes=3)).isoformat(timespec="seconds")
    ten_min = (now - timedelta(minutes=10)).isoformat(timespec="seconds")
    _seed_feedback({
        "__general__": [
            {"id": "old", "author": "user", "kind": "comment", "comment": "ten-minute item",
             "status": "done", "ts": ten_min},
            {"id": "mid", "author": "user", "kind": "comment", "comment": "three-minute item",
             "status": "done", "ts": three_min},
            {"id": "new", "author": "user", "kind": "comment", "comment": "thirty-second item",
             "status": "new", "ts": recent},
        ],
    })

    all_body = client.get("/general").get_data(as_text=True)
    assert "1 minute" in all_body and "5 minutes" in all_body
    assert "ten-minute item" in all_body and "three-minute item" in all_body and "thirty-second item" in all_body

    one_min_body = client.get("/general?range=1m").get_data(as_text=True)
    assert "thirty-second item" in one_min_body
    assert "three-minute item" not in one_min_body and "ten-minute item" not in one_min_body

    five_min_body = client.get("/general?range=5m").get_data(as_text=True)
    assert "thirty-second item" in five_min_body and "three-minute item" in five_min_body
    assert "ten-minute item" not in five_min_body


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
