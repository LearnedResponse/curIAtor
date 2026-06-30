"""app_shell.py — CurIAtor — single-origin gallery shell + catalog + feedback. Port 8200.

The consolidated front door for your whole app gallery. ONE Flask server
(via a lazy DispatcherMiddleware) mounts every Dash app at a PATH, so everything
is same-origin. Layout: CATALOG (left) · app in an iframe (center) · FEEDBACK
(right).

Key properties:
  • Registry-driven — reads `all_apps_index` (the existing single source of truth:
    ports, titles, tags, the 18-tag system). Adding an app = one registry entry.
  • Zero per-app edits — each app is mounted UNMODIFIED: the env var
    DASH_REQUESTS_PATHNAME_PREFIX is set, Dash reads it at construction, and we
    take the app's Flask server. Handles both entry patterns (`build_app()` and a
    module-level `app = Dash(...)`).
  • Lazy — apps are built on first view (a few hundred ms), not at startup; a
    build failure shows in the iframe, never breaks the shell.
  • Numbers kept as IDs — the old port number is the permanent reference label,
    decoupled from the (now nonexistent) live port. Apps are keyed by their
    registry `key` (file stem); the number is shown for reference.
  • Catalog = quality dashboard — sort/filter by id · title · tag · ★rating ·
    recency · open-feedback (the last is the Phase-2 loop's work queue).
  • Same-origin feedback — ★1–5 + comment + one-click html2canvas screenshot of
    the iframe (the thing separate ports blocked) + upload fallback. Claude posts
    back ⚙ system notes; entries carry status badges. Persisted to
    feedback/app_feedback.json (git-tracked) + feedback/shots/ (gitignored).

Run:  python app_shell.py   →   http://127.0.0.1:8200
"""
from __future__ import annotations

import base64
import importlib
import json
import os
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from html import escape as _esc
from pathlib import Path

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update
from dash.dependencies import ClientsideFunction
from flask import send_from_directory
from werkzeug.middleware.dispatcher import DispatcherMiddleware  # noqa: F401 (kept for reference)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
PORT = 8200  # default; overridden by gallery.yaml shell.port just below (after the registry import)

import registry as REG  # gallery.yaml-backed registry (CurIAtor drop-in for all_apps_index)
from curiator import auth  # identity / provenance resolution (none | header | oidc)
PORT = REG.SHELL_CFG.get("port", PORT)  # honor gallery.yaml: shell.port
def _norm_title(raw):
    """Browser-tab title: normalize a leading brand token to the canonical lowercase 'curIAtor'."""
    s = (raw or "curIAtor").strip()
    m = re.match(r"(?i)^curiator\b", s)
    return ("curIAtor" + s[m.end():]) if m else s


def _collection_name(raw):
    """The collection/repo name for the General banner — the title with a leading brand token stripped
    (the purple logo already shows the brand), or the repo dir name."""
    s = (raw or "").strip()
    m = re.match(r"(?i)^curiator\b", s)
    if m:
        rest = s[m.end():].lstrip(" ·:|/–—-").strip()
        if rest:
            return rest
    return s or REG.COLLECTION_ROOT.name


TITLE = _norm_title(REG.SHELL_CFG.get("title"))                # browser tab title (lowercase brand)
POLL_MS = int(REG.SHELL_CFG.get("poll_seconds", 4) * 1000)     # live-refresh the feedback panel (0 = off)
COLLECTION_NAME = _collection_name(REG.SHELL_CFG.get("title"))  # this collection/repo's name (brand-free)

# The ledger + shots live at the repo-root feedback/ dir — the SAME tracked
# feedback/app_feedback.json that ledger.py (the loop + `curiator reply`) reads/writes. The shell is
# nested under curiator/shell/, so `HERE / feedback` would be a stray, split-brain ledger. Honor
# gallery.yaml's feedback.dir (default "feedback"), resolved against the repo root.
FEEDBACK_DIR = REG.REPO_ROOT / (REG.FEEDBACK_CFG.get("dir") or "feedback")
FEEDBACK_JSON = FEEDBACK_DIR / "app_feedback.json"
SHOTS = FEEDBACK_DIR / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
BLUE, GREEN, AMBER, GREY, PURPLE = "#2980b9", "#1f9d55", "#cc7a00", "#777", "#8e44ad"


def _wordmark(size=15, suffix=None):
    """The curIAtor wordmark — the purple **IA** carries the brand. Flask serves the shell (unlike GitHub
    markdown), so we CAN color the letters: it reads as cur·IA·tor, never the 'curlAtor' I/l collision."""
    parts = [html.Span("◆ ", style={"color": PURPLE}),
             html.Span("cur"), html.Span("IA", style={"color": PURPLE}), html.Span("tor")]
    if suffix:
        parts.append(html.Span(f" {suffix}", style={"fontWeight": 400, "color": GREY,
                                                          "fontSize": f"{max(size - 4, 10)}px"}))
    return html.Span(parts, style={"fontWeight": 800, "fontSize": f"{size}px",
                                   "fontFamily": "system-ui, sans-serif", "letterSpacing": ".2px"})


def _wordmark_html(size=22):
    """The curIAtor wordmark as an HTML string (for the server-rendered General/history view)."""
    return (f"<span style='font-weight:800;font-size:{size}px;font-family:system-ui,sans-serif;"
            f"letter-spacing:.3px;white-space:nowrap'><span style='color:{PURPLE}'>◆</span> "
            f"cur<span style='color:{PURPLE}'>IA</span>tor</span>")


def _page(heading, body_html):
    """A small server-rendered shell page (logo banner + heading + body) — for /profile and /login."""
    return (f"<div style='font-family:system-ui,sans-serif;padding:1.6em 2em;color:#333;max-width:680px'>"
            f"<div style='display:flex;align-items:baseline;gap:11px;margin:0 0 12px'>{_wordmark_html(20)}"
            f"<span style='color:#ccc;font-size:15px'>/</span>"
            f"<span style='font-weight:700;font-size:15px;color:#444'>{_esc(COLLECTION_NAME)}</span></div>"
            f"<h2 style='color:{PURPLE};margin:0 0 12px;font-size:17px'>{heading}</h2>{body_html}</div>")


# the account dropdown (upper-right): a mini menu of Profile / Sign out (or Log in)
_AUTH_MENU_BASE = {"position": "absolute", "top": "100%", "right": "0", "marginTop": "5px",
                   "background": "white", "border": "1px solid #ddd", "borderRadius": "8px",
                   "boxShadow": "0 6px 18px rgba(0,0,0,.13)", "minWidth": "132px", "zIndex": 1000,
                   "overflow": "hidden", "textAlign": "left"}
_AUTH_MENU_HIDDEN = {**_AUTH_MENU_BASE, "display": "none"}


def _menu_item(label, href, target):
    return html.A(label, href=href, target=target, className="auth-menu-item",
                  style={"display": "block", "padding": "7px 14px", "color": "#333",
                         "textDecoration": "none", "fontSize": "12.5px", "whiteSpace": "nowrap"})


