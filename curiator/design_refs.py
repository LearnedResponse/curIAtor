"""Sanitized external design references carried by feedback entries."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


MAX_DESIGN_REFS = 5
MAX_URL_LENGTH = 2048
MAX_LABEL_LENGTH = 120
MAX_NOTE_LENGTH = 1000
_FIGMA_HOSTS = {"figma.com", "www.figma.com"}
_FIGMA_KINDS = {"design", "file", "proto", "board", "slides", "make"}
_FILE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{4,160}$")
_NODE_ID_RE = re.compile(r"^\d{1,12}(?::\d{1,12})?$|^0:1$")
_SECRET_QUERY_RE = re.compile(r"(?:token|secret|password|credential|api[_-]?key|auth|code)", re.I)


class DesignReferenceError(ValueError):
    """A design reference is unsafe or malformed."""


def _bounded(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _figma_parts(url: str) -> tuple[str, str, str]:
    if not isinstance(url, str):
        raise DesignReferenceError("design reference URL must be text")
    exact = url.strip()
    if not exact or len(exact) > MAX_URL_LENGTH:
        raise DesignReferenceError(f"design reference URL must be 1-{MAX_URL_LENGTH} characters")
    parsed = urlparse(exact)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in _FIGMA_HOSTS:
        raise DesignReferenceError("only https://figma.com design references are supported")
    if parsed.username or parsed.password or parsed.port:
        raise DesignReferenceError("design reference URL must not contain credentials or a custom port")
    for key in parse_qs(parsed.query, keep_blank_values=True):
        if _SECRET_QUERY_RE.search(key):
            raise DesignReferenceError(f"design reference URL contains forbidden query field {key!r}")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0] not in _FIGMA_KINDS:
        raise DesignReferenceError("Figma reference must point to a design, file, board, slide, prototype, or Make file")
    kind = parts[0]
    file_key = parts[1]
    if kind == "design" and len(parts) >= 4 and parts[2] == "branch":
        file_key = parts[3]
    if not _FILE_KEY_RE.fullmatch(file_key):
        raise DesignReferenceError("Figma reference has an invalid file key")

    values = parse_qs(parsed.query).get("node-id") or []
    if kind == "make" and not values:
        node_id = "0:1"
    elif not values:
        raise DesignReferenceError("Figma reference must include a node-id")
    else:
        node_id = str(values[0]).replace("-", ":")
    if not _NODE_ID_RE.fullmatch(node_id):
        raise DesignReferenceError("Figma reference has an invalid node-id")
    return exact, file_key, node_id


def clean_design_ref(raw) -> dict:
    """Validate one Figma URL/dict without copying credentials or provider payloads."""
    item = {"url": raw} if isinstance(raw, str) else raw
    if not isinstance(item, dict):
        raise DesignReferenceError("design reference must be a URL or object")
    provider = str(item.get("provider") or "figma").strip().lower()
    if provider != "figma":
        raise DesignReferenceError(f"unsupported design provider {provider!r}")
    exact, file_key, node_id = _figma_parts(item.get("url"))
    access = str(item.get("access") or "read").strip().lower()
    if access not in {"read", "write"}:
        raise DesignReferenceError("design reference access must be read or write")
    out = {
        "provider": "figma",
        "url": exact,
        "file_key": file_key,
        "node_id": node_id,
        "access": access,
    }
    label = _bounded(item.get("label"), MAX_LABEL_LENGTH)
    note = _bounded(item.get("note"), MAX_NOTE_LENGTH)
    if label:
        out["label"] = label
    if note:
        out["note"] = note
    return out


def clean_design_refs(raw) -> list[dict]:
    """Return a bounded list of validated references, preserving input order."""
    if raw in (None, ""):
        return []
    values = raw if isinstance(raw, list) else [raw]
    if len(values) > MAX_DESIGN_REFS:
        raise DesignReferenceError(f"at most {MAX_DESIGN_REFS} design references may be attached")
    return [clean_design_ref(item) for item in values]


def thread_design_refs(data: dict, key: str, entry: dict) -> list[dict]:
    """Return sanitized references on this entry or its explicit reply thread."""
    items = (data or {}).get(key, []) if isinstance(data, dict) else []
    current = entry.get("id")
    related = {current} if current else set()
    related.update(entry.get("reply_to") or [])
    changed = True
    while changed:
        changed = False
        for item in items:
            if not isinstance(item, dict):
                continue
            iid = item.get("id")
            links = set(item.get("reply_to") or [])
            if iid in related or links & related:
                before = len(related)
                if iid:
                    related.add(iid)
                related.update(links)
                changed = changed or len(related) != before
    selected = [*items, entry] if current else [entry]
    refs = []
    seen = set()
    for item in selected:
        if not isinstance(item, dict) or (item is not entry and item.get("id") not in related):
            continue
        for ref in clean_design_refs(item.get("design_refs")):
            marker = (ref["provider"], ref["url"])
            if marker not in seen:
                refs.append(ref)
                seen.add(marker)
    if len(refs) > MAX_DESIGN_REFS:
        refs = refs[-MAX_DESIGN_REFS:]
    return refs
