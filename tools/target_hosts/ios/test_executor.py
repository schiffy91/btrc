"""Portable tests of the ios-simulator executor; none of these claim iOS execution.

The supervisor and the fixtures are compiled with this host's C compiler and
run as local processes; only simctl's transport is replaced (`LocalHost`), so
the supervisor's spawn, wait, deadline and group kill are the real ones. The
simulator itself is exercised by host-ios.yml and macos.yml's target-corpus
job on hosted macOS runners.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tools.target_hosts.ios import executor as executor_module
from tools.target_hosts.ios.executor import (
    TARGET_EXECUTORS,
    ExecutionRequest,
    IOSSimulatorExecutor,
    LaunchWithdrawn,
    MachOImage,
    XcodeSupervisorBuilder,
    digest,
)
from tools.target_hosts.ios.simhost import AppleEnvironment, IOSSimulatorHost, SimulatorError
from tools.target_hosts.ios.spike import SimulatorSpike

LABEL = SimulatorSpike.target
CC = shutil.which("cc")
needs_cc = pytest.mark.skipif(CC is None or os.name != "posix", reason="requires a POSIX host C compiler")


def local_builder(source: Path, output: Path, triple: str) -> None:
    """Build the supervisor for this host instead of the simulator triple."""

    assert triple == SimulatorSpike.triple
    subprocess.run([CC, *XcodeSupervisorBuilder.FLAGS, str(source), "-o", str(output)], check=True, timeout=120)


def compile_program(directory: Path, name: str, source: str) -> Path:
    path = directory / f"{name}.c"
    path.write_text(source, encoding="utf-8")
    subprocess.run([CC, *XcodeSupervisorBuilder.FLAGS, str(path), "-o", str(directory / name)], check=True, timeout=120)
    path.unlink()
    return directory / name


def add_program(bundle: Path, executable: Path) -> None:
    """Add a locally built program to a spike bundle, as the runner's bundle.json records one."""

    manifest = json.loads((bundle / "bundle.json").read_text())
    if executable.parent != bundle:
        shutil.copyfile(executable, bundle / executable.name)
        os.chmod(bundle / executable.name, 0o755)
    manifest["programs"][executable.name] = {
        "source": f"{executable.name}.c",
        "frontend": "c",
        "status": "built",
        "artifact": executable.name,
        "sha256": digest((bundle / executable.name).read_bytes()),
    }
    (bundle / "bundle.json").write_text(json.dumps(manifest))


class LocalHost:
    """simctl spawn without the device: the supervisor runs as a local child of the executor."""

    def __init__(self, launcher: tuple[str, ...] = ()):
        self.launcher = launcher
        self.prepared = 0
        self.closed = 0
        self.spawned: list[subprocess.Popen[bytes]] = []

    def prepare(self):
        self.prepared += 1

    def provenance(self):
        return {"device": "unit-test transport", "device_class": "test", "os_build": "unit-test transport"}

    def spawn(self, argv, env):
        process = subprocess.Popen(
            [*self.launcher, *argv],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, **env},
            start_new_session=True,
        )
        self.spawned.append(process)
        return process

    @staticmethod
    def kill_group(pid):
        IOSSimulatorHost.kill_group(pid)

    def close(self):
        self.closed += 1


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    if CC is None or os.name != "posix":
        pytest.skip("requires a POSIX host C compiler")
    directory = tmp_path_factory.mktemp("ios-bundle")
    SimulatorSpike.build(directory, local_cc=CC)
    return directory


def executor_for(host=None, **options) -> IOSSimulatorExecutor:
    return IOSSimulatorExecutor(
        host=host or LocalHost(),
        builder=local_builder,
        image_check=lambda data, name: None,
        machine=lambda: "arm64",
        **options,
    )


@pytest.fixture
def prepared(bundle):
    executor = executor_for()
    executor.prepare(bundle, LABEL)
    try:
        yield executor
    finally:
        executor.close()


# Registration and options ----------------------------------------------------


