"""The runbook engine (tools/runbook) against fake hubs, fake BTRSmith trees and fake probes.

Nothing here needs the Mac or BTRSmith: each test builds a small btrc "hub"
and BTRSmith "hub" as git repositories under tmp_path, writes a preset whose
cells are short shell commands, and runs the engine with ``--rehearsal`` (or
with the host injected as Darwin) so locks, clones, checkpoints, resumption,
the quiet hook and evidence publication are exercised end to end.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import ClassVar

import pytest

from src.tests.process_limits import TOOL_TIMEOUT
from tools.runbook import engine as runbook
from tools.runbook.engine import CellOutcome, Host, Preset, RunbookEngine, RunbookError, RunOptions
from tools.runbook.evidence import EvidencePublisher, Redactor, SecretScan
from tools.runbook.quiet import Observation, QuietCheck, QuietSettings

REPO = Path(__file__).resolve().parents[3]
TODAY = datetime.date(2026, 10, 3)


@pytest.fixture(autouse=True)
def git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "GIT_AUTHOR_NAME": "runbook test",
        "GIT_AUTHOR_EMAIL": "runbook@test.invalid",
        "GIT_COMMITTER_NAME": "runbook test",
        "GIT_COMMITTER_EMAIL": "runbook@test.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("BTRC_TEST_BTRCC", raising=False)


@pytest.fixture(autouse=True)
def lock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The Mac's lock files, as AGENTS.md "Locks" lays them out."""

    directory = tmp_path / "locks"
    directory.mkdir()
    for name in ("gate", "bench", "linux-ci", "guest", "gui-capture", "signing", "btrcc-build.1", "btrcc-build.2"):
        (directory / name).touch()
    monkeypatch.setenv("BTRC_LOCK_DIR", str(directory))
    return directory
    monkeypatch.delenv("BTRC_TEST_BTRCC", raising=False)


def git(*arguments: str, cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=cwd, capture_output=True, text=True, check=True, timeout=TOOL_TIMEOUT
    )
    return completed.stdout.strip()


def make_repo(root: Path, files: dict[str, str], *, branches: dict[str, dict[str, str]] | None = None) -> Path:
    root.mkdir(parents=True)
    git("init", "--quiet", "--initial-branch=main", cwd=root)
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git("add", "-A", cwd=root)
    git("commit", "--quiet", "-m", "initial", cwd=root)
    for branch, changes in (branches or {}).items():
        git("checkout", "--quiet", "-b", branch, cwd=root)
        for relative, text in changes.items():
            (root / relative).write_text(text)
        git("commit", "--quiet", "-am", branch, cwd=root)
        git("checkout", "--quiet", "main", cwd=root)
    return root


@pytest.fixture
def hubs(tmp_path: Path) -> dict[str, Path]:
    """A btrc hub with a Makefile and a stdlib, and a BTRSmith hub with a pin-bump branch, each mirroring an upstream."""

    btrc_upstream = tmp_path / "upstream" / "btrc.git"
    btrsmith_upstream = tmp_path / "upstream" / "btrsmith.git"
    for upstream in (btrc_upstream, btrsmith_upstream):
        upstream.mkdir(parents=True)
        git("init", "--quiet", "--bare", "--initial-branch=main", cwd=upstream)
    btrc = make_repo(
        tmp_path / "btrc-hub",
        {"Makefile": "test:\n\ttrue\n", "src/stdlib/Prelude.btrc": "// prelude\n", "README.md": "btrc\n"},
    )
    btrsmith = make_repo(
        tmp_path / "btrsmith-hub",
        {"src/BTRSmith.btrc": "int main() { return 0; }\n", "flake.nix": "{ }\n"},
        branches={"stage4/pin-bump": {"flake.nix": "{ pinned = true; }\n"}},
    )
    git("remote", "add", "origin", str(btrc_upstream), cwd=btrc)
    git("push", "--quiet", "origin", "main", cwd=btrc)
    git("remote", "add", "origin", str(btrsmith_upstream), cwd=btrsmith)
    git("push", "--quiet", "origin", "main", cwd=btrsmith)
    return {"btrc": btrc, "btrsmith": btrsmith, "btrc_upstream": btrc_upstream, "btrsmith_upstream": btrsmith_upstream}


def write_preset(directory: Path, body: str, name: str = "fake") -> Path:
    path = directory / f"{name}.toml"
    path.write_text(textwrap.dedent(body))
    return path


def options(tmp_path: Path, hubs: dict[str, Path], preset: Path, *extra: str) -> RunOptions:
    return RunOptions.parse(
        [
            str(preset),
            "--home", str(tmp_path / "home"),
            "--btrsmith-home", str(tmp_path / "bsm-home"),
            "--btrc-hub", str(hubs["btrc"]),
            "--btrsmith-hub", str(hubs["btrsmith"]),
            "--min-free-gb", "0",
            *extra,
        ]
    )  # fmt: skip


class FakeQuiet(QuietCheck):
    def __init__(self, workspace: Path, settings: QuietSettings, rehearsal: bool) -> None:
        super().__init__(workspace, settings, rehearsal=rehearsal, system="Darwin", probes=[], say=lambda _: None)
        self.waited = 0

    def wait(self, deadline_s: float | None = None):  # type: ignore[no-untyped-def]
        FakeQuiet.calls.append(self.settings.window_s)
        from tools.runbook.quiet import QuietVerdict

        return QuietVerdict(True, False, 0.0, 1, [[Observation("fake", True, "quiet")]])

    calls: ClassVar[list[float]] = []


def engine_for(
    preset_path: Path, run_options: RunOptions, *, system: str = "Linux", today: datetime.date = TODAY
) -> RunbookEngine:
    FakeQuiet.calls = []
    return RunbookEngine(
        Preset.load(str(preset_path)),
        run_options,
        host=Host(system),
        quiet_factory=FakeQuiet,
        today=lambda: today,
    )


