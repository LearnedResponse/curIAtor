"""curiator.cli package shim.

The console entrypoint remains ``curiator.cli:main`` while the implementation lives in
``curiator.cli.__main__`` so ``python -m curiator.cli`` works too.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any


def _entry():
    return import_module("curiator.cli.__main__")


def main(argv=None) -> int:
    return _entry().main(argv)


def __getattr__(name: str) -> Any:
    try:
        return getattr(_entry(), name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
