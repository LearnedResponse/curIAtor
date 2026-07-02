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
