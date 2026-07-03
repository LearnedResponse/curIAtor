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
    assert data["auth"]["is_admin"] is True
    assert data["voice"]["local_transcribe"] is False
    assert data["voice"]["web_speech"] is False
    sample = next(a for a in data["apps"] if a["key"] == "sample")
    assert sample["revision"] == 0


def test_react_shell_general_iframe_src_is_stable(web_client):
    body = web_client.get("/assets/react_shell.js").get_data(as_text=True)
    assert "function appSrc(key, generalKey, revision)" in body
    assert 'return "/general";' in body
    assert "/general?t=" not in body
    assert '?v=' in body
    assert "selectedApp && selectedApp.revision" in body


def test_react_shell_pins_general_and_restores_auth_menu(web_client):
    body = web_client.get("/assets/react_shell.js").get_data(as_text=True)
    assert "function AccountMenu" in body
    assert "Queue" in body and "Settings" in body and "Profile" in body and "Log in" in body
    assert '.filter((a) => a.kind !== "general")' in body
    assert "rshell-general-row" in body


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
    assert "function annotationTarget" in js
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
    assert "annotations: screenshot ? annotations : []" in js
    assert "rshell-annotation-note" in js
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
    assert ".rshell-annotation-note input" in css
    assert ".rshell-annotation-summary" in css
    assert ".rshell-voice-summary" in css
    assert ".rshell-voice-row" in css
    assert ".rshell-voice-time" in css
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
    assert ".rshell-annotation-target" in css
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
    assert "#chart .legend" in home
    assert "target omitted" in home
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
