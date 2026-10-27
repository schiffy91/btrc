"""E40 AppKit evidence: build locally; run visible native trials only on hosted CI."""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from functools import cache
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.python.native_ui2_e40_evidence import E40Evidence
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "src/tests/native/gui/ui2/probes/macos/e40"


class E40NativeControl:
    """Retain a bounded native control independently of E40 acceptance."""

    TIMEOUT_SECONDS = 15

    def __init__(self, name, command, build_command, source_sha256):
        self.name = name
        self.command = command
        self.executable = Path(command[0])
        self.build_command = build_command
        self.source_sha256 = source_sha256
        self.recorded = set()

    @classmethod
    def build(cls, directory, name, source_name, frameworks):
        executable = directory / source_name
        source = FIXTURES / f"{source_name}.m"
        command = [
            "/usr/bin/clang",
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-fobjc-arc",
            "-O0",
            str(source),
        ]
        for framework in frameworks:
            command.extend(["-framework", framework])
        command.extend(["-o", str(executable)])
        subprocess.run(command, env=apple_environment(), capture_output=True, text=True, check=True, timeout=60)
        return cls(name, [str(executable)], command, hashlib.sha256(source.read_bytes()).hexdigest())

    def record(self, artifact_root, environment):
        directory = (artifact_root / f"{self.name}-control").resolve()
        if directory in self.recorded:
            return
        directory.mkdir(parents=True, exist_ok=True)
        report = directory / "observations.json"
        report.unlink(missing_ok=True)
        command = [*self.command, str(report)]
        receipt = {
            "schema": f"btrc.ui2.{self.name}-control-execution/1",
            "scope": f"direct {self.name} diagnostic; E40 outcomes are checked independently",
            "build_command": self.build_command,
            "source_sha256": self.source_sha256,
            "executable_sha256": hashlib.sha256(self.executable.read_bytes()).hexdigest(),
            "command": command,
            "timeout_seconds": self.TIMEOUT_SECONDS,
        }
        stdout, stderr = "", ""
        try:
            result = subprocess.run(
                command, env=environment, capture_output=True, text=True, timeout=self.TIMEOUT_SECONDS
            )
            receipt.update(status="completed", returncode=result.returncode)
            stdout, stderr = result.stdout, result.stderr
        except (OSError, subprocess.TimeoutExpired) as error:
            receipt.update(status="failed", error=str(error))
            if isinstance(error, subprocess.TimeoutExpired):
                stdout, stderr = error.stdout or b"", error.stderr or b""
        for name, text in (("stdout", stdout), ("stderr", stderr)):
            (directory / f"{name}.txt").write_text(text.decode(errors="replace") if isinstance(text, bytes) else text)
        receipt["report_written"] = report.is_file()
        (directory / "execution.json").write_text(json.dumps(receipt, indent=2))
        self.recorded.add(directory)


@pytest.fixture(scope="session")
def build_native_controls(tmp_path_factory):
    @cache
    def build():
        metal = E40NativeControl.build(
            tmp_path_factory.mktemp("e40-metal-control"),
            "metal",
            "MetalPresentation",
            ("AppKit", "Metal", "QuartzCore"),
        )
        synchronized = E40NativeControl(
            "metal-vsync", [*metal.command, "--vsync"], metal.build_command, metal.source_sha256
        )
        resize = E40NativeControl.build(
            tmp_path_factory.mktemp("e40-resize-control"),
            "resize",
            "NativeResize",
            ("AppKit", "CoreGraphics", "QuartzCore"),
        )
        return metal, synchronized, resize

    return build


