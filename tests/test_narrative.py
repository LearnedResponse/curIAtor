from __future__ import annotations

from curiator.narrative import build_narrative


def test_build_narrative_pairs_timed_marks_with_overlapping_segments():
    rows = build_narrative(
        [
            {"tool": "arrow", "x1": 0.1, "y1": 0.2, "start_ms": 900, "end_ms": 1200,
             "note": "destination", "target": {"selector": "#plot"}},
            {"tool": "box", "x1": 0.2, "y1": 0.3, "start_ms": 100, "end_ms": 500,
             "target": {"selector": "#legend"}},
            {"tool": "pin", "n": 3, "x1": 0.4, "y1": 0.5},
        ],
        [
            {"start_ms": 0, "end_ms": 250, "text": "this legend"},
            {"start_ms": 250, "end_ms": 700, "text": "is cramped"},
            {"start_ms": 900, "end_ms": 1300, "text": "move it here"},
        ],
    )

    assert [row["label"] for row in rows] == ["mark 2", "mark 1"]
    assert rows[0]["text"] == "this legend is cramped"
    assert rows[0]["segment_indexes"] == [1, 2]
    assert rows[1]["text"] == "move it here"
    assert rows[1]["note"] == "destination"
    assert rows[1]["target"]["selector"] == "#plot"


def test_build_narrative_keeps_timed_mark_without_matching_speech():
    rows = build_narrative(
        [{"tool": "box", "x1": 0.1, "y1": 0.1, "start_ms": 1000}],
        [{"start_ms": 0, "end_ms": 500, "text": "earlier"}],
    )

    assert rows == [{
        "mark_index": 1,
        "label": "mark 1",
        "tool": "box",
        "start_ms": 1000.0,
        "end_ms": 1000.0,
        "text": "",
        "segment_indexes": [],
    }]
