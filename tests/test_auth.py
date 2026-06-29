"""auth: identity resolution per mode (none/header directly; oidc claim-mapping + session via a mock),
the provenance stamp, config default, and that the ledger entry carries `user`."""
from __future__ import annotations

import flask

from curiator import auth, ledger


def _ctx(headers):
    return flask.Flask(__name__).test_request_context(headers=headers)


# ── none mode ──────────────────────────────────────────────────────────────
def test_none_mode_default_user():
    u = auth.current_user({"mode": "none", "default_user": "adam@local"})
    assert u == {"id": "adam@local", "email": "adam@local", "name": "adam", "groups": []}


def test_none_mode_fallback_and_no_request_context_needed():
    assert auth.current_user({})["email"] == "anonymous@local"   # works with no flask request at all


# ── header mode (trusted proxy) ────────────────────────────────────────────
def test_header_mode_reads_proxy_headers():
    with _ctx({"X-Auth-Request-User": "u1", "X-Auth-Request-Email": "u1@corp.com",
               "X-Auth-Request-Groups": "eng, admins"}):
        u = auth.current_user({"mode": "header"})
    assert u["id"] == "u1" and u["email"] == "u1@corp.com" and u["groups"] == ["eng", "admins"]


def test_header_mode_custom_header_names():
    with _ctx({"X-User": "bob", "X-Email": "bob@x.io"}):
        u = auth.current_user({"mode": "header", "user_header": "X-User", "email_header": "X-Email"})
    assert u["email"] == "bob@x.io" and u["name"] == "bob"


def test_header_mode_unauthenticated_is_none():
    with _ctx({}):
        assert auth.current_user({"mode": "header"}) is None       # proxy set no headers ⇒ not authenticated


# ── oidc (claim mapping + session, no live IdP) ────────────────────────────
def test_oidc_claim_mapping():
    u = auth.user_from_claims({"sub": "abc", "email": "jane@corp.com", "name": "Jane Doe",
                               "groups": ["team-a", "leads"]})
    assert u == {"id": "abc", "email": "jane@corp.com", "name": "Jane Doe", "groups": ["team-a", "leads"]}


def test_oidc_claim_mapping_fallbacks():
    u = auth.user_from_claims({"sub": "s1", "preferred_username": "kpiter", "roles": "a, b"})
    assert u["name"] == "kpiter" and u["groups"] == ["a", "b"] and u["id"] == "s1"


def test_oidc_session_roundtrip():
    app = flask.Flask(__name__); app.secret_key = "t"
    with app.test_request_context():
        flask.session[auth.SESSION_KEY] = {"id": "z", "email": "z@z", "name": "Z", "groups": []}
        assert auth.current_user({"mode": "oidc"})["email"] == "z@z"


def test_oidc_not_logged_in_is_none():
    app = flask.Flask(__name__); app.secret_key = "t"
    with app.test_request_context():
        assert auth.current_user({"mode": "oidc"}) is None


# ── helpers ────────────────────────────────────────────────────────────────
def test_login_required_only_oidc():
    assert auth.login_required({"mode": "oidc"}) is True
    assert auth.login_required({"mode": "header"}) is False
    assert auth.login_required({"mode": "none"}) is False
    assert auth.login_required({}) is False


def test_stamp_is_id_email_name_only():
    assert auth.stamp({"id": "i", "email": "e@x", "name": "N", "groups": ["g"]}) == \
        {"id": "i", "email": "e@x", "name": "N"}                 # groups stay in the session, not the ledger
    assert auth.stamp(None) is None


# ── wiring: config default + ledger provenance ─────────────────────────────
def test_config_auth_defaults_to_none(cfg):
    assert cfg["auth"]["mode"] == "none" and cfg["auth"]["default_user"]


def test_ledger_entry_carries_user(cfg):
    ledger.save_entry(cfg, "sample", comment="hi",
                      user={"id": "u", "email": "u@x.io", "name": "u"}, ts="t")
    assert ledger.load(cfg)["sample"][0]["user"]["email"] == "u@x.io"
