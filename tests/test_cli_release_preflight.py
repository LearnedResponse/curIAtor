"""CLI release preflight: validate nested gallery repos before publishing."""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_gallery(tmp_path: Path, name: str = "curiator-demo") -> Path:
    repo = tmp_path / "galleries" / name
    (repo / "apps").mkdir(parents=True)
    (repo / "feedback").mkdir()
    (repo / "apps" / "sample.py").write_text("app = object()\n")
    (repo / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            mount: { kind: dash-inproc, module: sample }
            source: apps/sample.py
        runner:
          mode: pinned
        feedback:
          dir: feedback
        shell:
          port: 8399
    """))
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test Curator")
    _git(repo, "config", "user.email", "curator@test.local")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_release_preflight_checks_nested_gallery(tmp_path, monkeypatch, capsys):
    from curiator import cli

    _make_gallery(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["galleries"][0]["doctor"]["ok"] is True
    assert payload["galleries"][0]["smoke"]["ok"] is True


def test_release_preflight_json_output_writes_evidence_file(tmp_path, monkeypatch, capsys):
    from curiator import cli

    _make_gallery(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)
    out_path = tmp_path / "evidence" / "release-preflight.json"

    assert cli.main([
        "release-preflight",
        "--gallery", "curiator-demo",
        "--no-smoke",
        "--json",
        "--output", str(out_path),
    ]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"curiator: wrote {out_path}" in captured.err
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["checks"]["smoke"] is False
    assert payload["galleries"][0]["name"] == "curiator-demo"


def test_release_preflight_output_keeps_human_summary(tmp_path, monkeypatch, capsys):
    from curiator import cli

    _make_gallery(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)
    out_path = tmp_path / "evidence" / "release-preflight.json"

    assert cli.main([
        "release-preflight",
        "--gallery", "curiator-demo",
        "--no-smoke",
        "--output", str(out_path),
    ]) == 0

    captured = capsys.readouterr()
    assert "curiator: release preflight OK [nested] (1/1 galleries)" in captured.out
    assert f"curiator: wrote {out_path}" in captured.err
    assert json.loads(out_path.read_text(encoding="utf-8"))["galleries"][0]["name"] == "curiator-demo"


def test_release_preflight_can_include_optional_public_galleries(tmp_path, monkeypatch, capsys):
    from curiator import cli

    required = ["curiator-aviato", "curiator-ot", "curiator-geometry"]
    optional = ["curiator-finance", "curiator-phylogenetics"]
    for name in [*required, *optional]:
        _make_gallery(tmp_path, name=name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["release-preflight", "--no-smoke", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [g["name"] for g in payload["galleries"]] == required
    assert payload["checks"]["include_optional"] is False

    assert cli.main(["release-preflight", "--include-optional", "--no-smoke", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [g["name"] for g in payload["galleries"]] == [*required, *optional]
    assert payload["checks"]["include_optional"] is True


def test_release_preflight_can_run_http_smoke(tmp_path, monkeypatch, capsys):
    from curiator import cli

    _make_gallery(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)
    calls = []

    def fake_smoke_results(cfg, app=None, jobs=1, *, http=False):
        calls.append({"gallery": cfg["gallery_path"], "http": http})
        result = {
            "app": "sample",
            "smoke": "python -m py_compile apps/sample.py",
            "ok": True,
            "message": "ok",
        }
        if http:
            result["http_smoke"] = {
                "ok": True,
                "url": "http://127.0.0.1:8800/healthz",
                "message": "HTTP 204",
            }
        return [result]

    monkeypatch.setattr(cli, "_smoke_results", fake_smoke_results)

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--http-smoke", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["checks"]["smoke"] is True
    assert payload["checks"]["http_smoke"] is True
    assert calls == [{"gallery": str(tmp_path / "galleries" / "curiator-demo" / "gallery.yaml"), "http": True}]
    assert payload["galleries"][0]["smoke"]["results"][0]["http_smoke"]["url"].endswith("/healthz")


def test_release_preflight_rejects_http_smoke_without_smoke(tmp_path, monkeypatch, capsys):
    from curiator import cli

    _make_gallery(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--no-smoke", "--http-smoke"]) == 2
    out = capsys.readouterr().out
    assert "--http-smoke requires smoke checks" in out


def test_release_preflight_strict_fails_doctor_warnings(tmp_path, monkeypatch, capsys):
    from curiator import cli

    repo = _make_gallery(tmp_path)
    (repo / "apps" / "sample").mkdir()
    (repo / "apps" / "sample" / "index.html").write_text("<h1>Sample</h1>\n")
    (repo / "gallery.yaml").write_text(textwrap.dedent("""\
        apps:
          - name: sample
            title: Sample
            root: apps/sample
            source: .
            mount: { kind: proxy, cmd: "python -m http.server {port}", port: 8899 }
        runner:
          mode: pinned
        feedback:
          dir: feedback
        shell:
          port: 8399
    """))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "make proxy app warning-only")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--no-smoke", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    gallery = payload["galleries"][0]
    assert payload["ok"] is True
    assert payload["checks"]["strict"] is False
    assert gallery["ok"] is True
    assert gallery["doctor"]["errors"] == 0
    assert gallery["doctor"]["warnings"] == 1

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--no-smoke", "--strict", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    gallery = payload["galleries"][0]
    assert payload["ok"] is False
    assert payload["checks"]["strict"] is True
    assert gallery["ok"] is False
    assert gallery["doctor"]["warnings"] == 1

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--no-smoke", "--strict"]) == 1
    out = capsys.readouterr().out
    assert "strict=true: doctor warnings block this gallery" in out


def test_release_preflight_fails_dirty_gallery_by_default(tmp_path, monkeypatch, capsys):
    from curiator import cli

    repo = _make_gallery(tmp_path)
    (repo / "apps" / "sample.py").write_text("app = object()\nVALUE = 2\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["galleries"][0]["dirty"]

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--allow-dirty", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True


def test_release_preflight_flags_tracked_machine_paths(tmp_path, monkeypatch, capsys):
    from curiator import cli

    repo = _make_gallery(tmp_path)
    (repo / "README.md").write_text("Do not publish /Users/alice/private/curiator checkout paths.\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "add bad path")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["galleries"][0]["path_hits"][0]["file"] == "README.md"


def test_release_preflight_flags_publish_unsafe_runtime_artifacts(tmp_path, monkeypatch, capsys):
    from curiator import cli

    repo = _make_gallery(tmp_path)
    (repo / "feedback" / "tasks").mkdir()
    (repo / "feedback" / "replies").mkdir()
    (repo / "feedback" / "shots").mkdir()
    (repo / "apps" / "__pycache__").mkdir()
    (repo / "node_modules" / "pkg").mkdir(parents=True)
    (repo / ".venv").mkdir()
    (repo / ".pytest_cache" / "v" / "cache").mkdir(parents=True)
    (repo / ".curiator-users.json").write_text('{"users": []}\n')
    (repo / ".env.local").write_text("OPENAI_API_KEY=sk-local\n")
    (repo / ".env.example").write_text("OPENAI_API_KEY=\n")
    (repo / "requirements.txt").write_text(
        "-e ../curiator\n"
        "-e git+https://github.com/example/pkg.git#egg=pkg\n"
        "--editable=../local_pkg\n"
        "--find-links ./wheels\n"
        "local-pkg @ file:///tmp/local-pkg\n"
    )
    (repo / "feedback" / "tasks" / "abc.md").write_text("task bundle\n")
    (repo / "feedback" / "replies" / "abc.md").write_text("agent trace\n")
    (repo / "feedback" / "shots" / "abc.png").write_bytes(b"not really png")
    (repo / "apps" / "__pycache__" / "sample.cpython-314.pyc").write_bytes(b"pyc")
    (repo / "node_modules" / "pkg" / "index.js").write_text("module.exports = {}\n")
    (repo / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (repo / ".pytest_cache" / "v" / "cache" / "nodeids").write_text("[]\n")
    (repo / "coverage.xml").write_text("<coverage />\n")
    (repo / "npm-debug.log").write_text("debug log\n")
    (repo / "feedback" / "app_feedback.json").write_text("[]\n")
    (repo / "feedback" / "app_feedback.sqlite").write_bytes(b"intentional ledger")
    (repo / "feedback" / "app_feedback.sqlite-wal").write_bytes(b"live sidecar")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add runtime artifacts")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    gallery = payload["galleries"][0]
    hits = gallery["publish_artifact_hits"]
    files = {hit["file"] for hit in hits}
    assert payload["ok"] is False
    assert ".curiator-users.json" in files
    assert ".env.local" in files
    assert "feedback/tasks/abc.md" in files
    assert "feedback/replies/abc.md" in files
    assert "feedback/shots/abc.png" in files
    assert "feedback/app_feedback.json" in files
    assert "feedback/app_feedback.sqlite-wal" in files
    assert "apps/__pycache__/sample.cpython-314.pyc" in files
    assert "node_modules/pkg/index.js" in files
    assert ".venv/pyvenv.cfg" in files
    assert ".pytest_cache/v/cache/nodeids" in files
    assert "coverage.xml" in files
    assert "npm-debug.log" in files
    assert {"file": "requirements.txt", "line": 1, "message": (
        "tracked local editable/path dependency; public examples should depend on published packages or VCS URLs"
    )} in hits
    assert {"file": "requirements.txt", "line": 3, "message": (
        "tracked local editable/path dependency; public examples should depend on published packages or VCS URLs"
    )} in hits
    assert {"file": "requirements.txt", "line": 4, "message": (
        "tracked local editable/path dependency; public examples should depend on published packages or VCS URLs"
    )} in hits
    assert {"file": "requirements.txt", "line": 5, "message": (
        "tracked local editable/path dependency; public examples should depend on published packages or VCS URLs"
    )} in hits
    assert not any(hit["file"] == "requirements.txt" and hit.get("line") == 2 for hit in hits)
    assert "feedback/app_feedback.sqlite" not in files
    assert ".env.example" not in files


def test_release_preflight_can_check_a_fresh_clone(tmp_path, monkeypatch, capsys):
    from curiator import cli

    _make_gallery(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main([
        "release-preflight",
        "--gallery", "curiator-demo",
        "--fresh-clone",
        "--clone-root", "clones",
        "--keep-clones",
        "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    gallery = payload["galleries"][0]
    assert payload["checks"]["fresh_clone"] is True
    assert Path(payload["clone_root"]).exists()
    assert gallery["mode"] == "fresh-clone"
    assert gallery["source_path"].endswith("galleries/curiator-demo")
    assert gallery["path"].startswith(str(tmp_path / "clones"))
    assert gallery["ok"] is True


def test_release_preflight_fresh_clone_fails_dirty_source_by_default(tmp_path, monkeypatch, capsys):
    from curiator import cli

    repo = _make_gallery(tmp_path)
    (repo / "apps" / "sample.py").write_text("app = object()\nVALUE = 2\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)

    assert cli.main(["release-preflight", "--gallery", "curiator-demo", "--fresh-clone", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    gallery = payload["galleries"][0]
    assert payload["ok"] is False
    assert gallery["mode"] == "fresh-clone"
    assert gallery["dirty"]
    assert "source repo is dirty" in gallery["error"]
