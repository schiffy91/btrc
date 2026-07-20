"""Production-driver parity for explicit source dependencies."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CC = shlex.split(os.environ.get("BTRC_CC", "cc"))

pytestmark = pytest.mark.skipif(
    not CC or shutil.which(CC[0]) is None,
    reason="needs a C compiler",
)


def _run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_no_stdlib_still_resolves_explicit_include_and_import(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    legacy_helper = tmp_path / "legacy_helper.btrc"
    imported_helper = tmp_path / "imported_helper.btrc"
    program = tmp_path / "program.btrc"
    legacy_helper.write_text("int legacyValue() { return 19; }\n")
    imported_helper.write_text("int importedValue() { return 23; }\n")
    program.write_text(
        '#include "legacy_helper.btrc"\n'
        "import ./imported_helper.btrc\n"
        "int main() { return legacyValue() + importedValue() == 42 ? 0 : 1; }\n"
    )

    selfhost = _run([str(semantic_btrcc), "--no-stdlib", str(program)])
    selfhost_c = tmp_path / "selfhost.c"
    if selfhost.returncode == 0:
        selfhost_c.write_text(selfhost.stdout)

    reference_c = tmp_path / "reference.c"
    reference = _run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(program),
            "--no-stdlib",
            "--no-cache",
            "-o",
            str(reference_c),
        ]
    )

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    for frontend, generated in (("selfhost", selfhost_c), ("reference", reference_c)):
        source = generated.read_text()
        assert "legacyValue" in source
        assert "importedValue" in source
        assert "legacy_helper.btrc" not in source
        assert "imported_helper.btrc" not in source
        executable = tmp_path / frontend
        build = _run(
            [
                *CC,
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(generated),
                "-lm",
                "-o",
                str(executable),
            ]
        )
        assert build.returncode == 0, build.stderr
        executed = _run([str(executable)], timeout=30)
        assert executed.returncode == 0, executed.stderr