COUNTING_PRESET = """\
    [preset]
    title = "fake round"
    packet = "MAC-TEST"
    kind = "measurement"
    quiet = true
    next_action = "go to bed"

    [btrsmith]
    pins = { old = "main", new = "stage4/pin-bump" }
    branch_pin = "new"

    [variables]
    greeting = "hello from {home}"
    report_text = REPORT

    [stand_in]
    collapse = ["pin"]

    [[budget]]
    scenario = "noop"
    limit = 5
    [[budget]]
    frontend = "reference"
    scenario = "noop"
    limit = 1

    [[cell]]
    id = "count-{pin}-{frontend}"
    title = "count {pin} {frontend}"
    matrix = { pin = ["old", "new"], frontend = ["selfhost", "reference"] }
    lock = "bench"
    result = "budget-bench"
    env = { REPORT = "{report_text}" }
    command = ["sh", "-c", "echo {pin} >> {run}/executions; printf '%s' \\"$REPORT\\" > {out}/report.json; echo {greeting}"]

    [[cell]]
    id = "whoami"
    title = "which BTRSmith"
    quiet = false
    cwd = "btrsmith"
    command = ["sh", "-c", "git rev-parse HEAD > {out}/sha; cat flake.nix"]
    """


def report_json(median: float) -> str:
    return json.dumps(
        {
            "failure": None,
            "dry_run": False,
            "configuration": {"stand_in": False},
            "scenarios": {
                "noop": {"samples": [median] * 3, "median": median, "p95": median, "max": median, "facts": {}}
            },
        }
    )


def counting_preset(tmp_path: Path) -> Path:
    return write_preset(tmp_path, COUNTING_PRESET.replace("REPORT\n", json.dumps(report_json(2.0)) + "\n", 1))


# -- presets ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["stage4-requal", "stage5", "stage13-final", "stage6-reference"])
def test_every_shipped_preset_parses_and_expands(name: str) -> None:
    preset = Preset.load(name)

    for stand_in in (False, True):
        cells = preset.cells(stand_in=stand_in)
        assert cells
        assert len({cell.id for cell in cells}) == len(cells)
        for cell in cells:
            assert "{pin}" not in cell.id and "{frontend}" not in cell.id
    assert preset.packet.startswith("MAC-R-")


def test_stage5_measures_both_pins_on_both_frontends_with_quiet_before_every_measurement() -> None:
    preset = Preset.load("stage5")
    cells = {cell.id: cell for cell in preset.cells(stand_in=False)}

    for pin in ("aeeca0fd", "post-stage4"):
        for frontend in ("selfhost", "reference"):
            for kind in ("product-cold", "product-edits", "product-steady", "batch", "make-noop"):
                cell = cells[f"{kind}-{pin}-{frontend}"]
                assert cell.quiet and cell.lock == "bench" and cell.result == "budget-bench"
    assert preset.pins == {"aeeca0fd": "aeeca0fd", "post-stage4": "main"}
    product = " ".join(cells["product-cold-aeeca0fd-selfhost"].command)
    for option in ("--timing-cold", "--native-jobs {native_jobs}", "--workers {workers}", "{scenarios_cold}"):
        assert option in product
    assert preset.variables["workers"] == "1,2,4,8" and preset.variables["native_jobs"] == "8"
    assert preset.variables["cold_samples"] == "5" and preset.variables["incremental_samples"] == "20"
    assert "--entry make" in " ".join(cells["make-noop-post-stage4-selfhost"].command)
    assert "self-compile,corpus" in " ".join(cells["scaling-reference"].command)
    assert cells["btrcc"].provides == "btrcc" and cells["btrcc"].lock == "btrcc-build"
    assert {budget.scenario for budget in preset.budgets} >= {"cold-transpile", "cold-dev", "noop", "batch", "memory"}


def test_stage4_requal_orders_gate_release_checks_diff_and_a_green_only_push() -> None:
    preset = Preset.load("stage4-requal")
    ids = [cell.id for cell in preset.cells(stand_in=False) if not cell.optional]

    assert ids == ["gate", "release-check-reference", "release-check-selfhost", "qualifying-diff", "push-btrsmith-main"]
    cells = {cell.id: cell for cell in preset.cells(stand_in=False)}
    assert cells["gate"].lock == "gate" and "batch_gate.sh" in cells["gate"].command[0]
    assert cells["release-check-selfhost"].lock == "gui-capture" and cells["release-check-selfhost"].retries == 1
    assert cells["push-btrsmith-main"].when == "green" and cells["push-btrsmith-main"].action == "push"
    assert all(cells[cell].optional for cell in ("ab-build-before", "ab-instr-after"))
    assert preset.branch_pin == "requal"
    assert preset.evidence_repo == "btrsmith"
    assert Preset.load("stage5").evidence_repo == "btrc"


def test_stage13_final_stops_at_the_first_red_gate_and_compares_with_stage5() -> None:
    preset = Preset.load("stage13-final")
    cells = preset.cells(stand_in=False)

    assert preset.on_failure == "stop"
    assert [cell.id for cell in cells[:3]] == ["gate", "determinism", "btrcc"]
    assert cells[1].requires == ("make:test-determinism",)
    assert {rule["scenario"] for rule in preset.regressions} == {"self-compile", "corpus"}


