from __future__ import annotations

import json

import yaml


def test_voice_setup_configures_packaged_faster_whisper_adapter(collection, monkeypatch, capsys):
    from curiator import cli
    from curiator.config import load_config

    monkeypatch.chdir(collection)
    assert cli.main(["voice", "setup", "--timeout", "7", "--max-bytes", "12345"]) == 0

    data = yaml.safe_load((collection / "gallery.yaml").read_text())
    assert data["voice"]["transcribe_cmd"] == "python -m curiator.voice.faster_whisper {audio}"
    assert data["voice"]["transcribe_timeout"] == 7
    assert data["voice"]["transcribe_max_bytes"] == 12345
    assert load_config()["voice"]["transcribe_cmd"] == "python -m curiator.voice.faster_whisper {audio}"

    out = capsys.readouterr().out
    assert "configured faster-whisper voice transcription" in out
    assert "pip install 'curiator[voice]'" in out

    assert cli.main(["voice", "show"]) == 0
    shown = capsys.readouterr().out
    assert "voice.transcribe_cmd = python -m curiator.voice.faster_whisper {audio}" in shown


def test_voice_setup_refuses_to_overwrite_existing_command_without_force(collection, monkeypatch, capsys):
    from curiator import cli

    monkeypatch.chdir(collection)
    (collection / "gallery.yaml").write_text((collection / "gallery.yaml").read_text() + """
voice:
  transcribe_cmd: scripts/custom-transcribe {audio}
""")

    assert cli.main(["voice", "setup"]) == 1
    assert "already configured" in capsys.readouterr().out
    assert yaml.safe_load((collection / "gallery.yaml").read_text())["voice"]["transcribe_cmd"] == (
        "scripts/custom-transcribe {audio}"
    )

    assert cli.main(["voice", "setup", "--force"]) == 0
    assert yaml.safe_load((collection / "gallery.yaml").read_text())["voice"]["transcribe_cmd"] == (
        "python -m curiator.voice.faster_whisper {audio}"
    )


def test_faster_whisper_adapter_payload_formats_segments():
    from curiator.voice.faster_whisper import payload_from_segments

    class Segment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text

    payload = payload_from_segments([
        Segment(0.25, 1.5, " move\nthis "),
        Segment(1.5, 2.0, ""),
        Segment(2, 3, " legend "),
    ])

    assert payload == {
        "text": "move this legend",
        "segments": [
            {"start": 0.25, "end": 1.5, "text": "move this"},
            {"start": 2.0, "end": 3.0, "text": "legend"},
        ],
    }


def test_voice_doctor_warns_for_missing_transcriber_executable(collection, monkeypatch, capsys):
    from curiator import cli

    monkeypatch.chdir(collection)
    monkeypatch.setattr(cli.shutil, "which", lambda exe: None if exe == "missing-transcriber" else f"/usr/bin/{exe}")
    (collection / "gallery.yaml").write_text((collection / "gallery.yaml").read_text() + """
voice:
  transcribe_cmd: missing-transcriber {audio}
""")

    assert cli.main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    messages = "\n".join(issue["message"] for issue in payload["issues"])
    assert "voice transcribe command executable not found on PATH: missing-transcriber" in messages
