"""Debug-event handling without launching or attaching to any host process."""

import ctypes
from types import SimpleNamespace

import pytest

from tools.windows_toolchain import arm64, crash_probe


class FakeKernel:
    def __init__(self):
        self.closed = []
        self.continuations = []
        self.events = []
        self.kill_on_exit = False

    def GetFinalPathNameByHandleW(self, handle, buffer, length, flags):
        buffer.value = f"module-{handle}.dll"
        return len(buffer.value)

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True

    def DebugSetProcessKillOnExit(self, enabled):
        self.kill_on_exit = enabled
        return True

    def WaitForDebugEvent(self, output, timeout):
        event = self.events.pop(0)
        ctypes.memmove(output, ctypes.byref(event), ctypes.sizeof(event))
        return True

    def ContinueDebugEvent(self, pid, tid, status):
        self.continuations.append((pid, tid, status))
        return True


def event(code, pid=17):
    result = crash_probe.DebugEvent()
    result.code, result.pid, result.tid = code, pid, 23
    return result


def exception(code, *, first_chance=True, pid=17):
    result = event(1, pid)
    result.data.exception.first_chance = first_chance
    result.data.exception.record.code = code
    result.data.exception.record.address = 0x12345678
    return result


def test_debug_event_layout_matches_the_64_bit_windows_abi():
    assert ctypes.sizeof(crash_probe.ExceptionRecord) == 152
    assert ctypes.sizeof(crash_probe.ProcessInfo) == 72
    assert ctypes.sizeof(crash_probe.DllInfo) == 40
    assert crash_probe.DebugEvent.data.offset == 16
    assert ctypes.sizeof(crash_probe.DebugEvent) == 176


def test_only_the_initial_breakpoint_is_handled_and_fatal_modules_are_retained():
    kernel = FakeKernel()
    probe = crash_probe.WindowsCrashProbe(kernel=kernel)
    created = event(3)
    created.data.process.file, created.data.process.base = 101, 0x10000000
    probe.observe(created)
    loaded = event(6)
    loaded.data.dll.file, loaded.data.dll.base = 102, 0x12000000
    probe.observe(loaded)
    assert kernel.closed == [101, 102]
    assert probe.observe(exception(0x80000003)) == probe.CONTINUE
    assert probe.observe(exception(0x80000003)) == probe.NOT_HANDLED
    assert probe.observe(exception(0xC0000005)) == probe.NOT_HANDLED
    assert probe.report["exceptions"] == []
    fatal = exception(0xC0000005, first_chance=False)
    fatal.data.exception.record.parameter_count = 2
    fatal.data.exception.record.parameters[:2] = (0, 8)
    assert probe.observe(fatal) == probe.NOT_HANDLED
    row = probe.report["exceptions"][0]
    assert row["code"] == "0xc0000005" and row["address"] == "0x12345678"
    assert row["parameters"] == ["0x0", "0x8"]
    assert [module["path"] for module in row["modules"]] == ["module-101.dll", "module-102.dll"]
    unloaded = event(7)
    unloaded.data.unload_base = 0x12000000
    probe.observe(unloaded)
    assert len(row["modules"]) == 2  # Preserve the snapshot at the exception.
    probe.observe(fatal)
    assert len(probe.report["exceptions"][-1]["modules"]) == 1


def test_missing_image_path_still_closes_its_debugger_file_handle(monkeypatch):
    kernel = FakeKernel()
    monkeypatch.setattr(kernel, "GetFinalPathNameByHandleW", lambda *args: 0)
    probe = crash_probe.WindowsCrashProbe(kernel=kernel)
    assert probe.module(101, 0x1000) == {"base": "0x1000", "path": None}
    assert kernel.closed == [101]


def test_child_debug_session_waits_for_descendants_and_retains_exit_status(monkeypatch):
    kernel = FakeKernel()
    root, child, root_exit, child_exit = event(3), event(3, 18), event(5), event(5, 18)
    root_exit.data.exit_code = child_exit.data.exit_code = 0xC0000005
    kernel.events = [
        root,
        child,
        exception(0x80000003),
        exception(0x80000003, pid=18),
        exception(0xC0000005, first_chance=False, pid=18),
        root_exit,
        child_exit,
    ]
    launched = []

    def launch(command, **kwargs):
        launched.append((command, kwargs))
        return SimpleNamespace(pid=17, wait=lambda timeout: 0xC0000005)

    monkeypatch.setattr(crash_probe.subprocess, "Popen", launch)
    probe = crash_probe.WindowsCrashProbe(kernel=kernel)
    probe.run(["zig", "cc", "minimal.c"], 20)
    assert launched[0][1]["creationflags"] == 1
    assert kernel.kill_on_exit
    assert not kernel.events and not probe.active
    assert probe.report["root_exit_code"] == 0xC0000005
    assert probe.report["exceptions"][0]["pid"] == 18
    assert kernel.continuations[-3][2] == probe.NOT_HANDLED


def test_debug_session_timeout_preserves_kill_on_exit(monkeypatch):
    kernel = FakeKernel()
    monkeypatch.setattr(crash_probe.subprocess, "Popen", lambda *args, **kwargs: SimpleNamespace(pid=17))
    times = iter([0, 21])
    probe = crash_probe.WindowsCrashProbe(kernel=kernel, clock=lambda: next(times))
    with pytest.raises(TimeoutError, match="deadline"):
        probe.run(["zig"], 20)
    assert kernel.kill_on_exit


def test_native_access_violation_requests_a_bounded_diagnostic_without_changing_failure(tmp_path, monkeypatch):
    evidence = arm64.Evidence(tmp_path, "zig")
    evidence.report["steps"].append({"exit_code": 0xC0000005})
    monkeypatch.setattr(arm64.sys, "platform", "win32")
    calls = []

    def run(args, name, *, timeout):
        calls.append((list(map(str, args)), name, timeout))
        if name == "diagnostic-crash-location":
            raise RuntimeError("diagnostic deadline")
        return b""

    monkeypatch.setattr(evidence, "run", run)
    evidence.diagnose_c_frontend(tmp_path / "probe.c")
    command, name, timeout = calls[-1]
    assert name == "diagnostic-crash-location" and timeout == 30
    assert command[1:3] == ["-m", "tools.windows_toolchain.crash_probe"]
    assert command[command.index("--timeout") + 1] == "20"
    assert evidence.report["status"] == "failed" and evidence.report["native_execution"] == "not-run"
    assert evidence.report["c_frontend_diagnostics"]["failures"]["crash-location"] == "diagnostic deadline"
