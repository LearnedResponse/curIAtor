"""CLI smoke checks: run the same app gates used before git-as-memory commits."""
from __future__ import annotations

import json
import sys
import textwrap


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
