from __future__ import annotations

from curiator.transcripts import clean_transcript_segments


def test_clean_transcript_segments_accepts_seconds_and_ms():
    segments = clean_transcript_segments([
        {"start": 0.25, "end": 0.75, "text": " move\nthis "},
        {"start_ms": 800, "end_ms": 700, "text": " legend "},
        {"text": "untimed phrase"},
        {"start": "bad", "end": "bad", "text": ""},
    ])

    assert segments == [
        {"text": "move this", "start_ms": 250.0, "end_ms": 750.0},
        {"text": "legend", "start_ms": 800.0, "end_ms": 800.0},
        {"text": "untimed phrase"},
    ]
