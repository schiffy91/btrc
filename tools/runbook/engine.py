"""The runbook engine: one command per owner session, resumable cell by cell.

    tools/runbook/run.sh <preset> [<preset> ...] [options]

A preset (``tools/runbook/presets/<name>.toml``) is an ordered list of cells.
Each cell is one command, or one built-in action, run under a named lock,
optionally after the quiet check, with its log, output directory and a
checkpoint of its own. The engine:

1. checks the host (macOS unless --rehearsal), free disk and the
   ``build/test-btrcc`` cache;
2. clones btrc from ``~/.cache/btrc/hub.git`` and every BTRSmith pin from
   ``~/.cache/btrsmith/hub.git`` into ``~/.cache/{btrc,btrsmith}/clones/<preset>``,
   outside Google Drive, at SHAs it resolves once and records;
3. runs each cell not already finished, writing ``cells/<id>.json`` after it,
   so rerunning the same command resumes where the last one stopped;
4. hands the run to ``EvidencePublisher`` (summary, ingest, redaction, the
   evidence branch).

``--rehearsal`` runs anywhere: it clones from this checkout, takes Python
locks instead of ``withlock.sh`` and lets the quiet check report instead of
wait. ``--stand-in`` replaces BTRSmith with budget_bench's generated stand-in
and skips cells that need the real product. ``--dry-run`` takes one sample of
each scenario and never pushes. None of the three produces acceptance evidence,
and the summary says so.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import fnmatch
import hashlib
import itertools
import json
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import tomllib
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.runbook.quiet import QuietCheck, QuietRefused, QuietSettings, QuietTimeout

REPO = Path(__file__).resolve().parents[2]
PRESETS = REPO / "tools" / "runbook" / "presets"
ACCEPTANCE_HOST = "Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0"
LOCKS = ("gate", "bench", "linux-ci", "guest", "gui-capture", "signing", "btrcc-build")
GIT_TIMEOUT_S = 1800
KEEP_TEST_BTRCC = 20
DEFAULT_MIN_FREE_GB = 80.0
REHEARSAL_MIN_FREE_GB = 5.0
REHEARSAL_QUIET_WINDOW_S = 10.0
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][\w.:-]*)\}")
_RESULTS = ("exit", "budget-bench", "gate-summary", "failure-list", "instr", "attribution")
_ACTIONS = ("subset", "push")


class RunbookError(RuntimeError):
    """A preset, option or host problem that stops the run before or between cells."""


def say(text: str = "") -> None:
    print(text, flush=True)


# -- presets --------------------------------------------------------------------


@dataclass(frozen=True)
class CellSpec:
    """One cell after matrix expansion; strings still hold their placeholders."""

    id: str
    title: str
    command: tuple[str, ...] = ()
    action: str | None = None
    lock: str | None = None
    quiet: bool = False
    result: str = "exit"
    timeout_s: float = 4 * 3600.0
    retries: int = 0
    when: str = "always"
    stand_in: str = "run"
    optional: bool = False
    cwd: str = "btrc"
    shell: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    requires: tuple[str, ...] = ()
    provides: str | None = None
    tree: str | None = None
    owner_action: str | None = None
    failures: tuple[str, ...] = ()
    of: str | None = None
    allowed: str | None = None
    repo: str | None = None
    branch: str | None = None
    variables: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Budget:
    """A PLAN.md budget a budget-bench cell's report is compared against."""

    scenario: str
    limit: float
    frontend: str | None = None
    statistic: str | None = "median"
    fact: str | None = None
    label: str = ""

    def describe(self) -> str:
        measure = f"facts.{self.fact}" if self.fact else self.statistic
        scope = f"{self.frontend} " if self.frontend else ""
        return self.label or f"{scope}{self.scenario} {measure} <= {self.limit:g}"


