"""Dogfood screenshot annotations through a real Brave-rendered curIAtor shell.

This intentionally sits outside the normal pytest suite because it requires Brave. It starts a
temporary same-origin Dash collection, drives the React shell through Brave's DevTools protocol,
draws a marked screenshot in the feedback composer, saves it, then verifies the SQLite ledger and
generated task bundle.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from capture_demo_gif import CdpClient, _free_port, _start_brave, _wait_url

ROOT = Path(__file__).resolve().parents[1]
COMMENT = "fix the marked legend target"
NOTE = "marked legend needs room"


def _write_collection(root: Path, port: int) -> Path:
    apps = root / "apps"
    (root / "feedback" / "shots").mkdir(parents=True)
    apps.mkdir(parents=True)
    (apps / "sample.py").write_text(
        '''import dash
from dash import html


def build_app():
    app = dash.Dash(__name__)
    app.layout = html.Div([
        html.H1("Annotation dogfood"),
        html.Div("Revenue by segment", id="chart", **{"data-testid": "chart-target"}, style={
            "height": "220px",
            "border": "1px solid #bbb",
            "background": "linear-gradient(180deg, #eef7ff, #ffffff)",
            "padding": "24px",
            "fontFamily": "Arial, sans-serif",
        }),
        html.Div("Legend target", id="legend", className="legend cramped", role="note",
                 **{"data-testid": "legend-target"}, style={
                     "position": "absolute",
                     "left": "420px",
                     "top": "135px",
                     "padding": "10px 14px",
                     "border": "2px solid #8e44ad",
                     "background": "#fff5cc",
                     "fontFamily": "Arial, sans-serif",
                 }),
    ], style={"position": "relative", "minHeight": "420px", "padding": "36px"})
    return app


app = build_app()
''',
        encoding="utf-8",
    )
    gallery = root / "gallery.yaml"
    gallery.write_text(
        f"""apps:
  - name: sample
    title: Annotation dogfood
    mount: {{ kind: dash-inproc, module: sample }}
    source: apps/sample.py
    tags: [dogfood, annotations]
agent:
  adapter: command
  autonomy: auto-small
runner:
  mode: pinned
feedback:
  dir: feedback
  screenshots: true
auth:
  mode: none
  default_user: dogfood@local
git:
  commit: false
shell:
  port: {port}
  poll_seconds: 0.2
tags:
  dogfood: "#666"
  annotations: "#8e44ad"
