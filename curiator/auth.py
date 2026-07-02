"""auth.py — resolve a *verified* identity per request, for feedback provenance.

curiator RECORDS identity; it doesn't run a user database it doesn't have to. Modes (gallery.yaml `auth.mode`):
  none   → a fixed `default_user` (provenance even solo; the default — today's behavior)
  header → trust an edge proxy's OIDC headers (oauth2-proxy / ingress already did the dance) — near-zero code
  oidc   → curiator runs the OIDC auth-code flow itself via authlib (self-hosted, no proxy)
  local  → a built-in username/password login form against a hashed-password user file (managed by
           `curiator user add`) — for self-hosted installs with no IdP and no proxy

`auth.allow_anonymous: true` may be paired with local/oidc for hosted galleries: logged-out feedback
is accepted only into the held moderation queue, never directly dispatched.

A user is `{id, email, name, groups}`. Roles + reputation are OUT OF SCOPE — we only capture `groups`
for when they arrive. OIDC secrets come from env (`auth.client_secret_env`), NEVER the YAML; local
passwords are stored only as hashes (werkzeug), in a gitignored file.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from flask import has_request_context, redirect, request, session, url_for

SESSION_KEY = "curiator_user"
_OIDC_NAME = "curiator_idp"


def _norm(uid, email, name, groups) -> dict:
    email = email or uid or ""
    return {
        "id": uid or email or "anonymous",
        "email": email,
        "name": name or (email.split("@")[0] if email else (uid or "anonymous")),
        "groups": list(groups or []),
    }


def user_from_claims(claims: dict) -> dict:
    """Map OIDC ID-token / userinfo claims → a curiator user. Pure + testable (no IdP needed)."""
    groups = claims.get("groups") or claims.get("roles") or []
    if isinstance(groups, str):
        groups = [g.strip() for g in groups.split(",") if g.strip()]
    return _norm(claims.get("sub"), claims.get("email"),
                 claims.get("name") or claims.get("preferred_username"), list(groups))


def _from_headers(a: dict) -> dict | None:
    uid = request.headers.get(a.get("user_header", "X-Auth-Request-User"))
    email = request.headers.get(a.get("email_header", "X-Auth-Request-Email"))
    raw = request.headers.get(a.get("groups_header", "X-Auth-Request-Groups"), "")
    if not (uid or email):
        return None                                       # the proxy didn't authenticate this request
    groups = [g.strip() for g in raw.split(",") if g.strip()]
    return _norm(uid, email, None, groups)


def current_user(auth_cfg: dict) -> dict | None:
    """The verified user for the current request, or None (header/oidc and not authenticated)."""
    a = auth_cfg or {}
    mode = a.get("mode", "none")
    if mode == "none":
        u = a.get("default_user") or "anonymous@local"
        return _norm(u, u, None, [])
    if not has_request_context():
        return None
    if mode == "header":
        return _from_headers(a)
    if mode == "oidc":
        return session.get(SESSION_KEY)                   # set on a successful OIDC callback
    if mode == "local":
        u = session.get(SESSION_KEY)                      # set on a successful local form login
        if not u:
            return None
        rec = _local_users(a).get(u.get("email") or u.get("id"))
        if not rec or rec.get("disabled"):
            session.pop(SESSION_KEY, None)
            return None
        return u
    return None


def login_required(auth_cfg: dict) -> bool:
    """Does this mode gate feedback behind a curiator login? (oidc/local yes; none/header resolve transparently.)"""
    return (auth_cfg or {}).get("mode") in ("oidc", "local")


def allow_anonymous_feedback(auth_cfg: dict) -> bool:
    """May logged-out users leave feedback in an otherwise login-gated gallery?

    This only applies to explicit hosted modes. `auth.mode: none` keeps its existing clone-and-run
    behavior, while `local|oidc + allow_anonymous: true` means anonymous feedback is accepted into a
    held moderation queue rather than dispatched.
    """
    a = auth_cfg or {}
    return a.get("mode") in ("local", "oidc") and bool(a.get("allow_anonymous"))


def anonymous_user() -> dict:
    return _norm("anonymous", "", "anonymous", [])


def is_admin(auth_cfg: dict, user: dict | None) -> bool:
    """May this user change gallery-wide settings (e.g. the agent provider / trust level)? In `none` mode
    there's no auth — it's your box, so yes. Otherwise the user's groups must intersect `auth.admin_groups`
    (default ['admin']) — the same trusted-group idea that gates elevated agent runs."""
    a = auth_cfg or {}
    if a.get("mode", "none") == "none":
        return True
    if not user:
        return False
    return bool(set(user.get("groups") or []) & set(a.get("admin_groups") or ["admin"]))


def stamp(user: dict | None) -> dict | None:
    """The identity subset recorded on a ledger entry — {id, email, name, groups}. `groups` carry the
    author's authorization context (e.g. `agent.elevated` trusted-group gating), not just provenance."""
    if not user:
        return None
    return {"id": user.get("id"), "email": user.get("email"), "name": user.get("name"),
            "groups": list(user.get("groups") or [])}


