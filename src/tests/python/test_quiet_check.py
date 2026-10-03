"""The automated quiet check (tools/runbook/quiet.py) with fake probes, and the real probes report-only.

PLAN.md's standing approvals start a quiet round only after 60 s in which no
agent, build or guest runs, podman's btrc machine is stopped, Time Machine is
idle and Google Drive, mds and mdworker stay under 5% CPU. The last test runs
the real probes once on whatever host runs the suite: on macOS CI that is the
Darwin ``ps``, ``tmutil`` and ``podman`` the owner's Mac uses, in report-only
mode, because a hosted runner is never quiet.
"""

from __future__ import annotations

import json
import os
import platform
from collections.abc import Sequence
from pathlib import Path

import pytest

from tools.runbook.quiet import (
    CommandRunner,
    CpuProbe,
    Observation,
    PodmanProbe,
    ProcessInfo,
    ProcessProbe,
    ProcessRule,
    ProcessTable,
    ProcFilesystem,
    QuietCheck,
    QuietRefused,
    QuietSettings,
    QuietTimeout,
    TimeMachineProbe,
    WorkspaceProbe,
)


class FakeRunner(CommandRunner):
    """Canned (exit, stdout) per command; a missing entry is a program that is not installed."""

    def __init__(self, outputs: dict[tuple[str, ...], tuple[int, str] | None]) -> None:
        self.outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def output(self, command: Sequence[str]) -> tuple[int, str] | None:
        self.calls.append(tuple(command))
        return self.outputs.get(tuple(command))


def ps_output(*rows: tuple[int, int, str, float, str]) -> tuple[int, str]:
    return 0, "".join(f"{pid:>6} {ppid:>6} {user} {cpu:>5.1f} {args}\n" for pid, ppid, user, cpu, args in rows)


def table(*rows: tuple[int, int, str, float, str], own_pid: int = 500) -> ProcessTable:
    return ProcessTable(FakeRunner({tuple(ProcessTable.COMMAND): ps_output(*rows)}), own_pid=own_pid, proc=None)


class Script:
    """A probe that returns a scripted sequence of verdicts, then repeats the last."""

    name = "scripted"

    def __init__(self, *verdicts: bool) -> None:
        self.verdicts = list(verdicts)
        self.calls = 0

    def observe(self) -> Observation:
        verdict = self.verdicts[min(self.calls, len(self.verdicts) - 1)]
        self.calls += 1
        return Observation(self.name, verdict, "quiet" if verdict else "busy", None if verdict else "stop it")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def check(probes: Sequence[object], clock: FakeClock, *, system: str = "Darwin", **options: object) -> QuietCheck:
    messages: list[str] = []
    quiet = QuietCheck(
        Path("/unused"),
        QuietSettings(window_s=60, interval_s=5, retry_after_s=60),
        system=system,
        probes=probes,  # type: ignore[arg-type]
        clock=clock,
        sleep=clock.sleep,
        say=messages.append,
        **options,  # type: ignore[arg-type]
    )
    quiet.messages = messages  # type: ignore[attr-defined]
    return quiet


# -- the process scan -------------------------------------------------------------


def test_process_table_parses_ps_rows_and_drops_its_own_ancestry_and_children() -> None:
    processes = table(
        (1, 0, "root", 0.0, "/sbin/launchd"),
        (400, 1, "owner", 0.1, "/bin/zsh -l"),
        (450, 400, "owner", 0.0, "nix develop --profile /x --command python3 -m tools.runbook stage5"),
        (500, 450, "owner", 2.0, "python3 -m tools.runbook stage5"),
        (501, 500, "owner", 0.0, "ps -A -o pid="),
        (700, 1, "owner", 30.0, "/usr/bin/clang -c x.c"),
    ).snapshot()

    assert processes is not None
    assert [process.pid for process in processes] == [1, 700]
    assert processes[1].name == "clang"


