"""Reject incomplete E40 evidence independently of the hosted native runner."""

from copy import deepcopy

import pytest

from src.tests.python.native_ui2_e40_evidence import E40Evidence


@pytest.fixture
def header():
    return {
        "schema": "btrc.ui2.macos-e40/1",
        "trial": "bursts",
        "entry": "desktop",
        "native_backend": "AppKit",
        "clock": "mach_continuous_time nanoseconds",
        "visible_windows": 2,
        "application_active": True,
        "window_key": True,
        "native_failure": None,
        "trace_overflow": 0,
    }


@pytest.fixture
def bursts(header):
    return header | {
        "bursts": [
            {
                "size": size,
                "final": final,
                "repeat": repeat,
                "native_submitted": size,
                "native_observed": size,
                "native_enqueue_errors": 0,
                "native_duplicates": 0,
                "native_reordered": 0,
                "ordered_delivered": size - (final != "release"),
                "ordered_duplicates": 0,
                "ordered_reordered": 0,
                "terminal_delivered": 1,
                "pending": 0,
                "window_key": True,
            }
            for size in E40Evidence.SIZES
            for final in E40Evidence.FINALS
            for repeat in range(100)
        ]
    }


def test_complete_burst_evidence(bursts):
    E40Evidence(bursts, False).bursts()


@pytest.mark.parametrize("defect", ["missing", "duplicate", "lost", "native_rejection", "extra_final", "not_key"])
def test_incomplete_burst_evidence_is_rejected(bursts, defect):
    if defect == "missing":
        bursts["bursts"].pop()
    elif defect == "duplicate":
        bursts["bursts"][-1] = deepcopy(bursts["bursts"][0])
    else:
        field, value = {
            "lost": ("native_observed", 4094),
            "native_rejection": ("native_enqueue_errors", 1),
            "extra_final": ("terminal_delivered", 2),
            "not_key": ("window_key", False),
        }[defect]
        bursts["bursts"][0][field] = value
    with pytest.raises(AssertionError):
        E40Evidence(bursts, True).bursts()


@pytest.fixture
def load(header):
    classes = []
    for name in E40Evidence.CLASSES:
        classes.append(
            {
                "name": name,
                "accepted": 600,
                "rejected": 0,
                "delivered": 600,
                "cancelled": 0,
                "stale": 0,
                "pending": 0,
                "duplicates": 0,
                "ordered_reordered": 0,
                "latency_histogram": [600] + [0] * 10001,
                "latency_bin_ns": 100000,
                "maximum_latency_ns": 50000,
                "runnable_service_gaps_ns": [50000],
                "handler_ns": [1000],
                "queue_depth": [1],
                "queue_bytes": [8],
                "capacity": 128,
                "byte_limit": 1024,
                "accepted_by_second": [1] * 600,
                "delivered_by_second": [1] * 600,
                "runnable_by_second": [True] * 600,
            }
        )
    return header | {
        "trial": "load",
        "classes": classes,
        "elapsed_ns": 600_000_000_000,
        "load_started_ns": 1,
        "load_ended_ns": 600_000_000_001,
        "close_start_ns": [1000],
        "presented_counts": [600, 600],
        "presentation_attempts": [
            {
                "attempts": 603,
                "acquired": 602,
                "presented": 600,
                "dropped": 2,
                "unavailable": 1,
                "pending": False,
                "inflight": False,
                "failed": False,
                "duplicates": 0,
                "stale": 0,
                "invalid": 0,
            }
            for _ in range(2)
        ],
        "presentation_source": "MTLDrawable.addPresentedHandler/presentedTime",
        "native_enqueue_errors": 0,
        "producer_by_second": [1] * 600,
        "producer_iterations": 600,
        "producer_max_gap_ns": 1_000_000_000,
        "presentation_clock_uncertainty_ns": 10,
        "accounted_storage": "retained payload/reference credits; excludes native and driver allocations",
    }


def test_complete_load_evidence(load):
    E40Evidence(load, False).load()


