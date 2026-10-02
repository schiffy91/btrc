"""Whole-program C parity between the two compilers.

Both compilers transpile the same corpus program; the only normalization is the
absolute checkout path, which each compiler embeds (`#line` markers, embedded
source paths) and which differs between checkouts, never between compilers.
Every other byte is compared.

``COutputParitySurvey`` transpiles programs with both compilers and classifies
the first difference of each pair. ``python3 -m src.tests.c_output_parity
survey`` measures the whole corpus and prints the byte-identical count and the
first-difference histogram; ``--write-manifest`` records the identical set in
``IDENTICAL_MANIFEST``, which ``test_c_output_parity.py`` pins: a program
listed there must keep transpiling to identical C through both compilers.

Two narrower views are measured beside the whole translation unit. The
*user declarations* view removes every pre-authored runtime helper, whose text
both compilers copy from the shared runtime catalog, so it compares only what
each compiler lowered from the program. ``--module-units`` also builds every
program with ``--module-units --emit-units`` through both command lines and
compares each emitted unit.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

REPO = Path(__file__).resolve().parents[2]
TEST_DIRECTORY = REPO / "src" / "tests"
IDENTICAL_MANIFEST = TEST_DIRECTORY / "fixtures" / "c_output_parity" / "identical.txt"
CHECKOUT_TOKEN = "<checkout>"
UNITS_TOKEN = "<units>"

# A compiler-generated temporary: `__btrc_<role>_<counter>`.
_TEMPORARY = re.compile(r"\b__btrc_[A-Za-z_]*?_\d+\b")
_FUNCTION_POINTER_TYPEDEF = re.compile(r"^typedef\b.*\(\s*\*")
# Lines only the pre-authored runtime assets emit at file scope: their
# comments, their preprocessor conditionals, and their `__btrc_` definitions.
_RUNTIME_LINE = re.compile(r"^(/\*| \*|#(if|elif|else|endif|define|undef)\b|static\b.*\b__btrc_\w+\s*[(=;\[])")
_BLANK_RUNS = re.compile(r"\n{3,}")


def _runtime_helper_texts() -> tuple[str, ...]:
    from src.compiler.python.runtime.generated import RUNTIME_HELPER_ROWS

    # Longest first, so a helper that contains another is removed whole.
    return tuple(sorted({row.c_source for row in RUNTIME_HELPER_ROWS if row.c_source}, key=len, reverse=True))


_RUNTIME_HELPER_TEXTS = _runtime_helper_texts()


@dataclass(frozen=True)
class ParityResult:
    """One program's comparison: identical, a classified difference, or a failure."""

    program: str
    category: str
    python_line: str = ""
    btrcc_line: str = ""
    line_number: int = 0
    user_identical: bool = False

    @property
    def identical(self) -> bool:
        return self.category == "identical"


