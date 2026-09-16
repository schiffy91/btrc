"""Performance benchmark suite for the BTRC toolchain.

The suite measures the key performance indicators of the whole system, not one
layer of it: how fast the self-hosted compiler starts and compiles, how fast the
reference compiler transpiles in-process, how large the emitted C is and how
long the system C compiler needs for it (the cost every test in the corpus
pays), how fast a compiled program starts, and how fast the generated code
runs on fixed workloads. Every number is recorded to JSON and compared with a
tracked per-platform baseline so a regression in any of them fails CI and is
just as visible on a developer machine.

Run it from the repository root::

    make bench                # table + build/bench/results.json
    make bench-check          # the same, then fail on regressions
    make bench-baseline       # record this platform's baseline
"""