@pytest.mark.parametrize(
    "defect", ["short", "missing_class", "idle_bucket", "worker_gap", "histogram_loss", "pending", "not_key"]
)
def test_incomplete_load_evidence_is_rejected(load, defect):
    if defect == "short":
        load["elapsed_ns"] -= 1
    elif defect == "missing_class":
        load["classes"].pop()
    elif defect == "idle_bucket":
        load["classes"][0]["runnable_by_second"][300] = False
    elif defect == "worker_gap":
        load["producer_by_second"][300] = 0
    elif defect == "histogram_loss":
        load["classes"][0]["latency_histogram"][0] -= 1
    elif defect == "pending":
        load["classes"][0]["pending"] = 1
    else:
        load["window_key"] = False
    with pytest.raises(AssertionError):
        E40Evidence(load, True).load()


@pytest.mark.parametrize("budget", ["latency", "service", "close"])
def test_numeric_budgets_apply_only_to_plain(load, budget):
    if budget == "latency":
        load["classes"][0]["latency_histogram"] = [0] * 10002
        load["classes"][0]["latency_histogram"][-1] = 600
        load["classes"][0]["maximum_latency_ns"] = 2_000_000_000
    elif budget == "service":
        load["classes"][0]["runnable_service_gaps_ns"] = [250_000_001]
    else:
        load["close_start_ns"] = [250_000_001]
    with pytest.raises(AssertionError):
        E40Evidence(load, False).load()
    E40Evidence(load, True).load()


def test_presentation_is_not_a_short_semantic_command(load):
    presentation = load["classes"][-1]
    presentation["latency_histogram"] = [0] * 10002
    presentation["latency_histogram"][1500] = 600
    presentation["maximum_latency_ns"] = 150_000_000
    E40Evidence(load, False).load()


@pytest.fixture
def tracking(load):
    entered = 1_000_000_001
    exited = 3_200_000_001
    load.update(trial="popup", elapsed_ns=10_000_000_000, load_ended_ns=10_000_000_001)
    native = [
        {
            "identity": index + 1,
            "type": 10,
            "submitted_ns": entered + index * 100_000_000,
            "dequeued_ns": None,
            "post_returned_ns": entered + index * 100_000_000 + 10_000,
            "posted_event_identities": [100 + index * 2, 101 + index * 2],
            "previous_highlight": index - 1,
            "resulting_highlight": index,
            "effect_observed_ns": entered + index * 100_000_000 + 20_000,
            "semantic_delivered_ns": 0,
            "window_number": 10,
            "application_active": True,
            "window_key": True,
            "native_value": index,
            "disposition": "native-effect-observed",
        }
        for index in range(22)
    ]
    native[-1].update(
        submitted_ns=exited - 100_000,
        post_returned_ns=exited - 90_000,
        effect_observed_ns=exited,
        resulting_highlight=-1,
    )
    for row in load["classes"]:
        row.update(
            accepted_by_second=[1] * 10,
            delivered_by_second=[1] * 10,
            runnable_by_second=[True] * 10,
            delivery_kind="presentation" if row["name"].startswith("presentation_") else "semantic-callback",
        )
    load["classes"][0].update(
        accepted=22,
        delivered=22,
        latency_histogram=[22] + [0] * 10001,
        delivery_kind="native-effect",
        runnable_by_second=[False, True, True] + [False] * 7,
    )
    receipts = [
        {
            "delivered_ns": native[trigger - 1]["submitted_ns"] + 50_000,
            "phase": phase,
            "generation": 1,
            "interaction": 1,
            "sequence": sequence,
            "model_revision": 0,
            "trigger_identity": trigger,
            "candidate_index": candidate,
            "latency_ns": 50_000,
            "disposition": "semantic-delivered",
        }
        for sequence, (phase, trigger, candidate) in enumerate(((1, 2, 1), (1, 21, 20), (3, 22, 20)), 1)
    ]
    load["tracking"] = {
        "entered_ns": entered,
        "exited_ns": exited,
        "native_entry_observed": True,
        "native_exit_observed": True,
        "run_modal_used": False,
        "forced_cleanup": False,
        "unavailable": None,
        "service_run_loop_modes": ["NSEventTrackingRunLoopMode"],
        "input_route": "menu-arrow-highlight-return",
        "tracking_model": "native tracking loop",
        "highlight_changes": 21,
        "target_window_number": 10,
        "independent_window_number": 11,
        "native_input": native,
        "semantic_receipts": receipts,
        "service": {
            name: {
                "count": 20,
                "first_ns": entered + 10_000,
                "last_ns": exited - 10_000,
                "maximum_gap_ns": 100_000_000,
            }
            for name in E40Evidence.CLASSES
        },
    }
    return load


