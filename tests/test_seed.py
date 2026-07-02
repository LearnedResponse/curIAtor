"""seed: `curiator seed <file>` loads canned feedback into the ledger as attributed, status:new
entries (the self-building-demo build queue)."""
from __future__ import annotations

import argparse
import textwrap

from curiator import ledger
from curiator.cli import cmd_seed


def test_seed_loads_attributed_new_feedback(cfg, collection, tmp_path):
    seed = tmp_path / "seed.yaml"
    seed.write_text(textwrap.dedent('''\
        user: { id: paola, email: paola@acme.example, name: Paola }
        items:
          - { app: sample, stars: 2, comment: "make the pie a donut" }
          - { app: sample, comment: "label the axes" }
          - { app: other, comment: "from someone else", user: { id: bob, email: bob@x.io, name: Bob } }
    '''))
    cmd_seed(argparse.Namespace(file=str(seed)))

    data = ledger.load(cfg)
    assert len(data["sample"]) == 2 and len(data["other"]) == 1
    assert all(e["status"] == "new" and e["author"] == "user" for its in data.values() for e in its)
    # default author (Paola) applied, per-item override honored
    assert data["sample"][0]["user"]["email"] == "paola@acme.example" and data["sample"][0]["stars"] == 2
    assert data["other"][0]["user"]["email"] == "bob@x.io"


def test_seed_loads_sanitized_annotations(cfg, tmp_path):
    seed = tmp_path / "seed.yaml"
    seed.write_text(textwrap.dedent('''\
        items:
          - app: sample
            comment: "fix the marked legend"
            annotations:
              - tool: box
                x1: -1
                y1: 0.2
                x2: 0.8
                y2: 2
                note: "  legend   overlaps "
                target:
                  selector: "#chart .legend"
                  text: "not stored"
              - tool: unknown
                x1: 0.5
                y1: 0.5
    '''))
    cmd_seed(argparse.Namespace(file=str(seed)))

    entry = ledger.load(cfg)["sample"][-1]
    assert len(entry["annotations"]) == 1
    assert entry["annotations"][0]["x1"] == 0.0
    assert entry["annotations"][0]["y2"] == 1.0
    assert entry["annotations"][0]["note"] == "legend overlaps"
    assert entry["annotations"][0]["target"]["selector"] == "#chart .legend"
    assert "text" not in entry["annotations"][0]["target"]
