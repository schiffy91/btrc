"""Build and run the hand-written simulator fixtures; never claim Linux as iOS."""

from __future__ import annotations

import argparse
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

from tools.target_hosts.ios.executor import ExecutionRequest, IOSSimulatorExecutor
from tools.target_hosts.ios.simhost import SimulatorError


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
    target = "ios-aarch64-simulator"
    root = Path(__file__).resolve().parent
    flags = ("-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror")

    @classmethod
    def build(cls, output: Path, *, local_cc: str | None = None) -> None:
        output.mkdir(parents=True, exist_ok=True)
        output = output.resolve()
        if local_cc:
            cc = [local_cc]
        else:
            cc = ["xcrun", "--sdk", "iphonesimulator", "clang", "-target", "arm64-apple-ios17.0-simulator"]
        template = plistlib.loads((cls.root / "app/Info.plist").read_bytes())
        if template["UIDeviceFamily"] != [1, 2] or template["MinimumOSVersion"] != "17.0":
            raise ValueError("Test host must declare iPhone, iPad and the iOS 17 floor")
        host_object = output / "host_main.o"
        subprocess.run(
            [*cc, *cls.flags, "-c", str(cls.root / "app/host_main.c"), "-o", str(host_object)], check=True, timeout=120
        )
        app_objects = []
        if not local_cc:
            app_host = output / "app_host.o"
            launcher = output / "launcher.o"
            subprocess.run(
                [
                    *cc,
                    *cls.flags,
                    "-Dmain=btrc_fixture_host_main",
                    "-c",
                    str(cls.root / "app/host_main.c"),
                    "-o",
                    str(app_host),
                ],
                check=True,
                timeout=120,
            )
            subprocess.run(
                [
                    *cc,
                    "-fobjc-arc",
                    "-fblocks",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-c",
                    str(cls.root / "app/launcher.m"),
                    "-o",
                    str(launcher),
                ],
                check=True,
                timeout=120,
            )
            app_objects = [str(app_host), str(launcher)]
        programs = {}
        for mode, name in enumerate(cls.cases, 1):
            object_path = output / f"{name}.o"
            executable = output / name
            subprocess.run(
                [
                    *cc,
                    *cls.flags,
                    f"-DFIXTURE_MODE={mode}",
                    "-Dmain=btrc_program_main",
                    "-c",
                    str(cls.root / "fixtures/fixture.c"),
                    "-o",
                    str(object_path),
                ],
                check=True,
                timeout=120,
            )
            subprocess.run(
                [*cc, *cls.flags, str(host_object), str(object_path), "-o", str(executable)], check=True, timeout=120
            )
            app = output / f"{name}.app"
            app.mkdir(exist_ok=True)
            if local_cc:
                shutil.copy2(executable, app / "TestHost")
            else:
                subprocess.run(
                    [
                        *cc,
                        *app_objects,
                        str(object_path),
                        "-framework",
                        "UIKit",
                        "-framework",
                        "Foundation",
                        "-o",
                        str(app / "TestHost"),
                    ],
                    check=True,
                    timeout=120,
                )
            metadata = dict(template, CFBundleIdentifier=f"dev.btrc.testhost.{name}")
            (app / "Info.plist").write_bytes(plistlib.dumps(metadata))
            if not local_cc:
                subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True, timeout=120)
            programs[name] = {"spawn": name, "app": app.name, "bundle_id": metadata["CFBundleIdentifier"]}
        manifest = {
            "schema": "btrc.ios-testhost/1",
            "target": cls.target if not local_cc else "local-host-check-only",
            "programs": programs,
        }
        (output / "programs.json").write_text(json.dumps(manifest, indent=2) + "\n")

    @staticmethod
    def request(name: str) -> ExecutionRequest:
        return ExecutionRequest(
            name,
            argv=("one argument", "é𝄞", "--literal") if name == "argv" else (),
            stdin=b"binary\x00input\n\xff" if name == "stdin" else b"",
            env={"BTRC_FIXTURE_VALUE": "value with spaces é𝄞"} if name == "env" else {},
            timeout_s=0.5 if name == "timeout" else 15,
        )

    @staticmethod
    def check(name: str, result) -> None:
        expected_stdout = {
            "stdout": b"stdout\n",
            "large": b"x" * 1048576,
            "argv": "one argument\né𝄞\n--literal\n".encode(),
            "env": "value with spaces é𝄞\n".encode(),
            "stdin": b"binary\x00input\n\xff",
        }.get(name, b"")
        if name == "cwd":
            if not result.stdout.rstrip().endswith(b"/work"):
                raise SimulatorError(f"{name}: cwd mismatch: {result.stdout!r}")
        elif result.stdout != expected_stdout:
            raise SimulatorError(f"{name}: stdout mismatch")
        if result.stderr != (b"stderr\n" if name == "stderr" else b""):
            raise SimulatorError(f"{name}: stderr mismatch")
        if name == "timeout":
            if not result.timed_out or result.exit_status is not None:
                raise SimulatorError("timeout: expected a verified execution timeout")
        elif name == "abort":
            if result.timed_out or result.exit_status is not None or result.signal != 6:
                raise SimulatorError("abort: expected SIGABRT rather than an ordinary exit")
        elif (
            result.timed_out
            or result.signal is not None
            or result.exit_status != {"exit3": 3, "exit124": 124, "exit137": 137}.get(name, 0)
        ):
            raise SimulatorError(f"{name}: exit status mismatch")
        if result.provenance.get("mode") == "spawn" and not result.timed_out:
            # Record raw simctl output too: the hosted run must prove propagation.
            expected_statuses = (
                {-result.signal, 128 + result.signal} if result.signal is not None else {result.exit_status}
            )
            if result.provenance["simctl_spawn_status"] not in expected_statuses:
                raise SimulatorError(
                    f"{name}: simctl status {result.provenance['simctl_spawn_status']} does not match "
                    f"fixture status {sorted(expected_statuses)}; stderr={result.provenance['simctl_stderr']!r}"
                )
        if result.provenance.get("mode") == "app" and not result.provenance["app_container_marker_absent"]:
            raise SimulatorError(f"{name}: app container freshness was not verified")

    @classmethod
    def run(cls, bundle: Path, output: Path, *, device_class: str, mode: str) -> None:
        executor = IOSSimulatorExecutor(mode=mode, device_class=device_class)
        reports = []
        cases = (*cls.cases, "stdout") if mode == "app" else cls.cases
        primary_error = None
        try:
            executor.prepare(bundle, cls.target)
            for index, name in enumerate(cases):
                result = executor.run(cls.request(name))
                invocation = name if index < len(cls.cases) else f"{name}-repeat"
                executor.write_result(result, output / device_class / mode / invocation)
                cls.check(name, result)
                reports.append(
                    {"fixture": name, "invocation": invocation, "passed": True, "provenance": result.provenance}
                )
        except BaseException as error:
            primary_error = error
            raise
        finally:
            cleanup_error = None
            try:
                executor.close()
            except Exception as error:
                cleanup_error = error
                if primary_error is not None:
                    primary_error.add_note(f"Simulator close also failed: {error!r}")
            output.mkdir(parents=True, exist_ok=True)
            summary = {
                "device_class": device_class,
                "mode": mode,
                "results": reports,
                "complete": len(reports) == len(cases) and cleanup_error is None,
                "error": repr(primary_error) if primary_error is not None else None,
                "cleanup_error": repr(cleanup_error) if cleanup_error is not None else None,
            }
            (output / f"{device_class}-{mode}.json").write_text(json.dumps(summary, indent=2) + "\n")
            if cleanup_error is not None and primary_error is None:
                raise cleanup_error

    @classmethod
    def main(cls) -> None:
        parser = argparse.ArgumentParser(description=__doc__)
        commands = parser.add_subparsers(dest="command", required=True)
        build = commands.add_parser("build")
        build.add_argument("output", type=Path)
        run = commands.add_parser("run")
        run.add_argument("bundle", type=Path)
        run.add_argument("output", type=Path)
        run.add_argument("--device-class", choices=("iphone", "ipad"), required=True)
        run.add_argument("--mode", choices=("spawn", "app"), required=True)
        args = parser.parse_args()
        if args.command == "build":
            cls.build(args.output)
        else:
            cls.run(args.bundle, args.output, device_class=args.device_class, mode=args.mode)


if __name__ == "__main__":
    SimulatorSpike.main()
