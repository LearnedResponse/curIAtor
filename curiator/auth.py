"""auth.py — resolve a *verified* identity per request, for feedback provenance.

curiator RECORDS identity; it never runs its own user database. Three modes (gallery.yaml `auth.mode`):
  none   → a fixed `default_user` (provenance even solo; the default — today's behavior)
  header → trust an edge proxy's OIDC headers (oauth2-proxy / ingress already did the dance) — near-zero code
  oidc   → curiator runs the OIDC auth-code flow itself via authlib (self-hosted, no proxy)

A user is `{id, email, name, groups}`. Roles + reputation are OUT OF SCOPE — we only capture `groups`
for when they arrive. Secrets come from env (`auth.client_secret_env`), NEVER the YAML.
"""
from __future__ import annotations

import os

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
        return session.get(SESSION_KEY)
    return None


def login_required(auth_cfg: dict) -> bool:
    """Does this mode gate feedback behind a curiator login? (oidc yes; none/header resolve transparently.)"""
    return (auth_cfg or {}).get("mode") == "oidc"


def stamp(user: dict | None) -> dict | None:
    """The provenance subset recorded on a ledger entry — {id, email, name} (groups stay in the session)."""
    if not user:
        return None
    return {"id": user.get("id"), "email": user.get("email"), "name": user.get("name")}


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
