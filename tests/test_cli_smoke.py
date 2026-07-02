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
