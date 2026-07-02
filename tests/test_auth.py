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


def test_is_admin_open_in_none_group_gated_otherwise():
    assert auth.is_admin({"mode": "none"}, None) is True            # solo / your box → open
    assert auth.is_admin({}, None) is True                          # default mode is none
    assert auth.is_admin({"mode": "local", "admin_groups": ["admin"]}, {"groups": ["admin"]}) is True
    assert auth.is_admin({"mode": "local"}, {"groups": ["dev"]}) is False   # default admin group, no match
    assert auth.is_admin({"mode": "local"}, None) is False          # not signed in
    assert auth.is_admin({"mode": "header", "admin_groups": ["ops"]}, {"groups": ["ops", "x"]}) is True


def test_stamp_carries_identity_and_groups():
    assert auth.stamp({"id": "i", "email": "e@x", "name": "N", "groups": ["g"]}) == \
        {"id": "i", "email": "e@x", "name": "N", "groups": ["g"]}   # groups gate elevated agent runs
    assert auth.stamp(None) is None


# ── wiring: config default + ledger provenance ─────────────────────────────
def test_config_auth_defaults_to_none(cfg):
    assert cfg["auth"]["mode"] == "none" and cfg["auth"]["default_user"]


def test_ledger_entry_carries_user(cfg):
    ledger.save_entry(cfg, "sample", comment="hi",
                      user={"id": "u", "email": "u@x.io", "name": "u"}, ts="t")
    assert ledger.load(cfg)["sample"][0]["user"]["email"] == "u@x.io"


# ── local login (built-in username/password) ───────────────────────────────
def test_local_login_required():
    assert auth.login_required({"mode": "local"}) is True


def test_local_verify_inline_users():
    from werkzeug.security import generate_password_hash
    a = {"mode": "local", "users": [{"email": "a@x.io", "name": "A", "groups": ["dev"],
                                     "password_hash": generate_password_hash("pw")}]}
    assert auth.verify_local(a, "a@x.io", "pw") == {"id": "a@x.io", "email": "a@x.io", "name": "A", "groups": ["dev"]}
    assert auth.verify_local(a, "a@x.io", "bad") is None        # wrong password
    assert auth.verify_local(a, "nobody@x.io", "pw") is None    # unknown user


def test_local_users_file_roundtrip(tmp_path):
    from werkzeug.security import generate_password_hash
    f = tmp_path / "users.json"
    auth.save_users_file(str(f), {"u@x.io": {"name": "U", "groups": [],
                                             "password_hash": generate_password_hash("s3cret")}})
    a = {"mode": "local", "users_file": str(f)}
    assert auth.verify_local(a, "u@x.io", "s3cret")["email"] == "u@x.io"
    assert auth.verify_local(a, "u@x.io", "wrong") is None


def test_local_disabled_user_cannot_login_or_keep_session(tmp_path):
    from werkzeug.security import generate_password_hash

    f = tmp_path / "users.json"
    auth.save_users_file(str(f), {"u@x.io": {"name": "U", "groups": ["trusted"],
                                             "password_hash": generate_password_hash("s3cret"),
                                             "disabled": True}})
    a = {"mode": "local", "users_file": str(f)}
    assert auth.verify_local(a, "u@x.io", "s3cret") is None

    app = flask.Flask(__name__); app.secret_key = "t"
    with app.test_request_context():
        flask.session[auth.SESSION_KEY] = {"id": "u@x.io", "email": "u@x.io", "name": "U", "groups": ["trusted"]}
        assert auth.current_user(a) is None
        assert auth.SESSION_KEY not in flask.session


def test_cmd_user_add_hashes_and_verifies(cfg):
    import argparse

    from curiator.cli import cmd_user
    cmd_user(argparse.Namespace(action="add", email="bob@x.io", name="Bob", groups="qa", password="hunter2"))
    uf = cfg["auth"]["users_file"]
    assert "hunter2" not in __import__("pathlib").Path(uf).read_text()   # stored as a hash, never plaintext
    u = auth.verify_local({"mode": "local", "users_file": uf}, "bob@x.io", "hunter2")
    assert u and u["name"] == "Bob" and u["groups"] == ["qa"]


