"""Validate E40 observations without turning missing native trials into passes."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import ceil


@dataclass(frozen=True)
class E40Evidence:
    """One native trial's count and timing contract, independent of its runner."""

    report: dict
    sanitized: bool

    SIZES = (4095, 4096, 4097, 8193)
    FINALS = ("release", "text", "close")
    CLASSES = ("input", "completion", "timer", "immediate", "delayed", "presentation")
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
            assert row["pending"] == 0, row
        assert seen == expected

    def _class(self, row):
        counts = {
            name: self._integer(row[name])
            for name in ("accepted", "rejected", "delivered", "cancelled", "stale", "pending")
        }
        assert counts["accepted"] == sum(counts[name] for name in ("delivered", "cancelled", "stale", "pending")), row
        assert counts["delivered"] > 0 and counts["pending"] == 0, row
        assert row["duplicates"] == row["ordered_reordered"] == 0, row
        latency = self._samples(row["latency_ns"])
        assert len(latency) == counts["delivered"], row
        gaps = self._samples(row["runnable_service_gaps_ns"])
        self._samples(row["handler_ns"])
        depths = self._samples(row["queue_depth"])
        byte_depths = self._samples(row["queue_bytes"])
        assert max(depths) <= self._integer(row["capacity"], minimum=1)
        assert max(byte_depths) <= self._integer(row["byte_limit"], minimum=1)
        if not self.sanitized:
            if row["name"] != "presentation":
                assert sorted(latency)[ceil(len(latency) * 0.95) - 1] <= 100_000_000, row["name"]
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
        presented = self._samples(self.report["presented_ns"])
        assert len(presented) >= 2 and all(a < b for a, b in pairwise(presented))
        assert self.report["presentation_source"] == "MTLDrawable.addPresentedHandler/presentedTime"
        assert self.report["native_enqueue_errors"] == 0

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
