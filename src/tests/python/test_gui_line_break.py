"""Exercise every published Unicode 17 line-break case through native bindings."""

import lzma
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageTarget
from src.tests.native_bindings import NativeBindingPackage
from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.test_network_runtime import _transpile
from tools.native_plan import NativePlanBuilder
from tools.qualification.dependencies import DependencyAudit

ROOT = Path(__file__).resolve().parents[3]
TEXT = ROOT / "src/stdlib/GUI/Text"
FIXTURE = ROOT / "src/tests/native/gui/text"


@pytest.fixture(scope="session")
def line_break_cases(tmp_path_factory):
    output = tmp_path_factory.mktemp("line-breaks") / "cases.bin"
    mandatory = {0xA, 0xB, 0xC, 0xD, 0x85, 0x2028, 0x2029}
    with lzma.open(FIXTURE / "LineBreakTest.txt.xz", "rt", encoding="utf-8") as official, output.open("wb") as records:
        records.write(b"\x00\x00\x02")  # the empty input ends at zero
        count = 0
        for line in official:
            words = line.partition("#")[0].split()
            if not words:
                continue
            data = bytearray()
            decisions = {}
            previous = None
            for word in words:
                if word == "÷":
                    decisions[len(data)] = 2 if previous in mandatory else 1
                elif word != "\N{MULTIPLICATION SIGN}":
                    previous = int(word, 16)
                    data.extend(chr(previous).encode())
            assert len(data) in decisions
            decisions[len(data)] = 2
            marks = bytearray(len(data) + 1)
            for at, decision in decisions.items():
                marks[at] = decision
            records.write(len(data).to_bytes(2, "big") + data + marks)
            count += 1
        assert count == 19338
    return output


@pytest.mark.parametrize("sanitized", [False, True])
def test_gui_line_break(tmp_path, compiler, request, line_break_cases, sanitized):
    NativeBindingPackage.require_reader()
    package = tmp_path / "fixture"
    source = NativeBindingPackage.write(
        FIXTURE / "LineBreakConformance.btrc",
        package,
        TEXT / "LineBreak.h",
        ("BtrcLineOpportunity", "BtrcLineBreaks", "btrcLineBreaks", "btrcLineBreakDestroy"),
    )
    for name in ("LineBreak.c", "LineBreakData.h", "UTF8.h"):
        shutil.copyfile(TEXT / name, package / name)
    with (package / "btrc.toml").open("a") as manifest:
        manifest.write(
            '\n[[native.sources]]\npath = "LineBreak.c"\nmodules = ["LineBreakConformance"]\nlanguage = "c"\nstandard = "c11"\n'
        )
    generated, program = tmp_path / "Program.c", tmp_path / "Program"
    plan = _transpile(compiler, source, generated, request)
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitized else []
    builder, toolchain = NativePlanBuilder(), {}
    run_env = os.environ
    if sanitized and sys.platform == "darwin":

        def run(command, **options):
            return subprocess.run(command, **{**options, "env": apple_environment(options.get("env"))})

        builder = NativePlanBuilder(runner=run)
        toolchain = {"cc": "/usr/bin/clang", "cxx": "/usr/bin/clang++"}
        run_env = apple_environment(run_env)
    builder.build(
        plan_path=plan,
        generated_c=generated,
        output=program,
        optimization=1 if sanitized else 2,
        compile_flags=["-Wall", "-Wextra", "-Werror", "-pedantic-errors", *flags],
        link_flags=flags,
        **toolchain,
    )
    assert not DependencyAudit().binary_problems(program, PackageTarget.parse(None).label)
    asan_options = "halt_on_error=1" if sys.platform == "darwin" else "detect_leaks=1:halt_on_error=1"
    result = subprocess.run(
        [program, line_break_cases],
        capture_output=True,
        timeout=30,
        env=run_env | {"ASAN_OPTIONS": asan_options, "UBSAN_OPTIONS": "halt_on_error=1"},
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
