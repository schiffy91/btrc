"""Windows ARM64 compiler evidence; Linux builds are explicitly not native runs."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import shlex
import sys
import sysconfig
import time
from pathlib import Path

from tools.target_hosts.windows.bundle import TARGETS, compiler_flags, pe_machine
from tools.windows_toolchain.process_runner import run as run_process

ROOT = Path(__file__).resolve().parents[2]
PINS = json.loads(Path(__file__).with_name("pins.json").read_text())
TARGET, MACHINE = TARGETS["windows-aarch64"]
FLAGS = compiler_flags(root=ROOT)


def pe_arm64(path: Path) -> dict[str, str | int]:
    data = path.read_bytes()
    machine = pe_machine(data, optional_magic=0x20B)
    if machine != MACHINE:
        raise ValueError(f"expected ARM64 PE32+, got machine={machine:#x}: {path}")
    return {"path": str(path), "machine": machine, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


class Evidence:
    def __init__(self, output: Path, zig: str):
        self.output, self.zig = output.resolve(), zig
        self.output.mkdir(parents=True, exist_ok=True)
        self.environment = {**os.environ, "BTRC_HOME": str(ROOT / "src")}
        self.deadline = None
        self.report = {
            "status": "failed",
            "host": platform.platform(),
            "host_system": platform.system(),
            "python_platform": sysconfig.get_platform(),
            "native_execution": "not-run",
            "containment": "windows-job" if sys.platform == "win32" else "process-group",
            "steps": [],
        }

    def run(self, args: list[str | Path], name: str, *, timeout: int = 3600) -> bytes:
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - time.monotonic())
            if timeout <= 0:
                raise TimeoutError(f"overall native evidence deadline expired before {name}")
        command = list(map(str, args))
        started = time.monotonic()
        result = run_process(command, cwd=ROOT, env=self.environment, timeout=timeout)
        (self.output / f"{name}.stdout").write_bytes(result.stdout)
        (self.output / f"{name}.stderr").write_bytes(result.stderr)
        self.report["steps"].append(
            {
                "name": name,
                "argv": command,
                "exit_code": result.returncode,
                "timed_out": result.timed_out,
                "timeout_s": timeout,
                "elapsed_s": time.monotonic() - started,
            }
        )
        if result.error:
            raise RuntimeError(f"{name}: {result.error}; partial stdout/stderr retained")
        if result.timed_out:
            raise RuntimeError(f"{name} timed out after {timeout}s; partial stdout/stderr retained")
        if result.returncode:
            raise RuntimeError(f"{name} exited {result.returncode}; see {self.output / (name + '.stderr')}")
        return result.stdout

    def identify(self) -> None:
        self.report["revision"] = self.run(["git", "rev-parse", "HEAD"], "revision", timeout=60).decode().strip()
        version = self.run([self.zig, "version"], "zig-version", timeout=60).decode().strip()
        if version != PINS["zig_version"]:
            raise RuntimeError(f"expected pinned Zig {PINS['zig_version']}, got {version}")
        self.report["zig_version"] = version

    def diagnose_windows_failure(self) -> None:
        """Keep bounded, read-only crash observations without replacing the error."""
        script = """$ErrorActionPreference = 'Stop'