@pytest.mark.parametrize(
    ("cell", "message"),
    [
        ('id = "x"\ncommand = ["true"]\nlock = "nope"', "lock 'nope'"),
        ('id = "x"\ncommand = ["true"]\nresult = "magic"', "result 'magic'"),
        ('id = "x"\ncommand = ["true"]\ncolour = "red"', "unknown key"),
        ('id = "x"', "exactly one of command or action"),
        ('id = "x"\naction = "subset"', "needs of and allowed"),
        ('id = "x"\naction = "push"', "repo = btrc or btrsmith"),
        ('id = "x"\ncommand = ["true"]\n[[cell]]\nid = "x"\ncommand = ["true"]', "duplicate cell id"),
    ],
)
def test_bad_presets_are_refused_with_the_reason(tmp_path: Path, cell: str, message: str) -> None:
    path = write_preset(tmp_path, f'[preset]\ntitle = "bad"\n[[cell]]\n{cell}\n')

    with pytest.raises(RunbookError, match=message):
        Preset.load(str(path))


def test_an_unknown_preset_lists_the_known_ones() -> None:
    with pytest.raises(RunbookError, match="stage5"):
        Preset.load("no-such-preset")


# -- running, resuming ----------------------------------------------------------------


def test_a_rehearsal_runs_every_cell_then_resumes_without_repeating_any(
    tmp_path: Path, hubs: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    preset = counting_preset(tmp_path)
    first = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))

    assert first.run() == 0
    state = first.state
    assert state is not None
    assert state.run_id == "fake-2026-10-03"
    assert state.work == tmp_path / "home" / "bench.noindex" / "fake-2026-10-03"
    assert (state.work / "executions").read_text().split() == ["old", "old", "new", "new"]
    assert FakeQuiet.calls == [10.0] * 4
    new_pin = git("rev-parse", "stage4/pin-bump", cwd=hubs["btrsmith"])
    assert (state.cell_out("whoami") / "sha").read_text().strip() == new_pin
    assert (tmp_path / "bsm-home" / "clones" / "fake" / "old" / ".git").is_dir()
    log = state.cell_log("count-old-selfhost").read_text()
    assert f"hello from {tmp_path / 'home'}" in log

    summary = json.loads((state.work / "summary.json").read_text())
    assert summary["result"] == "green" and summary["acceptance"] is False
    assert summary["provenance"]["btrsmith"]["new"]["sha"] == new_pin
    assert summary["provenance"]["stdlib_tree"] == git("rev-parse", "HEAD:src/stdlib", cwd=hubs["btrc"])
    misses = summary["budget_misses"]
    assert [miss["cell"] for miss in misses] == ["count-old-reference", "count-new-reference"]
    assert summary["publication"]["pushed"] is False
    staged = state.work / "evidence" / state.run_id
    assert (staged / "summary.json").is_file() and (staged / "cells" / "count-new-selfhost" / "report.json").is_file()
    printed = capsys.readouterr().out
    assert "next: rehearsal complete" in printed

    second = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))
    assert second.run() == 0
    assert (state.work / "executions").read_text().split() == ["old", "old", "new", "new"]
    assert "not repeated" in capsys.readouterr().out
    assert FakeQuiet.calls == []


def test_a_resumed_run_keeps_the_shas_it_resolved_first(tmp_path: Path, hubs: dict[str, Path]) -> None:
    preset = counting_preset(tmp_path)
    first = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))
    first.run()
    pinned = first.frozen["shas"]["btrsmith"]["new"]
    git("checkout", "--quiet", "stage4/pin-bump", cwd=hubs["btrsmith"])
    (hubs["btrsmith"] / "flake.nix").write_text("{ moved = true; }\n")
    git("commit", "--quiet", "-am", "moved", cwd=hubs["btrsmith"])
    git("checkout", "--quiet", "main", cwd=hubs["btrsmith"])

    second = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))
    second.run()

    assert second.frozen["shas"]["btrsmith"]["new"] == pinned
    fresh = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal", "--fresh"))
    fresh.run()
    assert fresh.state is not None and fresh.state.run_id == "fake-2026-10-03-2"
    assert fresh.frozen["shas"]["btrsmith"]["new"] != pinned


def test_resuming_with_different_options_is_refused(tmp_path: Path, hubs: dict[str, Path]) -> None:
    preset = counting_preset(tmp_path)
    engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal")).run()

    with pytest.raises(RunbookError, match="--fresh"):
        engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal", "--dry-run")).run()
    with pytest.raises(RunbookError, match="refs"):
        engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal", "--btrsmith-branch", "main")).run()


def test_failed_cells_rerun_on_resume_and_retries_take_a_second_attempt(tmp_path: Path, hubs: dict[str, Path]) -> None:
    flag = tmp_path / "flag"
    preset = write_preset(
        tmp_path,
        f"""\
        [preset]
        title = "flaky"
        [[cell]]
        id = "flaky"
        retries = 1
        command = ["sh", "-c", "if [ -e {flag} ]; then echo second; else touch {flag}; echo first; exit 3; fi"]
        [[cell]]
        id = "broken"
        command = ["sh", "-c", "test -e {flag}.ok"]
        """,
    )
    engine = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))

    assert engine.run() == 1
    assert engine.state is not None
    flaky = engine.state.checkpoint("flaky")
    assert flaky is not None and flaky.status == "passed" and flaky.attempts == 2
    assert engine.state.checkpoint("broken").status == "failed"  # type: ignore[union-attr]

    Path(f"{flag}.ok").touch()
    again = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))
    assert again.run() == 0
    assert again.state.checkpoint("flaky").attempts == 2  # type: ignore[union-attr]


def test_a_stopping_preset_reaches_nothing_after_its_first_failure(tmp_path: Path, hubs: dict[str, Path]) -> None:
    preset = write_preset(
        tmp_path,
        """\
        [preset]
        title = "chain"
        kind = "gate"
        on_failure = "stop"
        [[cell]]
        id = "first"
        command = ["false"]
        [[cell]]
        id = "second"
        command = ["true"]
        """,
    )
    engine = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))

    assert engine.run() == 1
    assert engine.state is not None
    assert engine.state.work == tmp_path / "home" / "gates" / "fake-2026-10-03"
    summary = json.loads((engine.state.work / "summary.json").read_text())
    assert summary["result"] == "red" and summary["not_reached"] == ["second"]
    assert "rerun the same command" in summary_text(engine)


