"""Headless browser smoke checks for the curIAtor shell."""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .agent_capabilities import safe_artifact_label
from .serve_cli import _child_env, _shell_path


W, H = 1280, 720
_BROWSER_CANDIDATES = (
    "brave-browser",
    "brave-browser-stable",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_url(url: str, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if int(getattr(response, "status", 200)) < 500:
                    return True
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.2)
    return False


def _json_get(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _reload_app(base_url: str, app: str, timeout: float = 3.0) -> bool:
    """Drop any cached mount/build failure before rendered verification."""
    url = f"{base_url}/reload/{urllib.parse.quote(app, safe='')}"
    try:
        request = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(getattr(response, "status", 200)) < 400
    except (OSError, urllib.error.URLError):
        return False


class CdpClient:
    """Minimal Chrome DevTools Protocol websocket client for navigation/evaluation."""

    def __init__(self, ws_url: str):
        parsed = urllib.parse.urlparse(ws_url)
        if parsed.scheme != "ws":
            raise ValueError(f"expected ws:// URL, got {ws_url}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path + (("?" + parsed.query) if parsed.query else "")
        self.sock = socket.create_connection((host, port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = self.sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"websocket handshake failed: {response[:200]!r}")
        self._next_id = 0
        self.events: list[dict] = []

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def command(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        ident = self._next_id
        self._send_json({"id": ident, "method": method, "params": params or {}})
        while True:
            msg = json.loads(self._recv_message())
            if msg.get("id") == ident:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method} failed: {msg['error']}")
                return msg.get("result") or {}
            if msg.get("method"):
                self.events.append(msg)

    def wait_value(self, expression: str, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        last: dict = {}
        while time.monotonic() < deadline:
            result = self.command("Runtime.evaluate", {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            })
            value = (result.get("result") or {}).get("value")
            if isinstance(value, dict) and value.get("ok"):
                return value
            if isinstance(value, dict):
                last = value
            time.sleep(0.25)
        return last or {"ok": False, "message": "timed out waiting for app iframe render"}

    def navigate_and_check(self, url: str, timeout: float) -> dict:
        self.command("Page.navigate", {"url": url})
        return self.wait_value(_BROWSER_CHECK_EXPR, timeout)

    def capture_screenshot(self) -> bytes:
        result = self.command("Page.captureScreenshot", {
            "format": "png",
            "captureBeyondViewport": False,
        })
        return base64.b64decode(result.get("data") or "")

    def console_events(self) -> list[dict]:
        rows: list[dict] = []
        for event in self.events:
            method = event.get("method")
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            if method == "Runtime.consoleAPICalled":
                args = params.get("args") if isinstance(params.get("args"), list) else []
                text = " ".join(
                    str(arg.get("value") if "value" in arg else arg.get("description") or "")
                    for arg in args
                    if isinstance(arg, dict)
                ).strip()
                rows.append({"source": "console", "level": params.get("type"), "text": text})
            elif method == "Log.entryAdded":
                entry = params.get("entry") if isinstance(params.get("entry"), dict) else {}
                rows.append({
                    "source": entry.get("source") or "log",
                    "level": entry.get("level"),
                    "text": entry.get("text") or "",
                    "url": entry.get("url"),
                })
        return rows

    def _send_json(self, payload: dict) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", n))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", n))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(header + masked)

    def _recv_exact(self, n: int) -> bytes:
        chunks = []
        remaining = n
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise RuntimeError("websocket closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _recv_message(self) -> str:
        chunks: list[bytes] = []
        while True:
            b1, b2 = self._recv_exact(2)
            fin = bool(b1 & 0x80)
            opcode = b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            masked = bool(b2 & 0x80)
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length)
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 8:
                raise RuntimeError("websocket closed")
            if opcode in (1, 2, 0):
                chunks.append(payload)
                if fin:
                    return b"".join(chunks).decode("utf-8")


_BROWSER_CHECK_EXPR = r"""(() => {
  const frame = document.querySelector("#app-frame");
  if (document.readyState !== "complete") {
    return {ok: false, message: "shell document not complete"};
  }
  if (!frame) {
    return {ok: false, message: "shell did not render #app-frame"};
  }
  let doc = null;
  try {
    doc = frame.contentDocument || (frame.contentWindow && frame.contentWindow.document);
  } catch (err) {
    return {ok: false, message: "app iframe is not same-origin: " + err};
  }
  if (!doc || doc.readyState !== "complete" || !doc.body) {
    return {ok: false, message: "app iframe document not complete"};
  }
  const text = (doc.body.innerText || "").trim();
  const hasVisibleNode = !!doc.body.querySelector("canvas,svg,img,table,main,section,article,div,p,h1,h2,h3");
  const lower = text.toLowerCase();
  if (lower === "loading..." || lower === "loading") {
    return {ok: false, message: "app iframe is still on the loading placeholder"};
  }
  if (lower.startsWith("loading website") ||
      lower.includes("requires javascript to load and work properly")) {
    return {ok: false, message: "app iframe is still on a JavaScript loading fallback"};
  }
  if (lower.includes("could not be mounted") ||
      lower.includes("proxy is not reachable") ||
      lower.includes("proxy could not start") ||
      lower.includes("proxy backend did not respond") ||
      lower.includes("websocket/hmr upgrade requests are not supported")) {
    return {ok: false, message: text.slice(0, 220)};
  }
  if (text.length < 2 && !hasVisibleNode) {
    return {ok: false, message: "app iframe rendered no visible content"};
  }
  return {ok: true, message: text ? text.slice(0, 160) : "visible non-text content rendered"};
})()"""


def _start_shell_if_needed(cfg: dict, timeout: float) -> tuple[subprocess.Popen | None, str]:
    from .web_paths import local_shell_url

    base_url = local_shell_url(cfg).rstrip("/")
    if _wait_url(f"{base_url}/api/bootstrap", timeout=0.75):
        return None, base_url
    shell_args = [sys.executable, str(_shell_path()), "--gallery", str(Path(cfg["gallery_path"]).resolve())]
    if cfg.get("state_dir"):
        shell_args += ["--state-dir", str(Path(cfg["state_dir"]).resolve())]
    proc = subprocess.Popen(
        shell_args,
        cwd=cfg["repo_root"],
        env=_child_env(cfg),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    if not _wait_url(f"{base_url}/api/bootstrap", timeout=timeout):
        code = proc.poll()
        if code is None:
            proc.terminate()
        return proc, base_url
    return proc, base_url


def _start_browser(
    brave_bin: str,
    profile: Path,
    debug_port: int,
    viewport: tuple[int, int] = (W, H),
) -> subprocess.Popen:
    width, height = viewport
    return subprocess.Popen(
        [
            brave_bin,
            "--headless=new",
            f"--remote-debugging-port={debug_port}",
            "--remote-debugging-address=127.0.0.1",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-scrollbars",
            f"--user-data-dir={profile}",
            f"--window-size={width},{height}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _cdp_client(
    debug_port: int,
    timeout: float,
    viewport: tuple[int, int] = (W, H),
) -> CdpClient:
    version_url = f"http://127.0.0.1:{debug_port}/json/version"
    if not _wait_url(version_url, timeout=timeout):
        raise RuntimeError("browser did not expose a DevTools endpoint")
    pages = _json_get(f"http://127.0.0.1:{debug_port}/json/list")
    page = next((p for p in pages if p.get("type") == "page"), None)
    if not page:
        raise RuntimeError("browser did not expose a page target")
    cdp = CdpClient(page["webSocketDebuggerUrl"])
    cdp.command("Page.enable")
    cdp.command("Runtime.enable")
    try:
        cdp.command("Log.enable")
    except RuntimeError:
        pass
    width, height = viewport
    cdp.command("Emulation.setDeviceMetricsOverride", {
        "width": width,
        "height": height,
        "deviceScaleFactor": 1,
        "mobile": width <= 600,
    })
    return cdp


def _artifact_path(cfg: dict, artifact_dir: str | Path, app: str, suffix: str) -> Path:
    base = Path(artifact_dir)
    if not base.is_absolute():
        base = Path(cfg["repo_root"]) / base
    return base / f"{safe_artifact_label(app)}{suffix}"


def _repo_rel(cfg: dict, path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(cfg["repo_root"]).resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _console_error_count(events: list[dict]) -> int:
    return sum(
        1 for event in events if str(event.get("level") or "").lower() in {"error", "exception", "assert"}
    )


def _write_artifacts(
    cfg: dict,
    cdp: CdpClient,
    app: str,
    artifact_dir: str | Path | None,
    console_events: list[dict],
) -> dict:
    if not artifact_dir:
        return {}
    screenshot_path = _artifact_path(cfg, artifact_dir, app, ".png")
    console_path = _artifact_path(cfg, artifact_dir, app, ".console.json")
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    written: dict = {}
    try:
        png = cdp.capture_screenshot()
        if png:
            screenshot_path.write_bytes(png)
            written["screenshot"] = _repo_rel(cfg, screenshot_path)
    except Exception as exc:  # noqa: BLE001
        written["screenshot_error"] = f"{type(exc).__name__}: {exc}"
    try:
        console_path.write_text(json.dumps(console_events, indent=2), encoding="utf-8")
        written["console_log"] = _repo_rel(cfg, console_path)
        written["console_errors"] = _console_error_count(console_events)
    except Exception as exc:  # noqa: BLE001
        written["console_error"] = f"{type(exc).__name__}: {exc}"
    return written


def browser_smoke_apps(
    cfg: dict,
    apps: list[str],
    *,
    browser_bin: str | None = None,
    timeout: float = 15.0,
    artifact_dir: str | Path | None = None,
    viewport: tuple[int, int] = (W, H),
) -> dict[str, dict]:
    """Open the React shell in a headless browser and verify each app iframe renders."""
    brave_bin = browser_bin or os.environ.get("CURIATOR_BROWSER") or next(
        (path for name in _BROWSER_CANDIDATES if (path := shutil.which(name))),
        None,
    )
    if not brave_bin:
        return {
            app: {
                "ok": False,
                "message": "Brave/Chromium is required for browser smoke; pass --browser-bin or set CURIATOR_BROWSER",
            }
            for app in apps
        }

    shell = None
    browser = None
    cdp = None
    with tempfile.TemporaryDirectory(prefix="curiator-browser-smoke-") as tmpdir:
        try:
            shell, base_url = _start_shell_if_needed(cfg, timeout)
            bootstrap = _json_get(f"{base_url}/api/bootstrap")
            available = {str(a.get("key")) for a in bootstrap.get("apps", [])}
            missing = [app for app in apps if app not in available]
            if missing:
                return {
                    app: {
                        "ok": False,
                        "message": f"running shell does not expose app {app!r}",
                        "browser": str(brave_bin),
                        "started_shell": shell is not None,
                    }
                    for app in missing
                } | {
                    app: {
                        "ok": False,
                        "message": f"browser smoke skipped because requested app(s) are missing: {', '.join(missing)}",
                        "browser": str(brave_bin),
                        "started_shell": shell is not None,
                    }
                    for app in apps
                    if app not in missing
                }
            debug_port = _free_port()
            browser = _start_browser(brave_bin, Path(tmpdir) / "profile", debug_port, viewport)
            cdp = _cdp_client(debug_port, timeout, viewport)
            results: dict[str, dict] = {}
            for app in apps:
                url = f"{base_url}/?app={urllib.parse.quote(app)}"
                _reload_app(base_url, app)
                cdp.events.clear()
                checked = cdp.navigate_and_check(url, timeout)
                console_events = cdp.console_events()
                console_errors = _console_error_count(console_events)
                artifacts = _write_artifacts(cfg, cdp, app, artifact_dir, console_events)
                ok = bool(checked.get("ok")) and console_errors == 0
                message = str(checked.get("message") or "")
                if console_errors:
                    suffix = f"{console_errors} browser console/network error(s)"
                    message = f"{message}; {suffix}" if message else suffix
                results[app] = {
                    "ok": ok,
                    "url": url,
                    "message": message,
                    "browser": str(brave_bin),
                    "viewport": {"width": viewport[0], "height": viewport[1]},
                    "started_shell": shell is not None,
                    "console_errors": console_errors,
                    **artifacts,
                }
            return results
        except Exception as exc:  # noqa: BLE001
            return {app: {"ok": False, "message": f"{type(exc).__name__}: {exc}", "browser": str(brave_bin)} for app in apps}
        finally:
            if cdp:
                cdp.close()
            for proc in (browser, shell):
                if proc and proc.poll() is None:
                    proc.terminate()
            for proc in (browser, shell):
                if proc:
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
