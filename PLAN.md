# PLAN: sequential roadmap for the remaining btrc and BTRSmith work

This plan replaces the previous PLAN.md, which is archived verbatim, with its line numbering intact, as [`docs/design/plan-reference.md`](docs/design/plan-reference.md). `ref:N` cites line N of that frozen reference. The reference keeps the detailed numeric budgets, ground rules, measurement rules and milestone specifications; this plan sequences the remaining work, keeps the reference's bucket order, and has one integrator run every gate. The status below was verified read-only against both repositories on 2026-09-30. Every decision is resolved in [Decisions](#decisions-all-resolved-2026-09-30); no stage waits on one.

This plan contains no effort or calendar estimates (ref:1822): order is by dependency and payoff only.

## Status (2026-09-30)

**Checked today:**
- **btrc repository**
  - `main` = `429d2e0`, clean. `origin/main` = `7b266e7`, 53 commits behind.
  - The repository is **public**. BTRSmith is **private**.
- **CI triggers**
  - The three workflows (`ci.yml`, `macos.yml`, `windows.yml`) trigger only on pushes to `main` and on PRs to `main`. None has `workflow_dispatch`.
  - `ci.yml` already runs a 13-shard Linux matrix covering `make test` and `make test-c11`.
- **BTRSmith**
  - At `7f69459b`, with 18 uncommitted files. They include `src/application/runtime/GUIApplication.btrc`, `tests/macos/SharedGPUComposition.btrc`, and the vgmstream and sqlite package sources.
  - Its flake pins btrc as `github:schiffy91/btrc` rev `05ec9cb744`.
- **Branches and worktrees**
  - Unmerged btrc branches: `native-ui-row` (4 commits), `native-ui-chrome` (4) and `btrsmith-macos-menu` (1). Their worktrees sit under `/private/tmp`.
  - The existing worktrees under `~/.cache/btrc/wt` keep their git metadata inside the Drive-synced `.git`.
- **Host**
  - Apple M1 Max (8 performance + 2 efficiency cores), 64 GiB, macOS 27.0, Xcode 27.0 (27A266a).
  - Disk: 54 GB free (99% used).
  - The podman machine is a 99 GB raw disk with 10 CPUs and 24 GiB. The applehv provider also holds unrelated `semu-*` VMs.
  - Google Drive sync and Spotlight indexing are running. `FRACTAL-NORTH.local` (in `~/.ssh/config`) did not resolve.
- **Commit signing.** Commits are unsigned (1Password SSH agent). The standing directive is to commit unsigned rather than stall, and not to push.
- **The reference** (the previous PLAN.md) is 3,885 lines. 23 of the 35 `~/.cache/btrc` paths cited in it and in the docs are already gone (listed under Corrections). Among them are `perf/setjmp-builds-2026-09-22`, `scope-copy-builds-2026-09-22` and `emission-builds-2026-09-22`.

