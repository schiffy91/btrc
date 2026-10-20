"""Portable transport tests; none of these claim native Windows execution."""

from __future__ import annotations

import ctypes
import io
import json
import os
import signal
import stat
import struct
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from . import bundle as bundle_module
from . import check as check_module
from . import executor as executor_module
from .bundle import (
    acceptance_cases,
    digest,
    pe_machine,
    record_compiler_provenance,
    run_build_command,
    verify_compiler_provenance,
)
from .check import validate_cases, verify
from .executor import (
    TARGET_EXECUTORS,
    Accounting,
    BoundedOutput,
    ExecutionRequest,
    ExecutionResult,
    ExtendedLimits,
    WindowsNativeExecutor,
    merged_environment,
    remove_tree,
)

LABEL = "windows-x86_64"


def pe_image(machine=0x8664, tail=b""):
    data = bytearray(128)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 64)
    data[64:68] = b"PE\0\0"
    struct.pack_into("<H", data, 68, machine)
    return bytes(data) + tail


def write_bundle(directory, programs=None, label=LABEL):
    """A ``btrc.target-bundle/1`` bundle as the target runner writes it."""
    directory.mkdir(parents=True, exist_ok=True)
    entries = {}
    for name, data in (programs or {"probe": pe_image()}).items():
        (directory / f"{name}.exe").write_bytes(data)
        entries[name] = {
            "source": f"fixtures/{name}.c",
            "frontend": "c",
            "status": "built",
            "artifact": f"{name}.exe",
            "sha256": digest(data),
        }
    document = {
        "schema": "btrc.target-bundle/1",
        "protocol": 1,
        "target": {"label": label, "triple": "x86_64-windows-gnu", "operating_system": "windows"},
        "toolchain": {"cc": ["stand-in"]},
        "programs": entries,
    }
    (directory / "bundle.json").write_text(json.dumps(document), encoding="utf-8")
    return directory


def read_document(bundle):
    return json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))


def write_document(bundle, document):
    (bundle / "bundle.json").write_text(json.dumps(document), encoding="utf-8")


@pytest.fixture(autouse=True)
def private_temporary_root(tmp_path, monkeypatch):
    """Every staging, cwd and control directory lands under this test's own temporary root."""
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(executor_module.tempfile, "tempdir", str(root))
    return root


@pytest.fixture
def bundle(tmp_path):
    return write_bundle(tmp_path / "bundle")


class Transport:
    def __init__(self, *, status=0, timeout=False, assignment_failure=False, gate_failure=False):
        self.events = []
        self.status, self.timeout, self.assignment_failure, self.gate_failure = (
            status,
            timeout,
            assignment_failure,
            gate_failure,
        )
        self.returncode = None
        self.name = "fake-event"
        self.terminated = False

    def spawn(self, command, **kwargs):
        self.events.append("spawn")
        self.command = command
        self.input = kwargs["stdin"].read()
        self.spec = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        assert kwargs["cwd"] == self.spec["cwd"]
        assert "btrc host λ " in self.spec["cwd"]
        return self

    def assign(self, process):
        assert process is self
        self.events.append("assign")
        if self.assignment_failure:
            raise OSError("assignment rejected")

    def release(self):
        self.events.append("release")

    def communicate(self, data=None, timeout=None):
        self.events.append("communicate")
        self.input = data if data is not None else getattr(self, "input", None)
        if self.timeout and not self.terminated:
            raise subprocess.TimeoutExpired("fake gate", timeout)
        self.returncode = self.status
        return b"out\0\xff", b"err\0\xfe"

    def terminate(self):
        self.events.append("terminate")
        self.terminated = True

    def wait_empty(self):
        self.events.append("empty")

    def processes_started(self):
        # The gate is the job's first process; a gate that launched its target saw a second.
        return 1 if self.gate_failure else 2

    def close(self):
        self.events.append("close")

    def poll(self):
        return self.returncode

    def kill(self):
        self.events.append("kill-gate")
        self.returncode = 1


def executor(bundle, transport, label=LABEL):
    host = WindowsNativeExecutor(
        job_factory=lambda: transport, spawn=transport.spawn, capture_factory=lambda process: process
    )
    host.prepare(bundle, label)
    return host


def test_the_executor_is_registered_as_windows_native():
    assert TARGET_EXECUTORS == {"windows-native": "WindowsNativeExecutor"}
    assert frozenset({"isolated"}) == WindowsNativeExecutor.CWD_POLICIES
    assert frozenset({"process"}) == WindowsNativeExecutor.LAUNCH_MODES


def test_gate_assignment_precedes_target_release_and_binary_transport(bundle):
    transport = Transport()
    host = executor(bundle, transport)
    result = host.run(ExecutionRequest("probe", ("a b", 'quoted"value', ""), b"\0\xff", {"BTRC_PROBE": "space value"}))
    assert transport.events[:4] == ["spawn", "assign", "release", "communicate"]
    assert transport.events[-2:] == ["empty", "close"]
    assert transport.input == b"\0\xff"
    staged = host.programs["probe"].path
    assert transport.spec["command"] == [str(staged), "a b", 'quoted"value', ""]
    assert bundle not in staged.parents, "only the private staged copy is launched"
    assert staged.read_bytes() == (bundle / "probe.exe").read_bytes()
    assert transport.spec["env"]["BTRC_PROBE"] == "space value"
    assert result.stdout == b"out\0\xff" and result.stderr == b"err\0\xfe"
    assert not Path(transport.spec["cwd"]).exists()
    assert result.exit_status == 0
    assert result.provenance["executor"] == "windows-native" and result.provenance["label"] == LABEL


@pytest.mark.parametrize("status", [3, 124, 137, 255])
def test_normal_exit_is_never_inferred_to_be_timeout(bundle, status):
    result = executor(bundle, Transport(status=status)).run(ExecutionRequest("probe"))
    assert result.exit_status == status and result.signal is None and not result.timed_out


@pytest.mark.parametrize(
    "status,signal", [(0xC0000005, 11), (-1073741819, 11), (0xC000001D, 4), (0xC0000094, 8), (0x40000015, 6)]
)
def test_ntstatus_preserves_all_bits_and_maps_crash(bundle, status, signal):
    result = executor(bundle, Transport(status=status)).run(ExecutionRequest("probe"))
    assert result.exit_status is None and result.signal == signal and not result.timed_out
    assert result.provenance["ntstatus"] == f"0x{status & 0xFFFFFFFF:08x}"


