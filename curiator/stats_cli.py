"""CLI handler for reproducible ledger/git stats reports."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import stats as stats_mod
from .config import load_config, load_config_at


def _fmt_seconds(seconds) -> str:
    if seconds is None:
        return "n/a"
    seconds = int(round(float(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s" if sec else f"{minutes}m"
    hours, minute = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {minute}m" if minute else f"{hours}h"
    days, hour = divmod(hours, 24)
    return f"{days}d {hour}h" if hour else f"{days}d"


def _fmt_counts(counts: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"


def _fmt_optional_int(value) -> str:
    return "n/a" if value is None else str(value)


def _emit_stats_report(text: str, output: str | None) -> None:
    if output:
        path = Path(output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"curiator: wrote {path}", file=sys.stderr)
        return
    print(text, end="" if text.endswith("\n") else "\n")


def cmd_stats(args) -> int:
    """Emit reproducible collection metrics for release notes and case studies."""
    if args.mode == "compare":
        if args.app:
            print("curiator: `stats compare` cannot be combined with --app")
            return 2
        if not args.galleries:
            print("curiator: `stats compare` needs at least one gallery path")
            return 2
        configs = [load_config_at(gallery) for gallery in args.galleries]
        report = stats_mod.compare(configs, include_git=not args.no_git)
        if args.json:
            _emit_stats_report(json.dumps(report, indent=2, sort_keys=True) + "\n", args.output)
            return 0
        if args.markdown:
            _emit_stats_report(stats_mod.format_compare_markdown(report), args.output)
            return 0
        if args.csv:
            _emit_stats_report(stats_mod.format_compare_csv(report), args.output)
            return 0
        totals = report["totals"]
        lines = [
            "curIAtor stats compare",
            "  totals: "
            f"{totals['collections']} collections, {totals['cycles']} cycles, "
            f"{totals['replied_cycles']} replied ({totals['reply_rate_percent']}%), "
            f"{totals['curator_commits']} curator commits",
        ]
        for row in report["collections"]:
            lines.append(
                f"  {row['collection']}: {row['cycles']} cycles, {row['open_cycles']} open, "
                f"{row['replied_cycles']} replied ({row['reply_rate_percent']}%), "
                f"median reply {_fmt_seconds(row['median_reply_seconds'])}, "
                f"curator commits {_fmt_optional_int(row['curator_commits'])}"
            )
        _emit_stats_report("\n".join(lines) + "\n", args.output)
        return 0

    cfg = load_config()
    summary = stats_mod.summarize(cfg, app=args.app, include_git=not args.no_git)
    if args.json:
        _emit_stats_report(json.dumps(summary, indent=2, sort_keys=True) + "\n", args.output)
        return 0
    if args.markdown:
        _emit_stats_report(stats_mod.format_markdown(summary), args.output)
        return 0
    if args.csv:
        _emit_stats_report(stats_mod.format_csv(summary), args.output)
        return 0

    totals = summary["totals"]
    latency = summary["reply_latency"]
    lines = [
        "curIAtor stats",
        f"  gallery: {summary['gallery']}",
        f"  ledger:  {summary['ledger']}",
        f"  apps:    {summary['apps_with_feedback']} with feedback",
        "  cycles:  "
        f"{totals['cycles']} feedback items, {totals['open_cycles']} open, "
        f"{totals['replied_cycles']} replied ({totals['reply_rate_percent']}%)",
        f"  notes:   {totals['agent_notes']} agent notes",
        f"  media:   {totals['screenshots']} screenshots, {totals['rated_cycles']} rated",
        "  latency: "
        f"median={_fmt_seconds(latency['median_seconds'])}, "
        f"avg={_fmt_seconds(latency['avg_seconds'])}, n={latency['count']}",
        f"  status:  {_fmt_counts(summary['status_counts'])}",
    ]
    if "git" in summary:
        git = summary["git"]
        if git.get("available"):
            latest = git.get("latest") or {}
            suffix = f", latest={latest.get('sha')} {latest.get('subject')}" if latest else ""
            lines.append(
                "  git:     "
                f"{git['curator_commits']} curator commits, {git['revert_commits']} reverts, "
                f"{git['feedback_ids']} feedback ids{suffix}"
            )
        else:
            lines.append(f"  git:     unavailable ({git.get('reason')})")
    lines.extend(["", "per app:"])
    for row in summary["apps"]:
        if not row["entries"]:
            continue
        lat = row["reply_latency"]
        lines.append(
            f"  {row['app']}: {row['cycles']} cycles, {row['open_cycles']} open, "
            f"{row['agent_notes']} notes, {row['replied_cycles']} replied, "
            f"median reply {_fmt_seconds(lat['median_seconds'])}, "
            f"status [{_fmt_counts(row['status_counts'])}]"
        )
    _emit_stats_report("\n".join(lines) + "\n", args.output)
    return 0
