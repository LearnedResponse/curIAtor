"""app_shell.py — curIAtor — single-origin gallery shell + catalog + feedback. Port 8200.

The consolidated front door for your whole app gallery. ONE Flask server
(via a lazy DispatcherMiddleware) mounts every Dash app at a PATH, so everything
is same-origin. Layout: CATALOG (left) · app in an iframe (center) · FEEDBACK
(right).

Key properties:
  • Registry-driven — reads the gallery.yaml-backed shell registry. Adding an
    app = one gallery entry, either as an in-process Dash mount or a proxy mount.
  • Zero per-app edits — each app is mounted UNMODIFIED: the env var
    DASH_REQUESTS_PATHNAME_PREFIX is set, Dash reads it at construction, and we
    take the app's Flask server. Handles both entry patterns (`build_app()` and a
    module-level `app = Dash(...)`).
  • Lazy — apps are built on first view (a few hundred ms), not at startup; a
    build failure shows in the iframe, never breaks the shell.
  • Stable app keys — apps are keyed by their configured gallery names; numeric
    labels are optional display metadata for collections that want them.
  • Catalog = quality dashboard — sort/filter by id · title · tag · ★rating ·
    recency · open-feedback (the last is the Phase-2 loop's work queue).
  • Same-origin feedback — ★1–5 + comment + one-click html2canvas screenshot of
    the iframe (the thing separate ports blocked) + upload fallback. Claude posts
    back ⚙ system notes; entries carry status badges. Runtime state is persisted to
    feedback/app_feedback.sqlite; legacy JSON is import-only, and any web cache belongs under
    feedback/cache/.

Run:  python app_shell.py   →   http://127.0.0.1:8200
"""
from __future__ import annotations

import base64
import atexit
import importlib
import json
import os
import re
import shlex
import sys
import subprocess
import tempfile
import threading
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape as _esc
from pathlib import Path

from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update
from dash.dependencies import ClientsideFunction
from flask import has_request_context, request, send_from_directory
from werkzeug.middleware.dispatcher import DispatcherMiddleware  # noqa: F401 (kept for reference)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
PORT = 8200  # default; overridden by gallery.yaml shell.port just below (after the registry import)

from curiator.annotations import clean_annotations  # noqa: E402
from curiator.narrative import build_narrative, narrative_rows  # noqa: E402
from curiator.transcripts import clean_transcript_segments  # noqa: E402
import registry as REG  # gallery.yaml-backed registry
from curiator import auth, ledger  # identity/provenance + shared SQLite feedback ledger
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
# feedback/app_feedback.sqlite that ledger.py (the loop + `curiator reply`) reads/writes. The shell is
# nested under curiator/shell/, so `HERE / feedback` would be a stray, split-brain ledger. Honor
# gallery.yaml's feedback.dir (default "feedback"), resolved against the repo root.
FEEDBACK_DIR = REG.REPO_ROOT / (REG.FEEDBACK_CFG.get("dir") or "feedback")
LEDGER_CFG = {**REG.CONFIG, "repo_root": str(REG.REPO_ROOT), "gallery_path": str(REG.GALLERY_YAML)}
SHOTS = FEEDBACK_DIR / "shots"
REPLIES = FEEDBACK_DIR / "replies"
AUDIO = FEEDBACK_DIR / "audio"
PENDING_AUDIO = AUDIO / "pending"
SHOTS.mkdir(parents=True, exist_ok=True)
REPLIES.mkdir(parents=True, exist_ok=True)
BLUE, GREEN, AMBER, GREY, PURPLE = "#2980b9", "#1f9d55", "#cc7a00", "#777", "#8e44ad"
HELD, REJECTED = "#6f42c1", "#555"
OPEN_STATUSES = {"new", "working", "awaiting_approval", "held"}


def _sync_shell_config() -> None:
    """Refresh shell globals derived from gallery.yaml after registry reloads."""
    global TITLE, POLL_MS, COLLECTION_NAME, FEEDBACK_DIR, LEDGER_CFG, SHOTS, REPLIES, AUDIO, PENDING_AUDIO
    TITLE = _norm_title(REG.SHELL_CFG.get("title"))
    POLL_MS = int(REG.SHELL_CFG.get("poll_seconds", 4) * 1000)
    COLLECTION_NAME = _collection_name(REG.SHELL_CFG.get("title"))
    FEEDBACK_DIR = REG.REPO_ROOT / (REG.FEEDBACK_CFG.get("dir") or "feedback")
    LEDGER_CFG = {**REG.CONFIG, "repo_root": str(REG.REPO_ROOT), "gallery_path": str(REG.GALLERY_YAML)}
    SHOTS = FEEDBACK_DIR / "shots"
    REPLIES = FEEDBACK_DIR / "replies"
    AUDIO = FEEDBACK_DIR / "audio"
    PENDING_AUDIO = AUDIO / "pending"
    SHOTS.mkdir(parents=True, exist_ok=True)
    REPLIES.mkdir(parents=True, exist_ok=True)


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


def _trace_path(feedback_id: str | None) -> Path | None:
    if not feedback_id or not re.fullmatch(r"[A-Za-z0-9_-]+", str(feedback_id)):
        return None
    return REPLIES / f"{feedback_id}.md"


def _trace_exists(entry: dict) -> bool:
    p = _trace_path(entry.get("id"))
    return bool(p and p.exists())


def _trace_href(entry: dict) -> str:
    return f"/feedback-trace/{entry.get('id')}"


def _status_badge(entry: dict, status: str, color: str):
    style = {"fontSize": "9.5px", "color": "white", "background": color,
             "padding": "1px 6px", "borderRadius": "8px", "textDecoration": "none"}
    if _trace_exists(entry):
        return html.A(status, href=_trace_href(entry), target="_blank", title="open agent trace",
                      style={**style, "cursor": "pointer"})
    return html.Span(status, style=style)


def _status_badge_html(entry: dict, status: str, color: str) -> str:
    style = f"background:{color};color:white;font-size:9.5px;border-radius:8px;padding:1px 6px"
    if _trace_exists(entry):
        href = _esc(_trace_href(entry))
        return (f"<a href='{href}' target='_blank' title='open agent trace' "
                f"style='{style};text-decoration:none;cursor:pointer'>{_esc(status)}</a>")
    return f"<span style='{style}'>{_esc(status)}</span>"


def _entry_actor(entry: dict) -> str:
    if entry.get("kind") == "system" or entry.get("author") == "claude":
        return "Codex" if entry.get("agent") == "Codex" else str(entry.get("agent") or "Claude")
    return (entry.get("user") or {}).get("name") or "user"


def _entry_excerpt(entry: dict, limit: int = 74) -> str:
    text = " ".join((entry.get("comment") or "").split())
    if not text and entry.get("stars"):
        text = "★" * int(entry.get("stars") or 0)
    return text[:limit] + ("…" if len(text) > limit else "")


def _thread_tree(items: list[dict]) -> tuple[list[dict], dict[str, list[dict]], dict[str, int]]:
    """Build a parent→children tree from reply_to links, preserving ledger order inside each sibling set."""
    by_id = {e.get("id"): e for e in items if e.get("id")}
    children: dict[str, list[dict]] = {}
    roots: list[dict] = []
    order = {e.get("id"): i for i, e in enumerate(items) if e.get("id")}
    for e in items:
        parents = [pid for pid in (e.get("reply_to") or []) if pid in by_id]
        parent = parents[-1] if parents else None
        if parent:
            children.setdefault(parent, []).append(e)
        else:
            roots.append(e)
    return roots, children, order


def _thread_activity(entry: dict, children: dict[str, list[dict]], order: dict[str, int]) -> int:
    eid = entry.get("id")
    latest = order.get(eid, -1)
    for child in children.get(eid, []):
        latest = max(latest, _thread_activity(child, children, order))
    return latest


def _reply_button(key: str, entry: dict):
    return html.Button(
        "reply",
        id={"type": "fbreply", "key": key, "target": entry.get("id")},
        n_clicks=0,
        title="Reply to this message",
        style={"border": "none", "background": "transparent", "color": BLUE, "fontSize": "10px",
               "fontWeight": 700, "padding": "0 0 0 6px", "cursor": "pointer"},
    )


