"""Line coverage of the standard library and of both compilers: one run, one report (`make coverage`).

What is measured, and from what:

- **The standard library** (``src/stdlib``): the lines the corpus executes.
  `make coverage` runs the fast tier with ``BTRC_TEST_LINE_COVERAGE`` set, so
  each corpus program is built with line directives and gcov instrumentation
  (`src/tests/line_coverage.py`) and reports the BTRC lines it ran. The
  self-hosted compiler's own use of the library is added. A line counts as
  executable when gcov saw code on it in any of those programs, or in the
  *census*: each module compiled alone with every function kept, so that a
  function no test reaches still counts, as not executed.
- **The self-hosted compiler** (``src/compiler/btrc``): the lines it executes
  while it transpiles the corpus. `selfhost-build` builds it with line
  directives and instrumentation; the corpus is then run through that binary.
- **The reference compiler** (``src/compiler/python``): coverage.py's statement
  coverage of the same fast-tier run.

What it does not see: a program a Python test builds for itself outside the
corpus runner (the native suites under ``src/tests/native``), a corpus program
that ends without exiting (gcov writes its data at exit; the report names
these programs), a generic that no program instantiates, and a compiler run
in a child process.
`CoverageReport` writes ``report.json`` (``btrc.line-coverage/1``) and
``report.md`` beside the data.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from src.tests.c_toolchains import configured_c_compiler
from src.tests.line_coverage import LineCoverage, Lines
from src.tests.process_limits import C_COMPILE_TIMEOUT
from src.tests.selfhost_cache import ENTRY

REPO = Path(__file__).resolve().parents[1]
SCHEMA = "btrc.line-coverage/1"
STDLIB = "src/stdlib"
PRIVATE = "private to its package"
SELFHOST = "src/compiler/btrc"
REFERENCE = "src/compiler/python"


class StdlibCensus:
    """Every line of the standard library that carries code, whether or not a test reaches it."""

    def __init__(self, repo: Path, directory: Path) -> None:
        self.repo = repo
        self.directory = directory

    def modules(self) -> list[str]:
        """Each module by the name a program imports it with; a package's facade goes by the package's name."""

        root = self.repo / STDLIB
        names = set()
        for source in root.rglob("*.btrc"):
            parts = source.relative_to(root).with_suffix("").parts
            if len(parts) > 1 and parts[-1] == parts[-2]:
                parts = parts[:-1]
            names.add(".".join(parts))
        return sorted(names)

    def take(self, workers: int) -> dict[str, object]:
        """Compile every module alone, side by side; modules that cannot be are named with the reason."""

        work = self.directory / "census"
        work.mkdir(parents=True, exist_ok=True)
        lines: dict[str, Lines] = {}
        failed: dict[str, str] = {}
        private = 0
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            for module, found, reason in pool.map(
                _census_module, [(module, str(self.repo), str(work)) for module in self.modules()]
            ):
                if found is None and reason == PRIVATE:
                    private += 1  # an implementation behind a facade: its lines are taken with the facade's
                elif found is None:
                    failed[module] = reason
                else:
                    LineCoverage.add(lines, found)
        shutil.rmtree(work)
        return {
            "lines": {file: sorted(counts) for file, counts in sorted(lines.items())},
            "failed": failed,
            "private": private,
        }


def _census_module(arguments: tuple[str, str, str]) -> tuple[str, dict[str, Lines] | None, str]:
    """One module's executable lines: compiled alone with nothing removed, never run."""

    module, repo, work = arguments
    from src.compiler.python import Compiler, CompilerOptions

    stem = module.replace(".", "-")
    entry = Path(work) / f"{stem}.btrc"
    source = f"import Library.{module};\n\nint main() {{\n\treturn 0;\n}}\n"
    entry.write_text(source, encoding="utf-8")
    try:
        result = Compiler().compile(
            source,
            str(entry),
            CompilerOptions(debug=True, dce=False, map_stdlib_positions=True, use_cache=False),
        )
    except Exception as error:  # a module that cannot be compiled alone is reported, not fatal
        return module, None, f"{type(error).__name__}: {error}".splitlines()[0]
    if result.failure is not None:
        message = str(getattr(result.failure, "message", result.failure))
        return module, None, PRIVATE if "is private to package" in message else message.splitlines()[0]
    if result.c_source is None:
        return module, None, "no C for this host"
    generated = entry.with_suffix(".c")
    generated.write_text(result.c_source, encoding="utf-8")
    # The headers of what the module binds, where the host's pkg-config knows them.
    libraries = sorted({entry["name"] for entry in result.native_plan.as_dict().get("pkg-config", [])})
    headers = subprocess.run(
        ["pkg-config", "--cflags", *libraries], capture_output=True, text=True, timeout=C_COMPILE_TIMEOUT, check=False
    )
    include = headers.stdout.split() if libraries and headers.returncode == 0 else []
    built = subprocess.run(
        [*configured_c_compiler(), "-std=c11", "-w", *LineCoverage.FLAGS, *include]
        + ["-c", generated.name, "-o", f"{stem}.o"],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )
    if built.returncode != 0:
        errors = [line for line in built.stderr.splitlines() if "error" in line]
        return module, None, (errors or ["the C does not compile alone"])[0].strip()
    coverage = LineCoverage(Path(work), repo=Path(repo))
    return module, coverage.lines_of(coverage.read(entry.with_suffix(".gcno"))), ""


