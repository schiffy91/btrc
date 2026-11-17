"""Which lines of BTRC source the corpus executes (`make coverage`).

The reference compiler can stamp every statement it emits with the BTRC line
it came from (`debug`). A corpus program built that way, unoptimised and with
gcov's instrumentation, tells gcov which BTRC lines it ran: the program's own
and the standard library's. With ``BTRC_TEST_LINE_COVERAGE`` naming a
directory, the corpus runner builds its reference-compiler programs so and
calls `LineCoverage.record` after each has run; `tools/line_coverage.py` adds
the records up into the report.

The notes and data are GCC's, so the job needs gcc and the gcov beside it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from src.tests.process_limits import TOOL_TIMEOUT

REPO = Path(__file__).resolve().parents[2]
# One file's lines: line number -> how often it ran; 0 is a line that carries code and did not run.
Lines = dict[int, int]


class LineCoverage:
    """Record, per corpus program, the BTRC lines gcov saw it execute."""

    VARIABLE = "BTRC_TEST_LINE_COVERAGE"
    # Unoptimised, so a statement stays on its line, and instrumented for gcov. A lambda's body is emitted
    # after the function it is written in, so its lines run backwards for GCC, which says so and carries on.
    FLAGS = ("-O0", "--coverage", "-Wno-error=coverage-invalid-line-number")
    # The BTRC trees a report covers.
    ROOTS = ("src/stdlib", "src/compiler/btrc")

    def __init__(self, directory: Path, *, repo: Path = REPO, gcov: str = "gcov") -> None:
        self.directory = directory
        self.repo = repo.resolve()
        self.gcov = gcov

    @classmethod
    def configured(cls) -> LineCoverage | None:
        raw = os.environ.get(cls.VARIABLE)
        if raw is None:
            return None
        if not raw.strip() or not Path(raw).is_absolute():
            raise ValueError(f"{cls.VARIABLE} must be an absolute directory path")
        return cls(Path(raw))

    def record(self, binary: Path, *directories: Path) -> bool:
        """Add up what the program at `binary` executed; False when it left no data.

        gcov's data lies beside the binary, named after it, and under each of
        `directories` (the objects of a program built from a native plan). The
        data and its notes are removed: the record is what is kept.
        """

        data = sorted(
            {
                *binary.parent.glob(f"{binary.name}*.gcda"),
                *(path for root in directories for path in root.rglob("*.gcda")),
            }
        )
        lines: dict[str, Lines] = {}
        for path in data:
            self.add(lines, self.lines_of(self.read(path)))
        for path in data:
            path.unlink(missing_ok=True)
            path.with_suffix(".gcno").unlink(missing_ok=True)
        if lines:
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / f"{os.getpid()}.jsonl").open("a", encoding="utf-8") as records:
                records.write(json.dumps(lines, sort_keys=True) + "\n")
        return bool(data)

    @staticmethod
    def keeping_notes(directory: Path, run):
        """A tool runner that keeps gcov's notes of every object it compiles.

        A native plan's objects are built in a directory that is removed once
        the program is linked, and the notes beside them with it. Each is
        copied under `directory` at its own absolute path, which is where a
        program run with ``GCOV_PREFIX=directory`` then writes its data.
        """

        def watched(command, **options):
            result = run(command, **options)
            command = [str(argument) for argument in command]
            if result.returncode == 0 and "-c" in command and "-o" in command:
                produced = Path(options.get("cwd") or ".", command[command.index("-o") + 1]).resolve()
                notes = produced.with_suffix(".gcno")
                if notes.is_file():
                    kept = directory / notes.relative_to(notes.anchor)
                    kept.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(notes, kept)
            return result

        return watched

    def unrecorded(self, program: str) -> None:
        """Name a program that ran and left no data, so the report can say what it does not count."""

        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / f"{os.getpid()}.unrecorded").open("a", encoding="utf-8") as names:
            names.write(program + "\n")

    @classmethod
    def unrecorded_programs(cls, directory: Path) -> list[str]:
        return sorted(
            {name for names in directory.glob("*.unrecorded") for name in names.read_text().split("\n") if name}
        )

    def read(self, data: Path) -> Mapping:
        """gcov's JSON for one data or notes file; a notes file alone lists every line as not executed."""

        result = subprocess.run(
            [self.gcov, "--json-format", "--stdout", data.name],
            cwd=data.parent,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(f"gcov could not read {data}: {result.stderr.strip()}")
        return json.loads(result.stdout)

    def lines_of(self, document: Mapping) -> dict[str, Lines]:
        """The lines of tracked BTRC files in one gcov document, by path relative to the repository."""

        base = Path(document.get("current_working_directory") or ".")
        found: dict[str, Lines] = {}
        for entry in document.get("files", []):
            path = Path(os.path.realpath(base / entry["file"]))
            if path.suffix != ".btrc" or not path.is_relative_to(self.repo):
                continue
            relative = path.relative_to(self.repo).as_posix()
            if not relative.startswith(tuple(f"{root}/" for root in self.ROOTS)):
                continue
            counts = found.setdefault(relative, {})
            # A line shared by several functions (a generic's instances) is listed once for each.
            for line in entry.get("lines", []):
                number = int(line["line_number"])
                counts[number] = counts.get(number, 0) + int(line["count"])
        return found

    @staticmethod
    def add(total: dict[str, Lines], more: Mapping[str, Mapping[int, int]]) -> None:
        for file, lines in more.items():
            counts = total.setdefault(file, {})
            for number, count in lines.items():
                counts[int(number)] = counts.get(int(number), 0) + int(count)

    @classmethod
    def total(cls, directory: Path) -> dict[str, Lines]:
        """Every record under `directory`, added up."""

        total: dict[str, Lines] = {}
        for records in sorted(directory.glob("*.jsonl")):
            with records.open(encoding="utf-8") as lines:
                for line in lines:
                    if line.strip():
                        cls.add(total, json.loads(line))
        return total