def test_process_table_rejects_malformed_rows() -> None:
    assert ProcessTable.parse("garbage") is None
    assert ProcessTable.parse("12 1 user notanumber args") is None
    assert ProcessTable.parse("12 1 user 3,5 /bin/x").cpu_percent == 3.5  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("row", "label"),
    [
        ((10, 1, "owner", 1.0, "/opt/claude-code/bin/claude --resume"), "agent"),
        ((11, 1, "owner", 1.0, "/usr/local/bin/codex exec"), "agent"),
        ((20, 1, "owner", 1.0, "node /opt/homebrew/bin/claude --continue"), "agent"),
        ((21, 1, "owner", 1.0, "/Users/o/Library/Application Support/Claude/claude-code/2.1/claude"), "agent"),
        ((12, 1, "owner", 1.0, "/tmp/btrcc-a1b2 --jobs 8 src/BTRSmith.btrc"), "compiler build"),
        ((13, 1, "owner", 1.0, "/nix/store/x-gcc/libexec/gcc/cc1 -quiet x.c"), "compiler build"),
        ((14, 1, "owner", 1.0, "/nix/store/x-python3/bin/python3 -m pytest src/tests -n 8"), "test run"),
        ((15, 1, "_nixbld3", 1.0, "/nix/store/x-bash/bin/bash -e builder.sh"), "nix builder"),
        ((16, 1, "owner", 1.0, "nix build .#btrc-native-header"), "nix build"),
        ((17, 1, "owner", 1.0, "/opt/homebrew/bin/qemu-system-aarch64 -M virt"), "guest"),
        ((18, 1, "owner", 1.0, "/Applications/Xcode.app/Contents/Developer/Applications/Simulator"), "simulator"),
        ((19, 1, "owner", 1.0, "/Users/o/Library/Android/sdk/emulator/emulator -avd Pixel"), "guest"),
    ],
)
def test_the_process_probe_names_every_kind_of_disturbance(row: tuple[int, int, str, float, str], label: str) -> None:
    observation = ProcessProbe(table(row), QuietSettings()).observe()

    assert not observation.ok
    assert observation.detail.startswith(f"{label}: pid {row[0]}")
    assert observation.action


def test_the_process_probe_passes_a_quiet_desktop_and_honours_ignore_rules() -> None:
    quiet_desktop = table(
        (1, 0, "root", 0.0, "/sbin/launchd"),
        (90, 1, "owner", 0.5, "/System/Library/CoreServices/Finder.app/Contents/MacOS/Finder"),
        (91, 1, "owner", 0.2, "/Applications/Claude.app/Contents/MacOS/Claude"),
        (92, 1, "root", 0.0, "/nix/var/nix/profiles/default/bin/nix-daemon"),
        (93, 1, "owner", 0.0, "nix develop --profile /Users/o/.cache/btrc/gcroots/dev"),
    )
    assert ProcessProbe(quiet_desktop, QuietSettings()).observe().ok

    helper = table((30, 1, "owner", 0.0, "/usr/bin/clang --version"))
    settings = QuietSettings().overlay({"ignore": [r"clang --version"]})
    assert ProcessProbe(helper, settings).observe().ok


def test_the_process_probe_fails_closed_when_ps_fails() -> None:
    broken = ProcessTable(FakeRunner({tuple(ProcessTable.COMMAND): (1, "")}), proc=None)

    assert not ProcessProbe(broken, QuietSettings()).observe().ok


def fake_proc(root: Path, uptime: float, *rows: tuple[int, int, str, str, int, bytes]) -> ProcFilesystem:
    """A /proc tree: (pid, ppid, comm, state, cpu ticks, cmdline) per process, started at tick 100."""

    root.mkdir()
    (root / "uptime").write_text(f"{uptime} 0.00\n")
    (root / "self").mkdir()
    for pid, ppid, comm, state, ticks, cmdline in rows:
        entry = root / str(pid)
        entry.mkdir()
        fixed = [state, str(ppid), *["0"] * 9, str(ticks), "0", *["0"] * 6, "100", "0"]
        (entry / "stat").write_text(f"{pid} ({comm}) {' '.join(fixed)}\n")
        (entry / "cmdline").write_bytes(cmdline)
    return ProcFilesystem(root)


def test_the_process_table_reads_proc_on_linux(tmp_path: Path) -> None:
    ticks = os.sysconf("SC_CLK_TCK")
    proc = fake_proc(
        tmp_path / "proc",
        100.0 / ticks + 10.0,
        (10, 1, "clang", "R", 5 * ticks, b"/usr/bin/clang\0-c\0x.c\0"),
        (11, 2, "kworker/0:1 (x)", "I", 0, b""),
    )
    rows = {process.pid: process for process in ProcessTable(FakeRunner({}), own_pid=500, proc=proc).snapshot()}

    assert rows[10].args == "/usr/bin/clang -c x.c" and rows[10].ppid == 1 and rows[10].cpu_percent == 50.0
    assert rows[11].args == "[kworker/0:1 (x)]" and rows[11].ppid == 2
    # The probe reads the same rows: the compile is a build that blocks a quiet round.
    observation = ProcessProbe(ProcessTable(FakeRunner({}), proc=proc), QuietSettings()).observe()
    assert not observation.ok and "pid 10 /usr/bin/clang -c x.c" in observation.detail