@dataclass(frozen=True)
class Preset:
    """A parsed preset file."""

    name: str
    title: str
    packet: str
    kind: str
    on_failure: str
    before: tuple[str, ...]
    next_action: str
    btrc_ref: str
    pins: Mapping[str, str]
    branch_pin: str | None
    optional_pins: tuple[str, ...]
    variables: Mapping[str, str]
    rehearsal_variables: Mapping[str, str]
    collapse: tuple[str, ...]
    quiet_table: Mapping[str, Any]
    budgets: tuple[Budget, ...]
    regressions: tuple[Mapping[str, Any], ...]
    baseline: str | None
    evidence_repo: str
    raw_cells: tuple[Mapping[str, Any], ...]
    default_quiet: bool
    path: Path

    @classmethod
    def available(cls, directory: Path = PRESETS) -> list[str]:
        return sorted(path.stem for path in directory.glob("*.toml"))

    @classmethod
    def load(cls, name: str, directory: Path = PRESETS) -> Preset:
        path = Path(name) if name.endswith(".toml") else directory / f"{name}.toml"
        if not path.is_file():
            known = ", ".join(cls.available(directory)) or "none"
            raise RunbookError(f"no preset {name!r} (known: {known})")
        try:
            with path.open("rb") as stream:
                data = tomllib.load(stream)
        except tomllib.TOMLDecodeError as error:
            raise RunbookError(f"{path}: {error}") from error
        return cls.parse(data, path)

    @classmethod
    def parse(cls, data: Mapping[str, Any], path: Path) -> Preset:
        try:
            header = data["preset"]
            kind = header.get("kind", "measurement")
            if kind not in ("measurement", "gate"):
                raise RunbookError(f"{path}: preset.kind must be measurement or gate")
            on_failure = header.get("on_failure", "continue")
            if on_failure not in ("continue", "stop"):
                raise RunbookError(f"{path}: preset.on_failure must be continue or stop")
            if header.get("evidence_repo", "btrc") not in ("btrc", "btrsmith"):
                raise RunbookError(f"{path}: preset.evidence_repo must be btrc or btrsmith")
            btrsmith = data.get("btrsmith", {})
            pins = {str(label): str(ref) for label, ref in btrsmith.get("pins", {}).items()}
            branch_pin = btrsmith.get("branch_pin")
            if branch_pin is not None and branch_pin not in pins:
                raise RunbookError(f"{path}: btrsmith.branch_pin {branch_pin!r} is not a pin")
            budgets = tuple(
                Budget(
                    scenario=entry["scenario"],
                    limit=float(entry["limit"]),
                    frontend=entry.get("frontend"),
                    statistic=None if "fact" in entry else entry.get("statistic", "median"),
                    fact=entry.get("fact"),
                    label=entry.get("label", ""),
                )
                for entry in data.get("budget", [])
            )
            cells = tuple(data.get("cell", []))
            if not cells:
                raise RunbookError(f"{path}: a preset needs at least one [[cell]]")
            preset = cls(
                name=str(header.get("name", path.stem)),
                title=str(header["title"]),
                packet=str(header.get("packet", "")),
                kind=kind,
                on_failure=on_failure,
                before=tuple(header.get("before", ())),
                next_action=str(header.get("next_action", "")),
                btrc_ref=str(data.get("btrc", {}).get("ref", "main")),
                pins=pins,
                branch_pin=branch_pin or (next(iter(pins)) if len(pins) == 1 else None),
                optional_pins=tuple(btrsmith.get("optional", ())),
                variables={key: str(value) for key, value in data.get("variables", {}).items()},
                rehearsal_variables={
                    key: str(value) for key, value in data.get("rehearsal", {}).get("variables", {}).items()
                },
                collapse=tuple(data.get("stand_in", {}).get("collapse", ())),
                quiet_table=data.get("quiet", {}),
                budgets=budgets,
                regressions=tuple(data.get("regression", [])),
                baseline=header.get("baseline"),
                evidence_repo=str(header.get("evidence_repo", "btrc")),
                raw_cells=cells,
                default_quiet=bool(header.get("quiet", False)),
                path=path,
            )
        except KeyError as error:
            raise RunbookError(f"{path}: missing key {error}") from error
        preset.cells(stand_in=False)
        preset.cells(stand_in=True)
        return preset

    def cells(self, *, stand_in: bool) -> list[CellSpec]:
        """Every cell in order, each matrix expanded; ids are unique."""

        expanded: list[CellSpec] = []
        for raw in self.raw_cells:
            matrix: dict[str, list[str]] = {
                key: [str(value) for value in values] for key, values in raw.get("matrix", {}).items()
            }
            if stand_in:
                for axis in self.collapse:
                    if axis in matrix:
                        matrix[axis] = ["stand-in"]
            axes = list(matrix)
            for values in itertools.product(*(matrix[axis] for axis in axes)) if axes else [()]:
                variables = dict(zip(axes, values, strict=True))
                expanded.append(self.cell(raw, variables))
        seen: set[str] = set()
        for cell in expanded:
            if cell.id in seen:
                raise RunbookError(f"{self.path}: duplicate cell id {cell.id!r}")
            seen.add(cell.id)
        return expanded

    def cell(self, raw: Mapping[str, Any], variables: Mapping[str, str]) -> CellSpec:
        def fill(text: str) -> str:
            return _PLACEHOLDER.sub(lambda match: variables.get(match[1], match[0]), text)

        known = {
            "id", "title", "command", "action", "lock", "quiet", "result", "timeout_hours", "retries", "when",
            "stand_in", "optional", "cwd", "shell", "env", "requires", "provides", "tree", "owner_action",
            "failures", "of", "allowed", "repo", "branch", "matrix",
        }  # fmt: skip
        unknown = sorted(set(raw) - known)
        if unknown:
            raise RunbookError(f"{self.path}: cell {raw.get('id')!r} has unknown key(s) {', '.join(unknown)}")
        if "id" not in raw or ("command" in raw) == ("action" in raw):
            raise RunbookError(f"{self.path}: every cell needs an id and exactly one of command or action")
        cell = CellSpec(
            id=fill(raw["id"]),
            title=fill(raw.get("title", raw["id"])),
            command=tuple(fill(str(part)) for part in raw.get("command", ())),
            action=raw.get("action"),
            lock=raw.get("lock"),
            quiet=bool(raw.get("quiet", self.default_quiet)),
            result=raw.get("result", "exit"),
            timeout_s=float(raw.get("timeout_hours", 4)) * 3600,
            retries=int(raw.get("retries", 0)),
            when=raw.get("when", "always"),
            stand_in=raw.get("stand_in", "run"),
            optional=bool(raw.get("optional", False)),
            cwd=raw.get("cwd", "btrc"),
            shell=raw.get("shell"),
            env={key: fill(str(value)) for key, value in raw.get("env", {}).items()},
            requires=tuple(fill(item) for item in raw.get("requires", ())),
            provides=raw.get("provides"),
            tree=fill(raw["tree"]) if "tree" in raw else None,
            owner_action=raw.get("owner_action"),
            failures=tuple(raw.get("failures", ())),
            of=raw.get("of"),
            allowed=raw.get("allowed"),
            repo=raw.get("repo"),
            branch=raw.get("branch"),
            variables=dict(variables),
        )
        problems = []
        if cell.lock is not None and cell.lock not in LOCKS:
            problems.append(f"lock {cell.lock!r} is not one of {', '.join(LOCKS)}")
        if cell.result not in _RESULTS:
            problems.append(f"result {cell.result!r} is not one of {', '.join(_RESULTS)}")
        if cell.action is not None and cell.action not in _ACTIONS:
            problems.append(f"action {cell.action!r} is not one of {', '.join(_ACTIONS)}")
        if cell.when not in ("always", "green"):
            problems.append("when must be always or green")
        if cell.stand_in not in ("run", "skip"):
            problems.append("stand_in must be run or skip")
        if cell.cwd not in ("btrc", "btrsmith", "tree", "out"):
            problems.append("cwd must be btrc, btrsmith, tree or out")
        if cell.shell not in (None, "btrsmith"):
            problems.append("shell must be btrsmith when given")
        if cell.action == "subset" and not (cell.of and cell.allowed):
            problems.append("a subset action needs of and allowed")
        if cell.action == "push" and cell.repo not in ("btrc", "btrsmith"):
            problems.append("a push action needs repo = btrc or btrsmith")
        if problems:
            raise RunbookError(f"{self.path}: cell {cell.id}: {'; '.join(problems)}")
        return cell


# -- options ----------------------------------------------------------------------


@dataclass(frozen=True)
class RunOptions:
    """One invocation's options, shared by every preset it names."""

    presets: tuple[str, ...]
    home: Path
    btrsmith_home: Path
    btrc_hub: Path | None
    btrsmith_hub: Path | None
    btrc_ref: str | None
    btrsmith_branch: str | None
    btrcc: Path | None
    rehearsal: bool
    stand_in: bool
    dry_run: bool
    fresh: bool
    list_only: bool
    publish: bool
    with_cells: tuple[str, ...]
    settings: Mapping[str, str]
    min_free_gb: float
    quiet_window_s: float | None
    quiet_timeout_h: float | None
    evidence_remote: str | None
    owner_wait_s: float

    @staticmethod
    def parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog="tools/runbook/run.sh",
            description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument("presets", nargs="*", help=f"preset names ({', '.join(Preset.available())})")
        parser.add_argument(
            "--list", action="store_true", help="show each preset's cells and their status, run nothing"
        )
        parser.add_argument("--fresh", action="store_true", help="abandon the preset's unfinished run and start anew")
        parser.add_argument("--rehearsal", action="store_true", help="run off the Mac: local clone, report-only quiet")
        parser.add_argument("--stand-in", action="store_true", help="budget_bench's stand-in instead of BTRSmith")
        parser.add_argument("--dry-run", action="store_true", help="one sample per scenario; never push")
        parser.add_argument("--no-publish", action="store_true", help="write summary.json but push nothing")
        parser.add_argument("--btrc-ref", help="btrc ref to measure (default: the preset's, usually main)")
        parser.add_argument("--btrsmith-branch", help="BTRSmith ref for the preset's branch pin")
        parser.add_argument("--btrcc", help="use this btrcc instead of building one (skips the build cell)")
        parser.add_argument("--with", dest="with_cells", action="append", default=[], help="run an optional cell")
        parser.add_argument("--set", dest="settings", action="append", default=[], help="NAME=VALUE preset variable")
        parser.add_argument("--home", help="btrc cache root (default ~/.cache/btrc, or $BTRC_BENCH_HOME)")
        parser.add_argument("--btrsmith-home", help="BTRSmith cache root (default ~/.cache/btrsmith)")
        parser.add_argument("--btrc-hub", help="btrc repository to clone (default <home>/hub.git)")
        parser.add_argument("--btrsmith-hub", help="BTRSmith repository to clone (default <btrsmith-home>/hub.git)")
        parser.add_argument("--min-free-gb", type=float, help=f"free disk required (default {DEFAULT_MIN_FREE_GB:g})")
        parser.add_argument("--quiet-window", type=float, help="seconds one quiet window lasts (default 60)")
        parser.add_argument(
            "--quiet-timeout", type=float, help="hours to wait for quiet before failing (default: wait)"
        )
        parser.add_argument("--evidence-remote", help="where evidence branches go (default: the btrc hub's origin)")
        parser.add_argument("--owner-wait", type=float, default=30.0, help="minutes to wait for an owner action")
        return parser

    @classmethod
    def parse(cls, argv: Sequence[str] | None = None) -> RunOptions:
        parser = cls.parser()
        arguments = parser.parse_args(argv)
        if not arguments.presets:
            parser.error(f"name at least one preset: {', '.join(Preset.available())}")
        settings: dict[str, str] = {}
        for item in arguments.settings:
            name, separator, value = item.partition("=")
            if not separator or not name:
                parser.error(f"--set takes NAME=VALUE, not {item!r}")
            settings[name] = value
        home = Path(arguments.home or os.environ.get("BTRC_BENCH_HOME") or "~/.cache/btrc").expanduser()
        btrsmith_home = Path(arguments.btrsmith_home or "~/.cache/btrsmith").expanduser()
        min_free = arguments.min_free_gb
        if min_free is None:
            min_free = REHEARSAL_MIN_FREE_GB if arguments.rehearsal else DEFAULT_MIN_FREE_GB
        quiet_window = arguments.quiet_window
        if quiet_window is None and arguments.rehearsal:
            quiet_window = REHEARSAL_QUIET_WINDOW_S
        return cls(
            presets=tuple(arguments.presets),
            home=home.resolve(),
            btrsmith_home=btrsmith_home.resolve(),
            btrc_hub=Path(arguments.btrc_hub).expanduser().resolve() if arguments.btrc_hub else None,
            btrsmith_hub=Path(arguments.btrsmith_hub).expanduser().resolve() if arguments.btrsmith_hub else None,
            btrc_ref=arguments.btrc_ref,
            btrsmith_branch=arguments.btrsmith_branch,
            btrcc=Path(arguments.btrcc).expanduser().resolve() if arguments.btrcc else None,
            rehearsal=arguments.rehearsal,
            stand_in=arguments.stand_in,
            dry_run=arguments.dry_run,
            fresh=arguments.fresh,
            list_only=arguments.list,
            publish=not arguments.no_publish,
            with_cells=tuple(arguments.with_cells),
            settings=settings,
            min_free_gb=min_free,
            quiet_window_s=quiet_window,
            quiet_timeout_h=arguments.quiet_timeout,
            evidence_remote=arguments.evidence_remote,
            owner_wait_s=arguments.owner_wait * 60,
        )

    def mode(self) -> dict[str, bool]:
        return {"rehearsal": self.rehearsal, "stand_in": self.stand_in, "dry_run": self.dry_run}

    def acceptance(self) -> bool:
        """Whether this run's numbers can count as evidence at all."""

        return not (self.rehearsal or self.stand_in or self.dry_run)


