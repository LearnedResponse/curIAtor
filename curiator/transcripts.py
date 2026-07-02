"""Transcript segment sanitization for voice feedback."""
from __future__ import annotations


def bounded_text(value, limit: int) -> str:
    text = "" if value is None else str(value).strip()
    return text[:limit]


def _ms(value, *, seconds: bool) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if seconds:
        n *= 1000.0
    return max(0.0, min(86_400_000.0, n))


def clean_transcript_segments(raw) -> list[dict]:
    """Sanitize optional transcript timing metadata before it enters the durable ledger."""
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:200]:
        if not isinstance(item, dict):
            continue
        text = bounded_text(item.get("text"), 1000)
        if not text:
            continue
        start_ms = _ms(item.get("start_ms"), seconds=False)
        end_ms = _ms(item.get("end_ms"), seconds=False)
        if start_ms is None:
            start_ms = _ms(item.get("start"), seconds=True)
        if end_ms is None:
            end_ms = _ms(item.get("end"), seconds=True)
        seg = {"text": " ".join(text.split())}
        if start_ms is not None:
            seg["start_ms"] = start_ms
        if end_ms is not None:
            seg["end_ms"] = max(start_ms or 0.0, end_ms)
        out.append(seg)
    return out
