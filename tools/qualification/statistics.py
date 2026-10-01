"""Order statistics for raw measurement samples.

P6 reports the median, the nearest-rank p95 and the maximum of every sample
set, and keeps the samples themselves. The nearest-rank percentile is the
smallest sample at or above that fraction of the ordered set -- never an
interpolation -- so p95 of five cold builds is the slowest of the five, and
p95 of twenty edits is the nineteenth. `tools.budget_bench` reports through
this owner, so the bench and the ledger cannot disagree about a percentile.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class Statistic(StrEnum):
    """A summary a budget can be stated against."""

    MEDIAN = "median"
    P95 = "p95"
    MAX = "max"


@dataclass(frozen=True, slots=True)
class SampleStatistics:
    """Median, nearest-rank p95, minimum and maximum of one non-empty sample set."""

    count: int
    median: float
    p95: float
    minimum: float
    maximum: float

    @classmethod
    def of(cls, samples: Iterable[float]) -> SampleStatistics | None:
        """Summarize `samples`, or return None when there are none."""

        ordered = sorted(float(sample) for sample in samples)
        if not ordered:
            return None
        if not all(math.isfinite(sample) for sample in ordered):
            raise ValueError("samples must be finite numbers")
        return cls(
            count=len(ordered),
            median=statistics.median(ordered),
            p95=cls.nearest_rank(ordered, 0.95),
            minimum=ordered[0],
            maximum=ordered[-1],
        )

    @staticmethod
    def nearest_rank(ordered: list[float], fraction: float) -> float:
        """The nearest-rank percentile of an ascending, non-empty sample list."""

        if not ordered:
            raise ValueError("nearest-rank percentile of no samples")
        if not 0.0 < fraction <= 1.0:
            raise ValueError("percentile fraction must be in (0, 1]")
        rank = max(1, math.ceil(fraction * len(ordered)))
        return ordered[rank - 1]

    def value(self, statistic: Statistic) -> float:
        """The summary a budget names."""

        if statistic is Statistic.MEDIAN:
            return self.median
        if statistic is Statistic.P95:
            return self.p95
        return self.maximum
