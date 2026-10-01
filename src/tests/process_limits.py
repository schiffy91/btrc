"""Wall-clock limits for every subprocess a test starts.

A test that waits on a child without a limit turns a hang into a stalled
suite, so every ``subprocess.run``/``check_output``/``check_call``/``call`` in
``src/tests`` passes one of these (``test_subprocess_timeouts.py`` enforces
it). The two corpus limits are tunable for slower hosts, as the corpus runner
documents.
"""

from __future__ import annotations

import math
import os


class ProcessLimits:
    """Parses the environment-tunable limits once."""

    @staticmethod
    def positive_seconds(raw: str | None, *, name: str, default: float) -> float:
        """Parse a positive finite subprocess timeout from the environment."""
        if raw is None:
            return default
        try:
            seconds = float(raw)
        except ValueError as error:
            raise ValueError(f"{name} must be a positive number of seconds") from error
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError(f"{name} must be a positive number of seconds")
        return seconds


# One btrc compile through either compiler, or a tool of the same weight
# (make, a native-plan build, naga).
TRANSPILE_TIMEOUT = ProcessLimits.positive_seconds(
    os.environ.get("BTRC_TEST_TRANSPILE_TIMEOUT"),
    name="BTRC_TEST_TRANSPILE_TIMEOUT",
    default=300.0,
)

# How long a compiled test program may run. The default suits the corpus,
# where all but a handful finish in well under a second, and it is what catches
# a program that hangs. The heaviest test is an order of magnitude slower than
# the rest at -O0, so a slower machine -- a VM, an emulated architecture -- can
# need a larger budget without anything being wrong.
RUN_TIMEOUT = ProcessLimits.positive_seconds(
    os.environ.get("BTRC_TEST_RUN_TIMEOUT"),
    name="BTRC_TEST_RUN_TIMEOUT",
    default=15.0,
)

# One C compile and link of generated or fixture C.
C_COMPILE_TIMEOUT = 120.0

# A quick host probe: git, pkg-config, xcrun, ps, a compiler's --version.
TOOL_TIMEOUT = 60.0