@pytest.fixture(scope="session")
def check_tracking_stimulus(tmp_path_factory):
    @cache
    def check():
        directory = tmp_path_factory.mktemp("e40-tracking-stimulus")
        source = FIXTURES / "TrackingStimulus.m"
        records = []
        for sanitized in (False, True):
            executable = directory / ("sanitized" if sanitized else "plain")
            flags = (
                ["-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
                if sanitized
                else ["-O2"]
            )
            command = [
                "/usr/bin/clang",
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-fblocks",
                *flags,
                str(source),
                "-framework",
                "AppKit",
                "-framework",
                "CoreGraphics",
                "-o",
                str(executable),
            ]
            environment = apple_environment() | {"UBSAN_OPTIONS": "halt_on_error=1"}
            built = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=60)
            assert built.returncode == 0, built.stdout + built.stderr
            symbols = subprocess.check_output(["/usr/bin/nm", "-u", str(executable)], text=True, timeout=30)
            assert "_CGEventPost" not in symbols, "The headless scheduler must intercept every input post"
            for scenario in ("complete", "cancel", "late"):
                result = subprocess.run(
                    [str(executable), scenario], env=environment, capture_output=True, text=True, timeout=10
                )
                records.append(
                    {
                        "sanitized": sanitized,
                        "scenario": scenario,
                        "build_command": command,
                        "driver_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "tracking_sha256": hashlib.sha256((FIXTURES / "Tracking.m").read_bytes()).hexdigest(),
                        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
                (directory / "results.json").write_text(json.dumps(records, indent=2))
                assert result.returncode == 0, result.stdout + result.stderr
                assert f"PASS: resize stimulus {scenario}" in result.stdout
        return records

    return check


class E40LoopDiagnostic:
    """Observe one existing native trial without changing its timeout or result."""

    SAMPLE_TIMES = (3.0, 7.0)

    def __init__(self, directory):
        self.directory = directory
        self.stopped = threading.Event()
        self.samples = []
        self.observer_error = None

    def _sample(self, process, scheduled):
        path = self.directory / f"sample-{int(scheduled)}s.txt"
        command = ["/usr/bin/sample", str(process.pid), "1", "1", "-file", str(path)]
        row = {"scheduled_seconds": scheduled, "pid": process.pid, "command": command}
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=4)
            row.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
            row["status"] = "captured" if result.returncode == 0 and path.is_file() else "failed"
        except (OSError, subprocess.TimeoutExpired) as error:
            row.update(status="failed", error=str(error))
        return row

    def _observe(self, process, started):
        try:
            for scheduled in self.SAMPLE_TIMES:
                if self.stopped.wait(max(0.0, started + scheduled - time.monotonic())):
                    break
                if process.poll() is not None:
                    break
                self.samples.append(self._sample(process, scheduled))
        except Exception as error:
            self.observer_error = repr(error)

    def run(self, command, *, env, timeout):
        started = time.monotonic()
        with subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
            observer = threading.Thread(target=self._observe, args=(process, started), name="e40-stack-samples")
            observer_started = False
            try:
                observer.start()
                observer_started = True
                stdout, stderr = process.communicate(timeout=timeout)
                return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            except BaseException:
                # Preserve the original exception/outcome and never leave the
                # native child alive when sampling or the harness fails.
                process.kill()
                process.communicate()
                raise
            finally:
                self.stopped.set()
                if observer_started:
                    observer.join()
                receipt = {
                    "schema": "btrc.ui2.e40-loop-diagnostic/1",
                    "qualification_scope": "one instrumented existing trial; not the full E40 matrix",
                    "pid": process.pid,
                    "native_timeout_seconds": timeout,
                    "native_returncode": process.returncode,
                    "elapsed_seconds": time.monotonic() - started,
                    "sample_schedule_seconds": list(self.SAMPLE_TIMES),
                    "samples": self.samples,
                    "observer_error": self.observer_error,
                    "trace": "observations.json.loop-trace.jsonl",
                    "timing_evidence": "instrumented; not an acceptance latency measurement",
                }
                (self.directory / "loop-diagnostic.json").write_text(json.dumps(receipt, indent=2))

    def retain_build(self, executable):
        generated = executable.with_suffix(".c")
        symbols = executable.with_suffix(".dSYM")
        command = ["/usr/bin/dsymutil", str(executable), "-o", str(symbols)]
        subprocess.run(command, capture_output=True, text=True, check=True, timeout=60)
        shutil.copy2(executable, self.directory / executable.name)
        shutil.copy2(generated, self.directory / generated.name)
        shutil.copy2(executable.with_suffix(".link.json"), self.directory / "native.link.json")
        shutil.copytree(symbols, self.directory / symbols.name)
        return {
            "symbols_command": command,
            "generated_sha256": hashlib.sha256(generated.read_bytes()).hexdigest(),
            "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        }


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
    (package / "KeyTimestamp.h").write_text((FIXTURES / "KeyTimestamp.h").read_text())
    symbols = [
        "+[BTRCE40Boundary requireHosted]",
        "+[BTRCE40Boundary setup:output:]",
        "+[BTRCE40Boundary ready]",
        "+[BTRCE40Boundary begin:final:repeat:ordinal:]",
        "+[BTRCE40Boundary key]",
        "+[BTRCE40Boundary text:]",
        "+[BTRCE40Boundary close]",
        "+[BTRCE40Boundary complete]",
        "+[BTRCE40Boundary diagnoseDeadline]",
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
        '[[native.frameworks]]\nname = "CoreGraphics"\nmodules = ["Main"]\nos = ["macos"]\n'
    )
    if stem == "Load":
        with manifest.open("a") as stream:
            stream.write('[[native.sources]]\npath = "Tracking.m"\nlanguage = "objective-c"\nstandard = "c11"\n')
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
        if Path(command[0]).name in {"clang", "clang++"} and os.environ.get("BTRC_UI2_E40_TRACE") == "1":
            flags += ["-g"]
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
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=30).strip(),
        "source_changes": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True, timeout=30
        ).splitlines(),
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
def test_macos_ui2_e40_load_compile(e40_program, trial, build_native_controls, check_tracking_stimulus):
    """Build the workload without starting its worker, windows or run loop."""
    executable, _ = e40_program
    assert executable.is_file()
    assert all(control.executable.is_file() for control in build_native_controls())
    check_tracking_stimulus()


