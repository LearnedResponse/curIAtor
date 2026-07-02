"""Screenshot annotation sanitization shared by the shell and CLI."""
from __future__ import annotations


def _clamp01(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, n))


def _short_text(value, limit: int = 240) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def clean_annotations(raw) -> list[dict]:
    """Sanitize optional screenshot annotation metadata before it enters the durable ledger."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw[:50]:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool")
        if tool not in {"box", "arrow", "pin", "redact"}:
            continue
        mark = {"tool": tool}
        for field in ("x1", "y1", "x2", "y2"):
            n = _clamp01(item.get(field))
            if n is not None:
                mark[field] = n
        if "x1" not in mark or "y1" not in mark:
            continue
        if tool == "pin":
            try:
                mark["n"] = max(1, min(99, int(item.get("n") or 1)))
            except (TypeError, ValueError):
                mark["n"] = 1
        note = _short_text(item.get("note"), 500)
        if note:
            mark["note"] = " ".join(note.split())
        if tool != "redact" and isinstance(item.get("target"), dict):
            target = item["target"]
            clean_target: dict = {}
            for field in ("selector", "tag", "id", "data_testid", "role"):
                text = _short_text(target.get(field))
                if text:
                    clean_target[field] = text
            classes = target.get("classes")
            if isinstance(classes, list):
                clean_target["classes"] = [c for c in (_short_text(v, 80) for v in classes[:5]) if c]
            if clean_target:
                mark["target"] = clean_target
        out.append(mark)
    return out
