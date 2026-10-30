"""Hosted, same-toolchain memory attribution; never changes benchmark budgets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from tools.bench.suite import COMMAND_TIMEOUT, MAXRSS_REPORTER, Peak
from tools.host_c_compiler import HostCCompiler

MAIN_REVISION = "dc97d1f23610a7135d8471cbc0450e39ac196452"
PROGRAMS = ("BenchArc", "RunStrings")
ENVIRONMENT_KEYS = (
    "PATH",
    "BTRC_HOME",
    "BASH_ENV",
    "DEVCONTAINER",
    "BTRC_NATIVE_HEADER_READER",
    "BTRC_NATIVE_SYSROOT",
    "BTRC_NATIVE_TARGET",
    "BTRC_JAVA_CLASS_READER",
    "PKG_CONFIG_PATH",
    "BTRC_CFLAGS",
    "CC",
    "HOST_CC",
    "NIX_CFLAGS_COMPILE",
    "NIX_LDFLAGS",
    "LD_LIBRARY_PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
)


class MemoryDiagnostic:
    """Own two fresh builds and the explicitly labelled attribution receipts."""

    @staticmethod
    def container_command(arguments: list[str]) -> list[str] | None:
        """Enter the image's BASH_ENV once, before selecting or recording tools.

        A direct podman Python command bypasses BASH_ENV. Make recipes happen
        to load it, but Python-run guards do not, leaving typed native imports
        without their reader/sysroot and pkg-config environment.
        """
        if (
            os.environ.get("DEVCONTAINER") != "true"
            or not os.environ.get("BASH_ENV")
            or os.environ.get("BTRC_BENCH_DIAGNOSTIC_SHELL") == "1"
        ):
            return None
        return [
            "bash",
            "-c",
            'export BTRC_BENCH_DIAGNOSTIC_SHELL=1; exec "$@"',
            "bench-diagnostic",
            sys.executable,
            "-m",
            "tools.bench.diagnostic",
            *arguments,
        ]

    def __init__(self, repository: Path, output: Path, scratch: Path, candidate: str, cc: list[str]) -> None:
        self.repository = repository.resolve()
        self.output = output.resolve()
        self.scratch = scratch.resolve()
        self.candidate = candidate
        self.cc = cc
        self.receipt: dict = {
            "schema_version": 1,
            "purpose": "diagnostic only; no baseline update or final-tree qualification",
            "historical_baseline_caveat": (
                "The tracked baseline has mixed-age measurements. Main versus candidate isolates integration "
                "on this host; neither reconstructs every historical compiler/toolchain. A shared failure "
                "does not establish reporter drift. Cross data-root rows are unsupported compositions."
            ),
            "floor_policy": "context only; never subtract from compiler peaks",
            "emitted_artifact_policy": (
                "Separate unmeasured transpile and O0/O2 compile/link only; these binaries are not executed. "
                "Behavioral parity is checked by each unchanged matched-tree guard."
            ),
            "commands": [],
            "samples": [],
            "artifacts": {},
            "builds": {},
            "guards": {},
            "emissions": {},
        }

    @staticmethod
    def digest(path: Path) -> str:
        value = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                value.update(block)
        return value.hexdigest()

    @staticmethod
    def environment(tree: Path) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("BTRC_TIMING", None)
        # Each normal guard imports its own tree's tools; an inherited path must
        # not silently replace those owners with the diagnostic checkout.
        env.pop("PYTHONPATH", None)
        env["BTRC_HOME"] = str(tree / "src")
        return env

    @staticmethod
    def recorded_environment(env: dict[str, str]) -> dict[str, str]:
        return {key: env[key] for key in ENVIRONMENT_KEYS if key in env}

    def save(self) -> None:
        self.output.mkdir(parents=True, exist_ok=True)
        temporary = self.output / "receipt.json.tmp"
        temporary.write_text(json.dumps(self.receipt, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.output / "receipt.json")

    @staticmethod
    def resident_maps(source: str) -> list[dict]:
        """Keep Linux smaps accounting per mapping, without treating PSS as RSS."""
        mappings = []
        current = None
        counters = {"Rss", "Pss", "Private_Clean", "Private_Dirty", "Shared_Clean", "Shared_Dirty", "Anonymous"}
        for line in source.splitlines():
            if re.match(r"^[0-9a-f]+-[0-9a-f]+\s", line):
                fields = line.split(maxsplit=5)
                if len(fields) < 5:
                    raise ValueError("incomplete smaps mapping header")
                current = {
                    "address": fields[0],
                    "permissions": fields[1],
                    "path": fields[5] if len(fields) == 6 else "",
                }
                mappings.append(current)
            elif current is not None and ":" in line:
                name, value = line.split(":", 1)
                if name in counters:
                    parts = value.split()
                    if len(parts) != 2 or parts[1] != "kB" or not parts[0].isdigit():
                        raise ValueError(f"invalid smaps counter {name}")
                    current[name] = int(parts[0]) * 1024
        if any(not counters.issubset(row) for row in mappings):
            raise ValueError("incomplete smaps accounting")
        return mappings

    def observe_residency(self, process: subprocess.Popen, record: dict) -> int:
        """Sample a separate, unmeasured emission; leave wait4 budget samples alone."""
        observed = {"scope": "sampled mapping RSS; not peak-rusage or budget evidence", "samples": 0}
        record["residency"] = observed
        deadline = time.monotonic() + COMMAND_TIMEOUT
        while process.poll() is None:
            if time.monotonic() >= deadline:
                process.kill()
                process.wait(timeout=10)
                raise subprocess.TimeoutExpired(record["argv"], COMMAND_TIMEOUT)
            try:
                # Popen has completed exec before returning. Retain a raw snapshot
                # so every aggregate can be checked against the kernel's rows.
                source = Path(f"/proc/{process.pid}/smaps").read_text()
                mappings = self.resident_maps(source)
                if mappings:
                    observed["samples"] += 1
                    rss = sum(row["Rss"] for row in mappings)
                    if rss > observed.get("maximum_sampled_rss_bytes", -1):
                        snapshot = self.output / f"{record['label']}.smaps"
                        snapshot.write_text(source)
                        observed.update(maximum_sampled_rss_bytes=rss, snapshot=snapshot.name, mappings=mappings)
            except (OSError, ValueError) as error:
                # Exit can race a procfs read. Missing samples remain explicit;
                # they never become zero-memory observations or hide child errors.
                observed["last_observation_error"] = str(error)
            time.sleep(0.02)
        return process.returncode

    def command(self, label: str, argv: list[str], cwd: Path, env: dict[str, str], *, residency: bool = False) -> dict:
        record = {
            "label": label,
            "argv": argv,
            "cwd": str(cwd),
            "environment": self.recorded_environment(env),
            "timing_unset": "BTRC_TIMING" not in env,
        }
        self.receipt["commands"].append(record)
        self.save()
        stdout = self.output / f"{label}.stdout"
        stderr = self.output / f"{label}.stderr"
        try:
            with stdout.open("wb") as out, stderr.open("wb") as err:
                if residency:
                    with subprocess.Popen(argv, cwd=cwd, env=env, stdout=out, stderr=err) as process:
                        record["returncode"] = self.observe_residency(process, record)
                else:
                    completed = subprocess.run(argv, cwd=cwd, env=env, stdout=out, stderr=err, timeout=COMMAND_TIMEOUT)
                    record["returncode"] = completed.returncode
        except (OSError, subprocess.TimeoutExpired) as error:
            record["error"] = str(error)
            record["returncode"] = None
        finally:
            record["stdout"] = stdout.name
            record["stderr"] = stderr.name
            self.save()
        return record

    def git(self, *arguments: str) -> str:
        return subprocess.check_output(
            ["git", "-c", "safe.directory=*", *arguments], cwd=self.repository, text=True, timeout=60
        ).strip()

    def retain(self, source: Path, relative: str) -> None:
        destination = self.output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        self.receipt["artifacts"][relative] = {"sha256": self.digest(destination), "bytes": destination.stat().st_size}
        self.save()

    def prepare(self) -> dict[str, Path]:
        if sys.platform != "linux":
            raise ValueError("this diagnostic requires the hosted Linux devcontainer")
        if self.scratch.exists():
            raise ValueError("diagnostic scratch must be new; do not reuse previous compiler outputs")
        if self.git("rev-parse", "HEAD") != self.candidate:
            raise ValueError("candidate must be the exact checked-out diagnostic revision")
        if self.git("status", "--porcelain", "--untracked-files=no"):
            raise ValueError("tracked diagnostic checkout is dirty")
        self.scratch.mkdir(parents=True)
        trees = {name: self.scratch / name for name in ("main", "candidate")}
        revisions = {"main": MAIN_REVISION, "candidate": self.candidate}
        for name, revision in revisions.items():
            self.git("worktree", "add", "--detach", str(trees[name]), revision)
            self.receipt["builds"][name] = {
                "revision": revision,
                "tree": self.git("rev-parse", f"{revision}^{{tree}}"),
                "path": str(trees[name]),
            }
        env = self.environment(trees["candidate"])
        self.receipt["host"] = {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version,
            "python_executable": sys.executable,
            "python_sha256": self.digest(Path(sys.executable).resolve()),
            "cc": self.cc,
            "page_size_bytes": os.sysconf("SC_PAGE_SIZE"),
            "cc_resolved": shutil.which(self.cc[0]),
            "image_receipt": "image.json (podman inspect, saved outside the container)",
        }
        resolved_cc = shutil.which(self.cc[0])
        if resolved_cc is None:
            raise ValueError("configured C compiler is not executable")
        self.receipt["host"]["cc_realpath"] = str(Path(resolved_cc).resolve())
        self.receipt["host"]["cc_sha256"] = self.digest(Path(resolved_cc).resolve())
        self.retain(Path(resolved_cc).resolve(), "tools/cc-driver")
        self.retain(Path(__file__).with_name("suite.py"), "tools/measurement-suite.py")
        reporter = self.output / "maxrss-reporter.py"
        reporter.write_text(MAXRSS_REPORTER, encoding="utf-8")
        self.receipt["artifacts"][reporter.name] = {"sha256": self.digest(reporter), "bytes": reporter.stat().st_size}
        # Nix's cc can be a wrapper. Ask the driver for its actual C frontend
        # and linker instead of treating the wrapper digest as the full tool.
        self.receipt["host"]["compiler_tools"] = {}
        for tool in ("cc1", "as", "ld"):
            result = self.command(f"cc-tool-{tool}", [*self.cc, f"-print-prog-name={tool}"], self.repository, env)
            identity = {"returncode": result["returncode"]}
            self.receipt["host"]["compiler_tools"][tool] = identity
            if result["returncode"] == 0:
                reported = (self.output / result["stdout"]).read_text().strip()
                resolved = shutil.which(reported)
                identity.update(reported=reported, resolved=resolved)
                if resolved is not None:
                    path = Path(resolved).resolve()
                    identity.update(realpath=str(path), sha256=self.digest(path))
                    self.retain(path, f"tools/{tool}")
                else:
                    identity["disposition"] = "driver did not expose an executable path"
        self.command("cpu", ["lscpu"], self.repository, env)
        self.command("cc-version", [*self.cc, "--version"], self.repository, env)
        self.command("cc-search-dirs", [*self.cc, "-print-search-dirs"], self.repository, env)
        for name, tree in trees.items():
            env = self.environment(tree)
            build = self.command(
                f"build-{name}", ["make", "NIX=", f"HOST_CC={shlex.join(self.cc)}", "btrcc"], tree, env
            )
            self.receipt["builds"][name]["returncode"] = build["returncode"]
            for path in (
                "bin/btrcc",
                "dist/btrcc.c",
                "src/tests/fixtures/benchmarks/baseline.json",
                "flake.lock",
                "tools/bench/suite.py",
                *(f"src/tests/benchmarks/{program}.btrc" for program in PROGRAMS),
            ):
                if (tree / path).is_file():
                    self.retain(tree / path, f"builds/{name}/{path}")
            if build["returncode"] != 0:
                continue
            self.command(f"libraries-{name}", ["ldd", str(tree / "bin/btrcc")], tree, env)
        return trees

    def samples(self, label: str, argv: list[str], tree: Path, *, matched: bool, floor: bool = False) -> None:
        env = self.environment(tree)
        for index in range(3):
            row = {
                "label": label,
                "sample": index,
                "argv": argv,
                "cwd": str(tree),
                "environment": self.recorded_environment(env),
                "timing_unset": "BTRC_TIMING" not in env,
                "composition": "reporter floor"
                if floor
                else "matched tree"
                if matched
                else "unsupported cross data-root",
            }
            self.receipt["samples"].append(row)
            self.save()

            def observed(raw: int, returncode: int, row: dict = row) -> None:
                row.update(raw_ru_maxrss=raw, raw_unit="KiB", returncode=returncode)
                self.save()

            try:
                peak = Peak.measure(argv, env, tree, observation=observed)
                if peak.source != "maxrss":
                    raise ValueError(f"expected Linux wait4 maxrss, received {peak.source}")
                row.update(bytes=peak.bytes, raw_ru_maxrss=peak.bytes // 1024, raw_unit="KiB", returncode=0)
            except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError) as error:
                row.update(error=str(error), disposition="measurement failed")
                row.setdefault("returncode", None)
                row.setdefault("raw_ru_maxrss", None)
            finally:
                self.save()
        self.receipt.setdefault("sample_groups", {})[label] = {
            "complete": all(row.get("returncode") == 0 for row in self.receipt["samples"] if row["label"] == label),
            "samples": 3,
        }
        rows = [row for row in self.receipt["samples"] if row["label"] == label]
        self.receipt["sample_groups"][label]["minimum_bytes"] = (
            min(row["bytes"] for row in rows) if all("bytes" in row for row in rows) else None
        )
        self.save()

    def guard(self, name: str, tree: Path) -> None:
        destination = self.output / f"guard-{name}.json"
        argv = [
            sys.executable,
            "-m",
            "tools.bench",
            "check",
            "--btrcc",
            str(tree / "bin/btrcc"),
            "--cc",
            shlex.join(self.cc),
            "--repeat",
            "3",
            "--strict",
            "--timings",
            "report",
            "--json",
            str(destination),
            "--out-dir",
            # Compiler caches contain private 0700 directories. They are
            # scratch state, not evidence, and the host uploader may have a
            # different uid from the container that owns them.
            str(self.scratch / f"guard-{name}"),
        ]
        result = self.command(f"guard-{name}", argv, tree, self.environment(tree))
        self.receipt["guards"][name] = result["returncode"]
        self.save()

    def print_summary(self) -> None:
        """Keep useful results in job logs even if artifact delivery fails."""
        summary = {key: self.receipt.get(key) for key in ("status", "error", "guards", "sample_groups")}
        summary["builds"] = {
            name: {key: build.get(key) for key in ("revision", "returncode")}
            for name, build in self.receipt["builds"].items()
        }
        print(json.dumps(summary, indent=2), flush=True)
        for command in self.receipt["commands"]:
            if command.get("returncode") == 0:
                continue
            for stream in ("stdout", "stderr"):
                if stream not in command:
                    continue
                path = self.output / command[stream]
                if not path.is_file():
                    continue
                with path.open("rb") as source:
                    source.seek(max(0, path.stat().st_size - 12000))
                    tail = source.read().decode("utf-8", errors="replace")
                if tail:
                    print(f"{command['label']} {stream} (last 12000 bytes):\n{tail}", flush=True)

    def emitted(self, compiler_name: str, tree_name: str, tree: Path, compiler: Path, program: str) -> None:
        label = f"emitted-{compiler_name}-{tree_name}-{program}"
        argv = [str(compiler), str(tree / "src/tests/benchmarks" / f"{program}.btrc")]
        result = self.command(label, argv, tree, self.environment(tree), residency=compiler_name == tree_name)
        emission = {
            "evidence": "unmeasured transpile plus compile/link only; executable not run",
            "matched": compiler_name == tree_name,
            "transpile_returncode": result["returncode"],
            "cc_returncodes": {},
        }
        self.receipt["emissions"][label] = emission
        self.save()
        if result["returncode"] != 0:
            return
        source = self.output / f"{label}.c"
        shutil.copy2(self.output / result["stdout"], source)
        self.receipt["artifacts"][source.name] = {"sha256": self.digest(source), "bytes": source.stat().st_size}
        for optimization in ("-O0", "-O2"):
            binary = self.output / f"{label}{optimization}"
            built = self.command(
                f"{label}{optimization}",
                [
                    *self.cc,
                    *shlex.split(os.environ.get("BTRC_CFLAGS", "-std=c11 -pedantic")),
                    optimization,
                    str(source),
                    "-o",
                    str(binary),
                    "-lm",
                    "-lpthread",
                ],
                tree,
                self.environment(tree),
            )
            emission["cc_returncodes"][optimization] = built["returncode"]
            if built["returncode"] == 0:
                self.receipt["artifacts"][binary.name] = {"sha256": self.digest(binary), "bytes": binary.stat().st_size}
        self.save()

    def execute(self) -> int:
        if (self.output / "receipt.json").exists():
            raise ValueError("diagnostic evidence already exists; choose a new output directory")
        self.output.mkdir(parents=True, exist_ok=True)
        try:
            trees = self.prepare()
            floor_source = self.output / "floor.c"
            floor_source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
            floor = self.output / "floor"
            made = self.command(
                "build-floor",
                [*self.cc, "-std=c11", "-pedantic", "-O2", str(floor_source), "-o", str(floor)],
                trees["candidate"],
                self.environment(trees["candidate"]),
            )
            if made["returncode"] != 0:
                raise RuntimeError("floor control failed to build")
            self.retain(floor, "controls/floor")
            # Alternate compiler order across source/data-root columns. Every
            # row in a column uses the identical program path, cwd and home.
            for tree_name, order in (("main", ("main", "candidate")), ("candidate", ("candidate", "main"))):
                tree = trees[tree_name]
                self.samples(f"floor-before-{tree_name}", [str(floor)], tree, matched=True, floor=True)
                for compiler_name in order:
                    if self.receipt["builds"][compiler_name]["returncode"] != 0:
                        continue
                    compiler = trees[compiler_name] / "bin/btrcc"
                    for program in PROGRAMS:
                        argv = [str(compiler), str(tree / "src/tests/benchmarks" / f"{program}.btrc")]
                        self.samples(
                            f"{compiler_name}-{tree_name}-{program}", argv, tree, matched=compiler_name == tree_name
                        )
                        self.emitted(compiler_name, tree_name, tree, compiler, program)
                self.samples(f"floor-after-{tree_name}", [str(floor)], tree, matched=True, floor=True)
            for name, tree in trees.items():
                if self.receipt["builds"][name]["returncode"] == 0:
                    self.guard(name, tree)
            success = all(build["returncode"] == 0 for build in self.receipt["builds"].values())
            success = success and self.receipt["guards"] == {"main": 0, "candidate": 0}
            success = success and all(
                row["transpile_returncode"] == 0 and row["cc_returncodes"] == {"-O0": 0, "-O2": 0}
                for row in self.receipt["emissions"].values()
                if row["matched"]
            )
            success = success and all(
                row["returncode"] == 0
                for row in self.receipt["samples"]
                if row["composition"] != "unsupported cross data-root"
            )
            self.receipt["status"] = (
                "diagnostic completed; matched guards passed" if success else "diagnostic completed with failures"
            )
            return 0 if success else 1
        except Exception as error:
            self.receipt.update(status="diagnostic interrupted", error=f"{type(error).__name__}: {error}")
            return 1
        finally:
            self.save()
            self.print_summary()

    @classmethod
    def main(cls, argv: list[str] | None = None) -> int:
        arguments = list(sys.argv[1:] if argv is None else argv)
        command = cls.container_command(arguments)
        if command is not None:
            os.execvp(command[0], command)
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--candidate", required=True)
        parser.add_argument("--output", type=Path, default=Path("build/bench-diagnostic"))
        parser.add_argument("--scratch", type=Path, default=Path("build/bench-diagnostic-trees"))
        args = parser.parse_args(arguments)
        reader = os.environ.get("BTRC_NATIVE_HEADER_READER")
        if not reader or not os.access(reader, os.X_OK):
            parser.error("native header reader is unavailable; run from the configured devcontainer shell")
        return cls(
            Path.cwd(), args.output, args.scratch, args.candidate, HostCCompiler.configured(empty_is_unset=True)
        ).execute()


if __name__ == "__main__":
    raise SystemExit(MemoryDiagnostic.main())
