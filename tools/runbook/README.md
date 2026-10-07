# Owner runbooks

Each owner session on the Mac is one command (WORKSTREAMS.md §3.12):

```sh
tools/runbook/run.sh stage4-requal --btrsmith-branch stage4/pin-bump   # MAC-R-01, about 5 h, attended at the end
tools/runbook/run.sh stage5                                            # MAC-R-02, overnight
tools/runbook/run.sh stage13-final                                     # MAC-R-03, gates then overnight
```

Run it from a clone of `~/.cache/btrc/hub.git` outside Google Drive. `run.sh`
enters this checkout's pinned dev shell (GC-rooted at
`~/.cache/btrc/gcroots/runbook`) and runs `python3 -m tools.runbook`. The
command prints what it is about to do, each cell as it starts and finishes,
and at the end a summary and the **next** thing to do.

**If it stops** (a red cell, a reboot, Ctrl-C, a closed terminal, a locked SSH
agent), rerun the same command. Finished cells are not repeated, failed ones
run again, an interrupted cell starts over, and the run keeps the SHAs it
resolved the first time. Once a run is green and published, rerunning it says
so and does nothing. `--list` shows every cell and its status without running
anything; `--fresh` abandons the current run and starts a new one (needed after
a fix lands, because the SHAs are frozen).

Exit status: 0 green (and published, for an acceptance run); 1 a red or
unfinished cell; 2 a setup problem the message names; 3 the quiet check gave
up (`--quiet-timeout`); 4 green but not yet published (unlock 1Password and
rerun); 130 interrupted.

## What a run does

1. **Host checks.** macOS only (unless `--rehearsal`), at least 80 GB free
   under `~/.cache/btrc` (AGENTS.md "Disk"), and `build/test-btrcc` in the
   clone pruned to the newest 20 fingerprints plus any `BTRC_TEST_BTRCC` pins.
2. **Clones.** btrc from `~/.cache/btrc/hub.git` into
   `~/.cache/btrc/clones/<preset>`, and each BTRSmith pin from
   `~/.cache/btrsmith/hub.git` into `~/.cache/btrsmith/clones/<preset>/<pin>`.
   A clone with local changes is never touched; the run stops and says so.
3. **Cells**, in order. Each runs under its lock (`gate`, `bench`,
   `gui-capture`, `guest`, `btrcc-build`, ...), after the quiet check when the
   cell asks for it, with its log under the run's raw-log directory and a
   checkpoint in `cells/<id>.json`. The engine takes the lock itself with
   `flock` on the files `tools/bench/scripts/withlock.sh` uses
   (`$BTRC_LOCK_DIR`, default `~/.cache/btrc/locks`; macOS `lockf` locks the
   same way, so the two exclude each other), and runs the quiet check while
   holding it, so no lock wait separates a quiet window from its measurement.
   `btrcc-build` is the same two-slot semaphore. On the Mac a missing lock file
   is an error, as in `withlock.sh`.
4. **Evidence** (`evidence.py`): `summary.json` and `summary.txt` in the run's
   workspace; every acceptance budget_bench report ingested with
   `python3 -m tools.qualification ingest --budget-bench ... --this-host`;
   a redacted (`$HOME` → `~`, other home paths → `<redacted>`) and
   secret-scanned (built-in patterns, plus gitleaks when it is on `PATH`) copy
   of the summaries, never raw logs or the host name, pushed fast-forward to
   the never-merged branch `evidence/<preset>-<date>` on the btrc hub's
   upstream, or on BTRSmith's for a preset whose summary quotes BTRSmith
   (`evidence_repo = "btrsmith"`: stage4-requal), per WORKSTREAMS.md §7 Q24.
   Each report is ingested once per run, however often the run is resumed.
   Raw logs stay in `~/.cache/btrc/bench/<run>`.

| Where | Measurement presets | Gate presets |
| --- | --- | --- |
| workspace, checkpoints, `summary.json` | `~/.cache/btrc/bench.noindex/<preset>-<date>` | `~/.cache/btrc/gates/<preset>-<date>` |
| raw logs | `~/.cache/btrc/bench/<preset>-<date>/logs` | same directory as the workspace |
| current run pointer | `~/.cache/btrc/runbook/<preset>/current` | same |

## Owner actions the run may ask for

- **Quiet machine.** Before every quiet cell the check samples every 5 s for
  60 s. If something blocks it, the run prints the blocker and the action
  (`podman machine stop podman-machine-default`, "let the backup finish", the
  pid of a stray build) and retries every minute; it never changes a setting.
  `--quiet-timeout HOURS` gives up instead of waiting forever.
- **1Password.** Pushes (BTRSmith main, then the BTRSmith hub so later clones
  see it; the evidence branch) need the SSH agent. When `ssh-add -l` lists no identity the run asks you to unlock it and
  waits up to `--owner-wait` minutes (30); if you miss it, rerun the same
  command and only the push runs.
