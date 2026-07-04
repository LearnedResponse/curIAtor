"""adapters: the task bundle (app + runner routing), the M2 screenshot-path regression, LESSONS load,
and the `command` adapter's {task_file}/{source} substitution."""
from __future__ import annotations

from pathlib import Path

from curiator.loop import adapters
from curiator.loop.adapters import GENERAL_KEY, Task, build_task, command
from curiator import ledger


def _entry(**kw):
    base = {"id": "f1", "stars": 2, "comment": "legend covers the chart",
            "screenshot": None, "status": "new", "kind": "comment", "author": "user"}
    base.update(kw)
    return base


def test_app_bundle_paths_and_commands(cfg, collection):
    t = build_task(cfg, "sample", _entry(screenshot="shots/sample_f1.png"))
    body = Path(t.task_file).read_text()
    assert t.source == str((collection / "apps" / "sample.py").resolve())
    assert Path(t.task_file) == collection / "feedback" / "tasks" / "f1.md"
    assert Path(t.reply_file) == collection / "feedback" / "replies" / "f1.md"
    assert "feedback/shots/sample_f1.png" in body          # screenshot path joined ONCE
    assert "shots/shots/" not in body                       # M2 double-join regression guard
    assert "CURIATOR_GALLERY=" not in body                  # task bundles stay clone-portable
    assert str(collection) not in body
    assert "app root: `.`" in body
    assert "source scope to edit: `apps/sample.py`" in body
    assert "SQLite source of truth: `feedback/app_feedback.sqlite`" in body
    assert "curiator reply sample f1" in body               # ready-to-run reply
    assert "SMOKE OK" in body                               # smoke-test recipe


def test_app_bundle_includes_doctor_gated_browser_smoke_contract(cfg, monkeypatch):
    from curiator import agent_capabilities

    def fake_which(name):
        return "/usr/bin/brave-browser" if name == "brave-browser" else None

    monkeypatch.delenv("CURIATOR_BROWSER", raising=False)
    monkeypatch.setattr(agent_capabilities.shutil, "which", fake_which)

    body = Path(build_task(cfg, "sample", _entry()).task_file).read_text()
    assert "## Browser-smoke capability" in body
    assert "curiator smoke --app sample --browser" in body
    assert "--artifact-dir feedback/replies/f1-browser-smoke" in body
    assert "--output feedback/replies/f1-browser-smoke/result.json --json" in body
    assert "feedback/replies/f1-browser-smoke/sample.png" in body
    assert "what was not verified" in body


def test_app_bundle_omits_browser_smoke_contract_when_browser_missing(cfg, monkeypatch):
    from curiator import agent_capabilities

    monkeypatch.delenv("CURIATOR_BROWSER", raising=False)
    monkeypatch.setattr(agent_capabilities.shutil, "which", lambda _name: None)

    body = Path(build_task(cfg, "sample", _entry()).task_file).read_text()
    assert "## Browser-smoke capability" not in body


def test_app_bundle_includes_screenshot_annotations(cfg):
    entry = _entry(
        screenshot="shots/sample_f1.png",
        annotations=[
            {
                "tool": "pin",
                "x1": 0.25,
                "y1": 0.4,
                "n": 1,
                "note": "legend overlaps chart",
                "target": {"selector": "#chart .legend", "tag": "div", "data_testid": "legend"},
            },
            {"tool": "redact", "x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2,
             "note": "token hidden", "target": {"selector": "#secret"}},
        ],
    )

    body = Path(build_task(cfg, "sample", entry).task_file).read_text()
    assert "## Screenshot annotations" in body
    assert "pin 1: `pin` at x1=0.250, y1=0.400 -> selector `#chart .legend`" in body
    assert "data-testid `legend`" in body
    assert "legend overlaps chart" in body
    assert "target omitted for redaction" in body
    assert "token hidden" in body
    assert "#secret" not in body


def test_app_bundle_includes_voice_transcript_segments(cfg):
    entry = _entry(
        transcript_segments=[
            {"start_ms": 100, "end_ms": 350, "text": "move the legend"},
            {"text": "untimed follow-up"},
        ],
    )

    body = Path(build_task(cfg, "sample", entry).task_file).read_text()
    assert "## Voice transcript segments" in body
    assert "segment 1 [start=100ms, end=350ms]: move the legend" in body
    assert "segment 2: untimed follow-up" in body


