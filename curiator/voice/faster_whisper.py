"""Local faster-whisper adapter for curIAtor voice feedback.

Usage:
    python -m curiator.voice.faster_whisper <audio-file>

The module prints JSON shaped like:
    {"text": "...", "segments": [{"start": 0.0, "end": 1.2, "text": "..."}]}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def payload_from_segments(segments) -> dict:
    rows = []
    for segment in segments:
        text = str(getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        rows.append({
            "start": float(getattr(segment, "start", 0.0) or 0.0),
            "end": float(getattr(segment, "end", 0.0) or 0.0),
            "text": " ".join(text.split()),
        })
    return {"text": " ".join(row["text"] for row in rows), "segments": rows}


def transcribe(audio: Path, *, model: str, device: str, compute_type: str, language: str | None = None) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(
            "curIAtor voice transcription needs faster-whisper. "
            "Install it with: pip install 'curiator[voice]'"
        ) from exc

    whisper = WhisperModel(model, device=device, compute_type=compute_type)
    kwargs = {"vad_filter": True}
    if language:
        kwargs["language"] = language
    segments, _info = whisper.transcribe(str(audio), **kwargs)
    return payload_from_segments(segments)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Transcribe an audio clip for curIAtor feedback.")
    parser.add_argument("audio", help="audio file path from curIAtor /api/transcribe")
    parser.add_argument("--model", default=os.environ.get("CURIATOR_WHISPER_MODEL", "base"))
    parser.add_argument("--device", default=os.environ.get("CURIATOR_WHISPER_DEVICE", "cpu"))
    parser.add_argument("--compute-type", default=os.environ.get("CURIATOR_WHISPER_COMPUTE_TYPE", "int8"))
    parser.add_argument("--language", default=os.environ.get("CURIATOR_WHISPER_LANGUAGE"))
    args = parser.parse_args(argv)

    audio = Path(args.audio)
    if not audio.exists():
        print(json.dumps({"error": f"audio file not found: {audio}"}), file=sys.stderr)
        return 2
    payload = transcribe(audio, model=args.model, device=args.device, compute_type=args.compute_type,
                         language=args.language)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
