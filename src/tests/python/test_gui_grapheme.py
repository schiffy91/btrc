"""Verify cursor and truncation byte boundaries through the real C ABI and both BTRC compilers."""

import lzma
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.native_bindings import NativeBindingPackage
from src.tests.python.test_network_runtime import _transpile
from tools.native_plan import NativePlanBuilder
from tools.qualification.dependencies import DependencyAudit

ROOT = Path(__file__).resolve().parents[3]
TEXT = ROOT / "src/stdlib/GUI/Text"
FIXTURE = ROOT / "src/tests/native/gui/text"


@pytest.fixture(scope="session")
def grapheme_cases(tmp_path_factory):
    output = tmp_path_factory.mktemp("graphemes") / "boundaries.bin"
    with (
        lzma.open(FIXTURE / "GraphemeBreakTest.txt.xz", "rt", encoding="utf-8") as official,
        output.open("wb") as records,
    ):
        records.write(b"\x00\x00\x01")
        count = 0
        for line in official:
            words = line.partition("#")[0].split()
            if not words:
                continue
            data = bytearray()
            boundaries = []
            for word in words:
                if word == "÷":
                    boundaries.append(len(data))
                elif word != "\N{MULTIPLICATION SIGN}":
                    data.extend(chr(int(word, 16)).encode())
            marks = bytearray(len(data) + 1)
            for at in boundaries:
                marks[at] = 1
            records.write(len(data).to_bytes(2, "big") + data + marks)
            count += 1
        assert count == 766
    return output


@pytest.mark.parametrize("sanitized", [False, True])
def test_gui_grapheme(tmp_path, compiler, request, grapheme_cases, sanitized):
    NativeBindingPackage.require_reader()
    package = tmp_path / "fixture"
    source = NativeBindingPackage.write(
        FIXTURE / "GraphemeConformance.btrc",
        package,
        TEXT / "Grapheme.h",
        ("BtrcGraphemes", "btrcGraphemeBoundaries", "btrcGraphemeFloor", "btrcGraphemeCeil", "btrcGraphemeDestroy"),
    )
    for name in ("Grapheme.c", "GraphemeData.h", "UTF8.h"):
        shutil.copyfile(TEXT / name, package / name)
    with (package / "btrc.toml").open("a") as manifest:
        manifest.write(
            '\n[[native.sources]]\npath = "Grapheme.c"\nmodules = ["GraphemeConformance"]\nlanguage = "c"\nstandard = "c11"\n'
        )
    generated, client = tmp_path / "Program.c", tmp_path / "Program"
    plan = _transpile(compiler, source, generated, request)
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitized else []
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=client,
        optimization=1 if sanitized else 2,
        compile_flags=["-Wall", "-Wextra", "-Werror", "-pedantic-errors", *flags],
        link_flags=flags,
    )
    assert not DependencyAudit().binary_problems(client, PackageTarget.parse(None).label)
    result = subprocess.run(
        [client, grapheme_cases],
        capture_output=True,
        timeout=20,
        env=os.environ | {"ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1"},
    )
    assert result.returncode == 0 and not result.stderr, result.stderr
