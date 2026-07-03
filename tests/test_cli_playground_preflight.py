"""CLI playground preflight: hosted public-pilot posture checks."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import textwrap


def _ignore_local_users_file(collection):
    path = collection / ".gitignore"
    current = path.read_text() if path.exists() else ""
    if ".curiator-users.json" not in current.splitlines():
        path.write_text(current + ("\n" if current and not current.endswith("\n") else "") + ".curiator-users.json\n")


def _write_phase0_local_auth_config(collection):
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
        agent:
          adapter: headless-cc
          autonomy: propose-only
          dispatch:
            trusted_groups: [trusted]
          quotas:
            per_user_daily: 3
            global_daily: 25
        feedback:
          dir: feedback
        shell:
          port: 8399
    """))


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
    _ignore_local_users_file(collection)
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
    assert payload["user_store"]["inline_users"] == 0
    assert payload["user_store"]["users_file_mode"] == "0o600"
    assert payload["user_store"]["users_file_owner_only"] is True
    assert payload["user_store"]["users_file_rel"] == ".curiator-users.json"
    assert payload["user_store"]["users_file_tracked"] is False
    assert payload["user_store"]["users_file_ignored"] is True
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
    _ignore_local_users_file(collection)
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
    _ignore_local_users_file(collection)
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


