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
