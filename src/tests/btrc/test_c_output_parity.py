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
import re
import subprocess
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


def test_function_temporary_identity_survives_rebuilds_and_unrelated_lowering(
    immutable_btrcc: Path, tmp_path: Path
) -> None:
    from src.compiler.python import Compiler, CompilerOptions

    compiler = Compiler()
    options = CompilerOptions(include_stdlib=False, use_cache=False, dce=False)
    program = tmp_path / "TemporaryIdentity.btrc"
    # Repeated effectful operands force generated temporaries and long emitted
    # expressions. Keep unrelated functions so DCE cannot hide a module counter.
    interpolations = " ".join("{advance(value)}" for _ in range(80))
    probe = f'string stableProbe(int value) {{ return f"{interpolations}"; }}\n'
    expected = None
    for unrelated in (0, 0, 1, 12):
        source = (
            "int advance(int value) { return value + 1; }\n"
            + "".join(probe.replace("stableProbe", f"unrelated{index}") for index in range(unrelated))
            + probe
            + "int main() { print(stableProbe(1)); return 0; }\n"
        )
        program.write_text(source)
        reference = compiler.compile(source, str(program), options)
        assert reference.failure is None, reference.failure
        selfhost = subprocess.run(
            [str(immutable_btrcc), "--no-stdlib", "--no-dce", str(program)],
            capture_output=True,
            text=True,
            timeout=TRANSPILE_TIMEOUT,
        )
        assert selfhost.returncode == 0, selfhost.stderr
        for frontend, emitted in (("reference", reference.c_source), ("selfhost", selfhost.stdout)):
            match = re.search(r"^[^\n;]*\bstableProbe\([^;{}]*\) \{\n.*?^\}", emitted, re.MULTILINE | re.DOTALL)
            assert match is not None, f"{frontend}: missing stableProbe definition"
            body = match.group()
            assert len(body) > 1000 and re.search(r"\b__btrc_\w+_\d+\b", body), body
            if expected is None:
                expected = body
            assert body == expected, f"{frontend}: unrelated={unrelated} changed temporary names or line structure"