def _reply_button_html(key: str, entry: dict) -> str:
    key_js = json.dumps(key)
    id_js = json.dumps(entry.get("id"))
    onclick = (
        "event.stopPropagation();"
        "if(window.parent&&window.parent.curiatorShell){"
        f"window.parent.curiatorShell.replyTo({key_js}, {id_js});return;"
        "}"
        "if(window.parent&&window.parent.dash_clientside){"
        f"window.parent.dash_clientside.set_props('selected-app', {{data: {key_js}}});"
        f"window.parent.dash_clientside.set_props('fb-reply-to', {{data: {{key: {key_js}, id: {id_js}}}}});"
        "}"
    )
    return (f"<button onclick=\"{_esc(onclick)}\" title='Reply to this message' "
            f"style='border:none;background:transparent;color:{BLUE};font-size:10px;"
            f"font-weight:700;padding:0 0 0 6px;cursor:pointer'>reply</button>")


def _reply_context(key: str | None, target: dict | None):
    if not key or not target or target.get("key") != key:
        return None
    entry = next((e for e in load_feedback().get(key, []) if e.get("id") == target.get("id")), None)
    if not entry:
        return None
    return html.Div([
        html.Div([
            html.Span("replying to ", style={"color": GREY}),
            html.B(_entry_actor(entry), style={"color": BLUE if entry.get("author") == "claude" else "#333"}),
            html.Button("×", id="fb-reply-cancel", n_clicks=0, title="Cancel reply",
                        style={"float": "right", "border": "none", "background": "transparent",
                               "fontWeight": 800, "color": GREY, "cursor": "pointer", "fontSize": "13px"}),
        ], style={"fontSize": "11px", "marginBottom": "2px"}),
        html.Div(_entry_excerpt(entry, 110),
                 style={"fontSize": "11px", "color": "#444", "whiteSpace": "nowrap",
                        "overflow": "hidden", "textOverflow": "ellipsis"}),
    ], style={"borderLeft": f"3px solid {BLUE}", "background": "#eef5fb", "padding": "5px 7px",
              "borderRadius": "3px", "marginBottom": "6px"})