def test_tracking_has_separate_native_and_semantic_evidence(tracking):
    E40Evidence(tracking, False).tracking("popup")


@pytest.mark.parametrize(
    "defect",
    [
        "missing_entry",
        "missing_exit",
        "reversed_interval",
        "outside_load",
        "service_before_entry",
        "service_after_exit",
        "missing_input",
        "duplicate_identity",
        "lost_native_input",
        "native_reordered",
        "not_key",
        "missing_highlight",
        "missing_commit",
        "bad_trigger",
        "forced_cleanup",
    ],
)
def test_incomplete_tracking_evidence_is_rejected(tracking, defect):
    interval = tracking["tracking"]
    if defect == "missing_entry":
        interval["entered_ns"] = 0
    elif defect == "missing_exit":
        interval["exited_ns"] = 0
    elif defect == "reversed_interval":
        interval["exited_ns"] = interval["entered_ns"] - 1
    elif defect == "outside_load":
        interval["exited_ns"] = tracking["load_ended_ns"] + 1
    elif defect == "service_before_entry":
        interval["service"]["input"]["first_ns"] = interval["entered_ns"] - 1
    elif defect == "service_after_exit":
        interval["service"]["input"]["last_ns"] = interval["exited_ns"] + 1
    elif defect == "missing_input":
        interval["native_input"].pop()
    elif defect == "duplicate_identity":
        interval["native_input"][1]["identity"] = 1
    elif defect == "lost_native_input":
        interval["native_input"][1]["effect_observed_ns"] = 0
    elif defect == "native_reordered":
        interval["native_input"][1]["effect_observed_ns"] = interval["native_input"][0]["effect_observed_ns"] - 1
    elif defect == "not_key":
        interval["native_input"][1]["window_key"] = False
    elif defect == "missing_highlight":
        interval["highlight_changes"] -= 1
    elif defect == "missing_commit":
        interval["semantic_receipts"].pop()
    elif defect == "bad_trigger":
        interval["semantic_receipts"][-1]["trigger_identity"] = len(interval["native_input"]) + 1
    elif defect == "forced_cleanup":
        interval["forced_cleanup"] = True
    with pytest.raises(AssertionError):
        E40Evidence(tracking, True).tracking("popup")


def test_tracking_native_progress_is_not_a_short_semantic_command(tracking):
    row = tracking["classes"][0]
    row["latency_histogram"] = [0] * 10002
    row["latency_histogram"][1500] = row["delivered"]
    row["maximum_latency_ns"] = 150_000_000
    E40Evidence(tracking, False).tracking("popup")


def test_tracking_semantic_latency_budget_is_preserved(tracking):
    receipt = tracking["tracking"]["semantic_receipts"][-1]
    receipt["latency_ns"] = 200_000_000
    source = tracking["tracking"]["native_input"][-1]
    receipt["delivered_ns"] = source["submitted_ns"] + receipt["latency_ns"]
    with pytest.raises(AssertionError):
        E40Evidence(tracking, False).tracking("popup")
    E40Evidence(tracking, True).tracking("popup")