def test_playground_preflight_rejects_world_readable_local_users_file(collection, capsys):
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
    _ignore_local_users_file(collection)
    users_file = collection / ".curiator-users.json"
    auth.save_users_file(
        str(users_file),
        {"admin@example.com": {"name": "Admin", "groups": ["admin"], "password_hash": "test-hash"}},
    )
    users_file.chmod(0o644)

    assert cli.main(["playground-preflight", "--no-smoke", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert payload["user_store"]["users_file_mode"] == "0o644"
    assert payload["user_store"]["users_file_owner_only"] is False
    assert "must be owner-only (0600)" in messages


def test_playground_preflight_rejects_unignored_local_users_file(collection, capsys):
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

    assert cli.main(["playground-preflight", "--no-smoke", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert payload["user_store"]["users_file_tracked"] is False
    assert payload["user_store"]["users_file_ignored"] is False
    assert "must be gitignored" in messages


def test_playground_preflight_rejects_tracked_local_users_file(collection, capsys):
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
    users_file = collection / ".curiator-users.json"
    auth.save_users_file(
        str(users_file),
        {"admin@example.com": {"name": "Admin", "groups": ["admin"], "password_hash": "test-hash"}},
    )
    subprocess.run(["git", "add", ".curiator-users.json"], cwd=collection, check=True, capture_output=True)

    assert cli.main(["playground-preflight", "--no-smoke", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert payload["user_store"]["users_file_tracked"] is True
    assert "must not be tracked by git" in messages


def test_playground_preflight_rejects_inline_local_users(collection, capsys):
    from curiator import cli

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
          admin_groups: [admin]
          users:
            - email: admin@example.com
              name: Admin
              groups: [admin]
              password_hash: test-hash
        agent:
          autonomy: propose-only
          dispatch:
            trusted_groups: [trusted]
          quotas:
            per_user_daily: 3
            global_daily: 25
    """))

    assert cli.main(["playground-preflight", "--no-smoke", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert payload["user_store"]["inline_users"] == 1
    assert "auth.users_file, not inline auth.users" in messages


def test_playground_preflight_rejects_incomplete_oidc_config(collection, monkeypatch, capsys):
    from curiator import cli

    monkeypatch.delenv("CURIATOR_OIDC_SECRET", raising=False)
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
          mode: oidc
        agent:
          autonomy: propose-only
          dispatch:
            trusted_groups: [trusted]
          quotas:
            per_user_daily: 3
            global_daily: 25
    """))

    assert cli.main(["playground-preflight", "--no-smoke", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert payload["auth"]["mode"] == "oidc"
    assert payload["auth"]["oidc"]["issuer_configured"] is False
    assert payload["auth"]["oidc"]["client_id_configured"] is False
    assert payload["auth"]["oidc"]["client_secret_env"] == "CURIATOR_OIDC_SECRET"
    assert payload["auth"]["oidc"]["client_secret_set"] is False
    assert "auth.issuer" in "\n".join(issue["where"] for issue in payload["issues"])
    assert "auth.client_id" in "\n".join(issue["where"] for issue in payload["issues"])
    assert "OIDC client secret env var CURIATOR_OIDC_SECRET must be set" in messages


def test_playground_preflight_accepts_complete_oidc_config(collection, monkeypatch, capsys):
    from curiator import cli

    monkeypatch.setenv("TEST_CURIATOR_OIDC_SECRET", "not-for-output")
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
          mode: oidc
          issuer: https://idp.example.test/realms/curiator
          client_id: curiator-playground
          client_secret_env: TEST_CURIATOR_OIDC_SECRET
          admin_groups: [admin]
          allow_anonymous: true
        agent:
          autonomy: propose-only
          dispatch:
            anonymous: hold
            trusted_groups: [trusted]
          quotas:
            per_user_daily: 3
            global_daily: 25
    """))

    assert cli.main(["playground-preflight", "--no-smoke", "--json"]) == 0
    payload_text = capsys.readouterr().out
    payload = json.loads(payload_text)
    assert payload["ok"] is True
    assert payload["auth"]["allow_anonymous"] is True
    assert payload["auth"]["oidc"] == {
        "issuer_configured": True,
        "client_id_configured": True,
        "client_secret_env": "TEST_CURIATOR_OIDC_SECRET",
        "client_secret_set": True,
        "scope": "openid email profile",
    }
    assert "not-for-output" not in payload_text


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
    _ignore_local_users_file(collection)
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
    _ignore_local_users_file(collection)
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


def test_playground_backup_smoke_restores_collection_and_runs_preflight(collection, capsys, tmp_path):
    from curiator import auth, cli

    _write_phase0_local_auth_config(collection)
    _ignore_local_users_file(collection)
    auth.save_users_file(
        str(collection / ".curiator-users.json"),
        {"admin@example.com": {"name": "Admin", "groups": ["admin"], "password_hash": "test-hash"}},
    )
    (collection / "feedback" / "tasks").mkdir(parents=True, exist_ok=True)
    (collection / "feedback" / "tasks" / "abc123.md").write_text("restored task trace\n", encoding="utf-8")
    restore_root = collection.parent / f"{tmp_path.name}-restores"

    assert cli.main([
        "playground-backup-smoke",
        "--no-smoke",
        "--keep-restore",
        "--restore-root",
        str(restore_root),
        "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    restore_path = Path(payload["restore"]["path"])

    assert payload["ok"] is True
    assert payload["source"] == str(collection.resolve())
    assert payload["restore"]["kept"] is True
    assert restore_path.exists()
    assert payload["preflight"]["gallery"] == str(restore_path / "gallery.yaml")
    assert payload["preflight"]["user_store"]["users_file_rel"] == ".curiator-users.json"
    assert payload["preflight"]["checks"] == {"smoke": False, "http_smoke": False}
    assert (restore_path / ".curiator-users.json").exists()
    assert (restore_path / "feedback" / "tasks" / "abc123.md").read_text(encoding="utf-8") == "restored task trace\n"


def test_playground_backup_smoke_cleans_restore_by_default(collection, capsys, tmp_path):
    from curiator import auth, cli

    _write_phase0_local_auth_config(collection)
    _ignore_local_users_file(collection)
    auth.save_users_file(
        str(collection / ".curiator-users.json"),
        {"admin@example.com": {"name": "Admin", "groups": ["admin"], "password_hash": "test-hash"}},
    )

    assert cli.main([
        "playground-backup-smoke",
        "--no-smoke",
        "--restore-root",
        str(collection.parent / f"{tmp_path.name}-restores"),
        "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert payload["restore"]["kept"] is False
    assert not Path(payload["restore"]["root"]).exists()


def test_playground_backup_smoke_rejects_restore_root_inside_collection(collection, capsys):
    from curiator import cli

    assert cli.main([
        "playground-backup-smoke",
        "--no-smoke",
        "--restore-root",
        str(collection / "restore"),
        "--json",
    ]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is False
    assert payload["restore"]["error"] == "restore root must not live inside the source collection"
