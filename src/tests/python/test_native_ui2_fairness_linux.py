"""E40 native SDL bursts and declared load; headless timings are not physical latency."""

import csv
import json
import os
import platform
import subprocess
from pathlib import Path

import pytest

from src.tests.python.linux_provider_fixtures import build_observed_provider_program, provider_environment
from tools.qualification.skips import RunnerIdentity

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.linux_gui
CLASS_NAMES = (
    "input",
    "worker_completion",
    "due_timer",
    "self_posted_immediate",
    "self_posted_delayed",
    "presentation_first",
    "presentation_second",
    "close_start",
)


@pytest.fixture(scope="module", params=["python", "selfhost"])
def frontend(request):
    return request.param


@pytest.fixture(scope="module", params=[False, True], ids=["plain", "sanitized"])
def sanitized(request):
    return request.param


@pytest.fixture(scope="module")
def burst_program(tmp_path_factory, request, frontend, sanitized):
    return build_observed_provider_program(
        tmp_path_factory,
        request,
        frontend,
        sanitized,
        "src/tests/native/gui/linux/LinuxEventBoundary.btrc",
        "src/tests/native/gui/shell/probes/linux/EventBoundary",
        (
            "eventBoundaryArm",
            "eventBoundaryQueued",
            "eventBoundaryLatest",
            "eventBoundaryFrames",
            "eventBoundaryClose",
            "eventBoundaryDisarm",
            "eventBoundaryAccepted",
            "eventBoundaryRejected",
        ),
        ("SDL_PollEvent", "SDL_PushEvent", "wgpuSurfacePresent"),
    )


@pytest.fixture(scope="module")
def load_program(tmp_path_factory, request, frontend, sanitized):
    return build_observed_provider_program(
        tmp_path_factory,
        request,
        frontend,
        sanitized,
        "src/tests/native/gui/ui2/probes/linux/UI2LinuxFairness.btrc",
        "src/tests/native/gui/ui2/probes/linux/Fairness",
        (
            "e40Start",
            "e40LoadBegin",
            "e40ProducerTick",
            "e40Begin",
            "e40Reject",
            "e40Deliver",
            "e40Handler",
            "e40Pending",
            "e40Frames",
            "e40InputDelivery",
            "e40PushInput",
            "e40PushClose",
            "e40Frame",
            "e40Report",
        ),
        ("SDL_PollEvent", "SDL_WaitEventTimeout", "wgpuSurfacePresent"),
    )