def summary_text(engine: RunbookEngine) -> str:
    assert engine.state is not None
    return (engine.state.work / "summary.txt").read_text()


def test_requirements_absent_on_the_revision_fail_with_a_named_reason(tmp_path: Path, hubs: dict[str, Path]) -> None:
    preset = write_preset(
        tmp_path,
        """\
        [preset]
        title = "needs"
        [[cell]]
        id = "has-test"
        requires = ["make:test"]
        command = ["true"]
        [[cell]]
        id = "determinism"
        requires = ["make:test-determinism"]
        command = ["true"]
        [[cell]]
        id = "path"
        requires = ["path:{btrc}/README.md"]
        command = ["true"]
        """,
    )
    engine = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))
    engine.run()
    state = engine.state
    assert state is not None

    assert state.checkpoint("has-test").status == "passed"  # type: ignore[union-attr]
    assert state.checkpoint("path").status == "passed"  # type: ignore[union-attr]
    missing = state.checkpoint("determinism")
    assert missing is not None and missing.status == "failed"
    assert "no `test-determinism` target" in missing.message


# -- release-check failures, the qualifying diff, the green-only push ------------------------

REQUAL = """\
    [preset]
    title = "requal"
    kind = "gate"
    evidence_repo = "btrsmith"
    [btrsmith]
    pins = { requal = "stage4/pin-bump" }
    [variables]
    qualifying_failures = "{home}/qualifying.txt"
    [[cell]]
    id = "release-check-{frontend}"
    matrix = { frontend = ["reference", "selfhost"] }
    cwd = "btrsmith"
    result = "failure-list"
    lock = "gui-capture"
    command = ["sh", "-c", "echo 'FAILED tests/Drifted.py::test_{frontend}'; echo 'FAILED tests/Old.py::test_x'; exit 2"]
    [[cell]]
    id = "qualifying-diff"
    action = "subset"
    of = "release-check-*"
    allowed = "{qualifying_failures}"
    [[cell]]
    id = "push-btrsmith-main"
    action = "push"
    repo = "btrsmith"
    branch = "main"
    when = "green"
    """


def test_new_release_check_failures_block_the_push(
    tmp_path: Path, hubs: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    preset = write_preset(tmp_path, REQUAL)
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "qualifying.txt").write_text("# Stage 2\ntests/Old.py::test_x\ntests/Gone.py::test_y\n")
    engine = engine_for(preset, options(tmp_path, hubs, preset), system="Darwin")

    assert engine.run() == 1
    state = engine.state
    assert state is not None
    reference = state.checkpoint("release-check-reference")
    assert reference is not None and reference.status == "passed" and reference.exit == 2
    assert reference.results["failures"] == ["tests/Drifted.py::test_reference", "tests/Old.py::test_x"]
    diff = state.checkpoint("qualifying-diff")
    assert diff is not None and diff.status == "failed"
    assert diff.results["new_failures"] == ["tests/Drifted.py::test_reference", "tests/Drifted.py::test_selfhost"]
    assert diff.results["now_passing"] == ["tests/Gone.py::test_y"]
    push = state.checkpoint("push-btrsmith-main")
    assert push is not None and push.status == "blocked"
    assert git("rev-parse", "main", cwd=hubs["btrsmith_upstream"]) == git("rev-parse", "main", cwd=hubs["btrsmith"])


def test_a_green_requalification_fast_forwards_btrsmith_main_upstream(
    tmp_path: Path, hubs: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    preset = write_preset(tmp_path, REQUAL)
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "qualifying.txt").write_text(
        "tests/Old.py::test_x\ntests/Drifted.py::test_reference\ntests/Drifted.py::test_selfhost\n"
    )
    engine = engine_for(preset, options(tmp_path, hubs, preset), system="Darwin")

    assert engine.run() == 0
    pin = git("rev-parse", "stage4/pin-bump", cwd=hubs["btrsmith"])
    assert git("rev-parse", "main", cwd=hubs["btrsmith_upstream"]) == pin
    assert engine.state.checkpoint("push-btrsmith-main").results["sha"] == pin  # type: ignore[union-attr]
    # Its summary names BTRSmith tests, so the evidence goes to the private repository only (§7 Q24).
    assert git("ls-remote", "--heads", str(hubs["btrsmith_upstream"]), "evidence/*", cwd=tmp_path)
    assert not git("ls-remote", "--heads", str(hubs["btrc_upstream"]), "evidence/*", cwd=tmp_path)


def test_a_missing_qualifying_list_names_the_owner_action(tmp_path: Path, hubs: dict[str, Path]) -> None:
    preset = write_preset(tmp_path, REQUAL)
    engine = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))
    engine.run()

    diff = engine.state.checkpoint("qualifying-diff")  # type: ignore[union-attr]
    assert diff is not None and diff.status == "failed"
    assert "write the allowed failures there" in diff.message


def test_pushes_never_happen_in_a_rehearsal_or_dry_run(tmp_path: Path, hubs: dict[str, Path]) -> None:
    preset = write_preset(
        tmp_path,
        '[preset]\ntitle = "p"\n[btrsmith]\npins = { a = "stage4/pin-bump" }\n'
        '[[cell]]\nid = "push"\naction = "push"\nrepo = "btrsmith"\n',
    )
    engine = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))

    assert engine.run() == 0
    assert engine.state.checkpoint("push").status == "skipped"  # type: ignore[union-attr]
    assert git("rev-parse", "main", cwd=hubs["btrsmith_upstream"]) == git("rev-parse", "main", cwd=hubs["btrsmith"])


