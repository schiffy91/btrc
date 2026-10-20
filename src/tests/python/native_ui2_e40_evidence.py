"""Validate E40 observations without turning missing native trials into passes."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from itertools import pairwise


@dataclass(frozen=True)
class E40Evidence:
    """One native trial's count and timing contract, independent of its runner."""

    report: dict
    sanitized: bool

    SIZES = (4095, 4096, 4097, 8193)
    FINALS = ("release", "text", "close")
    CLASSES = ("input", "completion", "timer", "immediate", "delayed", "presentation_first", "presentation_second")
    TRACKING = ("popup", "slider", "resize", "sheet")

    @staticmethod
    def _integer(value, *, minimum=0):
        assert type(value) is int and value >= minimum, value
        return value

    @classmethod
    def _samples(cls, values, *, required=True):
        assert isinstance(values, list) and (values or not required), values
        for value in values:
            cls._integer(value)
        return values

    def header(self, trial):
        assert self.report["schema"] == "btrc.ui2.macos-e40/1"
        assert self.report["trial"] == trial
        assert self.report["entry"] in {"desktop", "host"}
        assert self.report["native_backend"] == "AppKit"
        assert self.report["clock"] == "mach_continuous_time nanoseconds"
        assert self.report["visible_windows"] >= 2
        assert self.report["application_active"] is True
        assert self.report["window_key"] is True
        assert self.report["native_failure"] is None
        assert self.report["trace_overflow"] == 0

    def bursts(self):
        self.header("bursts")
        rows = self.report["bursts"]
        expected = {(size, final, repeat) for size in self.SIZES for final in self.FINALS for repeat in range(100)}
        assert len(rows) == len(expected)
        seen = set()
        for row in rows:
            identity = (row["size"], row["final"], row["repeat"])
            assert identity in expected and identity not in seen, identity
            seen.add(identity)
            size, final, _ = identity
            assert row["native_submitted"] == row["native_observed"] == size, row
            assert row["native_enqueue_errors"] == 0, row
            assert row["native_duplicates"] == row["native_reordered"] == 0, row
            assert row["ordered_delivered"] == size - (final != "release"), row
            assert row["ordered_duplicates"] == row["ordered_reordered"] == 0, row
            assert row["terminal_delivered"] == 1, row
            assert row["pending"] == 0 and row["window_key"] is True, row
        assert seen == expected

    def _class(self, row):
        counts = {
            name: self._integer(row[name])
            for name in ("accepted", "rejected", "delivered", "cancelled", "stale", "pending")
        }
        assert counts["accepted"] == sum(counts[name] for name in ("delivered", "cancelled", "stale", "pending")), row
        assert counts["delivered"] > 0 and counts["pending"] == 0, row
        assert row["duplicates"] == row["ordered_reordered"] == 0, row
        histogram = self._samples(row["latency_histogram"])
        assert len(histogram) == 10002 and sum(histogram) == counts["delivered"]
        width = self._integer(row["latency_bin_ns"], minimum=1)
        maximum = self._integer(row["maximum_latency_ns"])
        threshold = (counts["delivered"] * 95 + 99) // 100
        cumulative = 0
        percentile = None
        for index, count in enumerate(histogram):
            cumulative += count
            if cumulative >= threshold:
                percentile = maximum if index == len(histogram) - 1 else (index + 1) * width
                break
        for name in ("accepted_by_second", "delivered_by_second"):
            buckets = self._samples(row[name])
            assert len(buckets) == 600
        runnable = row["runnable_by_second"]
        assert len(runnable) == 600 and all(value is True for value in runnable)
        gaps = self._samples(row["runnable_service_gaps_ns"])
        self._samples(row["handler_ns"])
        depths = self._samples(row["queue_depth"])
        byte_depths = self._samples(row["queue_bytes"])
        assert max(depths) <= self._integer(row["capacity"], minimum=1)
        assert max(byte_depths) <= self._integer(row["byte_limit"], minimum=1)
        if not self.sanitized:
            if not row["name"].startswith("presentation_"):
                assert percentile is not None and percentile <= 100_000_000, row["name"]
            assert max(gaps) <= 250_000_000, row["name"]

    def load(self):
        self.header("load")
        assert self._integer(self.report["elapsed_ns"]) >= 600_000_000_000
        classes = self.report["classes"]
        assert len(classes) == len(self.CLASSES)
        assert {row["name"] for row in classes} == set(self.CLASSES)
        for row in classes:
            self._class(row)
        closes = self._samples(self.report["close_start_ns"])
        if not self.sanitized:
            assert max(closes) <= 250_000_000
        assert self.report["presentation_source"] == "MTLDrawable.addPresentedHandler/presentedTime"
        assert self.report["native_enqueue_errors"] == 0
        started = self._integer(self.report["load_started_ns"], minimum=1)
        ended = self._integer(self.report["load_ended_ns"], minimum=started + 600_000_000_000)
        assert ended - started == self.report["elapsed_ns"]
        producer = self._samples(self.report["producer_by_second"])
        assert len(producer) == 600 and min(producer) > 0
        assert sum(producer) == self._integer(self.report["producer_iterations"], minimum=600)
        self._integer(self.report["producer_max_gap_ns"])
        self._integer(self.report["presentation_clock_uncertainty_ns"])
        assert (
            self.report["accounted_storage"]
            == "retained payload/reference credits; excludes native and driver allocations"
        )

    def presentations(self, path):
        counts = [0, 0]
        previous = [0, 0]
        active = [set(), set()]
        began = self.report["load_started_ns"]
        ended = self.report["load_ended_ns"]
        with path.open(newline="") as stream:
            rows = csv.DictReader(stream)
            assert rows.fieldnames == [
                "window",
                "presented_continuous_ns",
                "native_presented_seconds",
                "callback_continuous_ns",
            ]
            for row in rows:
                window = int(row["window"])
                assert window in (0, 1)
                stamp = int(row["presented_continuous_ns"])
                assert stamp > previous[window] and float(row["native_presented_seconds"]) > 0
                # The mapping is sampled once; retain its measured uncertainty.
                assert stamp <= int(row["callback_continuous_ns"]) + self.report["presentation_clock_uncertainty_ns"]
                previous[window] = stamp
                counts[window] += 1
                if began <= stamp < ended:
                    active[window].add((stamp - began) // 1_000_000_000)
        assert counts == self.report["presented_counts"] and min(counts) > 0
        by_name = {row["name"]: row for row in self.report["classes"]}
        for window, name in enumerate(("presentation_first", "presentation_second")):
            assert counts[window] == by_name[name]["delivered"]
            if not self.sanitized:
                assert active[window] == set(range(600))

    def tracking(self, trial):
        assert trial in self.TRACKING
        self.header(trial)
        interval = self.report["tracking"]
        entered = self._integer(interval["entered_ns"], minimum=1)
        exited = self._integer(interval["exited_ns"], minimum=entered + 1)
        assert interval["native_entry_observed"] is interval["native_exit_observed"] is True
        assert interval["run_modal_used"] is False
        classes = interval["service"]
        assert set(classes) == set(self.CLASSES)
        for name, samples in classes.items():
            self._samples(samples)
            assert any(entered < stamp < exited for stamp in samples), name
            in_interval = [entered, *(stamp for stamp in samples if entered < stamp < exited), exited]
            if not self.sanitized:
                assert max(b - a for a, b in pairwise(in_interval)) <= 250_000_000, name
        if trial == "resize":
            assert interval["in_live_resize_observed"] is True
        if trial == "slider":
            assert interval["pointer_down"] == interval["pointer_up"] == interval["commits"] == 1
            assert interval["previews"] > 0
        if trial == "sheet":
            assert interval["attached_sheet_observed"] is True