_INPUT = ("display:block;width:100%;padding:8px 10px;margin:6px 0;box-sizing:border-box;"
          "border:1px solid #ccc;border-radius:6px;font-size:13px")
_LOGIN_FORM = (
    f"<form method='post' action='/login' style='max-width:300px'>"
    f"<input name='email' type='email' placeholder='email' autofocus required style='{_INPUT}'>"
    f"<input name='password' type='password' placeholder='password' required style='{_INPUT}'>"
    f"<button type='submit' style='background:{PURPLE};color:white;border:none;padding:9px 18px;"
    f"border-radius:6px;font-weight:600;font-size:13px;cursor:pointer;margin-top:6px'>Sign in</button></form>")


# ============================== registry =====================================
def load_registry():
    """Normalize ALL_APPS into shell records. kind ∈ {dynamic, static, missing}."""
    recs = []
    for a in REG.ALL_APPS:
        f = a.get("file")
        key = a.get("key") or (Path(f).stem if f else None)
        if not key:
            continue
        # registry.py emits ABSOLUTE source paths — use them as-is (not HERE / f, which assumed the
        # research-era layout where apps lived next to the shell).
        p = Path(f) if f else None
        if p and p.suffix == ".py" and p.exists():
            kind = "dynamic"
        elif p and p.suffix == ".html" and p.exists():
            kind = "static"
        else:
            kind = "missing"
        recs.append({
            "key": key, "port": a.get("port"), "title": a.get("title", key),
            "tags": list(a.get("tags") or []), "color": a.get("color", "#888"),
            "file": f, "kind": kind,
        })
    return recs


REGISTRY = load_registry()
BY_KEY = {r["key"]: r for r in REGISTRY}
TAG_META = list(getattr(REG, "TAG_META", []))
TAG_COLOR = dict(TAG_META)

# gallery & runner-wide feedback target (not tied to any single app)
GENERAL_KEY = "__general__"
BY_KEY[GENERAL_KEY] = {"key": GENERAL_KEY, "port": None, "title": "General — the gallery & runner",
                       "tags": ["meta"], "kind": "general"}


# ============================== feedback =====================================
def load_feedback() -> dict:
    if FEEDBACK_JSON.exists():
        try:
            return json.loads(FEEDBACK_JSON.read_text())
        except Exception:
            return {}
    return {}


def _write(data):
    FEEDBACK_JSON.write_text(json.dumps(data, indent=2) + "\n")


def _current_user():
    """The verified identity for this request (default_user / proxy header / OIDC session), or None."""
    try:
        return auth.current_user(REG.AUTH_CFG)
    except Exception:                                    # no request context, etc. — provenance is best-effort
        return None


def save_entry(key, stars, comment, shot_dataurl, user=None):
    data = load_feedback()
    e = {"id": uuid.uuid4().hex[:8], "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "author": "user", "kind": "comment", "stars": stars, "comment": (comment or "").strip(),
         "screenshot": None, "status": "new", "proposed_plan": None,
         "user": auth.stamp(user if user is not None else _current_user())}
    if shot_dataurl and shot_dataurl.startswith("data:image"):
        fname = f"{key}_{e['id']}.png"
        (SHOTS / fname).write_bytes(base64.b64decode(shot_dataurl.split(",", 1)[1]))
        e["screenshot"] = f"shots/{fname}"
    data.setdefault(key, []).append(e)
    _write(data)
    return e


def add_system_note(key, text, reply_to=None, actions=None):
    """`actions` (optional) = list of approval-macro buttons, each a [label, value] pair (or a bare
    string used for both). When set — or when omitted but the note text contains A/B/C options — the
    feedback UI shows quick-approval buttons that post `value` as a user reply (so the loop fires)."""
    norm = None
    if actions:
        norm = [[a, a] if isinstance(a, str) else list(a) for a in actions]
    data = load_feedback()
    e = {"id": uuid.uuid4().hex[:8], "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "author": "claude", "kind": "system", "comment": text.strip(), "reply_to": reply_to or [],
         "status": "update", "stars": None, "screenshot": None, "actions": norm}
    data.setdefault(key, []).append(e)
    _write(data)
    return e


def set_status(key, ids, status):
    data = load_feedback()
    for e in data.get(key, []):
        if e["id"] in ids:
            e["status"] = status
    _write(data)


def _parse_actions(text):
    """Fallback action detection for ⚙ notes posted without an explicit `actions` list. Detect A/B/C/D
    options in the phrasings agents actually use — parenthesized ("(A)", "(A, recommended)") or line
    bullets ("A)", "A:", "A —") — else offer Yes/No when the note reads like an approval ask. (Prefer
    passing `curiator reply --actions` so the buttons match the text exactly.)"""
    letters = [L for L in ("A", "B", "C", "D")
               if re.search(rf"\(\s*{L}\b", text)                      # (A   (A,   (A)   (A, recommended)
               or re.search(rf"(?:^|\n)\s*{L}\s*[).:—\-]", text)       # A)  A.  A:  A—  at a line start
               or re.search(rf"\b{L}\s*\(recommended\)", text)         # A (recommended)
               or re.search(rf"\boption\s+{L}\b", text, re.I)]         # option A
    if len(letters) >= 2:
        return [[L, L] for L in letters]
    low = text.lower()
    if any(s in low for s in ("want me to", "say the word", "say go", "shall i", "approve", "go ahead", "?")):
        return [["Yes", "yes"], ["No", "no"]]
    return []


def thread_buttons(items):
    """For a feedback thread, return (system_note_id, [[label, value], ...]) for quick-approval
    buttons, or None. Buttons attach to the LATEST ⚙ note while the thread is awaiting approval."""
    awaiting = any(e.get("kind") != "system" and e.get("status") == "awaiting_approval" for e in items)
    if not awaiting:
        return None
    sysnotes = [e for e in items if e.get("kind") == "system"]
    if not sysnotes:
        return None
    note = sysnotes[-1]
    acts = note.get("actions") or _parse_actions(note.get("comment", ""))
    return (note["id"], acts) if acts else None


def record_action(key, value):
    """A quick-approval button was clicked → post it as a normal user reply (status 'new') so the
    feedback watcher fires and the loop processes it exactly like a typed approval."""
    return save_entry(key, None, str(value), None)


def app_metrics(key):
    """(avg_stars or None, n_open, n_total) from the feedback ledger."""
    items = load_feedback().get(key, [])
    stars = [e["stars"] for e in items if e.get("stars")]
    avg = round(sum(stars) / len(stars), 1) if stars else None
    n_open = sum(1 for e in items if e.get("kind") != "system" and e.get("status") in ("new", "awaiting_approval"))
    return avg, n_open, len(items)


def recency(rec):
    f = rec.get("file")
    try:
        return Path(f).stat().st_mtime if f else 0   # registry gives an absolute path
    except Exception:
        return 0


def _ts_span(iso):
    """A timestamp wrapped so assets/localtime.js re-renders it in the viewer's LOCAL timezone. Degrades
    to the raw ISO (JS off) or '' (missing). Stored timestamps are UTC (tz-aware), so the conversion is
    unambiguous; the same `.ts[data-ts]` marker is emitted as HTML in render_history for the General view."""
    iso = iso or ""
    return html.Span(iso, className="ts", title=iso, **{"data-ts": iso})


