"""The GUI conformance suite (src/tests/native/gui/conformance), one test per case.

The suite is one portable BTRC program over the public GUI facade, with a
per-platform probe for the input a person gives a window. This driver builds
it through each compiler, plain and sanitized, and runs every case of
cases.toml in its own process on the session's display. Run it inside
tools/ui/headless-session.sh --x11 or --wayland.
"""

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from src.tests.process_limits import TOOL_TIMEOUT
from src.tests.python.linux_provider_fixtures import (
    build_provider_program,
    provider_environment,
    require_linux_reader,
)
from src.tests.runner_capabilities import linux_display_error

REPO = Path(__file__).resolve().parents[3]
SUITE = REPO / "src/tests/native/gui/conformance"
CASES = tomllib.loads((SUITE / "cases.toml").read_text())["case"]
NAMES = [case["name"] for case in CASES]
LINUX_ONLY = "requires Linux: the GUI conformance suite's Linux rows"
# Catalog operations no case exercises yet, each with what stands in the way.
UNCOVERED = {
    "IWindow.showAlert": "modal: the probe cannot yet dismiss the alert it would open",
    "GUI.chooseDirectory": "modal: the probe cannot yet answer the picker it would open",
    "IDirectoryPicker.chooseDirectory": "modal: the probe cannot yet answer the picker it would open",
    "IApplication.pollClose": "the facade never calls it, and the suite reaches the application through the facade only",
}


class ConformancePrograms:
    """One build per compiler and sanitizer mode, kept for the module."""

    def __init__(self, directories):
        self.directories = directories
        self.built = {}
        self.font_file = None

    def program(self, request, frontend, sanitized):
        key = (frontend, sanitized)
        if key not in self.built:
            directory = self.directories.mktemp(f"conformance-{frontend}-{'sanitized' if sanitized else 'plain'}")
            self.built[key] = build_provider_program(SUITE / "Main.btrc", directory, frontend, sanitized, request)
        return self.built[key]

    def run(self, request, frontend, sanitized, argument):
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
            env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1", BTRC_CONFORMANCE_FONT=self.font()),
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


def session():
    return "wayland" if os.environ.get("SDL_VIDEODRIVER") == "wayland" else "x11"


@pytest.mark.linux_gui
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("name", NAMES)
def test_linux_conformance_case(programs, request, name, frontend, sanitized):
    result = programs.run(request, frontend, sanitized, name)
    report = f"{name} on linux-{session()} ({frontend}, {'sanitized' if sanitized else 'plain'})\n"
    report += result.stdout + result.stderr
    assert result.returncode == 0, report
    assert "ERROR: AddressSanitizer" not in result.stderr and "runtime error:" not in result.stderr, report
    assert result.stdout.splitlines()[-2:] == [f"CASE {name} PASS", "CONFORMANCE ran=1 failed=0"], report


@pytest.mark.linux_gui
def test_the_program_lists_exactly_the_recorded_cases(programs, request):
    listed = programs.run(request, "python", False, "--list")
    assert listed.returncode == 0, listed.stderr
    assert sorted(listed.stdout.split()) == sorted(NAMES)
    assert len(set(NAMES)) == len(NAMES)


def test_the_cases_cover_the_catalog_but_for_the_listed_operations():
    """Every catalog operation is exercised by a case or named in UNCOVERED with its reason."""
    catalog = set()
    for shard in sorted((REPO / "docs/design/native-ui-catalog/operations").glob("*.toml")):
        catalog.update(operation["id"] for operation in tomllib.loads(shard.read_text()).get("operations", []))
    covered = [operation for case in CASES for operation in case["operations"]]
    assert len(covered) == len(set(covered)), "an operation is recorded under two cases"
    assert set(covered) | set(UNCOVERED) == catalog
    assert not set(covered) & set(UNCOVERED)