@pytest.mark.parametrize("trial", ["slider", "resize", "sheet"])
def test_tracking_uses_each_interactions_native_input(tracking, trial):
    tracking["trial"] = trial
    interval = tracking["tracking"]
    count = 40 if trial == "sheet" else 22
    template = interval["native_input"][0]
    native = []
    for index in range(count):
        row = deepcopy(template)
        stamp = interval["entered_ns"] + index * 40_000_000
        row.update(
            identity=index + 1,
            submitted_ns=stamp,
            dequeued_ns=stamp + 10_000,
            effect_observed_ns=stamp + 20_000,
            native_value=index,
            posted_event_identities=[100 + index],
            disposition="native-dequeued",
        )
        native.append(row)
    interval["native_input"] = native
    tracking["classes"][0].update(
        accepted=count, delivered=count, latency_histogram=[count] + [0] * 10001, delivery_kind="native-dequeue"
    )
    for row in interval["semantic_receipts"]:
        row.update(trigger_identity=count, delivered_ns=native[-1]["submitted_ns"] + row["latency_ns"])
    interval["input_route"] = {
        "slider": "slider-drag-release",
        "resize": "native-window-edge-drag",
        "sheet": "independent-public-view-pointer",
    }[trial]
    for index, row in enumerate(native):
        row["type"] = 1 if index == 0 else 2 if index == len(native) - 1 else 6
    if trial == "slider":
        interval["semantic_receipts"].pop(0)
        interval.update(
            pointer_down=1, pointer_up=1, previews=1, commits=1, tracking_model="provider-owned slider drag"
        )
        interval["semantic_receipts"][0]["phase"] = 2
    else:
        interval["semantic_receipts"] = []
    if trial == "resize":
        interval.update(in_live_resize_observed=True, resize_changes=18)
    if trial == "sheet":
        interval["attached_sheet_observed"] = True
        tracking["classes"][0]["delivery_kind"] = "semantic-callback"
        for index, row in enumerate(native):
            row.update(type=1 if index % 2 == 0 else 2, window_number=11, window_key=False)
            row["semantic_delivered_ns"] = row["dequeued_ns"] + 1
    E40Evidence(tracking, False).tracking(trial)


@pytest.mark.parametrize(
    "defect",
    [
        "change_on_return",
        "wrong_candidate",
        "wrong_commit_key",
        "before_highlight",
        "commit_on_arrow",
        "reused_arrow",
        "missing_change",
    ],
)
def test_popup_receipts_require_their_own_native_effect(tracking, defect):
    receipts = tracking["tracking"]["semantic_receipts"]
    native = tracking["tracking"]["native_input"]
    if defect == "change_on_return":
        receipts[0]["trigger_identity"] = len(native)
    elif defect == "wrong_candidate":
        receipts[0]["candidate_index"] = 20
    elif defect == "wrong_commit_key":
        receipts[-1]["candidate_index"] = 19
    elif defect == "before_highlight":
        source = native[receipts[0]["trigger_identity"] - 1]
        receipts[0]["delivered_ns"] = source["effect_observed_ns"] - 1
        receipts[0]["latency_ns"] = receipts[0]["delivered_ns"] - source["submitted_ns"]
    elif defect == "commit_on_arrow":
        receipts[-1]["trigger_identity"] = len(native) - 1
    elif defect == "reused_arrow":
        receipts[1].update(
            trigger_identity=receipts[0]["trigger_identity"], candidate_index=receipts[0]["candidate_index"]
        )
    else:
        receipts[:] = receipts[-1:]
    with pytest.raises(AssertionError):
        E40Evidence(tracking, True).tracking("popup")


def test_popup_commit_can_precede_native_menu_exit(tracking):
    receipt = tracking["tracking"]["semantic_receipts"][-1]
    assert receipt["delivered_ns"] < tracking["tracking"]["exited_ns"]
    E40Evidence(tracking, False).tracking("popup")


@pytest.mark.parametrize("samples", [[], [-1], [True]])
@pytest.mark.parametrize("sanitized", [False, True])
def test_tracking_requires_valid_close_observation(tracking, samples, sanitized):
    tracking["close_start_ns"] = samples
    with pytest.raises(AssertionError):
        E40Evidence(tracking, sanitized).tracking("popup")


def test_tracking_close_budget_exempts_only_sanitized_latency(tracking):
    tracking["close_start_ns"] = [250_000_001]
    with pytest.raises(AssertionError):
        E40Evidence(tracking, False).tracking("popup")
    E40Evidence(tracking, True).tracking("popup")


@pytest.mark.parametrize(
    "defect",
    [
        "pending",
        "inflight",
        "failed",
        "duplicates",
        "stale",
        "invalid",
        "missing_attempt",
        "false_presentation",
        "missing_acquisition",
    ],
)
def test_presentation_attempt_evidence_rejects_lost_or_false_completion(load, defect):
    row = load["presentation_attempts"][0]
    if defect in {"pending", "inflight", "failed"}:
        row[defect] = True
    elif defect in {"duplicates", "stale", "invalid"}:
        row[defect] = 1
    elif defect == "missing_attempt":
        row["attempts"] -= 1
    elif defect == "false_presentation":
        row["presented"] += 1
        row["dropped"] -= 1
    else:
        row["acquired"] -= 1
    with pytest.raises(AssertionError):
        E40Evidence(load, True).load()