""",
        encoding="utf-8",
    )
    return gallery


def _start_shell(gallery: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env.pop("CURIATOR_GALLERY", None)
    return subprocess.Popen(
        [sys.executable, "-m", "curiator.cli", "--gallery", str(gallery), "up"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )


def _eval(cdp: CdpClient, expression: str):
    result = cdp.command("Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True,
    })
    inner = result.get("result") or {}
    if "exceptionDetails" in result:
        raise RuntimeError(result["exceptionDetails"])
    if inner.get("subtype") == "error":
        raise RuntimeError(inner.get("description") or inner.get("value"))
    return inner.get("value")


def _wait_value(cdp: CdpClient, expression: str, timeout: float = 10.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            value = _eval(cdp, expression)
        except Exception as exc:  # noqa: BLE001 - keep the dogfood error useful.
            last = exc
        else:
            if value:
                return value
        time.sleep(0.2)
    raise RuntimeError(f"timed out waiting for browser value: {expression}; last={last}")


def _click_text(cdp: CdpClient, text: str) -> None:
    ok = _eval(cdp, f"""(() => {{
      const btn = Array.from(document.querySelectorAll('button'))
        .find((node) => (node.textContent || '').includes({json.dumps(text)}));
      if (!btn) return false;
      btn.click();
      return true;
    }})()""")
    if not ok:
        raise RuntimeError(f"button not found: {text}")


def _set_value(cdp: CdpClient, selector: str, value: str) -> None:
    ok = _eval(cdp, f"""(() => {{
      const node = document.querySelector({json.dumps(selector)});
      if (!node) return false;
      const proto = node instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(node, {json.dumps(value)});
      node.dispatchEvent(new Event('input', {{bubbles: true}}));
      return true;
    }})()""")
    if not ok:
        raise RuntimeError(f"input not found: {selector}")


def _draw_box_on_legend(cdp: CdpClient) -> None:
    coords = _wait_value(cdp, """(() => {
      const canvas = document.querySelector('.rshell-annotation-canvas');
      const iframe = document.getElementById('app-frame');
      const doc = iframe && iframe.contentDocument;
      const target = doc && doc.querySelector('#legend');
      if (!canvas || !target || !canvas.getBoundingClientRect) return null;
      const c = canvas.getBoundingClientRect();
      const docEl = doc.documentElement || {};
      const body = doc.body || {};
      const pageW = Math.max(body.scrollWidth || 0, docEl.scrollWidth || 0, body.offsetWidth || 0, docEl.clientWidth || 0, 1);
      const pageH = Math.max(body.scrollHeight || 0, docEl.scrollHeight || 0, body.offsetHeight || 0, docEl.clientHeight || 0, 1);
      const t = target.getBoundingClientRect();
      const sx = (t.left + (doc.defaultView.pageXOffset || 0)) / pageW;
      const sy = (t.top + (doc.defaultView.pageYOffset || 0)) / pageH;
      const ex = (t.right + (doc.defaultView.pageXOffset || 0)) / pageW;
      const ey = (t.bottom + (doc.defaultView.pageYOffset || 0)) / pageH;
      return {
        startX: c.left + Math.max(0.01, sx - 0.015) * c.width,
        startY: c.top + Math.max(0.01, sy - 0.02) * c.height,
        endX: c.left + Math.min(0.99, ex + 0.015) * c.width,
        endY: c.top + Math.min(0.99, ey + 0.02) * c.height
      };
    })()""", timeout=10.0)
    cdp.command("Input.dispatchMouseEvent", {
        "type": "mousePressed",
        "x": coords["startX"],
        "y": coords["startY"],
        "button": "left",
        "clickCount": 1,
    })
    cdp.command("Input.dispatchMouseEvent", {
        "type": "mouseMoved",
        "x": coords["endX"],
        "y": coords["endY"],
        "button": "left",
    })
    cdp.command("Input.dispatchMouseEvent", {
        "type": "mouseReleased",
        "x": coords["endX"],
        "y": coords["endY"],
        "button": "left",
        "clickCount": 1,
    })


def _verify_collection(collection: Path) -> str:
    from curiator import ledger
    from curiator.config import load_config_at
    from curiator.loop.adapters import build_task

    cfg = load_config_at(collection / "gallery.yaml")
    entries = ledger.load(cfg).get("sample", [])
    if len(entries) != 1:
        raise RuntimeError(f"expected one saved feedback entry, found {len(entries)}")
    entry = entries[0]
    if entry.get("comment") != COMMENT:
        raise RuntimeError(f"unexpected comment: {entry.get('comment')!r}")
    shot = entry.get("screenshot")
    if not shot or not (collection / "feedback" / shot).exists():
        raise RuntimeError(f"missing saved screenshot: {shot!r}")
    marks = entry.get("annotations") or []
    if len(marks) != 1:
        raise RuntimeError(f"expected one annotation mark, found {marks!r}")
    mark = marks[0]
    target = mark.get("target") or {}
    if mark.get("tool") != "box":
        raise RuntimeError(f"expected a box mark, found {mark!r}")
    if mark.get("note") != NOTE:
        raise RuntimeError(f"annotation note did not persist: {mark!r}")
    if target.get("id") != "legend" or target.get("data_testid") != "legend-target":
        raise RuntimeError(f"DOM target did not persist: {target!r}")

    task = build_task(cfg, "sample", entry)
    body = Path(task.task_file).read_text(encoding="utf-8")
    required = [
        "## Screenshot annotations",
        "`box`",
        "selector `",
        "data-testid `legend-target`",
        NOTE,
        f"screenshot (Read this PNG): `feedback/{shot}`",
    ]
    missing = [text for text in required if text not in body]
    if missing:
        raise RuntimeError(f"task bundle missing expected text: {missing}")
    return entry["id"]


def dogfood(brave_bin: str) -> None:
    with tempfile.TemporaryDirectory(prefix="curiator-annotation-dogfood-") as tmpdir:
        tmp = Path(tmpdir)
        collection = tmp / "collection"
        port = _free_port()
        debug_port = _free_port()
        gallery = _write_collection(collection, port)
        shell = _start_shell(gallery)
        brave = None
        cdp = None
        try:
            _wait_url(f"http://127.0.0.1:{port}/api/bootstrap")
            brave = _start_brave(brave_bin, tmp / "brave-profile", debug_port)
            _wait_url(f"http://127.0.0.1:{debug_port}/json/version")
            cdp = CdpClient(_wait_value_for_page(debug_port))
            cdp.command("Page.enable")
            cdp.command("Runtime.enable")
            cdp.command("Emulation.setDeviceMetricsOverride", {
                "width": 1280,
                "height": 760,
                "deviceScaleFactor": 1,
                "mobile": False,
            })
            base = f"http://127.0.0.1:{port}/?app=sample"
            cdp.navigate(base)
            _wait_value(cdp, "!!document.querySelector('.rshell-feedback textarea')", timeout=10.0)
            _set_value(cdp, ".rshell-feedback textarea", COMMENT)
            _click_text(cdp, "Capture view")
            _wait_value(cdp, "document.querySelector('.rshell-annotation-canvas') && document.querySelector('.rshell-annotation-canvas').width > 20", timeout=15.0)
            _draw_box_on_legend(cdp)
            _wait_value(cdp, "document.querySelectorAll('.rshell-annotation-note input').length === 1", timeout=10.0)
            _set_value(cdp, ".rshell-annotation-note input", NOTE)
            _click_text(cdp, "Save feedback")
            _wait_value(cdp, "(document.querySelector('.rshell-msg') || {}).textContent && document.querySelector('.rshell-msg').textContent.includes('saved')", timeout=15.0)
            entry_id = _verify_collection(collection)
            print(f"curiator: Brave annotation dogfood OK ({entry_id})")
        finally:
            if cdp:
                cdp.close()
            for proc in (brave, shell):
                if proc and proc.poll() is None:
                    proc.terminate()
            for proc in (brave, shell):
                if proc:
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()


def _wait_value_for_page(debug_port: int) -> str:
    import urllib.request

    deadline = time.time() + 10.0
    while time.time() < deadline:
        with urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json/list", timeout=2) as response:
            pages = json.loads(response.read().decode("utf-8"))
        page = next((p for p in pages if p.get("type") == "page" and p.get("webSocketDebuggerUrl")), None)
        if page:
            return page["webSocketDebuggerUrl"]
        time.sleep(0.2)
    raise RuntimeError("Brave did not expose a page target")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brave-bin", default=shutil.which("brave-browser") or shutil.which("brave-browser-stable"),
                        help="Brave executable")
    args = parser.parse_args(argv)
    if not args.brave_bin:
        raise SystemExit("Brave is required: install brave-browser or pass --brave-bin")
    dogfood(args.brave_bin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
