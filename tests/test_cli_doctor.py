"""CLI doctor: release-preflight checks for collection portability."""
from __future__ import annotations

import json
import textwrap


def test_doctor_ok_for_portable_collection(collection, capsys):
    from curiator import cli

    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "doctor OK" in out


def test_doctor_flags_absolute_paths_and_missing_sources(collection, capsys):
    from curiator import cli

    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            mount: { kind: dash-inproc, module: sample }
            source: apps/missing.py
        runner:
          mode: checkout
          path: /home/adamguetz/projects/curiator
    """))

    assert cli.main(["doctor", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert "absolute path" in messages or "machine-local path" in messages
    assert "configured path does not exist" in messages


def test_doctor_warns_without_failing_for_weak_release_smoke(collection, capsys):
    from curiator import cli

    (collection / "apps" / "proxy_app").mkdir()
    (collection / "apps" / "proxy_app" / "server.py").write_text("print('ok')\n")
    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: proxy_app
            root: apps/proxy_app
            source: .
            mount: { kind: proxy, cmd: "python server.py", port: 8800 }
    """))

    assert cli.main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["errors"] == 0
    assert payload["warnings"] == 2
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert "no smoke command configured" in messages
    assert "does not mention configured port 8800" in messages
