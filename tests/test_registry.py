"""registry: gallery.yaml → ALL_APPS, the COLLECTION_ROOT vs PACKAGE_ROOT resolution (regression-guard
for the M1 bug where app sources resolved against the package, not the collection), and sys.path injection.
"""
from __future__ import annotations

import importlib
import sys
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