def test_timeout_terminates_entire_job_before_draining_pipes(bundle):
    transport = Transport(status=0xB7C00001, timeout=True)
    result = executor(bundle, transport).run(ExecutionRequest("probe", timeout_s=0.01))
    termination = transport.events.index("terminate")
    assert transport.events[termination : termination + 3] == ["terminate", "communicate", "terminate"]
    assert result.timed_out and result.exit_status is None and result.signal is None
    assert transport.events[-1] == "close"


def test_assignment_failure_kills_unreleased_gate_and_closes_handles(bundle):
    transport = Transport(assignment_failure=True)
    with pytest.raises(OSError, match="assignment rejected"):
        executor(bundle, transport).run(ExecutionRequest("probe"))
    assert "release" not in transport.events
    assert "kill-gate" in transport.events
    assert transport.events[-2:] == ["empty", "close"]


def test_a_gate_that_started_nothing_is_an_infrastructure_error_not_a_program_exit(bundle):
    """The job's accounting, not a marker file, says whether the program ever started."""
    transport = Transport(status=1, gate_failure=True)
    with pytest.raises(RuntimeError, match="exited with 0x00000001 without starting probe"):
        executor(bundle, transport).run(ExecutionRequest("probe"))
    assert transport.events[-1] == "close"
    with pytest.raises(RuntimeError, match=r"had not started probe when its 0\.01s deadline expired"):
        executor(bundle, Transport(timeout=True, gate_failure=True)).run(ExecutionRequest("probe", timeout_s=0.01))


@pytest.mark.parametrize(
    "execution_request",
    [
        ExecutionRequest("probe", timeout_s=0),
        ExecutionRequest("probe", timeout_s=float("nan")),
        ExecutionRequest("probe", timeout_s=float("inf")),
        ExecutionRequest("probe", timeout_s=True),
        ExecutionRequest("probe", cwd_policy="repo"),
        ExecutionRequest("probe", cwd_policy="bundle"),
        ExecutionRequest("probe", launch_mode="app"),
        ExecutionRequest("probe", app_roots=("files",)),
        ExecutionRequest("probe", argv=("bad\0argument",)),
        ExecutionRequest("probe", env={"A=B": "x"}),
        ExecutionRequest("unadmitted"),
    ],
)
def test_invalid_request_never_spawns(bundle, execution_request):
    transport = Transport()
    with pytest.raises(ValueError):
        executor(bundle, transport).run(execution_request)
    assert transport.events == []


@pytest.mark.parametrize(
    "change",
    [
        "digest",
        "missing-digest",
        "architecture",
        "target-label",
        "unknown-target",
        "escape",
        "missing-file",
        "schema",
        "programs",
    ],
)
def test_bundle_admission_rejects_corruption_and_path_escape(bundle, change):
    document, label = read_document(bundle), LABEL
    if change == "digest":
        (bundle / "probe.exe").write_bytes((bundle / "probe.exe").read_bytes() + b"corrupted")
    elif change == "missing-digest":
        del document["programs"]["probe"]["sha256"]
    elif change == "architecture":
        image = pe_image(0xAA64)
        (bundle / "probe.exe").write_bytes(image)
        document["programs"]["probe"]["sha256"] = digest(image)
    elif change == "target-label":
        # The executor honours the label it is given: a bundle for another row is refused.
        label = "windows-aarch64"
    elif change == "unknown-target":
        document["target"]["label"] = label = "windows-unknown"
    elif change == "escape":
        document["programs"]["probe"]["artifact"] = "../outside.exe"
        (bundle.parent / "outside.exe").write_bytes((bundle / "probe.exe").read_bytes())
    elif change == "missing-file":
        (bundle / "probe.exe").unlink()
    elif change == "schema":
        document["schema"] = "btrc.windows-host-bundle/1"
    else:
        document["programs"] = []
    write_document(bundle, document)
    with pytest.raises(ValueError):
        executor(bundle, Transport(), label)


def test_an_architecture_the_hardware_would_only_emulate_is_refused(bundle):
    host = WindowsNativeExecutor(machine=lambda: 0xAA64)
    with pytest.raises(ValueError, match="emulated target runs are not evidence"):
        host.prepare(bundle, LABEL)
    WindowsNativeExecutor(machine=lambda: 0x8664).prepare(bundle, LABEL)


def test_the_loopback_listener_capability_is_the_hosts_own_probe():
    """A program that declares BTRC_TEST_REQUIRES: loopback-listener runs only
    where this host opens an IPv4 loopback listener; the runner asks after
    prepare, and the default probe opens a real one."""
    assert WindowsNativeExecutor(loopback=lambda: True).granted_capabilities() == frozenset({"loopback-listener"})
    assert WindowsNativeExecutor(loopback=lambda: False).granted_capabilities() == frozenset()
    assert WindowsNativeExecutor.loopback_listener() in {True, False}


def test_unbuilt_programs_are_never_staged(bundle):
    document = read_document(bundle)
    document["programs"]["selfhost-basics-Missing"] = {"source": "basics/Missing.btrc", "status": "missing"}
    document["programs"]["selfhost-basics-Broken"] = {"source": "basics/Broken.btrc", "status": "failed"}
    write_document(bundle, document)
    host = executor(bundle, Transport())
    assert set(host.programs) == {"probe"}


@pytest.mark.parametrize("data", [b"", b"MZ" + b"\0" * 126, b"MZ" + b"\xff" * 126])
def test_pe_parser_rejects_truncated_and_malformed_images(tmp_path, data):
    path = tmp_path / "bad.exe"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        pe_machine(path)


def test_ctypes_layout_uses_windows_fixed_width_dwords():
    assert ctypes.sizeof(Accounting) == 48
    assert Accounting.total_processes.offset == 36
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(ExtendedLimits) == 144
        assert ExtendedLimits.io.offset == 64


def test_tree_evidence_requires_all_generations_and_checks_each_pid():
    case = {
        "name": "tree",
        "exit_status": None,
        "signal": None,
        "timed_out": True,
        "stdout_policy": "tree-pids",
        "expected_stderr_sha256": digest(b""),
    }
    result = ExecutionResult(
        None,
        None,
        b"generation=0 pid=10\r\ngeneration=1 pid=20\r\ngeneration=2 pid=30\r\n",
        b"",
        True,
        1,
        {"job_empty": True},
    )
    checked = []
    verify(case, result, dead_check=checked.append)
    assert checked == [10, 20, 30]
    with pytest.raises(AssertionError, match="three distinct"):
        verify(case, replace(result, stdout=b"generation=0 pid=10\r\n"), dead_check=checked.append)
    with pytest.raises(AssertionError, match="three distinct"):
        verify(case, replace(result, stdout=result.stdout.replace(b"pid=30", b"pid=20")), dead_check=checked.append)