# -- stand-in, btrcc, host checks -------------------------------------------------------------


def test_stage5_rehearsal_commands_use_the_stand_in_and_one_sample(tmp_path: Path, hubs: dict[str, Path]) -> None:
    run_options = options(tmp_path, hubs, PRESETS_STAGE5, "--rehearsal", "--stand-in", "--dry-run")
    engine = RunbookEngine(Preset.load("stage5"), run_options, host=Host("Linux"), today=lambda: TODAY)
    engine.frozen = {"shas": {"btrc": "0" * 40}}
    state = engine.new_state()
    cells = {cell.id: cell for cell in engine.cells}

    assert set(cells) == {
        "btrcc",
        *(
            f"product-{group}-stand-in-{frontend}"
            for group in ("cold", "edits", "steady")
            for frontend in ("selfhost", "reference")
        ),
        "batch-stand-in-selfhost",
        "batch-stand-in-reference",
        "make-noop-stand-in-selfhost",
        "make-noop-stand-in-reference",
        "scaling-selfhost",
        "scaling-reference",
    }
    selfhost = engine.expand_command(
        cells["product-cold-stand-in-selfhost"].command, engine.context(cells["product-cold-stand-in-selfhost"], state)
    )
    reference = engine.expand_command(
        cells["product-cold-stand-in-reference"].command,
        engine.context(cells["product-cold-stand-in-reference"], state),
    )
    assert selfhost[:5] == ["python3", "-m", "tools.budget_bench", "--btrcc", str(state.work / "btrcc" / "btrcc")]
    assert "--stand-in" in selfhost and "--dry-run" in selfhost and "--workspace" not in selfhost
    assert "--btrcc" not in reference
    scaling = engine.expand_command(cells["scaling-selfhost"].command, engine.context(cells["scaling-selfhost"], state))
    assert scaling[scaling.index("--corpus-jobs") + 1] == "4"
    assert engine.skip_reason(cells["batch-stand-in-selfhost"], {}) is not None
    assert engine.skip_reason(cells["make-noop-stand-in-reference"], {}) is not None
    assert engine.skip_reason(cells["product-cold-stand-in-selfhost"], {}) is None


PRESETS_STAGE5 = runbook.PRESETS / "stage5.toml"


def test_cells_that_need_btrcc_wait_for_its_build(tmp_path: Path, hubs: dict[str, Path]) -> None:
    preset = write_preset(
        tmp_path,
        """\
        [preset]
        title = "b"
        [[cell]]
        id = "btrcc"
        provides = "btrcc"
        command = ["false"]
        [[cell]]
        id = "use"
        command = ["test", "-x", "{btrcc}"]
        """,
    )
    engine = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))
    engine.run()
    assert engine.state.checkpoint("use").status == "blocked"  # type: ignore[union-attr]

    given = tmp_path / "given-btrcc"
    given.write_text("#!/bin/sh\n")
    given.chmod(0o755)
    reused = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal", "--fresh", "--btrcc", str(given)))
    assert reused.run() == 0
    assert reused.state.checkpoint("btrcc").message.startswith("using --btrcc")  # type: ignore[union-attr]


def test_the_engine_refuses_other_hosts_and_short_disks(tmp_path: Path, hubs: dict[str, Path]) -> None:
    preset = counting_preset(tmp_path)

    with pytest.raises(RunbookError, match="--rehearsal"):
        engine_for(preset, options(tmp_path, hubs, preset)).run()
    with pytest.raises(RunbookError, match="GB are required"):
        engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal", "--min-free-gb", "1e12")).run()


def test_a_dirty_clone_is_never_overwritten(tmp_path: Path, hubs: dict[str, Path]) -> None:
    preset = counting_preset(tmp_path)
    engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal")).run()
    (tmp_path / "home" / "clones" / "fake" / "README.md").write_text("edited\n")

    with pytest.raises(RunbookError, match="local changes"):
        engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal", "--fresh")).run()


def test_test_btrcc_is_pruned_to_the_newest_twenty_and_pinned_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "build" / "test-btrcc"
    for index in range(25):
        entry = root / f"fp{index:02d}"
        entry.mkdir(parents=True)
        os.utime(entry, (1_000_000 + index, 1_000_000 + index))
    monkeypatch.setenv("BTRC_TEST_BTRCC", str(root / "fp01" / "btrcc"))

    removed = Host.prune_test_btrcc(tmp_path)

    assert sorted(path.name for path in removed) == ["fp00", "fp02", "fp03", "fp04"]
    assert len(list(root.iterdir())) == 21


def test_the_host_entry_follows_the_compiler_host() -> None:
    assert Host("Darwin").entry() == "src/compiler/btrc/cli/MacOSMain.btrc"
    assert Host("Linux").entry() == "src/compiler/btrc/BtrccMain.btrc"


def test_locks_exclude_withlock_sh_and_each_other(tmp_path: Path, lock_dir: Path) -> None:
    """The engine's flock excludes macOS lockf (withlock.sh) on the same file, and util-linux flock."""

    locks = runbook.Locks(lock_dir, create=False)
    with locks.held("bench"):
        if Path("/usr/bin/lockf").exists():
            # withlock.sh's own call: -t 0 gives up at once with EX_TEMPFAIL (75) when the lock is held.
            busy = subprocess.run(
                ["/usr/bin/lockf", "-s", "-k", "-t", "0", str(lock_dir / "bench"), "true"], timeout=TOOL_TIMEOUT
            )
            assert busy.returncode == 75
        elif shutil.which("flock"):
            busy = subprocess.run(["flock", "-n", str(lock_dir / "bench"), "true"], timeout=TOOL_TIMEOUT)
            assert busy.returncode == 1
        else:
            import fcntl

            with (lock_dir / "bench").open("a") as other, pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if Path("/usr/bin/lockf").exists():
        free = subprocess.run(
            ["/usr/bin/lockf", "-s", "-k", "-t", "0", str(lock_dir / "bench"), "true"], timeout=TOOL_TIMEOUT
        )
        assert free.returncode == 0

    with locks.held("btrcc-build"), locks.held("btrcc-build"):
        pass  # two slots: a second build gets the other one
    with (
        pytest.raises(RunbookError, match="does not exist"),
        runbook.Locks(tmp_path / "none", create=False).held("gate"),
    ):
        pass
    with runbook.Locks(tmp_path / "fresh", create=True).held("gate"):
        assert (tmp_path / "fresh" / "gate").is_file()


