"""Re-check the recorded host facts of the platform toolchain matrix.

``docs/design/platform-toolchain-matrix.md`` pins the toolchain for every
host/target slice and records what the acceptance Mac had installed when it
was pinned. Its "Recorded host" table, between the ``host-facts:begin`` and
``host-facts:end`` markers, is the single source of those facts: one row per
fact, giving the probe id, the read-only command that shows it, whether the
recorded text must be ``present`` or ``absent``, and the text itself.

A ``present`` fact holds when the command exits 0 and its combined
stdout/stderr contains the text (``java -version`` writes to stderr). An
``absent`` fact holds when the command is missing, exits non-zero, or its
output lacks the text -- "no JDK" and "no iOS 17 simulator runtime" are
facts too, and installing one is a change the matrix has to record.

The facts describe the macOS host, so on any other system every probe is
reported as not applicable and the command exits 0. On macOS it prints each
mismatch and exits 1 when there is one. Nothing is installed or changed::

    python3 -m tools.qualification.toolchain
    python3 -m tools.qualification.toolchain --matrix docs/design/platform-toolchain-matrix.md
"""

from __future__ import annotations

import argparse
import enum
import hashlib
import json
import os
import platform as host_platform
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MATRIX = REPO / "docs/design/platform-toolchain-matrix.md"
BEGIN = "<!-- host-facts:begin -->"
END = "<!-- host-facts:end -->"
# The recorded facts are the acceptance Mac's; `platform.system()` spells it this way.
APPLICABLE_SYSTEM = "Darwin"
# A dev-shell probe may have to realise the flake's shell first.
COMMAND_TIMEOUT_SECONDS = 300


class ToolchainMatrixError(ValueError):
    """The matrix's recorded-host table is missing or malformed."""


class Expectation(enum.Enum):
    PRESENT = "present"
    ABSENT = "absent"