| | |
|---|---|
| **Done** | **M11 self-host budget numbers met on Apple Silicon at `65057cb`:**<br>• edit medians 9.62 / 9.69 / 9.31 s<br>• cold transpile 43.57 s, cold dev 59.76 s<br>• no-op 2.92 s, touch 2.91 s<br>• peak 2.966 GiB (35 MiB under the 3 GiB budget), aggregate 4.828 GiB<br><br>**M11 itself is not closed.** Its acceptance counter (exactly one changed source group analyzed and lowered per body edit, ref:2915–2918) is unmet, because every edit still analyzes the whole program (ref:1104).<br><br>Recorded gates:<br>• `make test`: 12,431 passed / 142 skipped on `65057cb`; 12,439 / 172 on `1cadaf4`<br>• `make test-c11`: 8 × 1,934<br>• Boundary manifest: 309 records (`test_boundary_manifest.py:645`)<br><br>Native receipts are keyed on the environment, and debug generations are per output (`ab1f68f`, `1cadaf4`). BTRSmith's structure-first pass was done 2026-09-14 but has drifted since. |
| **Open, bucket 1 (M11)** | • Stage B skip-unchanged, which is required by the M11 acceptance counter<br>• M11 acceptance matrix<br>• 10-executable batch: ≤60 s self-host, ≤120 s reference<br>• Cold release ≤90 s<br>• Reference M11 budgets. Last reference numbers (Sept 24, compiler only): 202 s cold with module units, 228 s cold whole-program, 88–89 s module-unit edit. None taken since the M11 campaign.<br>• BTRSmith dev builds still don't use module units<br>• The required x86_64 NixOS host, where nothing has been measured |
| **Open, bucket 1 (M8a, M10, finals)** | • **M8a** (ref:2720–2724): ≥50% fewer empty child-container allocations, peak ≤3 GiB, cold transpile ≤40 s (now 43.57 s)<br>• **M10** (ref:3042–3071): a 1/2/4/8-worker table with peak RSS; ≥1.5× wall speedup at 4 workers (4 workers became the default in `6b2bf5e` with no recorded evidence); lock wait/hold counts; TSan; real-thread qualification of the stdlib concurrency contracts<br>• **Self-host finals** (ref:1740–1751):<br>  – transpile ≤10 s<br>  – cold dev ≥10× and ≤min(20 s, baseline/10), working budget 13 s<br>  – cold release ≤30 s<br>  – edit ≤5 s (p95 ≤8 s)<br>  – batch ≤30 s<br>  – peak ≤1.5 GiB<br>• **Reference finals:** transpile ≤60 s; cold dev ≤75 s; edit ≤10 s (p95 ≤15 s); batch ≤60 s; peak ≤1.5 GiB<br>• **≥10× against a frozen, repeated baseline on each required host** (ref:11–12, 23–25, 815–817)<br>• **Self-compile and full-corpus scaling workloads** (ref:1792–1794): baseline not yet recorded; no median wall/RSS regression >5% allowed |
| **Open, buckets 2–5** | • **Bucket 2:** all of C1–C5. The probe battery was never committed. There is one silent divergence: the reference compiler lowers `int d[];` to `int* d;`. There is also one misleading diagnostic: `{[2]=7}` fails with "Assignment target is not assignable".<br>• **Bucket 3:** all of P0–P4, W1, and the non-UI parts of W2/I1/I2/A1/A2. There are six target vocabularies, and none can express iOS or Android.<br>• **Bucket 4:** UI0–UI11. Windows, iOS and Android have 0 of 60 capability families.<br>• **Bucket 5:** all of P5–P7. BTRSmith has no CI. |
| **Stale (corrected in Stage 1; see [Corrections](#corrections-to-the-reference))** | • The reference's bucket row (ref:828) still says "next is the September 24 measurement round". Its header (ref:4–30) and KPI table (ref:1333–1339) still show 92 s edits.<br>• The reference's M11 record says "met" while its own acceptance counter (ref:2915–2918) is unmet.<br>• Its header says a 13 s working cold-dev budget; ref:1102 says ≤13.5 s.<br>• The P6 tables differ in the no-op row (ref:3351 vs platform-parity.md:498). The reference private-body edit row (≤15/≤20/≤30 s, platform-parity.md:501) is missing from ref:3347–3353.<br>• CLAUDE.md lines 14–40 still call the structure-first review "next" and point at BTRSmith GOAL.md, which is now issue #15. They also quote 7,274 passed / 20 skipped, and 301/277 boundary records with "twenty skips".<br>• The 21 missing cited evidence paths are not recorded as lost. |

**Unverified assumptions (marked ⚠ where they are used):**
- FRACTAL-NORTH (the 2026-09-18 x86_64 KDE/NVIDIA/PipeWire host) still exists and meets ≥16 logical CPUs and ≥16 GiB.
- `wgpu-utils-29.0.1` in the pinned nixpkgs ships a `naga` binary. There is no `naga`/`naga-cli` attribute.
- An iOS 17 simulator runtime can be installed under Xcode 27. The iOS 17 *deployment target* is confirmed supported: the SDK minimum is 15.0.
- `windows-11-arm` hosted runners are available to this repository.
- windows-aarch64 builds of wgpu-native exist for MinGW.
- The Quad Cortex is class-compliant on iPad and Android and has a WASAPI driver.
- The duration of the reference's §2 batch gate including the BTRSmith checks. It is unmeasured; Stage 2 measures it.

**Machine limits that shape this plan:**
- One Mac (M1 Max, 8P+2E, 64 GiB, 54 GB free disk).
- The batch gate saturates the machine. `make bootstrap` must never run beside the parallel suite.
- `stdlib/StdlibDaemon.btrc` asserts a wall-clock deadline. It already failed `test-c11` on `5008fae` under load, so agent builds beside a gate risk a full gate rerun.
- Wall-clock benchmarks need an otherwise idle machine. Agents change no system settings, so quiet rounds use the automated check in the standing approvals.

## Progress log

Each stage records its exit evidence here as it closes; measurements and commit hashes go with it.

### Stage 1: pre-flight (closed 2026-09-30)
- **Disk.** 54 GB free → 212 GB free. Measurement tooling preserved in `~/.cache/btrc/tools` (48 scripts, including every D2-listed one). Deleted: the `btrcc-m11*`/`btrcc-m12*` binaries and logs, `step1`–`step4`, every uncited `perf/` workspace (kept `edit-cold-2026-09-22`, `e2e-2026-09-24`, `btrcc-65057cb`), `build/test-btrcc` pruned from 828 to 20 fingerprints, and BTRSmith's `build/tests` and `build/perf` (see the lost-evidence note under Corrections). Every cited path that resolved before still resolves except those BTRSmith test outputs.
- **Podman.** `podman machine list` showed only `podman-machine-default`; it was recreated at 6 CPUs / 24 GiB / 40 GB. The 13 `semu-*` files in the applehv directory are untouched.
- **Hubs.** `~/.cache/btrc/hub.git` and `~/.cache/btrsmith/hub.git` (bare), added as remote `hub` in both Drive checkouts.
- **D3(b).** `archive/native-ui-row` tags `1e4cb30`; `native-ui-row`, `native-ui-chrome` and `btrsmith-macos-menu` deleted; `git worktree prune` removed 4 stale entries. Other sessions' worktrees untouched.
- **D3(a).** BTRSmith's 18 files committed as `5a840ba6` on `wip/2026-09-28-snapshot` without touching the working tree, and checked from `~/.cache/btrsmith/clones/d3a` at pin `05ec9cb`:
  - `application-frontend-check` fails in `tests/packaging/BuildArtifacts.py` (`test_import_content_touch_edit_and_removal`, a warm rebuild links once instead of 0 times, both frontends). It fails identically on `7f69459b` without the snapshot, so it predates the snapshot; Stage 2's BTRSmith baseline tracks it (the pin lacks `ab1f68f`'s tool-environment receipt keys, the likely cause).
  - `btrsmith-library-smoke` printed nothing and failed on both frontends while two agents and a nix build loaded the machine (load average 21), then passed on both frontends on rerun (`albums=1/1 cells=1 frames=600`). Recorded as a load flake for Stage 2's flake table.
  - The snapshot adds no failure, so BTRSmith `main` was fast-forwarded to it, the docs commit `adb3276f` landed on top, and `main` was pushed to GitHub (D4). The Drive checkout is clean.
- **Secret scan (D4).** gitleaks 8.30.1 over the 57 unpushed btrc commits: no leaks. The unpushed diff adds no home-directory paths (the four in `compile-performance.md` were already public).
- **BTRSmith docs** (`adb3276f`): HWW, NativePlatformPlan (dated 2026-09-13/14 notes moved verbatim to a history section), DD, Handoff (pin now `05ec9cb`) and the PRD's post-MVP release section record D6 and D25.
- **Exit.** Met: tools preserved outside `perf/`; free disk 212 GB (≥80 GB to continue; ≥100 GB for Stage 23 already met); hubs, locks and the capacity policy in CLAUDE.md exist; BTRSmith clean with D3(a)/(b) recorded; PLAN.md, CLAUDE.md and platform-parity agree; `git diff --check` clean. **Not met as written:** "no currently-resolving cited path was removed" holds for every btrc citation but not for BTRSmith's evidence notes, whose cited test outputs were deleted (see Corrections). The 23 already-missing btrc paths, not 21, are recorded as lost.
- **Locks.** `~/.cache/btrc/locks/{gate,bench,linux-ci,guest,gui-capture,signing}` plus the two-slot `btrcc-build` semaphore, taken through `~/.cache/btrc/tools/withlock.sh` (macOS `lockf`).
- **Docs.** CLAUDE.md's current-state section and host capacity rules; this plan's Corrections section; the P6 table made identical in `platform-parity.md`.

### Stage 2: baselines, CI health, evidence and skip ledgers (started 2026-09-30)
- **Pilot (sizing the fan-outs).** One builder and one read-only auditor, run together (workflow `wf_86fc7278-dbe`):
  - **Builder, the daemon-deadline fix** (`c110056` on `stage2/daemon-deadline`): 129 turns, 68k output tokens, 17.4M cache-read tokens, about 27 minutes including a cold btrcc build. It found the real cause: not a tight deadline but a check-then-read race in `DaemonControlProtocol.waitForRemoval` (and the same ordering in `stop()`'s reuse of a pending request). A record the exiting supervisor deleted between `absent()` and `record()` read as "replaced", so a daemon that had stopped returned 124 within 0.15–2.1 s of 5–7.5 s budgets. Under CPU load: 3 of 376 runs failed before, 0 of 256 after; with a 5 ms window injected, 12 of 16 before and 0 of 16 after. No deadline changed; a new deterministic SIGSTOP case covers the deadline path.
  - **Auditor, stdlib FileSystem/BackgroundJobs/Daemon/LocalApplicationChannel**: 129 turns, 75k output tokens, 24.3M cache-read tokens; 32 concrete findings, fed into Stage 4 wave 1.
  - **Sizing.** The weekly meter moved about one point for both together, so a builder or an auditor costs roughly half a point. Builder fan-outs are sized at up to 8 concurrent lanes and auditor waves at up to 20 agents, with the usage meter checked after every stage.
- **Docs-only since the last green code record.** `git diff 1cadaf4..main` touches only `.md` files, so the `1cadaf4` record (12,439 passed / 172 skipped; test-c11 8 × 1,934) is the code baseline.
- **Nix and container** (`330c336`, from `e74a3cc`): naga 29.0.1 comes from the pinned nixpkgs' `wgpu-utils` as a single-link package in `cfg.packages`, so the dev shell and the devcontainer share it; `flake.lock` is unchanged. The 5 naga-gated skips are gone (`make test` 172 → 167 skipped). One of them then exposed a real self-host defect (below). The devcontainer was rebuilt on gcc 15.2.0 (about 2 minutes); `make linux-ci` smoke (lint, format-check) passed in 1:35, and the full Linux run gave 2 failed / 9,468 passed / 3,139 skipped in 34:48, with the bootstrap passing separately (17:34). Both failures were real defects, fixed below. naga 29 is newer than the naga 27 inside wgpu-native 27.0.4.0, so naga acceptance does not prove wgpu-native acceptance.
- **lldb.** Two causes. The host had developer mode off (you enabled it on 2026-10-01), and the nix dev shell's `DEVELOPER_DIR`/`SDKROOT` make the `/usr/bin/lldb` and `/usr/bin/python3` xcrun shims misresolve; the fix belongs in `LldbBootstrap.ensure_lldb` (follow-up lane). The Linux container has no lldb.
- **Infrastructure hazard found.** The Determinate nix daemon garbage-collects unrooted store paths every 30 minutes on this disk, including the toolchain of a running `nix develop --command`. Every gate and agent now roots its dev shell with `--profile ~/.cache/btrc/gcroots/<name>`.
- **CI health** (`1fc2fc5`, `docs/design/ci-health.md`): 1,071 runs, 2,253 job executions and 740 of 820 failed-job logs analysed. The hard-coded corpus count (`source_count == 1246`) alone caused 20 failures; it is now derived from git. Current shards' intermittent failures: nix cache 5, daemon 4, ARC worker race 1, process corpus 1, devcontainer network 1. FlakeHub authentication is off in every nix job (`0ee699d`).
- **Defects reproduced and fixed** (each reproduced before the fix):

  | Defect | Root cause | Evidence | Commit |
  |---|---|---|---|
  | Daemon stop "deadline" flake | check-then-read race in `waitForRemoval` | 3/376 → 0/256 under load | `4c9af96` |
  | Precompiled prelude never used on glibc | glibc's `features.h` redefines `_DEFAULT_SOURCE` | 0 → 20 prelude units; objects byte-identical | `a71a9d0` |
  | ARC worker-entry flake (1.2%) | the fixture never fixed which thread drops the last reference; no runtime change | 311/40,000 → 0/150,000 | `8333e10` |
  | Self-host rejects a `@gpu` array return | array parameters decayed to pointers in GPU bodies; latent CPU-fallback typing | 7 GPU probes now agree with Python | `2c23ef7` |
  | No BTRSmith binary links through btrc's flake | the packaged native plan shipped 2 of its 12 imported files (since `ab1f68f`) | 480/480 links failed | stage2/flakefix |
  | Self-host fails a chained call on a generic type-parameter receiver | self-host never got its half of `3b13682`; Python also leaked one owned temporary | `BTRSmithCtl` builds and runs on selfhost | stage2/genchain |
  | Reference module-unit links fail | native declarations grouped by binding module instead of the program | `TrayNative` 89 undefined → links; 975 programs byte-identical | stage2/refmodlink |
- **Evidence ledger and skip gate** (`baa4d32`, `8e5e097`, then batch s2-d): one record format (`btrc.qualification.ledger/1`) for P0 rows, UI-catalog rows, P6 samples, tests and boundary records, with frozen denominators (300 family cells, 1,620 UI operation slots, 470 UI case slots). A read-only reviewer found 15 format gaps; all were closed before the gate. Every gate writes `build/skip-report.json`, and an unexpected skip fails it.
- **BTRSmith baseline** (122 MVP tests × {pin `05ec9cb`, btrc main} × {reference, selfhost} × {clang, gcc}): the five still-failing pre-existing failures (`UiApplicationRouter` now passes) plus seven new drifted tests fail identically in every cell (tests drifted from product changes; Stage 4 applies them). The old `BuildArtifacts` warm-link failure is BTRSmith's post-link `codesign` rewriting the binary after the link receipt (passes with `CODESIGN_IDENTITY=-`). Library smoke passed 4 of 4 when not overloaded. One clone measures 7.8 GB after a full run.
- **Gates.** s2-a `1745fa4` green: lint 23 s, format-check 74 s, generated-check 17 s, extension 28 s, `make test` 3,211 s (12,445 passed / 172 skipped), bootstrap 713 s, test-c11 1,979 s (8 × 1,934); **1 h 41 m** without the BTRSmith checks, which wait for the flake fix. s2-c `0ee699d` green (12,449 / 172; bootstrap 712 s; test-c11 1,651 s). s2-b `8e5e097`: phase 1 green (12,503 passed / 167 skipped).
- **Pushes (D4).** gitleaks found nothing in the 57 unpushed commits. The first HTTPS push was refused for the workflow edits (the `gh` token lacks the `workflow` scope), so the workflow-free prefix `e65d2be` went first; once 1Password was unlocked, SSH pushed `1745fa4` and then `0ee699d`. GitHub CI on `e65d2be`: Windows and macOS green, Linux 15 of 16 jobs (the glibc prelude test, fixed in s2-c).
- **Daemon runtime in the cloud containers** (lane `stage2/daemon-runtime`, `6ccfd0e`, landed in batch 5). `stdlib/Daemon.btrc` took 13–15 s against the corpus runner's 15 s limit there. The supervisor judged a child's process group alive with `kill -0 -pgid`, which still reaches zombies; once TERM kills the `sh -c` leader, its orphaned children stay zombies until pid 1 reaps them, so every stop waited out the TERM grace and sent a needless KILL. `group_running` now asks `ps` for a member not in state Z once the reaped leader is gone (and stays conservative without `ps`). The program now runs in about 5.6 s.

### Stage 3: measurement harness, peak guard, Linux-portable bench (lanes done 2026-10-01)
- **Harness** (stage3/harness, 3 commits): `budget_bench` gains `--frontend`, `--mode`, `--units`, `--target`, `--entry make`, `--dry-run` and `--timing-cold`, plus the scenarios interface-edit (≤1.10 of a clean build), instance-edit, batch, release (module ≤110% of whole), workers 1/2/4/8, self-compile and corpus (967 programs); report schema 2 carries provenance. The preserved scripts are committed in `tools/bench/scripts/`. Dry runs: 14 of 14 selfhost scenarios pass; the reference release and workers scenarios needed the module-unit link fix above. It found three harness bugs (BTRC_TIMING disabled the reference cache, 241 s → 5.05 s no-op; a smoke socket path over 104 bytes changed teardown counts; self-compile needed `--target`).
- **Peak guard** (stage3/peak, 3 commits): a peak metric in the bench suite fails above 2% (at least 1 MiB slack), and `--peak-budget-gib` adds an absolute ceiling, because 2% of the 3 GiB peak (64 MB) exceeds the 35 MiB headroom.
- **D10 batch manifest**: 10 of the 178 integration programs, one per product subsystem, sharing 65% of their app lines (`~/.cache/btrc/roadmap/batch-proposal.json`), recorded as approved.

### Stage 4: structure-first drift review (wave 1 done 2026-10-01)
- **Wave 1** (read-only, 21 agents, 77 minutes): 551 raw findings → 122 ranked (btrc 77: 8 high / 55 medium / 14 low; BTRSmith 45: 8 high / 30 medium / 7 low), plus the issue #20 inventory of all 17 tracked BTRSmith native files with keep/migrate/delete reasons. The ranked list is `~/.cache/btrc/roadmap/stage4-consolidated.json`; wave 2 writes it into BTRSmith `docs/NativePlatformPlan.md` and `src/stdlib/README.md`.
- **Wave 2 split (recorded deviation).** One serial apply agent per repository cannot carry 122 findings, so btrc's apply runs as seven lanes by disjoint file ownership (GUI/Linux; GUI core and macOS; Audio and Realtime; root prelude; the other stdlib groups; tools, build and CI; docs), with cross-repository renames last under one BTRSmith apply owner.
- **Cloud phase (2026-10-01, the Mac offline).** The apply ran as 14 cloud builder lanes forked from `cf28fe7`, each pushing only its own branch, with no per-lane CI except one macOS dispatch for macOS-only lanes:
  - Stage 2/3/14 lanes: `stage2/ci-health` (Linux/Windows expected-skip manifests, the enforced skip gate, 122 Windows self-host warnings), `stage2/module-units` (forked-worker `BTRC_TIMING` lines in both compilers; btrcc-only enum `_toString` unit parity), `stage2/gpu-parity` (self-host `@gpu` validation regardless of reachability; GPU probes 114/114 agree, was 14/105; 95 shaders byte-identical WGSL), `stage3/linux-bench` (portable `budget_bench` and receipts on Linux; CI bench `linux-x86_64` baseline with `--strict`, btrc-D002), `stage14/ccompat-inventory` (Stage 14's three items: probe battery, refusal policy with `_Bool` as `bool` per D20, VLA audit).
  - Stage 4 lanes: `gui-linux`, `gui-core-macos`, `audio-realtime`, `root-a`, `root-b`, `stdlib-services`, `stdlib-media-ui`, `tools-ci`, `tests-tools`. gui-core-macos fixed the 8 macOS CI failures (`NativeLabels` drew in the runner's light appearance; `NativeGUI` compared against a baseline macOS 15 keeps alive one run-loop turn longer); macOS run 36905763175 passed 8,407 unit tests.
  - **Integration.** Batch 1 (gpu-parity, module-units, linux-bench, gui-linux) = `d7a965a`: bootstrap fixed point passed locally in 18 min. Batch 2 (the other ten) = `4d29623`. Conflict resolutions of note: the GUI facade owns the single application slot (D035) while image handles stay worker-safe and need no application on either provider (D004/D005); `BTRC_TIMING` alone gates the timer.
  - **D14 re-captures.** root-a renamed `__btrc_application_directories_platform` to `__btrc_target_platform` (new record 0233; 310 records) and root-b removed nine unused runtime helpers (`__btrc_math_*`, `__btrc_str_track`/`__btrc_str_flush`); each accepted its own `shared.runtime-source`/order/metadata deltas. On the merged tree five records were re-captured once (`b9fb481`): the `core.c` asset, both helper orders, the retired 0228 row (now `null`) and 0233 (orders 213/228 → 204/219), each exactly the union of the two lanes' deltas. `boundary-check`: 286 of 310 checked, the 24 unchecked being the gcc/clang behavior envelope a Linux host cannot observe.
- **Wave 2 (launched 21:42Z from `4d29623`)**, cloud lanes: `stage4/w2-docs` (D072–D076), `stage4/w2-primitives` (D050, D051), `stage4/w2-crossrepo` (D068, D069, D070, D042 DateTime/Timer, D057, D059 `removeAt`/SPSC, D062 SPSC close, D031 un-export, plus a BTRSmith rename table), `stage4/w2-native-constants` (D049), `stage2/worker-usage` (per-worker `wait4` usage and the module-unit parity follow-ups), `stage4/w2-tests-ci` (D044 split, Xvfb + lavapipe for Linux GUI tests in CI, the macOS pugixml skips), `stage4/w2-macos-gui` (macOS fixture migration, then the D056/D055/D033 deletions, ActionMailbox, typography constants, D008 regression), `stage4/w2-compiler-gaps` and `stage4/w2-analyzer-parity` (compiler gaps and Python/self-host divergences wave 1 reported), `stage4/w2-tools-bench` (tools and CI follow-ups, bench baseline re-record), and the BTRSmith apply lane `stage4/w2-btrsmith` (pin bump, wave-1 ripple, bsm-D001–D045; bsm-D020/D013 follow the rename table).
- **Integration fix-forward on `main`.** CI on `109a209` failed every Linux job building the devcontainer: the GPU runtime moved to `src/runtime/gpu`, which the image's flake context did not copy (`a5fc1a5`). CI on `a5fc1a5`: the Windows self-host transpile and `src/tests/conftest.py` both refuse analyzer warnings, and gpu-parity's `analyzer/GPU.btrc` read `.kind` on a `Node?` (`14cd58f`); two LSP chain tests asserted `Vector` members after the built-in `string.split`, which returns a C string array (`b7df972`). Windows then ran `test_bootstrap.py` as a script, where tests-tools' `src.tests` imports do not resolve (`d6471c2`). A read-only adversarial review of all 14 lanes plus the merge resolutions (workflow `wf_6c5bcb3c-050`, 39 agents) confirmed 24 findings; the blocking ones (the Linux tray still called the deleted `UnixFileSystem`, `make package` required a deleted lock file, a test imported a removed name, four untimed subprocess calls) are fixed in `a637aed`, and the 12 major ones went to the wave-2 lanes that own their files plus `stage4/w2-review-fixes`. The local bootstrap does not check analyzer warnings, so every integration now also transpiles `BtrccMain.btrc` and `cli/WindowsMain.btrc` and requires zero `warning:` lines. Later fixes on `main`: `0a3213d` (gpu-parity moved the kernel contract after body validation, so both compilers reported `gpu_id() takes no arguments` before the named-argument error for `gpu_id(value=1)`; and the realtime clip-transport snapshot proof's `accepted > 0` liveness check failed on a loaded runner although every accepted snapshot was whole - acceptance is now proven after the publisher joins, the seqlock unchanged) and `db3a4f1` (the header reader refused `#define WIDE UINT32_MAX` in CI's Alpine image, where musl spells UINT32_MAX through `UINT32_C`; object-like macros now expand through Clang's preprocessor). CI on `0a3213d`: Windows green; Linux 14 of 16 jobs green (btrc, bootstrap, bench, both corpora, seven of eight strict-C11 cells), the two failures being the reader (fixed in `db3a4f1`) and a nix substitution failure before any test ran. Nix download failures while building the devcontainer (Magic Nix Cache throttled, then cache.nixos.org substitution failures) are the recurring infrastructure cause; `stage4/w2-tools-bench` makes the image build fall back and retry.
- **Wave 2 integration** (`integ/w2` from `28280e7`, merged as nine lane merges). The lanes are `stage4/w2-review-fixes`, `w2-compiler-gaps`, `stage2/worker-usage`, `w2-tools-bench`, `w2-tests-ci`, `w2-native-constants`, `w2-primitives`, `w2-crossrepo` and `w2-docs`. `w2-macos-gui`, `w2-analyzer-parity` and the BTRSmith apply lane were still running and land later.
  - **D14 re-capture.** `d2dc5a0` accepts the merged runtime-order records: primitives removed `__btrc_join`, and compiler-gaps added `__btrc_target_architecture` (order 222 in Python, 207 in btrc).
  - **Crossrepo resolutions.** `MonotonicClock` moves into `Library.Timer` beside `Timer`. `Library.Datetime` imports become `Library.Timer` or `Library.DateTime`. Code from the other lanes that still spelled a renamed API was updated (the doubled GUI facade import, `Library.GUI.Capture`, `Library.GPU.SurfaceRenderer`, `CallbackCancellation.*`, `TerminalPassword`).
  - **Docs resolutions.** The docs lane rewrote the READMEs against the pre-rename tree, so the crossrepo names were reapplied and the native-file table recounted.
  - **Review.** A read-only adversarial review of the merges (workflow `wf_7d9f6920-573`) confirmed 3 findings. Two were blocking: `macos.json` had no rule for the native-constants lane's three new Linux-only macro tests or for review-fixes' `test_linux_gui_gpu_view_reparent`, so the macOS skip gate would fail. The third was a stale `Hardware.h` row in `native-interop.md`. All three are fixed, along with the review's minor doc findings: README counts and GPU module names, Daemon/FileSystem/GUI README references to removed or renamed APIs, `INCLUDE_FIXTURES`, and the w2-primitives removals added to the BTRSmith rename table.
  - **Sent to a lane.** One minor parity divergence went to `w2-analyzer-parity`. btrcc types an empty `[]` from its target in return and argument positions (bare, or both branches of a ternary); the reference compiler does so only for declared locals. Probing showed the bare-literal half predates wave 2.
  - **Gates on the merged tree.** Clean: generated-source check, lint, format-check, `git diff --check`, and the self-host transpile of `BtrccMain`, `cli/WindowsMain` and `cli/MacOSMain` with zero analyzer warnings. `boundary-check` checked 287 of 311 records. The 65 changed test modules plus the 64 corpus programs the lanes touched, through both compilers: 1,046 passed. The 16 initial failures were the dev shell's header reader, which builds from the primary checkout and predated native-constants; all 34 macro-constant tests pass on the current reader.
- **Wave 2, second batch** (from `35e6b91`): `stage4/w2-macos-gui` closes D033/D055/D056/D008. The macOS fixtures mount through the GUI factory, and the provider's raw mounting paths, `setFrame`, `MacOSPanel.addChild` and the embedded event pump are gone. Every `MacOS.*` module except the Tray seam is private; tests that inspect provider internals compile against a test-only stdlib root (`src/tests/gui_provider_root.py`). The macOS action mailbox wraps the shared `ActionMailbox`, and the typography limits are named constants. It passed three macOS dispatches on the lane. Landed with `stage18/emit-order` and `stage22/p0-inventory`; its removed provider APIs were added to the BTRSmith rename table. Local gates on the batch: the generated-source check, lint, format-check, zero-warning self-host transpiles and `boundary-check` (287 of 311) are clean. Changed tests plus the full corpus through both compilers: 2,129 passed. The bootstrap reached its fixed point (20 min). The review (workflow `wf_1ce4083f-71c`) found one stale native-interop line, now fixed.
- **Wave 2, analyzer parity** (`stage4/w2-analyzer-parity`, merged onto `cf68f93`): 8 of the 9 assigned divergences are closed in both compilers:
  - GPU `var` float typing;
  - bool operators;
  - `new` on non-classes;
  - access specifiers on class members;
  - unreachable GPU rejects;
  - f-string diagnostic positions;
  - the duplicate `assert.h` include;
  - one rule for empty `[]`/`{}` taking the target's type.

  It also fixed a trigraph-escaping bug in both C emitters and added a parity battery. `docs/design/compiler-parity.md` records what is held equal and what remains: emitted-C gaps, btrcc's missing nullable flow, and nullable-to-non-nullable stores. Lanes `stage4/nullable-flow-parity` and `stage4/c-output-parity` own those. Two merge conflicts were resolved: btrc keeps r05's `StringConcat` piece check after the lane moved `validateAssignment`, and the lane's `rejectDuplicateTopLevel` composes with r01's repeated-prototype rule. Local gates on the merged tree:
  - clean: generated-source check, lint, format-check, zero-warning self-host transpiles, `boundary-check` (287 of 311);
  - `src/tests/btrc`, the changed tests and the full corpus through both compilers: 5,982 passed. The one failure was `stdlib/Daemon.btrc`'s wall-clock limit under load; it passes alone, and lane `stage2/daemon-runtime` owns the cause;
  - the bootstrap reached its fixed point.

### Stage 14: C5 inventory (done 2026-10-01, cloud lane `stage14/ccompat-inventory`)
- `ccompat-c5-baseline`, `ccompat-refusal-policy`, `ccompat-r23-vla-audit` landed in `828f3a2`, `8b0ec02`, `dda6e26`: a 134-probe inventory through both compilers (`test_c_compatibility_inventory.py`), identical refusal diagnostics for rows 20, 22 and 24 (`_Bool` is `bool` per D20; reserved-word names give a targeted error), and VLA forms pinned and documented in `docs/known-language-gaps.md`. 171 of 171 tests passed and the bootstrap stayed byte-for-byte. The review later found that a negative runtime bound clamps the storage but not the iteration length (both compilers); `stage4/w2-compiler-gaps` owns the fix.

### Stage 15: C1 schema commit (done 2026-10-02, main session)
- **Design review.** Two read-only adversarial reviewers (workflow `wf_7d48ab51-ee9`) compared options (a)–(f) and C4's needs; they agreed on (a), (b), (d), (f) and C4, and split on (c) and (e). Decisions, conventions and the rules fixed now so no construct needs a second schema commit are in `docs/design/c-compatibility.md`: unnamed prototype parameters use `""`; several declarators splice into the enclosing list with per-declarator copies of the specifier, and only the C-for initializer holds a list; no `EmptyStmt`; braceless bodies are synthesized blocks; adjacent strings are a new `StringConcat(expr* parts)`, leaving `StringLiteral` one token; `for`-header commas are `CommaExpr(expr* elements)`; C4 needs no AST change; a nullable `?` specifier with several declarators is refused; `T (*name)(...)` is disambiguated syntactically with an analyzer check.
- **Schema.** `ForInitVar(stmt* declarations)` replaces `ForInitVar(stmt var_decl)`; `StringConcat` and `CommaExpr` are appended to `expr`. Both reuse existing lazy list storage, so the fat `Node` gains no field and loses `varDecl`. Every consumer in both compilers and the LSP reads the declaration list; the realtime canonical-loop proof accepts exactly one declaration; the canonical renderer covers both new kinds. The parsers produce no new syntax yet.
- **Exit evidence.** Generated-source check clean; `boundary-check` unchanged (286 of 310 checked; no record changed, because the boundary source has no C-for, parameter or adjacent string); self-host AST/parser/driver/lexer parity 857 passed; full corpus through both compilers 1,920 passed / 6 skipped; bootstrap fixed point (19 min); zero analyzer warnings on the self-host transpile. **Memory** (Linux stand-in; the BTRSmith row needs the Mac): btrcc built by gcc from `a637aed` and from this commit, each compiling `src/compiler/btrc/BtrccMain.btrc` (`--target linux-x86_64 --no-cache`, whole program) three times alternately, measured through `wait4`: peak RSS 2,730,348 → 2,720,784 KiB (−0.35%, identical across runs), user CPU median 111.9 → 112.3 s (+0.3%, within run-to-run noise; instructions retired are not measurable in this container), byte-identical C output. The ≤0.3% exit gate passes on memory. **Awaiting the Mac:** the BTRSmith self-host compile's peak footprint and instructions retired at `--jobs 1` under `/usr/bin/time -l`, before and after.

### Stage 17: C2 design (done 2026-10-02, main session)
- `de986a9`: workflow `wf_104e132f-1a7` (three read-only drafters, two adversarial reviewers, synthesis) recorded the C2 aggregate representation and Stage 18's array dimensions in `docs/design/c-compatibility.md`. Unions are `StructDecl(is_union)`. Typedef records are spliced. Anonymous members are their own kind, and designators sit in a parallel `BraceInitializer.entries` list. `CompoundLiteral` is added. Flexible array members follow C11. Bit-field widths go in `FieldDef.value`, and `TypeExpr.elements`/`array_pointer_depth` carry the dimensions. The fat `Node` gains no pointer field. The serial schema commit waits for `ccompat-c1-integrate`.

### Stage 16: C1 constructs (lanes integrated 2026-10-02)
- Four cloud lanes, merged in PLAN order onto `3812e44`: `stage16/c1-body` (r02 braceless bodies, r06 the empty statement), `stage16/c1-params` (r01 `(void)` and unnamed prototype parameters), `stage16/c1-lit` (r05 adjacent string literals as `StringConcat`) and `stage16/c1-sem` (r04 char arrays from string literals). Each lane flipped its inventory rows and pinned identical refusals in both compilers.
- **Integration fixes.** Merging r05 dropped an import r04 used. r04's literal-only sites broke r05's kind-coverage contract, so r04 now takes any string constant through the source-macro decoder: `char s[] = "ab" "cd";` works in both compilers, and its exact fit and overflow refuse. r04's duplicate byte counters were removed, leaving one decoder per compiler. Two c1-body corpus files were also run through `btrc-format`. `docs/design/c-compatibility.md` lists what `ccompat-c1-integrate` still owes.
- **Evidence.** The generated-source check, lint, format-check and `git diff --check` are clean. The self-host transpile of all three entries has zero warnings. The full corpus through both compilers, plus the parser, formatter, LSP, refusal, inventory, contract and lexer tests, gave 2,837 passed. The one failure was `stdlib/Daemon.btrc`'s wall-clock deadline under `-n 4`, which passes alone in both compilers. The bootstrap reached its fixed point (20 min).
- **Devex follow-ups (lane `stage16/devex-c1-fixes`, landed in batch 5).** The review's F1–F6 are fixed. The LSP ends a braceless body's scope with its statement (`58892da`). The formatter now lays out braceless `else`, do-while, closing brackets, imports and compaction correctly (`557ea36`), closes an `if` inside an unbraced `do` with it, and nests continuation-line bodies (`b4f2c1b`); three corpus files were reindented, whitespace only. Formatter and LSP tests: 529 passed.
- **Next.** The `c1-decl` lane (r03 multi-declarators, r19 the comma operator, r07 function-pointer declarators, plus the header miner), then `ccompat-c1-integrate`, then C4.

### Stages 16 (C4), 19 and 20: designs (done 2026-10-02)
- Workflow `wf_926e5dfc-b6e` ran one drafter and two adversarial reviewers (implementability and C11 soundness) per topic, followed by a synthesis. It produced `docs/design/c-preprocessor-conditionals.md`, `docs/design/c-vocabulary-specifiers.md` and `docs/design/c-goto-labels.md`, linked from `c-compatibility.md`.

### Stage 18: emission-order parity (lane `stage18/emit-order`, 2026-10-02)
- **Serial step 1.** `IRTypeDeclarationPlanner` (`ir/optimization/Optimizer.btrc`) ports `IROptimizer.plan_type_declarations`. btrcc's `CEmitter` now emits forwards, the planned type declarations, then prototypes, for whole programs, split units and module units. `ModuleUnitDeclarations.orderStructs` is retired. Over the 964-program corpus, Python's C is byte-identical before and after; the only differences are three files whose absolute `#include` path names the checkout. 546 btrcc outputs changed, each a pure reordering. The layout of user declarations and prototypes now matches Python's in 960 of 964 programs (446 before) and in 496 of 496 sampled module-unit files (286 before). Whole-file byte identity stays at 3 programs, because lowering differs; `docs/design/c-compatibility.md` lists the differences. A read-only reviewer confirmed the port and found no blocking defect. Two gaps shared by both planners are left as they are: array sizes do not wait for enum values, and `X_V_Data` has no forward declaration.
- **Exit evidence.** The bootstrap fixed point passed (`test_bootstrap.py`, 20m42s). The corpus through both compilers had 1,983 passed, 6 skipped and 1 failed: `stdlib/Daemon.btrc` under btrcc ran 15.0 s against the runner's 15 s limit. The unchanged base binary also takes 15.0–15.15 s and Python's build takes 14.6 s in this 4-CPU container, so the change is not the cause; it needs a look on the Mac. Module-unit suites had 61 passed and 8 skipped. `test_cached_split_cli_restores_complete_executable_generation` (4 cases) also fails on the unchanged base, because the Python CLI reports `--profile` as cached; that is recorded, not fixed here. `boundary-check` held 287 records unchanged. Strict C11 compiled 39 reordered programs under gcc and clang at `-O0` and `-O2` (156 compiles) with no errors. Both self-host entries transpiled with zero analyzer warnings.

### Stage 22: P0 inventory (inventory done 2026-10-02, cloud lane `stage22/p0-inventory`; the stage stays open)
- **`platforms-p0-inventory`.** `docs/design/platform-inventory.toml` classifies every operation on the six target slices, in the ledger format. The ledger gained `TARGET_SLICES`, which lets an inventory row name a family plus artifact variant, a `slices` denominator axis, and a compact TOML row form (`InventoryRows`).
- **Denominator.** 323 operations × 6 slices = 1,938 slots, frozen as release `p0-inventory-2026-10-02` in `tools/qualification/denominators.toml`. The operations are 84 stdlib exports outside UI0's `App`/`GUI`/`Tray`/`UI`, 223 runtime helpers and 16 corpus topics. `test_platform_inventory.py`, which runs in `make test`, recomputes them from the manifests, exports and corpus and fails on drift.
- **Totals (equivalent / adapted / os-restricted / missing).**
  - Windows x64 and arm64: 271 / 36 / 4 / 12 each.
  - iOS device and simulator: 281 / 16 / 23 / 3 each.
  - Android arm64 and x86_64: 294 / 15 / 11 / 3 each.
  - No row is `passed`: no slice result has been ingested.
- **Review.** A skeptical reviewer checked 30 sampled cells and confirmed 22. Its 8 findings were applied: 6 regression lists, 1 owner and 1 reason. None changed a class.
- **Deferred.**
  - BTRSmith journeys and package contracts are pending in the private BTRSmith repository (`btrsmith-p0-inventory`) and are kept out of these totals.
  - The entry gate, the adaptation approvals (`platforms-p0-adaptations`), the matrix pin and the device registry are still pending.
- **Runtime-helper pins (cloud lane `stage22/runtime-helper-pins`).** Each runtime row now cites the corpus programs whose emitted C carries its helper, for every compiler whose catalog carries it: a greedy cover of 26 programs reaches 199 of the 223 helpers, five of them through new corpus programs. The other 24 carry a checked reason: five arc_runtime API roots that only a stdlib archive selects, and nineteen catalog rows (the collection templates, the typed div/mod and `fromInt`/`fromFloat`) that no lowering in either compiler selects. `test_platform_inventory.py` compiles every pinned program with both compilers and requires each pinned helper's catalog definition in the C. `__btrc_gpu_index_check` is pinned for the Python compiler alone: the manifest gives gpu helpers no btrc order, and btrcc's CPU fallback lowers its own `__btrc_gpu_checked_index`. Moving that fallback onto the catalog helper is a catalog decision left open.

- **Batch 5** (`integ/b5` on `7948af0`): `stage16/devex-c1-fixes`, `stage22/runtime-helper-pins`, `stage2/daemon-runtime` and `stage22/p0-matrix`. Gates: the generated-source check, lint, format-check, `git diff --check` and the zero-warning self-host transpile of all three entries are clean. The formatter, LSP, platform-inventory, device-registry, toolchain-matrix and naming tests plus the full corpus through both compilers gave 2,581 passed and 6 skipped (the GPU compute runtime). No compiler source or compiler-imported stdlib module changed, so the bootstrap was not re-run locally; CI runs it.

### Stage 22 (read-only planning, cloud lane `stage22/p0-matrix`, 2026-10-02)
- **Toolchain matrix** (`tooling-p0-toolchain-matrix` with `platforms-p0-matrix-pin`): `docs/design/platform-toolchain-matrix.md` pins one row per slice and tool, each with its source and access date. The pins:
  - **Apple.** Xcode 27.0 (27A266a, GA), with deployment targets iOS 15–27 and simulators iOS 17 or later.
  - **Android.** NDK r29 `29.0.14206865` (16 KiB pages by default), minSdk 29, target and compile API 36 (Play's requirement from 2026-08-31), JDK 17, Gradle 9.6.0 with AGP 9.4.0. The direct aapt2/d8 path is undocumented as a supported build.
  - **Windows.** Windows 11 24H2 (26100) as the floor; zig 0.16.0 for `x86_64-` and `aarch64-windows-gnu`.
  - **Libraries.** wgpu-native v27.0.4.0 prebuilt archives per slice, and FreeType 2.14.3.
- **D21's MSVC condition holds.** wgpu-native ships Windows ARM64 only as an MSVC build, so GPU-linked ARM64 artifacts take `aarch64-windows-msvc`. The owner confirms this at Stage 24.
- **Probe.** `python3 -m tools.qualification.toolchain` re-checks the recorded Mac facts and prints mismatches; on Linux it reports every probe not applicable. Its test is `test_toolchain_matrix.py`.
- **Device registry** (`qualification-device-lab`): `docs/qualification/devices.toml` and its README. Every physical gate of Stages 23 and 39–43 maps to a named device or an `unavailable` row that names its blocking item. `test_device_registry.py` verifies it against this plan's item ids.
- **Adaptations** (`platforms-p0-adaptations`): `docs/design/platform-adaptations.md` is a draft, drafted by three read-only agents from official platform docs. It covers ten desktop-only contracts across three platform families and ends with ten questions for the owner.
- **Entry baseline.** The Windows overlay docs were already correct (`src/runtime/windows/`). The naming test's dead `Windows/sys` exemption is removed.
- **Pending:**
  - the entry gate run (`platforms-p0-entry-baseline`), which needs the Mac and the bucket-order call;
  - the owner's sign-off on the adaptations;
  - every physical device and account (D8);
  - wgpu-native archive digests, recorded at first download in Stage 23.

## Decisions (all resolved 2026-09-30)

Every decision below is settled. Where stage text further down still says "you approve", "you close", "if approved", "your checklist" or "blocked on push", the resolution in this section and the standing approvals after it govern. No stage waits on a decision.

| # | Decision | Resolution |
|---|---|---|
| D1 | **Bucket order** | **The reference's bucket order**, Stages 1–43 as numbered. UI-first is rejected. |
| D2 | **Disk reclaim** | **The allowlist sequence, as listed:**<br>1. **Preserve first.** Copy the measurement tooling to `~/.cache/btrc/tools`: from `perf/`, `gates.sh`, `bench.sh`, `build_btrcc.sh`, `edit_instr.py`, `cmp_units.py`, `instr.sh`, `sample_*.py`, `bsm_env.sh`, `native_build.py` and `edit_e2e.sh`; plus `m12/split.py`. Stage 3 commits it into `tools/bench`.<br>2. **Keep** every cited path that still resolves: `perf/edit-cold-2026-09-22`, `perf/e2e-2026-09-24`, `perf/btrcc-65057cb`, `bench/final-*`, `bsm-measure`, `checkpoints/2026-09-22-*` and `gcroots`.<br>3. **Delete only** the `btrcc-m11*`/`btrcc-m12*` binaries and their build logs, the `step*` directories, uncited `perf/` workspaces, and `build/test-btrcc` fingerprints beyond the newest 20 plus pinned ones.<br>4. **BTRSmith:** after a citation check, clean `~/.cache/btrsmith/build/tests`, and `perf` only if nothing cites it. Keep `build/evidence` and `signing`.<br>5. **Podman:** run `podman machine list` and never touch a `semu-*` VM; recreate only the btrc machine, with a 40 GB disk and 6 CPUs.<br><br>No local Windows VM (D8), so the bucket-3 target is **≥100 GB free before Stage 23**. If free space is short, re-prune `build/test-btrcc` and the BTRSmith test outputs, and install one iOS runtime at a time. |
| D3 | **Work in progress** | **(a) BTRSmith's 18 uncommitted files** (last modified 2026-09-28). In Stage 1:<br>• commit them unsigned on BTRSmith branch `wip/2026-09-28-snapshot`<br>• run `application-frontend-check` and the library smoke on both frontends from a clone outside Drive<br>• if green, fast-forward BTRSmith `main` to the snapshot<br>• if red, keep `main` at `7f69459b` with a clean tree, record the failures here, and give the branch to Stage 4 as input. Nothing is lost either way.<br><br>**(b) Unmerged btrc branches.**<br>• `btrsmith-macos-menu`: its one commit is already on `main` as `768ccd8` (patch-identical), so delete the branch.<br>• `native-ui-row` and `native-ui-chrome`: both point at the same 4 commits (`1e4cb30`). They are unmerged and predate the camelCase migration. Tag them `archive/native-ui-row`, then delete both branches. Stages 31 and 34 port what still applies: sRGB presented once, the app-owned title bar, offscreen capture of the presented frame, and the select-chevron uploads.<br>• Then run `git worktree prune`. It drops only entries whose directories are gone. Existing worktrees of other sessions (for example `/private/tmp/claude-501/btrc-latest`) are left alone. |
| D4 | **Pushes and CI triggers** | **Push, without per-batch approval.** This supersedes the standing "don't push" note.<br>• **btrc.** After every green batch gate, push `main` to `origin` fast-forward only. Never force-push and never rewrite pushed history. The first push (Stage 2) adds `workflow_dispatch` to `ci.yml`, `macos.yml` and `windows.yml`.<br>• **Before the first push,** scan the whole unpushed range for secrets, tokens, keys and private absolute paths (gitleaks from nixpkgs plus a grep). If something is found, remove it from the still-unpushed commits before pushing.<br>• **BTRSmith** (private). Push `main` after its own gates, so its flake can pin pushed btrc commits and its CI can run.<br>• **Transport.** SSH, or HTTPS through `gh`'s credential helper if the SSH agent does not answer.<br>• **A red CI run after a push** is fixed forward, or reverted by a new commit, before the next push. |
| D5 | **Gate cadence** | **One batch gate per merge batch of 2–4 commits.** This amends ref:842–844 and ref:3269–3271.<br>• **The batch gate** is the reference's §2 list: `make test`, `make bootstrap`, `make test-c11`, `lint`, `format-check`, `generated-check`, `extension`, structure/hygiene and `git diff --check`, plus BTRSmith `application-frontend-check` and the library smoke on both frontends.<br>• **Where it runs.** On the Mac, from a worktree outside Drive, one gate at a time; `make bootstrap` never runs beside anything. Once D4's first push lands, Linux CI's 13 shards carry `make test` and `test-c11` on Linux, and the Mac's own `test-c11` runs at bucket exits and whenever a batch touches emission, the runtime or the C11 flags.<br>• **The daemon deadline.** If `test-c11` fails only on `stdlib/StdlibDaemon.btrc`'s wall-clock deadline before Stage 2's fix lands, rerun it once.<br>• **A red batch** gets D5's revert-bisect: revert one lane commit at a time on a scratch branch with the failing tests, re-gate without the culprit, and send it back to its lane. |
| D6 | **Agent use** | **(a) Yes.** Agents work only from clones of `~/.cache/btrc/hub.git` and `~/.cache/btrsmith/hub.git`, outside Drive.<br>**(b) Yes.** Read-only auditors run the structure-first review; one owner applies the changes.<br>**(c) Yes.** Platform lanes run in parallel in buckets 3–4, with one contract owner.<br><br>Stage 4 amends BTRSmith `HWW.md:18`, `HWW.md:67` and `NativePlatformPlan.md:17` to match. Stage 22 amends `platform-parity.md:587–588` and the native-ui-parity review-checkpoint wording. |
| D7 | **x86_64 NixOS acceptance host** (ref:1724) | `FRACTAL-NORTH.local` did not resolve on 2026-09-30.<br>• **At Stage 10's start,** probe it again, read-only (`nproc`, `free -g`, `lscpu`, `nix --version`).<br>• **If it answers with ≥16 logical CPUs and ≥16 GiB,** it is the acceptance host and BTRSmith's self-hosted CI runner. Registering that runner is approved.<br>• **If it does not,** ref:1724 is amended: Apple Silicon is the primary acceptance host, and x86_64 Linux is qualified on GitHub-hosted `ubuntu-24.04` x86_64 runners through `workflow_dispatch`. That covers correctness, instructions retired, peak memory and the ≥10× ratio against a baseline frozen on the same runner image. The ≥16-CPU wall-clock rows are recorded as **awaiting hardware**, with the exact command to run.<br>• No purchase. |
| D8 | **Devices, accounts, licences, disk** | **No procurement and no account creation by an agent.**<br>• **iOS:** simulators. Use the iOS 17 runtime if Xcode 27 can install it; otherwise the oldest installable runtime, with the iOS 17 deployment target compile-checked.<br>• **Android:** emulators for API 29, the current API, and a 16 KiB-page image. **Accepting the Android SDK licences is approved.**<br>• **Windows:** GitHub-hosted `windows-latest` (x64) and `windows-11-arm` (ARM64) runners. No local Windows VM.<br>• **Signing:** ad-hoc on Apple platforms (no Developer ID identity exists: `security find-identity` reports 0 valid identities). Android uses the debug keystore plus a locally generated release keystore in `~/.cache/btrsmith/signing`, never committed. Windows builds are test-signed or unsigned.<br>• **Awaiting hardware or an account:** physical iPhone/iPad (ProMotion), Android vendor devices, Windows hardware, the Quad Cortex, notarization, store packages and Windows code signing. These rows are fully prepared (scripts, runbooks, builds signed as far as possible) and recorded as **awaiting hardware/account**, never as met. |
| D9 | **Measurement copy and BTRSmith Makefiles** | **Yes.** Re-pin the measurement copy to the post-Stage-4 BTRSmith; Stage 5 measures both pins; any M11 budget the new pin misses is a finding before Stage 6. Dev builds may pass `--module-units`; attestation runs after `SIGN_CODE`. |
| D10 | **Batch manifest** | The 10 entry points the Stage 3 agent proposes from the 178 integration tests are **approved as proposed**. The agent records them with the reason each was picked. |
| D11 | **Does bucket 1 close at M11?** | **No: run the push for every final row**, with a measured stopping rule instead of a timebox. The rows are the self-host finals, the reference finals, M8a's ≤40 s, and ≥10× on each required host.<br><br>A row closes when it is met, or when two consecutive merge batches aimed at it each improve its metric by less than 2% (instructions retired at `--jobs 1`, or the row's own metric). In the second case the row is revised formally in this plan: the measured value, the profile evidence, and the next lever named. |
| D12 | **Resident compiler** | **Build it only if** Stage 6's floor experiment shows per-file caches cannot bring a btrcc private-body edit to ≤3 s of compile time. If it is built, both compilers get it. No parity exception. |
| D13 | **Reference compiler budgets** | **The M11 budgets are binding:** ≤15 s edit (p95 ≤20 s), ≤180 s cold transpile, ≤210 s cold dev, ≤2 GiB peak, ≤120 s batch. The reference finals stay open rows under D11's stopping rule, revisited after Stage 8 with the cProfile evidence. |
| D14 | **Frozen runtime source** (`shared.runtime-source`) | **Approved where a stage needs it:** borrowed returns, M9, the ARC fast path, the P2 probes and the P3 launch seam. One re-capture per commit, its reason recorded in the boundary manifest and here, both compilers in parity. |
| D15 | **mimalloc, release mode, prebuilt stdlib** | • **mimalloc:** adopt only if a quiet run shows it is still ≥5% faster cold.<br>• **Release builds:** whole-program until Stage 7 qualifies separate mode, then module units plus LTO.<br>• **A prebuilt stdlib does not count as the "installed toolchain."** |
| D16 | **BTRSmith default dev frontend** | **Switch to selfhost** at Stage 9's exit. |
| D17 | **M8b (per-kind nodes)** | **Deferred.** It runs only if Stage 12's cold-transpile profile attributes ≥20% of samples to fat-node construction and field defaults (`Node_init`, child-container allocation). If it runs, it lands before Stage 15. |
| D18 | **C-compatibility order** | **§5's order (ref:3265): C5 → C1 → C4 → C2 → C3.** C4 runs after C1 integrates, never alongside it, and its ASDL needs fold into Stage 15's schema commit. D5 applies to the C track. |
| D19 | **Constructs with no current consumer** | **Approve every row:** flexible array members, designated initializers and compound literals, variadic definitions, bitfields, `goto` and labels (Stage 20), multi-dimensional arrays (Stage 18), and C4 `#if`.<br><br>Their consumer is the Stage 14 probe battery plus C headers mined through the native header reader. This amends ref:3266–3267's consumer-need rule.<br><br>Rows 19–22 stay deliberate refusals, with tests (the comma operator outside `for` headers, reserved words, strict integer mixing, int-to-bool and returning a void expression). Row 24 (`_Atomic`, `_Complex`) stays documented as deferred. Row 23 (VLAs) is preserved and pinned. |
| D20 | **C semantic policies** | • **`_Bool`** is a spelling of `bool`. Implicit int-to-bool stays refused (row 22).<br>• **`auto`** is C11's storage class: accepted on block-scope objects as a no-op, refused at file scope and on parameters, and never type inference (`var` is).<br>• **`inline` under split compilation** follows C11: the inline definition sits in the shared declarations every unit sees, and exactly one owning unit emits the external definition. `static inline` stays unit-local.<br>• **Char arrays:** `char s[] = "abc"` and `char s[4] = "abc"` are accepted; the exact fit `char s[3] = "abc"` (no terminator) is refused with a targeted diagnostic.<br>• **Multiple declarators** use C binding: `*` and `[]` bind to each declarator, so `int *p, v;` makes `v` an `int`. Each declarator keeps its own initializer, its scope starts at its own declarator, and initializers run left to right.<br>• **Function-pointer disambiguation** follows C: `T (*name)(...)` is a declaration when `T` resolves to a type name in scope, and an expression otherwise.<br>• **`_Static_assert` on `sizeof`** is evaluated in the front end from btrc layouts, the hosted ABI and native-header layouts. With no known layout it is refused with a diagnostic naming the type. It is also emitted to C as a cross-check.<br>• **Adjacent literals** concatenate after source-macro expansion. An f-string next to another literal, or a native macro the front end cannot resolve to a string literal, is refused with a diagnostic.<br>• **An undefined identifier in `#if`** is an error naming it, not C's silent 0, unless it is a target predefined macro. `defined(X)` and `#ifdef` are the way to test for it. |
| D21 | **Platform choices** | • **Floors:** iOS 17 (simulator fallback per D8), API 29, Windows 11.<br>• **Toolchain:** the matrix pins the Xcode build number (27A266a), not nix. MinGW first; MSVC only if the arm64 wgpu-native build forces it.<br>• **Target spec:** a new `src/language` spec file generated into the existing generated modules, so the 88/100 file inventories do not change.<br>• **wgpu-native:** pinned prebuilt archives. |
| D22 | **Interop and service choices** | • **iOS:** generated Objective-C delegate adapters, shared with macOS.<br>• **Android:** a class-file reader over `android.jar` for JNI.<br>• **HTTP:** per-platform transports using the OS trust stores.<br>• **Windows regex:** a vendored POSIX regex. |
| D23 | **Linux toolkit** | **Run the GTK4 spike.** Adopt GTK4 for Linux UI4–UI8 if a btrc-hosted GTK4 window passes the UI1 shell journey with native controls, keyboard focus, IME and an AT-SPI tree. Otherwise use SDL plus an AT-SPI bridge, custom-drawn. |
| D24 | **UI API choices** | • Host-owned event loop.<br>• Reuse `UIEventKind` / `UISemantics`.<br>• A shim keeps index-based `ISelect` until BTRSmith re-pins.<br>• Reproductions land with their fix, with no xfail. A reproduction written before its fix stays on a branch and is recorded as failing in the catalog.<br>• Directory name `GUI/IOS`.<br>• `Raster`/`View` are classified as legacy.<br>• A versioned change to `ui.snapshot` is allowed. |
| D25 | **Product scope** | • **BTRSmith's PRD MVP stays macOS-only and unchanged.** The PRD gains a post-MVP cross-platform release section matching buckets 4–5: accessibility, Linux, Windows, iOS, iPadOS and Android.<br>• **The Player reference for #6** is `docs/product/PlayerScreenReference.png`, with deliberate deviations recorded in `PlayerConfiguration.md` and `UXConstants.md`. Correct musical geometry wins where the mock is wrong (HWW.md:51).<br>• **#13 (full-screen practice mode) is post-MVP.**<br>• **Skin art** outside Apple platforms: only owned or licensed assets ship; a platform without licensed art uses the procedural skin.<br>• **Mobile scope:** USB class-compliant audio input, yes. Plug-in hosting, no (a PRD exclusion). `btrsmithctl`/MCP stays desktop-only; mobile automation goes through the test channel.<br>• **The macOS MVP closure** stays in bucket 5 (D1). |
| D26 | **Bucket-5 budgets, formats and CI cost** | • **P6 no-op:** ≤5 s (ref:3351), plus platform-parity's reference private-body edit row in the P6 table.<br>• **Linux:** ship via Nix first.<br>• **Android:** APK and AAB.<br>• **BTRSmith CI:** Linux hosted runners on every push and PR; macOS only for tagged releases; the self-hosted runner only on the D7 host, if it exists.<br>• **No binary-cache account.** Cache btrcc with `actions/cache`, keyed on `flake.lock` and the btrc revision.<br>• **Budget:** BTRSmith CI stays within the account's included monthly minutes. Cost per run is measured, and triggers are adjusted to fit. |

### Standing approvals (every "you" step in the stages)

| Step in the stages | Resolution |
|---|---|
| Pushes, `ci/**` branches, pin bumps | D4. Every "blocked on push" step proceeds after its gate. |
| Closing issues (Stages 4, 9, 39, 40) | The agent posts the evidence and closes the issue once its acceptance is demonstrated, including #6's side-by-side visual review. Issues whose acceptance needs a listening approval or physical hardware (#4, #5, #21, #22, and Stage 40's records) stay open with the evidence posted. |
| Design and interface approvals (Stage 27's ownership plan; Stage 32's interface diff and `ui.snapshot` change; Stage 34's contract packets) | Approved when its two adversarial reviewers and the parity reviewer leave no unresolved blocking finding. The main session records the approval and the review files in this plan. |
| Stage 15's "≤0.3% or you explicitly accept more" | ≤0.3% passes. Up to 1% is accepted with the delta recorded. Above 1%, apply D17 or optimize before landing. |
| Stage 12's conditional tiers (borrowed returns, M9 arena, thread-confined ARC, M8b) | A tier runs when a Stage 12 profile attributes ≥5% of a still-open row's cost to what it removes (M8b uses D17's 20%). Otherwise it is declined, with the numbers recorded. |
| Parity exceptions | None. Anything that changes observable behavior is paired. |
| Quiet measurement rounds (Stages 5, 41 and the quiet queue) | The agent changes no system settings. Measurement workspaces live under `~/.cache/btrc/bench.noindex/` (Spotlight skips `*.noindex`). A round starts only when an automated check passes for 60 s: no agents, builds or guests running; podman stopped (the btrc machine only); `tmutil currentphase` is `BackupNotRunning`; Google Drive, `mds` and `mdworker` each under 5% CPU. Otherwise the round waits and retries, overnight preferred. Instructions retired and peak memory are the primary comparison (CLAUDE.md); wall-clock medians come from quiet runs. |
| Notarization and store submissions (Stage 42) | Recorded as declined (no Developer ID or store account exists). If an identity appears later, submitting is approved. |
| Physical sessions (Stage 40) | The agent builds the rig software, the latency program, the checklists and the per-platform scripts, then sends a push notification that the session is ready. The sessions themselves need you; until then they are recorded as **awaiting you**. |
| Agreements | Accepting the Android SDK licences is approved. No other agreement or account. |
| Signing | Commit unsigned rather than stall. |

## Corrections to the reference

The reference is frozen, so its stale or conflicting statements are corrected here (Stage 1, 2026-09-30). Where a correction and the reference disagree, the correction governs.

| Reference | Correction |
|---|---|
| **M11 status** (ref:4–30, ref:828, ref:2915–2918) | **Budgets met; acceptance counter open.** The self-host M11 budget numbers were met at `65057cb` (Status above). The acceptance counter, exactly one changed source group analyzed and lowered per body edit, is unmet; Stage 9 closes it. The header's "92 s edits" (ref:4–30, ref:1333–1339) and "next is the September 24 measurement round" (ref:828) are superseded by the Status section. |
| **Cold-dev working budget** (ref:6–7 says 13 s; ref:1102 says ≤13.5 s) | **The final cold-dev objective is ≥10× against the frozen repeated baseline and ≤min(20 s, baseline/10) (ref:1747), with a working budget of 13.5 s.** The header's 13 s is superseded. |
| **P6 build budgets** (ref:3347–3353 vs `platform-parity.md:494–501`) | One authoritative table, identical in both documents, below. The no-op row is ≤5 s on every platform (D26, matching the M6a closure), and the reference private-body edit row from platform-parity is added. |
| **Gating** (ref:842–844, ref:3269–3271) | Every-step gating is replaced by D5's batch gate. |
| **C-construct selection** (ref:3266–3267) | Replaced by D19: every row is approved, with the Stage 14 probe battery as consumer. |
| **x86_64 acceptance host** (ref:1724) | Governed by D7. |
| **Stale performance leads** | Python `_binding_conflicts_with_type` is already table lookups (`src/compiler/python/ir/lowering/calls.py:868`), so Stage 12 profiles it before treating it as a hotspot. M8a's lazy lists are done (`449d00c`); its ≤40 s cold-transpile target is still unmet (43.57 s at `65057cb`). |
| **CLAUDE.md handoff** | Updated in Stage 1: the structure-first "next" claim, the `GOAL.md` pointer (now BTRSmith issue #15), the 12,439/172 counts, the 309 boundary records and the skip bullet, plus the host capacity rules. |

**Authoritative P6 build budgets** (final self-host product builds after M6a/M11; identical in `docs/design/platform-parity.md`):

| Scenario | Windows | iOS/iPadOS | Android |
| --- | --- | --- | --- |
| Cold dev package, one architecture | ≤30 s | ≤45 s | ≤60 s |
| One private-body edit to installable dev artifact | ≤10 s; p95 ≤15 s | ≤15 s; p95 ≤20 s | ≤20 s; p95 ≤30 s |
| No-op through actual platform build driver | ≤5 s | ≤5 s | ≤5 s |
| Install/relaunch on already-running local test target, incremental artifact | ≤5 s | ≤15 s | ≤15 s |
| Cold reference-frontend dev package | ≤90 s | ≤120 s | ≤150 s |
| Reference private-body edit to installable artifact | ≤15 s | ≤20 s | ≤30 s |

**Lost evidence.** These 23 cited paths no longer exist; they were deleted before 2026-09-30 and cannot be recovered. Their numbers survive only as recorded in the reference and `compile-performance.md`:<br>`~/.cache/btrc/perf/artifact-execution-2026-09-21/`<br>`~/.cache/btrc/perf/directive-cache-2026-09-21/`<br>`~/.cache/btrc/perf/edit-cold-2026-09-22/summary.json`<br>`~/.cache/btrc/perf/emission-builds-2026-09-22/`<br>`~/.cache/btrc/perf/emission-owner-2026-09-22/bootstrap/results.json`<br>`~/.cache/btrc/perf/flow-owner-2026-09-22/results.json`<br>`~/.cache/btrc/perf/lowering-owner-2026-09-22/results.json`<br>`~/.cache/btrc/perf/native-fragment-2026-09-22/`<br>`~/.cache/btrc/perf/native-observation-2026-09-22/`<br>`~/.cache/btrc/perf/native-operation-2026-09-22/`<br>`~/.cache/btrc/perf/native-preparation-2026-09-22/`<br>`~/.cache/btrc/perf/native-receipt-profile-2026-09-21/`<br>`~/.cache/btrc/perf/native-validation-2026-09-21/`<br>`~/.cache/btrc/perf/operator-lookup-2026-09-21/`<br>`~/.cache/btrc/perf/scope-copy-2026-09-22/bootstrap/results.json`<br>`~/.cache/btrc/perf/scope-copy-builds-2026-09-22/`<br>`~/.cache/btrc/perf/scope-copy-final-2026-09-22/bootstrap/results.json`<br>`~/.cache/btrc/perf/selfhost-sdk-profile-2026-09-22/qualified/`<br>`~/.cache/btrc/perf/setjmp-builds-2026-09-22/`<br>`~/.cache/btrc/perf/setjmp-origin-2026-09-22/qualified/results.json`<br>`~/.cache/btrc/perf/source-resolution-2026-09-21/`<br>`~/.cache/btrc/perf/type-owner-2026-09-22/results.json`<br>`~/.cache/btrc/perf/vocabulary-identity-2026-09-21/`

Also lost, on 2026-09-30 during the Stage 1 reclaim: the regenerable test outputs under `~/.cache/btrsmith/build/tests` (30 GB) and `~/.cache/btrsmith/build/perf` (5.8 GB). A citation check found that 73 of the 259 notes in `~/.cache/btrsmith/build/evidence` cite run directories there, but the delete ran in the same command as the check, so it went ahead. The notes themselves are kept; the captures and logs they point at are gone, and no backup exists. The affected notes and paths are listed in `~/.cache/btrc/roadmap/lost-btrsmith-test-outputs.txt`. Stages 4, 39 and 40 regenerate every capture their exits need instead of citing these.

## Phase overview

| Stages | Bucket |
|---|---|
| 1–13 | 1 Compiler performance |
| 14–21 | 2 C compatibility |
| 22–29 | 3 Platform foundations (hardware-bound) |
| 30–37 | 4 Native UI (Stages 34–36 are pipelined) |
| 38–43 | 5 Qualification |

**What bounds progress:**
- the serial schema and interop chains
- the adversarial reviews that stand in for approvals (contracts, budget revisions)
- procurement
- quiet measurement windows
- integration throughput: merges, regeneration, boundary re-captures and bisects across 10–20 agents

**Where more lanes help.** Implementation-bound stages (16–19, 25, 28, 34–36) do get shorter with more lanes. Each stage therefore has **one integrator sub-agent** running the scripted merge-batch procedure below. The main session stays coordinator and gate runner.

Stages are numbered in the order they start. Stage 10 and Stages 34–36 overlap other stages on purpose. Read-only planning work may start one bucket early (see Stages 22, 27 and 30).

---

## Bucket 1: compiler performance

### Stage 1: Pre-flight (disk, capacity rules, hub clones, accurate docs, work in progress)
- **Goal.** Prepare the machine, the repositories and the documents for a long multi-agent campaign without losing evidence.
- **Items.**
  - `tooling-disk-reclaim`
  - `tooling-host-capacity-policy`
  - `btrsmith-wip-reconcile`
  - `perf-plan-refresh`
  - `qualification-plan-doc-reconcile`
  - `btrsmith-docs-reconcile`
- **Steps (serial, main session):**
  1. **Inventory.**
     - List the podman machines.
     - List the 35 cited `~/.cache` paths and mark which resolve.
     - List the unmerged branches and the `/private/tmp` worktrees.
  2. **Preserve, then delete** per the D2 allowlist.
  3. **Recreate the podman machine** (D2), after `podman machine list`.
  4. **Hub clones outside Drive.**
     - Create `~/.cache/btrc/hub.git` and `~/.cache/btrsmith/hub.git`.
     - Every agent worktree or clone is made from a hub. The integrator fetches finished batches into the Drive checkouts.
     - Apply the D3(b) branch dispositions, then run `git worktree prune`.
  5. **Locks and capacity rules.** Create `~/.cache/btrc/locks/{gate,bench,linux-ci,guest,gui-capture,signing}` plus a counting `btrcc-build` semaphore with N=2. Use `lockf`, or util-linux `flock` from nix, because macOS has no `flock`. The capacity policy goes into CLAUDE.md:
     - a RAM table
     - the load rules
     - an LRU prune of `build/test-btrcc` (keep the newest 20 plus pinned), run before every agent wave
     - BTRSmith clone caps
     - a free-disk check at the start of every stage
     - host provenance recorded as "Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0" in manifests and bench JSON
  6. **Docs, one commit** (the reference stays frozen; corrections go here):
     - **PLAN.md**, a "Corrections to the reference" section:
       - the M11 status: "budgets met; acceptance counter open"
       - 13 vs 13.5 s settled, with the final cold objective stated in this plan's terms
       - the P6 tables reconciled row by row with platform-parity.md (no-op and reference private-body edit)
       - the lost-evidence list for the 21 missing paths
       - the D5 gating amendment if approved
     - **CLAUDE.md** lines 14–40: the structure-first "next" claim, the GOAL.md pointer, 12,439/172, 309 boundary records, and the skip bullet.
  7. **BTRSmith docs** in the same pass.
- **Exit and gates.**
  - No currently-resolving cited path was removed, and the 21 already-missing paths are recorded in this plan as lost.
  - The measurement scripts exist outside `perf/`.
  - Free disk is recorded:
    - ≥80 GB is needed to continue.
    - ≥150 GB, or an SSD, is a Stage 23 prerequisite.
    - BTRSmith clones are capped at 1 until the podman shrink is done, and at 2 afterwards.
  - Hub clones and locks exist, and the capacity policy is in CLAUDE.md.
  - BTRSmith is clean (D3a), and the branch dispositions are recorded (D3b).
  - This plan, CLAUDE.md and platform-parity agree.
  - `git diff --check` and the hygiene check pass. This stage is docs-only, so no batch gate.
- **Depends on.** Your decisions D2, D3 and D5.
- **Parallelization: SERIAL in the main session.** It edits files the main session must read anyway, so two agents would cost more than they save.

### Stage 2: Baselines, CI health, evidence and skip ledgers
- **Goal.** Know exactly what is green before changing anything. Make gate results trustworthy, and make every skip visible, before the batched gates rely on them.
- **Items.**
  - `tooling-devshell-missing-tools`: naga, plus the lldb probe
  - `tooling-linux-container-refresh`
  - `tooling-ci-dispatch-policy`: now the `ci/**` push trigger
  - `qualification-ci-health`: includes deriving `source_count` in `test_corpus_strict_imports.py:177` instead of hard-coding 1246
  - `btrsmith-baseline`
  - `qualification-evidence-ledger`: one record format that also carries UI-catalog shard rows and P0 inventory rows
  - `qualification-skip-ledger`: local parts
  - **Only with D4 pushes:** pull `qualification-ci-macos-native-suite` forward from Stage 38. btrc is public, so its minutes are free.
- **Exit and gates.**
  - **Baseline.**
    - The code baseline is the `1cadaf4` record: `make test` 12,439 passed / 172 skipped, `test-c11` 8 × 1,934. `git diff 1cadaf4..429d2e0` is confirmed docs-only.
    - A fresh `make test-boundaries` log gives the record count (309 expected) and how many are checked inside nix.
    - No fresh baseline matrix is run. That slot goes to flake-rate reruns.
  - **Container and dev shell.**
    - `make linux-ci` is green on gcc 15.2 in the resized container, or its failures are filed.
    - `naga` runs in the dev shell, either from `wgpu-utils` (verified first ⚠) or from a new naga derivation, and the skips it caused are gone.
  - **BTRSmith.**
    - A table covers 2 frontends × {`05ec9cb` pinned (**qualifying**), `429d2e0` through a local override (**diagnostic only**)}.
    - One clone's disk footprint is measured.
  - **Flake rates and known failures.**
    - A flake-rate table built from `gh run list` history plus targeted repeats of suspect tests.
    - The daemon-deadline and Linux-audio failures are reproduced and fixed.
    - Windows failures are **blocked on push** until D4.
  - **Skip ledger.**
    - Ledger schema and statistics tests pass.
    - Every gate writes a skip report that classifies all 172 skips and records the environment variables gating each one (for example `BTRC_NATIVE_PROVIDER_CC`/`CXX`).
    - An injected unexpected skip fails the gate.
  - **Final gate.** One batch gate (D5 list) is green on the merged fixes, and its measured duration is recorded.
- **Depends on.** Stage 1, D4 (Windows and CI parts), D5.
- **Parallelization: WORKFLOW, in order.**
  0. **Serial first: 1 nix agent.** It owns `flake.nix`, `flake.lock` and `nix/*` until Stage 23, covering naga, the lldb probe, the container on gcc 15.2 and the devcontainer image. It lands before the fan-out, because a lock change changes the toolchain and invalidates every worktree's btrcc key. The container is the only heavy job while the VM is up.
  1. **Ledger agent.** Sole owner of `conftest.py`. It publishes the ledger schema first, then builds the skip collector.
  2. **Fan-out, each writer in its own worktree from the hub:**
     - the daemon-deadline agent
     - the Linux-audio agent, which queues for the container
     - the trigger agent: `ci/**` triggers plus a contract test
     - the Windows CI-health agent, which starts only after the first approved push
     - 2 manifest agents (Linux, macOS), which start after the ledger schema
     - 1 read-only reviewer, who checks that the format carries P0 and UI-catalog rows
     - the Makefile has one owner for this batch (the ledger agent)
  3. **BTRSmith baseline agent.** One clone. Reference and selfhost `source-check` run as 2 background jobs. `release-check` then runs serially: one window server, one GPU.
  4. **Load rule.** Until the daemon-deadline fix lands, only read-only agents run while any gate runs.
  5. **Integration.** The integrator runs the merge-batch procedure, then the main session runs the gate. Stage 4 wave-1 auditors may use this stage's gate windows.

### Stage 3: Measurement harness, peak guard, Linux-portable bench
- **Goal.** Make every open bucket-1 scenario measurable on both frontends, including the scaling workloads and worker sweeps, and guard the 35 MiB of peak headroom.
- **Items.**
  - `perf-harness`: also commits the preserved scripts into `tools/bench`
  - `perf-peak-guard`
  - `perf-linux-bench`
- **Exit and gates.**
  - `test_budget_bench.py` passes.
  - A dry run per scenario × frontend writes `report.json`. Scenarios:
    - interface-edit and instance-edit
    - batch and release
    - `--entry make` and `--timing-cold`
    - self-compile and the full corpus (ref:1792–1794)
    - a 1/2/4/8-worker sweep at fixed native jobs, with peak RSS (M10)
  - The peak guard trips on an injected allocation, and a census of retained bytes is in compile-performance.md (written by the integrator from JSON).
  - The container completes one scenario set with clean-build equivalence.
  - D10 is approved.
  - 1 batch gate, shareable with Stage 2's if both are ready.
- **Depends on.** Stage 1. It **overlaps Stage 2**, because the files are disjoint. Only the Linux rehearsal waits for the container.
- **Parallelization: WORKFLOW, 3 agents.**
  - **H:** sole owner of `tools/budget_bench.py`, in `wt/harness`. Does the harness, then the Linux bench.
  - **P:** the peak guard in `tools/bench`. Footprint measurements tolerate load, but never run them during a gate.
  - **R:** read-only. Proposes the 10 batch entry points.
  - The integrator merges, and the main session gates.

### Stage 4: Structure-first drift review, native-migration audit, BTRSmith pin bump
- **Goal.** Close the structure-first step CLAUDE.md calls load-bearing, and BTRSmith issue #20 (the remaining-native-code audit). Then re-pin BTRSmith, so the measured workload is final and measured only once.
- **Items.**
  - `btrsmith-structure-stdlib`
  - `btrsmith-structure-repo` (including #20)
  - `btrsmith-pin-bump`
- **Exit and gates.**
  - **Findings file.** The consolidator's ranked findings are tracked in a "Drift findings" section of BTRSmith `docs/NativePlatformPlan.md` and in `src/stdlib/README.md`. Every finding is closed or has a documented exception.
  - **stdlib.** Each of the 16 stdlib groups plus the root manifest (17 manifests) has a facade and a manifest, or a documented exception (GPU, Realtime). Naming and LSP-catalog tests pass.
  - **BTRSmith.**
    - native-source-check covers `*.swift`.
    - The #20 evidence is posted; you close the issue.
    - BTRSmith is pinned to the Stage-4 btrc commit, with byte-identical link plans and no new release-check failures against Stage 2's qualifying column. This pin is **blocked on push (D4)**.
  - **Gates.** btrc batch gates and a BTRSmith requalification.
- **Depends on.** Stages 2–3, D3 (blocking), D4 (for the pin), D6 (a)(b).
- **Parallelization: WORKFLOW.**
  - **Wave 1: read-only, about 23 agents in waves of at most 10, no worktrees.** Run during Stage 2/3 gate windows, never during a quiet round.
    - **9 btrc stdlib auditors, balanced by size:**
      - GUI portable plus FreeType
      - GUI/MacOS
      - GUI/Linux
      - root ×2 (27 files, about 8k lines)
      - UI + Tray + App
      - Audio + Realtime
      - FileSystem + BackgroundJobs + Daemon + LocalApplicationChannel
      - HTTP + Image + GPU + Digest + Graph + Terminal
    - **4 btrc repository auditors:** tests; tools; examples; nix plus docs.
    - **8 BTRSmith-area auditors.** One covers the remaining native code for #20.
    - **1 consolidating reviewer.** Removes duplicates, ranks findings and writes the findings file.
  - **Wave 2: serial.**
    - 1 btrc apply agent in its own worktree. Both compilers must resolve the changes. The integrator regenerates derived files, then 1 gate.
    - 1 BTRSmith apply agent in one clone. Renames ripple through imports and Make targets, so this cannot be split.
    - After the push: the pin bump and requalification. The 2 frontends run concurrently; GUI checks run serially.

### Stage 5: Quiet baseline measurement round
- **Goal.** Record every open bucket-1 scenario on an idle Mac on the final workload.
- **Items.** `perf-baseline-round`.
- **Before each quiet round:** the automated quiet check in the standing approvals passes for 60 s, and the workspace is under `~/.cache/btrc/bench.noindex/`. The agent changes no system settings.
- **Exit.**
  - 5 cold or 20 incremental samples per scenario, with median, p95 and max.
  - Raw logs under `~/.cache/btrc/bench/<run>`, naming the clang `-O2` btrcc, the SHAs and the host provenance.
  - **Both pins measured:** `aeeca0fd`, for continuity with the `65057cb` record, and the post-Stage-4 pin. Any M11 budget the new pin misses is a recorded finding before Stage 6.
  - Coverage:
    - the owner/worker split
    - cold release on both frontends
    - all reference scenarios
    - interface and instance edits
    - the product-Make no-op
    - the module-unit build at ≤110% of whole-program
    - **self-compile and full-corpus wall/RSS baselines**
    - **the 1/2/4/8-worker sweep with peak RSS**
  - The gap table in this plan's status section is updated.
- **Depends on.** Stage 4 wave 2 **and its pin bump** (so D4), and D9. The measurement itself runs overnight on the quiet machine.

  An overnight run before Stage 4 is allowed only as a labelled **pre-Stage-4 diagnostic**. It does not satisfy this stage.
- **Parallelization: SERIAL.**
  - Main session only. No agents of any kind, no gate, no guest. The NixOS remote agent also pauses its local activity.
  - After capture, a WORKFLOW of 4 read-only analysts attributes the logs: self-host cold, release, reference, and edits plus workers.

### Stage 6: Edit-floor spikes, Stage B key and journal spec, reference attribution, native track I
- **Goal.**
  - Find the real per-file-cache floor, which decides the resident-compiler question.
  - Specify the consulted-fact reuse keys **and the skip-unchanged journal** before Stage 9 implements them.
  - Attribute the reference compiler's unaccounted edit time.
  - Remove the relink and re-sign on product no-ops.
- **Items.**
  - `perf-floor-spikes`
  - `perf-ref-attribution`
  - `perf-signing-attest`
  - `perf-native-receipts`
  - The written key spec and journal spec for `perf-stageb-slice4` and `perf-stageb-skip-unchanged`
- **Exit and gates.**
  - **Spikes.** A table of per-lever instruction deltas, written as JSON; the integrator writes the separate-compilation.md table. It gives either a deliberately composed combined floor from one quiet wall-clock run, or the per-lever deltas reported as a non-additive estimate. It ends with a go/no-go on the resident compiler.
  - **Key and journal spec.** Reviewed. Every suspected unsound reuse is filed as a Stage 7 invalidation row.
  - **Reference.** At least 90% of reference time is attributed.
  - **Native.**
    - The product no-op does 0 links and 0 signings.
    - The native edit step is ≤1.4 s.
  - **Gate.** 1 batch gate.
- **Depends on.** Stage 5. **Then decide D11 and D12.**
- **Parallelization: WORKFLOW, about 13 agents.**
  - **5 spike agents**, in `wt/spike-{decl,parse,instances,records,visibility}`.
    - Each builds an uncommitted btrcc variant under the `btrcc-build` semaphore (N=2).
    - Each compares instructions retired at `--jobs 1`. That metric is valid here because these are single-thread algorithmic cuts.
    - Each saves a **patch**, never a commit.
  - **1 key/journal designer** (read-only) plus **4 read-only pass-family auditors**, who list every lookup each pass consults.
  - **2 adversarial reviewers**, who try to construct edits the spec would reuse unsoundly.
  - **1 Python agent** in `wt/ref-attr`.
  - **1 native-track agent**, sole owner of `native_plan.py`. Attestation first, then receipts and the natives spike, which is folded in here.
  - **Main session:** one quiet wall-clock run of the composed spike, then 1 gate.

### Stage 7: Correctness nets, M10 pool qualification, first cold-path cuts
- **Goal.**
  - Prove M11 correctness, including the new key-spec rows.
  - Give BTRSmith a regression oracle before dev mode switches to module units.
  - Qualify the worker pool against M10.
  - Land the first cold-path cuts toward M8a.
- **Items.**
  - `perf-m11-acceptance`
  - `btrsmith-portable-coverage`
  - `perf-setjmp-barriers`: **paired**, one commit
  - `perf-generic-temporaries`: **btrc-internal**. No observable output change; btrcc's emitted units are byte-identical to its own previous output. Precedent: `fcdbd6d`.
  - `perf-mimalloc`: btrc-internal
  - `perf-m10-pool-qualification`: added
- **Exit and gates.**
  - **M11 acceptance.**
    - Every acceptance row passes in both compilers.
    - The edit-sequence harness is green.
  - **Determinism matrix** (1/2/4/8 workers, 10 shuffled schedules, module-unit self-compile byte-stable). It lives in an **opt-in tier** like bootstrap, runs at batch and bucket exits, and is not part of `make test`.
  - **BTRSmith.** Every PortableCoverage.md row is covered on both frontends.
  - **setjmp.** `u-solve` is at least 40% faster at 4 workers.
  - **M8a, as ref:2720–2724 states it.**
    - At least 50% fewer empty child-container allocations.
    - Self-host peak ≤3 GiB.
    - Cold transpile ≤40 s on the BTRSmith workload.
    - Any miss is recorded as an explicit budget revision with evidence, and the remaining levers move to Stage 12.
  - **mimalloc.** An instruction table now; wall time and RSS from the quiet-window queue; then D15.
  - **M10 (ref:3042–3071).**
    - The worker table with peak RSS.
    - Either ≥1.5× wall speedup at 4 workers on the cold BTRSmith compile, or a revised pool default.
    - Hot-lock wait/hold counts and time.
    - A TSan run, or a recorded unavailability.
    - Real-thread stress of the stdlib concurrency contracts (contention, producer/consumer races, full/empty queues, shutdown while blocked, worker failure, exactly-once completion with managed payload destruction), composed in the M11a compiler fixture.
- **Depends on.** Stage 6.
- **Parallelization: WORKFLOW, about 19 agents, at most 5 writer worktrees.**
  - **Lane T, tests:**
    - 6 test authors share `wt/m11-tests` and one pinned `BTRC_TEST_BTRCC`. That is sound because they add test modules and fixtures only. Each owns one module: invalidation; corruption and interruption; concurrency and directories; native and sanitizer; dev/release switching; determinism tier.
    - **1 fixer** in its own worktree, serial per owning file.
    - **1 adversarial determinism reviewer.**
    - The integrator owns the `source_count` and fixture-list updates.
  - **Lane A, setjmp barriers.** First in the `ModuleUnits.btrc`/`modules.py` queue. A btrc agent and a Python agent work from one spec and land one commit.
  - **Lane D, generic temporaries.** 3 read-only caller-mutation auditors, then 1 btrc implementer.
  - **Lane M10.** 1 agent for the counters, TSan and stdlib stress. BackgroundJobs is a compiler import, so this lane builds its own btrcc and needs a bootstrap. The wall-clock sweep goes on the quiet queue.
  - **Lane B, BTRSmith.** 3 authors (PlayerPan; SharedGPUComposition; Library/Journey/Hover) in at most 1 clone before the podman shrink, 2 after. Runs share one serialized GUI queue and never run during a btrc gate.
  - **mimalloc.** 1 agent.
  - **Load rules.** At most one agent build beside `make test`, none beside `test-c11` or bootstrap.

### Stage 8: Reference compiler M11 budgets (Python track)
- **Goal.** Bring the reference compiler to its binding M11 budgets (D13), and record its distance from the finals.
- **Items.**
  - `perf-ref-frontend-cache`
  - `perf-ref-stageb`
  - `perf-ref-cold`, which includes the reference side's own generic-allocation work as a separate reference-budget item (not a "half" of Stage 7)
- **Exit and gates.**
  - Reference lex plus parse ≤3 s per edit, with identical canonical renders.
  - Verify mode passes on all 965 corpus programs and on BTRSmith. Units are byte-identical to the reference compiler's own pre-change output.
  - Edit ≤15 s median, ≤20 s p95.
  - Cold transpile ≤180 s and cold dev ≤210 s, with peak ≤2 GiB.
  - A table for 1/2/4 workers.
  - Distances to the reference finals recorded.
  - Gates: slices gated in pairs under D5.
- **Depends on.** Stage 6. It overlaps Stage 7, except on `modules.py`, where the setjmp Python half lands first.
- **Parallelization: WORKFLOW, about 12 agents.**
  1. In parallel: **F** (frontend cache, `wt/ref-fe`) and **S0** (shared positions and codec, serial).
  2. **3 slice agents** in `wt/ref-{validation,generics,realtime}`.
     - They write **only** codecs and replay in the owning analyzer modules (for example `analyzer/generics.py`, `analyzer/realtime.py` and the validation owner).
     - **One `modules.py` owner** wires all the slices, in order.
     - Each slice gets 2 adversarial reviewers: one runs verify mode and diffs against clean builds; one cross-reads btrcc's `ValidationRecordCodec`.
  3. One serial cProfile, then 2–3 agents on the reference cold path, one per hotspot module.

### Stage 9: Stage B completion and M11 closure on the Mac
- **Goal.** Finish what M11 itself requires: consulted-fact keys, **skipping analysis and lowering of unchanged groups**, the batch, cold release and product integration.
- **Items.**
  - **9a:**
    - `perf-stageb-slice4`
    - `perf-stageb-skip-unchanged`, moved here from Stage 11 because ref:2846–2848 and ref:2915–2918 make it an M11 acceptance requirement
  - **9b:**
    - `perf-batch-10`
    - `btrsmith-test-batch`
    - `perf-cold-release`
    - `perf-product-integration`
    - `btrsmith-dev-mode`
- **Exit and gates.**
  - **The Stage B counter.** For each fixed body-edit fixture, in both compilers:
    - exactly **one** changed source group is analyzed and lowered
    - **no** unchanged group is re-lowered
    - only dependency-justified native compiles happen, plus one link
    - shared specialization or registration changes are counted and explained
  - **Fall-back.** It goes to full analysis when a journal is missing or incomplete, is visible in the counters, and is green in the edit-sequence harness.
  - **Edits.** An instance edit relowers only the edited and template groups. An interface edit costs ≤110% of a clean build.
  - **Batch.** ≤60 s self-host and ≤120 s reference, with shared reuse proven by counters.
  - **Cold release.** ≤90 s, within the runtime guardrail.
  - **Product.**
    - Product-Make medians are within 5% of `budget_bench`.
    - Dev and release suites pass without a clean between them.
    - Evidence is posted on issue #1; you close it.
    - The BTRSmith dev-mode pin is **blocked on push (D4)**.
  - **Every M11 KPI row and the acceptance counter are met on the Mac.**
  - **Gates.** Batch gates plus a BTRSmith requalification.
- **Depends on.** Stages 7–8, D15. Then decide D16.
- **Parallelization: WORKFLOW, about 12 agents. All Stage B work is paired, one commit per step.**
  1. **Slice 4.** A btrc agent and a Python agent implement the Stage 6 key spec. 2 adversarial reviewers re-run the invalidation table.
  2. **Skip-unchanged.** The same pair implements the Stage 6 journal, with the edit-sequence harness and the fall-back. 2 adversarial reviewers try to break it. The journal spec is **frozen** here. Any later memo cache (Stage 12) must extend it.
  3. **Batch, after slice 4 merges.** 3 agents: btrc emitter and keys; Python emitter and keys; manifest. The BTRSmith Make-graph owner does `btrsmith-test-batch` in parallel.
  4. **Cold release.** 2 agents: the emitter pair; LTO by the native owner.
  5. **Finally.** 1 cross-repository agent does product integration and then dev mode, serially.

### Stage 10: x86_64 NixOS acceptance host (remote lane, starts whenever the host exists)
- **Items.**
  - `tooling-x86-acceptance-host`
  - `qualification-acceptance-hosts`
  - `perf-nixos-acceptance`
- **Exit.**
  - The FRACTAL-NORTH probe (or the replacement hardware) meets the spec.
  - Host and Mac manifests are committed and embedded in `budget_bench` JSON.
  - An early baseline at the Stage-5 SHA.
  - **The frozen baseline compiler is re-measured on the host with repeats**, so the ≥10× ratio can be computed there.
  - A separate Linux table.
  - **Stdlib concurrency contracts are qualified with real threads on the host** (M10).
  - Gates are green on the host at the bucket-1 exit.
- **Depends on.** D7, Stage 3. Measurement continues across the rest of bucket 1.
- **Parallelization: 1 remote agent over ssh.**
  - This is real machine-level parallelism.
  - Measurements on the host are serial.
  - During Mac quiet windows the local agent process pauses, while the host keeps measuring on its own.
  - It repeats at Stages 9 and 13.
  - A btrc self-hosted runner needs your explicit approval and runs only on push events, because btrc is public. A BTRSmith runner is safe (Stage 38).

### Stage 11: Bounded final push A, the edit path (D11)
- **Items.** Final ≤5 s edit and cold-dev objective:
  - `perf-records-pack` (paired)
  - `perf-frontend-durable` (paired)
  - `perf-decl-session-cache` (paired)
  - `perf-parse-cache` (btrc-internal; the Python equivalent is Stage 8's frontend cache)
  - `perf-native-link` and `perf-cold-native` (shared `native_plan.py`, one commit)
  - `perf-resident-compiler`: only if D12 says go; paired or a recorded parity exception
- **Exit and gates.**
  - Records plus `g-transitive` ≤0.4 s (from 1.42 s).
  - Visibility plus `n-import` ≤0.15 s, and no-op ≤1.0 s.
  - Declarations session ≤0.2 s, verified against live lowering.
  - Lex plus parse ≤0.3 s, or a recorded no-go.
  - All `a-*`/`g-*`/`v-*`/`c-*`/`r-*` phases ≤0.5 s.
  - Edit link ≤0.2 s, with `test-debug` passing.
  - Cold native ≤8 s.
  - Each compiler's units byte-identical to its own output, verify gates passing, and the bootstrap fixed point holding.
  - A quiet re-measure after each batch.
- **Parallelization: WORKFLOW, about 12 agents, at most 4 writer worktrees (6 after the podman shrink).**
  - **Lane Q, the serial queue on `ModuleUnits.btrc` and `modules.py`.**
    1. Records pack.
    2. Declaration-session cache: 2 codec agents from one schema note, then 1 wiring agent.
    - Before each is implemented, 2 adversarial reviewers add invalidation rows.
  - **Lane F, front end.**
    - First, serially, a durable cache-store API (`frontend/Models.btrc`, `cli/Driver.btrc`, `artifacts/cache.py`, `BTRC_CACHE_DIR`).
    - Then 2 agents: Visibility with `imports.py`; NativeImports with `native_imports.py`.
    - Then a parse-cache decoder prototype (go/no-go), then 2 agents.
  - **Lane N, native.** Link, then cold native.
  - **Resident compiler** (if approved). 1 design agent, then a serial core plus 1 protocol-and-tests agent. Its wall clock is measured on the quiet queue.

### Stage 12: Bounded final push B, cold path and memory (conditional tiers)
- **Items.**
  - `perf-decl-lowering-hotspots`
  - `perf-parallel-analysis`: changes observable build behavior, so it is **paired**, or you record a parity exception
  - Only on evidence and your approval: `perf-borrowed-returns`, `perf-m9-arena`, `perf-arc-thread-confined`, `perf-m8b`
- **Exit.**
  - Each hotspot cut saves at least 1% and is **recorded in the frozen Stage 9 journal**. Rejected cuts are recorded with numbers.
  - Cold transpile ≤25 s at 4 workers (wall clock, quiet window), aggregate memory ≤6 GiB, and identical output across workers and shuffles.
  - M8a is closed if Stage 7 left it open.
  - Each conditional tier meets its own exit, or is declined with your sign-off.
  - **M8b finishes or is declined before Stage 15.**
- **Parallelization: WORKFLOW. Implementation fans out; measurement is serial on the quiet queue.**
  - **Hotspots.** They land after Stage 9 froze the journal, never interleaved with journal work. 1 serial profile, then 4 agents with exact paths:
    - `ir/lowering/Calls.btrc` (`CallTargetResolver.resolve`)
    - `ir/lowering/CallableFlow.btrc` (`CallableFlowState.applyEvaluation`)
    - `ir/lowering/Callables.btrc` (`CallableValueSemantics.expressionAbi`)
    - `analyzer/ownership/Cycles.btrc` (`CycleSemantics.reaches`)
    - plus the Python `ir/lowering/calls.py` (`_binding_conflicts_with_type`)

    Every memo needs an adversarial reviewer's sign-off that its lookups are journaled.
  - **Parallel analysis**, after Lane Q drains:
    - a serial protocol core
    - 3–4 read-only journal-completeness auditors
    - 2 test authors sharing one worktree
    - the btrc and Python halves landing in one commit
  - **Each conditional tier.** 1 design agent, then 4 read-only auditors, then serial implementation by a btrc/Python pair. `runtime/c` has a single owner. Allocator, arena, ARC and parallelism effects are measured only in quiet windows.
  - **M8b only.** After a serial vertical slice, 4 agents work by package directory, using renamed readers as the compile-error oracle, and merge serially.

### Stage 13: Bucket-1 exit qualification
- **Items.** `perf-final-qualification`.
- **Exit.**
  - **This plan's bucket-1 row is marked done.** The Mac and NixOS tables cite **each** row as met or explicitly revised with evidence:
    - all self-host and reference final rows listed in D11
    - M8a, and the M10 table
    - the ≥10× ratio against the frozen baseline on each required host
    - self-compile and full-corpus median wall/RSS within 5% of Stage 5's baselines, or an explained tradeoff
  - **Full gates on the final SHA.** The full D5 list, including the Mac's own `test-c11` and the determinism tier.
  - **BTRSmith.** `application-frontend-check` and the library smoke pass on both frontends.
- **Parallelization: SERIAL.**
  - The Mac gate chain runs strictly in sequence.
  - The NixOS agent runs on its own machine.
  - 1 docs agent drafts tables from JSON while the gates run.

## Bucket 2: C compatibility

D5 amends §5's every-step gating for this bucket. Both compilers still land in one commit per construct, and the boundary fixtures for `surface.python.tokens`/`surface.python.ast` are reviewed in every batch.

### Stage 14: C5 inventory first (probe battery, deliberate refusals, VLA audit)
- **Items.**
  - `ccompat-c5-baseline`
  - `ccompat-refusal-policy`
  - `ccompat-r23-vla-audit`
- **Exit.**
  - **Inventory test.** `test_c_compatibility_inventory.py` passes through both the Python compiler and the cached btrcc.
    - Every row and every extra gap has a positive and a negative program.
    - Known divergences are explicit: the flexible-array lowering, and the misleading designated-initializer diagnostic.
  - **Refusals.** Rows 20, 22 and 24 give identical targeted diagnostics in both compilers. The constructs D19 refuses get the same treatment.
  - **VLA.** VLA forms are pinned and documented.
- **Depends on.** Stage 13, D18, D19.
- **Parallelization: WORKFLOW, 7 agents.**
  - 4 authors share `wt/ccompat-inventory`, each owning one manifest (c1, c2, c3_c4, c5). They use in-process Python probes plus the pinned btrcc and make no compiler edits.
  - 1 assembler writes the pytest driver.
  - 1 refusal agent changes diagnostic paths only and merges before any C1 parser lane.
  - 1 VLA agent writes tests and docs.
  - The integrator owns the count and fixture-list updates.

### Stage 15: C1 schema commit
- **Items.** `ccompat-c1-schema`, plus C4's ASDL needs if D18 approves C4.
- **Exit.**
  - The generated-source check is clean.
  - Boundary records are accepted with reasons.
  - The BTRSmith self-host peak and instruction delta is ≤0.3%, or you explicitly accept more. If the peak guard trips, land M8b first (if approved) or record a budget revision.
  - 1 gate.
- **Depends on.** Stage 14, D17, D20.
- **Parallelization: SERIAL.**
  - The main session is the only owner of `ast.asdl`, the generated files, the `Identity.btrc` renderer, `AstJsonCodec` and the boundary records.
  - Beforehand, 2 read-only adversarial design reviewers critique options (a) through (f).

### Stage 16: C1 constructs, then C4 (approved, D19)
- **Items.**
  - `ccompat-r02-braceless-bodies` and `ccompat-r06-empty-statement` (first)
  - `ccompat-r01-void-unnamed-params`
  - `ccompat-r05-adjacent-strings`
  - `ccompat-r04-char-array-string-init`
  - `ccompat-r03-multi-declarators`
  - `ccompat-r19-comma-operator` (moved here from Stage 21)
  - `ccompat-r07-function-pointer-declarators`
  - `ccompat-c1-integrate`
  - `ccompat-r18-preprocessor-conditionals` (C4, only if approved; after C1 integrates)
- **Exit.**
  - Every C1 row is PASS in both compilers.
  - Raw IR is identical for braced and braceless bodies.
  - ARC behavior is proven per declarator.
  - Negative diagnostics match.
  - Strict C11 holds under gcc and clang at `-O0` to `-O3` (by the gate).
  - Batch gates, plus a BTRSmith rerun.
  - **If C4 is in:**
    - live branch selection per target is identical in both compilers
    - a dead-branch import adds no edge
    - cache keys invalidate correctly
    - a quiet M11 re-measure shows no regression
- **Depends on.** Stage 15. C4 follows only if approved (D18, D19).
- **Parallelization: WORKFLOW, a serial first step, then 3 lanes.**
  1. **Serial.** r02 and r06 land as one shared `_parse_body` helper used by `_parse_for_stmt`, `_parse_if_stmt` and `_parse_while_stmt`, in both compilers.
  2. **Lanes.** Each does Python first, then the btrc port by the same agent in the same commit. Each lane builds its own btrcc under the semaphore.
     - `wt/c1-decl`: r01, then r03, then r19, then r07, plus 1 read-only agent mining C headers.
     - `wt/c1-lit`: r05.
     - `wt/c1-sem`: r04.
  3. **Merge order:** refusal, r02/r06, r01, r05, r04, r03, r19, r07.
  4. **1 parity reviewer per construct** (semantics, diagnostics, ARC witnesses), reusing the lane's btrcc. C11 strictness is left to the gate.
  5. **C4 (if approved), after `ccompat-c1-integrate`:**
     - spec and codegen, the only writer of the hosted-ABI generator
     - the Python evaluator
     - the btrc port
     - cache fingerprints plus a quiet re-measure

     iOS and Android macros are deferred to Stage 24.

### Stage 17: C2 aggregates
- **Items.**
  - `ccompat-c2-schema`
  - `ccompat-r09-union-declarations`
  - `ccompat-r08-typedef-struct-anonymous-members`
  - `ccompat-r10-designated-init-compound-literals`
  - `ccompat-r13-flexible-array-members`
  - `ccompat-x-enum-tag-spelling`
  - `ccompat-r12-bitfields` (only if D19 names a consumer; otherwise a documented refusal)
  - `ccompat-c2-integrate`
- **Exit.**
  - Approved C2 rows are PASS.
  - `sizeof` and `offsetof` match gcc and clang.
  - The flexible-array divergence and the misleading `{[2]=7}` diagnostic are gone.
  - If bitfields land, no `&` is ever taken of one.
  - The memory delta is recorded.
- **Parallelization: WORKFLOW.**
  - 3 read-only spec drafters: unions, anonymous members and designators; flexible arrays; bitfields (if approved).
  - Then the serial schema commit, with 2 reviewers.
  - Then 2 lanes, because they share `ir/lowering/Aggregates.btrc`, Types and struct parsing:
    - **L1:** r09, then r08, then r10.
    - **L2:** r13, then the enum-tag fix, then r12 if approved.
  - Merge order: r09, r08, r13, enum, r10, r12.
  - 1 parity reviewer per construct.

### Stage 18: Multi-dimensional arrays, alone (approved, D19)
- **Items.** `ccompat-r17-multidimensional-arrays`.
- **Exit.**
  - A 2D corpus passes through both compilers under strict C11, and the pinned rejection tests are inverted.
  - If declined: a documented refusal is added in Stage 21.
- **Parallelization: SERIAL first, then 2 lanes.**
  - The type representation and analyzer, then storage lowering, run serially on one branch.
  - After the representation lands, the GPU and the collections/iteration steps run in parallel, because their files are disjoint.
  - 2 reviewers.

### Stage 19: C3 vocabulary and specifier lanes
- **Items.**
  - `ccompat-c3-schema-vocabulary`
  - `ccompat-r15a-qualifiers-storage-classes`
  - `ccompat-r15b-inline-noreturn`
  - `ccompat-r15c-static-assert`
  - `ccompat-r15d-alignment`
  - `ccompat-r16-wide-literals-long-double`
  - `ccompat-x-expression-stragglers`
  - `ccompat-r14-variadic-definitions` (only if D19 names a consumer)
  - `ccompat-c3-integrate`
- **Exit.**
  - Token vocabulary validates in both compilers, and the extension and LSP tests pass.
  - Approved rows are PASS.
  - `static inline` works under `--module-units`.
- **Parallelization: WORKFLOW.**
  - **Serial vocabulary commit first.** 1 owner for the grammar's lexical section, ASDL, `hosted_abi.toml`, `intrinsic_effects.toml` (the `va_*` intrinsics) and the VS Code grammar. Plus 1 read-only pre-drafter and 2 reviewers.
  - **Then lanes, at most 4 writers:**
    - r15b
    - r15c, plus a constant-evaluator parity reviewer
    - r15d
    - r16 then the stragglers, by one agent (shared lexer)
    - r15a in the declarator lane
    - r14 if approved
  - **Merge order:** r15b, r15c, r15d, r16, stragglers, r15a, then r14 as its own batch.

### Stage 20: goto and labels, alone (approved, D19)
- **Items.** `ccompat-r11-goto-labels`. `goto` is already a keyword (grammar.ebnf:38).
- **Exit.**
  - Every unsafe-path negative test gives identical diagnostics.
  - Positive cleanup programs are clean under the ARC witness.
  - If declined: a documented refusal in Stage 21.
- **Overlap.** It may **overlap Stage 19's r15c/r15d/r16 lanes**, rebasing after r15b (`_Noreturn` flow).
- **Parallelization: SERIAL implementation.**
  - 2 read-only agents first: one gathers unsafe-path fixtures, reusing Stage 14's VLA cases; one drafts the Python contract.
  - Then 1 implementer, Python first and then btrc.
  - 2 adversarial reviewers: ARC, and setjmp.

### Stage 21: C5 close-out
- **Items.**
  - `ccompat-c5-docs-final`
  - `btrsmith-c-compat-regression`. It also runs in the background after Stages 16, 17, 19 and 20. Each pin is **blocked on push**.
- **Exit.**
  - Every row is PASS or deliberately refused, with a test in both compilers. No known divergence remains.
  - The final bucket-2 matrix is green, including the Mac's `test-c11`.
  - This plan and MEMORY are updated.
- **Parallelization: Mostly SERIAL.** 1 docs agent drafts while the main session runs the exit gate.

## Bucket 3: cross-platform foundations

Lane parallelism in this bucket depends on D6(c). Without it, one bounded contract is in flight at a time.

### Stage 22: P0 entry, parity inventory, adaptations, toolchain matrix, device registry
- **Items.**
  - `platforms-p0-entry-baseline`
  - `platforms-p0-inventory`
  - `btrsmith-p0-inventory`
  - `platforms-p0-adaptations`
  - `platforms-p0-matrix-pin` and `tooling-p0-toolchain-matrix`, done as one unit
  - `qualification-device-lab`
- **Exit.**
  - The entry gate log is recorded.
  - The inventory TOML covers 100% of rows × 6 slices, in the Stage 2 ledger format, and its verifier is in `make test`.
  - Adaptations are approved.
  - The toolchain matrix is pinned with sources. Xcode is pinned by build number.
  - Every physical gate maps to a named device or to "unavailable".
- **Overlap.** The read-only inventory work, a planning artifact, **may start during bucket 2's gate windows**.
- **Parallelization: SERIAL entry gate, then a read-only WORKFLOW of about 23 agents in waves of at most 10.**
  - 9 stdlib auditors, using Stage 4's balanced split (16 groups plus the root, 17 manifests).
  - 1 runtime-manifest agent, 2 corpus-topic agents, 6 BTRSmith product-area agents.
  - 3 toolchain-research agents (Apple, Android, Windows) and 1 device-registry drafter.
  - 3 adaptation drafters, one per platform; you review them.
  - 1 integrator writes the TOML and the verifier.

### Stage 23: P1 provisioning (toolchains, simulators, SDK, VM, signing, devices)
- **Items.**
  - `platforms-p1-toolchains`
  - `tooling-ios-simulator-runtimes`
  - `tooling-android-sdk-ndk`
  - `tooling-windows-vm`
  - `tooling-windows-ci-arm64-llvm`
  - `tooling-apple-signing`
  - `qualification-signing-accounts`
  - `tooling-ios-physical-devices`
  - `tooling-android-physical-devices`
- **Prerequisites (D8).**
  - ≥150 GB free or an external SSD.
  - Android SDK licences accepted by you.
  - Re-check free disk before each download.
- **Exit.**
  - The pinned NDK (29.0.14206865), SDK, a JDK and zig 0.16.0 are available in `nix develop`. There is no JDK or adb today.
  - The iOS SDK comes from host Xcode 27A266a, recorded in the matrix.
  - API 29, current and 16 KiB AVDs boot.
  - The current iOS simulator runtime launches a C11 app. The iOS 17 runtime launches one too, or is recorded as uninstallable under Xcode 27 ⚠.
  - `ssh winvm` runs a cross-built btrcc on the **ARM64** VM. Under Prism, x64 is not native evidence. Native x64 evidence comes only from CI or the D7 dual-boot.
  - Pushed `ci/**` Windows x64 and ARM64 bootstraps pass. This is **blocked on push (D4)**.
  - Signing identities and paired devices are listed, or recorded as unavailable.
- **Bound by** your purchases and licence acceptance. Non-code provisioning may begin during bucket 2 if the disk allows.
- **Parallelization: WORKFLOW, 5 agents.**
  - 1 nix owner (flake files).
  - 3 background provisioning agents (iOS runtimes, Android SDK and AVDs, Windows 11 ARM VM), running concurrently only with ≥60 GB of headroom.
  - 1 workflow agent (arm64 job plus LLVM).
  - **RAM rule.** At most the 8 GiB VM plus one 4 GiB emulator at once, and none during bootstrap.
  - After this stage, each device has one device-owner agent and one queue.

### Stage 24: P1 shared target contract
- **Items.**
  - `platforms-p1-target-spec`
  - `platforms-p1-hosted-abi-targets`
  - `platforms-p1-native-import-targets`
  - `platforms-p1-native-plan-toolchain`
  - `platforms-p1-provider-filters`
  - `platforms-p1-cache-identity`
  - `platforms-p1-abi-fixture`
- **Exit.**
  - Both frontends accept and reject the same target set, proven by a parity test.
  - Existing spellings still round-trip.
  - Real header extraction works for 5 new triples.
  - Link-plan schema v5 output is byte-identical across frontends.
  - The provider matrix shows zero foreign SDK imports.
  - The cache-poisoning matrix is green, and a quiet M11 re-measure shows no regression.
  - C4's iOS and Android rows are added if C4 landed.
- **Depends on.** D21.
- **Parallelization: SERIAL spec, then a WORKFLOW of about 14 agents, at most 4 writers.**
  - **Spec.** 1 design agent plus 2 adversarial reviewers (Python/btrc parity including host inference; per-platform triple and sysroot rules).
  - **Fan-out:**
    - 2 consumer writers (Python, btrc) and 1 parity-test author
    - 3 read-only extractors (iOS SDK, NDK bionic, MinGW) and 1 integrator, the only writer of `hosted_abi.toml`
    - an importer pair (Python, btrc)
    - the native-plan owner plus 1 test agent working against the frozen v5 schema
    - 1 provider-filter writer
    - 1 ABI-fixture author
  - **Last.** Cache identity, by a single owner, then the quiet re-measure.
  - **Gates by sub-batch:** spec; ABI names; importers plus native plan; filters plus cache.

### Stage 25: P1 test hosts and P2 runtime parity
- **Items.**
  - `platforms-p1-host-windows`, `platforms-p1-host-ios`, `platforms-p1-host-android`
  - `platforms-p2-target-probes`, `platforms-p2-target-runner`, `platforms-p2-runtime-semantics`, `platforms-p2-portable-corpus`, `platforms-p2-ci-lanes`
  - `tooling-android-ci-emulator`
- **Exit.**
  - The ABI fixture runs on every host.
  - Probes are correct regardless of working directory, and the macOS/Linux goldens are unchanged.
  - The runtime boundary re-capture is approved (D14).
  - Per-target pass/restricted/missing counts are reported.
  - 100% of the applicable corpus passes on each target.
  - CI lanes are green (blocked on push for Windows).
- **Parallelization: WORKFLOW, about 22 agents.**
  - **Host lanes.** 3, each owning its own `tools/` subdirectory.
  - **Probes.** Serial, because `runtime/c` and its manifest have a single owner. The runner core is serial, then 3 executor adapters.
  - **Execution, separate from triage.** One runner per target runs the whole applicable corpus once, serially on its device queue, and writes logs. Then the read-only triage agents fan out over those logs, by target × topic, in waves of 10.
  - **Runtime triage.** 3 read-mostly agents. Every runtime fix goes through the single owner.
  - **Fixes.** 3 worktrees split by owner (`runtime/c`; stdlib; compiler with both halves), merged serially.
  - **CI.** 3 agents.
  - At most 1 emulator during a gate.

### Stage 26: P3 OS services
- **Items.**
  - `platforms-p3-windows-launch-seam`
  - `platforms-p3-fs-windows`
  - `platforms-p3-process-terminal`
  - `platforms-p3-sockets-http`
  - `platforms-p3-regex-glob`
  - `platforms-p3-fs-mobile`
  - `platforms-p3-jobs-ipc`
- **Exit.**
  - Windows argv, timeout and tree-kill tests pass.
  - Junction-swap, long-path and UNC-path tests pass.
  - The HTTP corpus passes with no `curl` on PATH.
  - Regex behaves the same on all slices.
  - Channel and job tests pass on Windows; mobile has tests or declared restrictions.
- **Depends on.** D22.
- **Parallelization: SERIAL launch seam, then a WORKFLOW of 4 writers.**
  - The `runtime/c` owner does the launch seam first.
  - Then 4 writers on disjoint stdlib files: Windows filesystem; process/terminal; sockets/HTTP (after its interface freezes, 3 sub-agents for WinHTTP, NSURLSession and Android); regex/glob.
  - **FileSystem, Process and BackgroundJobs are compiler imports.** Those lanes build their own btrcc and need a bootstrap. The other lanes pin the integrator's btrcc.
  - Then the mobile filesystem, after the `FileSystem.btrc` merge.
  - Then 2 agents for jobs and IPC.
  - Windows evidence is batched on the VM or in CI.

### Stage 27: W1 Windows host and interop lane I (one ownership design, function tables, early Objective-C and JNI slices, then COM)
- **Items.**
  - `platforms-interop-function-table-calls`
  - `platforms-w1-win32-com-imports`
  - `platforms-w1-sdk-reader-provider`
  - `platforms-w1-worker-pools`
  - `platforms-w1-unicode-host`
  - `platforms-w1-ci-and-bundle`
  - `qualification-ci-windows-matrix`
  - The **first slices** of `platforms-i1-objc-protocol-adapters` and `platforms-a1-checked-jni`, both still mapped to Stage 29
- **Why this order.** platform-parity §8 orders P2/P3/P4 → W1. This stage starts W1 before P4, because W1's listed dependencies are only P1–P3 and the interop lane is the long pole. platform-parity.md:590–593 also requires the mobile bridges to be proven early.
- **Exit.**
  - The vtable fixture passes at `-O2` and under sanitizers.
  - A **checked** Objective-C delegate makes one round trip on macOS and the iOS simulator test host.
  - A **checked** JNI call makes one round trip on the emulator test host.
  - A real COM round trip shows exact release counts.
  - A native Windows btrcc imports Win32 headers.
  - Parallel and serial builds produce identical output.
  - A PowerShell build works from a non-ASCII path with spaces.
  - 10 consecutive green Windows runs on x64 and ARM64, including bootstrap. This is **blocked on push**.
  - A bootstrap for each interop feature.
  - **W1 stays open** until Stage 28's ABI-route decision.
- **Depends on.** D4, D6(c).
- **Parallelization: a WORKFLOW design step, then a SERIAL interop lane.**
  - **Design step 0.** Read-only; may run during bucket 2 gate windows.
    - 5 agents, one per foreign ownership model: C function tables, COM, Objective-C protocols and blocks, JNI references, GObject floating references.
    - 1 designer writes a single `native_abi.asdl` extension plan.
    - 2 adversarial reviewers, then your approval.
    - Stages 29 and 31 implement this same plan.
  - **Interop lane.** 1 owner for the ASDL, both importers and lowering. Order: function tables, then the Objective-C slice, then the JNI slice, then COM. A mirror agent ports each feature to btrc, and 1 fixture author supports.
  - **In parallel:**
    - SDK-reader and worker-pool agents; the integrator merges `WindowsMain.btrc`
    - the Unicode-host agent, after Stage 26's Windows filesystem work
    - 3 CI agents, each in its own reusable workflow file

### Stage 28: P4 dependency closure and library artifacts (W1 exit)
- **Items.**
  - `platforms-p4-dependency-crossbuild` and `btrsmith-package-closure`, as one unit
  - `tooling-cross-gpu-deps`
  - `platforms-w1-toolchain-abi-route`
  - `platforms-p4-library-artifacts`
  - `platforms-p4-assets-streams-plugins`
  - `platforms-p4-package-contracts`
  - `btrsmith-cross-target-build`
- **Exit.**
  - A manifest with hash and licence per dependency × ABI, and every library links into the fixture.
  - The ABI-route decision is recorded, which **closes W1**.
  - A library artifact rebuilds incrementally.
  - Package suites pass per ABI on both frontends.
  - A BTRSmith launch artifact exists for every target, with host builds byte-identical to before. The pin is blocked on push.
- **Parallelization: WORKFLOW, about 25 agents, at most 4 builders at once (disk).**
  - **Dependencies.** 1 agent per dependency (about 10), each building all 6 slices in `~/.cache/btrc/xbuild/<dep>`. `psarc` and `sloppak` start after `zlib`, `miniz` and `yaml`.
  - **GPU dependencies.** 3 per-target agents, then the nix owner merges.
  - **ABI route.** 1 research agent.
  - **Library artifacts.** Serial, by the `native_plan` owner.
  - **Assets.** 2 agents.
  - **Package contracts.** 8 agents, one per package.
  - **BTRSmith.** The `Config.mk` abstraction is serial, then 3 per-target packaging agents.
  - Lock-file merges are serial, by the integrator.

### Stage 29: Non-UI platform tracks and interop lane II (Objective-C protocols, then JNI)
- **Items.**
  - **W2:** `platforms-w2-arm64`, `platforms-w2-wasapi`, `platforms-w2-gpu-image-font`, `platforms-w2-packaging`
  - **I1:** `platforms-i1-objc-protocol-adapters`, `platforms-i1-app-lifecycle`, `platforms-i1-sandbox-storage`
  - **I2:** `platforms-i2-audio`, `platforms-i2-gpu`, `platforms-i2-app-packaging`
  - **A1:** `platforms-a1-checked-jni`, `platforms-a1-activity-lifecycle`, `platforms-a1-storage-permissions`
  - **A2:** `platforms-a2-aaudio`, `platforms-a2-gpu`, `platforms-a2-packaging-16k`
  - **BTRSmith:** `btrsmith-storage-resources`, `btrsmith-audio-adaptation`, `btrsmith-gpu-portability`
  - **CI:** `qualification-ci-ios`, `qualification-ci-android`
- **Exit.**
  - Every provider suite passes through both frontends on its simulator, emulator, VM or device. Physical evidence is recorded where a device exists, otherwise marked "unavailable".
  - 100 lifecycle cycles without leaks.
  - MSIX, xcarchive and AAB validate, with every `.so` 16 KiB-aligned.
  - BTRSmith fault journeys and pixel readback pass per backend.
  - **Bucket-3 exit.**
- **Bound by** hardware availability.
- **Parallelization: WORKFLOW, rescoped around the interop dependencies, about 12 agents.**
  - **Windows lane.** Fully parallel, because COM landed in Stage 27.
  - **iOS lane.** Starts with packaging and simulator plumbing. **Blocked** until interop delivers the full Objective-C adapters: `UIApplicationDelegate`, `AVAudioSession`, CAMetalLayer hosting, and the I1 lifecycle.
  - **Android lane.** Starts with AAudio, NDK GPU and 16 KiB packaging (plain C). **Blocked** until interop delivers full checked JNI: activity lifecycle, storage, permissions.
  - **Interop lane.** A single owner does Objective-C first (unblocks I1/I2), then JNI (unblocks A1), following the Stage 27 plan. 1 separate agent builds the Java metadata reader.
  - **Lifecycle check.** Before the I1/A1 lifecycle owners land, 1 read-only agent checks them against a draft of UI2's host-owned loop and executor shape.
  - **`btrc.toml` changes** go through the integrator as fragments.
  - **BTRSmith.** Storage is serial, then 2–3 fixture agents. Audio policy is serial, then 3 port agents. GPU runs as 3 lanes, one per backend.
  - **2 CI agents.** One device owner and one queue per device.

## Bucket 4: native UI

UI8 (accessibility) and UI9 (GPU) are qualified **throughout**, not as a final retrofit (native-ui-parity.md:1108–1109, 1263–1265; ref:3691). Bridges start in UI1, and every UI4–UI7 landing carries its own UI8/UI9 acceptance on every provider. E46/E47 follow ref:3424–3428.

### Stage 30: UI0 catalog, journeys and evidence hosts
- **Items.**
  - `ui-0-focused-gate`
  - `ui-0-catalog-schema`
  - `ui-0-operation-map`
  - `ui-0-broader-surface`
  - `ui-0-product-journeys` and `btrsmith-ui0-callers`, as one unit
  - `ui-0-host-matrix`
  - `ui-0-doc-reconcile`
  - `qualification-p5-journey-catalog`
  - `tooling-linux-headless-gui`
  - `tooling-linux-desktop-host`
- **Exit.**
  - The drift test reports 19 files, 24 interfaces and 162 declarations, and fails when a dummy method is added.
  - All 1,620 operation slots and 470 case slots are classified, in the ledger format.
  - 100% of BTRSmith callers are mapped.
  - The journey catalog is frozen.
  - Linux GUI tests run under both Wayland and X11.
  - 1 gate plus linux-ci.
- **Depends on.** D24, D25. Read-only mapping may start during bucket 3's gate windows.
- **Parallelization: SERIAL first, then a read-only WORKFLOW of about 15 agents in waves of at most 10.**
  - **Serial first:** the focused gate and the catalog schema.
  - **Read-only fan-out:**
    - 4 operation-map agents and 3 broader-surface agents
    - 5 BTRSmith mappers, each writing the journey shard and the caller inventory in one pass
    - 1 journey drafter, plus 1 auditor checking against PRD and issue #15
  - **In parallel:** the nix owner adds weston, Xvfb, lavapipe, GTK4 and at-spi.
  - Doc reconciliation has a single writer.

### Stage 31: UI1 shells on all five platforms and the toolkit decision
- **Items.**
  - `ui-1-shell-fixture`
  - `ui-1-macos`
  - `ui-1-linux-sdl-baseline`
  - `ui-1-linux-gobject-binding`
  - `ui-1-linux-gtk-spike`
  - `ui-1-windows-shell`
  - `ui-1-ios-shell`
  - `ui-1-android-shell`
  - `ui-1-feasibility-review`
  - `qualification-ci-linux-gui-audio`
- **Exit.**
  - **Shell harness.** It passes on every provider × frontend × sanitizer, with accessibility bridges and tree artifacts from the start, and 0 leaked handles over 100 cycles.
  - **E46.** A Save/Discard/Cancel transaction, with 100 cycles per applicable entry path and zero lost drafts or duplicate saves.
  - **E47.** 100 fresh-process restores, with zero replayed side effects or cross-scene swaps.
  - **E40.** The reproduction is written and recorded as failing in the catalog. It stays on a branch (D24) until Stage 32's repair.
  - **GObject.** Binding parity holds and the bootstrap is byte-stable.
  - **Toolkit.** The GTK feasibility record exists, D23 is recorded, and the Linux GUI shard is green.
- **Parallelization: WORKFLOW, 11 agents** (one platform at a time without D6(c)).
  - **Serial first:** the fixture and the harness.
  - **6 provider agents** in separate worktrees:
    - macOS
    - Linux SDL, in the container and never during a gate
    - GTK, after the GObject binding
    - Windows: compile-only via zig, runtime on the ARM64 VM or in CI
    - iOS on the simulator
    - Android on the emulator
  - **Manifests.** Provider agents submit `GUI/btrc.toml` fragments; the integrator owns the file. They pin the integrator's btrcc, because GUI is not a compiler import.
  - **GObject.** 1 agent implements the Stage 27 plan, serially against other compiler work, with a bootstrap.
  - **Toolkit.** 2 adversarial reviewers argue GTK4 versus SDL plus AT-SPI.
  - **CI.** 2 agents.
  - Then your decision.

### Stage 32: UI2 contracts (events, executor, lifecycle) and the Library.UI split
- **Items.**
  - `ui-2-contract-control-events`
  - `ui-2-contract-executor`
  - `ui-2-contract-lifecycle`
  - `ui-2-contract-review`
  - `ui-2-macos`
  - `ui-2-linux`
  - `ui-2-btrsmith-subscriptions`
  - `btrsmith-libraryui-split`
- **Exit.**
  - You approve the interface diff.
  - E01–E04, E29, E31, E35, E39, E40 and E46 pass on macOS and Linux with sanitizers.
  - **The E40 repair lands with its Stage 31 reproduction:** 0 lost events across bursts of 4,095, 4,096, 4,097 and 8,193 events, with progress for input, rendering and close.
  - BTRSmith idle wakeups are measured before and after.
  - Library.UI is limited to the musical surfaces.
- **Parallelization: WORKFLOW, about 12 agents.**
  - **Drafting.** 3 drafters on disjoint files: control events; executor; lifecycle, which is the only IView writer.
  - **Review.** 2 feasibility reviewers using the real Stage 31 shells, plus 1 reconciler. Then your approval.
  - **Providers.** macOS and Linux agents start from the approved draft.
  - **Atomic landing.** The contract, macOS and Linux land in one commit. The Windows, iOS and Android shells keep compiling by throwing a typed "unsupported" error, recorded as "missing" in the catalog.
  - **BTRSmith.** Then 1 subscriptions agent.
  - **Library.UI split.** A serial view-model design (you approve the `ui.snapshot` change), then 4 surface agents in at most 2 clones at a time. ApplicationSession merges are serial. Code signing runs behind `locks/signing`.

### Stage 33: UI3 input, focus and commands, then the tray
- **Items.**
  - `ui-3-contract-input`
  - `ui-3-macos`
  - `ui-3-linux`
  - `ui-11-tray`
- **Exit.**
  - E05–E07, E13, E14, E25, E27, E44 and E45 pass on macOS and Linux.
  - **E46** Save/Discard/Cancel holds over 100 cycles per UI3 entry path.
  - The tray passes 100 cycles with exactly one typed command per activation.
  - Your IME trials are recorded.
- **Parallelization: WORKFLOW.**
  - 1 serial contract writer, the only writer of IView, IWindow and `App.btrc`, plus 2 feasibility reviewers.
  - macOS and Linux agents, then an atomic landing.
  - **The tray agent starts after that landing**, because it needs UI3's typed commands. Its accessibility rows are completed with Stage 34's UI8 work.
  - Meanwhile, 2–3 read-only agents pre-draft the UI4–UI9 contract notes against the five shells.

### Stage 34: UI4–UI9 contract packet and macOS/Linux reference providers
- **Items.**
  - **UI4:** `ui-4-contract-controls`, `ui-4-macos`, `ui-4-linux`
  - **UI5:** `ui-5-contract-layout`, `ui-5-macos`, `ui-5-linux`
  - **UI6:** `ui-6-contract-collections`, `ui-6-stress-fixture`, `ui-6-macos`, `ui-6-linux`
  - **UI7:** `ui-7-contract-services`, `ui-7-macos`, `ui-7-linux`
  - **UI8:** `ui-8-contract-a11y`, `ui-8-macos`, `ui-8-linux`
  - **UI9:** `ui-9-contract-gpu`, `ui-9-macos`, `ui-9-linux`
  - `qualification-catalog-fixtures` (`ui-6-stress-fixture` is its btrc half)
  - `qualification-p6-runtime-probes`
- **Exit, per UI4–UI7 landing, on both frontends:**
  - **Functional:**
    - UI4: 12 of 12 control families.
    - UI5: a layout matrix that clips nothing. **E46** transactions, and **E47** 100 fresh-process restores.
    - UI6: the 100,000-row collection budget, with recycled-collection identity exposed to accessibility.
    - UI7: 8 of 8 service families, with **E46** transactions.
  - **UI8, in the same landing:**
    - correct names, roles, states, actions and focus for that family's actionable controls
    - **keyboard-only journeys**
    - **VoiceOver journeys on macOS and Orca journeys on Linux**

    A semantic snapshot alone does not count.
  - **UI9, in the same landing:** GPU-backed content of that family is qualified, including virtual GPU content in the accessibility tree.
  - **Overall:** E36, E38, E42 and E43 pass; a static idle screen uses ≤1% CPU; fixtures produce stable content hashes. At the end, 100% of core actionable controls are covered by UI8. Each landing is atomic with a gate, about 12 gates in total.
- **Parallelization: WORKFLOW.**
  - **Step 0, the packet.**
    - Drafts for UI4 (3 sub-drafters plus a reconciler), UI6, UI7 (2 drafters) and UI9 run concurrently.
    - One IView writer drafts UI5 and the UI8 bridge contract.
    - Reviewed by 5 platform reviewers plus 1 adversary looking for AppKit-shaped APIs, then **one approval from you**.
  - **Then milestone by milestone, UI4 to UI7.** macOS and Linux agents, each optionally split into 2 by family, each carrying the family's accessibility and GPU work. The integrator merges `btrc.toml` fragments and lands the contract plus providers atomically.
  - **Fixtures.** 2 agents, one per repository.
  - **Probes.** A serial contract with a proof that realtime paths do not allocate, then 1 agent per provider.
  - GUI captures and screen-reader sessions are serialized on the `gui-capture` lock.

### Stage 35: Windows, iOS and Android UI tracks (one milestone behind Stage 34)
- **Items.**
  - **Windows:** `ui-win-core`, `ui-win-controls-layout`, `ui-win-collections-services`, `ui-win-a11y-gpu`
  - **iOS:** `ui-ios-core`, `ui-ios-controls-layout`, `ui-ios-collections-services`, `ui-ios-a11y-gpu`
  - **Android:** `ui-android-core`, `ui-android-controls-layout`, `ui-android-collections-services`, `ui-android-a11y-gpu`
- **Exit.**
  - Each platform passes the same E-cases (including E46/E47 where applicable) and family fixtures as macOS and Linux.
  - Each family ships with its UIA, XCUITest or UiAutomator trees, and Narrator, VoiceOver or TalkBack journeys, at the time it lands.
  - The `*-a11y-gpu` items close the remaining platform bridge work and GPU qualification.
  - Mobile artwork stays ≤64 MiB.
- **Overlap.** It overlaps Stage 34.
- **Parallelization: WORKFLOW, 3 long-lived agents (up to 6), subject to D6(c).**
  - Each agent owns one provider directory, `GUI/{Windows,IOS,Android}`, and submits `btrc.toml` fragments to the integrator.
  - Each moves through core, then controls and layout, then collections and services, with accessibility and GPU inside every step.
  - Contract defects go back to the single contract owner.
  - At most 3 builds and 2 guests at once. One device queue per guest.

### Stage 36: BTRSmith screen migration slices (one milestone behind Stage 34)
- **Items.**
  - `btrsmith-ui-event-loop`
  - `btrsmith-ui-slice1-search-filters`
  - `btrsmith-ui-slice2-settings` with `ui-4-btrsmith-settings`
  - `btrsmith-ui-adaptive-layout` with `ui-5-btrsmith-adaptive`
  - `btrsmith-ui-slice3-library` with `ui-6-btrsmith-library` and `ui-7-btrsmith-import`
  - `btrsmith-ui-slice4-player` with `ui-9-btrsmith-player`
  - `btrsmith-ui-accessibility`
- **Exit.**
  - Each slice's E-cases pass on every available provider, with that screen's screen-reader journey.
  - No polling remains.
  - Search p95 ≤100 ms.
  - Static idle uses ≤1% CPU.
  - Player shows 0 app-induced xruns over 30 minutes, with frame p95 ≤16.7 ms.
- **Overlap.** It interleaves with Stages 34–35.
- **Parallelization: WORKFLOW, at most 2 BTRSmith clones.**
  - 1 integrator owns ApplicationSession, ApplicationView and GUIApplication. The event-loop change is serial.
  - Per-slice agents work on disjoint frontend files: Library 2 (grid, picker), Settings 1, Player 2, accessibility 1 per screen.
  - Each duplicate pair counts as one unit of work.

### Stage 37: UI10 automation and mobile restoration; UI11 long tail
- **Items.**
  - `ui-10-automation-diagnostics` and `qualification-p5-journey-drivers`, as one unit
  - `ui-10-btrsmith-mobile` and `btrsmith-ui-slice5-mobile-restoration`, as one unit
  - `ui-10-qualification`
  - `ui-11-pickers-n51-n52`, `ui-11-rich-web-n53-n54`, `ui-11-print-media-n55-n57`, `ui-11-data-docs-help-n58-n60`
- **Exit.**
  - Drivers pass the seed journeys on the installed app.
  - 100 fresh-process restores (E47), with 0 replayed side effects.
  - The catalog resolves 470 of 470 case slots and 1,620 of 1,620 operation slots, and 50 of 50 core families.
  - UI11 families are dispositioned.
  - A full gate.
  - **Deferred UI10 parts** (native-ui-parity.md:1142–1147): "all numeric goals on the named matrix" closes in Stage 41, and "minimum/current OS and SDK-update evidence" closes in Stage 42. The UI10 row stays open until Stage 42.
- **Parallelization: WORKFLOW.**
  - A serial script schema, then 5 per-platform driver agents.
  - BTRSmith mobile: a serial checkpoint format, then 2 device agents.
  - UI11: 1 agent per family, then 1 per provider.
  - Evidence collection fans out per host. Aggregation and the gate are serial.

## Bucket 5: product and release qualification

### Stage 38: CI tiers, macOS native suite, BTRSmith CI, cross-target benchmarks
- **Items.**
  - `qualification-ci-macos-native-suite` (unless done in Stage 2)
  - `qualification-ci-btrsmith` and `btrsmith-q-ci`, as one unit
  - `qualification-ci-tiering`
  - `qualification-p6-build-bench-targets`
- **Exit.**
  - The macOS shards skip only hardware-tier cases.
  - BTRSmith CI is green on both frontends: on Linux hosted runners plus the self-hosted D7 runner per push, and on macOS for tagged releases. The cost per run is recorded against D26's budget.
  - One release dispatch produces one ledger bundle.
  - Benchmark adapters emit valid records.
- **Depends on.** D4, D26.
- **Parallelization: WORKFLOW, about 6 agents.**
  - 1 macOS agent and 1 BTRSmith-CI agent.
  - Tiering is serial, done afterwards by 1 agent.
  - Benchmarks: the core is serial, then 3 adapters.

### Stage 39: P5 journeys on installed products and the macOS MVP closure
- **Items.**
  - `btrsmith-macos-mvp-automatable`
  - `btrsmith-q-selfhost-matrix`
  - `qualification-p5-runs-macos-linux`, `qualification-p5-runs-windows`, `qualification-p5-runs-ios`, `qualification-p5-runs-android`
  - `tooling-windows-physical`
- **Exit.**
  - Captures are posted on issues #2, #3, #6, #7 and #16–#19; you close them.
  - The self-host matrix is green.
  - Every journey slot is passed, or adapted with review, with 0 missing core journeys.
- **Parallelization: WORKFLOW across machines.**
  - **MVP.** 3 agents, one per screen, plus 1 reviewer with you for #6. GUI capture is serialized.
  - **Runners.** 1 runner agent per host or device.
    - Only the NixOS host, Windows x64 hardware and CI are separate machines.
    - The iPhone, iPad, Android devices and the ARM64 VM are driven through this Mac (devicectl, adb), so they count against its CPU and GUI queue: **at most two at a time**, serial within each device.

### Stage 40: Physical instrument, listening and latency sessions
- **Items.**
  - `qualification-p5-physical-audio-visual`
  - `btrsmith-macos-mvp-physical`
  - `tooling-audio-loopback-rig` and `qualification-p6-audio-latency-rig`, as one unit
- **Exit.**
  - Signed-off listening, route and visual records per platform.
  - Evidence posted on issues #4, #5, #21 and #22; you close them.
  - At least 100 round-trip latency samples: p95 ≤20 ms on Windows and iOS, ≤30 ms on Android.
  - A 2-hour soak.
- **Bound by** your availability for the sessions.
- **Parallelization: SERIAL.**
  - One rig, with you in the loop.
  - 1 agent writes the latency program. 1 prepares checklists and the next platform's scripts.

### Stage 41: P6 numeric acceptance
- **Items.**
  - `qualification-p6-build-measure`
  - `qualification-p6-runtime-runs`
  - Also closes UI10's numeric goals on the named matrix.
- **Exit.**
  - Raw sample distributions per host and device for every build and runtime budget, using the reconciled P6 table (including the reference private-body edit row), with any misses stated.
  - UI10 numeric rows met or revised.
- **Parallelization: WORKFLOW across machines only.**
  - 1 measuring agent per quiet host or device.
  - Never two measurements on the same host.
  - The Mac runs your quiet checklist.

### Stage 42: P7 release engineering
- **Items.**
  - `qualification-p7-sanitizers`
  - `qualification-p7-devtools-targets`, containing `tooling-target-debuggers`
  - `qualification-p7-release-artifacts`
  - `qualification-p7-macos-notarization`
  - `tooling-release-signing-mobile-store`
  - `qualification-p7-install-upgrade`
  - `qualification-p7-stress-faults`
  - `qualification-p7-os-version-matrix`, which also closes UI10's minimum/current OS and SDK-update evidence
- **Exit.**
  - A sanitizer omissions table.
  - A `.btrc` breakpoint works and a crash symbolicates on every target.
  - Unsigned builds are reproducible byte for byte.
  - `spctl` accepts the stapled app.
  - Mobile release packages validate, or are recorded as declined.
  - Upgrades lose no state.
  - Every fault class passes 100 cycles.
  - Minimum and current OS versions pass, and **the UI10 row closes**.
- **Parallelization: WORKFLOW in waves.**
  - 4 sanitizer agents.
  - Devtools: the interface is serial, then 4 agents.
  - Artifacts: 4 agents, plus a serial Makefile and Packaging.mk integrator.
  - Notarization is serial, and you approve every submission.
  - 5 install/upgrade agents, 4 stress agents, 1 OS-matrix agent per platform.
  - Sanitizers never run alongside bootstrap.

### Stage 43: Final platform exits and the release candidate
- **Items.**
  - `qualification-final-w2-exit`, `qualification-final-i2-exit`, `qualification-final-a2-exit`
  - `btrsmith-q-platform-release`
  - `qualification-p7-release-candidate-run`
- **Exit.**
  - One ledger bundle with every required gate on the same frozen SHAs and package set.
  - A coverage report of equivalent, adapted, restricted and missing items.
  - Bucket 5 marked done.
- **Parallelization: SERIAL coordinator.**
  - The Mac gate chain runs strictly in order.
  - CI tiers run remotely.
  - Device agents run across devices, within the Mac's two-at-a-time limit.
  - Any fix restarts the run.

---

## Where sub-agents help and where they do not

| Helps | Rule |
|---|---|
| Read-only swarms (audits, inventories, attribution, triage over logs) | No worktree. Waves of at most 10. Run them during gate windows, never during quiet rounds. Inventories of the next bucket may run early. |
| Throwaway experiments | Instructions retired at `--jobs 1` (repeatable within about 0.3% under load) are valid **only for single-thread algorithmic cuts**. Allocator swaps, parallel analysis, arenas, ARC contention and the resident compiler go on a **quiet-window queue** (nightly, with your checklist). Save patches, never commits. |
| Test authoring | Authors write new, disjoint test modules and may share one worktree with a pinned `BTRC_TEST_BTRCC`. A fixer always gets its own worktree. Expensive matrices go in opt-in tiers. |
| Implementation lanes | Disjoint files only. **Every writer has its own worktree from the hub clone.** Lanes deliver unsigned branch commits, and never commit derived artifacts. |
| Python/btrc halves | Each perf or language item is labelled one of two ways:<br>• **"paired, one commit"**: both halves from one written spec<br>• **"single-compiler internal"**: no observable output change; that compiler's emitted units are byte-identical to its own previous output; precedent `fcdbd6d`<br>Anything that changes observable behavior is paired, or you record a parity exception. |
| Adversarial reviewers | Use them on schema commits, reuse-key, journal and memo designs, the interop plan, UI contract packets, and C constructs (one parity reviewer each). Their output is new invalidation rows or tests, and they reuse the lane's btrcc. |
| Remote hosts | One agent per machine. The NixOS host and CI are the only truly separate machines. |

| Does not help | Rule |
|---|---|
| Gates | The batch gate is the reference's §2 list (see D5). Only the main session runs it, one at a time. `make bootstrap` never runs beside the suite or a guest.<br>**Load rules:**<br>• Before Stage 2's daemon-deadline fix, only read-only agents run during any gate.<br>• After it, at most one agent build beside `make test`, and none beside `test-c11` or bootstrap. |
| Wall-clock measurements | Quiet machine: the automated quiet check, no agents, no guest. The remote agent pauses locally. |
| Shared specs | `grammar.ebnf`; `ast.asdl` plus generated code; `native_abi.asdl`; `hosted_abi.toml` plus generated code; `intrinsic_effects.toml` (owned by the Stage 19 vocabulary owner); `src/runtime/c` plus manifest; the boundary manifest. One owner per schema commit. |
| **Derived artifacts** | No lane commits any of these: `src/stdlib/btrc.symbols`, `src/stdlib/btrc.lock`, `src/devex/lsp/catalog/generated.py`, boundary re-captures, the `source_count` and `INCLUDE_FIXTURES` updates, or `GUI/btrc.toml` and other `btrc.toml` exports. Lanes submit manifest fragments. |
| Hotspot files (one owner at a time) | • **Compiler:** `pipeline/ModuleUnits.btrc` with `application/modules.py`; `cli/Driver.btrc`; `pipeline/Pipeline.btrc`; `ir/Emitter.btrc`; `backend/c_emitter.py`; `syntax/Identity.btrc`; `tools/compiler_codegen/ast.py` with generated `Node.btrc`<br>• **Tools:** `tools/native_plan.py`; `tools/budget_bench.py`; `Makefile`; `conftest.py`; `flake.nix`, `flake.lock` and `nix/*`<br>• **The 100-file inventory:** `test_compiler_structure_contract.py`, `docs/design/compiler-structure.md`, AGENTS.md<br>• **Docs:** `docs/design/compile-performance.md`, `separate-compilation.md`, PLAN.md, CLAUDE.md. Lanes write JSON; the integrator writes the tables.<br>• **UI:** IView, IWindow and `App.btrc`<br>• **BTRSmith:** ApplicationSession, ApplicationView, GUIApplication and the Make graph |
| Parsers | `Parser.btrc` and `parser.py` are touched by every C lane, so they are not single-owner. Shared body parsing lands first, as `_parse_body`, then lanes merge in a set order and rebase. |
| Google Drive | Agents never work in the Drive checkouts or in worktrees whose gitdir lives in Drive. They work from `~/.cache/btrc/hub.git` and `~/.cache/btrsmith/hub.git`. The integrator fetches batches into Drive. Gates never run from Drive. Check `git status` at the start of every stage. |
| Disk and RAM | • **Free disk** re-checked at every stage start.<br>• **`build/test-btrcc`:** LRU prune before every wave.<br>• **btrcc builds:** the `btrcc-build` semaphore allows N=2. The integrator builds one btrcc per base SHA, and lanes pin it. That is sound unless a lane edits a compiler stdlib import (the root prelude, FileSystem, Digest, BackgroundJobs, Process, Platform, IO, JSON, TOML, Datetime, Console); such a lane builds its own and runs bootstrap.<br>• **Writer worktrees:** at most 4 before the podman shrink, 6 after.<br>• **BTRSmith clones:** 1 before the shrink, 2 after. Clean test outputs after each run, and sign behind `locks/signing`.<br>• **Guests:** podman 24 GiB, Windows VM 8 GiB, emulator 4 GiB. At most one beside a gate, none during bootstrap or a quiet round. Never put caches in `/tmp`. |
| GUI capture and devices | One queue per window server and per device. Devices driven through the Mac count against it, at most two at a time. Human-in-the-loop sessions are serial. |
| Authority | Only the main session pushes, after a green batch gate (D4). Agents close issues only under the standing approvals. No agent changes system settings (Spotlight, Time Machine), enters credentials, creates accounts or accepts agreements other than the Android SDK licences. Signing: agents commit unsigned, and the integrator signs when the 1Password agent is available, otherwise commits unsigned rather than stall. |
| Duplicate items | Each pair runs as one unit:<br>• `platforms-p0-matrix-pin` and `tooling-p0-toolchain-matrix`<br>• `ui-0-product-journeys` and `btrsmith-ui0-callers`<br>• `ui-4/5/6/7/9-btrsmith-*` and the matching `btrsmith-ui-slice*`<br>• `ui-10-btrsmith-mobile` and `slice5`<br>• `ui-10-automation-diagnostics` and `qualification-p5-journey-drivers`<br>• `ui-6-stress-fixture` and `qualification-catalog-fixtures`<br>• `qualification-ci-btrsmith` and `btrsmith-q-ci`<br>• `tooling-audio-loopback-rig` and `qualification-p6-audio-latency-rig`<br>• `tooling-target-debuggers` inside `qualification-p7-devtools-targets`<br>• `platforms-p4-dependency-crossbuild` and `btrsmith-package-closure` |

**Merge-batch procedure (one integrator sub-agent per stage):**
1. Fetch the lanes' unsigned branches from the hub, and rebase them in the stage's merge order.
2. Apply the `btrc.toml` fragments. Run `make compiler-codegen-generate`, re-resolve the stdlib lock, and regenerate `btrc.symbols` and the LSP catalog.
3. Re-capture boundary records with reasons, and update `source_count` and the fixture lists. Write the docs tables from the lanes' JSON. All of this goes in one merge commit.
4. Build one btrcc for the new base SHA, so the next wave can pin it. Prune `test-btrcc`.
5. Hand the batch to the main session for the D5 gate. When it is green, the main session pushes `main` (D4).
6. If the gate is green, fetch into the Drive checkout. If it is red, run D5's revert-bisect and send the culprit back to its lane.

## Ultracode recommendation

**Yes, at the named fan-out points, after a measured pilot.**

Progress is bounded by:
- the serial gate and schema/interop chains
- quiet measurement windows
- hardware and accounts that only you can provide (D7, D8)
- one window server and GPU
- disk
- integration throughput

Agent count is not the limit. Ultracode pays off where work is token-bound, read-only, or confined to disjoint files. It also shortens the implementation-bound stages (16–19, 25, 28, 34–36). Each Workflow stage gets one integrator sub-agent running the merge-batch procedure, so the main session stays coordinator and gate runner.

| Use a Workflow | Shape | Fan-out width (agents) |
|---|---|---|
| 2 | Nix agent first, then ledger schema, CI health, trigger, manifests | 8–9 |
| 3 | Harness, peak guard, batch proposal (overlapping 2) | 3 |
| 4 | Structure and native-migration audit (waves ≤10), then serial apply | 23 + 2 |
| 6 | Floor spikes (patches), key/journal spec with reviewers, attribution, native | 13 |
| 7 | Acceptance-test authors, setjmp pair, generics audit, M10 lane, BTRSmith net | 19 (≤5 worktrees) |
| 8, 9, 11, 12 | Python Stage B slices, Stage B completion, edit-path lanes, hotspot cuts, conditional audits | 10–14 each |
| 14, 16, 17, 19 | C inventory authors, construct lanes, 1 parity reviewer per construct | 7–15 each |
| 22, 25, 28 | P0 swarm, corpus triage over runner logs, dependency cross-builds | 22–25 each |
| 24, 26, 27, 29 | Paired consumers, P3 slices, ownership design plus serial interop, platform lanes (D6c) | 10–20 each |
| 30–37 | UI0 swarm, five shells, contract drafters and reviewers, per-platform tracks, BTRSmith slices | 10–15 each |
| 39, 41–43 | One runner per host or device | 6–8 |

**Do not use a Workflow for:**
- Stages 1, 5, 13, 15, 18 (first half), 20, 21, 40 and 43
- gates, wall-clock measurements, schema or runtime commits, or physical sessions

**Starting sequence:**
- **Decisions:** all resolved; Stage 1 carries out D2 and D3.
- **Stage 1**, serially in the main session.
- **Stages 2 and 3 overlapped:** the nix agent first, then the fan-outs.
- **Stage 4 wave 1:** the read-only audit, inside Stage 2/3 gate windows.
- **Pilot before fanning out:** run one builder agent (the daemon-deadline fix) and one auditor, measure their token use from the session usage report, and size the next fan-outs from those numbers.
- **Stretch:** Stage 4's btrc-side apply plus its gate.
- **Waits:** the BTRSmith pin bump follows the first D4 push; Stage 5 follows the pin bump and the automated quiet check. An overnight pre-Stage-4 diagnostic is fine, but it does not satisfy Stage 5.

**Usage rules:**
- Read-only auditors are much cheaper than builder agents; size builder fan-outs from the pilot's measured cost.
- Check the session usage report after every stage.
- If the remaining weekly budget runs low, stop at a commit boundary and save state.
- More tokens shorten the implementation-bound stages, but not the serial chains, quiet windows, approvals or hardware lead times.

## Appendix: every mapped item → stage (286 items)

**Compiler performance (37)**

| Stage | Items |
|---|---|
| 1 | `perf-plan-refresh` |
| 3 | `perf-harness`, `perf-peak-guard`, `perf-linux-bench` |
| 5 | `perf-baseline-round` |
| 6 | `perf-floor-spikes`, `perf-ref-attribution`, `perf-signing-attest`, `perf-native-receipts` |
| 7 | `perf-m11-acceptance`, `perf-setjmp-barriers`, `perf-generic-temporaries` (btrc-internal; reference-side work is in `perf-ref-cold`), `perf-mimalloc`, `perf-m10-pool-qualification` (added) |
| 8 | `perf-ref-frontend-cache`, `perf-ref-stageb`, `perf-ref-cold` |
| 9 | `perf-stageb-slice4`, `perf-stageb-skip-unchanged` (moved from 11; M11 acceptance), `perf-batch-10`, `perf-cold-release`, `perf-product-integration` |
| 10 | `perf-nixos-acceptance` |
| 11 | `perf-records-pack`, `perf-frontend-durable`, `perf-decl-session-cache`, `perf-parse-cache`, `perf-native-link`, `perf-cold-native`, `perf-resident-compiler` |
| 12 | `perf-decl-lowering-hotspots`, `perf-parallel-analysis`, `perf-borrowed-returns`, `perf-m9-arena`, `perf-arc-thread-confined`, `perf-m8b` |
| 13 | `perf-final-qualification` |

**C compatibility (34)**

| Stage | Items |
|---|---|
| 14 | `ccompat-c5-baseline`, `ccompat-refusal-policy`, `ccompat-r23-vla-audit` |
| 15 | `ccompat-c1-schema` |
| 16 | `ccompat-r02-braceless-bodies`, `ccompat-r06-empty-statement`, `ccompat-r01-void-unnamed-params`, `ccompat-r05-adjacent-strings`, `ccompat-r04-char-array-string-init`, `ccompat-r03-multi-declarators`, `ccompat-r19-comma-operator` (moved from 21), `ccompat-r07-function-pointer-declarators`, `ccompat-c1-integrate`, `ccompat-r18-preprocessor-conditionals` (if approved, after C1; otherwise refused in 21) |
| 17 | `ccompat-c2-schema`, `ccompat-r09-union-declarations`, `ccompat-r08-typedef-struct-anonymous-members`, `ccompat-r10-designated-init-compound-literals`, `ccompat-r12-bitfields` (only with a named consumer; otherwise refused), `ccompat-r13-flexible-array-members`, `ccompat-x-enum-tag-spelling`, `ccompat-c2-integrate` |
| 18 | `ccompat-r17-multidimensional-arrays` |
| 19 | `ccompat-c3-schema-vocabulary`, `ccompat-r15a-qualifiers-storage-classes`, `ccompat-r15b-inline-noreturn`, `ccompat-r15c-static-assert`, `ccompat-r15d-alignment`, `ccompat-r16-wide-literals-long-double`, `ccompat-x-expression-stragglers`, `ccompat-r14-variadic-definitions` (only with a named consumer), `ccompat-c3-integrate` |
| 20 | `ccompat-r11-goto-labels` |
| 21 | `ccompat-c5-docs-final` |

**Platform foundations (54)**

| Stage | Items |
|---|---|
| 22 | `platforms-p0-entry-baseline`, `platforms-p0-inventory`, `platforms-p0-adaptations`, `platforms-p0-matrix-pin` |
| 23 | `platforms-p1-toolchains` |
| 24 | `platforms-p1-target-spec`, `platforms-p1-hosted-abi-targets`, `platforms-p1-native-import-targets`, `platforms-p1-native-plan-toolchain`, `platforms-p1-provider-filters`, `platforms-p1-cache-identity`, `platforms-p1-abi-fixture` |
| 25 | `platforms-p1-host-windows`, `platforms-p1-host-ios`, `platforms-p1-host-android`, `platforms-p2-target-probes`, `platforms-p2-target-runner`, `platforms-p2-runtime-semantics`, `platforms-p2-portable-corpus`, `platforms-p2-ci-lanes` |
| 26 | `platforms-p3-windows-launch-seam`, `platforms-p3-fs-windows`, `platforms-p3-process-terminal`, `platforms-p3-sockets-http`, `platforms-p3-regex-glob`, `platforms-p3-fs-mobile`, `platforms-p3-jobs-ipc` |
| 27 | `platforms-interop-function-table-calls`, `platforms-w1-win32-com-imports`, `platforms-w1-sdk-reader-provider`, `platforms-w1-worker-pools`, `platforms-w1-unicode-host`, `platforms-w1-ci-and-bundle` (plus the first slices of the I1 Objective-C and A1 JNI items, which are mapped to 29) |
| 28 | `platforms-p4-dependency-crossbuild`, `platforms-w1-toolchain-abi-route` (closes W1), `platforms-p4-library-artifacts`, `platforms-p4-assets-streams-plugins`, `platforms-p4-package-contracts` |
| 29 | `platforms-w2-arm64`, `platforms-w2-wasapi`, `platforms-w2-gpu-image-font`, `platforms-w2-packaging`, `platforms-i1-objc-protocol-adapters`, `platforms-i1-app-lifecycle`, `platforms-i1-sandbox-storage`, `platforms-i2-audio`, `platforms-i2-gpu`, `platforms-i2-app-packaging`, `platforms-a1-checked-jni`, `platforms-a1-activity-lifecycle`, `platforms-a1-storage-permissions`, `platforms-a2-aaudio`, `platforms-a2-gpu`, `platforms-a2-packaging-16k` |

**Native UI (70)**

| Stage | Items |
|---|---|
| 30 | `ui-0-focused-gate`, `ui-0-catalog-schema`, `ui-0-operation-map`, `ui-0-broader-surface`, `ui-0-product-journeys`, `ui-0-host-matrix`, `ui-0-doc-reconcile` |
| 31 | `ui-1-shell-fixture`, `ui-1-macos`, `ui-1-linux-sdl-baseline`, `ui-1-linux-gobject-binding`, `ui-1-linux-gtk-spike`, `ui-1-windows-shell`, `ui-1-ios-shell`, `ui-1-android-shell`, `ui-1-feasibility-review` |
| 32 | `ui-2-contract-control-events`, `ui-2-contract-executor`, `ui-2-contract-lifecycle`, `ui-2-contract-review`, `ui-2-macos`, `ui-2-linux`, `ui-2-btrsmith-subscriptions` |
| 33 | `ui-3-contract-input`, `ui-3-macos`, `ui-3-linux`, `ui-11-tray` (after the UI3 landing) |
| 34 | `ui-4-contract-controls`, `ui-4-macos`, `ui-4-linux`, `ui-5-contract-layout`, `ui-5-macos`, `ui-5-linux`, `ui-6-contract-collections`, `ui-6-stress-fixture`, `ui-6-macos`, `ui-6-linux`, `ui-7-contract-services`, `ui-7-macos`, `ui-7-linux`, `ui-8-contract-a11y`, `ui-8-macos`, `ui-8-linux`, `ui-9-contract-gpu`, `ui-9-macos`, `ui-9-linux` (UI8/UI9 acceptance carried in each UI4–UI7 landing) |
| 35 | `ui-win-core`, `ui-win-controls-layout`, `ui-win-collections-services`, `ui-win-a11y-gpu`, `ui-ios-core`, `ui-ios-controls-layout`, `ui-ios-collections-services`, `ui-ios-a11y-gpu`, `ui-android-core`, `ui-android-controls-layout`, `ui-android-collections-services`, `ui-android-a11y-gpu` |
| 36 | `ui-4-btrsmith-settings`, `ui-5-btrsmith-adaptive`, `ui-6-btrsmith-library`, `ui-7-btrsmith-import`, `ui-9-btrsmith-player` |
| 37 | `ui-10-automation-diagnostics`, `ui-10-btrsmith-mobile`, `ui-10-qualification` (numeric goals close in 41, OS evidence in 42), `ui-11-pickers-n51-n52`, `ui-11-rich-web-n53-n54`, `ui-11-print-media-n55-n57`, `ui-11-data-docs-help-n58-n60` |

**BTRSmith (31)**

| Stage | Items |
|---|---|
| 1 | `btrsmith-wip-reconcile`, `btrsmith-docs-reconcile` |
| 2 | `btrsmith-baseline` |
| 4 | `btrsmith-structure-stdlib`, `btrsmith-structure-repo` (includes issue #20), `btrsmith-pin-bump` (blocked on push) |
| 7 | `btrsmith-portable-coverage` |
| 9 | `btrsmith-test-batch`, `btrsmith-dev-mode` |
| 21 | `btrsmith-c-compat-regression` (also reruns after 16, 17, 19 and 20) |
| 22 | `btrsmith-p0-inventory` |
| 28 | `btrsmith-cross-target-build`, `btrsmith-package-closure` |
| 29 | `btrsmith-storage-resources`, `btrsmith-audio-adaptation`, `btrsmith-gpu-portability` |
| 30 | `btrsmith-ui0-callers` |
| 32 | `btrsmith-libraryui-split` |
| 36 | `btrsmith-ui-event-loop`, `btrsmith-ui-slice1-search-filters`, `btrsmith-ui-slice2-settings`, `btrsmith-ui-adaptive-layout`, `btrsmith-ui-slice3-library`, `btrsmith-ui-slice4-player`, `btrsmith-ui-accessibility` |
| 37 | `btrsmith-ui-slice5-mobile-restoration` |
| 38 | `btrsmith-q-ci` |
| 39 | `btrsmith-macos-mvp-automatable`, `btrsmith-q-selfhost-matrix` |
| 40 | `btrsmith-macos-mvp-physical` |
| 43 | `btrsmith-q-platform-release` |

BTRSmith issues outside the item list: issue #13 (full-screen practice mode) is dispositioned in D25, with post-MVP recommended. Issue #20 is in Stage 4.

**Tooling (22)**

| Stage | Items |
|---|---|
| 1 | `tooling-disk-reclaim`, `tooling-host-capacity-policy` |
| 2 | `tooling-devshell-missing-tools`, `tooling-linux-container-refresh`, `tooling-ci-dispatch-policy` |
| 10 | `tooling-x86-acceptance-host` (decision D7 now) |
| 22 | `tooling-p0-toolchain-matrix` |
| 23 | `tooling-ios-simulator-runtimes`, `tooling-android-sdk-ndk`, `tooling-windows-vm`, `tooling-windows-ci-arm64-llvm`, `tooling-apple-signing`, `tooling-ios-physical-devices`, `tooling-android-physical-devices` |
| 25 | `tooling-android-ci-emulator` |
| 28 | `tooling-cross-gpu-deps` |
| 30 | `tooling-linux-headless-gui`, `tooling-linux-desktop-host` |
| 39 | `tooling-windows-physical` |
| 40 | `tooling-audio-loopback-rig` |
| 42 | `tooling-target-debuggers`, `tooling-release-signing-mobile-store` |

**Qualification (38)**

| Stage | Items |
|---|---|
| 1 | `qualification-plan-doc-reconcile` |
| 2 | `qualification-ci-health`, `qualification-evidence-ledger`, `qualification-skip-ledger` |
| 10 | `qualification-acceptance-hosts` |
| 22 | `qualification-device-lab` (procurement decision D8 now) |
| 23 | `qualification-signing-accounts` |
| 27 | `qualification-ci-windows-matrix` |
| 29 | `qualification-ci-ios`, `qualification-ci-android` |
| 30 | `qualification-p5-journey-catalog` |
| 31 | `qualification-ci-linux-gui-audio` |
| 34 | `qualification-catalog-fixtures`, `qualification-p6-runtime-probes` |
| 37 | `qualification-p5-journey-drivers` |
| 38 | `qualification-ci-macos-native-suite` (moves to 2 if pushes are allowed), `qualification-ci-btrsmith`, `qualification-ci-tiering`, `qualification-p6-build-bench-targets` |
| 39 | `qualification-p5-runs-macos-linux`, `qualification-p5-runs-windows`, `qualification-p5-runs-ios`, `qualification-p5-runs-android` |
| 40 | `qualification-p5-physical-audio-visual`, `qualification-p6-audio-latency-rig` |
| 41 | `qualification-p6-build-measure`, `qualification-p6-runtime-runs` |
| 42 | `qualification-p7-sanitizers`, `qualification-p7-devtools-targets`, `qualification-p7-release-artifacts`, `qualification-p7-macos-notarization`, `qualification-p7-install-upgrade`, `qualification-p7-stress-faults`, `qualification-p7-os-version-matrix` |
| 43 | `qualification-final-w2-exit`, `qualification-final-i2-exit`, `qualification-final-a2-exit`, `qualification-p7-release-candidate-run` |

**Totals:** 37 + 34 + 54 + 70 + 31 + 22 + 38 = **286**. Every item is assigned to exactly one stage.