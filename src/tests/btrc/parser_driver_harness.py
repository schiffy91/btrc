"""The parser-stage self-host driver beside the shared production compiler, for parser diagnostics tests."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


DRIVER_SOURCES = {
    "parser": "src/compiler/btrc/tools/ParseMain.btrc",
    "compiler": "src/compiler/btrc/BtrccMain.btrc",
}


@pytest.fixture(scope="module")
def selfhost_drivers(selfhost_driver, immutable_btrcc: Path) -> dict[str, Path]:
    """The parser-stage and production self-host drivers.

    The production driver is the compiler the suite already shares; the parser
    tool driver comes from the shared session cache, so it is built once per
    revision rather than once per xdist worker reaching this module.
    """

    drivers = {
        name: selfhost_driver(REPO / source, compile_flags=("-pedantic-errors",))
        for name, source in DRIVER_SOURCES.items()
        if name != "compiler"
    }
    drivers["compiler"] = immutable_btrcc
    return drivers