def test_cmd_user_add_update_preserves_name_and_groups(cfg):
    """Re-adding with ONLY a new password must keep name/groups (they gate elevated runs)."""
    import argparse

    from curiator.cli import cmd_user
    a = {"mode": "local", "users_file": cfg["auth"]["users_file"]}
    cmd_user(argparse.Namespace(action="add", email="ann@x.io", name="Ann", groups="admin", password="pw1"))
    cmd_user(argparse.Namespace(action="add", email="ann@x.io", name=None, groups=None, password="pw2"))
    u = auth.verify_local(a, "ann@x.io", "pw2")
    assert u and u["name"] == "Ann" and u["groups"] == ["admin"]    # preserved on update
    assert auth.verify_local(a, "ann@x.io", "pw1") is None          # old password rotated out
    # an explicit --groups still overrides (and empty clears)
    cmd_user(argparse.Namespace(action="add", email="ann@x.io", name=None, groups="dev,ops", password="pw3"))
    assert auth.verify_local(a, "ann@x.io", "pw3")["groups"] == ["dev", "ops"]


def test_cmd_user_passwd_changes_only_password(cfg):
    import argparse

    from curiator.cli import cmd_user
    a = {"mode": "local", "users_file": cfg["auth"]["users_file"]}
    cmd_user(argparse.Namespace(action="add", email="bo@x.io", name="Bo", groups="qa,dev", password="old"))
    rc = cmd_user(argparse.Namespace(action="passwd", email="bo@x.io", name=None, groups=None, password="new"))
    assert rc == 0
    u = auth.verify_local(a, "bo@x.io", "new")
    assert u and u["name"] == "Bo" and u["groups"] == ["qa", "dev"]  # untouched
    assert auth.verify_local(a, "bo@x.io", "old") is None
    # passwd on a non-existent user fails (doesn't create one)
    assert cmd_user(argparse.Namespace(action="passwd", email="ghost@x.io",
                                       name=None, groups=None, password="x")) == 1


def test_cmd_user_disable_enable_preserves_record(cfg, capsys):
    import argparse

    from curiator.cli import cmd_user
    a = {"mode": "local", "users_file": cfg["auth"]["users_file"]}
    cmd_user(argparse.Namespace(action="add", email="cy@x.io", name="Cy", groups="trusted", password="pw"))

    assert cmd_user(argparse.Namespace(action="disable", email="cy@x.io",
                                       name=None, groups=None, password=None)) == 0
    assert auth.verify_local(a, "cy@x.io", "pw") is None
    cmd_user(argparse.Namespace(action="list", email=None, name=None, groups=None, password=None))
    out = capsys.readouterr().out
    assert "cy@x.io" in out and "disabled" in out

    assert cmd_user(argparse.Namespace(action="enable", email="cy@x.io",
                                       name=None, groups=None, password=None)) == 0
    u = auth.verify_local(a, "cy@x.io", "pw")
    assert u and u["name"] == "Cy" and u["groups"] == ["trusted"]


def test_login_rate_limit_locks_then_clears():
    a = {"max_attempts": 3, "lockout_seconds": 60}
    auth.clear_login_failures("1.2.3.4")
    assert auth.rate_limit_status(a, "1.2.3.4") == (False, 0)
    for _ in range(3):
        auth.record_login_failure(a, "1.2.3.4")
    blocked, retry = auth.rate_limit_status(a, "1.2.3.4")
    assert blocked is True and retry > 0                    # locked out after 3 failures
    assert auth.rate_limit_status(a, "5.6.7.8")[0] is False  # a different IP is unaffected
    auth.clear_login_failures("1.2.3.4")                   # success clears the counter
    assert auth.rate_limit_status(a, "1.2.3.4")[0] is False


def test_cmd_auth_sets_mode_preserving_comments(tmp_path, monkeypatch):
    import argparse
    import textwrap

    from curiator.cli import cmd_auth
    g = tmp_path / "gallery.yaml"
    g.write_text(textwrap.dedent('''\
        apps: []
        auth:
          mode: none          # none | local | header | oidc
          default_user: x@y
    '''))
    monkeypatch.setenv("CURIATOR_GALLERY", str(g))
    cmd_auth(argparse.Namespace(mode="local"))
    txt = g.read_text()
    assert "mode: local" in txt and "# none | local | header | oidc" in txt   # changed + comment kept
    assert "default_user: x@y" in txt                                          # rest intact
