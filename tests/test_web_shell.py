"""web_shell: Flask/React overlay shell API + same-origin app mounting."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

SHELL_DIR = Path(__file__).resolve().parents[1] / "curiator" / "shell"


def _load_web_mod(monkeypatch):
    import importlib.util as u
    import sys

    monkeypatch.syspath_prepend(str(SHELL_DIR))
    for name in ("registry", "curiator.shell.app_shell", "curiator.shell.web_shell"):
        sys.modules.pop(name, None)
    import curiator.shell as shell_pkg
    for attr in ("app_shell", "web_shell"):
        if hasattr(shell_pkg, attr):
            delattr(shell_pkg, attr)
    spec = u.spec_from_file_location("curiator.shell.web_shell", str(SHELL_DIR / "web_shell.py"))
    mod = u.module_from_spec(spec)
    sys.modules["curiator.shell.web_shell"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def web_mod(collection, monkeypatch):
    return _load_web_mod(monkeypatch)


@pytest.fixture
def web_client(web_mod):
    app = web_mod.build_flask_app()
    return app.test_client()


def test_react_shell_index_and_bootstrap(web_client):
    body = web_client.get("/").get_data(as_text=True)
    assert "react_shell.js" in body
    assert "_dash" not in body
    data = web_client.get("/api/bootstrap").get_json()
    assert data["general_key"] == "__general__"
    assert data["general"]["key"] == "__general__"
    assert data["general"]["tags"] == []
    assert data["auth"]["is_admin"] is True
    assert data["voice"]["local_transcribe"] is False
    assert data["voice"]["web_speech"] is False
    sample = next(a for a in data["apps"] if a["key"] == "sample")
    assert sample["revision"] == 0


def test_web_shell_argv_gallery_beats_ambient_env(collection, tmp_path, monkeypatch):
    from curiator.config import set_gallery_override

    bad = tmp_path / "bad-gallery"
    (bad / "apps").mkdir(parents=True)
    (bad / "gallery.yaml").write_text("""\
apps:
  - name: wrong_app
    mount: { kind: dash-inproc, module: wrong_app }
    source: apps/wrong_app.py
