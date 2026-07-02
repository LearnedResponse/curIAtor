"""CLI-native interactive curator workflows for app repos."""
from __future__ import annotations

def test_link_file_resolves_gallery_from_external_app_repo(collection, tmp_path, monkeypatch):
    import subprocess
    import yaml

    from curiator import cli
    from curiator.config import load_config

    app_repo = tmp_path / "external_app"
    app_repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=app_repo, check=True)
    monkeypatch.chdir(app_repo)

    assert cli.main([
        "link",
        "--gallery", str(collection / "gallery.yaml"),
        "--app", "sample",
        "--commands",
    ]) == 0

    link = app_repo / ".curiator" / "app.yaml"
    assert link.exists()
    link_data = yaml.safe_load(link.read_text())
    assert link_data == {"gallery": "../gallery.yaml", "app": "sample"}
    assert (app_repo / ".claude" / "commands" / "curiator.md").exists()
    skill = app_repo / ".agents" / "skills" / "curiator" / "SKILL.md"
    assert skill.exists()
    assert skill.read_text().startswith("---\nname: curiator\n")

    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)
    cfg = load_config()
    assert cfg["gallery_path"] == str((collection / "gallery.yaml").resolve())
    assert cfg["current_app"] == "sample"


def test_interactive_work_and_done_use_same_ledger_and_git_memory(collection, monkeypatch, capsys):
    import subprocess

    from curiator import cli, ledger
    from curiator.config import load_config

    monkeypatch.chdir(collection)
    assert cli.main(["feedback", "add", "sample", "make it calmer"]) == 0
    cfg = load_config()
    fid = ledger.load(cfg)["sample"][-1]["id"]

    assert cli.main(["work", fid, "--no-print"]) == 0
    cfg = load_config()
    items = ledger.load(cfg)["sample"]
    assert next(e for e in items if e["id"] == fid)["status"] == "working"
    assert (collection / "feedback" / "tasks" / f"{fid}.md").exists()
    trace = collection / "feedback" / "replies" / f"{fid}.md"
    assert "interactive CLI work" in trace.read_text()

    assert cli.main(["done", fid, "Kept the current UI; no source change needed."]) == 0
    cfg = load_config()
    items = ledger.load(cfg)["sample"]
    assert next(e for e in items if e["id"] == fid)["status"] == "done"
    assert any(e.get("kind") == "system" and fid in (e.get("reply_to") or []) for e in items)

    out = capsys.readouterr().out
    assert "curiator: committed" in out
    assert "curiator: working sample/" in out
    assert subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "feedback/app_feedback.sqlite"],
                          cwd=collection, check=False).returncode == 0


def test_status_and_context_default_to_current_app(collection, monkeypatch, capsys):
    from curiator import cli

    monkeypatch.chdir(collection / "apps")
    assert cli.main(["status"]) == 0
    assert cli.main(["context", "--limit", "2"]) == 0
    out = capsys.readouterr().out
    assert "curIAtor status" in out
    assert "app:     sample" in out
    assert "# curIAtor Context: sample" in out
    assert "curiator work --app sample" in out


def test_context_without_selected_app_summarizes_multi_app_collection(collection, monkeypatch, capsys):
    import yaml

    from curiator import cli

    (collection / "apps" / "other").mkdir()
    (collection / "apps" / "other" / "server.py").write_text("print('other')\n")
    gallery = yaml.safe_load((collection / "gallery.yaml").read_text())
    gallery["apps"].append({
        "name": "other",
        "title": "Other",
        "root": "apps/other",
        "source": ".",
        "smoke": "python -m py_compile server.py",
        "mount": {"kind": "proxy", "cmd": "python server.py --port 8810", "port": 8810},
    })
    (collection / "gallery.yaml").write_text(yaml.safe_dump(gallery, sort_keys=False))

    outside = collection.parent / "outside"
    outside.mkdir(exist_ok=True)
    monkeypatch.chdir(outside)
    assert cli.main(["context", "--limit", "1"]) == 0

    out = capsys.readouterr().out
    assert "# curIAtor Context: collection" in out
    assert "- apps: 2" in out
    assert "- selected app: none" in out
    assert "curiator context --app" in out
    assert "`sample`:" in out
    assert "`other`:" in out
    assert "Recent General Feedback" in out


def test_status_surfaces_nested_app_repo(collection, monkeypatch, capsys):
    import subprocess

    from curiator import cli

    appdir = collection / "apps" / "imported"
    appdir.mkdir()
    (appdir / "server.py").write_text("print('imported')\n")
    subprocess.run(["git", "init", "-q"], cwd=appdir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Curator"], cwd=appdir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "curator@test.local"], cwd=appdir, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=appdir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed imported app"], cwd=appdir, check=True, capture_output=True)
    (collection / "gallery.yaml").write_text(
        (collection / "gallery.yaml").read_text().replace(
            "    tags: [demo]\n",
            "    tags: [demo]\n"
            "  - name: imported\n"
            "    title: Imported\n"
            "    root: apps/imported\n"
            "    source: .\n"
            "    smoke: python server.py\n"
            "    mount: { kind: proxy, cmd: \"python server.py --port 8812\", port: 8812 }\n",
        )
    )

    monkeypatch.chdir(collection)
    assert cli.main(["status", "--app", "imported"]) == 0

    out = capsys.readouterr().out
    assert f"app git: {appdir}" in out
    assert "clean]" in out


