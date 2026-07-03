"""CLI smoke checks: run the same app gates used before git-as-memory commits."""
from __future__ import annotations

import json
import sys
import textwrap
import time


def test_smoke_runs_fallback_import_for_collection(collection, capsys):
    from curiator import cli

    assert cli.main(["smoke", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["results"][0]["app"] == "sample"
    assert payload["results"][0]["source"] == "apps/sample.py"


def test_smoke_can_limit_to_one_app(collection, capsys):
    from curiator import cli

    assert cli.main(["app", "create", "status_server", "--template", "python"]) == 0
    capsys.readouterr()

    assert cli.main(["smoke", "--app", "status_server", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [r["app"] for r in payload["results"]] == ["status_server"]
    assert payload["results"][0]["smoke"] == "python -m py_compile server.py"


def test_smoke_infers_python_proxy_directory_check(collection, capsys):
    from curiator import cli

    root = collection / "apps" / "proxy_server"
    root.mkdir()
    (root / "server.py").write_text("def broken(:\n")
    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: proxy_server
            title: Proxy Server
            root: apps/proxy_server
            source: .
            mount: { kind: proxy, cmd: "python server.py --port 8800", port: 8800 }
    """))

    assert cli.main(["smoke", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["smoke"] == "python -m py_compile server.py"
    assert "SyntaxError" in payload["results"][0]["message"]


def test_smoke_http_starts_proxy_and_checks_configured_path(collection, capsys, monkeypatch):
    from curiator import cli
    from curiator import gitmem

    port = 8877
    root = collection / "apps" / "proxy_http"
    root.mkdir()
    (root / "server.py").write_text(textwrap.dedent("""\
        from __future__ import annotations

        import argparse
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/healthz":
                    body = b"ok"
                    self.send_response(200)
                    self.send_header("content-length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def log_message(self, fmt, *args):
                return


        parser = argparse.ArgumentParser()
        parser.add_argument("--port", type=int, required=True)
        args = parser.parse_args()
        ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    """))
    (collection / "gallery.yaml").write_text(textwrap.dedent(f"""\
        apps:
          - name: proxy_http
            title: Proxy HTTP
            root: apps/proxy_http
            source: .
            smoke: python -m py_compile server.py
            smoke_http: /healthz
            commands:
              preview: "{sys.executable} server.py --port {{port}}"
            mount: {{ kind: proxy, cmd: "{sys.executable} server.py --port {{port}}", port: {port} }}
    """))

    popen_calls = []

    class FakeProc:
        pid = 123

        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    def fake_popen(args, *popen_args, **popen_kwargs):
        if args[:2] != [sys.executable, "server.py"]:
            return real_popen(args, *popen_args, **popen_kwargs)
        popen_calls.append({"args": args, "cwd": popen_kwargs.get("cwd"), "env": popen_kwargs.get("env")})
        return FakeProc()

    class FakeResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    real_popen = gitmem.subprocess.Popen
    monkeypatch.setattr(gitmem.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(gitmem.urllib.request, "urlopen", lambda url, timeout=None: FakeResponse())

    assert cli.main(["smoke", "--app", "proxy_http", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "http_smoke" not in payload["results"][0]

    assert cli.main(["smoke", "--app", "proxy_http", "--http", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    result = payload["results"][0]
    assert result["smoke"] == "python -m py_compile server.py"
    assert result["http_smoke"]["ok"] is True
    assert result["http_smoke"]["url"] == f"http://127.0.0.1:{port}/healthz"
    assert result["http_smoke"]["command"] == f"{sys.executable} server.py --port {port}"
    assert popen_calls[0]["cwd"] == root
    assert popen_calls[0]["env"]["PORT"] == str(port)
    assert popen_calls[0]["env"]["CURIATOR_APP"] == "proxy_http"


def test_smoke_browser_opens_apps_through_shell(collection, capsys, monkeypatch):
    from curiator import browser_smoke, cli

    calls = []

    def fake_browser_smoke_apps(cfg, apps, *, browser_bin=None, timeout=15.0, artifact_dir=None):
        calls.append({
            "gallery": cfg["gallery_path"],
            "apps": apps,
            "browser_bin": browser_bin,
            "timeout": timeout,
            "artifact_dir": artifact_dir,
        })
        return {
            app: {
                "ok": True,
                "url": f"http://127.0.0.1:8300/?app={app}",
                "message": "Sample app rendered",
                "browser": browser_bin,
                "started_shell": True,
            }
            for app in apps
        }

    monkeypatch.setattr(browser_smoke, "browser_smoke_apps", fake_browser_smoke_apps)

    assert cli.main(["smoke", "--browser", "--browser-bin", "/usr/bin/brave", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert calls == [{
        "gallery": str(collection / "gallery.yaml"),
        "apps": ["sample"],
        "browser_bin": "/usr/bin/brave",
        "timeout": 15.0,
        "artifact_dir": None,
    }]
    assert payload["results"][0]["browser_smoke"]["ok"] is True
    assert payload["results"][0]["browser_smoke"]["message"] == "Sample app rendered"


def test_smoke_browser_writes_json_output_and_passes_artifact_dir(collection, capsys, monkeypatch):
    from curiator import browser_smoke, cli

    calls = []

    def fake_browser_smoke_apps(cfg, apps, *, browser_bin=None, timeout=15.0, artifact_dir=None):
        calls.append({"apps": apps, "artifact_dir": artifact_dir})
        return {
            "sample": {
                "ok": True,
                "url": "http://127.0.0.1:8399/?app=sample",
                "message": "Sample app rendered",
                "screenshot": "feedback/replies/f1-browser-smoke/sample.png",
                "console_log": "feedback/replies/f1-browser-smoke/sample.console.json",
                "console_errors": 0,
            }
        }

    monkeypatch.setattr(browser_smoke, "browser_smoke_apps", fake_browser_smoke_apps)
    output = collection / "feedback" / "replies" / "f1-browser-smoke" / "result.json"

    assert cli.main([
        "smoke",
        "--app", "sample",
        "--browser",
        "--artifact-dir", "feedback/replies/f1-browser-smoke",
        "--output", str(output),
        "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    written = json.loads(output.read_text())

    assert calls == [{"apps": ["sample"], "artifact_dir": "feedback/replies/f1-browser-smoke"}]
    assert payload == written
    browser = payload["results"][0]["browser_smoke"]
    assert browser["screenshot"] == "feedback/replies/f1-browser-smoke/sample.png"
    assert browser["console_log"] == "feedback/replies/f1-browser-smoke/sample.console.json"


def test_smoke_browser_failure_fails_app_result(collection, capsys, monkeypatch):
    from curiator import browser_smoke, cli

    monkeypatch.setattr(
        browser_smoke,
        "browser_smoke_apps",
        lambda cfg, apps, *, browser_bin=None, timeout=15.0, artifact_dir=None: {
            app: {"ok": False, "message": "app iframe rendered no visible content"}
            for app in apps
        },
    )

    assert cli.main(["smoke", "--browser", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    result = payload["results"][0]
    assert result["ok"] is False
    assert result["browser_smoke"]["ok"] is False
    assert "browser smoke failed: app iframe rendered no visible content" in result["message"]


def test_smoke_reports_failing_configured_smoke(collection, capsys):
    from curiator import cli

    (collection / "apps" / "broken.py").write_text("def nope(:\n")
    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: broken
            title: Broken
            mount: { kind: dash-inproc, module: broken }
            source: apps/broken.py
            smoke: python -m py_compile apps/broken.py
    """))

    assert cli.main(["smoke", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["results"][0]["app"] == "broken"
    assert "SyntaxError" in payload["results"][0]["message"]


def test_smoke_reports_timeout(collection, capsys):
    from curiator import cli

    (collection / "gallery.yaml").write_text(textwrap.dedent(f"""\
        smoke:
          timeout: 0.1
        apps:
          - name: slow
            title: Slow
            mount: {{ kind: proxy, cmd: "python server.py", port: 8800 }}
            source: apps/sample.py
            smoke: {sys.executable} -c "import time; time.sleep(2)"
    """))

    assert cli.main(["smoke", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["smoke_timeout"] == 0.1
    assert "timeout after 0.1s" in payload["results"][0]["message"]


def test_smoke_jobs_runs_independent_checks_in_parallel(collection, capsys):
    from curiator import cli

    sleep_cmd = f'{sys.executable} -c "import time; time.sleep(0.45)"'
    (collection / "gallery.yaml").write_text(textwrap.dedent(f"""\
        apps:
          - name: slow_a
            title: Slow A
            mount: {{ kind: dash-inproc, module: sample }}
            source: apps/sample.py
            smoke: {sleep_cmd}
          - name: slow_b
            title: Slow B
            mount: {{ kind: dash-inproc, module: sample }}
            source: apps/sample.py
            smoke: {sleep_cmd}
    """))

    start = time.perf_counter()
    assert cli.main(["smoke", "--json"]) == 0
    serial = time.perf_counter() - start
    capsys.readouterr()

    start = time.perf_counter()
    assert cli.main(["smoke", "--jobs", "2", "--json"]) == 0
    parallel = time.perf_counter() - start
    payload = json.loads(capsys.readouterr().out)

    assert [r["app"] for r in payload["results"]] == ["slow_a", "slow_b"]
    assert parallel < serial - 0.25


def test_smoke_jobs_preserves_failure_order(collection, capsys):
    from curiator import cli

    (collection / "gallery.yaml").write_text(textwrap.dedent(f"""\
        apps:
          - name: slow_first
            title: Slow First
            mount: {{ kind: dash-inproc, module: sample }}
            source: apps/sample.py
            smoke: {sys.executable} -c "import time; time.sleep(0.3)"
          - name: fast_fail
            title: Fast Fail
            mount: {{ kind: dash-inproc, module: sample }}
            source: apps/sample.py
            smoke: {sys.executable} -c "import sys; sys.exit(3)"
          - name: slow_last
            title: Slow Last
            mount: {{ kind: dash-inproc, module: sample }}
            source: apps/sample.py
            smoke: {sys.executable} -c "import time; time.sleep(0.1)"
    """))

    assert cli.main(["smoke", "--jobs", "3", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert [r["app"] for r in payload["results"]] == ["slow_first", "fast_fail", "slow_last"]
    assert [r["ok"] for r in payload["results"]] == [True, False, True]
    assert payload["results"][1]["message"] == "exit 3"


def test_smoke_rejects_nonpositive_jobs(collection, capsys):
    from curiator import cli

    assert cli.main(["smoke", "--jobs", "0"]) == 2
    assert "smoke --jobs must be >= 1" in capsys.readouterr().out