""")
    (bad / "apps" / "wrong_app.py").write_text("app = object()\n")
    monkeypatch.setenv("CURIATOR_GALLERY", str(bad / "gallery.yaml"))
    monkeypatch.setattr(sys, "argv", ["web_shell.py", "--gallery", str(collection / "gallery.yaml")])
    try:
        mod = _load_web_mod(monkeypatch)
        assert mod.core.REG.GALLERY_YAML == (collection / "gallery.yaml").resolve()
        assert [app["key"] for app in mod.core.REG.ALL_APPS] == ["sample"]
    finally:
        set_gallery_override(None)


def test_react_shell_general_iframe_src_is_stable(web_client):
    body = web_client.get("/assets/react_shell.js").get_data(as_text=True)
    assert "function appSrc(key, generalKey, revision, extraQuery)" in body
    assert 'return "/general";' in body
    assert "/general?t=" not in body
    assert 'params.set("v", String(rev))' in body           # app cache-buster still applied
    assert "selectedApp && selectedApp.revision" in body


def test_react_shell_forwards_deep_link_query_args(web_client):
    """`/?app=X&node=crit` must forward `node=crit` to the /app/X/ iframe (app-to-app deep links)."""
    body = web_client.get("/assets/react_shell.js").get_data(as_text=True)
    assert "frameQuery" in body
    assert 'p.delete("app")' in body                          # capture everything except our own control param
    assert "revision, frameQuery)" in body                    # appSrc is called with the forwarded args


def test_react_shell_pins_general_and_restores_auth_menu(web_client):
    body = web_client.get("/assets/react_shell.js").get_data(as_text=True)
    assert "function AccountMenu" in body
    assert "Queue" in body and "Settings" in body and "Profile" in body and "Log in" in body
    assert '.filter((a) => a.kind !== "general")' in body
    assert "rshell-general-row" in body


def test_react_shell_has_new_app_wizard(web_client):
    js = web_client.get("/assets/react_shell.js").get_data(as_text=True)
    css = web_client.get("/assets/react_shell.css").get_data(as_text=True)
    general = web_client.get("/general").get_data(as_text=True)
    assert "function NewAppWizard" in js
    assert "/api/new-app" in js
    assert "openNewAppWizard" in js
    assert "React + Rust" in js
    assert "GitHub repo" in js
    assert "Pyodide / WASM" in js
    assert "Other (will try to accommodate)" in js
    assert "repo_url: repoUrl" in js
    assert "dockerize," in js
    assert "Dockerize" in js
    assert "rshell-general-title-row" in js
    assert "rshell-new-app-inline" in js
    assert ".rshell-new-app-modal" in css
    assert ".rshell-new-app-prompt" in css
    assert ".rshell-checkbox-field" in css
    assert ".rshell-button.secondary.rshell-new-app-inline" in css
    assert "background: #8e44ad" in css
    assert "openNewAppWizard" not in general
    assert "+ New app" not in general


def test_react_shell_side_rails_are_collapsible(web_client):
    js = web_client.get("/assets/react_shell.js").get_data(as_text=True)
    css = web_client.get("/assets/react_shell.css").get_data(as_text=True)
    assert "catCollapsed" in js and "fbCollapsed" in js
    assert "rshell-edge-tab left" in js and "rshell-edge-tab right" in js
    assert "rshell-collapse-btn" in js
    assert ".rshell-catalog.collapsed" in css
    assert ".rshell-feedback.collapsed" in css
    assert ".rshell-edge-tab" in css


def test_react_shell_has_burned_screenshot_annotations(web_client):
    js = web_client.get("/assets/react_shell.js").get_data(as_text=True)
    css = web_client.get("/assets/react_shell.css").get_data(as_text=True)
    assert "function AnnotationEditor" in js
    assert "function AnnotationSummary" in js
    assert "function AnnotationPreview" in js
    assert "function ShotThumbnail" in js
    assert "function DraftAnnotationModal" in js
    assert "function AnnotationReplayOverlay" in js
    assert "function VoiceSummary" in js
    assert "function buildNarrative" in js
    assert "entry.narrative" in js
    assert "function NarrativeReplay" in js
    assert "function narrativeStepDuration" in js
    assert "function copyAnnotations" in js
    assert "function useAnnotationDraft" in js
    assert "function composeShot" in js
    assert "function withDomTarget" in js
    assert "function annotationDoc" in js
    assert "function nativeCapture" in js
    assert "getDisplayMedia" in js
    assert 'setShotSource("native")' in js
    assert "Native capture unavailable in this browser." in js
    assert "Browser screen capture" in js
    assert "function selectorFor" in js
    assert "function annotationTarget" not in js
    assert 'mark.tool === "redact" || !doc || !doc.elementFromPoint' in js
    assert "return withDomTarget(mark, annotationDoc())" in js
    assert 'if (shotSource !== "capture") return mark;' in js
    assert "return null;" in js
    assert "rshell-annotation-preview-btn" in js
    assert "rshell-annotation-modal" in js
    assert "rshell-annotation-replay-overlay" in js
    assert "rshell-annotation-replay-pin" in js
    assert "rshell-narrative-replay" in js
    assert "rshell-narrative-audio" in js
    assert "Narrative replay" in js
    assert "Play transcript-timed narrative" in js
    assert "entry.audio_url" in js
    assert "Retained audio" in js
    assert "activeIndex" in js
    assert "retainedAudioRef" in js
    assert "audio_ref: retainedAudioRef" in js
    assert "Use as reply draft" in js
    assert 'setShotSource("replay")' in js
    assert "shotEditorOpen" in js
    assert "Open expanded annotation view" in js
    assert "rshell-shot-thumb" in js
    assert "rshell-draft-annotation-modal" in js
    assert "selectedAnnotation" in js
    assert "rshell-annotation-drawer" in js
    assert "drawer-collapsed" in js
    assert "Move annotation earlier" in js
    assert "Move annotation later" in js
    assert "shotApp" in js
    assert "function clearShotDraft" in js
    assert "selectedRef.current" in js
    assert "rshell-annotation-summary-count" in js
    assert "function selectNearestAnnotation" in js
    assert "function markDistance" in js
    assert "function toolSelectsOnClick" in js
    assert 'value === "arrow" || value === "box" || value === "redact"' in js
    assert "if (toolSelectsOnClick(tool)) selectNearestAnnotation(p);" in js
    assert "annotations: screenshot ? draftAnnotations : []" in js
    assert "rshell-annotation-note" in js
    assert "rshell-annotation-properties" in js
    assert "rshell-annotation-summary" in js
    assert "annotation note " in js
    assert "OS dictation can type feedback here." in js
    assert "start_ms" in js and "end_ms" in js
    assert "shotSource" in js
    assert 'setShotSource("capture")' in js
    assert 'setShotSource("upload")' in js
    assert "drawAnnotation(ctx, mark" in js
    assert "tool === \"redact\"" in js
    assert "anonymousHeld ? null" in js
    assert "rshell-annotation-canvas" in css
    assert ".rshell-shot-thumb" in css
    assert ".rshell-shot-thumb-frame" in css
    assert ".rshell-shot-thumb-action" in css
    assert ".rshell-annotation-empty" in css
    assert ".rshell-annotation-drawer" in css
    assert ".rshell-annotation-modal-body.drawer-collapsed" in css
    assert ".rshell-annotation-properties" in css
    assert ".rshell-annotation-replay-shot .rshell-annotation-canvas" in css
    assert ".rshell-annotation-summary-count" in css
    assert "overflow: hidden" in css
    assert "max-height: 100%" in css
    assert ".rshell-annotation-note input" in css
    assert ".rshell-annotation-summary" in css
    assert ".rshell-annotation-summary-row.selected" in css
    assert ".rshell-voice-summary" in css
    assert ".rshell-voice-row" in css
    assert ".rshell-voice-time" in css
    assert ".rshell-voice-note" in css
    assert ".rshell-annotation-preview-btn" in css
    assert ".rshell-modal-backdrop" in css
    assert ".rshell-modal-actions" in css
    assert ".rshell-annotation-modal-body" in css
    assert ".rshell-annotation-replay-overlay" in css
    assert ".rshell-annotation-replay-box" in css
    assert ".rshell-annotation-replay-arrow" in css
    assert ".rshell-annotation-replay-redact" in css
    assert ".rshell-annotation-replay-pin" in css
    assert ".rshell-narrative-replay" in css
    assert ".rshell-narrative-audio" in css
    assert ".rshell-narrative-step.active" in css
    assert ".rshell-annotation-replay-box.active" in css
    assert ".rshell-annotation-target" not in css
    assert "touch-action: none" in css


def test_react_shell_has_local_voice_transcription(web_client):
    js = web_client.get("/assets/react_shell.js").get_data(as_text=True)
    css = web_client.get("/assets/react_shell.css").get_data(as_text=True)
    assert "function startVoice" in js
    assert "function stopVoice" in js
    assert "function transcribeBlob" in js
    assert "MediaRecorder" in js
    assert "getUserMedia" in js
    assert 'fetch("/api/transcribe"' in js
    assert "function startBrowserSpeech" in js
    assert "function stopBrowserSpeech" in js
    assert "displayNarrativeRows(buildNarrative(entry))" in js
    assert "no overlapping transcript" not in js
    assert "SpeechRecognition" in js
    assert "webkitSpeechRecognition" in js
    assert "voice.local_transcribe" in js
    assert "voice.web_speech" in js
    assert "Browser Web Speech dictation; may use browser speech services" in js
    assert "Browser dictation is not enabled for this collection." in js
    assert "transcriptSegments" in js
    assert "transcript_segments: transcriptSegments" in js
    assert "function ensureNarrativeClock" in js
    assert "function offsetTranscriptSegments" in js
    assert "recordingOffsetRef.current" in js
    assert "clockStart: narrativeClockStart" in js
    assert "clockRef.current = clockStart || performance.now()" in js
    assert ".rshell-button.secondary.active" in css


def test_react_shell_new_app_api_creates_general_collection_request(web_client):
    from pathlib import Path

    from curiator import ledger
    from curiator.config import load_config
    from curiator.loop.adapters import GENERAL_KEY, build_task, general_targets_collection

    response = web_client.post("/api/new-app", json={
        "app_type": "dash",
        "title": "Orange tree picker",
        "app_key": "orange_tree_picker",
        "prompt": "Find oranges in orchard photos and report mask quality.",
        "notes": "Use generated sample data first.",
    })

    assert response.status_code == 200
    entry = response.get_json()["entry"]
    assert entry["status"] == "new"
    assert entry["app_request"]["kind"] == "new_app"
    assert entry["app_request"]["app_key"] == "orange_tree_picker"
    assert entry["app_request"]["template"] == "dash"
    assert "Create a new curIAtor app." in entry["comment"]
    assert "curiator app create" in entry["comment"]

    cfg = load_config()
    stored = ledger.load(cfg)[GENERAL_KEY][-1]
    assert general_targets_collection(stored, cfg)
    task = build_task(cfg, GENERAL_KEY, stored)
    body = Path(task.task_file).read_text()
    assert "## New app wizard request" in body
    assert "curiator app create orange_tree_picker --template dash" in body
    assert "Find oranges in orchard photos" in body


def test_react_shell_new_app_api_supports_github_import(web_client):
    from pathlib import Path

    from curiator import ledger
    from curiator.config import load_config
    from curiator.loop.adapters import GENERAL_KEY, build_task, general_targets_collection

    response = web_client.post("/api/new-app", json={
        "app_type": "github_repo",
        "title": "Lab viewer",
        "repo_url": "https://github.com/example/lab-viewer.git",
        "dockerize": True,
        "prompt": "Host the existing app and preserve its local development workflow.",
    })

    assert response.status_code == 200
    entry = response.get_json()["entry"]
    request = entry["app_request"]
    assert request["app_type"] == "github_repo"
    assert request["repo_url"] == "https://github.com/example/lab-viewer.git"
    assert request["dockerize"] is True
    assert "curiator app import" in entry["comment"]
    assert "Dockerize requested" in entry["comment"]

    cfg = load_config()
    stored = ledger.load(cfg)[GENERAL_KEY][-1]
    assert general_targets_collection(stored, cfg)
    task = build_task(cfg, GENERAL_KEY, stored)
    body = Path(task.task_file).read_text()
    assert "source repo: `https://github.com/example/lab-viewer.git`" in body
    assert "curiator app import https://github.com/example/lab-viewer.git lab_viewer --template react" in body
    assert "--tags imported,docker" in body
    assert "Docker requested" in body


def test_react_shell_new_app_api_supports_pyodide_static(web_client):
    from pathlib import Path

    from curiator import ledger
    from curiator.config import load_config
    from curiator.loop.adapters import GENERAL_KEY, build_task

    response = web_client.post("/api/new-app", json={
        "app_type": "pyodide_wasm",
        "title": "Browser solver",
        "prompt": "Run the solver entirely in the browser with Python packages loaded by Pyodide.",
    })

    assert response.status_code == 200
    entry = response.get_json()["entry"]
    assert entry["app_request"]["app_type"] == "pyodide_wasm"
    assert entry["app_request"]["template"] == "static"
    assert "Pyodide / WASM" in entry["comment"]
    assert "offloads Python or compute-heavy work" in entry["comment"]

    cfg = load_config()
    stored = ledger.load(cfg)[GENERAL_KEY][-1]
    body = Path(build_task(cfg, GENERAL_KEY, stored).task_file).read_text()
    assert "curiator app create browser_solver --template static" in body
    assert "--tags pyodide,static" in body
    assert "keep compute browser-side with Pyodide/WASM" in body


def test_react_shell_new_app_api_supports_other_type(web_client):
    from pathlib import Path

    from curiator import ledger
    from curiator.config import load_config
    from curiator.loop.adapters import GENERAL_KEY, build_task

    response = web_client.post("/api/new-app", json={
        "app_type": "other",
        "title": "Unusual prototype",
        "prompt": "Make whatever host best fits this odd simulator.",
    })

    assert response.status_code == 200
    entry = response.get_json()["entry"]
    assert entry["app_request"]["app_type"] == "other"
    assert entry["app_request"]["template"] == "python"
    assert "Other (will try to accommodate)" in entry["comment"]

    cfg = load_config()
    stored = ledger.load(cfg)[GENERAL_KEY][-1]
    body = Path(build_task(cfg, GENERAL_KEY, stored).task_file).read_text()
    assert "choose the closest supported template from the brief" in body


def test_react_shell_can_expose_opt_in_browser_speech(collection, monkeypatch):
    (collection / "gallery.yaml").write_text((collection / "gallery.yaml").read_text() + """
