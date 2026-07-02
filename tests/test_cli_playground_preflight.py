"""CLI playground preflight: hosted public-pilot posture checks."""
from __future__ import annotations

import json
import textwrap


def test_playground_preflight_fails_unsafe_collection_defaults(collection, capsys):
    from curiator import cli

    assert cli.main(["playground-preflight", "--no-smoke", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert payload["ok"] is False
    assert payload["runner"]["mode"] == "checkout"
    assert "runner.mode: pinned" in messages
    assert "auth.mode: local, header, or oidc" in messages
    assert payload["smoke"]["ok"] is None


def test_playground_preflight_accepts_phase0_local_auth_config(collection, capsys):
    from curiator import auth, cli

    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            mount: { kind: dash-inproc, module: sample }
            source: apps/sample.py
            tags: [demo]
        runner:
          mode: pinned
        git:
          commit: true
        auth:
          mode: local
          users_file: .curiator-users.json
          admin_groups: [admin]
          allow_anonymous: true
        agent:
          adapter: headless-cc
          autonomy: propose-only
          dispatch:
            anonymous: hold
            user: auto
            trusted_groups: [trusted]
          quotas:
            per_user_daily: 3
            global_daily: 25
        feedback:
          dir: feedback
        shell:
          port: 8399
    """))
    auth.save_users_file(
        str(collection / ".curiator-users.json"),
        {
            "admin@example.com": {
                "name": "Admin",
                "groups": ["admin", "trusted"],
                "password_hash": "test-hash",
            }
        },
    )

    assert cli.main(["playground-preflight", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["auth"]["mode"] == "local"
    assert payload["auth"]["allow_anonymous"] is True
    assert payload["user_store"]["active"] == 1
    assert payload["user_store"]["admins"] == 1
    assert payload["doctor"]["ok"] is True
    assert payload["smoke"]["ok"] is True
    assert payload["checks"] == {"smoke": True, "http_smoke": False}


def test_playground_preflight_json_output_writes_evidence_file(collection, capsys, tmp_path):
    from curiator import auth, cli

    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            mount: { kind: dash-inproc, module: sample }
            source: apps/sample.py
        runner:
          mode: pinned
        git:
          commit: true
        auth:
          mode: local
          users_file: .curiator-users.json
          admin_groups: [admin]
        agent:
          autonomy: propose-only
          dispatch:
            trusted_groups: [trusted]
          quotas:
            per_user_daily: 3
            global_daily: 25
    """))
    auth.save_users_file(
        str(collection / ".curiator-users.json"),
        {"admin@example.com": {"name": "Admin", "groups": ["admin"], "password_hash": "test-hash"}},
    )
    out_path = tmp_path / "evidence" / "playground-preflight.json"

    assert cli.main(["playground-preflight", "--no-smoke", "--json", "--output", str(out_path)]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"curiator: wrote {out_path}" in captured.err
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["checks"]["smoke"] is False
    assert payload["auth"]["mode"] == "local"


def test_playground_preflight_output_keeps_human_summary(collection, capsys, tmp_path):
    from curiator import auth, cli

    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            mount: { kind: dash-inproc, module: sample }
            source: apps/sample.py
        runner:
          mode: pinned
        git:
          commit: true
        auth:
          mode: local
          users_file: .curiator-users.json
          admin_groups: [admin]
        agent:
          autonomy: propose-only
          dispatch:
            trusted_groups: [trusted]
          quotas:
            per_user_daily: 3
            global_daily: 25
    """))
    auth.save_users_file(
        str(collection / ".curiator-users.json"),
        {"admin@example.com": {"name": "Admin", "groups": ["admin"], "password_hash": "test-hash"}},
    )
    out_path = tmp_path / "evidence" / "playground-preflight.json"

    assert cli.main(["playground-preflight", "--no-smoke", "--output", str(out_path)]) == 0

    captured = capsys.readouterr()
    assert "curiator: playground preflight OK" in captured.out
    assert f"curiator: wrote {out_path}" in captured.err
    assert json.loads(out_path.read_text(encoding="utf-8"))["user_store"]["admins"] == 1


def test_playground_preflight_can_run_http_smoke(collection, monkeypatch, capsys):
    from curiator import auth, cli

    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            mount: { kind: dash-inproc, module: sample }
            source: apps/sample.py
        runner:
          mode: pinned
        git:
          commit: true
        auth:
          mode: local
          users_file: .curiator-users.json
          admin_groups: [admin]
        agent:
          autonomy: propose-only
          dispatch:
            trusted_groups: [trusted]
          quotas:
            per_user_daily: 3
            global_daily: 25
    """))
    auth.save_users_file(
        str(collection / ".curiator-users.json"),
        {"admin@example.com": {"name": "Admin", "groups": ["admin"], "password_hash": "test-hash"}},
    )
    calls = []

    def fake_smoke_results(cfg, app=None, jobs=1, *, http=False):
        calls.append({"gallery": cfg["gallery_path"], "http": http})
        result = {
            "app": "sample",
            "smoke": "python -m py_compile apps/sample.py",
            "ok": True,
            "message": "ok",
        }
        if http:
            result["http_smoke"] = {
                "ok": True,
                "url": "http://127.0.0.1:8800/",
                "message": "HTTP 200",
            }
        return [result]

    monkeypatch.setattr(cli, "_smoke_results", fake_smoke_results)

    assert cli.main(["playground-preflight", "--http-smoke", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["checks"] == {"smoke": True, "http_smoke": True}
    assert calls == [{"gallery": str(collection / "gallery.yaml"), "http": True}]
    assert payload["smoke"]["results"][0]["http_smoke"]["url"].endswith(":8800/")


def test_playground_preflight_rejects_http_smoke_without_smoke(collection, capsys):
    from curiator import cli

    assert cli.main(["playground-preflight", "--no-smoke", "--http-smoke"]) == 2
    out = capsys.readouterr().out
    assert "--http-smoke requires smoke checks" in out


def test_playground_preflight_strict_fails_warning_only_posture(collection, capsys):
    from curiator import auth, cli

    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            mount: { kind: dash-inproc, module: sample }
            source: apps/sample.py
        runner:
          mode: pinned
        git:
          commit: true
        auth:
          mode: local
          users_file: .curiator-users.json
          admin_groups: [admin]
        agent:
          adapter: headless-cc
          autonomy: auto-small
    """))
    auth.save_users_file(
        str(collection / ".curiator-users.json"),
        {"admin@example.com": {"name": "Admin", "groups": ["admin"], "password_hash": "test-hash"}},
    )

    assert cli.main(["playground-preflight", "--no-smoke", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["strict"] is False
    assert payload["warnings"] == 4

    assert cli.main(["playground-preflight", "--no-smoke", "--strict", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert payload["ok"] is False
    assert payload["strict"] is True
    assert payload["warnings"] == 4
    assert "agent.autonomy: propose-only" in messages
    assert "per-user daily dispatch quota" in messages

    assert cli.main(["playground-preflight", "--no-smoke", "--strict"]) == 1
    out = capsys.readouterr().out
    assert "strict=true: 4 warning(s) block this gate" in out
    assert "WARNING agent.quotas.global_daily" in out


def test_playground_preflight_rejects_anonymous_auto_dispatch(collection, capsys):
    from curiator import auth, cli

    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            mount: { kind: dash-inproc, module: sample }
            source: apps/sample.py
        runner:
          mode: pinned
        git:
          commit: true
        auth:
          mode: local
          users_file: .curiator-users.json
          admin_groups: [admin]
          allow_anonymous: true
        agent:
          autonomy: propose-only
          dispatch:
            anonymous: auto
            trusted_groups: [trusted]
          quotas:
            per_user_daily: 3
            global_daily: 25
    """))
    auth.save_users_file(
        str(collection / ".curiator-users.json"),
        {"admin@example.com": {"name": "Admin", "groups": ["admin"], "password_hash": "test-hash"}},
    )

    assert cli.main(["playground-preflight", "--no-smoke", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert payload["ok"] is False
    assert "agent.dispatch.anonymous: hold" in messages
