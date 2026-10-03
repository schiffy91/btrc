"""The automated quiet check PLAN.md's standing approvals require before a quiet round.

A round starts only when every probe passes on every sample of one window
(60 s, a sample every 5 s):

- no other agents, builds or guests (a process scan);
- the btrc podman machine is stopped (``podman machine list --format json``);
- Time Machine is idle (``tmutil currentphase`` is ``BackupNotRunning``);
- Google Drive, ``mds`` and ``mdworker`` each use under 5% CPU;
- the measurement workspace lives under ``~/.cache/btrc/bench.noindex/``.

Otherwise it waits and retries. It never changes a setting: every blocker it
reports names the owner's action instead. Every probe is injectable, and the
process rules and thresholds are data (``QuietSettings``) that a preset's
``[quiet]`` table or ``~/.cache/btrc/runbook/quiet.toml`` overrides, so a rule
that misfires on the Mac is tuned without a code change. Off macOS the check
refuses to run unless the caller rehearses, where it reports without waiting.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

PROBE_TIMEOUT_S = 30


class QuietRefused(RuntimeError):
    """The check cannot judge this host (not macOS, and not a rehearsal)."""


class QuietTimeout(RuntimeError):
    """No quiet window arrived before the caller's deadline."""


@dataclass(frozen=True)
class ProcessRule:
    """One kind of process that must not run during a quiet round.

    ``pattern`` is a regular expression searched in the process's command line
    (``args``), or matched against the executable's base name when ``field``
    is ``name``, or against the owning user when it is ``user``.
    """

    label: str
    pattern: str
    field: str = "args"

    def matches(self, process: ProcessInfo) -> bool:
        if self.field == "name":
            return re.fullmatch(self.pattern, process.name) is not None
        if self.field == "user":
            return re.fullmatch(self.pattern, process.user) is not None
        return re.search(self.pattern, process.args) is not None


@dataclass(frozen=True)
class CpuRule:
    """A group of background processes whose summed CPU must stay under a limit."""

    label: str
    pattern: str
    limit_percent: float = 5.0


DEFAULT_PROCESS_RULES = (
    # The CLI agents, however launched (``node …/bin/claude``, a path with spaces); the
    # desktop chat app (``…/Claude.app/Contents/MacOS/Claude``) is not an agent session.
    ProcessRule("agent", r"(^|/)(claude|codex)(\s|$)"),
    ProcessRule(
        "compiler build", r"btrcc[\w.-]*|cc1|cc1plus|cc1obj|clang(\+\+)?(-\d+)?|gcc(-\d+)?|g\+\+|ld|ld64", "name"
    ),
    ProcessRule("test run", r"(^|[/\s])(py\.test|pytest)(\s|$)|-m\s+pytest\b"),
    ProcessRule("nix builder", r"_?nixbld\d*", "user"),
    # An idle `nix develop` shell is not load; builds are (and their builders run as _nixbld users).
    ProcessRule("nix build", r"(^|/)nix(-build|-store)?\s+(build|flake check|store)\b"),
    ProcessRule("guest", r"qemu-system[\w-]*|emulator\d*|vfkit|krunkit|UTM|VirtualBoxVM", "name"),
    ProcessRule("simulator", r"Simulator|launchd_sim|SimulatorTrampoline", "name"),
)
DEFAULT_CPU_RULES = (
    CpuRule("Google Drive", r"Google Drive"),
    CpuRule("mds", r"(^|/)mds(_stores)?(\s|$)"),
    CpuRule("mdworker", r"(^|/)mdworker(_shared)?(\s|$)"),
)


