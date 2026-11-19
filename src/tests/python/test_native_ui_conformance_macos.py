"""The GUI conformance suite's macOS rows (src/tests/native/gui/conformance).

The same portable program and cases as test_native_ui_conformance.py, built for
the AppKit provider with its own probe (probes/macos/AppKitProbe.m) through
each compiler, plain and sanitized. Every case runs in its own process on the
session's display.
"""

import platform
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.native_bindings import NativeBindingPackage
from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_ui_shell_fixtures import transpile
from src.tests.python.test_native_ui_conformance import NAMES, NEEDS, SUITE
from tools.native_plan import NativePlanBuilder

MACOS_ONLY = "requires macOS: the GUI conformance suite's macOS rows"
# What the AppKit provider has beyond the frozen contract (cases.toml `needs`).
HAS: set[str] = {"web", "freetype"}
# The font face case reads a font file; these ship with every macOS release.
FONTS = (Path("/System/Library/Fonts/Supplemental/Arial.ttf"), Path("/System/Library/Fonts/Helvetica.ttc"))
SANITIZERS = ("-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer")


class MacOSConformancePrograms:
    """One build per compiler and sanitizer mode, kept for the module."""

    def __init__(self, directories):
        self.directories = directories
        self.built = {}

    def program(self, request, frontend, sanitized):
        key = (frontend, sanitized)
        if key not in self.built:
            mode = "sanitized" if sanitized else "plain"
            self.built[key] = self.build(self.directories.mktemp(f"conformance-macos-{frontend}-{mode}"), request, *key)
        return self.built[key]

    def build(self, directory, request, frontend, sanitized):
        generated, plan = directory / "Program.c", directory / "Program.json"
        architecture = "aarch64" if platform.machine() == "arm64" else "x86_64"
        result = transpile(SUITE / "Main.btrc", generated, plan, frontend, request, f"macos-{architecture}")
        assert result.returncode == 0, result.stderr
        assert "warning:" not in result.stderr.lower(), result.stderr
        flags = list(SANITIZERS) if sanitized else []
        environment = apple_environment()

        def run(command, **kwargs):
            command = list(command)
            if "-c" in command:
                command[1:1] = flags
            elif "-o" in command:
                command.extend(flags)
            return subprocess.run(command, env=environment, **kwargs)

        executable = directory / "Program"
        NativePlanBuilder(runner=run).build(
            plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
        )
        return executable

    def run(self, request, frontend, sanitized, argument):
        if sys.platform != "darwin":
            pytest.skip(MACOS_ONLY)
        NativeBindingPackage.require_reader()
        font = next((str(path) for path in FONTS if path.is_file()), "")
        return subprocess.run(
            [str(self.program(request, frontend, sanitized)), argument],
            capture_output=True,
            text=True,
            timeout=120,
            env={
                **apple_environment(),
                "ASAN_OPTIONS": "detect_leaks=0",
                "UBSAN_OPTIONS": "halt_on_error=1",
                "BTRC_CONFORMANCE_FONT": font,
                "BTRC_CONFORMANCE_WEB": str(SUITE / "web"),
            },
        )


@pytest.fixture(scope="module")
def programs(tmp_path_factory):
    return MacOSConformancePrograms(tmp_path_factory)


@pytest.mark.macos_gui
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("name", [name for name in NAMES if name not in NEEDS or NEEDS[name] in HAS])
def test_macos_conformance_case(programs, request, name, frontend, sanitized):
    result = programs.run(request, frontend, sanitized, name)
    report = f"{name} on macos ({frontend}, {'sanitized' if sanitized else 'plain'})\n"
    report += result.stdout + result.stderr
    assert result.returncode == 0, report
    assert "ERROR: AddressSanitizer" not in result.stderr and "runtime error:" not in result.stderr, report
    assert result.stdout.splitlines()[-2:] == [f"CASE {name} PASS", "CONFORMANCE ran=1 failed=0"], report


@pytest.mark.macos_gui
def test_the_macos_program_lists_exactly_the_recorded_cases(programs, request):
    listed = programs.run(request, "python", False, "--list")
    assert listed.returncode == 0, listed.stderr
    assert sorted(listed.stdout.split()) == sorted(NAMES)
