"""Qualify the ios-simulator executor with hand-written C11 fixtures (CX-P1-04).

``build`` compiles the twelve fixtures of ``fixtures/fixture.c`` for the
simulator triple with Xcode's clang into a ``btrc.target-bundle/1`` bundle;
``run`` executes each through `IOSSimulatorExecutor` on one device class and
checks its bytes and outcome: stdout and stderr, exit 3, SIGABRT, a deadline
that needs SIGKILL, a 1 MiB stream, argv, environment, both cwd policies,
binary stdin, and the ordinary exits 124 and 137, which are not timeouts.
Simulator evidence is never physical-device evidence (D8).

    python3 -m tools.target_hosts.ios.spike build build/ios-testhost
    python3 -m tools.target_hosts.ios.spike run build/ios-testhost build/ios-results --device-class iphone
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar

from tools.target_hosts.ios.executor import (
    BUNDLE_MANIFEST,
    BUNDLE_SCHEMA,
    ExecutionRequest,
    IOSSimulatorExecutor,
    XcodeSupervisorBuilder,
    digest,
)
from tools.target_hosts.ios.simhost import AppleEnvironment, IOSSimulatorHost, SimulatorError


class SimulatorSpike:
    cases = (
        "stdout",
        "stderr",
        "exit3",
        "abort",
        "timeout",
        "large",
        "argv",
        "env",
        "cwd",
        "stdin",
        "exit124",
        "exit137",
    )
    # Invocations beyond one per fixture: the cwd fixture again, from the staged program's directory.
    extra: ClassVar[Mapping[str, str]] = MappingProxyType({"cwd-bundle": "cwd"})
    target = "ios-aarch64-simulator"
    triple = "arm64-apple-ios17.0.0-simulator"
    root = Path(__file__).resolve().parent
    flags = XcodeSupervisorBuilder.FLAGS

    @classmethod
    def build(cls, output: Path, *, local_cc: str | None = None) -> None:
        """Compile every fixture into `output`, with Xcode's clang, or `local_cc` for the portable tests."""

        output.mkdir(parents=True, exist_ok=True)
        if local_cc:
            compiler = [local_cc]
        else:
            compiler = [str(AppleEnvironment.XCRUN), "--sdk", "iphonesimulator", "clang", f"--target={cls.triple}"]
        programs: dict[str, Any] = {}
        for mode, name in enumerate(cls.cases, 1):
            executable = output / name
            subprocess.run(
                [
                    *compiler,
                    *cls.flags,
                    f"-DFIXTURE_MODE={mode}",
                    str(cls.root / "fixtures/fixture.c"),
                    "-o",
                    str(executable),
                ],
                check=True,
                timeout=120,
                env=AppleEnvironment.variables(),
            )
            programs[name] = {
                "source": f"tools/target_hosts/ios/fixtures/fixture.c#{mode}",
                "frontend": "c",
                "status": "built",
                "artifact": name,
                "sha256": digest(executable.read_bytes()),
            }
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "protocol": 1,
            "target": {"label": cls.target, "triple": cls.triple, "operating_system": "ios", "architecture": "aarch64"},
            "toolchain": {"cc": compiler, "cflags": list(cls.flags)},
            "programs": programs,
        }
        (output / BUNDLE_MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def request(cls, invocation: str) -> ExecutionRequest:
        name = cls.extra.get(invocation, invocation)
        return ExecutionRequest(
            name,
            argv=("one argument", "é𝄞", "--literal") if name == "argv" else (),
            stdin=b"binary\x00input\n\xff" if name == "stdin" else b"",
            env={"BTRC_FIXTURE_VALUE": "value with spaces é𝄞"} if name == "env" else {},
            timeout_s=0.5 if name == "timeout" else 15,
            cwd_policy="bundle" if invocation == "cwd-bundle" else "isolated",
        )

    @classmethod
    def check(cls, invocation: str, result) -> None:
        """Raise unless `result` is exactly what the fixture does; active under ``python -O`` too."""

        name = cls.extra.get(invocation, invocation)
        expected_stdout = {
            "stdout": b"stdout\n",
            "large": b"x" * 1048576,
            "argv": "one argument\né𝄞\n--literal\n".encode(),
            "env": "value with spaces é𝄞\n".encode(),
            "stdin": b"binary\x00input\n\xff",
        }.get(name, b"")
        if name == "cwd":
            directory = b"/programs" if invocation == "cwd-bundle" else b"/work"
            if not result.stdout.rstrip(b"\n").endswith(directory):
                raise SimulatorError(f"{invocation}: cwd mismatch: {result.stdout!r}")
        elif result.stdout != expected_stdout:
            raise SimulatorError(f"{invocation}: stdout mismatch: {result.stdout[:200]!r}")
        if result.stderr != (b"stderr\n" if name == "stderr" else b""):
            raise SimulatorError(f"{invocation}: stderr mismatch: {result.stderr[:200]!r}")
        if name == "timeout":
            if not result.timed_out or result.exit_status is not None:
                raise SimulatorError(f"timeout: expected the executor's deadline, got {result!r}")
        elif name == "abort":
            if result.timed_out or result.exit_status is not None or result.signal != 6:
                raise SimulatorError(f"abort: expected SIGABRT rather than an ordinary exit, got {result!r}")
        elif (
            result.timed_out
            or result.signal is not None
            or result.exit_status != {"exit3": 3, "exit124": 124, "exit137": 137}.get(name, 0)
        ):
            raise SimulatorError(f"{invocation}: exit status mismatch: {result!r}")

    @staticmethod
    def write_result(result, output: Path) -> None:
        output.mkdir(parents=True, exist_ok=True)
        (output / "stdout").write_bytes(result.stdout)
        (output / "stderr").write_bytes(result.stderr)
        metadata = {
            "exit_status": result.exit_status,
            "signal": result.signal,
            "timed_out": result.timed_out,
            "duration_s": result.duration_s,
            "provenance": result.provenance,
        }
        (output / "result.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    @classmethod
    def run(cls, bundle: Path, output: Path, *, device_class: str, executor=None) -> None:
        executor = executor or IOSSimulatorExecutor(
            device_class=device_class, diagnostics=output / device_class / "host-diagnostics"
        )
        invocations = (*cls.cases, *cls.extra)
        reports = []
        primary: BaseException | None = None
        stage, invocation = "prepare", None
        try:
            executor.prepare(bundle, cls.target)
            for invocation in invocations:
                stage = "execute"
                result = executor.run(cls.request(invocation))
                stage = "record"
                cls.write_result(result, output / device_class / invocation)
                stage = "validate"
                cls.check(invocation, result)
                reports.append({"fixture": invocation, "passed": True, "provenance": result.provenance})
        except BaseException as error:
            primary = error
            raise
        finally:
            cleanup: BaseException | None = None
            try:
                executor.close()
            except Exception as error:
                cleanup = error
                if primary is not None:
                    primary.add_note(f"closing the simulator also failed: {error!r}")
            output.mkdir(parents=True, exist_ok=True)
            summary = {
                "device_class": device_class,
                "results": reports,
                "complete": len(reports) == len(invocations) and cleanup is None,
                "error": repr(primary) if primary is not None else None,
                "error_notes": getattr(primary, "__notes__", []),
                "failed_stage": stage if primary is not None else None,
                "failed_invocation": invocation if primary is not None else None,
                "cleanup_error": repr(cleanup) if cleanup is not None else None,
            }
            (output / f"{device_class}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            if cleanup is not None and primary is None:
                raise cleanup

    @classmethod
    def main(cls, argv=None) -> None:
        parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
        commands = parser.add_subparsers(dest="command", required=True)
        build = commands.add_parser("build")
        build.add_argument("output", type=Path)
        run = commands.add_parser("run")
        run.add_argument("bundle", type=Path)
        run.add_argument("output", type=Path)
        run.add_argument("--device-class", choices=sorted(IOSSimulatorHost.FAMILIES), required=True)
        arguments = parser.parse_args(argv)
        if arguments.command == "build":
            cls.build(arguments.output)
        else:
            cls.run(arguments.bundle, arguments.output, device_class=arguments.device_class)


if __name__ == "__main__":
    SimulatorSpike.main()