# ─────────────────────────── local login (built-in, for self-hosted installs) ───────────────────────────
def load_users_file(path: str | None) -> dict:
    """The local user store: {email: {name, password_hash, groups, disabled?}}. Empty if absent/unreadable."""
    if not path or not Path(path).exists():
        return {}
    try:
        return json.loads(Path(path).read_text()) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_users_file(path: str, users: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(users, indent=2) + "\n")
    try:
        p.chmod(0o600)                                    # password hashes — keep it owner-only
    except OSError:
        pass


def _local_users(auth_cfg: dict) -> dict:
    """Merge the managed users_file (the CLI's `curiator user add`) with any inline `auth.users` list."""
    users = dict(load_users_file((auth_cfg or {}).get("users_file")))
    for u in (auth_cfg or {}).get("users") or []:
        if u.get("email"):
            users[u["email"]] = {"name": u.get("name"), "groups": u.get("groups") or [],
                                 "password_hash": u.get("password_hash")}
    return users


def verify_local(auth_cfg: dict, email: str, password: str) -> dict | None:
    """Check email + password against the local store. Returns the user (no hash), or None."""
    from werkzeug.security import check_password_hash
    rec = _local_users(auth_cfg).get((email or "").strip())
    if rec and rec.get("disabled"):
        return None
    if not (rec and rec.get("password_hash") and password):
        return None
    if not check_password_hash(rec["password_hash"], password):
        return None
    return _norm(email, email, rec.get("name"), rec.get("groups"))


# ── login rate limit (brute-force lockout for the local portal) ──
# In-memory, per key (the client IP), in the single shell process. A sliding window of recent failures;
# once `max_attempts` failures land within `lockout_seconds`, the key is blocked until the oldest ages out.
_LOGIN_FAILS: dict = {}
_LOGIN_LOCK = threading.Lock()


def _rl_params(auth_cfg) -> tuple[int, float]:
    a = auth_cfg or {}
    return int(a.get("max_attempts", 5)), float(a.get("lockout_seconds", 300))


def rate_limit_status(auth_cfg, key) -> tuple[bool, int]:
    """(blocked, retry_after_seconds) for a login `key` (e.g. the client IP)."""
    maxn, window = _rl_params(auth_cfg)
    now = time.monotonic()
    with _LOGIN_LOCK:
        fails = [t for t in _LOGIN_FAILS.get(key, []) if now - t < window]
        _LOGIN_FAILS[key] = fails
        if len(fails) >= maxn:
            return True, int(window - (now - fails[0])) + 1
        return False, 0


def record_login_failure(auth_cfg, key) -> None:
    _, window = _rl_params(auth_cfg)
    now = time.monotonic()
    with _LOGIN_LOCK:
        fails = [t for t in _LOGIN_FAILS.get(key, []) if now - t < window]
        fails.append(now)
        _LOGIN_FAILS[key] = fails


def clear_login_failures(key) -> None:
    with _LOGIN_LOCK:
        _LOGIN_FAILS.pop(key, None)


# ─────────────────────────────── OIDC flow (authlib) ───────────────────────────────
def _oauth(auth_cfg: dict, flask_app):
    if getattr(flask_app, "_curiator_oauth", None) is None:
        from authlib.integrations.flask_client import OAuth          # lazy — only the oidc path needs authlib
        oauth = OAuth(flask_app)
        oauth.register(
            name=_OIDC_NAME,
            client_id=auth_cfg["client_id"],
            client_secret=os.environ.get(auth_cfg.get("client_secret_env", "CURIATOR_OIDC_SECRET")),
            server_metadata_url=auth_cfg["issuer"].rstrip("/") + "/.well-known/openid-configuration",
            client_kwargs={"scope": auth_cfg.get("scope", "openid email profile")},
        )
        flask_app._curiator_oauth = oauth
    return flask_app._curiator_oauth


def register_oidc(auth_cfg: dict, flask_app) -> None:
    """Wire /login, /auth/callback, /logout for the self-hosted OIDC auth-code flow."""

    @flask_app.route("/login")
    def _login():
        client = getattr(_oauth(auth_cfg, flask_app), _OIDC_NAME)
        return client.authorize_redirect(url_for("_oidc_callback", _external=True))

    @flask_app.route("/auth/callback")
    def _oidc_callback():
        client = getattr(_oauth(auth_cfg, flask_app), _OIDC_NAME)
        token = client.authorize_access_token()            # authlib validates the id_token signature + claims
        claims = token.get("userinfo") or {}
        session[SESSION_KEY] = user_from_claims(dict(claims))
        return redirect("/")

    @flask_app.route("/logout")
    def _logout():
        session.pop(SESSION_KEY, None)
        return redirect("/")
