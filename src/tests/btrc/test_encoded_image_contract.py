"""Provider-neutral encoded-image decode contract conformance."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

REPOSITORY = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).with_name("fixtures") / "EncodedImageContract.btrc"
API = REPOSITORY / "src" / "stdlib" / "EncodedImage.btrc"
STRICT_COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _compile(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=120)


@pytest.mark.skipif(not STRICT_COMPILERS, reason="requires GCC or Clang")
def test_encoded_image_contract_runs_with_both_frontends(semantic_btrcc: Path, tmp_path: Path) -> None:
    generated = {
        "reference": tmp_path / "EncodedImageReference.c",
        "selfhost": tmp_path / "EncodedImageSelfhost.c",
    }
    reference = _compile(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-stdlib",
            "--no-cache",
            str(FIXTURE),
            "-o",
            str(generated["reference"]),
        ],
        REPOSITORY,
    )
    selfhost = _compile([str(semantic_btrcc), "--no-stdlib", str(FIXTURE)], REPOSITORY)
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    generated["selfhost"].write_text(selfhost.stdout)

    for frontend, source in generated.items():
        for compiler in STRICT_COMPILERS:
            executable = tmp_path / f"EncodedImage-{frontend}-{Path(compiler).name}"
            built = _compile(
                [
                    compiler,
                    "-std=c11",
                    "-pedantic-errors",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-O2",
                    str(source),
                    "-lm",
                    "-o",
                    str(executable),
                ],
                REPOSITORY,
            )
            assert built.returncode == 0, built.stderr
            run = _compile([str(executable)], REPOSITORY)
            assert run.returncode == 0, run.stderr
            assert run.stdout == "PASS EncodedImageContract\n"
            assert run.stderr == ""


def test_encoded_image_contract_is_content_only_bounded_and_owning() -> None:
    source = API.read_text()
    assert "interface EncodedImageDecoder" in source
    assert "EncodedImageDecodeOutcome decode(Bytes encoded, EncodedImageDecodeLimits limits);" in source
    assert "maximumInputBytes" in source
    assert "maximumWidth" in source
    assert "maximumHeight" in source
    assert "maximumPixels" in source
    assert "decode(string" not in source
    assert "extension" in source.lower()
    assert "failures own no image" in source
    assert "encodedImageDecodeStatusMessage" in source