def test_commands_install_without_link(collection, monkeypatch):
    from curiator import cli

    monkeypatch.chdir(collection)
    assert cli.main(["commands", "install"]) == 0
    assert (collection / ".claude" / "commands" / "curiator.md").exists()
    assert (collection / ".agents" / "skills" / "curiator" / "SKILL.md").exists()


def test_commands_install_removes_generated_legacy_codex_skill(collection, monkeypatch, capsys):
    from curiator import cli

    legacy = collection / ".codex" / "skills" / "curiator" / "SKILL.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(cli._legacy_command_markdown())

    monkeypatch.chdir(collection)
    assert cli.main(["commands", "install"]) == 0

    assert not legacy.exists()
    assert not (collection / ".codex").exists()
    assert (collection / ".agents" / "skills" / "curiator" / "SKILL.md").exists()
    assert "legacy Codex skill path" in capsys.readouterr().out


def test_commands_install_keeps_customized_legacy_codex_skill(collection, monkeypatch, capsys):
    from curiator import cli

    legacy = collection / ".codex" / "skills" / "curiator" / "SKILL.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("custom local instructions\n")

    monkeypatch.chdir(collection)
    assert cli.main(["commands", "install"]) == 0

    assert legacy.read_text() == "custom local instructions\n"
    assert (collection / ".agents" / "skills" / "curiator" / "SKILL.md").exists()
    assert "kept customized legacy file" in capsys.readouterr().out


def test_done_with_message_only_closes_the_working_item(collection, monkeypatch, capsys):
    """`curiator done "<summary>"` (no id) must treat the words as the message, not an id."""
    from curiator import cli, ledger
    from curiator.config import load_config

    monkeypatch.chdir(collection)
    assert cli.main(["feedback", "add", "sample", "make it calmer"]) == 0
    cfg = load_config()
    fid = ledger.load(cfg)["sample"][-1]["id"]
    assert cli.main(["work", fid, "--no-print"]) == 0

    assert cli.main(["done", "calmed", "the", "layout", "and", "smoke-tested"]) == 0
    items = ledger.load(load_config())["sample"]
    assert next(e for e in items if e["id"] == fid)["status"] == "done"
    note = next(e for e in items if e.get("kind") == "system" and fid in (e.get("reply_to") or []))
    assert note["comment"].startswith("calmed the layout and smoke-tested")


def test_done_rejects_an_id_shaped_typo(collection, monkeypatch):
    import pytest
    from curiator import cli

    monkeypatch.chdir(collection)
    with pytest.raises(SystemExit, match="not found"):
        cli.main(["done", "deadbeef", "message text"])   # looks like an id → error, never message text


def test_feedback_add_rejects_unknown_app(collection, monkeypatch):
    """A comment swallowed by the app positional must not create a ledger key."""
    import pytest
    from curiator import cli

    monkeypatch.chdir(collection)
    with pytest.raises(SystemExit, match="unknown app"):
        cli.main(["feedback", "add", "great app", "--stars", "5"])


def test_feedback_add_stores_sanitized_annotations_for_task_bundle(collection, monkeypatch, capsys):
    import json
    from pathlib import Path

    from curiator import cli, ledger
    from curiator.config import load_config
    from curiator.loop.adapters import build_task

    monkeypatch.chdir(collection)
    marks = [
        {
            "tool": "pin",
            "x1": 1.4,
            "y1": 0.25,
            "n": 7,
            "note": "  marked   legend\nneeds room ",
            "target": {"selector": "#chart .legend", "classes": ["legend", "wide"]},
        },
        {"tool": "redact", "x1": 0.1, "y1": 0.2, "target": {"selector": "#secret"}},
    ]

    assert cli.main([
        "feedback",
        "add",
        "sample",
        "fix the marked legend",
        "--annotations-json",
        json.dumps(marks),
    ]) == 0
    cfg = load_config()
    entry = ledger.load(cfg)["sample"][-1]
    assert entry["annotations"][0]["x1"] == 1.0
    assert entry["annotations"][0]["note"] == "marked legend needs room"
    assert entry["annotations"][0]["target"]["selector"] == "#chart .legend"
    assert "target" not in entry["annotations"][1]
    assert "with 2 annotation(s)" in capsys.readouterr().out

    task = build_task(cfg, "sample", entry)
    body = Path(task.task_file).read_text()
    assert "## Screenshot annotations" in body
    assert "pin 7: `pin` at x1=1.000, y1=0.250" in body
    assert "selector `#chart .legend`" in body
    assert "marked legend needs room" in body
    assert "target omitted for redaction" in body
    assert "#secret" not in body


