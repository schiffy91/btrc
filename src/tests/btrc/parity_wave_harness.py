"""Compile one program through both compilers, then build and run each one's C under strict C11.

The parity waves (``test_parity_wave_*.py``) hold each disagreement they fix
to one rule: an accepted program is accepted by both compilers with no
diagnostic, and its C builds under strict C11 and prints the same; a refused
one is refused by both with the same rendered diagnostic.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from src.tests.c_toolchains import configured_c_compiler
from src.tests.process_limits import C_COMPILE_TIMEOUT, RUN_TIMEOUT, TRANSPILE_TIMEOUT

REPO = Path(__file__).resolve().parents[3]
STRICT_C11 = ("-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror")
DIAGNOSTIC = re.compile(r"^(?:error|warning): ", re.MULTILINE)


@dataclass(frozen=True)
class Outcome:
    """One compiler's result: its exit status, rendered diagnostics and C."""

    returncode: int
    diagnostics: tuple[str, ...]
    c_path: Path


class ParityHarness:
    """Compile one program through both compilers, then build and run its C."""

    def __init__(self, btrcc: Path, workspace: Path) -> None:
        self._btrcc = btrcc
        self._workspace = workspace

    def compile(self, name: str, source: str) -> tuple[Outcome, Outcome]:
        path = self._workspace / f"{name}.btrc"
        path.write_text(source, encoding="utf-8")
        return self.compile_path(path)

    def compile_path(self, path: Path) -> tuple[Outcome, Outcome]:
        """Compile a program already on disk, such as one in a package with native bindings."""
        reference_c = self._workspace / f"{path.stem}.reference.c"
        selfhost_c = self._workspace / f"{path.stem}.selfhost.c"
        reference = subprocess.run(
            [sys.executable, "-m", "src.compiler.python.main", str(path), "--no-cache", "-o", str(reference_c)],
            cwd=REPO,
            capture_output=True,
            text=True,
            env={**os.environ, "BTRC_CACHE_DIR": str(self._workspace / "reference-cache")},
            timeout=TRANSPILE_TIMEOUT,
        )
        selfhost = subprocess.run(
            [str(self._btrcc), str(path), "--no-cache", "-o", str(selfhost_c)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=TRANSPILE_TIMEOUT,
        )
        return (
            Outcome(reference.returncode, self._blocks(reference.stderr), reference_c),
            Outcome(selfhost.returncode, self._blocks(selfhost.stderr), selfhost_c),
        )

    def run(self, outcome: Outcome) -> str:
        """Build one compiler's C under strict C11 and return what it prints."""
        executable = outcome.c_path.with_suffix(".exe")
        built = subprocess.run(
            [*configured_c_compiler(), *STRICT_C11, str(outcome.c_path), "-o", str(executable), "-lm", "-lpthread"],
            capture_output=True,
            text=True,
            timeout=C_COMPILE_TIMEOUT,
        )
        assert built.returncode == 0, built.stderr
        ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=RUN_TIMEOUT)
        assert ran.returncode == 0, (ran.stdout, ran.stderr)
        return ran.stdout

    def accepted(self, name: str, source: str) -> tuple[str, str]:
        """Both compilers accept with no diagnostic; return each program's output."""
        return self.accepted_outcomes(*self.compile(name, source))

    def accepted_outcomes(self, reference: Outcome, selfhost: Outcome) -> tuple[str, str]:
        """Both compilers accepted with no diagnostic; return each program's output."""
        assert reference.returncode == 0 and not reference.diagnostics, reference.diagnostics
        assert selfhost.returncode == 0 and not selfhost.diagnostics, selfhost.diagnostics
        return self.run(reference), self.run(selfhost)

    def refused(self, name: str, source: str) -> str:
        """Both compilers refuse with one identical diagnostic; return it."""
        reference, selfhost = self.compile(name, source)
        assert reference.returncode != 0 and selfhost.returncode != 0, (reference, selfhost)
        assert len(reference.diagnostics) == 1, reference.diagnostics
        assert reference.diagnostics == selfhost.diagnostics
        return reference.diagnostics[0]

    @staticmethod
    def _blocks(stderr: str) -> tuple[str, ...]:
        """Each rendered diagnostic: its message, location and source excerpt."""
        starts = [match.start() for match in DIAGNOSTIC.finditer(stderr)]
        ends = [*starts[1:], len(stderr)] if starts else []
        return tuple(stderr[start:end].rstrip("\n") for start, end in zip(starts, ends, strict=True))


def message(block: str) -> str:
    """A rendered diagnostic's first line: its severity and message."""
    return block.splitlines()[0]