voice:
  web_speech: true
  web_speech_lang: en-US
""")
    mod = _load_web_mod(monkeypatch)
    client = mod.build_flask_app().test_client()

    boot = client.get("/api/bootstrap").get_json()
    assert boot["voice"]["local_transcribe"] is False
    assert boot["voice"]["web_speech"] is True
    assert boot["voice"]["web_speech_lang"] == "en-US"


def test_react_shell_transcribe_api_runs_configured_local_command(collection, monkeypatch):
    script = collection / "transcribe_fixture.py"
    script.write_text(
        "import json, os, sys\n"
        "audio = sys.argv[1]\n"
        "assert audio == os.environ['CURIATOR_AUDIO']\n"
        "print(json.dumps({'text': 'move the legend', 'segments': ["
        "{'start': 0.25, 'end': 0.75, 'text': 'move'}, "
        "{'start_ms': 800, 'end_ms': 1200, 'text': 'the legend'}]}))\n"
    )
    (collection / "gallery.yaml").write_text((collection / "gallery.yaml").read_text() + f"""
voice:
  transcribe_cmd: "{sys.executable} {script} {{audio}}"
  transcribe_timeout: 5
  transcribe_max_bytes: 1024
""")
    mod = _load_web_mod(monkeypatch)
    client = mod.build_flask_app().test_client()

    boot = client.get("/api/bootstrap").get_json()
    assert boot["voice"]["local_transcribe"] is True
    assert boot["voice"]["retain_audio"] is False
    r = client.post("/api/transcribe", data={"audio": (io.BytesIO(b"audio"), "clip.webm")})
    assert r.status_code == 200
    data = r.get_json()
    assert data["text"] == "move the legend"
    assert "audio_ref" not in data
    assert data["segments"] == [
        {"start_ms": 250.0, "end_ms": 750.0, "text": "move"},
        {"start_ms": 800.0, "end_ms": 1200.0, "text": "the legend"},
    ]


def test_react_shell_can_retain_audio_for_saved_feedback(collection, monkeypatch):
    script = collection / "transcribe_fixture.py"
    script.write_text("import json\nprint(json.dumps({'text': 'move it', 'segments': []}))\n")
    (collection / "gallery.yaml").write_text((collection / "gallery.yaml").read_text() + f"""