@dataclass(frozen=True)
class QuietSettings:
    """The window, the process rules and the thresholds; data, not code."""

    window_s: float = 60.0
    interval_s: float = 5.0
    retry_after_s: float = 60.0
    podman_machine: str = "podman-machine-default"
    workspace_root: str = "~/.cache/btrc/bench.noindex"
    process_rules: tuple[ProcessRule, ...] = DEFAULT_PROCESS_RULES
    cpu_rules: tuple[CpuRule, ...] = DEFAULT_CPU_RULES
    ignore: tuple[str, ...] = ()

    def overlay(self, table: Mapping[str, Any]) -> QuietSettings:
        """These settings with a TOML table's keys replacing or extending them.

        ``process_rules``/``cpu_rules`` replace the defaults; ``extra_process_rules``
        and ``extra_cpu_rules`` append to them; ``ignore`` lists command-line
        regexes the scan never reports (a known-benign helper on the owner's Mac).
        """

        known = {"window_s", "interval_s", "retry_after_s", "podman_machine", "workspace_root"}
        allowed = known | {"process_rules", "cpu_rules", "extra_process_rules", "extra_cpu_rules", "ignore"}
        unknown = sorted(set(table) - allowed)
        if unknown:
            raise ValueError(f"unknown quiet setting(s): {', '.join(unknown)}")
        changes: dict[str, Any] = {name: table[name] for name in known if name in table}
        for name in ("window_s", "interval_s", "retry_after_s"):
            if name in changes:
                changes[name] = float(changes[name])
                if changes[name] < 0:
                    raise ValueError(f"quiet {name} must not be negative")
        process_rules = self.process_rules
        if "process_rules" in table:
            process_rules = tuple(ProcessRule(**rule) for rule in table["process_rules"])
        process_rules += tuple(ProcessRule(**rule) for rule in table.get("extra_process_rules", ()))
        cpu_rules = self.cpu_rules
        if "cpu_rules" in table:
            cpu_rules = tuple(CpuRule(**rule) for rule in table["cpu_rules"])
        cpu_rules += tuple(CpuRule(**rule) for rule in table.get("extra_cpu_rules", ()))
        ignore = self.ignore + tuple(table.get("ignore", ()))
        for pattern in (*(rule.pattern for rule in process_rules), *(rule.pattern for rule in cpu_rules), *ignore):
            re.compile(pattern)
        return replace(self, process_rules=process_rules, cpu_rules=cpu_rules, ignore=ignore, **changes)

    def load(self, path: Path) -> QuietSettings:
        """Overlay a local TOML file when it exists (its whole content is the table)."""

        if not path.is_file():
            return self
        with path.open("rb") as stream:
            return self.overlay(tomllib.load(stream))


@dataclass(frozen=True)
class Observation:
    """One probe's verdict on one sample."""

    probe: str
    ok: bool
    detail: str
    action: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {"probe": self.probe, "ok": self.ok, "detail": self.detail, "action": self.action}


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    ppid: int
    user: str
    cpu_percent: float
    args: str

    @property
    def name(self) -> str:
        executable = self.args.split(" ", 1)[0] if self.args else ""
        return os.path.basename(executable)


class Probe(Protocol):
    name: str

    def observe(self) -> Observation: ...