@pytest.mark.e40_qualification
@pytest.mark.macos_gui
@pytest.mark.skipif(
    sys.platform == "darwin" and (os.environ.get("BTRC_UI2_HOSTED_E40") != "1" or os.environ.get("CI") != "true"),
    reason="E40 visible native execution requires explicit hosted CI opt-in",
)
@pytest.mark.parametrize("trial", ["bursts", "load", "popup", "slider", "resize", "sheet"])
@pytest.mark.parametrize("entry", ["desktop", "host"])
def test_macos_ui2_e40(e40_program, sanitized, entry, trial, tmp_path, build_native_controls):
    executable, provenance = e40_program
    artifact_root = Path(os.environ.get("BTRC_UI2_E40_ARTIFACTS", str(tmp_path / "e40")))
    directory = artifact_root / provenance["frontend"] / ("sanitized" if sanitized else "plain") / entry / trial
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / "observations.json"
    diagnostic = E40LoopDiagnostic(directory) if os.environ.get("BTRC_UI2_E40_TRACE") == "1" else None
    if diagnostic is not None:
        assert sanitized and provenance["frontend"] == "selfhost" and trial in {"slider", "resize"}
        provenance["diagnostic"] = diagnostic.retain_build(executable)
        provenance["diagnostic"]["full_e40_qualification"] = False
        compiler = Path(os.environ["BTRC_TEST_BTRCC"]).resolve(strict=True)
        provenance["diagnostic"]["compiler_sha256"] = hashlib.sha256(compiler.read_bytes()).hexdigest()
    (directory / "provenance.json").write_text(json.dumps(provenance, indent=2))
    environment = apple_environment() | {"UBSAN_OPTIONS": "halt_on_error=1"}
    environment.pop("BTRC_GUI_BACKGROUND", None)
    if trial == "load":
        for control in build_native_controls():
            control.record(artifact_root, environment)
    command = [str(executable), entry, *([] if trial == "bursts" else [trial]), str(report.resolve())]
    timeout = 1800 if trial == "bursts" else 900 if trial == "load" else 60
    try:
        if diagnostic is None:
            result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=timeout)
        else:
            result = diagnostic.run(command, env=environment, timeout=timeout)
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