$report = @{schema = 'btrc.windows-host-diagnostics/1'}
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $report.capacity = $os | Select-Object Caption, Version, OSArchitecture,
        TotalVisibleMemorySize, FreePhysicalMemory, TotalVirtualMemorySize, FreeVirtualMemory
} catch { $report.capacity_error = $_.Exception.Message }
try {
    $events = Get-WinEvent -FilterHashtable @{
        LogName = 'Application'; Id = 1000, 1001; StartTime = (Get-Date).AddMinutes(-15)
    } -MaxEvents 50
    $report.crashes = @($events | Where-Object { $_.Message -match 'zig|clang|lld' } |
        Select-Object TimeCreated, Id, ProviderName, Message)
} catch { $report.events_error = $_.Exception.Message }
$report | ConvertTo-Json -Depth 6
"""
        # PowerShell receives one UTF-16LE encoded argument, independent of
        # CreateProcess/CRT quoting of multiline command text.
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        command = ["pwsh", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
        result = run_process(command, cwd=ROOT, env=self.environment, timeout=20)
        (self.output / "host-diagnostics.stdout").write_bytes(result.stdout)
        (self.output / "host-diagnostics.stderr").write_bytes(result.stderr)
        self.report["host_diagnostics"] = {
            "argv": command,
            "exit_code": result.returncode,
            "timed_out": result.timed_out,
            "error": result.error,
            "timeout_s": 20,
        }
        if result.returncode == 0 and not result.timed_out and result.error is None:
            try:
                report = json.loads(result.stdout)
            except (ValueError, UnicodeError) as error:
                raise RuntimeError("host diagnostic did not emit a JSON report") from error
            if not isinstance(report, dict) or report.get("schema") != "btrc.windows-host-diagnostics/1":
                raise RuntimeError("host diagnostic emitted an invalid report")

    def build(self) -> Path:
        source, binary = self.output / "btrcc-windows.c", self.output / "btrcc.exe"
        self.run(
            [
                sys.executable,
                "-m",
                "src.compiler.python.main",
                ROOT / "src/compiler/btrc/cli/WindowsMain.btrc",
                "--no-cache",
                "-o",
                source,
            ],
            "transpile",
        )
        if any(line.startswith(b"warning:") for line in (self.output / "transpile.stderr").read_bytes().splitlines()):
            raise RuntimeError("Windows compiler transpile emitted analyzer warnings")
        self.report["generated_c"] = {
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "bytes": source.stat().st_size,
        }
        self.run([self.zig, "cc", "-v", "-target", TARGET, *FLAGS, source, "-o", binary, "-lm"], "build")
        self.report["compiler"] = pe_arm64(binary)
        return binary

    def probe_native_toolchain(self) -> None:
        """Separate driver/stdio failures from the generated compiler's C input."""
        version = self.run([self.zig, "cc", "--version"], "cc-version", timeout=60)
        if not version.strip():
            raise RuntimeError("C frontend version probe returned no output")
        source, binary = self.output / "toolchain-probe.c", self.output / "toolchain-probe.exe"
        source.write_text(
            "#include <stdio.h>\nint main(void) {\n"
            '    puts("BTRC_TOOLCHAIN_STDOUT");\n'
            '    fputs("BTRC_TOOLCHAIN_STDERR\\n", stderr);\n'
            "    return 0;\n}\n",
            encoding="utf-8",
        )
        try:
            self.run(
                [self.zig, "cc", "-v", "-target", TARGET, *FLAGS, source, "-o", binary, "-lm"],
                "toolchain-probe-build",
                timeout=240,
            )
        except RuntimeError:
            try:
                self.diagnose_c_frontend(source)
            except Exception as error:
                self.report["c_frontend_diagnostics_error"] = str(error)
            raise
        image = pe_arm64(binary)
        stdout = self.run([binary], "toolchain-probe-run", timeout=60)
        stderr = (self.output / "toolchain-probe-run.stderr").read_bytes()
        if stdout.splitlines() != [b"BTRC_TOOLCHAIN_STDOUT"] or stderr.splitlines() != [b"BTRC_TOOLCHAIN_STDERR"]:
            raise RuntimeError("native C toolchain probe did not preserve both output streams")
        self.report["native_toolchain_probe"] = {"status": "passed", "image": image}

    def diagnose_c_frontend(self, source: Path) -> None:
        """Isolate a failed tiny build without changing its qualification result."""
        minimal = self.output / "minimal.c"
        minimal.write_text("int main(void) { return 0; }\n", encoding="utf-8")
        # Zig 0.16 selects link mode unless -c/-S/-E changes c_out_mode;
        # forwarding -### or -fsyntax-only to Clang does not change that mode.
        probes = [
            ("driver-plan", ["-c", "-###", minimal]),
            ("native-syntax", ["-c", "-fsyntax-only", minimal]),
            ("target-syntax", ["-target", TARGET, "-c", "-fsyntax-only", minimal]),
            ("target-object", ["-target", TARGET, "-c", minimal, "-o", self.output / "minimal.o"]),
            (
                "verbose-object",
                ["-v", "-target", TARGET, "-c", minimal, "-o", self.output / "minimal-verbose.o"],
            ),
            ("target-link", ["-target", TARGET, minimal, "-o", self.output / "minimal.exe"]),
            ("overlay-preprocess", ["-target", TARGET, *FLAGS, "-E", source]),
        ]
        failures = {}
        self.report["c_frontend_diagnostics"] = {"qualification": "not-run", "failures": failures}
        for name, arguments in probes:
            try:
                self.run([self.zig, "cc", *arguments], f"diagnostic-{name}", timeout=60)
            except RuntimeError as error:
                failures[name] = str(error)
        if sys.platform == "win32" and any(step.get("exit_code") == 0xC0000005 for step in self.report["steps"]):
            report = self.output / "crash-location.json"
            self.report["c_frontend_diagnostics"]["crash_location"] = str(report)
            try:
                self.run(
                    [
                        sys.executable,
                        "-m",
                        "tools.windows_toolchain.crash_probe",
                        "--output",
                        report,
                        "--timeout",
                        "20",
                        "--",
                        self.zig,
                        "cc",
                        "-target",
                        TARGET,
                        minimal,
                        "-o",
                        self.output / "minimal-debug.exe",
                    ],
                    "diagnostic-crash-location",
                    timeout=30,
                )
            except RuntimeError as error:
                failures["crash-location"] = str(error)

    def verify_cross(self, path: Path) -> None:
        data = path.read_bytes()
        summary = json.loads(data)
        required = {
            "status": "passed",
            "mode": "cross",
            "host_system": "Linux",
            "native_execution": "not-run",
            "revision": self.report["revision"],
            "zig_version": PINS["zig_version"],
        }
        if any(summary.get(key) != value for key, value in required.items()):
            raise RuntimeError("cross summary must identify a passing Linux cross-build at this source revision")
        for field in ("sha256", "machine", "bytes"):
            if summary.get("compiler", {}).get(field) != self.report["cross_compiler"][field]:
                raise RuntimeError(f"cross artifact differs from its Linux manifest: {field}")
        self.report["cross_summary_sha256"] = hashlib.sha256(data).hexdigest()
        self.report["cross_source_revision"] = summary["revision"]

    def native(self, cross: Path, cross_summary: Path) -> None:
        # Leave ten minutes of the 210-minute hosted step for report/cleanup.
        self.deadline = time.monotonic() + 12000
        self.report["overall_timeout_s"] = 12000
        if platform.system() != "Windows" or sysconfig.get_platform() != "win-arm64":
            raise RuntimeError("native evidence requires ARM64 Python on an actual ARM64 Windows host")
        if any(path.resolve().is_relative_to(self.output) for path in (cross, cross_summary)):
            raise RuntimeError("cross artifact must be separate from the native output directory")
        self.report["cross_compiler"] = pe_arm64(cross)
        self.verify_cross(cross_summary)
        self.probe_native_toolchain()
        native = self.build()
        sample = ROOT / "src/tests/strings/BracesInCodeGen.btrc"
        self.report["native_execution"] = "running"
        cross_c = self.run([cross, sample], "cross-sample")
        native_c = self.run([native, sample], "native-sample")
        if cross_c != native_c:
            raise RuntimeError("cross-built and native-built compilers emitted different C")
        generated, executable = self.output / "sample.c", self.output / "sample.exe"
        generated.write_bytes(native_c)
        self.run([self.zig, "cc", "-target", TARGET, *FLAGS, generated, "-o", executable, "-lm"], "sample-build")
        self.report["sample"] = pe_arm64(executable)
        actual = self.run([executable], "sample-run", timeout=60).decode().splitlines()
        expected = (ROOT / "src/tests/strings/expected/BracesInCodeGen.stdout").read_text().splitlines()
        if actual != expected:
            raise RuntimeError("native ARM64 sample differs from its golden output")
        self.environment.update(
            BTRC_CC=shlex.join([self.zig, "cc", "-target", TARGET]),
            BTRC_CFLAGS=shlex.join(FLAGS),
            BTRC_BOOTSTRAP_TIMEOUT_SECONDS="3600",
        )
        self.run([sys.executable, "-m", "unittest", "-v", "src.tests.btrc.test_bootstrap"], "bootstrap", timeout=10800)
        bootstrap = (self.output / "bootstrap.stderr").read_bytes()
        if b"Ran 1 test in " not in bootstrap or not bootstrap.rstrip().endswith(b"\nOK"):
            raise RuntimeError("bootstrap did not record one executed passing test (skips are not evidence)")
        self.report["native_execution"] = "passed"
        self.report["sample_c_sha256"] = hashlib.sha256(native_c).hexdigest()
        self.report["bootstrap"] = "three-stage C fixed point and self-built sample passed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["cross", "native", "pe"])
    parser.add_argument("--out", type=Path, default=ROOT / "build/windows-toolchain")
    parser.add_argument("--zig", default="zig")
    parser.add_argument("--cross", type=Path)
    parser.add_argument("--cross-summary", type=Path)
    args = parser.parse_args()
    if args.mode in {"native", "pe"} and args.cross is None:
        parser.error("--cross is required for native or pe")
    if args.mode == "native" and args.cross_summary is None:
        parser.error("--cross-summary is required for native provenance")
    if any(
        path is not None and path.resolve().is_relative_to(args.out.resolve())
        for path in (args.cross, args.cross_summary)
    ):
        parser.error("cross inputs must be separate from the output directory; refusing to overwrite evidence")
    evidence = Evidence(args.out, args.zig)
    evidence.report["mode"] = args.mode
    try:
        if args.mode == "pe":
            evidence.report["compiler"] = pe_arm64(args.cross)
        else:
            evidence.identify()
            if args.mode == "cross":
                evidence.build()
            else:
                evidence.native(args.cross.resolve(), args.cross_summary.resolve())
        evidence.report["status"] = "passed"
        return 0
    except Exception as error:
        evidence.report["error"] = str(error)
        if sys.platform == "win32":
            try:
                evidence.diagnose_windows_failure()
            except Exception as diagnostic_error:
                evidence.report["host_diagnostics_error"] = str(diagnostic_error)
        if evidence.report["native_execution"] == "running":
            evidence.report["native_execution"] = "failed"
        print(str(error), file=sys.stderr)
        return 1
    finally:
        (evidence.output / "summary.json").write_text(json.dumps(evidence.report, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