voice:
  transcribe_cmd: "{sys.executable} {script} {{audio}}"
  retain_audio: true
""")
    mod = _load_web_mod(monkeypatch)
    client = mod.build_flask_app().test_client()

    boot = client.get("/api/bootstrap").get_json()
    assert boot["voice"]["retain_audio"] is True
    r = client.post("/api/transcribe", data={"audio": (io.BytesIO(b"audio bytes"), "clip.webm")})
    assert r.status_code == 200
    audio_ref = r.get_json()["audio_ref"]
    assert audio_ref.startswith("audio/pending/")
    assert (collection / "feedback" / audio_ref).exists()

    saved = client.post("/api/feedback/sample", json={"comment": "voice note", "audio_ref": audio_ref})
    assert saved.status_code == 200
    entry = saved.get_json()["entry"]
    assert entry["audio"].startswith("audio/sample_")
    assert entry["audio_url"].startswith("/feedback-audio/sample_")
    assert not (collection / "feedback" / audio_ref).exists()
    audio_file = collection / "feedback" / entry["audio"]
    assert audio_file.read_bytes() == b"audio bytes"
    assert client.get(entry["audio_url"]).get_data() == b"audio bytes"


def test_react_shell_profile_settings_and_collection_home(web_client):
    web_client.post("/api/feedback/sample", json={"comment": "app activity", "stars": 3})
    home = web_client.get("/general").get_data(as_text=True)
    assert "collection home" in home
    assert home.index("General feedback") < home.index("Latest activity")
    assert "app activity" in home
    assert "selectApp(&quot;sample&quot;)" in home
    assert 'selectApp("sample")' not in home
    assert web_client.get("/profile").status_code == 200
    settings = web_client.get("/settings")
    assert settings.status_code == 200
    assert "Provider (adapter)" in settings.get_data(as_text=True)


def test_react_shell_admin_queue_page_reviews_held_feedback(web_client):
    from curiator import ledger
    from curiator.config import load_config

    cfg = load_config()
    fid = ledger.save_entry(
        cfg,
        "sample",
        comment="public typo report",
        stars=4,
        user={"id": "visitor", "email": "visitor@example.com", "name": "Visitor", "groups": []},
        extra={"status": "held"},
    )
    page = web_client.get("/queue")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "public typo report" in body and "visitor@example.com" in body

    approved = web_client.post(f"/queue/{fid}/approve")
    assert approved.status_code == 302
    items = ledger.load(load_config())["sample"]
    assert next(e for e in items if e["id"] == fid)["status"] == "new"
    assert any(e.get("kind") == "system" and fid in (e.get("reply_to") or [])
               and "approved by anonymous@local" in e.get("comment", "")
               for e in items)

    reject_id = ledger.save_entry(cfg, "sample", comment="spam link", extra={"status": "held"})
    rejected = web_client.post(f"/queue/{reject_id}/reject", data={"reason": "spam"}, follow_redirects=True)
    assert rejected.status_code == 200
    items = ledger.load(load_config())["sample"]
    assert next(e for e in items if e["id"] == reject_id)["status"] == "rejected"
    assert any(e.get("kind") == "system" and reject_id in (e.get("reply_to") or [])
               and "Reason: spam" in e.get("comment", "")
               for e in items)


def test_react_shell_login_required_rejects_logged_out_feedback_by_default(collection, monkeypatch):
    (collection / "gallery.yaml").write_text((collection / "gallery.yaml").read_text() + """
auth:
  mode: local
  users_file: .curiator-users.json
""")
    mod = _load_web_mod(monkeypatch)
    client = mod.build_flask_app().test_client()
    r = client.post("/api/feedback/sample", json={"comment": "logged out"})
    assert r.status_code == 401
    assert r.get_json()["error"] == "sign in required"


def test_react_shell_header_auth_requires_proxy_identity_for_feedback(collection, monkeypatch):
    from curiator import ledger
    from curiator.config import load_config

    script = collection / "transcribe_fixture.py"
    script.write_text("import json\nprint(json.dumps({'text': 'header voice', 'segments': []}))\n")
    (collection / "gallery.yaml").write_text((collection / "gallery.yaml").read_text() + f"""
auth:
  mode: header
  admin_groups: [ops]
voice:
  transcribe_cmd: "{sys.executable} {script} {{audio}}"
  retain_audio: true
