"""The GUI conformance suite (src/tests/native/gui/conformance), one test per case.

The suite is one portable BTRC program over the public GUI facade, with a
per-platform probe for the input a person gives a window. This driver builds
it through each compiler, plain and sanitized, and runs every case of
cases.toml in its own process on the session's display. Run it inside
.github/ci/headless-session.sh --x11 or --wayland: the probe sends real input
through the display server, and those sessions are private ones that take it.
"""

import fcntl
import os
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from src.tests.dependencies import BinaryImports, DependencyAudit
from src.tests.process_limits import TOOL_TIMEOUT
from src.tests.python.linux_provider_fixtures import (
    TARGET,
    build_provider_program,
    provider_environment,
    require_linux_reader,
)
from src.tests.runner_capabilities import linux_display_error

REPO = Path(__file__).resolve().parents[3]
SUITE = REPO / "src/tests/native/gui/conformance"
CASES = tomllib.loads((SUITE / "cases.toml").read_text())["case"]
NAMES = [case["name"] for case in CASES]
# What a case needs of a provider beyond the frozen contract, and what this
# platform's provider has.
NEEDS = {case["name"]: case["needs"] for case in CASES if "needs" in case}
HAS = {"web", "freetype", "modal", "wheel"}
LINUX_ONLY = "requires Linux: the GUI conformance suite's Linux rows"
SESSION = os.environ.get("BTRC_UI_SESSION") or (
    "wayland" if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("GDK_BACKEND") == "wayland" else "x11"
)
# Catalog operations no case exercises yet, each with what stands in the way.
UNCOVERED = tomllib.loads((SUITE / "cases.toml").read_text(encoding="utf-8"))["uncovered"]


class ConformancePrograms:
    """One build per compiler and sanitizer mode for the whole run: parallel
    workers share them, and whichever needs one first builds it."""

    def __init__(self, directories):
        base = directories.getbasetemp()
        # Each xdist worker has its own base directory under the run's one.
        self.shared = (base.parent if os.environ.get("PYTEST_XDIST_WORKER") else base) / "conformance"
        self.font_file = None

    def program(self, request, frontend, sanitized):
        """The suite's program for this compiler and mode, built by one worker only."""
        directory = self.shared / f"{frontend}-{'sanitized' if sanitized else 'plain'}"
        directory.mkdir(parents=True, exist_ok=True)
        result = directory / "result"
        with open(directory / "lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not result.exists():
                result.write_text(
                    str(build_provider_program(SUITE / "Main.btrc", directory, frontend, sanitized, request))
                )
        return Path(result.read_text())

    def run(self, request, frontend, sanitized, argument, **extra_environment):
        if sys.platform != "linux":
            pytest.skip(LINUX_ONLY)
        require_linux_reader()
        if error := linux_display_error():
            pytest.skip(error)
        return subprocess.run(
            [str(self.program(request, frontend, sanitized)), argument],
            capture_output=True,
            text=True,
            timeout=120,
            env=provider_environment(
                sanitized,
                UBSAN_OPTIONS="halt_on_error=1",
                BTRC_CONFORMANCE_FONT=self.font(),
                BTRC_CONFORMANCE_WEB=str(SUITE / "web"),
                # WebKit's own sandbox needs user namespaces a CI container does not give it.
                WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS="1",
                **extra_environment,
            ),
        )

    def font(self):
        """A font file this host has, for the font face case."""
        if self.font_file is None:
            self.font_file = subprocess.check_output(
                ["fc-match", "--format=%{file}", "sans"], text=True, timeout=TOOL_TIMEOUT, stderr=subprocess.DEVNULL
            )
        return self.font_file


@pytest.fixture(scope="module")
def programs(tmp_path_factory):
    return ConformancePrograms(tmp_path_factory)


@pytest.mark.linux_gui
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_plain_linux_gui_without_webkit(tmp_path, request, frontend):
    if sys.platform != "linux":
        pytest.skip(LINUX_ONLY)
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    program = build_provider_program(
        REPO / "src/tests/native/gui/plain/NativeControls.btrc", tmp_path, frontend, False, request
    )
    imports = BinaryImports.read(program)
    assert all("webkit" not in library.lower() for library in imports), imports
    assert DependencyAudit().binary_problems(program, TARGET) == []
    result = subprocess.run([program], env=provider_environment(False), capture_output=True, text=True, timeout=120)
    assert result.returncode == 0 and "PASS native controls" in result.stdout, result.stderr


@pytest.mark.linux_gui
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("name", [name for name in NAMES if name not in NEEDS or NEEDS[name] in HAS])
def test_linux_conformance_case(programs, request, name, frontend, sanitized):
    result = programs.run(request, frontend, sanitized, name)
    report = f"{name} on linux-{SESSION} ({frontend}, {'sanitized' if sanitized else 'plain'})\n"
    report += result.stdout + result.stderr
    assert result.returncode == 0, report
    assert "ERROR: AddressSanitizer" not in result.stderr and "runtime error:" not in result.stderr, report
    assert result.stdout.splitlines()[-2:] == [f"CASE {name} PASS", "CONFORMANCE ran=1 failed=0"], report


@pytest.mark.linux_gui
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
def test_wayland_window_and_subtree_capture_without_gpu(programs, request, frontend, tmp_path):
    if SESSION != "wayland":
        pytest.skip("software capture before GPU selection is a Wayland provider capability")
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    guard = tmp_path / "no-gpu.so"
    # Abort on actual public WebGPU instance allocation, even if a driver could
    # have satisfied the request. Native Wayland presents controls in software.
    subprocess.run(
        [
            "cc",
            "-shared",
            "-fPIC",
            "-std=c11",
            "-Werror",
            *shlex.split(subprocess.check_output(["pkg-config", "--cflags", "wgpu-native"], text=True)),
            "-x",
            "c",
            "-",
            "-o",
            guard,
        ],
        input="#include <webgpu.h>\n#include <stdio.h>\n#include <stdlib.h>\n"
        "WGPUInstance wgpuCreateInstance(WGPUInstanceDescriptor const *desc) {"
        ' (void)desc; fputs("GPU allocation intercepted\\n", stderr); _Exit(91); }\n',
        text=True,
        check=True,
    )
    preload = os.pathsep.join(filter(None, (str(guard), os.environ.get("LD_PRELOAD"))))
    for case in ("window.state", "capture.subtree"):
        result = programs.run(request, frontend, False, case, LD_PRELOAD=preload)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.splitlines()[-2:] == [f"CASE {case} PASS", "CONFORMANCE ran=1 failed=0"]
    requested = programs.run(request, frontend, False, "gpu.frame", LD_PRELOAD=preload)
    assert requested.returncode == 91 and "GPU allocation intercepted" in requested.stderr, (
        requested.stdout + requested.stderr
    )


@pytest.mark.linux_gui
def test_the_program_lists_exactly_the_recorded_cases(programs, request):
    listed = programs.run(request, "python", False, "--list")
    assert listed.returncode == 0, listed.stderr
    assert sorted(listed.stdout.split()) == sorted(NAMES)
    assert len(set(NAMES)) == len(NAMES)
