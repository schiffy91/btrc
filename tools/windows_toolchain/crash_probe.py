"""Bounded crash-location diagnostics for a child tool on 64-bit Windows.

Run this entry point as a separate process through process_runner's Windows Job.
The debug session follows only its newly launched child and descendants. It
records exception addresses and module paths, not a memory dump, and keeps the
default kill-on-debugger-exit policy. It does not configure postmortem debugging.

ABI and handle ownership:
https://learn.microsoft.com/windows/win32/api/minwinbase/ns-minwinbase-debug_event
https://learn.microsoft.com/windows/win32/api/debugapi/nf-debugapi-continuedebugevent
"""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import ClassVar

DWORD = ctypes.c_uint32
HANDLE = ctypes.c_void_p


class ExceptionRecord(ctypes.Structure):
    _fields_ = [
        ("code", DWORD),
        ("flags", DWORD),
        ("record", HANDLE),
        ("address", HANDLE),
        ("parameter_count", DWORD),
        ("parameters", ctypes.c_size_t * 15),
    ]


class ExceptionInfo(ctypes.Structure):
    _fields_ = [("record", ExceptionRecord), ("first_chance", DWORD)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [
        ("file", HANDLE),
        ("process", HANDLE),
        ("thread", HANDLE),
        ("base", HANDLE),
        ("debug_offset", DWORD),
        ("debug_size", DWORD),
        ("tls", HANDLE),
        ("start", HANDLE),
        ("name", HANDLE),
        ("unicode", ctypes.c_uint16),
    ]


class DllInfo(ctypes.Structure):
    _fields_ = [
        ("file", HANDLE),
        ("base", HANDLE),
        ("debug_offset", DWORD),
        ("debug_size", DWORD),
        ("name", HANDLE),
        ("unicode", ctypes.c_uint16),
    ]


class EventData(ctypes.Union):
    _fields_: ClassVar = [
        ("exception", ExceptionInfo),
        ("process", ProcessInfo),
        ("dll", DllInfo),
        ("exit_code", DWORD),
        ("unload_base", HANDLE),
    ]


class DebugEvent(ctypes.Structure):
    _fields_ = [("code", DWORD), ("pid", DWORD), ("tid", DWORD), ("data", EventData)]


class WindowsCrashProbe:
    """Own one child debug session; ordinary crashes remain unhandled."""

    CONTINUE = 0x00010002
    NOT_HANDLED = 0x80010001

    def __init__(self, *, kernel=None, clock=time.monotonic):
        if ctypes.sizeof(HANDLE) != 8:
            raise RuntimeError("crash-location diagnostics require a 64-bit process")
        self.kernel = kernel if kernel is not None else self.native_api()
        self.clock = clock
        self.active = set()
        self.initial_breakpoints = set()
        self.modules = {}
        self.report = {
            "schema": "btrc.windows-crash-location/1",
            "scope": "diagnostic-only",
            "exceptions": [],
            "exits": [],
        }

    @staticmethod
    def native_api():
        if sys.platform != "win32":
            raise RuntimeError("crash-location diagnostics require Windows")
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "WaitForDebugEvent": ([ctypes.POINTER(DebugEvent), DWORD], ctypes.c_int),
            "ContinueDebugEvent": ([DWORD, DWORD, DWORD], ctypes.c_int),
            "DebugSetProcessKillOnExit": ([ctypes.c_int], ctypes.c_int),
            "GetFinalPathNameByHandleW": ([HANDLE, ctypes.POINTER(ctypes.c_wchar), DWORD, DWORD], DWORD),
            "CloseHandle": ([HANDLE], ctypes.c_int),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(api, name)
            function.argtypes, function.restype = arguments, result
        return api

    def module(self, handle, base):
        row = {"base": hex(base or 0), "path": None}
        if not handle:
            return row
        try:
            path = ctypes.create_unicode_buffer(32768)
            length = self.kernel.GetFinalPathNameByHandleW(handle, path, len(path), 0)
            if 0 < length < len(path):
                row["path"] = path.value
        finally:
            # CREATE_PROCESS/LOAD_DLL file handles belong to the debugger.
            # ContinueDebugEvent closes debug process/thread handles at exit.
            if not self.kernel.CloseHandle(handle):
                raise RuntimeError("could not close debugger image-file handle")
        return row

    def observe(self, event):
        pid = event.pid
        if event.code == 3:  # CREATE_PROCESS_DEBUG_EVENT
            self.active.add(pid)
            self.initial_breakpoints.add(pid)
            info = event.data.process
            self.modules[pid] = {info.base: self.module(info.file, info.base)}
        elif event.code == 6:  # LOAD_DLL_DEBUG_EVENT
            info = event.data.dll
            self.modules.setdefault(pid, {})[info.base] = self.module(info.file, info.base)
        elif event.code == 7:  # UNLOAD_DLL_DEBUG_EVENT
            self.modules.get(pid, {}).pop(event.data.unload_base, None)
        elif event.code == 1:  # EXCEPTION_DEBUG_EVENT
            info = event.data.exception
            if info.first_chance and info.record.code == 0x80000003 and pid in self.initial_breakpoints:
                self.initial_breakpoints.remove(pid)
                return self.CONTINUE
            if not info.first_chance:
                self.report["exceptions"].append(
                    {
                        "pid": pid,
                        "tid": event.tid,
                        "code": hex(info.record.code),
                        "address": hex(info.record.address or 0),
                        "first_chance": False,
                        "parameters": [
                            hex(value) for value in info.record.parameters[: min(info.record.parameter_count, 15)]
                        ],
                        "modules": list(self.modules.get(pid, {}).values()),
                    }
                )
            return self.NOT_HANDLED
        elif event.code == 5:  # EXIT_PROCESS_DEBUG_EVENT
            self.active.discard(pid)
            self.initial_breakpoints.discard(pid)
            self.modules.pop(pid, None)
            self.report["exits"].append({"pid": pid, "code": event.data.exit_code})
        return self.CONTINUE

    def run(self, command, timeout):
        deadline = self.clock() + timeout
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, creationflags=0x00000001)  # DEBUG_PROCESS
        self.report["root_pid"] = process.pid
        if not self.kernel.DebugSetProcessKillOnExit(True):
            raise RuntimeError("could not retain kill-on-debugger-exit policy")
        root_exited = False
        while not root_exited or self.active:
            if self.clock() >= deadline:
                raise TimeoutError("crash-location diagnostic deadline expired")
            event = DebugEvent()
            if not self.kernel.WaitForDebugEvent(ctypes.byref(event), 100):
                error = ctypes.get_last_error()
                if error == 121:  # ERROR_SEM_TIMEOUT
                    continue
                raise OSError(error, "WaitForDebugEvent failed")
            continuation = self.NOT_HANDLED if event.code == 1 else self.CONTINUE
            try:
                continuation = self.observe(event)
                root_exited |= event.code == 5 and event.pid == process.pid
            finally:
                if not self.kernel.ContinueDebugEvent(event.pid, event.tid, continuation):
                    raise RuntimeError("ContinueDebugEvent failed")
        self.report["root_exit_code"] = process.wait(timeout=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command.pop(0)
    if not args.command or not 0 < args.timeout <= 60:
        parser.error("a command and a timeout of at most 60 seconds are required")
    probe = WindowsCrashProbe()
    try:
        probe.run(args.command, args.timeout)
    except Exception as error:
        probe.report["error"] = str(error)
        return 1
    finally:
        args.output.write_text(json.dumps(probe.report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