def test_app_bundle_includes_retained_voice_audio(cfg):
    entry = _entry(audio="audio/sample_f1.webm")

    body = Path(build_task(cfg, "sample", entry).task_file).read_text()
    assert "## Retained voice audio" in body
    assert "audio clip (local runtime media): `feedback/audio/sample_f1.webm`" in body
    assert "listen to the clip only when the transcript is ambiguous" in body


def test_app_bundle_includes_narrated_feedback_when_timings_overlap(cfg):
    entry = _entry(
        annotations=[
            {"tool": "box", "x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4,
             "start_ms": 100, "end_ms": 500, "note": "legend area",
             "target": {"selector": "#chart .legend"}},
        ],
        transcript_segments=[
            {"start_ms": 0, "end_ms": 250, "text": "this legend"},
            {"start_ms": 250, "end_ms": 700, "text": "is cramped"},
        ],
    )

    body = Path(build_task(cfg, "sample", entry).task_file).read_text()
    assert "## Narrated feedback" in body
    assert (
        "1. mark 1: `box` [start=100ms, end=500ms] -> selector `#chart .legend`: "
        "this legend is cramped"
    ) in body
    assert "(mark note: legend area)" in body


def test_app_bundle_omits_empty_narrated_feedback_rows(cfg):
    entry = _entry(
        annotations=[
            {"tool": "box", "x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4,
             "start_ms": 100, "end_ms": 500,
             "target": {"selector": "#chart .legend"}},
        ],
        transcript_segments=[
            {"start_ms": 700, "end_ms": 900, "text": "unrelated later comment"},
        ],
    )

    body = Path(build_task(cfg, "sample", entry).task_file).read_text()
    assert "## Screenshot annotations" in body
    assert "## Voice transcript segments" in body
    assert "## Narrated feedback" not in body
    assert "no overlapping transcript" not in body


def test_app_bundle_uses_persisted_narrative_rows(cfg):
    entry = _entry(
        annotations=[
            {"tool": "box", "x1": 0.1, "y1": 0.2, "start_ms": 100, "end_ms": 500},
        ],
        narrative=[
            {"mark_index": 1, "label": "saved mark", "tool": "arrow", "start_ms": 900,
             "end_ms": 1200, "text": "persisted text", "target": {"selector": "#saved"}},
        ],
    )

    body = Path(build_task(cfg, "sample", entry).task_file).read_text()
    assert "saved mark: `arrow` [start=900ms, end=1200ms] -> selector `#saved`: persisted text" in body


def test_runner_routing_checkout_vs_pinned(cfg):
    g = build_task(cfg, GENERAL_KEY, _entry(id="g1", comment="the shell chrome is ugly"))
    body = Path(g.task_file).read_text()
    assert "checkout" in body.lower() and g.source is not None    # cfg runner.mode == checkout

    cfg2 = {**cfg, "runner": {"mode": "pinned"}}
    p = build_task(cfg2, GENERAL_KEY, _entry(id="g2", comment="same"))
    pbody = Path(p.task_file).read_text()
    assert "pinned" in pbody.lower() and "upstream" in pbody.lower() and p.source is None


def test_general_new_app_request_routes_to_collection(cfg, collection):
    entry = _entry(id="g3", comment="create a new curiator app as an explainer/overview")
    t = build_task(cfg, GENERAL_KEY, entry)
    body = Path(t.task_file).read_text()
    assert t.source == str(collection.resolve())
    assert "General collection feedback" in body
    assert "Do NOT edit the runner checkout" in body
    assert "CURIATOR_GALLERY=" not in body
    assert str(collection) not in body
    assert "collection root: `.`" in body
    assert "curiator app create" in body
    assert "gallery.yaml" in body and "curiator reply __general__ g3" in body
    assert adapters.general_targets_collection(entry)
    assert not adapters.general_targets_collection(_entry(comment="make the shell chrome clearer"))


