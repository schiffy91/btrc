"""Performance benchmark suite for the BTRC toolchain.

The suite measures the key performance indicators of the whole system, not one
layer of it: how fast the self-hosted compiler starts and compiles, how fast the
reference compiler transpiles in-process, how large the emitted C is and how
long the system C compiler needs for it (the cost every test in the corpus
pays), how fast a compiled program starts, and how fast the generated code
runs on fixed workloads. Every number is recorded to JSON and compared with a
tracked per-platform baseline so a regression in any of them fails CI and is
just as visible on a developer machine.

Peak memory is guarded too: each program's compile peak, and with
``--peak-workload <workspace>`` the cold ``--jobs 1`` module-unit compile of a
pinned whole program, the workload the M11 peak budget is written for. A peak
more than 2% over its baseline fails the check. ``--peak-only`` skips every
timing and ``--no-peaks`` the programs, so the M11 guard alone is::

    python3 -m tools.bench check --peak-only --no-peaks --peak-workload ~/.cache/btrc/bsm-measure
    python3 -m tools.bench baseline --merge --peak-only --no-peaks --peak-workload ~/.cache/btrc/bsm-measure

Run it where the workload builds (BTRSmith's dev shell, as tools/budget_bench.py
documents), and not beside a gate: the compile peaks near 3 GiB.

Run it from the repository root::

    make bench                # table + build/bench/results.json
    make bench-check          # the same, then fail on regressions
    make bench-baseline       # record this platform's baseline
"""
