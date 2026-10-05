"""Portable transport tests; none of these claim native Windows execution."""

from __future__ import annotations

import ctypes
import json
import os
import signal
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
    Accounting,
    BoundedOutput,
    ExecutionRequest,
    ExecutionResult,
    ExtendedLimits,
    WindowsNativeExecutor,
    merged_environment,
)


@pytest.fixture
def bundle(tmp_path):
    executable = tmp_path / "probe.exe"
    data = bytearray(128)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 64)
    data[64:68] = b"PE\0\0"
    struct.pack_into("<H", data, 68, 0x8664)
    executable.write_bytes(data)
    manifest = {
        "schema": "btrc.windows-host-bundle/1",
        "target": "windows-x86_64",
        "pe_machine": 0x8664,
        "programs": {"probe": {"executable": "probe.exe", "sha256": digest(data), "pe_machine": 0x8664}},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


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
        if not self.gate_failure and "release" in self.events:
            Path(self.spec["status"]).write_text(str(self.status & 0xFFFFFFFF), encoding="ascii")
        return b"out\0\xff", b"err\0\xfe"

    def terminate(self):
        self.events.append("terminate")
        self.terminated = True

    def wait_empty(self):
        self.events.append("empty")

    def close(self):
        self.events.append("close")

    def poll(self):
        return self.returncode

    def kill(self):
        self.events.append("kill-gate")
        self.returncode = 1


def executor(bundle, transport):
    host = WindowsNativeExecutor(
        job_factory=lambda: transport, spawn=transport.spawn, capture_factory=lambda process: process
    )
    host.prepare(bundle, "unit-test transport")
    return host


def test_gate_assignment_precedes_target_release_and_binary_transport(bundle):
    transport = Transport()
    host = executor(bundle, transport)
    result = host.run(ExecutionRequest("probe", ("a b", 'quoted"value', ""), b"\0\xff", {"BTRC_PROBE": "space value"}))
    assert transport.events[:4] == ["spawn", "assign", "release", "communicate"]
    assert transport.events[-2:] == ["empty", "close"]
    assert transport.input == b"\0\xff"
    assert transport.spec["command"] == [str(bundle / "probe.exe"), "a b", 'quoted"value', ""]
    assert transport.spec["env"]["BTRC_PROBE"] == "space value"
    assert result.stdout == b"out\0\xff" and result.stderr == b"err\0\xfe"
    assert not Path(transport.spec["cwd"]).exists()
    assert result.exit_status == 0


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


def test_gate_launch_failure_is_infrastructure_error_not_program_exit(bundle):
    transport = Transport(status=1, gate_failure=True)
    with pytest.raises(RuntimeError, match="gate failed"):
        executor(bundle, transport).run(ExecutionRequest("probe"))
    assert transport.events[-1] == "close"


@pytest.mark.parametrize(
    "execution_request",
    [
        ExecutionRequest("probe", timeout_s=0),
        ExecutionRequest("probe", timeout_s=float("nan")),
        ExecutionRequest("probe", timeout_s=float("inf")),
        ExecutionRequest("probe", cwd_policy="repo"),
        ExecutionRequest("probe", argv=("bad\0argument",)),
        ExecutionRequest("probe", env={"A=B": "x"}),
    ],
)
def test_invalid_request_never_spawns(bundle, execution_request):
    transport = Transport()
    with pytest.raises(ValueError):
        executor(bundle, transport).run(execution_request)
    assert transport.events == []


@pytest.mark.parametrize(
    "change", ["digest", "architecture", "target-label", "unknown-target", "program-machine", "escape", "schema"]
)
def test_bundle_admission_rejects_corruption_and_path_escape(bundle, change):
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if change == "digest":
        (bundle / "probe.exe").write_bytes((bundle / "probe.exe").read_bytes() + b"corrupted")
    elif change == "architecture":
        manifest["pe_machine"] = 0xAA64
    elif change == "target-label":
        manifest["target"] = "windows-aarch64"
    elif change == "unknown-target":
        manifest["target"] = "windows-unknown"
    elif change == "program-machine":
        manifest["programs"]["probe"]["pe_machine"] = 0xAA64
    elif change == "escape":
        manifest["programs"]["probe"]["executable"] = "../outside.exe"
        (bundle.parent / "outside.exe").write_bytes((bundle / "probe.exe").read_bytes())
    else:
        manifest["schema"] = "unknown"
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        executor(bundle, Transport())


@pytest.mark.parametrize("data", [b"", b"MZ" + b"\0" * 126, b"MZ" + b"\xff" * 126])
def test_pe_parser_rejects_truncated_and_malformed_images(tmp_path, data):
    path = tmp_path / "bad.exe"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        pe_machine(path)


def test_ctypes_layout_uses_windows_fixed_width_dwords():
    assert ctypes.sizeof(Accounting) == 48
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
        self.ready = Path(self.spec["cwd"]) / "ready.json"
        script = """
import json, pathlib, subprocess, sys, time
spec = json.loads(pathlib.Path(sys.argv[1]).read_text())
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
ready = pathlib.Path(sys.argv[2])
ready.with_suffix('.tmp').write_text(str(child.pid))
ready.with_suffix('.tmp').replace(ready)
print('real output', flush=True)
if sys.argv[3] == 'normal':
    status = pathlib.Path(spec['status'])
    status.with_suffix('.tmp').write_text('0')
    status.with_suffix('.tmp').replace(status)
else:
    time.sleep(60)
"""
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                script,
                command[-1],
                str(self.ready),
                "error" if self.fail_communication else "normal",
            ],
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
    host.prepare(bundle, "unit-test clock")
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
            Path(self.spec["launch_error"]).write_text(
                json.dumps(
                    {
                        "stage": "CreateProcessW",
                        "winerror": 193,
                        "errno": 8,
                        "message": "not a valid Win32 application",
                    }
                ),
                encoding="utf-8",
            )
            return super().communicate(data, timeout)

    with pytest.raises(RuntimeError, match="CreateProcessW: winerror=193 errno=8: not a valid Win32 application"):
        executor(bundle, LaunchFailure(gate_failure=True)).run(ExecutionRequest("probe"))


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
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, timeout=10)
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
    manifest["target"] = "windows-x86_64"
    if truncated:
        manifest["cases"] = []
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    report = tmp_path.parent / (tmp_path.name + "-report.json")

    class FailedExecutor:
        def prepare(self, *args):
            pass

        def run(self, *args):
            raise OSError("target launch rejected")

        def close(self):
            pass

    monkeypatch.setattr(check_module, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(check_module, "WindowsNativeExecutor", FailedExecutor)
    with pytest.raises((ValueError, RuntimeError)):
        check_module.check(tmp_path, report, "portable checker test")
    outcome = json.loads(report.read_text())
    assert outcome["passed"] == 0 and outcome["failed"] == (1 if truncated else 16) and not outcome["complete"]
    assert len(outcome["results"]) == (0 if truncated else 16)
    if not truncated:
        assert outcome["results"][0]["error"] == "OSError: target launch rejected"


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


def test_failed_prepare_keeps_only_previous_verified_bundle(bundle, tmp_path):
    host = executor(bundle, Transport())
    rejected = tmp_path / "rejected"
    rejected.mkdir()
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["programs"]["probe"]["sha256"] = "0" * 64
    (rejected / "probe.exe").write_bytes((bundle / "probe.exe").read_bytes())
    (rejected / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        host.prepare(rejected, "must not become provenance")
    assert host.bundle == bundle and host.provenance["label"] == "unit-test transport"
    assert host.run(ExecutionRequest("probe")).exit_status == 0
    fresh = WindowsNativeExecutor()
    with pytest.raises(ValueError):
        fresh.prepare(rejected, "rejected")
    with pytest.raises(RuntimeError, match="prepare a bundle"):
        fresh.run(ExecutionRequest("probe"))


def test_image_changed_after_prepare_never_spawns(bundle):
    transport = Transport()
    host = executor(bundle, transport)
    image = bytearray((bundle / "probe.exe").read_bytes())
    image[-1] ^= 1  # Same length and still a valid PE; only the digest detects it.
    (bundle / "probe.exe").write_bytes(image)
    with pytest.raises(ValueError, match="digest changed"):
        host.run(ExecutionRequest("probe"))
    assert "spawn" not in transport.events


@pytest.mark.parametrize("filename", ["probe.cmd", "probe.bat", "other.exe"])
def test_executable_mapping_and_extension_cannot_select_another_launcher(bundle, filename):
    (bundle / filename).write_bytes((bundle / "probe.exe").read_bytes())
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["programs"]["probe"]["executable"] = filename
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="exact program name"):
        executor(bundle, Transport())


def test_target_cwd_cannot_forge_control_files_or_read_host_environment(bundle, monkeypatch):
    class CwdForger(Transport):
        def spawn(self, command, **kwargs):
            result = super().spawn(command, **kwargs)
            cwd = Path(self.spec["cwd"])
            assert set(cwd.iterdir()) == set()
            assert Path(command[-1]).parent != cwd
            assert Path(self.spec["status"]).parent != cwd
            assert "PRIVATE_HOST_VALUE" not in self.spec["env"]
            for filename in ("status.txt", "launch-error.json", "request.json", "stdin.bin"):
                (cwd / filename).write_text("forged")
            return result

    monkeypatch.setenv("PRIVATE_HOST_VALUE", "not serialized")
    result = executor(bundle, CwdForger()).run(ExecutionRequest("probe"))
    assert result.exit_status == 0 and not result.timed_out


def test_windows_environment_override_replaces_different_case():
    assert merged_environment({"Path": "host", "Temp": "temp"}, {"PATH": "target", "tEmP": "new"}) == {
        "PATH": "target",
        "TEMP": "new",
    }


def test_temporary_cleanup_failure_retains_finished_result(bundle, monkeypatch):
    real = executor_module.shutil.rmtree
    retained = []

    def fail(path):
        retained.append(path)
        raise PermissionError("busy directory")

    monkeypatch.setattr(executor_module.shutil, "rmtree", fail)
    try:
        result = executor(bundle, Transport()).run(ExecutionRequest("probe"))
        assert result.exit_status == 0
        assert "busy directory" in result.provenance["cleanup_warnings"][0]
    finally:
        for path in retained:
            real(path)


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


def test_case_admission_recomputes_goldens_and_checks_checkout_revision(tmp_path):
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
            data = bytearray(128)
            data[:2] = b"MZ"
            struct.pack_into("<I", data, 0x3C, 64)
            data[64:68] = b"PE\0\0"
            struct.pack_into("<H", data, 68, machine)
            Path(command[command.index("-o") + 1]).write_bytes(data)
        elif stdout is not None:
            stdout.write(b"/* stub C */")
        else:
            Path(command[command.index("-o") + 1]).write_text("/* stub C */")

    monkeypatch.setattr(bundle_module, "run_build_command", run)
    manifest = bundle_module.build(tmp_path / "output", target, compiler, root=root)
    assert len(validate_cases(manifest, root=root)) == 16
    assert manifest["cases"][-1]["expected_stdout_sha256"] == digest(b"line one\nline two\n")
    assert len(manifest["programs"]) == 6


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
status=child.wait()
pathlib.Path(spec['status']).write_text(str(status))
sys.exit(status)
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
    manifest["target"] = "windows-x86_64"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
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
        check_module.check(tmp_path, report, "portable mixed failures")
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
    manifest["target"] = "windows-x86_64"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
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
        check_module.check(tmp_path, report, "interrupted")
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
    host.prepare(bundle, "real portable pipes with production capture")
    result = host.run(ExecutionRequest("probe", timeout_s=2))
    assert result.timed_out == timeout
    assert result.stdout == b"real output\n"
    assert result.exit_status == (None if timeout else 0)
    assert transport.process.stdout.closed and transport.process.stderr.closed
    assert_process_dead(transport.child_pid)