def render_history():
    """Server-rendered HTML: every feedback thread across the library, newest app
    first (General pinned), entries chronological with user/⚙Claude styling."""
    data = load_feedback()
    keys = [k for k in data if data.get(k)]
    keys.sort(key=lambda k: max((e.get("ts") or "" for e in data[k]), default=""), reverse=True)
    if GENERAL_KEY in keys:
        keys.remove(GENERAL_KEY)
        keys = [GENERAL_KEY] + keys
    n_threads = len(keys)
    n_open = sum(1 for k in keys for e in data[k]
                 if e.get("kind") != "system" and e.get("status") in ("new", "awaiting_approval"))
    out = [
        "<div style='font-family:system-ui,sans-serif;padding:1.6em 2em;color:#333;max-width:760px'>",
        # curIAtor logo + this collection's name (the custom repo name)
        f"<div style='display:flex;align-items:baseline;gap:11px;margin:0 0 10px'>{_wordmark_html(22)}"
        f"<span style='color:#ccc;font-size:16px'>/</span>"
        f"<span style='font-weight:700;font-size:16px;color:#444'>{_esc(COLLECTION_NAME)}</span></div>",
        "<h2 style='color:#8e44ad;margin:0 0 2px;font-size:17px'>General feedback &amp; history</h2>",
        "<p style='color:#555;margin:0 0 6px;font-size:13px'>Use the panel on the right for "
        "<b>gallery & runner-wide</b> notes (this thread is “General”). Below: every feedback thread across "
        f"the library.</p><p style='color:#777;font-size:12px;margin:0 0 14px'>{n_threads} threads · "
        f"{n_open} open · {len(REGISTRY)} apps.</p>",
    ]
    for key in keys:
        rec = BY_KEY.get(key, {})
        if key == GENERAL_KEY:
            label = "◆ General — library &amp; shell"
        else:
            label = f"<span style='font-family:monospace;background:{rec.get('color', '#888')};color:white;" \
                    f"padding:1px 5px;border-radius:4px;font-size:11px'>{rec.get('port', '—')}</span> " \
                    f"{_esc(rec.get('title', key))}"
        items = data[key]
        opn = sum(1 for e in items if e.get("kind") != "system" and e.get("status") in ("new", "awaiting_approval"))
        ob = f" <span style='background:#c0392b;color:white;font-size:10px;border-radius:8px;" \
             f"padding:0 6px'>{opn} open</span>" if opn else ""
        if key == GENERAL_KEY:                       # the General thread itself doesn't navigate
            out.append(f"<div style='margin:14px 0 4px;border-top:1px solid #eee;padding-top:10px'>"
                       f"<span style='font-weight:700;font-size:13px'>{label}</span>{ob}</div>")
        else:                                        # app threads: click → select that app (same-origin)
            click = (f"window.parent && window.parent.dash_clientside && "
                     f"window.parent.dash_clientside.set_props('selected-app', {{data: '{key}'}})")
            out.append(f"<div onclick=\"{click}\" title='open this app' "
                       f"style='margin:14px 0 4px;border-top:1px solid #eee;padding-top:10px;cursor:pointer'>"
                       f"<span style='font-weight:700;font-size:13px'>{label}</span>{ob} "
                       f"<span style='color:#2980b9;font-size:10.5px'>↗ open</span></div>")
        tb = thread_buttons(items)
        for e in items:
            ts = e.get("ts") or ""
            tsh = (f"<span class='ts' data-ts='{_esc(ts)}' style='color:#999;font-size:10px'>"
                   f"{_esc(ts)}</span>") if ts else ""
            if e.get("kind") == "system" or e.get("author") == "claude":
                btns = ""
                if tb and e["id"] == tb[0]:
                    chips = "".join(
                        f"<button onclick=\"fetch('/fb-action?key={_esc(key)}&amp;value={_esc(val)}',"
                        f"{{method:'POST'}}).then(function(){{location.reload()}})\" "
                        f"style='font-size:11px;font-weight:700;color:white;background:#2980b9;border:none;"
                        f"border-radius:6px;padding:3px 11px;margin:0 5px 0 0;cursor:pointer'>{_esc(lbl)}</button>"
                        for lbl, val in tb[1])
                    btns = (f"<div style='margin-top:6px'>{chips}"
                            f"<span style='color:#999;font-size:10px;margin-left:4px'>"
                            f"optional — or type a reply</span></div>")
                out.append(f"<div style='margin:4px 0 4px 22px;border-left:3px solid #2980b9;"
                           f"background:#eef5fb;padding:5px 9px;border-radius:3px'>"
                           f"<b style='color:#2980b9'>⚙ Claude</b> {tsh}"
                           f"<div style='font-size:12.5px;color:#1a3a5a;white-space:pre-wrap;margin-top:2px'>"
                           f"{_esc(e.get('comment', ''))}</div>{btns}</div>")
            else:
                st = e.get("status", "new")
                stc = {"new": "#cc7a00", "done": "#1f9d55", "awaiting_approval": "#2980b9"}.get(st, "#777")
                stars = ("★" * (e.get("stars") or 0)) if e.get("stars") else ""
                shot = (f"<br><img src='/feedback-shot/{Path(e['screenshot']).name}' "
                        f"style='max-width:320px;border:1px solid #ddd;border-radius:4px;margin-top:4px'>"
                        if e.get("screenshot") else "")
                who = (e.get("user") or {}).get("name")
                whoh = (f" <span style='color:#8e44ad;font-size:10px;font-weight:600'>· {_esc(who)}</span>"
                        if who else "")
                out.append(f"<div style='margin:4px 0;border-left:2px solid {stc};padding:5px 9px;"
                           f"background:#fafafa;border-radius:3px'>"
                           f"<span style='color:#cc7a00'>{stars}</span> "
                           f"<span style='background:{stc};color:white;font-size:9.5px;border-radius:8px;"
                           f"padding:1px 6px'>{st}</span> {tsh}{whoh}"
                           f"<div style='font-size:12.5px;color:#333;white-space:pre-wrap;margin-top:2px'>"
                           f"{_esc(e.get('comment', ''))}{shot}</div></div>")
    out.append("</div>")
    out.append("<script src='/assets/localtime.js'></script>")   # render .ts in the viewer's local tz
    return "".join(out)