""")
    mod = _load_web_mod(monkeypatch)
    client = mod.build_flask_app().test_client()

    rejected = client.post("/api/feedback/sample", json={"comment": "missing proxy identity"})
    assert rejected.status_code == 401
    assert rejected.get_json()["error"] == "sign in required"
    assert ledger.load(load_config()).get("sample", []) == []

    route_action = client.get("/fb-action?key=sample&value=approve")
    assert route_action.status_code == 401

    transcribe = client.post("/api/transcribe", data={"audio": (io.BytesIO(b"audio"), "clip.webm")})
    assert transcribe.status_code == 401
    assert transcribe.get_json()["error"] == "sign in required"

    accepted = client.post(
        "/api/feedback/sample",
        json={"comment": "proxied feedback"},
        headers={
            "X-Auth-Request-User": "u-1",
            "X-Auth-Request-Email": "alex@example.com",
            "X-Auth-Request-Groups": "ops, trusted",
        },
    )
    assert accepted.status_code == 200
    entry = accepted.get_json()["entry"]
    assert entry["status"] == "new"
    assert entry["user"] == {
        "id": "u-1",
        "email": "alex@example.com",
        "name": "alex",
        "groups": ["ops", "trusted"],
    }

    action = client.post("/api/action", json={"key": "sample", "value": "approve"})
    assert action.status_code == 401


def test_react_shell_allow_anonymous_feedback_is_held(collection, monkeypatch):
    from curiator import auth, ledger
    from curiator.config import load_config

    auth.clear_anonymous_feedback("127.0.0.1")
    (collection / "gallery.yaml").write_text((collection / "gallery.yaml").read_text() + """
auth:
  mode: local
  allow_anonymous: true
  users_file: .curiator-users.json
""")
    mod = _load_web_mod(monkeypatch)
    client = mod.build_flask_app().test_client()

    boot = client.get("/api/bootstrap").get_json()
    assert boot["auth"]["mode"] == "local"
    assert boot["auth"]["allow_anonymous"] is True
    assert boot["user"] == {"authenticated": False}

    r = client.post("/api/feedback/sample", json={"comment": "logged out public comment", "stars": 5})
    assert r.status_code == 200
    entry = r.get_json()["entry"]
    assert entry["status"] == "held"
    assert entry["user"]["name"] == "anonymous"

    action = client.post("/api/action", json={"key": "sample", "value": "yes", "reply_to": entry["id"]})
    assert action.status_code == 200
    action_entry = action.get_json()["entry"]
    assert action_entry["status"] == "held"
    assert action_entry["reply_to"] == [entry["id"]]

    items = ledger.load(load_config())["sample"]
    assert [e["status"] for e in items if e.get("author") == "user"] == ["held", "held"]


def test_react_shell_rejects_anonymous_upload_and_native_screenshots(collection, monkeypatch):
    from curiator import auth, ledger
    from curiator.config import load_config

    auth.clear_anonymous_feedback("127.0.0.1")
    (collection / "gallery.yaml").write_text((collection / "gallery.yaml").read_text() + """
auth:
  mode: local
  allow_anonymous: true
  users_file: .curiator-users.json
""")
    mod = _load_web_mod(monkeypatch)
    client = mod.build_flask_app().test_client()

    upload = client.post("/api/feedback/sample", json={
        "comment": "uploaded image",
        "screenshot": "data:image/png;base64,aGVsbG8=",
        "screenshot_source": "upload",
    })
    assert upload.status_code == 400
    assert upload.get_json()["error"] == "anonymous uploaded/native screenshots are disabled; use Capture view"
    assert ledger.load(load_config()).get("sample", []) == []

    auth.clear_anonymous_feedback("127.0.0.1")
    native = client.post("/api/feedback/sample", json={
        "comment": "screen capture",
        "screenshot": "data:image/png;base64,aGVsbG8=",
        "screenshot_source": "native",
    })
    assert native.status_code == 400
    assert native.get_json()["error"] == "anonymous uploaded/native screenshots are disabled; use Capture view"
    assert ledger.load(load_config()).get("sample", []) == []

    auth.clear_anonymous_feedback("127.0.0.1")
    capture = client.post("/api/feedback/sample", json={
        "comment": "captured image",
        "screenshot": "data:image/png;base64,aGVsbG8=",
        "screenshot_source": "capture",
    })
    assert capture.status_code == 200
    entry = capture.get_json()["entry"]
    assert entry["status"] == "held"
    assert entry["screenshot"]


def test_react_shell_rejects_anonymous_retained_audio(collection, monkeypatch):
    from curiator import auth, ledger
    from curiator.config import load_config

    auth.clear_anonymous_feedback("127.0.0.1")
    script = collection / "transcribe_fixture.py"
    script.write_text("import json\nprint(json.dumps({'text': 'public voice', 'segments': []}))\n")
    (collection / "gallery.yaml").write_text((collection / "gallery.yaml").read_text() + f"""
auth:
  mode: local
  allow_anonymous: true
  users_file: .curiator-users.json
voice:
  transcribe_cmd: "{sys.executable} {script} {{audio}}"
  retain_audio: true
""")
    mod = _load_web_mod(monkeypatch)
    client = mod.build_flask_app().test_client()

    transcribed = client.post("/api/transcribe", data={"audio": (io.BytesIO(b"audio"), "clip.webm")})
    assert transcribed.status_code == 200
    assert transcribed.get_json()["text"] == "public voice"
    assert "audio_ref" not in transcribed.get_json()

    auth.clear_anonymous_feedback("127.0.0.1")
    saved = client.post("/api/feedback/sample", json={"comment": "voice", "audio_ref": "audio/pending/fake.webm"})
    assert saved.status_code == 400
    assert saved.get_json()["error"] == "anonymous retained audio is disabled; sign in to attach audio"
    assert ledger.load(load_config()).get("sample", []) == []


def test_react_shell_allow_anonymous_feedback_is_rate_limited(collection, monkeypatch):
    from curiator import auth, ledger
    from curiator.config import load_config

    auth.clear_anonymous_feedback("127.0.0.1")
    (collection / "gallery.yaml").write_text((collection / "gallery.yaml").read_text() + """
auth:
  mode: local
  allow_anonymous: true
  anonymous_feedback_max: 1
  anonymous_feedback_window_seconds: 60
  users_file: .curiator-users.json