# -- evidence ---------------------------------------------------------------------------------


def test_redaction_replaces_every_home_path() -> None:
    redactor = Redactor(Path("/Users/owner"))

    assert redactor.text("/Users/owner/.cache/btrc/x and /Users/other/y and /home/me/z") == (
        "~/.cache/btrc/x and /Users/<redacted>/y and /home/<redacted>/z"
    )
    assert redactor.value({"/Users/owner/a": ["/Users/owner/b", 3]}) == {"~/a": ["~/b", 3]}
    host = {"system": "Darwin", "node": "Owners-MacBook-Pro.local", "release": "27.0"}
    assert redactor.value({"host": host}) == {"host": {"system": "Darwin", "node": "<redacted>", "release": "27.0"}}


def test_the_builtin_secret_scan_finds_tokens_keys_and_home_paths(tmp_path: Path) -> None:
    (tmp_path / "clean.json").write_text('{"path": "~/.cache/btrc", "sha": "' + "a" * 40 + '"}\n')
    assert SecretScan.builtin(tmp_path) == []

    (tmp_path / "leak.txt").write_text(
        "token ghp_" + "A" * 36 + "\n-----BEGIN OPENSSH PRIVATE KEY-----\n/Users/owner/x\n"
    )
    findings = SecretScan.builtin(tmp_path)
    assert findings == ["leak.txt:1: GitHub token", "leak.txt:2: private key", "leak.txt:3: home path"]


def acceptance_run(tmp_path: Path, hubs: dict[str, Path], *extra: str) -> RunbookEngine:
    preset = write_preset(
        tmp_path,
        """\
        [preset]
        title = "evidence"
        next_action = "read the branch"
        [[cell]]
        id = "gate"
        result = "gate-summary"
        command = ["sh", "-c", "printf 'tree x\\nlint exit=0 3s ok\\ntest exit=0 99s 12 passed\\n' > {out}/summary.txt"]
        """,
    )
    engine = engine_for(
        preset,
        options(tmp_path, hubs, preset, "--evidence-remote", str(hubs["btrc_upstream"]), *extra),
        system="Darwin",
    )
    return engine


def test_an_acceptance_run_pushes_redacted_summaries_to_an_evidence_branch(
    tmp_path: Path, hubs: dict[str, Path]
) -> None:
    engine = acceptance_run(tmp_path, hubs)

    assert engine.run() == 0
    branch = "evidence/fake-2026-10-03"
    files = git("ls-tree", "-r", "--name-only", branch, cwd=hubs["btrc_upstream"]).splitlines()
    assert files == [
        "fake-2026-10-03/cells/gate/summary.txt",
        "fake-2026-10-03/summary.json",
        "fake-2026-10-03/summary.txt",
    ]
    summary = json.loads(git("show", f"{branch}:fake-2026-10-03/summary.json", cwd=hubs["btrc_upstream"]))
    assert summary["acceptance"] is True and summary["result"] == "green"
    assert summary["cells"][0]["results"]["steps"][1] == {
        "step": "test",
        "exit": 0,
        "duration_s": 99,
        "counts": "12 passed",
    }
    assert summary["provenance"]["acceptance_host"] == "Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0"
    assert "next: read the branch" in summary_text(engine)
    assert str(Path.home()) not in json.dumps(summary) or str(Path.home()) == "/"
    first = git("rev-parse", branch, cwd=hubs["btrc_upstream"])

    # Rerunning a published green run does nothing: no second ingest, no second push.
    rerun = acceptance_run(tmp_path, hubs)
    assert rerun.run() == 0
    assert git("rev-parse", branch, cwd=hubs["btrc_upstream"]) == first

    # A run republished (say, red, then fixed by a rerun) builds on the branch, fast-forward.
    state_path = rerun.state.state_path  # type: ignore[union-attr]
    state = json.loads(state_path.read_text())
    del state["published"]
    state_path.write_text(json.dumps(state))
    again = acceptance_run(tmp_path, hubs)
    assert again.run() == 0
    second = git("rev-parse", branch, cwd=hubs["btrc_upstream"])
    assert second != first and git("rev-parse", f"{second}^", cwd=hubs["btrc_upstream"]) == first