@pytest.mark.parametrize("exit_code", [0, 7])
def test_loop_diagnostic_preserves_process_outcome_and_bounds_samples(tmp_path, monkeypatch, exit_code):
    import json
    import os
    import sys

    from src.tests.python.test_native_ui2_macos_e40 import E40LoopDiagnostic

    diagnostic = E40LoopDiagnostic(tmp_path)
    monkeypatch.setattr(diagnostic, "SAMPLE_TIMES", (0.01, 0.03))
    observed = []
    released = tmp_path / "sampled-twice"

    def sample(process, scheduled):
        assert process.poll() is None
        observed.append(process.pid)
        if len(observed) == 2:
            released.touch()
        return {"scheduled_seconds": scheduled, "pid": process.pid, "status": "test-observation"}

    monkeypatch.setattr(diagnostic, "_sample", sample)
    command = [
        sys.executable,
        "-c",
        f"import time\nfrom pathlib import Path\nprint('native output', flush=True)\n"
        f"while not Path({str(released)!r}).exists(): time.sleep(0.005)\nraise SystemExit({exit_code})",
    ]
    result = diagnostic.run(command, env=os.environ.copy(), timeout=5)
    assert result.returncode == exit_code and result.stdout == "native output\n" and result.stderr == ""
    receipt = json.loads((tmp_path / "loop-diagnostic.json").read_text())
    assert observed == [receipt["pid"], receipt["pid"]]
    assert receipt["native_returncode"] == exit_code and receipt["native_timeout_seconds"] == 5
    assert receipt["observer_error"] is None and len(receipt["samples"]) == 2


def test_loop_diagnostic_timeout_reaps_child_and_retains_observer_failure(tmp_path, monkeypatch):
    import json
    import os
    import subprocess
    import sys

    from src.tests.python import test_native_ui2_macos_e40 as driver

    processes = []
    original = subprocess.Popen

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(driver.subprocess, "Popen", spawn)
    diagnostic = driver.E40LoopDiagnostic(tmp_path)
    monkeypatch.setattr(diagnostic, "SAMPLE_TIMES", (0.0,))

    def failed_sample(process, scheduled):
        raise RuntimeError("sample observer failed")

    monkeypatch.setattr(diagnostic, "_sample", failed_sample)
    with pytest.raises(subprocess.TimeoutExpired):
        diagnostic.run([sys.executable, "-c", "import time; time.sleep(30)"], env=os.environ.copy(), timeout=0.1)
    assert len(processes) == 1 and processes[0].poll() is not None
    receipt = json.loads((tmp_path / "loop-diagnostic.json").read_text())
    assert "sample observer failed" in receipt["observer_error"]
    assert receipt["native_timeout_seconds"] == 0.1 and receipt["samples"] == []


