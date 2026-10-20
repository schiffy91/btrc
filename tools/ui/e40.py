"""Run a serial E40 qualification cell and retain its exact evidence inventory.

Provider case owners select exact nodes and validate native evidence. macOS
execution requires explicit hosted admission and a new output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class LinuxE40Cases:
    """The complete Linux burst/load denominator for one compiler variant."""

    suite = "src/tests/python/test_native_ui2_fairness_linux.py"

    @classmethod
    def nodes(cls, frontend: str, variant: str) -> list[str]:
        prefix = f"{cls.suite}::"
        parameter = f"{frontend}-{variant}"
        return [
            f"{prefix}test_linux_e40_repeated_bursts[{parameter}-{terminal}-{count}]"
            for terminal in ("keys", "release", "text", "close")
            for count in (4095, 4096, 4097, 8193)
        ] + [f"{prefix}test_linux_e40_sustained_load[{parameter}]"]

    @classmethod
    def validate_evidence(cls, output: Path, metadata: dict[str, object]) -> None:
        expected = {(count, terminal) for count in (4095, 4096, 4097, 8193) for terminal in range(4)}
        found = []
        reports = list((output / "pytest").rglob("e40-bursts.json"))
        loads = list((output / "pytest").rglob("e40-load.json"))
        if len(reports) != 16 or len(loads) != 1:
            raise RuntimeError("E40 evidence requires 16 burst reports and one load report")
        for path in reports + loads:
            report = json.loads(path.read_text())
            if (
                report["frontend"] != metadata["frontend"]
                or report["sanitized"] != (metadata["variant"] == "sanitized")
                or report["backend"] != metadata["session"]
                or report["returncode"] != 0
                or report["revision"] != metadata["revision"]
                or report["source_changes"] != metadata["source_changes"]
            ):
                raise RuntimeError(f"E40 report provenance/outcome differs: {path}")
            for name in ("stdout.txt", "stderr.txt"):
                if not (path.parent / name).is_file():
                    raise RuntimeError(f"Missing E40 native output: {path.parent / name}")
            if path.name == "e40-bursts.json":
                found.append((report["count"], report["terminal"]))
                if report["repetitions"] != 100 or len(report["trials"]) != 100 or len(report["admission"]) != 100:
                    raise RuntimeError(f"Incomplete 100-repetition E40 report: {path}")
            else:
                native = report["native"]
                if (
                    report["requested_seconds"] != 600
                    or report["qualifying"] is not True
                    or len(native) != 1
                    or native[0]["duration_ns"] < 600_000_000_000
                    or native[0]["qualifying"] is not True
                ):
                    raise RuntimeError(f"Incomplete 600-second E40 report: {path}")
                presentation = path.parent / "presentations.csv"
                if not presentation.is_file() or not presentation.stat().st_size:
                    raise RuntimeError(f"Missing E40 presentation evidence: {presentation}")
        if set(found) != expected:
            raise RuntimeError("E40 burst evidence must cover every count/final pair exactly once")


class MacOSE40Cases:
    """Hosted AppKit desktop/attached-host trials for one compiler variant."""

    suite = "src/tests/python/test_native_ui2_macos_e40.py"
    entries = ("desktop", "host")
    trials = ("bursts", "load", "popup", "slider", "resize", "sheet")

    @classmethod
    def nodes(cls, frontend: str, variant: str) -> list[str]:
        return [
            f"{cls.suite}::test_macos_ui2_e40[{variant}-{frontend}-{entry}-{trial}]"
            for entry in cls.entries
            for trial in cls.trials
        ]

    @classmethod
    def all_nodes(cls) -> list[str]:
        return [
            node
            for frontend in ("reference", "selfhost")
            for variant in ("plain", "sanitized")
            for node in cls.nodes(frontend, variant)
        ]

    @staticmethod
    def require_hosted(host: str, environment: dict[str, str]) -> None:
        if host != "darwin" or environment.get("CI") != "true" or environment.get("BTRC_UI2_HOSTED_E40") != "1":
            raise RuntimeError("macOS E40 requires Darwin and explicit hosted CI opt-in")

    @classmethod
    def validate_evidence(cls, output: Path, metadata: dict[str, object]) -> None:
        from src.tests.python.native_ui2_e40_evidence import E40Evidence

        root = output / "native" / str(metadata["frontend"]) / str(metadata["variant"])
        expected = {root / entry / trial / "observations.json" for entry in cls.entries for trial in cls.trials}
        if set((output / "native").rglob("observations.json")) != expected:
            raise RuntimeError("macOS E40 requires exactly 12 distinct native trial reports")
        for entry in cls.entries:
            for trial in cls.trials:
                directory = root / entry / trial
                for name in ("provenance.json", "stdout.txt", "stderr.txt"):
                    if not (directory / name).is_file():
                        raise RuntimeError(f"Missing macOS E40 evidence: {directory / name}")
                identity = json.loads((directory / "provenance.json").read_text())
                if (
                    identity["revision"] != metadata["revision"]
                    or identity["source_changes"] != metadata["source_changes"]
                    or identity["frontend"] != metadata["frontend"]
                    or identity["sanitized"] != (metadata["variant"] == "sanitized")
                ):
                    raise RuntimeError(f"macOS E40 report identity differs: {directory}")
                commands = identity["native_build_commands"]
                if (
                    not isinstance(commands, list)
                    or not commands
                    or not all(
                        isinstance(command, list) and command and all(isinstance(arg, str) for arg in command)
                        for command in commands
                    )
                    or not any("-c" in command for command in commands)
                    or not any("-o" in command and "-c" not in command for command in commands)
                    or identity["native_optimization"] != 2
                    or re.fullmatch(r"[0-9a-f]{64}", identity["executable_sha256"]) is None
                ):
                    raise RuntimeError(f"Incomplete macOS E40 build provenance: {directory}")
                report = json.loads((directory / "observations.json").read_text())
                if report["entry"] != entry or report["trial"] != trial:
                    raise RuntimeError(f"macOS E40 native trial identity differs: {directory}")
                evidence = E40Evidence(report, metadata["variant"] == "sanitized")
                if trial == "bursts":
                    evidence.bursts()
                elif trial == "load":
                    evidence.load()
                else:
                    evidence.tracking(trial)
                if trial != "bursts":
                    evidence.presentations(directory / "observations.json.presentations.csv")


class E40Run:
    """Own collection, one serial test process and its durable evidence record."""

    def __init__(
        self,
        nodes: list[str],
        output: Path,
        metadata: dict[str, object],
        validate_evidence: Callable[[Path, dict[str, object]], None],
        *,
        fresh_output: bool = False,
        environment: dict[str, str] | None = None,
        native_compiler: str = "cc",
        catalog_nodes: list[str] | None = None,
    ):
        self.nodes = nodes
        self.output = output
        self.metadata = metadata
        self.validate_evidence = validate_evidence
        self.fresh_output = fresh_output
        self.environment = dict(os.environ) | (environment or {})
        self.native_compiler = native_compiler
        self.catalog_nodes = catalog_nodes
        self.record: dict[str, object] = {
            "schema": "btrc.e40-run/1",
            **metadata,
            "expected_nodes": nodes,
            "status": "not_started",
            "phases": [],
        }

    @staticmethod
    def digest(path: str | None) -> dict[str, str] | None:
        if not path:
            return None
        source = Path(path)
        if not source.is_file():
            raise RuntimeError(f"Configured evidence input does not exist: {source}")
        return {"path": str(source.resolve()), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}

    @staticmethod
    def command_line(command: list[str]) -> str:
        return subprocess.check_output(command, cwd=ROOT, text=True, timeout=30).strip()

    def save(self) -> None:
        (self.output / "provenance.json").write_text(json.dumps(self.record, indent=2) + "\n")

    def phase(self, name: str, command: list[str]) -> subprocess.CompletedProcess:
        began = time.monotonic()
        self.record["status"] = name
        self.save()
        # Stream pytest progress to the CI log while retaining its full output.
        log = self.output / f"{name}.txt"
        with log.open("w") as stream:
            process = subprocess.Popen(
                command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=self.environment
            )
            assert process.stdout is not None
            for line in process.stdout:
                stream.write(line)
                stream.flush()
                print(line, end="", flush=True)
            returncode = process.wait()
        self.record["phases"].append(
            {"name": name, "command": command, "returncode": returncode, "wall_seconds": time.monotonic() - began}
        )
        self.save()
        if returncode:
            raise RuntimeError(f"E40 {name} exited {returncode}; see {log}")
        return subprocess.CompletedProcess(command, returncode, log.read_text())

    @staticmethod
    def validate_collection(output: str, expected: list[str]) -> None:
        actual = [line.strip() for line in output.splitlines() if re.match(r"^\S+\.py::", line)]
        if len(actual) != len(expected) or set(actual) != set(expected):
            raise RuntimeError(f"E40 collection differs: expected {expected!r}; got {actual!r}")

    @staticmethod
    def validate_junit(path: Path, expected: list[str]) -> None:
        wanted = {
            (source.removesuffix(".py").replace("/", "."), name)
            for source, name in (node.split("::") for node in expected)
        }
        cases = list(ET.parse(path).getroot().iter("testcase"))
        actual = {(case.get("classname"), case.get("name")) for case in cases}
        if len(cases) != len(expected) or actual != wanted:
            raise RuntimeError("E40 JUnit must account for every selected node exactly once")
        if any(case.find(status) is not None for case in cases for status in ("skipped", "failure", "error")):
            raise RuntimeError("E40 qualification requires every selected case to pass without skips")

    def run(self) -> None:
        self.output.mkdir(parents=True, exist_ok=not self.fresh_output)
        cell = str(self.metadata["cell"])
        self.record.update(
            revision=self.command_line(["git", "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"]),
            source_changes=self.command_line(
                ["git", "-c", f"safe.directory={ROOT}", "status", "--porcelain"]
            ).splitlines(),
            platform=platform.platform(),
            machine=platform.machine(),
            runner=os.environ.get("BTRC_TEST_RUNNER", "unconfigured"),
            compiler=self.command_line([self.native_compiler, "--version"]).splitlines()[0],
            native_reader=self.digest(os.environ.get("BTRC_NATIVE_HEADER_READER")),
            selfhost_compiler=self.digest(os.environ.get("BTRC_TEST_BTRCC")),
            display={name: os.environ.get(name) for name in ("SDL_VIDEODRIVER", "DISPLAY", "WAYLAND_DISPLAY")},
            graphics={
                name: os.environ.get(name) for name in ("VK_DRIVER_FILES", "VK_ICD_FILENAMES", "BTRC_LAVAPIPE_ICD")
            },
            physical_device_latency="not measured",
            native_environment={
                name: self.environment.get(name) for name in ("CI", "BTRC_UI2_HOSTED_E40", "BTRC_UI2_E40_ARTIFACTS")
            },
        )
        self.save()
        try:
            if self.catalog_nodes is not None:
                catalog = self.phase(
                    "catalog",
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "--collect-only",
                        "-q",
                        "-n",
                        "0",
                        "-m",
                        "e40_qualification",
                        f"--skip-report=build/skip-report-e40-{cell}-catalog.json",
                        *dict.fromkeys(node.split("::")[0] for node in self.catalog_nodes),
                    ],
                )
                self.validate_collection(catalog.stdout, self.catalog_nodes)
            collection = self.phase(
                "collection",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "--collect-only",
                    "-q",
                    "-n",
                    "0",
                    "-m",
                    "e40_qualification",
                    f"--skip-report=build/skip-report-e40-{cell}-collection.json",
                    *self.nodes,
                ],
            )
            self.validate_collection(collection.stdout, self.nodes)
            junit = self.output / "junit.xml"
            self.phase(
                "qualification",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-vv",
                    "-rs",
                    "-n",
                    "0",
                    "--durations=0",
                    "-m",
                    "e40_qualification",
                    "--junitxml=" + str(junit),
                    "--basetemp=" + str(self.output / "pytest"),
                    f"--skip-report=build/skip-report-e40-{cell}.json",
                    *self.nodes,
                ],
            )
            self.validate_junit(junit, self.nodes)
            self.validate_evidence(self.output, self.record)
            self.record["status"] = "passed"
        except Exception as error:
            self.record["status"] = "failed"
            self.record["error"] = str(error)
            raise
        finally:
            self.record["evidence"] = [
                {"path": str(path.relative_to(self.output)), "bytes": path.stat().st_size}
                for path in sorted(self.output.rglob("*"))
                if path.is_file()
                and path.suffix in {".json", ".csv", ".txt", ".xml"}
                and path != self.output / "provenance.json"
            ]
            self.save()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("linux", "macos"), default="linux")
    parser.add_argument("--frontend", required=True, choices=("python", "reference", "selfhost"))
    parser.add_argument("--variant", required=True, choices=("plain", "sanitized"))
    parser.add_argument("--session", choices=("x11", "wayland"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.provider == "linux":
        if sys.platform != "linux" or args.frontend not in ("python", "selfhost"):
            parser.error("Linux E40 requires Linux and the python or selfhost frontend")
        if args.session is None or os.environ.get("SDL_VIDEODRIVER") != args.session:
            parser.error("Run inside the explicitly selected native display session")
        cases = LinuxE40Cases
    else:
        try:
            MacOSE40Cases.require_hosted(sys.platform, dict(os.environ))
        except RuntimeError as error:
            parser.error(str(error))
        if args.session is not None or args.frontend not in ("reference", "selfhost"):
            parser.error("macOS E40 uses AppKit with the reference or selfhost frontend")
        cases = MacOSE40Cases
    if not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        parser.error("E40 requires an explicit native reader")
    if args.frontend == "selfhost" and not os.environ.get("BTRC_TEST_BTRCC"):
        parser.error("Selfhost E40 requires the compiler built for this revision")
    cell = f"{args.session or args.provider}-{args.frontend}-{args.variant}"
    output = (args.output or ROOT / "build" / "e40" / cell).resolve()
    metadata = {
        "provider": args.provider,
        "cell": cell,
        "session": args.session,
        "frontend": args.frontend,
        "variant": args.variant,
    }
    if args.provider == "linux":
        metadata["linux_observer_flags"] = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2"]
        if args.variant == "sanitized":
            metadata["linux_observer_flags"] += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    run = E40Run(
        cases.nodes(args.frontend, args.variant),
        output,
        metadata,
        cases.validate_evidence,
        fresh_output=args.provider == "macos",
        environment={"BTRC_UI2_E40_ARTIFACTS": str(output / "native")} if args.provider == "macos" else None,
        native_compiler="/usr/bin/clang" if args.provider == "macos" else "cc",
        catalog_nodes=MacOSE40Cases.all_nodes() if args.provider == "macos" else None,
    )
    try:
        run.run()
    except Exception as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
