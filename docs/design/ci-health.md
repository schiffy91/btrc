# CI health

This is the pass, failure and flake record of btrc's three GitHub Actions
workflows, [`ci.yml`](../../.github/workflows/ci.yml),
[`macos.yml`](../../.github/workflows/macos.yml) and
[`windows.yml`](../../.github/workflows/windows.yml), with every failure
signature classified and given an owner. It is the flake-rate table that
`PLAN.md` Stage 2 (`qualification-ci-health`) asks for, and the place to look
before deciding that a red job is "just flaky".

## The data

The CI-health lane collected it on 2026-09-30 from the GitHub Actions API
(`gh api`) for `schiffy91/btrc`:

- **Window:** every run from 2026-02-28 to 2026-09-28.
- **1,071 workflow runs:** 450 of `ci.yml`, 307 of `macos.yml` and 314 of
  `windows.yml`. They hold 2,253 job executions: 1,335 passed, 98 were
  cancelled and 820 failed.
- **740 of the 820 failed-job logs were retrieved.** The other 80 (76 from
  the old single `test` job and 4 from `windows`, all from 2026-06-26 or
  earlier) had passed GitHub's log retention and are counted as
  `logs-expired`.

Each retrieved log was reduced to its failing pytest cases, or to the failing
step's error lines when no test failed, and each failure was matched to one
named signature. A signature is **deterministic** when its hits form a streak
that a later push ended, and **intermittent** when they interleave with
passes of the same job. Suspect intermittent signatures were then repeated
locally: 1,600 runs of the ARC worker-entry fixture and 600 of the `Process`
corpus case on macOS, plus the daemon-deadline lane's 376 loaded runs before
its fix and 256 after.

Two rates are reported per job:

- **Failure rate** is failed executions over all executions. Most failures
  are deterministic, a regression or a broken environment that lasted until
  a later push fixed it, so this measures push discipline more than test
  reliability.
- **Flake rate** counts a failed execution as flaky only when *every*
  signature in its log is intermittent. A job that failed on a real
  regression and also hit a slow test is not a flake.

Evidence ids are GitHub Actions run and job ids. Commits are named where
the lane found or measured them. Most are on `main`; `c110056` and `1fc2fc5`
are lane-branch commits that reach `main` under new hashes in the merge
batch that added this document, and the lane's local repeats ran on
`1fc2fc5`'s tree.

## Flake rates by job

### Current jobs

The 13 `tests (...)` shards replaced the single `test` job on 2026-09-15.
The macOS matrix took its current two entries on 2026-09-01.

