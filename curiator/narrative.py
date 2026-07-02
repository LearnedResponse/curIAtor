"""Build an ordered voice+annotation narrative from shared-clock feedback fields."""
from __future__ import annotations

from math import isfinite


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if isfinite(n) else None


def _interval(item: dict) -> tuple[float, float] | None:
    start = _number(item.get("start_ms"))
    end = _number(item.get("end_ms"))
    if start is None and end is None:
        return None
    if start is None:
        start = end
    if end is None:
        end = start
    assert start is not None and end is not None
    return (start, max(start, end))


def _overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return b[0] <= a[1] and a[0] <= b[1]


def _label(mark: dict, idx: int) -> str:
    if mark.get("tool") == "pin" and mark.get("n"):
        return f"pin {mark.get('n')}"
    return f"mark {idx}"


def build_narrative(annotations, transcript_segments) -> list[dict]:
    """Pair timed annotation marks with transcript segments that overlap them.

    Returns structured rows sorted by mark time. Untimed marks are skipped because they cannot be
    aligned to speech; timed marks with no overlapping speech are retained so the task bundle still
    shows sequence.
    """
    if not isinstance(annotations, list) or not isinstance(transcript_segments, list):
        return []
    segments = []
    for idx, seg in enumerate(transcript_segments[:200], start=1):
        if not isinstance(seg, dict):
            continue
        interval = _interval(seg)
        text = str(seg.get("text") or "").strip()
        if interval is None or not text:
            continue
        segments.append({"index": idx, "interval": interval, "text": " ".join(text.split())})

    rows = []
    for idx, mark in enumerate(annotations[:50], start=1):
        if not isinstance(mark, dict):
            continue
        interval = _interval(mark)
        if interval is None:
            continue
        matches = [seg for seg in segments if _overlaps(interval, seg["interval"])]
        row = {
            "mark_index": idx,
            "label": _label(mark, idx),
            "tool": mark.get("tool") or "mark",
            "start_ms": interval[0],
            "end_ms": interval[1],
            "text": " ".join(seg["text"] for seg in matches),
            "segment_indexes": [seg["index"] for seg in matches],
        }
        note = str(mark.get("note") or "").strip()
        if note:
            row["note"] = " ".join(note.split())
        target = mark.get("target") if isinstance(mark.get("target"), dict) else None
        if target and mark.get("tool") != "redact":
            row["target"] = {k: v for k, v in target.items() if k in {"selector", "tag", "data_testid", "role"} and v}
        rows.append(row)
    rows.sort(key=lambda row: (row["start_ms"], row["mark_index"]))
    return rows