# -- host, git, locks ------------------------------------------------------------


class Git:
    """The git commands the engine needs, each with a timeout."""

    @staticmethod
    def run(*arguments: str, cwd: Path | None = None, check: bool = True, timeout: float = GIT_TIMEOUT_S) -> str:
        command = ["git", *arguments]
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=Git.environment(),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise RunbookError(f"`{shlex.join(command)}` timed out after {timeout:g} s") from error
        if check and completed.returncode != 0:
            raise RunbookError(f"`{shlex.join(command)}` failed: {completed.stderr.strip()[-600:]}")
        return completed.stdout.strip()

    @staticmethod
    def environment() -> dict[str, str]:
        """Never prompt: an HTTPS remote without credentials fails at once instead of waiting on a terminal."""

        return dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="", SSH_ASKPASS="")

    @classmethod
    def ok(cls, *arguments: str, cwd: Path | None = None) -> bool:
        try:
            completed = subprocess.run(["git", *arguments], cwd=cwd, capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0

    @classmethod
    def clone(cls, source: Path, destination: Path) -> None:
        """Clone ``source`` once, then fetch every later time; never touch a dirty tree."""

        if (destination / ".git").exists():
            status = cls.run("status", "--porcelain", "--untracked-files=no", cwd=destination)
            if status:
                raise RunbookError(
                    f"{destination} has local changes; commit or discard them, or move the clone aside:\n{status[:800]}"
                )
            cls.run("fetch", "--prune", "--tags", "origin", cwd=destination)
            return
        if not source.exists():
            raise RunbookError(f"no repository to clone at {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        cls.run("clone", "--quiet", str(source), str(destination))

    @classmethod
    def resolve(cls, clone: Path, ref: str) -> str:
        for candidate in (f"origin/{ref}", ref):
            if cls.ok("rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}", cwd=clone):
                return cls.run("rev-parse", f"{candidate}^{{commit}}", cwd=clone)
        raise RunbookError(f"ref {ref!r} is not in {clone} (fetched from its hub)")

    @classmethod
    def checkout(cls, clone: Path, sha: str) -> None:
        if cls.run("rev-parse", "HEAD", cwd=clone) != sha:
            cls.run("checkout", "--quiet", "--detach", sha, cwd=clone)

    @classmethod
    def worktree(cls, clone: Path, sha: str, destination: Path) -> Path:
        if not (destination / ".git").exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            cls.run("worktree", "add", "--force", "--detach", str(destination), sha, cwd=clone)
        cls.checkout(destination, sha)
        return destination


class Locks:
    """The shared locks of AGENTS.md "Locks", taken in this process with ``flock``.

    ``tools/bench/scripts/withlock.sh`` takes the same files with macOS
    ``lockf``, which locks through ``O_EXLOCK``: the BSD ``flock`` lock, so the
    two exclude each other. Taking the lock here, not by prefixing the command
    with ``withlock.sh``, lets the quiet check run while the lock is held, so no
    lock wait separates a quiet window from its measurement. ``btrcc-build`` is
    the same two-slot semaphore (``btrcc-build.1``, ``btrcc-build.2``).
    """

    SLOT_WAIT_S = 5.0

    def __init__(self, directory: Path, *, create: bool) -> None:
        self.directory = directory
        self.create = create

    def path(self, name: str) -> Path:
        path = self.directory / name
        if not path.exists():
            if not self.create:
                raise RunbookError(f"lock {path} does not exist (AGENTS.md 'Locks'); is BTRC_LOCK_DIR right?")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        return path

    @contextlib.contextmanager
    def held(self, name: str | None) -> Iterator[None]:
        if name is None:
            yield
            return
        import fcntl

        slots = [f"{name}.1", f"{name}.2"] if name == "btrcc-build" else [name]
        streams = [self.path(slot).open("a") for slot in slots]
        try:
            if len(streams) == 1:
                fcntl.flock(streams[0], fcntl.LOCK_EX)
                held = streams[0]
            else:
                held = None
                while held is None:
                    for stream in streams:
                        try:
                            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            continue
                        held = stream
                        break
                    else:
                        time.sleep(self.SLOT_WAIT_S)
            try:
                yield
            finally:
                fcntl.flock(held, fcntl.LOCK_UN)
        finally:
            for stream in streams:
                stream.close()


class Host:
    """Facts about the machine the run is on, and the preflight checks."""

    def __init__(self, system: str | None = None) -> None:
        self.system = system or platform.system()

    def entry(self) -> str:
        """The compiler entry this host bootstraps (AGENTS.md: build for the compiler's host)."""

        if self.system == "Darwin":
            return "src/compiler/btrc/cli/MacOSMain.btrc"
        return "src/compiler/btrc/BtrccMain.btrc"

    @staticmethod
    def free_gb(path: Path) -> float:
        probe = path
        while not probe.exists():
            probe = probe.parent
        return shutil.disk_usage(probe).free / 1e9

    @staticmethod
    def prune_test_btrcc(clone: Path, keep: int = KEEP_TEST_BTRCC) -> list[Path]:
        """Delete ``build/test-btrcc`` fingerprints beyond the newest ``keep`` and any pinned one."""

        root = clone / "build" / "test-btrcc"
        if not root.is_dir():
            return []
        pinned = os.environ.get("BTRC_TEST_BTRCC")
        protected = {Path(pinned).resolve().parent} if pinned else set()
        entries = sorted(
            (entry for entry in root.iterdir() if entry.is_dir()), key=lambda entry: entry.stat().st_mtime, reverse=True
        )
        removed = []
        for entry in entries[keep:]:
            if entry.resolve() in protected:
                continue
            shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry)
        return removed

    @staticmethod
    def ssh_agent_ready() -> bool:
        if shutil.which("ssh-add") is None:
            return False
        try:
            completed = subprocess.run(["ssh-add", "-l"], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0

    @staticmethod
    def first_line(*command: str) -> str | None:
        if shutil.which(command[0]) is None:
            return None
        try:
            completed = subprocess.run(list(command), capture_output=True, text=True, errors="replace", timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None
        lines = (completed.stdout or completed.stderr).strip().splitlines()
        return lines[0] if completed.returncode == 0 and lines else None


# -- run state ---------------------------------------------------------------------


@dataclass
class CellOutcome:
    """What one cell did, as its checkpoint records it."""

    id: str
    title: str
    status: str
    exit: int | None = None
    attempts: int = 0
    started: str | None = None
    finished: str | None = None
    duration_s: float | None = None
    lock: str | None = None
    message: str = ""
    log: str | None = None
    out: str | None = None
    variables: dict[str, str] = field(default_factory=dict)
    quiet: dict[str, object] | None = None
    results: dict[str, object] = field(default_factory=dict)

    FINISHED = frozenset({"passed", "skipped"})

    def as_dict(self) -> dict[str, object]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CellOutcome:
        return cls(**{key: value for key, value in data.items() if key in cls.__dataclass_fields__})


class RunState:
    """One run's directories, its frozen choices (state.json) and its checkpoints."""

    def __init__(self, work: Path, logs: Path) -> None:
        self.work = work
        self.logs = logs
        self.state_path = work / "state.json"
        self.cells_dir = work / "cells"

    @property
    def run_id(self) -> str:
        return self.work.name

    def load(self) -> dict[str, Any]:
        return json.loads(self.state_path.read_text()) if self.state_path.is_file() else {}

    def save(self, state: Mapping[str, Any]) -> None:
        self.work.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2) + "\n")
        temporary.replace(self.state_path)

    def checkpoint_path(self, cell_id: str) -> Path:
        return self.cells_dir / f"{cell_id}.json"

    def checkpoint(self, cell_id: str) -> CellOutcome | None:
        path = self.checkpoint_path(cell_id)
        if not path.is_file():
            return None
        try:
            return CellOutcome.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, TypeError):
            return None

    def record(self, outcome: CellOutcome) -> None:
        self.cells_dir.mkdir(parents=True, exist_ok=True)
        path = self.checkpoint_path(outcome.id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(outcome.as_dict(), indent=2) + "\n")
        temporary.replace(path)

    def cell_out(self, cell_id: str) -> Path:
        return self.work / "out" / cell_id

    def cell_log(self, cell_id: str) -> Path:
        return self.logs / "logs" / f"{cell_id}.log"