def test_the_executor_registers_as_ios_simulator_for_the_runner():
    assert TARGET_EXECUTORS == {"ios-simulator": "IOSSimulatorExecutor"}
    modes, policies = IOSSimulatorExecutor.LAUNCH_MODES, IOSSimulatorExecutor.CWD_POLICIES
    assert modes == {"process"} and policies == {"isolated", "bundle"}


def test_options_configure_the_device_and_deadlines_without_touching_a_simulator():
    executor = IOSSimulatorExecutor.from_options(
        {"device_class": "ipad", "runtime": "27.0", "launch_timeout_s": "90", "warmup_timeout_s": "900"}
    )
    assert (executor.host.device_class, executor.host.requested_runtime) == ("ipad", "27.0")
    assert (executor.launch_timeout_s, executor.warmup_timeout_s) == (90.0, 900.0)
    assert executor.host.udid is None
    with pytest.raises(ValueError, match="unknown ios-simulator option"):
        IOSSimulatorExecutor.from_options({"mode": "app"})
    with pytest.raises(ValueError, match="number of seconds"):
        IOSSimulatorExecutor.from_options({"launch_timeout_s": "soon"})
    with pytest.raises(ValueError, match="positive finite"):
        IOSSimulatorExecutor(launch_timeout_s=float("inf"))
    with pytest.raises(ValueError, match="device_class"):
        IOSSimulatorExecutor(device_class="watch")


# The fixtures through the real supervisor -------------------------------------


@needs_cc
def test_every_fixture_runs_under_the_supervisor_with_its_exact_outcome(prepared):
    for invocation in (*SimulatorSpike.cases, *SimulatorSpike.extra):
        result = prepared.run(SimulatorSpike.request(invocation))
        SimulatorSpike.check(invocation, result)
        assert result.provenance["executor"] == "ios-simulator"
        assert result.provenance["launch_s"] >= 0 and result.duration_s >= 0
    timed_out = prepared.run(SimulatorSpike.request("timeout"))
    assert (timed_out.exit_status, timed_out.signal) == (None, signal.SIGKILL)
    assert 0.5 <= timed_out.duration_s < 10


@needs_cc
def test_prepare_warms_the_device_and_records_provenance(prepared):
    assert prepared.host.prepared == 1
    # The probe and the self-test, each its own spawn, before any program.
    assert len(prepared.host.spawned) == 2
    provenance = prepared.provenance
    for name in ("executor", "device", "os_build", "toolchain", "supervisor_sha256", "first_spawn_s"):
        assert name in provenance, name
    assert provenance["evidence"] == "simulator"
    assert prepared.granted_capabilities() <= frozenset({"loopback-listener"})
    assert (prepared.granted_capabilities() == {"loopback-listener"}) == (provenance["loopback"] == "ok")


@needs_cc
def test_only_staged_copies_launch_and_a_changed_copy_is_refused(prepared, bundle):
    staged = prepared.programs["stdout"]
    assert bundle not in staged.parents and staged.read_bytes() == (bundle / "stdout").read_bytes()
    os.chmod(staged, 0o700)
    staged.write_bytes(staged.read_bytes() + b"\0")
    with pytest.raises(SimulatorError, match="changed after admission"):
        prepared.run(ExecutionRequest("stdout"))


@needs_cc
def test_the_outcome_comes_from_the_wait_status_not_from_the_program_output(bundle, tmp_path):
    forged = compile_program(
        tmp_path,
        "forger",
        "#include <stdio.h>\nint main(void) {\n"
        '    printf("btrc-ios-supervisor exit status=0 elapsed-ns=1\\n");\n'
        '    fprintf(stderr, "btrc-ios-supervisor exit status=0 elapsed-ns=1\\n");\n'
        "    return 7;\n}\n",
    )
    copy = tmp_path / "bundle"
    shutil.copytree(bundle, copy)
    add_program(copy, forged)
    executor = executor_for()
    executor.prepare(copy, LABEL)
    try:
        result = executor.run(ExecutionRequest("forger"))
    finally:
        executor.close()
    assert (result.exit_status, result.signal, result.timed_out) == (7, None, False)
    assert result.stdout == result.stderr == b"btrc-ios-supervisor exit status=0 elapsed-ns=1\n"