class InstrumentedCompiler:
    """The self-hosted compiler built so that gcov sees which of its BTRC lines run."""

    def __init__(self, repo: Path, directory: Path) -> None:
        self.repo = repo
        self.directory = directory / "btrcc"
        self.binary = self.directory / "btrcc"

    def build(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        generated = self.directory / "btrcc.c"
        environment = {
            **os.environ,
            "BTRC_HOME": str(self.repo / "src"),
            "BTRC_CACHE_DIR": str(self.directory / "cache"),
        }
        transpiled = subprocess.run(
            [sys.executable, "-m", "src.compiler.python.main", ENTRY, "--debug", "--no-cache", "-o", str(generated)],
            cwd=self.repo,
            env=environment,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if transpiled.returncode != 0 or not generated.is_file():
            raise RuntimeError(f"the reference compiler could not transpile {ENTRY}:\n{transpiled.stderr[-4000:]}")
        built = subprocess.run(
            [*configured_c_compiler(), "-std=c11", "-w", *LineCoverage.FLAGS, generated.name, "-o", self.binary.name]
            + ["-lm", "-lpthread"],
            cwd=self.directory,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if built.returncode != 0 or not self.binary.is_file():
            raise RuntimeError(f"the instrumented compiler does not build:\n{built.stderr[-4000:]}")
        return self.binary

    def lines(self) -> dict[str, Lines]:
        """What the compiler executed so far; empty when it never ran."""

        coverage = LineCoverage(self.directory, repo=self.repo)
        found: dict[str, Lines] = {}
        for data in sorted(self.directory.glob("*.gcda")):
            LineCoverage.add(found, coverage.lines_of(coverage.read(data)))
        return found


class CoverageReport:
    """One report from the census, the corpus records, the instrumented compiler and coverage.py."""

    def __init__(self, repo: Path, directory: Path) -> None:
        self.repo = repo
        self.directory = directory

    @staticmethod
    def group(path: str, root: str) -> str:
        """The package a file belongs to: its first directory under `root`, or its own name at the top."""

        parts = Path(path).relative_to(root).parts
        return parts[0] if len(parts) > 1 else Path(parts[0]).stem

    @staticmethod
    def summary(lines: int, executed: int) -> dict[str, object]:
        return {"lines": lines, "executed": executed, "percent": round(100.0 * executed / lines, 1) if lines else None}

    def btrc_section(
        self, root: str, executable: Mapping[str, set[int]], executed: Mapping[str, set[int]], tracked: list[str]
    ) -> dict[str, object]:
        """Totals, packages and files of one BTRC tree; a tracked file with no executable line seen is listed too."""

        files: dict[str, dict[str, object]] = {}
        for path in sorted({*tracked, *executable}):
            if not path.startswith(f"{root}/"):
                continue
            lines = executable.get(path, set())
            ran = executed.get(path, set()) & lines
            files[path] = {**self.summary(len(lines), len(ran)), "missed": sorted(lines - ran)}
        groups: dict[str, list[int]] = {}
        for path, entry in files.items():
            totals = groups.setdefault(self.group(path, root), [0, 0])
            totals[0] += int(entry["lines"])
            totals[1] += int(entry["executed"])
        return {
            **self.summary(sum(lines for lines, _ in groups.values()), sum(ran for _, ran in groups.values())),
            "packages": {name: self.summary(*totals) for name, totals in sorted(groups.items())},
            "files": files,
        }

    def reference_section(self, document: Mapping) -> dict[str, object]:
        groups: dict[str, list[int]] = {}
        files: dict[str, dict[str, object]] = {}
        for path, entry in sorted(document.get("files", {}).items()):
            relative = Path(path).as_posix()
            if not relative.startswith(f"{REFERENCE}/"):
                continue
            statements, covered = int(entry["summary"]["num_statements"]), int(entry["summary"]["covered_lines"])
            files[relative] = {**self.summary(statements, covered), "missed": entry.get("missing_lines", [])}
            totals = groups.setdefault(self.group(relative, REFERENCE), [0, 0])
            totals[0] += statements
            totals[1] += covered
        return {
            **self.summary(sum(lines for lines, _ in groups.values()), sum(ran for _, ran in groups.values())),
            "packages": {name: self.summary(*totals) for name, totals in sorted(groups.items())},
            "files": files,
        }

    def build(self) -> dict[str, object]:
        census = json.loads((self.directory / "census.json").read_text(encoding="utf-8"))
        programs = LineCoverage.total(self.directory / "lines")
        compiler = InstrumentedCompiler(self.repo, self.directory).lines()
        executable: dict[str, set[int]] = {file: set(lines) for file, lines in census["lines"].items()}
        executed: dict[str, set[int]] = {}
        for source in (programs, compiler):
            for file, lines in source.items():
                executable.setdefault(file, set()).update(lines)
                executed.setdefault(file, set()).update(number for number, count in lines.items() if count > 0)
        tracked = [path.relative_to(self.repo).as_posix() for path in sorted(self.repo.glob("src/**/*.btrc"))]
        reference = self.directory / "reference.json"
        return {
            "schema": SCHEMA,
            "stdlib": self.btrc_section(STDLIB, executable, executed, tracked),
            "selfhost_compiler": self.btrc_section(SELFHOST, executable, executed, tracked),
            "reference_compiler": self.reference_section(
                json.loads(reference.read_text(encoding="utf-8")) if reference.is_file() else {}
            ),
            "census_failed": census["failed"],
            "unrecorded_programs": LineCoverage.unrecorded_programs(self.directory / "lines"),
            "corpus_programs": sum(
                1 for records in (self.directory / "lines").glob("*.jsonl") for line in records.open() if line.strip()
            ),
        }

    @staticmethod
    def markdown(report: Mapping) -> str:
        def row(name: str, entry: Mapping) -> str:
            percent = "n/a" if entry["percent"] is None else f"{entry['percent']:.1f}%"
            return f"| {name} | {entry['lines']} | {entry['executed']} | {percent} |"

        sections = (
            ("Standard library (`src/stdlib`)", "stdlib"),
            ("Self-hosted compiler (`src/compiler/btrc`)", "selfhost_compiler"),
            ("Reference compiler (`src/compiler/python`)", "reference_compiler"),
        )
        text = ["# Line coverage", "", "| Tree | Lines | Executed | Covered |", "|---|---:|---:|---:|"]
        text += [row(title, report[key]) for title, key in sections]
        text += ["", f"Corpus programs recorded: {report['corpus_programs']}."]
        if report["census_failed"]:
            text += [
                "",
                f"{len(report['census_failed'])} stdlib modules could not be compiled alone for the census, so only "
                "the lines a test program reaches count for them: " + ", ".join(sorted(report["census_failed"])) + ".",
            ]
        if report["unrecorded_programs"]:
            text += [
                "",
                f"{len(report['unrecorded_programs'])} corpus programs ran and left no gcov data, so what they "
                "execute is not counted (gcov writes at exit, and these end another way): "
                + ", ".join(report["unrecorded_programs"])
                + ".",
            ]
        for title, key in sections:
            text += ["", f"## {title}", "", "| Package | Lines | Executed | Covered |", "|---|---:|---:|---:|"]
            text += [row(name, entry) for name, entry in report[key]["packages"].items()]
            unreached = [
                path for path, entry in report[key]["files"].items() if entry["lines"] and not entry["executed"]
            ]
            if unreached:
                text += ["", f"Files with code that no test executes ({len(unreached)}): " + ", ".join(unreached) + "."]
        return "\n".join(text) + "\n"

    def write(self) -> dict[str, object]:
        report = self.build()
        (self.directory / "report.json").write_text(
            json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        (self.directory / "report.md").write_text(self.markdown(report), encoding="utf-8")
        return report


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Line coverage of the standard library and both compilers.")
    parser.add_argument("action", choices=("census", "selfhost-build", "report"))
    parser.add_argument("--output", type=Path, default=Path("build/coverage"))
    parser.add_argument("--workers", default="8")
    options = parser.parse_args(arguments)
    directory = (REPO / options.output).resolve()
    if not directory.is_relative_to(REPO / "build"):
        parser.error("the coverage directory stays beneath build/")
    if options.action == "census":
        # A census starts a run: nothing of an earlier one may be counted again.
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
        workers = os.cpu_count() or 1 if options.workers == "auto" else int(options.workers)
        census = StdlibCensus(REPO, directory).take(workers)
        (directory / "census.json").write_text(json.dumps(census, sort_keys=True) + "\n", encoding="utf-8")
        print(
            f"census: {len(census['lines'])} stdlib files carry code; {census['private']} modules are private to "
            f"their package; {len(census['failed'])} could not be compiled alone"
        )
    elif options.action == "selfhost-build":
        print(InstrumentedCompiler(REPO, directory).build())
    else:
        report = CoverageReport(REPO, directory).write()
        for name in ("stdlib", "selfhost_compiler", "reference_compiler"):
            entry = report[name]
            print(f"{name}: {entry['executed']} of {entry['lines']} lines ({entry['percent']}%)")
        print(directory / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