def provenance(frontend, sanitized):
    return {
        "schema": "btrc.linux-e40/1",
        "revision": subprocess.check_output(
            ["git", "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_changes": subprocess.check_output(
            ["git", "-c", f"safe.directory={ROOT}", "status", "--porcelain"], cwd=ROOT, text=True
        ).splitlines(),
        "frontend": frontend,
        "sanitized": sanitized,
        "runner": RunnerIdentity.detect(),
        "backend": os.environ.get("SDL_VIDEODRIVER", "unspecified"),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "session": "headless native SDL; synthetic input; real delegated wgpuSurfacePresent",
        "physical_device_latency": "not measured",
        "clock": "SDL_GetTicksNS monotonic nanoseconds",
        "compiler": subprocess.check_output(["cc", "--version"], text=True).splitlines()[0],
        "selfhost_binary": os.environ.get("BTRC_TEST_BTRCC") if frontend == "selfhost" else None,
        "limits": {
            "input_count_per_turn": 4096,
            "input_slice_ns": 2_000_000,
            "scheduler_count_per_turn": 64,
            "scheduler_slice_ns": 2_000_000,
            "publisher_count_per_turn": 64,
            "publisher_slice_ns": 2_000_000,
            "semantic_count_per_turn": 64,
            "semantic_slice_ns": 2_000_000,
            "work_capacity": 128,
            "publisher_capacity": 64,
            "capture_credit_policy": 16384,
            "terminal_pool": 16384,
        },
    }


def run_observed(command, sanitized, timeout, directory):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1"),
        )
    except subprocess.TimeoutExpired as error:
        # Timeout output is bytes even for text=True. Preserve it alongside the
        # normal structured failure report instead of losing the unfinished run.
        stdout = error.stdout.decode(errors="replace") if isinstance(error.stdout, bytes) else error.stdout or ""
        stderr = error.stderr.decode(errors="replace") if isinstance(error.stderr, bytes) else error.stderr or ""
        result = subprocess.CompletedProcess(command, -124, stdout, stderr + f"\nTimed out after {timeout}s.\n")
    (directory / "stdout.txt").write_text(result.stdout)
    (directory / "stderr.txt").write_text(result.stderr)
    return result


@pytest.mark.parametrize("count", [4095, 4096, 4097, 8193])
@pytest.mark.parametrize("terminal", [0, 1, 2, 3], ids=["keys", "release", "text", "close"])
def test_linux_e40_repeated_bursts(burst_program, frontend, sanitized, count, terminal, tmp_path):
    result = run_observed(
        [str(burst_program), str(count), str(terminal), "100"],
        sanitized,
        600,
        tmp_path,
    )
    trials = []
    admissions = []
    for line in result.stdout.splitlines():
        if line.startswith("E40 count="):
            trials.append({key: int(value) for key, value in (field.split("=") for field in line.split()[1:])})
        elif line.startswith("E40_ADMISSION "):
            admissions.append({key: int(value) for key, value in (field.split("=") for field in line.split()[1:])})
    report = {
        **provenance(frontend, sanitized),
        "kind": "bursts",
        "repetitions": 100,
        "count": count,
        "terminal": terminal,
        "trials": trials,
        "admission": admissions,
        "returncode": result.returncode,
    }
    # Boundary uses its original work capacity; it does not create a publisher.
    report["limits"]["work_capacity"] = 16
    report["limits"]["publisher_capacity"] = 0
    (tmp_path / "e40-bursts.json").write_text(json.dumps(report, indent=2) + "\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(trials) == len(admissions) == 100
    for trial, admission in zip(trials, admissions, strict=True):
        assert trial["count"] == count and trial["terminal"] == terminal
        assert all(trial[key] == 1 for key in ("bounded", "work", "frame", "lossless")), trial
        assert trial["first_key_mismatch"] == 0
        assert admission == {"accepted": count, "rejected": 0}
        assert trial["releases"] == (1 if terminal == 1 else 0)
        if terminal == 2:
            assert trial["text"] == 1
        if terminal == 3:
            assert trial["close"] == 1
            assert trial["total_keys"] + trial["closed_keys"] == trial["expected_keys"]
        else:
            assert trial["closed_keys"] == 0


def exercise_load(program, frontend, sanitized, seconds, tmp_path):
    presentations = tmp_path / "presentations.csv"
    result = run_observed(
        [str(program), str(seconds), "1" if sanitized else "0", str(presentations)],
        sanitized,
        seconds + 90,
        tmp_path,
    )
    rows = [
        json.loads(line.removeprefix("E40_LOAD "))
        for line in result.stdout.splitlines()
        if line.startswith("E40_LOAD ")
    ]
    report = {
        **provenance(frontend, sanitized),
        "kind": "load",
        "requested_seconds": seconds,
        "qualifying": seconds == 600,
        "returncode": result.returncode,
        "native": rows,
        "workload": {
            "producer_period_ms": 5,
            "input_attempts_per_period": 4,
            "worker_completion_outstanding_limit": 1,
            "timer_delay_ms": 5,
            "self_posted_delayed_ms": 1,
            "shown_windows": 2,
            "activity_requirement": "worker source iterations and runnable receipts in every one-second load bucket",
            "handlers": "bounded, nonblocking; no overload or intentional blocking trial",
        },
        "timestamp_meaning": {
            "admission": "immediately before SDL_PushEvent, tryPublish or schedule; rollback on refusal",
            "presentation": "SDL monotonic observation after successful wgpuSurfacePresent; not scanout",
            "runnable": "accepted input/completion/immediate work, due timer deadlines, dirty presentation",
        },
        "depth_meaning": "receipt depth includes in-progress admission; bytes are payload storage, not total allocation",
        "presentation_file": presentations.name,
    }
    (tmp_path / "e40-load.json").write_text(json.dumps(report, indent=2) + "\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(rows) == 1
    native = rows[0]
    assert native["qualifying"] == (seconds == 600) and native["sanitized"] == sanitized
    assert native["duration_ns"] >= seconds * 1_000_000_000
    assert native["activity_bucket_ns"] == 1_000_000_000
    assert native["load_ends_ns"] - native["load_started_ns"] == seconds * 1_000_000_000
    producer_buckets = native["producer_by_second"]
    assert len(producer_buckets) == seconds and all(value > 0 for value in producer_buckets), producer_buckets
    assert sum(producer_buckets) == native["producer_iterations"]
    native["producer_iterations_per_second"] = native["producer_iterations"] / seconds
    assert 0 < native["producer_max_gap_ns"] <= native["duration_ns"]
    assert [row["kind"] for row in native["classes"]] == list(range(8))
    for row, name in zip(native["classes"], CLASS_NAMES, strict=True):
        row["name"] = name
        assert row["accepted"] == row["delivered"] > 0 and row["pending"] == 0, row
        assert 0 < row["peak_depth_including_admission"] <= 128 and row["peak_payload_bytes"] > 0, row
        accepted_buckets = row["accepted_by_second"]
        delivered_buckets = row["delivered_by_second"]
        runnable_buckets = row["runnable_by_second"]
        assert len(accepted_buckets) == len(delivered_buckets) == len(runnable_buckets) == seconds, row
        assert sum(accepted_buckets) <= row["accepted"] and sum(delivered_buckets) <= row["delivered"], row
        if row["kind"] < 7:
            # Admission and service counts are reported separately. A receipt
            # that remains runnable spans buckets even when sanitizers delay its
            # service; source continuity adds no sanitizer latency threshold.
            assert all(runnable_buckets), row
        else:
            # The close is deliberately requested after the declared interval,
            # while every producer remains live until its decision starts.
            assert sum(accepted_buckets) == sum(delivered_buckets) == 0, row
            assert not any(runnable_buckets), row
        row["accepted_per_second"] = row["accepted"] / (native["measurement_ns"] / 1_000_000_000)
        row["attempted_per_second"] = (row["accepted"] + row["rejected"]) / (native["measurement_ns"] / 1_000_000_000)
        row["coalesced"] = 0
        row["terminal_dispositions"] = {
            "delivered": row["delivered"],
            "cancelled": 0,
            "stale": 0,
            "superseded": 0,
            "closed": 0,
            "failed": 0,
        }
        if not sanitized:
            assert row["max_service_gap_ns"] <= 250_000_000, row
            if row["kind"] < 5:
                assert row["p95_upper_ns"] <= 100_000_000, row
    assert native["classes"][7]["delivered"] == 1
    if not sanitized:
        assert native["classes"][7]["max_runnable_wait_ns"] <= 250_000_000
    with presentations.open() as stream:
        samples = list(csv.DictReader(stream))
    assert {int(row["window"]) for row in samples} == {0, 1}
    stamps = [int(row["monotonic_ns"]) for row in samples]
    assert stamps == sorted(stamps)
    for window in range(2):
        assert sum(int(row["window"]) == window for row in samples) >= native["classes"][5 + window]["delivered"]
    report["presentation_count"] = len(samples)
    (tmp_path / "e40-load.json").write_text(json.dumps(report, indent=2) + "\n")


def test_linux_e40_sustained_load(load_program, frontend, sanitized, tmp_path):
    exercise_load(load_program, frontend, sanitized, 600, tmp_path)


def test_linux_e40_diagnostic(load_program, frontend, sanitized, tmp_path):
    """Short development check, explicitly excluded from E40 qualification."""
    exercise_load(load_program, frontend, sanitized, 10, tmp_path)