def test_corpus_lf_policy_is_explicit_and_raw_streams_are_not_normalized():
    case = {
        "name": "corpus",
        "exit_status": 0,
        "signal": None,
        "timed_out": False,
        "expected_stdout_sha256": digest(b"a\nb\n"),
        "expected_stderr_sha256": digest(b""),
    }
    result = ExecutionResult(0, None, b"a\r\nb\r\n", b"", False, 0.1, {"job_empty": True})
    with pytest.raises(AssertionError, match="stdout digest"):
        verify(case, result)
    verify({**case, "stdout_policy": "lf"}, result)


class RealPipeTransport(Transport):
    """POSIX process groups stand in for jobs, exercising real inherited pipes."""

    def __init__(self, *, fail_communication=False, fail_cleanup=False):
        super().__init__()
        self.fail_communication, self.fail_cleanup = fail_communication, fail_cleanup

    def spawn(self, command, **kwargs):
        self.spec = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        self.ready = Path(command[-1]).parent / "ready.json"
        script = """
import pathlib, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
ready = pathlib.Path(sys.argv[1])
ready.with_suffix('.tmp').write_text(str(child.pid))
ready.with_suffix('.tmp').replace(ready)
print('real output', flush=True)
if sys.argv[2] != 'normal':
    time.sleep(60)
"""
        self.process = subprocess.Popen(
            [sys.executable, "-c", script, str(self.ready), "error" if self.fail_communication else "normal"],
            start_new_session=True,
            **kwargs,
        )
        return self

    def communicate(self, data=None, timeout=None):
        if self.fail_communication:
            self.fail_communication = False
            deadline = time.monotonic() + 5
            while not self.ready.exists():
                if time.monotonic() > deadline:
                    raise AssertionError("portable pipe fixture did not start")
                time.sleep(0.01)
            self.child_pid = int(self.ready.read_text())
            raise OSError("injected transport failure")
        result = self.process.communicate(timeout=timeout)
        self.returncode = self.process.returncode
        if self.ready.exists():
            self.child_pid = int(self.ready.read_text())
        return result

    def poll(self):
        return self.process.poll()

    def kill(self):
        self.process.kill()

    def terminate(self):
        with suppress(ProcessLookupError):
            os.killpg(self.process.pid, signal.SIGKILL)

    def wait_empty(self):
        self.process.wait(timeout=2)
        if self.fail_cleanup:
            raise RuntimeError("injected accounting failure")


@pytest.mark.skipif(os.name != "posix", reason="real pipe stand-in uses POSIX groups; native proof is check.py")
def test_target_return_with_descendant_holding_real_pipe_is_not_timeout(bundle):
    transport = RealPipeTransport()
    started = time.monotonic()
    result = executor(bundle, transport).run(ExecutionRequest("probe", timeout_s=3))
    assert result.exit_status == 0 and not result.timed_out
    assert result.stdout == b"real output\n"
    assert time.monotonic() - started < 2
    assert_process_dead(transport.child_pid)


@pytest.mark.skipif(os.name != "posix", reason="real pipe stand-in uses POSIX groups; native proof is check.py")
def test_infrastructure_error_terminates_real_pipe_holder_and_preserves_original(bundle):
    transport = RealPipeTransport(fail_communication=True, fail_cleanup=True)
    started = time.monotonic()
    with pytest.raises(OSError, match="injected transport failure") as caught:
        executor(bundle, transport).run(ExecutionRequest("probe"))
    assert "injected accounting failure" in caught.value.__notes__[0]
    assert time.monotonic() - started < 2
    assert transport.process.poll() is not None
    assert_process_dead(transport.child_pid)
    assert transport.events[-1] == "close"


def test_setup_time_uses_request_deadline_and_stdin_does_not_block_pipe(bundle):
    transport = Transport()
    times = iter([0, 2])
    # The injected clock belongs to this executor only; repeated reads are stable.
    host = WindowsNativeExecutor(
        job_factory=lambda: transport,
        spawn=transport.spawn,
        clock=lambda: next(times, 2),
        capture_factory=lambda process: process,
    )
    host.prepare(bundle, LABEL)
    result = host.run(ExecutionRequest("probe", stdin=b"x" * 300000, timeout_s=1))
    assert result.timed_out
    assert len(transport.input) == 300000


def assert_process_dead(pid):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        status = Path(f"/proc/{pid}/stat")
        try:
            if status.read_text().split(") ", 1)[1].split()[0] == "Z":
                return  # Exited, awaiting the host's reaper; cannot hold a pipe.
        except FileNotFoundError:
            pass
        time.sleep(0.01)
    raise AssertionError(f"portable fixture process {pid} survived cleanup")


def test_success_inside_caller_exception_does_not_hide_cleanup_failure(bundle):
    class CleanupFailure(Transport):
        def close(self):
            super().close()
            raise RuntimeError("cleanup failure on otherwise successful run")

    try:
        raise KeyError("caller exception")
    except KeyError:
        with pytest.raises(RuntimeError, match="cleanup failure on otherwise successful run"):
            executor(bundle, CleanupFailure()).run(ExecutionRequest("probe"))


def test_target_launch_failure_preserves_exact_native_error(bundle):
    class LaunchFailure(Transport):
        def communicate(self, data=None, timeout=None):
            super().communicate(data, timeout)
            return (
                b"",
                b"btrc Windows gate: CreateProcessW failed: winerror=193 errno=8: not a valid Win32 application\n",
            )

    with pytest.raises(
        RuntimeError, match="CreateProcessW failed: winerror=193 errno=8: not a valid Win32 application"
    ):
        executor(bundle, LaunchFailure(status=1, gate_failure=True)).run(ExecutionRequest("probe"))


def acceptance_manifest():
    cases = acceptance_cases()
    return {
        "cases": cases,
        "programs": {case["program"]: {"executable": f"{case['program']}.exe"} for case in cases},
        "toolchain": {
            "source_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=bundle_module.ROOT, text=True, timeout=10
            ).strip()
        },
    }


def test_acceptance_requires_every_exact_case_once():
    manifest = acceptance_manifest()
    assert len(validate_cases(manifest)) == 16
    for index in range(16):
        with pytest.raises(ValueError, match="case set mismatch"):
            validate_cases({"cases": manifest["cases"][:index] + manifest["cases"][index + 1 :]})
    for cases in ([], manifest["cases"][:5], manifest["cases"] + [manifest["cases"][0]]):
        with pytest.raises(ValueError, match="case set mismatch"):
            validate_cases({"cases": cases})
    for value in ({}, {"cases": None}, {"cases": [{}]}, {"cases": "cases"}):
        with pytest.raises(ValueError, match="complete named case list"):
            validate_cases(value)


