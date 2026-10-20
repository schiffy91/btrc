"""Validate E40 observations without turning missing native trials into passes."""

from __future__ import annotations

import csv
from dataclasses import dataclass


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

    def _class(self, row, seconds=600, *, continuous=True):
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
            assert len(buckets) == seconds
        runnable = row["runnable_by_second"]
        assert len(runnable) == seconds and all(type(value) is bool for value in runnable)
        assert all(runnable) if continuous else any(runnable)
        gaps = self._samples(row["runnable_service_gaps_ns"])
        self._samples(row["handler_ns"])
        depths = self._samples(row["queue_depth"])
        byte_depths = self._samples(row["queue_bytes"])
        assert max(depths) <= self._integer(row["capacity"], minimum=1)
        assert max(byte_depths) <= self._integer(row["byte_limit"], minimum=1)
        if not self.sanitized:
            if not row["name"].startswith("presentation_") and row.get("delivery_kind") not in {
                "native-dequeue",
                "native-effect",
            }:
                assert percentile is not None and percentile <= 100_000_000, row["name"]
            assert max(gaps) <= 250_000_000, row["name"]

    def presentation_attempts(self):
        attempts = self.report["presentation_attempts"]
        assert len(attempts) == 2
        by_name = {row["name"]: row for row in self.report["classes"]}
        for window, row in enumerate(attempts):
            values = {
                name: self._integer(row[name])
                for name in (
                    "attempts",
                    "acquired",
                    "presented",
                    "dropped",
                    "unavailable",
                    "duplicates",
                    "stale",
                    "invalid",
                )
            }
            assert row["pending"] is row["inflight"] is row["failed"] is False
            assert values["duplicates"] == values["stale"] == values["invalid"] == 0
            assert values["attempts"] == values["presented"] + values["dropped"] + values["unavailable"]
            assert values["presented"] + values["dropped"] <= values["acquired"] <= values["attempts"]
            assert values["presented"] == self.report["presented_counts"][window]
            name = "presentation_first" if window == 0 else "presentation_second"
            assert name in by_name
            assert values["presented"] == by_name[name]["delivered"] > 0

    def load(self):
        self.header("load")
        self.presentation_attempts()
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
                assert active[window] == set(range((ended - began) // 1_000_000_000))

    def tracking(self, trial):
        assert trial in self.TRACKING
        self.header(trial)
        self.presentation_attempts()
        interval = self.report["tracking"]
        entered = self._integer(interval["entered_ns"], minimum=1)
        exited = self._integer(interval["exited_ns"], minimum=entered + 1)
        assert interval["native_entry_observed"] is interval["native_exit_observed"] is True
        assert interval["run_modal_used"] is False
        assert interval["forced_cleanup"] is False
        assert self.report["load_started_ns"] <= entered < exited <= self.report["load_ended_ns"]
        assert interval["unavailable"] is None
        assert self.report["elapsed_ns"] == 10_000_000_000
        assert self.report["load_ended_ns"] - self.report["load_started_ns"] == self.report["elapsed_ns"]
        assert self.report["native_enqueue_errors"] == 0
        closes = self._samples(self.report["close_start_ns"])
        if not self.sanitized:
            assert max(closes) <= 250_000_000
        assert interval["service_run_loop_modes"]
        observed = self.report["classes"]
        assert len(observed) == len(self.CLASSES) and {row["name"] for row in observed} == set(self.CLASSES)
        for row in observed:
            self._class(row, seconds=10, continuous=row["name"] != "input")
        classes = interval["service"]
        assert set(classes) == set(self.CLASSES)
        for name, row in classes.items():
            self._integer(row["count"], minimum=1)
            first = self._integer(row["first_ns"], minimum=entered)
            last = self._integer(row["last_ns"], minimum=first)
            assert first <= last <= exited, name
            gap = self._integer(row["maximum_gap_ns"])
            if not self.sanitized:
                assert gap <= 250_000_000, name
        native = interval["native_input"]
        assert len(native) >= 2
        previous = 0
        event_identities = set()
        target = self._integer(interval["target_window_number"], minimum=1)
        independent = self._integer(interval["independent_window_number"], minimum=1)
        assert target != independent
        for identity, row in enumerate(native, 1):
            assert row["identity"] == identity
            submitted = self._integer(row["submitted_ns"], minimum=self.report["load_started_ns"])
            ids = row["posted_event_identities"]
            assert len(ids) == (2 if trial == "popup" else 1)
            for event_id in ids:
                self._integer(event_id, minimum=1)
                assert event_id not in event_identities
                event_identities.add(event_id)
            if trial == "popup":
                assert row["dequeued_ns"] is None
                assert row["disposition"] == "native-effect-observed"
                posted = self._integer(row["post_returned_ns"], minimum=submitted)
                observed_at = self._integer(row["effect_observed_ns"], minimum=max(posted, previous))
                assert row["window_key"] is True and row["type"] == 10
            else:
                assert row["disposition"] == "native-dequeued"
                observed_at = self._integer(row["dequeued_ns"], minimum=max(submitted, previous))
                assert row["window_number"] == (independent if trial == "sheet" else target)
            assert observed_at <= exited and row["application_active"] is True
            previous = observed_at
            if trial == "sheet":
                assert observed_at <= row["semantic_delivered_ns"] <= exited
        by_name = {row["name"]: row for row in observed}
        assert by_name["input"]["accepted"] == by_name["input"]["delivered"] == len(native)
        expected_delivery = (
            "semantic-callback" if trial == "sheet" else "native-effect" if trial == "popup" else "native-dequeue"
        )
        assert by_name["input"]["delivery_kind"] == expected_delivery
        receipts = interval["semantic_receipts"]
        if trial in {"popup", "slider"}:
            assert receipts and sum(row["phase"] == 3 for row in receipts) == 1
            sequence = 0
            identity = None
            latencies = []
            previous_trigger = 0
            for row in receipts:
                assert row["disposition"] == "semantic-delivered"
                assert row["phase"] in ({1, 3} if trial == "popup" else {2, 3})
                current = (self._integer(row["generation"], minimum=1), self._integer(row["interaction"], minimum=1))
                assert identity is None or current == identity
                identity = current
                sequence = self._integer(row["sequence"], minimum=sequence + 1)
                trigger = self._integer(row["trigger_identity"], minimum=1)
                assert trigger <= len(native)
                source = native[trigger - 1]
                if trial == "popup":
                    assert trigger > previous_trigger
                    previous_trigger = trigger
                    candidate = self._integer(row["candidate_index"])
                    if row["phase"] == 1:
                        assert trigger < len(native)
                        assert candidate == source["resulting_highlight"]
                        observed_at = source["effect_observed_ns"]
                    else:
                        assert trigger == len(native) and candidate == 20
                        # Native action may precede the menu-exit notification.
                        # Its key and Return source prove selection independently.
                        observed_at = source["post_returned_ns"]
                else:
                    observed_at = source["dequeued_ns"]
                assert row["delivered_ns"] >= observed_at
                assert row["latency_ns"] == row["delivered_ns"] - source["submitted_ns"]
                latencies.append(self._integer(row["latency_ns"]))
            if not self.sanitized:
                assert sorted(latencies)[(len(latencies) * 95 + 99) // 100 - 1] <= 100_000_000
        else:
            assert receipts == []
        if trial == "popup":
            assert interval["input_route"] == "menu-arrow-highlight-return"
            assert interval["highlight_changes"] == len(native) - 1 >= 20
            assert any(row["phase"] == 1 for row in receipts)
            assert receipts[-1]["phase"] == 3
            assert interval["tracking_model"] == "native tracking loop"
            assert native[-1]["effect_observed_ns"] == exited
            previous_highlight = None
            for row in native[:-1]:
                before, after = row["previous_highlight"], row["resulting_highlight"]
                assert type(before) is int and -1 <= before < 20
                assert type(after) is int and 0 <= after <= 20
                assert after in {0, 1} if before == -1 else after == before + 1
                assert previous_highlight is None or before == previous_highlight
                previous_highlight = after
            assert previous_highlight == 20
            assert native[-1]["previous_highlight"] == 20 and native[-1]["resulting_highlight"] == -1
        if trial == "resize":
            assert interval["input_route"] == "native-window-edge-drag"
            assert interval["in_live_resize_observed"] is True
            assert interval["resize_changes"] >= 2
        if trial in {"slider", "resize"}:
            assert len(native) == 22
            assert native[0]["type"] == 1 and native[-1]["type"] == 2
            assert all(row["type"] == 6 for row in native[1:-1])
        if trial == "slider":
            assert interval["input_route"] == "slider-drag-release"
            assert interval["tracking_model"] == "provider-owned slider drag"
            assert len({row["native_value"] for row in native}) > 2
            for row in native:
                assert row["dequeued_ns"] <= row["effect_observed_ns"] <= exited
            assert interval["pointer_down"] == interval["pointer_up"] == interval["commits"] == 1
            assert interval["previews"] > 0
        if trial == "sheet":
            assert interval["input_route"] == "independent-public-view-pointer"
            assert interval["attached_sheet_observed"] is True
            assert len(native) == 40
            assert [row["type"] for row in native] == [1, 2] * (len(native) // 2)