def test_queue_reviews_held_feedback_without_dispatching_it(collection, monkeypatch, capsys):
    import json
    import pytest

    from curiator import cli, ledger
    from curiator.config import load_config

    monkeypatch.chdir(collection)
    assert cli.main(["feedback", "add", "sample", "anonymous suggestion", "--status", "held", "--stars", "4"]) == 0
    cfg = load_config()
    held_id = ledger.load(cfg)["sample"][-1]["id"]
    capsys.readouterr()

    with pytest.raises(SystemExit, match="no open feedback"):
        cli.main(["work", "--app", "sample", "--no-print"])

    assert cli.main(["queue", "list", "--json"]) == 0
    out = capsys.readouterr().out
    rows = json.loads(out)
    assert rows == [{
        "app": "sample",
        "id": held_id,
        "ts": ledger.load(cfg)["sample"][-1]["ts"],
        "author": "anonymous@local",
        "stars": 4,
        "comment": "anonymous suggestion",
    }]

    assert cli.main(["queue", "approve", held_id]) == 0
    items = ledger.load(load_config())["sample"]
    assert next(e for e in items if e["id"] == held_id)["status"] == "new"
    assert any(e.get("kind") == "system" and held_id in (e.get("reply_to") or [])
               and "approved by curator@test.local" in e.get("comment", "")
               for e in items)

    assert cli.main(["feedback", "add", "sample", "duplicate public comment", "--status", "held"]) == 0
    reject_id = ledger.load(load_config())["sample"][-1]["id"]
    assert cli.main(["queue", "reject", reject_id, "duplicate"]) == 0
    items = ledger.load(load_config())["sample"]
    assert next(e for e in items if e["id"] == reject_id)["status"] == "rejected"
    assert any(e.get("kind") == "system" and reject_id in (e.get("reply_to") or [])
               and "Reason: duplicate" in e.get("comment", "")
               for e in items)


def test_queue_refuses_non_held_and_system_notes(collection, monkeypatch):
    import pytest

    from curiator import cli, ledger
    from curiator.config import load_config

    monkeypatch.chdir(collection)
    assert cli.main(["feedback", "add", "sample", "normal dispatchable feedback"]) == 0
    cfg = load_config()
    fid = ledger.load(cfg)["sample"][-1]["id"]
    note_id = ledger.add_system_note(cfg, "sample", "internal note", reply_to=[fid])

    with pytest.raises(SystemExit, match="not held"):
        cli.main(["queue", "approve", fid])
    with pytest.raises(SystemExit, match="system note"):
        cli.main(["queue", "reject", note_id])


def test_queue_sweep_dry_runs_and_rejects_only_stale_held_items(collection, monkeypatch, capsys):
    import json
    from datetime import datetime, timedelta, timezone

    from curiator import cli, ledger
    from curiator.config import load_config

    monkeypatch.chdir(collection)
    cfg = load_config()
    now = datetime.now(timezone.utc)
    old_id = ledger.save_entry(
        cfg,
        "sample",
        comment="old held public feedback",
        ts=(now - timedelta(days=45)).isoformat(timespec="seconds"),
        user={"email": "old@example.com", "name": "Old"},
        extra={"status": "held"},
    )
    recent_id = ledger.save_entry(
        cfg,
        "sample",
        comment="recent held public feedback",
        ts=(now - timedelta(days=3)).isoformat(timespec="seconds"),
        user={"email": "recent@example.com", "name": "Recent"},
        extra={"status": "held"},
    )

    assert cli.main(["queue", "sweep", "--older-than", "30", "--json"]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry["applied"] is False
    assert [row["id"] for row in dry["rows"]] == [old_id]
    assert next(e for e in ledger.load(cfg)["sample"] if e["id"] == old_id)["status"] == "held"

    assert cli.main(["queue", "sweep", "--older-than", "30", "--apply", "--reason", "stale"]) == 0
    items = ledger.load(cfg)["sample"]
    assert next(e for e in items if e["id"] == old_id)["status"] == "rejected"
    assert next(e for e in items if e["id"] == recent_id)["status"] == "held"
    assert any(e.get("kind") == "system" and old_id in (e.get("reply_to") or [])
               and "stale held item rejected by curator@test.local" in e.get("comment", "")
               and "Reason: stale" in e.get("comment", "")
               for e in items)


def test_work_refuses_a_system_note(collection, monkeypatch):
    import pytest
    from curiator import cli, ledger
    from curiator.config import load_config

    monkeypatch.chdir(collection)
    assert cli.main(["feedback", "add", "sample", "needs a legend"]) == 0
    cfg = load_config()
    fid = ledger.load(cfg)["sample"][-1]["id"]
    nid = ledger.add_system_note(cfg, "sample", "plan: add a legend", reply_to=[fid])
    with pytest.raises(SystemExit, match="agent note"):
        cli.main(["work", nid])
