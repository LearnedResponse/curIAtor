"""Dogfood narrated feedback through a real Brave-rendered curIAtor shell.

This requires Brave, so it lives outside the normal pytest suite. It starts a
temporary same-origin Dash collection with local voice transcription enabled,
drives the React shell through Brave, records with a fake local microphone,
captures the app view, draws a timed annotation while recording, stops
recording, saves feedback, then verifies the SQLite ledger and generated agent
task bundle contain the ordered narrated mark.
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
import wave
from pathlib import Path

from capture_demo_gif import CdpClient, _free_port, _start_brave, _wait_url
from dogfood_annotations_brave import _click_text, _set_value, _wait_value, _wait_value_for_page

ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPT = "this legend is cramped"
MARK_NOTE = "spoken while boxing the legend"


def _write_collection(root: Path, port: int) -> Path:
    apps = root / "apps"
    feedback = root / "feedback"
    apps.mkdir(parents=True)
    (feedback / "shots").mkdir(parents=True)
    (apps / "sample.py").write_text(
        '''import dash
from dash import html


def build_app():
    app = dash.Dash(__name__)
    app.layout = html.Div([
        html.H1("Narrated feedback dogfood"),
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
    transcriber = root / "transcribe_fixture.py"
    transcriber.write_text(
        "import json\n"
        "print(json.dumps({\n"
        f"  'text': {TRANSCRIPT!r},\n"
        "  'segments': [{'start': 0.0, 'end': 30.0, 'text': "
        f"{TRANSCRIPT!r}" + "}]\n"
        "}))\n",
        encoding="utf-8",
    )
    gallery = root / "gallery.yaml"
    gallery.write_text(
        f"""apps:
  - name: sample
    title: Narrated feedback dogfood
    mount: {{ kind: dash-inproc, module: sample }}
    source: apps/sample.py
    tags: [dogfood, voice]
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
voice:
  transcribe_cmd: "{sys.executable} {transcriber} {{audio}}"
  transcribe_timeout: 10
  transcribe_max_bytes: 26214400
tags:
  dogfood: "#666"
  voice: "#2980b9"
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


def _write_fake_audio(path: Path, seconds: float = 1.0, rate: int = 16000) -> None:
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * frames)


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
    if TRANSCRIPT not in (entry.get("comment") or ""):
        raise RuntimeError(f"transcript did not populate comment: {entry.get('comment')!r}")
    if not entry.get("screenshot") or not (collection / "feedback" / entry["screenshot"]).exists():
        raise RuntimeError(f"missing saved screenshot: {entry.get('screenshot')!r}")
    marks = entry.get("annotations") or []
    if len(marks) != 1:
        raise RuntimeError(f"expected one annotation mark, found {marks!r}")
    mark = marks[0]
    if mark.get("tool") != "box" or "start_ms" not in mark or "end_ms" not in mark:
        raise RuntimeError(f"expected a timed box mark, found {mark!r}")
    if mark.get("note") != MARK_NOTE:
        raise RuntimeError(f"annotation note did not persist: {mark!r}")
    target = mark.get("target") or {}
    if target.get("id") != "legend" or target.get("data_testid") != "legend-target":
        raise RuntimeError(f"DOM target did not persist: {target!r}")
    segments = entry.get("transcript_segments") or []
    if len(segments) != 1 or segments[0].get("text") != TRANSCRIPT:
        raise RuntimeError(f"transcript segment did not persist: {segments!r}")
    narrative = entry.get("narrative") or []
    if len(narrative) != 1 or narrative[0].get("text") != TRANSCRIPT:
        raise RuntimeError(f"narrative row did not persist: {narrative!r}")

    task = build_task(cfg, "sample", entry)
    body = Path(task.task_file).read_text(encoding="utf-8")
    required = [
        "## Voice transcript segments",
        "## Narrated feedback",
        "## Screenshot annotations",
        TRANSCRIPT,
        MARK_NOTE,
        "selector `",
        "data-testid `legend-target`",
    ]
    missing = [text for text in required if text not in body]
    if missing:
        raise RuntimeError(f"task bundle missing expected text: {missing}")
    return entry["id"]


def dogfood(brave_bin: str) -> None:
    with tempfile.TemporaryDirectory(prefix="curiator-narrated-dogfood-") as tmpdir:
        tmp = Path(tmpdir)
        collection = tmp / "collection"
        fake_audio = tmp / "fake-audio.wav"
        _write_fake_audio(fake_audio)
        port = _free_port()
        debug_port = _free_port()
        gallery = _write_collection(collection, port)
        shell = _start_shell(gallery)
        brave = None
        cdp = None
        try:
            _wait_url(f"http://127.0.0.1:{port}/api/bootstrap")
            brave = _start_brave(
                brave_bin,
                tmp / "brave-profile",
                debug_port,
                extra_args=[
                    "--use-fake-ui-for-media-stream",
                    "--use-fake-device-for-media-stream",
                    f"--use-file-for-fake-audio-capture={fake_audio}",
                ],
            )
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
            cdp.navigate(f"http://127.0.0.1:{port}/?app=sample")
            _wait_value(cdp, "!!document.querySelector('.rshell-feedback textarea')", timeout=10.0)
            _click_text(cdp, "Record")
            _wait_value(cdp, "(document.querySelector('.rshell-msg') || {}).textContent.includes('Recording feedback')", timeout=15.0)
            _click_text(cdp, "Capture view")
            _wait_value(cdp, "document.querySelector('.rshell-annotation-canvas') && document.querySelector('.rshell-annotation-canvas').width > 20", timeout=15.0)
            _draw_box_on_legend(cdp)
            _wait_value(cdp, "document.querySelectorAll('.rshell-annotation-note input').length === 1", timeout=10.0)
            _set_value(cdp, ".rshell-annotation-note input", MARK_NOTE)
            time.sleep(0.3)
            _click_text(cdp, "Stop")
            _wait_value(cdp, "(document.querySelector('.rshell-msg') || {}).textContent.includes('Transcript added')", timeout=20.0)
            _wait_value(cdp, f"document.querySelector('.rshell-feedback textarea').value.includes({json.dumps(TRANSCRIPT)})", timeout=10.0)
            _click_text(cdp, "Save feedback")
            _wait_value(cdp, "(document.querySelector('.rshell-msg') || {}).textContent.includes('saved')", timeout=15.0)
            entry_id = _verify_collection(collection)
            print(f"curiator: Brave narrated-feedback dogfood OK ({entry_id})")
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