def test_an_unreadable_proc_falls_back_to_ps_and_a_failing_ps_fails_closed(tmp_path: Path) -> None:
    missing = ProcFilesystem(tmp_path / "no-proc")
    fallback = ProcessTable(FakeRunner({tuple(ProcessTable.COMMAND): ps_output((7, 1, "u", 0.0, "sh"))}), proc=missing)
    broken = ProcessTable(FakeRunner({tuple(ProcessTable.COMMAND): (1, "")}), proc=missing)

    assert [process.pid for process in fallback.snapshot()] == [7]
    assert broken.snapshot() is None


def test_background_cpu_is_summed_per_group_against_its_limit() -> None:
    busy = table(
        (40, 1, "root", 3.0, "/System/Library/Frameworks/CoreServices.framework/mds"),
        (41, 1, "owner", 2.5, "/System/Library/Frameworks/CoreServices.framework/mdworker_shared -s mdworker"),
        (42, 1, "owner", 2.6, "/usr/libexec/mdworker_shared -s mdworker"),
        (43, 1, "owner", 1.0, "/Applications/Google Drive.app/Contents/MacOS/Google Drive"),
    )
    observation = CpuProbe(busy, QuietSettings()).observe()

    assert not observation.ok
    assert "mdworker at 5.1%" in observation.detail
    assert "mds" not in observation.detail.replace("mdworker", "")

    calm = table((40, 1, "root", 4.9, "/System/Library/Frameworks/CoreServices.framework/mds"))
    assert CpuProbe(calm, QuietSettings()).observe().ok


# -- podman, Time Machine, workspace ----------------------------------------------------

PODMAN = ("podman", "machine", "list", "--format", "json")


@pytest.mark.parametrize(
    ("output", "ok"),
    [
        (None, True),
        ((0, json.dumps([{"Name": "podman-machine-default*", "Running": False}])), True),
        (
            (
                0,
                json.dumps([{"Name": "semu-1", "Running": True}, {"Name": "podman-machine-default", "Running": False}]),
            ),
            True,
        ),
        ((0, json.dumps([{"Name": "podman-machine-default*", "Running": True}])), False),
        ((0, json.dumps([{"Name": "podman-machine-default", "Running": False, "Starting": True}])), False),
        ((0, "not json"), False),
        ((125, ""), False),
        ((0, "null"), True),
    ],
)
def test_podman_judges_only_the_btrc_machine(output: tuple[int, str] | None, ok: bool) -> None:
    observation = PodmanProbe(FakeRunner({PODMAN: output}), "podman-machine-default").observe()

    assert observation.ok is ok
    if not ok and "running" in observation.detail:
        assert observation.action == "podman machine stop podman-machine-default"


@pytest.mark.parametrize(
    ("output", "required", "ok"),
    [
        ((0, "BackupNotRunning\n"), True, True),
        ((0, "Copying\n"), True, False),
        ((1, ""), True, False),
        (None, True, False),
        (None, False, True),
    ],
)
def test_time_machine_must_report_backup_not_running(output: tuple[int, str] | None, required: bool, ok: bool) -> None:
    observation = TimeMachineProbe(FakeRunner({("tmutil", "currentphase"): output}), required).observe()

    assert observation.ok is ok


def test_the_workspace_must_live_under_bench_noindex(tmp_path: Path) -> None:
    root = tmp_path / "bench.noindex"

    assert WorkspaceProbe(root / "stage5-2026-10-03", root).observe().ok
    assert not WorkspaceProbe(tmp_path / "bench" / "stage5", root).observe().ok


# -- waiting --------------------------------------------------------------------------


def test_a_full_quiet_window_is_thirteen_samples_five_seconds_apart() -> None:
    clock = FakeClock()
    probe = Script(True)
    verdict = check([probe], clock).wait()

    assert verdict.quiet and not verdict.advisory
    assert verdict.windows == 1
    assert probe.calls == 13
    assert clock.sleeps == [5] * 12


def test_a_busy_sample_restarts_the_window_after_the_retry_pause() -> None:
    clock = FakeClock()
    probe = Script(True, True, False, True)
    quiet = check([probe], clock)
    verdict = quiet.wait()

    assert verdict.quiet
    assert verdict.windows == 2
    assert clock.sleeps[:3] == [5, 5, 60]
    assert any("blocked by" in message for message in quiet.messages)  # type: ignore[attr-defined]
    assert any("-> stop it" in message for message in quiet.messages)  # type: ignore[attr-defined]