def test_general_example_dash_app_request_routes_to_collection(cfg, collection):
    entry = _entry(
        id="g4",
        comment=(
            "let's do an example dash app like this one:\n"
            "https://dash.gallery/dash-image-segmentation/\n"
            "https://github.com/plotly/dash-sample-apps/tree/main/apps/dash-image-segmentation\n\n"
            "but instead of cells, do an example picking out oranges from photos of orange trees"
        ),
    )
    t = build_task(cfg, GENERAL_KEY, entry)
    body = Path(t.task_file).read_text()
    assert t.source == str(collection.resolve())
    assert "General collection feedback" in body
    assert "Do NOT edit the runner checkout" in body
    assert "CURIATOR_GALLERY=" not in body
    assert str(collection) not in body
    assert "curiator app create" in body
    assert adapters.general_targets_collection(entry)


def test_general_approval_reply_inherits_collection_request_context(cfg, collection):
    fid = ledger.save_entry(
        cfg,
        GENERAL_KEY,
        comment=(
            "let's do an example dash app like this one:\n"
            "https://dash.gallery/dash-image-segmentation/\n"
            "but instead of cells, do an example picking out oranges from photos of orange trees"
        ),
        ts="t0",
    )
    nid = ledger.add_system_note(
        cfg,
        GENERAL_KEY,
        "This should route to collection app work.",
        reply_to=[fid],
        ts="t1",
    )
    aid = ledger.save_entry(
        cfg,
        GENERAL_KEY,
        comment="ok, go ahead",
        ts="t2",
        extra={"reply_to": [nid]},
    )
    entry = next(e for e in ledger.load(cfg)[GENERAL_KEY] if e["id"] == aid)

    t = build_task(cfg, GENERAL_KEY, entry)
    body = Path(t.task_file).read_text()
    assert t.source == str(collection.resolve())
    assert "General collection feedback" in body
    assert "APPROVAL/FOLLOW-UP RUN" in body
    assert "perform that app work now" in body
    assert "curiator app create" in body
    assert "orange" in body
    assert adapters.general_targets_collection(entry, cfg)
    assert not adapters.general_targets_collection(entry)


def test_bundle_loads_lessons_when_present(cfg, collection):
    (collection / "LESSONS.md").write_text("# LESSONS.md\n\n## sample\n- ✓ stuck · `abc1234` · curator(sample): tidy\n")
    body = Path(build_task(cfg, "sample", _entry()).task_file).read_text()
    assert "Prior lessons for `sample`" in body and "abc1234" in body


def test_bundle_includes_feedback_thread_for_action_reply(cfg, collection):
    fid = ledger.save_entry(cfg, "sample", comment="getting this error on the react app",
                            screenshot="shots/sample_f1.png", ts="t0")
    nid = ledger.add_system_note(cfg, "sample", "Option A: install dependencies. Option B: simplify.",
                                 reply_to=[fid], ts="t1", actions=["A", "B"])
    aid = ledger.save_entry(cfg, "sample", comment="A", ts="t2", extra={"reply_to": [nid]})
    entry = next(e for e in ledger.load(cfg)["sample"] if e["id"] == aid)

    body = Path(build_task(cfg, "sample", entry).task_file).read_text()
    assert "Feedback thread context" in body
    assert "getting this error on the react app" in body
    assert "Option A: install dependencies" in body
    assert "feedback/shots/sample_f1.png" in body
    assert "Feedback ledger and tooling" in body
    assert "curiator feedback show sample --limit 20" in body
    assert "SQLite source of truth" in body


def test_short_unlinked_action_reply_gets_recent_thread_context(cfg, collection):
    ledger.save_entry(cfg, "sample", comment="getting this error on the react app",
                      screenshot="shots/sample_f1.png", ts="t0")
    ledger.add_system_note(cfg, "sample", "Option A: install dependencies. Option B: simplify.", ts="t1",
                           actions=["A", "B"])
    aid = ledger.save_entry(cfg, "sample", comment="A", ts="t2")
    entry = next(e for e in ledger.load(cfg)["sample"] if e["id"] == aid)

    body = Path(build_task(cfg, "sample", entry).task_file).read_text()
    assert "Feedback thread context" in body
    assert "getting this error on the react app" in body
    assert "Option A: install dependencies" in body
    assert "feedback/shots/sample_f1.png" in body


