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

import pytest

from .bundle import digest, pe_machine
from .check import verify
from .executor import Accounting, ExecutionRequest, ExecutionResult, ExtendedLimits, WindowsNativeExecutor


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
    host = WindowsNativeExecutor(job_factory=lambda: transport, spawn=transport.spawn)
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
    assert result.exit_status == 0 and result.provenance["job_empty"]


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
    assert result.provenance["job_empty"] and transport.events[-1] == "close"


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


@pytest.mark.parametrize("change", ["digest", "architecture", "escape", "schema"])
def test_bundle_admission_rejects_corruption_and_path_escape(bundle, change):
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if change == "digest":
        (bundle / "probe.exe").write_bytes((bundle / "probe.exe").read_bytes() + b"corrupted")
    elif change == "architecture":
        manifest["pe_machine"] = 0xAA64
    elif change == "escape":
        manifest["programs"]["probe"]["executable"] = "../outside.exe"
        (bundle.parent / "outside.exe").write_bytes(b"outside")
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
pathlib.Path(sys.argv[2]).write_text(str(child.pid))
print('real output', flush=True)
if sys.argv[3] == 'normal':
    pathlib.Path(spec['status']).write_text('0')
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
    assert transport.child_pid > 0


@pytest.mark.skipif(os.name != "posix", reason="real pipe stand-in uses POSIX groups; native proof is check.py")
def test_infrastructure_error_terminates_real_pipe_holder_and_preserves_original(bundle):
    transport = RealPipeTransport(fail_communication=True, fail_cleanup=True)
    started = time.monotonic()
    with pytest.raises(OSError, match="injected transport failure") as caught:
        executor(bundle, transport).run(ExecutionRequest("probe"))
    assert "injected accounting failure" in caught.value.__notes__[0]
    assert time.monotonic() - started < 2
    assert transport.process.poll() is not None
    assert transport.child_pid > 0
    assert transport.events[-1] == "close"


def test_setup_time_uses_request_deadline_and_stdin_does_not_block_pipe(bundle, monkeypatch):
    transport = Transport()
    clock = iter([0, 2, 2])
    monkeypatch.setattr("tools.target_hosts.windows.executor.time.monotonic", lambda: next(clock))
    result = executor(bundle, transport).run(ExecutionRequest("probe", stdin=b"x" * 300000, timeout_s=1))
    assert result.timed_out
    assert len(transport.input) == 300000