def test_a_secret_in_the_evidence_stops_the_push(
    tmp_path: Path, hubs: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = acceptance_run(tmp_path, hubs)
    original = EvidencePublisher.stage

    def leaky(self: EvidencePublisher, summary: dict[str, object]) -> Path:
        stage = original(self, summary)
        (stage / "leak.txt").write_text("AKIA" + "B" * 16 + "\n")
        return stage

    monkeypatch.setattr(EvidencePublisher, "stage", leaky)

    assert engine.run() == 4
    summary = json.loads((engine.state.work / "summary.json").read_text())  # type: ignore[union-attr]
    assert summary["secret_scan"]["builtin"] == ["leak.txt:1: AWS access key"]
    assert summary["publication"]["pushed"] is False
    assert not git("ls-remote", "--heads", str(hubs["btrc_upstream"]), "evidence/*", cwd=tmp_path)


def test_publication_waits_for_the_owner_when_the_ssh_agent_is_locked(
    tmp_path: Path, hubs: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = acceptance_run(tmp_path, hubs, "--evidence-remote", "git@github.com:example/none.git", "--owner-wait", "0")
    monkeypatch.setattr(Host, "ssh_agent_ready", staticmethod(lambda: False))

    assert engine.run() == 4  # green, but the evidence is not published yet
    summary = json.loads((engine.state.work / "summary.json").read_text())  # type: ignore[union-attr]
    assert summary["publication"]["pushed"] is False
    assert "unlock 1Password" in summary["publication"]["message"]
    assert "unlock 1Password" in summary_text(engine)


def test_ingest_is_only_for_acceptance_reports(tmp_path: Path, hubs: dict[str, Path]) -> None:
    preset = counting_preset(tmp_path)
    engine = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))
    engine.run()
    summary = json.loads((engine.state.work / "summary.json").read_text())  # type: ignore[union-attr]

    assert {record["status"] for record in summary["ingest"]} == {"skipped"}
    assert len(summary["ingest"]) == 4


ATTRIBUTION_WRITER = (
    "import json, sys\n"
    "out, outcome = sys.argv[1], sys.argv[2]\n"
    "summary = {'attributed_fraction': 0.93, 'minimum_fraction': 0.91, 'target_fraction': 0.9,\n"
    "           'meets_target': True, 'scenario_fractions': {'cold': 0.91},\n"
    "           'owner_shares': {'cold': {'analyzer': 0.4}}}\n"
    "failure = None if outcome == 'green' else 'attributed 41.0% below --min-attributed 90%'\n"
    "report = {'configuration': {'dry_run': True, 'stand_in': True}, 'summary': summary, 'failure': failure}\n"
    "json.dump(report, open(out + '/attribution.json', 'w'))\n"
    "sys.exit(0 if failure is None else 1)\n"
)


def test_attribution_cells_record_the_summary_and_are_never_ingested(tmp_path: Path, hubs: dict[str, Path]) -> None:
    writer = tmp_path / "attribution_writer.py"
    writer.write_text(ATTRIBUTION_WRITER)
    preset = write_preset(
        tmp_path,
        f"""\
        [preset]
        title = "attribution"
        [[cell]]
        id = "attribution-{{outcome}}"
        matrix = {{ outcome = ["green", "red"] }}
        result = "attribution"
        command = ["python3", "{writer}", "{{out}}", "{{outcome}}"]
        [[cell]]
        id = "attribution-missing"
        result = "attribution"
        command = ["true"]
        """,
    )
    engine = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))
    engine.run()
    summary = json.loads((engine.state.work / "summary.json").read_text())  # type: ignore[union-attr]
    cells = {cell["id"]: cell for cell in summary["cells"]}

    green = cells["attribution-green"]
    assert green["status"] == "passed"
    assert green["results"]["minimum_fraction"] == 0.91 and green["results"]["meets_target"] is True
    assert green["results"]["owner_shares"] == {"cold": {"analyzer": 0.4}}
    assert green["results"]["stand_in"] is True and "report" not in green["results"]
    red = cells["attribution-red"]
    assert red["status"] == "failed" and "below --min-attributed" in red["message"]
    assert red["results"]["failure"] == red["message"]
    missing = cells["attribution-missing"]
    assert missing["status"] == "failed" and "no attribution.json" in missing["message"]
    assert summary["ingest"] == []


def test_regressions_compare_matching_cells_with_a_baseline_summary(tmp_path: Path, hubs: dict[str, Path]) -> None:
    preset = counting_preset(tmp_path)
    text = preset.read_text().replace('kind = "measurement"\n', 'kind = "measurement"\nbaseline = "{home}/base.json"\n')
    preset.write_text(text + '\n[[regression]]\nscenario = "noop"\ntolerance = 1.05\n')
    (tmp_path / "home").mkdir()
    baseline = {
        "cells": [
            {"id": "count-old-selfhost", "results": {"scenarios": {"noop": {"median": 1.95}}}},
            {"id": "count-new-selfhost", "results": {"scenarios": {"noop": {"median": 1.0}}}},
        ]
    }
    (tmp_path / "home" / "base.json").write_text(json.dumps(baseline))
    engine = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))
    engine.run()
    summary = json.loads((engine.state.work / "summary.json").read_text())  # type: ignore[union-attr]

    verdicts = {item["cell"]: item["ok"] for item in summary["regressions"]}
    assert verdicts == {"count-old-selfhost": True, "count-new-selfhost": False}
    assert "Regressions against the baseline" in summary_text(engine)


