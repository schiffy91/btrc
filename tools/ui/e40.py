"""Run a serial E40 qualification cell and retain its exact evidence inventory.

Linux currently supplies the case selection. The run/evidence owner accepts an
explicit node list so a later native provider can reuse it with its own cases
and visibility admission. This command does not activate a macOS application.
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


class E40Run:
    """Own collection, one serial test process and its durable evidence record."""

    def __init__(
        self,
        nodes: list[str],
        output: Path,
        metadata: dict[str, object],
        validate_evidence: Callable[[Path, dict[str, object]], None],
    ):
        self.nodes = nodes
        self.output = output
        self.metadata = metadata
        self.validate_evidence = validate_evidence
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
            process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
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
        self.output.mkdir(parents=True, exist_ok=True)
        cell = str(self.metadata["cell"])
        self.record.update(
            revision=self.command_line(["git", "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"]),
            source_changes=self.command_line(
                ["git", "-c", f"safe.directory={ROOT}", "status", "--porcelain"]
            ).splitlines(),
            platform=platform.platform(),
            machine=platform.machine(),
            runner=os.environ.get("BTRC_TEST_RUNNER", "unconfigured"),
            compiler=self.command_line(["cc", "--version"]).splitlines()[0],
            native_reader=self.digest(os.environ.get("BTRC_NATIVE_HEADER_READER")),
            selfhost_compiler=self.digest(os.environ.get("BTRC_TEST_BTRCC")),
            native_flags=["-std=c11", "-pedantic-errors", "-O2"],
            sanitizer_flags=["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            if self.metadata["variant"] == "sanitized"
            else [],
            display={name: os.environ.get(name) for name in ("SDL_VIDEODRIVER", "DISPLAY", "WAYLAND_DISPLAY")},
            graphics={
                name: os.environ.get(name) for name in ("VK_DRIVER_FILES", "VK_ICD_FILENAMES", "BTRC_LAVAPIPE_ICD")
            },
            physical_device_latency="not measured; hosted headless native session",
        )
        self.save()
        try:
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
                {"path": str(path.relative_to(self.output)), "bytes": path.stat().st_size()}
                for path in sorted(self.output.rglob("*"))
                if path.is_file()
                and path.suffix in {".json", ".csv", ".txt", ".xml"}
                and path.name != "provenance.json"
            ]
            self.save()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", required=True, choices=("python", "selfhost"))
    parser.add_argument("--variant", required=True, choices=("plain", "sanitized"))
    parser.add_argument("--session", required=True, choices=("x11", "wayland"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("The Linux E40 cell requires Linux; no native macOS admission is implied")
    if os.environ.get("SDL_VIDEODRIVER") != args.session:
        parser.error("Run inside the explicitly selected native display session")
    if not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        parser.error("E40 requires an explicit native reader")
    if args.frontend == "selfhost" and not os.environ.get("BTRC_TEST_BTRCC"):
        parser.error("Selfhost E40 requires the compiler built for this revision")
    cell = f"{args.session}-{args.frontend}-{args.variant}"
    run = E40Run(
        LinuxE40Cases.nodes(args.frontend, args.variant),
        (args.output or ROOT / "build" / "e40" / cell).resolve(),
        {
            "provider": "linux",
            "cell": cell,
            "session": args.session,
            "frontend": args.frontend,
            "variant": args.variant,
        },
        LinuxE40Cases.validate_evidence,
    )
    try:
        run.run()
    except Exception as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
