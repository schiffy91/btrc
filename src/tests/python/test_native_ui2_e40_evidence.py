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