@pytest.mark.parametrize("change", ["program", "frontend", "policy", "tree"])
def test_acceptance_case_names_cannot_mask_missing_evidence(change):
    manifest = acceptance_manifest()
    if change == "program":
        manifest["cases"][-1]["program"] = "probe"
    elif change == "frontend":
        manifest["cases"][-1]["frontend"] = "python"
    elif change == "policy":
        manifest["cases"][-1]["stdout_policy"] = "bytes"
    else:
        manifest["cases"][10]["stdout_policy"] = "bytes"
    with pytest.raises(ValueError):
        validate_cases(manifest)


def test_compiler_receipt_binds_binary_and_source_inputs(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=10)
    source = tmp_path / "src/compiler/input.c"
    source.parent.mkdir(parents=True)
    source.write_text("source")
    subprocess.run(["git", "add", "src"], cwd=tmp_path, check=True, timeout=10)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
        timeout=10,
    )
    compiler = tmp_path / "btrcc"
    compiler.write_bytes(b"binary")
    receipt = tmp_path / "receipt.json"
    recorded = record_compiler_provenance(compiler, receipt, root=tmp_path)
    assert verify_compiler_provenance(compiler, receipt, root=tmp_path) == recorded
    compiler.write_bytes(b"wrong binary")
    with pytest.raises(ValueError, match="does not match its build receipt"):
        verify_compiler_provenance(compiler, receipt, root=tmp_path)
    compiler.write_bytes(b"binary")
    source.write_text("different source")
    with pytest.raises(ValueError, match="source inputs do not match"):
        verify_compiler_provenance(compiler, receipt, root=tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="bundle producer uses the Linux build host")
def test_bundle_command_timeout_kills_descendant_pipe_holder(tmp_path):
    ready = tmp_path / "child.pid"
    script = "import pathlib,subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(60)"
    with pytest.raises(subprocess.TimeoutExpired):
        run_build_command([sys.executable, "-c", script, str(ready)], cwd=tmp_path, capture=True, timeout_s=0.5)
    assert ready.is_file()
    assert_process_dead(int(ready.read_text()))