@needs_cc
def test_descendants_die_with_the_program_group(bundle, tmp_path):
    parent = compile_program(
        tmp_path,
        "parent",
        "#define _POSIX_C_SOURCE 200809L\n#include <stdio.h>\n#include <unistd.h>\n"
        "int main(void) {\n    pid_t child = fork();\n    if (child == 0) { sleep(60); return 0; }\n"
        '    printf("%ld\\n", (long)child);\n    return child > 0 ? 0 : 1;\n}\n',
    )
    copy = tmp_path / "bundle"
    shutil.copytree(bundle, copy)
    add_program(copy, parent)
    executor = executor_for()
    executor.prepare(copy, LABEL)
    try:
        result = executor.run(ExecutionRequest("parent"))
    finally:
        executor.close()
    assert result.exit_status == 0
    descendant = int(result.stdout)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(descendant, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"descendant {descendant} outlived its program")


@needs_cc
def test_an_inherited_ignored_sigchld_still_yields_the_wait_status(bundle):
    # A launcher that ignores SIGCHLD passes that disposition through exec; the
    # supervisor restores it, or the kernel would reap the child before waitpid.
    executor = executor_for(host=LocalHost(("/bin/sh", "-c", 'trap \'\' CHLD; exec "$0" "$@"')))
    executor.prepare(bundle, LABEL)
    try:
        for invocation in ("exit3", "abort", "stdout"):
            SimulatorSpike.check(invocation, executor.run(SimulatorSpike.request(invocation)))
    finally:
        executor.close()


# Admission ------------------------------------------------------------------


@needs_cc
def test_admission_refuses_another_row_an_emulated_host_and_a_wrong_digest(bundle, tmp_path):
    with pytest.raises(ValueError, match="built for"):
        executor_for().prepare(bundle, "ios-aarch64")
    with pytest.raises(ValueError, match="emulation is not evidence"):
        IOSSimulatorExecutor(host=LocalHost(), builder=local_builder, machine=lambda: "x86_64").prepare(bundle, LABEL)
    copy = tmp_path / "bundle"
    shutil.copytree(bundle, copy)
    (copy / "stderr").write_bytes((copy / "stdout").read_bytes())
    with pytest.raises(ValueError, match="does not match the bundle's SHA-256"):
        executor_for().prepare(copy, LABEL)


@needs_cc
def test_a_host_build_cannot_pass_as_an_ios_simulator_bundle(bundle):
    executor = IOSSimulatorExecutor(host=LocalHost(), builder=local_builder, machine=lambda: "arm64")
    with pytest.raises(ValueError, match=r"iOS simulator image|Mach-O"):
        executor.prepare(bundle, LABEL)
    assert executor.staging is None and executor.host.prepared == 0


@needs_cc
def test_a_refused_admission_keeps_the_admitted_bundle(prepared, bundle, tmp_path):
    staging = prepared.staging
    with pytest.raises(ValueError, match="built for"):
        prepared.prepare(bundle, "ios-aarch64")
    copy = tmp_path / "bundle"
    shutil.copytree(bundle, copy)
    (copy / "stdout").write_bytes(b"replaced")
    with pytest.raises(ValueError, match="SHA-256"):
        prepared.prepare(copy, LABEL)
    assert prepared.staging == staging and staging.is_dir()
    SimulatorSpike.check("stdout", prepared.run(SimulatorSpike.request("stdout")))


