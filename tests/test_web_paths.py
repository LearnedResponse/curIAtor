from io import BytesIO

import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response

from curiator.web_paths import PrefixMiddleware, local_shell_url, normalize_base_path, public_path


def test_normalize_and_join_base_paths():
    assert normalize_base_path(None) == ""
    assert normalize_base_path("/") == ""
    assert normalize_base_path("gallery/sietch/") == "/gallery/sietch"
    assert public_path("/gallery/sietch", "/api/bootstrap") == "/gallery/sietch/api/bootstrap"
    assert public_path("/gallery/sietch", "/") == "/gallery/sietch/"
    assert public_path("/gallery/sietch", "https://example.test/x") == "https://example.test/x"


@pytest.mark.parametrize("value", ["../gallery", "/gallery/../x", "https://example.test", "/x?q=1"])
def test_invalid_base_paths_are_rejected(value):
    with pytest.raises(ValueError, match="invalid shell.base_path"):
        normalize_base_path(value)


def test_local_shell_url_includes_prefix_and_app_query():
    cfg = {"shell": {"port": 8310, "base_path": "/gallery/aviato"}}
    assert local_shell_url(cfg) == "http://127.0.0.1:8310/gallery/aviato/"
    assert local_shell_url(cfg, app="react detail") == \
        "http://127.0.0.1:8310/gallery/aviato/?app=react%20detail"
    assert local_shell_url(cfg, path="/reload/react_detail") == \
        "http://127.0.0.1:8310/gallery/aviato/reload/react_detail"


def test_prefix_middleware_scopes_path_and_script_name():
    def app(environ, start_response):
        start_response("200 OK", [("Content-Type", "text/plain")])
        return [f"{environ['SCRIPT_NAME']}|{environ['PATH_INFO']}".encode()]

    client = Client(PrefixMiddleware(app, "/gallery/demo"), Response)
    assert client.get("/gallery/demo/api/bootstrap").get_data(as_text=True) == \
        "/gallery/demo|/api/bootstrap"
    redirect = client.get("/gallery/demo")
    assert redirect.status_code == 308
    assert redirect.headers["Location"] == "/gallery/demo/"
    assert client.get("/api/bootstrap").status_code == 404


def test_prefix_middleware_preserves_existing_script_name():
    captured = {}

    def app(environ, start_response):
        captured.update(environ)
        start_response("204 No Content", [])
        return []

    middleware = PrefixMiddleware(app, "/gallery/demo")
    middleware({
        "REQUEST_METHOD": "GET",
        "SCRIPT_NAME": "/edge",
        "PATH_INFO": "/gallery/demo/",
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.url_scheme": "http",
        "wsgi.input": BytesIO(),
    }, lambda _status, _headers: None)
    assert captured["SCRIPT_NAME"] == "/edge/gallery/demo"
    assert captured["PATH_INFO"] == "/"
