from __future__ import annotations

from curiator.annotations import clean_annotations


def test_clean_annotations_preserves_nonempty_target_classes():
    marks = clean_annotations([
        {
            "tool": "box",
            "x1": 0.1,
            "y1": 0.2,
            "target": {"classes": ["", "legend", None, "  plot  "]},
        }
    ])

    assert marks == [{
        "tool": "box",
        "x1": 0.1,
        "y1": 0.2,
        "target": {"classes": ["legend", "plot"]},
    }]


def test_clean_annotations_drops_empty_target_metadata():
    marks = clean_annotations([
        {
            "tool": "arrow",
            "x1": 0.1,
            "y1": 0.2,
            "target": {"classes": ["", "  ", None], "selector": "  "},
        }
    ])

    assert marks == [{"tool": "arrow", "x1": 0.1, "y1": 0.2}]


def test_clean_annotations_can_strip_dom_targets_for_non_capture_sources():
    marks = clean_annotations([
        {
            "tool": "box",
            "x1": 0.1,
            "y1": 0.2,
            "note": "keep this",
            "target": {"selector": "#chart", "tag": "div"},
        }
    ], allow_targets=False)

    assert marks == [{"tool": "box", "x1": 0.1, "y1": 0.2, "note": "keep this"}]


def test_clean_annotations_preserves_shared_clock_offsets():
    marks = clean_annotations([
        {"tool": "box", "x1": 0.1, "y1": 0.2, "start_ms": 42.4, "end_ms": 12.0},
        {"tool": "pin", "x1": 0.3, "y1": 0.4, "start_ms": -5, "end_ms": 999_999_999},
    ])

    assert marks[0]["start_ms"] == 42.4
    assert marks[0]["end_ms"] == 42.4
    assert marks[1]["start_ms"] == 0.0
    assert marks[1]["end_ms"] == 86_400_000.0