# -- result readers -----------------------------------------------------------------


class Results:
    """Turn a finished command into (passed, results, message) by the cell's ``result`` kind."""

    # pytest's summary lines. Make's own "*** [target] Error" lines are not test names.
    DEFAULT_FAILURES = (r"^FAILED\s+(\S+)",)

    @classmethod
    def read(cls, cell: CellSpec, code: int, out: Path, log: Path) -> tuple[bool, dict[str, object], str]:
        reader = {
            "exit": cls.exit,
            "budget-bench": cls.budget_bench,
            "gate-summary": cls.gate_summary,
            "failure-list": cls.failure_list,
            "instr": cls.instr,
            "attribution": cls.attribution,
        }[cell.result]
        return reader(cell, code, out, log)

    @staticmethod
    def exit(cell: CellSpec, code: int, out: Path, log: Path) -> tuple[bool, dict[str, object], str]:
        return code == 0, {}, "" if code == 0 else f"exit {code}"

    @staticmethod
    def budget_bench(cell: CellSpec, code: int, out: Path, log: Path) -> tuple[bool, dict[str, object], str]:
        path = out / "report.json"
        if not path.is_file():
            return False, {}, f"exit {code}; no report.json in {out}"
        report = json.loads(path.read_text())
        scenarios = {
            name: {key: summary.get(key) for key in ("median", "p95", "max")}
            | {
                "samples": len(summary.get("samples", [])),
                "facts": summary.get("facts", {}),
                "metric_medians": summary.get("metric_medians", {}),
            }
            for name, summary in report.get("scenarios", {}).items()
        }
        failure = report.get("failure")
        results: dict[str, object] = {
            "report": str(path),
            "dry_run": report.get("dry_run"),
            "stand_in": report.get("configuration", {}).get("stand_in"),
            "frontend": report.get("configuration", {}).get("frontend"),
            "scenarios": scenarios,
        }
        if failure:
            results["failure"] = failure
        passed = code == 0 and not failure
        return passed, results, "" if passed else (failure or f"exit {code}")

    @staticmethod
    def gate_summary(cell: CellSpec, code: int, out: Path, log: Path) -> tuple[bool, dict[str, object], str]:
        path = out / "summary.txt"
        steps: list[dict[str, object]] = []
        if path.is_file():
            for line in path.read_text(errors="replace").splitlines():
                match = re.match(r"^(\S+) exit=(\d+) (\d+)s ?(.*)$", line)
                if match:
                    steps.append(
                        {"step": match[1], "exit": int(match[2]), "duration_s": int(match[3]), "counts": match[4]}
                    )
        failed = [step["step"] for step in steps if step["exit"] != 0]
        results: dict[str, object] = {"summary": str(path), "steps": steps, "failed_steps": failed}
        if code == 0:
            return True, results, ""
        return False, results, f"red: {', '.join(map(str, failed)) or f'exit {code}'}"

    @classmethod
    def failure_list(cls, cell: CellSpec, code: int, out: Path, log: Path) -> tuple[bool, dict[str, object], str]:
        """A command whose failures are expected, as long as they are named (release-check)."""

        text = log.read_text(errors="replace") if log.is_file() else ""
        names: list[str] = []
        for pattern in cell.failures or cls.DEFAULT_FAILURES:
            for match in re.finditer(pattern, text, flags=re.MULTILINE):
                name = match.group(1) if match.groups() else match.group(0)
                if name not in names:
                    names.append(name)
        results: dict[str, object] = {"failures": names, "exit": code}
        if code != 0 and not names:
            return False, results, f"exit {code} with no failure named in the log"
        return True, results, f"{len(names)} failure(s) named" if names else ""

    @staticmethod
    def instr(cell: CellSpec, code: int, out: Path, log: Path) -> tuple[bool, dict[str, object], str]:
        text = log.read_text(errors="replace") if log.is_file() else ""
        match = re.search(r"rc=(\d+)\s+(\S+)\s+instructions=(\S*) peak-footprint=(\S*) real=(\S*)", text)
        if match is None:
            return False, {}, f"exit {code}; no instr.sh result line"

        def number(text: str) -> float | None:
            try:
                return float(text)
            except ValueError:
                return None

        results: dict[str, object] = {
            "tag": match[2],
            "instructions": number(match[3]),
            "peak_footprint_bytes": number(match[4]),
            "real_s": number(match[5]),
        }
        passed = code == 0 and match[1] == "0"
        return passed, results, "" if passed else f"rc={match[1]}"

    @staticmethod
    def attribution(cell: CellSpec, code: int, out: Path, log: Path) -> tuple[bool, dict[str, object], str]:
        """`tools/perf.py --cprofile`'s attribution.json: its summary, never a ledger report."""

        path = out / "attribution.json"
        if not path.is_file():
            return False, {}, f"exit {code}; no attribution.json in {out}"
        report = json.loads(path.read_text())
        configuration = report.get("configuration", {})
        summary = report.get("summary", {})
        results: dict[str, object] = {
            "attribution": str(path),
            "dry_run": configuration.get("dry_run"),
            "stand_in": configuration.get("stand_in"),
            **{
                key: summary.get(key)
                for key in (
                    "attributed_fraction",
                    "minimum_fraction",
                    "target_fraction",
                    "meets_target",
                    "scenario_fractions",
                    "owner_shares",
                )
            },
        }
        failure = report.get("failure")
        if failure:
            results["failure"] = failure
        passed = code == 0 and not failure
        return passed, results, "" if passed else (failure or f"exit {code}")