def test_headless_cc_streams_json_events_with_a_formatter(cfg, monkeypatch, tmp_path):
    """The default headless run uses `--output-format stream-json --verbose` + the event formatter, so
    the trace shows live progress instead of sitting silent until `--output-format text` finishes."""
    from curiator.loop.adapters import headless_cc

    task_file = tmp_path / "task.md"
    task_file.write_text("do the thing")
    cap = {}
    monkeypatch.setattr(headless_cc, "available", lambda: True)
    monkeypatch.setattr(headless_cc.runlog, "run_streamed",
                        lambda task, c, **k: cap.update(cmd=c, kwargs=k) or headless_cc.runlog.RunResult(0, ""))

    headless_cc.run(Task(key="sample", entry={"id": "x"}, source="apps/sample.py",
                         task_file=str(task_file), reply_file=str(tmp_path / "r.md"), cfg=cfg))
    assert cap["cmd"][:3] == ["claude", "-p", "do the thing"]
    assert "--verbose" in cap["cmd"]
    assert cap["cmd"][cap["cmd"].index("--output-format") + 1] == "stream-json"
    assert cap["kwargs"]["line_formatter"] is headless_cc._format_stream_event
    # tools LAST (variadic), and web research is pre-approved so it works headlessly
    assert cap["cmd"][-9:] == ["--allowedTools", "Read", "Edit", "Write", "Bash", "Glob", "Grep",
                               "WebSearch", "WebFetch"]


def test_headless_cc_stream_can_be_disabled(cfg, monkeypatch, tmp_path):
    from curiator.loop.adapters import headless_cc

    task_file = tmp_path / "task.md"
    task_file.write_text("x")
    cap = {}
    monkeypatch.setattr(headless_cc, "available", lambda: True)
    monkeypatch.setattr(headless_cc.runlog, "run_streamed",
                        lambda task, c, **k: cap.update(cmd=c, kwargs=k) or headless_cc.runlog.RunResult(0, ""))
    cfg2 = {**cfg, "agent": {"adapter": "headless-cc", "stream": False}}
    headless_cc.run(Task(key="sample", entry={"id": "x"}, source=None,
                         task_file=str(task_file), reply_file=str(tmp_path / "r.md"), cfg=cfg2))
    assert "--output-format" not in cap["cmd"]
    assert cap["kwargs"]["line_formatter"] is None


def test_format_stream_event_renders_readable_progress():
    from curiator.loop.adapters import headless_cc as h
    f = h._format_stream_event

    assert f("") is None
    assert "session started" in f('{"type":"system","subtype":"init","model":"opus","tools":["Read","Bash"]}')
    assert f('{"type":"assistant","message":{"content":[{"type":"text","text":" Reading the scope "}]}}') == "Reading the scope"
    assert f('{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{"file_path":"a.py"}}]}}') == "▸ Read(a.py)"
    assert f('{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"curiator reply x y"}}]}}') == "▸ Bash: curiator reply x y"
    assert f('{"type":"user","message":{"content":[{"type":"tool_result","content":"ok"}]}}') is None
    assert "error" in f('{"type":"user","message":{"content":[{"type":"tool_result","is_error":true}]}}')
    r = f('{"type":"result","subtype":"success","num_turns":5,"duration_ms":12000,"total_cost_usd":0.1234}')
    assert "result: success" in r and "5 turns" in r and "12.0s" in r and "$0.1234" in r
    assert f("not json at all") == "not json at all"


def test_run_streamed_applies_line_formatter(tmp_path):
    """A formatter can drop lines (return None) and rewrite others; multi-line reads are split."""
    import sys
    import types

    from curiator.loop import runlog

    task = types.SimpleNamespace(reply_file=str(tmp_path / "trace.md"))
    runlog.run_streamed(
        task, [sys.executable, "-c", "print('drop'); print('keep')"],
        cwd=str(tmp_path), timeout=30, label="x", display_cmd=["py", "..."],
        line_formatter=lambda line: None if line.strip() == "drop" else line.strip().upper(),
    )
    text = Path(task.reply_file).read_text()
    assert "KEEP" in text
    assert "drop" not in text          # dropped by the formatter, and not in the display header


def test_command_adapter_substitutes(cfg, monkeypatch):
    captured = {}
    monkeypatch.setattr(command.runlog, "run_streamed",
                        lambda task, c, **k: captured.update(cmd=c) or command.runlog.RunResult(0, ""))
    cfg2 = {**cfg, "agent": {"adapter": "command", "cmd": "mytool {task_file} {source}"}}
    command.run(Task(key="sample", entry={"id": "x"}, source="apps/sample.py",
                     task_file="/tmp/task.md", reply_file="/tmp/reply.md", cfg=cfg2))
    assert captured["cmd"] == ["mytool", "/tmp/task.md", "apps/sample.py"]


