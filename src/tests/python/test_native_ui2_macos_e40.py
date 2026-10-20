"""E40 AppKit evidence: build locally; run visible native trials only on hosted CI."""

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.python.native_ui2_e40_evidence import E40Evidence
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "src/tests/native/gui/ui2/probes/macos/e40"


@pytest.fixture(params=[False, True], ids=["plain", "sanitized"])
def sanitized(request):
    return request.param


@pytest.fixture
def boundary_program(native_project, native_compile, gui_provider_root, sanitized, request):
    source, _, triple = native_project
    package = source.parent.parent
    for suffix in ("h", "m"):
        name = f"Boundary.{suffix}"
        (package / name).write_text((FIXTURES / name).read_text())
    symbols = [
        "+[BTRCE40Boundary requireHosted]",
        "+[BTRCE40Boundary setup:output:]",
        "+[BTRCE40Boundary ready]",
        "+[BTRCE40Boundary begin:final:repeat:ordinal:]",
        "+[BTRCE40Boundary key]",
        "+[BTRCE40Boundary text:]",
        "+[BTRCE40Boundary close]",
        "+[BTRCE40Boundary complete]",
        "+[BTRCE40Boundary finish]",
        "+[BTRCE40Boundary report]",
        "+[BTRCE40Boundary cleanup]",
        "+[BTRCE40Boundary runHost]",
    ]
    manifest = package / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "Boundary.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        f"symbols = {json.dumps(symbols)}\n"
        '[[native.sources]]\npath = "Boundary.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
    )
    source.write_text((FIXTURES / "Boundary.btrc").read_text())
    plan = package / "Boundary.link.json"
    compiled = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    generated = package / "Boundary.c"
    generated.write_text(compiled.c_source)
    executable = package / "Boundary"

    def runner(command, **kwargs):
        flags = ["-O1"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitized:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    frontend = request.node.callspec.params["native_compile"]
    provenance = {
        "frontend": frontend,
        "sanitized": sanitized,
        "target": triple,
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_changes": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).splitlines(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "selfhost_binary": os.environ.get("BTRC_TEST_BTRCC") if frontend == "selfhost" else None,
        "physical_device_latency": "not measured",
        "input": "synthetic queued AppKit events",
    }
    return executable, provenance


def test_macos_ui2_e40_boundary_compile(boundary_program):
    """Compilation/linking only: the executable is never launched by this case."""
    executable, _ = boundary_program
    assert executable.is_file()


@pytest.mark.macos_gui
@pytest.mark.skipif(
    sys.platform == "darwin" and (os.environ.get("BTRC_UI2_HOSTED_E40") != "1" or os.environ.get("CI") != "true"),
    reason="E40 visible native execution requires explicit hosted CI opt-in",
)
@pytest.mark.parametrize("trial", ["bursts"])
@pytest.mark.parametrize("entry", ["desktop", "host"])
def test_macos_ui2_e40(boundary_program, sanitized, entry, trial, tmp_path):
    executable, provenance = boundary_program
    artifact_root = Path(os.environ.get("BTRC_UI2_E40_ARTIFACTS", str(tmp_path / "e40")))
    directory = artifact_root / provenance["frontend"] / ("sanitized" if sanitized else "plain") / entry / trial
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / "observations.json"
    (directory / "provenance.json").write_text(json.dumps(provenance, indent=2))
    environment = apple_environment() | {"UBSAN_OPTIONS": "halt_on_error=1"}
    environment.pop("BTRC_GUI_BACKGROUND", None)
    command = [str(executable), entry, str(report.resolve())]
    try:
        result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
        result = subprocess.CompletedProcess(command, -124, stdout, stderr + "\nE40 timed out after 1800 seconds.\n")
    (directory / "stdout.txt").write_text(result.stdout)
    (directory / "stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report.is_file(), "Native trial returned without evidence"
    E40Evidence(json.loads(report.read_text()), sanitized).bursts()
    assert "PASS: E40 macOS native boundary bursts" in result.stdout
