"""Check managed collection lifetimes and compare release policies on a hosted Mac."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import statistics
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from tools.budget_bench import TimeReport
from tools.qualification.adapters import HostProvenance

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path("src/tests/benchmarks/fixtures/ManagedCollections.btrc")
CC = "/usr/bin/clang"
FORMS = ("whole", "modules")
FRONTENDS = ("reference", "selfhost")
SANITIZERS = ("-fsanitize=address,undefined", "-fno-omit-frame-pointer")


class CollectionReleaseDiagnostic:
    """Own correctness controls, identical-toolchain builds, and measured samples."""

    def __init__(self, repository: Path, output: Path, btrcc: Path | None = None, *, check_only: bool = False) -> None:
        self.repository = repository.resolve()
        self.output = output.resolve()
        self.btrcc = btrcc.resolve() if btrcc is not None else self.repository / "bin/btrcc"
        self.check_only = check_only
        self.receipt: dict = {
            "schema": 1,
            "purpose": "Collection release policy diagnostic; no baseline update or application budget qualification",
            "commands": [],
            "controls": [],
            "samples": [],
            "binaries": {},
            "c_comparisons": [],
            "measurement_qualified": False,
        }

    @staticmethod
    def digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def save(self) -> None:
        temporary = self.output / "receipt.json.tmp"
        temporary.write_text(json.dumps(self.receipt, indent=2) + "\n")
        temporary.replace(self.output / "receipt.json")

    def git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.repository, text=True).strip()

    @staticmethod
    def require_host(*, check_only: bool) -> None:
        if sys.platform != "darwin":
            raise ValueError("This diagnostic requires macOS and Apple clang")
        if not check_only and not (
            os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_OS") == "macOS"
            and os.environ.get("BTRC_TEST_RUNNER") == "macos-hosted"
        ):
            raise ValueError("Measurements require a dedicated hosted macOS workflow job")

    @staticmethod
    def native_environment(*, sanitized: bool = False) -> dict[str, str]:
        # Apple clang and its sanitizer runtime must not inherit Nix linker settings.
        env = {
            key: os.environ[key]
            for key in ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE")
            if key in os.environ
        }
        env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        if sanitized:
            env.update(ASAN_OPTIONS="detect_leaks=0:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
        return env

    def compiler_environment(self) -> dict[str, str]:
        env = dict(os.environ, BTRC_HOME=str(self.repository / "src"), PYTHONPATH=str(self.repository))
        env.pop("BTRC_TIMING", None)
        return env

    def command(
        self, label: str, argv: list[str], *, env: dict[str, str], timeout: int = 180
    ) -> subprocess.CompletedProcess:
        record = {"label": label, "argv": argv, "cwd": str(self.repository)}
        self.receipt["commands"].append(record)
        self.save()
        stdout, stderr = self.output / f"{label}.stdout", self.output / f"{label}.stderr"
        try:
            with stdout.open("wb") as out, stderr.open("wb") as err:
                result = subprocess.run(argv, cwd=self.repository, env=env, stdout=out, stderr=err, timeout=timeout)
            record["returncode"] = result.returncode
            return subprocess.CompletedProcess(argv, result.returncode, stdout.read_text(), stderr.read_text())
        except (OSError, subprocess.TimeoutExpired) as error:
            record.update(error=str(error), returncode=None)
            raise
        finally:
            record.update(stdout_sha256=self.digest(stdout), stderr_sha256=self.digest(stderr))
            self.save()

    def prepare(self) -> None:
        self.require_host(check_only=self.check_only)
        dirty = self.git("status", "--porcelain")
        if not self.check_only and dirty:
            raise ValueError("Measured source must be a clean checkout")
        self.output.mkdir(parents=True, exist_ok=False)
        self.receipt.update(
            head=self.git("rev-parse", "HEAD"),
            tree=self.git("rev-parse", "HEAD^{tree}"),
            dirty=bool(dirty),
            check_only=self.check_only,
            fixture_sha256=self.digest(self.repository / FIXTURE),
            tool_sha256=self.digest(Path(__file__)),
            host=asdict(HostProvenance(self.repository).detect()),
            host_summary=HostProvenance(self.repository).summary(),
        )
        self.save()
        version = self.command("clang-version", [CC, "--version"], env=self.native_environment())
        version.check_returncode()
        self.receipt["c_compiler"] = {
            "command": [CC],
            "realpath": str(Path(CC).resolve()),
            "sha256": self.digest(Path(CC)),
            "version": version.stdout,
        }
        if not self.check_only:
            if self.btrcc.exists() or (self.repository / "dist/btrcc-macos-native.c").exists():
                raise ValueError("Hosted measurement requires a fresh compiler build")
            build = self.command(
                "build-btrcc",
                ["make", "NIX=", f"HOST_CC={CC}", "generated-check", "btrcc"],
                env=self.compiler_environment(),
                timeout=1800,
            )
            build.check_returncode()
            self.receipt["generated_compiler_sha256"] = self.digest(self.repository / "dist/btrcc-macos-native.c")
        self.receipt["compiler_sha256"] = self.digest(self.btrcc)
        self.save()

    @staticmethod
    def expected_stdout(operation: int, size: int, rounds: int) -> str:
        checksum = size * (size - 1) // 2 * rounds * (4 if operation == 1 else 1)
        return f"{checksum}\n{size * rounds}\n0\n"

    def compile_controls(self) -> None:
        source = self.output / "project/src/Main.btrc"
        source.parent.mkdir(parents=True)
        source.write_bytes((self.repository / FIXTURE).read_bytes())
        (source.parent.parent / "btrc.toml").write_text(
            'manifest-version = 1\n[package]\nname = "collectionReleasePolicy"\n'
        )
        generated = {}
        for form in FORMS:
            generated[form] = {}
            for frontend in FRONTENDS:
                label = f"{form}-{frontend}"
                print("Checking collection lifetimes: " + label, flush=True)
                output = self.output / label
                output.mkdir()
                compiler = (
                    [sys.executable, "-m", "src.compiler.python.main"] if frontend == "reference" else [str(self.btrcc)]
                )
                argv = [*compiler, str(source), "--strict-imports", "--no-cache", "-o", str(output / "program.c")]
                if form == "modules":
                    argv += ["--module-units", "--jobs", "1", "--emit-units", str(output / "program")]
                self.command(label + "-generate", argv, env=self.compiler_environment()).check_returncode()
                files = sorted(output.glob("program*.c"))
                if not files:
                    raise ValueError("Compiler produced no C files")
                generated[form][frontend] = {path.name: path for path in files}
                for sanitized in (False, True):
                    mode = "sanitized" if sanitized else "strict"
                    executable = output / mode
                    # The fixed fixture has only core C runtime dependencies. Compile
                    # every emitted unit with the same driver and flags on both sides.
                    argv = [
                        CC,
                        "-std=c11",
                        "-pedantic-errors",
                        "-Wall",
                        "-Wextra",
                        "-Werror",
                        "-O1" if sanitized else "-O2",
                        *(SANITIZERS if sanitized else ()),
                        *map(str, files),
                        "-lm",
                        "-lpthread",
                        "-o",
                        str(executable),
                    ]
                    self.command(label + "-" + mode + "-build", argv, env=self.native_environment()).check_returncode()
                    key = label + "-" + mode
                    self.receipt["binaries"][key] = {"path": str(executable), "sha256": self.digest(executable)}
                    for operation in range(4):
                        for cyclic in (0, 1):
                            result = self.command(
                                f"{key}-{operation}-{cyclic}",
                                [str(executable), str(operation), "16", "2", str(cyclic)],
                                env=self.native_environment(sanitized=sanitized),
                            )
                            self.receipt["controls"].append(
                                {
                                    "binary": key,
                                    "operation": operation,
                                    "cyclic": cyclic,
                                    "passed": result.returncode == 0
                                    and result.stdout == self.expected_stdout(operation, 16, 2)
                                    and not result.stderr,
                                }
                            )
                            self.save()
        for form, frontends in generated.items():
            if frontends["reference"].keys() != frontends["selfhost"].keys():
                raise ValueError("Frontends produced different C file sets")
            for name, reference in frontends["reference"].items():
                selfhost = frontends["selfhost"][name]
                row = {
                    "form": form,
                    "name": name,
                    "reference_sha256": self.digest(reference),
                    "selfhost_sha256": self.digest(selfhost),
                }
                row["equal"] = row["reference_sha256"] == row["selfhost_sha256"]
                if not row["equal"]:
                    difference = self.output / f"{form}-{name}.diff"
                    difference.write_text(
                        "".join(
                            difflib.unified_diff(
                                reference.read_text().splitlines(True),
                                selfhost.read_text().splitlines(True),
                                fromfile="reference/" + name,
                                tofile="selfhost/" + name,
                            )
                        )
                    )
                    row["diff_sha256"] = self.digest(difference)
                self.receipt["c_comparisons"].append(row)
        self.receipt["controls_passed"] = len(self.receipt["controls"]) == 64 and all(
            row["passed"] for row in self.receipt["controls"]
        )
        self.save()
        if not self.receipt["controls_passed"]:
            raise ValueError("All 64 strict and sanitized controls must pass before measurement")

    def sample(self, form: str, frontend: str, operation: int, size: int, cyclic: int, index: int) -> None:
        key = f"{form}-{frontend}-strict"
        binary = self.receipt["binaries"][key]
        executable = Path(binary["path"])
        if self.digest(executable) != binary["sha256"]:
            raise ValueError("Correctness-checked executable changed before measurement")
        label = f"sample-{key}-{operation}-{size}-{cyclic}-{index}"
        result = self.command(
            label,
            [*TimeReport.command(), str(executable), str(operation), str(size), "3", str(cyclic)],
            env=self.native_environment(),
            timeout=120,
        )
        usage = TimeReport.parse(result.stderr)
        row = {
            "form": form,
            "frontend": frontend,
            "operation": operation,
            "size": size,
            "cyclic": cyclic,
            "index": index,
            "usage": asdict(usage),
            "correct": result.returncode == 0 and result.stdout == self.expected_stdout(operation, size, 3),
            "counters_present": all(
                isinstance(value, int) and value > 0
                for value in (usage.instructions_retired, usage.peak_footprint_bytes)
            ),
        }
        self.receipt["samples"].append(row)
        self.save()
        if not row["correct"]:
            raise ValueError("Measured execution failed its correctness contract: " + label)

    def measure(self) -> None:
        self.require_host(check_only=False)
        if not self.receipt.get("controls_passed"):
            raise ValueError("Correctness controls must finish before measurement")
        self.receipt.update(collector=TimeReport.collector(), instruction_counter=TimeReport.instruction_counter())
        for form in FORMS:
            print("Measuring collection release policies: " + form, flush=True)
            for operation in range(4):
                for cyclic in (0, 1):
                    for size in (64, 512, 4096):
                        for index in range(5):
                            for frontend in FRONTENDS if index % 2 == 0 else FRONTENDS[::-1]:
                                self.sample(form, frontend, operation, size, cyclic, index)
        groups: dict[str, list] = {}
        for row in self.receipt["samples"]:
            key = "-".join(str(row[field]) for field in ("form", "frontend", "operation", "size", "cyclic"))
            groups.setdefault(key, []).append(row)
        summaries = {}
        for key, rows in groups.items():
            summary = {"samples": len(rows)}
            for metric in ("instructions_retired", "peak_footprint_bytes", "wall_s"):
                values = [row["usage"][metric] for row in rows]
                summary[metric] = (
                    {"median": statistics.median(values), "maximum": max(values)}
                    if all(value is not None for value in values)
                    else None
                )
            summaries[key] = summary
        self.receipt["summaries"] = summaries
        self.receipt["measurement_qualified"] = len(self.receipt["samples"]) == 480 and all(
            row["correct"] and row["counters_present"] for row in self.receipt["samples"]
        )
        self.save()
        if not self.receipt["measurement_qualified"]:
            raise ValueError("Instruction or footprint counters are missing; measurement is unqualified")

    def run(self) -> None:
        self.prepare()
        try:
            self.compile_controls()
            if not self.check_only:
                self.measure()
            if (
                self.git("rev-parse", "HEAD") != self.receipt["head"]
                or self.digest(self.btrcc) != self.receipt["compiler_sha256"]
                or self.digest(self.repository / FIXTURE) != self.receipt["fixture_sha256"]
                or self.digest(Path(__file__)) != self.receipt["tool_sha256"]
                or (not self.check_only and self.git("status", "--porcelain"))
            ):
                raise ValueError("Source or compiler changed during the diagnostic")
            self.receipt["status"] = "correctness passed" if self.check_only else "measurement complete"
        except Exception as error:
            self.receipt["measurement_qualified"] = False
            self.receipt["status"] = str(error)
            raise
        finally:
            self.save()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--check-only", action="store_true", help="Run fixed-size correctness controls without measuring"
    )
    parser.add_argument("--btrcc", type=Path, help="Existing compiler, allowed only with --check-only")
    args = parser.parse_args(argv)
    if bool(args.btrcc) != args.check_only:
        parser.error("--check-only requires --btrcc; measurements build a fresh compiler")
    CollectionReleaseDiagnostic(REPO, args.output, args.btrcc, check_only=args.check_only).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
