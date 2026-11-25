# Measurement scripts

The helpers behind the compile-performance campaign, preserved from
`~/.cache/btrc/tools` so the procedures that cite them keep
working from a checkout. `tools/budget_bench.py` is the measurement of record:
it runs every bucket-1 scenario on either frontend, samples it as acceptance
budgets require and writes `report.json`. These scripts run it,
build what it measures, or hold shared host locks.

Run them from a clone outside Google Drive. Paths default to the measurement
layout under `~/.cache/btrc`; every one is a parameter or an environment
variable:

| Variable | Default | Meaning |
| --- | --- | --- |
| `BTRC_BENCH_HOME` | `~/.cache/btrc` | measurement root (`perf/`, `measure/`, `gcroots/`) |
| `BTRC_REPO` | the repository holding the script | btrc tree whose stdlib, compiler or native builder is measured |
| `BSM_WORKSPACE` | `$BTRC_BENCH_HOME/bsm-measure` | the pinned BTRSmith copy |
| `BTRSMITH_DEV_SHELL` | `$BTRC_BENCH_HOME/gcroots/btrsmith-dev` | BTRSmith's dev shell for `nix develop` |
| `READER` | the September 2026 baseline reader | native header reader inside `bsm_env.sh` |
| `BTRC_LOCK_DIR` | `~/.cache/btrc/locks` | `withlock.sh`'s locks |

Scripts that need BTRSmith's packages re-execute themselves inside
`bsm_env.sh`. Keep measurement output under `~/.cache/btrc/bench.noindex/`
and take the `bench` lock for timed runs (AGENTS.md "Measurements", "Locks").

## Running the harness

| Script | What it does |
| --- | --- |
| `bsm_env.sh` | Runs a command in BTRSmith's dev shell with `PKG_CONFIG_PATH` and the native header reader's `BTRC_NATIVE_*` variables set: the environment `budget_bench` documents. |
| `bench.sh` | `bench.sh <btrc-tree> <btrcc> <out> [options]`: runs `python3 -m tools.budget_bench` from that tree, inside `bsm_env.sh`, on `BSM_WORKSPACE`. |
| `build_btrcc.sh` | `build_btrcc.sh <out> [entry]`: transpiles the host entry with the reference compiler and builds it with Apple clang `-O2`, the binary every timing names (`docs/design/compile-performance.md`, "Measuring a compile"). Wrap it in `withlock.sh btrcc-build`. |
| `withlock.sh` | `withlock.sh <lock> <command>`: holds one of the shared locks, or a slot of the two-slot `btrcc-build` semaphore, with macOS `lockf`. |
| `instr.sh` | Instructions retired and peak footprint of one cold `--jobs 1` module-unit compile (`/usr/bin/time -l`). |
| `batch_gate.sh` | The D5 batch gate: diff-check, lint, format, generated, extension, `make test`, `bootstrap`, `test-c11` and BTRSmith's frontend check and library smoke, each logged with its duration. Run under `withlock.sh gate`. |

A dry run of one scenario on the reference frontend, for example:

```sh
tools/bench/scripts/withlock.sh bench tools/bench/scripts/bench.sh "$PWD" "" \
    ~/.cache/btrc/bench.noindex/dry-cold/reference --frontend reference --scenarios cold --dry-run
```