def _trace_page(feedback_id: str, text: str) -> str:
    fid = _esc(feedback_id)
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>curIAtor trace {fid}</title>
    <style>
      body {{ margin: 0; font-family: system-ui, sans-serif; color: #222; background: #f6f7f9; }}
      header {{ position: sticky; top: 0; z-index: 2; background: white; border-bottom: 1px solid #ddd;
        padding: 10px 14px; display: flex; align-items: baseline; gap: 10px; }}
      h1 {{ font-size: 14px; margin: 0; color: {PURPLE}; }}
      .meta {{ color: #777; font-size: 11px; }}
      pre {{ box-sizing: border-box; height: calc(100vh - 43px); margin: 0; overflow: auto; padding: 14px;
        background: #111820; color: #dce7ef; font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        white-space: pre-wrap; word-break: break-word; }}
    </style>
  </head>
  <body>
    <header>{_wordmark_html(17)}<h1>agent trace</h1><span class="meta">feedback {fid}</span></header>
    <pre id="trace">{_esc(text)}</pre>
    <script>
      const pre = document.getElementById('trace');
      async function refresh() {{
        const nearBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 40;
        const r = await fetch('/feedback-trace/{fid}.md', {{cache: 'no-store'}});
        if (r.ok) {{
          pre.textContent = await r.text();
          if (nearBottom) pre.scrollTop = pre.scrollHeight;
        }}
      }}
      pre.scrollTop = pre.scrollHeight;
      setInterval(refresh, 1500);
    </script>
  </body>
</html>"""


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


def _settings_html(agent: dict, gallery_path: str, saved: bool = False) -> str:
    """The /settings form — edits the live `agent:` block (provider, model, autonomy, trust)."""
    import shutil
    lbl = "display:block;font-weight:600;font-size:12px;color:#555;margin-top:11px"

    def sel(name, value, options):
        opts = "".join(f"<option value='{_esc(o)}'{' selected' if o == value else ''}>{_esc(o)}</option>"
                       for o in options)
        return f"<select name='{_esc(name)}' style='{_INPUT}'>{opts}</select>"

    model = agent.get("model")
    model = "" if model in (None, "null") else str(model)
    avail = " · ".join(f"<code>{c}</code> {'✓' if shutil.which(c) else '✗ not installed'}"
                       for c in ("claude", "codex"))
    banner = ("<div style='background:#e8f6ec;border:1px solid #b6e0c2;color:#1f7a44;padding:7px 11px;"
              "border-radius:6px;margin-bottom:12px;font-size:13px'>✓ Saved — the watcher hot-reloads "
              "it on the next poll (no restart).</div>" if saved else "")
    return (
        f"{banner}"
        f"<form method='post' action='/settings' style='max-width:430px'>"
        f"<label style='{lbl}'>Provider (adapter)</label>"
        f"{sel('adapter', agent.get('adapter', 'headless-cc'), ['headless-cc', 'codex', 'command'])}"
        f"<label style='{lbl}'>Model <span style='font-weight:400;color:#999'>(blank = provider default)</span></label>"
        f"<input name='model' value='{_esc(model)}' placeholder='e.g. opus, gpt-5-codex' style='{_INPUT}'>"
        f"<label style='{lbl}'>Autonomy</label>"
        f"{sel('autonomy', agent.get('autonomy', 'auto-small'), ['auto-small', 'propose-only'])}"
        f"<label style='{lbl}'>Claude trust <span style='font-weight:400;color:#999'>(headless-cc)</span></label>"
        f"{sel('permission_mode', agent.get('permission_mode', 'acceptEdits'), ['acceptEdits', 'bypassPermissions', 'default'])}"
        f"<label style='{lbl}'>Codex sandbox <span style='font-weight:400;color:#999'>(codex)</span></label>"
        f"{sel('sandbox', agent.get('sandbox', 'workspace-write'), ['read-only', 'workspace-write', 'danger-full-access'])}"
        f"<label style='{lbl}'>Timeout (seconds)</label>"
        f"<input name='timeout' type='number' min='30' value='{_esc(str(agent.get('timeout', 900)))}' style='{_INPUT}'>"
        f"<button type='submit' style='background:{PURPLE};color:white;border:none;padding:9px 20px;"
        f"border-radius:6px;font-weight:600;font-size:13px;cursor:pointer;margin-top:15px'>Save</button>"
        f"</form>"
        f"<p style='color:#888;font-size:11.5px;margin-top:14px'>Agent CLIs on PATH: {avail}<br>"
        f"Editing <code>{_esc(gallery_path)}</code> · comments preserved.</p>")


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
        mount = a.get("mount") or {}
        if mount.get("kind") == "proxy":
            kind = "proxy"
        elif p and p.suffix == ".py" and p.exists():
            kind = "dynamic"
        elif p and p.suffix == ".html" and p.exists():
            kind = "static"
        elif p and p.is_dir() and p.exists():
            kind = mount.get("kind", "directory")
        else:
            kind = "missing"
        recs.append({
            "key": key, "port": a.get("port"), "title": a.get("title", key),
            "tags": list(a.get("tags") or []), "color": a.get("color", "#888"),
            "file": f, "kind": kind, "mount": a.get("mount") or {},
            "root": a.get("root"), "source": a.get("source"), "smoke": a.get("smoke"),
        })
    return recs


# gallery & runner-wide feedback target (not tied to any single app)
GENERAL_KEY = "__general__"


def _general_record() -> dict:
    return {"key": GENERAL_KEY, "port": None, "title": "General — the gallery & runner",
            "tags": ["meta"], "kind": "general"}


def refresh_registry(*, reload_module: bool = True) -> int:
    """Re-read gallery.yaml so newly scaffolded apps appear in a running shell."""
    global REG, REGISTRY, BY_KEY, TAG_META, TAG_COLOR
    importlib.invalidate_caches()
    if reload_module:
        REG = importlib.reload(REG)
    _sync_shell_config()
    REGISTRY = load_registry()
    BY_KEY = {r["key"]: r for r in REGISTRY}
    TAG_META = list(getattr(REG, "TAG_META", []))
    TAG_COLOR = dict(TAG_META)
    BY_KEY[GENERAL_KEY] = _general_record()
    return len(REGISTRY)


refresh_registry(reload_module=False)
HISTORY_RANGES = {
    "1m": ("1 minute", timedelta(minutes=1)),
    "5m": ("5 minutes", timedelta(minutes=5)),
}


# ============================== feedback =====================================
def load_feedback() -> dict:
    return ledger.load(LEDGER_CFG)


def _current_user():
    """The verified identity for this request (default_user / proxy header / OIDC session), or None."""
    try:
        return auth.current_user(REG.AUTH_CFG)
    except Exception:                                    # no request context, etc. — provenance is best-effort
        return None


def _annotation_label(mark: dict, idx: int) -> str:
    tool = mark.get("tool")
    if tool == "pin":
        return str(mark.get("n") or idx + 1)
    if tool == "box":
        return f"□{idx + 1}"
    if tool == "arrow":
        return f"↗{idx + 1}"
    if tool == "redact":
        return f"█{idx + 1}"
    return str(idx + 1)


def _annotation_target_text(mark: dict) -> str:
    if mark.get("tool") == "redact":
        return "target omitted"
    target = mark.get("target") or {}
    if not isinstance(target, dict):
        return ""
    if target.get("selector"):
        return str(target["selector"])
    if target.get("data_testid"):
        return f'[data-testid="{target["data_testid"]}"]'
    if target.get("id"):
        return f'#{target["id"]}'
    if target.get("role"):
        return f'[role="{target["role"]}"]'
    if target.get("tag"):
        return str(target["tag"])
    return ""


def _annotation_marks(entry: dict) -> list[dict]:
    marks = entry.get("annotations")
    return [mark for mark in marks if isinstance(mark, dict)] if isinstance(marks, list) else []


def _annotation_summary_html(entry: dict) -> str:
    marks = _annotation_marks(entry)
    if not marks:
        return ""
    rows = []
    for idx, mark in enumerate(marks):
        label = _annotation_label(mark, idx)
        note = mark.get("note")
        target = _annotation_target_text(mark)
        text = _esc(str(mark.get("tool") or "mark"))
        if note:
            text += f" — {_esc(str(note))}"
        target_html = (f"<code style='display:block;margin-top:2px;color:#555;background:#f7f7f7;"
                       f"border-radius:3px;padding:2px 4px;white-space:normal'>{_esc(target)}</code>"
                       if target else "")
        rows.append(
            "<div style='display:grid;grid-template-columns:28px minmax(0,1fr);gap:6px;"
            "align-items:start;margin-top:4px'>"
            f"<span style='display:inline-flex;align-items:center;justify-content:center;min-height:20px;"
            f"border:1px solid #ddd;border-radius:4px;background:#f7f7f7;font-weight:700'>{_esc(label)}</span>"
            f"<span style='min-width:0;overflow-wrap:anywhere'>{text}{target_html}</span></div>"
        )
    return ("<div style='margin-top:6px;padding:6px 7px;border:1px solid #e5e5e5;border-radius:4px;"
            "background:#fff;color:#444;font-size:11px'>"
            "<div style='font-weight:700;color:#555'>Annotations</div>"
            f"{''.join(rows)}</div>")


def _annotation_summary_dash(entry: dict):
    marks = _annotation_marks(entry)
    if not marks:
        return None
    rows = []
    for idx, mark in enumerate(marks):
        target = _annotation_target_text(mark)
        body = [html.Span(str(mark.get("tool") or "mark"))]
        if mark.get("note"):
            body.append(html.Span(f" — {mark['note']}"))
        if target:
            body.append(html.Code(target, style={"display": "block", "marginTop": "2px", "color": "#555",
                                                "background": "#f7f7f7", "borderRadius": "3px",
                                                "padding": "2px 4px", "whiteSpace": "normal"}))
        rows.append(html.Div([
            html.Span(_annotation_label(mark, idx),
                      style={"display": "inline-flex", "alignItems": "center", "justifyContent": "center",
                             "minHeight": "20px", "border": "1px solid #ddd", "borderRadius": "4px",
                             "background": "#f7f7f7", "fontWeight": 700}),
            html.Span(body, style={"minWidth": 0, "overflowWrap": "anywhere"}),
        ], style={"display": "grid", "gridTemplateColumns": "28px minmax(0, 1fr)", "alignItems": "start",
                  "gap": "6px"}))
    return html.Div([html.Div("Annotations", style={"fontWeight": 700, "color": "#555"})] + rows,
                    style={"display": "grid", "gap": "4px", "marginTop": "6px", "padding": "6px 7px",
                           "border": "1px solid #e5e5e5", "borderRadius": "4px", "background": "#fff",
                           "color": "#444", "fontSize": "11px"})


def _ms_label(value) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return ""
    if n < 1000:
        return f"{round(n)}ms"
    seconds = n / 1000
    if seconds < 60:
        return f"{seconds:.1f}s" if seconds < 10 else f"{round(seconds)}s"
    return f"{int(seconds // 60)}:{round(seconds % 60):02d}"


def _time_range_label(start, end) -> str:
    a = _ms_label(start)
    b = _ms_label(end)
    if not a and not b:
        return ""
    if not b or a == b:
        return a
    if not a:
        return b
    return f"{a}-{b}"


def _voice_segments(entry: dict) -> list[dict]:
    raw = entry.get("transcript_segments")
    if not isinstance(raw, list):
        return []
    segments = []
    for idx, seg in enumerate(raw[:200], start=1):
        if not isinstance(seg, dict):
            continue
        text = " ".join(str(seg.get("text") or "").split())
        if not text:
            continue
        segments.append({
            "kind": "segment",
            "key": idx,
            "time": _time_range_label(seg.get("start_ms"), seg.get("end_ms")),
            "text": text,
            "muted": False,
        })
    return segments


def _voice_summary_rows(entry: dict):
    segments = _voice_segments(entry)
    narrative = narrative_rows(entry)
    if narrative:
        rows = []
        for row in narrative[:8]:
            target = _annotation_target_text({"tool": row.get("tool"), "target": row.get("target")})
            note = f" — {row['note']}" if row.get("note") else ""
            rows.append({
                "kind": "narrative",
                "key": row.get("mark_index"),
                "time": _time_range_label(row.get("start_ms"), row.get("end_ms")),
                "lead": f"{row.get('label') or 'mark'} · {row.get('tool') or 'mark'}{note}",
                "target": target,
                "text": row.get("text") or "no overlapping transcript",
                "muted": not bool(row.get("text")),
            })
        return "Narrated feedback", rows, max(0, len(narrative) - len(rows))
    if segments:
        rows = segments[:8]
        return "Voice transcript", rows, max(0, len(segments) - len(rows))
    return None


def _voice_summary_html(entry: dict) -> str:
    summary = _voice_summary_rows(entry)
    audio = entry.get("audio")
    if not summary and not audio:
        return ""
    title, rows, extra = summary or ("Retained audio", [], 0)
    out = [
        "<div style='margin-top:6px;padding:6px 7px;border:1px solid #e0e8ef;border-radius:4px;"
        "background:#fbfdff;color:#3c4a55;font-size:11px'>",
        f"<div style='font-weight:700;color:#555;margin-bottom:4px'>{_esc(title)}</div>",
    ]
    if audio:
        out.append(f"<audio controls src='/feedback-audio/{_esc(Path(audio).name)}' "
                   "style='display:block;width:100%;margin-bottom:5px'></audio>")
    for row in rows:
        text_style = "color:#777;font-style:italic" if row.get("muted") else "color:#243746"
        target = row.get("target")
        target_html = (f"<code style='display:block;margin-top:2px;color:#555;background:#f7f7f7;"
                       f"border-radius:3px;padding:2px 4px;white-space:normal'>{_esc(target)}</code>"
                       if target else "")
        lead = f"<b>{_esc(row['lead'])}</b>" if row.get("lead") else ""
        copy = (f"{lead}{target_html}<span style='display:block;margin-top:1px;{text_style}'>"
                f"{_esc(row.get('text') or '')}</span>")
        out.append(
            "<div style='display:grid;grid-template-columns:54px minmax(0,1fr);gap:6px;"
            "align-items:start;margin-top:4px'>"
            f"<span style='color:#597083;font-weight:700;white-space:nowrap'>{_esc(row.get('time') or '')}</span>"
            f"<span style='min-width:0;overflow-wrap:anywhere'>{copy}</span></div>"
        )
    if extra:
        out.append(f"<div style='color:#777;font-size:10px;margin-top:4px'>+{extra} more</div>")
    out.append("</div>")
    return "".join(out)


def _voice_summary_dash(entry: dict):
    summary = _voice_summary_rows(entry)
    audio = entry.get("audio")
    if not summary and not audio:
        return None
    title, rows, extra = summary or ("Retained audio", [], 0)
    children = [html.Div(title, style={"fontWeight": 700, "color": "#555"})]
    if audio:
        children.append(html.Audio(src=f"/feedback-audio/{Path(audio).name}", controls=True,
                                   style={"display": "block", "width": "100%", "marginBottom": "5px"}))
    for row in rows:
        body = []
        if row.get("lead"):
            body.append(html.B(row["lead"]))
        if row.get("target"):
            body.append(html.Code(row["target"], style={"display": "block", "marginTop": "2px", "color": "#555",
                                                       "background": "#f7f7f7", "borderRadius": "3px",
                                                       "padding": "2px 4px", "whiteSpace": "normal"}))
        body.append(html.Span(row.get("text") or "", style={"display": "block", "marginTop": "1px",
                                                            "color": "#777" if row.get("muted") else "#243746",
                                                            "fontStyle": "italic" if row.get("muted") else "normal"}))
        children.append(html.Div([
            html.Span(row.get("time") or "", style={"color": "#597083", "fontWeight": 700,
                                                    "whiteSpace": "nowrap"}),
            html.Span(body, style={"minWidth": 0, "overflowWrap": "anywhere"}),
        ], style={"display": "grid", "gridTemplateColumns": "54px minmax(0, 1fr)", "alignItems": "start",
                  "gap": "6px"}))
    if extra:
        children.append(html.Div(f"+{extra} more", style={"color": "#777", "fontSize": "10px"}))
    return html.Div(children, style={"display": "grid", "gap": "4px", "marginTop": "6px",
                                    "padding": "6px 7px", "border": "1px solid #e0e8ef",
                                    "borderRadius": "4px", "background": "#fbfdff",
                                    "color": "#3c4a55", "fontSize": "11px"})


_AUDIO_SUFFIXES = {".webm", ".ogg", ".mp3", ".m4a", ".mp4", ".wav", ".flac"}


def _pending_audio_path(audio_ref) -> Path | None:
    if not isinstance(audio_ref, str) or "\\" in audio_ref:
        return None
    ref = Path(audio_ref)
    if ref.is_absolute() or len(ref.parts) != 3 or ref.parts[0] != "audio" or ref.parts[1] != "pending":
        return None
    if ref.suffix.lower() not in _AUDIO_SUFFIXES:
        return None
    candidate = (FEEDBACK_DIR / ref).resolve()
    try:
        if candidate.parent != PENDING_AUDIO.resolve():
            return None
    except FileNotFoundError:
        return None
    return candidate


def _claim_audio_ref(key: str, eid: str, audio_ref) -> str | None:
    pending = _pending_audio_path(audio_ref)
    if not pending or not pending.exists() or not pending.is_file():
        return None
    AUDIO.mkdir(parents=True, exist_ok=True)
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(key or "feedback")).strip("._") or "feedback"
    fname = f"{safe_key}_{eid}{pending.suffix.lower()}"
    dest = AUDIO / fname
    os.replace(pending, dest)
    return f"audio/{fname}"


def save_entry(
    key,
    stars,
    comment,
    shot_dataurl,
    user=None,
    reply_to=None,
    status: str = "new",
    annotations=None,
    annotation_targets: bool = True,
    transcript_segments=None,
    audio_ref=None,
):
    eid = uuid.uuid4().hex[:8]
    screenshot = None
    if shot_dataurl and shot_dataurl.startswith("data:image"):
        fname = f"{key}_{eid}.png"
        (SHOTS / fname).write_bytes(base64.b64decode(shot_dataurl.split(",", 1)[1]))
        screenshot = f"shots/{fname}"
    extra = {"proposed_plan": None, "reply_to": reply_to or []}
    if status != "new":
        extra["status"] = status
    cleaned_annotations = clean_annotations(annotations, allow_targets=annotation_targets)
    if cleaned_annotations:
        extra["annotations"] = cleaned_annotations
    cleaned_segments = clean_transcript_segments(transcript_segments)
    if cleaned_segments:
        extra["transcript_segments"] = cleaned_segments
    narrative = build_narrative(cleaned_annotations, cleaned_segments)
    if narrative:
        extra["narrative"] = narrative
    audio = _claim_audio_ref(key, eid, audio_ref)
    if audio:
        extra["audio"] = audio
    ledger.save_entry(
        LEDGER_CFG,
        key,
        entry_id=eid,
        stars=stars,
        comment=(comment or "").strip(),
        screenshot=screenshot,
        ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        user=auth.stamp(user if user is not None else _current_user()),
        extra=extra,
    )
    return next(e for e in load_feedback().get(key, []) if e.get("id") == eid)


def add_system_note(key, text, reply_to=None, actions=None):
    """`actions` (optional) = list of approval-macro buttons, each a [label, value] pair (or a bare
    string used for both). When set — or when omitted but the note text contains A/B/C options — the
    feedback UI shows quick-approval buttons that post `value` as a user reply (so the loop fires)."""
    nid = ledger.add_system_note(LEDGER_CFG, key, text.strip(), reply_to=reply_to, actions=actions)
    return next(e for e in load_feedback().get(key, []) if e.get("id") == nid)


def set_status(key, ids, status):
    ledger.set_status(LEDGER_CFG, key, ids, status)


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


def record_action(key, value, reply_to=None, user=None, status: str = "new"):
    """A quick-approval button was clicked → post it as a normal user reply.

    Normally it is status:new so the watcher processes it like a typed approval; logged-out
    `allow_anonymous` users are forced to status:held.
    """
    return save_entry(key, None, str(value), None, user=user, reply_to=[reply_to] if reply_to else None, status=status)


def _client_key() -> str:
    return (request.remote_addr or "?") if has_request_context() else "cli"


def _feedback_user_and_status(rate_limit_key: str | None = None) -> tuple[dict | None, str, str | None, int]:
    u = _current_user()
    if auth.login_required(REG.AUTH_CFG) and not u:
        if not auth.allow_anonymous_feedback(REG.AUTH_CFG):
            return None, "new", "Sign in to leave feedback.", 401
        key = rate_limit_key or _client_key()
        blocked, retry = auth.anonymous_feedback_rate_limit_status(REG.AUTH_CFG, key)
        if blocked:
            return None, "new", f"Too many anonymous submissions. Try again in {retry}s.", 429
        auth.record_anonymous_feedback(REG.AUTH_CFG, key)
        return auth.anonymous_user(), "held", None, 0
    return u, "new", None, 0


def app_metrics(key):
    """(avg_stars or None, n_open, n_total) from the feedback ledger."""
    items = load_feedback().get(key, [])
    stars = [e["stars"] for e in items if e.get("stars")]
    avg = round(sum(stars) / len(stars), 1) if stars else None
    n_open = sum(1 for e in items if e.get("kind") != "system" and e.get("status") in OPEN_STATUSES)
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


def _parse_history_ts(iso):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _history_range_nav(active):
    def link(label, href, selected=False):
        bg = PURPLE if selected else "#fff"
        fg = "#fff" if selected else "#555"
        border = PURPLE if selected else "#ddd"
        return (f"<a href='{href}' style='display:inline-block;text-decoration:none;font-size:11px;"
                f"font-weight:700;color:{fg};background:{bg};border:1px solid {border};"
                f"border-radius:999px;padding:3px 9px;margin-left:5px'>{label}</a>")

    return ("<div style='margin:2px 0 12px;color:#777;font-size:11px'>range "
            f"{link('All', '/general', active is None)}"
            f"{link(HISTORY_RANGES['1m'][0], '/general?range=1m', active == '1m')}"
            f"{link(HISTORY_RANGES['5m'][0], '/general?range=5m', active == '5m')}</div>")


def render_history(range_key=None):
    """Server-rendered HTML: every feedback thread across the library, newest app
    first (General pinned), entries chronological with user/⚙Claude styling."""
    range_key = range_key if range_key in HISTORY_RANGES else None
    cutoff = None
    if range_key:
        cutoff = datetime.now(timezone.utc) - HISTORY_RANGES[range_key][1]

    def in_range(e):
        if cutoff is None:
            return True
        dt = _parse_history_ts(e.get("ts"))
        return bool(dt and dt >= cutoff)

    data = load_feedback()
    visible = {k: [e for e in items if in_range(e)] for k, items in data.items()}
    visible.setdefault(GENERAL_KEY, [])
    activity_keys = [k for k in visible if k != GENERAL_KEY and visible.get(k)]
    activity_keys.sort(key=lambda k: max((_parse_history_ts(e.get("ts")) or datetime.min.replace(tzinfo=timezone.utc)
                                          for e in visible[k]),
                                         default=datetime.min.replace(tzinfo=timezone.utc)),
                       reverse=True)
    keys = [GENERAL_KEY] + activity_keys
    n_threads = sum(1 for k in keys if visible.get(k))
    n_open = sum(1 for k in keys for e in visible.get(k, [])
                 if e.get("kind") != "system" and e.get("status") in OPEN_STATUSES)
    out = [
        "<div style='font-family:system-ui,sans-serif;padding:1.6em 2em;color:#333;max-width:920px'>",
        # curIAtor logo + this collection's name (the custom repo name)
        f"<div style='display:flex;align-items:baseline;gap:11px;margin:0 0 10px'>{_wordmark_html(22)}"
        f"<span style='color:#ccc;font-size:16px'>/</span>"
        f"<span style='font-weight:700;font-size:16px;color:#444'>{_esc(COLLECTION_NAME)}</span></div>",
        f"<h2 style='color:#8e44ad;margin:0 0 2px;font-size:18px'>{_esc(COLLECTION_NAME)} collection home</h2>",
        "<p style='color:#555;margin:0 0 10px;font-size:13px;max-width:720px'>Use the panel on the right "
        "for <b>gallery &amp; runner-wide</b> notes. General feedback stays pinned here; app-specific "
        "threads roll up below as recent collection activity.</p>",
        "<div style='display:flex;gap:8px;flex-wrap:wrap;margin:0 0 16px'>"
        f"<span style='font-size:11px;color:#555;background:#f6f1fb;border:1px solid #e3d8ef;"
        f"border-radius:999px;padding:3px 9px'>{len(REGISTRY)} apps</span>"
        f"<span style='font-size:11px;color:#555;background:#f7f7f7;border:1px solid #e5e5e5;"
        f"border-radius:999px;padding:3px 9px'>{n_threads} active threads</span>"
        f"<span style='font-size:11px;color:#555;background:#fff5f5;border:1px solid #f0d4d4;"
        f"border-radius:999px;padding:3px 9px'>{n_open} open</span></div>",
        _history_range_nav(range_key),
    ]
    for idx, key in enumerate(keys):
        if idx == 1:
            out.append("<div style='margin:18px 0 6px;border-top:1px solid #eee;padding-top:13px'>"
                       "<h3 style='font-size:14px;margin:0 0 3px;color:#333'>Latest activity</h3>"
                       "<p style='color:#777;font-size:12px;margin:0 0 8px'>Recent app-specific "
                       "feedback across the collection.</p></div>")
        rec = BY_KEY.get(key, {})
        if key == GENERAL_KEY:
            label = "◆ General feedback"
        else:
            label = f"<span style='font-family:monospace;background:{rec.get('color', '#888')};color:white;" \
                    f"padding:1px 5px;border-radius:4px;font-size:11px'>{rec.get('port', '—')}</span> " \
                    f"{_esc(rec.get('title', key))}"
        items = visible.get(key, [])
        opn = sum(1 for e in items if e.get("kind") != "system" and e.get("status") in OPEN_STATUSES)
        ob = f" <span style='background:#c0392b;color:white;font-size:10px;border-radius:8px;" \
             f"padding:0 6px'>{opn} open</span>" if opn else ""
        if key == GENERAL_KEY:                       # the General thread itself doesn't navigate
            out.append(f"<div style='margin:0 0 6px;border-top:1px solid #eee;padding-top:12px'>"
                       f"<span style='font-weight:700;font-size:14px;color:{PURPLE}'>{label}</span>{ob}"
                       "<div style='color:#777;font-size:12px;margin-top:2px'>Collection-wide notes, "
                       "runner feedback, and coordination for the overlay itself.</div></div>")
        else:                                        # app threads: click → select that app (same-origin)
            key_js = json.dumps(key)
            click = (f"if(window.parent&&window.parent.curiatorShell){{window.parent.curiatorShell.selectApp({key_js});}}"
                     f"else if(window.parent&&window.parent.dash_clientside){{"
                     f"window.parent.dash_clientside.set_props('selected-app', {{data: {key_js}}});}}")
            out.append(f"<div onclick=\"{_esc(click)}\" title='open this app' "
                       f"style='margin:14px 0 4px;border-top:1px solid #eee;padding-top:10px;cursor:pointer'>"
                       f"<span style='font-weight:700;font-size:13px'>{label}</span>{ob} "
                       f"<span style='color:#2980b9;font-size:10.5px'>↗ open</span></div>")
        if key == GENERAL_KEY and not items:
            out.append("<div style='background:#fafafa;border-left:2px solid #ddd;padding:7px 10px;"
                       "font-size:12.5px;color:#777;margin:4px 0 8px'>No General feedback yet. "
                       "Use the feedback panel on the right for collection-wide notes.</div>")
        tb = thread_buttons(data.get(key, []))
        roots, children, order = _thread_tree(items)

        def render_entry(e: dict, depth: int = 0):
            ts = e.get("ts") or ""
            tsh = (f"<span class='ts' data-ts='{_esc(ts)}' style='color:#999;font-size:10px'>"
                   f"{_esc(ts)}</span>") if ts else ""
            indent = min(depth * 18, 72)
            if e.get("kind") == "system" or e.get("author") == "claude":
                btns = ""
                if tb and e["id"] == tb[0]:
                    chips = "".join(
                        f"<button onclick=\"fetch('/fb-action?key={_esc(key)}&amp;value={_esc(val)}"
                        f"&amp;reply_to={_esc(tb[0])}',"
                        f"{{method:'POST'}}).then(function(){{location.reload()}})\" "
                        f"style='font-size:11px;font-weight:700;color:white;background:#2980b9;border:none;"
                        f"border-radius:6px;padding:3px 11px;margin:0 5px 0 0;cursor:pointer'>{_esc(lbl)}</button>"
                        for lbl, val in tb[1])
                    btns = (f"<div style='margin-top:6px'>{chips}"
                            f"<span style='color:#999;font-size:10px;margin-left:4px'>"
                            f"optional — or type a reply</span></div>")
                out.append(f"<div style='margin:4px 0 4px {22 + indent}px;border-left:3px solid #2980b9;"
                           f"background:#eef5fb;padding:5px 9px;border-radius:3px'>"
                           f"<b style='color:#2980b9'>⚙ {_esc(e.get('agent') or 'Claude')}</b> {tsh}"
                           f"{_reply_button_html(key, e)}"
                           f"<div style='font-size:12.5px;color:#1a3a5a;white-space:pre-wrap;margin-top:2px'>"
                           f"{_esc(e.get('comment', ''))}</div>{btns}</div>")
            else:
                st = e.get("status", "new")
                stc = {"new": "#cc7a00", "working": "#8e44ad", "done": "#1f9d55",
                       "awaiting_approval": "#2980b9", "held": HELD,
                       "rejected": REJECTED}.get(st, "#777")
                stars = ("★" * (e.get("stars") or 0)) if e.get("stars") else ""
                shot = (f"<img src='/feedback-shot/{Path(e['screenshot']).name}' "
                        f"style='display:block;max-width:320px;border:1px solid #ddd;"
                        f"border-radius:4px;margin-top:4px'>"
                        if e.get("screenshot") else "")
                annotations = _annotation_summary_html(e)
                voice = _voice_summary_html(e)
                who = (e.get("user") or {}).get("name")
                whoh = (f" <span style='color:#8e44ad;font-size:10px;font-weight:600'>· {_esc(who)}</span>"
                        if who else "")
                out.append(f"<div style='margin:4px 0 4px {indent}px;border-left:2px solid {stc};padding:5px 9px;"
                           f"background:#fafafa;border-radius:3px'>"
                           f"<span style='color:#cc7a00'>{stars}</span> "
                           f"{_status_badge_html(e, st, stc)} {tsh}{whoh}"
                           f"{_reply_button_html(key, e)}"
                           f"<div style='font-size:12.5px;color:#333;white-space:pre-wrap;margin-top:2px'>"
                           f"{_esc(e.get('comment', ''))}</div>{shot}{annotations}{voice}</div>")
            for child in children.get(e.get("id"), []):
                render_entry(child, depth + 1)

        roots = sorted(roots, key=lambda e: _thread_activity(e, children, order), reverse=True)
        for root in roots:
            render_entry(root, 0)
    out.append("</div>")
    out.append("<script src='/assets/localtime.js'></script>")   # render .ts in the viewer's local tz
    return "".join(out)


def feedback_list(key):
    items = load_feedback().get(key, [])
    if not items:
        return html.Div("No feedback yet.", style={"color": GREY, "fontSize": "12px"})
    tb = thread_buttons(items)
    roots, children, order = _thread_tree(items)

    def render_entry(e: dict, depth: int = 0):
        indent = min(depth * 14, 56)
        if e.get("kind") == "system" or e.get("author") == "claude":
            kids = [html.Div([html.Span(f"⚙ {e.get('agent') or 'Claude'}",
                                        style={"fontWeight": 700, "color": BLUE}),
                              html.Span(["  update · ", _ts_span(e.get("ts"))],
                                        style={"color": GREY, "fontSize": "10px"}),
                              _reply_button(key, e)]),
                    html.Div(e.get("comment", ""), style={"fontSize": "12px", "color": "#1a3a5a",
                             "marginTop": "2px", "whiteSpace": "pre-wrap"})]
            if tb and e["id"] == tb[0]:
                kids.append(html.Div(
                    [html.Button(lbl, id={"type": "fbact", "key": key, "value": val, "reply_to": tb[0]}, n_clicks=0,
                                 style={"fontSize": "11px", "fontWeight": 700, "color": "white",
                                        "background": BLUE, "border": "none", "borderRadius": "6px",
                                        "padding": "3px 11px", "marginRight": "5px", "cursor": "pointer"})
                     for lbl, val in tb[1]]
                    + [html.Span("optional — or type a reply", style={"color": GREY, "fontSize": "10px"})],
                    style={"marginTop": "6px"}))
            row = html.Div(kids,
                style={"borderLeft": f"3px solid {BLUE}", "padding": "5px 8px", "marginBottom": "6px",
                       "marginLeft": f"{indent}px", "background": "#eef5fb", "borderRadius": "3px"})
        else:
            st = e.get("status", "new")
            st_col = {"new": AMBER, "working": PURPLE, "done": GREEN, "awaiting_approval": BLUE,
                      "held": HELD, "rejected": REJECTED}.get(st, GREY)
            stars = ("★" * (e.get("stars") or 0) + "✩" * (5 - (e.get("stars") or 0))) if e.get("stars") else ""
            head = [html.Span(stars, style={"color": AMBER, "fontSize": "13px", "marginRight": "6px"}),
                    _status_badge(e, st, st_col),
                    html.Span(["  ", _ts_span(e.get("ts"))], style={"color": GREY, "fontSize": "10px"}),
                    _reply_button(key, e)]
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
            annotation_summary = _annotation_summary_dash(e)
            if annotation_summary:
                kids.append(annotation_summary)
            voice_summary = _voice_summary_dash(e)
            if voice_summary:
                kids.append(voice_summary)
            row = html.Div(kids, style={"borderLeft": f"2px solid {st_col}", "padding": "4px 8px",
                                        "marginBottom": "6px", "marginLeft": f"{indent}px",
                                        "background": "#fafafa", "opacity": 0.6 if st == "done" else 1.0})
        return html.Div([row] + [render_entry(child, depth + 1) for child in children.get(e.get("id"), [])])

    roots = sorted(roots, key=lambda e: _thread_activity(e, children, order), reverse=True)
    rows = [render_entry(root, 0) for root in roots]
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
_PROXY_PROCS: dict[str, subprocess.Popen] = {}
_PROXY_LOGS: dict[str, dict[str, str]] = {}
_HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
                "te", "trailers", "transfer-encoding", "upgrade"}


def _discard_proxy_logs(key: str) -> None:
    info = _PROXY_LOGS.pop(key, None) or {}
    for field in ("stdout", "stderr"):
        path = info.get(field)
        if not path:
            continue
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass


def _cleanup_proxies():
    for proc in list(_PROXY_PROCS.values()):
        if proc.poll() is None:
            proc.terminate()
    for key in list(_PROXY_LOGS):
        _discard_proxy_logs(key)


atexit.register(_cleanup_proxies)


def resolve_server(key):
    """Build a sub-app's WSGI server, UNMODIFIED, with its pathname prefix.
    Handles build_app() and module-level `app`. Returns server or None."""
    rec = BY_KEY.get(key) or {}
    mount_cfg = rec.get("mount") or {}
    module = mount_cfg.get("module") or key
    os.environ["DASH_REQUESTS_PATHNAME_PREFIX"] = f"/app/{key}/"
    try:
        mod = importlib.import_module(module)
        if hasattr(mod, "build_app"):
            return mod.build_app().server
        if hasattr(mod, "app") and hasattr(mod.app, "server"):
            return mod.app.server
        return None
    finally:
        os.environ.pop("DASH_REQUESTS_PATHNAME_PREFIX", None)


def _ensure_proxy(key: str, rec: dict) -> tuple[bool, str | None]:
    """Start a proxy app process if needed. Returns (ok, error_message)."""
    mount_cfg = rec.get("mount") or {}
    port = mount_cfg.get("port") or rec.get("port")
    cmd = mount_cfg.get("cmd")
    if not (port and cmd):
        return False, "proxy mount needs `cmd` and `port`"
    proc = _PROXY_PROCS.get(key)
    if proc and proc.poll() is None:
        return True, None
    cwd = mount_cfg.get("cwd") or rec.get("root") or str(REG.COLLECTION_ROOT)
    env = {**os.environ, "PORT": str(port), "CURIATOR_APP": key}
    _discard_proxy_logs(key)
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", key)
    stdout = Path(tempfile.gettempdir()) / f"curiator-proxy-{safe_key}.stdout.log"
    stderr = Path(tempfile.gettempdir()) / f"curiator-proxy-{safe_key}.stderr.log"
    _PROXY_LOGS[key] = {
        "stdout": str(stdout),
        "stderr": str(stderr),
        "cmd": str(cmd),
        "cwd": str(cwd),
        "port": str(port),
    }
    try:
        with stdout.open("wb") as out, stderr.open("wb") as err:
            _PROXY_PROCS[key] = subprocess.Popen(shlex.split(cmd), cwd=cwd, env=env, stdout=out, stderr=err)
    except OSError as exc:
        return False, str(exc)
    return True, None


def _proxy_log_tail(path: str | None, limit: int = 4000) -> str:
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:].strip()


def _proxy_diagnostics_html(key: str, rec: dict, *, message: str, url: str | None = None) -> str:
    mount_cfg = rec.get("mount") or {}
    port = mount_cfg.get("port") or rec.get("port")
    cmd = mount_cfg.get("cmd") or ""
    cwd = mount_cfg.get("cwd") or rec.get("root") or str(REG.COLLECTION_ROOT)
    proc = _PROXY_PROCS.get(key)
    if proc is None:
        state = "not started"
    else:
        code = proc.poll()
        state = f"running pid {proc.pid}" if code is None else f"exited with code {code}"
    info = _PROXY_LOGS.get(key) or {}
    stderr = _proxy_log_tail(info.get("stderr"))
    stdout = _proxy_log_tail(info.get("stdout"))

    def row(label: str, value: str | int | None) -> str:
        return ("<tr><th style='text-align:left;color:#777;padding:2px 10px 2px 0'>"
                f"{_esc(label)}</th><td><code>{_esc(str(value or ''))}</code></td></tr>")

    logs = ""
    if stderr:
        logs += ("<h4 style='margin:14px 0 4px'>stderr</h4>"
                 f"<pre style='white-space:pre-wrap;background:#fff;border:1px solid #ddd;"
                 f"border-radius:4px;padding:8px;max-width:860px'>{_esc(stderr)}</pre>")
    if stdout:
        logs += ("<h4 style='margin:14px 0 4px'>stdout</h4>"
                 f"<pre style='white-space:pre-wrap;background:#fff;border:1px solid #ddd;"
                 f"border-radius:4px;padding:8px;max-width:860px'>{_esc(stdout)}</pre>")
    if not logs:
        logs = "<p style='color:#777;font-size:13px'>No proxy stdout/stderr has been captured yet.</p>"

    return (
        "<div style='font-family:system-ui,sans-serif;padding:2em;color:#333'>"
        f"<h3 style='margin:0 0 8px'><b>{_esc(key)}</b> proxy is not reachable</h3>"
        f"<p style='color:#555;margin:0 0 12px'>{_esc(message)}</p>"
        "<table style='font-size:13px;border-collapse:collapse'>"
        f"{row('command', cmd)}"
        f"{row('cwd', cwd)}"
        f"{row('port', port)}"
        f"{row('target', url or '')}"
        f"{row('process', state)}"
        "</table>"
        f"{logs}"
        "<p style='color:#777;font-size:12px;max-width:860px'>"
        "Check that the scaffold dependencies are installed, the command can bind the configured port, "
        "and the app honors its curIAtor base path when served under <code>/app/&lt;name&gt;/</code>."
        "</p></div>"
    )


def _is_websocket_upgrade(environ) -> bool:
    upgrade = (environ.get("HTTP_UPGRADE") or "").lower()
    connection = (environ.get("HTTP_CONNECTION") or "").lower()
    return upgrade == "websocket" or ("upgrade" in connection and "websocket" in upgrade)


def _proxy_backend_path(key: str, rest: str, mount_cfg: dict) -> str:
    path = rest or "/"
    if not path.startswith("/"):
        path = "/" + path
    if mount_cfg.get("preserve_prefix"):
        return f"/app/{key}/" if path == "/" else f"/app/{key}{path}"
    return path


def _proxy_call(key: str, rec: dict, rest: str, environ, start_response):
    ok, err = _ensure_proxy(key, rec)
    if not ok:
        start_response("502 Bad Gateway", [("Content-Type", "text/html; charset=utf-8")])
        return [_proxy_diagnostics_html(key, rec, message=f"proxy could not start: {err}").encode()]
    mount_cfg = rec.get("mount") or {}
    port = mount_cfg.get("port") or rec.get("port")
    path = _proxy_backend_path(key, rest, mount_cfg)
    qs = environ.get("QUERY_STRING") or ""
    url = f"http://127.0.0.1:{port}{path}" + (f"?{qs}" if qs else "")
    if _is_websocket_upgrade(environ):
        start_response("501 Not Implemented", [("Content-Type", "text/html; charset=utf-8")])
        message = ("WebSocket/HMR upgrade requests are not supported by curIAtor's lightweight built-in "
                   "proxy; use a production reverse proxy for live HMR, or use the scaffold preview/build "
                   "commands for this mount.")
        return [_proxy_diagnostics_html(key, rec, message=message, url=url).encode()]
    method = environ.get("REQUEST_METHOD", "GET")
    length = int(environ.get("CONTENT_LENGTH") or 0)
    body = environ["wsgi.input"].read(length) if length else None
    headers = {}
    for k, v in environ.items():
        if not k.startswith("HTTP_"):
            continue
        h = k[5:].replace("_", "-").title()
        if h.lower() not in _HOP_HEADERS:
            headers[h] = v
    if environ.get("CONTENT_TYPE"):
        headers["Content-Type"] = environ["CONTENT_TYPE"]
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    last_exc = None
    for _ in range(20):
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            break
        except urllib.error.HTTPError as exc:
            resp = exc
            break
        except OSError as exc:
            last_exc = exc
            time.sleep(0.1)
    else:
        start_response("502 Bad Gateway", [("Content-Type", "text/html; charset=utf-8")])
        message = f"proxy backend did not respond: {last_exc or 'no response'}"
        return [_proxy_diagnostics_html(key, rec, message=message, url=url).encode()]
    status = f"{resp.status} {getattr(resp, 'reason', 'OK')}"
    out_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in _HOP_HEADERS]
    start_response(status, out_headers)
    return [resp.read()]


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
                rec = BY_KEY.get(key) or {}
                mount_cfg = rec.get("mount") or {}
                mount = self.prefix + key
                rest = p[len(mount):] or "/"
                if mount_cfg.get("kind") == "proxy":
                    return _proxy_call(key, rec, rest, environ, start_response)
                app = self._get(key)
                if app is None:
                    start_response("200 OK", [("Content-Type", "text/html")])
                    return [f"<div style='font-family:sans-serif;padding:2em;color:#555'>"
                            f"<b>{key}</b> could not be mounted (no build_app / module app, or a build "
                            f"error). It still runs standalone on its own port.</div>".encode()]
                environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + mount
                environ["PATH_INFO"] = p[len(mount):]
                return app(environ, start_response)
        return self.root(environ, start_response)


# The live dispatcher of a running shell. `invalidate_app` (reached via the /reload/<key> route, which
# `curiator reply --status done` pokes after the agent edits an app) drops ONE app's cached module +
# built server, so the next view rebuilds from the edited source — the M2 "shell-cache" fix: an edit
# goes live without restarting the whole shell.
_DISPATCHER = None
APP_REVISIONS: dict[str, int] = {}


def invalidate_app(key: str) -> bool:
    """Forget a mounted app's cached build AND its imported Python module, so the next /app/<key>/ hit
    re-imports the edited source and rebuilds fresh. Returns True if the module had been imported."""
    importlib.invalidate_caches()
    rec = BY_KEY.get(key) or {}
    module = (rec.get("mount") or {}).get("module") or key
    was_loaded = sys.modules.pop(module, None) is not None
    d = _DISPATCHER
    if d is not None:
        with d.lock:
            d.cache.pop(key, None)
    proc = _PROXY_PROCS.pop(key, None)
    if proc and proc.poll() is None:
        proc.terminate()
    return was_loaded


def reload_app(key: str) -> dict:
    """Refresh gallery.yaml and invalidate one app. Used by `curiator reply --status done`.

    Refreshing the registry here is what lets agent-created apps appear in the running shell without a
    manual restart: the agent updates `gallery.yaml`, then `curiator reply` pokes `/reload/<new_app>`.
    """
    count = refresh_registry()
    was_loaded = invalidate_app(key)
    revision = APP_REVISIONS.get(key, 0) + 1
    APP_REVISIONS[key] = revision
    return {
        "reloaded": key,
        "module_was_loaded": was_loaded,
        "registered": key in BY_KEY,
        "registry_count": count,
        "revision": revision,
    }


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

    @shell.server.route("/settings", methods=["GET", "POST"])
    def _settings():             # admins configure the agent (provider / model / autonomy / trust)
        from flask import redirect, request

        from curiator.config import load_config, set_block_key
        cfg = load_config()                                   # fresh — reflects live edits
        acfg = cfg["auth"]
        if not auth.is_admin(acfg, auth.current_user(acfg)):
            return _page("Agent settings", "<p style='color:#a33;font-size:13px'>Admins only — your "
                         "account isn't in <code>auth.admin_groups</code>.</p>"), 403
        gallery = Path(cfg["gallery_path"])
        if request.method == "POST":
            text = gallery.read_text()
            for key in ("adapter", "autonomy", "permission_mode", "sandbox", "timeout", "model"):
                if key in request.form:
                    text = set_block_key(text, "agent", key, request.form.get(key))
            gallery.write_text(text)
            return redirect("/settings?saved=1")
        return _page("Agent settings",
                     _settings_html(cfg.get("agent") or {}, cfg["gallery_path"],
                                    saved=request.args.get("saved") == "1"))

    @shell.server.route("/whoami")
    def _whoami():               # the resolved identity for this request (handy for header-mode + debugging)
        from flask import jsonify
        return jsonify(auth.current_user(REG.AUTH_CFG) or {"authenticated": False})

    @shell.server.route("/feedback-shot/<path:fname>")
    def _shot(fname):
        return send_from_directory(SHOTS, fname)

    @shell.server.route("/feedback-audio/<path:fname>")
    def _audio(fname):
        return send_from_directory(AUDIO, fname)

    @shell.server.route("/feedback-trace/<feedback_id>.md")
    def _trace_raw(feedback_id):
        from flask import Response
        p = _trace_path(feedback_id)
        if not p or not p.exists():
            return ("trace not found", 404)
        return Response(p.read_text(encoding="utf-8", errors="replace"),
                        mimetype="text/markdown; charset=utf-8")

    @shell.server.route("/feedback-trace/<feedback_id>")
    def _trace(feedback_id):
        p = _trace_path(feedback_id)
        if not p or not p.exists():
            return _page("Agent trace", "<p style='color:#777;font-size:13px'>No trace file for this feedback.</p>"), 404
        return _trace_page(feedback_id, p.read_text(encoding="utf-8", errors="replace"))

    @shell.server.route("/static-app/<path:fname>")
    def _static_app(fname):
        return send_from_directory(HERE, fname)

    @shell.server.route("/general")
    def _general():
        from flask import request
        return render_history(request.args.get("range"))

    @shell.server.route("/reload/<key>", methods=["POST", "GET"])
    def _reload(key):
        # Poked by `curiator reply --status done` after the agent edits an app: drop the cached build so
        # the next view rebuilds from the edited source (refresh the gallery to see the fix).
        from flask import jsonify
        return jsonify(reload_app(key))

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
        dcc.Store(id="fb-reply-to"),
        html.Div(id="fb-reply-context"),
        dcc.Textarea(id="fb-comment", placeholder="What's good / what to change…",
                     title="OS dictation can type feedback here.",
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

    @shell.callback(Output("fb-reply-to", "data"),
                    Input({"type": "fbreply", "key": ALL, "target": ALL}, "n_clicks"),
                    Input("fb-reply-cancel", "n_clicks"), prevent_initial_call=True)
    def _set_reply_target(_clicks, _cancel):
        trig = ctx.triggered_id
        if trig == "fb-reply-cancel":
            return None
        if isinstance(trig, dict) and trig.get("type") == "fbreply":
            return {"key": trig.get("key"), "id": trig.get("target")}
        return no_update

    @shell.callback(Output("fb-reply-context", "children"),
                    Input("fb-reply-to", "data"), Input("selected-app", "data"))
    def _show_reply_target(target, key):
        return _reply_context(key, target)

    @shell.callback(Output("fb-status", "children"), Output("fb-status", "style"),
                    Output("fb-list", "children", allow_duplicate=True), Output("fb-comment", "value"),
                    Output("fb-stars", "value"), Output("shot-store", "data", allow_duplicate=True),
                    Output("fb-preview", "style", allow_duplicate=True), Output("cat-list", "children", allow_duplicate=True),
                    Output("fb-reply-to", "data", allow_duplicate=True),
                    Input("fb-save", "n_clicks"), State("selected-app", "data"), State("fb-stars", "value"),
                    State("fb-comment", "value"), State("shot-store", "data"),
                    State("cat-search", "value"), State("cat-sort", "value"), State("cat-tags", "value"),
                    State("cat-rev", "value"), State("fb-reply-to", "data"), prevent_initial_call=True)
    def _save(n, key, stars, comment, shot, search, sortby, tags_sel, rev, reply_to):
        okstyle = {"fontSize": "11.5px", "color": GREEN}
        errstyle = {"fontSize": "11.5px", "color": "#c0392b"}
        hide = {"display": "none"}
        if not key:
            return "Select an app first.", errstyle, no_update, no_update, no_update, no_update, no_update, no_update, no_update
        u, status, auth_error, _code = _feedback_user_and_status()
        if auth_error:
            return (auth_error, errstyle, no_update, no_update, no_update,
                    no_update, no_update, no_update, no_update)
        if not stars and not (comment or "").strip() and not shot:
            return "Add a rating, comment, or screenshot.", errstyle, no_update, no_update, no_update, \
                no_update, no_update, no_update, no_update
        shot = shot if (isinstance(shot, str) and shot.startswith("data:image")) else None
        parent = reply_to.get("id") if isinstance(reply_to, dict) and reply_to.get("key") == key else None
        e = save_entry(key, stars, comment, shot, user=u, reply_to=[parent] if parent else None, status=status)
        who = (e.get("user") or {}).get("name")
        msg = f"✓ saved ({e['id']})" + (f" · {who}" if who else "") + ("  +screenshot" if e["screenshot"] else "")
        if e.get("status") == "held":
            msg += " · queued for review"
        return msg, okstyle, feedback_list(key), "", None, None, hide, \
            catalog_rows(search, sortby, tags_sel, bool(rev)), None

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
            mtime = ledger.storage_mtime(LEDGER_CFG)
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
        if auth.is_admin(REG.AUTH_CFG, u):                    # admins (or solo `none` mode) → agent settings
            menu = [_menu_item("⚙ Settings", "/settings", "app-frame")] + menu
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
        u, status, auth_error, _code = _feedback_user_and_status()
        if auth_error:
            return no_update, auth_error, {"fontSize": "11.5px", "color": "#c0392b"}
        entry = record_action(trig["key"], trig["value"], trig.get("reply_to"), user=u, status=status)
        newlist = feedback_list(trig["key"]) if trig["key"] == sel else no_update
        suffix = "queued for review" if entry.get("status") == "held" else "processing shortly"
        return newlist, f"✓ recorded “{trig['value']}” — {suffix}", {"fontSize": "11.5px", "color": GREEN}

    @shell.server.route("/fb-action", methods=["POST", "GET"])
    def _fb_action_route():
        from flask import request
        key = request.args.get("key")
        value = request.args.get("value")
        reply_to = request.args.get("reply_to")
        if key and value is not None:
            u, status, auth_error, code = _feedback_user_and_status()
            if auth_error:
                return (auth_error, code or 401)
            record_action(key, value, reply_to, user=u, status=status)
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
    import logging

    from werkzeug.serving import run_simple
    # Quiet werkzeug's per-request access log — the live-poll Interval makes `POST /_dash-update-component`
    # spam that buries the watcher's feedback/agent lines. Set CURIATOR_HTTP_LOG=1 to restore it.
    if os.environ.get("CURIATOR_HTTP_LOG") != "1":
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
    # 0.0.0.0 so the shell is reachable over the Tailscale tailnet (phone-on-the-go).
    # NB this also exposes it on the LAN; it's an internal dev tool on a private tailnet.
    host = os.environ.get("SHELL_HOST", "0.0.0.0")
    run_simple(host, PORT, application, threaded=True)
