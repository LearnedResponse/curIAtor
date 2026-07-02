from __future__ import annotations

import subprocess
from pathlib import Path

from curiator import cli


def test_init_can_initialize_collection_git_repo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)
    dest = tmp_path / "galleries" / "curiator-demo"

    assert cli.main(["init", str(dest), "--git"]) == 0

    assert (dest / "gallery.yaml").exists()
    assert (dest / "apps" / "sample.py").exists()
    assert (dest / ".git").is_dir()
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=dest,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "true"