@pytest.mark.parametrize("truncated", [True, False])
def test_native_checker_reports_manifest_and_launch_failures(tmp_path, monkeypatch, truncated):
    manifest = acceptance_manifest()
    manifest["target"] = LABEL
    if truncated:
        manifest["cases"] = []
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    report = tmp_path / "report.json"
    labels = []

    class FailedExecutor:
        def prepare(self, bundle_dir, label):
            labels.append(label)

        def run(self, *args):
            raise OSError("target launch rejected")

        def close(self):
            pass

    monkeypatch.setattr(check_module, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(check_module, "WindowsNativeExecutor", FailedExecutor)
    with pytest.raises((ValueError, RuntimeError)):
        check_module.check(bundle, report, "portable checker test")
    outcome = json.loads(report.read_text())
    assert outcome["passed"] == 0 and outcome["failed"] == (1 if truncated else 16) and not outcome["complete"]
    assert len(outcome["results"]) == (0 if truncated else 16)
    assert outcome["runner"] == "portable checker test"
    if not truncated:
        assert outcome["results"][0]["error"] == "OSError: target launch rejected"
        # The executor is given the bundle's targets.toml row, not the runner's name.
        assert labels == [LABEL]


@pytest.mark.skipif(os.name != "posix", reason="bundle producer uses the Linux build host")
@pytest.mark.parametrize("status", [0, 7])
def test_returned_bundle_wrapper_cannot_leave_file_writer_alive(tmp_path, status):
    ready = tmp_path / "child.pid"
    script = "import pathlib,subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); pathlib.Path(sys.argv[1]).write_text(str(p.pid)); sys.exit(int(sys.argv[2]))"
    command = [sys.executable, "-c", script, str(ready), str(status)]
    with (tmp_path / "generated.c").open("wb") as output:
        if status:
            with pytest.raises(subprocess.CalledProcessError) as caught:
                run_build_command(command, cwd=tmp_path, stdout=output, capture=False, timeout_s=5)
            assert caught.value.returncode == status
        else:
            run_build_command(command, cwd=tmp_path, stdout=output, capture=False, timeout_s=5)
    assert_process_dead(int(ready.read_text()))


def test_failed_prepare_keeps_only_previous_verified_bundle(bundle, tmp_path, private_temporary_root):
    host = executor(bundle, Transport())
    admitted = host.staging
    rejected = write_bundle(tmp_path / "rejected")
    document = read_document(rejected)
    document["programs"]["probe"]["sha256"] = "0" * 64
    write_document(rejected, document)
    with pytest.raises(ValueError):
        host.prepare(rejected, LABEL)
    assert host.label == LABEL and host.staging == admitted
    assert host.run(ExecutionRequest("probe")).exit_status == 0
    # The refused admission left no staging directory behind.
    assert [path.name for path in private_temporary_root.iterdir()] == [admitted.name]
    fresh = WindowsNativeExecutor()
    with pytest.raises(ValueError):
        fresh.prepare(rejected, "rejected")
    with pytest.raises(RuntimeError, match="prepare a bundle"):
        fresh.run(ExecutionRequest("probe"))


def test_a_bundle_changed_after_prepare_cannot_change_what_runs(bundle):
    transport = Transport()
    host = executor(bundle, transport)
    admitted = (bundle / "probe.exe").read_bytes()
    image = bytearray(admitted)
    image[-1] ^= 1  # Same length and still a valid PE; only a digest tells them apart.
    (bundle / "probe.exe").write_bytes(image)
    assert host.run(ExecutionRequest("probe")).exit_status == 0
    launched = Path(transport.spec["command"][0])
    assert launched == host.programs["probe"].path and launched.read_bytes() == admitted


def test_the_digest_is_checked_on_the_held_staged_copy(bundle):
    class SwappedAfterCopy:
        """Stands in for bytes that changed between the copy and the hold."""

        def __init__(self, path):
            self.path = path

        def read(self):
            return pe_image(tail=b"swapped")

        def close(self):
            pass

    host = WindowsNativeExecutor(hold=SwappedAfterCopy)
    with pytest.raises(ValueError, match="staged copy does not match"):
        host.prepare(bundle, LABEL)
    assert host.staging is None and host.programs == {}


def test_close_releases_every_staged_copy_and_is_idempotent(bundle):
    held = []

    class Recorded(executor_module.HeldArtifact):
        def __init__(self, path):
            super().__init__(path)
            held.append(self)

    host = WindowsNativeExecutor(hold=Recorded)
    host.prepare(bundle, LABEL)
    staging = host.staging
    assert staging.is_dir() and len(held) == 1 and not held[0].closed
    host.close()
    host.close()
    assert held[0].closed and not staging.exists()
    assert host.label is None and host.programs == {}
    with pytest.raises(ValueError, match="no longer held"):
        held[0].read()


@pytest.mark.parametrize("filename", ["probe.cmd", "probe.bat", "other.exe"])
def test_executable_mapping_and_extension_cannot_select_another_launcher(bundle, filename):
    (bundle / filename).write_bytes((bundle / "probe.exe").read_bytes())
    document = read_document(bundle)
    document["programs"]["probe"]["artifact"] = filename
    write_document(bundle, document)
    with pytest.raises(ValueError, match="exact program name"):
        executor(bundle, Transport())


def test_the_control_directory_is_neither_in_nor_beside_the_target_cwd(bundle, monkeypatch):
    class CwdForger(Transport):
        def spawn(self, command, **kwargs):
            result = super().spawn(command, **kwargs)
            cwd, control = Path(self.spec["cwd"]), Path(command[-1]).parent
            assert set(cwd.iterdir()) == set()
            assert control != cwd and cwd not in control.parents and control.parent != cwd.parent
            # Nothing but the launch itself is serialized: no status or error marker.
            assert set(self.spec) == {"command", "cwd", "env"}
            assert "PRIVATE_HOST_VALUE" not in self.spec["env"]
            for filename in ("status.txt", "launch-error.json", "request.json", "stdin.bin"):
                (cwd / filename).write_text("forged")
            return result

    monkeypatch.setenv("PRIVATE_HOST_VALUE", "not serialized")
    result = executor(bundle, CwdForger(status=3)).run(ExecutionRequest("probe"))
    assert result.exit_status == 3 and not result.timed_out


def test_no_control_file_decides_the_outcome(bundle):
    class ControlForger(Transport):
        def communicate(self, data=None, timeout=None):
            result = super().communicate(data, timeout)
            control = Path(self.command[-1]).parent
            for name in ("status.txt", "launch-error.json", "request.json", "stdin.bin"):
                (control / name).write_text("0")
            return result

    result = executor(bundle, ControlForger(status=3)).run(ExecutionRequest("probe"))
    assert result.exit_status == 3


def test_provenance_names_a_device_class_never_the_host(bundle, monkeypatch):
    monkeypatch.setenv("COMPUTERNAME", "private-host-name")
    result = executor(bundle, Transport()).run(ExecutionRequest("probe"))
    assert {"executor", "device", "os_build", "toolchain"} <= set(result.provenance)
    assert "private-host-name" not in json.dumps(result.provenance)
    assert result.provenance["toolchain"] == {"cc": ["stand-in"]}


def test_windows_environment_override_replaces_different_case():
    assert merged_environment({"Path": "host", "Temp": "temp"}, {"PATH": "target", "tEmP": "new"}) == {
        "PATH": "target",
        "TEMP": "new",
    }


def test_temporary_cleanup_failure_retains_finished_result(bundle, monkeypatch):
    real = executor_module.shutil.rmtree
    retained = []

    def fail(path, **kwargs):
        retained.append(path)
        raise PermissionError("busy directory")

    host = executor(bundle, Transport())
    monkeypatch.setattr(executor_module.shutil, "rmtree", fail)
    try:
        result = host.run(ExecutionRequest("probe"))
        assert result.exit_status == 0
        assert "busy directory" in result.provenance["cleanup_warnings"][0]
    finally:
        monkeypatch.setattr(executor_module.shutil, "rmtree", real)
        for path in retained:
            real(path)
        host.close()


@pytest.mark.skipif(os.name != "posix", reason="a read-only POSIX directory stands in for a read-only Windows file")
def test_a_read_only_tree_the_target_leaves_in_its_cwd_is_removed(bundle):
    class ReadOnlyLitter(Transport):
        def spawn(self, command, **kwargs):
            result = super().spawn(command, **kwargs)
            litter = Path(self.spec["cwd"]) / "litter"
            litter.mkdir()
            (litter / "file").write_text("kept read-only")
            (litter / "file").chmod(stat.S_IRUSR)
            litter.chmod(stat.S_IRUSR | stat.S_IXUSR)
            return result

    transport = ReadOnlyLitter()
    result = executor(bundle, transport).run(ExecutionRequest("probe"))
    assert result.provenance["cleanup_warnings"] == []
    assert not Path(transport.spec["cwd"]).exists()


def test_remove_tree_clears_read_only_bits(tmp_path):
    tree = tmp_path / "tree"
    (tree / "nested").mkdir(parents=True)
    (tree / "nested" / "file").write_text("x")
    (tree / "nested" / "file").chmod(stat.S_IRUSR)
    (tree / "nested").chmod(stat.S_IRUSR | stat.S_IXUSR)
    remove_tree(tree)
    assert not tree.exists()


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_bounded_capture_stops_unlimited_output_without_retaining_over_budget(stream):
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            f"import os,time; os.write({1 if stream == 'stdout' else 2}, b'x'*131072); time.sleep(30)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    captured = BoundedOutput(process, limit=4096)
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                captured.communicate(timeout=0.05)
            except subprocess.TimeoutExpired:
                assert time.monotonic() < deadline
                continue
            except RuntimeError as error:
                assert stream in str(error) and "exceeded 4096" in str(error)
                break
            raise AssertionError("unlimited writer unexpectedly completed")
        assert all(len(buffer) <= 4096 for buffer in captured.buffers)
    finally:
        process.kill()
        with suppress(RuntimeError):
            captured.communicate(timeout=5)
        assert not any(thread.is_alive() for thread in captured.threads)


@pytest.mark.parametrize(
    "field,value",
    [
        ("argv", ["exit", "0"]),
        ("exit_status", 1),
        ("exit_status", False),
        ("signal", 11),
        ("timed_out", True),
        ("timeout_s", 100),
        ("expected_stdout_sha256", digest(b"forged")),
        ("expected_stderr_sha256", digest(b"forged")),
        ("stdin_hex", "ff"),
        ("env", {"PATH": "forged"}),
        ("stdout_policy", "lf"),
    ],
)
def test_case_admission_pins_every_execution_and_expectation_field(field, value):
    for index in range(16):
        manifest = acceptance_manifest()
        if json.dumps(manifest["cases"][index].get(field)) == json.dumps(value):
            continue
        manifest["cases"][index][field] = value
        with pytest.raises(ValueError, match="acceptance inputs"):
            validate_cases(manifest)


def test_case_admission_recomputes_goldens_and_checks_checkout_revision():
    manifest = acceptance_manifest()
    manifest["cases"][-1]["expected_stdout_sha256"] = digest(b"counterfeit golden")
    with pytest.raises(ValueError, match="golden digests"):
        validate_cases(manifest)
    manifest = acceptance_manifest()
    manifest["toolchain"]["source_revision"] = "0" * 40
    with pytest.raises(ValueError, match="checkout revision"):
        validate_cases(manifest)
    manifest = acceptance_manifest()
    manifest["programs"]["probe"]["executable"] = "other.exe"
    with pytest.raises(ValueError, match="executable mapping"):
        validate_cases(manifest)


@pytest.mark.parametrize("target", list(bundle_module.TARGETS))
def test_builder_manifest_roundtrips_complete_validator_with_stubbed_compilers(tmp_path, monkeypatch, target):
    compiler = tmp_path / "btrcc"
    compiler.write_bytes(b"stub")
    monkeypatch.setattr(bundle_module, "verify_compiler_provenance", lambda *args, **kwargs: {})
    machine = bundle_module.TARGETS[target][1]
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=10)
    for source in bundle_module.CORPUS:
        program = root / f"src/tests/{source}.btrc"
        program.parent.mkdir(parents=True, exist_ok=True)
        program.write_text("stub program")
        golden = program.parent / "expected" / f"{program.stem}.stdout"
        golden.parent.mkdir(exist_ok=True)
        golden.write_bytes(b"line one\r\nline two\r\n")
    commit_fixture(root, "stub corpus")

    def run(command, *, cwd, stdout=None, capture=False, **kwargs):
        if command == ["zig", "version"]:
            return b"stub-zig\n"
        if command[:2] == ["zig", "cc"]:
            Path(command[command.index("-o") + 1]).write_bytes(pe_image(machine))
        elif stdout is not None:
            stdout.write(b"/* stub C */")
        else:
            Path(command[command.index("-o") + 1]).write_text("/* stub C */")

    monkeypatch.setattr(bundle_module, "run_build_command", run)
    output = tmp_path / "output"
    manifest = bundle_module.build(output, target, compiler, root=root)
    assert len(validate_cases(manifest, root=root)) == 16
    assert manifest["cases"][-1]["expected_stdout_sha256"] == digest(b"line one\nline two\n")
    assert len(manifest["programs"]) == 6
    # The same build writes the protocol index, which the executor admits as is.
    document = read_document(output)
    assert document["schema"] == "btrc.target-bundle/1" and document["target"]["label"] == target
    assert document["source_revision"] == manifest["toolchain"]["source_revision"]
    assert {name: entry["artifact"] for name, entry in document["programs"].items()} == {
        name: record["executable"] for name, record in manifest["programs"].items()
    }
    assert {entry["frontend"] for entry in document["programs"].values()} == {"c", "reference", "selfhost"}
    host = WindowsNativeExecutor(machine=lambda: machine)
    try:
        host.prepare(output, target)
        assert set(host.programs) == set(manifest["programs"])
    finally:
        host.close()


