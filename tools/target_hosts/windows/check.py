"""Execute a Windows bundle natively and retain byte-level protocol evidence."""

from __future__ import annotations

import argparse
import ctypes
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .bundle import METADATA_TIMEOUT_S, ROOT, acceptance_cases, digest
from .executor import ExecutionRequest, WindowsNativeExecutor


def assert_dead(pid):
    """Check each observed tree PID independently of Job Object accounting."""
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    api.OpenProcess.restype = ctypes.c_void_p
    api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    api.WaitForSingleObject.restype = ctypes.c_uint32
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = api.OpenProcess(0x00100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: process no longer exists.
            return
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if api.WaitForSingleObject(handle, 0) != 0:
            raise AssertionError(f"tree process {pid} survived Job Object cleanup")
    finally:
        api.CloseHandle(handle)


def verify(case, result, *, dead_check=assert_dead):
    for field in ("exit_status", "signal", "timed_out"):
        if getattr(result, field) != case[field]:
            raise AssertionError(f"{case['name']}: {field} expected {case[field]!r}, got {getattr(result, field)!r}")
    stdout = result.stdout
    policy = case.get("stdout_policy", "bytes")
    if policy == "tree-pids":
        rows = re.findall(rb"generation=([012]) pid=([0-9]+)\r?\n", stdout)
        if len(rows) != 3 or {row[0] for row in rows} != {b"0", b"1", b"2"} or len({row[1] for row in rows}) != 3:
            raise AssertionError("tree fixture did not start all three distinct generations")
        for _, pid in rows:
            dead_check(int(pid))
    else:
        if policy == "lf":
            stdout = stdout.replace(b"\r\n", b"\n")
        elif policy != "bytes":
            raise ValueError(f"unsupported stdout policy: {policy}")
        if digest(stdout) != case["expected_stdout_sha256"]:
            raise AssertionError(f"{case['name']}: stdout digest mismatch ({result.stdout[:200]!r})")
    if digest(result.stderr) != case["expected_stderr_sha256"]:
        raise AssertionError(f"{case['name']}: stderr digest mismatch ({result.stderr[:200]!r})")


def validate_cases(manifest, *, root=ROOT):
    """Pin the entire fixed-case contract and current checkout golden outputs."""
    expected = {case["name"]: case for case in acceptance_cases(root)}
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not all(
        isinstance(case, dict) and isinstance(case.get("name"), str) for case in cases
    ):
        raise ValueError("Windows acceptance manifest requires the complete named case list")
    names = [case["name"] for case in cases]
    if len(names) != len(set(names)) or set(names) != set(expected):
        raise ValueError("Windows acceptance case set mismatch")
    for case in cases:
        if json.dumps(case, sort_keys=True) != json.dumps(expected[case["name"]], sort_keys=True):
            raise ValueError(f"{case['name']}: acceptance inputs, outcomes or golden digests mismatch")
    programs = {case["program"] for case in cases}
    records = manifest.get("programs", {})
    if set(records) != programs or any(records[name].get("executable") != f"{name}.exe" for name in programs):
        raise ValueError("acceptance executable mapping mismatch")
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, timeout=METADATA_TIMEOUT_S
    ).strip()
    if manifest.get("toolchain", {}).get("source_revision") != revision:
        raise ValueError("bundle must match the native checking checkout revision")
    return cases


def check(bundle, report, label):
    if sys.platform != "win32":
        raise RuntimeError("native Windows is required; Linux mocks are not execution evidence")
    bundle, report = Path(bundle).resolve(), Path(report).resolve()
    rows = []
    outcome = {"results": rows, "complete": False, "passed": 0, "failed": 0, "skipped": 0}
    try:
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        cases = validate_cases(manifest)
        outcome["target"] = manifest["target"]
        outcome["expected"] = len(cases)
        with tempfile.TemporaryDirectory(prefix="btrc bundle λ ") as directory:
            relocated = Path(directory) / "programs with spaces"
            shutil.copytree(bundle, relocated)
            executor = WindowsNativeExecutor()
            try:
                executor.prepare(relocated, label)
                for case in cases:
                    row = {"name": case["name"], "frontend": case.get("frontend", "C fixture"), "passed": False}
                    rows.append(row)
                    try:
                        result = executor.run(
                            ExecutionRequest(
                                case["program"],
                                tuple(case["argv"]),
                                bytes.fromhex(case.get("stdin_hex", "")),
                                case.get("env", {}),
                                case["timeout_s"],
                            )
                        )
                        row.update(
                            {
                                "stdout_sha256": digest(result.stdout),
                                "stderr_sha256": digest(result.stderr),
                                "exit_status": result.exit_status,
                                "signal": result.signal,
                                "timed_out": result.timed_out,
                                "duration_s": result.duration_s,
                                "provenance": result.provenance,
                            }
                        )
                        verify(case, result)
                        row["passed"] = True
                    except Exception as error:
                        row["error"] = f"{type(error).__name__}: {error}"
            finally:
                executor.close()
        if any(not row["passed"] for row in rows):
            raise RuntimeError("one or more native acceptance cases failed; see all collected results")
        outcome["complete"] = True
    except BaseException as error:
        outcome["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        outcome["passed"] = sum(row["passed"] for row in rows)
        outcome["failed"] = sum(not row["passed"] for row in rows) or int("error" in outcome)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps({key: outcome[key] for key in ("passed", "failed", "skipped", "complete")} | {"report": str(report)})
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--label", default="native Windows host spike")
    args = parser.parse_args(argv)
    check(args.bundle, args.report, args.label)


if __name__ == "__main__":
    main()
