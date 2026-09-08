"""Cycle-suspect buffer removal stays correct when many suspects die at once."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.test_mutex_value_contract import COMPILERS, REPO, _build_and_run, _compile_pair

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)
pytestmark = pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")

FIXTURE = Path(__file__).with_name("fixtures") / "CycleSuspectChurn.btrc"
EXPECTED_STDOUT = "total=37495500\nPASS: cycle suspect churn\n"


def test_forgetting_a_suspect_uses_its_hash_slot_index(semantic_btrcc: Path, tmp_path: Path) -> None:
    """Both compilers materialize the indexed suspect buffer and the program runs clean."""
    for frontend, generated in _compile_pair(semantic_btrcc, tmp_path, FIXTURE.read_text(), FIXTURE.stem):
        emitted = generated.read_text()
        assert "__btrc_suspect_slots" in emitted, frontend
        assert "__btrc_suspect_slots[key] = __btrc_suspect_count;" in emitted, frontend
        for compiler in COMPILERS:
            output = tmp_path / f"{frontend}-{Path(compiler).name}"
            _build_and_run(generated, output, compiler)
            executed = subprocess.run(
                [str(output)],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert executed.returncode == 0, executed.stderr
            assert executed.stdout == EXPECTED_STDOUT


def test_suspect_churn_is_sanitizer_clean(semantic_btrcc: Path, tmp_path: Path) -> None:
    """The swap-removal keeps the hash and buffer in sync under AddressSanitizer."""
    for frontend, generated in _compile_pair(semantic_btrcc, tmp_path, FIXTURE.read_text(), FIXTURE.stem):
        output = tmp_path / f"{frontend}-asan"
        _build_and_run(generated, output, COMPILERS[0], extra_flags=("-fsanitize=address,undefined", "-g"))
        executed = subprocess.run(
            [str(output)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert executed.returncode == 0, executed.stderr
        assert executed.stdout == EXPECTED_STDOUT