def commit_fixture(root, message):
    subprocess.run(["git", "add", "."], cwd=root, check=True, timeout=10)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            message,
        ],
        cwd=root,
        check=True,
        timeout=10,
    )
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=10).strip()


def test_receipt_requires_real_matching_revision_and_reports_dirty_inputs(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=10)
    source = root / "src/compiler/input.c"
    source.parent.mkdir(parents=True)
    source.write_text("original input")
    original = commit_fixture(root, "original")
    compiler, receipt = tmp_path / "btrcc", tmp_path / "receipt.json"
    compiler.write_bytes(b"compiler")
    record = record_compiler_provenance(compiler, receipt, root=root)
    assert record["source_tree_dirty"] is False and record["source_inputs_dirty"] is False
    (root / "README.md").write_text("docs only")
    commit_fixture(root, "docs only")
    assert verify_compiler_provenance(compiler, receipt, root=root) == record
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=root, text=True, timeout=10).strip()
    for revision in ("f" * 40, "x" * 40, tree):
        receipt.write_text(json.dumps({**record, "source_revision": revision}))
        with pytest.raises(ValueError, match="revision"):
            verify_compiler_provenance(compiler, receipt, root=root)
    source.write_text("modified input")
    for staged in (False, True):
        if staged:
            subprocess.run(["git", "add", str(source)], cwd=root, check=True, timeout=10)
        dirty = record_compiler_provenance(compiler, receipt, root=root)
        assert dirty["source_tree_dirty"] is True and dirty["source_inputs_dirty"] is True
        with pytest.raises(ValueError, match="committed compiler inputs"):
            verify_compiler_provenance(compiler, receipt, root=root)
    commit_fixture(root, "different compiler inputs")
    changed = record_compiler_provenance(compiler, receipt, root=root)
    receipt.write_text(json.dumps({**changed, "source_revision": original}))
    with pytest.raises(ValueError, match="different compiler inputs"):
        verify_compiler_provenance(compiler, receipt, root=root)


def test_windows_gate_launch_detaches_from_harness_console(bundle, monkeypatch):
    class ConsoleTransport(Transport):
        def spawn(self, command, **kwargs):
            assert kwargs["creationflags"] == 0x00000008 | 0x00000200
            return super().spawn(command, **kwargs)

    host = executor(bundle, ConsoleTransport())
    monkeypatch.setattr(executor_module, "sys", SimpleNamespace(platform="win32", executable=sys.executable))
    assert host.run(ExecutionRequest("probe")).exit_status == 0


def _gate_api(events):
    return SimpleNamespace(
        OpenEventW=lambda *_: 1,
        WaitForSingleObject=lambda *_: 0,
        CloseHandle=lambda *_: 1,
        GetErrorMode=lambda: 0,
        SetErrorMode=lambda flags: events.append(("error-mode", flags)),
        ExitProcess=lambda status: events.append(("exit", status)),
    )


def _gate_request(path, command, cwd, env=None):
    path.write_text(json.dumps({"command": command, "cwd": str(cwd), "env": env or {}}), encoding="utf-8")
    return path


