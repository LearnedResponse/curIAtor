"""Public shell path helpers for galleries mounted below an origin prefix."""
from __future__ import annotations

from urllib.parse import quote


def normalize_base_path(value: object) -> str:
    """Return ``""`` or a normalized absolute path without a trailing slash."""
    raw = str(value or "").strip()
    if not raw or raw == "/":
        return ""
    if any(token in raw for token in ("://", "?", "#", "\\")):
        raise ValueError(f"invalid shell.base_path: {raw!r}")
    parts = [part for part in raw.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError(f"invalid shell.base_path: {raw!r}")
    return "/" + "/".join(parts)


def shell_base_path(cfg: dict) -> str:
    return normalize_base_path(((cfg.get("shell") or {}).get("base_path")))


def public_path(base_path: str, path: str = "/") -> str:
    """Prefix one origin-local absolute path while leaving external URLs untouched."""
    if path.startswith(("http://", "https://", "//")):
        return path
    base = normalize_base_path(base_path)
    suffix = "/" + str(path or "").lstrip("/")
    if suffix == "/" and base:
        return base + "/"
    return base + suffix


def local_shell_url(cfg: dict, app: str | None = None, path: str | None = None) -> str:
    port = (cfg.get("shell") or {}).get("port", 8200)
    base = f"http://127.0.0.1:{port}"
    target = public_path(shell_base_path(cfg), path or "/")
    if app:
        separator = "&" if "?" in target else "?"
        target += f"{separator}app={quote(str(app), safe='')}"
    return base + target


class PrefixMiddleware:
    """Mount a WSGI application at one configured path without changing its internal routes."""

    def __init__(self, app, base_path: str):
        self.app = app
        self.base_path = normalize_base_path(base_path)

    def __call__(self, environ, start_response):
        if not self.base_path:
            return self.app(environ, start_response)
        path = environ.get("PATH_INFO") or "/"
        if path == self.base_path:
            start_response("308 Permanent Redirect", [("Location", self.base_path + "/")])
            return [b""]
        if not path.startswith(self.base_path + "/"):
            start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"not found"]
        scoped = environ.copy()
        scoped["SCRIPT_NAME"] = (environ.get("SCRIPT_NAME") or "").rstrip("/") + self.base_path
        scoped["PATH_INFO"] = path[len(self.base_path):] or "/"
        return self.app(scoped, start_response)
