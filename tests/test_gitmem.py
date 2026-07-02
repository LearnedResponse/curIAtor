"""gitmem: the commit-per-run schema + trailers, that the commit bundles source+ledger, branch
selection, and that revert APPENDS a note (preserving the record) rather than erasing it. reflect →
LESSONS.md. Runs against the tmp collection's real git repo — no agent needed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from curiator import gitmem, ledger


def _log(collection: Path, *fmt) -> str:
    return subprocess.run(["git", "log", *fmt], cwd=collection, capture_output=True, text=True).stdout


def _do_fix(cfg, collection, *, comment="legend covers the chart", stars=2):
    """Simulate an agent run: edit the source, post the reply note, set done — then commit_run."""
    src = collection / "apps" / "sample.py"
    src.write_text(src.read_text().replace('"sample"', '"sample (fixed)"'))
    fid = ledger.save_entry(cfg, "sample", stars=stars, comment=comment, ts="t0")
    nid = ledger.add_system_note(cfg, "sample", "Fixed the layout.", reply_to=[fid], ts="t1")
    ledger.set_status(cfg, "sample", [fid], "done")
    res = gitmem.commit_run(cfg, "sample", fid, status="done", note_text="Fixed the layout.")
    return fid, nid, res


def test_commit_bundles_source_and_ledger_with_trailers(cfg, collection):
    fid, _, res = _do_fix(cfg, collection)
    assert res["committed"], res
    files = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"],
                           cwd=collection, capture_output=True, text=True).stdout.split()
    assert "apps/sample.py" in files                       # the source edit
    assert "feedback/app_feedback.sqlite" in files         # …and the ledger, in ONE commit
    body = _log(collection, "-1", "--format=%B")
    assert body.startswith("curator(sample):")
    assert "Smoke-test: passed" in body
    assert "Curiator-App: sample" in body
    assert f"Curiator-Feedback: {fid}" in body
    assert "Co-Authored-By: curiator[" in body
    assert "Signed-off-by:" in body                        # DCO (signoff:true)
    assert "(★★)" in body                                  # stars rendered


def test_queryable_by_trailer(cfg, collection):
    fid, _, _ = _do_fix(cfg, collection)
    found = _log(collection, "--all", "--grep=Curiator-App: sample", "--format=%H")
    assert found.strip(), "git log --grep on the trailer should find the commit"
    assert gitmem.find_commit(cfg, fid) is not None


def test_smoke_gate_blocks_broken_commit(cfg, collection):
    src = collection / "apps" / "sample.py"
    src.write_text("this is not valid python {{{")
    fid = ledger.save_entry(cfg, "sample", comment="x", ts="t0")
    ledger.add_system_note(cfg, "sample", "tried", reply_to=[fid], ts="t1")
    res = gitmem.commit_run(cfg, "sample", fid, status="done", note_text="tried")
    assert not res["committed"] and "smoke-test failed" in res["reason"]
    # the broken edit was reverted, nothing committed
    assert "{{{" not in src.read_text()
    assert _log(collection, "--format=%s").splitlines()[0] == "init"


def test_smoke_timeout_blocks_and_reverts_commit(cfg, collection):
    src = collection / "apps" / "sample.py"
    src.write_text(src.read_text().replace('"sample"', '"sample (slow)"'))
    cfg["apps"][0]["smoke"] = f'{sys.executable} -c "import time; time.sleep(2)"'
    cfg["apps"][0]["smoke_timeout"] = 0.1
    fid = ledger.save_entry(cfg, "sample", comment="x", ts="t0")
    ledger.add_system_note(cfg, "sample", "tried", reply_to=[fid], ts="t1")
    ledger.set_status(cfg, "sample", [fid], "done")

    res = gitmem.commit_run(cfg, "sample", fid, status="done", note_text="tried")

    assert not res["committed"] and "timeout after 0.1s" in res["reason"]
    assert "(slow)" not in src.read_text()
    assert _log(collection, "--format=%s").splitlines()[0] == "init"


def test_branch_selection(cfg, collection):
    cfg["git"]["branch"] = "curiator/sandbox"
    _do_fix(cfg, collection)
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            cwd=collection, capture_output=True, text=True).stdout.strip()
    assert branch == "curiator/sandbox"                    # commit landed on the configured branch


def test_revert_appends_note_keeps_thread(cfg, collection):
    fid, _, _ = _do_fix(cfg, collection)
    res = gitmem.revert_feedback(cfg, fid, reason="rewind")
    assert res["ok"] and res["reverted_source"]
    # the source is back to its pre-fix state
    assert "(fixed)" not in (collection / "apps" / "sample.py").read_text()
    # a dedicated revert commit exists (history preserved — both fix and revert are on the log)
    subjects = _log(collection, "--format=%s").splitlines()
    assert any(s.startswith("curator(sample): revert") for s in subjects)
    assert any(s.startswith("curator(sample): Fixed") for s in subjects)   # original NOT erased
    # the conversation: original reply kept + a new ↩ revert note appended
    notes = [e for e in ledger.load(cfg)["sample"] if e["author"] == "claude"]
    assert any("Fixed the layout" in (e.get("comment") or "") for e in notes)
    assert any("reverted" in (e.get("comment") or "").lower() for e in notes)


def test_reflect_writes_lessons(cfg, collection):
    fid, _, _ = _do_fix(cfg, collection)
    gitmem.revert_feedback(cfg, fid, reason="rewind")
    content = gitmem.reflect(cfg)
    assert "## sample" in content
    assert "revert" in content.lower()
    p = gitmem.write_lessons(cfg)
    assert Path(p).exists() and "## sample" in Path(p).read_text()


def test_ledger_only_commit_for_no_source_change(cfg, collection):
    # a positive ack: a reply with no source edit still produces a (ledger-only) commit
    fid = ledger.save_entry(cfg, "sample", stars=5, comment="love it", ts="t0")
    ledger.add_system_note(cfg, "sample", "Glad you like it!", reply_to=[fid], ts="t1")
    ledger.set_status(cfg, "sample", [fid], "done")
    res = gitmem.commit_run(cfg, "sample", fid, status="done", note_text="Glad you like it!")
    assert res["committed"]
    files = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"],
                           cwd=collection, capture_output=True, text=True).stdout.split()
    assert files == ["feedback/app_feedback.sqlite"]       # ledger only, no source
    assert "ack / no source change" in _log(collection, "-1", "--format=%B")


def test_general_collection_commit_captures_app_and_gallery(cfg, collection):
    app = collection / "apps" / "models.py"
    app.write_text("import dash\nfrom dash import html\n\ndef build_app():\n    a = dash.Dash(__name__)\n    a.layout = html.Div('models')\n    return a\n")
    (collection / "gallery.yaml").write_text(
        (collection / "gallery.yaml").read_text()
        + "\n  - name: models\n    title: Models\n    mount: { kind: dash-inproc, module: models }\n    source: apps/models.py\n"
    )
    fid = ledger.save_entry(cfg, "__general__", comment="create a new curiator app as an overview", ts="t0")
    ledger.add_system_note(cfg, "__general__", "Added the model overview app.", reply_to=[fid], ts="t1")
    ledger.set_status(cfg, "__general__", [fid], "done")
    res = gitmem.commit_run(cfg, "__general__", fid, status="done", note_text="Added the model overview app.")
    assert res["committed"], res
    files = _names_at_head(collection)
    assert "apps/models.py" in files and "gallery.yaml" in files and "feedback/app_feedback.sqlite" in files
    body = _log(collection, "-1", "--format=%B")
    assert "apps/models.py" in body and "gallery.yaml" in body


def test_general_runner_feedback_does_not_sweep_collection_changes(cfg, collection):
    (collection / "gallery.yaml").write_text((collection / "gallery.yaml").read_text() + "\n# local draft\n")
    fid = ledger.save_entry(cfg, "__general__", comment="make the shell chrome clearer", ts="t0")
    ledger.add_system_note(cfg, "__general__", "Patched the runner shell.", reply_to=[fid], ts="t1")
    ledger.set_status(cfg, "__general__", [fid], "done")
    res = gitmem.commit_run(cfg, "__general__", fid, status="done", note_text="Patched the runner shell.")
    assert res["committed"], res
    assert _names_at_head(collection) == ["feedback/app_feedback.sqlite"]
    porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=collection,
                               capture_output=True, text=True).stdout
    assert "gallery.yaml" in porcelain


def test_feedback_from_trailer_carries_provenance(cfg, collection):
    src = collection / "apps" / "sample.py"
    src.write_text(src.read_text().replace('"sample"', '"sample (fixed)"'))
    fid = ledger.save_entry(cfg, "sample", stars=2, comment="fix the layout",
                            user={"id": "u", "email": "dev@corp.com", "name": "Dev"}, ts="t0")
    ledger.add_system_note(cfg, "sample", "Fixed.", reply_to=[fid], ts="t1")
    ledger.set_status(cfg, "sample", [fid], "done")
    res = gitmem.commit_run(cfg, "sample", fid, status="done", note_text="Fixed.")
    assert res["committed"]
    assert "Feedback-From: dev@corp.com" in _log(collection, "-1", "--format=%B")


def test_no_feedback_from_trailer_when_anonymous(cfg, collection):
    fid, _, _ = _do_fix(cfg, collection)                   # _do_fix saves with no user
    assert "Feedback-From:" not in _log(collection, "-1", "--format=%B")


def _names_at_head(collection: Path) -> list[str]:
    return subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"],
                          cwd=collection, capture_output=True, text=True).stdout.split()


def test_commit_includes_dependency_manifest(cfg, collection):
    """An elevated run that adds a dependency: requirements.txt rides in the SAME atomic commit as the
    source + ledger — not left dangling in the working tree (the M2/elevated re-run regression)."""
    src = collection / "apps" / "sample.py"
    src.write_text(src.read_text().replace('"sample"', '"sample (live)"'))
    (collection / "requirements.txt").write_text("dash\nyfinance>=0.2\n")    # the agent's new dep
    fid = ledger.save_entry(cfg, "sample", comment="use yfinance", ts="t0")
    ledger.add_system_note(cfg, "sample", "Added live data.", reply_to=[fid], ts="t1")
    ledger.set_status(cfg, "sample", [fid], "done")
    res = gitmem.commit_run(cfg, "sample", fid, status="done", note_text="Added live data.")
    assert res["committed"], res
    files = _names_at_head(collection)
    assert "apps/sample.py" in files and "feedback/app_feedback.sqlite" in files
    assert "requirements.txt" in files                     # the dep manifest, in the SAME commit
    assert "requirements.txt" in _log(collection, "-1", "--format=%B")      # and noted in the message
    porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=collection,
                               capture_output=True, text=True).stdout
    assert "requirements.txt" not in porcelain             # nothing dependency-related left behind


def test_unrelated_files_not_swept_into_commit(cfg, collection):
    """Only source + ledger (+ manifests) are captured — a stray non-manifest change is left untouched."""
    src = collection / "apps" / "sample.py"
    src.write_text(src.read_text().replace('"sample"', '"sample (x)"'))
    (collection / "scratch.txt").write_text("not a manifest")
    fid = ledger.save_entry(cfg, "sample", comment="x", ts="t0")
    ledger.add_system_note(cfg, "sample", "y", reply_to=[fid], ts="t1")
    ledger.set_status(cfg, "sample", [fid], "done")
    gitmem.commit_run(cfg, "sample", fid, status="done", note_text="y")
    assert "scratch.txt" not in _names_at_head(collection)  # stray file stays in the working tree


def test_also_commit_can_be_disabled(cfg, collection):
    """`git.also_commit: []` restores the strict source+ledger-only policy."""
    cfg["git"]["also_commit"] = []
    src = collection / "apps" / "sample.py"
    src.write_text(src.read_text().replace('"sample"', '"sample (z)"'))
    (collection / "requirements.txt").write_text("dash\n")
    fid = ledger.save_entry(cfg, "sample", comment="x", ts="t0")
    ledger.add_system_note(cfg, "sample", "y", reply_to=[fid], ts="t1")
    ledger.set_status(cfg, "sample", [fid], "done")
    gitmem.commit_run(cfg, "sample", fid, status="done", note_text="y")
    assert "requirements.txt" not in _names_at_head(collection)   # opt-out honored


def test_directory_source_commit_uses_configured_smoke(cfg, collection):
    appdir = collection / "apps" / "suite"
    appdir.mkdir()
    (appdir / "server.py").write_text("print('ok')\n")
    (appdir / "README.md").write_text("before\n")
    cfg["apps"] = [{
        "name": "suite",
        "root": "apps/suite",
        "source": ".",
        "mount": {"kind": "proxy", "cmd": "python server.py --port {port}", "port": 8811},
        "smoke": "python server.py",
    }]
    subprocess.run(["git", "add", "apps/suite/server.py", "apps/suite/README.md"],
                   cwd=collection, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "add suite"],
                   cwd=collection, check=True, capture_output=True)

    (appdir / "README.md").write_text("after\n")
    fid = ledger.save_entry(cfg, "suite", comment="touch suite", ts="t0")
    ledger.add_system_note(cfg, "suite", "Updated suite.", reply_to=[fid], ts="t1")
    ledger.set_status(cfg, "suite", [fid], "done")
    res = gitmem.commit_run(cfg, "suite", fid, status="done", note_text="Updated suite.")
    assert res["committed"], res
    files = _names_at_head(collection)
    assert "apps/suite/README.md" in files and "feedback/app_feedback.sqlite" in files
    assert "Smoke-test: passed" in _log(collection, "-1", "--format=%B")


def test_nested_app_repo_commit_preserves_app_history_and_collection_receipt(cfg, collection):
    appdir = collection / "apps" / "imported"
    appdir.mkdir()
    (appdir / "server.py").write_text("print('imported v1')\n")
    subprocess.run(["git", "init", "-q"], cwd=appdir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Curator"], cwd=appdir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "curator@test.local"], cwd=appdir, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=appdir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "imported app seed"], cwd=appdir, check=True, capture_output=True)

    cfg["apps"] = [{
        "name": "imported",
        "root": "apps/imported",
        "source": ".",
        "mount": {"kind": "proxy", "cmd": "python server.py --port 8812", "port": 8812},
        "smoke": "python server.py",
    }]
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
    subprocess.run(["git", "add", "gallery.yaml", "apps/imported"], cwd=collection, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "register imported app"], cwd=collection, check=True, capture_output=True)

    (appdir / "server.py").write_text("print('imported v2')\n")
    fid = ledger.save_entry(cfg, "imported", comment="update imported app", ts="t0")
    ledger.add_system_note(cfg, "imported", "Updated imported app.", reply_to=[fid], ts="t1")
    ledger.set_status(cfg, "imported", [fid], "done")

    res = gitmem.commit_run(cfg, "imported", fid, status="done", note_text="Updated imported app.")

    assert res["committed"], res
    assert res["app_commits"][0]["repo"] == str(appdir)
    app_sha = res["app_commits"][0]["sha"]
    assert app_sha == subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=appdir,
                                     capture_output=True, text=True).stdout.strip()
    app_files = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=appdir,
                               capture_output=True, text=True).stdout.split()
    assert app_files == ["server.py"]
    assert f"Curiator-Feedback: {fid}" in _log(appdir, "-1", "--format=%B")

    parent_files = _names_at_head(collection)
    assert "apps/imported" in parent_files
    assert "apps/imported/server.py" not in parent_files
    assert "feedback/app_feedback.sqlite" in parent_files
    body = _log(collection, "-1", "--format=%B")
    assert f"nested app imported@{app_sha}" in body
    assert f"Curiator-Feedback: {fid}" in body
    assert not subprocess.run(["git", "status", "--porcelain"], cwd=appdir,
                              capture_output=True, text=True).stdout.strip()