| Workflow | Job | Window | Runs | Passed | Cancelled | Failed | Failure rate | Flaky | Flake rate | Logs expired |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ci.yml` | `bench` | 2026-09-16 – 2026-09-28 | 37 | 36 | 0 | 1 | 2.7% | 0 | 0.0% | 0 |
| `ci.yml` | `linux-arm64-bundle` | 2026-07-22 – 2026-09-28 | 306 | 240 | 11 | 55 | 18.0% | 3 | 1.0% | 0 |
| `ci.yml` | `release` | 2026-09-15 – 2026-09-28 | 41 | 38 | 0 | 3 | 7.3% | 1 | 2.4% | 0 |
| `ci.yml` | `tests (bootstrap)` | 2026-09-15 – 2026-09-28 | 41 | 31 | 0 | 10 | 24.4% | 0 | 0.0% | 0 |
| `ci.yml` | `tests (btrc)` | 2026-09-15 – 2026-09-28 | 41 | 32 | 0 | 9 | 21.9% | 1 | 2.4% | 0 |
| `ci.yml` | `tests (c11-clang-O0)` | 2026-09-15 – 2026-09-28 | 41 | 39 | 0 | 2 | 4.9% | 1 | 2.4% | 0 |
| `ci.yml` | `tests (c11-clang-O1)` | 2026-09-15 – 2026-09-28 | 41 | 40 | 0 | 1 | 2.4% | 0 | 0.0% | 0 |
| `ci.yml` | `tests (c11-clang-O2)` | 2026-09-15 – 2026-09-28 | 41 | 40 | 0 | 1 | 2.4% | 0 | 0.0% | 0 |
| `ci.yml` | `tests (c11-clang-O3)` | 2026-09-15 – 2026-09-28 | 41 | 39 | 0 | 2 | 4.9% | 1 | 2.4% | 0 |
| `ci.yml` | `tests (c11-gcc-O0)` | 2026-09-15 – 2026-09-28 | 41 | 38 | 0 | 3 | 7.3% | 2 | 4.9% | 0 |
| `ci.yml` | `tests (c11-gcc-O1)` | 2026-09-15 – 2026-09-28 | 41 | 39 | 0 | 2 | 4.9% | 1 | 2.4% | 0 |
| `ci.yml` | `tests (c11-gcc-O2)` | 2026-09-15 – 2026-09-28 | 41 | 40 | 0 | 1 | 2.4% | 0 | 0.0% | 0 |
| `ci.yml` | `tests (c11-gcc-O3)` | 2026-09-15 – 2026-09-28 | 41 | 40 | 0 | 1 | 2.4% | 0 | 0.0% | 0 |
| `ci.yml` | `tests (corpus-btrc)` | 2026-09-15 – 2026-09-28 | 41 | 39 | 0 | 2 | 4.9% | 1 | 2.4% | 0 |
| `ci.yml` | `tests (corpus-python)` | 2026-09-15 – 2026-09-28 | 41 | 40 | 0 | 1 | 2.4% | 0 | 0.0% | 0 |
| `ci.yml` | `tests (unit)` | 2026-09-15 – 2026-09-28 | 41 | 27 | 0 | 14 | 34.2% | 0 | 0.0% | 0 |
| `windows.yml` | `windows` | 2026-06-26 – 2026-09-28 | 314 | 101 | 26 | 187 | 59.6% | 0 | 0.0% | 4 |
| `macos.yml` | `native-bundle (macos-15, macos-arm64, arm64, false)` | 2026-09-01 – 2026-09-28 | 172 | 132 | 19 | 21 | 12.2% | 1 | 0.6% | 0 |
| `macos.yml` | `native-bundle (macos-15, macos-x64, x86_64, true)` | 2026-09-01 – 2026-09-28 | 172 | 138 | 13 | 21 | 12.2% | 0 | 0.0% | 0 |

Since the shards started, no shard has flaked more than twice in its 41
runs. Every flaky failure in this table traces to five signatures:
`daemon-deadline` (4), `nix-cache` (5), and one each of
`arc-worker-entry-race`, `process-corpus` and `devcontainer-network`. The
high failure rates of `windows` and `tests (unit)` are deterministic: the
`windows` job failed on every run from 2026-07-20 until LF checkouts were
forced on 2026-09-01, and `tests (unit)` hit four container-environment
signatures between 2026-09-19 and 2026-09-22 (`linux-audio`, `busybox-ps`,
`nix-clang-wrapper-newline` and `container-git-ownership`, below).

### Older jobs

These job names no longer run. They are kept because their history holds
most of the infrastructure signatures.

| Workflow | Job | Window | Runs | Passed | Cancelled | Failed | Failure rate | Flaky | Flake rate | Logs expired |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ci.yml` | `test` | 2026-02-28 – 2026-09-15 | 410 | 66 | 29 | 315 | 76.8% | 19 | 4.6% | 76 |
| `macos.yml` | `native-bundle` | 2026-07-20 – 2026-07-21 | 2 | 1 | 0 | 1 | 50.0% | 0 | 0.0% | 0 |
| `macos.yml` | `native-bundle (macos-15, macos-arm64, arm64)` | 2026-07-22 – 2026-09-01 | 133 | 99 | 0 | 34 | 25.6% | 13 | 9.8% | 0 |
| `macos.yml` | `native-bundle (macos-15-intel, macos-x64, x86_64)` | 2026-07-22 – 2026-09-01 | 133 | 0 | 0 | 133 | 100.0% | 0 | 0.0% | 0 |

`native-bundle (macos-15-intel, ...)` never passed: the Nix installer could
not run on the Intel image, and the matrix moved to `macos-15` with Rosetta.
The old `test` job's 19 flakes are 18 `nix-cache` hits and one
`devcontainer-network` hit.

## Failure signatures