def test_unchanged_blockers_are_announced_once() -> None:
    clock = FakeClock()
    quiet = check([Script(False, False, False, True)], clock)
    quiet.wait()

    assert sum("blocked by" in message for message in quiet.messages) == 1  # type: ignore[attr-defined]


def test_the_wait_gives_up_at_its_deadline() -> None:
    clock = FakeClock()

    with pytest.raises(QuietTimeout):
        check([Script(False)], clock).wait(deadline_s=300)
    assert clock.now >= 300


def test_the_check_refuses_other_hosts_unless_rehearsing() -> None:
    with pytest.raises(QuietRefused, match="--rehearsal"):
        check([Script(True)], FakeClock(), system="Linux").wait()


def test_a_rehearsal_reports_blockers_without_waiting() -> None:
    clock = FakeClock()
    quiet = check([Script(False)], clock, system="Linux", rehearsal=True)
    verdict = quiet.wait()

    assert not verdict.quiet and verdict.advisory
    assert clock.sleeps == []
    assert verdict.as_dict()["blockers"] == [{"probe": "scripted", "ok": False, "detail": "busy", "action": "stop it"}]
    assert any("rehearsal, not waiting" in message for message in quiet.messages)  # type: ignore[attr-defined]


# -- settings ---------------------------------------------------------------------------


def test_settings_are_tunable_without_code(tmp_path: Path) -> None:
    local = tmp_path / "quiet.toml"
    local.write_text(
        'window_s = 120\nignore = ["helper-daemon"]\n'
        '[[extra_process_rules]]\nlabel = "renderer"\npattern = "Blender"\nfield = "name"\n'
        '[[extra_cpu_rules]]\nlabel = "Dropbox"\npattern = "Dropbox"\nlimit_percent = 2\n'
    )
    settings = QuietSettings().load(local)

    assert settings.window_s == 120
    assert settings.process_rules[-1] == ProcessRule("renderer", "Blender", "name")
    assert len(settings.process_rules) == len(QuietSettings().process_rules) + 1
    assert settings.cpu_rules[-1].limit_percent == 2
    assert settings.ignore == ("helper-daemon",)
    assert QuietSettings().load(tmp_path / "absent.toml") == QuietSettings()

    replaced = QuietSettings().overlay({"process_rules": [{"label": "only", "pattern": "x"}]})
    assert replaced.process_rules == (ProcessRule("only", "x"),)


@pytest.mark.parametrize(
    ("table_", "message"),
    [
        ({"window": 60}, "unknown quiet setting"),
        ({"interval_s": -1}, "must not be negative"),
        ({"ignore": ["("]}, "missing \\)"),
    ],
)
def test_bad_settings_are_rejected(table_: dict[str, object], message: str) -> None:
    with pytest.raises(Exception, match=message):
        QuietSettings().overlay(table_)


def test_process_info_name_is_the_executable_basename() -> None:
    assert ProcessInfo(1, 0, "u", 0.0, "/usr/bin/clang -c x.c").name == "clang"
    assert ProcessInfo(1, 0, "u", 0.0, "").name == ""


# -- the real probes, report-only -------------------------------------------------------


def test_the_real_probes_report_on_this_host(tmp_path: Path) -> None:
    """Every real probe answers without raising; on macOS the Darwin tools are really consulted."""

    quiet = QuietCheck(tmp_path / "bench.noindex" / "run", rehearsal=True)
    observations = {observation.probe: observation for observation in quiet.report()}

    assert set(observations) == {"processes", "podman", "time-machine", "background-cpu", "workspace"}
    assert all(observation.detail for observation in observations.values())
    assert "ps failed" not in observations["processes"].detail
    assert "ps failed" not in observations["background-cpu"].detail
    print(json.dumps([observation.as_dict() for observation in observations.values()], indent=2))
    if platform.system() == "Darwin":
        # A hosted runner may be backing up or indexing; the probe must still have read a phase.
        assert "not available" not in observations["time-machine"].detail
        assert "missing" not in observations["time-machine"].detail
        assert "mds" in observations["background-cpu"].detail or not observations["background-cpu"].ok
    else:
        assert observations["time-machine"].ok
        with pytest.raises(QuietRefused):
            QuietCheck(tmp_path).wait()