""")
    mod = _load_web_mod(monkeypatch)
    client = mod.build_flask_app().test_client()

    first = client.post("/api/feedback/sample", json={"comment": "first public note"})
    assert first.status_code == 200
    assert first.get_json()["entry"]["status"] == "held"

    second = client.post("/api/feedback/sample", json={"comment": "second public note"})
    assert second.status_code == 429
    assert "too many anonymous submissions" in second.get_json()["error"]

    action = client.post("/api/action", json={"key": "sample", "value": "yes", "reply_to": first.get_json()["entry"]["id"]})
    assert action.status_code == 429
    items = ledger.load(load_config())["sample"]
    assert [e["comment"] for e in items if e.get("author") == "user"] == ["first public note"]


def test_react_shell_feedback_api_threads_replies(web_client):
    r1 = web_client.post("/api/feedback/sample", json={"comment": "original", "stars": 2})
    assert r1.status_code == 200
    parent = r1.get_json()["entry"]["id"]
    r2 = web_client.post("/api/feedback/sample", json={"comment": "reply", "reply_to": [parent]})
    assert r2.status_code == 200
    child = r2.get_json()["entry"]
    assert child["reply_to"] == [parent]
    data = web_client.get("/api/feedback/sample").get_json()
    assert [e["comment"] for e in data["items"]] == ["original", "reply"]


def test_react_shell_feedback_api_stores_sanitized_annotations(web_client):
    from pathlib import Path

    from curiator import ledger
    from curiator.config import load_config
    from curiator.loop.adapters import build_task

    r = web_client.post("/api/feedback/sample", json={
        "comment": "marked chart",
        "screenshot": "data:image/png;base64,aGVsbG8=",
        "screenshot_source": "capture",
        "annotations": [
            {
                "tool": "box",
                "x1": -1,
                "y1": 0.2,
                "x2": 0.9,
                "y2": 2,
                "start_ms": 123.4,
                "end_ms": 456.7,
                "note": "  legend   overlaps\nchart  ",
                "target": {
                    "selector": "#chart .legend",
                    "tag": "div",
                    "id": "chart",
                    "data_testid": "legend",
                    "role": "img",
                    "classes": ["plot", "legend", "extra", "ignored", "last", "dropped"],
                    "text": "not stored",
                },
            },
            {"tool": "redact", "x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2,
             "note": "private value", "target": {"selector": "#secret"}},
            {"tool": "unknown", "x1": 0.1, "y1": 0.1},
        ],
        "transcript_segments": [
            {"start": 0.2, "end": 0.8, "text": " move the legend "},
            {"start_ms": 900, "end_ms": 1000, "text": " then widen the plot "},
            {"text": ""},
        ],
    })
    assert r.status_code == 200
    annotations = r.get_json()["entry"]["annotations"]
    assert len(annotations) == 2
    assert annotations[0]["x1"] == 0.0 and annotations[0]["y2"] == 1.0
    assert annotations[0]["start_ms"] == 123.4
    assert annotations[0]["end_ms"] == 456.7
    assert annotations[0]["note"] == "legend overlaps chart"
    assert annotations[0]["target"]["selector"] == "#chart .legend"
    assert annotations[0]["target"]["classes"] == ["plot", "legend", "extra", "ignored", "last"]
    assert "text" not in annotations[0]["target"]
    assert annotations[1]["note"] == "private value"
    assert "target" not in annotations[1]
    segments = r.get_json()["entry"]["transcript_segments"]
    assert segments == [
        {"start_ms": 200.0, "end_ms": 800.0, "text": "move the legend"},
        {"start_ms": 900.0, "end_ms": 1000.0, "text": "then widen the plot"},
    ]
    narrative = r.get_json()["entry"]["narrative"]
    assert narrative[0]["label"] == "mark 1"
    assert narrative[0]["text"] == "move the legend"
    assert narrative[0]["segment_indexes"] == [1]
    assert narrative[0]["target"]["selector"] == "#chart .legend"

    home = web_client.get("/general").get_data(as_text=True)
    assert "Annotations" in home
    assert "legend overlaps chart" in home
    assert "Narrated feedback" in home
    assert "move the legend" in home

    cfg = load_config()
    entry = ledger.load(cfg)["sample"][-1]
    assert entry["screenshot"].startswith("shots/sample_")
    assert (Path(cfg["repo_root"]) / "feedback" / entry["screenshot"]).exists()

    task = build_task(cfg, "sample", entry)
    body = Path(task.task_file).read_text()
    assert "screenshot (Read this PNG): `feedback/shots/sample_" in body
    assert "## Screenshot annotations" in body
    assert "mark 1: `box` at x1=0.000, y1=0.200, x2=0.900, y2=1.000 [start=123ms, end=457ms]" in body
    assert "selector `#chart .legend`" in body
    assert "data-testid `legend`" in body
    assert "legend overlaps chart" in body
    assert "## Voice transcript segments" in body
    assert "segment 1 [start=200ms, end=800ms]: move the legend" in body
    assert "segment 2 [start=900ms, end=1000ms]: then widen the plot" in body
    assert "## Narrated feedback" in body
    assert (
        "1. mark 1: `box` [start=123ms, end=457ms] -> selector `#chart .legend`; "
        "tag `div`; data-testid `legend`; role `img`: move the legend"
    ) in body
    assert "mark 2: `redact` at x1=0.100, y1=0.100, x2=0.200, y2=0.200 (target omitted for redaction)" in body
    assert "#secret" not in body


def test_react_shell_feedback_api_strips_dom_targets_for_non_capture_screenshots(web_client):
    r = web_client.post("/api/feedback/sample", json={
        "comment": "uploaded marked image",
        "screenshot": "data:image/png;base64,aGVsbG8=",
        "screenshot_source": "upload",
        "annotations": [
            {
                "tool": "box",
                "x1": 0.1,
                "y1": 0.2,
                "x2": 0.8,
                "y2": 0.9,
                "note": "keep mark",
                "target": {"selector": "#chart .legend", "tag": "div"},
            },
        ],
    })

    assert r.status_code == 200
    assert r.get_json()["entry"]["annotations"] == [{
        "tool": "box",
        "x1": 0.1,
        "y1": 0.2,
        "x2": 0.8,
        "y2": 0.9,
        "note": "keep mark",
    }]


def test_react_shell_trace_and_app_mount(collection, web_mod):
    from werkzeug.test import Client
    from werkzeug.wrappers import Response

    trace = collection / "feedback" / "replies" / "abc123.md"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text("# trace\nhello\n")
    application, _flask = web_mod.build_application()
    client = Client(application, Response)
    raw = client.get("/feedback-trace/abc123.md")
    assert raw.status_code == 200 and "hello" in raw.get_data(as_text=True)
    mounted = client.get("/app/sample/")
    assert mounted.status_code == 200


def test_api_apps_poll_invalidates_changed_dash_source(collection, web_mod):
    from werkzeug.test import Client
    from werkzeug.wrappers import Response

    application, flask_app = web_mod.build_application()
    api_client = flask_app.test_client()
    api_client.get("/api/bootstrap")

    client = Client(application, Response)
    mounted = client.get("/app/sample/")
    assert mounted.status_code == 200
    assert "sample" in mounted.get_data(as_text=True)

    (collection / "apps" / "sample.py").write_text("""\
