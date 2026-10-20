"""Manual USER-census comparison; original NativeShell assertions remain the gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


class UserCensusDiagnostic:
    DRIVER = "src/tests/python/test_native_ui_shell_windows.py"
    BUILD = (
        f"{DRIVER}::test_windows_native_shell_builds[python-windows-x64-plain]",
        f"{DRIVER}::test_windows_native_shell_builds[python-windows-x64-ubsan]",
    )
    RUN = f"{DRIVER}::test_windows_native_shell_runs[python-windows-x64-ubsan]"
    MODES = ("count-only", "query-bracket")

    def __init__(self, stage: str, output: Path):
        self.stage = stage
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.evidence = Path("build/user-census-executables").resolve()
        self.records: list[dict] = []

    @staticmethod
    def exact_collection(text: str, expected: tuple[str, ...]) -> None:
        nodes = tuple(line.strip() for line in text.splitlines() if line.startswith(UserCensusDiagnostic.DRIVER + "::"))
        if nodes != expected:
            raise ValueError(f"Unexpected collection: {nodes!r}, expected {expected!r}")

    @staticmethod
    def junit_passed(path: Path, expected: int) -> bool:
        try:
            cases = ET.parse(path).getroot().findall(".//testcase")
        except ET.ParseError:
            return False
        return len(cases) == expected and all(
            not any(case.find(tag) is not None for tag in ("failure", "error", "skipped")) for case in cases
        )

    @staticmethod
    def hashes(directory: Path) -> dict[str, str]:
        return {
            path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        }

    def command(self, name: str, args: list[str], environment: dict[str, str]) -> int:
        log = self.output / f"{name}.log"
        record = {"name": name, "argv": args, "started_ns": time.time_ns(), "log": str(log)}
        with log.open("wb") as stream:
            process = subprocess.Popen(args, env=environment, stdout=stream, stderr=subprocess.STDOUT)
            record["pid"] = process.pid
            self.records.append(record)
            self.save()
            # Existing pytest/native process limits apply; the workflow bounds the job.
            record["returncode"] = process.wait()
        record["ended_ns"] = time.time_ns()
        self.save()
        print(f"{name}: exit {record['returncode']}; {log}", flush=True)
        return record["returncode"]

    def save(self) -> None:
        (self.output / "commands.json").write_text(json.dumps(self.records, indent=2) + "\n")

    def run(self) -> int:
        environment = dict(os.environ)
        environment.pop("PYTEST_ADDOPTS", None)
        environment.pop("BTRC_UI_SHELL_USER_DIAGNOSTIC", None)
        environment["BTRC_UI_SHELL_CYCLES"] = "100"
        environment["BTRC_WIN32_EVIDENCE_DIR"] = str(self.evidence)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        (self.output / "provenance.json").write_text(
            json.dumps(
                {
                    "head": head,
                    "platform": platform.platform(),
                    "python": sys.version,
                    "stage": self.stage,
                    "cycles": 102,
                    "measured_cycles": 100,
                    "restores": 100,
                },
                indent=2,
            )
            + "\n"
        )
        nodes = self.BUILD if self.stage == "build" else (self.RUN,)
        base = [sys.executable, "-m", "pytest", "-q", "-n", "0"]
        if self.command("collection", [*base, "--collect-only", *nodes], environment):
            return 1
        self.exact_collection((self.output / "collection.log").read_text(errors="replace"), nodes)
        manifest = self.evidence / "sha256.json"
        if self.stage == "run":
            expected = json.loads(manifest.read_text())
            actual = self.hashes(self.evidence)
            actual.pop("sha256.json", None)
            if actual != expected:
                raise ValueError("Downloaded diagnostic binary hashes differ from builder receipt")
            (self.output / "binary-sha256.json").write_text(json.dumps(actual, indent=2) + "\n")
        failed = False
        for mode in ("build",) if self.stage == "build" else self.MODES:
            env = dict(environment)
            if mode != "build":
                env["BTRC_UI_SHELL_USER_DIAGNOSTIC"] = mode
            junit = self.output / f"{mode}.xml"
            code = self.command(
                mode, [*base, *nodes, f"--junitxml={junit}", f"--basetemp={self.output / (mode + '-tmp')}"], env
            )
            passed = junit.is_file() and self.junit_passed(junit, len(nodes))
            failed |= code != 0 or not passed
        if self.stage == "build" and not failed:
            hashes = self.hashes(self.evidence)
            hashes.pop("sha256.json", None)
            manifest.write_text(json.dumps(hashes, indent=2) + "\n")
        return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("build", "run"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return UserCensusDiagnostic(args.stage, args.output).run()


if __name__ == "__main__":
    raise SystemExit(main())