class CommandRunner:
    """Runs one probe command; tests replace it with canned output."""

    def output(self, command: Sequence[str]) -> tuple[int, str] | None:
        """(exit code, stdout), or None when the program is not installed."""

        if shutil.which(command[0]) is None:
            return None
        try:
            completed = subprocess.run(
                list(command), capture_output=True, text=True, errors="replace", timeout=PROBE_TIMEOUT_S
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return 127, str(error)
        return completed.returncode, completed.stdout


@dataclass(frozen=True)
class ProcFilesystem:
    """Linux's process table read from ``/proc``, for a host without ``ps``.

    CI's devcontainer image has no procps. Each row matches what ``ps`` reports:
    the parent, the owner, the lifetime CPU share (``pcpu``) and the command line,
    or ``[comm]`` for a kernel thread.
    """

    root: Path = Path("/proc")

    def processes(self) -> list[ProcessInfo] | None:
        try:
            ticks = os.sysconf("SC_CLK_TCK")
            uptime = float((self.root / "uptime").read_text().split()[0])
            entries = [entry for entry in self.root.iterdir() if entry.name.isdigit()]
        except (OSError, ValueError, IndexError):
            return None
        return [process for entry in entries if (process := self.process(entry, ticks, uptime)) is not None]

    @staticmethod
    def process(entry: Path, ticks: int, uptime: float) -> ProcessInfo | None:
        try:
            stat = (entry / "stat").read_text(errors="replace")
            cmdline = (entry / "cmdline").read_bytes()
            uid = entry.stat().st_uid
        except OSError:
            return None  # it exited while the table was read
        # The command name (field 2) may hold spaces and parentheses, so the
        # fixed fields are counted from its closing parenthesis.
        fields = stat[stat.rfind(")") + 2 :].split()
        try:
            ppid, used, start = int(fields[1]), int(fields[11]) + int(fields[12]), int(fields[19])
        except (IndexError, ValueError):
            return None
        command = cmdline.replace(b"\0", b" ").decode(errors="replace").strip()
        args = command or f"[{stat[stat.find('(') + 1 : stat.rfind(')')]}]"
        elapsed = uptime - start / ticks
        cpu = round(100.0 * used / ticks / elapsed, 1) if elapsed > 0 else 0.0
        return ProcessInfo(int(entry.name), ppid, ProcFilesystem.owner(uid), cpu, args)

    @staticmethod
    def owner(uid: int) -> str:
        import pwd

        try:
            return pwd.getpwuid(uid).pw_name
        except KeyError:
            return str(uid)


@dataclass
class ProcessTable:
    """The host's processes, minus this check's own ancestry and descendants."""

    runner: CommandRunner = field(default_factory=CommandRunner)
    own_pid: int = field(default_factory=os.getpid)
    # Read when ``ps`` is not installed; only Linux has it.
    proc: ProcFilesystem | None = field(
        default_factory=lambda: ProcFilesystem() if platform.system() == "Linux" else None
    )

    COMMAND: Sequence[str] = ("ps", "-A", "-o", "pid=", "-o", "ppid=", "-o", "user=", "-o", "pcpu=", "-o", "args=")

    def snapshot(self) -> list[ProcessInfo] | None:
        result = self.runner.output(self.COMMAND)
        if result is None and self.proc is not None:
            processes = self.proc.processes()
            return None if processes is None else self.foreign(processes)
        if result is None or result[0] != 0:
            return None
        processes = [process for line in result[1].splitlines() if (process := self.parse(line)) is not None]
        return self.foreign(processes)

    @staticmethod
    def parse(line: str) -> ProcessInfo | None:
        parts = line.split(None, 4)
        if len(parts) < 4:
            return None
        try:
            pid, ppid, cpu = int(parts[0]), int(parts[1]), float(parts[3].replace(",", "."))
        except ValueError:
            return None
        return ProcessInfo(pid, ppid, parts[2], cpu, parts[4] if len(parts) > 4 else "")

    def foreign(self, processes: list[ProcessInfo]) -> list[ProcessInfo]:
        """Drop this process, its ancestors (the shell that ran us) and its children (``ps``)."""

        parents = {process.pid: process.ppid for process in processes}
        own = {self.own_pid}
        cursor = self.own_pid
        while cursor in parents and parents[cursor] not in own and parents[cursor] > 1:
            cursor = parents[cursor]
            own.add(cursor)
        changed = True
        while changed:
            changed = False
            for process in processes:
                if process.ppid == self.own_pid and process.pid not in own:
                    own.add(process.pid)
                    changed = True
        return [process for process in processes if process.pid not in own]


@dataclass
class ProcessProbe:
    """No other agent, build or guest is running."""

    table: ProcessTable
    settings: QuietSettings
    name: str = "processes"

    def observe(self) -> Observation:
        processes = self.table.snapshot()
        if processes is None:
            return Observation(self.name, False, "ps failed; cannot scan processes")
        offenders: list[str] = []
        for process in processes:
            if any(re.search(pattern, process.args) for pattern in self.settings.ignore):
                continue
            for rule in self.settings.process_rules:
                if rule.matches(process):
                    offenders.append(f"{rule.label}: pid {process.pid} {process.args[:100]}")
                    break
        if not offenders:
            return Observation(self.name, True, f"{len(processes)} processes, no agent, build or guest")
        shown = "; ".join(offenders[:5]) + (f"; and {len(offenders) - 5} more" if len(offenders) > 5 else "")
        return Observation(
            self.name, False, shown, "stop the agent sessions, builds and guests listed (or tune quiet.toml)"
        )


@dataclass
class CpuProbe:
    """Google Drive, mds and mdworker each stay under their CPU limit."""

    table: ProcessTable
    settings: QuietSettings
    name: str = "background-cpu"

    def observe(self) -> Observation:
        processes = self.table.snapshot()
        if processes is None:
            return Observation(self.name, False, "ps failed; cannot read CPU use")
        busy: list[str] = []
        readings: list[str] = []
        for rule in self.settings.cpu_rules:
            total = sum(process.cpu_percent for process in processes if re.search(rule.pattern, process.args))
            readings.append(f"{rule.label} {total:.1f}%")
            if total >= rule.limit_percent:
                busy.append(f"{rule.label} at {total:.1f}% (limit {rule.limit_percent:g}%)")
        if busy:
            return Observation(
                self.name,
                False,
                "; ".join(busy),
                "wait for indexing/sync to settle; pause Google Drive by hand if it never does",
            )
        return Observation(self.name, True, ", ".join(readings))


@dataclass
class PodmanProbe:
    """The btrc podman machine is stopped (other machines are not ours to judge)."""

    runner: CommandRunner
    machine: str
    name: str = "podman"

    def observe(self) -> Observation:
        result = self.runner.output(("podman", "machine", "list", "--format", "json"))
        if result is None:
            return Observation(self.name, True, "podman is not installed")
        code, text = result
        if code != 0:
            return Observation(self.name, False, f"podman machine list exited {code}", "check `podman machine list`")
        try:
            machines = json.loads(text or "[]")
        except json.JSONDecodeError:
            return Observation(self.name, False, "podman machine list printed no JSON", "check `podman machine list`")
        for machine in machines or []:
            name = str(machine.get("Name", "")).rstrip("*")
            if name == self.machine and (machine.get("Running") or machine.get("Starting")):
                return Observation(
                    self.name, False, f"podman machine {self.machine} is running", f"podman machine stop {self.machine}"
                )
        return Observation(self.name, True, f"podman machine {self.machine} is stopped")


@dataclass
class TimeMachineProbe:
    """``tmutil currentphase`` reports BackupNotRunning."""

    runner: CommandRunner
    required: bool
    name: str = "time-machine"

    def observe(self) -> Observation:
        result = self.runner.output(("tmutil", "currentphase"))
        if result is None:
            if self.required:
                return Observation(self.name, False, "tmutil is missing", "run on macOS")
            return Observation(self.name, True, "tmutil is not available on this host")
        code, text = result
        phase = text.strip()
        if code == 0 and phase == "BackupNotRunning":
            return Observation(self.name, True, phase)
        return Observation(
            self.name, False, f"Time Machine phase {phase or f'unknown (exit {code})'}", "let the backup finish"
        )


@dataclass
class WorkspaceProbe:
    """The measurement workspace lives under ``bench.noindex`` (Spotlight skips it)."""

    workspace: Path
    root: Path
    name: str = "workspace"

    def observe(self) -> Observation:
        workspace, root = self.workspace.expanduser().resolve(), self.root.expanduser().resolve()
        if workspace.is_relative_to(root):
            return Observation(self.name, True, f"{workspace} is under {root}")
        return Observation(self.name, False, f"{workspace} is outside {root}", f"measure under {root}")


@dataclass(frozen=True)
class QuietVerdict:
    """The outcome of one wait: whether a window passed, after how long, and what blocked it."""

    quiet: bool
    advisory: bool
    waited_s: float
    windows: int
    samples: list[list[Observation]]

    def blockers(self) -> list[Observation]:
        seen: dict[str, Observation] = {}
        for sample in self.samples:
            for observation in sample:
                if not observation.ok:
                    seen.setdefault(f"{observation.probe}:{observation.detail}", observation)
        return list(seen.values())

    def as_dict(self) -> dict[str, object]:
        last = self.samples[-1] if self.samples else []
        return {
            "quiet": self.quiet,
            "advisory": self.advisory,
            "waited_s": round(self.waited_s, 1),
            "windows": self.windows,
            "samples": len(self.samples),
            "last_sample": [observation.as_dict() for observation in last],
            "blockers": [observation.as_dict() for observation in self.blockers()],
        }


class QuietCheck:
    """Wait for one quiet window, or report the probes once, never changing a setting."""

    def __init__(
        self,
        workspace: Path,
        settings: QuietSettings | None = None,
        *,
        rehearsal: bool = False,
        system: str | None = None,
        probes: Sequence[Probe] | None = None,
        runner: CommandRunner | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        say: Callable[[str], None] = print,
    ) -> None:
        self.settings = settings or QuietSettings()
        self.rehearsal = rehearsal
        self.system = system or platform.system()
        self.clock, self.sleep, self.say = clock, sleep, say
        runner = runner or CommandRunner()
        if probes is None:
            table = ProcessTable(runner)
            probes = (
                ProcessProbe(table, self.settings),
                PodmanProbe(runner, self.settings.podman_machine),
                TimeMachineProbe(runner, required=self.system == "Darwin"),
                CpuProbe(table, self.settings),
                WorkspaceProbe(workspace, Path(self.settings.workspace_root)),
            )
        self.probes = tuple(probes)

    def refuse_unless_supported(self) -> None:
        if self.system != "Darwin" and not self.rehearsal:
            raise QuietRefused(
                f"the quiet check judges the owner's Mac; this host is {self.system}. Pass --rehearsal to rehearse here."
            )

    def sample(self) -> list[Observation]:
        return [probe.observe() for probe in self.probes]

    def report(self) -> list[Observation]:
        """One sample of every probe, without waiting or judging the host (CI's report-only mode)."""

        return self.sample()

    def window(self) -> tuple[bool, list[list[Observation]]]:
        """Sample every interval for one window; stop at the first failing sample."""

        samples: list[list[Observation]] = []
        started = self.clock()
        while True:
            observations = self.sample()
            samples.append(observations)
            if not all(observation.ok for observation in observations):
                return False, samples
            if self.clock() - started >= self.settings.window_s:
                return True, samples
            self.sleep(self.settings.interval_s)

    def wait(self, deadline_s: float | None = None) -> QuietVerdict:
        """Block until one full window passes; a rehearsal samples one window and never blocks."""

        self.refuse_unless_supported()
        started = self.clock()
        windows = 0
        last_blockers: tuple[str, ...] = ()
        history: list[list[Observation]] = []
        while True:
            windows += 1
            quiet, samples = self.window()
            history = samples
            if quiet:
                return QuietVerdict(True, False, self.clock() - started, windows, history)
            failing = [observation for observation in samples[-1] if not observation.ok]
            if self.rehearsal:
                for observation in failing:
                    self.say(f"    quiet (rehearsal, not waiting): {observation.probe}: {observation.detail}")
                return QuietVerdict(False, True, self.clock() - started, windows, history)
            blockers = tuple(f"{observation.probe}: {observation.detail}" for observation in failing)
            if blockers != last_blockers:
                waited = (self.clock() - started) / 60
                self.say(f"    quiet check waiting ({waited:.0f} min so far); blocked by:")
                for observation in failing:
                    action = f"  -> {observation.action}" if observation.action else ""
                    self.say(f"      - {observation.probe}: {observation.detail}{action}")
                last_blockers = blockers
            if deadline_s is not None and self.clock() - started >= deadline_s:
                raise QuietTimeout(f"no quiet {self.settings.window_s:g} s window in {deadline_s / 3600:.1f} h")
            self.sleep(self.settings.retry_after_s)