class COutputParitySurvey:
    """Transpiles corpus programs through both compilers and compares the C."""

    def __init__(self, btrcc: Path, *, timeout: float = 300.0) -> None:
        self.btrcc = Path(btrcc)
        self.timeout = timeout
        self._compiler = None

    @staticmethod
    def corpus_programs() -> list[str]:
        from src.tests.corpus_files import language_test_files

        return [Path(program).as_posix() for program in language_test_files(TEST_DIRECTORY)]

    @staticmethod
    def manifest_programs() -> list[str]:
        lines = IDENTICAL_MANIFEST.read_text(encoding="utf-8").splitlines()
        return [line.strip() for line in lines if line.strip() and not line.startswith("#")]

    @staticmethod
    def normalize(c_source: str) -> str:
        return c_source.replace(str(REPO), CHECKOUT_TOKEN)

    def python_c(self, program: str) -> str:
        from src.compiler.python import Compiler, CompilerOptions

        if self._compiler is None:
            self._compiler = Compiler()
        path = TEST_DIRECTORY / program
        result = self._compiler.compile(
            path.read_text(encoding="utf-8"),
            str(path),
            CompilerOptions(map_stdlib_positions=True, use_cache=False),
        )
        if result.failure is not None or result.c_source is None:
            raise RuntimeError(f"python: {result.failure}")
        return self.normalize(result.c_source)

    def btrcc_c(self, program: str) -> str:
        completed = subprocess.run(
            [str(self.btrcc), str(TEST_DIRECTORY / program)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"btrcc: {completed.stderr[:500]}")
        return self.normalize(completed.stdout)

    def compare(self, program: str) -> ParityResult:
        try:
            python_source = self.python_c(program)
            btrcc_source = self.btrcc_c(program)
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            return ParityResult(program, "failure", python_line=str(error))
        return self.classify(program, python_source, btrcc_source)

    @staticmethod
    def user_declarations(c_source: str) -> str:
        """The translation unit without the runtime catalog's helper definitions."""
        for helper in _RUNTIME_HELPER_TEXTS:
            c_source = c_source.replace(helper, "")
        return _BLANK_RUNS.sub("\n\n", c_source)

    def module_units(self, program: str, command: list[str]) -> dict[str, str]:
        """Build one program as module units; return each unit's normalized text."""
        with tempfile.TemporaryDirectory(prefix="btrc-units-") as scratch:
            output = Path(scratch) / "out"
            output.mkdir()
            completed = subprocess.run(
                [
                    *command,
                    str(TEST_DIRECTORY / program),
                    "-o",
                    str(output / "program.c"),
                    "--emit-units",
                    str(output / "program"),
                    "--module-units",
                    "--jobs",
                    "1",
                ],
                cwd=REPO,
                env={**os.environ, "BTRC_CACHE_DIR": str(Path(scratch).resolve() / "cache")},
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if completed.returncode != 0:
                raise RuntimeError(f"{command[-1]}: {completed.stderr[:500]}")
            return {
                path.name: self.normalize(path.read_text(encoding="utf-8")).replace(str(output), UNITS_TOKEN)
                for path in sorted(output.glob("program*.c"))
            }

    def compare_units(self, program: str) -> tuple[int, int]:
        """Identical and total module units of one program, failures counting as different."""
        try:
            python_units = self.module_units(program, [sys.executable, "-m", "src.compiler.python.main"])
            btrcc_units = self.module_units(program, [str(self.btrcc)])
        except (RuntimeError, subprocess.TimeoutExpired):
            return 0, 1
        names = sorted(set(python_units) | set(btrcc_units))
        identical = sum(1 for name in names if python_units.get(name) == btrcc_units.get(name))
        return identical, len(names)

    @classmethod
    def classify(cls, program: str, python_source: str, btrcc_source: str) -> ParityResult:
        if python_source == btrcc_source:
            return ParityResult(program, "identical", user_identical=True)
        user_identical = cls.user_declarations(python_source) == cls.user_declarations(btrcc_source)
        python_lines = python_source.split("\n")
        btrcc_lines = btrcc_source.split("\n")
        index = 0
        while index < min(len(python_lines), len(btrcc_lines)) and python_lines[index] == btrcc_lines[index]:
            index += 1
        python_line = python_lines[index] if index < len(python_lines) else "<end>"
        btrcc_line = btrcc_lines[index] if index < len(btrcc_lines) else "<end>"
        return ParityResult(
            program,
            cls.category(python_line, btrcc_line),
            python_line=python_line,
            btrcc_line=btrcc_line,
            line_number=index + 1,
            user_identical=user_identical,
        )

    @staticmethod
    def category(python_line: str, btrcc_line: str) -> str:
        pair = (python_line, btrcc_line)
        if any(line.startswith("#include") for line in pair):
            return "include"
        if any(line.startswith("#line") for line in pair):
            return "line-marker"
        if any(_RUNTIME_LINE.match(line) for line in pair):
            return "runtime-helper"
        if any(_FUNCTION_POINTER_TYPEDEF.match(line) for line in pair):
            return "function-pointer-typedef"
        if _TEMPORARY.search(python_line) or _TEMPORARY.search(btrcc_line):
            if _TEMPORARY.sub("__btrc_T", python_line) == _TEMPORARY.sub("__btrc_T", btrcc_line):
                return "temporary-name"
            return "temporary-lowering"
        if any(line.startswith(("typedef", "struct")) for line in pair):
            return "type-declaration"
        if any(line.startswith(("static", "void", "int")) and line.endswith(";") for line in pair):
            return "prototype"
        return "other"


class COutputParityCommand:
    """``survey``: measure the corpus, optionally recording the identical set."""

    # One survey per worker process, so each keeps its Python compiler warm.
    _worker_surveys: ClassVar[dict[str, COutputParitySurvey]] = {}

    @classmethod
    def compare_in_worker(cls, arguments: tuple[str, str]) -> ParityResult:
        btrcc, program = arguments
        survey = cls._worker_surveys.setdefault(btrcc, COutputParitySurvey(Path(btrcc)))
        return survey.compare(program)

    @classmethod
    def compare_units_in_worker(cls, arguments: tuple[str, str]) -> tuple[int, int]:
        btrcc, program = arguments
        survey = cls._worker_surveys.setdefault(btrcc, COutputParitySurvey(Path(btrcc)))
        return survey.compare_units(program)

    def run(self, argv: list[str]) -> int:
        parser = argparse.ArgumentParser(prog="python3 -m src.tests.c_output_parity")
        parser.add_argument("operation", choices=["survey"])
        parser.add_argument("--btrcc", required=True, type=Path)
        parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
        parser.add_argument("--filter", default="", help="only programs whose path contains this text")
        parser.add_argument("--details", type=Path, help="write every difference to this file")
        parser.add_argument("--write-manifest", action="store_true")
        parser.add_argument("--module-units", action="store_true", help="also compare every emitted module unit")
        arguments = parser.parse_args(argv)
        os.environ.setdefault("BTRC_HOME", str(REPO / "src"))
        programs = [program for program in COutputParitySurvey.corpus_programs() if arguments.filter in program]
        btrcc = str(arguments.btrcc.resolve())
        with ProcessPoolExecutor(max_workers=max(1, arguments.jobs)) as pool:
            results = list(
                pool.map(
                    COutputParityCommand.compare_in_worker, [(btrcc, program) for program in programs], chunksize=4
                )
            )
        histogram = Counter(result.category for result in results)
        identical = sorted(result.program for result in results if result.identical)
        print(f"byte-identical: {len(identical)} of {len(results)}")
        print(f"user declarations identical: {sum(result.user_identical for result in results)} of {len(results)}")
        for category, count in histogram.most_common():
            print(f"  {category:28} {count}")
        if arguments.module_units:
            with ProcessPoolExecutor(max_workers=max(1, arguments.jobs)) as pool:
                units = list(
                    pool.map(
                        COutputParityCommand.compare_units_in_worker,
                        [(btrcc, program) for program in programs],
                        chunksize=4,
                    )
                )
            identical_units = sum(identical for identical, _total in units)
            total_units = sum(total for _identical, total in units)
            whole = sum(1 for identical, total in units if identical == total)
            print(f"module units identical: {identical_units} of {total_units}")
            print(f"programs with every module unit identical: {whole} of {len(units)}")
        if arguments.details:
            with arguments.details.open("w", encoding="utf-8") as details:
                for result in sorted(results, key=lambda item: (item.category, item.program)):
                    if result.identical:
                        continue
                    details.write(f"[{result.category}] {result.program}:{result.line_number}\n")
                    details.write(f"  python: {result.python_line}\n  btrcc:  {result.btrcc_line}\n")
        if arguments.write_manifest:
            if arguments.filter:
                parser.error("--write-manifest measures the whole corpus; drop --filter")
            IDENTICAL_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
            header = (
                "# Corpus programs whose C is byte-identical through both compilers.\n"
                "# Regenerate: python3 -m src.tests.c_output_parity survey --btrcc <btrcc> --write-manifest\n"
            )
            IDENTICAL_MANIFEST.write_text(header + "".join(f"{program}\n" for program in identical), encoding="utf-8")
        return 0


if __name__ == "__main__":
    raise SystemExit(COutputParityCommand().run(sys.argv[1:]))