def feedback_list(key):
    items = load_feedback().get(key, [])
    if not items:
        return html.Div("No feedback yet.", style={"color": GREY, "fontSize": "12px"})
    tb = thread_buttons(items)
    rows = []
    for e in reversed(items):
        if e.get("kind") == "system" or e.get("author") == "claude":
            kids = [html.Div([html.Span("⚙ Claude", style={"fontWeight": 700, "color": BLUE}),
                              html.Span(["  update · ", _ts_span(e.get("ts"))],
                                        style={"color": GREY, "fontSize": "10px"})]),
                    html.Div(e.get("comment", ""), style={"fontSize": "12px", "color": "#1a3a5a",
                             "marginTop": "2px", "whiteSpace": "pre-wrap"})]
            if tb and e["id"] == tb[0]:
                kids.append(html.Div(
                    [html.Button(lbl, id={"type": "fbact", "key": key, "value": val}, n_clicks=0,
                                 style={"fontSize": "11px", "fontWeight": 700, "color": "white",
                                        "background": BLUE, "border": "none", "borderRadius": "6px",
                                        "padding": "3px 11px", "marginRight": "5px", "cursor": "pointer"})
                     for lbl, val in tb[1]]
                    + [html.Span("optional — or type a reply", style={"color": GREY, "fontSize": "10px"})],
                    style={"marginTop": "6px"}))
            rows.append(html.Div(kids,
                style={"borderLeft": f"3px solid {BLUE}", "padding": "5px 8px", "marginBottom": "6px",
                       "background": "#eef5fb", "borderRadius": "3px"}))
            continue
        st = e.get("status", "new")
        st_col = {"new": AMBER, "done": GREEN, "awaiting_approval": BLUE}.get(st, GREY)
        stars = ("★" * (e.get("stars") or 0) + "✩" * (5 - (e.get("stars") or 0))) if e.get("stars") else ""
        head = [html.Span(stars, style={"color": AMBER, "fontSize": "13px", "marginRight": "6px"}),
                html.Span(st, style={"fontSize": "9.5px", "color": "white", "background": st_col,
                          "padding": "1px 6px", "borderRadius": "8px"}),
                html.Span(["  ", _ts_span(e.get("ts"))], style={"color": GREY, "fontSize": "10px"})]
        who = (e.get("user") or {}).get("name")
        if who:
            head.append(html.Span(f"  · {who}", title=(e.get("user") or {}).get("email", ""),
                                  style={"color": PURPLE, "fontSize": "10px", "fontWeight": 600}))
        kids = [html.Div(head)]
        if e.get("comment"):
            kids.append(html.Div(e["comment"], style={"fontSize": "12px", "color": "#333", "marginTop": "2px"}))
        if e.get("screenshot"):
            kids.append(html.Img(src=f"/feedback-shot/{Path(e['screenshot']).name}",
                                 style={"maxWidth": "100%", "marginTop": "4px", "border": "1px solid #ddd",
                                        "borderRadius": "4px"}))
        rows.append(html.Div(kids, style={"borderLeft": f"2px solid {st_col}", "padding": "4px 8px",
                                          "marginBottom": "6px", "background": "#fafafa",
                                          "opacity": 0.6 if st == "done" else 1.0}))
    return html.Div(rows)


# ============================== catalog ======================================
SORTS = [("recency", "recently touched"), ("open", "open feedback"), ("rating", "rating"),
         ("id", "number"), ("title", "title"), ("tag", "tag")]


def _tag_chip(t):
    return html.Span(t, style={"fontSize": "9px", "color": "white", "background": TAG_COLOR.get(t, "#999"),
                               "padding": "0 5px", "borderRadius": "7px", "marginRight": "3px"})


def _share_btn(key):
    """A small per-app share button — copies a deep-link (?app=<key>) so a teammate lands on this app."""
    return html.Button("🔗", id={"type": "share", "key": key}, n_clicks=0, className="share-btn",
                       title="Copy a shareable link to this app",
                       style={"border": "none", "background": "transparent", "cursor": "pointer",
                              "fontSize": "12px", "padding": "2px 6px", "borderRadius": "4px",
                              "flex": "0 0 auto", "lineHeight": "1"})


def catalog_rows(search, sortby, tags_sel, reverse):
    recs = list(REGISTRY)
    s = (search or "").lower().strip()
    if s:
        recs = [r for r in recs if s in r["title"].lower() or s in " ".join(r["tags"]).lower()
                or s in str(r.get("port", "")) or s in r["key"].lower()]
    if tags_sel:
        recs = [r for r in recs if any(t in r["tags"] for t in tags_sel)]
    met = {r["key"]: app_metrics(r["key"]) for r in recs}
    rcy = {r["key"]: recency(r) for r in recs}

    def keyf(r):
        avg, nopen, _ = met[r["key"]]
        return {"recency": rcy[r["key"]], "open": nopen, "rating": (avg or -1),
                "id": (r.get("port") or 0), "title": r["title"].lower(),
                "tag": (r["tags"][0] if r["tags"] else "zzz")}[sortby]

    recs.sort(key=keyf, reverse=not reverse if sortby in ("recency", "open", "rating") else reverse)
    rows = []
    for r in recs:
        avg, nopen, ntot = met[r["key"]]
        badges = []
        if avg is not None:
            badges.append(html.Span(f"★{avg}", style={"color": AMBER, "fontSize": "11px", "marginLeft": "6px"}))
        if nopen:
            badges.append(html.Span(f"●{nopen}", title=f"{nopen} open", style={"color": "white",
                          "background": "#c0392b", "fontSize": "9px", "borderRadius": "8px",
                          "padding": "0 5px", "marginLeft": "5px"}))
        num = html.Span(str(r.get("port") or "—"), style={"fontFamily": "monospace", "fontSize": "10.5px",
                        "color": "white", "background": r["color"], "padding": "1px 5px", "borderRadius": "4px"})
        dead = r["kind"] == "missing"
        content = html.Div([
            html.Div([num] + badges, style={"display": "flex", "alignItems": "center"}),
            html.Div(r["title"], style={"fontSize": "12px", "color": "#999" if dead else "#222",
                     "fontWeight": 600, "margin": "2px 0", "lineHeight": "1.25"}),
            html.Div([_tag_chip(t) for t in r["tags"][:5]]),
        ], id={"type": "approw", "key": r["key"]}, n_clicks=0,
            style={"cursor": "pointer", "flex": "1", "minWidth": "0"})
        rows.append(html.Div([content, _share_btn(r["key"])], className="approw-wrap",
            style={"display": "flex", "alignItems": "center", "gap": "2px", "padding": "7px 9px",
                   "borderBottom": "1px solid #eee", "background": "#fff"}))
    head = html.Div(f"{len(recs)} apps", style={"fontSize": "10.5px", "color": GREY, "padding": "4px 9px"})
    # pinned general (library/shell) feedback row at the very top
    _, gopen, _ = app_metrics(GENERAL_KEY)
    gbadge = [html.Span(f"●{gopen}", style={"color": "white", "background": "#c0392b", "fontSize": "9px",
              "borderRadius": "8px", "padding": "0 5px", "marginLeft": "6px"})] if gopen else []
    general = html.Div([html.Span("◆ General", style={"fontWeight": 700, "fontSize": "12px", "color": PURPLE}),
                        html.Span(" — gallery & runner feedback", style={"fontSize": "10.5px", "color": GREY})]
                       + gbadge,
                       id={"type": "approw", "key": GENERAL_KEY}, n_clicks=0,
                       style={"padding": "8px 9px", "borderBottom": "2px solid #ddd", "cursor": "pointer",
                              "background": "#f6f1fb"})
    return [general, head] + rows