- **Stage 2's qualifying column.** `stage4-requal` compares release-check
  failures with `~/.cache/btrc/runbook/stage2-qualifying-failures.txt`, one test
  identity per line, derived from the actual qualifying release-check log.
  Pytest identities retain their complete node ID. Unittest headers such as
  `FAIL: test_warm (__main__.Artifacts.test_warm)` normalize to
  `tests/packaging/Artifacts.py::Artifacts::test_warm` only when that script's
  Python command appears in the log. Already module-qualified unittest IDs use
  `unittest:package.module.Artifacts.test_warm`. A summary such as
  `FAILED (failures=2)` is never an identity. Missing command provenance or
  incomplete/mismatched unittest summaries stop qualification.
  The run says so if the allowance file is missing; do not create an empty
  allowance or substitute source-check TSVs for release-check evidence.
  Compilation, linking, infrastructure and unclassified command failures are
  recorded separately and block qualification even when all named tests are
  allowed. Consecutive Make errors count as test-command propagation only
  immediately after its recognized result and with decreasing recursion depth.
- **Stage 5's baseline.** `stage13-final` compares self-compile and corpus with
  `~/.cache/btrc/runbook/stage5-summary.json` (copy it from Stage 5's workspace
  or evidence branch).

## Tuning the quiet check without code

`~/.cache/btrc/runbook/quiet.toml` (local, untracked) overrides the preset's
`[quiet]` table and the defaults in `quiet.py`:

```toml
window_s = 60
interval_s = 5
retry_after_s = 60
podman_machine = "podman-machine-default"
ignore = ["SomeHelper --daemon"]                 # command-line regexes never reported
[[extra_process_rules]]                          # appended to the defaults
label = "renderer"
pattern = "Blender"
field = "name"                                   # name (executable), args (default) or user
[[extra_cpu_rules]]
label = "Dropbox"
pattern = "Dropbox"
limit_percent = 5
```

`process_rules` and `cpu_rules` replace the defaults outright. The defaults
look for agents (`claude`, `codex`), compiler builds (`btrcc*`, `cc1`, `clang`,
`gcc`, `ld`), pytest, nix builders (`_nixbld*` users) and `nix build`, guests
(`qemu-system*`, `emulator`, `vfkit`, ...) and simulators; Google Drive, `mds`
and `mdworker` must each stay under 5% CPU.

## Options

