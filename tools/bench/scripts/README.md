# Measurement scripts

The helpers behind the compile-performance campaign, preserved from
`~/.cache/btrc/tools` (PLAN.md D2) so the procedures that cite them keep
working from a checkout. `tools/budget_bench.py` is the measurement of record:
it runs every bucket-1 scenario on either frontend, samples it as PLAN's
acceptance budgets require and writes `report.json`. These scripts run it,
build what it measures, or dig into one number it reports.

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
| `tools/runbook/run.sh` | `run.sh <preset>`: the owner's one-command session. It clones from the hubs, builds btrcc with `build_btrcc.sh`, runs `bench.sh`'s budget_bench, `batch_gate.sh` and `instr.sh` cells under their locks after the automated quiet check, resumes after an interruption, and publishes redacted summaries (`tools/runbook/README.md`). |

A dry run of one scenario on the reference frontend, for example:

```sh
tools/bench/scripts/withlock.sh bench tools/bench/scripts/bench.sh "$PWD" "" \
    ~/.cache/btrc/bench.noindex/dry-cold/reference --frontend reference --scenarios cold --dry-run
```

## Narrower measurements

| Script | What it does | Relation to `budget_bench` |
| --- | --- | --- |
| `instr.sh` | Instructions retired and peak footprint of one cold `--jobs 1` module-unit compile (`/usr/bin/time -l`). | The `memory` scenario records the same counters; this is the quick A/B. |
| `edit_instr.py` | Instructions retired for one private-body edit compile, each fixture from the same primed cache snapshot; `--sample` captures a call graph. | Uses `budget_bench`'s `EDIT_FIXTURES`; the `edit-*` scenarios time those edits end to end. |
| `edit_e2e.sh` | Cold, two body edits and a no-op, compile plus native plan, one sample each (the 2026-09-24 evidence). | A four-build smoke of the `cold`, `edit` and `noop` scenarios. |
| `e2e_report.py` | Formats one `edit_e2e.sh` build from its native report. | Helper of `edit_e2e.sh`. |
| `gen_units.sh` | One cold module-unit compile into `<outdir>/out`, with `BTRC_TIMING`. | Produces the input of the next two. |
| `native_build.py` | Compiles those units eight at a time with the product's command (optionally with the native builder's preludes); run under `/usr/bin/time -l` for native CPU. | Isolates the native half of a `cold-dev` sample. |
| `cmp_units.py` | Compares two module-unit outputs by unit stem, ignoring paths and hashes. | Checks that two compilers emit the same program before their timings are compared. |
| `phases.py` | Sums each `BTRC_TIMING` line's phases and lists the largest. | Reads `budget_bench`'s `timing/*.txt` (`--timing-cold` keeps cold builds' too). |

## Profiles

`sample_top.py` (inclusive and self counts), `sample_callers.py`,
`sample_children.py`, `sample_path.py` and `sample_path2.py` read macOS
`sample` call graphs, such as `edit_instr.py --sample` writes, by function,
caller chain, callee and caller-callee edge.

## Gates and commits

| Script | What it does |
| --- | --- |
| `batch_gate.sh` | The D5 batch gate: diff-check, lint, format, generated, extension, `make test`, `bootstrap`, `test-c11` (rerun once for the daemon deadline alone) and BTRSmith's frontend check and library smoke, each logged with its duration. Run under `withlock.sh gate`. |
| `gates.sh` | The shorter gate matrix (lint, format, test, bootstrap, test-c11) on one tree. |
| `split.py` | Rebuilds one combined diff as a stack of unsigned commits from a JSON plan of hunks; `split-m12.json` is the plan that built the M12 stack. |

## Left in `~/.cache/btrc/tools`

The other scripts there are one-off probes bound to workspaces that no longer
exist (`bench/final-35b51de`, `perf/ei-m11*`, `bench/quick-m12*`) or
experiments whose results are recorded in the plan reference: the
native-plan probes (`np_*`, `native_ab.sh`, `native_jobs.sh`,
`native_prof.sh`, `native_pch.py`, `product_build.py`, `pieces.sh`,
`chunks_ab.sh`), the native header reader probes (`reader_*`, `prep_*`,
`nb_probe.sh`, `edit_dump.sh`, `edit_native*.sh`, `cleanup_e2e.sh`), the
`#line` trimming study (`line_dedup.py`, `line_map_equal.py`), a refactoring
oracle (`oracle_irnode.py`) and agent bookkeeping (`wf_usage.py`).
`budget_bench` supersedes `jobs_cold.py` (the `workers` scenario) and
`noop_compile*.sh` (`noop`); `batch_gate.sh` supersedes `bsm_check.sh`.
