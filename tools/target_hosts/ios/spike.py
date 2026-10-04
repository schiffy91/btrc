"""Build and run the hand-written simulator fixtures; never claim Linux as iOS."""

from __future__ import annotations

import argparse
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

from tools.target_hosts.ios.executor import ExecutionRequest, IOSSimulatorExecutor


class SimulatorSpike:
    cases = ("stdout", "stderr", "exit3", "abort", "timeout", "large", "argv", "env", "cwd", "stdin")
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
        subprocess.run([*cc, *cls.flags, "-c", str(cls.root / "app/host_main.c"), "-o", str(host_object)], check=True)
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
            )
            subprocess.run([*cc, *cls.flags, str(host_object), str(object_path), "-o", str(executable)], check=True)
            app = output / f"{name}.app"
            app.mkdir(exist_ok=True)
            shutil.copy2(executable, app / "TestHost")
            metadata = dict(template, CFBundleIdentifier=f"dev.btrc.testhost.{name}")
            (app / "Info.plist").write_bytes(plistlib.dumps(metadata))
            if not local_cc:
                subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
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
            assert result.stdout.rstrip().endswith(b"/work"), result.stdout
        else:
            assert result.stdout == expected_stdout, f"{name}: stdout mismatch"
        assert result.stderr == (b"stderr\n" if name == "stderr" else b""), f"{name}: stderr mismatch"
        if name == "timeout":
            assert result.timed_out and result.exit_status is None
            assert result.provenance["timeout_kill_verified"]
        elif name == "abort":
            assert not result.timed_out and result.exit_status is None and result.signal == 6
        else:
            assert not result.timed_out and result.signal is None
            assert result.exit_status == (3 if name == "exit3" else 0)

    @classmethod
    def run(cls, bundle: Path, output: Path, *, device_class: str, mode: str) -> None:
        executor = IOSSimulatorExecutor(mode=mode, device_class=device_class)
        reports = []
        try:
            executor.prepare(bundle, cls.target)
            for name in cls.cases:
                result = executor.run(cls.request(name))
                executor.write_result(result, output / device_class / mode / name)
                cls.check(name, result)
                reports.append({"fixture": name, "passed": True, "provenance": result.provenance})
        finally:
            executor.close()
            output.mkdir(parents=True, exist_ok=True)
            summary = {
                "device_class": device_class,
                "mode": mode,
                "results": reports,
                "complete": len(reports) == len(cls.cases),
            }
            (output / f"{device_class}-{mode}.json").write_text(json.dumps(summary, indent=2) + "\n")

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