# -- the engine ----------------------------------------------------------------------


class RunbookEngine:
    """Run one preset to completion, resuming from its checkpoints."""

    def __init__(
        self,
        preset: Preset,
        options: RunOptions,
        *,
        host: Host | None = None,
        quiet_factory: Callable[[Path, QuietSettings, bool], QuietCheck] | None = None,
        today: Callable[[], datetime.date] = datetime.date.today,
    ) -> None:
        self.preset = preset
        self.options = options
        self.host = host or Host()
        self.quiet_factory = quiet_factory or (
            lambda workspace, settings, rehearsal: QuietCheck(workspace, settings, rehearsal=rehearsal)
        )
        self.today = today
        self.cells = [
            cell
            for cell in preset.cells(stand_in=options.stand_in)
            if not cell.optional or self.requested(cell.id, options.with_cells)
        ]
        self.optional_skipped = [
            cell.id
            for cell in preset.cells(stand_in=options.stand_in)
            if cell.optional and not self.requested(cell.id, options.with_cells)
        ]
        # withlock.sh's own default, so both name the same files; a rehearsal keeps its locks beside its cache.
        default = options.home / "locks" if options.rehearsal else Path.home() / ".cache" / "btrc" / "locks"
        self.lock_dir = Path(os.environ.get("BTRC_LOCK_DIR") or default)
        self.locks = Locks(self.lock_dir, create=options.rehearsal or self.host.system != "Darwin")
        self.state: RunState | None = None
        self.frozen: dict[str, Any] = {}

    @staticmethod
    def requested(cell_id: str, patterns: Sequence[str]) -> bool:
        return any(fnmatch.fnmatchcase(cell_id, pattern) or cell_id.startswith(pattern) for pattern in patterns)

    # -- directories and state

    def pointer(self) -> Path:
        return self.options.home / "runbook" / self.preset.name / "current"

    def new_state(self) -> RunState:
        base = f"{self.preset.name}-{self.today().isoformat()}"
        root = self.options.home / ("bench.noindex" if self.preset.kind == "measurement" else "gates")
        for suffix in itertools.count(1):
            run_id = base if suffix == 1 else f"{base}-{suffix}"
            if not (root / run_id).exists():
                break
        logs = (self.options.home / "bench" / run_id) if self.preset.kind == "measurement" else root / run_id
        return RunState(root / run_id, logs)

    def open_state(self) -> RunState:
        pointer = self.pointer()
        if pointer.is_file() and not self.options.fresh:
            recorded = json.loads(pointer.read_text())
            state = RunState(Path(recorded["work"]), Path(recorded["logs"]))
            if state.state_path.is_file():
                return state
        state = self.new_state()
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(json.dumps({"work": str(state.work), "logs": str(state.logs)}) + "\n")
        return state

    def variables(self) -> dict[str, str]:
        variables = dict(self.preset.variables)
        if self.options.rehearsal:
            variables.update(self.preset.rehearsal_variables)
        variables.update(self.options.settings)
        return variables

    def requested_refs(self) -> dict[str, Any]:
        pins = dict(self.preset.pins)
        if self.options.btrsmith_branch:
            if self.preset.branch_pin is None:
                raise RunbookError(f"preset {self.preset.name} has no branch pin for --btrsmith-branch")
            pins[self.preset.branch_pin] = self.options.btrsmith_branch
        btrc = self.options.btrc_ref or self.preset.btrc_ref
        if self.options.rehearsal and not self.options.btrc_ref and not self.options.btrc_hub:
            btrc = "HEAD"  # a rehearsal measures this checkout's commit, resolved once in prepare()
        return {"btrc": btrc, "btrsmith": pins}

    def freeze(self, state: RunState) -> dict[str, Any]:
        """Load the run's frozen choices, or record them; a mismatch is the owner's call."""

        requested = {
            "preset": self.preset.name,
            "mode": self.options.mode(),
            "refs": self.requested_refs(),
            "variables": self.variables(),
            "with": sorted(self.options.with_cells),
            "btrcc": str(self.options.btrcc) if self.options.btrcc else None,
        }
        frozen = state.load()
        if frozen:
            for key in ("mode", "refs", "variables", "with", "btrcc"):
                if frozen.get(key) != requested[key]:
                    raise RunbookError(
                        f"run {state.run_id} was started with {key} = {json.dumps(frozen.get(key))}, "
                        f"not {json.dumps(requested[key])}.\n"
                        f"Rerun with the same options to resume it, or add --fresh to start a new run."
                    )
            return frozen
        frozen = requested | {
            "run": state.run_id,
            "work": str(state.work),
            "logs": str(state.logs),
            "started": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "packet": self.preset.packet,
            "title": self.preset.title,
            "kind": self.preset.kind,
        }
        state.save(frozen)
        return frozen

    # -- workspace

    def btrc_hub(self) -> Path:
        if self.options.btrc_hub:
            return self.options.btrc_hub
        return REPO if self.options.rehearsal else self.options.home / "hub.git"

    def btrsmith_hub(self) -> Path:
        return self.options.btrsmith_hub or self.options.btrsmith_home / "hub.git"

    def btrc_clone(self) -> Path:
        return self.options.home / "clones" / self.preset.name

    def btrsmith_clone(self, label: str) -> Path:
        return self.options.btrsmith_home / "clones" / self.preset.name / label

    def needs_btrsmith(self) -> bool:
        return bool(self.preset.pins) and not self.options.stand_in

    def prepare(self, state: RunState) -> None:
        """Clone, resolve and record SHAs once; later invocations check out the same SHAs."""

        frozen = self.frozen
        clone = self.btrc_clone()
        say(f"  btrc clone      {clone}  (from {self.btrc_hub()})")
        Git.clone(self.btrc_hub(), clone)
        shas = frozen.setdefault("shas", {})
        if "btrc" not in shas:
            if frozen["refs"]["btrc"] == "HEAD" and self.btrc_hub() == REPO:
                shas["btrc"] = Git.run("rev-parse", "HEAD", cwd=REPO)
            else:
                shas["btrc"] = Git.resolve(clone, frozen["refs"]["btrc"])
        Git.checkout(clone, shas["btrc"])
        say(f"  btrc            {frozen['refs']['btrc']} = {shas['btrc'][:12]}")
        removed = Host.prune_test_btrcc(clone)
        if removed:
            say(f"  pruned          {len(removed)} build/test-btrcc fingerprint(s) beyond the newest {KEEP_TEST_BTRCC}")
        if self.needs_btrsmith():
            pins = shas.setdefault("btrsmith", {})
            for label, ref in frozen["refs"]["btrsmith"].items():
                pin_clone = self.btrsmith_clone(label)
                Git.clone(self.btrsmith_hub(), pin_clone)
                if label not in pins:
                    try:
                        pins[label] = Git.resolve(pin_clone, ref)
                    except RunbookError:
                        if label not in self.preset.optional_pins:
                            raise
                        pins[label] = None
                if pins[label] is None:
                    say(f"  BTRSmith {label:<7}{ref} is not in the hub; its cells are skipped (optional pin)")
                    continue
                Git.checkout(pin_clone, pins[label])
                say(f"  BTRSmith {label:<7}{ref} = {pins[label][:12]}  ({pin_clone})")
        state.save(frozen)

    # -- placeholders

    def context(self, cell: CellSpec, state: RunState) -> dict[str, str | list[str]]:
        frozen = self.frozen
        btrc = self.btrc_clone()
        btrcc = self.options.btrcc or (state.work / "btrcc" / "btrcc")
        out = state.cell_out(cell.id)
        frontend = cell.variables.get("frontend", "selfhost")
        context: dict[str, str | list[str]] = {
            **self.variables(),
            **cell.variables,
            "home": str(self.options.home),
            "btrsmith_home": str(self.options.btrsmith_home),
            "run": str(state.work),
            "logs": str(state.logs),
            "run_id": state.run_id,
            "btrc": str(btrc),
            "btrc_sha": frozen.get("shas", {}).get("btrc", ""),
            "scripts": str(btrc / "tools" / "bench" / "scripts"),
            "btrcc": str(btrcc),
            "out": str(out),
            "host_entry": self.host.entry(),
            "python": sys.executable,
            "dry_run_args": ["--dry-run"] if self.options.dry_run else [],
            "btrcc_args": ["--btrcc", str(btrcc)] if frontend == "selfhost" else [],
        }
        pin = cell.variables.get("pin") or self.preset.branch_pin
        if self.options.stand_in:
            context["workspace_args"] = ["--stand-in"]
        elif pin is not None:
            context["btrsmith"] = str(self.btrsmith_clone(pin))
            context["btrsmith_sha"] = frozen.get("shas", {}).get("btrsmith", {}).get(pin, "")
            context["workspace_args"] = ["--workspace", str(self.btrsmith_clone(pin))]
        for other in self.cells:
            context[f"cell:{other.id}"] = str(state.cell_out(other.id))
        for name, value in list(context.items()):
            if isinstance(value, str) and "{" in value and name not in ("btrsmith", "btrc"):
                context[name] = self.expand(value, context)
        if cell.tree:
            ref = self.expand(cell.tree, context)
            sha = frozen.get("shas", {}).get("trees", {}).get(ref)
            context["tree"] = str(state.work / "trees" / (sha or ref)[:12])
        return context

    @staticmethod
    def expand(text: str, context: Mapping[str, str | list[str]]) -> str:
        def substitute(match: re.Match[str]) -> str:
            value = context.get(match[1])
            if value is None:
                raise RunbookError(f"unknown placeholder {{{match[1]}}} in {text!r}")
            return shlex.join(value) if isinstance(value, list) else value

        return _PLACEHOLDER.sub(substitute, text)

    @classmethod
    def expand_command(cls, command: Sequence[str], context: Mapping[str, str | list[str]]) -> list[str]:
        expanded: list[str] = []
        for part in command:
            whole = _PLACEHOLDER.fullmatch(part)
            if whole and isinstance(context.get(whole[1]), list):
                expanded.extend(context[whole[1]])  # type: ignore[arg-type]
            else:
                expanded.append(cls.expand(part, context))
        return expanded

    # -- cells

    def skip_reason(self, cell: CellSpec, outcomes: Mapping[str, CellOutcome]) -> str | None:
        if cell.stand_in == "skip" and self.options.stand_in:
            return "needs the real BTRSmith; skipped under --stand-in"
        pin = cell.variables.get("pin")
        if pin is not None and pin in self.frozen.get("shas", {}).get("btrsmith", {}):
            if self.frozen["shas"]["btrsmith"][pin] is None:
                return f"BTRSmith pin {pin} is not in the hub; only the other pins are measured"
        if cell.provides == "btrcc" and self.options.btrcc is not None:
            return f"using --btrcc {self.options.btrcc}"
        if cell.action == "push" and (self.options.dry_run or self.options.rehearsal):
            return "dry run or rehearsal: nothing is pushed"
        return None

    def uses_btrcc(self, cell: CellSpec) -> bool:
        text = " ".join((*cell.command, *cell.env.values()))
        selfhost = cell.variables.get("frontend", "selfhost") == "selfhost"
        return "{btrcc}" in text or ("{btrcc_args}" in text and selfhost)

    def blocked_reason(self, cell: CellSpec, outcomes: Mapping[str, CellOutcome]) -> str | None:
        if cell.provides is None and self.uses_btrcc(cell):
            builders = [outcomes.get(other.id) for other in self.cells if other.provides == "btrcc"]
            unfinished = [outcome for outcome in builders if outcome is None or outcome.status != "passed"]
            if builders and unfinished and self.options.btrcc is None:
                return "needs btrcc, whose build cell did not pass"
        if cell.when != "green":
            return None
        red = [outcome.id for outcome in outcomes.values() if outcome.status not in CellOutcome.FINISHED]
        return f"waits for a green run; red or unfinished: {', '.join(red)}" if red else None

    def check_requirements(self, cell: CellSpec, context: Mapping[str, str | list[str]]) -> str | None:
        for requirement in cell.requires:
            kind, _, value = requirement.partition(":")
            value = self.expand(value, context)
            if kind == "path" and not Path(value).exists():
                return f"{value} does not exist on this revision"
            if kind == "make":
                makefile = Path(str(context["btrc"])) / "Makefile"
                text = makefile.read_text(errors="replace") if makefile.is_file() else ""
                if not re.search(rf"^{re.escape(value)}\s*:", text, flags=re.MULTILINE):
                    return f"the Makefile at this revision has no `{value}` target"
            if kind not in ("path", "make"):
                raise RunbookError(f"cell {cell.id}: unknown requirement {requirement!r}")
        return None

    def run_cells(self, state: RunState) -> list[CellOutcome]:
        outcomes: dict[str, CellOutcome] = {}
        total = len(self.cells)
        stopped = False
        for index, cell in enumerate(self.cells, 1):
            label = f"[{index}/{total}] {cell.id}"
            done = state.checkpoint(cell.id)
            if done is not None and done.status in CellOutcome.FINISHED:
                outcomes[cell.id] = done
                say(f"{label}: {done.status} earlier ({done.message or 'ok'}); not repeated")
                continue
            if stopped:
                say(f"{label}: not reached (the preset stops at its first failure)")
                continue
            reason = self.skip_reason(cell, outcomes)
            if reason:
                outcome = CellOutcome(cell.id, cell.title, "skipped", message=reason, variables=dict(cell.variables))
                state.record(outcome)
                outcomes[cell.id] = outcome
                say(f"{label}: skipped ({reason})")
                continue
            blocked = self.blocked_reason(cell, outcomes)
            if blocked:
                outcome = CellOutcome(cell.id, cell.title, "blocked", message=blocked, variables=dict(cell.variables))
                state.record(outcome)
                outcomes[cell.id] = outcome
                say(f"{label}: blocked ({blocked})")
                continue
            say(f"{label}: {cell.title}")
            outcome = self.run_cell(cell, state, outcomes)
            state.record(outcome)
            outcomes[cell.id] = outcome
            mark = {"passed": "ok", "failed": "FAILED"}.get(outcome.status, outcome.status)
            duration = f" in {outcome.duration_s / 60:.1f} min" if outcome.duration_s else ""
            say(f"    -> {mark}{duration}{': ' + outcome.message if outcome.message else ''}")
            if outcome.status == "failed" and self.preset.on_failure == "stop":
                stopped = True
        return [outcomes[cell.id] for cell in self.cells if cell.id in outcomes]

    def run_cell(self, cell: CellSpec, state: RunState, outcomes: Mapping[str, CellOutcome]) -> CellOutcome:
        context = self.context(cell, state)
        out = state.cell_out(cell.id)
        log = state.cell_log(cell.id)
        outcome = CellOutcome(
            cell.id,
            cell.title,
            "failed",
            lock=cell.lock,
            log=str(log),
            out=str(out),
            variables=dict(cell.variables),
            started=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        )
        started = time.monotonic()
        try:
            if cell.tree:
                self.prepare_tree(cell, state)
                context = self.context(cell, state)
            missing = self.check_requirements(cell, context)
            if missing:
                outcome.message = missing
                return outcome
            if cell.owner_action:
                say(f"    owner: {cell.owner_action}")
            if cell.action == "subset":
                self.subset(cell, context, outcomes, outcome)
            elif cell.action == "push":
                self.push(cell, context, outcome)
            else:
                self.command(cell, context, out, log, outcome)
        except (RunbookError, OSError) as error:
            outcome.status = "failed"
            outcome.message = str(error)
        finally:
            outcome.finished = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
            outcome.duration_s = round(time.monotonic() - started, 1)
        return outcome

    def prepare_tree(self, cell: CellSpec, state: RunState) -> None:
        assert cell.tree is not None
        ref = self.expand(cell.tree, self.context(cell, state))
        trees = self.frozen.setdefault("shas", {}).setdefault("trees", {})
        clone = self.btrc_clone()
        if ref not in trees:
            trees[ref] = Git.resolve(clone, ref)
            state.save(self.frozen)
        Git.worktree(clone, trees[ref], state.work / "trees" / trees[ref][:12])

    def quiet(self, cell: CellSpec, state: RunState) -> dict[str, object]:
        settings = (
            QuietSettings()
            .overlay({"workspace_root": str(self.options.home / "bench.noindex")})
            .overlay(self.preset.quiet_table)
            .load(self.options.home / "runbook" / "quiet.toml")
        )
        if self.options.quiet_window_s is not None:
            settings = settings.overlay({"window_s": self.options.quiet_window_s})
        check = self.quiet_factory(state.work, settings, self.options.rehearsal)
        say(f"    quiet check: {settings.window_s:g} s window, a sample every {settings.interval_s:g} s")
        deadline = None if self.options.quiet_timeout_h is None else self.options.quiet_timeout_h * 3600
        verdict = check.wait(deadline)
        if verdict.quiet:
            say(f"    quiet after {verdict.waited_s / 60:.1f} min ({verdict.windows} window(s))")
        return verdict.as_dict()

    def command(
        self, cell: CellSpec, context: Mapping[str, str | list[str]], out: Path, log: Path, outcome: CellOutcome
    ) -> None:
        argv = self.expand_command(cell.command, context)
        if cell.shell == "btrsmith" and not self.options.stand_in:
            argv = [str(Path(str(context["scripts"])) / "bsm_env.sh"), *argv]
        cwd = {
            "btrc": Path(str(context["btrc"])),
            "btrsmith": Path(str(context.get("btrsmith", context["btrc"]))),
            "tree": Path(str(context.get("tree", context["btrc"]))),
            "out": out,
        }[cell.cwd]
        environment = dict(os.environ)
        environment.update({key: self.expand(value, context) for key, value in cell.env.items()})
        if cell.shell == "btrsmith" and "btrsmith" in context:
            environment.setdefault("BTRSMITH_DEV_SHELL", str(context["btrsmith"]))
            reader = os.environ.get("BTRC_NATIVE_HEADER_READER")
            if reader:
                environment.setdefault("READER", reader)
        out.mkdir(parents=True, exist_ok=True)
        log.parent.mkdir(parents=True, exist_ok=True)
        if cell.provides == "btrcc":
            Path(str(context["btrcc"])).parent.mkdir(parents=True, exist_ok=True)
        say(f"    log: {log}")
        attempts = cell.retries + 1
        for attempt in range(1, attempts + 1):
            outcome.attempts = attempt
            with self.locks.held(cell.lock):
                if cell.lock:
                    say(f"    holding lock {cell.lock}")
                if cell.quiet:
                    outcome.quiet = self.quiet(cell, self.state)  # type: ignore[arg-type]
                attempt_log = log if attempt == 1 else log.with_suffix(f".attempt{attempt}.log")
                code = self.execute(argv, cwd, environment, attempt_log, cell.timeout_s)
            passed, results, message = Results.read(cell, code, out, attempt_log)
            if cell.result == "failure-list" and attempt > 1 and passed and outcome.results.get("failures"):
                # A failure counts only if every attempt failed it; the rest were flakes the rerun cleared.
                earlier = list(outcome.results.get("failures", []))  # type: ignore[arg-type]
                now = list(results.get("failures", []))  # type: ignore[arg-type]
                results["failures"] = [name for name in now if name in earlier]
                results["flaky"] = sorted(set(earlier) ^ set(now))
                count = len(results["failures"])  # type: ignore[arg-type]
                message = f"{count} failure(s) named in every attempt" if count else ""
            outcome.exit, outcome.results, outcome.message = code, results, message
            outcome.log = str(attempt_log)
            named = cell.result == "failure-list" and bool(results.get("failures"))
            if passed and not (named and attempt < attempts):
                outcome.status = "passed"
                return
            self.show_tail(attempt_log)
            if attempt < attempts:
                reason = "named failures" if passed else message
                say(f"    attempt {attempt} ended with {reason}; rerunning once more")
        outcome.status = "failed"

    @staticmethod
    def execute(argv: Sequence[str], cwd: Path, environment: Mapping[str, str], log: Path, timeout: float) -> int:
        with log.open("w") as stream:
            stream.write(f"$ (cd {shlex.quote(str(cwd))} && {shlex.join(argv)})\n")
            stream.flush()
            try:
                process = subprocess.Popen(
                    list(argv), cwd=cwd, env=dict(environment), stdout=stream, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )  # fmt: skip
            except OSError as error:
                stream.write(f"runbook: cannot start: {error}\n")
                return 127
            try:
                return process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=60)
                stream.write(f"\nrunbook: timed out after {timeout / 3600:.1f} h\n")
                return 124
            except KeyboardInterrupt:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                raise

    @staticmethod
    def show_tail(log: Path, lines: int = 15) -> None:
        if not log.is_file():
            return
        tail = log.read_text(errors="replace").splitlines()[-lines:]
        say(f"    last lines of {log}:")
        for line in tail:
            say(f"      | {line[:200]}")

    def subset(
        self,
        cell: CellSpec,
        context: Mapping[str, str | list[str]],
        outcomes: Mapping[str, CellOutcome],
        outcome: CellOutcome,
    ) -> None:
        """Every failure the ``of`` cells named must be on the ``allowed`` list."""

        assert cell.of and cell.allowed
        allowed_path = Path(self.expand(cell.allowed, context)).expanduser()
        sources = [outcomes[key] for key in outcomes if fnmatch.fnmatchcase(key, cell.of)]
        if not sources:
            outcome.message = f"no finished cell matches {cell.of}"
            return
        unfinished = [source.id for source in sources if source.status != "passed"]
        if unfinished:
            outcome.message = f"cannot compare: {', '.join(unfinished)} did not finish"
            return
        if not allowed_path.is_file():
            outcome.message = (
                f"{allowed_path} is missing: write the allowed failures there, one per line "
                "(for stage4-requal, Stage 2's qualifying column at BTRSmith 05ec9cb), then rerun"
            )
            return
        allowed = {
            line.strip()
            for line in allowed_path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        per_cell = {source.id: list(source.results.get("failures", [])) for source in sources}
        observed = {name for names in per_cell.values() for name in names}
        new = sorted(observed - allowed)
        outcome.results = {
            "allowed_file": str(allowed_path),
            "allowed": sorted(allowed),
            "failures": per_cell,
            "new_failures": new,
            "now_passing": sorted(allowed - observed),
        }
        outcome.exit = 0 if not new else 1
        outcome.status = "passed" if not new else "failed"
        outcome.message = f"{len(new)} new failure(s): {', '.join(new)}" if new else "no new failure"

    def push(self, cell: CellSpec, context: Mapping[str, str | list[str]], outcome: CellOutcome) -> None:
        """Fast-forward a branch upstream from a clone; never forced."""

        clone = Path(str(context["btrc"] if cell.repo == "btrc" else context.get("btrsmith", "")))
        hub = self.btrc_hub() if cell.repo == "btrc" else self.btrsmith_hub()
        remote = Evidence.upstream(hub, fallback=f"git@github.com:schiffy91/{cell.repo}.git")
        branch = cell.branch or "main"
        sha = Git.run("rev-parse", "HEAD", cwd=clone)
        if remote.startswith(("git@", "ssh://")) and not self.wait_for_ssh_agent():
            outcome.message = (
                "the SSH agent has no identity: unlock 1Password (or `ssh-add`), then rerun the same command"
            )
            return
        say(f"    pushing {sha[:12]} to {remote} {branch} (fast-forward only)")
        Git.run("push", remote, f"{sha}:refs/heads/{branch}", cwd=clone)
        if hub.exists() and Git.run("rev-parse", "--is-bare-repository", cwd=hub) == "true":
            # The hub feeds every later clone (stage5 resolves BTRSmith main there), so keep it level.
            Git.run("push", str(hub), f"{sha}:refs/heads/{branch}", cwd=clone)
        outcome.status, outcome.exit = "passed", 0
        outcome.results = {"remote": remote, "branch": branch, "sha": sha}
        outcome.message = f"{branch} is now {sha[:12]}"

    def wait_for_ssh_agent(self) -> bool:
        deadline = time.monotonic() + self.options.owner_wait_s
        announced = False
        while not Host.ssh_agent_ready():
            if not announced:
                say(
                    f"    owner: unlock 1Password so the SSH agent can sign the push "
                    f"(waiting up to {self.options.owner_wait_s / 60:.0f} min)"
                )
                announced = True
            if time.monotonic() >= deadline:
                return False
            time.sleep(15)
        return True

    # -- listing and the whole run

    def list_cells(self) -> None:
        pointer = self.pointer()
        state = None
        if pointer.is_file():
            recorded = json.loads(pointer.read_text())
            state = RunState(Path(recorded["work"]), Path(recorded["logs"]))
        say(f"{self.preset.name}: {self.preset.title}" + (f"  [{self.preset.packet}]" if self.preset.packet else ""))
        say(f"  current run: {state.work if state else 'none'}")
        for cell in self.cells:
            outcome = state.checkpoint(cell.id) if state else None
            status = f"{outcome.status}{': ' + outcome.message if outcome.message else ''}" if outcome else "pending"
            lock = f" [lock {cell.lock}]" if cell.lock else ""
            quiet = " [quiet]" if cell.quiet else ""
            say(f"  - {cell.id}{lock}{quiet}: {status}")
        for cell_id in self.optional_skipped:
            say(f"  - {cell_id}: optional; add --with {cell_id}")

    def describe(self, text: str) -> str:
        """Owner-facing text with the preset's variables and the cache roots filled in."""

        values = {**self.variables(), "home": str(self.options.home), "btrsmith_home": str(self.options.btrsmith_home)}
        for _ in range(3):
            text = _PLACEHOLDER.sub(lambda match: values.get(match[1], match[0]), text)
        return text

    def preflight(self) -> None:
        if self.host.system != "Darwin" and not self.options.rehearsal:
            raise RunbookError(
                f"this runbook drives the owner's Mac; this host is {self.host.system}. "
                "Pass --rehearsal (with --stand-in and --dry-run) to rehearse it here."
            )
        free = Host.free_gb(self.options.home)
        if free < self.options.min_free_gb:
            raise RunbookError(
                f"only {free:.0f} GB free under {self.options.home}; {self.options.min_free_gb:g} GB are required "
                "(AGENTS.md 'Disk'). Free space, then rerun."
            )
        say(f"  free disk       {free:.0f} GB (need {self.options.min_free_gb:g})")

    def run(self) -> int:
        if self.options.list_only:
            self.list_cells()
            return 0
        preset = self.preset
        say(f"=== {preset.name}: {preset.title}" + (f"  [{preset.packet}]" if preset.packet else ""))
        modes = [name.replace("_", "-") for name, on in self.options.mode().items() if on]
        if modes:
            say(f"  mode            --{' --'.join(modes)} (rehearsal: not acceptance evidence)")
        for line in preset.before:
            say(f"  before you start: {self.describe(line)}")
        self.preflight()
        state = self.open_state()
        self.state = state
        self.frozen = self.freeze(state)
        published = self.frozen.get("published")
        if published and all(
            (outcome := state.checkpoint(cell.id)) is not None and outcome.status in CellOutcome.FINISHED
            for cell in self.cells
        ):
            say(f"  run {state.run_id} is complete and published to {published.get('branch')}.")
            say(f"  summary: {state.work / 'summary.txt'}")
            say("  Nothing to do. Add --fresh to start a new round (for example after a fix lands).")
            return 0
        say(f"  run             {state.run_id}")
        say(f"  workspace       {state.work}")
        say(f"  raw logs        {state.logs}")
        self.prepare(state)
        for cell_id in self.optional_skipped:
            say(f"  optional cell   {cell_id} not requested (add --with {cell_id})")
        say("")
        try:
            outcomes = self.run_cells(state)
        except QuietTimeout as error:
            say(f"\nquiet check gave up: {error}. Rerun the same command to resume.")
            return 3
        except QuietRefused as error:
            raise RunbookError(str(error)) from error
        from tools.runbook.evidence import EvidencePublisher

        publisher = EvidencePublisher(self, state, outcomes)
        summary = publisher.publish()
        say("")
        say(publisher.render_text(summary))
        if summary["result"] != "green":
            return 1
        publication = summary.get("publication") or {}
        if self.options.acceptance() and self.options.publish and not publication.get("pushed"):  # type: ignore[union-attr]
            return 4
        return 0


class Evidence:
    """Small helpers the engine and the publisher share."""

    @staticmethod
    def upstream(hub: Path, *, fallback: str) -> str:
        """The URL a hub mirrors (its ``origin``), so pushes reach GitHub, not the local hub."""

        if hub.exists() and Git.ok("remote", "get-url", "origin", cwd=hub):
            return Git.run("remote", "get-url", "origin", cwd=hub)
        return fallback

    @staticmethod
    def digest(path: Path) -> str | None:
        if not path.is_file():
            return None
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()


def interrupt(signum: int, frame: object) -> None:
    """SIGTERM/SIGHUP stop a run like Ctrl-C: the running cell's process group is stopped too."""

    raise KeyboardInterrupt


def main(argv: Sequence[str] | None = None) -> int:
    options = RunOptions.parse(argv)
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupt)
    status = 0
    for name in options.presets:
        try:
            preset = Preset.load(name)
            result = RunbookEngine(preset, options).run()
        except RunbookError as error:
            say(f"\nrunbook {name}: {error}")
            result = 2
        except KeyboardInterrupt:
            say(f"\nrunbook {name}: interrupted. Rerun the same command to resume from the last finished cell.")
            return 130
        status = status or result
    return status