def test_detached_gate_explicitly_forwards_binary_standard_streams(tmp_path, monkeypatch):
    # Model Windows' lack of implicit stdio inheritance from a detached gate.
    # The target really transports bytes; this is not native Windows evidence.
    payload = bytes(range(256)) * 1024
    request = _gate_request(
        tmp_path / "request.json",
        [
            sys.executable,
            "-c",
            "import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data); "
            "sys.stderr.buffer.write(b'error\\x00\\xff'); sys.exit(3)",
        ],
        tmp_path,
    )
    events = []
    monkeypatch.setattr(executor_module.WindowsJob, "bind", staticmethod(lambda: _gate_api(events)))
    real_run = subprocess.run
    launches = []

    def detached_run(command, **kwargs):
        launches.append(kwargs.pop("creationflags", 0))
        # Without explicit STARTF_USESTDHANDLES, a detached Windows parent
        # cannot supply its standard handles through console inheritance.
        for stream in ("stdin", "stdout", "stderr"):
            kwargs.setdefault(stream, subprocess.DEVNULL)
        return real_run(command, **kwargs, timeout=10)

    monkeypatch.setattr(executor_module.subprocess, "run", detached_run)
    stdin_path = tmp_path / "stdin.bin"
    stdin_path.write_bytes(payload)
    with (
        stdin_path.open("rb") as stdin,
        (tmp_path / "stdout.bin").open("w+b") as stdout,
        (tmp_path / "stderr.bin").open("w+b") as stderr,
    ):
        monkeypatch.setattr(
            executor_module, "sys", SimpleNamespace(platform="win32", stdin=stdin, stdout=stdout, stderr=stderr)
        )
        executor_module.WindowsJob.gate("test-event", request)
        stdout.seek(0)
        stderr.seek(0)
        assert stdout.read() == payload
        assert stderr.read() == b"error\x00\xff"
    assert launches == [0x08000000 | 0x00000200]
    assert events == [("error-mode", 0x0001 | 0x0002 | 0x8000), ("exit", 3)]
    # The gate writes no marker: its exit code is the whole report.
    written = sorted(path.name for path in tmp_path.iterdir() if path.is_file())
    assert written == ["request.json", "stderr.bin", "stdin.bin", "stdout.bin"]


def test_the_gate_reports_a_launch_failure_on_its_own_stderr(tmp_path, monkeypatch):
    request = _gate_request(tmp_path / "request.json", ["missing.exe"], tmp_path)
    events = []
    monkeypatch.setattr(executor_module.WindowsJob, "bind", staticmethod(lambda: _gate_api(events)))

    def refused(command, **kwargs):
        error = OSError(8, "not a valid Win32 application")
        error.winerror = 193
        raise error

    monkeypatch.setattr(executor_module.subprocess, "run", refused)
    stderr = io.StringIO()
    monkeypatch.setattr(
        executor_module, "sys", SimpleNamespace(platform="win32", stdin=None, stdout=None, stderr=stderr)
    )
    executor_module.WindowsJob.gate("event", request)
    assert stderr.getvalue() == (
        "btrc Windows gate: CreateProcessW failed: winerror=193 errno=8: not a valid Win32 application\n"
    )
    assert events[-1] == ("exit", 1)


@pytest.mark.skipif(os.name != "posix", reason="real pipe stand-in uses POSIX groups; native proof is check.py")
@pytest.mark.parametrize("mode", ["return", "sleep"])
def test_real_target_cwd_control_collisions_do_not_forge_exit_or_timeout(bundle, mode):
    class CollisionTransport(RealPipeTransport):
        def spawn(self, command, **kwargs):
            self.spec = json.loads(Path(command[-1]).read_text())
            self.ready = Path(command[-1]).parent / "ready.pid"
            target = "import pathlib,time,sys; [pathlib.Path(n).write_text('not-an-int') for n in ('status.txt','launch-error.json','request.json','stdin.bin')]; time.sleep(60 if sys.argv[1]=='sleep' else 0); sys.exit(3)"
            gate = """
import json,pathlib,subprocess,sys
spec=json.loads(pathlib.Path(sys.argv[1]).read_text())
child=subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[3]],cwd=spec['cwd'])
ready=pathlib.Path(sys.argv[4]); ready.with_suffix('.tmp').write_text(str(child.pid)); ready.with_suffix('.tmp').replace(ready)
sys.exit(child.wait())
"""
            self.process = subprocess.Popen(
                [sys.executable, "-c", gate, command[-1], target, mode, str(self.ready)],
                start_new_session=True,
                **kwargs,
            )
            return self

    transport = CollisionTransport()
    result = executor(bundle, transport).run(ExecutionRequest("probe", timeout_s=2))
    assert result.timed_out == (mode == "sleep")
    assert result.exit_status == (None if mode == "sleep" else 3)
    assert_process_dead(transport.child_pid)