import dash
from dash import html


def build_app():
    app = dash.Dash(__name__)
    app.layout = html.Div("updated sample")
    return app


app = build_app()
""")

    apps = api_client.get("/api/apps").get_json()["apps"]
    sample = next(a for a in apps if a["key"] == "sample")
    assert sample["revision"] == 1

    refreshed = client.get("/app/sample/_dash-layout?v=1")
    assert refreshed.status_code == 200
    assert "updated sample" in refreshed.get_data(as_text=True)


def test_api_apps_poll_does_not_remount_proxy_app_on_runtime_writes(collection, monkeypatch):
    appdir = collection / "apps" / "proxy_app"
    appdir.mkdir()
    (appdir / "server.js").write_text("console.log('proxy app')\n")
    (collection / "gallery.yaml").write_text(
        (collection / "gallery.yaml").read_text().replace(
            "    tags: [demo]\n",
            "    tags: [demo]\n"
            "  - name: proxy_app\n"
            "    title: Proxy App\n"
            "    root: apps/proxy_app\n"
            "    source: .\n"
            "    mount: { kind: proxy, cmd: \"node server.js\", port: 8701 }\n",
        )
    )
    mod = _load_web_mod(monkeypatch)
    app = mod.build_flask_app()
    api_client = app.test_client()

    apps = api_client.get("/api/apps").get_json()["apps"]
    proxy = next(a for a in apps if a["key"] == "proxy_app")
    assert proxy["revision"] == 0

    (appdir / "runtime-cache.json").write_text("{}\n")
    apps = api_client.get("/api/apps").get_json()["apps"]
    proxy = next(a for a in apps if a["key"] == "proxy_app")
    assert proxy["revision"] == 0


def test_reload_refreshes_registry_for_newly_created_app(collection, web_mod):
    from werkzeug.test import Client
    from werkzeug.wrappers import Response

    from curiator import cli

    application, flask_app = web_mod.build_application()
    api_client = flask_app.test_client()
    assert all(a["key"] != "orange_picker" for a in api_client.get("/api/bootstrap").get_json()["apps"])

    assert cli.main([
        "app", "create", "orange_picker",
        "--template", "dash",
        "--title", "Orange Picker",
    ]) == 0

    reload_data = api_client.post("/reload/orange_picker").get_json()
    assert reload_data["registered"] is True
    assert reload_data["registry_count"] == 2
    assert reload_data["revision"] == 1
    orange = next(a for a in api_client.get("/api/bootstrap").get_json()["apps"] if a["key"] == "orange_picker")
    assert orange["revision"] == 1

    client = Client(application, Response)
    mounted = client.get("/app/orange_picker/")
    assert mounted.status_code == 200
    assert "Orange Picker" in mounted.get_data(as_text=True)


def test_trace_stop_writes_cancel_marker_only_for_active_run(web_client, cfg):
    """The Stop button drops a cancel marker only while the item is `working`; otherwise it declines."""
    from curiator import ledger
    from curiator.loop import runlog

    fid = ledger.save_entry(cfg, "sample", comment="stop me", ts="t")

    # not dispatched yet → 409, no marker written
    r = web_client.post(f"/feedback-trace/{fid}/stop")
    assert r.status_code == 409
    assert not runlog.cancel_path(cfg, fid).exists()

    ledger.set_status(cfg, "sample", [fid], "working")
    r = web_client.post(f"/feedback-trace/{fid}/stop")
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert runlog.cancel_path(cfg, fid).exists()

    # unknown id → 404
    assert web_client.post("/feedback-trace/deadbeef/stop").status_code == 404


def test_proxy_streaming_detection(web_mod):
    """SSE and any no-Content-Length response are treated as streaming (so their read timeout is relaxed)."""
    core = web_mod.core

    class R:
        def __init__(self, headers):
            self.headers = headers

    assert core._proxy_response_is_streaming(R({"Content-Type": "text/event-stream"})) is True
    assert core._proxy_response_is_streaming(R({"Content-Type": "text/html"})) is True            # chunked/no length
    assert core._proxy_response_is_streaming(R({"Content-Type": "text/html", "Content-Length": "42"})) is False


def test_proxy_streams_body_incrementally(web_mod, monkeypatch):
    """The proxy yields the backend body in chunks (read1) instead of buffering it whole, and closes the
    upstream when done — the fix that makes SSE / chunked / large responses work through the overlay."""
    import io

    core = web_mod.core

    class Resp:
        status, reason = 200, "OK"

        def __init__(self):
            self.headers = {"Content-Type": "text/event-stream", "Cache-Control": "no-cache"}
            self._chunks = [b"data: 1\n\n", b"data: 2\n\n", b""]
            self.closed = False

        def read1(self, _n):
            return self._chunks.pop(0)

        def close(self):
            self.closed = True

    resp = Resp()
    monkeypatch.setattr(core, "_ensure_proxy", lambda key, rec: (True, None))
    monkeypatch.setattr(core.urllib.request, "urlopen", lambda req, timeout=None: resp)

    seen = {}

    def start_response(status, headers):
        seen["status"] = status
        seen["headers"] = dict(headers)

    environ = {"REQUEST_METHOD": "GET", "QUERY_STRING": "", "wsgi.input": io.BytesIO()}
    body = core._proxy_call("x", {"mount": {"port": 9999}}, "/", environ, start_response)
    chunks = list(body)                                   # consume the streaming generator

    assert chunks == [b"data: 1\n\n", b"data: 2\n\n"]      # per-read chunks, not one buffered blob
    assert seen["status"].startswith("200")
    assert seen["headers"]["Content-Type"] == "text/event-stream"
    assert resp.closed                                    # generator closed the upstream on completion


def test_ws_upgrade_request_reconstruction(web_mod):
    """The replayed upgrade request carries the client handshake headers + curIAtor's X-Forwarded-*."""
    core = web_mod.core
    env = {
        "REQUEST_METHOD": "GET", "QUERY_STRING": "flow=1",
        "HTTP_HOST": "h", "HTTP_UPGRADE": "websocket", "HTTP_CONNECTION": "Upgrade",
        "HTTP_SEC_WEBSOCKET_KEY": "abc", "REMOTE_ADDR": "127.0.0.1", "wsgi.url_scheme": "http",
    }
    req = core._ws_upgrade_request("nodered", env, "/comms").decode()
    assert req.startswith("GET /comms?flow=1 HTTP/1.1\r\n")
    assert "Upgrade: websocket" in req and "Connection: Upgrade" in req
    assert "Sec-Websocket-Key: abc" in req                 # handshake header forwarded
    assert "X-Forwarded-Prefix: /app/nodered" in req       # origin context added
    assert req.endswith("\r\n\r\n")


