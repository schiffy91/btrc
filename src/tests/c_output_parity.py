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
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

REPO = Path(__file__).resolve().parents[2]
TEST_DIRECTORY = REPO / "src" / "tests"
IDENTICAL_MANIFEST = TEST_DIRECTORY / "fixtures" / "c_output_parity" / "identical.txt"
CHECKOUT_TOKEN = "<checkout>"

# A compiler-generated temporary: `__btrc_<role>_<counter>`.
_TEMPORARY = re.compile(r"\b__btrc_[A-Za-z_]*?_\d+\b")
_FUNCTION_POINTER_TYPEDEF = re.compile(r"^typedef\b.*\(\s*\*")
# Lines only the pre-authored runtime assets emit at file scope: their
# comments, their preprocessor conditionals, and their `__btrc_` definitions.
_RUNTIME_LINE = re.compile(r"^(/\*| \*|#(if|elif|else|endif|define|undef)\b|static\b.*\b__btrc_\w+\s*[(=;\[])")


@dataclass(frozen=True)
class ParityResult:
    """One program's comparison: identical, a classified difference, or a failure."""

    program: str
    category: str
    python_line: str = ""
    btrcc_line: str = ""
    line_number: int = 0

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

    @classmethod
    def classify(cls, program: str, python_source: str, btrcc_source: str) -> ParityResult:
        if python_source == btrcc_source:
            return ParityResult(program, "identical")
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

    def run(self, argv: list[str]) -> int:
        parser = argparse.ArgumentParser(prog="python3 -m src.tests.c_output_parity")
        parser.add_argument("operation", choices=["survey"])
        parser.add_argument("--btrcc", required=True, type=Path)
        parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
        parser.add_argument("--filter", default="", help="only programs whose path contains this text")
        parser.add_argument("--details", type=Path, help="write every difference to this file")
        parser.add_argument("--write-manifest", action="store_true")
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
        for category, count in histogram.most_common():
            print(f"  {category:28} {count}")
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