| Option | Meaning |
| --- | --- |
| `--list` | show the cells and their status; run nothing |
| `--fresh` | start a new run instead of resuming |
| `--btrsmith-branch REF` | the BTRSmith ref for the preset's branch pin |
| `--btrc-ref REF` | the btrc ref to measure (default: the preset's, `main`) |
| `--btrcc PATH` | use this btrcc; the build cell is skipped |
| `--with ID` | run an optional cell (a prefix works: `--with ab`) |
| `--set NAME=VALUE` | override a preset variable |
| `--no-publish` | write the summary, push nothing |
| `--quiet-window S`, `--quiet-timeout H` | the quiet window length, and how long to wait for one |
| `--evidence-remote URL` | where evidence branches go (default: the hub's `origin`) |
| `--rehearsal` | run off the Mac: clone this checkout, Python locks, a 10 s advisory quiet check, 5 GB disk floor |
| `--stand-in` | budget_bench's generated stand-in instead of BTRSmith; cells that need the product are skipped |
| `--dry-run` | one sample per scenario; never pushes |

A rehearsal, stand-in or dry run is never evidence: it does not ingest or
push, and `summary.json` says `"acceptance": false`. In a Linux container:

```sh
BTRC_TEST_RUNNER=linux-devcontainer tools/runbook/run.sh stage5 --rehearsal --stand-in --dry-run
```

## Preset format

A preset is `tools/runbook/presets/<name>.toml`, owned by the packet whose
work it measures. Placeholders `{name}` expand from the preset's
`[variables]` (overridden by `[rehearsal.variables]` in a rehearsal and by
`--set`), the matrix values, and the engine:

| Placeholder | Value |
| --- | --- |
| `{btrc}`, `{btrc_sha}`, `{scripts}` | the btrc clone, its SHA, its `tools/bench/scripts` |
| `{btrsmith}`, `{btrsmith_sha}` | the cell's pin clone (its `pin` matrix value, else the branch pin) |
| `{btrcc}`, `{btrcc_args}` | the run's btrcc; `--btrcc <path>` for selfhost cells, nothing for reference |
| `{workspace_args}` | `--workspace <pin clone>`, or `--stand-in` |
| `{dry_run_args}` | `--dry-run` under `--dry-run`, else nothing |
| `{out}`, `{run}`, `{logs}`, `{run_id}`, `{home}` | the cell's output directory, the run's workspace, raw logs, id, cache root |
| `{host_entry}` | the compiler entry for this host (`cli/MacOSMain.btrc` on macOS) |
| `{tree}` | a worktree of the btrc clone at the cell's `tree` ref |
| `{cell:<id>}` | another cell's output directory |

A variable may itself hold placeholders, and a matrix value may pick a
variable: `"--scenarios", "{scenarios_{group}}"` with `group = ["cold", ...]`
reads `scenarios_cold`. A placeholder that is a whole list-valued argument (`{btrcc_args}`,
`{workspace_args}`, `{dry_run_args}`) expands to zero or more arguments.

```toml
[preset]
title = "..."            # printed and recorded
packet = "MAC-R-02"
kind = "measurement"     # measurement (bench.noindex) or gate (gates/)
quiet = true             # default for every cell
on_failure = "continue"  # or stop: nothing after the first red cell runs
before = ["..."]         # printed first: what the owner does before starting
next_action = "..."      # printed last when the run is green and published
baseline = "{home}/runbook/stage5-summary.json"   # for [[regression]]
evidence_repo = "btrc"   # or btrsmith: where the evidence branch goes

[btrc]
ref = "main"

[btrsmith]
pins = { label = "ref", ... }   # resolved once per run
branch_pin = "label"            # what --btrsmith-branch replaces
optional = ["label"]            # a pin the hub may have lost: its cells are skipped (Q44)

[variables]
name = "value"
[rehearsal.variables]
name = "value"
[stand_in]
collapse = ["pin"]              # matrix axes reduced to one "stand-in" value
[quiet]                         # QuietSettings overrides

[[budget]]                      # a miss is a finding in summary.json, not a red cell
frontend = "selfhost"           # optional
scenario = "cold-transpile"
statistic = "median"            # or p95, max; or fact = "<facts key>"
limit = 55

[[regression]]                  # compared with the same cell id in the baseline summary
scenario = "corpus"
measure = "median"              # or a metric_medians key such as max_rss_bytes
tolerance = 1.05

[[cell]]
id = "product-{pin}-{frontend}"
title = "..."
matrix = { pin = ["a", "b"], frontend = ["selfhost", "reference"] }
command = ["python3", "-m", "tools.budget_bench", "{btrcc_args}", "{workspace_args}", "--out", "{out}"]
lock = "bench"                  # gate, bench, linux-ci, guest, gui-capture, signing, btrcc-build
quiet = true
shell = "btrsmith"              # run inside tools/bench/scripts/bsm_env.sh with the pin's dev shell
cwd = "btrc"                    # btrc, btrsmith, tree or out
result = "budget-bench"         # exit, budget-bench, gate-summary, failure-list, instr, attribution
retries = 1                     # rerun a failed attempt (GUI flakes)
timeout_hours = 10
when = "green"                  # run only if every earlier cell passed
stand_in = "skip"               # cells that need the real BTRSmith
optional = true                 # only with --with <id>
requires = ["make:test-determinism", "path:{btrc}/x"]
provides = "btrcc"              # the build cell; --btrcc skips it, and cells using {btrcc} wait for it
tree = "a637aed"                # {tree} is a worktree at this ref
env = { NAME = "value" }
failures = ["^CASE-FAIL (\\S+)$"]  # optional other test format; pytest/unittest work without this
owner_action = "..."            # printed before the cell runs

# Built-in actions instead of a command:
#   action = "subset", of = "release-check-*", allowed = "{file}"   every named failure is on the list
#   action = "push", repo = "btrsmith", branch = "main"              fast-forward push upstream (never forced)
```

## Result kinds

| `result` | Passes when | Recorded |
| --- | --- | --- |
| `exit` | exit 0 | exit code |
| `budget-bench` | exit 0 and `report.json` has no failure | per scenario median, p95, max, sample count, facts, metric medians |
| `gate-summary` | exit 0 | every `batch_gate.sh` step's exit, duration and counts |
| `failure-list` | test failures have stable identities and no non-test/unclassified failure is present | `failures` feeds the later `subset`; `non_test_failures` retains blocking diagnostic records with their category and log line. With `retries`, a run that names failures is repeated; only eligible, complete attempts can establish which failures persist and which are `flaky`. One eligible attempt retains its entire failure list. `attempt_history` preserves every raw result and log path, including incomplete attempts. Interrupted commands and missing logs fail closed. |
| `instr` | `instr.sh` reports `rc=0` | instructions retired, peak footprint, real time |
| `attribution` | exit 0 and `attribution.json` (`tools/perf.py --cprofile`) has no failure | the attributed fractions (overall, minimum, per scenario), the target and each scenario's owner shares; never ingested |

The default pytest reader preserves spaces and ` - ` inside balanced parameter
brackets. Unbalanced brackets make the identity ambiguous and fail qualification
instead of truncating the name to a potentially allowed test.

## Rehearsed here, proven only on the Mac

The tests (`src/tests/python/test_runbook_engine.py`,
`test_quiet_check.py`) drive the engine against fake hubs and fake probes, and
the macOS CI unit shard runs the real Darwin probes once in report-only mode.
The macOS unit shard also proves that the engine's `flock` excludes
`/usr/bin/lockf`, which `withlock.sh` uses. Only the owner's Mac can prove: the
quiet window actually arriving (Drive, Spotlight, Time Machine, the real
process names), BTRSmith's dev shell and `bsm_env.sh`, `release-check` output
and the qualifying list, `batch_gate.sh` with the BTRSmith clone, the
1Password push, the Apple-clang btrcc build, and every number.
