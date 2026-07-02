"""stats: reproducible collection metrics from the ledger and git log."""
from __future__ import annotations

import csv
import io
import json
import subprocess
import textwrap
from pathlib import Path

from curiator import ledger, stats
from curiator.config import load_config_at


def _seed_two_cycles(cfg):
    fid1 = ledger.save_entry(cfg, "sample", stars=5, comment="fix the chart",
                             screenshot="shots/one.png", ts="2026-07-01T12:00:00+00:00")
    ledger.add_system_note(cfg, "sample", "Fixed.", reply_to=[fid1],
                           ts="2026-07-01T12:05:30+00:00")
    ledger.set_status(cfg, "sample", [fid1], "done")
    fid2 = ledger.save_entry(cfg, "sample", stars=3, comment="needs a filter",
                             ts="2026-07-01T12:10:00+00:00")
    return fid1, fid2


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_collection(root: Path, name: str) -> dict:
    collection = root / name
    (collection / "apps").mkdir(parents=True)
    (collection / "feedback").mkdir()
    (collection / "apps" / "sample.py").write_text("app = object()\n")
    (collection / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            mount: { kind: dash-inproc, module: sample }
            source: apps/sample.py
        feedback:
          dir: feedback
        git:
          commit: true
          branch:
          signoff: true
          include_ledger: true
    """))
    _git(collection, "init", "-q")
    _git(collection, "config", "user.name", "Test Curator")
    _git(collection, "config", "user.email", "curator@test.local")
    _git(collection, "add", "-A")
    _git(collection, "commit", "-q", "-m", "init")
    return load_config_at(collection)


def test_summarize_ledger_counts_cycles_statuses_and_latency(cfg):
    _seed_two_cycles(cfg)

    summary = stats.summarize(cfg, include_git=False)

    assert summary["totals"]["cycles"] == 2
    assert summary["totals"]["open_cycles"] == 1
    assert summary["totals"]["agent_notes"] == 1
    assert summary["totals"]["replied_cycles"] == 1
    assert summary["totals"]["screenshots"] == 1
    assert summary["totals"]["direct_fix_cycles"] == 1
    assert summary["totals"]["direct_fix_rate_percent"] == 50.0
    assert summary["totals"]["proposal_cycles"] == 0
    assert summary["totals"]["human_intervention_cycles"] == 0
    assert summary["status_counts"] == {"done": 1, "new": 1}
    assert summary["reply_latency"]["median_seconds"] == 330
    assert summary["apps"][0]["app"] == "sample"
    assert summary["apps"][0]["reply_rate_percent"] == 50.0


def test_summarize_ledger_counts_proposals_no_dispatch_and_intervention(cfg):
    done = ledger.save_entry(cfg, "sample", comment="fix it")
    ledger.set_status(cfg, "sample", [done], "done")
    proposed = ledger.save_entry(cfg, "sample", comment="needs a plan")
    ledger.set_status(cfg, "sample", [proposed], "awaiting_approval")
    ledger.save_entry(cfg, "sample", comment="anonymous moderation", extra={"status": "held"})
    ledger.save_entry(cfg, "sample", comment="spam", extra={"status": "rejected"})

    summary = stats.summarize(cfg, include_git=False)

    assert summary["totals"]["cycles"] == 4
    assert summary["totals"]["direct_fix_cycles"] == 1
    assert summary["totals"]["direct_fix_rate_percent"] == 25.0
    assert summary["totals"]["proposal_cycles"] == 1
    assert summary["totals"]["proposal_rate_percent"] == 25.0
    assert summary["totals"]["no_dispatch_cycles"] == 1
    assert summary["totals"]["no_dispatch_rate_percent"] == 25.0
    assert summary["totals"]["human_intervention_cycles"] == 3
    assert summary["totals"]["human_intervention_rate_percent"] == 75.0
    assert summary["apps"][0]["status_counts"] == {
        "awaiting_approval": 1,
        "done": 1,
        "held": 1,
        "rejected": 1,
    }


def test_stats_cli_json_is_machine_readable(cfg, capsys):
    from curiator import cli

    _seed_two_cycles(cfg)
    assert cli.main(["stats", "--json", "--no-git"]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["totals"]["cycles"] == 2
    assert out["apps"][0]["status_counts"] == {"done": 1, "new": 1}
    assert "git" not in out


def test_stats_markdown_renders_release_tables(cfg, capsys):
    from curiator import cli

    _seed_two_cycles(cfg)
    summary = stats.summarize(cfg, include_git=False)
    markdown = stats.format_markdown(summary)
    assert "| Feedback cycles | 2 |" in markdown
    assert "| Direct fixes | 1 (50.0%) |" in markdown
    assert "| sample | 2 | 1 (50.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 1 | 50.0% | 5m 30s | done=1, new=1 |" in markdown

    assert cli.main(["stats", "--markdown", "--no-git"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# curIAtor Stats")
    assert "## Per App" in out


def test_stats_csv_renders_app_rows(cfg, capsys):
    from curiator import cli

    _seed_two_cycles(cfg)
    csv_text = stats.format_csv(stats.summarize(cfg, include_git=False))
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert rows[0]["app"] == "sample"
    assert rows[0]["cycles"] == "2"
    assert rows[0]["median_reply_seconds"] == "330.0"
    assert rows[0]["direct_fix_cycles"] == "1"
    assert rows[0]["human_intervention_rate_percent"] == "0.0"

    assert cli.main(["stats", "--csv", "--no-git"]) == 0
    out_rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert out_rows[0]["reply_rate_percent"] == "50.0"
    assert out_rows[0]["status_counts"] == "done=1, new=1"


def test_summarize_git_counts_curator_commits(cfg):
    from curiator import gitmem

    fid, _ = _seed_two_cycles(cfg)
    res = gitmem.commit_run(cfg, "sample", fid, status="done", note_text="Fixed.")
    assert res["committed"], res

    summary = stats.summarize(cfg, include_git=True)
    assert summary["git"]["available"] is True
    assert summary["git"]["head"]
    assert summary["git"]["branch"] in {"main", "master"}
    assert summary["git"]["curator_commits"] == 1
    assert summary["git"]["feedback_ids"] == 1
    assert summary["git"]["apps"] == {"sample": 1}


def test_stats_compare_combines_collection_rows(tmp_path, capsys):
    from curiator import cli, gitmem

    alpha = _make_collection(tmp_path, "alpha")
    beta = _make_collection(tmp_path, "beta")
    fid_alpha, _ = _seed_two_cycles(alpha)
    fid_beta = ledger.save_entry(beta, "sample", stars=4, comment="tighten labels",
                                 ts="2026-07-01T12:00:00+00:00")
    ledger.add_system_note(beta, "sample", "Tightened labels.", reply_to=[fid_beta],
                           ts="2026-07-01T12:01:00+00:00")
    ledger.set_status(beta, "sample", [fid_beta], "done")
    assert gitmem.commit_run(alpha, "sample", fid_alpha, status="done", note_text="Fixed.")["committed"]
    assert gitmem.commit_run(beta, "sample", fid_beta, status="done", note_text="Fixed.")["committed"]

    report = stats.compare([alpha, beta])
    assert report["runner"]["version"]
    assert report["runner"]["git_available"] is True
    assert report["runner"]["git_head"]
    assert isinstance(report["runner"]["git_dirty"], bool)
    assert report["totals"]["collections"] == 2
    assert report["totals"]["cycles"] == 3
    assert report["totals"]["replied_cycles"] == 2
    assert report["totals"]["curator_commits"] == 2
    rows = {row["collection"]: row for row in report["collections"]}
    assert rows["alpha"]["git_head"]
    assert rows["alpha"]["git_branch"] in {"main", "master"}
    assert rows["beta"]["git_head"]
    assert rows["alpha"]["reply_rate_percent"] == 50.0
    assert rows["alpha"]["curator_commits"] == 1
    assert rows["beta"]["reply_rate_percent"] == 100.0
    assert rows["beta"]["median_reply_seconds"] == 60

    markdown = stats.format_compare_markdown(report)
    alpha_ref = f"{rows['alpha']['git_branch']}@{rows['alpha']['git_head']}"
    beta_ref = f"{rows['beta']['git_branch']}@{rows['beta']['git_head']}"
    assert "_Runner: curIAtor" in markdown
    assert "| Collection | Git head | Cycles |" in markdown
    assert f"| alpha | {alpha_ref} | 2 | 1 (50.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 1 | 50.0% | 5m 30s | 1 | 1 |" in markdown
    assert f"| beta | {beta_ref} | 1 | 1 (100.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 1 | 100.0% | 1m | 1 | 1 |" in markdown

    assert cli.main([
        "stats",
        "compare",
        str(Path(alpha["gallery_path"]).parent),
        str(beta["gallery_path"]),
        "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["runner"]["git_head"] == report["runner"]["git_head"]
    assert payload["totals"]["cycles"] == 3
    assert [row["collection"] for row in payload["collections"]] == ["alpha", "beta"]
    assert payload["collections"][0]["git_head"] == rows["alpha"]["git_head"]


def test_stats_compare_csv_keeps_single_collection_csv_unchanged(tmp_path):
    alpha = _make_collection(tmp_path, "alpha")
    _seed_two_cycles(alpha)

    rows = list(csv.DictReader(io.StringIO(stats.format_compare_csv(stats.compare([alpha], include_git=False)))))
    assert rows[0]["collection"] == "alpha"
    assert rows[0]["runner_version"]
    assert rows[0]["runner_git_head"] == ""
    assert rows[0]["git_head"] == ""
    assert rows[0]["curator_commits"] == ""

    app_rows = list(csv.DictReader(io.StringIO(stats.format_csv(stats.summarize(alpha, include_git=False)))))
    assert "app" in app_rows[0]
    assert "collection" not in app_rows[0]
