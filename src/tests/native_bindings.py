"""Harness-written packages that bind a native test fixture's header.

A native conformance program calls into a C fixture -- a probe, or an
SDK-shaped fault injector -- and must see that fixture's own declarations, not
prototypes re-spelled in the program: ``f()`` where the header says
``f(void)`` would drift silently. The harness therefore compiles the program
as the one module of a temporary package whose ``btrc.toml`` names the
fixture header in ``[[native.bindings]]``, and the native header reader
supplies the declarations.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest


class NativeBindingPackage:
    """One temporary package: a conformance program bound to one fixture header."""

    READER_REASON = "requires the explicitly built native header reader"

    @classmethod
    def require_reader(cls) -> None:
        """Skip a test whose program binds a header when no reader is configured."""
        if not os.environ.get("BTRC_NATIVE_HEADER_READER"):
            pytest.skip(cls.READER_REASON)

    @staticmethod
    def write(program: Path, directory: Path, header: Path, symbols: tuple[str, ...]) -> Path:
        """Lay out the package under `directory` and return its copy of `program`.

        The program becomes ``src/<Stem>.btrc``, the module the binding
        targets, and the header is copied to the package root beside the
        manifest. Only `symbols` are imported from it.
        """
        source = directory / "src" / program.name
        source.parent.mkdir(parents=True)
        shutil.copyfile(program, source)
        shutil.copyfile(header, directory / header.name)
        names = ", ".join(f'"{symbol}"' for symbol in symbols)
        (directory / "btrc.toml").write_text(
            "manifest-version = 1\n"
            "[package]\n"
            f'name = "{program.stem[0].lower()}{program.stem[1:]}"\n'
            "[[native.bindings]]\n"
            f'module = "{program.stem}"\n'
            f'header = "{header.name}"\n'
            'language = "c"\n'
            'standard = "c11"\n'
            f"symbols = [{names}]\n",
            encoding="utf-8",
        )
        return source
