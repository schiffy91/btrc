"""Run every spike fixture on an explicitly selected emulator and save evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path

from tools.target_hosts.android.avd import AvdManager
from tools.target_hosts.android.executor import AndroidEmulatorExecutor, ExecutionRequest


class HostFixtureCheck:
    def __init__(self, executor):
        self.executor = executor
        self.results = []
        self.current_case = None
        self.failed_result = None

    def run(self):
        rows = self.results
        for mode in self.executor.programs:
            for case in (
                "stdout",
                "stderr",
                "exit3",
                "exit124",
                "exit137",
                "sigkill",
                "abort",
                "timeout",
                "large",
                "argv",
                "env",
                "cwd",
                "cwd",
                "stdin",
            ):
                self.current_case = {"mode": mode, "case": case}
                arguments = (case, "space and ' quote", "", "$(touch should-not-exist)") if case == "argv" else (case,)
                request = ExecutionRequest(
                    mode,
                    arguments,
                    b"input\x00bytes\n",
                    {"BTRC_FIXTURE_VALUE": "fixture value"},
                    1 if case == "timeout" else 15,
                )
                result = self.executor.run(request)
                row = asdict(result)
                for name in ("stdout", "stderr"):
                    data = row.pop(name)
                    row[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                self.failed_result = {"mode": mode, "case": case, **row}
                expected = {
                    "stdout": (b"stdout\n", b""),
                    "stderr": (b"", b"stderr\n"),
                    "exit3": (b"", b""),
                    "exit124": (b"", b""),
                    "exit137": (b"", b""),
                    "large": (b"O" * 262144, b"E" * 262144),
                    "argv": (b"space and ' quote\n\n$(touch should-not-exist)\n", b""),
                    "env": (b"fixture value\n", b""),
                    "cwd": (b"fresh\n", b""),
                    "stdin": (request.stdin, b""),
                }
                if case in expected and (result.stdout, result.stderr) != expected[case]:
                    raise AssertionError(f"{mode}/{case}: stdout or stderr differs from expected bytes")
                if case == "timeout":
                    if not result.timed_out or result.stdout != b"started\n":
                        raise AssertionError(f"{mode}: timeout did not terminate the started fixture")
                elif case == "sigkill":
                    if result.signal != 9 or result.timed_out:
                        raise AssertionError(f"{mode}: SIGKILL was confused with a deadline")
                elif case == "abort":
                    if result.signal != 6 or result.timed_out:
                        raise AssertionError(f"{mode}: abort did not preserve SIGABRT")
                else:
                    if (
                        result.exit_status != {"exit3": 3, "exit124": 124, "exit137": 137}.get(case, 0)
                        or result.timed_out
                    ):
                        raise AssertionError(f"{mode}/{case}: exit status or deadline differs from expected")
                rows.append(self.failed_result)
                self.failed_result = None
        return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", default=os.environ.get("ANDROID_SDK_ROOT"))
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--boot", action="store_true", help="own the emulator lifecycle for this check")
    parser.add_argument("--state", type=Path)
    parser.add_argument("--api", default="29")
    parser.add_argument("--save-snapshot", action="store_true")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.sdk:
        parser.error("--sdk or ANDROID_SDK_ROOT is required")
    if args.boot and args.state is None:
        parser.error("--boot requires --state")
    manager = (
        AvdManager(args.sdk, args.state, api=args.api, port=int(args.serial.removeprefix("emulator-")))
        if args.boot
        else None
    )
    host = None
    executor = AndroidEmulatorExecutor(args.sdk, args.serial)
    checker = HostFixtureCheck(executor)
    failure = None
    stage = "boot"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        if manager:
            manager.create()
            host = manager.boot()
            if args.save_snapshot:
                manager.snapshot()
        stage = "prepare"
        executor.prepare(args.bundle, "CX-P1-05 fixture proof")
        stage = "fixtures"
        checker.run()
        stage = "cleanup"
    except BaseException as error:
        failure = error
    cleanup = ([manager.diagnostics] if failure and manager else []) + [executor.close]
    if manager:
        cleanup.append(manager.close)
    for action in cleanup:
        try:
            action()
        except BaseException as error:
            if failure is None:
                failure = error
            else:
                failure.add_note(f"{action.__qualname__} also failed: {error}")
    report = {
        "schema": "btrc.android-host-spike/1",
        "stand_in": True,
        "host": host,
        "status": "failed" if failure else "passed",
        "results": checker.results,
    }
    if failure:
        report.update(
            error=str(failure),
            notes=getattr(failure, "__notes__", []),
            failure_stage=stage,
            current_case=checker.current_case,
        )
        if checker.failed_result is not None:
            report["failed_result"] = checker.failed_result
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    if failure:
        raise failure
    print(f"{len(checker.results)} fixture executions passed")


if __name__ == "__main__":
    main()