def test_list_shows_status_without_running(
    tmp_path: Path, hubs: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    preset = counting_preset(tmp_path)
    engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal")).run()
    capsys.readouterr()

    assert engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal", "--list")).run() == 0
    listed = capsys.readouterr().out
    assert "count-old-selfhost [lock bench] [quiet]: passed" in listed


def test_run_sh_is_an_executable_bash_script_entering_the_dev_shell() -> None:
    script = REPO / "tools" / "runbook" / "run.sh"

    assert os.access(script, os.X_OK)
    subprocess.run(["bash", "-n", str(script)], check=True, timeout=TOOL_TIMEOUT)
    text = script.read_text()
    assert "--profile" in text and "python3 -m tools.runbook" in text and "Google Drive" in text


def test_the_module_entry_point_prints_usage(tmp_path: Path) -> None:
    completed = subprocess.run(
        ["python3", "-m", "tools.runbook", "--help"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT,
    )

    assert completed.returncode == 0
    assert "stage5" in completed.stdout and "--rehearsal" in completed.stdout


def test_checkpoints_round_trip(tmp_path: Path) -> None:
    state = runbook.RunState(tmp_path / "work", tmp_path / "logs")
    outcome = CellOutcome("a", "A", "passed", exit=0, results={"x": 1}, variables={"pin": "p"})
    state.record(outcome)

    assert state.checkpoint("a") == outcome
    (state.cells_dir / "b.json").write_text("{broken")
    assert state.checkpoint("b") is None


def test_a_gui_flake_cleared_by_the_rerun_is_not_counted(tmp_path: Path, hubs: dict[str, Path]) -> None:
    """release-check reruns once when it names failures; only tests failing both times count."""

    flag = tmp_path / "first-attempt"
    preset = write_preset(
        tmp_path,
        f"""\
        [preset]
        title = "gui"
        [[cell]]
        id = "release-check"
        result = "failure-list"
        retries = 1
        command = ["sh", "-c", "echo 'FAILED tests/Real.py::t'; if [ ! -e {flag} ]; then touch {flag}; echo 'FAILED tests/Gui.py::flaky'; fi; exit 2"]
        """,
    )
    engine = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))
    engine.run()
    outcome = engine.state.checkpoint("release-check")  # type: ignore[union-attr]

    assert outcome is not None and outcome.status == "passed" and outcome.attempts == 2
    assert outcome.results["failures"] == ["tests/Real.py::t"]
    assert outcome.results["flaky"] == ["tests/Gui.py::flaky"]


def test_a_missing_optional_pin_skips_only_its_cells(tmp_path: Path, hubs: dict[str, Path]) -> None:
    """WORKSTREAMS.md §7 Q44: if aeeca0fd is gone, Stage 5 measures only the new pin."""

    preset = write_preset(
        tmp_path,
        """\
        [preset]
        title = "pins"
        [btrsmith]
        pins = { gone = "0123456789abcdef0123456789abcdef01234567", new = "stage4/pin-bump" }
        branch_pin = "new"
        optional = ["gone"]
        [[cell]]
        id = "measure-{pin}"
        matrix = { pin = ["gone", "new"] }
        cwd = "btrsmith"
        command = ["true"]
        """,
    )
    engine = engine_for(preset, options(tmp_path, hubs, preset, "--rehearsal"))

    assert engine.run() == 0
    gone = engine.state.checkpoint("measure-gone")  # type: ignore[union-attr]
    assert gone is not None and gone.status == "skipped" and "not in the hub" in gone.message
    assert engine.state.checkpoint("measure-new").status == "passed"  # type: ignore[union-attr]

    required = write_preset(tmp_path, preset.read_text().replace('optional = ["gone"]\n', ""), name="required")
    with pytest.raises(RunbookError, match="is not in"):
        engine_for(required, options(tmp_path, hubs, required, "--rehearsal")).run()


def test_stage5_marks_aeeca0fd_optional_and_splits_each_night_into_resumable_groups() -> None:
    preset = Preset.load("stage5")
    ids = {cell.id for cell in preset.cells(stand_in=False)}

    assert preset.optional_pins == ("aeeca0fd",)
    assert {f"product-{group}-post-stage4-selfhost" for group in ("cold", "edits", "steady")} <= ids
    groups = {preset.variables[f"scenarios_{group}"] for group in ("cold", "edits", "steady")}
    covered = {name for group in groups for name in group.split(",")}
    assert covered == {
        "cold",
        "release",
        "memory",
        "workers",
        "edit",
        "instance-edit",
        "interface-edit",
        "noop",
        "touch",
    }
    facts = {(budget.scenario, budget.fact) for budget in preset.budgets if budget.fact}
    assert ("release-module", "ratio_to_whole") in facts and ("interface-edit", "ratio_max") in facts


def test_stopping_the_engine_stops_the_running_cell_and_leaves_no_checkpoint(
    tmp_path: Path, hubs: dict[str, Path]
) -> None:
    """A SIGTERM (a closed terminal, a logout) stops the cell's whole process group; the rerun repeats it."""

    import signal
    import time

    preset = write_preset(
        tmp_path,
        """\
        [preset]
        title = "long"
        [[cell]]
        id = "long"
        command = ["sh", "-c", "echo $$ > {out}/pid; exec sleep 120"]
        """,
    )
    arguments = [
        str(preset), "--rehearsal", "--home", str(tmp_path / "home"), "--btrc-hub", str(hubs["btrc"]),
        "--min-free-gb", "0",
    ]  # fmt: skip
    engine = subprocess.Popen(
        ["python3", "-m", "tools.runbook", *arguments], cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    pid_file = (
        tmp_path / "home" / "bench.noindex" / f"fake-{datetime.date.today().isoformat()}" / "out" / "long" / "pid"
    )
    deadline = time.monotonic() + TOOL_TIMEOUT
    while not (pid_file.is_file() and pid_file.read_text().strip()) and time.monotonic() < deadline:
        assert engine.poll() is None
        time.sleep(0.1)
    cell = int(pid_file.read_text())
    engine.send_signal(signal.SIGTERM)

    assert engine.wait(timeout=TOOL_TIMEOUT) == 130
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            os.kill(cell, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the cell's sleep survived the engine")
    assert not (pid_file.parent.parent.parent / "cells" / "long.json").exists()


def test_a_rehearsal_freezes_the_checkout_head_symbolically(tmp_path: Path) -> None:
    """New commits in the checkout must not block resuming a rehearsal; the SHA is resolved once in prepare()."""

    run_options = RunOptions.parse(["stage5", "--rehearsal", "--home", str(tmp_path / "home")])
    engine = RunbookEngine(Preset.load("stage5"), run_options, host=Host("Linux"), today=lambda: TODAY)

    assert engine.requested_refs()["btrc"] == "HEAD"
    assert engine.btrc_hub() == REPO