# ============================== lazy mounting ================================
def resolve_server(key):
    """Build a sub-app's WSGI server, UNMODIFIED, with its pathname prefix.
    Handles build_app() and module-level `app`. Returns server or None."""
    os.environ["DASH_REQUESTS_PATHNAME_PREFIX"] = f"/app/{key}/"
    try:
        mod = importlib.import_module(key)
        if hasattr(mod, "build_app"):
            return mod.build_app().server
        if hasattr(mod, "app") and hasattr(mod.app, "server"):
            return mod.app.server
        return None
    finally:
        os.environ.pop("DASH_REQUESTS_PATHNAME_PREFIX", None)


class LazyDispatcher:
    """Mounts /app/<key>/ → the sub-app, building (and caching) it on first hit."""
    def __init__(self, root, prefix="/app/"):
        self.root, self.prefix = root, prefix
        self.lock = threading.Lock()
        self.cache = {}

    def _get(self, key):
        with self.lock:
            if key not in self.cache:
                try:
                    self.cache[key] = resolve_server(key)
                except Exception as e:  # noqa: BLE001
                    print(f"[shell] mount failed: {key}: {e}")
                    self.cache[key] = None
            return self.cache[key]

    def __call__(self, environ, start_response):
        p = environ.get("PATH_INFO", "")
        if p.startswith(self.prefix):
            key = p[len(self.prefix):].split("/", 1)[0]
            if key:
                app = self._get(key)
                if app is None:
                    start_response("200 OK", [("Content-Type", "text/html")])
                    return [f"<div style='font-family:sans-serif;padding:2em;color:#555'>"
                            f"<b>{key}</b> could not be mounted (no build_app / module app, or a build "
                            f"error). It still runs standalone on its own port.</div>".encode()]
                mount = self.prefix + key
                environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + mount
                environ["PATH_INFO"] = p[len(mount):]
                return app(environ, start_response)
        return self.root(environ, start_response)


# The live dispatcher of a running shell. `invalidate_app` (reached via the /reload/<key> route, which
# `curiator reply --status done` pokes after the agent edits an app) drops ONE app's cached module +
# built server, so the next view rebuilds from the edited source — the M2 "shell-cache" fix: an edit
# goes live without restarting the whole shell.
_DISPATCHER = None


def invalidate_app(key: str) -> bool:
    """Forget a mounted app's cached build AND its imported Python module, so the next /app/<key>/ hit
    re-imports the edited source and rebuilds fresh. Returns True if the module had been imported."""
    importlib.invalidate_caches()
    was_loaded = sys.modules.pop(key, None) is not None
    d = _DISPATCHER
    if d is not None:
        with d.lock:
            d.cache.pop(key, None)
    return was_loaded


# ============================== shell chrome =================================
def app_src(key):
    if key == GENERAL_KEY:
        return "/general"
    r = BY_KEY.get(key)
    if not r:
        return ""
    if r["kind"] == "static":
        return f"/static-app/{key}.html"
    return f"/app/{key}/"


