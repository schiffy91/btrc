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
def e40_program(native_project, native_compile, gui_provider_root, sanitized, request):
    source, _, triple = native_project
    package = source.parent.parent
    trial = request.node.callspec.params.get("trial", "bursts")
    stem = "Boundary" if trial == "bursts" else "Load"
    for suffix in ("h", "m"):
        name = f"{stem}.{suffix}"
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
    if stem == "Load":
        symbols = [
            "e40LoadRequireHosted",
            "e40LoadSetup",
            "e40LoadReady",
            "e40LoadObserveSurfaces",
            "e40LoadNow",
            "e40LoadBegin",
            "e40LoadProducerTick",
            "e40LoadReceipt",
            "e40LoadReject",
            "e40LoadDeliver",
            "e40LoadHandler",
            "e40LoadPending",
            "e40LoadPushInput",
            "e40LoadInputDelivery",
            "e40LoadPushClose",
            "e40LoadTryFrame",
            "e40LoadDeadline",
            "e40LoadRejectFrame",
            "e40LoadReport",
            "e40LoadCleanup",
            "e40LoadRunHost",
        ]
    if stem == "Load":
        (package / "Presentation.h").write_text((FIXTURES / "Presentation.h").read_text())
        symbols += [
            "e40LoadTrial",
            "e40TrackingStart",
            "e40TrackingTick",
            "e40TrackingDone",
            "e40TrackingSemantic",
            "e40TrackingPointer",
        ]
        for suffix in ("h", "m"):
            name = f"Tracking.{suffix}"
            (package / name).write_text((FIXTURES / name).read_text())
    language = "objective-c" if stem == "Boundary" else "c"
    manifest = package / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + f'\n[[native.bindings]]\nmodule = "Main"\nheader = "{stem}.h"\n'
        f'language = "{language}"\nstandard = "c11"\nos = ["macos"]\n'
        f"symbols = {json.dumps(symbols)}\n"
        f'[[native.sources]]\npath = "{stem}.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.frameworks]]\nname = "QuartzCore"\nmodules = ["Main"]\nos = ["macos"]\n'
        '[[native.frameworks]]\nname = "Metal"\nmodules = ["Main"]\nos = ["macos"]\n'
    )
    if stem == "Load":
        with manifest.open("a") as stream:
            stream.write(
                '[[native.sources]]\npath = "Tracking.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
                '[[native.frameworks]]\nname = "CoreGraphics"\nmodules = ["Main"]\nos = ["macos"]\n'
            )
    (source.parent / "Host.btrc").write_text((FIXTURES / "Host.btrc").read_text())
    source.write_text((FIXTURES / f"{stem}.btrc").read_text())
    plan = package / f"{stem}.link.json"
    compiled = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert compiled.successful, str(compiled.failure) + str(compiled.diagnostics)
    generated = package / f"{stem}.c"
    generated.write_text(compiled.c_source)
    executable = package / stem

    native_build_commands = []

    def runner(command, **kwargs):
        flags = []
        if Path(command[0]).name in {"clang", "clang++"} and sanitized:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
        executed = [str(command[0]), *flags, *(str(argument) for argument in command[1:])]
        native_build_commands.append(executed)
        return subprocess.run(executed, env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan,
        generated_c=generated,
        output=executable,
        cc="/usr/bin/clang",
        cxx="/usr/bin/clang++",
        optimization=2,
    )
    frontend = request.node.callspec.params["native_compile"]
    provenance = {
        "frontend": frontend,
        "native_build_commands": native_build_commands,
        "native_optimization": 2,
        "sanitized": sanitized,
        "target": triple,
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_changes": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).splitlines(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "selfhost_binary": os.environ.get("BTRC_TEST_BTRCC") if frontend == "selfhost" else None,
        "physical_device_latency": "not measured",
        "input": "synthetic queued AppKit events; popup/resize use CGEventPost with permission preflight",
    }
    return executable, provenance


def test_macos_ui2_e40_boundary_compile(e40_program):
    """Compilation/linking only: the executable is never launched by this case."""
    executable, _ = e40_program
    assert executable.is_file()


@pytest.mark.parametrize("trial", ["load"])
def test_macos_ui2_e40_load_compile(e40_program, trial):
    """Build the workload without starting its worker, windows or run loop."""
    executable, _ = e40_program
    assert executable.is_file()


@pytest.mark.e40_qualification
@pytest.mark.macos_gui
@pytest.mark.skipif(
    sys.platform == "darwin" and (os.environ.get("BTRC_UI2_HOSTED_E40") != "1" or os.environ.get("CI") != "true"),
    reason="E40 visible native execution requires explicit hosted CI opt-in",
)
@pytest.mark.parametrize("trial", ["bursts", "load", "popup", "slider", "resize", "sheet"])
@pytest.mark.parametrize("entry", ["desktop", "host"])
def test_macos_ui2_e40(e40_program, sanitized, entry, trial, tmp_path):
    executable, provenance = e40_program
    artifact_root = Path(os.environ.get("BTRC_UI2_E40_ARTIFACTS", str(tmp_path / "e40")))
    directory = artifact_root / provenance["frontend"] / ("sanitized" if sanitized else "plain") / entry / trial
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / "observations.json"
    (directory / "provenance.json").write_text(json.dumps(provenance, indent=2))
    environment = apple_environment() | {"UBSAN_OPTIONS": "halt_on_error=1"}
    environment.pop("BTRC_GUI_BACKGROUND", None)
    command = [str(executable), entry, *([] if trial == "bursts" else [trial]), str(report.resolve())]
    timeout = 1800 if trial == "bursts" else 900 if trial == "load" else 60
    try:
        result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
        result = subprocess.CompletedProcess(
            command, -124, stdout, stderr + f"\nE40 timed out after {timeout} seconds.\n"
        )
    (directory / "stdout.txt").write_text(result.stdout)
    (directory / "stderr.txt").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report.is_file(), "Native trial returned without evidence"
    evidence = E40Evidence(json.loads(report.read_text()), sanitized)
    if trial == "bursts":
        evidence.bursts()
        assert "PASS: E40 macOS native boundary bursts" in result.stdout
    elif trial == "load":
        evidence.load()
        evidence.presentations(Path(str(report) + ".presentations.csv"))
        assert "PASS: E40 macOS 600-second declared load" in result.stdout

    else:
        evidence.tracking(trial)
        evidence.presentations(Path(str(report) + ".presentations.csv"))
        assert "PASS: E40 macOS native tracking load" in result.stdout
