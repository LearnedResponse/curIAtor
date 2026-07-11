"""Credential staging keeps provider auth narrow and writable by the workspace user."""
import os
from pathlib import Path

from curiator.workspace_credential import stage


def test_stage_codex_credential_under_workspace_state(tmp_path: Path):
    source = tmp_path / "host-auth.json"
    source.write_text("secret")
    state = tmp_path / "state"
    state.mkdir()

    destination = stage("codex", source, state, uid=os.getuid(), gid=os.getgid())

    assert destination == state / "provider" / "codex" / "auth.json"
    assert destination.read_text() == "secret"
    assert destination.stat().st_mode & 0o777 == 0o600
    assert destination.parent.stat().st_mode & 0o777 == 0o700
