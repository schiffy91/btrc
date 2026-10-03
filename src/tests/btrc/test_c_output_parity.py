"""The corpus programs whose C both compilers emit byte for byte.

``src/tests/fixtures/c_output_parity/identical.txt`` lists them; each must keep
transpiling to identical C through the Python compiler and ``btrcc``, with the
checkout path as the only normalization. A program leaves the list only by a
reviewed manifest edit, never by drifting. Re-measure the corpus and rewrite
the list with ``python3 -m src.tests.c_output_parity survey --btrcc <btrcc>
--write-manifest``.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

import pytest

from src.tests.c_output_parity import IDENTICAL_MANIFEST, COutputParitySurvey
from src.tests.process_limits import TRANSPILE_TIMEOUT

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires the POSIX self-host driver")

PROGRAMS = COutputParitySurvey.manifest_programs()


def test_manifest_lists_sorted_unique_corpus_programs() -> None:
    assert PROGRAMS, f"{IDENTICAL_MANIFEST} lists no program"
    assert sorted(set(PROGRAMS)) == PROGRAMS, "keep the manifest sorted and free of duplicates"
    missing = sorted(set(PROGRAMS) - set(COutputParitySurvey.corpus_programs()))
    assert not missing, f"manifest entries that are not runnable corpus programs: {missing}"


@pytest.fixture(scope="module")
def survey(immutable_btrcc: Path) -> COutputParitySurvey:
    return COutputParitySurvey(immutable_btrcc, timeout=TRANSPILE_TIMEOUT)


@pytest.mark.parametrize("program", PROGRAMS)
def test_both_compilers_emit_identical_c(survey: COutputParitySurvey, program: str) -> None:
    python_source = survey.python_c(program)
    btrcc_source = survey.btrcc_c(program)
    if python_source != btrcc_source:
        diff = difflib.unified_diff(
            python_source.splitlines(), btrcc_source.splitlines(), "python", "btrcc", n=2, lineterm=""
        )
        pytest.fail(f"{program}: the compilers' C diverged\n" + "\n".join(list(diff)[:60]))