def test_checker_collects_assertion_and_launch_failure_while_later_cases_run(tmp_path, monkeypatch):
    manifest = acceptance_manifest()
    manifest["target"] = LABEL
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    calls = []

    class MixedExecutor:
        def prepare(self, *args):
            pass

        def run(self, request):
            calls.append(request)
            if len(calls) == 8:
                raise OSError("middle launch error")
            return ExecutionResult(0, None, b"", b"", False, 0.01, {})

        def close(self):
            pass

    def mixed_verify(case, result):
        if case["name"] == manifest["cases"][0]["name"]:
            raise AssertionError("first case mismatch")

    monkeypatch.setattr(check_module, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(check_module, "WindowsNativeExecutor", MixedExecutor)
    monkeypatch.setattr(check_module, "verify", mixed_verify)
    report = tmp_path / "results.json"
    with pytest.raises(RuntimeError, match="all collected results"):
        check_module.check(bundle, report, "portable mixed failures")
    result = json.loads(report.read_text())
    assert len(calls) == len(result["results"]) == 16
    assert result["passed"] == 14 and result["failed"] == 2 and not result["complete"]


def test_bounded_capture_handles_simultaneous_stdout_and_stderr_flood():
    script = """
import os,threading,time
threads=[threading.Thread(target=os.write,args=(fd,b'x'*131072)) for fd in (1,2)]
for thread in threads: thread.start()
for thread in threads: thread.join()
time.sleep(30)
"""
    process = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    capture = BoundedOutput(process, limit=4096)
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                capture.communicate(timeout=0.05)
            except subprocess.TimeoutExpired:
                assert time.monotonic() < deadline
                continue
            except RuntimeError as error:
                assert "exceeded 4096" in str(error)
                break
            raise AssertionError("both-stream flood unexpectedly completed")
        assert all(len(buffer) <= 4096 for buffer in capture.buffers)
    finally:
        process.kill()
        with suppress(RuntimeError):
            capture.communicate(timeout=5)
        assert not any(thread.is_alive() for thread in capture.threads)


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
def test_checker_does_not_turn_interrupts_into_ordinary_case_failures(tmp_path, monkeypatch, interrupt):
    manifest = acceptance_manifest()
    manifest["target"] = LABEL
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    calls = []

    class InterruptedExecutor:
        def prepare(self, *args):
            pass

        def run(self, *args):
            calls.append(1)
            raise interrupt("stop")

        def close(self):
            pass

    monkeypatch.setattr(check_module, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(check_module, "WindowsNativeExecutor", InterruptedExecutor)
    report = tmp_path / "report.json"
    with pytest.raises(interrupt):
        check_module.check(bundle, report, "interrupted")
    result = json.loads(report.read_text())
    assert len(calls) == 1 and not result["complete"] and result["failed"] == 1


@pytest.mark.skipif(os.name != "posix", reason="symlink admission fixture uses the Linux bundle producer")
@pytest.mark.parametrize("suffix", [".cmd", ".bat"])
def test_canonical_exe_symlink_cannot_resolve_to_batch_launcher(bundle, suffix):
    launcher = bundle / ("launcher" + suffix)
    (bundle / "probe.exe").rename(launcher)
    (bundle / "probe.exe").symlink_to(launcher.name)
    transport = Transport()
    with pytest.raises(ValueError, match=r"\.exe extension"):
        executor(bundle, transport)
    assert transport.events == []


@pytest.mark.skipif(os.name != "posix", reason="real pipe stand-in uses POSIX groups; native proof is check.py")
@pytest.mark.parametrize("timeout", [False, True])
def test_production_capture_integrates_with_executor_and_descendant_cleanup(bundle, timeout):
    class ProductionCaptureTransport(RealPipeTransport):
        @property
        def stdout(self):
            return self.process.stdout

        @property
        def stderr(self):
            return self.process.stderr

        def wait(self, timeout):
            self.returncode = self.process.wait(timeout=timeout)
            if self.ready.exists():
                self.child_pid = int(self.ready.read_text())
            return self.returncode

    transport = ProductionCaptureTransport(fail_communication=timeout)
    host = WindowsNativeExecutor(job_factory=lambda: transport, spawn=transport.spawn)
    host.prepare(bundle, LABEL)
    result = host.run(ExecutionRequest("probe", timeout_s=2))
    assert result.timed_out == timeout
    assert result.stdout == b"real output\n"
    assert result.exit_status == (None if timeout else 0)
    assert transport.process.stdout.closed and transport.process.stderr.closed
    assert_process_dead(transport.child_pid)


@pytest.mark.skipif(os.name != "posix", reason="POSIX stand-in for the Windows gate")
def test_a_target_forging_every_control_file_it_can_find_cannot_change_its_outcome(bundle):
    """A program that searches its temporary root and overwrites what it finds still exits 3."""

    class Forger(RealPipeTransport):
        def spawn(self, command, **kwargs):
            self.spec = json.loads(Path(command[-1]).read_text())
            self.ready = Path(command[-1]).parent / "ready.pid"
            target = (
                "import pathlib,sys\n"
                "for path in pathlib.Path('..').rglob('*'):\n"
                "    if path.is_file() and path.suffix in ('.json', '.bin', '.txt', '.pid'):\n"
                "        path.write_text('0')\n"
                "(pathlib.Path('..')/'control').mkdir(exist_ok=True)\n"
                "(pathlib.Path('..')/'control'/'status.txt').write_text('0')\n"
                "sys.exit(3)\n"
            )
            gate = (
                "import json,pathlib,subprocess,sys\n"
                "spec=json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
                "ready=pathlib.Path(sys.argv[3])\n"
                "child=subprocess.Popen([sys.executable,'-c',sys.argv[2]],cwd=spec['cwd'])\n"
                "ready.with_suffix('.tmp').write_text(str(child.pid)); ready.with_suffix('.tmp').replace(ready)\n"
                "sys.exit(child.wait())\n"
            )
            self.process = subprocess.Popen(
                [sys.executable, "-c", gate, command[-1], target, str(self.ready)],
                start_new_session=True,
                **kwargs,
            )
            return self

    result = executor(bundle, Forger()).run(ExecutionRequest("probe", timeout_s=5))
    assert result.exit_status == 3 and not result.timed_out


@pytest.mark.skipif(os.name != "posix", reason="POSIX stand-in for the Windows gate")
def test_run_enforces_the_one_mebibyte_output_limit(bundle):
    """The production limit is applied through run(), not only BoundedOutput(limit=...)."""

    class Flood(RealPipeTransport):
        @property
        def stdout(self):
            return self.process.stdout

        @property
        def stderr(self):
            return self.process.stderr

        def wait(self, timeout):
            self.returncode = self.process.wait(timeout=timeout)
            return self.returncode

        def spawn(self, command, **kwargs):
            self.spec = json.loads(Path(command[-1]).read_text())
            self.ready = Path(command[-1]).parent / "ready.pid"
            self.child_pid = None
            script = "import os\nos.write(1, b'x' * (1024 * 1024 + 1))\n"
            self.process = subprocess.Popen([sys.executable, "-c", script], start_new_session=True, **kwargs)
            return self

    transport = Flood()
    host = WindowsNativeExecutor(job_factory=lambda: transport, spawn=lambda *a, **k: transport.spawn(*a, **k))
    host.prepare(bundle, LABEL)
    with pytest.raises(RuntimeError, match="exceeded 1048576") as caught:
        host.run(ExecutionRequest("probe", timeout_s=5))
    assert executor_module.OUTPUT_LIMIT_BYTES == 1024 * 1024
    # Draining the pipes again during cleanup re-raises the same overflow; it is not a second failure.
    assert not any("exceeded" in note for note in getattr(caught.value, "__notes__", []))


def test_the_gate_merges_the_host_environment_case_insensitively(tmp_path, monkeypatch):
    """Drive WindowsJob.gate and check the environment that reaches the target."""
    request = _gate_request(tmp_path / "request.json", ["target"], tmp_path, {"path": "override"})
    monkeypatch.setattr(executor_module.WindowsJob, "bind", staticmethod(lambda: _gate_api([])))
    seen = {}

    def fake_run(command, **kwargs):
        seen.update(kwargs["env"])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(executor_module.subprocess, "run", fake_run)
    monkeypatch.setattr(executor_module.os, "environ", {"PATH": "host", "SYSTEMROOT": "C:\\Windows"})
    executor_module.WindowsJob.gate("event", request)
    assert seen == {"PATH": "override", "SYSTEMROOT": "C:\\Windows"}
