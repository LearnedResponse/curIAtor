from __future__ import annotations

import json
from pathlib import Path

import pytest

from curiator.design_refs import (
    DesignReferenceError,
    clean_design_ref,
    clean_design_refs,
    thread_design_refs,
)


FIGMA_URL = "https://www.figma.com/design/Abc_def-123/Aviato?node-id=12-34"


def test_clean_design_ref_preserves_valid_url_and_derives_stable_ids():
    ref = clean_design_ref({"url": FIGMA_URL, "label": "  Checkout   panel ", "note": "desktop frame"})
    assert ref == {
        "provider": "figma",
        "url": FIGMA_URL,
        "file_key": "Abc_def-123",
        "node_id": "12:34",
        "access": "read",
        "label": "Checkout panel",
        "note": "desktop frame",
    }


@pytest.mark.parametrize("url", [
    "http://www.figma.com/design/Abcd/Test?node-id=1-2",
    "https://figma.example/design/Abcd/Test?node-id=1-2",
    "https://www.figma.com/design/Abcd/Test",
    "https://www.figma.com/design/Abcd/Test?node-id=1-2&access_token=secret",
    "https://user:secret@www.figma.com/design/Abcd/Test?node-id=1-2",
])
def test_clean_design_ref_rejects_unsafe_or_non_specific_urls(url):
    with pytest.raises(DesignReferenceError):
        clean_design_ref(url)


def test_clean_design_refs_is_bounded():
    with pytest.raises(DesignReferenceError, match="at most 5"):
        clean_design_refs([FIGMA_URL] * 6)


def test_thread_design_refs_inherits_only_explicit_reply_thread():
    first = {"id": "f1", "design_refs": [FIGMA_URL], "reply_to": []}
    reply = {"id": "f2", "reply_to": ["f1"]}
    unrelated = {"id": "f3", "design_refs": [FIGMA_URL.replace("12-34", "9-9")], "reply_to": []}
    refs = thread_design_refs({"sample": [first, reply, unrelated]}, "sample", reply)
    assert [ref["node_id"] for ref in refs] == ["12:34"]


def test_figma_capability_receipt_moves_doctor_from_auth_required_to_available(cfg, monkeypatch):
    from curiator import agent_capabilities

    cfg["agent"]["adapter"] = "codex"
    monkeypatch.setattr(agent_capabilities, "_figma_plugin_installed", lambda _adapter: (True, "installed"))
    before = agent_capabilities.figma_capabilities(cfg)
    assert before["read_context"] == "auth-required"
    assert before["write_design"] == "not-authorized"

    receipt = agent_capabilities.record_figma_receipt(
        cfg,
        read_context=True,
        render_reference=True,
        code_connect=False,
    )
    cached = json.loads(Path(before["receipt_path"]).read_text())
    assert cached == receipt
    assert "email" not in json.dumps(cached).lower()

    after = agent_capabilities.agent_report(cfg)["capabilities"]["figma"]
    assert after["read_context"] == "available"
    assert after["render_reference"] == "available"
    assert after["write_design"] == "not-authorized"
    assert after["code_connect"] == "unavailable"


def test_capability_cli_records_and_clears_local_figma_receipt(collection, monkeypatch, capsys):
    from curiator import agent_capabilities, cli

    monkeypatch.setattr(agent_capabilities, "_figma_plugin_installed", lambda _adapter: (True, "installed"))
    assert cli.main(["capability", "verify", "figma", "--provider", "headless-cc"]) == 0
    assert "recorded local Figma capability receipt" in capsys.readouterr().out
    assert (collection / ".curiator" / "cache" / "capabilities" / "figma.json").exists()
    assert cli.main(["capability", "clear", "figma"]) == 0
    assert not (collection / ".curiator" / "cache" / "capabilities" / "figma.json").exists()


def test_capability_cli_can_record_temporary_provider_unavailability(collection, monkeypatch, capsys):
    from curiator import agent_capabilities, cli
    from curiator.config import load_config

    monkeypatch.setattr(agent_capabilities, "_figma_plugin_installed", lambda _adapter: (True, "installed"))
    assert cli.main([
        "capability", "unavailable", "figma",
        "--provider", "headless-cc",
        "--reason", "Starter plan MCP quota exhausted",
        "--retry-hours", "12",
    ]) == 0
    assert "temporary Figma unavailability" in capsys.readouterr().out
    figma = agent_capabilities.figma_capabilities(load_config())
    assert figma["read_context"] == "unavailable"
    assert "Starter plan MCP quota exhausted" in figma["reason"]
