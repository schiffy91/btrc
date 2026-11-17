"""A sample of helper drivers is still built by the reference compiler.

Every helper driver is transpiled by the session's self-hosted compiler
(src/tests/selfhost_cache.py), so the reference compiler would otherwise
build only one program that imports compiler modules: the compiler itself.
These two tool drivers are built through both, and each pair must agree on
real input, which keeps the reference path covered on such programs and
checks the self-hosted build of them against it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.selfhost_snippet_harness import run_in_repo
from src.tests.selfhost_cache import REFERENCE

REPO = Path(__file__).resolve().parents[3]
SAMPLE = ("src/compiler/btrc/tools/LexMain.btrc", "src/compiler/btrc/tools/ParseMain.btrc")
INPUTS = (
    "src/tests/basics/Nullable.btrc",
    "src/tests/classes/Interfaces.btrc",
    "src/tests/generics/UserGenerics.btrc",
)


def test_sample_inputs_exist() -> None:
    assert all((REPO / path).is_file() for path in (*SAMPLE, *INPUTS))


@pytest.mark.parametrize("source", SAMPLE)
def test_reference_built_driver_agrees_with_the_selfhost_built_one(selfhost_driver, source: str) -> None:
    flags = ("-pedantic-errors",)
    selfhost = selfhost_driver(REPO / source, compile_flags=flags)
    reference = selfhost_driver(REPO / source, compile_flags=flags, frontend=REFERENCE)
    assert selfhost != reference, "the two frontends must not share one cached driver"
    for path in INPUTS:
        expected = run_in_repo([str(reference), str(REPO / path)], timeout=60)
        actual = run_in_repo([str(selfhost), str(REPO / path)], timeout=60)
        assert expected.returncode == 0 and expected.stdout, expected.stderr
        assert (actual.returncode, actual.stdout, actual.stderr) == (
            expected.returncode,
            expected.stdout,
            expected.stderr,
        )