def test_get_adapter_by_name(cfg):
    assert adapters.get(cfg) is adapters.headless_cc           # gallery's agent.adapter == headless-cc
    assert adapters.get({**cfg, "agent": {"adapter": "command"}}) is command
    assert adapters.get({**cfg, "agent": {"adapter": "codex"}}) is adapters.codex


def test_codex_adapter_maps_profile_to_exec_flags(monkeypatch, tmp_path):
    """The codex adapter maps the unified agent profile onto `codex exec` flags — model, sandbox, and the
    full-trust bypass for elevated — with the bundle passed as the prompt after `--`."""
    from curiator.loop.adapters import Task, codex

    cap = {}

    class _Proc:
        returncode, stdout, stderr = 0, "ok", ""

    def fake_run(task, c, **k):
        cap["cmd"] = c
        return codex.runlog.RunResult(_Proc.returncode, _Proc.stdout)

    monkeypatch.setattr(codex, "available", lambda: True)
    monkeypatch.setattr(codex.runlog, "run_streamed", fake_run)
    tf = tmp_path / "task.md"
    tf.write_text("the bundle")

    # normal profile → sandboxed workspace-write, model passed, prompt last after --
    codex.run(Task(key="sample", entry={"id": "x"}, source="apps/sample.py", task_file=str(tf),
                   reply_file=str(tmp_path / "reply.md"),
                   cfg={"repo_root": str(tmp_path)},
                   agent={"model": "gpt-5-codex", "permission_mode": "acceptEdits"}))
    cmd = cap["cmd"]
    assert cmd[:2] == ["codex", "exec"]
    assert cmd[cmd.index("-m") + 1] == "gpt-5-codex"
    assert cmd[cmd.index("-s") + 1] == "workspace-write"
    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd
    assert cmd[-2] == "--" and cmd[-1] == "the bundle"

    # elevated → full-trust bypass, no -s sandbox flag
    codex.run(Task(key="sample", entry={"id": "y"}, source="apps/sample.py", task_file=str(tf),
                   reply_file=str(tmp_path / "reply.md"),
                   cfg={"repo_root": str(tmp_path)},
                   agent={"permission_mode": "bypassPermissions", "elevated": True}))
    cmd2 = cap["cmd"]
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd2 and "-s" not in cmd2


# ── elevated (trusted-group) agent profile ─────────────────────────────────
_ELEV_CFG = {"agent": {"autonomy": "auto-small", "permission_mode": "acceptEdits",
                       "elevated": {"groups": ["admin"], "autonomy": "auto",
                                    "permission_mode": "bypassPermissions",
                                    "disallowed_tools": ["Bash(git push:*)"]}}}


def test_effective_agent_merges_elevated_for_trusted_group():
    base = adapters.effective_agent(_ELEV_CFG, {"user": {"groups": ["analysts"]}})
    assert base["elevated"] is False and base["autonomy"] == "auto-small"

    elev = adapters.effective_agent(_ELEV_CFG, {"user": {"groups": ["admin", "x"]}})
    assert elev["elevated"] is True and elev["autonomy"] == "auto"
    assert elev["permission_mode"] == "bypassPermissions"
    assert elev["disallowed_tools"] == ["Bash(git push:*)"]

    assert adapters.effective_agent(_ELEV_CFG, {})["elevated"] is False        # no user → base


def test_elevated_bundle_grants_install_scope(cfg):
    cfg2 = {**cfg, "agent": _ELEV_CFG["agent"]}
    admin = {"id": "f9", "comment": "live quotes via yfinance", "status": "new", "kind": "comment",
             "author": "user", "user": {"groups": ["admin"]}}
    t = build_task(cfg2, "sample", admin)
    body = Path(t.task_file).read_text()
    assert t.agent["elevated"] is True
    assert "ELEVATED" in body and "pip install" in body and "requirements.txt" in body
    # a non-admin author still gets the restricted, one-file bundle
    t2 = build_task(cfg2, "sample", {**admin, "id": "f10", "user": {"groups": ["analysts"]}})
    assert "Edit ONLY the source above" in Path(t2.task_file).read_text()
