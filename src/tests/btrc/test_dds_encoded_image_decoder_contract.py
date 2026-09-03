"""Pure BTRC DDS DXT1/DXT5 decoder conformance."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

REPOSITORY = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).with_name("fixtures") / "DdsEncodedImageDecoderContract.btrc"
API = REPOSITORY / "src" / "stdlib" / "DdsEncodedImageDecoder.btrc"
STRICT_COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=120)


@pytest.mark.skipif(not STRICT_COMPILERS, reason="requires GCC or Clang")
def test_dds_decoder_runs_with_both_frontends(semantic_btrcc: Path, tmp_path: Path) -> None:
    generated = {
        "reference": tmp_path / "DdsEncodedImageReference.c",
        "selfhost": tmp_path / "DdsEncodedImageSelfhost.c",
    }
    reference = _run(
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
    selfhost = _run([str(semantic_btrcc), "--no-stdlib", str(FIXTURE)], REPOSITORY)
    assert reference.returncode == 0, reference.stderr
    assert selfhost.returncode == 0, selfhost.stderr
    generated["selfhost"].write_text(selfhost.stdout)

    for frontend, source in generated.items():
        for compiler in STRICT_COMPILERS:
            executable = tmp_path / f"DdsEncodedImage-{frontend}-{Path(compiler).name}"
            built = _run(
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
            ran = _run([str(executable)], REPOSITORY)
            assert ran.returncode == 0, ran.stderr
            assert ran.stdout == "PASS DdsEncodedImageDecoderContract\n"
            assert ran.stderr == ""


def test_dds_decoder_is_bounded_and_content_driven() -> None:
    source = API.read_text()
    assert "implements EncodedImageDecoder" in source
    assert "68, 88, 84, 49" in source
    assert "68, 88, 84, 53" in source
    assert "limits.allowsInput(inputBytes)" in source
    assert "limits.allowsDimensions(header.width(), header.height())" in source
    assert "filename" not in source.lower()
