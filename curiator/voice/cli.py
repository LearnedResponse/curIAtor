"""CLI handlers for voice-feedback configuration."""
from __future__ import annotations

from pathlib import Path

from curiator.config import load_config, set_block_key

VOICE_FASTER_WHISPER_CMD = "python -m curiator.voice.faster_whisper {audio}"


def cmd_voice(args) -> int:
    """Show or configure local voice transcription for the React feedback shell."""
    cfg = load_config()
    gallery = Path(cfg["gallery_path"])
    voice = cfg.get("voice") or {}
    if args.action == "show":
        command = voice.get("transcribe_cmd")
        print(f"curiator: voice.transcribe_cmd = {command or 'null'}  ({gallery})")
        print(f"curiator: voice.transcribe_timeout = {voice.get('transcribe_timeout')}")
        print(f"curiator: voice.transcribe_max_bytes = {voice.get('transcribe_max_bytes')}")
        print(f"curiator: voice.web_speech = {bool(voice.get('web_speech'))}")
        print(f"curiator: voice.web_speech_lang = {voice.get('web_speech_lang') or 'null'}")
        print(f"curiator: voice.retain_audio = {bool(voice.get('retain_audio'))}")
        return 0

    if args.action == "web-speech":
        enabled = args.state == "on"
        text = gallery.read_text()
        text = set_block_key(text, "voice", "web_speech", enabled)
        if args.lang is not None:
            text = set_block_key(text, "voice", "web_speech_lang", args.lang)
        gallery.write_text(text)
        print(f"curiator: browser Web Speech dictation {'enabled' if enabled else 'disabled'} in {gallery}")
        if enabled:
            print("note: browser Web Speech may use the browser provider's speech service; use only for public/hosted collections.")
        return 0

    if args.action == "retain-audio":
        enabled = args.state == "on"
        text = gallery.read_text()
        text = set_block_key(text, "voice", "retain_audio", enabled)
        gallery.write_text(text)
        print(f"curiator: retained audio {'enabled' if enabled else 'disabled'} in {gallery}")
        if enabled:
            print("note: audio clips are stored under feedback/audio/ and should be audited before sharing or publishing.")
        return 0

    command = VOICE_FASTER_WHISPER_CMD
    existing = voice.get("transcribe_cmd")
    if existing and existing != command and not args.force:
        print("curiator: voice.transcribe_cmd is already configured; use --force to overwrite it")
        print(f"  current: {existing}")
        print(f"  new:     {command}")
        return 1

    text = gallery.read_text()
    text = set_block_key(text, "voice", "transcribe_cmd", command)
    text = set_block_key(text, "voice", "transcribe_timeout", args.timeout)
    text = set_block_key(text, "voice", "transcribe_max_bytes", args.max_bytes)
    gallery.write_text(text)
    print(f"curiator: configured {args.engine} voice transcription in {gallery}")
    print(f"  voice.transcribe_cmd: {command}")
    print("next:")
    print("  pip install 'curiator[voice]'")
    print("  curiator up")
    return 0
