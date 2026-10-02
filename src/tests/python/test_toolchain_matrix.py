"""The toolchain matrix's recorded host facts and the read-only probe that re-checks them."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.qualification.toolchain import (
    BEGIN,
    END,
    MATRIX,
    CommandResult,
    Expectation,
    HostProbe,
    ProbeStatus,
    ToolchainMatrix,
    ToolchainMatrixError,
    ToolchainProbeCommand,
)

# The facts PLAN.md Stage 22 asks the probe to re-check on the Mac.
REQUIRED_PROBES = {"xcode-build", "ios-sdk", "ios-simulator-runtime", "zig", "nix", "jdk", "android-sdk"}


def _table(*rows: str) -> str:
    header = "| Probe | Command | Expect | Recorded value |\n| --- | --- | --- | --- |\n"
    return f"intro\n{BEGIN}\n{header}" + "\n".join(rows) + f"\n{END}\ntrailer\n"


class _Runner:
    def __init__(self, results: dict[tuple[str, ...], CommandResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command: tuple[str, ...]) -> CommandResult:
        self.calls.append(command)
        return self.results.get(command, CommandResult(None, ""))


def test_the_tracked_matrix_records_every_required_host_fact() -> None:
    matrix = ToolchainMatrix.load(MATRIX)
    probes = {fact.probe for fact in matrix.facts}
    assert probes >= REQUIRED_PROBES
    xcode = next(fact for fact in matrix.facts if fact.probe == "xcode-build")
    # D21: Xcode is pinned by build number.
    assert xcode.text == "Build version 27A266a" and xcode.expectation is Expectation.PRESENT


def test_parse_reads_commands_expectations_and_backticked_values() -> None:
    matrix = ToolchainMatrix.parse(
        _table(
            "| `xcode` | `xcodebuild -version` | present | `Build version 27A266a` |",
            "| `jdk` | `java -version` | absent | `version` |",
        )
    )
    assert [(fact.probe, fact.command, fact.expectation, fact.text) for fact in matrix.facts] == [
        ("xcode", ("xcodebuild", "-version"), Expectation.PRESENT, "Build version 27A266a"),
        ("jdk", ("java", "-version"), Expectation.ABSENT, "version"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "no markers at all",
        _table(),
        _table("| `x` | `true` | maybe | `1` |"),
        _table("| `x` | `true` | present | `1` |", "| `x` | `true` | present | `2` |"),
        _table("| `x` | `` | present | `1` |"),
    ],
)
def test_parse_refuses_a_malformed_table(text: str) -> None:
    with pytest.raises(ToolchainMatrixError):
        ToolchainMatrix.parse(text)


def test_off_macos_every_probe_is_not_applicable_and_nothing_runs() -> None:
    matrix = ToolchainMatrix.load(MATRIX)
    runner = _Runner({})
    outcomes = HostProbe(system="Linux", runner=runner).check(matrix)
    assert {outcome.status for outcome in outcomes} == {ProbeStatus.NOT_APPLICABLE}
    assert len(outcomes) == len(matrix.facts)
    assert runner.calls == []


def test_on_macos_present_and_absent_facts_compare_against_output() -> None:
    matrix = ToolchainMatrix.parse(
        _table(
            "| `xcode` | `xcodebuild -version` | present | `Build version 27A266a` |",
            "| `xcode-name` | `xcodebuild -version` | present | `Xcode 27.0` |",
            "| `jdk` | `java -version` | absent | `version` |",
            "| `ios17` | `xcrun simctl list runtimes` | absent | `iOS 17.` |",
            "| `nix` | `nix --version` | present | `2.34.6` |",
        )
    )
    runner = _Runner(
        {
            ("xcodebuild", "-version"): CommandResult(0, "Xcode 27.1\nBuild version 27A9269\n"),
            # Installing a JDK makes `java -version` succeed, on stderr.
            ("java", "-version"): CommandResult(0, 'openjdk version "17.0.12"\n'),
            ("xcrun", "simctl", "list", "runtimes"): CommandResult(0, "== Runtimes ==\niOS 26.4 (26.4.1 - 23E)\n"),
        }
    )
    outcomes = {outcome.fact.probe: outcome for outcome in HostProbe(system="Darwin", runner=runner).check(matrix)}
    assert outcomes["xcode"].status is ProbeStatus.MISMATCH
    assert outcomes["xcode-name"].status is ProbeStatus.MISMATCH
    assert outcomes["jdk"].status is ProbeStatus.MISMATCH
    assert outcomes["ios17"].status is ProbeStatus.MATCH
    assert outcomes["nix"].status is ProbeStatus.MISMATCH
    assert outcomes["nix"].observed == "command not found"
    # One command backs several facts and runs once.
    assert runner.calls.count(("xcodebuild", "-version")) == 1


def test_an_absent_fact_holds_when_the_command_fails() -> None:
    matrix = ToolchainMatrix.parse(_table("| `jdk` | `java -version` | absent | `version` |"))
    # macOS's /usr/bin/java stub exits 1 without a runtime.
    runner = _Runner({("java", "-version"): CommandResult(1, "Unable to locate a Java Runtime that supports version.")})
    [outcome] = HostProbe(system="Darwin", runner=runner).check(matrix)
    assert outcome.status is ProbeStatus.MATCH


def test_the_command_exits_0_off_macos_and_1_on_a_mac_mismatch(tmp_path: Path, capsys) -> None:
    document = tmp_path / "matrix.md"
    document.write_text(_table("| `nix` | `nix --version` | present | `2.34.6` |"), encoding="utf-8")
    linux = ToolchainProbeCommand(HostProbe(system="Linux", runner=_Runner({})))
    assert linux.run(["--matrix", str(document)]) == 0
    assert "not-applicable nix" in capsys.readouterr().out

    stale = _Runner({("nix", "--version"): CommandResult(0, "nix (Nix) 2.35.0\n")})
    assert ToolchainProbeCommand(HostProbe(system="Darwin", runner=stale)).run(["--matrix", str(document)]) == 1
    output = capsys.readouterr().out
    assert "MISMATCH nix" in output and "0 of 1 recorded host facts match" in output

    current = _Runner({("nix", "--version"): CommandResult(0, "nix (Determinate Nix 3.8.0) 2.34.6\n")})
    assert ToolchainProbeCommand(HostProbe(system="Darwin", runner=current)).run(["--matrix", str(document)]) == 0


def test_the_command_reports_an_unreadable_matrix(tmp_path: Path) -> None:
    command = ToolchainProbeCommand(HostProbe(system="Linux", runner=_Runner({})))
    assert command.run(["--matrix", str(tmp_path / "missing.md")]) == 2