def test_proxy_websocket_falls_back_to_501_without_hijack_socket(web_mod, monkeypatch):
    """Behind a WSGI server that doesn't expose the raw socket (no `werkzeug.socket`), a WS upgrade
    degrades to an honest 501 rather than hanging."""
    import io

    core = web_mod.core
    monkeypatch.setattr(core, "_ensure_proxy", lambda key, rec: (True, None))
    seen = {}

    def start_response(status, headers):
        seen["status"] = status

    environ = {
        "REQUEST_METHOD": "GET", "QUERY_STRING": "",
        "HTTP_UPGRADE": "websocket", "HTTP_CONNECTION": "Upgrade",
        "wsgi.input": io.BytesIO(),                        # note: no "werkzeug.socket"
    }
    body = b"".join(core._proxy_call("x", {"mount": {"port": 9}}, "/", environ, start_response))
    assert seen["status"].startswith("501")
    assert b"WebSocket" in body


def test_proxy_bridges_websocket_upgrade_end_to_end(collection, monkeypatch):
    """A WS upgrade is tunneled through the real proxy: the client's upgrade reaches the backend, its 101
    is relayed, and bytes pump both ways. Raw sockets throughout (no WS library) — this tests the tunnel
    mechanics, which is exactly what carries real WebSocket frames on top."""
    import socket
    import threading

    import yaml
    from werkzeug.serving import make_server

    # a raw 'WebSocket-ish' echo backend: 101 handshake, then echo received bytes with an "echo:" prefix
    bsock = socket.socket()
    bsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bsock.bind(("127.0.0.1", 0))
    bport = bsock.getsockname()[1]
    bsock.listen(1)

    def backend():
        try:
            conn, _ = bsock.accept()
        except OSError:
            return
        buf = b""
        while b"\r\n\r\n" not in buf:
            d = conn.recv(4096)
            if not d:
                conn.close()
                return
            buf += d
        conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
        while True:
            d = conn.recv(4096)
            if not d:
                break
            conn.sendall(b"echo:" + d)
        conn.close()

    threading.Thread(target=backend, daemon=True).start()

    (collection / "apps" / "wsapp").mkdir(parents=True, exist_ok=True)
    gallery = yaml.safe_load((collection / "gallery.yaml").read_text())
    gallery["apps"].append({
        "name": "wsapp", "root": "apps/wsapp", "source": ".",
        "mount": {"kind": "proxy", "cmd": "true", "port": bport},
    })
    (collection / "gallery.yaml").write_text(yaml.safe_dump(gallery, sort_keys=False))

    web_mod = _load_web_mod(monkeypatch)
    application, _flask = web_mod.build_application()
    monkeypatch.setattr(web_mod.core, "_ensure_proxy", lambda key, rec: (True, None))

    srv = make_server("127.0.0.1", 0, application, threaded=True)
    sport = srv.socket.getsockname()[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = socket.create_connection(("127.0.0.1", sport), timeout=5)
        c.settimeout(5)
        c.sendall(b"GET /app/wsapp/comms HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
                  b"Connection: Upgrade\r\nSec-WebSocket-Key: abc\r\nSec-WebSocket-Version: 13\r\n\r\n")
        buf = b""
        while b"\r\n\r\n" not in buf:
            d = c.recv(4096)
            assert d, "connection closed before the 101 handshake was relayed"
            buf += d
        assert b"101 Switching Protocols" in buf           # backend handshake relayed to the client
        c.sendall(b"ping")
        assert c.recv(4096) == b"echo:ping"                # bidirectional byte pump through the tunnel
    finally:
        srv.shutdown()
        bsock.close()


def test_apps_payload_exposes_updated_timestamp(web_client, cfg):
    """Each app carries an `updated` epoch (newest of source mtime and latest feedback ts) for the
    'date updated' catalog sort; recent feedback bumps it above the source-file mtime."""
    import datetime

    from curiator import ledger

    ledger.save_entry(cfg, "sample", comment="recent", ts="2030-01-01T00:00:00+00:00")
    apps = web_client.get("/api/bootstrap").get_json()["apps"]
    sample = next(a for a in apps if a["key"] == "sample")
    assert "updated" in sample
    floor = datetime.datetime(2029, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
    assert sample["updated"] >= floor            # the 2030 feedback ts dominates → sorts as recently updated


def test_react_shell_has_date_updated_sort_option(web_client):
    body = web_client.get("/assets/react_shell.js").get_data(as_text=True)
    assert '["updated", "date updated"]' in body
    assert 'sort === "updated"' in body