class ProbeStatus(enum.Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    NOT_APPLICABLE = "not-applicable"


@dataclass(frozen=True)
class CommandResult:
    """What one probe command printed; `returncode` is None when it could not run."""

    returncode: int | None
    output: str

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class HostFact:
    """One recorded host fact: `text` is `expectation` in `command`'s output."""

    probe: str
    command: tuple[str, ...]
    expectation: Expectation
    text: str

    def holds(self, result: CommandResult) -> bool:
        found = result.succeeded and self.text in result.output
        return found if self.expectation is Expectation.PRESENT else not found


@dataclass(frozen=True)
class ProbeOutcome:
    fact: HostFact
    status: ProbeStatus
    observed: str = ""

    def line(self) -> str:
        command = shlex.join(self.fact.command)
        recorded = f"{self.fact.expectation.value} {self.fact.text!r}"
        if self.status is ProbeStatus.MISMATCH:
            return f"MISMATCH {self.fact.probe}: recorded {recorded}; `{command}` gave {self.observed!r}"
        return f"{self.status.value} {self.fact.probe}: {recorded} (`{command}`)"


class ToolchainMatrix:
    """The recorded-host table of the toolchain matrix document."""

    def __init__(self, facts: Sequence[HostFact]) -> None:
        self.facts = tuple(facts)

    @classmethod
    def load(cls, path: Path = MATRIX) -> ToolchainMatrix:
        return cls.parse(path.read_text(encoding="utf-8"))

    @classmethod
    def parse(cls, text: str) -> ToolchainMatrix:
        if BEGIN not in text or END not in text:
            raise ToolchainMatrixError(f"no {BEGIN} ... {END} table")
        table = text.split(BEGIN, 1)[1].split(END, 1)[0]
        facts: list[HostFact] = []
        seen: set[str] = set()
        for line in table.splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 4 or not line.lstrip().startswith("|") or set(cells[0]) <= {"-", ":", " "}:
                continue
            probe, command, expectation, recorded = (cls.unquote(cell) for cell in cells[:4])
            if probe == "Probe":
                continue
            if probe in seen:
                raise ToolchainMatrixError(f"probe {probe!r} is recorded twice")
            try:
                expected = Expectation(expectation)
            except ValueError as error:
                message = f"probe {probe!r}: expectation {expectation!r} is not present/absent"
                raise ToolchainMatrixError(message) from error
            if not command or not recorded:
                raise ToolchainMatrixError(f"probe {probe!r} needs a command and a recorded value")
            seen.add(probe)
            facts.append(HostFact(probe, tuple(shlex.split(command)), expected, recorded))
        if not facts:
            raise ToolchainMatrixError("the recorded-host table has no facts")
        return cls(facts)

    @staticmethod
    def unquote(cell: str) -> str:
        return cell[1:-1] if len(cell) >= 2 and cell[0] == cell[-1] == "`" else cell


class HostProbe:
    """Run each fact's command once and compare it with the record."""

    def __init__(
        self,
        system: str | None = None,
        runner: Callable[[tuple[str, ...]], CommandResult] | None = None,
        cwd: Path = REPO,
    ) -> None:
        self.system = system if system is not None else host_platform.system()
        self.runner = runner or self.run_command
        self.cwd = cwd

    @property
    def applicable(self) -> bool:
        return self.system == APPLICABLE_SYSTEM

    def check(self, matrix: ToolchainMatrix) -> list[ProbeOutcome]:
        if not self.applicable:
            return [ProbeOutcome(fact, ProbeStatus.NOT_APPLICABLE) for fact in matrix.facts]
        results: dict[tuple[str, ...], CommandResult] = {}
        outcomes = []
        for fact in matrix.facts:
            if fact.command not in results:
                results[fact.command] = self.runner(fact.command)
            result = results[fact.command]
            status = ProbeStatus.MATCH if fact.holds(result) else ProbeStatus.MISMATCH
            outcomes.append(ProbeOutcome(fact, status, self.observed(result)))
        return outcomes

    @staticmethod
    def observed(result: CommandResult) -> str:
        if result.returncode is None:
            return "command not found"
        first = next((line.strip() for line in result.output.splitlines() if line.strip()), "")
        return f"exit {result.returncode}: {first}" if first else f"exit {result.returncode}"

    def run_command(self, command: tuple[str, ...]) -> CommandResult:
        try:
            completed = subprocess.run(
                list(command),
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return CommandResult(None, "")
        return CommandResult(completed.returncode, completed.stdout + completed.stderr)


class NativeReaderProbe:
    """Retain reader launch prerequisites without realizing or repairing store paths."""

    def __init__(self, root: Path, evidence: Path, runner=None) -> None:
        self.root = root
        self.evidence = evidence
        self.runner = runner or subprocess.run

    @staticmethod
    def observe(path: Path) -> dict:
        row = {"path": str(path), "exists": path.exists(), "executable": os.access(path, os.X_OK)}
        try:
            row["mode"] = path.lstat().st_mode
            row["resolved"] = str(path.resolve(strict=True))
            if path.is_symlink():
                row["link"] = os.readlink(path)
            if path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                row["sha256"] = digest.hexdigest()
        except OSError as error:
            row["error"] = str(error)
        return row

    def capture(self, phase: str) -> int:
        self.evidence.mkdir(parents=True, exist_ok=True)
        previous = {}
        previous_error = None
        if phase == "post":
            try:
                previous = json.loads((self.evidence / "pre.json").read_text())
            except (OSError, ValueError) as error:
                previous_error = str(error)
        root = self.observe(self.root)
        # Keep probing the admitted store output even if its out-link disappears.
        store = Path(previous.get("store", root.get("resolved", str(self.root))))
        reader = store / "bin/btrc-native-header"
        files = {"reader": self.observe(reader), "backend": self.observe(store / "bin/.btrc-native-header-wrapped")}
        shebang = ""
        try:
            with reader.open("rb") as stream:
                shebang = stream.readline(4096).decode("utf-8").rstrip()
        except (OSError, UnicodeError) as error:
            files["reader"]["header_error"] = str(error)
        # A shebang carries an executable and at most one optional argument.
        # Preserve the latter verbatim; it is not a shell command to tokenize.
        words = shebang[2:].split(maxsplit=1) if shebang.startswith("#!") else []
        interpreter = words[0] if words and words[0].startswith("/") else None
        interpreter_arguments = words[1:]
        if interpreter is None:
            interpreter = previous.get("files", {}).get("interpreter", {}).get("path")
        if interpreter is not None:
            files["interpreter"] = self.observe(Path(interpreter))
        command = ["nix-store", "--query", "--requisites", str(store)]
        try:
            result = self.runner(command, capture_output=True, text=True, check=False, timeout=30)
            query = {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except (OSError, subprocess.TimeoutExpired) as error:
            query = {"command": command, "returncode": None, "error": str(error)}
        paths = set(previous.get("closure", {}))
        if query["returncode"] == 0:
            paths.update(query["stdout"].splitlines())
        closure = {path: Path(path).exists() for path in sorted(paths)}
        valid_shebang = bool(words and words[0].startswith("/"))
        usable = (
            root.get("resolved") == str(store)
            and valid_shebang
            and "interpreter" in files
            and all(row["exists"] and row["executable"] and "sha256" in row for row in files.values())
            and query["returncode"] == 0
            and str(store) in closure
            and all(closure.values())
        )
        unchanged = phase == "pre" or (
            previous.get("usable") is True
            and previous.get("store") == str(store)
            and previous.get("shebang") == shebang
            and previous.get("files") == files
            and previous.get("closure") == closure
        )
        report = {
            "phase": phase,
            "observer": {"executable": sys.executable, "version": sys.version},
            "store": str(store),
            "root": root,
            "shebang": shebang,
            "interpreter_arguments": interpreter_arguments,
            "files": files,
            "query": query,
            "closure": closure,
            "usable": usable,
            "unchanged": unchanged,
            "previous_error": previous_error,
        }
        (self.evidence / (phase + ".json")).write_text(json.dumps(report, indent=2) + "\n")
        return 0 if usable and unchanged else 1


class ToolchainProbeCommand:
    """``python3 -m tools.qualification.toolchain``: print every probe, fail on a mismatch."""

    def __init__(self, probe: HostProbe | None = None) -> None:
        self.probe = probe or HostProbe()

    def run(self, argv: list[str] | None = None) -> int:
        parser = argparse.ArgumentParser(prog="python3 -m tools.qualification.toolchain", description=__doc__)
        parser.add_argument("--matrix", type=Path, default=MATRIX, help="the toolchain matrix document")
        parser.add_argument("--reader-root", type=Path, help="observe a job-owned native reader out-link")
        parser.add_argument("--evidence", type=Path, help="directory for pre/post reader facts")
        parser.add_argument("--phase", choices=("pre", "post"))
        arguments = parser.parse_args(argv)
        if arguments.reader_root is not None:
            if arguments.evidence is None or arguments.phase is None:
                parser.error("--reader-root requires --evidence and --phase")
            return NativeReaderProbe(arguments.reader_root, arguments.evidence).capture(arguments.phase)
        if arguments.evidence is not None or arguments.phase is not None:
            parser.error("--evidence and --phase require --reader-root")
        try:
            matrix = ToolchainMatrix.load(arguments.matrix)
        except (ToolchainMatrixError, OSError) as error:
            print(f"toolchain: {error}", file=sys.stderr)
            return 2
        outcomes = self.probe.check(matrix)
        if not self.probe.applicable:
            print(f"toolchain: the recorded host facts are macOS facts; this is {self.probe.system or 'unknown'}")
        for outcome in outcomes:
            print(outcome.line())
        mismatches = sum(outcome.status is ProbeStatus.MISMATCH for outcome in outcomes)
        if self.probe.applicable:
            print(f"toolchain: {len(outcomes) - mismatches} of {len(outcomes)} recorded host facts match")
        return 1 if mismatches else 0


def main(argv: list[str] | None = None) -> int:
    return ToolchainProbeCommand().run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