One row per signature. "Hits" lists each job the signature failed, as
failed executions out of that job's runs in the window; a "per test" or "per
binary" line counts executions of the one failing test instead of jobs. The per-job evidence ids
are in the [appendix](#appendix-per-job-evidence).

Two rows changed state in the same merge batch that added this document:

- `daemon-deadline`: the fix ("close the daemon stop race that the deadline
  flake hid", `c110056` on `stage2/daemon-deadline`) is merged, so the race
  is closed on `main`. The rows keep the lane's wording from before the
  merge.
- `hardcoded-corpus-count`: `test_corpus_strict_imports.py` now derives its
  expected source set from git (`1fc2fc5` on `stage2/cihealth`), so a new
  corpus file can no longer break it.

### Product defects

| Signature | Classification | Hits (failed / runs) | Seen | Still present | Owner |
| --- | --- | --- | --- | --- | --- |
| `generated-stale` | product defect: generated source not regenerated before push; deterministic | `ci.yml` `bench` and the 13 `tests` shards: once each, in one run<br>`ci.yml` `linux-arm64-bundle`: 20 of 306<br>`ci.yml` `test`: 19 of 410<br>`windows.yml` `windows`: 4 of 314<br>`macos.yml` `native-bundle (macos-15, macos-arm64, arm64)`: 8 of 133<br>`macos.yml` `native-bundle (macos-15, macos-arm64, arm64, false)`: 2 of 172<br>`macos.yml` `native-bundle (macos-15, macos-x64, x86_64, true)`: 3 of 172 | 2026-09-20<br>2026-07-22 – 2026-09-08<br>2026-07-22 – 2026-09-08<br>2026-09-01 – 2026-09-20<br>2026-07-22 – 2026-09-01<br>2026-09-11 – 2026-09-20<br>2026-09-08 – 2026-09-20 | no (process risk): last hit 2026-09-20, stale src/devex/lsp/catalog/generated.py | integrator (generated-check before push) |
| `regression-burst` | product defect; deterministic | `ci.yml` `linux-arm64-bundle`: 4 of 306<br>`ci.yml` `test`: 36 of 410<br>`ci.yml` `tests (btrc)`: 7 of 41<br>`ci.yml` `tests (unit)`: 1 of 41<br>`macos.yml` `native-bundle`: 1 of 2<br>`macos.yml` `native-bundle (macos-15, macos-arm64, arm64)`: 1 of 133<br>`macos.yml` `native-bundle (macos-15, macos-arm64, arm64, false)`: 2 of 172<br>`macos.yml` `native-bundle (macos-15, macos-x64, x86_64, true)`: 2 of 172 | 2026-07-23 – 2026-09-15<br>2026-09-01 – 2026-09-15<br>2026-09-16 – 2026-09-18<br>2026-09-16<br>2026-07-21<br>2026-07-23<br>2026-09-10 – 2026-09-15<br>2026-09-10 – 2026-09-15 | no: fixed by a following push | none (resolved) |
| `bundle-manifest` | product defect; deterministic | `ci.yml` `linux-arm64-bundle`: 12 of 306<br>`macos.yml` `native-bundle (macos-15, macos-arm64, arm64)`: 12 of 133 | 2026-08-31 – 2026-09-01<br>2026-08-31 – 2026-09-01 | no: fixed 2026-09-01 | none (resolved) |
| `bundle-lock` | product defect; deterministic | `ci.yml` `linux-arm64-bundle`: 16 of 306<br>`windows.yml` `windows`: 16 of 314<br>`macos.yml` `native-bundle (macos-15, macos-arm64, arm64, false)`: 16 of 172<br>`macos.yml` `native-bundle (macos-15, macos-x64, x86_64, true)`: 16 of 172 | 2026-09-12 – 2026-09-15<br>2026-09-12 – 2026-09-15<br>2026-09-12 – 2026-09-15<br>2026-09-12 – 2026-09-15 | no: '.lock' in RUNTIME_SUFFIXES (artifacts/selfhost.py:539) | none (resolved) |
| `format-lint` | product defect: unformatted/unlinted tree pushed; deterministic | `ci.yml` `release`: 2 of 41<br>`ci.yml` `test`: 100 of 410 | 2026-09-16 – 2026-09-22<br>2026-07-20 – 2026-09-15 | no (process risk): last hit 2026-09-22 | integrator (lint/format-check before push) |
| `npm-deps-hash` | product defect: stale npmDepsHash in the flake; deterministic | `ci.yml` `test`: 31 of 410 | 2026-08-20 – 2026-09-01 | no: same got-hash on all 47 hits, fixed 2026-09-01 | none (resolved) |
| `boundary-stale` | product defect: frozen boundary not re-captured / host path leaked into IR artifacts; deterministic | `ci.yml` `test`: 13 of 410<br>`ci.yml` `tests (bootstrap)`: 9 of 41 | 2026-09-01 – 2026-09-15<br>2026-09-20 – 2026-09-22 | no for the path leak: _canonical_ir rewrites IRFunctionDef.source_file to $REPOSITORY (a544d5f); recapture discipline remains an integrator gate | integrator (make test-boundaries before push) |
| `daemon-headless-2026-09-01` | product defect; deterministic | `ci.yml` `test`: 10 of 410 | 2026-09-01 | no: c2cd68f (2026-09-01) supervises headless process groups and adds podman --init | none (resolved) |
| `fortify-write-result` | product defect: generated C ignored write() result under glibc fortify; deterministic | `ci.yml` `test`: 20 of 410 | 2026-09-10 – 2026-09-15 | no: release nix build green since 2026-09-15 | none (resolved) |
| `arc-worker-entry-race` | product defect; intermittent | `ci.yml` `tests (btrc)`: 2 of 41<br>`ci.yml` `tests (btrc)`, per binary: 2 of 160 fixture runs in CI | 2026-09-15 – 2026-09-18<br>— | yes: reproduced at 1fc2fc5 on macOS, 19/1600 runs (gcc 11/800, clang 8/800) of ThreadWorkerEntryErrorRuntime.btrc via the reference compiler<br>yes: CI 2/160 binary runs (1.25%); local 19/1600 (1.19%) at 1fc2fc5: 15 'Unhandled exception: final drain failure', 1 'Unhandled exception: capture cleanup failure', 3 allocation-delta assertion failures in the implicit-free scenario | ARC/threads runtime lane (src/runtime/c threads.c/cycles.c; this lane may not edit runtime)<br>ARC/threads runtime lane (src/runtime/c) |
| `daemon-deadline` | product defect; intermittent | `ci.yml` `tests (c11-clang-O3)`: 1 of 41<br>`ci.yml` `tests (c11-gcc-O0)`: 1 of 41<br>`ci.yml` `tests (c11-gcc-O1)`: 1 of 41<br>`ci.yml` `tests (corpus-btrc)`: 1 of 41<br>`ci.yml` the corpus shards, per test: 4 of 718 corpus executions | 2026-09-16<br>2026-09-28<br>2026-09-22<br>2026-09-18<br>— | yes on main: waitForRemoval check-then-read race; fix on stage2/daemon-deadline, unmerged<br>yes on main until stage2/daemon-deadline merges; btrc frontend 4/359 (1.1%), python frontend 0/359 | daemon-deadline lane -> integrator merge<br>daemon-deadline lane |
| `missing-import` | product defect; deterministic | `ci.yml` `tests (unit)`: 1 of 41 | 2026-09-15 | no: fixed in the next push | none (resolved) |
| `linux-audio` | product defect or environment (owned elsewhere); deterministic | `ci.yml` `tests (unit)`: 11 of 41 | 2026-09-19 – 2026-09-22 | masked: since a544d5f the CI container has no openable ALSA PCM, so the tests skip instead of failing | Linux audio lane (after the container rebuild) |
| `cache-check-then-lock` | product defect; intermittent | `ci.yml` `tests (unit)`: 1 of 41 | 2026-09-22 | no: CompilerCache.load_artifacts now checks existence under the publication lock, with a deterministic regression test (a544d5f) | none (resolved) |
| `windows-selfhost-compile` | product defect; deterministic | `windows.yml` `windows`: 11 of 314 | 2026-09-01 – 2026-09-28 | no at HEAD 1fc2fc5: Python transpile of cli/WindowsMain.btrc plus zig 0.16.0 cc -target x86_64-windows-gnu -std=c11 -O2 -Wall -Wextra -Werror -pedantic with the win compat layer exits 0 (22 MB btrcc.exe); the last hit (btrc_open missing from IWorkerPoolFactory, 2026-09-28) was gone by 7b266e7 | Windows lane / integrator |
| `windows-tooling` | product defect; deterministic | `windows.yml` `windows`: 3 of 314 | 2026-09-01 | no: Windows filesystem/bundle seams fixed 2026-09-01 | none (resolved) |
| `windows-bootstrap` | product defect; deterministic | `windows.yml` `windows`: 9 of 314 | 2026-09-15 | no: fixed the same day (2026-09-15) | none (resolved) |
| `windows-ctime` | product defect; deterministic | `windows.yml` `windows`: 4 of 314 | 2026-09-22 | no: SourceReadIdentity.validate compares fstat of an open handle on win32 (a544d5f) | none (resolved) |
| `selfhost-nullable-access-warnings` | product defect: non-fatal warnings in self-hosted compiler sources; deterministic | `windows.yml+ci.yml+macos.yml` `every btrcc build` | — | yes at HEAD 1fc2fc5: Python transpile of cli/WindowsMain.btrc emits 122 'Non-optional access' warnings (Declarations.btrc 63, NativeImports.btrc 37, WindowsMain.btrc:1:1 11 mislocated, SourceIo.btrc 4, others 7); 126 on Windows CI and 122 on Linux/macOS at 7b266e7 | self-host compiler lane (narrow FeNativeResourceBinding?/FeNativeRealtimeRegistration?/NativeNode? reads); diagnostics-provenance owner for the 11 warnings mislocated at WindowsMain.btrc:1:1 |

Three of these are **process risks** rather than code defects, and the
integrator owns all three: `generated-stale` (a derived file pushed without
`make compiler-codegen-generate`), `format-lint` (an unformatted tree pushed)
and `boundary-stale` (a frozen compiler boundary not re-captured). Each is
caught by a cheap local gate, `make generated-check`, `make lint
format-check` and `make test-boundaries`, which the integrator runs before
every push.

### Test-timing and test-count assumptions

| Signature | Classification | Hits (failed / runs) | Seen | Still present | Owner |
| --- | --- | --- | --- | --- | --- |
| `lsp-warm-keystroke` | test-timing assumption; intermittent | `ci.yml` `test`: 12 of 410 | 2026-09-01 – 2026-09-02 | mitigated: now process_time, min of 3 samples, bound relative to cold (1744e99); no hit since 2026-09-02 | LSP lane (watch only) |
| `hardcoded-corpus-count` | test assumption (hard-coded count; not timing); deterministic per commit, recurring | `ci.yml` `test`: 15 of 410<br>`ci.yml` `tests (unit)`: 5 of 41 | 2026-09-01 – 2026-09-15<br>2026-09-16 – 2026-09-22 | no after this lane: 1fc2fc5 derives the expected consumer set from git | CI-health lane (this commit) |
| `glob-transpile-timeout` | test-timing assumption; intermittent | `ci.yml` `test`: 9 of 410 | 2026-09-01 | mitigated: CI passes BTRC_TEST_TRANSPILE_TIMEOUT=600 (8e1a4e8/0826fd6); no hit since 2026-09-01 | CI lane (watch only) |

Both timing assumptions are mitigated and have not recurred since early
September. The hard-coded corpus count was a test assumption, not a timing
one: every commit that added a corpus file failed it until the count was
bumped by hand.

### Infrastructure

| Signature | Classification | Hits (failed / runs) | Seen | Still present | Owner |
| --- | --- | --- | --- | --- | --- |
| `nix-cache` | infrastructure; intermittent | `ci.yml` `linux-arm64-bundle`: 3 of 306<br>`ci.yml` `release`: 1 of 41<br>`ci.yml` `test`: 18 of 410<br>`macos.yml` `native-bundle (macos-15, macos-arm64, arm64)`: 13 of 133<br>`macos.yml` `native-bundle (macos-15, macos-arm64, arm64, false)`: 1 of 172 | 2026-08-31 – 2026-09-20<br>2026-09-20<br>2026-08-20 – 2026-09-11<br>2026-07-22 – 2026-09-01<br>2026-09-08 | yes: all Nix jobs still use magic-nix-cache-action v14 (last hit 2026-09-20) | CI lane + nix owner |
| `devcontainer-network` | infrastructure; intermittent | `ci.yml` `test`: 1 of 410<br>`ci.yml` `tests (c11-gcc-O0)`: 1 of 41 | 2026-07-09<br>2026-09-16 | yes: make devcontainer still downloads the Determinate installer on every shard; rerun of the one hit passed | CI lane (ci.yml) / tooling-linux-container-refresh |
| `busybox-ps` | infrastructure; deterministic | `ci.yml` `tests (unit)`: 4 of 41 | 2026-09-22 | no: test reads /proc/<pid>/stat on Linux (a544d5f) | none (resolved) |
| `nix-clang-wrapper-newline` | infrastructure; deterministic | `ci.yml` `tests (unit)`: 4 of 41 | 2026-09-22 | no: test passes the directory through CPATH (a544d5f) | none (resolved) |
| `container-git-ownership` | infrastructure; deterministic | `ci.yml` `tests (unit)`: 4 of 41 | 2026-09-22 | no: tests pass -c safe.directory=* and nix/containerfile.nix adds safe.directory /workspace (a544d5f) | none (resolved) |
| `windows-crlf-checkout` | infrastructure; deterministic | `windows.yml` `windows`: 136 of 314 | 2026-07-20 – 2026-09-01 | no: .gitattributes '* text=auto eol=lf' (2380b1b, 2026-09-01) | none (resolved) |
| `intel-installer` | infrastructure; deterministic | `macos.yml` `native-bundle (macos-15-intel, macos-x64, x86_64)`: 133 of 133 | 2026-07-22 – 2026-09-01 | no: matrix moved to macos-15 with Rosetta in b9b5484 (2026-09-01) | none (resolved) |
| `flakehub-auth-warning` | infrastructure; deterministic (every run), never causal | `ci.yml+macos.yml` `every Nix job`: 0 of 1939 | — | yes at 7b266e7: 'Unable to authenticate to FlakeHub' annotated once in each of the 16 CI jobs of run 36492446200 and both macOS jobs of run 36492446155, all green; present in all 423 failed Nix-job logs where the installer ran (the other 134 are the Intel-installer and pre-matrix macOS failures); the failing step was never the cache action | CI lane (ci.yml/macos.yml): set use-flakehub: false on magic-nix-cache-action, or drop it (PLAN D26: no binary-cache account) |

`flakehub-auth-warning` never failed a job, but it is the first `##[error]`
line in every Nix job's log, green or red, which makes real failures harder
to find. `magic-nix-cache-action` tries FlakeHub first and then falls back
to the GitHub Actions cache. A later merge batch sets `use-flakehub: false`
on every `magic-nix-cache-action` step in `ci.yml` and `macos.yml` and drops
the `id-token: write` permission that only the FlakeHub login used;
`test_ci_workflow_contracts.py` keeps it off. The row keeps the lane's
wording until a CI run confirms the annotation is gone.

### Unclassified

| Signature | Classification | Hits (failed / runs) | Seen | Still present | Owner |
| --- | --- | --- | --- | --- | --- |
| `logs-expired` | unclassified (GitHub log retention expired); unknown | `ci.yml` `test`: 76 of 410<br>`windows.yml` `windows`: 4 of 314 | 2026-02-28 – 2026-06-26<br>2026-06-26 | n/a | none |
| `process-corpus` | unclassified (not reproduced); intermittent | `ci.yml` `tests (c11-clang-O0)`: 1 of 41<br>`ci.yml` the corpus shards, per test: 1 of 718 corpus executions | 2026-09-20<br>— | unknown: 1 hit in ~720 corpus executions; 0/600 local macOS repeats at 1fc2fc5; needs Linux-container repeats<br>unknown: python frontend 1/359 in CI (stdout 'quiet' then an assertion after line 75 of src/tests/stdlib/Process.btrc); 0/600 local macOS repeats | tooling-linux-container-refresh (targeted repeats), then stdlib Process owner<br>tooling-linux-container-refresh (Linux repeats), then stdlib Process owner |

## Open owners

These are the signatures still live on `main`, with the owner who closes
each one:

1. **The ARC worker-entry race**, `src/runtime/c` (`threads.c` and
   `cycles.c`). About 1.2% of runs of
   `src/tests/btrc/fixtures/ThreadWorkerEntryErrorRuntime.btrc` fail: 2 of 160
   in CI and 19 of 1,600 locally, mostly as "Unhandled exception: final drain
   failure". It reproduces under both gcc and clang, through the reference
   compiler. **Owner:** the ARC/threads runtime lane. The CI-health lane did
   not edit the runtime.
2. **The Linux audio-session assertions** (`test_linux_audio_session`). They
   failed 11 `tests (unit)` runs between 2026-09-19 and 2026-09-22. Since
   `a544d5f` the CI container has no ALSA PCM it can open, so they skip
   instead of failing, which hides them rather than fixing them. `PLAN.md`
   Stage 2 requires them reproduced and fixed. **Owner:** the Linux audio
   lane, after the container rebuild.
3. **The FlakeHub and magic-nix-cache errors.** `nix-cache` (HTTP 418,
   throttling and disabled-substituter errors) failed 36 jobs across
   `ci.yml` and `macos.yml`, most recently on 2026-09-20, and the FlakeHub
   authentication error appears in every Nix job. **Owner:** the CI lane with
   the nix owner. FlakeHub is now off (`use-flakehub: false`, see
   `flakehub-auth-warning`); the `nix-cache` errors remain open, and the
   option left is to drop the action for `actions/cache` keyed on
   `flake.lock` (`PLAN.md` D26: no binary-cache account).
4. **The 122 "Non-optional access" warnings in the self-host Windows
   build.** The Python transpile of `src/compiler/btrc/cli/WindowsMain.btrc`
   emits them: 63 in `ir/lowering/Declarations.btrc`, 37 in
   `frontend/NativeImports.btrc`, 4 in `frontend/SourceIo.btrc`, 7 in five
   other files, and 11 reported at the wrong location,
   `cli/WindowsMain.btrc:1:1`. Windows CI showed 126 at `7b266e7`. They are not fatal, but
   they bury new diagnostics. **Owner:** the self-host compiler lane, which
   narrows the `FeNativeResourceBinding?`, `FeNativeRealtimeRegistration?`
   and `NativeNode?` reads, plus the diagnostics-provenance owner for the 11
   mislocated warnings.

Also open, at lower rates:

- **`process-corpus`**: one CI failure of `src/tests/stdlib/Process.btrc` in
  about 720 corpus executions, not reproduced in 600 macOS repeats. It needs
  repeats inside the Linux container (`tooling-linux-container-refresh`)
  before the stdlib `Process` owner can act on it.
- **`devcontainer-network`**: `make devcontainer` still downloads the
  Determinate installer on every shard, and that download failed two jobs
  in the window (2026-07-09 and 2026-09-16). **Owner:** the CI lane, with
  `tooling-linux-container-refresh`.

## Appendix: per-job evidence

One row per job and signature, as the lane recorded it. "Latest of N
runs" names the job id of the most recent of the N failing workflow runs;
where several job ids are listed, they are all of them.

| Workflow | Job | Signature | Failed / runs | Seen | Evidence job ids |
| --- | --- | --- | ---: | --- | --- |
| `ci.yml` | bench + 13 tests shards | `generated-stale` | 14 / 41 | 2026-09-20 | run 35490769726 (14 jobs, e.g. 106025181575) |
| `ci.yml` | linux-arm64-bundle | `generated-stale` | 20 / 306 | 2026-07-22 – 2026-09-08 | 102206231032 (latest of 20 runs) |
| `ci.yml` | linux-arm64-bundle | `regression-burst` | 4 / 306 | 2026-07-23 – 2026-09-15 | 104366645188 (latest of 4 runs) |
| `ci.yml` | linux-arm64-bundle | `bundle-manifest` | 12 / 306 | 2026-08-31 – 2026-09-01 | 99796258935 (latest of 12 runs) |
| `ci.yml` | linux-arm64-bundle | `nix-cache` | 3 / 306 | 2026-08-31 – 2026-09-20 | 106025181662 (latest of 3 runs) |
| `ci.yml` | linux-arm64-bundle | `bundle-lock` | 16 / 306 | 2026-09-12 – 2026-09-15 | 104361990682 (latest of 16 runs) |
| `ci.yml` | release | `format-lint` | 2 / 41 | 2026-09-16 – 2026-09-22 | 106825156766 (latest of 2 runs) |
| `ci.yml` | release | `nix-cache` | 1 / 41 | 2026-09-20 | 106025181581 (the only run) |
| `ci.yml` | test | `devcontainer-network` | 1 / 410 | 2026-07-09 | 86189538988 (the only run) |
| `ci.yml` | test | `format-lint` | 100 / 410 | 2026-07-20 – 2026-09-15 | 104429395933 (latest of 100 runs) |
| `ci.yml` | test | `generated-stale` | 19 / 410 | 2026-07-22 – 2026-09-08 | 102206230835 (latest of 19 runs) |
| `ci.yml` | test | `nix-cache` | 18 / 410 | 2026-08-20 – 2026-09-11 | 103450084984 (latest of 18 runs) |
| `ci.yml` | test | `npm-deps-hash` | 31 / 410 | 2026-08-20 – 2026-09-01 | 99875889930 (latest of 31 runs) |
| `ci.yml` | test | `boundary-stale` | 13 / 410 | 2026-09-01 – 2026-09-15 | 104429960661 (latest of 13 runs) |
| `ci.yml` | test | `regression-burst` | 36 / 410 | 2026-09-01 – 2026-09-15 | 104527695444 (latest of 36 runs) |
| `ci.yml` | test | `lsp-warm-keystroke` | 12 / 410 | 2026-09-01 – 2026-09-02 | 100137211273 (latest of 12 runs) |
| `ci.yml` | test | `hardcoded-corpus-count` | 15 / 410 | 2026-09-01 – 2026-09-15 | 104467789091 (latest of 15 runs) |
| `ci.yml` | test | `daemon-headless-2026-09-01` | 10 / 410 | 2026-09-01 | 100047375205 (latest of 10 runs) |
| `ci.yml` | test | `glob-transpile-timeout` | 9 / 410 | 2026-09-01 | 100047375205 (latest of 9 runs) |
| `ci.yml` | test | `fortify-write-result` | 20 / 410 | 2026-09-10 – 2026-09-15 | 104366644997 (latest of 20 runs) |
| `ci.yml` | test | `logs-expired` | 76 / 410 | 2026-02-28 – 2026-06-26 | runs 28221652218, 28221786923, 28222287927 (76 jobs) |
| `ci.yml` | tests (bootstrap) | `boundary-stale` | 9 / 41 | 2026-09-20 – 2026-09-22 | 106867562518 (latest of 9 runs) |
| `ci.yml` | tests (btrc) | `arc-worker-entry-race` | 2 / 41 | 2026-09-15 – 2026-09-18 | 105718367823 (latest of 2 runs) |
| `ci.yml` | tests (btrc) | `regression-burst` | 7 / 41 | 2026-09-16 – 2026-09-18 | 105784449384 (latest of 7 runs) |
| `ci.yml` | tests (c11-clang-O0) | `process-corpus` | 1 / 41 | 2026-09-20 | 106108482249 (the only run) |
| `ci.yml` | tests (c11-clang-O3) | `daemon-deadline` | 1 / 41 | 2026-09-16 | 104647852423 (the only run) |
| `ci.yml` | tests (c11-gcc-O0) | `devcontainer-network` | 1 / 41 | 2026-09-16 | 104695563088 (the only run) |
| `ci.yml` | tests (c11-gcc-O0) | `daemon-deadline` | 1 / 41 | 2026-09-28 | 109090221677 (the only run) |
| `ci.yml` | tests (c11-gcc-O1) | `daemon-deadline` | 1 / 41 | 2026-09-22 | 106825157313 (the only run) |
| `ci.yml` | tests (corpus-btrc) | `daemon-deadline` | 1 / 41 | 2026-09-18 | 105718367985 (the only run) |
| `ci.yml` | tests (unit) | `missing-import` | 1 / 41 | 2026-09-15 | 104595652629 (the only run) |
| `ci.yml` | tests (unit) | `hardcoded-corpus-count` | 5 / 41 | 2026-09-16 – 2026-09-22 | 106851787461 (latest of 5 runs) |
| `ci.yml` | tests (unit) | `regression-burst` | 1 / 41 | 2026-09-16 | 104636112716 (the only run) |
| `ci.yml` | tests (unit) | `linux-audio` | 11 / 41 | 2026-09-19 – 2026-09-22 | 106867562778 (latest of 11 runs) |
| `ci.yml` | tests (unit) | `busybox-ps` | 4 / 41 | 2026-09-22 | 106867562778 (latest of 4 runs) |
| `ci.yml` | tests (unit) | `nix-clang-wrapper-newline` | 4 / 41 | 2026-09-22 | 106867562778 (latest of 4 runs) |
| `ci.yml` | tests (unit) | `container-git-ownership` | 4 / 41 | 2026-09-22 | 106867562778 (latest of 4 runs) |
| `ci.yml` | tests (unit) | `cache-check-then-lock` | 1 / 41 | 2026-09-22 | 106856654737 (the only run) |
| `windows.yml` | windows | `windows-crlf-checkout` | 136 / 314 | 2026-07-20 – 2026-09-01 | 99882830075 (latest of 136 runs) |
| `windows.yml` | windows | `generated-stale` | 4 / 314 | 2026-09-01 – 2026-09-20 | 106025181591 (latest of 4 runs) |
| `windows.yml` | windows | `windows-selfhost-compile` | 11 / 314 | 2026-09-01 – 2026-09-28 | 109129802888 (latest of 11 runs) |
| `windows.yml` | windows | `windows-tooling` | 3 / 314 | 2026-09-01 | 99928836972 (latest of 3 runs) |
| `windows.yml` | windows | `bundle-lock` | 16 / 314 | 2026-09-12 – 2026-09-15 | 104361990472 (latest of 16 runs) |
| `windows.yml` | windows | `windows-bootstrap` | 9 / 314 | 2026-09-15 | 104416537853 (latest of 9 runs) |
| `windows.yml` | windows | `windows-ctime` | 4 / 314 | 2026-09-22 | 106867558539 (latest of 4 runs) |
| `windows.yml` | windows | `logs-expired` | 4 / 314 | 2026-06-26 | runs 28221368333, 28221500236, 28221652248 (4 jobs) |
| `macos.yml` | native-bundle | `regression-burst` | 1 / 2 | 2026-07-21 | 88751273314 (the only run) |
| `macos.yml` | native-bundle (macos-15, macos-arm64, arm64) | `nix-cache` | 13 / 133 | 2026-07-22 – 2026-09-01 | 99837194325 (latest of 13 runs) |
| `macos.yml` | native-bundle (macos-15, macos-arm64, arm64) | `generated-stale` | 8 / 133 | 2026-07-22 – 2026-09-01 | 99831243414 (latest of 8 runs) |
| `macos.yml` | native-bundle (macos-15, macos-arm64, arm64) | `regression-burst` | 1 / 133 | 2026-07-23 | 89088354429 (the only run) |
| `macos.yml` | native-bundle (macos-15, macos-arm64, arm64) | `bundle-manifest` | 12 / 133 | 2026-08-31 – 2026-09-01 | 99796258633 (latest of 12 runs) |
| `macos.yml` | native-bundle (macos-15, macos-arm64, arm64, false) | `nix-cache` | 1 / 172 | 2026-09-08 | 102206231346 (the only run) |
| `macos.yml` | native-bundle (macos-15, macos-arm64, arm64, false) | `regression-burst` | 2 / 172 | 2026-09-10 – 2026-09-15 | 104366648119 (latest of 2 runs) |
| `macos.yml` | native-bundle (macos-15, macos-arm64, arm64, false) | `generated-stale` | 2 / 172 | 2026-09-11 – 2026-09-20 | 106025182500 (latest of 2 runs) |
| `macos.yml` | native-bundle (macos-15, macos-arm64, arm64, false) | `bundle-lock` | 16 / 172 | 2026-09-12 – 2026-09-15 | 104361990580 (latest of 16 runs) |
| `macos.yml` | native-bundle (macos-15, macos-x64, x86_64, true) | `generated-stale` | 3 / 172 | 2026-09-08 – 2026-09-20 | 106025182390 (latest of 3 runs) |
| `macos.yml` | native-bundle (macos-15, macos-x64, x86_64, true) | `regression-burst` | 2 / 172 | 2026-09-10 – 2026-09-15 | 104366647781 (latest of 2 runs) |
| `macos.yml` | native-bundle (macos-15, macos-x64, x86_64, true) | `bundle-lock` | 16 / 172 | 2026-09-12 – 2026-09-15 | 104361990328 (latest of 16 runs) |
| `macos.yml` | native-bundle (macos-15-intel, macos-x64, x86_64) | `intel-installer` | 133 / 133 | 2026-07-22 – 2026-09-01 | 99882437818 (latest of 133 runs) |
| `ci.yml+macos.yml` | every Nix job | `flakehub-auth-warning` | 0 / 1939 | — | green: 109163982041, 109163981907, 109163981788, 109163981778 |
| `windows.yml+ci.yml+macos.yml` | every btrcc build | `selfhost-nullable-access-warnings` | — | — | 109163981360 (Windows), 109163982164 (Linux) |
| `ci.yml` | tests (btrc) [per-test] | `arc-worker-entry-race per-binary rate` | 2 / 40 | — | 104595652604, 105718367823 |
| `ci.yml` | corpus shards [per-test] | `daemon-deadline per-execution rate` | 4 / 718 | — | 104647852423, 105718367985, 106825157313, 109090221677 |
| `ci.yml` | corpus shards [per-test] | `process-corpus per-execution rate` | 1 / 718 | — | 106108482249 |
