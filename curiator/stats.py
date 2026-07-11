"""Collection statistics from the feedback ledger and git-as-memory log."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import csv
import io
import subprocess
from typing import Any

from . import __version__
from . import ledger

OPEN_STATUSES = {"new", "working", "awaiting_approval"}
DIRECT_FIX_STATUSES = {"done"}
PROPOSAL_STATUSES = {"awaiting_approval"}
NO_DISPATCH_STATUSES = {"rejected"}
HUMAN_INTERVENTION_STATUSES = {"awaiting_approval", "held", "rejected"}


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _percent(n: int, denom: int) -> float:
    return round((100.0 * n / denom), 1) if denom else 0.0


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


def _md(value) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _latency_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "avg_seconds": None, "median_seconds": None}
    vals = sorted(values)
    mid = len(vals) // 2
    median = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    return {
        "count": len(vals),
        "avg_seconds": round(sum(vals) / len(vals), 3),
        "median_seconds": round(median, 3),
    }


def _status_metric_fields(statuses: Counter[str], cycles: int) -> dict[str, Any]:
    direct = sum(statuses.get(s, 0) for s in DIRECT_FIX_STATUSES)
    proposals = sum(statuses.get(s, 0) for s in PROPOSAL_STATUSES)
    no_dispatch = sum(statuses.get(s, 0) for s in NO_DISPATCH_STATUSES)
    human = sum(statuses.get(s, 0) for s in HUMAN_INTERVENTION_STATUSES)
    return {
        "direct_fix_cycles": direct,
        "direct_fix_rate_percent": _percent(direct, cycles),
        "proposal_cycles": proposals,
        "proposal_rate_percent": _percent(proposals, cycles),
        "no_dispatch_cycles": no_dispatch,
        "no_dispatch_rate_percent": _percent(no_dispatch, cycles),
        "human_intervention_cycles": human,
        "human_intervention_rate_percent": _percent(human, cycles),
    }


def _entry_key(entry: dict) -> str:
    return str(entry.get("id") or "")


def summarize_ledger(cfg: dict, app: str | None = None) -> dict[str, Any]:
    """Summarize feedback cycles, status distribution, and first-reply latency."""
    raw = ledger.load(cfg)
    if app:
        raw = {app: raw.get(app, [])}

    app_rows = []
    status_total: Counter[str] = Counter()
    kind_total: Counter[str] = Counter()
    author_total: Counter[str] = Counter()
    all_latencies: list[float] = []
    totals = {
        "entries": 0,
        "cycles": 0,
        "open_cycles": 0,
        "agent_notes": 0,
        "replied_cycles": 0,
        "screenshots": 0,
        "rated_cycles": 0,
        "direct_fix_cycles": 0,
        "proposal_cycles": 0,
        "no_dispatch_cycles": 0,
        "human_intervention_cycles": 0,
    }

    for app_key in sorted(raw):
        entries = list(raw.get(app_key) or [])
        feedback = [e for e in entries if e.get("kind") != "system"]
        notes = [e for e in entries if e.get("kind") == "system"]
        by_id = {_entry_key(e): e for e in feedback if _entry_key(e)}
        first_reply: dict[str, datetime] = {}
        for note in notes:
            note_ts = _parse_ts(note.get("ts"))
            if not note_ts:
                continue
            for fid in note.get("reply_to") or []:
                if fid not in by_id:
                    continue
                if fid not in first_reply or note_ts < first_reply[fid]:
                    first_reply[fid] = note_ts

        latencies = []
        for fid, reply_ts in first_reply.items():
            fb_ts = _parse_ts(by_id[fid].get("ts"))
            if not fb_ts:
                continue
            delta = (reply_ts - fb_ts).total_seconds()
            if delta >= 0:
                latencies.append(delta)

        statuses = Counter(str(e.get("status") or "unknown") for e in feedback)
        kinds = Counter(str(e.get("kind") or "unknown") for e in entries)
        authors = Counter(str(e.get("author") or "unknown") for e in entries)
        cycles = len(feedback)
        open_cycles = sum(n for s, n in statuses.items() if s in OPEN_STATUSES)
        screenshots = sum(1 for e in feedback if e.get("screenshot"))
        rated = sum(1 for e in feedback if e.get("stars") is not None)
        status_metrics = _status_metric_fields(statuses, cycles)

        row = {
            "app": app_key,
            "entries": len(entries),
            "cycles": cycles,
            "open_cycles": open_cycles,
            "agent_notes": len(notes),
            "replied_cycles": len(first_reply),
            "reply_rate_percent": _percent(len(first_reply), cycles),
            "screenshots": screenshots,
            "rated_cycles": rated,
            **status_metrics,
            "status_counts": dict(sorted(statuses.items())),
            "kind_counts": dict(sorted(kinds.items())),
            "author_counts": dict(sorted(authors.items())),
            "reply_latency": _latency_summary(latencies),
        }
        app_rows.append(row)

        totals["entries"] += len(entries)
        totals["cycles"] += cycles
        totals["open_cycles"] += open_cycles
        totals["agent_notes"] += len(notes)
        totals["replied_cycles"] += len(first_reply)
        totals["screenshots"] += screenshots
        totals["rated_cycles"] += rated
        totals["direct_fix_cycles"] += status_metrics["direct_fix_cycles"]
        totals["proposal_cycles"] += status_metrics["proposal_cycles"]
        totals["no_dispatch_cycles"] += status_metrics["no_dispatch_cycles"]
        totals["human_intervention_cycles"] += status_metrics["human_intervention_cycles"]
        status_total.update(statuses)
        kind_total.update(kinds)
        author_total.update(authors)
        all_latencies.extend(latencies)

    totals["reply_rate_percent"] = _percent(totals["replied_cycles"], totals["cycles"])
    totals["direct_fix_rate_percent"] = _percent(totals["direct_fix_cycles"], totals["cycles"])
    totals["proposal_rate_percent"] = _percent(totals["proposal_cycles"], totals["cycles"])
    totals["no_dispatch_rate_percent"] = _percent(totals["no_dispatch_cycles"], totals["cycles"])
    totals["human_intervention_rate_percent"] = _percent(totals["human_intervention_cycles"], totals["cycles"])
    return {
        "ledger": str(ledger.path(cfg)),
        "apps_with_feedback": len([row for row in app_rows if row["entries"]]),
        "totals": totals,
        "status_counts": dict(sorted(status_total.items())),
        "kind_counts": dict(sorted(kind_total.items())),
        "author_counts": dict(sorted(author_total.items())),
        "reply_latency": _latency_summary(all_latencies),
        "apps": app_rows,
    }


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _git_text(cwd: Path, *args: str) -> str | None:
    result = _git(cwd, *args)
    return result.stdout.strip() if result.returncode == 0 else None


def summarize_git(cfg: dict) -> dict[str, Any]:
    """Summarize git-as-memory commits. Returns unavailable when cfg repo is not git."""
    root = Path(cfg.get("repo_root", "."))
    if _git(root, "rev-parse", "--git-dir").returncode != 0:
        return {"available": False, "reason": "not a git repo"}

    fmt = "%H%x1f%s%x1f%b%x1e"
    raw = _git(root, "log", "--all", "--grep=Curiator-App:", f"--format={fmt}").stdout
    apps: Counter[str] = Counter()
    feedback_ids = set()
    commits = 0
    reverts = 0
    latest = None
    for chunk in (c for c in raw.split("\x1e") if c.strip()):
        parts = (chunk.strip().split("\x1f") + ["", ""])[:3]
        sha, subject, body = parts
        trailers = {}
        for line in body.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            trailers[key.strip()] = value.strip()
        app = trailers.get("Curiator-App")
        fid = trailers.get("Curiator-Feedback")
        if not app:
            continue
        commits += 1
        apps[app] += 1
        if fid and fid != "-":
            feedback_ids.add(fid)
        if subject.lower().startswith(f"curator({app}): revert"):
            reverts += 1
        if latest is None:
            latest = {"sha": sha[:7], "subject": subject}
    return {
        "available": True,
        "branch": _git_text(root, "branch", "--show-current") or "detached",
        "head": _git_text(root, "rev-parse", "--short", "HEAD"),
        "curator_commits": commits,
        "revert_commits": reverts,
        "feedback_ids": len(feedback_ids),
        "apps": dict(sorted(apps.items())),
        "latest": latest,
    }


def summarize_replays(cfg: dict) -> dict[str, Any]:
    """Aggregate retained replay manifests without opening private provider payloads."""
    from .replay_lab import list_groups

    groups = list_groups(cfg)
    variants = [variant for group in groups for variant in (group.get("variants") or [])]
    results = [variant.get("result") or {} for variant in variants]
    durations = [
        float(variant["duration_seconds"])
        for variant in variants
        if isinstance(variant.get("duration_seconds"), (int, float))
    ]
    browser_passes = sum(1 for result in results if (result.get("browser") or {}).get("ok") is True)
    source_changes = sum(
        1 for result in results
        if (result.get("diff") or {}).get("dirty")
        or (result.get("diff") or {}).get("commits")
        or (result.get("diff") or {}).get("patch")
    )
    accepted = sum(
        1 for group in groups
        if (group.get("review") or {}).get("decision") == "accepted"
        and (group.get("review") or {}).get("variant_id")
    )
    adapters = Counter(
        str(((variant.get("result") or {}).get("effective_profile") or {}).get("adapter")
            or (variant.get("profile") or {}).get("adapter") or "unknown")
        for variant in variants
    )
    return {
        "groups": len(groups),
        "variants": len(variants),
        "accepted_variants": accepted,
        "browser_passes": browser_passes,
        "browser_pass_rate_percent": _percent(browser_passes, len(variants)),
        "source_change_variants": source_changes,
        "source_change_rate_percent": _percent(source_changes, len(variants)),
        "identical_task_groups": sum(
            1 for group in groups
            if (group.get("evidence_consistency") or {}).get("byte_identical_across_variants") is True
        ),
        "status_counts": dict(sorted(Counter(str(group.get("status") or "unknown") for group in groups).items())),
        "exactness_counts": dict(sorted(Counter(str(group.get("exactness") or "unknown") for group in groups).items())),
        "adapter_counts": dict(sorted(adapters.items())),
        "duration": _latency_summary(durations),
    }


def summarize_runner(include_git: bool = True) -> dict[str, Any]:
    """Summarize the curIAtor runner that produced a stats report."""
    out: dict[str, Any] = {"version": __version__}
    if not include_git:
        return {**out, "git_available": False, "reason": "git disabled"}
    root = Path(__file__).resolve().parents[1]
    if _git(root, "rev-parse", "--git-dir").returncode != 0:
        return {**out, "git_available": False, "reason": "not a git repo"}
    dirty = bool(_git_text(root, "status", "--porcelain"))
    return {
        **out,
        "git_available": True,
        "git_branch": _git_text(root, "branch", "--show-current") or "detached",
        "git_head": _git_text(root, "rev-parse", "--short", "HEAD"),
        "git_dirty": dirty,
    }


def summarize(cfg: dict, app: str | None = None, include_git: bool = True) -> dict[str, Any]:
    out = {
        "gallery": cfg.get("gallery_path"),
        "repo_root": cfg.get("repo_root"),
        **summarize_ledger(cfg, app=app),
        "replays": summarize_replays(cfg),
    }
    if include_git:
        out["git"] = summarize_git(cfg)
    return out


def _collection_label(summary: dict[str, Any]) -> str:
    gallery = summary.get("gallery")
    if gallery:
        return Path(gallery).resolve().parent.name
    repo = summary.get("repo_root")
    return Path(repo).resolve().name if repo else "collection"


def _compare_row(summary: dict[str, Any]) -> dict[str, Any]:
    totals = summary["totals"]
    latency = summary["reply_latency"]
    git = summary.get("git") or {}
    git_available = bool(git.get("available"))
    return {
        "collection": _collection_label(summary),
        "gallery": summary.get("gallery"),
        "cycles": totals["cycles"],
        "open_cycles": totals["open_cycles"],
        "replied_cycles": totals["replied_cycles"],
        "reply_rate_percent": totals["reply_rate_percent"],
        "direct_fix_cycles": totals["direct_fix_cycles"],
        "direct_fix_rate_percent": totals["direct_fix_rate_percent"],
        "proposal_cycles": totals["proposal_cycles"],
        "proposal_rate_percent": totals["proposal_rate_percent"],
        "no_dispatch_cycles": totals["no_dispatch_cycles"],
        "no_dispatch_rate_percent": totals["no_dispatch_rate_percent"],
        "human_intervention_cycles": totals["human_intervention_cycles"],
        "human_intervention_rate_percent": totals["human_intervention_rate_percent"],
        "agent_notes": totals["agent_notes"],
        "screenshots": totals["screenshots"],
        "rated_cycles": totals["rated_cycles"],
        "median_reply_seconds": latency["median_seconds"],
        "avg_reply_seconds": latency["avg_seconds"],
        "git_available": git_available,
        "git_branch": git.get("branch") if git_available else None,
        "git_head": git.get("head") if git_available else None,
        "curator_commits": git["curator_commits"] if git_available else None,
        "revert_commits": git["revert_commits"] if git_available else None,
    }


def compare(configs: list[dict], include_git: bool = True) -> dict[str, Any]:
    """Summarize several collections for a release/paper case-study table."""
    summaries = [summarize(cfg, include_git=include_git) for cfg in configs]
    rows = [_compare_row(summary) for summary in summaries]
    cycles = sum(row["cycles"] for row in rows)
    replied = sum(row["replied_cycles"] for row in rows)
    direct = sum(row["direct_fix_cycles"] for row in rows)
    proposals = sum(row["proposal_cycles"] for row in rows)
    no_dispatch = sum(row["no_dispatch_cycles"] for row in rows)
    human = sum(row["human_intervention_cycles"] for row in rows)
    return {
        "runner": summarize_runner(include_git=include_git),
        "collections": rows,
        "totals": {
            "collections": len(rows),
            "cycles": cycles,
            "open_cycles": sum(row["open_cycles"] for row in rows),
            "replied_cycles": replied,
            "reply_rate_percent": _percent(replied, cycles),
            "direct_fix_cycles": direct,
            "direct_fix_rate_percent": _percent(direct, cycles),
            "proposal_cycles": proposals,
            "proposal_rate_percent": _percent(proposals, cycles),
            "no_dispatch_cycles": no_dispatch,
            "no_dispatch_rate_percent": _percent(no_dispatch, cycles),
            "human_intervention_cycles": human,
            "human_intervention_rate_percent": _percent(human, cycles),
            "agent_notes": sum(row["agent_notes"] for row in rows),
            "curator_commits": sum(row["curator_commits"] or 0 for row in rows),
        },
    }


def _fmt_optional_int(value) -> str:
    return "n/a" if value is None else str(value)


def _fmt_git_ref(row: dict[str, Any]) -> str:
    head = row.get("git_head")
    if not head:
        return "n/a"
    branch = row.get("git_branch")
    return f"{branch}@{head}" if branch else str(head)


def _fmt_runner_ref(runner: dict[str, Any]) -> str:
    version = runner.get("version") or "unknown"
    if not runner.get("git_available"):
        return f"curIAtor {version}"
    ref = _fmt_git_ref({"git_branch": runner.get("git_branch"), "git_head": runner.get("git_head")})
    state = "dirty" if runner.get("git_dirty") else "clean"
    return f"curIAtor {version}, {ref}, {state}"


def format_compare_markdown(report: dict[str, Any]) -> str:
    """Render collection-level comparison rows for papers and release notes."""
    lines = [
        "# curIAtor Stats Compare",
        "",
        f"_Runner: {_md(_fmt_runner_ref(report.get('runner') or {}))}._",
        "",
        "| Collection | Git head | Cycles | Direct fixes | Proposals | No dispatch | Human intervention | Replied | Reply rate | Median reply | Agent notes | Curator commits |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["collections"]:
        lines.append(
            f"| {_md(row['collection'])} | {_md(_fmt_git_ref(row))} | {row['cycles']} | "
            f"{row['direct_fix_cycles']} ({row['direct_fix_rate_percent']}%) | "
            f"{row['proposal_cycles']} ({row['proposal_rate_percent']}%) | "
            f"{row['no_dispatch_cycles']} ({row['no_dispatch_rate_percent']}%) | "
            f"{row['human_intervention_cycles']} ({row['human_intervention_rate_percent']}%) | "
            f"{row['replied_cycles']} | {row['reply_rate_percent']}% | "
            f"{_fmt_seconds(row['median_reply_seconds'])} | {row['agent_notes']} | "
            f"{_fmt_optional_int(row['curator_commits'])} |"
        )
    totals = report["totals"]
    lines.extend([
        "",
        f"_Totals: {totals['collections']} collections, {totals['cycles']} cycles, "
        f"{totals['replied_cycles']} replied ({totals['reply_rate_percent']}%), "
        f"{totals['direct_fix_cycles']} direct fixes ({totals['direct_fix_rate_percent']}%), "
        f"{totals['proposal_cycles']} proposals ({totals['proposal_rate_percent']}%), "
        f"{totals['human_intervention_cycles']} human intervention ({totals['human_intervention_rate_percent']}%), "
        f"{totals['curator_commits']} curator commits._",
    ])
    return "\n".join(lines) + "\n"


def format_compare_csv(report: dict[str, Any]) -> str:
    """Render collection-level comparison rows as CSV."""
    buf = io.StringIO()
    fieldnames = [
        "collection",
        "runner_version",
        "runner_git_branch",
        "runner_git_head",
        "runner_git_dirty",
        "gallery",
        "cycles",
        "open_cycles",
        "replied_cycles",
        "reply_rate_percent",
        "direct_fix_cycles",
        "direct_fix_rate_percent",
        "proposal_cycles",
        "proposal_rate_percent",
        "no_dispatch_cycles",
        "no_dispatch_rate_percent",
        "human_intervention_cycles",
        "human_intervention_rate_percent",
        "agent_notes",
        "screenshots",
        "rated_cycles",
        "median_reply_seconds",
        "avg_reply_seconds",
        "git_available",
        "git_branch",
        "git_head",
        "curator_commits",
        "revert_commits",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    runner = report.get("runner") or {}
    for row in report["collections"]:
        writer.writerow({
            "runner_version": runner.get("version"),
            "runner_git_branch": runner.get("git_branch"),
            "runner_git_head": runner.get("git_head"),
            "runner_git_dirty": runner.get("git_dirty"),
            **row,
        })
    return buf.getvalue()


def format_markdown(summary: dict[str, Any]) -> str:
    """Render a stable Markdown table for release notes and papers."""
    totals = summary["totals"]
    latency = summary["reply_latency"]
    lines = [
        "# curIAtor Stats",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Apps with feedback | {summary['apps_with_feedback']} |",
        f"| Feedback cycles | {totals['cycles']} |",
        f"| Open cycles | {totals['open_cycles']} |",
        f"| Replied cycles | {totals['replied_cycles']} ({totals['reply_rate_percent']}%) |",
        f"| Direct fixes | {totals['direct_fix_cycles']} ({totals['direct_fix_rate_percent']}%) |",
        f"| Proposals awaiting approval | {totals['proposal_cycles']} ({totals['proposal_rate_percent']}%) |",
        f"| Closed without dispatch | {totals['no_dispatch_cycles']} ({totals['no_dispatch_rate_percent']}%) |",
        f"| Human intervention | {totals['human_intervention_cycles']} ({totals['human_intervention_rate_percent']}%) |",
        f"| Agent notes | {totals['agent_notes']} |",
        f"| Screenshots | {totals['screenshots']} |",
        f"| Rated cycles | {totals['rated_cycles']} |",
        f"| Median first reply | {_fmt_seconds(latency['median_seconds'])} |",
        f"| Average first reply | {_fmt_seconds(latency['avg_seconds'])} |",
        f"| Status counts | {_md(_fmt_counts(summary['status_counts']))} |",
        "",
        "## Per App",
        "",
        "| App | Cycles | Direct fixes | Proposals | No dispatch | Human intervention | Replied | Reply rate | Median reply | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    rows = [row for row in summary["apps"] if row["entries"]]
    if rows:
        for row in rows:
            lat = row["reply_latency"]
            lines.append(
                f"| {_md(row['app'])} | {row['cycles']} | "
                f"{row['direct_fix_cycles']} ({row['direct_fix_rate_percent']}%) | "
                f"{row['proposal_cycles']} ({row['proposal_rate_percent']}%) | "
                f"{row['no_dispatch_cycles']} ({row['no_dispatch_rate_percent']}%) | "
                f"{row['human_intervention_cycles']} ({row['human_intervention_rate_percent']}%) | "
                f"{row['replied_cycles']} | {row['reply_rate_percent']}% | "
                f"{_fmt_seconds(lat['median_seconds'])} | {_md(_fmt_counts(row['status_counts']))} |"
            )
    else:
        lines.append("| n/a | 0 | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | 0 | 0.0% | n/a | none |")

    if "git" in summary:
        git = summary["git"]
        lines.extend(["", "## Git", "", "| Metric | Value |", "|---|---:|"])
        if git.get("available"):
            lines.extend([
                f"| Branch | {_md(git.get('branch') or 'detached')} |",
                f"| Head | {_md(git.get('head') or 'unknown')} |",
                f"| Curator commits | {git['curator_commits']} |",
                f"| Revert commits | {git['revert_commits']} |",
                f"| Feedback ids | {git['feedback_ids']} |",
                f"| Apps | {_md(_fmt_counts(git.get('apps') or {}))} |",
            ])
            latest = git.get("latest") or {}
            if latest:
                lines.append(f"| Latest | {_md(latest.get('sha'))} {_md(latest.get('subject'))} |")
        else:
            lines.append(f"| Available | no ({_md(git.get('reason'))}) |")
    return "\n".join(lines) + "\n"


def format_csv(summary: dict[str, Any]) -> str:
    """Render app-level metrics as CSV for spreadsheets and plotting scripts."""
    buf = io.StringIO()
    fieldnames = [
        "app",
        "entries",
        "cycles",
        "open_cycles",
        "replied_cycles",
        "reply_rate_percent",
        "direct_fix_cycles",
        "direct_fix_rate_percent",
        "proposal_cycles",
        "proposal_rate_percent",
        "no_dispatch_cycles",
        "no_dispatch_rate_percent",
        "human_intervention_cycles",
        "human_intervention_rate_percent",
        "agent_notes",
        "screenshots",
        "rated_cycles",
        "median_reply_seconds",
        "avg_reply_seconds",
        "status_counts",
        "curator_commits",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    git_apps = ((summary.get("git") or {}).get("apps") or {}) if (summary.get("git") or {}).get("available") else {}
    rows = [row for row in summary["apps"] if row["entries"]]
    for row in rows:
        latency = row["reply_latency"]
        writer.writerow({
            "app": row["app"],
            "entries": row["entries"],
            "cycles": row["cycles"],
            "open_cycles": row["open_cycles"],
            "replied_cycles": row["replied_cycles"],
            "reply_rate_percent": row["reply_rate_percent"],
            "direct_fix_cycles": row["direct_fix_cycles"],
            "direct_fix_rate_percent": row["direct_fix_rate_percent"],
            "proposal_cycles": row["proposal_cycles"],
            "proposal_rate_percent": row["proposal_rate_percent"],
            "no_dispatch_cycles": row["no_dispatch_cycles"],
            "no_dispatch_rate_percent": row["no_dispatch_rate_percent"],
            "human_intervention_cycles": row["human_intervention_cycles"],
            "human_intervention_rate_percent": row["human_intervention_rate_percent"],
            "agent_notes": row["agent_notes"],
            "screenshots": row["screenshots"],
            "rated_cycles": row["rated_cycles"],
            "median_reply_seconds": latency["median_seconds"] if latency["median_seconds"] is not None else "",
            "avg_reply_seconds": latency["avg_seconds"] if latency["avg_seconds"] is not None else "",
            "status_counts": _fmt_counts(row["status_counts"]),
            "curator_commits": git_apps.get(row["app"], 0),
        })
    return buf.getvalue()
