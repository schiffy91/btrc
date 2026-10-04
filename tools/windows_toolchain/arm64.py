"""Windows ARM64 compiler evidence; Linux builds are explicitly not native runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import struct
import sys
import sysconfig
from pathlib import Path

from tools.windows_toolchain.process_runner import run as run_process

ROOT = Path(__file__).resolve().parents[2]
TARGET = "aarch64-windows-gnu"
FLAGS = [
    "-std=c11",
    "-O2",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-pedantic",
    "-I",
    str(ROOT / "src/runtime/windows"),
    "-include",
    str(ROOT / "src/runtime/windows/btrc_win_compat.h"),
]


def pe_arm64(path: Path) -> dict[str, str | int]:
    data = path.read_bytes()
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError(f"not a DOS/PE image: {path}")
    offset = struct.unpack_from("<I", data, 60)[0]
    if offset < 64 or offset + 26 > len(data) or data[offset : offset + 4] != b"PE\0\0":
        raise ValueError(f"invalid PE header: {path}")
    machine = struct.unpack_from("<H", data, offset + 4)[0]
    magic = struct.unpack_from("<H", data, offset + 24)[0]
    if machine != 0xAA64 or magic != 0x20B:
        raise ValueError(f"expected ARM64 PE32+, got machine={machine:#x}, magic={magic:#x}: {path}")
    return {"path": str(path), "machine": machine, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


class Evidence:
    def __init__(self, output: Path, zig: str):
        self.output, self.zig = output.resolve(), zig
        self.output.mkdir(parents=True, exist_ok=True)
        self.environment = {**os.environ, "BTRC_HOME": str(ROOT / "src")}
        self.report = {
            "status": "failed",
            "host": platform.platform(),
            "host_system": platform.system(),
            "python_platform": sysconfig.get_platform(),
            "native_execution": "not-run",
            "steps": [],
        }

    def run(self, args: list[str | Path], name: str, *, timeout: int = 3600) -> bytes:
        command = list(map(str, args))
        result = run_process(command, cwd=ROOT, env=self.environment, timeout=timeout)
        (self.output / f"{name}.stdout").write_bytes(result.stdout)
        (self.output / f"{name}.stderr").write_bytes(result.stderr)
        self.report["steps"].append(
            {"name": name, "argv": command, "exit_code": result.returncode, "timed_out": result.timed_out}
        )
        if result.timed_out:
            raise RuntimeError(f"{name} timed out after {timeout}s; partial stdout/stderr retained")
        if result.returncode:
            raise RuntimeError(f"{name} exited {result.returncode}; see {self.output / (name + '.stderr')}")
        return result.stdout

    def identify(self) -> None:
        self.report["revision"] = self.run(["git", "rev-parse", "HEAD"], "revision", timeout=60).decode().strip()
        version = self.run([self.zig, "version"], "zig-version", timeout=60).decode().strip()
        if version != "0.16.0":
            raise RuntimeError(f"expected pinned Zig 0.16.0, got {version}")
        self.report["zig_version"] = version

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
        self.run([self.zig, "cc", "-target", TARGET, *FLAGS, source, "-o", binary, "-lm"], "build")
        self.report["compiler"] = pe_arm64(binary)
        return binary

    def verify_cross(self, path: Path) -> None:
        data = path.read_bytes()
        summary = json.loads(data)
        required = {
            "status": "passed",
            "mode": "cross",
            "host_system": "Linux",
            "native_execution": "not-run",
            "revision": self.report["revision"],
            "zig_version": "0.16.0",
        }
        if any(summary.get(key) != value for key, value in required.items()):
            raise RuntimeError("cross summary must identify a passing Linux cross-build at this source revision")
        for field in ("sha256", "machine", "bytes"):
            if summary.get("compiler", {}).get(field) != self.report["cross_compiler"][field]:
                raise RuntimeError(f"cross artifact differs from its Linux manifest: {field}")
        self.report["cross_summary_sha256"] = hashlib.sha256(data).hexdigest()
        self.report["cross_source_revision"] = summary["revision"]

    def native(self, cross: Path, cross_summary: Path) -> None:
        if platform.system() != "Windows" or sysconfig.get_platform() != "win-arm64":
            raise RuntimeError("native evidence requires ARM64 Python on an actual ARM64 Windows host")
        if cross.resolve() == self.output / "btrcc.exe":
            raise RuntimeError("cross artifact must be separate from the native output directory")
        self.report["native_execution"] = "running"
        self.report["cross_compiler"] = pe_arm64(cross)
        self.verify_cross(cross_summary)
        native = self.build()
        sample = ROOT / "src/tests/strings/BracesInCodeGen.btrc"
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
        if evidence.report["native_execution"] == "running":
            evidence.report["native_execution"] = "failed"
        print(str(error), file=sys.stderr)
        return 1
    finally:
        (evidence.output / "summary.json").write_text(json.dumps(evidence.report, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
