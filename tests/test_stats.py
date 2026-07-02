"""stats: reproducible collection metrics from the ledger and git log."""
from __future__ import annotations

import csv
import io
import json

from curiator import ledger, stats


def _seed_two_cycles(cfg):
    fid1 = ledger.save_entry(cfg, "sample", stars=5, comment="fix the chart",
                             screenshot="shots/one.png", ts="2026-07-01T12:00:00+00:00")
    ledger.add_system_note(cfg, "sample", "Fixed.", reply_to=[fid1],
                           ts="2026-07-01T12:05:30+00:00")
    ledger.set_status(cfg, "sample", [fid1], "done")
    fid2 = ledger.save_entry(cfg, "sample", stars=3, comment="needs a filter",
                             ts="2026-07-01T12:10:00+00:00")
    return fid1, fid2


def test_summarize_ledger_counts_cycles_statuses_and_latency(cfg):
    _seed_two_cycles(cfg)

    summary = stats.summarize(cfg, include_git=False)

    assert summary["totals"]["cycles"] == 2
    assert summary["totals"]["open_cycles"] == 1
    assert summary["totals"]["agent_notes"] == 1
    assert summary["totals"]["replied_cycles"] == 1
    assert summary["totals"]["screenshots"] == 1
    assert summary["status_counts"] == {"done": 1, "new": 1}
    assert summary["reply_latency"]["median_seconds"] == 330
    assert summary["apps"][0]["app"] == "sample"
    assert summary["apps"][0]["reply_rate_percent"] == 50.0


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
    assert "| sample | 2 | 1 | 1 | 50.0% | 5m 30s | done=1, new=1 |" in markdown

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
    assert summary["git"]["curator_commits"] == 1
    assert summary["git"]["feedback_ids"] == 1
    assert summary["git"]["apps"] == {"sample": 1}
