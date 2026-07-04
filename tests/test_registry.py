"""registry: gallery.yaml → ALL_APPS, the COLLECTION_ROOT vs PACKAGE_ROOT resolution (regression-guard
for the M1 bug where app sources resolved against the package, not the collection), and sys.path injection.
"""
from __future__ import annotations

import importlib
import sys
import textwrap
from pathlib import Path


def _fresh_registry():
    import curiator.shell.registry as reg
    return importlib.reload(reg)


def test_sources_resolve_against_collection_not_package(collection):
    saved = list(sys.path)
    try:
        reg = _fresh_registry()
        # the bug: sources resolved against the curiator package root. Guard both halves:
        assert reg.COLLECTION_ROOT == collection.resolve()
        assert reg.PACKAGE_ROOT != collection.resolve()
        app = reg.ALL_APPS[0]
        assert app["key"] == "sample"
        assert app["file"] == str((collection / "apps" / "sample.py").resolve())
        assert Path(app["file"]).exists()
    finally:
        sys.path[:] = saved


def test_registry_uses_process_gallery_override_without_env(collection, monkeypatch):
    from curiator.config import set_gallery_override

    monkeypatch.delenv("CURIATOR_GALLERY", raising=False)
    set_gallery_override(collection / "gallery.yaml")
    saved = list(sys.path)
    try:
        reg = _fresh_registry()
        assert reg.GALLERY_YAML == (collection / "gallery.yaml").resolve()
        assert reg.ALL_APPS[0]["key"] == "sample"
    finally:
        set_gallery_override(None)
        sys.path[:] = saved


def test_injects_app_source_dir_on_syspath(collection):
    saved = list(sys.path)
    try:
        _fresh_registry()
        assert str((collection / "apps").resolve()) in sys.path   # so importlib.import_module("sample") resolves
    finally:
        sys.path[:] = saved


def test_tag_meta_exposed(collection):
    saved = list(sys.path)
    try:
        reg = _fresh_registry()
        assert isinstance(reg.ALL_APPS, list) and reg.ALL_APPS
        assert hasattr(reg, "TAG_META")
    finally:
        sys.path[:] = saved


def test_app_root_can_expand_to_multiple_mounts(collection):
    (collection / "apps" / "suite").mkdir()
    (collection / "apps" / "suite" / "sales.py").write_text("x = 1\n")
    (collection / "apps" / "suite" / "ops.py").write_text("x = 2\n")
    (collection / "gallery.yaml").write_text(textwrap.dedent('''\
        apps:
          - name: suite
            root: apps/suite
            tags: [demo]
            mounts:
              - name: suite_sales
                title: Suite sales
                source: sales.py
                mount: { kind: dash-inproc, module: sales }
              - name: suite_ops
                title: Suite ops
                source: ops.py
                mount: { kind: proxy, cmd: "python server.py --port {port}", port: 8811 }
        feedback: { dir: feedback }
    '''))
    saved = list(sys.path)
    try:
        reg = _fresh_registry()
        by = {a["name"]: a for a in reg.ALL_APPS}
        assert set(by) == {"suite_sales", "suite_ops"}
        assert by["suite_sales"]["root"].endswith("apps/suite")
        assert by["suite_sales"]["source"].endswith("apps/suite/sales.py")
        assert by["suite_sales"]["mount"]["module"] == "sales"
        assert by["suite_ops"]["mount"]["kind"] == "proxy"
        assert "8811" in by["suite_ops"]["mount"]["cmd"]
        assert str((collection / "apps" / "suite").resolve()) in sys.path
    finally:
        sys.path[:] = saved


def test_registry_renders_engine_backed_proxy_placeholders(collection):
    (collection / "apps" / "twin").mkdir()
    (collection / "gallery.yaml").write_text(textwrap.dedent('''\
        apps:
          - name: twin
            root: apps/twin
            source: .
            mount:
              kind: engine-backed
              cmd: "python server.py --port {port} --engine {engine_url}"
              port: 8742
              engine: "python engine.py --port {engine_port}"
              engine_port: 8842
              engine_health: /health
        feedback: { dir: feedback }
    '''))
    saved = list(sys.path)
    try:
        reg = _fresh_registry()
        app = reg.ALL_APPS[0]
        assert app["mount"]["cmd"] == "python server.py --port 8742 --engine http://127.0.0.1:8842"
    finally:
        sys.path[:] = saved
