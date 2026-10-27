"""A release-policy measurement must retain failures and use its checked binaries."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from src.tests.corpus_files import language_test_files
from tools.bench import collection_release as diagnostic
from tools.bench.collection_release import CollectionReleaseDiagnostic
from tools.bench.suite import Program


def owner(tmp_path: Path) -> CollectionReleaseDiagnostic:
    result = CollectionReleaseDiagnostic(tmp_path, tmp_path / "evidence")
    result.output.mkdir()
    return result


def test_argument_driven_fixture_is_not_an_ordinary_benchmark() -> None:
    assert (diagnostic.REPO / diagnostic.FIXTURE).is_file()
    assert str(diagnostic.FIXTURE.relative_to("src/tests")) not in language_test_files(diagnostic.REPO / "src/tests")
    assert all(
        program.path.resolve() != (diagnostic.REPO / diagnostic.FIXTURE).resolve() for program in Program.discover(None)
    )


def test_local_measurement_is_refused_before_any_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(diagnostic.sys, "platform", "darwin")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    result = CollectionReleaseDiagnostic(tmp_path, tmp_path / "evidence")
    with pytest.raises(ValueError, match="dedicated hosted"):
        result.run()
    assert not result.output.exists()


def test_correctness_mode_does_not_admit_measurement(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(diagnostic.sys, "platform", "darwin")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    result = owner(tmp_path)
    result.check_only = True
    result.receipt["controls_passed"] = True
    with pytest.raises(ValueError, match="dedicated hosted"):
        result.measure()
    assert not result.receipt["samples"]


def test_timeout_keeps_partial_output_and_failed_command(tmp_path: Path, monkeypatch) -> None:
    result = owner(tmp_path)

    def timeout(argv, **kwargs):
        kwargs["stdout"].write(b"started\n")
        kwargs["stderr"].write(b"partial failure\n")
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(diagnostic.subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        result.command("broken", ["fixture"], env={}, timeout=1)
    receipt = json.loads((result.output / "receipt.json").read_text())
    command = receipt["commands"][0]
    assert command["returncode"] is None and command["error"]
    assert (result.output / "broken.stdout").read_text() == "started\n"
    assert (result.output / "broken.stderr").read_text() == "partial failure\n"
    assert command["stderr_sha256"] == result.digest(result.output / "broken.stderr")
    assert not receipt["measurement_qualified"]


def test_replaced_native_binary_is_rejected_before_running(tmp_path: Path, monkeypatch) -> None:
    result = owner(tmp_path)
    binary = tmp_path / "native"
    binary.write_bytes(b"checked")
    result.receipt["binaries"]["whole-reference-strict"] = {"path": str(binary), "sha256": result.digest(binary)}
    binary.write_bytes(b"replacement")
    monkeypatch.setattr(result, "command", lambda *args, **kwargs: pytest.fail("changed binary executed"))
    with pytest.raises(ValueError, match="executable changed"):
        result.sample("whole", "reference", 0, 64, 0, 0)
    assert not result.receipt["samples"]


@pytest.mark.parametrize("missing_counter", [False, True])
def test_measurement_retains_all_samples_and_refuses_missing_counters(
    tmp_path: Path, monkeypatch, missing_counter: bool
) -> None:
    result = owner(tmp_path)
    result.receipt["controls_passed"] = True
    binary = tmp_path / "native"
    binary.write_bytes(b"checked")
    for form in diagnostic.FORMS:
        for frontend in diagnostic.FRONTENDS:
            result.receipt["binaries"][f"{form}-{frontend}-strict"] = {
                "path": str(binary),
                "sha256": result.digest(binary),
            }
    monkeypatch.setattr(result, "require_host", lambda **kwargs: None)
    monkeypatch.setattr(diagnostic.TimeReport, "collector", lambda: "fixture time")
    monkeypatch.setattr(diagnostic.TimeReport, "instruction_counter", lambda: "fixture instructions")
    monkeypatch.setattr(diagnostic.TimeReport, "command", lambda: ["time"])
    observed = []

    def run(label, argv, **kwargs):
        observed.append(label)
        operation, size, rounds, _ = map(int, argv[-4:])
        # One missing hardware count must invalidate the whole comparison.
        counters = "100 instructions retired\n" if not missing_counter or len(observed) != 12 else ""
        return subprocess.CompletedProcess(
            argv,
            0,
            result.expected_stdout(operation, size, rounds),
            "0.1 real 0.1 user 0.0 sys\n200 peak memory footprint\n" + counters,
        )

    monkeypatch.setattr(result, "command", run)
    if missing_counter:
        with pytest.raises(ValueError, match="counters are missing"):
            result.measure()
    else:
        result.measure()
    receipt = json.loads((result.output / "receipt.json").read_text())
    assert len(receipt["samples"]) == 480
    assert all(row["correct"] for row in receipt["samples"])
    assert receipt["measurement_qualified"] is not missing_counter
    assert sum(not row["counters_present"] for row in receipt["samples"]) == int(missing_counter)
    assert any(summary["instructions_retired"] is None for summary in receipt["summaries"].values()) is missing_counter


def test_incorrect_measured_result_stops_and_retains_failure(tmp_path: Path, monkeypatch) -> None:
    result = owner(tmp_path)
    binary = tmp_path / "native"
    binary.write_bytes(b"checked")
    result.receipt["binaries"]["whole-reference-strict"] = {"path": str(binary), "sha256": result.digest(binary)}
    monkeypatch.setattr(diagnostic.TimeReport, "command", lambda: ["time"])
    monkeypatch.setattr(
        result,
        "command",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, "wrong\n", "100 instructions retired\n200 peak memory footprint\n"
        ),
    )
    with pytest.raises(ValueError, match="correctness contract"):
        result.sample("whole", "reference", 0, 64, 0, 0)
    receipt = json.loads((result.output / "receipt.json").read_text())
    assert receipt["samples"][0]["correct"] is False
    assert receipt["samples"][0]["counters_present"] is True
    assert not receipt["measurement_qualified"]