@needs_cc
def test_artifacts_must_be_the_program_id_inside_the_bundle(bundle, tmp_path):
    copy = tmp_path / "bundle"
    shutil.copytree(bundle, copy)
    manifest = json.loads((copy / "bundle.json").read_text())
    manifest["programs"]["stdout"]["artifact"] = "../stdout"
    (copy / "bundle.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="program id itself"):
        executor_for().prepare(copy, LABEL)
    manifest["programs"]["stdout"]["artifact"] = "stdout"
    (copy / "stdout").unlink()
    (copy / "stdout").symlink_to(copy / "stderr")
    (copy / "bundle.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="regular file"):
        executor_for().prepare(copy, LABEL)


def test_the_mach_o_check_names_architecture_and_platform():
    def image(cpu=MachOImage.ARM64, platform_id=MachOImage.IOS_SIMULATOR, magic=MachOImage.MAGIC_64):
        command = struct.pack("<IIIIII", MachOImage.BUILD_VERSION, 24, platform_id, 0, 0, 0)
        segment = struct.pack("<II", 0x19, 8)
        header = struct.pack("<IiiIIIII", magic, cpu, 0, 2, 2, len(segment) + len(command), 0, 0)
        return header + segment + command

    MachOImage.check(image(), "program")
    assert MachOImage.describe(image(platform_id=1)) == (MachOImage.ARM64, 1)
    for data, message in (
        (image(platform_id=1), "platform 1"),
        (image(platform_id=2), "platform 2"),
        (image(cpu=0x01000007), "cpu 0x01000007"),
        (image(magic=0xBEBAFECA), "magic"),
        (b"\x7fELF" + bytes(60), "magic"),
        (image()[:20], "too short"),
        (image()[:40], "truncated"),
    ):
        with pytest.raises(ValueError, match=message):
            MachOImage.check(data, "program")


# Requests -------------------------------------------------------------------


@needs_cc
@pytest.mark.parametrize(
    "request_",
    [
        ExecutionRequest("missing"),
        ExecutionRequest("stdout", timeout_s=0),
        ExecutionRequest("stdout", timeout_s=float("nan")),
        ExecutionRequest("stdout", timeout_s=True),
        ExecutionRequest("stdout", argv=("bad\0argument",)),
        ExecutionRequest("stdout", cwd_policy="ambient"),
        ExecutionRequest("stdout", launch_mode="app"),
        ExecutionRequest("stdout", app_roots=("files",)),
        ExecutionRequest("stdout", env={"SIMCTL_CHILD_X": "value"}),
        ExecutionRequest("stdout", env={"DYLD_INSERT_LIBRARIES": "/tmp/x"}),
        ExecutionRequest("stdout", env={"BAD=NAME": "value"}),
        ExecutionRequest("stdout", env={"NAME": "nul\0value"}),
    ],
)
def test_an_invalid_request_is_refused_before_any_spawn(prepared, request_):
    spawned = len(prepared.host.spawned)
    with pytest.raises(ValueError):
        prepared.run(request_)
    assert len(prepared.host.spawned) == spawned


def test_running_before_admission_is_refused():
    with pytest.raises(RuntimeError, match="prepare"):
        executor_for().run(ExecutionRequest("stdout"))


# Infrastructure errors raise; they are never program outcomes ------------------


class ScriptedHost(LocalHost):
    """A transport whose 'supervisor' is a Python script printing whatever the test scripts."""

    def __init__(self, script: str):
        super().__init__()
        self.script = script
        self.scripted = False

    def spawn(self, argv, env):
        if not self.scripted and argv[1:2] == ["run"] and "status" not in argv:
            self.scripted = True
            argv = [sys.executable, "-c", self.script, *argv[1:]]
        return super().spawn(argv, env)


@needs_cc
@pytest.mark.parametrize(
    ("script", "message"),
    [
        ("import sys; sys.stderr.write('simctl: unable to spawn'); sys.exit(148)", "unable to spawn"),
        (
            "print('btrc-ios-supervisor ready pid=4242', flush=True); "
            "print('btrc-ios-supervisor error stage=spawn errno=8', flush=True); raise SystemExit(2)",
            "error",
        ),
        (
            "import os; print('btrc-ios-supervisor ready pid=%d' % os.getpid(), flush=True); "
            "print('btrc-ios-supervisor started pid=%d' % os.getpid(), flush=True); "
            "print('btrc-ios-supervisor exit status=0 elapsed-ns=5', flush=True); raise SystemExit(3)",
            "exited 3",
        ),
        (
            "import os; print('btrc-ios-supervisor started pid=%d' % os.getpid(), flush=True); "
            "print('btrc-ios-supervisor exit status=999 elapsed-ns=5', flush=True)",
            "exit status 999",
        ),
        (
            "import os; print('btrc-ios-supervisor started pid=%d' % os.getpid(), flush=True); "
            "print('btrc-ios-supervisor exit status=0', flush=True)",
            "elapsed-ns",
        ),
        (
            "import os; print('btrc-ios-supervisor started pid=%d' % os.getpid(), flush=True); "
            "print('btrc-ios-supervisor exit status=0; elapsed-ns=5', flush=True)",
            "malformed",
        ),
    ],
)
def test_a_broken_transport_or_supervisor_raises_with_its_diagnostics(bundle, script, message):
    executor = executor_for(host=ScriptedHost(script))
    executor.prepare(bundle, LABEL)
    try:
        with pytest.raises(SimulatorError, match=message):
            executor.run(ExecutionRequest("stdout"))
        # The next run uses the real supervisor again.
        SimulatorSpike.check("stdout", executor.run(SimulatorSpike.request("stdout")))
    finally:
        executor.close()


@needs_cc
def test_a_launch_that_misses_its_deadline_is_withdrawn_before_the_program_starts(bundle, tmp_path):
    marker = tmp_path / "ran"
    program = compile_program(
        tmp_path,
        "toucher",
        "#include <stdio.h>\nint main(int argc, char **argv) {\n"
        '    FILE *file = argc > 1 ? fopen(argv[1], "w") : NULL;\n    return file ? 0 : 1;\n}\n',
    )
    copy = tmp_path / "bundle"
    shutil.copytree(bundle, copy)
    add_program(copy, program)
    executor = executor_for()
    executor.prepare(copy, LABEL)
    executor.host.launcher = ("/bin/sh", "-c", 'sleep 2; exec "$0" "$@"')
    executor.launch_timeout_s = 0.3
    try:
        # Every attempt is late, so each is withdrawn and the last one raises.
        with pytest.raises(LaunchWithdrawn, match="simctl had not started the supervisor") as caught:
            executor.run(ExecutionRequest("toucher", argv=(str(marker),)))
        assert any("launch attempt 1 withdrawn" in note for note in caught.value.__notes__)
        time.sleep(3)
        assert not marker.exists(), "a withdrawn launch never runs the program"
        executor.host.launcher = ()
        result = executor.run(ExecutionRequest("toucher", argv=(str(marker),)))
        assert result.exit_status == 0 and result.provenance["launch_retries"] == 0
        assert marker.exists()
    finally:
        executor.close()


@needs_cc
def test_a_launch_withdrawn_before_the_program_started_is_retried_and_runs_once(bundle, tmp_path):
    stalled = tmp_path / "stalled"
    executor = executor_for()
    executor.prepare(bundle, LABEL)
    # Only the first launch stalls past the deadline, as CoreSimulator once did on a hosted runner.
    executor.host.launcher = (
        "/bin/sh",
        "-c",
        f'if [ ! -e "{stalled}" ]; then : > "{stalled}"; sleep 2; fi; exec "$0" "$@"',
    )
    executor.launch_timeout_s = 0.3
    try:
        result = executor.run(SimulatorSpike.request("stdout"))
    finally:
        executor.close()
    SimulatorSpike.check("stdout", result)
    assert result.provenance["launch_retries"] == 1
    assert "launch attempt 1 withdrawn" in result.provenance["warnings"][0]


@needs_cc
def test_a_late_launch_whose_supervisor_was_running_is_not_retried(bundle, tmp_path):
    # Once the supervisor runs, a missed deadline may have caught it inside
    # posix_spawn, so the launch is an error rather than a retry.
    executor = executor_for(
        host=ScriptedHost(
            "import os, time; print('btrc-ios-supervisor ready pid=%d' % os.getpid(), flush=True); time.sleep(5)"
        )
    )
    executor.prepare(bundle, LABEL)
    executor.launch_timeout_s = 0.3
    try:
        with pytest.raises(SimulatorError, match="the supervisor was running") as caught:
            executor.run(ExecutionRequest("stdout"))
        assert not isinstance(caught.value, LaunchWithdrawn)
    finally:
        executor.close()


@needs_cc
def test_an_output_beyond_the_limit_raises(prepared, monkeypatch):
    monkeypatch.setattr(executor_module, "OUTPUT_LIMIT_BYTES", 1024)
    with pytest.raises(SimulatorError, match="exceeded 1024 bytes"):
        prepared.run(SimulatorSpike.request("large"))


@needs_cc
def test_close_releases_the_staging_and_the_device_and_is_idempotent(bundle):
    executor = executor_for()
    executor.prepare(bundle, LABEL)
    staging = executor.staging
    executor.close()
    executor.close()
    assert not staging.exists() and executor.staging is None and executor.programs == {}
    assert executor.host.closed == 2


# The simulator host -----------------------------------------------------------


def inventory():
    return {
        "runtimes": [
            {
                "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-17-0",
                "version": "17.0",
                "buildversion": "21A328",
                "isAvailable": True,
            },
            {
                "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-27-0",
                "version": "27.0",
                "buildversion": "25A5",
                "isAvailable": False,
            },
            {"identifier": "com.apple.CoreSimulator.SimRuntime.tvOS-28-0", "version": "28.0", "isAvailable": True},
            {
                "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-16-4",
                "version": "16.4",
                "isAvailable": True,
            },
        ],
        "devices": {},
        "devicetypes": [
            {"name": "iPhone fixture", "identifier": "phone"},
            {"name": "iPad fixture", "identifier": "pad"},
        ],
    }


class SimctlRecorder:
    def __init__(self, listing=None, *, stalls=0):
        self.calls = []
        self.environments = []
        self.listing = listing or inventory()
        self.stalls = stalls

    def __call__(self, command, **options):
        self.calls.append(command)
        self.environments.append(options.get("env"))
        assert options["timeout"] > 0
        if command[1:] == ["--find", "simctl"]:
            return subprocess.CompletedProcess(command, 0, b"/Xcode/simctl\n", b"")
        if command[1:] == ["list", "-j"]:
            if self.stalls:
                self.stalls -= 1
                raise subprocess.TimeoutExpired(command, options["timeout"])
            return subprocess.CompletedProcess(command, 0, json.dumps(self.listing).encode(), b"")
        if command[1] == "create":
            return subprocess.CompletedProcess(command, 0, b"new-udid\n", b"")
        return subprocess.CompletedProcess(command, 0, b"", b"")


@pytest.mark.parametrize(
    ("device_class", "device_type", "name"), [("iphone", "phone", "iPhone"), ("ipad", "pad", "iPad")]
)
def test_the_host_boots_a_named_device_on_the_newest_runtime_and_shuts_down_only_its_own(
    device_class, device_type, name
):
    recorder = SimctlRecorder()
    host = IOSSimulatorHost(device_class, runner=recorder)
    host.prepare()
    host.prepare()
    runtime = "com.apple.CoreSimulator.SimRuntime.iOS-17-0"
    assert recorder.calls[0] == ["/usr/bin/xcrun", "--find", "simctl"]
    assert ["/Xcode/simctl", "create", f"btrc-host-{device_class}", device_type, runtime] in recorder.calls
    assert ["/Xcode/simctl", "boot", "new-udid"] in recorder.calls
    assert ["/Xcode/simctl", "bootstatus", "new-udid", "-b"] in recorder.calls
    assert sum(call[1:2] == ["boot"] for call in recorder.calls) == 1, "a prepared host boots once"
    provenance = host.provenance()
    assert provenance == {
        "device": f"{name} fixture simulator",
        "device_class": device_class,
        "os_build": "iOS 17.0 (21A328)",
        "runtime": runtime,
    }
    assert "new-udid" not in json.dumps(provenance)
    host.close()
    assert recorder.calls[-1] == ["/Xcode/simctl", "shutdown", "new-udid"]
    assert not any("erase" in call for call in recorder.calls)


def test_the_host_reuses_a_booted_device_and_leaves_it_running():
    listing = inventory()
    runtime = "com.apple.CoreSimulator.SimRuntime.iOS-17-0"
    listing["devices"] = {
        runtime: [
            {
                "name": "btrc-host-ipad",
                "udid": "kept",
                "isAvailable": True,
                "state": "Booted",
                "deviceTypeIdentifier": "pad",
            }
        ]
    }
    recorder = SimctlRecorder(listing)
    host = IOSSimulatorHost("ipad", runner=recorder)
    host.prepare()
    host.close()
    assert not any(call[1:2] in (["boot"], ["shutdown"], ["create"]) for call in recorder.calls)
    listing["devices"][runtime][0]["deviceTypeIdentifier"] = "phone"
    with pytest.raises(SimulatorError, match="not an iPad"):
        IOSSimulatorHost("ipad", runner=SimctlRecorder(listing)).prepare()


def test_the_host_selects_a_requested_runtime_and_refuses_a_missing_one():
    listing = inventory()
    listing["runtimes"].append(
        {"identifier": "com.apple.CoreSimulator.SimRuntime.iOS-18-5", "version": "18.5", "isAvailable": True}
    )
    recorder = SimctlRecorder(listing)
    IOSSimulatorHost(runner=recorder).prepare()
    assert any(call[-1] == "com.apple.CoreSimulator.SimRuntime.iOS-18-5" for call in recorder.calls)
    recorder = SimctlRecorder(listing)
    IOSSimulatorHost(runtime="17", runner=recorder).prepare()
    assert any(call[-1] == "com.apple.CoreSimulator.SimRuntime.iOS-17-0" for call in recorder.calls)
    with pytest.raises(SimulatorError, match="matching '19'"):
        IOSSimulatorHost(runtime="19", runner=SimctlRecorder(listing)).prepare()
    listing["runtimes"] = [row for row in listing["runtimes"] if not row["isAvailable"]]
    with pytest.raises(SimulatorError, match=r"no available iOS >= 17\.0"):
        IOSSimulatorHost(runner=SimctlRecorder(listing)).prepare()


def test_the_host_creates_only_a_device_type_its_runtime_supports():
    listing = inventory()
    listing["runtimes"][0]["supportedDeviceTypes"] = [{"identifier": "phone"}]
    listing["devicetypes"].append({"name": "iPhone unsupported", "identifier": "unsupported"})
    recorder = SimctlRecorder(listing)
    IOSSimulatorHost(runner=recorder).prepare()
    assert next(call for call in recorder.calls if call[1:2] == ["create"])[3] == "phone"


def test_a_slow_first_listing_is_retried_once_then_reported():
    recorder = SimctlRecorder(stalls=1)
    IOSSimulatorHost(runner=recorder).prepare()
    assert sum(call[1:] == ["list", "-j"] for call in recorder.calls) == 2
    with pytest.raises(SimulatorError, match="did not answer within 180 s"):
        IOSSimulatorHost(runner=SimctlRecorder(stalls=2)).prepare()


def test_simctl_runs_outside_a_nix_sdk_and_children_get_only_their_request(monkeypatch):
    monkeypatch.setenv("DEVELOPER_DIR", "/nix/store/abc-apple-sdk/Developer")
    monkeypatch.setenv("SDKROOT", "/nix/store/abc-apple-sdk/SDK")
    monkeypatch.setenv("SIMCTL_CHILD_STALE", "earlier request")
    recorder = SimctlRecorder()
    IOSSimulatorHost(runner=recorder).prepare()
    for environment in recorder.environments:
        assert not {"DEVELOPER_DIR", "SDKROOT", "SIMCTL_CHILD_STALE"} & set(environment)
    monkeypatch.setenv("DEVELOPER_DIR", "/Applications/Xcode_27.app/Contents/Developer")
    child = AppleEnvironment.child({"VALUE": "data"})
    assert child["DEVELOPER_DIR"] == "/Applications/Xcode_27.app/Contents/Developer"
    assert child["SIMCTL_CHILD_VALUE"] == "data" and "SIMCTL_CHILD_STALE" not in child


def test_spawn_runs_simctl_spawn_in_a_session_of_its_own():
    launched = []

    def spawner(command, **options):
        launched.append((command, options))
        return "process"

    host = IOSSimulatorHost(runner=SimctlRecorder(), spawner=spawner)
    host.prepare()
    assert host.spawn(["/staged/supervisor", "probe"], {"VALUE": "data"}) == "process"
    command, options = launched[0]
    assert command == ["/Xcode/simctl", "spawn", "new-udid", "/staged/supervisor", "probe"]
    assert options["start_new_session"] and options["stdin"] == subprocess.DEVNULL
    assert options["env"]["SIMCTL_CHILD_VALUE"] == "data"


def test_the_host_refuses_to_signal_a_system_process_group():
    for pid in (0, 1, -5):
        with pytest.raises(SimulatorError, match="refusing"):
            IOSSimulatorHost.kill_group(pid)


def test_diagnostics_keep_partial_output_and_change_no_simulator_state(tmp_path):
    calls = []

    def runner(command, **options):
        calls.append(command)
        assert options["timeout"] == 10
        if command[-3:] == ["list", "devices", "-j"]:
            raise subprocess.TimeoutExpired(command, 10, output=b"partial inventory", stderr=b"stalled")
        if command[0] == "/usr/bin/vm_stat":
            raise OSError("probe unavailable")
        return subprocess.CompletedProcess(command, 0, b"observation", b"")

    IOSSimulatorHost(runner=runner).diagnose(tmp_path)
    rows = json.loads((tmp_path / "commands.json").read_text())
    assert len(calls) == 5
    assert (tmp_path / "devices.stdout").read_bytes() == b"partial inventory"
    assert "TimeoutExpired" in rows["devices"]["error"] and "probe unavailable" in rows["memory"]["error"]
    assert not any(word in command for command in calls for word in ("boot", "shutdown", "erase"))


# The spike ------------------------------------------------------------------


def test_fixture_checks_stay_active_under_python_optimization():
    code = (
        "from types import SimpleNamespace; "
        "from tools.target_hosts.ios.spike import SimulatorSpike; "
        "SimulatorSpike.check('stdout', SimpleNamespace(stdout=b'wrong', stderr=b''))"
    )
    result = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True, timeout=60, check=False)
    assert result.returncode != 0 and b"stdout mismatch" in result.stderr


@needs_cc
def test_the_spike_runs_every_invocation_and_writes_a_complete_summary(bundle, tmp_path):
    SimulatorSpike.run(bundle, tmp_path, device_class="iphone", executor=executor_for())
    summary = json.loads((tmp_path / "iphone.json").read_text())
    assert summary["complete"] and summary["error"] is None
    assert [row["fixture"] for row in summary["results"]] == [*SimulatorSpike.cases, *SimulatorSpike.extra]
    assert (tmp_path / "iphone" / "large" / "stdout").stat().st_size == 1048576


def test_a_failed_spike_keeps_its_stage_notes_and_cleanup_error(tmp_path):
    class Failing:
        def prepare(self, bundle, label):
            pass

        def run(self, request):
            error = SimulatorError("launch deadline")
            error.add_note("simctl diagnostic")
            raise error

        def close(self):
            raise SimulatorError("shutdown failed")

    with pytest.raises(SimulatorError, match="launch deadline") as caught:
        SimulatorSpike.run(tmp_path, tmp_path, device_class="ipad", executor=Failing())
    assert any("shutdown failed" in note for note in caught.value.__notes__)
    summary = json.loads((tmp_path / "ipad.json").read_text())
    assert not summary["complete"] and summary["failed_stage"] == "execute"
    assert summary["failed_invocation"] == "stdout" and "simctl diagnostic" in summary["error_notes"]
    assert "shutdown failed" in summary["cleanup_error"]