def build_shell() -> Dash:
    shell = Dash(__name__, assets_folder="assets", title=TITLE,
                 suppress_callback_exceptions=True,
                 meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}])

    # Flask session (login state) + the login routes appropriate to auth.mode.
    shell.server.secret_key = os.environ.get("CURIATOR_SECRET_KEY") or os.urandom(24)
    _mode = REG.AUTH_CFG.get("mode", "none")
    if _mode == "oidc":
        auth.register_oidc(REG.AUTH_CFG, shell.server)       # /login → IdP, /auth/callback, /logout
    elif _mode == "local":
        @shell.server.route("/login", methods=["GET", "POST"])   # built-in username/password portal
        def _local_login():
            from flask import redirect, request, session
            ip = request.remote_addr or "?"
            err = ""
            blocked, retry = auth.rate_limit_status(REG.AUTH_CFG, ip)
            if request.method == "POST" and not blocked:
                u = auth.verify_local(REG.AUTH_CFG, request.form.get("email", ""), request.form.get("password", ""))
                if u:
                    auth.clear_login_failures(ip)
                    session[auth.SESSION_KEY] = u
                    return redirect("/")
                auth.record_login_failure(REG.AUTH_CFG, ip)   # too many → lock the IP out for a while
                blocked, retry = auth.rate_limit_status(REG.AUTH_CFG, ip)
                err = "" if blocked else "<p style='color:#c0392b;font-size:13px;margin:0 0 8px'>Invalid email or password.</p>"
            if blocked:
                err = f"<p style='color:#c0392b;font-size:13px;margin:0 0 8px'>Too many attempts — try again in {retry}s.</p>"
            return _page("Sign in", err + ("" if blocked else _LOGIN_FORM))

        @shell.server.route("/logout")
        def _local_logout():
            from flask import redirect, session
            session.pop(auth.SESSION_KEY, None)
            return redirect("/")
    else:                                                    # none / header — no curiator login
        @shell.server.route("/login")
        def _login_info():
            return _page("Sign in",
                f"<p>Sign-in isn't enabled for this gallery (<code>auth.mode: {_mode}</code>).</p>"
                "<p style='color:#777;font-size:13px'>Turn it on in <code>gallery.yaml</code>: "
                "<code>auth.mode: local</code> (a built-in username/password login — run "
                "<code>curiator user add &lt;email&gt;</code> to create accounts), <code>oidc</code> "
                "(your own IdP), or <code>header</code> (behind an auth proxy). See "
                "<code>docs/USING_CURIATOR.md</code>.</p>")

        @shell.server.route("/logout")                       # header/none: no curiator session to clear
        def _logout_noop():
            from flask import redirect
            return redirect("/")

    @shell.server.route("/profile")                          # who you are + sign in/out (all modes)
    def _profile():
        u = auth.current_user(REG.AUTH_CFG) or {}
        m = REG.AUTH_CFG.get("mode", "none")
        btn = (f"display:inline-block;background:{PURPLE};color:white;text-decoration:none;"
               "padding:6px 14px;border-radius:6px;font-weight:600;font-size:13px")
        info = (f"<p style='font-size:15px'><b>{_esc(u.get('name') or 'anonymous')}</b> &nbsp;"
                f"<span style='color:#777'>{_esc(u.get('email') or '—')}</span></p>"
                f"<p style='color:#777;font-size:12.5px'>groups: {_esc(', '.join(u.get('groups') or []) or '—')} "
                f"· auth mode: <code>{m}</code></p>")
        if m == "oidc":
            action = (f"<a href='/logout' target='_top' style='{btn}'>Sign out</a>" if u
                      else f"<a href='/login' target='_top' style='{btn}'>Sign in</a>")
        elif m == "header":
            action = ("<p style='color:#777;font-size:13px'>Authenticated via your gateway — "
                      "sign out through your identity provider.</p>")
        else:
            du = _esc(REG.AUTH_CFG.get("default_user") or "anonymous@local")
            action = (f"<p style='color:#777;font-size:13px'>Anonymous mode — everyone is <code>{du}</code>. "
                      "Enable sign-in by setting <code>auth.mode: oidc</code> in <code>gallery.yaml</code>.</p>")
        return _page("Your profile", info + action)

    @shell.server.route("/whoami")
    def _whoami():               # the resolved identity for this request (handy for header-mode + debugging)
        from flask import jsonify
        return jsonify(auth.current_user(REG.AUTH_CFG) or {"authenticated": False})

    @shell.server.route("/feedback-shot/<path:fname>")
    def _shot(fname):
        return send_from_directory(SHOTS, fname)

    @shell.server.route("/static-app/<path:fname>")
    def _static_app(fname):
        return send_from_directory(HERE, fname)

    @shell.server.route("/general")
    def _general():
        return render_history()

    @shell.server.route("/reload/<key>", methods=["POST", "GET"])
    def _reload(key):
        # Poked by `curiator reply --status done` after the agent edits an app: drop the cached build so
        # the next view rebuilds from the edited source (refresh the gallery to see the fix).
        from flask import jsonify
        return jsonify({"reloaded": key, "module_was_loaded": invalidate_app(key)})

    tag_opts = [{"label": t, "value": t} for t, _c in TAG_META]
    controls = html.Div([
        dcc.Input(id="cat-search", type="text", placeholder="search…", debounce=True,
                  style={"width": "100%", "fontSize": "12px", "padding": "4px 6px", "boxSizing": "border-box",
                         "marginBottom": "5px"}),
        html.Div([
            dcc.Dropdown(id="cat-sort", value="id", clearable=False, searchable=False,
                         options=[{"label": f"sort: {lab}", "value": v} for v, lab in SORTS],
                         style={"fontSize": "11px", "flex": "1"}),
            dcc.Checklist(id="cat-rev", options=[{"label": " ⇅", "value": "r"}], value=["r"],
                          style={"fontSize": "12px", "marginLeft": "4px"}),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "5px"}),
        dcc.Dropdown(id="cat-tags", multi=True, placeholder="filter tags…", options=tag_opts,
                     style={"fontSize": "11px"}),
    ], style={"padding": "8px 9px", "borderBottom": "1px solid #ddd"})

    catalog = html.Div([
        html.Div(_wordmark(16, suffix="gallery"), style={"padding": "10px 9px 5px"}),
        controls,
        html.Div(id="share-toast", className="share-toast",
                 style={"fontSize": "10px", "color": GREEN, "padding": "0 9px", "minHeight": "13px",
                        "whiteSpace": "nowrap", "overflow": "hidden", "textOverflow": "ellipsis"}),
        html.Div(id="cat-list", style={"overflowY": "auto", "flex": "1"}),
    ], id="catalog-div", className="shell-catalog",
        style={"width": "270px", "flex": "0 0 270px", "borderRight": "1px solid #ddd", "display": "flex",
               "flexDirection": "column", "height": "100vh", "background": "#fcfcfc"})

    frame = html.Iframe(id="app-frame", name="app-frame", src="", style={"flex": "1", "border": "none",
                        "height": "100%", "width": "100%"})

    sidebar = html.Div([
        html.Div([                                    # the account corner: click the identity → a mini menu
            html.Div(id="auth-trigger", n_clicks=0,
                     style={"cursor": "pointer", "display": "inline-block", "padding": "1px 5px",
                            "borderRadius": "5px", "userSelect": "none"}),
            html.Div(id="auth-menu", style=_AUTH_MENU_HIDDEN),
            html.Div(id="auth-scrim", n_clicks=0, style={"display": "none"}),   # outside-click → close
            dcc.Store(id="auth-init", data=1),
            dcc.Store(id="auth-open", data=False),
        ], style={"position": "relative", "textAlign": "right", "minHeight": "16px",
                  "marginBottom": "2px", "fontSize": "11px"}),
        html.H4("Feedback", style={"margin": "0 0 2px", "fontSize": "14px"}),
        html.Div([
            html.Div(id="fb-appname", style={"fontSize": "11.5px", "color": GREY, "flex": "1", "minWidth": "0"}),
            html.Button("🔗 Share", id="fb-share", n_clicks=0, className="fb-share-btn",
                        title="Copy a shareable link to the app you're viewing",
                        style={"fontSize": "10.5px", "padding": "2px 8px", "cursor": "pointer",
                               "border": "1px solid #ddd", "borderRadius": "5px", "background": "#fff",
                               "color": GREY, "whiteSpace": "nowrap", "flex": "0 0 auto"}),
        ], style={"display": "flex", "alignItems": "center", "gap": "6px", "marginBottom": "3px"}),
        html.Div(id="fb-share-msg", style={"fontSize": "10px", "color": GREEN, "minHeight": "12px",
                 "marginBottom": "6px", "whiteSpace": "nowrap", "overflow": "hidden", "textOverflow": "ellipsis"}),
        dcc.RadioItems(id="fb-stars", inline=True,
                       options=[{"label": "★" * i, "value": i} for i in range(1, 6)],
                       style={"fontSize": "15px", "color": AMBER, "marginBottom": "6px"}),
        dcc.Textarea(id="fb-comment", placeholder="What's good / what to change…",
                     style={"width": "100%", "height": "80px", "fontSize": "12px", "marginBottom": "6px",
                            "boxSizing": "border-box"}),
        html.Div([
            html.Button("📷 Capture view", id="capture-btn", n_clicks=0,
                        style={"fontSize": "12px", "marginRight": "8px", "cursor": "pointer"}),
            dcc.Upload(id="fb-upload", children=html.Span("⬆ upload", style={"fontSize": "12px"}),
                       style={"display": "inline-block", "padding": "4px 10px", "border": "1px dashed #bbb",
                              "borderRadius": "5px", "cursor": "pointer"}),
        ], style={"display": "flex", "alignItems": "center", "marginBottom": "6px"}),
        html.Img(id="fb-preview", style={"display": "none"}),
        dcc.Store(id="shot-store"),
        dcc.Store(id="selected-app"),
        html.Button("Save feedback", id="fb-save", n_clicks=0,
                    style={"width": "100%", "padding": "7px", "fontSize": "12.5px", "fontWeight": 700,
                           "background": GREEN, "color": "white", "border": "none", "borderRadius": "6px",
                           "cursor": "pointer", "marginBottom": "4px"}),
        html.Div(id="fb-status", style={"fontSize": "11.5px", "minHeight": "16px", "marginBottom": "10px"}),
        html.Hr(style={"border": "none", "borderTop": "1px solid #eee"}),
        html.Div("prior feedback", style={"fontSize": "11px", "color": "#666", "fontWeight": 700,
                 "marginBottom": "4px"}),
        html.Div(id="fb-list"),
    ], id="sidebar-div", className="shell-feedback",
        style={"width": "320px", "flex": "0 0 320px", "borderLeft": "1px solid #ddd", "background": "#fcfcfc",
               "padding": "12px", "boxSizing": "border-box", "overflowY": "auto", "height": "100vh"})

    # mobile-only top bar (hidden on desktop via CSS) — toggles the catalog / feedback drawers
    mobilebar = html.Div([
        html.Button("☰ Library", id="m-cat", n_clicks=0, className="shell-mbtn"),
        html.Div(_wordmark(14), style={"flex": "1", "textAlign": "center"}),
        html.Button("💬 Feedback", id="m-fb", n_clicks=0, className="shell-mbtn"),
    ], className="shell-mobilebar")
    scrim = html.Div(id="scrim", className="shell-scrim")

    row = html.Div([catalog, frame, sidebar], style={"display": "flex", "flex": "1", "minHeight": "0"})
    shell.layout = html.Div([dcc.Location(id="url", refresh=False),     # deep-link ?app=<key> ↔ selection
                             mobilebar, scrim, dcc.Store(id="cat-open", data=False),
                             dcc.Store(id="fb-open", data=False), dcc.Store(id="url-sync"),
                             dcc.Interval(id="live-poll", interval=max(POLL_MS, 1000),
                                          disabled=(POLL_MS <= 0)),   # live feedback refresh
                             dcc.Store(id="live-sig"), row],
                            style={"display": "flex", "flexDirection": "column", "height": "100vh",
                                   "margin": 0, "fontFamily": "system-ui, sans-serif"})

    # ---- callbacks ----
    @shell.callback(Output("cat-list", "children"), Input("cat-search", "value"), Input("cat-sort", "value"),
                    Input("cat-tags", "value"), Input("cat-rev", "value"))
    def _catalog(search, sortby, tags_sel, rev):
        return catalog_rows(search, sortby, tags_sel, bool(rev))

    @shell.callback(Output("selected-app", "data"),
                    Input("url", "search"), Input({"type": "approw", "key": ALL}, "n_clicks"))
    def _select(search, _clicks):
        """Single owner of the selected app — ONE output (no allow_duplicate: two callbacks writing the
        same prop mis-routes inputs). A row click wins; otherwise route from the URL (?app=<key>) on load
        and back/forward, defaulting to ◆ General so you land on something instead of a blank frame."""
        tid = ctx.triggered_id
        if isinstance(tid, dict) and tid.get("type") == "approw":          # a catalog row was clicked
            return tid["key"] if (ctx.triggered and ctx.triggered[0].get("value")) else no_update
        if isinstance(search, (list, tuple)):                              # be defensive about input shape
            search = search[0] if search else ""
        from urllib.parse import parse_qs
        cand = (parse_qs((search or "").lstrip("?")).get("app") or [None])[0]
        if cand == "general":
            cand = GENERAL_KEY
        return cand if cand in BY_KEY else GENERAL_KEY

    # ⤴ share: copy a deep-link to the clicked app (clientside — no round-trip). Robust across Dash
    # versions: parse the triggered pattern-id from prop_id for the key.
    shell.clientside_callback(
        "function(n){var c=window.dash_clientside.callback_context;"
        "if(!c||!c.triggered||!c.triggered.length||!c.triggered[0].value)return window.dash_clientside.no_update;"
        "var p=c.triggered[0].prop_id||'';var key=null;"
        "try{key=JSON.parse(p.substring(0,p.lastIndexOf('.'))).key;}catch(e){key=(c.triggered_id||{}).key;}"
        "if(!key)return window.dash_clientside.no_update;"
        "var url=window.location.origin+'/?app='+encodeURIComponent(key);"
        "try{navigator.clipboard.writeText(url);}catch(e){}"
        "return '🔗 copied: '+url;}",
        Output("share-toast", "children"),
        Input({"type": "share", "key": ALL}, "n_clicks"), prevent_initial_call=True)

    # keep the address bar in sync with the open app (so the bare URL is itself shareable) — via
    # replaceState so it doesn't feed back into dcc.Location. ◆ General stays the clean default (no param).
    shell.clientside_callback(
        "function(key){try{var G='" + GENERAL_KEY + "';"
        "if(key&&key!==G){var s='?app='+encodeURIComponent(key);"
        "if(window.location.search!==s){window.history.replaceState(null,'',s);}}"
        "else if(key===G&&window.location.search){window.history.replaceState(null,'',window.location.pathname);}"
        "}catch(e){}return window.dash_clientside.no_update;}",
        Output("url-sync", "data"), Input("selected-app", "data"), prevent_initial_call=True)

    # 🔗 Share (feedback-panel header): copy a link to the app you're currently viewing. Reads the
    # selection directly (not the address bar), so it's correct even before the bar syncs. General → clean URL.
    shell.clientside_callback(
        "function(n, key){if(!n)return window.dash_clientside.no_update;"
        "var G='" + GENERAL_KEY + "';"
        "var url=window.location.origin+'/'+((key&&key!==G)?('?app='+encodeURIComponent(key)):'');"
        "try{navigator.clipboard.writeText(url);}catch(e){}"
        "return '🔗 copied: '+url;}",
        Output("fb-share-msg", "children"),
        Input("fb-share", "n_clicks"), State("selected-app", "data"), prevent_initial_call=True)

    @shell.callback(Output("app-frame", "src"), Output("fb-appname", "children"),
                    Output("fb-list", "children"), Input("selected-app", "data"))
    def _open(key):
        if not key:
            return no_update, "Select an app from the library →", no_update
        r = BY_KEY.get(key, {})
        label = f"{r.get('port', '')} · {r.get('title', key)}"
        src = app_src(key)
        if key == GENERAL_KEY:                       # cache-bust so the history reloads fresh each time
            src += f"?t={datetime.now().timestamp()}"
        return src, label, feedback_list(key)

    shell.clientside_callback(ClientsideFunction(namespace="shell", function_name="capture"),
                              Output("shot-store", "data"), Input("capture-btn", "n_clicks"),
                              prevent_initial_call=True)

    @shell.callback(Output("shot-store", "data", allow_duplicate=True), Input("fb-upload", "contents"),
                    prevent_initial_call=True)
    def _upload(contents):
        return contents or no_update

    @shell.callback(Output("fb-preview", "src"), Output("fb-preview", "style"),
                    Input("shot-store", "data"), prevent_initial_call=True)
    def _preview(data):
        base = {"maxWidth": "100%", "border": "1px solid #ddd", "borderRadius": "4px", "marginBottom": "8px"}
        if data and isinstance(data, str) and data.startswith("data:image"):
            return data, {**base, "display": "block"}
        return no_update, {**base, "display": "none"}

    @shell.callback(Output("fb-status", "children"), Output("fb-status", "style"),
                    Output("fb-list", "children", allow_duplicate=True), Output("fb-comment", "value"),
                    Output("fb-stars", "value"), Output("shot-store", "data", allow_duplicate=True),
                    Output("fb-preview", "style", allow_duplicate=True), Output("cat-list", "children", allow_duplicate=True),
                    Input("fb-save", "n_clicks"), State("selected-app", "data"), State("fb-stars", "value"),
                    State("fb-comment", "value"), State("shot-store", "data"),
                    State("cat-search", "value"), State("cat-sort", "value"), State("cat-tags", "value"),
                    State("cat-rev", "value"), prevent_initial_call=True)
    def _save(n, key, stars, comment, shot, search, sortby, tags_sel, rev):
        okstyle = {"fontSize": "11.5px", "color": GREEN}
        errstyle = {"fontSize": "11.5px", "color": "#c0392b"}
        hide = {"display": "none"}
        if not key:
            return "Select an app first.", errstyle, no_update, no_update, no_update, no_update, no_update, no_update
        u = _current_user()
        if auth.login_required(REG.AUTH_CFG) and not u:    # oidc: feedback requires a verified identity
            return ("Sign in to leave feedback.", errstyle, no_update, no_update, no_update,
                    no_update, no_update, no_update)
        if not stars and not (comment or "").strip() and not shot:
            return "Add a rating, comment, or screenshot.", errstyle, no_update, no_update, no_update, \
                no_update, no_update, no_update
        shot = shot if (isinstance(shot, str) and shot.startswith("data:image")) else None
        e = save_entry(key, stars, comment, shot, user=u)
        who = (e.get("user") or {}).get("name")
        msg = f"✓ saved ({e['id']})" + (f" · {who}" if who else "") + ("  +screenshot" if e["screenshot"] else "")
        return msg, okstyle, feedback_list(key), "", None, None, hide, \
            catalog_rows(search, sortby, tags_sel, bool(rev))

    # ---- live refresh: poll the ledger; update the open thread + catalog badges when it changes ----
    @shell.callback(Output("fb-list", "children", allow_duplicate=True),
                    Output("cat-list", "children", allow_duplicate=True),
                    Output("live-sig", "data"),
                    Input("live-poll", "n_intervals"),
                    State("selected-app", "data"), State("live-sig", "data"),
                    State("cat-search", "value"), State("cat-sort", "value"),
                    State("cat-tags", "value"), State("cat-rev", "value"), prevent_initial_call=True)
    def _live_refresh(_n, sel, sig, search, sortby, tags_sel, rev):
        sig = sig or {}
        try:
            mtime = FEEDBACK_JSON.stat().st_mtime
        except OSError:
            mtime = 0
        if mtime == sig.get("mtime"):
            return no_update, no_update, no_update            # ledger unchanged → skip the render
        data = load_feedback()
        # re-render the open thread only if THIS app's entries changed (avoids scroll-jumps from other apps)
        fb = [[e.get("id"), e.get("status"), len(e.get("comment") or "")] for e in data.get(sel, [])] if sel else []
        fb_out = feedback_list(sel) if (sel and fb != sig.get("fb")) else no_update
        return fb_out, catalog_rows(search, sortby, tags_sel, bool(rev)), {"mtime": mtime, "fb": fb}

    # ---- account menu: click the identity → a mini menu (Profile / Sign out, or Log in) ----
    @shell.callback(Output("auth-trigger", "children"), Output("auth-menu", "children"),
                    Input("auth-init", "data"))
    def _auth_render(_):
        u = _current_user()
        mode = REG.AUTH_CFG.get("mode", "none")
        verified = bool(u) and mode != "none"                 # a real identity vs the anonymous default
        name = (u or {}).get("name") or "anonymous"
        trigger = [html.Span("● " if verified else "○ ", style={"color": GREEN if verified else GREY}),
                   html.Span(name, style={"fontWeight": 600, "color": "#333" if verified else GREY}),
                   html.Span(" ▾", style={"color": GREY, "fontSize": "9px", "marginLeft": "2px"})]
        if verified:
            menu = [_menu_item("Profile", "/profile", "app-frame"),
                    _menu_item("Sign out", "/logout", "_top")]
        else:
            menu = [_menu_item("Log in", "/login", "_top" if mode in ("oidc", "local") else "app-frame")]
        return trigger, menu

    @shell.callback(Output("auth-open", "data"), Input("auth-trigger", "n_clicks"),
                    Input("auth-scrim", "n_clicks"), State("auth-open", "data"), prevent_initial_call=True)
    def _auth_toggle(_t, _s, is_open):
        return (not is_open) if ctx.triggered_id == "auth-trigger" else False   # trigger toggles; scrim closes

    @shell.callback(Output("auth-menu", "style"), Output("auth-scrim", "style"), Input("auth-open", "data"))
    def _auth_menu_vis(is_open):
        if is_open:
            return ({**_AUTH_MENU_BASE, "display": "block"},
                    {"position": "fixed", "inset": "0", "zIndex": 999, "display": "block"})
        return _AUTH_MENU_HIDDEN, {"display": "none"}

    # ---- mobile drawers: ☰/💬 toggle catalog/feedback; selecting an app or tapping the scrim closes ----
    @shell.callback(Output("cat-open", "data"), Output("fb-open", "data"),
                    Input("m-cat", "n_clicks"), Input("m-fb", "n_clicks"),
                    Input("selected-app", "data"), Input("scrim", "n_clicks"),
                    State("cat-open", "data"), State("fb-open", "data"), prevent_initial_call=True)
    def _drawers(_c, _f, _sel, _s, cat, fb):
        t = ctx.triggered_id
        if t == "m-cat":
            return (not cat), False
        if t == "m-fb":
            return False, (not fb)
        return False, False                              # app selected / scrim tapped → close both

    @shell.callback(Output("catalog-div", "className"), Output("sidebar-div", "className"),
                    Output("scrim", "className"), Input("cat-open", "data"), Input("fb-open", "data"))
    def _drawer_classes(cat, fb):
        return ("shell-catalog" + (" open" if cat else ""),
                "shell-feedback" + (" open" if fb else ""),
                "shell-scrim" + (" open" if (cat or fb) else ""))

    # ---- quick-approval macros: A/B/C or Yes/No buttons on approval-pending ⚙ notes ----
    # Per-app (Dash) buttons → this pattern-matching callback; general-history (HTML iframe) buttons
    # → the /fb-action Flask route below. Both just post the choice as a user reply so the loop fires.
    @shell.callback(Output("fb-list", "children", allow_duplicate=True),
                    Output("fb-status", "children", allow_duplicate=True),
                    Output("fb-status", "style", allow_duplicate=True),
                    Input({"type": "fbact", "key": ALL, "value": ALL}, "n_clicks"),
                    State("selected-app", "data"), prevent_initial_call=True)
    def _fb_action(clicks, sel):
        trig = ctx.triggered_id
        if not trig or not any(clicks or []):
            return no_update, no_update, no_update
        record_action(trig["key"], trig["value"])
        newlist = feedback_list(trig["key"]) if trig["key"] == sel else no_update
        return newlist, f"✓ recorded “{trig['value']}” — processing shortly", {"fontSize": "11.5px", "color": GREEN}

    @shell.server.route("/fb-action", methods=["POST", "GET"])
    def _fb_action_route():
        from flask import request
        key = request.args.get("key")
        value = request.args.get("value")
        if key and value is not None:
            record_action(key, value)
            return ("ok", 200)
        return ("missing key/value", 400)

    return shell


def build_application():
    global _DISPATCHER
    shell = build_shell()
    _DISPATCHER = LazyDispatcher(shell.server)   # stash it so /reload/<key> can invalidate one app's cache
    return _DISPATCHER, shell


if __name__ == "__main__":
    application, _shell = build_application()
    from werkzeug.serving import run_simple
    # 0.0.0.0 so the shell is reachable over the Tailscale tailnet (phone-on-the-go).
    # NB this also exposes it on the LAN; it's an internal dev tool on a private tailnet.
    host = os.environ.get("SHELL_HOST", "0.0.0.0")
    run_simple(host, PORT, application, threaded=True)
