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