def test_loop_diagnostic_records_sample_tool_failure_without_inventing_stack(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from src.tests.python import test_native_ui2_macos_e40 as driver

    def unavailable(*args, **kwargs):
        assert args[0] == ["/usr/bin/sample", "123", "1", "1", "-file", str(tmp_path / "sample-3s.txt")]
        assert kwargs["timeout"] == 4
        raise OSError("sample unavailable")

    monkeypatch.setattr(driver.subprocess, "run", unavailable)
    row = driver.E40LoopDiagnostic(tmp_path)._sample(SimpleNamespace(pid=123), 3.0)
    assert row["status"] == "failed" and "sample unavailable" in row["error"]
    assert not (tmp_path / "sample-3s.txt").exists()


def test_loop_diagnostic_thread_start_failure_reaps_child_and_preserves_error(tmp_path, monkeypatch):
    import json
    import os
    import subprocess
    import sys

    from src.tests.python import test_native_ui2_macos_e40 as driver

    processes = []
    original = subprocess.Popen
    failure = RuntimeError("thread start failed")

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    def fail_start(self):
        assert processes and processes[0].poll() is None
        raise failure

    monkeypatch.setattr(driver.subprocess, "Popen", spawn)
    monkeypatch.setattr(driver.threading.Thread, "start", fail_start)
    diagnostic = driver.E40LoopDiagnostic(tmp_path)
    with pytest.raises(RuntimeError) as caught:
        diagnostic.run([sys.executable, "-c", "import time; time.sleep(30)"], env=os.environ.copy(), timeout=0.1)
    assert caught.value is failure
    assert len(processes) == 1 and processes[0].poll() is not None
    receipt = json.loads((tmp_path / "loop-diagnostic.json").read_text())
    assert receipt["native_returncode"] == processes[0].returncode
    assert receipt["samples"] == []


@pytest.mark.parametrize("exit_code", [0, 7])
def test_shutdown_diagnostic_waits_for_current_report_before_sampling(tmp_path, monkeypatch, exit_code):
    import json
    import os
    import sys

    from src.tests.python.test_native_ui2_macos_e40 import E40LoopDiagnostic

    report = tmp_path / "observations.json"
    report.write_text("stale report")
    released = tmp_path / "sampled"
    diagnostic = E40LoopDiagnostic(tmp_path, after_report=report)
    monkeypatch.setattr(diagnostic, "SAMPLE_TIMES", (0.0, 0.01))
    observed = []

    def sample(process, scheduled):
        assert report.read_text() == "current report" and process.poll() is None
        observed.append(process.pid)
        if len(observed) == 2:
            released.touch()
        return {"scheduled_seconds": scheduled, "status": "test-observation"}

    monkeypatch.setattr(diagnostic, "_sample", sample)
    command = [
        sys.executable,
        "-c",
        "import time\nfrom pathlib import Path\n"
        f"report = Path({str(report)!r})\nassert not report.exists()\ntime.sleep(0.1)\n"
        "report.write_text('current report')\nprint('burst report complete', flush=True)\n"
        f"while not Path({str(released)!r}).exists(): time.sleep(0.005)\nraise SystemExit({exit_code})",
    ]
    result = diagnostic.run(command, env=os.environ.copy(), timeout=5)
    assert result.returncode == exit_code and result.stdout == "burst report complete\n"
    receipt = json.loads((tmp_path / "loop-diagnostic.json").read_text())
    assert observed == [receipt["pid"], receipt["pid"]]
    assert receipt["sample_origin"] == "report publication" and receipt["report_observed_seconds"] is not None
    assert receipt["native_timeout_seconds"] == 5 and receipt["native_returncode"] == exit_code
    assert receipt["trace"] is None and receipt["observer_error"] is None


@pytest.mark.parametrize("publish", [False, True])
def test_shutdown_diagnostic_preserves_timeout_with_or_without_report(tmp_path, monkeypatch, publish):
    import json
    import os
    import subprocess
    import sys

    from src.tests.python.test_native_ui2_macos_e40 import E40LoopDiagnostic

    report = tmp_path / "observations.json"
    report.write_text("stale report")
    diagnostic = E40LoopDiagnostic(tmp_path, after_report=report)
    monkeypatch.setattr(diagnostic, "SAMPLE_TIMES", (0.0,))
    monkeypatch.setattr(diagnostic, "_sample", lambda *args: {"status": "test-observation"})
    command = [
        sys.executable,
        "-c",
        "import time\nfrom pathlib import Path\n"
        + (f"Path({str(report)!r}).write_text('current report')\n" if publish else "")
        + "print('native output', flush=True)\ntime.sleep(30)",
    ]
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        diagnostic.run(command, env=os.environ.copy(), timeout=1)
    assert caught.value.timeout == 1 and caught.value.stdout == b"native output\n"
    receipt = json.loads((tmp_path / "loop-diagnostic.json").read_text())
    assert receipt["native_returncode"] is not None
    assert len(receipt["samples"]) == int(publish)
    assert (receipt["report_observed_seconds"] is not None) == publish
    assert receipt["observer_error"] is None


@pytest.mark.parametrize("control_name", ["metal", "resize"])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_native_control_retains_native_outcome_and_runs_once(tmp_path, exit_code, control_name):
    import hashlib
    import json
    import os
    import sys

    from src.tests.python.test_native_ui2_macos_e40 import E40NativeControl

    executable = tmp_path / "control"
    executable.write_text(
        "import sys\nfrom pathlib import Path\n"
        "print('native output')\nprint('native diagnostic', file=sys.stderr)\n"
        "Path(sys.argv[1]).write_text('{\"presented\": 0}')\n"
        f"raise SystemExit({exit_code})\n"
    )
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    control = E40NativeControl(control_name, [sys.executable, str(executable)], [], digest)
    control.record(tmp_path, os.environ.copy())
    directory = tmp_path / f"{control_name}-control"
    receipt = json.loads((directory / "execution.json").read_text())
    assert receipt["schema"] == f"btrc.ui2.{control_name}-control-execution/1"
    assert receipt["source_sha256"] == digest
    assert receipt["status"] == "completed" and receipt["returncode"] == exit_code
    assert receipt["report_written"] is True
    assert json.loads((directory / "observations.json").read_text()) == {"presented": 0}
    assert (directory / "stdout.txt").read_text() == "native output\n"
    assert (directory / "stderr.txt").read_text() == "native diagnostic\n"
    executable.unlink()
    control.record(tmp_path, os.environ.copy())
    assert json.loads((directory / "execution.json").read_text()) == receipt


@pytest.mark.parametrize("control_name", ["metal", "resize"])
def test_native_control_timeout_reaps_child_and_discards_stale_report(tmp_path, monkeypatch, control_name):
    import hashlib
    import json
    import os
    import subprocess
    import sys

    from src.tests.python import test_native_ui2_macos_e40 as driver

    executable = tmp_path / "control"
    executable.write_text("import time\nprint('started', flush=True)\ntime.sleep(30)\n")
    control = driver.E40NativeControl(
        control_name, [sys.executable, str(executable)], [], hashlib.sha256(executable.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(control, "TIMEOUT_SECONDS", 0.5)
    directory = tmp_path / f"{control_name}-control"
    directory.mkdir()
    (directory / "observations.json").write_text('{"presented": 20}')
    children = []
    original = subprocess.Popen

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(driver.subprocess, "Popen", spawn)
    control.record(tmp_path, os.environ.copy())
    receipt = json.loads((directory / "execution.json").read_text())
    assert receipt["status"] == "failed" and receipt["report_written"] is False
    assert not (directory / "observations.json").exists()
    assert len(children) == 1 and children[0].poll() is not None
    assert (directory / "stdout.txt").read_text() in {"", "started\n"}


def test_native_metal_controls_share_binary_and_keep_distinct_receipts(tmp_path, tmp_path_factory, monkeypatch):
    import hashlib
    import json
    import os
    import sys

    from src.tests.python import test_native_ui2_macos_e40 as driver

    built = []

    def build_control(cls, directory, name, source, frameworks):
        built.append((name, source, frameworks))
        script = directory / "control.py"
        script.write_text(
            "import json, sys\nfrom pathlib import Path\n"
            "assert len(sys.argv) == 2 or sys.argv[1] == '--vsync'\n"
            "Path(sys.argv[-1]).write_text(json.dumps({'display_sync_enabled': '--vsync' in sys.argv, 'presented': 0}))\n"
        )
        return cls(
            name, [sys.executable, str(script)], ["build", source], hashlib.sha256(script.read_bytes()).hexdigest()
        )

    monkeypatch.setattr(driver.E40NativeControl, "build", classmethod(build_control))
    factory = driver.build_native_controls.__wrapped__(tmp_path_factory)
    controls = factory()
    assert factory() is controls and [row[0] for row in built] == ["metal", "resize"]
    metal, synchronized, resize = controls
    assert synchronized.command == [*metal.command, "--vsync"]
    assert synchronized.executable == metal.executable
    assert synchronized.source_sha256 == metal.source_sha256
    assert synchronized.build_command == metal.build_command
    assert synchronized.TIMEOUT_SECONDS == metal.TIMEOUT_SECONDS == 15
    for control in controls:
        control.record(tmp_path, os.environ.copy())
    for control, expected in ((metal, False), (synchronized, True), (resize, False)):
        directory = tmp_path / f"{control.name}-control"
        receipt = json.loads((directory / "execution.json").read_text())
        assert receipt["status"] == "completed" and receipt["returncode"] == 0
        assert receipt["command"] == [*control.command, str(directory.resolve() / "observations.json")]
        assert json.loads((directory / "observations.json").read_text()) == {
            "display_sync_enabled": expected,
            "presented": 0,
        }
