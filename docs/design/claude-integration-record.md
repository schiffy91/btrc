# Claude integration record

The Progress log of Claude's roadmap ([CLAUDE.md](../../CLAUDE.md)), moved verbatim from
`PLAN.md` on 2026-10-06 (D28) so the roadmap stays small enough to load in every Claude
session. New stage exits and integration batches are appended at the end of the
section they belong to. Codex's own results live in [CODEX.md](../../CODEX.md).

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

- **Nullable-flow parity** (lane `stage4/nullable-flow-parity`, batch 7 on `1837bf7`). Python gains non-returning calls: a `noreturn` list in `hosted_abi.toml` (`exit`, `abort`, `_Exit`, `quick_exit`, `longjmp`, `pthread_exit`), never-returning functions and methods, and unreachable code, so a null guard ending in one proves the value non-null after it. btrcc now prints warnings in the Python format (they never change the exit status) and ports the nullable-access flow as `NullableFlow`. Both compilers add the store warning `Possibly-null value stored in non-nullable <context> of type 'T'` for initializers, assignments, returns, arguments and defaults. Both report identical warnings on all 1,203 corpus, stdlib and example programs; the corpus runner checks every program's warnings against an `expected/<Stem>.warnings` golden, and the self-host transpiles stay at zero. `List.head`/`tail` and `ListNode.next` became nullable (rename table updated). Merge fix-ups: the `ControlFlow.btrc` conflict keeps batch 6's local-bound check before the flow checks, and batch 6's F9/F10 lowering stores a string-array extent only when there is one (`d662ab0`), which removed the two new self-host warnings. Gates: clean (generated-source, lint, format, diff, zero-warning self-host transpiles, `boundary-check` 287 of 311). `src/tests/python`, `src/tests/btrc`, the corpus through both compilers and the LSP tests: 11,220 passed, 3,165 skipped. The bootstrap reached its fixed point.

- **Batch 7 CI fix** (lane `stage4/macos-nullable-warnings`, `0311fee`). CI on `e9c72e8` failed 20 macOS unit tests: macOS-only providers and fixtures, which no Linux host compiles, now hit the possibly-null store warning, and those tests require warning-free compiles. The lane listed every macOS warning with a temporary workflow (reverted in `7734155`) and proved the values non-null before storing them in `MacOSSystemText`, `MacOSEncodedImageDecoder`, `MacOSGPUSurface`, `MacOSRunLoop`, `MacOSButton`, `MacOSTextField`, `MacOSTray` and three native GUI fixtures, with guards and no casts. Its full macOS run (37057700071) passed every job. It lands with batch 8.
- **Residual drift audit and batch 8.** A read-only audit of all 77 btrc findings against `7948af0` (workflow `wf_d0bf72b9-e2b`, 4 agents) found 62 closed, 2 documented exceptions (btrc-D024: lldb and a Linux native compiler provider; btrc-D039, LocalApplicationChannel's hosted includes), 12 partial and 1 open (btrc-D046). Six residual cloud lanes took the rest. Batch 8 (`integ/b8`, on batch 7) lands four:
  - `stage4/residual-stdlib`: D028 `DaemonSpec.renderStartCommand(controlFile, logFile)` takes canonical paths and never rewrites the spec; D052 the eleven `Strings` delegates whose only callers were tests are deleted and the stdlib callers use the built-ins; D053 one `NativeWorker` owner (`Library.BackgroundJobs.NativeWorker`) starts and joins both the background-job worker and the ALSA worker; D060 and D076 fix stale README and macOS comments. The new export re-froze the P0 inventory as `p0-inventory-2026-10-02-native-worker` (324 operations × 6 = 1,944 slots).
  - `stage4/residual-filesystem-outcomes`: D061 one `FileSystemOutcome<T>` replaces the FileSystem open, snapshot and read outcome classes and `ApplicationDirectoryRootsOutcome` (`FileReadOutcome` keeps its data kinds), with the compiler's publication locks moved onto it.
  - `stage4/residual-linux-gui`: D033's Linux half; the Linux GUI fixtures compile against `gui_provider_root` and `GUI/btrc.toml` no longer exports `Linux.*`.
  - `stage4/residual-tests-tools`: D064 four duplicate corpus programs removed; D066 codegen literal helpers, perf and bench get owner classes; D067 the GUI and sgd-render examples use `Example.mk`; D044 shared helpers leave test modules (115 `pytest_plugins` lines gone) and the portable native probes bind their headers.
  - Every renamed or removed public API is in the BTRSmith rename table. Merge fix-ups: batch 7's null guards moved onto `FileSystemOutcome<T>`, the Linux GUI lane's provider data root moved into the shared `linux_provider_fixtures`, and batch 6's C1 integration test imports `diagnostic_identity` from its new harness.
  - Gates: clean (generated-source, lint, format, diff, zero-warning self-host transpiles, `boundary-check` 287 of 311). `src/tests/python`, `src/tests/btrc`, the corpus through both compilers, LSP and formatter: 11,288 passed and 3,165 skipped; the 24 failures were one module that ran before a lint fix restored its `TARGET` import, and they pass on re-run (36 passed, 16 skipped without a display). The bootstrap reached its fixed point.
  - Still open: `stage4/residual-native-importer` (D046, D039) and `stage4/residual-macos-conformance` (D044's macOS programs) are running; D049 lands with `stage4/objc-macro-constants`. The findings ledger in `src/stdlib/README.md` is written after those land.

- **BTRSmith-reported btrc defects (2026-10-03).** The BTRSmith apply lane (`stage4/w2-btrsmith`, `e8a53e2`, pinning btrc `c7f785e`; it waits for the Mac smokes before BTRSmith `main`) reported seven btrc defects; one was already fixed upstream (`03e2e59`). Two lanes took the rest:
  - `stage4/realtime-seam` (landed as batch 10a): the practice mapping scales clip source frames to transport frames on seek, loop and command paths; `render()` honours the block's input/output device frames, stream epoch and discontinuity flags and re-anchors on a new epoch; and the renderer gets a `@realtime`, allocation-free read of the rendered position, play state, speed and mapping generation. Realtime tests through both compilers: 210 passed, 117 skipped.
  - `stage4/btrsmith-defects-compiler` (landed in batch 11): unknown ALL_CAPS names refused at the use site, volatile generated locals across `setjmp` for GCC 15's `-Wclobbered`, and `--emit-units` primary outputs that change whenever any unit does. Its first integration failed two contracts; the lane fixed them in both compilers (`5d1ba4a`, `2114017`): the reference compiler now reports an unresolved name in a `var` initializer before "Cannot infer type", as btrcc does.

- **Batch 11: Stage 4 close-out (`CL-R-00`) and Codex's first branch (2026-10-03).** Three lanes and one Codex draft PR:
  - `stage4/btrsmith-defects-compiler` (above).
  - `stage4/residual-final` closed the re-audit's three partial findings: D044 (`ImageIoCleanup` and `NativeWorkerFailures` bind their fault headers; shared test helpers moved into named harness modules; compiler probes go through `src/tests/c_toolchains.py`), D066 (`HOST_CXX`; perf's default drivers are one toolchain) and D067 (`Example.mk`'s parity comment; `examples/native-package/Makefile` stands alone because the flake's sandbox copies only that directory).
  - `stage4/c-output-parity`: 776 of 977 corpus programs now transpile to byte-identical C through both compilers, up from 224 of 972, and 2,542 of 3,845 module units. `src/tests/fixtures/c_output_parity/identical.txt` pins them (773 after dropping the three programs D064 deleted) and `test_c_output_parity.py` fails if one diverges. It also fixed a btrcc defect: a local struct staged as an assignment operand made `s.field = …` write into a copy. btrcc's `@gpu` CPU fallback now calls the runtime catalog's pre-authored bounds check. What still differs is listed in `docs/design/compiler-parity.md`: batched cycle flushing in collection methods (37 programs, deferred until measured), temporary allocation order (51), generic-instance and type-declaration order (47), operand staging (29) and 21 others.
  - Codex's PR #21 (`CX-UIA-02`, first commit): the UI0 catalog seed `docs/design/native-ui-catalog.toml` (1,620 operation slots and 470 case slots of the frozen 2026-09-21 release), `ui0-source-amendments.toml` pinning the 17 later declarations, and `test_ui0_catalog.py`, the parser-based drift gate.
  - The Stage 4 findings ledger is in `src/stdlib/README.md` ("Drift findings"): 77 btrc findings, 76 closed and D024 a documented exception.
  - Gates: generated-source, lint, format, diff and zero-warning self-host transpiles clean; `boundary-check` 287 of 311. `src/tests/python`, `src/tests/btrc`, the corpus through both compilers, LSP and formatter: 12,314 passed and 3,165 skipped; the 4 failures were the parity manifest's three deleted programs, fixed and re-run (796 passed). Merge fix-ups: c-output-parity's tests use batch 8's shared helper names. The bootstrap reached its fixed point (18 min).

- **Batch 11 CI fix-forward (2026-10-03).** CI on `cdf9d95` failed two jobs, both fixed on `main`:
  - Linux `bench`: `binary.RunArc.bytes` grew from 39,792 to 43,888 (1.10x, past the 3% slack). btrcc now retains, stores, releases and polls the cycle collector on every field store, as the reference compiler already did, so both compilers' C for those stores is identical. That adds 944 bytes of text, and the file grows a 4 KiB page. `ddb6498` re-recorded the linux-x86_64 baseline from that run's artifact (233 metrics, tolerances unchanged).
  - macOS unit: `test_module_unit_link_plans_match_across_compilers` (2 cases) compared whole link plans, which now carry `emitted-unit-digests`, and the program unit's C still differs between the compilers. `972e5ad` checks each digest against its own unit and compares the rest.
- **Batch 12 (2026-10-03).** The C1 exit (`CL-C-01`, Stage 16 above) and `stage19/c-prep` (`CL-C-00`, `CL-C-02`): the C3 vocabulary and goto designs now agree (`GotoStmt(name, name_line, name_col)`/`LabelStmt(name)`, no interim goto refusal, D-13 owned by r15b), and btrc has one lambda termination check, `ControlFlowValidator`'s, so it accepts the five terminating typed lambdas the reference compiler accepts (`test_lambda_termination_parity.py`). Gates: generated-source, lint, format, diff and zero-warning self-host transpiles clean; `boundary-check` 287 of 311; `src/tests/python`, `src/tests/btrc`, the corpus through both compilers, LSP and formatter: 12,350 passed, 0 failed, 3,165 skipped; the bootstrap reached its fixed point (19 min).

- **Batch 13 (2026-10-03): CI for Codex lanes, C4 directive order, the headless GUI shell, the Mac runbook kit and a setjmp-analysis speedup.**
  - `stage30/ci-codex-lanes` (`CL-UIA-02`): `test_ci_workflow_contracts.py` checks workflows by class (core; lane workflows with a paths filter; dispatch-only; tags-only) instead of exact triggers. `ci.yml`, `macos.yml` and `windows.yml` get concurrency groups: a newer pull-request push cancels the older run, while `main` runs never cancel. A `scope` job sorts each pull request as `docs`, `lane` (`codex/*`), `native-gui` (a `focus=native-gui` dispatch) or `full`. Skip-report artifacts are now named `skip-report-<workflow>-<job>[-<matrix>]`. The integrator added the `test-native-gui` Makefile target that the focused job runs (the line `CX-UIA-01` would have carried). Full macOS and Windows runs on the lane were green; cancellation and the per-class job counts prove themselves on the first pull requests.
  - `stage16/c4-directives` (`CL-C-04`): every module unit carries the program's whole directive list in source order, in both compilers. This fixes a unit emitting `#include "lib.h"` before the `#define` it depends on. 909 of 983 corpus programs' module units are byte-identical in btrcc, and the rest differ only in directive order or a checkout path. Under `--module-units` the corpus has 3 failures that the base had too; `CL-REQ-03` owns them.
  - `stage30/headless-gui-shell` (`CL-UIA-21`, `tooling-linux-headless-gui`): the Linux dev shell gains weston, Xvfb, dbus, AT-SPI, GTK4 and GLib development files and PyGObject (about 205 MiB, +4.8%; the Darwin shell is unchanged). `tools/ui/headless-session.sh` starts a Wayland or X11 session with an AT-SPI bus, and `tools/virtual-display.sh` uses it. The GUI provider tests passed 38 of 38 under X11 and under Wayland.
  - `stage5/runbook-kit` (`CL-R-02`): `tools/runbook` is the owner's one-command engine for Mac rounds: the automated quiet check, resumable cells, the `stage4-requal`, `stage5` and `stage13-final` presets, and redacted evidence publication. 174 tests passed; a stand-in container rehearsal ran 9 of 13 cells. Every number still comes from the Mac.
  - `stage18/req02-objc-emitter-transpile` (`CL-REQ-02`): setjmp safety analysis now walks only functions that call `setjmp` and what they consult, in both compilers. The `ObjectiveCEmitter.btrc` test transpile fell from 184 s to 126 s (Python) and from 97 s to 60 s (btrcc), with byte-identical output across 1,227 programs; the test fixture builds once per run.
  - `CL-REQ-01` needed no change (above, Stage 18).
  - Gates, in the batch's own dev shell: generated-source, lint, format, diff and zero-warning self-host transpiles clean; `boundary-check` 287 of 311; `src/tests/python`, `src/tests/btrc`, the corpus through both compilers, LSP and formatter: 12,519 passed, 0 failed, 3,144 skipped; `make test-native-gui`: 101 passed, 0 failed (its skip gate flagged 4 Linux audio-session skips because this container has no ALSA default device, which the CI image has); the bootstrap reached its fixed point (16 min).

- **Batch 14 (2026-10-03): the C4 spec commit, module-unit corpus fixes, the Stage 22 doc close-out.**
  - `stage16/c4-spec` (`CL-C-03`, `ccompat-r18-spec`): the shared spec `src/language/targets.toml` and its `TargetManifest` generator, with generated target tables in both compilers and no behavior change. `btrc.symbols` and the LSP catalog are byte-identical. The target union is vacuous until `CL-C-05` parses per target.
  - `stage18/req03-module-unit-corpus` (`CL-REQ-03`): the corpus under `--module-units` now passes in both compilers (1,960 passed). The reference compiler lowers a simple enum's `toString` as an if-chain, as btrcc does, because a `switch` broke when two members share a value. `stdlib/ChildProcessClosedFds` includes `<sys/resource.h>` itself. `test_module_units.py` guards both cases.
  - `stage22/doc-closeout` (`CL-P1-01`): `platform-parity.md` section 8 and `native-ui-parity.md`'s review checkpoint record D6(c) and D27: one contract owner (Claude), with the bucket 3–4 platform lanes split between the agents.
  - BTRSmith's pin bump (`CL-R-01`, BTRSmith `stage4/pin-bump` at `49a23af`, pinning `cdf9d95`) is done on Linux. Its MVP suite fails the 11 qualifying-column tests plus NativeAudioSessionOwner, which needs an audio device; Json and sqlite-library-root now pass. Both frontends pass application-frontend-check, linux-product-check and the library smoke. The macOS targets wait for `MAC-R-01`. It found two compiler changes the rename table had missed, now in `docs/design/btrsmith-rename-table-w2.md`, and a `btrc-format` defect (`CL-REQ-04`).
  - Gates, in the batch's own dev shell: generated-source, lint, format, diff and zero-warning self-host transpiles clean; `boundary-check` 287 of 311; `src/tests/python`, `src/tests/btrc`, the corpus through both compilers, LSP and formatter: 12,557 passed and 1 failed, `test_numeric_comparison_c11`, which counted the comparisons of the reference compiler's new enum `toString` if-chain and now counts only its subject function's; `make test-native-gui` 101 passed; the bootstrap reached its fixed point (16 min).
- **Batch 13 CI fix-forward (2026-10-03).** CI on `27e48d4` failed one Linux unit test, the quiet check's real-probe test: CI's devcontainer has no `ps`. `438a439` makes the quiet check read Linux's `/proc` when `ps` is missing. The focused `focus=native-gui` dispatches (ci.yml 37117635879, macos.yml 37117637179) were green, so `CL-UIA-02`'s scope job and the `test-native-gui` target work in the CI image and on hosted macOS.

- **Batch 14 CI fix-forward.** `e4f00ce`: the quiet check reads Linux's `/proc` first. CI's devcontainer has a `ps` that cannot run the probe's command, which `438a439` had not covered.
- **Batch 15 (2026-10-03): the formatter fix, reference attribution, the macOS hardware tier.**
  - `stage18/req04-formatter-indent` (`CL-REQ-04`): `btrc-format` indents a wrapped class header's body from the keyword line, for wrapped generic parameters and for an `implements`/`extends` continuation line. The defect came from the BTRSmith pin bump. All 1,550 tracked `.btrc` files format unchanged.
  - `stage6/reference-attribution` (`CL-R-06`): `tools/perf.py --cprofile` rolls a reference-compiler profile up by owner and phase, and the runbook gains an `attribution` result kind and the `stage6-reference` preset. A stand-in run attributed 93.0%; the Mac run on the BTRSmith pin is owed (`MAC-R-03`).
  - `stage38/macos-hardware-tier` (`CL-R-36`, `qualification-ci-macos-native-suite`): GitHub's macOS shards now run as `macos-hosted`, with their own expected-skip manifest. A new `hardware` skip category marks the cases only the owner's Mac can run, so hosted shards skip only those. macOS run 37118683472 had 0 unexpected skips. The `covered_by: macos` hardware rules are proved when the Mac's reports arrive.
- **Batch 16 (2026-10-03): CI tiers, the platforms shell, host manifests, the Stage B key spec.**
  - `stage38/ci-tiers` (`CL-R-38`, `qualification-ci-tiering`): `ci/tiers.toml` names seven tiers and the jobs and matrix rows each runs in `ci.yml`, `macos.yml` and `windows.yml`; every workflow's `scope` job classifies the event and plans from it (`tools/qualification/tiers.py`). A push to `main` runs the same matrix as before. A non-`codex/*` pull request outside the full paths now runs only the static job, the unit shard and the corpus shards its paths touch. The new `release.yml` calls all three workflows, nightly at 08:23 UTC (extended tier: adds macOS clang O1 and O3) and on a dispatch or `v*` tag (release tier), and assembles one ledger bundle (`tools/qualification/bundle.py`). The `docs` job is now `static`. A `release.yml` run waits for this push, because GitHub dispatches only workflows on the default branch.
  - `stage23/platforms-shell` (`CL-P1-02`, `tooling-android-sdk-ndk`): `nix develop .#platforms` adds the Android SDK (platforms 29 and 36), NDK 29.0.14206865, the emulator and JDK 17 to the default shell, plus wgpu-native's pinned prebuilt archives; the default shell's derivation is unchanged on all four systems. The licence acceptance and `allowUnfree` stay in that shell's own nixpkgs import. The closure is 17.75 GB; the Mac realization and AVD boots are `MAC-P1-03`'s.
  - `stage10/host-manifests` (`CL-R-23`): `tools/qualification/hosts/` describes the Mac, the GitHub Ubuntu runner and FRACTAL-NORTH (awaiting its probe), and the budget bench records `provenance.host_manifest`. The ledger adapters do not carry it yet.
  - `stage6/stageb-spec` (`CL-R-04`): `docs/design/stage-b-reuse-keys.md` specifies the Stage B reuse key and journal after three review rounds.
  - Push CI on `901728a` was green on all three workflows; a `release.yml` dispatch (run 37140445563) exercised the release tier and the bundle job.
- **Batch 17 (2026-10-03): the owner's UI go-ahead, the Codex UI lanes, the native-GUI gate line.**
  - The owner asked for all the native-UI work to run in parallel across macOS, Linux, iOS/iPadOS, Android and Windows, with Codex doing it. That approved Stage 24's early start (WORKSTREAMS.md §7 Q2, `85f24c3`). A planning workflow (four surveys, a synthesis, three adversarial reviewers) produced `docs/workstreams/codex-ui-lanes.md` (`c166847`), the file Codex's standing goal reads. It finds that only UI0's foundation has landed, that macOS and Linux UI1 can start now, and that the Windows, iOS/iPadOS and Android shells sit behind Stage 24/25 and interop (about 290–350 agent-hours today). WORKSTREAMS.md, the packet docs and `packets.json` were folded to match (`9f33d2c`): new packets `CX-UIA-30`, `CL-UIA-24`, `CL-R-50` and `CL-P2-29`, the Codex CI cap and monitor-and-fix policy, and Q48–Q51 for the owner.
  - `NATIVE_GUI_TESTS` gains `test_native_webgpu_imports.py`, so the focused gate drives the `webgpu_child` fixtures. In the container it ran 100 passed and 1 failed: `test_linux_gui_controls[True-python]` hit an X11 `BadWindow` on `X_ChangeProperty` once under four workers sharing one Xvfb display, and passed 24 of 24 runs alone. That race is open; it belongs to the Linux SDL baseline (`CX-UIA-11`).
  - `CL-UIA-03` (BTRSmith caller map) is BTRSmith draft PR #29: 3,479 call sites, 0 unmapped, 772 GUI sites on 115 catalog operations, five slices and nine workarounds.
  - Push CI on `c2cd745` was green on all three workflows. The `release.yml` dispatch on `901728a` (run 37140445563) ran every hosted job green and uploaded one `ledger-bundle-901728a…` artifact, which meets Stage 38's "one release dispatch produces one ledger bundle".
- **Batch 18 (2026-10-03): the path-selective lane tier, UI ledger releases, the Stage 6 spikes preset.**
  - `stage38/lane-tier-paths` (`CL-R-50`): `ci/tiers.toml` gains named path sets. In the lane tier, the heavy Linux shards run only for stdlib, test-program, example, tool and root-config paths, and the macOS jobs only for macOS, GUI and native paths; `scope`, `static`, `release` and the unit shard always run, and an empty or unlistable change list plans the whole lane. Over 7,228 change lists no other tier's plan changed. A catalog-data Codex PR drops from about 400 Linux and 41 macOS runner-minutes to about 60 Linux and none, and no longer counts against the Codex CI cap.
  - `stage30/ui-ledger-releases` (`CL-UIA-24`): the denominator manifest holds several releases per kind; undeclared slots count against their union, missing ones per release. A `retired` implementation state carries a decision and no evidence. The 2026-09-21 ui-operation and ui-case releases now read their ids from the seed ledger, with unchanged digests (`c08b9a80…`, `1bbc6343…`), so later Markdown edits cannot move them.
  - `stage6/spikes-preset` (`CL-R-05`): the `stage6-spikes` runbook preset for `MAC-R-03`. Six never-merged spike branches (`spike/stage6-{decl,parse,instances,records,visibility,composed}`) keep btrcc output byte-identical on the stand-in fixtures and on self-compile, build warning-free and pass the btrcc corpus. In the container the composed spike cut instructions from 113.09G to 88.05G (−22%) and wall clock from about 18 s to about 14.5 s; about 5.5 s of relowering remains, so no per-file cache reaches 3 s. D12 waits for the Mac's BTRSmith numbers.
  - Push CI on `cd195c2` was green on all three workflows.
- **Batch 19 (2026-10-03): C4 lands; lambda and scope captures.**
  - `stage16/c4-conditionals` (`CL-C-06`, `ccompat-r18-preprocessor-conditionals`): `#if`/`#ifdef`/`#ifndef`/`#elif`/`#else`/`#endif` in both compilers in one paired construct commit, conditioned per target from `targets.toml`'s predefined-macro table, with the module-unit, cache, formatter and LSP cases. An adversarial review (four dimensions, each verified) confirmed ten defects, all fixed on the branch before integration:
    - btrcc ordered the native plan by hash, the reference by name, so P3 and I3 named different headers and packages;
    - B1 was missed after a failed f-string interpolation;
    - the two compilers trimmed different whitespace sets;
    - the reference accepted malformed `\x` character constants;
    - `#if` expansion depth was unbounded (O(depth²) memory), and is now counted toward E16;
    - a dead second macro-name owner remained in btrcc;
    - a native test hard-coded the Linux target;
    - an expected-skip rule rested on a false premise;
    - the formatter refused a file guarding unsupported targets with `#error`;
    - stale documentation.
    The macOS dispatch then caught one stale lexer-contract site, which the integrator fixed.
  - `stage18/req05-lambda-capture` and `stage18/req06-scope-capture` (`CL-REQ-05`/`06`): btrcc no longer drops a lambda or spawn capture whose name matches a global (SB-D9: printed 9 or 10 where 5 was right). Captures follow the scope chain; realtime locals are typed by lexical scope. Static address constants must name file scope, and field initializers never see constructor parameters (both paired). A refused spawn capture now reports at the spawn in both compilers, which closed a pinned divergence. Four older parity gaps are recorded for a later packet.
  - Gate: zero warnings on the three self-host entries; `boundary-check` 287 of 311; 13,199 passed with 0 failures in the broad suite; the bootstrap fixed point in 16 minutes. `make test-native-gui` again hit the intermittent `BadWindow` race in `test_linux_gui_controls[True-python]` under four workers on one Xvfb display (passes alone, absent on GitHub runners); it is filed against `CX-UIA-11` in `codex-ui-lanes.md`.
  - With C4 on `main`, Stage 24 starts under the owner's §7 Q2 approval: `CL-P1-03` (targets.toml schema 2 with the iOS and Android rows) and `CL-REQ-07` (the module-unit staleness defects SB-D1…D8) run as lanes.
  - Push CI on `f431745` was green on all three workflows.
- **Batch 20 (2026-10-04): Codex's first UI wave.** Codex opened eight draft PRs; a review workflow (one reviewer each, an adversarial verifier on the two code PRs) passed seven.
  - PR #22 (`CX-UIA-02` follow-up): `tools/qualification/ui_catalog.py` loads the catalog's per-packet shards (`families.toml`, `operations/`, `cases/`, `surface/`, `evidence/`, `amendments/`), checks admission and the frozen, pending and retired partitions, and reports them. `families.toml` seeds the 300 family cells from the 2026-09-21 matrix (P 48, C 15, M 237). `IFontFace` is in scope (N44, N49). The integrator fixed two defects before the file became a Claude hotspot: later releases got no placeholder slots, and `--kind surface` selected nothing. `ui_catalog check`: 1,620/470/300 frozen, 17 pending ids (170 slots), `GUI.rasterText` retired (10 slots). Catalog wave 2 (`CX-UIA-03`, `04`, `30`, `05`) now branches from `main`.
  - Docs drafts:
    - the UI2 contract drafts `CX-UIA-18`/`19`/`20` in `docs/design/ui-contracts/`, which `CL-UIA-13` reviews;
    - the UI4, UI5 and UI8 pre-drafts `CX-UIB-01`/`02` in `docs/design/native-ui-contracts/`, which `CL-UIB-02` reviews;
    - the Win32, UIKit (with iPadOS) and Android Views shell notes `CX-UIA-13` in `docs/design/native-ui-shells/`.
    The reviewers' minor points are on each PR for those approvals. The UI2 index now links the other two directories.
  - PR #26 (`CX-C-01`) went back to Codex: its unit shard was red (two untimed subprocess calls), and `--btrsmith` silently moved the measurements to BTRSmith main's gate clone instead of the D9 copy.
- **Batch 21 (2026-10-04): Codex's second wave, docs.** A second review round passed eight of eleven PRs:
  - the UI6, UI7 and UI9 pre-drafts and the runtime-probe contract (`CX-UIB-03`/`04`/`05`) and the collection data-model findings (`CX-UIB-06`), which `CL-UIB-02` reviews;
  - the Windows OS-services, native HTTP transport and mobile storage designs (`CX-P2-01`/`02`/`03`), which `CL-P2-01` approves;
  - the GTK4/WebGPU pre-spike findings (`CX-UIA-12`).

  Three went back to Codex:
  - `CX-UIA-09`'s native-shell fixture passes on Linux (X11 and Wayland, both frontends, plain and sanitized) but fails all four macOS rows on a native-handle count after close, its unit shard is red, and its fresh-process restore check cannot fail;
  - `CX-UIA-01` pushed only the runbook;
  - `CX-UIB-07` needs the macOS run the integrator dispatched (37172345932).

  Codex's CI policy now requires the whole unit shard before any code push.
- **Batch 22 (2026-10-04): Stage 24 commit 1a; module-unit staleness.**
  - `stage24/targets-schema` (`CL-P1-03`, Stage 24 commit 1a, no behaviour change): `targets.toml` schema 2 holds the 11 target rows of `platform-target-contract.md` §1.2, including iOS, the iOS simulator and Android, with every column (triples, sizes, sysroot kinds, compiler host, Objective-C, frameworks). It also holds the §1.3 predefined-macro rows (`TARGET_OS_*`, `__ANDROID__`, MinGW). `TargetManifest` enforces every §1.1 rule with one failing fixture each, and the target rows are regenerated in both compilers. clang 21's `-dM` output matches the table for all 11 rows. The `_M_ARM64` row and the `TARGET_OS_*` refusals wait for commits 1b and 1c. CI caught two new generated accessors with no caller yet; the structure test lists them until `CL-P1-04` calls them.
  - `stage18/req07-module-unit-staleness` (`CL-REQ-07`): the eight staleness defects CL-R-04 found (SB-D1…D8) are fixed in both compilers. Module-unit builds now rebuild a dependent group when it depends on any of these that changed:
    - a `@gpu` kernel's body;
    - an inherited `__del__` and its `#line`;
    - a debug default-argument helper;
    - a "never returns" body fact (validation re-asks the answers it relied on);
    - the import order;
    - shared tuple, span and atomic declaration order;
    - instance discovery order.

    A stale `__LINE__`/`__FILE__` default is fixed too. Clean output is unchanged. The keys are coarser than the spec's per-body digests: sound, but they relower more, which is left to `CL-R-18`. CI caught one crash, on members lowered without the frontend, which the integrator fixed.
  - Gate: three zero-warning self-host entries; `boundary-check` 287 of 311; 13,398 passed with 0 failures in the broad suite; `make test-native-gui` 101 passed with 0 failures (four ALSA skips are this container's); the bootstrap fixed point in 16 minutes.
- **Batch 23 (2026-10-04): the UI case map and operation map B.** A third review round passed four Codex PRs and returned three:
  - `CX-UIA-30` classifies all 470 ui-case slots. The baselines are E40 Linux partial, and E46 and E47 missing.
  - `CX-UIA-04` classifies the 80 frozen operation ids of the controls, layout, image and font owners, plus the two pending `IFontFace` ids. Windows, iOS and Android are missing or unavailable.
  - Both keep macOS and Linux cells implemented-unverified: Codex's token cannot download the shared UI0 JUnit artifacts, and the reviewers confirmed every named regression passed in them. Promoting the evidence is a follow-up. `ui_catalog check --strict` passes for both scopes.
  - `CX-P1-02`'s `platform-adaptations.md` is ready for the owner's sign-off. Its 58 inventory cells wait for that sign-off.
  - The iOS, Android and Windows test-host spikes (`CX-P1-04`/`05`/`06`) went back: none committed its workflow, because Codex followed the integrator's over-broad "no CI workflows" wording, now corrected in `codex-ui-lanes.md`. The reviewers also found that Android app mode cannot work with real adb and that the iOS spawn timeout leaks its child.
  - The C2 schema commit (`CL-C-07`) started as a lane. D27 keeps Stage 24 commit 1b from running beside it; the C track is the longer path to the new-platform shells.
- **Batch 24 (2026-10-04): UI operation map A.** `CX-UIA-03` classifies the 81 frozen operation ids of the application, window, view, container, handler, GPU-view, picker and GUI facade owners, plus the 15 pending `IApplication` factories; `GUI.rasterText` stays retired. With `CX-UIA-04` and `CX-UIA-30`, all 1,610 live operation slots and 470 case slots are now classified (macOS and Linux implemented-unverified pending the evidence follow-up; Windows, iOS and Android missing or unavailable). `CX-UIA-05` (the broader surface) and `CX-UIA-07` (the documentation reconcile) remain in Stage 30. Probing it found nine defects on `main`: eight incremental-build staleness cases (SB-D1…D8), which wait for the C4 landing because they touch the module-unit owners, and one btrcc miscompile (SB-D9: an unimported module's same-named global shadows a lambda capture), which `CL-REQ-05` fixes.
  - The macOS run on `a6fec5e5` failed `test_host_gcc_agrees_on_its_own_target`: clang predefines `__ENVIRONMENT_OS_VERSION_MIN_REQUIRED__` on Apple targets, and GCC never does. `bfa950e2` leaves that clang-only name out of the host-GCC comparison; CI, macOS and Windows passed on it.
  - `CL-R-37` (BTRSmith `stage38/btrsmith-ci`, `6658536`) proved the Linux workflows: a warm run bills 50–57 minutes and a cold one about 250, and proving them cost about 1,041 Linux-equivalent minutes on the private repository. They are not green yet. Three product failures on BTRSmith's current tree (`PlayerAudioReconfiguration`, `sqlite_album_catalog`, a silent library smoke) belong to `CL-R-01`. The draft PR waits for those fixes, because every push to it would bill a failing run. The owner should check the plan's minutes against D26 before it opens.
- **Batch 25 (2026-10-04): the C2 schema commit.** `stage17/c2-schema` (`CL-C-07`) is the one serial schema commit for C2 aggregates and the Stage 18 array dimensions. It adds the ASDL, `Node`, IR and grammar forms, and the shape invariant. Both parsers still refuse every new form, so no program's behaviour changes; the C2 lanes from `CL-C-08` turn them on.
  - `sizeof(Node)` stays 760 bytes, and the self-host peak RSS moved by +0.007%.
  - Two AST boundary records were re-captured, because `TypeExpr` now carries inner array extents and outer pointers for C2 and r17.
  - `test_c2_ir_shape.py` (36 tests) pins the new IR shape. The designation constructor waits on the structure test's definition-only list for its first caller.
  - The reviewers' two blocking findings were fixed before the merge: the Python GPU struct rule, and btrc's setjmp pointer flow through designations.
  - One deviation from the spec: the record type rides on the field (`IRStructField.record_fields` / `recordFields`) instead of a record typed as `IRStructDef`, which would have made a retained-collaborator cycle. `c-compatibility.md` records it.
  - Deferred to r17: the inner-extent differences between `strip_outer_storage` and `withoutOuterArray`, the compound-literal kind-range check, and the child-walk order.
  - Gate: the lane ran the whole suite (python 5,941 passed, btrc 4,946 passed, corpus 1,970 passed), three zero-warning self-host entries and the bootstrap fixed point. Its CI run 37195841711 passed the full matrix on the same tree. The integrator re-ran codegen, lint, format, diff and boundary checks.
  - Next: `CL-P1-04` (Stage 24 commit 1b) may now run beside `CL-C-08`, but never beside `CL-C-23`.
- **Batch 26 (2026-10-04): the bucket-2 checkpoint script and the UI0 evidence.**
  - Codex's `CX-C-01` (PR #26) adds `tools/bench/scripts/ccompat_checkpoint.sh`, the one command behind `MAC-C-02` and `MAC-C-09`. It builds both revisions, takes the alternating instruction samples and the quiet-gated budget runs, runs the batch gate, and publishes the BTRSmith pin only after a GREEN gate on a clean `main`. Every failure records RED. The fix round closed all ten earlier findings, and the reviewer and verifier found nothing blocking. Their minor notes all fail closed and go back to Codex as a follow-up.
  - One finding is the plan's, not Codex's: BTRSmith pins btrc by commit inside its flake input URL, so a flake.lock-only bump can never move it. `CL-R-01` moves the input to a branch URL with the lock unchanged.
  - UI0 evidence: Codex's token cannot download CI artifacts, so the integrator promoted the shared UI0 runs (CI 37171132726, macOS 37171133887, both on `1645699f`, 0 failures). 438 operation cells are now passed, 130 on Linux and 308 on macOS across both frontends; 382 are frozen and 56 pending. Every listed regression passed. The 142 case cells whose component tests passed stay partial on purpose, because the case shards record component coverage only. The 274 operation cells with no listed regression stay implemented-unverified.
  - The run headers carry the workflows' creation times, which predate the source audits, so the loader now lets an observation supersede an inventory audit of the same `btrc_revision` regardless of clock order. Every other older-over-newer overwrite still fails.
- **Batch 27 (2026-10-04): the Stage 26 design reviews (`CL-P2-01`, first round).** Two adversarial reviewers and one parity reviewer read each Codex design. A verifier then tried to refute every blocking finding. None of the three is approved yet; the findings are posted on the Codex PRs, and Codex revises each in a docs-only PR.
  - `windows-os-services.md` (`CX-P2-01`, PR #37), 7 blocking findings:
    - SDK-reader bindings inside btrcc's own import closure break the Windows btrcc build, and they add a second process-launch owner;
    - first providers on IO, Process and FileSystem with only a Windows filter make those imports fail on iOS, Android and windows-aarch64-msvc;
    - nothing can link `ole32` or `bcrypt`;
    - the 128-bit Windows file identity does not fit the 64-bit device/inode carrier that the traversal and lock checks rely on;
    - the named-pipe endpoint and identity protocol is unspecified;
    - executable resolution is unspecified, so `CreateProcessW`'s search order and its implicit `cmd.exe` reopen shell injection;
    - a tag-blind reparse refusal breaks ordinary Windows 11 folders, and `:` can select an alternate data stream.
  - `http-transport.md` (`CX-P2-02`, PR #39), 5 blocking findings:
    - loading HTTPClient pulls in a native transport, which breaks the HTTP corpus and `test-c11`;
    - redirect and credential origin checks run in portable code that has no URL parser;
    - `HTTPServer.start` has no channel for the diagnostics the design requires;
    - there is no client request-header policy;
    - the Windows test-CA fixture cannot run unattended on a hosted runner.
  - `mobile-storage.md` (`CX-P2-03`, PR #36), 1 blocking finding: appending to `FileSystemErrorKind`, or a mobile branch in the root resolver, changes btrcc's own C on every host. The design routes that to a Codex packet under a gate weaker than WORKSTREAMS §3.4.
  - The reviews list 19, 12 and 13 requests to Claude (link plans, launch seam, harness changes, the URL parser and others). They become scope for `CL-P2-02`, `03`, `04` and `14` when the designs are approved.
  - Assumed adaptation defaults are listed on each PR, because the owner's sign-off on `platform-adaptations.md` is still pending.
- **Batch 28 (2026-10-04): the UI catalog in the qualification report.** `stage30/ui0-report` finishes `CL-UIA-24` step 4 and `CL-UIA-05` step 5.
  - The 2026-09-21 family-cell release now reads its ids from `native-ui-catalog/families.toml`, with the same 60 ids and the same digest (132b05e6…), which the reviewer recomputed.
  - `make qualification-report` renders a UI catalog section from the catalog's own counts: per kind the frozen, pending and retired partitions, classified slots and evidence statuses per platform and frontend, retired operations, and surface rows. With the catalog present, the UI denominators are counted once, by the catalog.
  - The reviewer and the verifier found nothing blocking. The integrator fixed two minor defects they found, each with a test that fails without the fix: a custom `--denominators` manifest's UI releases were silently dropped, and a malformed stdlib package manifest ended in a traceback instead of exit 2.
  - Behaviour change: with no skip reports, `make qualification-report` now exits 0 and renders the catalog section; before, it exited 2 with "nothing to report".
  - A planning note for a second family-cell release: families.toml is now both the base release's source and the only classification shard, so the base must be re-pointed to a `{list}` first.
  - `CL-P1-07` (the hosted-platform extractor) went back to its lane. Its conservative windows-aarch64-msvc table kept MinGW-only POSIX macros and `struct timezone` available, which breaks §2.3's "only refuse too much" rule. The integrator also decided:
    - stdlib-declared names such as `environ` count as declared wherever the libc exports them;
    - the Linux rows use zig's default glibc floor, not the host's;
    - struct members count as declared.
  - Codex's repaired accessibility prototype (`CX-UIB-07`) got its one native macOS run: 37217909473.
- **Batch 29 (2026-10-04): Stage 24 commit 1b, one target owner per compiler.** `stage24/target-owner` (`CL-P1-04`) adds `TargetRepository` in Python and `FePackageTarget` in btrc, both over the generated target rows.
  - Both compilers accept the same 30 spellings (11 labels plus the `x64`/`arm64` and `-gnu` aliases) and reject everything else with the same §1.5 message, at the same point: arguments, then target, then input.
  - Host inference returns only compiler-host rows. `--target ""` and a repeated `--target` are errors. Release names come from the compiler-host rows, which adds `windows-arm64`. btrcc keys its caches by the canonical label, so old entries go unused but are never misread.
  - `architectureAliases()` and `defaultEnvironments()` now have callers.
  - CI, macOS and Windows passed on the lane head, and the lane ran the bootstrap and three zero-warning self-host transpiles. Two reviewers and a verifier found nothing blocking.
  - Deferred to `CL-P1-05`, whose packet now owns it: both compilers still choose macro rows by operating system and architecture only. So the three newly accepted non-host rows get wrong `#if` values:
    - `ios-aarch64` gets `TARGET_OS_EMBEDDED=0` and `__APPLE_EMBEDDED_SIMULATOR__`;
    - `ios-aarch64-simulator` gets `TARGET_OS_SIMULATOR=0`;
    - `windows-aarch64-msvc` gets the MinGW macros.

    Nothing reaches this today. No source branches on those macros, and nothing selects those rows by default. 1c must land before the sub-batch 1 gate.
  - The integrator corrected the targets.toml comment to name 1c and updated three docs that still said `--target OS-ARCH`. Minor follow-ups are listed in the review:
    - the help text hard-codes the alias list;
    - btrc hard-codes the predicate vocabulary;
    - a non-UTF-8 `--target` gives a Python traceback;
    - argparse accepts `--target=X` where btrcc does not;
    - link plans drop the environment until schema 5.
  - `btrc-format` no longer removes the space after `;` when a `for` clause opens with `(`. BTRSmith's lane reported it.
  - BTRSmith (`CL-R-01`, `stage4/pin-bump` `8204b8a`):
    - The three Linux failures were out-of-date tests and a make recipe that hid the binary's exit status; none was a btrc defect.
    - Two flaky harness tests were also fixed: ToneRealtimeProcessor, and the AsyncLibraryScanReconfiguration cancel race.
    - The btrc input now follows a branch URL with the lock unchanged.
    - Only the 10 remaining qualifying-column tests stay red on Linux, plus `NativeAudioSessionOwner`, which needs a real audio device.
    - `CL-UIA-03`: 3,479 BTRSmith call sites map to the catalog with 0 unmapped; all 115 GUI operations and 38 cases are classified.
    - The BTRSmith CI pull request (`CL-R-37`) still waits: the qualifying-column tests keep its runs red, and every run bills minutes.
- **Batch 30 (2026-10-04): the native-shell fixture and the rest of the focused GUI gate.** Two Codex code PRs passed a reviewer and an adversarial verifier with no blocking finding.
  - `CX-UIA-09` (PR #40), the UI1 shell fixture: one portable `NativeShell.btrc` scene drives a window, a field, a button, a scroll view of 50 labels and a GPU view through 100 open and close cycles and 100 fresh-process restores. Probes count the provider-created objects, which must reach zero on every cycle.
    - On macOS, an AppKit probe tracks provider objects separately from AppKit-private views, and four AX/wheel A/B processes must also pass.
    - On Linux, an SDL probe runs under X11.
    - The Windows row asserts the exact "no provider" message.
    - CI, macOS (native-gui 252 passed, all four macOS shell rows run) and Windows were green on head `517032a`.
    - Wayland: 8 of 9 passed. Restore 56 timed out inside libdecor's GTK plugin. That case and the X11 BadWindow race go to `CX-UIA-11`.
    - The four macOS shell rows add time to the macOS unit shard.
  - `CX-UIA-01` (PR #33), the rest of the UI0 focused gate: the agent runbook, `tools/ui/codex-setup.sh`, and a coverage test that every native GUI test is in `NATIVE_GUI_TESTS`. It passes with #40's new shell tests on the merged tree.
  - Locally, the skip-ledger tests fail when `TMPDIR` lies inside the checkout, because their node ids become repository-relative. The batch gates now keep `TMPDIR` under `~/.cache`.
- **Batch 31 (2026-10-04): the hosted-platform extractor, and the first approved Stage 26 design.**
  - `CL-P1-07` (`stage24/hosted-platform-extractor`) adds `tools/hosted_platform.py` (`HostedPlatformExtractor`) and its test. It produces the seven Linux, MinGW and NDK unavailability fragments that `CL-P1-08` copies into `hosted_abi.toml`. They are on the never-merge branch `stage24/hosted-platform-fragments` (`1020307`).
  - Two review rounds sent it back:
    - **Round 1.** The conservative `windows-aarch64-msvc` table kept MinGW-only POSIX macros and `struct timezone` available.
    - **Round 2.** It also kept the dllimport objects `daylight` and `tzname`, and the Apple text dump missed inherited availability.
  - The final rule keeps a name on the MSVC row only if ISO C11 declares it in a UCRT-shared header, or the Windows API declares it as the same kind. Over-refusal is allowed until the runner extraction. A verifier mutation-tested both fixes.
  - Integrator decisions:
    - `environ` counts as declared through the stdlib's own `extern` on every row but MSVC;
    - the Linux rows use zig's default glibc floor (2.31);
    - struct members count as declared;
    - a name is refused only if every declaration is unavailable.
  - Integrator corrections to `platform-target-contract.md` §2.2, §2.3 and §2.5 and to the `CL-P1-07`/`08` packets:
    - bionic r29 has no `explicit_bzero` at any API level;
    - it declares the C11 `<threads.h>` names at API 29 as static inlines;
    - the probe and the declared rule are written down;
    - `CL-P1-08` gains the MSVC must-refuse names and `environ`.
  - Hand-off to `CL-P1-08`: the ISO set comes from the host's libc, so the extractor must run on a Linux host. A Darwin host would reopen the leak. Run the ISO probe through zig with a fixed Linux target, or refuse a non-Linux host, before anyone reruns it.
  - `CL-P2-01` round 2 reviewed Codex's three revisions at `854f33f`, `3d962e0` and `eb8a6e9` with a resolution check, a fresh adversarial review and a verifier:
    - `mobile-storage.md` (`CX-P2-03`, PR #50): approved under the standing design-approval rule and merged in this batch. The round-1 blocker is resolved: btrcc-C-changing pieces now go to Claude landings under the full §3.4 gate. Its 11 non-blocking items and 10 requests to Claude are on the PR; the requests become scope for `CL-P2-14` and the storage landing. It assumes adaptation defaults that wait for the owner's sign-off on `platform-adaptations.md`.
    - `windows-os-services.md` (`CX-P2-01`, PR #52): all seven round-1 blockers are resolved:
      - the btrcc import closure reads no headers;
      - an 11-row provider matrix;
      - a system-library request;
      - a 192-bit file identity;
      - the named-pipe protocol;
      - executable resolution that refuses batch files;
      - the reparse grammar.

      One new blocker remains: the Daemon supervisor executable has no build, bundle or trusted-location mechanism.
    - `http-transport.md` (`CX-P2-02`, PR #51): all five round-1 blockers are resolved. Two new blockers:
      - the frozen client validation lets providers send different requests, and Android silently turns a GET with a body into a POST;
      - the Windows row cancels synchronous WinHTTP requests with `WinHttpCloseHandle`, which Microsoft forbids.
- **Batch 32 (2026-10-04): the UI evidence host map and the 100,000-record fixture.** Two Codex code PRs passed a reviewer and an adversarial verifier with no blocking finding.
  - `CX-UIA-06` (PR #49) adds `native-ui-catalog/hosts.toml` (schema `btrc.ui-hosts/1`), its validator test, and `tools/ui/linux-desktop-check.sh`. The routes map each platform's UI evidence to a hosted runner, an owner device or a stand-in.
    - The data is correct today, but the validator can be fooled. It accepts a physical Windows route pointed at the owner's Mac, because runner and `device_id` are not tied to the platform and the stand-in check trusts the route's own `kind`.
    - Codex's follow-up must tie them together, and fix three more problems:
      - the Android owner-emulator and GitHub iOS simulator blockers are wrong;
      - the runner ids differ from the qualification ledger's (`github-linux` against `linux-devcontainer`);
      - recording `MAC-UIA-01` will need a probe field.
  - `CX-UIB-08` (PR #48) adds `CollectionRecords.btrc`: a deterministic 100,000-record generator with a frozen digest (3,974,541 bytes, `37f91c9b…`), checked through both compilers.
    - After the edit schedule, 989 sort keys repeat. Titles have only 8 distinct strings.
    - `CX-UIB-28` must pick a tie-break, or richer titles, before it consumes the digest.
  - `CX-P1-03` (PR #53, the Windows ARM64 lane) went back to Codex:
    - its workflow is missing, so none of its five acceptance items is met;
    - every native path depends on unintegrated PR #43;
    - its VsDevCmd capture quotes `cmd.exe` arguments wrongly and fails on a real runner.
- **Batch 33 (2026-10-05): the C2 shared owners.** `CL-C-08` (`stage17/c2-shared-owners`) lands the one commit every C2 construct lane builds on. Two review rounds sent it back. The first added the union zero-fill guard, the divergence record and stricter contract scans. The second, test-only, closed the last gap in the record scan.
  - **Record members.** `TypeSystem` and `SemanticTypeSystem` own every read of a record's members: its declarators, its direct members, its named members flattened through anonymous members with their member paths, and its fields. 33 btrc and 21 Python struct-field walks, the LSP's `symbols.py` among them, now go through the owner. `test_record_member_owner_contract.py` scans both compilers for raw member-list reads. The Python scan trusts no receiver name. A subscript, a slice or an `in` test counts, because a `StructDecl`'s list supports all three. Only `.get/.items/.keys/.values` reads, which a list lacks, are exempt, and every other read is listed with its reason and count.
  - **Initializer slots.** `plan_initializer_slots`/`planInitializerSlots` maps each brace element to a member path: positional order, a union's first member, an anonymous member as one braced slot, and designator chains. The analyzers record the plan; every reader goes through the owner, which re-plans identically what validation never saw (generic bodies, replayed module units). Static zero-fill moved into the owners and pads no union member. `test_initializer_slot_owner_contract.py` rejects a method that pairs elements with members outside the owner, including through a returned list or a slice.
  - **Integer constants.** Both compilers already answered "not a constant", "a constant btrc cannot evaluate" or a value. The Python evaluator now follows btrc's `long long` rule for overflow, shifts and casts. `test_integer_constant_query_parity.py` checks 37 probes. It pins five known divergences (`errno`, a lowercase source macro, `(Color)1`, `7 / 0` in a case label, `enum Other { X = RED }`), plus two Linux-only ones from btrc reading float literals with `strtold`. `CL-REQ-09` removes the two Linux-only ones.
  - **Evidence.**
    - No accepted program changes: a verifier found byte-identical C for 262 struct-heavy corpus programs through both compilers.
    - CI 37243013814 green on `55f9fa5`. One `c11-clang-O2` runner was lost before any test ran and was re-run once.
    - Bootstrap fixed point; zero-warning transpiles of all three entries.
    - The lane ran the corpus through both compilers: 1,970 passed.
    - The integrator re-ran lint, format, the codegen and boundary checks, the transpiles and the contract tests on the merged tree: 352 passed.
    - Peak RSS of btrcc compiling itself: 2,556,668 → 2,562,752 KiB (+0.24%, inside the 0.3% gate). The verifier traced the growth to about 260 more lines of compiled input, not to the recorded plans: btrc's own sources declare no struct.
  - **Hand-offs:**
    - r10 owns the C11 6.7.9p17 continuation rule and the constant query for designated index steps;
    - r08 and r10 must handle `AnonymousMember` where Python reads `member.type` (`collections.py` `plan_brace`/`plan_static`, `aggregates.py`, `classes.py`, btrc `staticInitializerPadding`);
    - plans retain their record and initializer, and the per-element plan lookup is O(n²), for later performance work;
    - folding object-like source macros was not done.
  - The LSP test `test_server_hardening.py::test_uncached_feature_compute_serializes_with_validation` fails intermittently on this commit and on its parent. It is not this change.
- **Batch 34 (2026-10-05): Linux SDL shell evidence, and a macOS skip-gate fix.**
  - **Fix pushed first (`3078b3d1`).** Batch 33's macOS run failed its skip gate: CL-C-08's two `strtold` platform-divergence tests skip off Linux x86-64, and the lane never ran macOS CI. Both macOS expected-skip manifests now expect them (`c2-strtold-platform-divergence`, covered by `linux-devcontainer`). `CL-REQ-09` removes the tests and the rule.
  - `CX-UIA-11` (PR #55) records the Linux SDL native-shell proof in `native-ui-catalog/evidence/ui1-linux.toml`. A reviewer and an adversarial verifier found nothing blocking.
    - X11 passes 4 of 4 rows. Wayland passes 3 of 4: selfhost with sanitizers times out at restore 61. The bounded `LibdecorPending` probe traces that to a libdecor 0.2.5 dispatch stall, and the PR files a dependency request.
    - The X11 clipboard crash (`BadWindow`, opcode 18) is reproduced by `ClipboardRequestor`: SDL writes to a requestor window that has already been destroyed. The fix goes to the pinned SDL dependency. Per-worker Xvfb displays are an integrator-side mitigation to weigh.
    - E40 is real: the Linux provider's `pumpEvents` drops the 4,097th queued event (keys, key release, committed text and close) in both compilers. 4,095 and 4,096 events pass; 4,097 and 8,193 fail. The reproduction stays on the never-merge branch `codex/cx-uia-11-e40-repro` (`bbe4f56e`) until `CX-UIA-23` repairs the provider (D24).
    - Follow-ups for Codex on the PR:
      - The E40 records put prose in `observed`, which should hold the outcome word (`failed`), so the generic ledger rollup does not count them as failed. The catalog's own counts are unaffected.
      - The probes are manual and never built in CI.
      - `LibdecorPending` arms its watchdog only around the dispatch call.
      - Both probes put required calls inside `assert()`.
      - The accessibility "dump" is a fixed probe string, not an AT-SPI tree.
  - `CX-UIA-10` (PR #54, macOS AppKit accessibility and key-view evidence) was returned. Its hosted evidence is genuine and the TOML matches it value for value. But the AX gate passes without the Commit button, because the window's close, zoom and minimise widgets and the scroller parts also report `AXButton`, and `identity()` never maps an `NSCell` to its `controlView`.
  - `CL-REQ-08` (btrcc tuple typedefs for tuple types spelled only at file scope) was returned. It fixes 11 of 16 failing programs and its default output is safe. But under `--no-dce` it now emits unsubstituted generic tuple structs (`struct btrc_Tuple_U_char { U _0; … }`). The lane will also walk generic instances' method signatures and bodies under substitution, which Python already does. On merge it needs one `GENERIC_WALK` line in the record-member contract.
- **Batch 35 (2026-10-05): the Windows native test host, its workflow, and a VS Code Windows cleanup fix.**
  - **Fix pushed first (`ae63edaf`).** Windows CI on batch 34 failed `Windows command-script servers launch through an owned process`: a command script's descendant outlived the language-server session. `ProcessTree` gave `taskkill /T /F` the whole 1 s stop budget. When taskkill overran it on a loaded runner, the extension killed taskkill mid-walk and then killed only the direct child, and Windows does not reparent orphans. The test's 5.3 s duration matched that path. Now a taskkill still running at the deadline finishes in the background and keeps ownership of the tree; if it fails later, the root is killed once. Four fake-host tests cover every outcome on every platform, and the slow-taskkill test fails on the old code. The extension's typecheck and suite pass: 77, with 2 Windows-only skips.
  - `CX-P1-06` (PR #43): Codex's native Windows test host. A reviewer and a security and robustness reviewer found nothing blocking; the diff stays inside `tools/target_hosts/windows/`.
    - **Executor:** a gated Python launcher is assigned to a kill-on-close Job Object before it starts the target. It records byte streams and maps NTSTATUS crash codes.
    - **Bundle builder:** two C fixtures and two corpus programs, through both compilers, for x64 and ARM64. That is six PE executables and 16 cases, with a receipt that binds btrcc's SHA-256 to its compiler inputs.
    - **Checker:** it relocates the bundle through paths with spaces and non-ASCII characters, requires the runner's native machine to match the PE, and checks tree death independently.
    - Its portable suite passes 48 of 48 and the skip gate is clean.
    - None of its three acceptance items could run before this batch, and the PR correctly leaves them unchecked.
  - The integrator added `.github/workflows/host-windows.yml`, the PR's REQUEST (Codex may not edit workflows). It is a lane workflow on `push`/`pull_request` path filters plus `workflow_dispatch`, and `test_ci_workflow_contracts.py` passes 72 of 72.
    - **`bundle` job (`ubuntu-latest`):** the portable tests and skip gate, `make btrcc`, the provenance receipt, then both cross-built bundles as artifacts.
    - **`native` job:** runs each bundle on `windows-latest` (x64) and `windows-11-arm` (ARM64), never emulated.
    - Its first run on this push is the packet's native evidence.
  - Follow-ups for Codex before `CL-P1-17` freezes the protocol or `CX-P1-07` runs the corpus:
    - The status file and `request.json` sit in the target's own cwd, so a program can forge its exit status.
    - `prepare()` is not atomic.
    - Admission pins only case names, programs and policies; argv, expected outcomes, deadlines and the executable mapping come unchecked from the manifest.
    - Executable admission ignores the file extension.
    - Captured streams have no size cap.
    - The gate shares the host console.
    - The receipt checks btrcc's hash but not that the source revision matches the checkout.
- **Batch 36 (2026-10-05): macOS accessibility evidence and trusted evidence routes.** Batch 35's push CI is green on all four workflows: CI, macOS, Windows, and Host Windows (16/16 native on x64 and ARM64).
  - `CX-UIA-10` (PR #54, round 2). The round-1 blocker is fixed:
    - `ShellProbe.m` maps each `NSCell` to its `controlView`;
    - `summarize_macos_shell` requires the fixture's field, button (titled Commit) and scroll nodes by identity;
    - a negative case removes only the Commit button from a tree that keeps the window's own `AXButton` widgets and scroller parts.
    - **Mutation checks:** reverting the gate fails four tests. On the real hosted trees, the old validator accepts a tree without the button and the new one rejects it.
    - **Other fixes:** the probe now records the application-active and key-window state before each Tab. All 300 contexts were inactive, so Tab delivery stays unproven and is recorded as such. Private survivors are bounded at one, and the records use exact pytest node ids.
    - **Integrator commit:** applied the PR's verified promotion patch, so the four test records now cite the fixed-gate run (artifact 11354918053, merge `25a160f7`). The verifier checked every promoted value against the downloaded artifact.
    - **Follow-ups:** identity mutations for field and scroll; `ax_exposed` still compares raw views; the slot keys carry frontend and variant values the JUnit adapter does not emit.
  - `CX-UIA-06` follow-up (PR #56) binds the UI evidence routes to trusted runners and devices, and fixes the four problems from batch 32. A reviewer found nothing blocking.
  - **Returned:**
    - `CX-P1-03` (PR #53). Nothing has run on `windows-11-arm`, and it duplicates `tools/target_hosts/windows` (a second, weaker Windows process owner). It must build on main's host. The integrator will add `windows-arm64.yml`, already drafted and contract-checked, when integrating.
    - `CL-P2-01` round 3 of `CX-P2-01` (PR #52). The round-2 blocker is mostly resolved: a sibling supervisor image, a leaf build with its digest bound into the consumer, and a trusted path. Four new blockers, each confirmed by a verifier:
      - the supervisor's side of READY/COMMIT/ACK has no runtime API or wire format;
      - Daemon now needs two tokens, but the Unix control record holds one;
      - mandatory breakaway fails under the repository's own Windows executor, whose job omits `BREAKAWAY_OK`;
      - the "wrong-machine" PE rule is undefined and would refuse executables Windows runs under emulation.
    - `CL-P2-01` round 3 of `CX-P2-02` (PR #51). Both round-2 blockers are resolved on the request side. Eight confirmed blockers remain, mostly on the response side:
      - HEAD, 204 and 304 have no response rule;
      - interim 1xx responses are undeclared;
      - duplicate `Location` fields are followed differently by each provider;
      - WinHTTP's 64 KB raw header limit fires before the portable bound;
      - libcurl's threaded resolver blocks cancellation during DNS;
      - Android drops a cancel that arrives before connect;
      - `Proxy-Authorization` is routed differently per provider;
      - the default `Content-Type` differs per provider.
- **Batch 37 (2026-10-05): btrcc tuple typedefs.**
  - **What it fixes.** `CL-REQ-08` (`stage18/req08-static-tuple-typedef`, round 2) fixes a btrcc bug: btrcc dropped the typedef of a tuple type spelled only at file scope, while Python handled every case. Affected positions:
    - globals and statics, including nested tuples and arrays of tuples;
    - typedef targets and struct fields;
    - `sizeof` and cast operands, C-for initializers, property bodies, lambda captures, enum values and array sizes.

    Before the fix, btrcc's C failed to compile for 11 of 16 repro programs.
  - **Round 1 was returned.** Under `--no-dce` it emitted unsubstituted generic tuple structs (`struct btrc_Tuple_U_char { U _0; … }`).
  - **Round 2** adds `TupleShapeScan`:
    - btrcc skips generic class, method and interface bodies, and walks each instance (`classPlans`/`methodPlans`) under its substitution and instance context, as Python's class and method views do;
    - neither compiler records a shape that still names an unbound type parameter.

    Generic instances' method signatures, bodies and field initializers now get their typedefs: those valid programs used to emit C that does not compile, while Python's compiled. The record-member contract lists the collector's child walk as a `GENERIC_WALK`.
  - **Evidence:**
    - `test_tuple_typedef_parity.py`: 18 cases, each with and without `--no-dce`, with identical C and run under strict gcc and clang;
    - three new corpus programs;
    - CI 37315573953 and macOS 37315578714 green on `5556e2cf`;
    - bootstrap fixed point; corpus 1,976 passed.
  - **Integrator review.** A second adversarial review found nothing blocking in round 2. These pre-existing gaps remain, each needing its own packet:
    - btrcc infers tuple shapes only for unannotated `var` initializers, with an empty variable map, so tuples first met as an expression's type get no typedef;
    - under `--no-dce`, btrcc emits uncalled generic-instance methods, which fail `-Werror=unused-function`;
    - btrcc cannot infer generic-method arguments inside f-strings or nested generic calls;
    - polymorphic recursion through a tuple hangs both analyzers;
    - btrcc accepts a global `var` tuple, which Python rejects;
    - both compilers reject indexing an array of tuples;
    - `sizeof(arrayVariable)` parses as a type.
  - **Returned the same day:**
    - `CL-REQ-09`: Python's new exact-rounding `float_value` crashes past 4,300 digits and hangs on `0e99999999f`;
    - `CL-C-13`: six blockers, all confirmed by a verifier:
      - a ternary copy of a FAM struct is accepted and memory-unsafe, as are list-literal elements of FAM type;
      - `new G<struct S>()` and `sizeof` of generic or tuple operands are accepted, and their C fails strict C11;
      - Python refuses hosted-ABI element types such as `uint8_t`;
      - a FAM struct named `T` or `K` breaks valid generic code, including stdlib `Map`.
- **Batch 38 (2026-10-05): Linux shell evidence follow-up.**
  - `CX-UIA-11` follow-up (PR #57). A reviewer found nothing blocking, and every batch-34 follow-up is fixed or disclosed:
    - The 18 E40 records now say `failed` in `observed`, and their detail moved to `reason`. The generic ledger rollup now counts 21 Linux failures instead of 3.
    - `LibdecorPending` arms its watchdog before connecting.
    - Both SDK probes use an NDEBUG-safe `REQUIRE` instead of `assert()`.
    - The clipboard probe compiles in CI.
    - Reference-frontend rows drop the btrcc `compiler_digest`.
    - `LibdecorPending` is still not compiled in CI, because `libdecor-0.pc` is missing from the dev shell; a request is filed.
  - **Integrator action.** Kept `bbe4f56e` reachable on the branch `evidence/cx-uia-11-e40-repro` (the proxy refuses tags). The E40 reproduction records cite it, so the evidence stays verifiable after the never-merge branch goes.
  - **Main CI.** Linux CI on batch 37 (`dd434efb`) was cancelled twice before any test ran ("job was not acquired by Runner of type hosted"). After the one re-run allowed, a fresh `ci.yml` dispatch (37379709059) is the gate. Windows passed.
  - `CL-C-09` (unions) went back with ten blockers, each confirmed by a verifier:
    - The alias rows let `Vector<struct P>` and `Vector<P>` diverge between the compilers. Python accepts them and emits two C types; btrcc refuses. Tuples spelled with a tag regress the same way, and so do function pointers that mix the two spellings.
    - btrcc skips the wrong-keyword check on `new`'s generic arguments.
    - Identity-typedef diagnostics diverge.
    - A tag reference is matched against every top-level name, so a function named `timeval` forces an import for `struct timeval`. Main accepted those programs.
    - Union diagnostic wording differs between the compilers.
    - btrcc drops the second element of a union brace initializer passed as an argument or assigned.
  - `CL-P1-05` (Stage 24 commit 1c, plus environment-aware macro selection) started on `stage24/target-data-model`.
- **Batch 39 (2026-10-06): Codex's own plan.** PR #59 (`CX-PLAN-01`, docs only) adds [CODEX.md](../../CODEX.md), Codex's stdlib lane: six Linux repairs and the macOS alignment repair as `CX-STDLIB-01`…`05`, then independent platform slices. It also adds D28 and the owner update to the roadmap, and hands the plan migration to Claude.
- **Batch 40 (2026-10-06): the roadmap moves to CLAUDE.md (D28).**
  - **What moved.** The roadmap that was `PLAN.md` is now [CLAUDE.md](../../CLAUDE.md), a regular file that imports AGENTS.md first, so every Claude session loads the shared rules and then the plan. The Progress log moved here verbatim (117 KB), which keeps CLAUDE.md small enough to load in every session (137 KB). `PLAN.md` stays as a pointer: every old heading keeps its anchor and links to where its text now lives, so `PLAN.md Stage N`, `PLAN.md D14` and the `PLAN items:` ids in older documents keep their meaning. `docs/design/plan-reference.md` is unchanged.
  - **Tests.** `test_device_registry.py` and `test_native_ui_hosts.py` read CLAUDE.md. `test_ci_workflow_contracts.py` now requires CLAUDE.md among the Markdown files tests read, and checks that CODEX.md and this record stay docs-tier. No workflow changed: CI's test-read pattern already matched CLAUDE.md.
  - **D28 reconciliation.** WORKSTREAMS.md, the Codex packet files, the UI lane notes, the runbook, the packet-report template and the catalog README now say that CODEX.md is Codex's queue and WORKSTREAMS.md keeps the path claims and protocol. Codex creates no workflow file, and the four-push limit became "batch corrections". Existing-interface repairs taken out of `CX-UIA-23`, `CX-UIA-27`, `CX-UIB-18`, `CX-UIB-26` and `CX-UIB-31` run now as `CX-STDLIB-01`…`05`. Old packet ids stay for traceability.
  - **Codex's active assignments** moved into CODEX.md, each with its owner, prerequisite and next acceptance: PRs #58, #53, #51/#52, #42, #34 and #35, the `CX-C-01` and `CX-UIA-10` follow-ups, the `CX-UIA-11` residuals, `CX-P1-02` and the carried items. The catalog-partition assertion and the Windows SDK qualified function type wait on Codex's minimal repros before Claude opens their paired fixes.
- **Batch 41 (2026-10-06): the X11 clipboard crash behind the flaky Linux GUI test.**
  - **Cause.** `test_linux_gui_controls` failed now and then on Linux CI and in local shards with an X11 `BadWindow` (opcode 18, `X_ChangeProperty`). SDL 3.4.10 answers a clipboard request by writing to the requestor's window, and when that window is already gone, Xlib's default handler exits the process. Parallel test workers share one X display, so one test's short-lived clipboard reader could kill another test's window. Every btrc GUI app on X11 had the same exposure. `ClipboardRequestor.c` (`CX-UIA-11`) already forced the interleaving deterministically.
  - **Fix.** `nix/sdl3-x11-selection-requestor.patch`, applied through `sdl3Patched` in `flake.nix`, scopes an error handler to that one reply. It absorbs only `BadWindow` errors that name the requestor and come from `X_ChangeProperty` or `X_SendEvent`; every other error still reaches the previous handler. Stock SDL exits 1 on the destroyed-requestor case; the patched SDL exits 0, and the live case passes on both.
  - **Guard.** `test_native_ui_sdl_clipboard_requestor.py` runs both cases under the virtual display and joins the native GUI gate through its glob. Expected-skip rules cover it on macOS, the hosted macOS runner and Windows.
  - **Also.** The dev shell carries `libdecor.dev`, so `libdecor-0.pc` resolves and Codex can compile `LibdecorPending` in CI. The Wayland restore timeout inside libdecor stays open.
  - **Checks.** Lint and format; 326 tests that read the flake, the skip ledger, the headless session and the naming contract; the new test and the probe compile tests (4 passed) in the patched shell. SDL's own test suite ran while the patched library built.
- **Batch 42 (2026-10-06): Windows host hardening (`CX-P1-06`, PR #58).**
  - **Review.** No production defect. All seven prerequisites from the PR #43 review are met. The native evidence is real: both result artifacts from run 37358027694 show 16/16 with `complete=true`. 25 single-line mutations of the PR's code found two fixes that the suite did not test: the status read from the gate's exit code and the case-insensitive environment merge.
  - **Integrator commit `2ca3ca56`.** Four tests, each confirmed by reverting the fix it names: the status comes from the gate's exit code, not the marker; a target writing `../control/status.txt` cannot end the run; `run()` applies the 1 MiB limit; the gate merges the host environment case-insensitively. The Windows host suite now has 89 tests.
  - **Follow-ups for Codex** (in CODEX.md and the PR's closing comment). Before `CX-P1-07`: the read-only temp-file regression (`shutil.rmtree` without the retry), the duplicate overflow note and `check.py`'s cleanup. For `CL-P1-17`: the marker-file channel and the digest-to-launch gap.
- **Batch 43 (2026-10-06): float literals at their C type (`CL-REQ-09`), and the mobile host workflows.**
  - **`CL-REQ-09`, round 2.** Approved. The blocker fix keeps Python's exact-rounding check on the Decimal path, so 5,000-digit spellings and `0e99999999f` finish in under 0.6 s. A reviewer ran 114 adversarial spellings through both compilers: huge and 4,300-plus-digit exponents, midpoints, `FLT_MAX`, the smallest subnormal and the strtold-to-strtod edges. Every accepted spelling folds and runs to the C value, matching gcc 15.2 and clang 21.1. btrcc no longer calls `strtold`, so its results no longer differ by platform, and the macOS expected-skip rule for that difference is gone.
  - **Recorded, not fixed:**
    - the lexers' double-rounded `f` range check refuses some literals C accepts near `FLT_MAX` and 2^-149;
    - both lexers read `5.f` and `1.e5f` as field access on an integer;
    - out-of-range float casts in static initializers are accepted;
    - btrcc stores a float literal's AST value as single precision.
  - **`host-ios.yml` and `host-android.yml`** answer Codex's `REQUEST(CL-R-38)` (PR #34) and Android `REQUEST(CL-REQ)` (PR #35). A guard job skips the device job until the host directory is on the revision, so both land before the hosts do. iOS runs the six commands on macos-15. Android runs API 29 and 36 KVM emulators. It feeds `sdkmanager` exactly `sdk packages`, installs the pinned emulator and platform-tools from the checksummed overlay archives, and runs `sdk verify`; it never enters `.#platforms`. A new contract test checks both. Codex rebases #34 and #35 next, and their first native runs follow.
  - **Returned the same day:**
    - `CL-C-13` round 3: all six round-2 blockers are fixed, but two new holes were confirmed by verifiers. Generic-method type arguments are inferred without the flexible-array check. A type parameter named like an outer flexible-array struct hides that struct's checks inside the generic.
    - `CL-REQ-10`: the runtime half (the 512 MiB compile thread, park accounting, the forked-worker guard) is approved. The semantics half has three confirmed blockers: a regression for map-literal call arguments whose parameter type differs from the first entry; a global map-literal `var` accepted by btrcc as invalid C; later map entries never checked against the inferred key and value types.
  - **Main CI on `04bcd693`:** CI, macOS, Windows, Host iOS and Host Android all green. The Linux unit shard, where the X11 clipboard crash used to strike, passed on the patched SDL.
- **Batch 44 (2026-10-06): design round 4, recorded.**
  - **`CL-P2-01` round 4 on Codex's HTTP (#51) and Windows services (#52) designs.** The panel ran three reviewers per design (feasibility, correctness, parity), with a verifier per blocking finding. Both returned; the details are in each PR's round-4 comment and in CODEX.md.
    - HTTP resolved 7 of its 8 round-3 blockers. Two Android blockers were confirmed against OkHttp 2.7.5 and AOSP sources. First, an exposed 1xx or 101 pools a connection whose response is still unread. Second, in-flight Java I/O cannot be aborted, which leaves the quarantine unbounded. A Windows revocation clarification is required; its verifiers split one to two on whether it blocks.
    - Windows services resolved its round-3 blockers, and six new ones were confirmed.
    - Refuted and dropped: a Linux trust-store gap, the meaning of `HTTP_FAILURE_UNSUPPORTED`, and a `platform-adaptations.md` recording rule.
  - **New lane `CL-REQ-11`** (`stage18/req11-tuple-sizeof-recursion`). Three defects both compilers share, re-confirmed on `04bcd693`: indexing an array of tuples is refused; `sizeof` of an array variable emits C that does not compile (the global is pruned); and polymorphic recursion through a tuple hangs both analyzers. The global `var` tuple that btrcc accepts as invalid C went to `CL-REQ-10`'s static-storage fix.
- **Batch 45 (2026-10-06): the native shell journey waits for its injected input.**
  - **Cause.** `test_linux_native_shell[plain-selfhost]` failed intermittently (lane CI run 37407657466, attempt 1): `ShellJourney_run` step 5 asserted `action.count == 1` and found 0. The journey re-posts itself every 10 ms and assumed the click injected at step 4 was already processed. On one virtual display shared by four test workers, delivery can take longer. Steps 1, 4 and 6 had the same assumption.
  - **Fix.** Those steps re-run on the next tick until their input lands, within a 15 s budget inside the 20 s journey deadline, then assert as before. Step 5 still requires exactly one action.
  - **Checks.** `btrc-format`; the shell and Linux provider suites at 10 cycles with `-n 4` on one display: 55 passed, 4 skipped (Wayland-only).
- **Batch 46 (2026-10-06): the UI1 checkpoint (`CL-UIA-09`).**
  - **Decision** ([`ui1-feasibility.md`](ui-contracts/ui1-feasibility.md)). macOS AppKit and Linux SDL under X11 enter UI2 on both frontends, plain and ASan/UBSan. Wayland enters with the selfhost ASan/UBSan restore-61 libdecor stall carried and is not recorded as qualified. Windows, iOS and Android stay blocked on the shell and host items `hosts.toml` already names. D24's host-owned loop is design-confirmed for mobile, not yet evidenced (`CL-P2-22`, `CL-UIA-22`). Win32 versus WinUI and Views versus GameActivity stay open for `CL-UIA-22`.
  - **Review.** Workflow `wf_271409ca-5fd`: two feasibility reviewers (macOS, Linux) approved with 0 blocking findings; the parity reviewer's two blocking findings (Wayland selfhost-sanitized proven only for the reference compiler; no catalog field for milestone eligibility) were refuted by their verifiers as carried gaps, not entry blockers. The three review files are under `docs/design/ui-contracts/reviews/ui1/`.
  - **Conditions for `CL-UIA-13`:** freeze `IApplication.attachHost` at least provisionally; phrase executor affinity as the application's UI executor thread and mark the Windows and Android rows provisional; decide SDL composition (adaptation or `SDL_EVENT_TEXT_EDITING`); add UI2 to E42's and E46's milestone links.
  - **Carried gaps, with owners:** hosted macOS never activates the application, so keyboard delivery (Tab, Return, Escape) is unproven for E01–E03, E33/E34, E39 and E42 (a `CX-UIA-10` follow-up; `MAC-UIA-02` covers timing only); the macOS key-view loop with Full Keyboard Access off and the GPU view's focus and AX (UI3, UI8, UI9); default-mode-only `postAfter` timers; the E31 survivor oracle; E40 (`CX-STDLIB-01`, `CX-UIA-23`); Linux AT-SPI (UI8); Linux synthetic input, resize exposure and window-only leak accounting; evidence freshness (macOS shard at `25a160f7`, artifact expiring 2026-10-19).
  - **Catalog.** The catalog has no milestone-eligibility field, so the decision is a note on the two eligible routes in `hosts.toml` (no `status` or `blocked_by` change; an integrator edit on a `CX-UIA-06` path, recorded in CODEX.md). Host, catalog and CI-contract tests: 239 passed, 23 skipped.
- **Batch 47 (2026-10-06): the UI2 contract is approved (`CL-UIA-13`).**
  - **Record.** [`ui2-approved.md`](ui-contracts/ui2-approved.md) freezes the UI2 interface diff from the three Codex drafts (control events `CX-UIA-18`, executor `CX-UIA-19`, lifecycle `CX-UIA-20`), the operation ids the catalog gains, and the E-case links (UI2 joins E42 and E46). Where a draft and the record differ, the record governs. Nothing under `src/` changes; `CX-UIA-21` writes the production interface from the record and `CL-UIA-14` lands it with the macOS (`CX-UIA-22`) and Linux (`CX-UIA-23`) providers atomically.
  - **Review.** Workflow `wf_b7573fea-5df`: two feasibility reviewers (macOS and Linux; Windows, iOS and Android), a reconciler and a parity reviewer; review files under `docs/design/ui-contracts/reviews/ui2/`. Eight findings were raised as blocking; each was adversarially verified and found to be a decision the drafts delegate to this record, and the record makes it: a provisional host link (`IApplicationHost`, `IApplicationHostAttachment`, `ApplicationHostAttachOutcome`, reached through `GUI.attachHost`); a common-mode macOS run-loop source and timers, with a reentrancy rule for nested tracking and modal loops; terminal capacity reserved per registration and channel at subscribe time (known conflict 1); text eligibility loss cancels the composition and ends the interaction once, keeping the draft (known conflict 2); Linux composition plumbed through `SDL_EVENT_TEXT_EDITING` with E01's Linux undo row deferred to `CX-UIA-27`; a fixed non-generic publication record; facade mirrors for `attachHost`, `createPublisher` and `schedule`; and `BackgroundJobExecutor.subscribeCompletionReady` as a non-catalog BackgroundJobs contract.
  - **Compiler gaps found** (proposed packets in the record; none blocks UI2): `CL-REQ-UI2-A` generic interface implementation (`implements I<T>`); `-B` btrcc rich-enum variants with `Vector<class>` payloads; `-C` a borrowed managed payload escaping a rich enum is a heap-use-after-free in both compilers (memory safety; UI2 forbids that shape until fixed); `-D` the realtime POD rule is not rechecked at generic specialization; `-E` `Atomic<T>` with 64-bit payloads (optional); `-F` executor-affine release for managed classes (optional); `-G` btrcc diagnostic positions in files with imports.
  - **Packet text.** `CX-UIA-16` and `CX-P2-36` step 1 now use `GUI.attachHost` from the host entry; `CX-UIA-22` step 3 uses a common-mode run-loop source (no `performBlock`) and its acceptance gains E40 with the macOS tracking trials and the `window_key` rule; `CX-UIA-23`'s acceptance gains E31 and the composition and undo classification. CODEX.md carries the UI2 landing chain.
- **Batch 48 (2026-10-06): Stage 24 commit 1c, the target data model (`CL-P1-05`).**
  - **What lands** (lane `stage24/target-data-model` at `d3b61197`, merged onto `a523dcf9`).
    - Both analyzers type integer literals and bound `long`/`unsigned long` casts by the selected row's `sizeof_long`, so LLP64 Windows rows type `3000000000` as `long long`.
    - Predefined macros are selected by operating system, architecture and environment over all 11 rows of `targets.toml`.
    - M3 refuses `#define` and `#undef` of every predefined or derived name, reading a generated names list (`TARGET_PREDEFINED_MACRO_NAMES`, `predefinedMacroNames()`). That list replaced building every macro row on every btrcc compile, which had cost the stdlib-heavy bench about 0.3 MiB of peak.
    - Release C is generated per operating system (`dist/btrcc.c` for linux-x86_64, `dist/btrcc-macos.c` for macos-x86_64, `dist/btrcc-windows.c` for windows-x86_64). Each is proven byte-identical for its other architecture through an incremental stamp under `build/btrcc/release-c/`.
    - The Python stdlib archive manifest (schema 6) records its target row and refuses another row.
  - **Review.**
    - Round 1 (workflow `wf_152e24ee-231`, three reviewers) checked 323 literals × 11 rows against clang's `_Generic` types and 66 predefined names × 11 rows against `clang -dM -E`, with 0 mismatches. It returned one confirmed blocker, the archive not keyed by row, plus seven cleanups: incremental row checks, the Windows `--target` in `windows.yml` and `test-windows`, docs drift, bundle tests, the three newly refused Apple names, a generator overlap check, and the narrowing note.
    - Round 2 (workflow `wf_b84878fe-41f`: a fixes reviewer reproducing each item, and a regressions reviewer) approved with no blocking finding.
  - **Integrator follow-ups in this batch:**
    - the archive checks the row before the source hash, so a cross-row archive names its remedy once the stdlib is target-conditioned;
    - the release targets depend on their stamps directly instead of recursing, so generated-check runs once;
    - a test pins both generated names lists to the macro rows;
    - `precompiled-stdlib.md` lists the row check;
    - the `CL-P1-05` packet no longer claims Windows rows refuse `long x = 3000000000;`.
  - **Checks.**
    - Lane: lint, format-check, codegen check, zero-warning transpiles of the three entries, the archive, build-safety, hosted-ABI, CI-contract and target-data-model suites, the preprocessor-conditional suites through both compilers, the bootstrap fixed point, and CI 37463222741, macOS 37463226026 and Windows 37463229256, all green on `d3b61197`.
    - Integrator, on the merged tree: btrcc built with 0 warnings; lint, format-check, codegen check and `git diff --check` clean; the six affected suites 372 passed.
  - **CI cost.** Each release job now runs a second BtrccMain transpile for the identity row. On a fresh checkout the stamp cannot help, so `release` takes about 19 min (8m47 s before the lane) and `native-bundle (macos-x64)` about 18 min. Overlapping the two transpiles, or proving identity in one job only, is left for the CI-tiering owner.
  - **Hand-offs.**
    - The constant-folder defects round 1 found go to `CL-C-25`: untyped integer folding, duplicate case values not converted to the controlling type, `char_signed` unused, and btrcc's `int_fast*_t` bounds taken from its build host.
    - The `-Wconstant-conversion` narrowing of `long x = 3000000000;` on Windows rows goes to the float and literal REQ lane.
    - New, pre-existing: btrcc lowers every untyped global `var` as `int` (`ir/lowering/Declarations.btrc` `emitGlobalVar`), while Python uses the inferred type. This goes to the same REQ lane.
    - New, pre-existing: whole-program dead-code elimination drops a global used only inside `sizeof` (both compilers). This joins `CL-REQ-11`'s `sizeof` work.
    - A Python `--module-units` compile retracts the units an earlier compile wrote under another `--emit-units` prefix, while btrcc keeps them. This is recorded for the artifact-publication owner.
- **Batch 49 (2026-10-06): GPU async completion waits get a CI-safe deadline.** macOS run 37468957133 on the docs-only `f6c2f2ae` failed one test, `test_gpu_concurrency_contracts_under_thread_sanitizer[async-publication]`: a waiter in `gpu_async_state_machine.c` had to see its fake future complete within 100 ms. The future needs only about five 1 ms driver polls, but under ThreadSanitizer on a loaded hosted runner each yield can stretch to tens of milliseconds. Every wait that must complete now uses a 10 s deadline; the timeout paths keep their explicit zero deadlines and the wait-error path is unchanged. Checks: `test_gpu_async_runtime.py` 18 passed.
- **`CL-C-09` round 3, returned (2026-10-06).** Workflow `wf_5df67358-dc4`, two reviewers. Blockers 2 and 3 of round 2 are fixed, but 10 new confirmed blockers were introduced by the lane. Seven share one cause: `struct X` is normalized to the bare `X`, and an alias row is registered for every source record, so a generic parameter named like a record captures it. The effects are ARC applied to struct values, btrcc silently writing struct fields through a copy, mismatched instance names, and a btrcc hang on `Box<struct P*>`. The other three are the typedef-order first diagnostic, header tags beside generic stdlib classes, and LSP false positives from composing the whole stdlib. The recommended fix restores main's handling for record names that collide with any generic parameter name.

- **Batch 50 (2026-10-06): the Linux GUI and audio CI shard (`CL-UIA-11`), and the native shell's final wait.**
  - **What lands** (lane `stage31/linux-gui-audio-shard` at `0e5bf7c5`).
    - `make test-shard-gui GUI_SESSION=x11|wayland` runs the native GUI tests, the ALSA session tests and the AlsaFaults fixture, plus the null-PCM check. It runs inside `tools/ui/headless-session.sh` with lavapipe and an ALSA null PCM, then writes JUnit, a skip report and the skip gate.
    - The ci.yml `linux-gui` matrix is planned from `ci/tiers.toml` (x11 gating, wayland report-only through `continue-on-error`) and uploads `gui-evidence`, `junit` and `skip-report` artifacts per session.
    - `tools/ui/status_notifier_watcher.py` is a stand-in StatusNotifierWatcher, so the Linux tray tests run in the shard; `tools/ui/session_evidence.py` samples the AT-SPI bus into `atspi.json`.
    - There is no D7 host, so the nightly real-session job is a hardware skip rule (`linux-real-desktop-session`, covered by a new `linux` runner) with the exact command recorded.
  - **Integrator changes:**
    - `NativeShell.btrc`'s final journey step waits for the native close through the same bounded `pending()` check as the input steps (batch 45), instead of asserting one tick after the close probe. That is the Wayland residual the lane could not touch.
    - The tiers comment now says what is left before Wayland gates: green runs on main.
    - The Makefile comment names `build/linux-gui/<session>/atspi.json`.
    - The `gui-evidence` artifact also keeps `.ppm` and `.png` captures.
  - **Review.** Workflow `wf_a5886bd1-160`, the `uia11` reviewer, approved with no blocking finding.
    - The workflow wiring, the report-only semantics and the artifact names all checked out.
    - The watcher's signal and exit handling were exercised, the sampler is bounded, and `make -n` resolves for both sessions.
    - The Makefile merge with batch 48's stamp rules is intact.
    - The native shell ran under X11 through the shard's wrapper chain: plain 2 passed, sanitized 2 passed. Three Linux tray tests passed under the watcher.
  - **Checks.**
    - Lane: unit shard plus btrc suite 11,312 passed, 3,151 skipped; corpus 1,982 passed; branch CI 37483800111 green (x11 200 passed, wayland 198 passed, skip gates clean).
    - Integrator: lint, format-check, codegen check and `git diff --check` clean; CI-contract, skip-ledger, qualification-bundle and build-safety tests 266 passed.
  - **Hand-offs to the CI-tiering owner (non-blocking review findings):**
    - Ledger records for the x11 and wayland JUnit artifacts share subjects, so the rollup keeps only one; pass the row's session as the adapter variant.
    - ci.yml's `skip-reports` job does not need `linux-gui`, so lost GUI reports only show up in release.yml's bundle.
    - A Wayland row that never reaches pytest still fails the nightly or release bundle, as the tiers comment says.
    - The GUI path list is copied three times in `ci/tiers.toml` with no test keeping the copies equal.
    - Nothing fails the shard if the tray skip rule fires there.
    - The AT-SPI dump is bus-only until the Linux SDL provider has a bridge (UI8).
- **`CL-C-13` round 6, returned (2026-10-06).** In the same workflow, round 6 (`cd13fd6`) fixed all three round-5 blockers. Warm module-unit replay matches clean builds in eight cache modes, optional calls refuse identically, and class-receiver callees are checked first. Two new first-diagnostic parity blockers were confirmed:
  - btrcc's type-parameter shadow check now runs before every declaration check, so it pre-empts errors Python reports first: FAM-not-last, by-value fields and parameters, and duplicate classes.
  - The callee-first fix covers only class receivers, not interface, `Atomic<T>` or `Mutex<T>` receivers.

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
- **Integration-review fixes (lane `stage16/c1-integrate-fixes`, `2822c60`, landed in batch 6).** F7: a run of macro names before a string literal (`A B "c"`) parses as one concatenation in both parsers. F8: btrcc refuses a non-`string` catch type with the Python message and position. F9/F10: an unsized string-initialized global or class static gets an explicit size at lowering from the source-macro decoder, which the analyzed program now carries, so split and module-unit builds emit `extern char g[5];`. F11: both lexers delete a backslash-newline inside a literal and keep line numbers. F12: one `validateArrayBound` in btrcc, checked after a local's initializer as in Python. New `test_c_compatibility_integration.py` (12 tests, both compilers). Deferred: `catch (string* e)` still parses to different errors, and a global read only through `sizeof` is still dropped by the optimizer.
- **Batch 6** (`integ/b6` on `d7e601a`, with the Stage 24 and Stage 27 design docs): the generated-source check, lint, format-check, `git diff --check`, zero-warning self-host transpiles of all three entries and `boundary-check` (287 of 311) are clean. `src/tests/btrc`, the corpus through both compilers and the lexer, parser, analyzer, grammar-drift and literal tests gave 6,502 passed and 43 skipped. The bootstrap reached its fixed point.
- **r03, r19 and r07 (lanes `stage16/c1-decl` and `stage16/c1-fnptr`, batch 9).** r03 multiple declarators follow D20's C binding (`*` and `[]` bind per declarator; each keeps its initializer; scope starts at its own declarator; initializers run left to right). r19 accepts the comma operator in `for` headers only, as a `CommaExpr` root that is discarded, and keeps the refusal elsewhere. r07 adds function-pointer declarators (locals, fields, parameters, arrays, typedefs, casts and declarator lists) with D20's disambiguation. The `c1-fnptr` lane reconciled r07 with r03 and with nullable flow. Two contracts were updated on the merged tree: the for-initializer array case now reaches the analyzer's existing refusal (`C-style for initializer cannot declare an array`) in both compilers, and the comma coverage contract exempts the nullable flow in `ControlFlow.btrc`.
- **Batch 9** (on `93d8c14`): `stage4/objc-macro-constants` (an Objective-C binding's imported integer constants are no longer re-declared in C under their macro names; `AppKitEvents.h` is an umbrella include again and binds `NX_DEVICE*` directly; D049 closed; macOS proof on the lane), `stage4/residual-native-importer` (D046: a Windows MinGW binding target, and the native-package example binds its headers; D039: glibc transparent-union parameters and variadic declarations, so LocalApplicationChannel binds `connect`/`bind`/`accept`/`fcntl`/`poll`; the reader marks transparent unions), `stage4/residual-macos-conformance` (D044's macOS programs bind their probe headers; two macOS runs green), and the C1 declarator lanes above. The macOS-conformance lane imported a helper from a test module; it moved to `src/tests/python/core_audio_fixtures.py`. Gates: clean (generated-source, lint, format, diff, zero-warning self-host transpiles). Because the dev shell builds the header reader from the primary checkout, the suites ran with a reader built from the batch's own `NativeHeaderReader.cpp`: `src/tests/python`, `src/tests/btrc`, the corpus through both compilers, LSP and formatter gave 11,491 passed and 3,165 skipped; the two failures were the contract updates above, which pass. The bootstrap reached its fixed point.
- **C1 exit (`ccompat-c1-integrate`, lane `stage16/ccompat-c1-integrate`, packet `CL-C-01`, batch 12).** Every C1 row passes in both compilers:
  - rows 1–7 and 19 (32 entries in `c1.toml` and `c5.toml`) were re-recorded through both compilers by a new recorder (`python3 -m src.tests.btrc.c_compat_inventory record --rows …`), with no outcome change; a test re-records every manifest and requires byte-identical files;
  - braced and braceless bodies give identical raw IR and C in each compiler, over 7 pairs, with and without `--debug`. btrcc gained `--emit-ir` and `--emit-optimized-ir` (`IRCanonicalRenderer` in `ir/Model.btrc`) for this;
  - ARC per declarator: `test_c_compatibility_declarator_arc.py` counts 14 ownership helpers in seven scenarios, with identical pinned counts in both compilers under gcc and clang and nothing left allocated;
  - every C1 refusal family (r01–r07, r19) is pinned with identical message, line and column;
  - the `c_compat` corpus passes in all 8 gcc 15.2/clang 21.1 configurations;
  - `tools/c_header_miner.py` counted C1 constructs in 316 Linux headers and compiled 28 self-contained declarations through both compilers with no failure.

  The BTRSmith rerun (`--jobs 1` instructions and peak) and a Darwin SDK pass of the miner are owed on the Mac. Two defects found on the way exist in both compilers and are not C1 bugs; they are in `docs/known-language-gaps.md`: `&` of a managed local that the setjmp pass made `volatile` produces C strict C11 rejects, and `string* p = null;` warns as if `p` were a `string`.
- **Next.** C4 (`CL-C-03` ∥ `CL-C-04`, then `CL-C-05`/`06`), reserved now that `CL-C-01` and `CL-R-00` are on `main`.

### Stages 16 (C4), 19 and 20: designs (done 2026-10-02)
- Workflow `wf_926e5dfc-b6e` ran one drafter and two adversarial reviewers (implementability and C11 soundness) per topic, followed by a synthesis. It produced `docs/design/c-preprocessor-conditionals.md`, `docs/design/c-vocabulary-specifiers.md` and `docs/design/c-goto-labels.md`, linked from `c-compatibility.md`.

### Stage 18: emission-order parity (lane `stage18/emit-order`, 2026-10-02)
- **Serial step 1.** `IRTypeDeclarationPlanner` (`ir/optimization/Optimizer.btrc`) ports `IROptimizer.plan_type_declarations`. btrcc's `CEmitter` now emits forwards, the planned type declarations, then prototypes, for whole programs, split units and module units. `ModuleUnitDeclarations.orderStructs` is retired. Over the 964-program corpus, Python's C is byte-identical before and after; the only differences are three files whose absolute `#include` path names the checkout. 546 btrcc outputs changed, each a pure reordering. The layout of user declarations and prototypes now matches Python's in 960 of 964 programs (446 before) and in 496 of 496 sampled module-unit files (286 before). Whole-file byte identity stays at 3 programs, because lowering differs; `docs/design/c-compatibility.md` lists the differences. A read-only reviewer confirmed the port and found no blocking defect. Two gaps shared by both planners are left as they are: array sizes do not wait for enum values, and `X_V_Data` has no forward declaration.
- **Exit evidence.** The bootstrap fixed point passed (`test_bootstrap.py`, 20m42s). The corpus through both compilers had 1,983 passed, 6 skipped and 1 failed: `stdlib/Daemon.btrc` under btrcc ran 15.0 s against the runner's 15 s limit. The unchanged base binary also takes 15.0–15.15 s and Python's build takes 14.6 s in this 4-CPU container, so the change is not the cause; it needs a look on the Mac. Module-unit suites had 61 passed and 8 skipped. `test_cached_split_cli_restores_complete_executable_generation` (4 cases) also failed on the lane's base, because the Python CLI reports `--profile` as cached. That base predated `3812e44`, which had already updated the test to the aligned contract (`--profile` keeps the artifact cache and records `artifact-hit`, as btrcc's `BTRC_TIMING` does); the 4 cases pass on `main` (`CL-REQ-01`, 2026-10-03, no code change). `boundary-check` held 287 records unchanged. Strict C11 compiled 39 reordered programs under gcc and clang at `-O0` and `-O2` (156 compiles) with no errors. Both self-host entries transpiled with zero analyzer warnings.

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

### Stage 27: interop ownership design (design step 0, lane `stage27/interop-design`, 2026-10-02)
- **Design.** [`docs/design/native-interop-ownership.md`](../../docs/design/native-interop-ownership.md) is the one ownership plan for C function tables, Objective-C protocols and blocks, JNI, COM and GObject. Every foreign value is in one of three relations to ARC: btrc owns a foreign claim, a call borrows, or foreign code holds one external claim on btrc. Three mechanisms are shared by every model: dispatch through a foreign table, one holder shape, and one checked conversion. One rule translates foreign failure. Foreign-held cycles break only by explicit cancellation, every foreign entry pins its receiver and holder, and `executor`/`release-executor` share one closed value set. It needs no new `runtime/c` asset or manifest row (step 2 adds one TLS field, a holder-thread generation, through one D14 re-capture), and no new compiler file (88/97 unchanged).
- **`native_abi.asdl` delta (purely additive, schema v2 → v4).** `NativeField.callback_parameters`; `NativeHeader.protocol_declarations` with `NativeObjectiveCProtocol`, `NativeProtocolRequirement` and `NativeObjectiveCProperty`; Objective-C interface `protocols`, `properties` and `main_actor`, and three method flags; `NativeJavaClass`, `NativeJavaMethod` and `NativeJavaField` declarations; `NativeJavaObject` and `NativeJavaArray` types. Java metadata comes from a new `tools/JavaClassReader.c` (C11 + zlib) on the existing batch protocol (D22). GObject needs no schema change; its transfer facts come from the manifest, not `.gir`.
- **Order.** 1 schema v2 → 2 function-table calls (exit: `-O2` and ASan/UBSan vtable fixture) → 3 Objective-C slice (macOS and iOS-simulator delegate round trip) → 4 JNI slice (host JVM with `-Xcheck:jni`, then the emulator round trip) → 5 COM (Linux proxy, then exact release counts on Windows CI). Stage 29 runs steps 6 (I1) and 7 (A1); Stage 31 runs step 8 (GObject, Linux tier A, with tier B required before the GTK spike). Each step lands Python first, then btrc, one commit per construct, and ends with a feature bootstrap.
- **Review.** Five drafting agents, one per model. Then 2 adversarial reviewers (ARC soundness; Python/btrc implementability) and 1 parity reviewer raised 44 findings, 13 of them blocking. The blocking findings covered off-thread holder release, the lack of a lease across a foreign entry, the GLib context check, the JVM lifetime owner, an over-broad verifier rule, the Java reader launch path, an ASDL field-name collision in the btrc renderer, an incomplete key list, the executor spelling, the signal syntax, COM sink cancellation, HRESULT on ordinary methods, and JNI `main`. All 44 are resolved in the document's Review section. A confirmation pass then found all 13 resolved and raised 4 new blocking gaps: the holder and resource release-executor defaults, JNI env-table privacy (`dispatch-records`), the COM sink IID source, and the dispatch key grammar. All 4 are resolved in the same section.
- **Approval.** Approved under the standing design-approval rule: the two adversarial reviewers and the parity reviewer leave no unresolved blocking finding.
- **Open for the owner (non-blocking).** The Java reader's implementation language (C11 chosen); `failure = "throw"` for Java entry only; free-threaded COM sinks waiting on atomic ARC; the iOS-simulator evidence depends on Stages 24–25.

### Stage 24: target-contract design (lane `stage24/target-contract-design`, 2026-10-02)
- **Spec step done; implementation waits for C4** (Stage 16 creates `targets.toml`). `docs/design/platform-target-contract.md` designs all seven Stage 24 items:
  - the spec delta: 11 rows with triples, sysroot kinds, data-model columns and the `""`/gnu/msvc/simulator environment axis;
  - the hosted-ABI unavailability tables and a reachability check run in the optimizer;
  - the native-reader targets, with sysroot validation and identity;
  - link plan schema 5;
  - provider filters with an `env` selector and a platform-directory rule;
  - cache identity on the canonical label;
  - the target ABI fixture.

  For each item it gives the owners in both compilers, the named tests, the exit evidence, the Linux/Mac/NDK/runner split and the four gated sub-batches.
- **Decisions.**
  - `__ANDROID_API__` is defined from the row's API level.
  - clang 21 predefines `TARGET_OS_*` for Darwin triples, so those names become rows rather than foreign names.
  - `__STDC__` excludes msvc.
  - Analyzer widths come from the row, which also covers btrc literal typing.
  - Both compilers refuse an unknown host up front with one message.
  - The LSP gains a `btrc.target` setting.
- **Review.** Three research agents (Apple, Android, Windows) checked every triple and macro with clang 21.1.8 and zig 0.16.0. Two adversarial reviewers (triples and sysroots; Python/btrc parity) and a parity reviewer raised 19 distinct blocking findings, all resolved and listed in the document's Review table.
- **PLAN amendment.** `windows-aarch64-msvc` is a provisional row: wgpu-native ships Windows ARM64 only as MSVC, which meets D21's condition. Stage 28's `platforms-w1-toolchain-abi-route` confirms or removes it.
- **Owner questions.**
  - Q1: the macOS row minimum (14.0 by default).
  - Q2: the MSVC row scope.
  - Q3: no `ios-x86_64-simulator` row.

### Two builder agents: Gate 0 (D27, 2026-10-03)
- **D27 is in force.** The owner asked for the work to be split between Claude and OpenAI Codex, with Codex taking the GUI for each stdlib platform, and started Codex on it. D27 records the split; the owner may strike any clause. On 2026-10-03 the owner also asked for all the UI work, iOS, iPadOS and Android included, to run in parallel, which approves Stage 24's early start after C4 (WORKSTREAMS.md §7 Q2).
- **`WORKSTREAMS.md`** (repository root) assigns every remaining PLAN.md item as one of 445 work packets: Claude 182, Codex 208, owner 55, each with owned paths, steps, acceptance and dependencies. The packets themselves are in `docs/workstreams/{claude,codex,owner}.md`, with `packets.json` and the planning appendices beside them. Six planning analysts wrote the packets from this plan; three review lenses checked them.
- **Gate 0 (`CL-UIA-01`)** also adds the Codex section to AGENTS.md and trims AGENTS.md to under Codex's 32 KiB read limit (37,433 → 29,664 bytes). The two measurement sections moved to `docs/design/compile-performance.md`, and the Python file tree now lives only in `docs/design/compiler-structure.md`, which `test_python_compiler_structure.py` still checks. Gate 0 adds the Codex packet-report template (`.github/PULL_REQUEST_TEMPLATE/codex-packet.md`), the Codex standing approval, the Codex lane rules under "Where sub-agents help", the Stage 34–37 lane owners, and the Stage 30 and 37 catalog readings: PR #21's amendment model and catalog layout (WORKSTREAMS.md §7 Q35, Q36).
- **Next.** Codex's PR #21 (`CX-UIA-02`) is integrated in the next batch, with `CL-UIA-02`'s CI policy. `CL-R-00` integrates the three open Stage 4 lanes and writes the findings ledger.

## Execution record (Claude integrator, from 2026-10-12)

Claude executes this plan as the integrator (CLAUDE.md roles, D4/D29): compiler,
spec and runtime owner, merges and `main` pushes after green gates. Each line gives
rank, capability, state and the next action; detailed evidence stays in the linked
PRs and the [integration record](docs/design/claude-integration-record.md).

| Rank | Capability | State | Next |
|---|---|---|---|
| 1 | Strict GCC (`-Werror=clobbered`, `-O1`…`-Os`) accepts every try/setjmp shape seen in the Linux GUI provider and BTRSmith scanner: scalars and pointers visible at a `setjmp` are kept out of register pseudos in both compilers | Batch 1, [PR #75](https://github.com/schiffy91/btrc/pull/75): paired contracts plus `RegisterScalarsAcrossTry` (red on the baseline, green on both compilers × GCC/Clang × `-O0`…`-Os`) | Land with batch 1 |
| 1 | Self-hosted compiler accepts class-typed collection field and parameter defaults (`new Vector<Slot>()`), as the reference compiler does | Batch 1: `ClassArgumentDefaults` through both compilers | Land with batch 1 |
| — | PR #70 (compact IR, Windows ProcessThreads, CoreAudio cleanup) and PR #74 (Linux thread-count errors) | Batch 1 with the owner's 2026-10-12 plan; Mac `make test` gate and hosted CI running | Merge on green |
| 2 | Android and iOS stdlib providers can be declared: `os`/`arch`/`env` selectors over every target row, row-based overlap, platform-directory rule (CL-P1-14) | `claude/provider-filters`: 172 paired tests | Batch 2 |
| 2 | Native SDK headers import for every row; iOS device and simulator headers read through Xcode's SDKs and the emitted C compiles for iOS 17 (CL-P1-10) | `claude/native-import-targets`: 177 paired tests | Batch 2 |
| 2 | Runtime reports iOS (4) and Android (5) instead of macOS/Linux; `Platform.isIOS/isAndroid/isApple/isMobile` (CL-P1-16) | `claude/target-probes`: per-triple IR probe test for all 11 rows | Boundary re-capture, then batch 2 |
| 2 | Corpus programs run on the iOS 26.4 simulator through the reference compiler | 41 of 41 sampled programs pass (survey, not yet a committed runner) | Full corpus both compilers through the Stage 25 runner once PR #34's executor adopts protocol 1 (`CX-P1-08`) |
| 2 | Any target row builds through one toolchain owner: link-plan schema 5 and `TargetToolchain` (CL-P1-11), with the target ABI fixture's static half for every row (CL-P1-13) | Batch 7 ([PR #81](https://github.com/schiffy91/btrc/pull/81)): both compilers write byte-identical v5 plans; the fixture compiles for every row whose toolchain is present here (Android needs the NDK, the MSVC row a Windows SDK runner) and runs on the host | Land with batch 7 |
| 2 | The Stage 25 target runner (CL-P1-17): compiles the corpus for a target through both compilers, runs it through a registered executor and writes ledger records | Batch 7: executor protocol 1 frozen in `src/tests/target_runner.py`. On macOS arm64 it reproduces `runner.py` program by program (1,018 per frontend; the same 3 GPU programs missing). Windows x86_64 compile-only through zig: 980 built per frontend, 7 real failures (the programs assume an 8-byte `long`; Windows `long` is 4), 1 restricted and 33 missing, each with its reason. The Codex executors' follow-ups are listed under the Codex queue below | Land with batch 7; then `CX-P1-07/08/09` adopt protocol 1, and `CL-P1-18` triages the 7 Windows failures |
| 2 | No cache entry built for one target row can serve another (CL-P1-15). Every target-dependent key spelled the raw `--target` option, so an alias or an inferred host keyed differently, and the prebuilt stdlib archive carried no target spec | Batch 10 (`1def2465`), in both compilers: whole-program artifacts, module units and validation records key on the canonical row label; stdlib archive schema 6 adds `target_spec` and refuses another row with `prebuilt stdlib archive was built for <label>; regenerate it for <label>`. `test_target_cache_identity.py` (23 cases, no SDK needed) runs cold/warm/alias steps across architecture, data model, ABI, device vs simulator, same-data-model OS, spelling, sysroot identity and spec fingerprint, comparing the emitted C, units and link plan; deliberately broken keys fail it | The full-matrix gate with batch 10; caches can then come back on in the target runner. MAC-P1-07 records the iOS native-read row on the real SDKs |
| 2 | Every package resolves on all 11 target rows, and no row selects another platform's SDK (CL-P1-14) | Batch 15 (`0210f395`, fragment `bc9e50cc`). `test_target_provider_matrix.py`, in its Python and btrc copies, resolves every stdlib, example and native test manifest for every row through both frontends: 0 foreign records, and the two frontends agree record for record. The missing exports match the platform inventory exactly. Mobile lacks Audio, HostWorkerPools, ProcessThreads, NativeSHA256, GUI, SystemImageDecoder, LocalApplicationChannel, LocalPeerCredentials and Tray. Windows lacks Audio, GUI, SystemImageDecoder, LocalApplicationChannel, LocalPeerCredentials and Tray. Two real leaks are fixed: Java's runtime and `jni.h` binding now select android, linux, macos and windows (iOS has no VM), and GUI's FreeType binding selects only rows with `freetype2`. The ProcessThreads Windows inventory cells were stale and now say implemented (`cf2ff940`; Codex `CX-P1-02` should confirm) | Two parser REQUESTs for the packages lane. (1) Enforce §5.2's other rules in both parsers with identical messages: `[[native.frameworks]]` only on rows with frameworks, Objective-C bindings only on rows with Objective-C, `[[native.pkg-config]]` never on ios or android. (2) Align the unknown-`env` message with the spec, or amend the spec |
| 2 | The native HTTP transports' build inputs (CL-P2-04): Linux libcurl with the OpenSSL 3.x backend and c-ares through pkg-config, and a pinned OpenSSL CLI for the per-run test CA | Batch 10 (`c86e48db`): libcurl 8.21.0 from curlMinimal (no `curl` on PATH) in the Linux shell and devcontainer, and the OpenSSL 3.6.3 CLI in every dev shell ahead of macOS's LibreSSL. `test_http_transport_inputs.py` mints and verifies a fixture CA, and on Linux reads `curl_version_info` (OpenSSL backend, c-ares named, AsynchDNS); it passed on hosted Linux CI | Codex's HTTP providers (`CX-P2-09`…`12`) can build on it. Windows and the Android host still need a pinned OpenSSL CLI in their workflows |
| 2 | The whole corpus runs on real Windows x64 and ARM64 through both compilers (CX-P1-07) | Batch 17 ([PR #94](https://github.com/schiffy91/btrc/pull/94)). The Windows executor adopts runner protocol 1 and is registered as `windows-native`. `windows.yml` cross-builds 987 programs per frontend per row on Linux, and each Windows runner executes its own row (run 39221683544). On both rows and both frontends: 971 pass, 12 fail, 2 restricted, 36 missing, each exclusion with its reason in `target-applicability.toml`. All 12 failures are one stdlib bug: `FileSystem.tempDir` builds its template from `TMPDIR` or `/tmp`. zig's `-O2` defines `NDEBUG`, so every assert had been compiled out of earlier Windows bundles; the runner now adds `-UNDEBUG`. 14 corpus programs lost LP64 or POSIX assumptions | The Windows FileSystem lane fixes `tempDir` (TEMP/TMP) and text-mode `Path.writeAll`/`readAll`; then the corpus shards stop being report-only |
| 2 | Regex, fnmatch and glob work on Windows (D22; CL-P2-03 route a; CX-P2-13), and `Library.Terminal` drives the Windows console (CX-P2-07) | Batch 17 ([PR #96](https://github.com/schiffy91/btrc/pull/96)). The overlay's `regex.h`, `fnmatch.h` and `glob.h` compile musl 1.2.5's engine into the including unit with internal linkage (MIT and BSD-2 licences vendored; every local change marked). The re-extracted hosted ABI makes exactly those names available on the MinGW rows; the MSVC row still refuses them, identically in both compilers. A 121-case regcomp/regexec/fnmatch table matches glibc on x64 and ARM64 (run 39222475738). Glob, PatternAny, Regex, RegexSafety and Terminal pass through both compilers on both rows, and the console journey (raw keys, hidden password echo restored on Ctrl-C) passes in a pseudoconsole. `Terminal` gains `size()`, `enableColors()` and `enterRawMode()` | Three parity divergences it found go to the parity wave (btrcc refuses `found->gl_pathv[i]`; the reference warns on a narrowed nullable receiver; the reference crashes on `raw.c_cc[VMIN] = …`). A hosted `CFunction` parameter does not accept `null`. Mobile console refusal providers |
| 2 | `Library.Process` launches child processes on Windows x64 and ARM64 (CL-P2-02, CX-P2-06; `windows-os-services.md` revision 6) | Batch 17 ([PR #97](https://github.com/schiffy91/btrc/pull/97)). `windows_os.c`, a separately compiled runtime object linked only when retained, starts children with a quoted UTF-16 command line, suspended in a kill-on-close job, with an explicit stdio handle list and overlapped pipes. Timeouts kill the whole tree; `.bat`/`.cmd`, aliases and wrong-machine images are refused. `Windows/ProcessHostProvider.btrc` is selected per row. Relaxed imports and the prebuilt archive now compose the providers the root manifest selects, in both compilers. The Linux and macOS C of every Process consumer is byte-identical to the base. On both Windows rows (run 39234189777): the seam harness passes 69 checks, the Process fixture 21 through both compilers, and the Process corpus 6 passed and 4 restricted per frontend. One D14 re-capture: the boundary manifest has 319 records | CX-P2-08 Daemon on Windows (its supervisor image); CL-P2-14 (UCRT `_popen`/`system` under the spawn lock) |
| 2 | `Library.FileSystem` works on Windows x64 and ARM64: exact file and directory handles, snapshots, tree walks and removal, durable replace, locks, owner-only private directories, temporary directories and per-user folders (CX-P2-04, CX-P2-05) | Batch 18 ([PR #95](https://github.com/schiffy91/btrc/pull/95)), through both compilers. `FileSystem/Windows` handles long `\\?\` and UNC paths and non-ASCII names, and never follows a junction or link, including one swapped in mid-walk. `tempDir` uses the user's temp folder, and `Path.readAll`/`writeAll` open in binary mode, which were the 14 failures of batch 17's Windows corpus run (978 passed, 8 restricted, 23 missing per frontend on x64). On both rows (run 39251771717): 12 of 12 provider cases, and 26 FileSystem and file-I/O corpus programs per frontend. Other platforms' C is unchanged apart from the two `fopen` modes | Windows has no directory fsync: durability relies on NTFS committing metadata on a handle flush (documented, not crash-tested). `Platform.currentDirectory()` still uses the narrow `getcwd` (W1 unicode host). Then the corpus shards stop being report-only |
| 1 | Parity: both compilers release an interface value according to whether any implementing class can cycle, and flush cycles after a native call only when a leased type may cycle | Batch 7 (`3c973248`) and batch 8 (`a04fb126`). The self-hosted compiler treated every interface as cyclic, and flushed after every native callback call, so an acyclic callback receiver brought the cycle collector into its C. The ABI fixture's C now differs between the compilers only in spelling, and its test checks for every row that neither flushes | Land with batches 7 and 8 |
| 1 | Interop step 1: callback slot parameters and every calling convention in the native document (schema v2) | `claude/interop-schema-v2`: 347 paired tests | Batch 3 |
| 1 | Interop step 2: BTRC calls through SDK-owned function tables (M1 dispatch) with release slots | `claude/interop-dispatch` `9428afbe`: 22 dispatch cases pass through both compilers (swap, release once, null table/slot and use-after-close aborts, `-O2` with ASan/UBSan) | Batch 3; the step's remaining items are listed in native-interop-ownership.md |
| 1 | iOS: a BTRC program can start UIKit. `UIApplicationMain` creates its delegate from a class name, and C entries in Objective-C bindings were rejected outright, so no BTRC iOS app could launch | Batch 3: `lifetime = "instantiated"`, `scope = "process"` in both compilers. A generated delegate class claims a `CallbackRoot`. The macOS proxy passes 16 cases plus rejections per compiler. On the iOS 26.4 simulator, an app built by each compiler launches through the real `UIApplicationMain`, and its BTRC receiver logs launch and activation. This is simulator evidence, not device evidence (D8) | Scene delegates (`scope = "instance"`), `UIView` subclasses, lightweight generics |
| 1 | Windows and Android: a C SDK can store a BTRC callback until its unregister call. Win32 window subclasses and looper callbacks were rejected by both compilers | Batch 4: pointer-width integer contexts, matched unregister parameters, status mapping, captured handles and opaque handle payloads. A Win32-shaped fixture passes 1,000 cycles plain and with ASan/UBSan through both compilers; the stored C, unmanaged-handle, callback and realtime callback suites pass 189 of 189. The real MinGW `commctrl.h` now imports for windows-x64 and windows-arm64 (both compilers passed `-isystem <sysroot>/include`, where zig keeps no headers, so no Windows SDK header could be read); a stored C subclass of a real message-only window builds with both compilers and zig, and `windows.yml`'s new `win32-native` job runs it on x64 and ARM64 runners | Batch 4 gate, then the first hosted `win32-native` results. Android self-removal (slice B) needs a design decision first: a looper can still deliver once after `ALooper_removeFd` within one poll, so the context must outlive removal |
| 1 | Windows: BTRC holds and calls COM interfaces (interop step 5, slice A). No COM object, so no DirectWrite, WIC, file dialog or WASAPI client, could be used from BTRC | Batch 8 (`a340f553`), in both compilers with the same diagnostics: `ownership = "com"` resources (`iid`, `base`, `release-executor = "apartment"`), `lpVtbl` slots 0–2 and `base` checked against the real layout, `dispatch` through `lpVtbl`, one counted claim per factory/`[out]`/QueryInterface result, `status-results` HRESULT throws, `(IBar?)foo` QueryInterface casts, `IUnknown.sameObject`, and `Library.COM.COMApartment`. 112 tests: a COM-shaped proxy with exact counts plain and under ASan/UBSan at `-O0`/`-O2`, 5 abort paths, 28 rejections, and zig's real MinGW `IStream`/`ISequentialStream` headers for windows-x64 and windows-arm64 (the generated C links with ole32). **Step 5's exit, batch 9 ([PR #83](https://github.com/schiffy91/btrc/pull/83), slice B):** `com-sinks` (a holder with one static vtable that holds one claim on its `CallbackContext`, Unadvise inside an event, `S_OK` without entering BTRC after cancellation, dead-state and off-thread aborts), `copied-outputs` for BSTR and CoTaskMem UTF-16 strings, a new `[[native.libraries]]` link record (Library.COM declares ole32, uuid and oleaut32 for Windows; plans without one are byte-identical), and 25 more identical rejections. On hosted Windows x64 and ARM64 (run 39089410292) both compilers' programs reach a registry-free `DllGetClassObject` server and print `com-server live=0 balanced=1 peak=2 last=0 destroyed=1 claims=0 sinks=0`; `CreateStreamOnHGlobal` QIs to `ISequentialStream`, and its last `Release` returns 0 | `status-results` and `copied-outputs` on C functions; the compile-time ban on capturing a COM resource in `spawn`; the direct R3 cycle rule for sink handlers |
| 3 | macOS UI2 provider: a run loop can hold raw CF timers beside managed CF objects (Codex REQUEST CL-REQ-UI2-CF-BORROW) | Batch 4: `unmanaged-handles` passes 28 tests through both compilers. The cross-binding reservation no longer depends on binding order. The resolution and Codex's remaining step are recorded in `docs/workstreams/ui2-cf-ownership-request.md` | Batch 4 gate; then Codex's RunLoop manifest fragment |
| 1 | iOS: BTRC apps run the UIScene life cycle that the iOS 27 SDK requires (its SDK deprecates the app-delegate life cycle; TN3187) | Batch 6: in both compilers, `scope = "instance"` instantiated adapters on `-[UISceneConfiguration setDelegateClass:]` (a generated factory interface; each scene claims a fresh receiver, released after `sceneDidDisconnect:` or at `dealloc`) and M3 checked downcasts `(UIWindowScene?)scene` through `isKindOfClass:`. Downcast and adapter suites pass with sanitizers. Before the macOS update, a UIScene app built by each compiler connected a key window scene and became active on the iOS 26.4 simulator | Re-run the simulator tests after the owner's `xcodebuild -runFirstLaunch`; the 100-cycle scene connect/disconnect row; `conformsToProtocol:` casts |
| 1 | iOS: UIKit buttons and text fields deliver actions to BTRC. `addTarget:action:forControlEvents:` keeps any number of pairs, which the AppKit setter form could not express | Batch 4: control actions (`action-parameter`, `captured-handles`) in both compilers; 32 macOS-proxy cases (1,000 cycles, ASan/UBSan, wrong sender and thread, rejections). On the iOS 26.4 simulator a real `UIButton` and `UITextField` built by each compiler deliver actions, cancel inside a delivery and release their receivers (simulator evidence, not device evidence) | Codex's iOS shell can use it; `executor = "main"` and scene delegates stay open |
| 1 | Android JNI, step 4b: BTRC calls Java through checked JNI adapters | Batch 5: `Library.Java` (a host VM owner; a C runtime for the per-thread `JNIEnv` with daemon attach and detach, user reference claims, the class and member ID cache, UTF-16 strings and Java exception messages; the flake's `btrc-jni` package and JDK 17 in the dev shell). `language = "java"` bindings in both compilers: each selected class is a unique owner of one global reference, with constructors, static and instance methods and fields, `string?` and owner values. Every adapter frames its local references, checks for an exception after each throwing JNI call and turns a Java exception into the string `JavaException: <Throwable.toString()>`. Verifier rule 2 checks that shape in both compilers. Under `-Xcheck:jni` with no CheckJNI warning, both compilers pass the static call, field, constructor and instance call, `"aé𝄞"` round trip, U+0000 refusal, exception, 10,000 object calls with no claim left, and a BTRC thread attaching and detaching. The design's `dispatch-records` key was dropped: adapters call JNI slots by name and the C compiler checks them against `jni.h`. **Step 4's exit, batch 8 ([PR #80](https://github.com/schiffy91/btrc/pull/80)):** a library loaded into a running VM adopts it at `JNI_OnLoad` (`btrcJavaAdopt`; `JavaVirtualMachine.adopted()`; an adopted VM refuses shutdown, options and a second VM). On the hosted API 29 and API 36 x86_64 emulators, `app_process -Xcheck:jni` with `debug.checkjni 1` runs the checked round trip through both compilers (runs 39073481245 and 39075025637): a deliberate misuse first aborts with CheckJNI's report, proving the check is on, then the round trip exits 0 with no CheckJNI report from its process. The same harness passes under the host `java -Xcheck:jni` on the Mac | The 16 KiB-page arm64 image (MAC-P1-03; the library is linked with 16 KiB pages and every LOAD segment checked). Arrays, nested classes, weak references and executors are step 7 |
| 1 | Android JNI, step 7 slice A: Java `native` methods call BTRC receivers (`RegisterNatives`), which Android UI events, lifecycle callbacks and listeners need | Batch 11 ([PR #87](https://github.com/schiffy91/btrc/pull/87), `4a55cfcd`), in both compilers. A `natives` table on a Java binding names a factory, a generated receiver interface and the methods. Thunks run over one M2 holder per class and the `caller` boundary, installing the calling `JNIEnv` and restoring the previous one, so Java→BTRC→Java→BTRC nests. With `failure = "throw"` a BTRC exception becomes a `java.lang.RuntimeException` with its message. After cancellation a call raises `IllegalStateException` without entering BTRC. An adopted VM resolves classes through the loading thread's class loader. Host JDK 17 under `-Xcheck:jni` and the hosted API 29 and 36 emulators (run 39123303259) pass through both compilers: `java-natives-ok`, with no CheckJNI report from the process | Landed in batch 11 (`145ee34e`). Slice B is the next row |
| 1 | Android JNI, step 7 slice B: callbacks pinned to the main Looper thread, weak Java references, and primitive arrays | Batch 14 ([PR #91](https://github.com/schiffy91/btrc/pull/91), on `main` at `26cd93a8`), in both compilers. Primitive arrays become owner classes (`JavaIntArray`, …) that copy through `Get/Set<X>ArrayRegion`. A native's array parameter is a borrowed span released with `JNI_ABORT`, or mode 0 when listed in `writable-arrays`. `GetPrimitiveArrayCritical` is rejected. `classes.C.weak = true` generates `JavaWeakC`, which owns a `jweak`; `get()` returns a strong owner or null, and `liveWeaks()` counts them. `executor = "main"` on classes and natives checks the thread found through `Looper.getMainLooper().getThread()`. Host JDK 17 under `-Xcheck:jni` and the hosted API 29 and 36 emulators (run 39165219971) pass through both compilers: `java-arrays-ok`, `java-weak-ok`, `java-main-ok` | Private natives (reader v2), nested classes, object arrays, and the 100-cycle activity lifecycle |
| 1 | iOS: a BTRC `UIView` subclass hosts Metal, and `NSError**` calls throw (step 6, subclass slice) | Batch 13 (on `main` at `d6926879`), in both compilers. The header reader reports designated initializers and `NS_REQUIRES_SUPER`. Subclass adapters with `superclass` and `overrides` are keyed on a designated initializer's implicit self (`"-[UIView initWithFrame:].self"`). `error-outputs` throw `NSError: <localizedDescription>`. Lightweight generics are erased. On the hosted iOS simulator (run 39127803005), a `UIView` subclass with `+layerClass` returning `CAMetalLayer` and `-layoutSubviews` reaching BTRC runs through both compilers | Slice C ([PR #92](https://github.com/schiffy91/btrc/pull/92)): `UIResponder` delegates, protocol casts, AVAudioSession interruptions. Then the 100 scene cycles |
| 1 | iOS: UIResponder-derived app and scene delegates, Objective-C protocol handles with checked casts, and main-queue stored blocks (interop step 6, slice C) | Batch 16 ([PR #92](https://github.com/schiffy91/btrc/pull/92), on `main` at `105fdc72`), in both compilers with the same new diagnostics. The `UIApplicationMain` and `-[UISceneConfiguration setDelegateClass:]` adapters take `superclass = "UIResponder"` and `overrides`. A protocol whose instance methods are selected becomes a handle, and `(P?)value` asks `conformsToProtocol:`. `executor = "main"` on a stored block throws off main and posts a final release made elsewhere to the main queue. On the hosted simulator, the delegate is UIApplication's next responder and answers `-targetForAction:withSender:`; an `AVAudioSessionInterruptionNotification` posted from a BTRC thread reaches its observer on the main queue | Step 6 still owes 100 scene connect/disconnect cycles and the device rows (D8). Deferred: `id<P>` in signatures, static conformance, `executor = "main"` on delegates and actions |
| 1 | Parity: `--no-dce` builds through btrcc. btrcc refused every program that specialized a stdlib generic over a class (`import Library.Callback;` alone, and TOML, BackgroundJobs, JSON, Process, FileSystem, HTTP, Graph and Daemon on every row), which the reference compiled | Batch 16 (`e2eea387`): btrcc marks a generic instance's methods and accessors on demand and, without DCE, keeps only those something names, then refuses any deferred diagnostic left, as the reference's lowering does. Typed-operator refusals use the reference's words. `test_no_dce_parity.py` compiles each module alone on the host and both Android rows through both compilers, plus five generic-demand probes whole-program and as module units | — |
| 1 | Parity wave 2: both compilers index and store through members of C header records, keep loop narrowing, and apply one null rule to function pointers | Batch 18 ([PR #100](https://github.com/schiffy91/btrc/pull/100)). btrcc refused `found->gl_pathv[i]`; the reference crashed on `raw.c_cc[VMIN] = 1` and on `values[raw.c_cc[i]] = 1`, and refused `raw.c_lflag \|= 8`. Untyped C storage is now stored through as written in both. The reference lost a non-null fact inside a loop when a freed variable's address was reused (a spurious warning, probabilistic); escaped symbols are now kept per run. btrcc let `null` and `void*` into plain `CFunction`, `Thread` and `Mutex`, and ignored a function pointer's outer pointer level, so `= &f` compiled to C that strict C11 rejects; the reference refused `null` for a hosted callback parameter. The rule is in `docs/language/callbacks.md`. `test_parity_wave_2.py` (16) plus both parity batteries and 785 C-output programs pass | Wave 3, below |
| 1 | Parity wave 3: no conversion between function and object pointers, callable nullable function pointers once checked, and one null rule for every C function-pointer parameter | Batch 18 ([PR #106](https://github.com/schiffy91/btrc/pull/106), stacked on #100). Both compilers accepted `void* p = callback` and its relatives (lambdas, arguments, returns, field stores, ternary arms, casts on a nullable function pointer), which strict C11 has no conversion for; both now refuse them with the same message. A `CFunction<...>?` is callable wherever the null-check tracking proves it non-null, and diagnostics spell it `CFunction<...>?`. The reference now accepts array decay to `CFunction<int, int>*`, as btrcc did; both refuse storing an array's element pointer into one element's slot (`string? s = names`). Natively bound function-pointer parameters take `null` like hosted ones, and `_Nonnull` ones keep their check. It also fixes #100's regression in the self-hosted `test_native_c_values.py` case. 692 parity and native-value cases pass | Recorded wording differences remain (refused comparisons, keyword-in-expression errors); `optional ?? fallback` with a callback is refused as an ambiguous ownership ABI; native struct function-pointer fields refuse `null`; `printf("%p", callback)` passes btrc but not gcc's `-Wformat`; `string?` prints as `string*` |
| — | Local Mac gates must not take the owner's focus or raise Xcode's install dialog | Batch 12 (`4e1e520b`): with `BTRC_GUI_BACKGROUND` set, `MacOSApplication` asks for an accessory app (no Dock icon, never brought to the front at launch), and the gate script sets it. Sampling `lsappinfo front` at 10 Hz, 112 GUI cases passed with no test process frontmost in 12,795 samples; four had been frontmost before the change. The gate leaves out only the cases that need real focus (the native-shell AppKit baseline, typed-text delivery, the `NSAlert` and `NSOpenPanel` modals) and anything that runs `xcodebuild` or `simctl`. Hosted macOS CI still runs all of them | The owner's one-time `sudo xcodebuild -runFirstLaunch` re-enables the headless simulator tests locally |
| — | Hosted macOS CI flaked whenever GitHub throttled its build cache | Batch 13 (`0dd8d15a`): the Darwin overlay (`2e8e3711`) rebuilds Python 3.14 against upstream libffi for macOS 27, so no Darwin Python package is in cache.nixos.org. A throttled Magic Nix Cache (HTTP 418) then forced a from-source rebuild with upstream test suites, and pytest-timeout's pexpect case failed it. The overlay now builds those packages with `doCheck = false`, which leaves 46 derivations to rebuild. Batch 9 rooted the whole dev shell (`9da96a84`), after Determinate's GC had deleted `wgpu-native.pc` mid-run. Batch 10 gave the emitter-probe and native-compile fixtures the transpile budget | — |
| 1 | Android JNI, step 4a: Java class files become native declarations | Batch 4: schema `btrc.native-declarations.v3` with Java classes, methods, fields, objects and arrays, decoded identically by both codecs (18 parity and rejection cases per compiler, plus real reader output); `tools/JavaClassReader.c` (C11 + zlib, jar and class directories, public non-synthetic members, smali identities) with its flake package: 91 reader tests, 115 with JDK 17, ASan/UBSan and a 6,000-case fuzz clean | Step 4b (checked JNI calls): environment dispatch records, the `language = "java"` importer, `src/stdlib/Java`, verifier rule 2 and a host-JVM test under `-Xcheck:jni` |
| — | Gate flake: `Process.btrc` timed out in every Mac gate | It scanned `$TMPDIR`, which holds about 300k foreign entries, for files the implementation can't create (stdin uses an anonymous `tmpfile()`); concurrent scans stalled in the kernel. The scan is removed (batch 2): 160 parallel runs now take 1.7 s, where they previously hung | — |
| — | Mac gates kept losing the native header reader mid-run | Determinate Nix collects every unrooted store path every 30 minutes while the disk is 99% full (`determinate_nixd::gc` in `/var/log/determinate-nix-daemon.log`); the gate environments were unrooted. They are now rooted per commit. This is a candidate explanation for the hosted "reader could no longer be started" failure, not yet confirmed there | Check whether hosted runners run the same GC |

**Landed 2026-10-19.** `main` is `105fdc72`: batches 15 and 16 ([PR #93](https://github.com/schiffy91/btrc/pull/93), [PR #98](https://github.com/schiffy91/btrc/pull/98)), after the batch 16 Mac gate (`GATE rc=0`, 19,410 tests) and 40 of PR #98's 41 hosted checks. The 41st, macOS `tests (unit)`, failed on a GPU-readiness flake in the native-shell fixture (98 of 100 frames). Main's own macOS runs failed 4 of the last 6 times, each on a different load-sensitive test, so a stabilization lane is fixing them. Batch 17 adds the three Windows lanes above.

**Landed 2026-10-18.** `main` was `26cd93a8`. Batches 9–14 landed, each after a Mac gate (batches 11–14 gave `GATE rc=0`, every step green) and its PR's hosted CI:
- 9 + 10: COM step 5's exit, cache identity, HTTP inputs ([PR #85](https://github.com/schiffy91/btrc/pull/85), [PR #86](https://github.com/schiffy91/btrc/pull/86));
- 11: JNI step 7 slice A ([PR #87](https://github.com/schiffy91/btrc/pull/87));
- 12: background GUI sessions ([PR #89](https://github.com/schiffy91/btrc/pull/89));
- 13: iOS subclasses and the Darwin Python CI fix ([PR #90](https://github.com/schiffy91/btrc/pull/90));
- 14: JNI step 7 slice B ([PR #91](https://github.com/schiffy91/btrc/pull/91)).

Since batch 11 the Mac gate runs the GUI tests in the background and leaves out only the focus-taking and Xcode-invoking cases, which hosted CI covers. The locked-screen and simulator failures of earlier gates are gone from it.

**Landed 2026-10-17, second push.** `main` is `4db0a98a`: batches 5 and 6 ([PR #78](https://github.com/schiffy91/btrc/pull/78), [PR #79](https://github.com/schiffy91/btrc/pull/79)), after PR #79's hosted CI passed every check and both Mac gates showed only environmental failures (below). Batch 7 then gates as one unit with the target runner and the parity fix: the old batch 7 gate found two `test_native_plan_builder.py` failures from `e73f9c74`, fixed by `6d17f037`.

**Landed 2026-10-17.** `main` was `c976993b`: batches 2–4 ([PR #77](https://github.com/schiffy91/btrc/pull/77), which also closes #71, #72, #73 and #76). Batch 4's Mac gate passes every step: lint, format, generated, extension, bootstrap and the eight strict C11 cells (2,042 each). In `make test` the only failures are the four macOS native-shell cases that need an unlocked screen. Its hosted CI passes 39 of 39, including the new `win32-native` jobs on x64 and ARM64 Windows.

**Batch 5 gate (Mac, `549a00f4`).** It passes bootstrap and all eight C11 cells. `make test` has 18,544 passes and 10 failures, all environmental:
- the four locked-screen native-shell cases;
- six UIKit simulator cases. Since the Mac's macOS 27.0.1 update, CoreSimulator (1171.7) is older than Xcode 27 expects (1174.9.2), so `simctl` waits for an admin `xcodebuild -runFirstLaunch`, an owner step.

All Java and JNI cases pass.

**Batch 6** ([PR #79](https://github.com/schiffy91/btrc/pull/79)) adds the UIKit scene lifecycle and checked Objective-C downcasts. Before the update, a real UIScene app built by each compiler connected a window scene on the iOS 26.4 simulator.

**Batch 3 gate (Mac, `6fb97f8b`).** `make test` has five failures. Four are the macOS native-shell cases, which need an unlocked screen. The fifth is real: `test_record_member_owner_contract` did not allow-list the dispatch-table importer's two native layout reads. The fix is in batch 4, so batches 3 and 4 land together on batch 4's gate.

**Batch 4** (CF borrow, stored C slice A, control actions, JNI schema v3, the Java class reader, Windows SDK headers and the Win32 runner jobs) is more commits than D5's two to four: each Mac gate takes hours, so related compiler slices that already pass their focused suites through both compilers share one gate. A red gate is bisected by reverting one slice at a time.

**Batch 2 ([PR #76](https://github.com/schiffy91/btrc/pull/76)).** Mac results:
- Lint, format, generated and extension pass, and bootstrap reaches its fixed point.
- `make test`: 18,205 pass. Every failure is either the locked screen or the fixed `Process.btrc`.
- Mac `test-c11` runs in batch 3's gate, which contains batch 2.

Batch 3 adds dispatch, the UIKit delegates, and Codex's PR #72 (Linux image lifetime) and PR #73 (muted speaker).

**Batch 1 gate (Mac, `62fd3d65`).** `make test`: every failure re-run passes once the environment uses batch 1's own reader. The 69 reader cases had used 36b's reader. The four macOS native-shell cases need an unlocked session: the screen is locked, and the test's own pure-AppKit baseline control fails the same way. Lint, format, generated, extension and bootstrap pass. `test-c11` and hosted CI on [PR #75](https://github.com/schiffy91/btrc/pull/75) are in progress.

<a id="goals-versus-status-2026-10-08"></a>
<a id="goals-versus-status-2026-10-09"></a>

## Goals versus status (2026-10-12)

The owner's priority is correct cross-platform operation: the compiler, standard
library, native GUI and BTRSmith on macOS, Linux, Windows, iOS/iPadOS and Android.
Speed and memory targets remain required later outcomes under the
[approved stack rank](#approved-stack-rank). The Goal 1/2/3 labels below retain
their historical topic IDs; they are not priority order. Report working library
features and completed application journeys per platform, alongside separately
tracked benchmark actuals versus targets.
Branch consolidation, test counts and environment repairs support those goals;
they do not by themselves demonstrate faster compilation or delivered GUI features.

**Overall, checked for this update:** main `36b647f0` contains the consolidated
plan and the qualified compiler-reuse, native-build and GUI integration from
[PR68](https://github.com/schiffy91/btrc/pull/68). This is not completion of the
five-platform goals. Complete providers, BTRSmith journeys and final performance
acceptance remain open. The detailed dated snapshots below preserve prior results
and pending work; recheck changed source and claims before assigning execution.
There is no defensible overall percentage complete across differently scoped
capabilities and missing acceptance evidence.

### Delivery checkpoint (October 12, Europe/London)

GitHub main remains `36b647f0`, the exact tree qualified before PR68 merged.
The local clone hub's older `cf28fe74` is not GitHub main. Automatic post-merge
Linux, Windows x64, Windows ARM64 and Android workflows passed. Mac post-merge
qualification retains two failures: Clang O0 initially stopped in the upstream
pytest-timeout dependency's debugger test before C11 execution; eight WebGPU
cases in the unit shard failed before native execution because the configured
header reader could no longer be started. The unit shard otherwise passed
10,142 cases and skipped 227 expected cases. The reader was legitimately built
and checked during setup; its later missing launch prerequisite remains unknown.

The single accepted Clang O0 retry passed the original C11 tests in job
`114596824910` (run `37905525576`, attempt 2). That workflow remains failed
because the separate unit-shard reader failure is retained. The separate
reader-lifetime repair `ad46f269` retains both jobs' Nix outputs through teardown
and captures wrapper/interpreter/backend/closure evidence before and after tests.
Independent review caught and corrected the actual wrapper's `bash -e` shebang
handling. The 91 baseline and 106 candidate workflow/toolchain checks now pass.
The first test attempt retained a wrong-shell environment failure; the corrected
attempt uses the original authenticated Nix Bash. Real pre/post observations of
two retained readers also pass, including each reader's 47 dependency paths.
A disposable path was protected while rooted and deleted after removing its root.
That runner's result remains failed because its text classifier expected different
Nix wording; independent audit establishes the recorded protection/release behavior.
The original reader's disappearance mechanism remains unknown; final hosted
qualification of this repair is still required.

Combined memory/Windows source `3694ce58` passes generated/lint/format gates,
a fresh Mac self-host build, 200 focused cases with zero skips, the strict native
flow driver and four Windows SDK projections. Both frontends produce identical
C and ordered plans for both Windows targets. Independent audit `216b3812`
verifies process and input closure. Projections do not establish Windows native
execution; the component's four actual Windows cells remain separately scoped.
Full final hosted qualification and main integration of this combined tree remain.

The measured memory improvement is 32.96%, but the worst Linux candidate remains
about 685 MiB above 1.5 GiB. The reviewed phase-RSS diagnostic was published once
at `b4efe229` and manually dispatched once: run `38182812913` is in progress.
It locates remaining peak retention using authenticated existing compiler inputs
and fresh plain/observed output parity. It is not a final benchmark acceptance run.

Current Linux BTRSmith replay `37905070491` completed successfully, including
album/Settings, Library and actual installed-app smoke steps. Independent audit
`e759a38b` is clear: 24 agent/audio, 40 album and six Settings cases, 15 paired
plan comparisons, two 600-frame Library runs and two installed-app smoke runs.
All 18 captures were reviewed and 104 process receipts closed. This qualifies
those selected journeys, not the complete MVP or physical desktop input. The Player No-folder diagnostic passed catalog and
arrangement readiness, then timed out waiting for the song at stage 1; close
remained RETRYABLE_FAILURE. No speaker stimulus ran. Reviewed failure-only
snapshot `58bcd266` is ready to distinguish timeline, media and audio readiness
without changing deadlines; it has not run.

The iOS host-tooling port `af50005b` passes 28 original tests, the same 28 on the
current-tree port and four workflow contracts, with independent audit clear.
It remains separate because publishing those paths activates simulator jobs,
and oldest-installed selection does not establish D8's oldest-installable runtime.
Historical 50-case C fixture evidence does not establish current BTRC providers.

### Goal 1: fast compilation and bounded memory

Except for the explicitly identified Linux memory comparison, the measurements
below are the historical `65057cb` record, retained in
[the performance baseline](#recorded-performance-and-coverage-baseline).
Historical ratios describe that record's distance from the target, not a measured
regression or a forecast. Linux RSS does not replace Mac footprint acceptance. Stages 5–13 define the
remaining implementation and measurement work; their intermediate milestones do
not replace the final objectives.

| Workload | Final objective | Last recorded evidence | Goal status |
|---|---|---|---|
| Body edits in navigation, UI controller and audio preparation | Median ≤5 s; p95 ≤8 s | Medians 9.62 / 9.69 / 9.31 s | Historical medians roughly 1.9× the limit; current medians and p95 unqualified |
| Cold transpilation | ≤10 s | 43.57 s | Historical result 4.4× the limit; current result unqualified |
| Cold development build | ≥10× faster than frozen baseline and ≤min(20 s, baseline/10); working budget 13.5 s | 59.76 s | Historical result 4.4× the working budget; current result unqualified |
| No-op / touch | Stage 11 no-op optimization target ≤1 s; final runbook no-op/touch acceptance ≤5 s | 2.92 / 2.91 s | Historical runbook limit met, Stage 11 no-op target missed; current product-Make result unqualified |
| Cold release | ≤30 s | Final acceptance outstanding | Unproven |
| Warm batch of ten product programs | ≤30 s | Final acceptance outstanding | Unproven |
| Compiler peak footprint | ≤1.5 GiB | Current scoped Linux product comparison: median RSS 3.23 → 2.17 GiB (−32.96%); worst candidate 2,329,120,768 bytes. Historical Mac footprint 2.966 GiB | Worst Linux candidate remains 718,508,032 bytes (about 685 MiB) above the limit; combined integration and final Mac footprint acceptance remain open |
| Self-compilation and full corpus | Median wall time and RSS within 5% of Stage 5 baselines, or an explained tradeoff | Current baseline/acceptance round outstanding | Unproven |
| Parallel workers and module builds | 1/2/4/8-worker wall/RSS sweep; module release ≤110% of whole-program | Current acceptance outstanding | Unproven |

The Python reference compiler also retains its own final targets: transpilation
≤60 s, cold development ≤75 s, edit median ≤10 s/p95 ≤15 s, batch ≤60 s and
peak ≤1.5 GiB. Current acceptance is missing. The paired incremental mechanism
must prove that a body edit analyzes and lowers exactly one changed source group
and does not lower unchanged groups; passing intermediate timing budgets does
not close that requirement.

**Current measurement status (October 9, 08:47 UTC):** Corrected comparison
[37901757750](https://github.com/schiffy91/btrsmith/actions/runs/37901757750)
completed successfully on workflow `5f3103a2`. Baseline compiler `6f1b81d9`
and candidate `c8221ae4` used authenticated GCC 15.2 binaries on unchanged
product `dbe8df0e`. After two discarded warmups, three paired samples give
median peak RSS 3,470,024,704 → 2,326,315,008 bytes: 1,143,709,696 bytes saved
(32.9597%). The worst candidate is 2,329,120,768 bytes, still 718,508,032 bytes
above 1.5 GiB. Median elapsed time is 124.184 → 115.342 seconds (7.12% lower),
reported as an observation on the shared Linux host; instruction counters are
unavailable and this is not final speed acceptance.

All original 45 correctness checks and the native incremental-flow driver pass.
All eight compilations preserve the 422 C/header outputs and complete ordered
build plan under the original comparator. Independent audit `4bb27c36` verifies
the full 215,216,793-byte artifact, all 33,295 members, authenticated sources,
tools, reused binaries and process receipts. Report `0b309bb9` records the result.
Combined source `3694ce58` composes this work with current main and the
native-qualified Windows provider. Its fresh self-host and all 200 affected checks,
native flow driver, four SDK projections and generated/lint/format gates pass;
full final hosted qualification is still outstanding. Reviewed phase-RSS diagnostic `b4efe229` is running in hosted run `38182812913`
to identify the remaining peak before another ownership optimization is attempted.
The failed preceding comparison and its receipt-label repair remain retained.
Mac quiet admission and the full final workload matrix remain open.

**Earlier measurement preparation and retained evidence:** qualify the current compiler/BTRSmith pin, capture
the quiet workload matrix, isolate the repeated Linux peak-memory regression,
and measure the reduced changed-group work before the next optimization claims. The local
Mac memory diagnostic was cancelled before any sample because the quiet check
refused the host; it supplies no performance result. The token-lifetime paired
attempt has likewise not sampled: all 851 D9 workload files match immutable Git
blobs, but the quiet check flags idle simulator/transport helpers despite all
simulators being shut down. Process classification is under review; the CPU,
active-build, guest and full quiet-window requirements remain unchanged. Do not refresh a benchmark
baseline or relax a target to hide the outstanding regression. The reviewed
quiet-service classifier (`bc685ed7`, 92 focused passes) preserves the complete
60-second/5-second/5-percent rules and distinguishes idle trusted transports from
active jobs. The second attempt still takes no samples: the retained build shell
sets DEVELOPER_DIR to its SDK-only Nix package, preventing even the absolute
Apple xcrun from locating simctl. The probe must query the selected installed
Xcode without changing compiler SDK inputs. Reviewed follow-up `afda125e`
passes 93 checks and the actual retained-shell probe, reporting all 13 devices
Shutdown with the parent environment unchanged. The third attempt passes the
process and simulator probes but reaches its strict 180-second deadline because
Google Drive and mdworker do not sustain the required CPU limit; it takes zero
compiler samples. All three attempts remain retained. These Mac attempts establish no speed or memory improvement; system settings
remain unchanged. The separate Linux result below is scoped to its two fixtures. The current `3974d47b`
hosted benchmark run has one failing memory row: `CompileStdlibHeavy` uses
45,936,640 bytes against the unchanged effective limit of 45,838,336 bytes
(96 KiB over); `RunDispatch` now passes at 18,829,312 bytes. Token-lifetime
candidate `71352c50` and exact baseline `3974d47b` both build with the same
Nix Clang 21.1.8. Their 292 focused diagnostic, managed-literal and scope
checks pass with zero skips; candidate self-emission and literal C-byte parity
also pass. Archived source bytes/modes and actual tool identities are verified.
The immutable 851-file D9 workload is reverified. The current-source attempt
also stops at its unchanged 180-second quiet deadline: actual `mds`/`mdworker`
CPU exceeds 5%, while guests are stopped and all other probes pass. It records
zero compiler samples (`token-current-3974/quiet-diagnostic-1`), supplies no
performance result, and does not replace Stage 5 or the full final matrix. A separate
[focused Linux x86_64 comparison](https://github.com/schiffy91/btrc/actions/runs/37732563990)
ran the original heavy-stdlib/dispatch peak checks on baseline `3974d47b`
and candidate `71352c50`, alternating six checks with unchanged allowances.
The comparison has now completed with exact source/tool/binary checks. All
three candidate checks pass both unchanged allowances. Heavy-stdlib results are
42,139,648 / 42,283,008 / 42,102,784 bytes, versus baseline
45,924,352 / 45,961,216 / 45,760,512 bytes; baseline fails two checks. Each
original check reports its minimum of three runs. The median of the three
reported heavy results falls by 3,784,704 bytes (8.241%); even the worst candidate
is 3,555,328 bytes below the unchanged allowance. Dispatch passes all three
candidate checks too. The overall workflow remains failed because it preserves
the baseline failures. Independent provenance review is clear; source `71352c50`
still needs final combined-tree qualification before integration. Evidence:
`token-linux-peak-3974-hosted/independent-performance-review.md`. These small-workload peak limits are regression guards;
passing them will not establish the product compiler's ≤1.5 GiB footprint or
its final build-time targets. The next module-build memory proposal releases
each consumed worker reply after its independently owned output has been read;
its candidate `d7268b46` now builds with the original toolchain and verifies
source/tool identity. Generated C confirms that the local reply is retained
before its vector slot releases ownership. The first observer attempt stopped because its diagnostic text anchor also
matched an embedded runtime string, after the original CatalogMain compilation
succeeded. The corrected observer authenticates that completed baseline output. A second
comparison correctly rejected differing path-derived unit filenames; rerunning
only the candidate fixture with the same authenticated standard-library root
preserves all seven original emitted C files byte for byte. At both one and
three workers, the original compiler retains all six watched replies and the
candidate releases all six before the next record or batch end. All 18 selected
module semantics checks pass with zero skips, and both actual Apple Clang
ASan/UBSan runs pass without reports. Source/tool closure and independent review
are clear. Measured peak savings and final combined-tree gates remain pending. Combined
candidate `92691bee` contains only the token and worker-reply lifetime changes
plus their claim/report, based on `3974d47b`; the generic experiment is excluded.
It now builds with the same original toolchain and passes 164 focused checks
with no skips, failures or errors. The two emitted production functions match
the independently qualified component outputs byte for byte. Its first current
BTRSmith product measurement passes the original quiet admission and completes
the discarded baseline warmup, reporting a 3.053 GiB peak. The harness then
rejects the compiler's actual publication-lock files before candidate or measured
samples. This is no paired performance result. A reviewed exact empty-lock
classification correction is ready; the original quiet limits, sample order,
counters and targets are unchanged. A second attempt stops at the unchanged 180-second quiet deadline, before
any compiler execution. Background CPU and a transiently active agent transport
prevent a continuous quiet window; post-run inspection does not establish a
classifier defect. Both attempts remain retained. Approximately 2 GB of
completed historical output has now been archived with verified restoration
inventories, providing space for a later comparison. A separately scoped Linux
product RSS comparison is prepared on private BTRSmith branch `0b040ca3`, with
explicit public compiler inputs `3974d47b` and `92691bee`. It preserves the
original product source, strict compilation recipe and paired sample order.
Independent review is clear; private run
[37771609277](https://github.com/schiffy91/btrsmith/actions/runs/37771609277)
has failed while the original devcontainer recipe committed its realized Nix
layer: Podman reported `io: read/write on closed pipe`. No compiler comparison
or sample stage ran. The logs do not establish disk exhaustion or OOM as the
cause. Final container inventory is empty and source checks pass. Retain this
infrastructure failure; any unchanged-recipe retry follows the hosted capacity
limit and the one-retry infrastructure rule. Private product source and generated output remain in private CI.
Linux RSS cannot substitute for Mac footprint. Evidence remains in
`compiler-lifetimes-3974/92691bee/`. Deliberately retained compiler graphs remain
unchanged; the full final matrix is still required.

Two current-product diagnostic hypotheses have now been measured and rejected
as optimization priorities. The setjmp solve performs 134,606 definition scans
for 45,877 actual flows; this does not support the proposed sparse worklist.
Repeated native-header validation/construction is real, but its foreign-group native prefix
accounts for only 0.346 seconds of the instrumented 83.444-second phase sum.
Both diagnostic compilers preserve all 423 emitted C/header outputs under the
explicit path normalization, with independently verified source/tool/process
closure. These instrumented timings identify work; they are not performance
acceptance results. The larger lowering buckets require a measured causal
hypothesis before further compiler changes. A third diagnostic now rejects
foreign-declaration key preflight as the next high-payoff priority. Across 463
conserved unit notes, 1,011,434 foreign rejections discard 1,818,645 key-building
calls, but the complete preflight scan envelope is only 1.528 seconds; actual
declaration ownership/emission accounts for 11.676 seconds of the enclosing
13.949-second phase. Key construction is only a subset of that scan envelope.
All 423 emitted C/header outputs preserve exact normalized parity, source/tools
are unchanged, and all six build/count groups are closed. Result SHA-256:
`17c10a6305ec92ab6e5a94ff480b4c157487d9f12e89a7d02d3da5e988d3ff70`
in `declaration-preflight-attribution-3974-count-1/result.json`. No optimization
or performance acceptance follows from these instrumented counts. The adjacent-call
resolution diagnostic also rejects its hypothesis as the next high-payoff
optimization: across 62,135 pairs, the second-query envelopes total only
0.410560 seconds (identifier 0.060842; field 0.349718). All 926 group/path notes
conserve first/second/validation counts, with zero kind/environment mismatches.
All 423 C/header outputs preserve the recorded normalized parity; independent
review verifies input/tool/log hashes and closed process groups. The retained
result is `adjacent-call-target-attribution-3974-count-2/result.json`, SHA-256
`e774d8e2ee12c168f900e154e4d37fae4f30c49344228467252454e1a02570e1`. This is instrumented,
nonquiet attribution, not a speedup or product memory acceptance result. The
first build's diagnostic-only managed-to-raw pointer rejection remains retained;
the successful correction uses the existing nonretaining AST identity string.

A native stack profile of unchanged compiler `3974d47b` on product `d3fb25f4`
now completes with 7,091 main-thread samples and all 423 generated C/header files
preserving normalized parity. Exact process identity, original 240-second compile
bound, source/tool closure and owned-group cleanup pass. Receipt
`current-product-stack-3974-attempt-2/result.json` has SHA-256
`0d763bb83d497004da0ac51cff00da2b3c2d61449fa8ca3bdda2541fc80da806`.
These are intrusive attribution observations, not speed or memory acceptance.
The raw profile records macOS 27.0.1 (26A434), alongside the inherited required
host label macOS 27.0; neither is silently rewritten. The profile identifies duplicated body emission in both compiler implementations:
module-unit header selection renders the complete draft, then final emission
renders the same body again. There are 354 draft-emission and 351 other
module-emission samples among 7,091 main-thread observations. These overlapping
owner counts are attribution, not a savings estimate. A reviewed design reuses
an emitter-owned immutable body within one finish operation while preserving
complete-draft identifier scanning, final IR validation, prologue policy and
separate debug-line finalization. Paired implementation `72357bac` now provides
that reuse in the existing four emitter/pipeline owners. Independent source and
regression-test review is clear; Python lint/format and BTRC format pass.
The unchanged source/binary first passed all 18 affected checks, with no skips
or errors and all 17 groups closed (baseline result SHA-256
`486f06e71d7f3b53144825cc5148e467e6801b4b048262fd9c3662eedff55f78`).
Two host-environment preflight failures before testing remain retained.
The first traversal counterfactual unexpectedly passes on the unchanged
compiler: CatalogMain's plain C include provides no native binding metadata,
so it never exercises header pruning. Receipt SHA-256 `6143e8f4a8738bb82c6bcd2466793491c2d99226ec6a80e8ee5334fc1b8cc864`
in `module-emission-once/counterfactual/result.json` is retained as invalid-test
evidence; no candidate tests or build followed it. Fixture-only repair `8c7a8124`
now uses the real CoreFoundation native binding through the public compiler API
at one worker, checks actual retained/pruned headers and source-function visits,
and strictly compiles/runs the native result. Independent source review is clear;
production bytes remain identical to `72357bac`. The second attempt compiles
successfully but fails the fixture's bare-header assertion before checking traversal
counts: the native reader correctly preserves the resolved absolute header path.
Receipt `module-emission-once-r2/counterfactual/result.json`, SHA-256
`e0d26c7fe3a8a0be94ce22d661869d6f043142c9187075eb110e0d305d017e60`,
retains that fixture failure; no candidate tests/build followed it. Fixture-only
`660ac18d` now checks the exact resolved native header identity. Independent
source and recipe reviews are clear; fresh R3 preparation preserves all original
bounds, source/tool pins and the requirement for an actual repeated-body Counter
failure on baseline `3974d47b`. R3 now proves that counterfactual: both observed
source functions have traversal count two. The old control successfully
transpiles and checks header selection, then fails before its native C/run step.
Candidate `660ac18d` passes all 18 reference checks, including the six new cases
and strict native compile/run, with zero failures/errors/skips. The original
MacOSMain/Nix Clang 21.1.8 `-O2` build succeeds within its unchanged 1800-second
bound; fresh binary SHA-256 `181e0d52ebe87396427155304f4bdd42b9f685e718aff06bbee352e8943f6625`
then passes all 18 original paired checks with no skips/errors. Independent
review confirms exact source/tool/JUnit identities and all 42 owned groups
closed. Under `module-emission-once-r3/`, receipt SHA-256 values are:
counterfactual `2327cf60538dd5cf9431fcb251eb5ea650f4bc2adc4803ca1fe5f04442b90dc5`,
reference `f5bc22e9b3d6b77278274a2d2cb2fa64dd4c8c114f3b1fdb014ea66e4e382ee8`,
build `edb08b87c2b22a07589ea6afafc4c0fd2367dd6e82e62fd30ffd859a2280cbcc`,
paired `052063121c3f1553208f9076d0da158399de5301abcf658c982bda2c8efd13d3`.
Report commit `1dbe4717` records the focused qualification without changing
production. Current-product parity now passes for all 423 generated C/header
names and bytes after only the permitted output-directory normalization. The
original BTRSmith `d3fb25f4` workload and 240-second compile bound are unchanged;
the compiler exits zero at one worker, lowers 461 units and reuses none.
Independent review confirms source/tool/output closure and all three groups
absent/reaped. Receipt `module-emission-once-product-660ac18d-attempt-1/result.json`
has SHA-256 `7b11d8092a5725bc9e6dd6d6445956728ff1d100b806094cdfd504ddd36e553f`.
Existing nullable warnings and the historical delayed baseline-output hashing
limitation remain explicit. Report `7e4c3e30` records this result. The first
quiet attempt passes the unchanged admission and both warmups compile with
exit zero, but the comparison rejects their build plans before any measured
sample. Both plans correctly hash all 422 raw emitted units; 418 hashes differ
because debug directives embed the distinct output paths. All 423 normalized
C/header files remain equal. Independent review confirms this comparator defect.
The repair must authenticate every ordered raw digest before comparing digests
of the already-normalized content, preserve all other fields/order, and reject
corrupt hashes, missing/reordered units, source changes and other plan changes.
Failed receipt `module-emission-once-quiet-660ac18d-attempt-1/manifest.json`,
SHA-256 `87d5582de694d235b1a76b32e790b6fcd4861d8206a071415d2a28bfe30f7460`,
retains both discarded warmups and unchanged final inputs; both process groups
closed. No measured sample or performance saving is claimed. Report `dccaeb78`
records the failure. Quiet paired instruction/peak-memory measurements remain
pending; the snapshot's extra tuple/vector copy may offset the removed work.
Comparator R2 is now independently reviewed: runner `53840249`, pins `73e80f71`,
control proof `8667a5a5`. The original comparator rejects the actual warmups;
the corrected comparator accepts them only after authenticating ordered raw
hashes. Five controls reject corrupt hashes, missing/reordered units, semantic C
changes and other plan changes. An initial control-copy newline error is retained.
Quiet limits, sample order, deadlines and cleanup remain unchanged. This is a
comparator proof, not a new compiler or performance run.
The fresh R2 campaign subsequently stops at the unchanged 180-second quiet
admission before the candidate warmup. The baseline warmup succeeds and is
discarded; the candidate never launches and there are zero measured samples.
The retained admission observations show background mdworker CPU activity and
an active exec-server process; a later individually clear probe does not satisfy
the required uninterrupted quiet window. No threshold or deadline was changed.
Receipt `module-emission-once-quiet-660ac18d-attempt-2/manifest.json`, SHA-256
`f41d318c3586a53ca543dd4a3ff98114372ddfbcbddb80289e7b768e29a2a5b7`,
records unchanged final inputs and the sole owned compiler group absent and
reaped with exit zero. Independent review confirms refusal evidence only. The
local lane is released with 81.962 GB free; there is no automatic retry or new
performance claim. The reviewed ApplicationHost repair is next in the local
qualification lane. Hosted macOS unit and explicit GUI retries were live on
`00e45379` at the 18:00 UTC check. The GUI retry later completes with a setup
failure at 18:20 UTC: exactly 522 identities match between JUnit and skip report,
with 352 passed, 169 expected platform skips and one GPU case that never reaches
native entry because GUI-lease admission expires at 1,800 seconds. The recorded
last holder itself passes; polling contention supports a starvation diagnosis,
not a claim that one native child hung for 30 minutes. Independent review
reconciles all skips; the Make skip-gate command did not run after pytest failed.
The original 90-minute job limit was not reached. Log SHA-256
`bd17ddbfd2f99a969e3769e6e81227c7279a24d30857d7402a8fa9d08ae4265c`,
JUnit artifact `11569359756` (archive `648d1c6c`) and skip artifact `11570077383`
(archive `9d940f14`) are retained under
`/private/tmp/btrc-audit-repair/pr68-00e45379-macos-gui-attempt-2`.
Scheduling repair `37f0a63c` now passes all 84 focused coordination/reporting
checks (23 coordination and 61 existing skip-ledger cases), with no errors or
skips. The actual original-source counterfactual fails the intended competing-
worker assertion after all eight inner cases pass: GUI cases occupy three
workers instead of one. The repair groups marked macOS GUI cases on one of the
existing three workers in the explicit native-GUI workflow; the kernel lease,
original cases, skip rules and deadlines remain unchanged. Exact canonical
report identities survive xdist grouping without modifying live worker reports
or stripping literal parameter suffixes. Controller-synthesized crash reports
remain fail-closed. Receipt `macos-gui-scheduling-37f0-attempt-1/result.json`,
SHA-256 `e1b95fcb0c1e08df6fc8d9b45a8478bb6dc3013749f40f6403a4d1117b7a7db9`,
records all eight owned process groups closed and source/tool/archive closure.
The report/claim is committed at `40bbafd3`; independent retained-result review
is clear. The full hosted native-GUI rerun remains required. This is process/reporting
evidence, not new AppKit execution or final combined-tree qualification.

The unchanged macOS unit retry finishes at 19:06 UTC with 10,127 passes, 227
expected skips and six failures, with zero setup errors. All 920 failures/errors
from attempt one now pass. Each new failure is ENOENT launching the same selected
absolute Nix GCC wrapper; no GCC or generated-C diagnostic is reached. The six
Clang counterparts and 210 other GCC-parameter cases pass. Failure alone cannot
distinguish a missing wrapper from a missing script interpreter/loader, and
there is no evidence yet establishing garbage collection as the cause. The
10,360 case identities match attempt one. Log SHA-256 `d64591d3` and artifact
`11573200267` (archive `cf8da9ee`) are retained in
`/private/tmp/btrc-audit-repair/pr68-00e45379-macos-unit-attempt-2`;
`audit.json` records the source/chronology review. No JUnit artifact was uploaded;
the retained unit skip ledger and job log supply these counts. Diagnostic
source `66047414` now captures bounded metadata at initial compiler selection
and at an actual selected-executable FileNotFoundError: wrapper/symlink/store
ancestor and readable shebang interpreter identity. It does not re-resolve,
replace, skip or retry the selected compiler, and preserves the original test
exception/outcome. The existing selection baseline has 15 passes; the candidate
has 109 passes (25 selection/diagnostic, 23 coordination and 61 skip-ledger),
with no errors/skips and exact collection/JUnit correspondence. Real controlled
wrapper/interpreter/parent removal and nested pytest failure reporting are
covered. Receipt `host-compiler-launch-66047414-attempt-1/result.json`, SHA-256
`74dfdf9306a63b439d99d0d49749754fba8aa80b9eb56427cfb7d41ae8fa0372`,
records unchanged source/tools and all eight owned groups closed; independent
review is clear. Report commit `decb5fd4` retains the unresolved hosted cause.
The diagnostic and scheduling changes are published in PR68 head `6f1b81d9`;
hosted merge `e10d8bab` has the same tree `5505ab70`. New Linux `37833377148`,
macOS `37833377244`, Windows `37833377072`, ARM64 `37833377199` and Android
`37833377200` workflows started at 19:37 UTC. Windows tests and Android tooling
pass. Windows bootstrap and both Android API 29/API 36 emulator lanes have since
passed, as have Linux X11/Wayland GUI, both compiler corpora, bootstrap and the
unchanged benchmark regression gate. Remaining Linux checks and Windows ARM64
native execution are running. Linux release and five C11 configurations now
pass, but its unit job `113504242493` fails at 20:34 UTC with 7,245 passed,
3,128 skipped and two failures. One workflow assertion still expects the old
command without loadgroup; the nested-report observer identifies the controller
as a worker using an inherited environment variable. Test-only repair `69e0b5d8` now reproduces both original failures and passes
all 110 focused candidate checks, with zero skips/errors. It identifies the
nested controller by actual pytest runtime role while preserving worker IDs,
canonical report identities and phase correspondence. Independent audit
`7eece4a55decb8cc3940e38f89f04196a6305faefa5300dbfa6aed5a0a611f4e`
closes all eight groups and exact source/tool/archive/log/JUnit inputs in
`linux-unit-gui-regressions-69e0-attempt-1`. This repair is locally integrated;
published PR68 remains at 6f during its active qualifications. The original outer
ledger's 10,375 identities reconcile exactly; its 3,128 skips are expected. The
standalone skip gate did not run after pytest failed. macOS reference corpus passes; remaining
checks run or queue. Its x64 bundle job `113504238329` hits the 45-minute limit
while building Nix dependencies, before compiler-bundle output. Retained log
SHA-256 is `a0864785d72863263063e9d790d9a9b639f77765605e46ae23aa2b187886711a`.
These are current-candidate component results, not full final qualification or
product performance/mobile-GUI acceptance.
The required separate native-GUI dispatch `37835919865` started at 19:58 UTC
on this exact head, with the reviewed worker grouping and original bounds.
At 20:34 UTC it reaches the actual native-GUI test command after SDK-reader
preparation; it is running, not merely queued.
At 21:12 UTC, Windows, Windows ARM64 and Android workflows are complete and
successful. Linux is terminal with every selected job except unit passing,
including all eight C11 configurations, both corpora, bootstrap, release/ARM64
bundles, X11, Wayland and benchmark regression. The unit failure and locally
qualified test-only repair remain recorded above. Mac both corpora and Clang
O0/O2 pass. At 21:28 UTC its bootstrap and ARM64 bundle also complete
successfully; unit, self-host tests and the separate native GUI test job remain
live. Its x64 job exhausted the unchanged 45-minute bound
realizing the full development shell before compiler-bundle output. A source-only
release-shell repair `3b64240e` preserves the original Python/compiler/SDK tools,
checks and deadline while omitting test/LSP dependencies. The subsequent October 9
evaluation below passes; actual release-bundle qualification remains open.
No unchanged third retry or combined hosted pass is claimed. Do not change the
published head during qualification. PR68 remains unqualified until the combined
final gates pass.

October 9 final audit of that exact head: the explicit Mac native-GUI run
`37835919865` succeeds with 353 passes and 169 expected platform skips. Its
JUnit and skip ledger have exactly the same 522 canonical identities. The full
Mac matrix also passes self-host tests, bootstrap and the ARM64 release bundle.
Unit finishes with 10,147 passes, 227 expected skips, the two known test-contract
failures repaired by `69e0b5d8`, and one additional setup error: tray lifecycle
reference/plain exhausts the unchanged 1800-second GUI lease wait. The recorded
sanitized self-hosted shell holder ultimately passes; the same tray row passes
in the dedicated grouped GUI run. No missing GCC-executable failure recurs, but
its earlier cause remains unproven. The unit workflow lacked the scheduler
opt-in used by the dedicated GUI job. Source `dbdc50d2` now applies the existing
loadgroup scheduler only to unit, retaining every row's selection flags and
three workers. Focused qualification now passes the original two baseline
contracts and all 102 candidate cases (79 workflow plus 23 coordination), with
zero failures, errors or skips. All eight owned process groups close and source,
archive and tool inputs remain unchanged. Independent audit SHA-256 is
`7f81ea57547b81f89eef765d5d4556217956863d6a596c2063346db8a1e31934`.
The change is integrated locally at `c782ace8`; actual full hosted unit replay
remains required before main integration.
Independent final Mac audit SHA-256 is
`69334cb33bf0a027c9d02281083fbffff67497c68be928263bc041718244ade2`
in `/private/tmp/btrc-audit-repair/pr68-6f-final-mac-oct9`.

The first local release-shell evaluation fails in its diagnostic expression:
a global ROOT substitution corrupted the BTRC_NATIVE_SYSROOT attribute into a
path. Both existing default/platform derivations otherwise match exactly, but
that attempt did not compare actual SDK values. Reviewed correction uses one
unique complete flake-URI placeholder and retains strict equality. The second
attempt is refused before any Nix command because actual free space falls below
80 GB; that attempt executes no commands. After verified recoverable archival,
the third evaluation passes for both Darwin architectures: existing default and
platform shell derivations and all metadata match exactly; the release shell
retains the original Python interpreter, five tool outputs, native SDK, reader,
target, provider compilers and hardening. The ARM64 derivation graph falls from
1,977 to 1,097 derivations. This is dependency-graph evidence, not realized disk,
build-time or release-bundle acceptance. Result SHA-256 is
`e94b5034776610c082e3c68454fadefd35a98936617977ba6fa99b5a19abdd0a`;
independent review is clear. Original bundle builds and relocated strict-C11
smokes remain pending. No gate threshold is reduced. The first combined workflow check
finds a new assertion comparing YAML text "45" with integer 45. Source `e893e174`
corrects only that assertion, preserving the 45-minute workflow limit. Combined
source `3a3304dd` passes all 102 workflow/coordination checks and the release source
passes its affected contract: 103 total, zero failures/errors/skips, independent
source/tool/process audit clear. Actual ARM64/x64 bundles and full hosted unit
qualification remain pending. Read-only Nix admission advertises only the shell
derivation to build; all selected release tools already exist.
The reviewed current-compiler IR allocation census
uses exact 6f compiler and dbe8 product sources. It now passes both actual
cold, single-worker product compiles and equality of all 423 emitted C/header
files; all 461 source groups are lowered with zero reuse. Three conserved
snapshots show 3,219,828 unique live IR nodes occupying 1,236,413,952 allocator
bytes after lowering and final demand. The separate 64 MiB observer is excluded.
Independent audit is clear, with all ten process groups reaped and absent and
source/tool inputs unchanged. This is allocation attribution, not quiet timing
or final memory acceptance. The [current IR census](docs/workstreams/current-ir-node-census.md)
records exact evidence and the next implementation: a compact fat-tagged core
with optional typed payloads, modeled at roughly 510 MiB reduction including new
allocation/edge costs. The compact representation and every production consumer
are implemented on a separate candidate; parser/receiver audits find no old
field accesses. Executable qualification first exposed a fixture nullability
warning, retained as attempt one. After a test-only replacement correction, all
three authentic old-layout native drivers pass. Candidate `5d092d0f` then fails
all four reference model cases before C emission: boolean payload selections
are inferred as integers and repeated nullable list projections do not narrow.
Model-only correction `043cfdaf` keeps the tests unchanged and uses checked
nullable locals plus typed short-circuit boolean selections. It now passes all
four reference-fronted native Model cases with zero failures/errors/skips,
authenticating the three existing baseline passes without rerunning them.
The cases prove defaults, shared metadata/statement-vector identity, child
replacement, derived destruction, a payload ownership cycle and exact canonical
ordering. Independent audit verifies all inputs, generated outputs and process
closure. Generated C uses the concrete payload ARC metadata and payload receiver
for cast-store ownership. This qualifies the model through the reference frontend;
the complete compact compiler, paired self-host tests, actual allocator sizes,
current-product output parity and memory/instruction savings remain open. The
first full MacOSMain build of `043cfdaf` fails during reference compilation:
boolean payload ternaries in the setjmp safety owner and C emitter infer integers
inside `&&`, while repeated nullable projections in the optimizer and emitter
produce warnings. No C compiler build or any of the 37 selected paired checks
runs. The attempt finishes in 46.51 seconds, with source/tool inputs unchanged
and all owned process groups closed. Four-consumer correction `61d60799`
preserves the Model and tests and fixes boolean selections and nullable narrowing.
Its fresh MacOSMain compiler now builds with the original strict Clang 21 O2
settings and passes all 37 focused cases: eight paired Model executions,
17 structured-IR cases, eight runtime-provider cases and four lazy-list cases.
No failures, errors or skips occur. Independent audit verifies source/tool and
binary identity, the inherited Model proof and all six closed process groups.
The failed attempt remains retained. Current BTRSmith output parity now passes;
paired memory/instruction measurements remain open. The first current-product paired
attempt stops at the original 180-second quiet deadline before either compiler
executes. Background CPU, guests, simulators, backup and workspace probes all
pass; a VS Code Codex app-server matches the unchanged agent-process refusal.
Its observed low CPU and absent descendants do not prove that it has no active
work. The process and quiet rules are unchanged. Independent audit verifies all
101 inputs and zero compiler samples. A separate correctness-only compile now
passes for exact compiler `61d60799` and product `dbe8df0e`: all 461 groups are
lowered with zero reuse, and all 423 C/header names and contents plus the complete
ordered link plan match the authenticated original `6f1b81d9` output. It uses
only the existing output-root and authenticated unit-digest normalization. No
measurement wrapper runs. Independent audit verifies 108 recipe pins, 115 inputs,
unchanged source/tools/outputs and three closed process groups. Result SHA-256:
`3035088ec253993273c09fe63b1b96756dfdd2cfbe253a02b1f8ad737d6dafc1`.
This proves emitted-output compatibility, not native application execution or a
speed/memory gain. Independent retention
candidate `266cadd7` keeps per-node setjmp facts only for fixed safety roots while
solving and exporting every function summary. The original `6f1b81d9` baseline edit passes;
the candidate passes the same production incremental edit and six added cases,
without skips/errors. Weak references prove non-root flow objects are collected,
and the ordinary Lib unit still exports changed effects. Independent audit is
clear. The fresh MacOSMain compiler now builds with strict Clang 21 at O2 and
passes all five focused self-host checks with zero skips/errors, including the
production incremental edit. The new driver also projects through that fresh
self-hosted compiler and compiles/runs as strict C11 O2 with the expected output.
Independent audit verifies exact inputs and all nine closed process groups.
Current-product output parity, remaining worker coverage, generated ownership
inspection and original performance gates remain. See
[flow retention](docs/workstreams/setjmp-flow-roots.md).
Combined source `c8221ae4` preserves the compact domain-guarded array-bound
traversal, immutable safety roots and complete summary/dependency computation.
Independent source review is clear. Its native flow driver exercises actual
module-unit root selection for direct, call-argument and array-bound-only setjmp
nodes, plus exclusion of an ordinary function. The fresh combined MacOSMain
compiler now passes strict Clang 21 O2 construction, all 37 compact checks,
all seven reference flow checks and the actual self-hosted native flow driver.
There are no failures, errors or skips. Independent audit verifies 78 inputs,
4,507 source files, 4,860 workspace artifacts and all 11 closed process groups.
Result SHA-256: `5914461928bb9fd595f77b088fc4578220398345f6c2da7427cb720108549ce9`;
audit SHA-256: `457ae6be1e60b5c7c44c7d7bffb2b7c544222754bc72d2db5a4b4cd78249ffc2`.
The production incremental-edit case through that same btrcc now also passes:
only the changed source group and affected consumer are lowered, and incremental,
clean and whole-program outputs agree. Its subsequent direct current-product
compile lowers all 461 groups with zero reuse and preserves exact names/content
for all 423 C/header files and the full ordered plan against the authenticated
6f baseline. Independent audit verifies 133 recipe pins, 143 inputs, 235 edit
artifacts and all five closed process groups. Result SHA-256:
`51f67e69af607fc8bcc3962541a962f5d3016fa0965b560d11f14cde8818881a`;
audit SHA-256: `f36ce4f988d7d3b2e456f574b661dea79187d953ef114f49172c2490432d896a`.
The combined candidate has 45 focused passes plus the native flow driver and
current-product emitted-output parity. Full compiler/platform qualification and
native product execution remain separate. A paired Linux current-product
comparison is prepared and independently reviewed as private BTRSmith workflow
`4f7e7c17`, with matched Linux-built baseline/candidate compilers, original
eight-run order and exact Linux output/plan parity. It requires the same 45
focused cases and native driver on Linux before sampling. It is not published
or dispatched. The exact compiler source `c8221ae4` is now published on
`codex/compact-ir-flow-roots-6f`; source publication triggers no additional CI.
The private workflow will report Linux RSS/instructions where available, not
replace Mac footprint acceptance. The same VS Code app-server still blocks Mac quiet admission; no
unchanged retry was launched. Product speed and memory targets stay open.

Both October 9 diagnostic runs are now terminal failures, with narrower
progress retained. BTRSmith `37864640752`, exact dbe8/f75, passes all four
channel and all four standalone CLI/MCP cells, plus both reference live-app
journeys. The first self-host/Clang live-app run fails when navigation.show-settings
returns code 1 for revision 5. Captured stdout is absent from the fixture's
failure message, so the actual protocol error is not established. Diagnostic-only
source `8e58bd76` now retains a bounded response in that same failure path;
reviewed replay `cd705952` starts automatic run `37869903754` with original full
stage bodies and bounds. That replay is now terminal failure. The retained
response explicitly reports a stale application semantic-state revision for the
revision-5 navigation request. Why the expected revision moved is still under
investigation; no retry or relaxed revision check is accepted as a repair.
Self-host/GCC live, audio and installed-product acceptance remain open. Artifact SHA-256 is
`738a0ab195497ba76f4c69bc7309735818b16bb6415960136c5777bebb52e862`.

Linux Window `37865587336` builds its image/compiler but refuses its semantic
baseline: two missing SDK bindings cause five unrelated SDL diagnostics alongside
expected missing-owner errors. No candidate native case runs. R2 adds only
SDL_WINDOW_MINIMIZED and SDL_EVENT_WINDOW_RESTORED identically to both role
manifests and recognizes only source-location-bound missing-owner cascades;
18 classifier controls reject unrelated errors. Exact source fe9e0c00 and
diagnostic f1428db0 start automatic run `37869472960`. R2 accepts all four exact
semantic baseline failures, then all four candidate C compilations reject an
undeclared fixture helper. No native case runs. The manifest lacks
`manifest-version = 1`, selecting legacy dependency-only metadata and excluding
the helper's native header/source. R3 adds that one line identically to baseline
`b9055d37` and candidate `bd2235f2`; actual f75 package resolution proves both
native entries are selected while an unimported helper stays excluded.
Diagnostic `e2b3619f` starts automatic run `37871496188`. R3 is now terminal:
all four exact baseline failures are accepted, and all four candidate projections,
strict C builds and links pass. Real native execution then reaches the same
queue-pressure assertion in both frontends, plain and sanitized, after the
earlier close/save/cancel checks pass. The failed predicate requires one state
callback and no close request after one semantic dispatch; the actual counters
are not captured, so a resize-settlement explanation is still a hypothesis.
Source/tool/binary closure passes. All three artifacts remain retained; provider,
assertions, four native cells, classifier and deadlines are unchanged.
R4 retains the original resize request and all pressure assertions, adding a
bounded real SDL event-pump prerequisite: actual size 180 by 110, exactly one
pending semantic record and neither callback delivered. The five-second native
settlement bound fits inside the unchanged 30-second case bound. Baseline
`dc73ce96` and candidate `fbb9e27a` carry the identical fixture change; classifier
changes only move six expected source coordinates. Reviewed diagnostic
`d6242d3e` starts automatic run `37874567498`, which passes. Independent review
authenticates the complete artifact, all four exact semantic baseline failures
and all four candidate native passes, with zero skips. Source, tool and binary
identities are unchanged; all eight process leaders are reaped and the container
is absent. This qualifies the Window component against compiler `f75c737b`.
Coordinated quit across multiple dirty Linux windows is the next provider change:
one cancelled member must preserve every window, draft and live work ingress.
Capture occurs when SDL's event pump dequeues QUIT. Reviewed Linux source
`32b361b2` now coordinates group authorization across dirty and clean windows,
keeps every window alive when a peer cancels, seals publication/work ingress
before releasing retained identities and supports retryable/reentrant cleanup.
Four native fixtures cover initial cancellation, revised/saving/stale decisions,
registration and membership changes, cleanup reentry and a real trylock failure.
The late-reply and already-authorized CANCEL branches are explicit. The planned
qualification compares fixture-only baseline `647363f9` with the candidate using
current compiler `5aa232ad`: one exact native failing predicate on the baseline,
then 28 candidate cells across both frontends/plain/sanitized, including existing
Window/Executor/Lifecycle regressions. The independently reviewed hosted recipe
is committed as `e6f076e5`; 23 synthetic classifier controls pass, and retained
real reference output supports its generated-expression matching. These are
preparation checks only. The workflow is not published or dispatched, and no
compiler or native execution has qualified the new group-quit source. Complete Linux GUI
and final combined-tree qualification remain open.

The qualified CI repair assembly is now published as PR68 head `5aa232ad`:
Windows ARM64 `37873882639`, Android `37873882709`, Windows `37873882883`,
macOS `37873882641` and Linux `37873882738`. Windows, Windows ARM64 and Android
workflows pass. Linux now completes successfully, including unit/self-host tests,
both corpora, bootstrap, all eight GCC/Clang C11 configurations, X11, Wayland,
benchmark guards and x64/ARM64 release bundles. Release also supplies the selected
lint, formatting, generated-source and extension checks; its scoped static-job
skip does not omit those gates. Independent final Linux audit is clear: all 18
artifact ZIP digests match, every skip is expected and enforced, and GUI JUnit
identities agree. Boundary coverage is 287/311, with the established 24 managed
behavior exclusions; GUI skips include one real-desktop hardware case. Audit
SHA-256: `414810d8b7af251dba590c0ec6eb95be6196eefe351d53439f8a6df03422c1e1`.
Both Mac
release bundles, self-host tests, bootstrap, both corpora and Clang O0/O2 pass;
Mac unit finished with two nested-test configuration failures; the focused
repair now reproduces both failures and passes all 84 affected ledger/coordination
checks. Hosted qualification is pending. Dedicated macOS native GUI run `37877458498` has
completed successfully on exact `5aa232ad`: 353 passes, 169 expected platform
skips and no failures/errors. Its independent source, artifact and skip audit is
clear; two Linux tray rows remain explicitly uncovered. The memory candidates
and new UI2 provider work remain separate. Main stays `cbd3ddcd`; Mac unit and
its final evidence audit are still required before integration. BTRSmith's
reviewed `2c9e5b43` live revision fixture now has a peer-cleared current-compiler
qualification workflow `16d69500`, pinned to exact `5aa232ad`. All original
acceptance commands and limits remain unchanged. The earlier `db9bc814`/`f75`
recipe remains retained and unpublished. Exact product source `2c9e5b43` is
published privately on `codex/live-agent-revision-recovery`, whose tree contains
no workflows. Workflow `16d69500` was published once by fast-forward to
`codex/linux-current-compiler-3974`; automatic push run `37883596677` started at
04:22 UTC October 9. Source/environment preparation passed; the original paired
live agent acceptance is running at the latest 05:19 UTC check. Audio failure
journeys and installed-product checks remain pending. No duplicate dispatch was
made. After Mac unit finished, private paired Linux memory workflow `4f7e7c17`
was published once; automatic run `37885703276` began at 04:49 UTC. It compares
baseline `6f1b81d9` with compact/flow candidate `c8221ae4` against exact product
`dbe8df0e`, with unchanged qualification and measurement bounds. Source and
workflow publication are verified. Both canonical Linux compilers built, and all
45 focused checks plus the actual native flow driver passed. The run then failed
at product-tool admission: the product environment omitted the SDK reader,
target and sysroot exported by the compiler environment. No product compilation,
warmup or measurement ran. The authenticated failure audit is `84366846d2d3497ad286db8dac3e397a419ee472e9806037c255b9524953ffe3`;
its binary addendum `f44cea16441bcf308aabc060209604fd52ff268db429c3f995bea632b9be5d84`
verifies both actual binaries and generated C. A minimal environment-composition
repair passes eight shell checks and is committed as `59108aad`, with the other
15 embedded helpers unchanged. It was published once by normal fast-forward at
06:31 UTC after the Linux product replay finished. Automatic push run
[37893971479](https://github.com/schiffy91/btrsmith/actions/runs/37893971479),
job `113700966212`, is building both canonical Linux compilers serially at the
06:49 UTC check. No manual
duplicate dispatch occurred; actual measurements remain pending.

That terminal run released a hosted slot. Qualified Mac test-helper `a29ab3e3`
was published once by normal fast-forward to PR68 at 05:32 UTC, preserving the
84-pass test bytes and ordinary checkout. Automatic workflows are Linux
`37889064844`, macOS `37889064858`, Windows `37889064843`, Windows ARM64
`37889064907` and Android `37889064913`; no manual duplicate dispatch occurred.
At the 06:49 UTC job-level check, all Windows x64/ARM64 and Android jobs have
passed. Linux release bundles, X11/Wayland GUI, bootstrap, benchmark guards, all
eight C11 cells and both corpora have passed; selfhost/unit test shards remain
running. macOS both release bundles, selfhost checks, bootstrap, both corpora and
Clang O0/O2 have passed; its unit shard remains running. Dedicated final-head
native-GUI qualification remains required. Windows/Android exact-tree logs are independently audited: Windows has 39
pytest passes and three expected POSIX skips, extension 79 passes/six explicit
Windows skips, and a successful native bootstrap. Android has 56 actual emulator
fixture executions across API 29/36; ARM64 remains compile-only. Audit:
`153fdfbd73f7738fdd6a9e61a101832caf730eb2a3efe65d1854319b4c5946df`.
The Windows release ZIP payload has not been downloaded locally; its in-job
checksum/smoke and upload digest are retained. This does not close other lanes.
The top-level queued labels do not imply that all jobs are idle. PR68's description
now matches current head `a29ab3e3` and its actual qualification scope. This PR68
wave and memory comparison `37893971479` now occupy both hosted slots. Required
final-head GUI qualification is now part of that same PR68 wave: Linux
37896628801 and macOS 37896651788 were each manually dispatched once with
focus=native-gui on unchanged a29ab3e3. Each manual dispatch has its own run-ID
concurrency group, so it does not cancel or restart the remaining PR test jobs.
Original job selection, deadlines and skip gates stay unchanged; there is no
additional private product/provider qualification wave. BTRSmith
replay `37883596677` completed successfully, including its original paired live-agent
and audio-failure journeys, installed-product check and final source closure/upload;
independent scoped audit
`3a9c9028479681a60b949698da6868e0f3ebf4788674c384e4df7711905035dd`
confirms 24 native executions: 12 agent scenarios across both frontends/Clang/GCC,
and 12 audio/scanner scenarios including four intentional terminal aborts. Four
audio plan comparisons and the current-compiler derivation/install-layout check
pass. It authenticates 847 product and 4,506 compiler Git blobs and four successful
stage leader receipts. The installed app was not launched in this run. Artifact
review extracts 31 small members with CRC/SHA checks, not the full ZIP or all
binaries; the remote owner records group cleanup but no final empty-group
assertion. These limits remain explicit. It covers product `2c9e5b43` with compiler
`5aa232ad`, whose production compiler inputs match `a29ab3e3`; the newer album
repair is separately qualified below. Native Linux quit `e6f076e5` remains queued.
Main integration and any measured compiler improvement remain unclaimed.

The current product review also found a concrete Library source defect against
PRD lines 53–55: `CatalogAlbumMerge.related` permits unknown years, two-year
release differences and small edit distances, while `AlbumName.mergeKey` folds
accents. These can silently combine distinct releases. The next product
implementation must use the existing conservative identity rules (same artist,
same known year, approved formatting only), preserve recordings/arrangements,
and refresh old derived memberships from authoritative sources. Existing songs
do not retain their original per-song year, so a migration must not invent it
from a merged survivor; failed or unavailable roots must preserve current data
and expose unresolved state. A new fixture-only baseline now proves the defect
through actual SQLite publication and the current-equivalent compiler: safe title
formatting consolidates to one album, then distinct 2006/2007 releases incorrectly
remain one instead of two. The native process aborts at that exact generated
count assertion. Baseline audit `6d7c8d0a9f6f6ecd5807f7cce996872fcf2675ea4d7c7c6749f89d6547e5135b`
authenticates all sources, compiler/tool inputs, generated C/plan/binary and six
closed groups. Earlier attempts stopped before compilation because of an archive
mode expectation and an incorrect Make owner; both are retained, and an actual
same-shell dry run confirmed `tests/Makefile` before the successful reproduction.

The production repair is now committed as `2a15e4c` after independent source
review. It removes fuzzy consolidation, preserves full legacy album rows in
recoverable storage, moves unverified old memberships away from canonical IDs,
and invalidates cached summaries for authoritative refresh. Unknown-year titles
retain authored formatting; failed/offline sources retain their records. Obsolete
schema9 rekeying and schema10 display cleanup are retired before preservation,
while version transitions and earlier migration/rollback/pagination oracles remain.
There is no new UI-badge claim: source-summary staleness is explicit in the record.

The complete AlbumReconciliation native fixture now passes through both current-
compiler frontends, followed by the original LinkPlanParity check. Each execution
reaches all 14 policy observations, both schema11 refresh orders and the schema9
migration journey before its completion marker. Both generated mains contain 98
actual assertion sites. Result SHA-256:
`a253d4f1c06fdd165a3d219ce1f563e665fe61a50406e2bb34ffb8352eb862dc`;
independent audit `86cc0b0d6f56d13b4497cf56bf5f62a827b3ca41b5caf37284e5161e47e2c5a1`
verifies 23 pins, 847 product files, 4,502 compiler files, 154 generated files,
original SDK/tools, 24 logs and 12 closed process groups. This repairs the
reproduced album-grouping defect in the native fixture; full product acceptance
still requires the surrounding catalog/format regressions and application journeys.

The next regression selection preserves nine original programs and their compiler
matrix: Clang/GCC through both frontends for eight programs, and PSARC's native/
Clang/GCC through both, for 38 native executions plus nine plan comparisons.
PSARC retains its actual fixture setup/cleanup owner. The bounded recipe passed
independent review. Attempt 1 passed eight native checks, then stopped after
Make successfully linked the next SQLite fixture and deleted its generated C/plan
intermediates. This was evidence-retention failure, not a native test failure; two
fixture nullability warnings are retained. Audit:
`22ed3c5f14ebdb548f87d7bc87655365592afb300379185938ec8f82a353655d`.
The reviewed one-line recipe correction names those generated files as explicit
Make goals, preserving the original rules, flags, time limits and full matrix.
Fresh `btrsmith-album-regressions-2a15e4c-attempt-2` passed all 38 native
executions and all nine original LinkPlanParity comparisons at 06:33 UTC. Result
`01fbf18a9393cf5462689bfcb9a9f382980c2ea7dd1fea2bf69829f85ad4c430`
and independent audit
`b725a253d24b1f2a9316100ad8ed37c1b51b843c3ea8779a52183bf32b3a44e0`
authenticate 18 frontend builds, 84 closed commands, 168 logs, source/tool identity
and 9,137 generated files. PSARC retains its original three-binary fail-fast loop;
its inner programs do not have separate process receipts. Existing nullable fixture
warnings remain recorded. This proves the scoped macOS regressions, not full
product/GUI acceptance or raw generated-C equality. Before launch, exactly ten historical generated C files were archived
with verified bytes, modes, timestamps and recovery instructions, reclaiming
644,300,800 allocated bytes and leaving about 80.75 GB free. Current sources,
binaries, readers, logs, audits and qualification inputs remain unchanged. Archive
audit: `01511ab42812e61da63228d67e27bacc536ee0000a3542af3d617b642442fa41`.
A second verified, reversible archive preserves 3,574 historical generated C files
and 19 old executable copies, reclaiming another 442,339,328 bytes. Its full
roundtrip and protected-input audit is
`148c91d26c01390ce5e12271a7ed6ee851ae00edd64e881933bebd8612e3e709`;
18,146 protected entries and nine original receipts are unchanged. Sources, current
binaries and evidence remain retained. Local free space is still only about 80.37 GB
after the next checks, so disk margin remains a throughput constraint.

A separate source review found that `SettingsScreen` attaches its only Back button
to the sidebar, then hides that sidebar below 900 pixels. The existing compact
Settings test calls `activate()` and does not establish user reachability. The next
product slice will preserve the existing navigation/draft owners while making Back
reachable in compact layouts and checking native ancestor visibility and hit testing.
This is a source-confirmed defect. Typed AppKit baseline fixture `bb91b409` and
final binding/Make fragment `1b577467` preserve the original Settings assertions
and check native ancestor visibility, converted bounds and hit testing. Independent
source review passed, but the first actual reference build failed on a private
`GUI/MacOS/MacOSView` import before any native execution. Its final inventory audit
also reports product-source drift; both causes are under review rather than treated
as an accepted baseline. Result:
`f7c2ebb37f4c2adfddc59b2655e06ddc2b90156f8349127a192879162e5b003c`.
The inventory difference is isolated to canonical btrc.lock manifest hashes;
all other product paths and compiler inputs are unchanged. A test-owned AppKit
discovery method now avoids private provider imports while preserving typed
visibility/hit-test/event assertions. Canonical metadata-only resolution has
refreshed the lock and proved idempotence; actual retry remains pending.
Production SettingsScreen remains unchanged. Correct fixture admission and an
actual failing baseline precede the stable-header repair and paired qualification.
The fixture scope is synthetic AppKit reachability and compositor capture, not
physical input.


A fresh compiler measurement preparation preserves the byte-identical reviewed
R2 runner, source/tool inputs, eight-run order, 60-second quiet windows and
180/240-second admission/compile bounds. The current preliminary observation
passes all six checks, but attempt three subsequently refuses first admission
at its unchanged 180-second deadline: mdworker reaches 29.6% and 8.9% against
the 5% limit. Other probes remain clear. No compiler is spawned, no warmup
completes and there are zero measured samples. Receipt
`module-emission-once-quiet-660ac18d-attempt-3/manifest.json`, SHA-256
`c3ef033096538787d03a3df3e8e534ce8b604092aa4af0c3ea00781137a73249`,
retains all 13 observations and unchanged final inputs. Independent review is
clear. The lane is released; there is no automatic retry or performance claim.
Completed
historical product outputs and the discarded R2 warmup outputs have been
archived with exact bytes/modes/symlinks verified before removal. Receipt
`completed-product-and-warmup-archive-2026-10-08/result.json` has SHA-256
`887e4ba1858fee74967bb136272da16d400387096e553221a6cffdf518fa6c48`;
archive SHA-256 `e2077414e4a3253281aef5240386dfdeaf88d379c9283a5f941b5960ca8698ce`.
All 11,182 protected entries remain unchanged and free space rises to 82.353 GB.
Restore the selected outputs before re-auditing historical raw outputs; current
compiler binaries, prepared inputs, source, logs and receipts remain in place.

The prepared private BTRSmith Linux replay is now terminal failure:
push-triggered run `37824120618`, job `113472397499`, diagnostic head
`b056e678107f3fbe596e46b0639865ac30baebc7`,
exact product `8f73b7d5` and compiler `f75c737b`. Reviewed workflow SHA-256
`52f18b20de7b1f393d3fe0bf626e3fb7e4d9c0297077d54b24a1ba7ddb03302a`
is unchanged: original live-agent, audio and package/install targets, process
ownership and bounds. Only its workflow file changed; product compiler pins
remain unchanged. The reference Clang AgentOperationChannel executable aborts
at 19:12:02 UTC, after about 9.1 seconds of native execution, at the original
`iterations < 1000000` guard in `agentChannelServeChild`. Make exits 134 then 2.
The wrapper subsequently remains alive until its unchanged 5,340-second bound
returns 124 at 19:56:10. These are distinct product and cleanup failures;
a timeout is not 89 minutes of test progress. Self-host, audio and installation
acceptance do not run. Exact remaining descendant identity is not recorded.
Terminal log SHA-256 is
`b74705a7402f35ca7d29b4bf498d10324e1a3e01cf16e3fd17eb5c6eaf1cf663`;
artifact `11575806419` is authenticated as
`2e51c0ce4d98b020152ed51733a6393e19b9eb0be1252ba6c429ad77d16ce904`.
Source/tool/final-tree hashes close. Diagnose both failures before another replay;
do not increase an iteration allowance or timeout to make this result green.
The freed hosted slot is allocated to PR68's source-changed explicit macOS
native-GUI gate. A redundant
manual dispatch `37824120641` was pending with no jobs, verified to have identical
inputs, and canceled at 18:39 UTC; the original push run is retained. Workflow
publication itself triggers this replay, so future publication must inspect that
run before considering any manual dispatch. This failed replay does not supply
Linux qualification or full-MVP acceptance.

BTRSmith test-source repair `dbe8df0e` preserves the original client assertions
and iteration guard while moving the forked child immediately through raw
async-safe operations into exec of the same binary's client mode. Arguments,
environment and descriptor bounds are prepared before fork. The child stays in
the outer stage process group; exact child-PID ownership, ECHILD handling and
bounded termination/reaping precede parent assertions. Independent source review
is clear. This addresses unsafe managed work after fork and missing child cleanup;
it does not establish which descendant held the failed wrapper alive. Original
compiler pins and workflows remain unchanged. Both original Clang Make targets
now compile/link with compiler `f75c737b`; independent review of the actual
26 emitted C units confirms both child-zero branches perform only descriptor
closure, execve and _exit before any managed cleanup. The unchanged full
three-client fixture passes through both frontends on macOS, with zero exit,
one original PASS marker per frontend and empty stderr. The explicit native
owner uses a 60-second outer bound per fixture; this is not an invented original
Make timeout. All five native and six build process groups are reaped and absent;
846 product files, 4,499 compiler files, tools, archives, recipes, plans and
binaries retain their exact identities. Native result SHA-256 is
`6870be3b7d790d9e211de49801476008ca5346f4564da01bda99623824301023`;
independent audit is
`b3ae7519c443937429b1e9e9d65f44a16b81e350ac498e39f6c37e49d05f9b8b`
in `btrsmith-agent-channel-dbe8-f75-native-attempt-1`. This is the original
product shell/SDK14.4 source-override Mac component proof. Linux replay, audio,
installed-product, dependency-pin and full MVP acceptance remain open; no
Linux rerun is dispatched yet.

Before that attempt, a verified payload-only archive preserved 924 completed
pre-October-8 emitted-C cache parts from 306 default-cache entries. It retained
all manifests, coordination locks, current entries and proof inputs, and recovered
1,988,952,064 allocated bytes. Archive `payloads.tar.gz` has SHA-256
`703df2aca2a3945a5c9c82f90367a8da226abb40455ba4b73a84ddc2f1ddc5d7`;
receipt `completed-pre-oct8-emission-cache-archive/result.json` has SHA-256
`2d56b229908600eebabae37750b57651c9cfd8a24ab787772b52abb745c90297`.
Its inventory and RESTORE.txt preserve bytes, modes and nanosecond mtimes.
The benchmark uses fresh private caches; absent old payloads are normal cache
misses through the existing driver. Free space after the failed comparison is
about 81.843 GB, so another full eight-run campaign needs additional safe headroom. A second
verified archive now preserves six completed product-parity/failed-warmup output
and cache trees, recovering 532,267,008 bytes and leaving about 82.344 GB free.
All 24,755 protected objects remain unchanged. Receipt
`completed-emission-quiet-warmups-archive-2026-10-08/manifest.json` has SHA-256
`fec9b58fe8ed62a2bec87ff8f453c1e7d9433749c152dc4feebd01975c1770c4`.
Restore these archived outputs before historical parity/comparator re-audits;
the next runner uses their authenticated compact receipts. The branch is unpublished; it does not alter PR68's current
qualification head. The first attempt's recording-only circular-reference failure is
retained separately with zero completed samples and explicit unknown sampler
numeric PID; fresh external checks found no surviving owned process. A direct
identity-serialization regression reproduces that bug and verifies the corrected
copied ancestry rows before the successful run.

The independent generic-plan allocation candidate `4d930d95` also builds through
the original Linux Make recipe. Its first comparison stopped before correctness
and memory checks because a broad pytest selector collected ten unintended
name matches in addition to the intended 178 rows. The exact inventory guard
rejected them. The diagnostic now names the same 89 corpus programs through
both frontends explicitly. Run `37743334979` has now completed: both baseline
and candidate pass all 178 corpus executions and 22 cache checks, with zero
skips. The real allocation observer confirms 16 / 8 / 4 / 2 fewer unused map
allocations across its four workloads, with identical emitted C. However, all
three candidate heavy-stdlib peak guards fail: 46,067,712 / 45,920,256 /
45,858,816 bytes against the unchanged 45,838,336-byte allowance. Baseline
passes two of three; dispatch passes throughout. Independent source, tool,
process and artifact review is clear. This is proven allocation removal without
a demonstrated peak-memory improvement; it is withheld from the integration
candidate. Evidence: `generic-linux-peak-3974-hosted-r3/INDEPENDENT-REVIEW.md`.


A further read-only memory audit identifies detailed setjmp flow graphs retained
for non-setjmp functions as a falsifiable lifetime hypothesis. The current solver
still analyzes every function; only the safety owner requires detailed root
flows. Any change must preserve all summaries/dependencies and the general
all-function API. Python module-unit callers currently obtain summaries through
returned contexts, so filtering contexts alone would lose zero-root-unit exports.
A fixed root selection and solver-owned summary accessor need paired review and
actual retained-byte/destruction evidence before an optimization claim. Historical
380.3 MiB attributed to the entire flow/effect category is not current savings;
the original product workload and parity/measurement gates remain required.

### Goal 2: usable standard library and native GUI on five platforms

These rows distinguish a compiler or fixture host from an application-facing
provider. The detailed feature acceptance remains in Stages 22–37 and the
[provider implementation queue](#provider-implementation-queue).

| Platform | Demonstrated capability | Missing product capability / next demonstrable result |
|---|---|---|
| macOS | Main `36b647f0` includes the qualified AppKit integration; final dedicated native GUI has 353 passes and 169 expected skips. Separate UI2 quit/application lifecycle repairs pass all 88 executions through both compilers, plain and sanitized | The newer UI2 provider composition qualified against `f75c737b` remains separate and unmerged. Complete its integration, remaining activation, controls, services, accessibility and final combined-tree qualification. |
| Linux | Main `36b647f0` includes the qualified SDL shell/provider integration. Final native-GUI, X11 and Wayland gates pass; X11 has 324 passes/199 expected skips and Wayland 322/199 | Physical desktop coverage, UI2, remaining features and accessibility stay open. Headless X11/Wayland results do not establish physical desktop input. |
| Windows | ARM64 compiler/bootstrap/sample and MSVC ABI/wgpu smoke are on main. Separate process/thread provider `3e480fcd` passes all four original native cells through both compilers on matching x64 and ARM64 hardware | Integrate the provider after combined gates, qualify remaining OS services and demonstrate a native shell with button, editable field, events and safe teardown. Process/thread passes do not establish a complete GUI provider. |
| iOS/iPadOS | Historical iOS 26.4 simulator host passes 50 handwritten strict-C11 fixtures. The 11-path host-tooling port passes 28 original, 28 current-tree and four workflow checks; simulator publication is held for D8 runtime admission | Run current-tree and oldest-installable-runtime qualification; demonstrate compiler-generated app-private persistence and checked UIKit lifecycle/button/text-field providers. The historical C host fixtures do not prove those providers. |
| Android | NativeActivity fixture host and lifecycle repair pass 56 combined executions | Add general in-process callback-safe provider execution; demonstrate app-private persistence and native lifecycle/button/text-field providers through checked JNI/Looper ownership. |

The main-based canonical PLAN candidate `f01ec0ff` passes Linux, Windows and
ARM workflows. Its Mac native GUI gate fails one unchanged self-hosted portable
GPU case (326 pass, 67 skip): the generated program aborts in its pixel journey.
The old artifact does not contain the failed generated C, so neither its exact
predicate nor cause is established. All production and native-test inputs match
main `49f136ec`. A standalone main-based AppKit coordination repair `13e147ed`
has passed the original three-worker native gate in run `37745915293`: 327
passes, 67 expected skips and no failures/errors across the exact 394 collected
cases. All eight real GPU pixel journeys pass. The baseline coordination
control has two required failures; the repair passes seven focused tests.
Independent review verifies all 4,374 source files against Git, exact diagnostic
pins and unchanged tools/inputs. The full artifact is retained with SHA-256
`07e0cabe6f83b4b854b1391dd578b26b4a1b1493a87858b097a97a9d55e365f9`.
This qualifies the affected native gate; it does not establish the historical
GPU failure's cause or the full final-tree matrix. The repair and consolidated plan landed through
[PR69](https://github.com/schiffy91/btrc/pull/69) at `cbd3ddcd` after all 36
selected checks passed on head `01621436`. Three scope-skipped jobs are not
counted as evidence. The post-merge Linux, macOS, Windows and Windows ARM64 workflows all pass at exact main `cbd3ddcd`. This closes that integration matrix; later compiler, UI2 and product changes require their own qualification.

The first Linux shared-display lease qualification, run `37743819333`, stops
before tests on both X11 and Wayland: its diagnostic launcher bypasses Bash and
therefore does not load the original image's exported Nix environment. The
image builds and immutable input checks pass; no lease or native pass is claimed.
The minimal launcher correction now reaches the original tests in run
`37749577958`. X11 stops in its baseline control: the execution-inventory check
correctly fails, but the exclusion test unexpectedly passes. Its unchanged
baseline has no Linux lease. A suspected scheduling race prompted the following
stronger handshake; that hypothesis has not explained the hosted behavior.
Source `9b03f794` now waits for actual kernel contention or body entry before
asserting exclusion. In the local matched source archives, the original baseline correctly fails
both required assertions and the candidate passes all 16 coordination checks
with zero skips.
A separate actual-process control verifies Darwin's zombie-only group EPERM
and safe cleanup that still removes live descendants. The full X11 native
stage has not run. Hosted continuation `37754953668` still stops because its
baseline exclusion control unexpectedly passes, so the local handshake result
is not sufficient. A real reproduction now records the cause: child pytest discovers the
candidate ancestor configuration and imports its lease owner even while the
outer test belongs to the baseline. Explicit child configuration and cache
ownership plus imported-owner path/hash checks restore both required baseline
failures and all 16 candidate passes in the same nested directory layout.
Hosted continuation `37758465696` now proves both required baseline failures
and all 16 candidate coordination passes. The controlled focus-loss case, eight
isolated native cases and all 12 concurrent native cases also pass. The qualifier
then rejects the parallel runner's `@scroll-diagnostic` name suffix before the
full original GUI shard. This is an inventory-adapter failure after native
success, not a new native assertion failure. Diagnostic `7661fa34` records exact
collected grouping markers when the stage uses loadgroup; a real four-case
parallel-runner proof verifies positional, keyword, default and combined markers,
and still rejects missing, duplicate and wrong identities. Its hosted run
[37763215278](https://github.com/schiffy91/btrc/actions/runs/37763215278)
has completed successfully. Its complete 129,604,291-byte artifact has passed
ZIP integrity and SHA-256 verification
(`2366679d471dadce9905e3eb0f304f23f484dbac79f01727d96e8f9e80583d19`).
Independent review is complete: the original full X11 Make shard contains
523 cases, with 324 passes, 199 expected platform skips and zero failures/errors.
Both required lease baseline failures, all 16 repaired coordination checks,
one controlled real focus-loss case, eight isolated native rows and 12
lease-scheduled native rows pass their respective oracles. All 4,503 publication
files independently match Git blobs and modes; source/index before and after
and recorded tool identities are unchanged. The 199 skips remain uncovered by
this host, and Fontconfig diagnostics remain retained. Command leaders were
waited/reaped; the artifact does not prove global final descendant absence.
Evidence: `linux-gui-lease-3974-hosted-r5/INDEPENDENT-REVIEW.md`.
Combined-tree Linux qualification now passes at PR68 `00e45379`, with the
independent report and coverage limits below. The original full Wayland gate at `14f9e193` passes all 322 executed cases, with 199 expected
skips classified and covered on other hosts. Independent review verifies all
521 collected/JUnit identities, 4,503 publication file hashes and modes,
unchanged source/tools/index and the original enforced skip gate. Artifact
SHA-256 is `c2b3dd7caacb3d6b708751503e204f357e99f7c881ad7e000bf9dc77b39c7a38`.
The later `9b03f794` coordination-test change is not represented as a new
Wayland execution. All attempts and their source/tool audits are retained.

The current macOS UI2 foundation snapshot `a9ffe1bd`, using compiler `56d548c4`,
now passes **28 actual native executions**: seven fixtures through both frontends,
plain and ASan/UBSan. Run-loop wake/deadline, work queue, lifetime fault injection,
publishing, interaction state and native view state pass with the original
assertions and deadlines. Both SDK projections are diagnostic-free; all 56 strict
C/Objective-C syntax checks and 28 links pass. This component is not on main and
does not qualify the complete provider: ordered-container tree cases, remaining
controls, application integration and Linux UI2 are still open. Evidence remains
in `ui2-macos-qualification-a9ffe1bd/`; the first warning-producing attempt is
preserved separately. The first ordered-container reference projection at
`4d1cd3d0` passes SDK selection and transpilation but stops on a nullable native
child warning. Guard `7a95ccdf` fixes that warning: the fresh NativeTreeState
reference projection is diagnostic-free. NativeContainerOrder then stops on
three unchecked interface casts and two nullable host arguments in its fixture.
Fixture correction `59cb61d9` now passes NativeContainerOrder's reference
projection too. NativeContainerBarrier's seven nullable-value warnings are
fixed by checked fixture locals in `8f6c8b21`. Frozen snapshot `71397941` now
passes all three fixtures through both compilers with zero diagnostics, all
34 strict C/Objective-C checks, all 12 links and all 12 actual native runs
(three fixtures × both frontends × plain/ASan+UBSan). Ordering, rollback and
callback-barrier assertions pass unchanged. Sanitizer flags and runtime logs,
319 provider inputs, 131 compiler inputs and all executable hashes are verified.
Evidence: `ui2-macos-container-projection-71397941/results/projection1/component-result.json`
(SHA-256 `d6bd4646020aeb630f7352df9a0fb4cbfdd6c318036764aa30ec4319ffc4aafd`),
with report commit `3bf85703`. Application-host wiring, ordinary input deferral,
remaining controls, Linux UI2 and final integration remain open.

The next Mac source snapshot adds staged run-loop attachment, native capture
failure reporting and two-axis ScrollView observations. Reference projection
of NativeCaptureFailure and RunLoopAttachment passes without diagnostics;
Scroll projection exposed a private test export omission and then the existing
compiler guard against mutable Objective-C object globals. Both failed attempts
are retained. Reviewed source `61748e0c` uses typed accessors for the actual SDK
notification identities; it does not relax the compiler or guess string names.
Fresh projection accepts those native identities and then rejects assumed
constructors on the approved data-only event records. Reviewed source `25c98801` now
uses their declared fields without changing the portable contract. Frozen `25c98801` then passes all six projections and 30 strict C/Objective-C
checks. Reference capture-failure and run-loop-attachment programs pass native
execution; Scroll initially rejects arrange-before-attachment in its fixture.
Fixture correction `8e21f235` preserves every assertion and attaches the view
first. The Scroll program now passes its earlier geometry, model-event, no-op,
invalid-input, clamping and retained-snapshot checks, then aborts at the real
wheel notification assertion. A matched native-only AppKit control reproduces
no movement or bounds/Did notification, while Start and End arrive during
one second of normal run-loop service. Changing only public host-event metadata
or line-versus-pixel units still produces no movement. A lost provider callback
has not been established; event dispatch/context remains under investigation.
Sanitized/self-hosted native stages have not run. The retained failures are not
counted as complete ScrollView qualification.

The next Window snapshot `12afdfff` implements state snapshots, state-change
callbacks, close requests and cancellable close decisions through the existing
window/context owners. Both reference and self-hosted projections of the two
fixtures pass without diagnostics, and all 24 strict C/Objective-C units pass.
The first native link is refused because fixture composition repeats the AppKit
framework row; no native execution is claimed. The reviewed fixture-only
correction keeps the inherited AppKit row once and preserves all production
source, native predicates and plan validation. The corrected composition passes fresh paired projections and strict units,
then its first native execution exposes a real lifecycle defect: detach failure
leaves the root-mutation guard active and a later close is rejected. Reviewed
repair `b6a4fe3e` retains an explicit failure flag and error, completes owned
cleanup, then rethrows according to the language's existing catch/finally
contract. All original fault/retry assertions remain. Fresh qualification passes
all eight native rows (both fixtures through both frontends, plain and
ASan/UBSan), four zero-diagnostic projections and all 24 strict C/Objective-C
units. Report `e05e684b` records unchanged inputs, tool identities and closed
process groups; aggregate SHA-256 is
`6f5cd2f3058acca9fec82bf4b90d6677bc821b93d7ab18189d2e60821be9eccc`.
That run uses compiler `56d548c4`. A fresh replay against repaired current
compiler `f75c737b` now also passes all eight native rows, four zero-diagnostic
projections, 24 strict C/Objective-C checks and eight links, with all input/tool
checks unchanged and process groups closed. Report `904d2716` retains aggregate
SHA-256 `1a395e4373e79835652e1d16920389750ebc4a0a14c91d50376b61f9f807a637`.
The same provider/current-compiler pair now also passes all eight native
capture-failure and run-loop-attachment rows (two fixtures, both frontends,
plain and ASan/UBSan), four diagnostic-free projections, 16 strict units and
eight links. All source/tool checks and process cleanup pass; aggregate
`74f102369d7a003a4d50371d19f677818b4769eccb8d592d7f0454aa04346043`
is retained in `ui2-macos-foundations-b6a4fe3e-compiler-f75c737b`.
The authentic public `NativeApplicationHost` baseline then fails on 19 missing
methods: TextField 3, Slider 6, Select 7 and Application 3. A separate nullable
fixture capture warning is repaired by binding its already-checked publisher;
none of the original assertions changed. Independent application, text-field
and range/selection implementation claims now target those concrete gaps.
This is the first public application baseline, not a complete application pass.
The next public-host composition is now concrete and independently reviewed:
Application base `b97732ba`, Text donor `88db78e5` and Range/Select donor
`209fe7f7` supply all 19 methods, with the shared interfaces unchanged. The
frozen bundle `ui2-macos-public-application-b97732ba-compiler-f75c737b` retains
343 provider and 131 compiler inputs, qualified compiler `f75c737b`, and the
original richer fixture SHA-256 `3c9554ce8a82fe2eea27b3e2450f81bf3cf54ef550069c0529aeb00a8dc3943b`.
Its only metadata composition is the existing three provider binding fragments
and removal of the duplicate fixture AppKit row. Prepared `b84fea33` and
qualifier `17f46bfe` preserve the original paired projections, strict checks,
plain/sanitized execution, assertions and deadlines. Its first reference
projection now stops on one actual diagnostic: `NSApplication.delegate` is not
an exposed method. The earlier 19 missing-method errors do not recur. Result
`results/application1/application/reference/project-plain.json` has SHA-256
`4f805ef0f439d6e3fec830a460c2ae88ba7f4e6ebd6eac73eaffa0955abe066e`;
all four groups close and inputs remain unchanged. No self-host, C/link or native
stage executes. Slot getters are intentionally private to the callback owner.
Both compiler implementations already make the scoped setter reject an occupied
slot before publication and abort the attempted activation. A reviewed one-file
Application repair uses that setter before the broad run/teardown transaction,
removing the invalid getter call and leaving the application open on rejected
admission. Patch SHA-256 `305b5caa9bc43fa8712029911f15bc812ff805cc43ecf9024c4aedc6919edc18`
is committed as Application-only `9ff2b912`; the active parser checkout and
ordinary index are unchanged. Fresh original qualification now passes both
compiler projections with zero diagnostics, all 22 strict syntax units and the
reference/plain native link. The first native child aborts on the unchanged
`application.pollClose() == COMPLETE` assertion after a real callback requests
closure and unwinds. The preceding native-dispatch, one-call and no-nested-work
assertions pass. This is distinct from the earlier deliberately failing host
case, whose deadline exception is expected. Aggregate
`ui2-macos-public-application-9ff2b912-compiler-f75c737b/application-result.json`,
SHA-256 `9f0fbaab192ca0b0222b07a7e74a7d793d42b14fb6eb30b162521987eab3239f`,
retains the failure, unchanged final sources/tools and all 59 groups reaped and
absent; the remaining three native cells do not execute. Independent review
confirms the assertion and evidence. Source review traces a deferred pointer
cancellation record retained by a closing view while application shutdown no
longer dispatches that queue. Fixture-only `21ee445b` reproduces this exact
native cancellation failure after both real PRESS callbacks, two reserved
credits and two queued records; receipt `4cc3fab55004a1db56602c1b370363b5e4845533864946bb310534ddacf79ce1`
retains the original failure and all 30 groups closed. Repair `676d5043` removes
only the canceled registration's queued record using the existing Context and
ViewInput owners, preserving native/in-flight drain and terminal-credit ownership.
Independent review confirms the approved contract already suppresses queued
delivery after registration cancellation. All four repaired Barrier cases now
pass through both frontends, plain and ASan/UBSan, including unrelated queue
survival, entered cancellation, idempotence and balanced credits. The unchanged
ApplicationHost fixture passes both projections/strict checks and reference/plain
link, then fails `ui2DispatchHostInput(kind)` before that iteration's receiver
and close assertions. The selected iteration/window was not logged in that run. A separate
failure-only diagnostic subsequently proves that kind 1 selects the previous
invisible, empty same-title window while the current visible window has one
child. Selection, stimulus and assertions remained unchanged during that
observation; receipt `c8ce66c031e7f745e1a495959d6ca61c7bffc19733f016d798fb51d43739cfe5`
retains it and all 40 groups closed. Probe-only `af71b170` now selects exactly
one visible same-title window and rejects ambiguity, preserving the original
child count, event and assertions. Diagnostic logging is not retained. Aggregate
`ui2-macos-deferred-input-676d5043-compiler-f75c737b/cancellation-application-result.json`,
SHA-256 `e3b6a071f73a495f187efceb8ff8e6f7177ad69d7c84d0dfb11633bf5df46aa0`,
records unchanged inputs and all 151 groups closed. Independent evidence review
is clear; the remaining three Application native cells were unrun in that
failed attempt. The fresh probe-corrected original ApplicationHost qualification
now passes all four native cells: reference/selfhost, plain and ASan/UBSan. Both
projections have zero diagnostics, all 22 strict source checks and four native
links pass. Every native run reaches the original final marker with only the
exact intentional `Host deadline failure` stderr from the earlier failure case;
there are no sanitizer diagnostics. Aggregate
`ui2-macos-public-application-af71b170-compiler-f75c737b/application-result.json`,
SHA-256 `b9c1d2dc59beae175500f2674cb14937412cdbbbbf4853c25b985042af9c742f`,
records the original rich fixture `3c9554ce`, unchanged production `676d5043`,
compiler `f75c737b`/binary `60639d60`, all 122 groups reaped/absent and closed
source/tool/output hashes. Independent review confirms this exact composed
App/Text/Range/Select attached-host capability on SDK 27, arm64 target 14. The
callback-close-after-unwind, queue/work, scope and foreign-host preservation
oracles pass. The prior four Barrier native passes remain valid because neither
production nor that fixture changed. Standalone run/delegate rejection, full
UI2, other platforms and the full BTRSmith MVP remain separate open outcomes.

The next native capability is coordinated application quit. Documentation
checkpoint `e91a7412` records the D29 integrator clarification in the approved
UI2 contract and IWindow comment: held AUTHORIZED transactions accept nonstale
CANCEL or an explicitly newer SAVE/DISCARD revision; the document owner must
report edits before returning to the executor. Application must revalidate
membership, handler/transaction identity and reported revisions, then seal
irreversible ingress without intervening callbacks or user destructors. Clean
windows remain open until the whole group commits; one cancellation preserves
all drafts. Independent contract review is clear. The packet retains all 12
original application lifecycle scenario oracles, documents five necessary UI2
fixture migrations and requires real native two-window evidence before
acceptance. Existing pending transactions must be promoted by identity without
another prompt/save attempt, including terminate followed by completeSave
before the originating callback unwinds. No executable implementation or native
quit result is claimed by that documentation checkpoint. The owned packet is
`docs/workstreams/ui2-macos-native-quit.md` on `codex/ui2-macos-native-quit`.

Fixture-only commit `f573f8dd` now demonstrates the actual missing native quit
behavior. Reference projection has zero diagnostics, all 11 strict units and
plain linking pass, then real NSApplication termination returns with one request
but zero close-decision deliveries. The native process aborts at the exact
`journey.cancellationObserved` assertion after its native-return/count assertion
passes. Both dirty windows therefore have no opportunity to veto this shutdown.
Aggregate `ui2-macos-native-quit-f573f8dd-baseline-compiler-f75c737b/baseline-result.json`,
SHA-256 `d3912db46a1be0dd7bb7ea3805c090cc8a39f5893ab5a453f38ed27f51ee6943`,
and native-stage receipt `cdfb0064904a6673e5d412f0cccbfe86f04edbc3691f8e9e5a864f40af472c96`
retain the original bounds, unchanged 347 provider/131 compiler files, exact
native assertion mapping and all 40 owned groups reaped/absent. Independent
review is clear. This is the genuine reference/plain baseline failure; the
provider repair, paired/sanitized acceptance, remaining save/revision/membership
journeys and all 12 original lifecycle scenarios are still required.

Reviewed production `39f9e0ce`, after fixture-first `2413b9dc`, now implements
native capture-time transaction holds, deferred group decisions, membership and
revision revalidation, and irreversible ingress sealing before user finalizers.
Review found and corrected stale queued prompts, partial/reentrant cancellation
progress and a native-only modal unwind deadlock. Four additional real-provider
fixtures cover these boundaries alongside the unchanged two-dirty-window veto
regression. The separate legacy lifecycle migration preserves all 12 scenarios,
exact delivery/destruction counts, native view/root/scope assertions and 30-second
native bounds. Its test-owned timer and explicit application context replace
obsolete test APIs; foreign-delegate rejection moves to run admission and is
proved to preserve the foreign owner and application's open windows. The original
10-second stuck-subtree error oracle remains exact. Source review is clear. Candidate `5dd18d19` now passes all 40 focused native
runs: five quit journeys, WorkQueue, Publisher, attached ApplicationHost and
both Window fixtures, through both frontends in plain and ASan/UBSan modes.
All 20 projections have zero diagnostics, all 174 strict units and 40 links pass.
The exact original failing quit fixture now delivers both decisions and preserves
the dirty windows on one veto. Early cancellation suppresses a queued peer
prompt without cancelling its registration; current and stale save revisions,
membership changes, retryable publisher cleanup, finalizer reentry and genuine
native-only modal unwind all execute their original assertions.

Independent aggregate
`ui2-macos-native-quit-5dd18d19-compiler-f75c737b-r2/independent-qualification-audit.json`,
SHA-256 `a639731ed60023c7b057c4dfc75bc191dae8690d7f60a333b08c7277584f2619`,
closes all 1,050 recorded process groups and exact source/tool/log/binary pins.
The overall runner then exits 1 at the legacy reference projection: the explicit
test-owned `IApplicationTimer` declaration duplicates the interface synthesized
from its native binding metadata. Receipt `42cb32412c0041784ce78e11404f5d178898e9a9131c79c9c0511ea12fb87fd4`
retains both diagnostics. No legacy native child or self-host projection started;
all 48 legacy runs were unrun on that source. Fixture repair `4fbed9a1` removes
only the duplicate interface and applies AST-identical Python formatting. Its
next native run passes the first ten reference/plain lifecycle scenarios, then
fails scope-exit with `cannot retain destroying managed object`; 37 native cases
remain unrun. Both projections, 20 strict units and the first link pass.
Independent audit `8a7a90299e0c0b8e098cf2c6d226e6e6b4be2d555e1447fda8b458ad277514be`
closes all 66 groups and exact input/tool/output inventories in
`ui2-macos-native-quit-legacy-4fbed9a1-compiler-f75c737b`.
Generated C connects destruction through close/sealQuit to replacing the
application's member vector while its owner is destroying. Reviewed production
repair `21ccce41` clears that existing vector in both guarded shutdown paths;
all original lifecycle assertions remain unchanged. Its qualification follows below.
The original stuck-subtree binary independently reproduces error masking
after 10.5019 seconds, under the unchanged 30-second bound; receipt `c4c95b89`
closes all four groups. Separate repair `4232652b` preserves the cleanup attempt
and prioritizes the actual failure before a generic pending result. Its native
replay passes eleven reference/plain scenarios, including scope-exit, and the
original subtree-error assertion. The next stopped-loop/state assertion then
fails. Independent audit `b97954384392ea9b637d849faffe23e38ee07b72b39574c4e5b2b4f48cf6abbe`
closes all 67 groups and exact inputs; 36 legacy and all 40 focused cases are
unrun on this source. isRunning counts an internally retained standalone-host
attachment after the actual loop stops. Reviewed one-line correction excludes
that internal cleanup attachment while preserving external-host semantics and
pending ownership. Correction `73f636e8` now passes all 88 native executions:
48 original lifecycle rows and all 40 focused quit, queue, publisher, attached-host
and window rows, through reference/self-hosted compilers in plain and ASan/UBSan
modes. The original assertions and deadlines remain unchanged. All 22 projections,
194 strict C/Objective-C unit checks and 44 links pass; there are no sanitizer
findings. Independent audit `b29066f543f43f92aa03c8aa6c47f999d4fc4390663d9977f413c4360a74f4d1`
verifies exact source/tool/output inventories and closes all 1,206 owned process
groups. Evidence is retained in
`ui2-macos-native-quit-73f636e8-compiler-f75c737b/independent-full-qualification-audit.json`;
the source report is committed at `238acc9f`. This qualifies the recorded macOS
provider composition against compiler `f75c737b`, including all three lifecycle
repairs; it is not a merged-tree, complete-control, other-platform or BTRSmith
MVP result. Narrow provider-manifest integration, remaining control journeys,
full UI2 and final integration gates remain open.

The missing method implementations now exist; qualification remains scoped to the results below.
Application provider `70df20a9` with compiler `f75c737b` passes WorkQueue,
NativeContainerBarrier and NativeCaptureFailure through both frontends, plain
and ASan/UBSan: 12 native rows, six zero-diagnostic projections, 28 strict
C/Objective-C checks and 12 links. Independent review rehashes all input/log
inventories and verifies all 180 command groups absent. Aggregate
`a54c1f28b116c6a17bb3a9caef28379341e36e4c4d8afc52bd3b1d4457e57f0f`
is retained in `ui2-macos-application-70df20a9-compiler-f75c737b`.
Those components do not qualify Public ApplicationHost; its actual rerun and remaining
shutdown failure are recorded above.

Text provider `b987ebdc` passes the original real AppKit field-editor fixture
through both current compiler frontends, plain and ASan/UBSan: four native rows,
two zero-diagnostic projections, 12 strict C/Objective-C checks and four links.
The original native attempt exposed unsupported `__weak` storage in the MRC
native source; the repair uses Foundation zeroing weak storage and balanced
native ownership without changing compiler flags. Native draft/composition,
model replacement, ordered commit/cancellation and eligibility assertions pass.
All 92 commands reap successfully, source/tool checks are unchanged and command
groups are absent. Aggregate
`273bdd3bbd6579527c18f631de3ac9e4b61b80458750ec1ad056409fa203fb84`
is retained in `ui2-macos-text-b987ebdc-native-compiler-f75c737b`.
Physical IME, expanded Escape/route/entered-close and combined application
acceptance remain open. Range and keyed selection source/fixtures are implemented and partially tested.
Range `b0305ce1` passes all four native model-state rows through both compiler
frontends, plain and ASan/UBSan. Its event fixture initially exposed nullable
probe owners and then a genuine manifest-order parity defect: the reference
compiler accepts callback metadata after a native source table, while the
self-host parser rejects it. Moving the source table preserves the exact parsed
TOML object and allows qualification to continue. Repair `6b83cf1b` now retains
the latest native-binding owner across unrelated tables and checks duplicate
property tables per binding. The original 20-row proof has 13 failures and seven
passes; the fresh candidate has 20 passes and zero skips/errors, including all
16 manifest cases and four actual callback rows across both compilers and
plain/sanitized native execution. Independent review is clear. The source is
not yet published or integrated and still needs combined qualification.
The original failure remains in `macos-range-current-f75-r4/METADATA-ORDER.md`;
candidate receipt is `native-binding-metadata-order/candidate-1/result.json`,
SHA-256 `cbc648afd4e5ebf9f8bbaacc089c3438e4363fe55df8ba05b54ca62e6078f33c`.
Its retained provenance records post-run association of Apple Clang identity,
not an invented before/after pin for that tool.

The corrected range event fixture passes both projections and strict compilation.
Its first native run passes key/repeat/accessibility/assistive assertions, then
fails the unchanged drag preview assertion. A failure-only trace records zero
previews, seven commits, zero cancels and unchanged value 4. A pointer commit
alone does not prove dragging works. A matched stock/native-provider input and
geometry comparison at `209fe7f7` now shows identical frames, bounds, track,
knob and event coordinates. Both stock NSSlider and provider remain at value 4;
stock emits zero actions and provider emits one unchanged-value action. Both
are inactive/non-key and loginwindow remains foreground. This diagnostic aborts
at the earlier unchanged pointer-commit assertion, rather than the prior preview
assertion, so it does not reproduce an identical failure. All 28 command groups
are closed and inputs unchanged (result `f57a4e02`). The evidence does not yet
identify a provider fix; original preview and movement assertions remain.

Selection's model fixture passes reference/plain native execution. Its first
real event fixture passes performClick and mouseDown journeys, then fails Space
input. The matched standard NSPopUpButton also fails to open despite actual
first-responder ownership and corrected native key codes. Current capture source
adds printable-key admission and a scoped Escape observer with exception and
teardown ownership cleanup, but those native behaviors remain unqualified.
The host fixture now uses regular activation policy, finishLaunching and an
actual bounded AppKit event pump. At `f68e5654`, both compiler projections and
strict checks pass; the reference executable fails the unchanged active-app,
key-window and first-responder prerequisite before Space. The three-second pump
dispatches zero events; app/window remain inactive/non-key. All 44 command groups
are closed and inputs unchanged (aggregate `60b9a122`). A separate read-only
LaunchServices query confirms `com.apple.loginwindow` is foreground. Do not
repeat foreground-dependent qualification until that prerequisite changes, and
do not claim the exact external cause beyond these observations. Original failed
runs remain retained; no keyboard/Escape/type-selection acceptance is inferred.
No source-only milestone counts as native capability.

The Linux counterpart `53e4bfaa` implements request admission, cancellable close
transactions, save-revision/attempt authority and context modal guards in the
existing provider owners. Independent source review and format checks pass;
actual baseline and repaired native execution remain outstanding. The real SDL
fixture retains drafts and tests independent windows, stale saves, cancellation,
terminal pressure and close during callbacks. Its existing text-field dependency
needs the actual `SDL_ClearComposition` native export in a final fragment shared
by both qualification compositions. Neither source review nor fixture completion
is a native pass. Group application quit, ordinary-input integration and full
provider acceptance remain open.

Portable filesystem, process/terminal, HTTP/networking, regex/glob, jobs/IPC,
audio and foreign-library ownership still require their platform-specific
implementations and acceptance. HTTP and Windows service contract drafts are
review work, not completed providers. Approved UI contracts likewise remain
separate from implemented, tested widgets. Independent existing-interface
repairs can proceed without waiting for all five shells or BTRSmith migration.

**Next measurable outcomes:** deliver the five small repairs in
[the first delivery queue](#first-delivery-queue), then land the approved UI2
interface with both desktop providers. Advance each Windows/mobile service or
small GUI slice as soon as its own ABI, lifecycle and ownership prerequisites
work. Each claim needs an actual application-facing operation on that platform.

### Goal 3: prove the compiler and library in BTRSmith

**Scope update, 2026-10-12:** BTRSmith must work and be qualified on macOS, Linux,
Windows, iOS/iPadOS and Android. Earlier macOS/Linux MVP evidence and packet names
remain intermediate milestones. Extend the existing journey and release matrix
to all five platform families with appropriate desktop/mobile interactions and
explicit OS constraints; do not treat Windows or mobile as optional follow-up.
Application integration follows available qualified providers without waiting
for compiler optimization targets. Full numeric acceptance remains required and
is reported separately from functional progress.

BTRSmith main was rechecked at `adb3276f`; its
[pinned compiler](https://github.com/schiffy91/btrsmith/blob/adb3276f93cbeb7b0c2ab79ab34e366c9eef5f5c/flake.lock)
remains `05ec9cb7`. The pin update and current application requalification are
outstanding. UI migration,
real application build/runtime budgets, installed-product journeys, physical
audio/latency sessions and release qualification remain open (Stages 36–43).
The targets include search p95 ≤100 ms, static idle CPU ≤1%, player frame p95
≤16.7 ms and zero app-induced xruns over 30 minutes. Those are acceptance goals,
not measured achievements in this integration session.

**Next measurable outcome:** a qualified current compiler pin running BTRSmith's
frontend and library smoke checks through both compilers, followed by completed
screen journeys as their library providers land. Hardware, listening and release
account requirements remain explicit where automated tests cannot prove them.

**Current product evidence (updated October 11):** album identity repair
`2a15e4c1` passes 38 actual Mac native regressions and nine original compiler-plan
comparisons. Settings Back repair `f077985b`, recorded in `3608cb65`, passes both
compilers at widths 480, 540 and 1100, original plan equality and visual review
of all 18 captures. The baseline really failed on the hidden compact button;
the repair places the same button in the persistent header. Earlier scoped Linux
agent/audio/scanner qualification has 24 native passes and four plan comparisons,
plus product derivation/install-layout checks; that run did not launch the
installed app.

The current Linux replay completed successfully as
[37905070491](https://github.com/schiffy91/btrsmith/actions/runs/37905070491),
workflow `a01ab210`, product `3608cb65` and compiler `a29ab3e3` (the tree merged
into main). It includes the latest album and Settings source, both original
Library journeys and installed-application smokes. It was published once, with
no duplicate manual dispatch. Independent artifact and visual audit `e759a38b` is clear for the selected journeys; full MVP acceptance remains open.
Native Linux Settings activation remains distinct from the Mac mouse-event/hit-test proof.

The native Player speaker button has a source-proven missing connection to the
existing mute/restore command. Its attempted real-library regression builds and
links, but fails at stage 0 with `Timed out waiting for the catalog`, before any
speaker stimulus. Cleanup reports `RETRYABLE_FAILURE` and the original completion
assertion aborts. Independent audit `85e9bc02` verifies all inputs and seven closed
process groups. The private catalog snapshot admits full-library refresh through
its configured root. The supported No-folder diagnostic subsequently passed catalog
readiness and opening the arrangement, then timed out waiting for the song at stage 1.
Audit `b0f75dd1` verifies exact retained binary/input identity and four closed groups;
close again reports RETRYABLE_FAILURE. Reviewed fixture `58bcd266` adds failure-only
observations of existing model, guarded errors, audio and presentation/clock state,
preserving the original readiness checks, assertions and deadlines. It has not run.
Neither diagnostic closes full-library refresh or cleanup acceptance. User originals
remain unchanged; no speaker regression pass or repair is claimed.

Remote BTRSmith main remains `adb3276f`, pinned to compiler `05ec9cb7`; the
current working product still locks `cdf9d952` and uses explicit current-compiler
overrides for these checks. A qualified lock update, complete MVP journeys and
final timing acceptance remain open.

**Earlier macOS library evidence:** product `5bb466b7` with immutable compiler
`3974d47b` passes the original macOS library journey through both frontends:
one album scanned, one cell rendered, 600 presented frames and completed
teardown. Both executable signatures and final source/lock checks pass. The
original frontend check on product `e00c61d2` passed both application compilers,
reference-output preservation, link-plan parity, 24 input tests and six artifact
tests. The only product delta is a Make directory dependency repair plus its
regressions: the first native launch exposed a missing `build/tests` ancestor;
the original recipes now create it through their existing directory owner,
with 26 build-input tests passing. Failed evidence remains retained.

The library passes do not qualify the native agent channel: both launches
reported an invalid endpoint. Its 123-byte socket path exceeds Darwin's usable
103-byte limit. Product `933f79b7` now implements a reviewed centralized bounded endpoint
policy. The separate long-path regression reproduces the original native
INVALID/EINVAL failure through both compilers; repaired storage passes four
reference/self-hosted × Clang/GCC native runs. The repaired reference
AgentOperationChannel subsequently reaches its native PASS marker for canonical
responses, recovery, reconnect, borrowed-session ownership and UI capture. The
next AgentSurfaceProcessAcceptance aborts because a command response is not
`applied`. A no-build protocol replay captures the first hardcoded revision-1
command returning canonical `stale`: background library progress advances the
revision before dispatch. This standalone path bypasses endpoint lookup. The
documented revision contract requires that progress to remain visible; the
fixture repair will query state and retain explicit stale/no-effect coverage,
without suppressing application ticks or shifting constants. Final failed-run
source/tool reconciliation passes; generated caches and package outputs are
retained separately with exact hashes. The live GUI acceptance, entire self-hosted agent pass and repaired
library replay remain pending. Shortening the smoke path is not acceptance.
Nullable-owner corrections are source-reviewed but not executed. The original
Linux x86_64 product qualification was recorded in
[BTRSmith PR30](https://github.com/schiffy91/btrsmith/pull/30), stacked on the
existing pin-migration PR28, using exact product `933f79b7` and compiler
`3974d47b`. The run has completed: original paired frontend checks, both library journeys
(one album/cell, 600 frames, teardown 4), both installed executable smokes, and
reference AgentOperationChannel with Clang and GCC pass. The next reference
AgentSurfaceProcessAcceptance aborts at the command-response assertion. Its
actual Linux response was not captured, so the separately observed Mac stale
response is not asserted as this run's cause. Self-hosted agent acceptance, live
GUI, audio failure journeys and the final product derivation remain unrun.
All 842 product and 4,496 compiler inputs and final Git indexes are verified
unchanged. Artifact 11533510297 has verified SHA-256
`209db7257e6807c26529e4e89b816cd757903850c598aa6038bb20c3a758e398`;
`btrsmith-linux-933-3974-hosted/REPORT.md` records the bounded result. This is
not completed Linux MVP qualification. Product locks remain unchanged;
these results use an explicit current-compiler override, not an accepted pin bump.
Evidence is in `btrsmith-frontend-3974-prepared/attempt-1` and
`btrsmith-frontend-3974-prepared/library-attempt-2`. The exact realized Nix shell
now has a task-owned GC root after its unrooted predecessor disappeared between
runs; no global Nix settings changed.

The Mac interactive fixture at `9b88ff73` now builds through both frontends
and passes all six process-transport failure controls through each (12 native
passes). The original reference agent channel passes too. The full journey
progresses beyond the former stale command and reaches an unchanged UI route
assertion. An actual event trace confirms the fixture opens Settings on Audio
then sends a Library-only edit, which routing correctly ignores. The fixture
now dispatches the real Library settings navigation before the unchanged edit
and save assertions. Combined source `254284c0`, including separately reviewed
fixture `5bded264`, gives each MCP retry a fresh
transport request ID while retaining logical command identity, raw response
validation and the original journey assertions. Its original reference target
now passes both AgentOperationChannel and AgentSurfaceProcessAcceptance. The
next LiveAgentProcessAcceptance exits before endpoint readiness. A separate
no-build capture of the exact application prints `FAIL: Instrument material
unavailable: No such file or directory` and exits 1; its required Rosewood.png
is absent. The acceptance Make prerequisite builds only the executable and
bypasses the existing `btrsmith-native` resource-staging owner. That dependency
repair is in progress. Source, tool and executable hashes close unchanged in
both failed-run and diagnostic records. Self-hosted full acceptance remains
unrun. This is not yet a pass of the full
paired journey; the earlier 12 transport controls remain tied to their exact
source and preserved executables.

Product `0b6c491a` fixes the native agent acceptance Make prerequisite to use
the existing resource owner. The baseline fails for missing Rosewood.png;
the repair passes 27 build-input checks, and the live app now starts. The
reference operation-channel and standalone agent-surface journeys pass again.
Live acceptance next aborts on typography. A no-build actual CLI/MCP capture
confirms the library heading is 22/38/400, matching the existing stylesheet and
independent UI integration test; the live fixture still expects 20/26/600.
Settings and audio typography agree with their contracts. The library expectation is corrected in `9d26ff0a`; its next original replay
passes that assertion, then fails the player weight check. A subsequent actual
open-arrangement, ready-transport, MCP seek to frame 48000, shared CLI scrub and
raw UI capture confirm the player heading is 22/24/400, again matching its
stylesheet while the fixture expects weight 600. Source `d3fb25f4` corrects
that one number and preserves the assertion. The original paired macOS replay has completed successfully: both frontends
pass AgentOperationChannel, standalone CLI/MCP acceptance and both original live
application invocations. Product `d3fb25f4` uses compiler `3974d47b`; final
source/tool checks are unchanged and all owned process groups are absent. The
original deadline was honored. Compiler warnings remain in the logs (41
reference and 165 self-hosted lines); they were not suppressed. Evidence:
`btrsmith-agent-endpoint/interactive-d3fb-attempt-1/REPORT.md`, result SHA-256
`a1012230150e154a956705fa4f9bda5469b86252b7f53789fee7c64653bc487d`.
This closes the paired Mac agent journey, not audio, installed-product,
performance or the complete MVP acceptance.
The corresponding Linux continuation `37753689445` has failed while building
reference AgentSurfaceProcessAcceptance with GCC 15.2 at the original strict
C11/-O2/-Werror settings. Four generated pointer temporaries in
`AgentAcceptanceProcess_init` trigger `-Wclobbered`; the failing generated C
is retained. The paired agent target therefore did not complete, and later
audio/product targets did not run. Prior frontend/library evidence stays
separate. Artifact SHA-256 is
`86b7dabba26e13c7405d078f8e2e41cb189ebe53fee77fb09504749a1976e472`;
the original class now reproduces the four failures through both compiler
frontends at GCC -O2 and -O3. Paired fix `f75c737b` extends the existing typed
setjmp storage policy to generated pointer temporaries inside protected regions.
The reference side passes 36 focused checks and compiles that original class
cleanly at both optimization levels, with strict flags unchanged. The new tests
fail on the unchanged baseline. Its fresh self-hosted build now passes; the same original class compiles
cleanly through that frontend at GCC -O2 and -O3 too. Four paired corpus runtime
rows pass (both frontends at both optimizations), with no skips. Source, tools,
binary and process closure are verified in report `3458c356`. The full hosted Linux application replay
[37775247066](https://github.com/schiffy91/btrsmith/actions/runs/37775247066)
has completed with a later failure, using unchanged product `d3fb25f4`, original
strict flags/assertions and compiler `f75c737b`. The paired live-agent acceptance
step passes: logs record operation-channel, standalone CLI/MCP and live GUI
journeys through both frontends. The subsequent audio step passes setup,
terminal-disposal and session-shutdown checks through both frontends, then
`ApplicationShutdown.reference.clang` aborts on generated condition 50.
The failing assertion requires one audio session before the first close, but
the fixture never steps the GUI host to start its intentionally deferred audio.
The self-hosted application-shutdown row and Linux product derivation/install
do not complete in that failed run. The private artifact is `11554081040`,
SHA-256 `9c9ed38209251a14a5ccc639dd5e3b58b0d42053118b60afa54af554e01594ee`;
its download digest and selected source/log evidence have been verified. Workflow revision `b383f9f2` changes
only compiler pins, artifact label and historical wording. Final combined gates
remain pending. App descendants are checked and cleaned on ordinary test failure
as well as timeout. No full MVP claim.

Fixture-only product repair `37bbb680` starts audio through the actual native
work queue and host step, preserving the original retryable-close, retained
session, terminal-close and idempotence assertions. With compiler `f75c737b`,
the original macOS `native-shutdown-failure-check` now passes through reference
and self-hosted frontends, including original link-plan parity. Independent
review verifies all five commands exited zero, their process groups are absent,
and source, tools, binaries and logs match the retained receipt. Original
60-second native limits and the 2640-second outer bound remain unchanged.
Result SHA-256 is `694388f117fbe94e211f69a4fb511bbe789fea7cd393dcbb7a93ef9eb85b8b6b`
in `btrsmith-native-shutdown-37bbb680-f75-attempt-1/result.json`. This is a macOS
source-override component result, not installed-product or dependency-pin
acceptance. Existing-owner nullable warnings remain in the logs. The matching
Linux replay is pending. A separate production defect remains: GUIApplication
must propagate every non-complete window-close state before releasing dependent
view/session ownership. Source candidate `8f73b7d5` calls the existing idempotent
window close operation unconditionally and preserves all non-complete results.
It also fatally stops destruction on unfinished or thrown cleanup before runtime
field release; throwing from the destructor alone is insufficient because the
runtime catches hook failures. Source and paired-control recipes are independently
reviewed. The first original-baseline attempt transpiles and compiles but fails
at native linking: the test driver compares a bare compiler name with the resolved
Nix executable path and omits its probe object. No native child executes, and the
required baseline failure is correctly refused. All five owned groups close and
inputs remain unchanged. Retained result SHA-256:
`18e770a3ca3464a484af76939423a8061b2454fd4f3ddfc2168f73e4cd37b722`
in `btrsmith-window-close-f75-baseline-attempt-1/result.json`. The narrow driver correction now recognizes the resolved compiler identity and
injects its probe only into the intended link command, once. Twelve command
controls pass, including the original resolved-link failure. Identical fixture
bytes are mirrored across original baseline `f6c98636`, old-destructor
counterfactual `435bf12d` and candidate `8f73b7d5`. The corrected original baseline
now reproduces the actual bug through both compilers: both normal-close children
exit zero; both failure children observe real GPU/window FAILED, then abort at
the exact generated assertion that the application must return FAILED. This
qualifies the counterfactual, not the fix. All ten owned groups are absent and
inputs remain unchanged. Receipt `btrsmith-window-close-f75-baseline-attempt-2/result.json`
has SHA-256 `1b8de5dc4b10783ac6c724f329e47f52b9c317a1624fe3cafa50e8d672f9bd5d`.
The old-destructor counterfactual also reproduces through both compilers: normal
and native-closed controls pass, while unique deletion returns after the exact
FAILED/retained-dependency marker. Generated C confirms the unguarded hook then
releases owner edges. All twelve groups close and inputs remain unchanged;
independent review is clear. Receipt SHA-256 is
`f1c983cb2d3747d5e335b20b944e97822763639f1f93c5fca7a88b79cedbb4fe`
in `btrsmith-window-close-f75-destructor-baseline-attempt-2/result.json`.
Candidate `8f73b7d5` now passes all eight native cases with compiler `f75c737b`:
normal close, FAILED-state propagation with retained dependencies, native-close
handling, and final-owner destruction through each frontend. Both destructor
children stop at the exact fatal message with SIGABRT, before the after-delete
marker. The original paired Make and link-plan parity also pass. Independent
review authenticates both counterfactual receipts, all 846 product and 4,499
compiler files/modes, 39 tools/wrappers, native binaries/logs, and all 13 closed
process groups. Inputs remain unchanged. Result
`btrsmith-window-close-f75-candidate-attempt-2/result.json` has SHA-256
`c99e68fdcb2ca100006fac930b480e5009449de74e257c2aeb3a844e32ab56c4`.
This is bounded macOS source-override qualification in the retained dependency
shell with SDK 14.4. Thrown-close handling remains source-reviewed only; retained
ownership in the deliberate failure child does not prove failed-resource cleanup
or cycle collection. Existing compiler/Nix warnings remain. Exact `8f73b7d5` is
published privately on `codex/window-close-result-propagation`; it includes the
previously qualified `37bbb680` startup fixture. Linux, installed product,
dependency-pin and complete MVP acceptance are still required. Product fixture `37bbb680` is now published privately on
`codex/native-shutdown-lifecycle`, satisfying the Linux replay's source
reachability requirement without changing the current dependency pin.

### Integration status in service of the goals

**Current checkpoint, October 9:** main remains `cbd3ddcd`; broader integration
PR68 is on exact head `5aa232ad`. Linux, Windows, Windows ARM64 and Android
workflows pass. Both Mac release bundles, self-host tests, bootstrap, corpora and
Clang O0/O2 pass. Independent audit of those eight completed Mac jobs is clear:
self-host reports 5,845 passes/46 expected platform skips, each corpus 1,019 passes,
each Clang cell 2,038 passes and bootstrap one pass. All nine artifact ZIP digests,
both 255-file bundle manifests and 253 source payloads per bundle match; actual
Mach-O architectures and hosted relocation/strict-C11 execution are verified.
Boundary coverage stays 287/311 with 24 explicit exclusions. Audit
`pr68-5aa-macos-completed-audit/audit.json` has SHA-256
`8e4ab2ae3e75e7c5b430f2079321e538990a225a1e15bf16477c735569a2ed3f`.
Dedicated native-GUI run `37877458498` is now successful and independently
audited: 353 passes, 169 expected platform skips, all 522 test identities matched,
and no failures/errors/xfails/xpasses. The 169 skips comprise 167 declared
counterpart cases and two explicitly uncovered Linux tray rows; the counterpart
labels do not independently re-prove another runner. Hosted ARM64 Darwin evidence
does not supply physical Mac input evidence. Audit
`pr68-5aa-macos-native-gui-audit/audit.json` has SHA-256
`365ed15d7bfe78b7aae41458cdd0c34e0a6642e5b2437366df8f26cb962eff0f`.
Mac unit completed at 04:46 UTC with 10,148 passes, 227 expected skips and two
failures. Both nested serial tests disable xdist but inherit the workflow's
`PYTEST_ADDOPTS=--dist=loadgroup`, causing pytest usage errors before their ledger
exists. The final log/skip audit authenticates exact `5aa232ad` and these two
failures; no unit JUnit was advertised. Audit SHA-256:
`fdd04b1a0fd71dfdcf2195653d6a1eef81249dc4e8f666ed4f85442df7a03d36`.
Repair `5594563d` removes inherited child options while retaining explicit child
arguments and the outer GUI grouping. Its focused gate reproduces the exact two
baseline failures and passes all 84 candidate ledger/coordination cases without
skips. Eight owned groups close; inputs and logs match. Independent audit:
`2c837e02ed890b32a0771e3366f7422eba967ef1098a24c9ea87298a908177a3`.
Report-only follow-up `a29ab3e3` preserves those test bytes and is ready for a
normal PR68 fast-forward from `5aa232ad`; publication completed once at 05:32 UTC.
Automatic qualification is now running on exact `a29ab3e3`, with run identities
recorded above. No final combined-tree merge is claimed. The separate compact/flow candidate
has passed its fresh build, 45 focused checks, native flow driver and exact
current-product 423-file/ordered-plan parity. Paired Linux measurement is now
attempted as `37885703276`: both builds and correctness passed, but missing
product SDK exports stopped admission before any measurement. Its reviewed
environment repair, actual samples and full integration matrix remain pending.
The latest compiler and native component outcomes are recorded under the goals
above; test passes do not close the outstanding product performance or MVP targets.

**Historical checkpoint, October 8:** main is `cbd3ddcdb25b9c7519f2babc3dce38647b3a0212`,
which merged the consolidated plan and qualified Mac test-coordination repair
through PR69. The final PR head passed 36 selected checks; all four post-merge
Linux, macOS, Windows and Windows ARM64 workflows now pass. This does not merge
the remaining compiler/UI2/product work. Published PR68 head `00e45379` combines
the reviewed token/reply lifetime, GCC pointer-temporary and Linux
test-coordination repairs. Its 172 affected checks, generated-source validation,
lint and formatting pass; the full combined matrix remains in progress.
Its hosted merge `d38f344f` has exactly the candidate's tree. The combined
benchmark gate now passes unchanged: heavy stdlib reports 42,213,376 bytes and
dispatch 18,432,000 bytes. Artifact `11555372802` has SHA-256
`da11918dd305041d1783e006c7e4d7ee5b1b0e63993415713251f8406c9573de`.
This closes that combined regression gate, not the product memory/speed targets.
Android API 36 first failed when adb reported its device offline; its one
unchanged retry passes. The failed artifact `11554383604`, digest
`668e13b8ec74d5f4b216d6df74530029fdd01b02f6ea006936f6486321e49ea2`,
remains retained. API 29 and Windows bootstrap also pass at the new head.
The required explicit macOS native-GUI dispatch is
[37791840625](https://github.com/schiffy91/btrc/actions/runs/37791840625).
Its first job reached the unchanged 90-minute limit: setup consumed 62m45s,
leaving 27m36s for tests. The last visible progress was 72 passing dots (13%),
with no logged failure; no JUnit/skip artifact survived. This is incomplete
qualification, not a green suite or proof against a native hang. The retained
job log has SHA-256 `3391f8e260da6509c7ac863ca77ab360bebcef45c62c5c5d8ac7d018b3bfacdd`
in `pr68-00e45379-macos-gui-timeout/job.log`. One unchanged failed-job retry is
accepted as attempt 2, job `113422566478`; preserve source, 90-minute job limit,
600/60-second test bounds and three workers. Linux run `37786709187` is complete and independently audited:
all 13 expected shard reports are present, tied to exact merge `d38f344f` and
candidate tree `53a05e9f`, with fatal skip classification enforced. Unit tests
report 7,230 passes/3,128 expected skips; self-host tests 5,857/34; both corpora
1,019 passes with zero skips each. All eight GCC/Clang C11 cells pass 2,038 cases
each with zero skips; bootstrap reaches its fixed point. X11 reports 324/199,
Wayland 322/199. Wayland remains configured report-only, but its actual test step
and JUnit pass. Release, generated-source, lint, format, extension, Linux bundle
and final source hygiene pass. Boundary accounting is 287 checked of 311, with
24 managed-behavior records explicitly excluded. Expected skips and physical
Linux desktop coverage require counterpart evidence; they are not passes.
Audit SHA-256 is `ff94d1ab8a3552c01121518f0bef6b9d4d1311d0a6449814a1055100a49164f8`
in `pr68-00e45379-linux-final-audit/audit.json`. The macOS ARM64 bundle now also
passes archive construction, relocation and execution of its strictly compiled
output (job `113343316526`). The Mac bootstrap boundary artifact likewise checks
287 of 311 records and excludes the same 24 managed-behavior records; it does
not fill the Linux exclusion. The exact-tree build-safety contract explicitly
keeps observed proof separate from the portable main gate; no required counterpart
workflow exists. Keep the 24 records unchecked. The existing opt-in observed
capture route is available without rewriting the frozen observation contract.
Artifact `11559776904` has ZIP SHA-256
`204066ca5f2cd1b9f95ab0f07ff50f93cfb11b109fa9b9eedfde7c921be1de8e`.
The macOS x64
bundle attempt reached its unchanged 45-minute job limit during Nix dependency
realization, before compiler/bundle tests. Its retained log digest is
`1cd1b8ca7ce8466b4e9498fbba383a74a2442d8543d889dc327428cd29b40588`;
cache HTTP 429 is observed but not established as the sole cause. GitHub refused
the immediate single-job rerun request while the workflow was live; that request
started no retry. The original workflow is now terminal: bootstrap, both corpora,
self-hosted tests, C11 O0/O2 and the ARM64 bundle pass. The macOS unit shard
has now failed: 660 failures, 260 errors, 9,213 passes and 227 skips. Its log
records previously used native-reader and Python store paths disappearing during
the run, with secondary Python-module and child-start failures. No removal/GC
cause is established; do not classify all failures as infrastructure. Job `113343316411` log SHA-256 is
`2cb00dd368165e68e2038d6fb5c94742be882d3631ffa2774f541554755fd0be`; artifact `11561484842` retains the main failing unit report separately
from a nested one-pass child report. On October 8, the one unchanged
failed-job replay was accepted as attempt 2. The x64 release bundle now passes
(job `113416270707`); unit retry `113416271573` is now executing its test step, with other successful jobs
retained. The original terminal snapshot has SHA-256
`4f4515b61e8e280b0588ba6f727aa67016d757afb45e33c92de8488898e9ff24`
in `pr68-00e45379-macos-retry-2/attempt-1-terminal.json`. Root-cause analysis and
the complete Mac matrix remain open. Do not merge until the failure is resolved
and required skip/native evidence is qualified.

Windows PR53 previously merged on main at
`49f136ec94bb46cf67dd9bf407df6e4b0d79332c`. Its source tree is exactly the
qualified `110a514c` / hosted merge `93093bd4` tree. All five hosted workflows
passed, including actual Windows ARM64 compiler/bootstrap, sample execution and
MSVC ABI/wgpu checks. All post-merge workflows on main `49f136ec` also pass,
including Linux and macOS. The Linux full test shards, bootstrap, all eight C11 cells,
generated checks, lint, formatting, extension and release hygiene passed;
skipped standalone jobs are not counted as evidence. This independent slice did
not wait for UI2 or the remaining compiler work.

The preceding broader candidate `3974d47b` remains the historical PR68 baseline;
the [current draft PR68](https://github.com/schiffy91/btrc/pull/68) head and its
qualification are recorded above. The baseline's original hosted matrix has
completed; Android tooling/API 29/API 36, Windows, Windows ARM64, the Linux
ARM64 bundle, release/static ownership and the Linux Wayland lane pass. Linux
and macOS bootstrap pass; all eight Linux C11 cells, all Linux test shards and
both platforms' paired corpus lanes pass. Linux CI has completed with exactly
the benchmark and X11 job failures; its skip classification passes. The macOS
workflow is now green, including self-hosted/unit shards and skip classification. The
Linux benchmark job fails only the unchanged heavy-stdlib memory allowance recorded
above. The current X11 native lane also fails three scrollbar input cases
(reference plain/sanitized and self-hosted sanitized); self-hosted plain passes.
The binaries abort in `ScrollJourney.run`, after the geometry checks, with
321 other passes and 199 skips. This is an open native assertion failure, not
a skipped capability or an accepted environment warning. The first [controlled X11 diagnostic](https://github.com/schiffy91/btrc/actions/runs/37735904202)
failed to upload container-owned evidence; that failed attempt is retained.
Its [transport-corrected rerun](https://github.com/schiffy91/btrc/actions/runs/37738526714)
retains a same-window DOWN with focus, then FOCUS_LOST, then MOTION; offset stays
zero and the original offset-300 assertion aborts. All eight isolated
original/traced, paired-frontend, plain/sanitized rows pass; concurrent scheduling
has ten passes and two original Python failures. The historical concurrent
event stream is still unproven. These results support qualifying coordination
for cooperating shared-display tests while preserving cancellation for real
external focus loss. Candidate `14f9e193` adds that bounded lease and process
regressions; its original full X11/Wayland suites are in hosted qualification.
No native assertion, timeout, skip allowance or provider input path changed.
Evidence: `linux-scroll-x11-hosted-37738526714/analysis-result.json`, SHA-256
`c59bef77236727959f4f354e8f44563f6f5cd59d9e6c548af125f6801f2822fd`. The earlier `71a22734` general CI failed on
tuple declaration ordering, two unchanged peak-memory allowances and two unit
contracts (compiler lambda ownership and missing signing subprocess timeouts).
The recorded peaks are 45,973,504 against 44,789,760 bytes for
`CompileStdlibHeavy`, and 18,989,056 against 17,924,096 for `RunDispatch`.
Logs remain in `hosted-71-current/`; no benchmark baseline was refreshed.
Source checkpoint `56d548c4` carries the reviewed tuple-order repair, ordinary
`operator.attrgetter` keys and bounded signing subprocesses. Its fresh native Mac
compiler builds with Clang 21.1.8; all 48 preflight checks pass. The paired tuple,
parent-reachability and original failing corpus checks pass. The initial 43-row
run has 41 passes and two stale expectations: the discovery-only edit now lowers
one group rather than three. The strengthened release/debug fixture at `dcf8ba88`
passes all four paired native rows, requiring exact unchanged-unit bytes, clean
versus incremental equality and executable output. Its edit changes neither the
shared shape inventory nor the separate whole-program mentioned-name set.
This is reduced compiler work, not a measured wall-time or memory improvement. The complete
311-record boundary recapture at `3974d47b` has 307 byte-identical records and
four tool/environment identity differences matching the previously qualified
same-host observation. All 34 equality checks and 32 status channels agree;
all 12 observed source/compile/run channels exit zero. The ordinary checker
accepts 287 records and classifies 24 as host-incompatible. No accepted fixture
or manifest was changed. Evidence is in `tuple-boundary-current/3974d47b…`.
The independent genuinely new-shape fixture at `3a294446` passes all four
paired release/debug native rows too: it lowers three groups, changes only Lib's
C bytes, matches a clean build and changes the native result from 6 to 13.
Both guards isolate the shared inventory from mentioned-name changes. Original
failures and fixture corrections remain retained in `tuple-canonical-order/`.

The local Linux qualification is complete for its bounded component snapshots:
**100 native provider cases pass**, plus all **11** inherited-interface compiler
regressions. All **100 counterfactual rows** reached native execution: **64
intended native failures and 36 passing controls**, with zero skips or setup
errors in the accepted rows. These cover event delivery, Cut/popup/visibility,
Grid/Stack resize, scrollbar pixels/input and Grid replacement. E40's original
invalid bool ternary was corrected only in fixture `2e82334d`, with paired
branch-truth/laziness proof; original failed attempts remain retained.
The 96-case snapshot is `2202c0bd` plus that fixture; the four Grid cases use
`47e64e21`. Both use compiler `808592c9`, native binary SHA-256 `1739f6b1…`.
The task-started Linux VM is stopped and its locks released.

`codex/integrate-qualified-linux` at `3974d47b` assembles those exact provider/test
bytes with compiler checkpoint `56d548c4`, strengthened reuse fixtures and current
Windows main. Its original hosted gates are complete, with memory and X11 failures above; it
is not yet a qualified combined tree. The Mac skip fragments classify platform absence
only. The normal Grid driver now records exactly four Mac skips; its precise
admission passes0→4 replay and mismatch/Linux rejection checks, with no native
pass inferred. Full tests,
bootstrap, C11, static/generated/extension/hygiene gates, current native checks
and final compiler parity remain required. No main or performance completion is
inferred from the component counts. See
[the integration record](https://github.com/schiffy91/btrc/blob/3974d47bc87851b1ac19b8d2b4bd5022f2d94676/docs/workstreams/qualified-linux-integration.md) and
[the inherited-interface repair](https://github.com/schiffy91/btrc/blob/3974d47bc87851b1ac19b8d2b4bd5022f2d94676/docs/workstreams/interface-parent-reachability.md).

The consolidated plan and candidate combine substantial compiler correctness,
C-compatibility, diagnostics and platform-host repairs. Bootstrap and all eight
strict-C11 configurations pass on the recorded checkpoint; final combined-tree
qualification, performance failures and native-platform gaps remain. The later
Apple availability schema/table merge `ba6c221d` passed 186 focused checks and
static/generated gates locally; semantic consumers and final integration remain.
The combined candidate `06c3923a` now includes that Apple merge, the current plan,
the runtime repair and the native button repair. Its fresh self-hosted compiler
build, lint, formatting, generated-source and extension checks passed. The
compiler SHA-256 is recorded with the source-pinned preparation evidence; the
full combined matrix stopped on October 7 at 17:54 UTC: **17 failed, 17,838
passed, 168 skipped** in the parallel suite. Bootstrap and strict-C11 steps did
not run after that failure. The 17 failures have three causes: 11 target-specific
structure checks need the exact externally exercised `platformUnavailable`
method recorded; five strict-import checks omit Python-owned BTRC fixtures and
their generated table dependency; and the GUI discovery audit does not recognize
the nested button fixture's exact root-relative path. The actual AppKit fixture
already has the four native passes recorded below. Audit repair `3cf1b084` is now
committed on the integration branch; it preserves exact-set coverage and adds
omission/path regressions. Isolated checks
against the read-only `06c3923a` tree reproduced exactly the 17 failed case names;
the three repaired audit modules then passed all **186 checks**, with no skips or
errors (70.81 seconds). Lint, formatting, patch applicability and independent
review pass. These draft checks exclude the repository's root gate configuration
and run no native/compiler builds. They do not replace the final matrix. The
patched source matches the reviewed draft; normal repository qualification is
the next gate.
The failed matrix and skip inventory remain preserved under
`combined-06c3923a`; the candidate has no passing full result.
The repaired candidate `dff538ef` passed lint, formatting, generated-source and
extension checks. Its full parallel suite finished with **17,855 passes, 168
skips and three failures** in the macOS native-shell lifecycle test. The failures
are plain-selfhost activation during repeated application cycles, a surviving
provider NSTextField during sanitized-selfhost teardown, and a surviving
NSTextField during sanitized-python restoration. Their raw source, executables,
logs and XML remain retained in `combined-dff538ef`; diagnosis is active.
The fresh compiler was reused only after verifying that the delta from
`06c3923a` contains PLAN.md and three audit files, with identical binary hash.
The parallel failure stopped the embedded serial bootstrap. Explicit bootstrap,
strict C11 and final main integration remain pending. This is not a qualified
combined tree. Integration candidate `28702e8d` now reconciles the signed native
link fix, the published button branch and current evidence; its compiler, stdlib,
runtime, specification and generator bytes remain identical to `dff538ef`.

The Mac retention diagnosis reproduced the same NSTextField survivor in an
independent AppKit-only executable: live after 221.9 and 292.8 ms, gone at
314.8 ms. The approved lifecycle contract permits bounded deferred deallocation;
the old ten-turn/200 ms probe assumption was too short. The reviewed probe repair
retains zero-owner and registration assertions, waits for convergence with a
two-second deadline, and includes a deliberate strong-reference negative control.
The focused module finishes **39 passes and two failures**. Reference
plain/sanitized journeys pass. Plain self-host activation still fails after 45
successful cycles. Sanitized self-host completes 100 cycles, 100 GPU frames and
100 restores with zero provider/registration survivors, but its private-class
comparison fails: its window becomes active/key, while the native control remains
inactive/nonkey throughout and never creates the insertion-indicator helper.
The independent sanitized AppKit control now completes 100 cycles with all
300 Tab observations active/key, zero provider survivors and one insertion
indicator per cycle. Its bounded public activation/key retry preserves the
original 15-second journey deadline. The source correction requires this actual
context in the comparison; private-class and growth checks remain unchanged.
Two standalone traced self-host runs pass, so the intermittent activation failure
was traced in the actual suite order after the reference restoration workload.
Source `c0e4d48a` passes all **47 focused cases** in that traced run, including
420 successful native-shell child processes. The independent AppKit control was
not instrumented. The same clean source then runs uninstrumented: **44 pass and
three fail**. All four BTRC variants complete their 100-cycle/100-frame journeys
with zero owned survivors; three companion controls fail before cycle one because
they cannot become active/key within the existing 15-second deadline. The exact
plain control binary passed 100 cycles in the preceding run. A public process
probe identifies `com.apple.loginwindow` as the active foreground application;
launching the unchanged control as an application bundle does not fix it.
Local foreground-dependent qualification is blocked. No unlock, credential or
system-setting change is attempted. The original BTRC activation error did not
recur in either full focused run and remains separately unresolved. Cross-worker
coordination now serializes the actual AppKit execution tests because local and
hosted parallel suites can otherwise compete for focus. Source `ade99447`, report
`49178fc1`, has seven passing independent-process checks plus 15 harness checks:
the shared checkout lease protects fixture setup/body/teardown, releases on errors
or process death, reports a bounded timeout's holder, and leaves ordinary workers
parallel. Actual pytest collection verifies the known parameterized AppKit paths.
Independent review is clear; native execution after this change remains pending.
The two-second weak-owner
deadline, deliberately retained negative control, actual active/key context and
unchanged private-class assertions are preserved. Source and evidence report
`08d77b32`, the coordination repair and the reviewed G12 compiler change are
reconciled into local candidate `db269d6c`; this is still not a
passing final combined tree.
The Darwin Python/libffi repair `2e8e3711` now passes the actual callback smoke,
46 build-safety checks and upstream CFFI's 1,888 checks (161 skips, four deselected,
four expected failures). Its four-platform package evaluation also passed;
Linux runtime builds and final combined-tree gates remain separate evidence.
Windows crash-location diagnostic `53da5fd0` passes 130 portable tests, one
native-only skip and ten subtests. PR53's native run `37651593291` stopped before
compiler qualification: the test still expected nine diagnostic commands, while
Windows correctly adds a tenth crash-location command. Fix `483e5bab` explicitly
checks the Windows, macOS and Linux command sequences and bounds; its 36-test
module has 35 passes and one native-only skip locally. The correction was
published normally to PR53 at `483e5bab`; general CI `37701082801` passed all
19 executed jobs. Native Windows run `37701082806` passed
preflight but failed before BTRC/bootstrap execution. Minimal ARM64 objects build,
while direct linking crashes in the root Zig process at `zig.exe + 0x910f34`.
The artifact records an access violation but no stack; it does not establish an
LLD child crash. Reviewed local diagnostic `75c00a96` bypasses the driver with the
pinned direct COFF linker under existing process limits; 37 portable tests pass,
with one native-only skip. It is published at `75c00a96`; native run
`37707241092` is terminal: cross-build passes, native qualification fails before
BTRC executes, and the separate MSVC/wgpu smoke passes. The direct `zig lld-link`
ARM64 DLL probe succeeds with exit zero and no captured exception, while
`zig cc -target aarch64-windows-gnu` still exits with an access violation when
linking an executable. This narrows the investigation to the driver/CRT path;
the no-CRT DLL probe does not qualify executable linking. This run’s driver
crash-location probe times out without an exception record. General CI
`37707240934` passes. Native-toolchain repair `fe115d6b` is published to
[PR53](https://github.com/schiffy91/btrc/pull/53): native Windows ARM64 uses the
official Zig 0.17.0 archive, whose release notes identify an ARM64 Windows LLVM
workaround; the separate cross-toolchain pin remains 0.16.0. Each native invocation
gets fresh bounded local/global caches. Portable qualification has **39 passes
and one native-only skip**, plus the workflow contract check and independent
review. Native run `37711636840` passes cross-compilation, C object generation
and actual minimal GNU executable linking. The strict probe then fails at the
newer CRT's external `mkdtemp` declaration colliding with our static adapter.
Follow-up `110a514c` preserves the adapter body under an internal name and an
object-like portable alias, matching existing CRT wrappers. Its strict-C11
three-translation-unit regression reproduces the conflict before repair; all
five compatibility checks pass afterward, with no skips. These local checks are
Windows cross-compilation/linking, not Windows runtime evidence. Independent
review is clear and the follow-up is published to the same PR for native rerun;
the prior general CI is superseded. Rerun `37714407651` now passes its ARM64
cross-build, native compiler build, three-stage byte-stable bootstrap and compiled
sample execution on Windows 11 ARM64. Cross/native sample C is identical.
The following MSVC ABI/wgpu smoke also passes, creating an instance and returning
an actual adapter through its callback. General CI, Windows, Host Windows and
macOS workflows all pass for published `110a514c`. The native job tests hosted
merge `93093bd4`; final combined-tree qualification and main integration remain.
The retained 146,088,636-byte artifact matches its hosted SHA-256
`4c4c5c0522f132f8a029567f4e23d832f8e6c86204f16529249995e0fa369226`.
Native compiler SHA-256 is
`9b0e5cfdc66c90e3d9096617261ccb2383a30933b2c85172ea9863ba86c99e4f`.
Evidence is retained under `windows-110-native/`, including both native summary
JSON files, the full archive, index and retrieval receipt. These repairs
restore verification capability; they do not demonstrate compiler speed gains.
The plan-reader modules passed 155 checks at `27417a89`.

**First product-facing result from the subagent pilot:** `CX-STDLIB-03` preserves
explicit Mac button alignment through title/symbol changes while retaining default
presentation. The actual AppKit regression failed in all four configurations at
`d248b742`; after one boolean-typing correction, integration `37a8ae67` passed
reference/selfhost × plain/ASan+UBSan (four passes, no skips, 52.80 seconds).
[PR66](https://github.com/schiffy91/btrc/pull/66), head `a6a55d73`, contains the
same provider/fixture/driver bytes, its evidence report and exact nested-fixture
admission repair. Hosted branch checks now pass; final combined-tree gates
remain open, and the repair is not yet on main. PR66's nine
failed CI jobs in run `37652762370` never started: each has the same GitHub runner
acquisition failure and zero executed steps. Attempt 2 is terminal: eight retried
jobs passed; the unit job ran and failed
only `test_native_gui_target_drives_every_fixture` because it did not discover
the nested ButtonAlignment fixture (6,815 passes, 3,120 skips). The audit repair
already present in `dff538ef` addresses this exact path-discovery defect. It is
now published at `a6a55d73`, with all 22 audit tests passing locally and independent
review complete. General CI `37707733710` is terminal success, including the BTRC corpus, all
eight C11 configurations, bootstrap and Linux X11/Wayland lanes. macOS run
`37707733657` passes its executed scope/native-GUI/native-bundle jobs; the broader
Mac test and skip-report jobs are deliberately scope-skipped. Final combined-tree
qualification remains separate.
[PR67](https://github.com/schiffy91/btrc/pull/67) claims `CX-UIA-21`. Local source
`ca4782e1` implements the approved 53 operations, values, facade and completion
hook, plus portable fixtures and the final catalog fragment. Independent review
found and closed cancellation-state defects. All 26 BackgroundJobs cases passed
through both compilers, including plain/sanitized completion and explicit-retry
regressions, at `06a4806f`. The catalog suite first exposed an isolated fixture
that omitted live amendments; after its repair, all 114 catalog tests pass.
Only that test and the report differ from the native-qualified source; production,
compiler and native-fixture bytes are identical. This qualifies the completion
hook, not the desktop providers. Both providers now have fixture-first source
checkpoints for worker wake and executor behavior. Shared private semantic owner
`cd5530af` centralizes cross-control event order, terminal reservations, callback
cancellation and eligibility; both provider branches use the same bytes. macOS
adds a common-mode CF source and deadline timer; Linux adds bounded plain-data
publication and a fair scheduler. Review exposed a post-admission host exception
that could strand cancellation; repair and failure fixtures are in progress.
These source checkpoints have formatting/static checks only. Compilation,
complete provider wiring, native acceptance and atomic landing remain open.

#### Current iOS runtime admission (October 9)

The historical local 50-case proof used iOS 26.4 and handwritten strict-C11
host fixtures, not compiler-generated BTRC provider acceptance. The retained hosted
attempt ran zero fixtures after launch-identity timeouts on iOS 27. Neither
establishes the minimum runtime. The exact 11-path host port onto main `36b647f0`
is source-reviewed; focused 28-test and workflow qualification is being prepared. D8 permits iOS17 when installable under exact Xcode27A266a, otherwise the
oldest installable runtime with the iOS17.0 deployment target compile-checked.
The live Apple catalog advertises actual17.0/build21A328 and later17.x; official
Xcode27 support includes iOS17+ simulators. Therefore absence from the installed
inventory is not proof of uninstallability. Versioned acquisition/import under
the existing toolchain is the next bounded admission, separate from the11-path
host-adapter integration and the existing hosted launch defect. No SDK payload,
installation, boot, new account or settings change has occurred. Audit1da45900
retains exact policy, catalog bytes and tool help; local capacity does not admit
the7.56GB asset plus extraction under the required floor.

## Outcome execution register

This retained register connects earlier evidence to the goals. Its rows describe
the dated October 7–9 state and must be reconciled with newer evidence when an
executor takes up work; their ordering and old next actions do not override the
[approved stack rank](#approved-stack-rank). Owners below are responsible roles,
not claims that a builder is currently running. The October 7
review used three read-only subagents (performance, platform/library and execution)
plus the main integrator. The October 8 implementation wave has produced the
reviewed token-lifetime candidate rebased at `71352c50`, the qualified Linux
provider repairs, and paired native BTRSmith library proof; their remaining
qualification is recorded below. Implementation assignments must also carry a live
WORKSTREAMS claim and exact base SHA. Update a row when its result or blocker
changes; historical test totals alone do not advance its status.

| Outcome | Current state / evidence | Responsible role | Next acceptance and actual blocker |
|---|---|---|---|
| Current compiler speed and memory matrix | Linux product comparison `37901757750` is independently accepted: median RSS −32.96%, 3.23 → 2.17 GiB; all 45 checks, native flow driver and eight output/plan comparisons pass | Performance owner; main session runs quiet measurements | Worst candidate remains about 685 MiB above 1.5 GiB. Qualify the combined source, use the held phase-RSS observation to identify remaining ownership, and complete the original speed/footprint matrix. |
| Faster incremental edits | Current tuple/instance repair proves one changed group for inventory-preserving edits and three for genuinely new shared tuple shapes, across both frontends/release/debug with strict native outputs and clean-versus-incremental equality | Incremental compiler owner | Finish current combined gates, then measure edit median/p95 and memory. Full consulted-fact/analysis reuse and Stage 9 counters remain open. Work counts are not speed results. |
| Useful desktop library improvement | Final source `a29ab3e3` passes Linux native-GUI, X11 and Wayland plus Mac native GUI; the identical tree is merged at main `36b647f0` | Provider repair owner; main integrator qualifies | Physical-desktop coverage and remaining UI2/features/accessibility stay open; preserve declared host limits. |
| UI2 events, executor and lifecycle on desktop | macOS source73f636e8 passes all 88 affected native cases: 48 lifecycle plus 40 focused, both compilers and sanitizers. Independent audit is clear; scope-exit, original error precedence and stopped-loop state defects are repaired | Application, text-field and range/selection owners | Integrate the exact qualified provider dependencies and narrow native manifest; complete remaining controls/platform capabilities and final combined-tree gates. The source is not yet merged. |
| Windows and mobile application-facing services | Windows source `3e480fcd` passes all four original process/thread native cells on real x64/ARM64 in `37904145886`, independently audited `b957d11d`. Historical Android and iOS fixture results remain scoped | Platform slice owners | Fresh combined compiler/provider gates are required. Mobile widgets/lifecycle/persistence and oldest-installable iOS runtime remain open. Reviewed acquisition packet is held; no runtime acquired. |
| BTRSmith on all five platforms (retained macOS/Linux milestone evidence) | Mac album/Settings fixes are qualified; latest Linux run `37905070491` completed successfully and includes installed-app launches, with independent artifact/visual audit `e759a38b` clear for the selected journeys. No-folder Player diagnostic passes catalog readiness then times out waiting for song | BTRSmith owner and integrator | Identify and repair Player readiness/cleanup and native mute, then complete broader screen/audio journeys, timing budgets and the actual compiler pin. |
| One qualified implementation on main | PR68 is merged at `36b647f0` after final standard/dedicated gates; eight included PRs reconciled. Next combined source `3694ce58` passes fresh build, 200 focused cases, native driver, four SDK projections and static checks | Main integrator | Repair retained post-merge Mac reader-lifetime/setup failures and complete the next exact-tree hosted/native matrix. Other UI2/iOS/design branches remain separately unqualified. |

**October 9, 08:47 UTC integration update:** [PR68](https://github.com/schiffy91/btrc/pull/68)
merged at `36b647f079ed7338e51b119a11046eb222dd4877` at 08:31:45 UTC.
Its tree `2bd979a7` exactly equals qualified head `a29ab3e3`. All standard
selected matrices passed; dedicated Linux `37896628801` has native-GUI
321 passes/201 expected skips, X11 324/199 and Wayland 322/199. Dedicated Mac
`37896651788` has 353 passes/169 expected skips. There are no failures, errors
or unexpected skips and all JUnit identities match their ledgers. Independent
audits are `83d02f71`, `6c367770` and `805d4392`. Across the declared host scopes,
522 of 523 distinct cases pass; the physical Linux desktop case remains unrun.
This does not claim physical-input, device or complete application acceptance.

GitHub automatically marked PR35 and PR60–66 merged because their exact heads
are ancestors of the integration. No branch was deleted. PR67 retains its
claim-only documentation, PR51/52 their HTTP/Windows-services design changes,
and PR34 its iOS host tooling; none is qualified merely by inclusion in this
inventory. The next compiler source `12fd0423` merges the accepted memory
candidate/report and Windows provider with main; production/test files merge
without conflicts and independent prerequisite review is clear. Fresh combined
self-host, affected paired checks, generated checks and the full final matrix
remain mandatory.

At the 08:47 UTC check, automatic post-merge Android is successful, Windows
ARM64 is running, and Linux/Mac/Windows standard workflows are queued. The two
active hosted waves are those post-merge checks and current BTRSmith Linux replay
`37905070491`; no duplicate dispatch or restart is scheduled. The separately
reviewed iOS acquisition packet preserves the 100 GB initial Stage 23 admission,
80 GB operation/final floor, known 7,559,529,352-byte image and unknown extraction
space. No runtime has been downloaded, imported or booted.

For usable-library status, use the existing native catalog and platform inventory
as the source of operation IDs and denominators. Each delivery report records
operation/family, platform, implemented revision, native-qualified revision,
merged revision, evidence link and missing acceptance. Do not infer a provider
pass from a host fixture or create another percentage-complete denominator.
The top-level platform table is a summary, not a substitute for those rows.

### Current performance prerequisite findings (2026-10-07)

The bounded G12/SB-29 candidate `c3f709f7` canonicalizes specialization emission
and matching module-cache identity in both compilers without changing analyzer
demand order. Four genuine reference regressions first fail because swapping
existing instance uses changes the otherwise unchanged template unit. The repair
passes nine reference cases and then **18 paired cases** with a freshly built
Mac native compiler (SHA-256
`5b5bd238a8313750d95834782a6a7c883e2ce975919422fb6fccf4f38878655f`,
Nix Clang 21.1.8, strict C11, `-O2`). Release/debug class and method reorderings
preserve `Lib` and lower exactly `Use`. Changed instance sets still update the
template and conservatively lower all three groups; reverse-lexical by-value
dependencies and tuple/span invalidation guards remain covered. Independent
source review is clear. Both retained dependency programs also compile under
strict C11 and execute successfully. The existing generator captures all 311
boundary records: 287 portable and 20 observed outputs are byte-identical to
their effective accepted artifacts; only four tool/host metadata records differ.
All 34 equality constraints and 32 status channels are preserved, including
eight expected negative diagnostics. Independent review confirms the inventory
and the unchanged original frozen tree. The normal checker reports 287 checked
and 24 incompatible observations; explicit capture executes those observation
producers and does not turn the checker result into 311 passes. No expectation
refresh is needed. Report `9a7e4310` is merged into the local candidate. This
is one approved reuse improvement, not complete G12, Stage 9 or a speed result.

The bounded memory candidate `69ca0f17` ends lexer/parser/token-vector ownership
after parsing while retaining the AST. Independent source review found no
blocker. Its native build and self-transpilation passed; both compilers' emitted
cleanup was reviewed. It passed 120 focused production diagnostic assertions,
eight paired literal/ownership cases and 18 scope/capture cases, with no skips;
two representative programs retained byte-identical C and diagnostics against
the baseline. The instrumented compiler also passes all 146 bounded checks with
zero ASan/UBSan reports. It observes 51 lexer-error, 16 parser-error and 26 success
paths, releasing all 2,296 watched tokens and their parse owners before the
asserted boundaries. This uses Apple Clang 21.0.0 after the Nix sanitizer's trivial
startup probe timed out; the original failure is retained, and leak detection is
disabled. Final branch `d6309c7c` adds only evidence documentation to the tested
production source. Full bootstrap/C11 and current memory/instruction measurements
remain unqualified. Historical retained-token attribution was 98.5 MiB; that is
not a measured saving on this candidate and does not close the 1.5 GiB target or
explain the outstanding Linux regression.

The Stage 4 btrc close-out is already recorded; reuse the existing BTRSmith
`stage4/pin-bump` branch at `8204b8a9` rather than repeating its rename/native-source
guard work. That branch still pins `cdf9d952`; application main still pins
`05ec9cb7`. The remaining work includes the current compiler pin, findings ledger
and actual application requalification, then the frozen D9 measurement copy.
The `stage4-requal` and `stage5` runbook presets already exist.

The existing `8204b8a9` product source was reused from the outside-Drive hub
for current-compiler diagnosis, without changing its lock. The two original
`BuildArtifacts.test_import_content_touch_edit_and_removal` tests reproduce the
warm-build defect against compiler `dff538ef`: both frontends compile zero native
units but relink once instead of zero times. Product Make previously signed the executable
after native-plan records its output hash; retained receipts and final signed
executables differ in both cases, so receipt validation correctly rejects reuse.
Native builder `3c5a89ec` now signs and verifies the staged executable before
publication and receipt creation; product caller `e00c61d2` supplies signing
policy and retains unattended keychain unlocking. The original paired tests pass
unchanged: both frontends perform zero compiles/links on warm and touch builds,
preserving executable inode, mtime and bytes. A content edit compiles one native
unit and links once; its next unchanged build reuses the result. A removed import
still fails before native execution. Every retained receipt matches the final
signed executable, and the named-certificate designated requirement remains
stable across all five successful builds per frontend. Independent review
verified the retained evidence. The native suite has 31 passes, the focused
signing units ten, and the product Make graph 24; separate failure checks preserve
the prior executable and receipt. Final BTRC branch `e2090c51` changes only the
report from the tested production source. An initial certificate lookup wrongly
excluded the existing local certificate; the corrected lookup preserves the
product's policy without changing keychain or trust settings. Main integration,
the product pin and full packaged qualification remain open. This fixture proof
does not establish the full-product latency budget.
The first diagnostic attempt stopped at an unset Nix wrapper build-directory
variable; after correcting only that external runner environment, the actual
product failures reproduced. This is source-override diagnosis and focused
qualification, not locked-pin or packaged-product qualification. All attempts and failure artifacts remain
preserved.

A concrete qualification blocker was found: the expected
`stage2-qualifying-failures.txt` is absent, and the runbook's pytest-style failure
parser does not normalize the retained Make/BTRC/unittest release log. It extracts
`(failures=2)` from a unittest summary instead of stable case IDs. The recoverable
source-test TSV failures are a different suite and must not be substituted as a
release allowance. Normalize the release-result adapter with fixture-backed tests,
keep infrastructure/compilation failures explicit, and reconstruct only allowances
supported by qualifying pin evidence. An empty or guessed allowance is not valid.
The bounded `codex/btrsmith-release-results` repair is committed locally at
`0fec0960`: 85 focused tests, lint and formatting pass, and independent review
has no remaining blocker. It names unittest cases from observed command
provenance, preserves full pytest parameter IDs, separates build/infrastructure
failures, and prevents an invalid earlier attempt from erasing new retry failures
or permitting a push. Replaying the retained release log yields two stable test
IDs plus 38 non-test/unclassified diagnostic records and still fails qualification.
It creates no allowance and does not qualify BTRSmith. The reviewed packet is
now reconciled into the local integration candidate; publication, combined gates
and actual application requalification remain outstanding.

### Delivery review and progress measurement (2026-10-07)

The review found that the old immediate queue scheduled reconciliation and
integration without explicitly scheduling current performance evidence or the
BTRSmith pin. It also repeated completed startup work, retained a Stage 1
Ultracode restart and asserted recovery bundles without a verified retrievable
location. Those instructions are corrected below. Existing compiler repairs do
not block UI2's approved interface: see the approved record's Compiler gaps.

The host is a real throughput constraint. The recorded full suite took 1,863.14 s
(about 31 minutes). The separate `checkpoint-skip-final/remaining-gates-manifest.json`
run took about 70 minutes for static checks, bootstrap and C11, including about
58 minutes for C11. These are observations from prior runs, not a forecast or
current-tree qualification. Runtime environment repair has also required failed
build attempts. There is no complete accounting that establishes which category
consumed most elapsed time, or that the model is the limiting factor.

For the next implementation pilot, record start/finish times for implementation,
review/rework, environment repair, gate execution, gate waiting and evidence
recovery, plus accepted outcomes and commits landed. Record overlapping intervals
rather than summing parallel time. Compare useful accepted output and waiting
time before increasing concurrency. Report progress as changed goal evidence,
shipped capability, blocker removed and next acceptance; keep infrastructure
activity subordinate to the outcome it enables.

## Owner update: one plan and integration (2026-10-07)

**D29.** The owner requested one detailed, current plan, then instructed this
session to implement and merge branches into main, resolve issues, and report
when the work is harmonized. This supersedes D28's separate-plan storage rule and
the earlier Claude-only integration restriction for this authorized session.
It does not waive parity, review, test gates, file-claim coordination, native
qualification, or the rule against losing evidence. Existing-interface repairs
and independent platform slices still follow D28's technical-prerequisite rule.

Integration means reconciling each branch's intended changes with current main.
An evidence branch or deliberately unsafe floor experiment is preserved and
accounted for; it is not mechanically merged into production. Superseded patches
are compared before disposition. A merged design is not an implemented provider,
and a green hosted workflow is not physical-device qualification. No branch or
issue is called complete merely because it applies without a Git conflict.

### Execution access update (2026-10-08)

The owner has prohibited new permission requests, including requests to use
`gh`. Filesystem and network access are now enabled without approval prompts;
continue authorized work with existing credentials and noninteractive commands.
Never raise a permission or credential prompt. An action lacking usable access
remains pending while independent work continues. The previously drafted audit
repairs are now committed at `3cf1b084`; their isolated proof remains separate
from the normal repository gate and main integration. Retain prior evidence and
do not repeat a failed access request.

## Navigation

- [Owner priorities and execution handoff](#owner-priorities-and-execution-handoff-2026-10-12)
- [Approved stack rank](#approved-stack-rank) and [communication expectations](#communication-and-progress-reporting)
- [Goals versus retained status](#goals-versus-status-2026-10-09)
- [Current status](#current-status-2026-10-07) and [immediate execution order](#immediate-execution-order)
- [Branch disposition](#branch-disposition-2026-10-07) and [open issue accounting](#open-issue-accounting)
- [Provider implementation queue](#provider-implementation-queue)
- [Decisions and standing approvals](#decisions-all-resolved-2026-09-30)
- [Stages 1–13: performance](#bucket-1-compiler-performance)
- [Stages 14–21: C compatibility](#bucket-2-c-compatibility)
- [Stages 22–29: platform foundations](#bucket-3-cross-platform-foundations)
- [Stages 30–37: native UI](#bucket-4-native-ui)
- [Stages 38–43: qualification](#bucket-5-product-and-release-qualification)
- [All 286 item-to-stage mappings](#appendix-every-mapped-item--stage-286-items)

## Current status (2026-10-07)

The initial reconciliation used upstream main
[`c011371b`](https://github.com/schiffy91/btrc/commit/c011371bf2cafd526348f3c6fc81f8958ddd0f9c)
(batch 50), the six initially open btrc PRs, and the remote branch inventory.
Current upstream main is `cbd3ddcd` (qualified Windows PR53 followed by
consolidated-plan/Mac-coordination PR69); the earlier integration checkpoints
below retain their original evidence. PR60 is published at `50bf1c8c`,
combining the existing integration, Weston repair, C2, REQ-10/11, rich-enum
and diagnostic corrections. Predecessor `b5e3f81a` found nine failures in
the structural audit's raw-source parser. Repair `bb40e39c` passes the expanded
155-check structural audit and Linux-target compiler transpilation; the combined
candidate completed 17,803 local tests with zero failures and 168 skips, then
failed its skip audit on two unclassified Linux-only stack-limit cases. Local
repair `8c71dda6` classifies those cases; `e497ac98` repairs the checkpoint
quiet-check omission. Their 106 focused checks pass. Local bootstrap passes;
all eight strict-C11 configurations passed 2,036 checks each with zero skips. The native Linux ARM64 bundle passes, while the hosted
benchmark reports two peak-memory regressions requiring investigation.


**Evidence boundary.** The implementation status below is a reconciliation of
source, merge history and recorded evidence, including the partial fresh Mac
matrix below. The earlier main CI, macOS and Windows workflows were green at
`c011371b`: [CI](https://github.com/schiffy91/btrc/actions/runs/37507347390),
[macOS](https://github.com/schiffy91/btrc/actions/runs/37507347352),
[Windows](https://github.com/schiffy91/btrc/actions/runs/37507347358).
Inspect individual jobs and skip reports before using a workflow as qualification;
Wayland remains report-only. Re-run required checks on every integrated candidate.

The Mac checkout was fast-forwarded from `cf28fe7` to `c011371b` during this
reconciliation. BTRSmith main remains `adb3276f`, clean, with btrc pinned to
`05ec9cb7447eeff37e57d5653425196a8a5c524c`; the Stage 4 pin and product
requalification remain outstanding. Do not copy private product sources into btrc.

**Host capacity and cleanup.** The prescribed host provenance is
`Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0`. The first October 7 check found
about 16 GiB free. The owner then authorized removal of two unused SEMU images
only if unchanged since July. Every image file was checked: newest writes were
July 21 and July 23; neither image was mounted or open. Their metadata and
65,685 regular diagnostic files were preserved in a case-sensitive tar archive,
with file contents and links verified, before the exact two images were removed.
Recovery evidence is at `~/.cache/semu/recovery/cleanup-2026-10-07/`.
The 01:45 BST recheck found **105.15 GB free (97.93 GiB)**, above the 80 GB
implementation and 100 GB Stage 23 thresholds at that moment. Recheck at each
stage start; this is not reserved capacity. The later repair-stage check found
87 GiB free; the 100 GB Stage 23 threshold must be re-established before that stage.
Completed test outputs later consumed that headroom. On October 7 at 12:31 UTC,
this session's completed C2 pytest scratch was replaced by a compressed archive
only after verifying all 121,990 entries, regular-file hashes, links, types and
modes, and rechecking the unchanged source. The archive hash and complete index
are retained beside that run; its logs and separate GUI evidence remain directly
available. Free space rose from 78.86 GB to **81.33 GB**. This preserved generated
test evidence; it did not remove additional user development data or change SEMU.
At 13:30 UTC, the same verified archive procedure preserved all 121,002 entries
of this session's completed `081aae51` pytest scratch in a 466,265,842-byte
archive. SHA-256 `4e35c810a796ba1111f1b32f900c0b68af874dbf5fdffdb9dc321aa855768e8d`
is retained with its index; free space rose from 77.97 to 80.44 GB. Separate
logs and GUI evidence remain directly available. Recheck before the next stage.

The active `podman-machine-default` is shared with SEMU: **8 CPUs, 28 GiB RAM,
180 GiB virtual disk**. It and its containers/volumes were left intact. Do not
apply the historical 40 GB btrc-machine recreation step to this shared VM.
The guest/load/quiet rules still apply even though disk headroom is restored.
A restored local full test run at plan revision `e3a6dea9` completed with
17,018 passed, 169 skipped and eight failures: four button-input timing cases
and four AppKit retention comparisons. Bootstrap did not run after that failure.
The first attempt used a stale Nix shell referencing deleted tools; the restored
shell was realized and pinned under `~/.cache/btrc/gcroots/harmonize-dev` before
the recorded rerun. No quiet performance round or final green matrix is claimed.

**Integration progress.** [PR42](https://github.com/schiffy91/btrc/pull/42)
merged at `87dd60d7c602448cdd1bcf78ab3134b772e3aed5` after review and green
docs CI. Only the accessibility findings note landed; AX trust remains unknown,
and the prototype and native qualification remain outstanding. Plan consolidation
is in [PR60](https://github.com/schiffy91/btrc/pull/60): the 153 affected reader
tests and full lint/format/generated-source checks passed locally.
[Linux CI 37554065870](https://github.com/schiffy91/btrc/actions/runs/37554065870)
passed, including 6,816 unit tests, 3,116 expected skips and zero unexpected
skips. Its macOS native bundle passed; native GUI had one activation-policy
failure late in the sanitized reference shell's 100-cycle run. Local shell
runs did not reproduce that activation failure. [PR61](https://github.com/schiffy91/btrc/pull/61)
repairs the separate button-input timing failure: all four original binaries
failed serially, and all four repaired variants passed after one deferred poll.
An independent native AppKit control reproduced the local seven private
framework survivors without BTRC and without growth over 100 cycles; the
measured comparison now replaces the older fixed allowance in `92c51bb2`.
All four local reference/self-hosted × plain/sanitized variants passed, each with
100 shell cycles, 100 independent control cycles and 100 fresh-process restores;
33 validation tests also passed. The second text-field edit now awaits actual
focus under its existing input deadline. The native macOS release bundle and
GUI job passed [run 37564440101](https://github.com/schiffy91/btrc/actions/runs/37564440101)
at this head; the hosted GUI ledger records 339 passed and 67 skipped.
Its full [Linux CI matrix 37564440031](https://github.com/schiffy91/btrc/actions/runs/37564440031)
also passed, including bootstrap and all eight strict-C11 configurations.
The local full pytest suite passed 17,038 tests with 169 skips, but its skip
audit failed on eight unexpected Apple macro checks, so bootstrap did not run.
Nix's SDK environment hid the installed required Xcode. Restoring the system
Xcode invocation exposed six Apple-only predefined names absent from upstream
clang. [PR64](https://github.com/schiffy91/btrc/pull/64) qualifies the explicit
foreign classification and system-Xcode invocation: 443 tests passed, including
all eight Apple checks and both compilers' vendor-name diagnostics; 41 Linux-only
oracle cases skipped. Full lint, format and generated checks passed. The final
integrated matrix is still outstanding.

[PR62](https://github.com/schiffy91/btrc/pull/62) adds issue #12's paired
function-temporary identity regression: byte-identical output survives repeated
builds and one or twelve unrelated functions. Disabling the existing reference
renumbering makes the test fail, proving it detects the defect. The architecture
mapping for issue #14 passed 111 structural checks. Both issues await landing.
[PR63](https://github.com/schiffy91/btrc/pull/63) integrates the historical LSP
target branch and repairs a reproduced stale-cache publication race during a
target change. All 476 LSP tests pass, including real stdio retargeting; lint,
format, generated-source checks and extension packaging also pass (83 extension
tests, two platform skips). Its final integration gates remain outstanding.

The integration candidate now merges PR35, PR61, PR62, PR63 and PR64
with this plan, preserving their histories. It also includes `186b5f7a` for
issue #16: both CLIs accept explicit `--emit-c`, preserve default output and
link plans (including real module units), and reject conflicting dump modes
before publication. All 151 CLI tests, lint, format and generated checks pass.
The combined candidate at `18185f0b` has passed lint, formatting, generated-source
checks, extension packaging and a fresh native compiler build. `make test`
passed: 17,182 tests, 161 expected skips, zero unexpected skips (159 covered
elsewhere, two uncovered), followed by the serial bootstrap's fixed point.
GCC strict-C11 `-O0`, `-O1` and `-O2` each passed all 1,982 corpus checks.
At `-O3`, both frontends' `c_compat/VariableLengthArrays.btrc` failed to compile
with `-Werror=dangling-pointer`; the other 1,980 checks passed. The gate stopped
there, before the four Clang configurations and final hygiene. Preserve
actual VLA scope/lifetime and do not suppress the warning.
The same warning now reproduces in a 20-line ordinary C11 program with an earlier
inlined VLA function and a separate main-block VLA. Removing the prior call or
making a captured bound volatile avoids it; neither is an accepted product fix.
No runtime helper or btrc lowering is needed to reproduce it. GCC tree inspection
now identifies the CCP pass inserting the main array's lifetime-end clobber
before the earlier inlined call's stack restore. Adding an explicit lexical
scope after the bound evaluation passes the strict GCC/Clang diagnostic
prototypes. Revision `1c9839cb` adds paired structured-IR lifetime scopes and
passes 53 fresh-compiler checks, including strict GCC/Clang `-O3` execution,
cleanup, loop exits, lambda captures and setjmp paths. The repair, qualified
Android lifecycle change and current plan are incorporated into the next
combined candidate `081aae51`. Its fresh lint, formatting, generated-source,
extension and native compiler-build checks passed. Its full suite ended with
17,183 passed, 161 skipped and four failures. Three failures came from the
qualification runner exporting an ancestor `--basetemp` to nested pytest runs;
the runner now supplies that option only to the outer invocation. The fourth
was a GPU assertion expecting the runtime array immediately after its captured
bound: the new lifetime block correctly lies between them. The assertion now
requires that block while retaining capacity, dispatch, strict compilation and
CPU-fallback execution checks. All 60 focused GPU and skip-ledger checks now pass. Bootstrap, all
eight strict-C11 configurations and final hygiene did not run after the failure.
All 824 native GUI evidence files were retained. No full green result is claimed. The earlier `18185f0b` combined
[Linux run 37570754386](https://github.com/schiffy91/btrc/actions/runs/37570754386)
passed all eight strict-C11 configurations, including GCC `-O3`, and all
remaining required shards. The combined macOS and Windows workflows also
passed. Their scope-skipped jobs do not supply native GUI evidence; the local
native GUI artifacts remain separately recorded. The local Darwin GCC repair
still awaits the full final gate. Android's older combined API 36 failure is
recorded below; the new `081aae51` combined Android workflow passed both APIs.
The `081aae51` hosted Wayland shard also failed after Weston aborted during
native-shell restoration. Subsequent clients reported unavailable Wayland.
The session wrapper deleted its compositor logs during cleanup; neither the
compositor abort's cause nor a repair is established. The original job log and
remaining GUI artifacts are retained. The next candidate includes `80b151ea`:
failed sessions emit the last 200 lines of their owned logs before cleanup.
The actual old/new teardown fragments were checked with real temporary files:
status and cleanup are preserved, failure tails are now retained, and successful
runs stay quiet. The two added real X11/Wayland regressions still need Linux
execution; this diagnostic change does not qualify or repair the compositor. Wayland remains report-only, with this
coverage gap explicit.
The `ad72af03` validation candidate includes the GPU assertion and
failure-log retention repairs. Its local lint, formatting, generated-source and
extension checks passed. Its full suite passed 17,187 tests with 163 expected
skips and zero unexpected skips in 1,819.62 seconds. The skip ledger identifies
161 skips covered on other runners and two uncovered Linux-native-reader cases.
Serial bootstrap passed its fixed-point test in 575.05 seconds with no skips.
All eight strict-C11 configurations, GCC and Clang at `-O0` through `-O3`,
each passed all 1,982 checks with no skips. Final plan/link/frozen-reference
and diff hygiene checks passed; the serial local matrix completed successfully.
All 824 native GUI evidence files were retained.
The native compiler binary is reused from the source-matched `081aae51` build,
not newly rebuilt. Hosted [Windows run 37588790879](https://github.com/schiffy91/btrc/actions/runs/37588790879)
passed tests and bootstrap. [Android run 37588790885](https://github.com/schiffy91/btrc/actions/runs/37588790885)
passed all 56 executions, verified from the two retained 28-case summaries.
The local gate remains pinned to `ad72af03`; it does not qualify later changes.
Its hosted Wayland shard ended with 15 failed, 195 passed and 195 skipped.
The retained compositor output identifies Weston 15.0.1's assertion at
`libweston/surface-state.c:282`, requiring a view-list rebuild when no view
may exist. The upstream fix
[`f3e30e46`](https://github.com/wayland-mirror/weston/commit/f3e30e4692f02f3d6183a3c88b5ac59c9a8b610a)
retains that assertion only for surfaces with views. Backport `5dbf80a1` applies
that exact change to the pinned source through the Linux Nix dependency and
adds a real Wayland client exercising 100 unmapped subsurface-order cycles.
Patch application, Nix syntax, Python syntax, lint, formatting and diff checks
passed. At `56909225`, the repaired hosted Wayland GUI shard passed 210
checks with 195 expected skips and no unexpected skips in 606.68 seconds;
retained JUnit and skip artifacts confirm the result. Its X11 sibling also
passed. The Linux unit shard now passes 6,916 checks with 3,116 expected
skips and zero unexpected skips, including the new standalone unmapped-subsurface
regression and all 29 headless-session cases. Its retained skip report records
CI merge revision `377666fe`; the complete Linux workflow is green. The new
regression has not been run against unpatched Weston. Other GTK/accessibility
warnings are not claimed fixed. The complete macOS workflow is now also green. Scope-skipped native-GUI
jobs remain excluded from coverage. No final integrated green result is claimed.
That broader combined tree remains pending its required gates. Windows ARM64 has since landed independently at main `49f136ec`; iOS native investigation remains open.

The pending C2 tag integration has reproduced and repaired three paired managed
union/formatting lookup omissions; 324 focused tests passed with a fresh compiler,
followed by 1,385 parser/analyzer/LSP tests. Four further regressions then proved
self-host-only acceptance of excess tagged-union initializers and incomplete
records whose names collide with generic parameters. Their lookup repairs
passed 328 tests. A separate positive case then failed
in both compilers: a generic field `T` was mistaken for a forward record `T`,
even when the explicit record was used only through a pointer. Completeness
validation now respects class and method generic scope, including tuple members.
The corrected analyzer suite passed 478 tests and a fresh paired compiler run
passed 331 tests. The broader C-compatibility/C-output run passed 1,239 tests;
three new explicit-tag refusal checks failed only because their assertions
expected uppercase `Incomplete` while the reference compiler reports lowercase
`incomplete`. Both frontends rejected the programs. The assertions now accept
the existing diagnostic capitalization; all three reruns passed. The repaired
L1 merge `d49961cb` and L2 changes are now combined with `081aae51` in
[PR65](https://github.com/schiffy91/btrc/pull/65), candidate `618e9ae1`.
Six conflicts were reconciled while retaining generic-scope, tag-ownership and
flexible-array checks. Static checks passed; the broader paired compiler,
parser/analyzer and LSP qualification ended with 2,474 passed and three failed. Both
parsers applied a struct-only spelling refusal before the existing union
refusal; the guard is now restricted to structs. Two layout expectations still
spelled `struct Pair`, although L1 normalizes that type to `Pair`; both compilers
already agreed and the native C layout checks passed. Their expected spelling
is corrected without changing the unsized-array or layout requirements. A fresh
compiler run of refusals, layouts, flexible-array checks and parser tests passed
all 360 checks. The fixes are committed as `c063cc18` and merged with `ad72af03`
in local candidate `98b88440`. Follow-up `0a332665` combines that compiler tree
with PR60's `56909225` Weston repair and the current plan; two documentation
conflicts were reconciled. Its compiler, language, runtime and stdlib sources
are unchanged from `98b88440`. PR65 is now published at `93856dfc`, combining
those repairs, the AppKit comparison described below and the current plan.
Its hosted [CI](https://github.com/schiffy91/btrc/actions/runs/37611484077),
[macOS](https://github.com/schiffy91/btrc/actions/runs/37611484239),
[Windows](https://github.com/schiffy91/btrc/actions/runs/37611484144) and
[Android](https://github.com/schiffy91/btrc/actions/runs/37611484229) workflows
are now terminal: 37 successful checks and three skipped checks. The skips are
the static job and the two native-GUI jobs; the dedicated Linux GUI
jobs passed, with Wayland still report-only. This qualifies those hosted checks
at `93856dfc`, not the later combined tree or the outstanding C2 memory and
independent-review exits.
The subsequent local candidate `1fe1dc1e` adds the qualification and
fork-safety review plan; its source owners remain unchanged. Its full local
matrix stopped at the independent AppKit control failure detailed below. Hosted
runs on the older head were deferred to respect the shared CI capacity limit;
the current publication began after the prior workflows completed. Cancellation
is not qualification. `CL-C-09` and `CL-C-13` remain open; narrow green suites do not
qualify the whole C2 merge.

**Stage 17 remains broader than PR65.** At local candidate `0a332665`, the
23 recorded rows in `src/tests/btrc/fixtures/c_compat_probe/c2.toml` include
three accepted positive cases (union declarations, flexible-array members and
union typedefs), eight rejected positive cases, nine expected rejections and
three known divergences. Typedef/anonymous-record forms, enum typedefs,
designated initializers, compound literals and bitfields remain to be implemented; enum-tag behavior
still has two recorded divergences. The remaining positive rank-2-array row
belongs to Stage 18. D19 approves these constructs; their current rejection is
an implementation gap, not a decision to refuse them. Union and FAM layout
mirrors exist, while anonymous-member layout proof follows its implementation.
The schema's historical `sizeof(Node) == 760` and +0.007% self-host peak result
are recorded in `docs/design/claude-integration-record.md`, Batch 25. The final
C2 integration still needs the memory comparison required by
`docs/design/c-compatibility.md` under a quiet host, in addition to review and
the full correctness matrix. The 360-check repair run does not prove those exits.
A read-only dry run of `tools/bench/scripts/ccompat_checkpoint.sh --memory`
exposed a qualification-helper gap: all six instruction/footprint samples run
without the required automated quiet check, although budget runs use it. Local
repair `e497ac98` wraps every sample and budget run in the existing quiet check
under the same bench lock. The check now validates the actual measured workspace:
`instr.sh` uses BTRSmith in place, while budget_bench measures its copy at the
budget output's `ws` directory. Missing or failed quiet checks prevent sampling
and a green summary. All 45 checkpoint tests pass, including executable wrapper
probes proving a refused check cannot launch its child. No measurement was run
and no earlier result is retroactively qualified by this repair.

The fresh full C2 run at `1fe1dc1e` ended with **17,431 passed, 166 skipped
and one failure** in 1,881.71 seconds. Lint, formatting, generated-source,
extension and the fresh Clang compiler build passed; bootstrap and strict-C11
stopped behind the suite failure. All 824 GUI evidence files are retained.
`test_macos_native_shell[sanitized-selfhost]` failed because the independent
public-AppKit control retained seven private objects after its first cycle and
eight thereafter: `NSTextInsertionIndicator` appears in cycles 2–100. BTRC has
no such survivor. Its probe was inactive/non-key in all cycles; the control was
active/key in all cycles. This shows an unstable control baseline, not BTRC
retention growth. Two local experiments were rejected: an extra initialization
cycle did not reproduce the active-window condition, and forced activation
failed the native gate (`303d3353`: four failures, 37 passing checks). Three
failures were control activation deadlines; the fourth was a surviving BTRC-owned
`NSTextField` in fresh-process restore 54. That provider failure remains open.

Local candidate `a696ccf4` restores the original control lifecycle and compares
each private class against its first observed positive multiplicity. A helper
may first appear after cycle one, but its allowance never increases; disappearing
and returning with more instances still fails. Unknown BTRC classes, excess
BTRC instances, owned objects and live registrations still fail. All 37 focused
checks pass, including two lazy-initialization cases that failed before the
change and two subsequent-growth refusals. Fresh native qualification at
`a696ccf4` passed all **41 checks** in 654.39 seconds: both compilers, plain
and ASan/UBSan, each completed 100 lifecycle cycles and 100 fresh-process
restores with zero provider/registration survivors. Two independent controls
actually exhibited seven private objects initially and eight later, exercising
the lazy-class comparison. Keyboard traversal and GPU focusability remain
explicit gaps. The earlier restore-54 provider survivor was not reproduced;
this successful rerun does not establish its cause or resolution. The final
full matrix remains pending.

`CL-REQ-10` (`e1bc5dfa`) remains unmerged after a blocking source review:
`BtrccCompilerStack.run` marks its parent parked before `pthread_create`, while
`ForkedWorkerPool.start` subtracts parked threads from its fork-safety count.
The child can start before the parent reaches its join. Moreover, the
[POSIX fork contract](https://pubs.opengroup.org/onlinepubs/9799919799/functions/fork.html)
restricts a multithreaded fork's child to async-signal-safe operations until
`exec`; these workers instead perform managed compilation directly. The added
fixture explicitly marks a thread parked without parking it, so it proves only
the accounting change. Replace that exemption with a safe large-stack startup
strategy and a native handoff regression, preserving the branch's 2,000-term
expression support, module-worker parallelism and collection-literal repairs.

Local candidate `226506eb` now merges that branch into C2 candidate `1fe1dc1e`
and replaces the parked-thread exemption. The compiler stays on its original
thread: macOS native/cross/bootstrap/test-cache/benchmark builds reserve a
512 MiB main stack, and Linux startup adjusts only its process-local soft limit
within the existing hard limit, diagnosing less than 64 MiB. The worker pool
again checks the actual live-thread count. The new native regression requires
one startup thread and two distinct worker processes; Linux cases check 16 and
64 MiB hard limits. A native C prototype proves the Darwin stack/fork strategy,
and Python syntax, lint/format, btrc formatting and generated-source checks
pass. Its focused run completed with **1,170 passed, three platform skips and
one naming-audit failure**. The actual Mac startup/fork regression, both deep
expression shapes and their execution tests passed; the two Linux resource-limit
cases were skipped on this Mac. The sole failure was the compiler naming audit
omitting the existing system-struct field exceptions for `rlim_cur`/`rlim_max`.
Correction `148c3f42` preserves the real C field spellings and passes all seven
naming tests. The full integrated matrix and Linux limit tests remain pending;
the local candidate is not published or landed on main.

Local candidate `e1787f9b` merges `CL-REQ-11` into `226506eb` for qualification.
Its tuple-array indexing, `sizeof` binding/retention and generic-termination
changes preserve C2's flexible-array diagnostics at the merge conflicts.
Review reproduced a false rejection in the original branch: applying `T?`
repeatedly stabilizes, but its parsed pointer layer was marked as growing.
Both compilers now distinguish that nullable layer from a growing `T*?`
constructor. Three accepting parity probes, one rejecting probe, and a runnable
nullable-cycle corpus cover the repair. All 127 analyzer-battery probes match
their expected results through the reference compiler; the new corpus also
transpiles. Lint, Python/btrc formatting, generated-source and plan/hygiene
checks pass. The fresh focused native qualification at `f3a5d3c6` now has
**1,210 passing checks and three platform skips**, including self-hosted parity.
The nine new corpus cases ran through both compilers: 16 checks passed, while
both nullable-cycle checks produced the expected `true`, `true`, `3` output but
failed the corpus runner's required `PASS` marker. Local correction `d2ffae69`
adds that marker and its golden; both checks now pass (1.55 seconds), and the
fixture formatting check passes. Compiler production sources are unchanged. The final integrated matrix remains pending;
this is a local checkpoint, not a main merge.

Local candidate `e151f6be` merges the rich-enum B/C packet into `e1787f9b`,
with a repair for writes into nested payload storage. The original branch
accepts a store through `saved.data.Held.wrapped.child` whose generated C
releases the new payload owner before its following read. Both analyzers now
follow inline struct, tuple and array projections, stopping when a projection
crosses a pointer or managed object. Four new refusal cases cover nested storage;
the existing sanitizer execution fixture also checks allowed nested object
writes. All 67 rich-enum reference checks and 127 analyzer reference probes pass;
lint, formatting, generated-source and plan/hygiene checks pass. Native parity
and sanitizer qualification at `2d645e27` completed with **328 passing checks
and one diagnostic-parity failure** in 397.84 seconds. All four allowed-flow
sanitizer cases passed through both compilers, including nested payload-object
writes. For an inferred global, self-hosted validation reported static-initializer
admissibility before the nonescaping-enum storage error. Local `2a0af4c6` checks
the nonescaping role first, matching the reference, and also includes the nullable
corpus marker fix. Native verification of this repair is included in the D/G
candidate below. A separate retry stopped before tests because its launcher
entered Nix before the simulator preflight, where `simctl` was unavailable;
that is not a compiler result. Earlier attempts stopped
at the stopped-guest preflight while the shared `semu-release-build` container
was active; it was left intact. The fresh runs began after the VM was observed
stopped, without stopping it ourselves. Neither earlier preflight stop is a
compiler-test result. The naming correction is propagated through local
REQ-11 `f3a5d3c6` and rich-enum `2d645e27`; their production sources are unchanged
from `e1787f9b` and `e151f6be`, respectively. External owner rebinding and shallow
struct escapes remain separate gaps; universal lifetime safety is not claimed.
The iOS `1844837b` branch is preserved while its idle clone hosts this checkpoint.

Local D/G candidate `cec4cc13` merges `1cc97ab8` into `2a0af4c6`. Review
reproduced a conflict with REQ-11: incoming realtime-payload recursion turned
`Chain<T>` → `Chain<(T, int)>` into “expression or declaration nested too deeply
to compile”, replacing the precise growing-specialization diagnostic. Both
compilers now retain each instantiation site's payload check and execute it
after their generic expansion has completed and growing cycles have been
refused. This preserves the original instantiation-site payload diagnostics.
All 127 reference analyzer probes, all ten realtime payload refusal cases,
and the valid payload example's reference transpilation pass; lint, Python/btrc
formatting, generated-source and diff checks pass. Native parity qualification
at `cec4cc13` completed with **1,159 passes, 20 failures and three skips** in
661.15 seconds. The B/C ordering repair and valid realtime payload example passed
through both compilers. Nineteen failures came from REQ-11 generic-growth errors
still using direct combined-position printing. The remaining test expected the
constructor's line 35 instead of the invalid field's line 33; inspection also
found that self-hosted validation pointed at `public` rather than the type.
Local `9a01104c` routes generic-growth and nesting-limit errors through the
source diagnostic owner, points the invalid SPSC payload at its type, and pins
its full line/column identity. Analyzer parity now checks file-local lines even
with stdlib imports. Ruff, full btrc formatting and diff checks pass. With a fresh compiler, the
same native suite passed **1,179 checks with three platform skips** in 625.74
seconds, resolving all 20 prior failures. The skips are Linux resource-limit
and `/dev/full` paths. A combined candidate now includes this repair, PR65
`93856dfc` and the current plan; its production sources match `9a01104c`.
The combined tree is published in PR60 at `1424c2db`. Its local lint,
formatting, generated-source checks, extension and native compiler build passed.
The full run then stopped at boundary verification: the accepted lexer/parser
stderr fixtures still expected terse diagnostics. Both captured outputs are
byte-identical to the reference, preserving the original messages, source
locations and exit status 1 while adding the positioned source line and caret.
Under D14, only those two accepted artifacts and their reviewed manifest hashes
are updated (43→206 and 42→149 bytes); all frozen baseline bytes and 311 records
remain unchanged. Regressions cover lexer/parser diagnostics and cross-file
position parity. Rechecking the preserved current capture passes **287 records**;
24 observed-behavior records remain unchecked because four managed-code
capabilities are incompatible with this environment. All **13 boundary-manifest
checks pass**. The full matrix remains pending. The old `build/boundary-report.json`
predates this failed run and is not fresh evidence.
Main-suite, bootstrap and C11 checks did not run at `1424c2db`. The reviewed
correction is published as `b5e3f81a`; a new full serial run has started, reusing
the production-source-identical compiler binary. Its lint/format/generated and
extension checks passed again, and fresh boundary capture passed 287 checks with
24 unchecked records. The main local suite completed with **17,664 passed,
nine failed and 168 skipped** in 1,916.83 seconds. All nine failures are in the
structural audit: its helper feeds raw `#if` lines inside the new startup method
to the parser, bypassing the required conditional-preprocessing stage. Bootstrap
and C11 did not follow the failed suite; 824 native GUI evidence files are retained.
Hosted Linux release, btrc, C11, ARM64 bundle and X11 jobs reject the
Linux-only startup expression `limit.rlim_max != (rlim_t)RLIM_INFINITY`:
the left C field is opaque and cannot precede an ordered sibling without an
explicit type. The release source position maps to `cli/Driver.btrc:1906`.
The first local cast repair, `d941f74d`, was insufficient: `rlim_t` remains opaque
to the analyzer, so its explicit comparison was rejected as an aggregate operation.
Repair `bb40e39c` performs the bounded arithmetic in `unsigned long long` and
converts back to `rlim_t` at the system boundary, preserving the 512 MiB request,
hard-limit clamp and 64 MiB refusal. It also routes structural parsing through
`SourceConditionals` for every target from the shared manifest, caching identical
conditioned programs. All **155 structural checks pass**, as do lint and formatting.
The complete strict-import, no-cache Linux-x64 compiler entry transpiles successfully
through the reference compiler. This check runs on macOS and does not establish
native Linux execution; the Linux hard-limit cases and release build still must pass.
The hosted bootstrap job also stopped at boundary capture, with empty self-host
artifacts; that result does not establish a bootstrap fixed point. Hosted checks
must qualify the eventual corrected head;
older-head cancellation is not success. Merge resolution preserves
C2's union admission logic in the shared realtime owner and its union refusal
regressions. The intentional positioned-diagnostic boundary update retains
311 records and its reviewed SHA-256. No main landing or full-matrix
qualification is claimed yet.

| Area | Implemented / integrated evidence | Remaining acceptance and next action |
|---|---|---|
| Stages 1–4 | Pre-flight history, Stage 2 fixes, measurement harness and extensive stdlib drift repairs landed. Daemon failures were races/zombie handling, not a deadline to relax. | Disk headroom restored; finish Mac and BTRSmith requalification and pin; reconcile residual findings before closing Stage 4. |
| Stages 5–13 | Runbook kit, reference attribution and never-merge floor experiments prepared. M11 self-host budget numbers were met at `65057cb`. | Quiet current-source baseline; Stage B skip-unchanged acceptance counter; reference budgets, worker scaling, finals and x86_64 evidence. No new final-performance claim. |
| Stages 14–16 | C5 inventory, C1 schema/constructs and C4 integrated; C1 Linux evidence recorded. | Outstanding Mac memory/instructions and BTRSmith evidence do not disappear because implementation landed. |
| Stages 17–21 | C2 schema and shared owners landed; declaration-order parity landed separately. | C2 L1/L2 reviews still have blockers; multidimensional arrays, C3, goto and final inventory closure remain. |
| Stages 22–25 | P0 inventory, platform shell, target schema/owner, extractor, and target data model through `CL-P1-05` integrated. Windows host hardening merged in batch 42. The LSP target repair and Android host are qualified individually and included in PR60's combined candidate. | Land the combined gate; finish hosted ABI availability, target-aware readers/link plans/provider/cache isolation. iOS has a green local matrix but awaits its pinned hosted lane; Windows ARM64 native bootstrap remains unqualified. |
| Stages 26–29 | Interop ownership design exists; HTTP and Windows service revision-5 drafts contain the reviewed corrections. PR52's latest lost-ACK outcome clarification passed static CI. | Complete PR51/52 contract review, then implement checked service/interop providers and qualify actual target ABIs and dependency closure. |
| Stages 30–33 | UI catalog and macOS/Linux shell evidence landed; UI1 checkpoint recorded (batch 46); UI2 contract approved (batch 47). Linux X11 GUI/audio shard landed (batch 50). | Port independent repairs first; land UI2 interface and both providers atomically. Mac keyboard delivery and Wayland sanitizer evidence remain gaps. Other platform shells remain incomplete. |
| Stages 34–37 | Drafts, model/accessibility spikes and fixtures exist. | Reviewed feature contracts and real providers; per-platform slices may advance when their own prerequisites work. No blanket all-platform qualification claim. |
| Stages 38–43 | CI tiers and host workflows exist; a workflow that skips a missing host does not prove it. | Installed-product journeys, numeric budgets, physical/listening sessions, signing/account-dependent releases and final candidate gates remain open. |

### Recorded performance and coverage baseline

At `65057cb`, self-host edit medians were 9.62 / 9.69 / 9.31 s, cold transpile
43.57 s, cold dev 59.76 s, no-op 2.92 s, touch 2.91 s, peak 2.966 GiB and
aggregate 4.828 GiB. These are historical measurements. M11 remains open until
one body edit analyzes and lowers exactly one changed source group and the
complete matrix qualifies it. M8a's 40 s transpile row was not met.

Self-host finals remain transpile ≤10 s; cold dev ≥10× and
≤min(20 s, frozen baseline/10), working budget **13.5 s**; cold release ≤30 s;
edit ≤5 s (p95 ≤8 s); batch ≤30 s; peak ≤1.5 GiB. Reference finals remain
transpile ≤60 s; cold dev ≤75 s; edit ≤10 s (p95 ≤15 s); batch ≤60 s;
peak ≤1.5 GiB. D11 governs measured revisions, not silent target deletion.

The source boundary manifest has **311 records**. The historical 309-record,
12,439-passed/172-skipped and 8×1,934 results belong to older revisions; they
are not today's counts. The current architecture inventory is **88 Python /
97 btrc files**. `targets.toml` now carries **11 rows**, not six independent
target vocabularies. Frozen UI denominators and later releases/amendments stay
versioned; do not flatten retired or unavailable rows into passing rows.

## Immediate execution order

The [approved stack rank](#approved-stack-rank) is the active ordering. This
section is a handoff procedure for an authorized executor, not a fixed assignment
to this document's author or a claim that old runs remain active.

1. **Establish the actual starting point.** Check current main, relevant branch
   heads, live claims and existing results for the selected outcome. Reconcile
   old "running" and "next" notes before relying on them. Reuse completed work;
   do not restart an inventory, broad audit or Stage 1 merely because a new agent
   or model takes over.
2. **Choose the highest-value feasible platform outcome.** Follow ranks 1–5,
   explaining the rank, affected platforms and tangible result. Remove a blocking
   correctness defect, or implement an independently ready stdlib, GUI or product
   capability. Missing Windows/mobile capabilities deserve direct implementation
   attention; unrelated Mac/Linux polish and optimization must not consume the
   queue by default. Confirm actual prerequisites rather than treating historical
   stage ordering as a blanket gate.
3. **Implement and prove the bounded change.** Choose an appropriate decomposition
   and useful independent review. Reproduce defects where applicable, fix their
   actual owner, and verify meaningful behavior on the affected targets through
   the required compiler/native matrix. Preserve shared contracts and existing
   qualification requirements. Report a genuine dependency immediately and
   continue another valuable independent slice where possible.
4. **Integrate continuously and demonstrate the result.** Reconcile branch
   dependencies, qualify the exact combined tree and land through the authorized
   integrator. Advance the BTRSmith pin and affected application journeys as their
   required providers qualify. Keep target-tested, merged and product-available
   states distinct; do not call unmerged evidence delivered on main.
5. **Report and choose again.** Update capabilities, blockers, revisions and
   evidence against the stack rank. State what advanced, what did not, and why
   the next action is useful. Performance-only work is rank 6, except for the
   demonstrated functional-blocker rule in the owner update. Preserve every
   numeric target and required final gate while making that scheduling choice.

The executor determines the implementation path within these priorities and
current authority. Use the [agent guidance](#ultracode-recommendation) to size
independent work; parallelism never overrides file ownership, host constraints,
required review or native evidence. A new plan edit is not itself an instruction
to launch an implementation wave.

## Completion contract

Completion of the owner's goal includes correct compiler/library operation, the
required native GUI capabilities and BTRSmith journeys on all five platform
families, followed by the retained full qualification and performance targets.
An individual qualified platform slice may be integrated before that whole goal
is complete. A macOS/Linux MVP alone does not satisfy the five-platform scope.

A branch is integrated only after its intended behavior is present on main and
its required checks pass there. A superseded branch needs a recorded replacement
or semantic comparison. An issue closes only when its acceptance is demonstrated,
with evidence linked to the resolving commit. Experiments retain their nonshipping
status. Required final gates are `make test`, `make bootstrap`, `make test-c11`,
lint, format-check, generated-source, extension, structure/hygiene and
`git diff --check`, plus affected BTRSmith and native-provider checks. Follow the
host locks and serial memory limits. Never mark unavailable physical, listening,
account or platform evidence as passed.

## Branch disposition (2026-10-07)

The remote snapshot contains 183 branches: 151 tips are ancestors of main and
32 are not. These are initial dispositions, not completed reviews. Local legacy
branches must also be checked before deletion; nothing is deleted by this plan.

The later integration branches are tracked separately from that frozen inventory.
These rows retain historical qualification receipts as well as current heads;
the detailed status above names the active candidate and later failures. PR60
`50bf1c8c` and PR65 `93856dfc` are exact ancestors of PR68 `6f1b81d9` with zero
unique commits relative to it. They remain open until qualified integration.
PR34 `f49c5fe1` still has 13 unique commits and its iOS host files are absent from
PR68; it requires separate reconciliation and hosted acceptance.

| Integration checkpoint | Current head | Qualification / remaining work |
|---|---|---|
| PR60, `codex/harmonize-plan` | `50bf1c8c` | Predecessor `b5e3f81a` completed with 17,664 passes, nine structural-audit failures and 168 skips. All nine are resolved by the expanded 155-check target-conditioned audit; Linux-target reference transpilation passes after the arithmetic repair. The combined run completed 17,803 passed, zero failed and 168 skipped in 1,863.14 seconds; the skip audit then failed on two Linux-only hard-limit cases, stopping before bootstrap/C11. Local `8c71dda6` adds narrow macOS classifications: 61 ledger checks pass and the retained report reclassifies with zero unexpected skips. Local `e497ac98` repairs quiet measurement orchestration; 106 combined focused checks pass. The combined local tree `a8d92cb8` has passed lint, formatting, generated-source and extension checks, and passed bootstrap in 594.69 seconds with zero skips. All eight strict-C11 configurations (GCC and Clang, -O0 through -O3) passed 2,036 checks each without skips. The serialized remaining-gate run finished successfully, including the plan and diff checks. This resumes the remaining gates; it is not a fresh full make test result. Neither repair is published yet; full final qualification remains pending. |
| PR65, `codex/integrate-c2-arrays` | `93856dfc` | Published with the AppKit comparison repair and plan. All hosted workflows are terminal: 37 successful checks and three skipped jobs (static and two native-GUI jobs). The source-matched AppKit run passed 41 tests, but the earlier restore-54 owned-field survivor remains unexplained and full integrated qualification remains open. |
| Local REQ-10/11, rich-enum and Apple availability integration, `codex/integrate-rich-enum-diagnostics` | `ba6c221d` | Apple schema and pinned tables passed 186 focused checks plus static/generated checks; semantic consumers and final integration remain open. Before `bb40e39c`, parent `9a01104c` passed 1,179 native checks with three platform skips. The first Linux cast attempt failed; the revised integer arithmetic and all-target structural audit pass their focused checks and full Linux-target reference transpilation. The earlier REQ-10/11 and rich-enum changes are integrated into the combined candidate; the Apple merge is now included in `06c3923a`; full qualification/main landing remain pending. |
| PR53, Windows ARM64 host | Merged main `49f136ec`, tested head `110a514c` | All five workflows and native ARM64 compiler/bootstrap/sample plus MSVC ABI/wgpu checks pass. Merged tree equals tested tree; archive checksum verified. Broader provider and combined-tree gates remain separate. |
| PR68, compiler and Linux GUI integration | Published `6f1b81d9`; hosted merge `e10d8bab` has the same tree | Reviewed scheduling and bounded GCC launch diagnostics pass 109 focused checks. The new full matrix and explicit native-GUI run `37835919865` are active. Previous `00e45379` Linux/Windows/ARM64/Android passes remain historical; its Mac unit rerun failed six actual GCC launch ENOENT cases, and native-GUI failed lease admission before the GPU test body. Current exact-tree gates, skip classification and main integration remain open. |
| PR34, iOS host | Published `f49c5fe1`; local `1844837b` | Local 50-case matrix passed. Hosted launch completed zero fixtures; iOS 17 floor and final hosted acceptance remain open. |

At `50bf1c8c`, the [native Linux ARM64 release job](https://github.com/schiffy91/btrc/actions/runs/37623566727/job/112799636879)
passes archive construction, checksum, relocatable stdlib discovery and compilation
and execution of its strict-C11 fixture. The [benchmark job](https://github.com/schiffy91/btrc/actions/runs/37623566727/job/112799636710)
fails two peak-memory checks: BenchCollections rises from 22,134,784 to 23,195,648
bytes, and CompileStdlibHeavy from 44,789,760 to 45,895,680 bytes. Both exceed the
existing 1 MiB minimum allowance, by 12,288 and 57,344 bytes respectively. All
emitted-C size/line/parity comparisons pass. The benchmark's GitHub merge commit
`01b70d67` has exactly the candidate's tree, so this is source-matched evidence.
The original log and artifact are retained. The first repetition request was
rejected while the workflow was still running. After it finished, one unchanged-
source benchmark repeat completed at attempt 2,
[job `112835659915`](https://github.com/schiffy91/btrc/actions/runs/37623566727/job/112835659915),
with two memory failures. CompileStdlibHeavy reached 45,993,984 bytes, exceeding
the allowance by 155,648 bytes; it fails both attempts. RunDispatch reached
19,017,728 against a 17,924,096-byte baseline, exceeding the allowance by 45,056
bytes. BenchCollections passed the repeat at 22,917,120 bytes. Artifact
`11490775379` retains the repeated measurements at the same merge revision;
size, line and parity checks still pass. No further unchanged rerun is requested.
Keep the baseline and tolerances unchanged while isolating the growth. The
cause remains unproved and is independent of the local quiet-helper omission.
A source-pinned Mac comparison of `93856dfc` and `50bf1c8c` prepared the retained
clang-built binaries for three alternating pairs of the stdlib-heavy workload.
The automated quiet check refused the host, so the owned runner was cancelled
before any sample to release the gate for independent work. No instructions,
footprint or timing result was produced; no quiet rule or system setting changed.
The source snapshots, binaries and cancellation record are retained. This remains
an unexecuted diagnostic, separate from Linux peak-memory qualification and the
outstanding C2/BTRSmith acceptance measurement.

The completed Linux btrc shard at `50bf1c8c` passed **5,850 tests with 34 skips**.
Artifact `11486902534` confirms both native hard-stack-limit cases passed: the
launcher refuses 16 MiB and succeeds at 64 MiB. Its workflow metadata pins the
same source revision. The hosted macOS btrc shard passed 5,838 tests with 46 skips,
then failed solely on those two Linux-only skips lacking a macOS classification;
local `8c71dda6` supplies the narrow fix already exercised by the 61 ledger tests.
The Linux workflow's first attempt finished with only the benchmark failing.

PR65 `93856dfc` and PR60 `50bf1c8c` have both completed their hosted workflows.
PR60 finishes with 35 successful checks, three skipped jobs and two failures:
the benchmark and the macOS btrc skip audit described above. The last macOS unit
job passed 9,924 tests with 127 skips; retained artifact `11491321670` pins the
same merge tree. Neither candidate occupies a running wave now. Recheck actual
queued and running workflows before publishing another candidate; the allowance
remains at most two code candidates.
Cancellation and scope-only jobs are not qualification. No branch is deleted.

The C4 branch comparison is complete: `db229df7` and main ancestor `245cc209`
have the same full Git tree, `87666402b8638440ed04dff17664de955fb16c48`.
This proves that the branch's entire snapshot landed, including its paired
compiler implementation and tests, despite different commit ancestry. Main
then received integrator fixes in `914ad585`. No branch deletion or new
qualification claim follows from that source comparison.

| Branch | Head | Disposition / next proof |
|---|---|---|
| `codex/cx-p1-03` | `958d309b` | Active PR; exact remaining acceptance is in the provider queue below. |
| `codex/cx-p1-04` | `55a71b8c` | Active PR; exact remaining acceptance is in the provider queue below. |
| `codex/cx-p1-05` | `628a4a54` | Active PR; exact remaining acceptance is in the provider queue below. |
| `codex/cx-p2-01-r2` | `d77b4b14` | Active PR; exact remaining acceptance is in the provider queue below. |
| `codex/cx-p2-02-r2` | `0fa4c093` | Active PR; exact remaining acceptance is in the provider queue below. |
| `codex/cx-uia-11-e40-repro` | `bbe4f56e` | Pair the reproduction with CX-STDLIB-01; do not introduce a knowingly failing normal gate. |
| `codex/cx-uia-12-spike` | `47f381f9` | Preserve evidence/prototype; integrate findings or reviewed production port only. |
| `codex/cx-uib-06-spike` | `156353a5` | Preserve evidence/prototype; integrate findings or reviewed production port only. |
| `codex/cx-uib-07` | `6d62e046` | PR42 findings note merged at `87dd60d7`; prototype stays separate and native AX evidence remains unavailable. |
| `codex/cx-uib-07-spike` | `0d6127a6` | Preserve evidence/prototype; integrate findings or reviewed production port only. |
| `evidence/cx-uia-11-e40-repro` | `bbe4f56e` | Preserve evidence/prototype; integrate findings or reviewed production port only. |
| `integ/b17` | `fce184b6` | Superseded by main ancestor `9f33d2c3` (UI parallel plan): all 449 packet IDs, owners, stages and roadmap assignments retained; 434 packets identical, 15 revised for dependency, ownership and qualification corrections. Preserve WIP history without replay. |
| `integ/b20` | `c6fe3a6b` | All three changed files are byte-identical to main ancestor `ce886ee4`: catalog implementation, tests and README. Already landed; preserve the historical branch without replay. |
| `spike/stage6-composed` | `9ae0d17a` | Keep as nonshipping Stage 6 floor experiment; measure and port qualified changes, never merge the spike. |
| `spike/stage6-decl` | `1d546c26` | Keep as nonshipping Stage 6 floor experiment; measure and port qualified changes, never merge the spike. |
| `spike/stage6-instances` | `a3f96e46` | Keep as nonshipping Stage 6 floor experiment; measure and port qualified changes, never merge the spike. |
| `spike/stage6-parse` | `8a8733cd` | Keep as nonshipping Stage 6 floor experiment; measure and port qualified changes, never merge the spike. |
| `spike/stage6-records` | `88f82de0` | Keep as nonshipping Stage 6 floor experiment; measure and port qualified changes, never merge the spike. |
| `spike/stage6-visibility` | `8107ae1f` | Keep as nonshipping Stage 6 floor experiment; measure and port qualified changes, never merge the spike. |
| `stage16/c4-python` | `db229df7` | Already represented on main: its complete tree is identical to `245cc209`; later paired review fixes landed at `914ad585`. Preserve the historical branch; do not replay it. |
| `stage17/c2-l1` | `4ef167af` | Preserved through merge `d49961cb`, with generic/tag scope, native-tag and LSP repairs, then combined in PR65 and PR60. PR65 hosted checks passed at `93856dfc`; independent review, quiet-host C2 memory comparison, combined-tree gates and main landing remain pending. |
| `stage17/c2-l2` | `2e65f7c6` | Preserved in PR65 and PR60 with declaration/shadow and callee-first repairs; `c063cc18` reconciles union diagnostics and aggregate layout expectations. The 360-check focused repair run and PR65 hosted workflows pass. Independent review, quiet-host C2 memory comparison, combined-tree gates and main landing remain pending. |
| `stage18/req-ui2-bc-rich-enum-payloads` | `6ad62d2f` | Integrated through local `9a01104c` with nested payload-store repair. Native sanitizer cases passed at `2d645e27`; its inferred-global diagnostic ordering repair passed in the broader `cec4cc13` run. Final integrated qualification and owner-rebinding/shallow-struct gaps remain open. |
| `stage18/req-ui2-dg` | `1cc97ab8` | Merged locally at `cec4cc13`, with realtime checks deferred until finite generic closure. All 20 diagnostic failures are resolved in `9a01104c`, whose native suite passed 1,179 checks with three platform skips. Final integrated matrix remains open. |
| `stage18/req10-parity-gaps` | `e1bc5dfa` | Integrated with safe main-stack startup replacing the parked-thread fork exemption. Native single-thread startup/two-worker handoff and deep-expression parity passed in the recorded REQ-10 run; naming repair `148c3f42` and later integration are retained. Linux hard-limit paths and final matrix remain open. |
| `stage18/req11-tuple-sizeof-recursion` | `271397d3` | Integrated through local `9a01104c` with paired finite-nullable-cycle repair. Native focused run at `f3a5d3c6` passed 1,210 checks; the two corpus marker checks passed at `d2ffae69`. Final integrated matrix remains open. |
| `stage24/apple-standin-extraction` | `7b3d1195` | Contains the standalone Apple evidence workflow and extractor provenance option, neither present in PR60. Review any production port separately; its Xcode 16.4 results remain stand-in evidence. Pinned Xcode 27A266a/SDK 27.0 re-extraction now passes for all four Apple targets at source bb40e39c, with 23 extractor tests and the namespace/stand-in comparison passing. Five functions and 22 macros become declared per row, with no newly unavailable names. This is header evidence; the schema is included in local candidate `06c3923a`, while semantic consumers and runtime qualification remain pending. |
| `stage24/apple-standin-extraction-run` | `9c0d737d` | Its tree differs from `7b3d1195` only by the four-line scratch push trigger for this run branch. Preserve its evidence; never merge that trigger. Any reviewed workflow port must come from the base extraction branch without this scratch change. |
| `stage24/hosted-abi-platform-targets` | `8df5d732` | CL-P1-08 schema-3 candidate includes four Apple tables explicitly sourced from Xcode 16.4/SDK 15.5 or 18.5 and a conservative MSVC copy awaiting runner extraction. Wait for CL-P1-06 and qualified inputs, then review schema/generation parity. Local merge `ba6c221d` replaces the four Apple rows with verified Xcode 27A266a/SDK 27.0 extraction and preserves the newer generic-depth limit and all preexisting manifest sections. Generator resolution, regeneration, pinned-source tests and actual self-host table parity passed: 186 checks plus lint, format and generated-source gates. The contract spot check now uses clock_settime instead of the incorrect fork assertion. This merge is now included in local combined candidate `06c3923a`, whose fresh build/static/generated checks pass, but is not yet published; MSVC runner extraction, semantic consumers and the final combined matrix remain open. Header declarations do not prove runtime support. |
| `stage24/hosted-platform-fragments` | `10203072` | Keep as extractor evidence/input only; consume validated data in the hosted-ABI owner, never merge the fragment branch. |
| `stage24/hosted-platform-fragments-apple-standin` | `c9dad69a` | Keep as extractor evidence/input only; consume validated data in the hosted-ABI owner, never merge the fragment branch. |
| `stage24/lsp-target` | `3aef3988` | Preserved by the real merge into PR63 (`8f964c1b`), with the stale-cache race repaired and 476 LSP tests passing, including actual stdio target changes. Included in PR60; await its combined gate and main landing. |

## Open issue accounting

The initial October 7 inventory covered 17 then-open btrc issues. Resolved rows
remain here with their evidence; this is not a count of issues still open.
The table assigns review work and does not infer resolution from an old title
or merge. Retrieve each issue’s current acceptance before changing or closing it.

| Issue | Subject | Route |
|---|---|---|
| [#20](https://github.com/schiffy91/btrc/issues/20) | CoreAudio: duplex open with a closed-lid built-in mic fails 'audio stream format is unsupported' and its cleanup never completes | Runtime/concurrency regression and native gate |
| [#18](https://github.com/schiffy91/btrc/issues/18) | Feature: analyzer-level pruning of stdlib bodies and a 'stdlib strict' CI mode | Stages 5–13: source-bound performance/acceptance evidence |
| [#17](https://github.com/schiffy91/btrc/issues/17) | Feature: implement or drop the reserved keywords (override, goto, auto, register) | Paired compiler regression and relevant C/IR stage |
| [#16](https://github.com/schiffy91/btrc/issues/16) | Feature: btrcc -o <file> and --emit-c, instead of C on stdout | `-o` landed at `d7f24d73`; current generation publication stages C, units and link plans with recovery/atomicity coverage, and btrcc still defaults to stdout. Explicit `--emit-c` now lands in this integration candidate at `186b5f7a`; 151 CLI tests pass, covering byte-identical default/named/module-unit output and conflict rejection before publication. Await final gates and main integration before closure. |
| [#15](https://github.com/schiffy91/btrc/issues/15) | Tech debt: macOS native tests cannot run in the dev shell (nix cc-wrapper vs Xcode 27 SDK, no FreeType, no libasan) | Resolved by native Apple compiler/SDK routing and provisioned FreeType; restored local checks pass (see evidence below). |
| [#14](https://github.com/schiffy91/btrc/issues/14) | Tech debt: two architecture contracts (test_lowering_architecture.py vs test_compiler_structure_contract.py) encode the same rules differently | PR60 adds the shared rule-to-check mapping and module-change procedure in [compiler structure](https://github.com/schiffy91/btrc/blob/3974d47bc87851b1ac19b8d2b4bd5022f2d94676/docs/design/compiler-structure.md#mapping-the-two-architecture-contracts). The original mapping passed 111 structural checks; the later target-conditioned audit passes all 155 checks at `bb40e39c`. Final integrated qualification and main landing remain pending. |
| [#13](https://github.com/schiffy91/btrc/issues/13) | Tech debt: reference and self-host emit different C (runtime helper layout, ~1000 lines on small programs) | Resolved by shared runtime order and the pinned full-C identity sample at `362a43b7`; 776 cases pass. |
| [#12](https://github.com/schiffy91/btrc/issues/12) | Tech debt: emitted C depends on temp numbering through the 1000-character wrap rule | Main already contains per-function numbering at `8549ddd6`. PR62 adds the paired whole-function byte-identity regression at `777cc4cc`, including unrelated lowering and a mutation check that detects disabled renumbering. Included in PR60; final integrated gates and main landing remain pending before issue closure. |
| [#11](https://github.com/schiffy91/btrc/issues/11) | Threaded lifecycle fixture fails under host load: destructor exception during final drain escapes the joiner | Main includes fixture-ordering repair `8333e10a`: the worker waits until the spawner has released its captures. Closed after independent forced-schedule proof through both frontends and GCC/Clang: old variants drain on the joiner and fail; repaired variants drain on the worker and pass, including 80 old failures and 80 repaired passes under eight CPU-load processes. The runtime contract was already correct; the fixture ordering was defective. |
| [#10](https://github.com/schiffy91/btrc/issues/10) | Self-host optimizer never sweeps unreferenced function-pointer typedefs (reference does) | Resolved on main by `f6edfdd1`; 776 full-C identity cases pass (see evidence below). |
| [#9](https://github.com/schiffy91/btrc/issues/9) | Incremental floor: 2–5 second edit-to-run loop for BTRSmith | Stages 5–13: source-bound performance/acceptance evidence |
| [#8](https://github.com/schiffy91/btrc/issues/8) | Content-addressed build cache for transpiled modules | Stages 5–13: source-bound performance/acceptance evidence |
| [#7](https://github.com/schiffy91/btrc/issues/7) | Per-module translation units with parallel C compilation | Stages 5–13: source-bound performance/acceptance evidence |
| [#6](https://github.com/schiffy91/btrc/issues/6) | Reduce compiler self-overhead on AST traversals (ARC traffic, arenas, borrowed walks) | Stages 5–13: source-bound performance/acceptance evidence |
| [#5](https://github.com/schiffy91/btrc/issues/5) | Whole-app-scale compile benchmark fixture and gate | Stages 5–13: source-bound performance/acceptance evidence |
| [#4](https://github.com/schiffy91/btrc/issues/4) | Lazy analysis of unreached stdlib bodies | Stages 5–13: source-bound performance/acceptance evidence |
| [#3](https://github.com/schiffy91/btrc/issues/3) | Epic: sub-minute clean builds for BTRSmith | Stages 5–13: source-bound performance/acceptance evidence |

### Verified issue resolutions (2026-10-07)

- **#10:** main includes `f6edfdd116d024148e237058311c3871fff2d9c5`,
  which replaces struct-only pruning with keep-set closure over all six typed
  declaration groups. It also includes the stronger whole-C identity gate in
  `src/tests/btrc/test_c_output_parity.py`, introduced at `362a43b7`:
  all **776 corpus programs** passed at `e3a6dea9`, with no skips. This compares
  the complete translation unit, including types, using only checkout-path
  normalization; temporary numbering is not masked. Both issue requirements
  are present on main and verified, so #10 is resolved.
- **#13:** `362a43b7a35645972552aab7e8437e7fef1c7eba` puts both
  runtime catalogs and materializers on the same dependency-first order and
  adds the pinned whole-C identity gate. Its current 776-program sample passed
  in the same run. Byte identity is enforced for every manifest member; removing
  one requires a reviewed manifest change. This resolves the issue's runtime
  order and corpus-sample contract requests, not every remaining corpus mismatch.
- **#15:** the same restored Nix-shell run passed **172 native-import tests**
  and all **eight FreeType setup/snapshot variants**, including both compilers
  and sanitizer modes. Apple fixtures route through `/usr/bin/clang` and the
  selected Apple environment; the shell provisions FreeType. The initial stale
  Nix store references were repaired by realizing/pinning the development
  profile. The eight remaining full-suite failures were the separately tracked
  GUI input/retention cases, not native SDK/linker/FreeType environment failures.
  Independent GCC/LLVM sanitizer-probe skips remain explicitly in the skip
  ledger and are not claimed as executed coverage.

These results are retained in the local full-suite test ledger and
`~/.cache/btrc/plan-consolidation-2026-10-07/issues-10-15-evidence.json`.
The full suite still requires the repaired final-tree run; these issue-specific
resolutions do not claim whole-repository completion.

## Provider implementation queue

All items below retain their original packet IDs and acceptance. Claims remain
in WORKSTREAMS §3.3. Select work by the October 12 stack rank and actual technical
prerequisites; old queue order and session-specific assignments are retained
context. Establish the executing agent's current integration authority separately.

## Goal and ownership

Deliver usable btrc standard-library providers on Linux, macOS, Windows,
iOS/iPadOS and Android. BTRSmith may verify a library feature, but app migration
and caller-count documentation do not gate unrelated stdlib repairs.

The ordinary Codex lane owns provider implementation, dedicated regression
drivers/fixtures and its platform test-host tools; the ordinary Claude lane owns
the compiler pair, shared specs/generators/runtime/readers and integration.
D29 authorizes this session to combine those responsibilities for the requested
harmonization. Both queues live here, and one writer holds a file at a time.
A current-interface repair may start independently of the
larger future packet that originally named the file. Check active claims first;
carry any shared-data changes as integrator fragments. Public API changes still
need explicit contract review and coordinated provider validation.

This owner update supersedes older scheduling clauses that make these repairs
wait for BTRSmith, documentation reconciliation, future widget contracts, or all
five native shells. Each new platform slice starts when its own demonstrated
prerequisites are ready. Missing native evidence remains missing; simulator,
emulator and hosted results never become physical-device qualification.

## Why the queue changes

The provider queue separates current-interface defects from future UI features.
Preserving the 4,097th input event, clamping scroll offsets after resize and
retaining explicit button alignment do not need BTRSmith caller reconciliation
or all five native shells. Real target/ABI, cache-isolation and callback-lifetime
requirements still block the dependent platform slice.

Batch 47 approved the UI2 interface/provider landing contract. Use
[ui2-approved.md](docs/design/ui-contracts/ui2-approved.md) instead of the earlier
stacked packet's contradictory bootstrap wording. Reviewed interface readiness
and acceptance of the combined interface/provider tree are separate milestones.
A blocked slice does not stop independent work, and passing counts from an old
unpublished revision do not qualify a new port.

## First delivery queue

These are small repair units extracted from the named older packets, not claims
that those entire future milestones are complete. Check live path claims before
opening each implementation branch. The first three unpublished revisions below
were reported by the earlier cloud session. Their original commit objects are
unavailable in the checked local clones, and no retrievable recovery bundle has
been verified. `CX-STDLIB-03` has since been reconstructed and tested as recorded
above; `01`/`02` have now been reconstructed into `2202c0bd` with their
fixture-only red checkpoints preserved. Their historical commit objects remain
unavailable; current native qualification must establish the reconstructed
behavior. Publish reviewable commits and rerun their tests; old results do not
qualify a reconstruction. Independent repair units must not wait on this recovery.

| Unit | Outcome and scope | Starting evidence | Remaining acceptance |
|---|---|---|---|
| CX-STDLIB-01 (from UIA23) | Retain queued input; match popup hit testing to painted position; preserve text/selection on clipboard Cut failure; honor external hide/show rendering | Historical `d6df2cb6335e122526204f0408602aeef6d31b66` is unavailable locally and remotely; its 84-case record does not qualify reconstructed code. E40 `bbe4f56e` recovered; current reconstruction `42d5a7c1` has 80 native cases, static checks pass, execution pending | Execute preserved fixture-only red and reconstructed green through the normal driver, both compilers and sanitizer/control cases on final source; catalog: a new `evidence/ui2-linux-e40.toml` shard plus the E40 hunk in `cases/E25-E47.toml`, carried per WORKSTREAMS §3.3 step 4 ([catalog README](docs/design/native-ui-catalog/README.md)) |
| CX-STDLIB-02 (from UIB26) | Grid and both Stack orientations invoke child layout so scroll offsets clamp after resize | Historical combined `0f6f3448967720480365d43980c74baf7280b7e4` and resize fixtures are unavailable; its 40-case record is historical. Reconstructed `364a2bd6` changes three child-layout dispatch calls and adds 12 native cases; static checks pass | Execute fixture-only red `366da1cd` and repaired green with both compilers and sanitizers; verify actual pixel/offset behavior and fixture discovery |
| CX-STDLIB-03 (from UIB18) | Explicit Mac button alignment survives title/symbol updates; defaults preserved | Original `f6071c8a` unavailable; reconstructed in PR66 (`4f5c9b30`). Actual AppKit red: four failures; corrected integration `37a8ae67`: four passes through both compilers, plain/sanitized | Hosted branch checks pass; the final combined-tree gate and main integration remain. Focused native proof and retained intermediate failure are recorded in the packet report |
| CX-STDLIB-04 | Reject an invalid Linux grid replacement without losing the old child | Reviewed source `47e64e21`, fixture-only red `36b47db5`; after paired compiler fix `808592c9`, all four native rows pass through Python/self-host, plain/ASan/UBSan, and all four genuine negative controls fail the intended old-child identity assertion | Final combined-tree gates/main integration remain. Green execution proves rejected replacement retains identity/pixels, same-child no-op, valid replacement/null clear and cleanup; negative controls compile/link successfully and have no sanitizer diagnostic |
| CX-STDLIB-05 | Keep scrollbar geometry valid in a tiny viewport and at large finite content extents | Reviewed provider `6720fc0b`, final admission checkpoint `e3281e6e`; fixture-only parent `7c060d08` preserves the native red candidate. Formatting, discovery and import checks pass (10 checks); four Mac platform skips are classified with no Linux allowance | Run the dedicated actual pixel/pointer/wheel regression through both compilers and sanitizer variants on Linux, including zero/tiny track and `1e308` content. Mac skip admission is not native Linux evidence. No executed native failure/pass or main landing is claimed yet |

### Repair files and test admission

The combined Linux `01`/`02`/`05` candidate is preserved at `2202c0bd`.
It passes 31 source/fixture/import audits. All 96 Mac skips are admitted only by
exact platform/test patterns; replaying the real skip owner verifies 96 expected
rows on each Mac lane, 460 negative mismatches per lane and rejection of all 96
rows on Linux. There is no Linux skip allowance or native Linux result. The
prepared qualification uses four immutable fixture-only red checkpoints and the
96-case green tree, one inspected container image and one source-matched Linux
compiler. The original container lacked actual Xvfb and Mesa renderer outputs.
A task-owned incremental image from the exact pinned source now passes native
admission with Xvfb, live X11/DBus, Mesa 26.1.5 lavapipe, SDL 3.4.10 and wgpu
27.0.4.0. The shared image and guest configuration are preserved. Its immutable
image is `f68b039191ea`; the actual native compiler build passes on Linux ARM64,
using GCC 15.2 at `-O2` (not the separately installed Clang). Existing
`btrcc-release-c-linux` passes: both Linux LP64 rows emit byte-identical C;
the paired functional baseline also passes. Compiler binary SHA-256 is
`9037c9ba483dcf7affa21c4de99d694e37d6846c111e8b0afa45caee66b68033`.
The first actual Grid04 attempt fails all four rows, with zero skips, at strict-C
compilation: inherited `IApplication` signatures refer to pruned `IButton`,
`IStack`, `IGPUView` and other interface types. The same reference-compiler
failure reproduces on current `71a22734`. This is a compiler defect, not native
Grid acceptance. The original 96 rows and intended fixture-only red runs have
not executed. Reviewed paired repair `808592c9` adds the missing interface-parent
reachability edge in the two existing lowering owners; it does not weaken
pruning or change the emitter. Fixture-only `72be5947` records three failures and
eight passes; repaired reference closure/strict-C execution records ten passes.
The fresh Linux ARM64 self-host build now passes, followed by LP64 target-row
identity, paired functional baseline and **11 regression passes, zero skips**
(including strict-C execution through both compilers). Grid04 then executes
**four native passes, zero skips**, plain and ASan/UBSan through both compilers
with actual pixel and ownership assertions (129.72 seconds). Binary SHA-256 is
`1739f6b16838694fa52297379f431777238ed8a01ec24577fc51ca7d9b07c505`.
Source-inventoried qualification composites retain each original provider tree
and identical repaired compiler inputs; all original archives/failures remain.
The genuine Grid negative controls now execute: all four compile/link successfully
and abort at the intended `IGrid_childAt(grid, 0, 0) == previous` assertion in
`verifyCell`, with no sanitizer diagnostic (130.43 seconds). Their receipt is
`rows/grid-red/native-red-classification.json` beneath the repaired evidence root.
The first 96-case attempt stops at fixture setup because its boolean conditional
expression promotes to int under both compilers' existing numeric rules.
Fixture-only `2e82334d` replaces that one expression with equivalent lazy if/else
branches. Thresholds and assertions are unchanged. Both frontends reject the
original expression; both repaired strict-C executables pass 96 truth and lazy
evaluation combinations. That proof is `frame-progress-proof-808592c9/result.json`.
The corrected native 96-case suite passes **96 cases, zero failures, errors or
skips** (783.61 seconds); its original setup failure remains retained. Together
with Grid04 this supplies 100 actual Linux ARM64 provider passes through both
frontends, plain and ASan/UBSan. The E40 counterfactual uses the
same corrected fixture/observer ABI with original `5299b7a8` production behavior,
whose only relevant green delta is the 4096-event dequeue boundary. It produces
exactly **32 intended native failures and 32 control passes** (136.47 seconds):
4097/8193-event inputs expose loss at boundary 4097 while work and frame progress
remain live. All at/below-4096 controls pass; no setup error, skip or sanitizer
diagnostic is accepted as an intended failure. Remaining input/layout/scroll
negative controls are running. Receipts are in `rows/green96-fixed/` and
`rows/event-fixed-red/native-red-classification.json`.
The original build took 470.21 seconds and its required target-row comparison
241.46 seconds; these are preparation elapsed times, not benchmark measurements.
The source repair requires a fresh build/comparison, while the image and SDK
provisioning are reused. Recoverable archival of completed,
unopened September benchmark caches freed 4.85 GB; post-provision free space was
84.955 GB, above the unchanged 80 GB gate. Logs, source and binaries are retained. A fifth repair, Grid child
replacement, is preserved at `47e64e21` with fixture-only parent `36b47db5`: it
validates the new child's lifecycle/parent/cycle conditions before detaching the
old child. Its four native rows test rejected replacement retaining identity and
pixels, valid replacement, null clear and ownership cleanup. Source review and
static checks are clear; native green behavior and genuine fixture-only negative
controls pass as recorded above, while final integration remains pending. Minimize/
restore and final X11/Wayland acceptance remain separate. UI2 macOS and Linux
provider implementation has started independently on preserved branches, using
the approved interface and existing completion hook; native qualification and
atomic interface/provider landing are still required. Six macOS UI2 foundation
fixture types now pass real-SDK reference transpilation and 20 strict-C/Objective-C
syntax checks on a source-inventoried private binding composition. They have not
yet linked or executed, and no paired native UI2 acceptance is claimed. Linux's
publisher foundation reference-transpiles with its real SDK at `818e9ee0`; later
queue, text and lifecycle source work still requires fresh qualification.

CX-STDLIB-01 production files are
`src/stdlib/GUI/Linux/{LinuxApplication,LinuxSelect,LinuxTextField,LinuxWindow}.btrc`.
Recover the event fixture under `src/tests/native/gui/linux/` from retained E40
commit `bbe4f56e9a462002bb8d96df4bc7c7d1bed4a6f3`. Reconstruct the unavailable
popup, clipboard and visibility probes under `src/tests/native/gui/ui2/probes/linux/`.
Move the recovered collector into `src/tests/python/test_native_ui_linux_spike.py`
with the established platform, native-reader and display guards; remove the old
collector to avoid duplicate unguarded collection. The historical `spike`
spelling does not relax acceptance.
Its catalog update is the new `docs/design/native-ui-catalog/evidence/ui2-linux-e40.toml`
shard plus the E40 hunk in `docs/design/native-ui-catalog/cases/E25-E47.toml`.

CX-STDLIB-02 owns `src/stdlib/GUI/Linux/{LinuxGrid,LinuxStack}.btrc`, reconstructed
`src/tests/native/gui/layout/linux/{LinuxGridScrollResize,LinuxStackScrollResize}.btrc`
fixtures and `src/tests/python/test_native_ui_layout_resize.py`. Grid and both
Stack orientations must invoke the child view's layout override; ScrollView
already owns offset clamping. Recovering the historical combined repair failed
in the hub, active/parked clones and exact GitHub object lookup; do not repeat
that search or treat its old passing counts as evidence for this reconstruction.
CX-STDLIB-04 follows this unit because both edit LinuxGrid; reserve any needed
LinuxViewNode validation change explicitly. CX-STDLIB-05 owns LinuxScrollView and
its dedicated fixture/driver, independently of the grid writer.

CX-STDLIB-03 owns `src/stdlib/GUI/MacOS/MacOSButton.btrc`,
`src/tests/native/gui/controls/macos/ButtonAlignment.btrc` and the narrow fixture
registration in `src/tests/python/test_native_gui_appkit.py`, coordinated with any
active AppKit harness writer.

The Linux driver names already match the normal native-GUI target's selection.
Keep the fixture-discovery guard active. These repair units include their test
admission work; shared expected-skip data still travels as a reviewed integrator
fragment with actual node IDs and capability reasons. No Makefile or workflow edit
is needed for these Linux drivers. Do not publish a known-red normal gate or hide
an unwired fixture. Old passing counts do not validate a newly ported tree.

## Platform slices beyond the repairs

| Platform | Next concrete checkpoint | Actual dependency and evidence |
|---|---|---|
| Windows | Wire and qualify the actual Toolhelp/process thread-count provider | Candidate `3e02deba` passes all 155 paired checks and all four genuine SDK imports through reference/selfhost for x64/ARM64, with exact paired C/plan equality. The original pointer and function-signature defects are repaired. Provider/fixture candidate `25b5b572` includes manifest wiring; actual checks pass generated-source validation and 17 contracts but expose unused enum-tag selections in native bindings. The provider selection is corrected in `e5ec3cf5`; the fixture selection remains under repair. Both-frontend fixture projection, strict Windows C build and real x64/ARM64 execution remain unqualified. |
| iOS/iPadOS | App-private file create/write/read and relaunch persistence through both frontends | Actual iOS target/provider/cache selection, required nongeneric Foundation ownership/calls, filesystem seam and a real Xcode simulator host. Full UIKit widgets are not prerequisites for this service. |
| Android | NativeActivity host execution, then app-private file create/write/read and relaunch persistence | NDK/SDK, correct target/provider selection, trusted host-derived roots, filesystem seam and emulator execution. Initial private roots need not wait for the complete Java UI/JNI stack. |
| Each mobile GUI | Lifecycle, one native button and one editable field with events and safe teardown | Checked UIKit/main-executor adapters on iOS; checked JNI/Looper/callback ownership on Android. GPU embedding and richer collection controls are subsequent milestones. |

The October 9 Toolhelp prerequisite uses the installed genuine Zig 0.16.0
MinGW-w64 SDK (1,610 pinned headers), the selected reader and 273 Clang resource
headers. The uninstrumented `6f1b81d9` compiler is authenticated to its successful
build and exactly matches `5aa232ad` compiler/spec/runtime/stdlib/codegen inputs.
All four imports terminate at the same pointer-macro rejection in 3.66 seconds;
all six command groups close, source/tools stay unchanged, and no C compile, link
or Windows process runs. Independent audit is clear for that limited finding:
`windows-toolhelp-current-5aa/results/baseline1/independent-audit.json`, SHA-256
`4192c100734175f01f17becdabd818606c48fd4855b65bb4927d68af7e66fde2`.
The historical eight-case qualified-function rejection remains a separate record
whose artifact locator has not been recovered; this fresh earlier rejection does
not reproduce it. The next repair must preserve typed native semantics rather
than skipping the sentinel check or inventing another provider ownership model.

The typed pointer-constant repair is implemented in isolated candidate
`414db329` on `codex/native-pointer-constants`, based on exact `5aa232ad`.
Its shared ASDL, SDK reader and paired importers/analyzers preserve pointer type,
target-width value identity, SDK spelling and value-only provenance. Unified
catalog generation and checks pass with exactly two derived catalogs changed;
all other 4,505 files remain exact. Generation audit SHA-256:
`46c2b0b2c268340fb7e376df2741e74f8016b7b394adc1100f8b611c7c57711e`.

The original locked Clang 21 build inputs were restored (71.8 MB); the updated
reader builds, installs and passes unchanged fixup checks. Initial build attempt
one compiled but failed because output was nested in its temporary build root;
R2 separates the directories without disabling fixup. All six groups closed,
source/tools remained exact, and the successful reader audit is
`33cc979a9fbbf72bbaf4cbecda2153bb4da82b6999ba6e64aba7159ac0dcb681`.

Reference attempt two passed 35 macro checks but 21 new direct-header checks
stopped on the fixture's `#pragma once` warning, before their metadata assertions.
Fixture-only commit `de4009d9` replaces that pragma with an include guard, retaining
all declarations and strict diagnostics. Attempt three authenticates every one
of the other 4,506 files as identical to the reader build. It passes all 99
reference checks (56 macro and 43 codec), with no skips/errors/xfails/xpasses.
The genuine x64 Toolhelp import now advances beyond the original pointer-macro
rejection and fails at `native function semantics do not match its signature`.
ARM64 was not reached in that attempt. Seven owned groups closed, all inputs
and outputs matched. Independent attempt-three audit:
`57720140e26c7323bc30b0c88783eef6d93eb79f61128b6e18e87ccc7dbc3375`.

Actual SDK documents captured for both targets subsequently identify the defect:
all six selected functions on each target have a neutral qualified wrapper over
a function, with matching parameter counts and the default calling convention.
This is current raw-document evidence, not a claim to recover the historical
eight-case artifact. Raw-document audit:
`69b7942b6462b1c3914a44cef89da3953d1188623295a012445d9a123028390d`.
Candidate `b04309d8` removes only neutral Clang sugar in the reader; meaningful
qualifiers, nullability, typedef identity and calling-convention rejection remain.
The original Clang 21 recipe builds it successfully. Five exact restored inputs
are protected by temporary task-local GC roots through qualification; no system
settings or toolchain version change. Reader build audit:
`4c8f1a259f5ebc6af8a007f8c23974797ea8e81d8b775d21ede4dd83cbb221a4`.

The completed reference qualification reproduces both old-reader failures at the
exact bare-function assertion, then passes all 103 candidate cases (58 reader/
macro and 45 codec), with zero skips, errors, xfails or xpasses. Genuine x64 and
ARM64 Toolhelp imports both produce C and correct target plans without diagnostics;
the C preserves actual SDK types and sentinel names. All ten owned process groups
close, with exact source, tools, SDK, readers and retained outputs. Result SHA-256:
`fa626924fe4b313dc15585e2b19a84fd492160f3cb3edfb7dac2e65b523458a4`.
Independent audit SHA-256: `bb63f5bd14688616daf520344941029e753e80e1f50dc0dacf20f77350c6f809`.
The fresh MacOSMain self-hosted compiler now builds with the original Clang 21
strict-C11/O2 recipe. Paired qualification executes all 155 selected cases:
92 codec and 62 macro cases pass, while one const-discard diagnostic comparison
fails. Both frontends reject the invalid conversion and publish no output;
the reference compiler uses its established generic assignment diagnostic and
the self-hosted compiler its established const-depth diagnostic. The four genuine
SDK projections are not reached. Result SHA-256:
`2516f6ed5cf6b8d9c518bcb90c71d8703ae5aee460665e3bc9f2f97b647be3b6`;
independent audit `6fab672a4567a1a0b12f8572e431ec618d88e9e02b524be14f9005b603d46f7a`
verifies exact inputs, all 155 identities, retained outputs and eight closed groups.
The narrow fixture correction `3e02deba` now requires each frontend's exact
established diagnostic and compares imported constants with ordinary same-type
const pointers, retaining all six rejection and no-output checks. Production
compiler bytes are unchanged. The corrected run authenticates and reuses the
fresh binary, then passes all 155 paired checks and all four genuine SDK imports
with empty diagnostics and byte-identical C/plans per target. Result SHA-256:
`a32d159f2e60807cfed9d36073630fac1f0cd8ef41dff29742e684152eae503a`;
independent audit `09b252f0e23e39c1115cbea02fe6e1810d3cc891aa35692b099d71dd9fd47948`
verifies 79 static pins, nine tools, 183 dynamic inputs, exact three-file test/report
delta, SDK/resource inventories, 22 logs and 11 closed groups. This establishes
paired Windows SDK projection, not native Windows link/runtime behavior.

The actual ProcessThreads provider and native fixtures are committed through
`25b5b572` and independently source-reviewed. It uses genuine SDK declarations, checks returned record extent
before owner-PID access, resets dwSize per call, filters the current PID, guards
count overflow and attempts exactly one handle close while preserving enumeration
errors. Public count()/minus-one behavior and Windows worker pools are unchanged.
The final manifest fragment and real-thread/fault fixtures are present. They check
three held threads and restoration, real foreign-process records, snapshot errors,
short records and cleanup. Overflow remains structurally checked. The explicit
driver preserves emitted C through two authenticated project-header VFS mappings;
actual projection now runs, while VFS lookup, strict native build and Windows
execution remain pending. Both bounded attempts pass generated-source validation
and all 17 provider/manifest/index contracts. The first x64 reference projection
rejects an unused `BtrcThreadEntryExtent` enum tag; source `e5ec3cf5` removes only
that selected name while retaining the exact SDK offsetof/sizeof expression and
constant. The fresh attempt reaches the fixture and rejects its unused
`ProcessThreadFault` tag. Neither run reaches C/plan output; the other three
projections remain unrun. The second attempt closes all eight process groups and
leaves source/tools unchanged. First audit:
`7ec99e4ff1a74750ec8d2d98deeedc5f7ca6009801526061310886a31945386b`.
The remaining fixture selection is corrected in 0799ae3d, with no change to
headers, enumerators, error cases or native assertions. Fresh attempt 3 passes
generated-source validation, all 17 contracts and all four SDK projections with
empty diagnostics and byte-identical paired C/plans. Result
ad9b798d0af36b895b56a6b673ae3e783263b99e780afd6bfc03d6e18d2b0bff
and independent audit
30083d132418900e735b1c78e2b4857252401a6d7c51a71af9381f2b79662ae4
verify 283 inputs, 4,514 source files, 4,618 workspace entries and 11 closed
process groups. The emitted provider retains the SDK-derived extent, overflow
guard and error-before-close order. Strict Windows build and native execution
remain the next acceptance. The original 17+4 denominator and bounds are unchanged.
A separate driver-only follow-up `bd50f377` reuses the established Job Object
process runner and native executor for process cleanup, PE/hardware validation
and retained raw results, preserving provider/fixture/header bytes and 180/90-second
limits. Repository-config formatting and independent source review passed; actual
native execution remains pending. The original
WindowsMain SDK-scanning process-composition gap remains explicit; supported-host
projection followed by actual Windows x64/ARM64 execution must be distinguished
from claiming SDK scanning on a Windows-hosted compiler.


Reuse the existing stdlib shell fixture as a small conformance app: window,
button, editable field, scrolling, clipboard, visibility and teardown. Attach
real platform adapters as they become executable. A plain C SDK probe or mock is
useful evidence for its limited purpose, not a delivered btrc provider.

The retained Android host in [PR35](https://github.com/schiffy91/btrc/pull/35) forks
C fixtures and excludes JNI/ART and arbitrary threaded-provider safety. Add a
proper in-process provider mode before general callback/audio tests. The iOS host
in [PR34](https://github.com/schiffy91/btrc/pull/34) now enters `UIApplicationMain`
and runs its C fixture on a worker after delegate setup. Its 50 local native
passes cover this test host, not UIKit scene, widget or callback-provider
conformance. Neither host proves completed mobile GUI support.

## Validation and progress reporting

- Use the repository's Nix environment for edit/test loops, actual SDL/X11/Wayland
  on qualified Linux hosts, both compiler frontends and appropriate sanitizer
  checks. On this Mac, follow AGENTS.md's locks and load rules; gates run from
  clones outside Drive, and bootstrap runs alone.
- Build a source-matched compiler after compiler changes. Run focused red/green
  regressions during development and the required static/unit/integration gates
  on the final candidate. Preserve ordinary fixture discovery and skip accounting.
- Use native Mac/Windows/emulator hosts for OS behavior. A Linux-only lane cannot
  claim Apple simulator execution, and an Android lane without KVM cannot claim
  accelerated emulator evidence. This session has qualified local Apple
  simulator execution and hosted Android KVM runs as recorded below. D29
  authorizes the workflow repairs needed for integration; ordinary provider
  lanes retain their assigned ownership boundaries.
- Batch meaningful corrections. The former four-push limit must not strand a
  verified repair; retain measured CI concurrency limits and avoid redundant
  dispatches. A busy hosted queue does not block independent local work.
- Report **implemented**, **locally tested**, **natively tested**, and **merged**
  separately. Every blocker names the smallest failing program/missing API, its
  owner and the next milestone it prevents. Never stop unrelated platform work
  merely because one prerequisite or approval is pending.
- D29 authorizes this harmonization session to integrate; ordinary lane work still follows the shared claims and gate protocol. Keep
  strict imports, structured IR, generated-source discipline, both-compiler parity,
  reviewed shared contracts and source-bound native evidence.

## Provider handoff at the consolidation snapshot

Reconciled against main `c011371b` and the six open PR heads on 2026-10-07:

- Mac evidence [PR54](https://github.com/schiffy91/btrc/pull/54) and
  [PR56](https://github.com/schiffy91/btrc/pull/56) merged in batch 36; Linux
  diagnostics [PR57](https://github.com/schiffy91/btrc/pull/57) merged in batch 38.
- Windows host hardening [PR58](https://github.com/schiffy91/btrc/pull/58), head
  `6ec9b9dc`, merged in batch 42 with 16 native cases passing on each of x64 and
  ARM64. This is execution infrastructure, not a Windows GUI provider.
- HTTP [PR51](https://github.com/schiffy91/btrc/pull/51), revision 5 `799c9de5`, and
  Windows services [PR52](https://github.com/schiffy91/btrc/pull/52), revision 5
  `6866eb3d`, address the round-4 findings. The earlier revision had green docs
  CI; the latest clarification also passed its static check. Contract
  review and implementation acceptance remain separate, as detailed below. That does not block unrelated Linux repairs.
- Windows ARM64 toolchain [PR53](https://github.com/schiffy91/btrc/pull/53), mobile
  hosts PR34/35 remain open with their individual acceptance/dependency gaps,
  listed in the next section. Reuse these branches; do not duplicate their tools
  or describe them as finished providers. Accessibility
  [PR42](https://github.com/schiffy91/btrc/pull/42) subsequently merged as a
  findings note at `87dd60d7`, without native qualification or prototype code.
- The six Linux repairs and Mac alignment repair above remain unpublished
  experiments. Their existing regression wiring proposals and frozen evidence
  are retained; normal integration and current-source validation remain to do.

## Active assignments carried from WORKSTREAMS (D28)

These assignments moved here from WORKSTREAMS.md and the old packet files in
batch 40. Old packet IDs stay for traceability; WORKSTREAMS.md §3.3.2 keeps the
path claims. Each entry names its source (a PR, branch or review comment), the
owner, the exact prerequisite and the next acceptance.

- **PR58, `CX-P1-06` Windows host hardening: integrated in batch 42** (main
  `2ca3ca56`; Claude added four tests that fail when its fixes are reverted).
  Next, owner Codex, before `CX-P1-07`: the follow-ups in the PR58 closing
  comment. First, `execution_workspace`'s bare `shutil.rmtree` loses the
  read-only retry, so a target that leaves a read-only file leaks its temp
  directory. Second, the duplicate overflow note. Third, `check.py`'s relocated
  bundle cleanup. The marker-file and digest-to-launch gaps are for `CL-P1-17`.
- **`CL-P1-17` target runner, executor protocol 1** (batch 7, `4df25c53`;
  the protocol is frozen in the `src/tests/target_runner.py` docstring). It
  closes both gaps above in the protocol: `prepare(bundle_dir, label)` is
  atomic and launches a private staged copy whose digest it checked, the
  outcome comes only from the OS process status, and no control file sits
  in or above the program's working directory. The registry imports
  `tools.target_hosts.<platform>.executor` (a `TARGET_EXECUTORS` mapping or
  the matching class), so no runner edit is needed. Owner Codex, to adopt it:
  - `CX-P1-07` (Windows): honour `label`; read `bundle.json` rather than the
    `manifest.json` view; stage a private copy instead of re-hashing just
    before launch; move the `control` directory and `status.txt` out of the
    program's reach, and stop letting a missing marker decide the outcome.
  - `CX-P1-09` (Android): make `prepare` atomic (it sets `bundle` and
    `programs` before validating); read `bundle.json` and supply its own
    supervisor instead of expecting one in the bundle; move shell mode's
    stdin, stderr and status files out of the program's cwd. Construction
    already works through `--executor-option sdk=… --executor-option serial=…`.
  - `CX-P1-08` (iOS): rename cwd policy `temp` to `isolated`; take
    `launch_mode` per request rather than from the constructor; read
    `bundle.json` instead of `btrc.ios-testhost/1`; move the status and
    identity files out of the cwd's parent; report `provenance["app_roots"]`.
  - Still open for the runner itself: caches stay off until `CL-P1-15`; no
    executor is granted `loopback-listener`; the inventory's `corpus.*` rows
    still cite `runner.py::test_btrc_file` rather than the runner's own
    record ids.
- **PR53, `CX-P1-03` Windows ARM64 toolchain** (`codex/cx-p1-03`,
  merged main `49f136ec`, qualified head `110a514c`). Owner: this authorized integration session. The final five workflows and actual ARM64 native proof pass; the historical diagnosis below remains retained.
  Main `87dd60d7` is merged into the branch; the tooling now uses the shared Windows Job/gate, target
  flags, PE parser and build-process owner. The overall native deadline,
  component-qualified Visual Studio discovery and separate developer-command
  diagnostics are implemented, and `windows-arm64.yml` is present.
  [Run 37560567746](https://github.com/schiffy91/btrc/actions/runs/37560567746)
  passed the Linux cross-build and native MSVC/wgpu probe: MSVC 19.51.36260,
  SDK 10.0.26100.0, Clang 22.1.8, strict-C11 hello, instance creation and adapter
  callback (adapter present). Native tooling passed 22/23 checks; the Windows
  missing-executable diagnostic omitted its filename. The repair preserves the
  executable identity alongside the OS error; 190 tests and eight subtests
  passed locally. The earlier failed tooling step prevented compiler/bootstrap
  execution. [Run 37564453309](https://github.com/schiffy91/btrc/actions/runs/37564453309)
  passed the repaired tooling, Linux cross-build and MSVC/wgpu probe, then
  failed in the native Zig 0.16.0 C build with `0xC0000005` and empty stderr.
  Python transpilation completed; no native-built btrcc or bootstrap result
  was produced. Retained source and exact command identify the failing tool;
  its crash cause still needs native diagnostics rather than a relaxed gate.
  Native and cross builds used byte-identical generated C (70,724,834 bytes).
  Revision `347dca91` adds verbose compiler output and bounded read-only Windows
  crash/capacity diagnostics, preserving the original failure; 192 tests and
  eight subtests passed locally. [Run 37567934632](https://github.com/schiffy91/btrc/actions/runs/37567934632)
  passed cross-build, native tooling and MSVC/wgpu but timed out in the native C
  build at 3,600 seconds. The host diagnostic exited zero with empty output, so
  no capacity/crash evidence was obtained. `d07d8ba9` rejects an empty diagnostic
  report, uses a UTF-16LE encoded PowerShell command, and adds an actual Windows
  Job/CIM regression before expensive compilation. Its portable suite passed
  27 tests with one native-only skip; lint/format/diff checks passed.
  [Run 37576400208](https://github.com/schiffy91/btrc/actions/runs/37576400208)
  failed at the new report test: encoded PowerShell still exited zero without
  JSON; the expensive compiler step did not run. Revision `9480f89f` launches
  targets with `CREATE_NO_WINDOW` through the existing detached Job-owned gate,
  preserving explicit streams and descendant cleanup. Its local Python 3.13
  process suites passed 116 tests and eight subtests, with one native-only skip;
  lint/format/diff passed. [Run 37578721489](https://github.com/schiffy91/btrc/actions/runs/37578721489)
  passed the actual native Job/CIM report regression and all 28 tooling tests,
  establishing the PowerShell repair. The run then failed in the deadline probe
  and MSVC setup because a captured `stderr` file remained locked
  (`WinError 32`). Native compiler/bootstrap did not run. Revision `7cb3770b`
  separates capture from disposal, retries only sharing violations for at most
  five seconds, and preserves the original result and capture path if disposal
  still fails. Fault-injection and process suites passed 119 tests and eight
  subtests, with one native-only skip. The exact original lock holder remains
  unproven. [Run 37581720184](https://github.com/schiffy91/btrc/actions/runs/37581720184)
  passed cross-build, all 31 native tooling tests, deadline/PowerShell checks
  and native MSVC/wgpu. Its C compiler again exited with `0xC0000005` and empty
  stderr; native btrcc execution and bootstrap did not run. The generated C
  hash is unchanged. The valid host report records about 12.8 GiB free physical
  memory after the failure and no matching crash event, without proving peak
  memory or the cause. Revision `f2476cc2` adds a small strict-C11 ARM64 build
  and stdout/stderr execution check through the same Job before the full build,
  plus elapsed command timings. Local process suites passed 122 tests and ten
  subtests with one native-only skip; lint, formatting and diff checks passed.
  [Run 37584587972](https://github.com/schiffy91/btrc/actions/runs/37584587972)
  passed both version probes, 34 native Python tests and the separate MSVC/wgpu
  lane, but the tiny C build crashed with `0xC0000005` in 0.158 seconds, with
  empty stderr. Compiler transpilation and bootstrap never began; the large C
  input is not required to reproduce this failure. Published revision `0423088d`
  adds bounded failure-only driver, syntax, object, link and overlay diagnostics
  without replacing the original qualification failure. Its local process
  checks passed 124 tests and ten subtests, with one native-only skip; lint and
  formatting passed. [Run 37589160851](https://github.com/schiffy91/btrc/actions/runs/37589160851)
  passed the cross-build and separate MSVC/wgpu lane, but the tiny native build
  failed again with `0xC0000005` after 0.164 seconds. Minimal target object
  generation and compatibility-overlay preprocessing passed. Driver-plan,
  explicit-target syntax and minimal linking failed with `0xC0000005`;
  default-target syntax returned `3221225642`. All failing diagnostics retained
  empty stdout/stderr. The CI merge revision is `ac003239`; the evidence narrows
  the failure without proving its cause. No full compiler transpile or bootstrap
  began. Inspection of the verified Zig 0.16.0 source showed that these first
  three diagnostics still selected link mode: forwarding `-###` and
  `-fsyntax-only` does not change Zig's default output mode. Revision `06870dfc`
  adds `-c` to isolate those frontend probes and adds a verbose object compile
  to distinguish diagnostic-output handling from linking. The focused evidence
  suite passed 35 tests and ten subtests, with one native-only skip, before and
  after the change; lint, formatting and diff checks passed. Native
  [run 37595036759](https://github.com/schiffy91/btrc/actions/runs/37595036759)
  passed the cross-build and separate MSVC/wgpu lane, but the original GNU
  probe still crashed with `0xC0000005` after 0.162 seconds. The actual CI merge
  checkout is `5cfee395`. Object generation and overlay preprocessing passed.
  Driver-plan and default-target syntax now exit 1 with `FileNotFound` after
  compile-only operation; that does not establish that the existing input is
  missing. Explicit-target syntax, verbose object compilation and linking still
  crash. The verbose object probe retained 10,395 bytes of Clang command and
  include-search diagnostics, with no stack trace. No full compiler execution
  or bootstrap began, and the crash cause remains unproved.
  Diagnostic `53da5fd0`, now published to PR53, adds a bounded child debugger
  after an access violation, recording fatal exception addresses and loaded
  modules. It follows only its newly launched process tree, retains
  kill-on-debugger-exit and the existing Windows Job, and has a 20-second inner
  deadline with a 30-second outer deadline. Portable validation passes 130 tests,
  one native-only skip and ten subtests, plus lint/format checks. Native crash
  evidence is pending run 37651593291; no crash cause or Windows acceptance is
  inferred from portable tests.
  The prior local collection abort was reproduced as Apple's libffi trampoline
  assertion. Darwin runtime repair `2e8e3711` now passes an actual ctypes callback,
  46 build-safety tests and CFFI's 1,888 checks. The first resumed Windows command
  then exposed a verification-command error: clearing pytest addopts removed
  importlib collection. Restoring the repository's import mode produced the
  passing portable run; it required no product-code change. Both failed attempts
  and the successful qualification are retained. This runtime repair is local
  in the integration candidate and still requires final combined-tree gates.
  The qualification command, pinned toolchain, Job containment and deadlines
  are unchanged; diagnostic success cannot turn the original failure green.
  Updating this existing PR stays within the two-active-code-PR allowance.
  Remaining acceptance: byte-identical three-stage native bootstrap and C
  from cross/native compilers, plus the complete native lane on the final head.
- **PR34, `CX-P1-04` iOS simulator test host** (`codex/cx-p1-04`,
  published head `f49c5fe1`, local candidate `1844837b`). The `host-ios.yml` workflow landed in batch 43 under `REQUEST(CL-R-38)`; that infrastructure is present, while hosted fixture execution remains unqualified. Main `87dd60d7` is merged into the branch. The UIKit app entry now has a responsive
  main loop and a fixture worker, with terminal publication arbitrated across
  threads. All twelve app bundles compile/sign with the local iOS SDK; local
  process tests pass (25 tests and 36 subtests). These are not simulator proof.
  The earlier plain-entry run passed 37/50 executions. The subsequent
  [run 37560529912](https://github.com/schiffy91/btrc/actions/runs/37560529912)
  passed all thirteen iPhone app cases and two iPad spawn cases, then failed
  on launch/identity deadlines and simulator cleanup. It used Xcode 16.4 with
  the available iOS 26.2 runtime. Root cause and complete acceptance remain
  open; the UIKit change has not qualified the whole matrix. Revision
  `532d4e45` adds bounded read-only simulator diagnostics and retains failure
  stages and partial results independently of cleanup. Its hosted run
  [37567969350](https://github.com/schiffy91/btrc/actions/runs/37567969350)
  passed all twelve iPhone spawn cases but failed the other three modes on
  launch/identity deadlines. Diagnostics record 7 GiB RAM, three CPUs, heavy
  memory compression and device-list queries timing out. Host pressure is a
  supported hypothesis, not a proven cause. The same revision and unchanged
  fixture binaries passed all **50 executions** on the acceptance Mac, Xcode
  27A266a and iOS 26.4.1 (23E254a), without changing deadlines. Both app modes
  proved fresh containers including the repeat, cleanup completed and both
  owned simulators were verified shut down. Retained manifests include fixture
  hashes and per-case results. Revision `7e31fdb2` selects GitHub's standard
  `xcode-27` runner and `/Applications/Xcode_27.app/Contents/Developer`, rejecting
  any Xcode build other than D21's `27A266a` before compiling fixtures. The
  [published image inventory](https://github.com/actions/runner-images/blob/main/images/macos/xcode-27-arm64-Readme.md)
  lists that build and iOS 27.0. The image is a public preview; the new hosted
  [run 37572123758](https://github.com/schiffy91/btrc/actions/runs/37572123758)
  failed in preparation with zero fixture executions: `xcodebuild -version`
  timed out at 30 seconds in both iPhone modes and iPad spawn; the final iPad
  app mode timed out in `simctl list` at 60 seconds. One owned iPad shutdown
  also timed out. Retained diagnostics confirm a 7 GiB/3-CPU runner, memory
  compression and stalled simulator queries. Pinning Xcode alone did not repair
  hosted execution. The older Xcode-16.4/iOS-26.2 failures remain recorded;
  changing toolchains does not establish their cause. The iOS 17 runtime floor
  is still unqualified. Revision `f49c5fe1` captures and caches Xcode provenance
  before simulator creation/boot. The stateful command-order regression failed
  against the previous ordering and passes after the repair; toolchain failure
  also proves no device mutation. The full local suite passed 26 tests before
  the second focused case was added, then both preparation cases passed. Lint,
  format and diff checks passed. [Run 37579929097](https://github.com/schiffy91/btrc/actions/runs/37579929097)
  passed tooling, local host tests and fixture builds, then failed all four
  modes on the first fixture's launch/identity deadline: zero of 50 executions
  completed. The iPad spawn mode also failed shutdown cleanup. Only iOS 27.0
  was available, with no initially booted devices. Preparation now works; hosted
  launch acceptance remains unresolved. Local revision `1844837b` corrects
  runtime selection to prefer the oldest available version at or above iOS 17,
  as required by D8. Three inventory cases failed before this change; all ten
  inventory/preparation checks now pass. This cannot repair an image containing
  only iOS 27.0 and does not qualify the iOS 17 floor. The unchanged 50-case
  local matrix passed at this exact revision under the guest/gate locks:
  twelve spawn and thirteen app executions on each device class, including
  repeated app invocation. The manifest pins Xcode 27A266a, iOS 26.4 build
  23E254a and fixture hashes; all 26 app invocations used fresh containers and
  fresh markers. Cleanup succeeded and both owned simulators were verified shut down. This
  current local evidence does not resolve the separate hosted failure.
  Next: qualify the pinned hosted lane without weakening fixture deadlines:
  12 fixtures × spawn/app × iPhone/iPad plus one repeated app invocation per
  class (50 executions). Preserve Xcode/runtime provenance,
  fresh-container and `UIDeviceFamily [1,2]` proof. These trusted child-free C
  fixtures do not qualify arbitrary descendants or the eventual in-process
  provider. Afterwards: `CX-P1-08` (needs `CL-P1-17`, `CL-P1-13`, `CL-P1-16`),
  `REQUEST(CL-P1-17)` (protocol), `REQUEST(CL-P1-21)` (entry symbol).
- **PR35, `CX-P1-05` Android host** (`codex/cx-p1-05`, locally validated head
  `0c76ac27`). Main `87dd60d7` is merged into the branch. SDK license handling and pinned archive package
  registration are repaired; failed runs retain partial results and bounded
  guest diagnostics. Local transport/workflow checks pass (143 tests).
  API 36 passed all 28 shell/NativeActivity cases on 4 KiB pages in both
  [run 37557518213](https://github.com/schiffy91/btrc/actions/runs/37557518213)
  and [run 37560687135](https://github.com/schiffy91/btrc/actions/runs/37560687135).
  The first API 29 run lost package/activity services. The later run passed
  25/28 cases before `am start -W` timed out although the activity had already
  completed its create/resume/destroy lifecycle. Removing the display wait in
  `f1cbf0db` passed all 28 API 29 cases in
  [run 37563205491](https://github.com/schiffy91/btrc/actions/runs/37563205491),
  but API 36 then failed after 21 cases because startup spent the one-second
  fixture timeout. The latest native ready/start handshake separates bounded
  launch readiness from the unchanged fixture execution budget.
  [Run 37564454274](https://github.com/schiffy91/btrc/actions/runs/37564454274)
  passed all 28 cases on each API at `68c7b553` (56 total), with retained
  stream/status, cleanup and separate launch-readiness timings. Both are
  x86_64 emulators on 4 KiB pages, NDK 29.0.14206865; boot took 18.89 / 36.89 s.
  The two requested native matrices passed at that revision. On combined
  candidate `18185f0b`, [run 37570754359](https://github.com/schiffy91/btrc/actions/runs/37570754359)
  passed API 29 but failed API 36 `app/large` after 22 successful checks. Logcat
  records NativeActivity destruction/recreation in the same process and an old
  worker trying to finish a destroyed activity. The actual C host failed a
  deterministic lifecycle simulation by finishing a retired activity. Revision
  `0c76ac27` gives the fixture process-owned execution/result state and a copied
  sandbox path, with a mutex-protected live-activity registration. Recreation
  during execution or after completion cannot rerun the fixture or truncate its
  files. GCC and Clang strict-C11 `-O2` simulations pass using real threads,
  fork and files; the host/workflow/skip-ledger matrix passed 204 tests. Failed
  comparisons now retain byte counts, hashes, status and timing separately from
  passing rows. [Run 37578476126](https://github.com/schiffy91/btrc/actions/runs/37578476126)
  passed both APIs: retained summaries prove **56/56 executions**, 14 shell
  and 14 app cases on each API. The change is integrated into PR60 candidate
  `081aae51`; its [combined Android run 37581622992](https://github.com/schiffy91/btrc/actions/runs/37581622992)
  passed tooling and both API jobs. Current candidate `ad72af03` also passed
  [run 37588790885](https://github.com/schiffy91/btrc/actions/runs/37588790885):
  retained summaries report 28 cases per API, 56 total. These remain trusted C
  stand-ins on x86_64 emulators, not physical ARM64 or provider qualification.
  The other combined gates remain required.
  Neither later failure proves the
  earlier service failure's cause.
  The i686 compatibility-builder issue (`REQUEST(CL-P1-02)`), ARM64 16 KiB
  execution and general in-process provider safety remain separate gaps.
- **PR42, `CX-UIB-07` accessibility spike** (findings head `6d62e046`, docs CI
  green; prototype `codex/cx-uib-07-spike` `0d6127a6`). Owner: Codex for the
  note, Claude for the decision. macOS run 37217909473 failed at compile in both
  frontends: a managed NSView passed as raw `void*`. AX trust is unknown.
  `REQUEST(CL-UIB-09)` asks for a nonescaping mutable NSView adapter boundary,
  and `CL-UIB-09` requires this packet's gap list and Stage 29 interop step 6.
  Landing the note resolves the gap-list dependency. `REQUEST(CL-UIB-12)` covers D-Bus vtables after
  D23. The findings note merged on October 7 at `87dd60d7`, with AX trust
  recorded as "unknown, blocked on CL-UIB-09". Missing evidence stays missing
  (D28), and the note meets `CL-UIB-09`'s gap-list dependency. The prototype
  remains unmerged; the native re-run follows `CL-UIB-09`.
- **PR51, `CX-P2-02` HTTP contract** (revision 5 `799c9de5`) and
  **PR52, `CX-P2-01` Windows services design** (revision 5 `6866eb3d`).
  Both are refreshed onto main. Earlier docs/static checks passed; PR52's latest
  clarification passed static CI.
  **`CL-P2-01` round 5 (2026-10-17).** The panel ran: feasibility,
  correctness and parity reviewers, plus a verifier for each blocking finding
  (reports `cl-p2-01-r5-*.md`, summarized on each PR).
  - **PR51 (HTTP) is approved.** All three round-4 findings are resolved, and
    no reviewer left a blocking finding. Batch 8 integrates
    `docs/design/http-transport.md` (`bed10094`). Its seven non-blocking notes
    are on [PR51](https://github.com/schiffy91/btrc/pull/51#issuecomment-6243709262).
    The request lists join the `CL-P2-02/03/04/14` scope. Provider
    implementation and native qualification are separate steps.
  - **PR52 (Windows services) is returned** with four confirmed blocking
    findings, each with a bounded required change
    ([round-5 comment](https://github.com/schiffy91/btrc/pull/52#issuecomment-6243793535)):
    - A: the Ctrl-C trampoline order, and an unclassified `ERROR_OPERATION_ABORTED` read;
    - B: `CX-P2-08`'s Daemon corpus split, covering owned paths, the portable case list and barrier coverage;
    - C: the strong metadata reference fails to link from the single `windows_os.c` object, confirmed by experiment with zig's lld-link;
    - D: no build path for the deterministic fixtures. Use a `DebugActiveProcess` freeze, add a test-only launcher fault build in `REQUEST(CL-P2-02)`, and a fake-launcher harness.

    Owner Codex: revision 6. Round 6 reviews only A–D and what the revision changes.
  - HTTP now requires provider-owned `Connection: close` on Android requests
    and redirects, bounded admission while native I/O drains, and hermetic
    Windows revocation fixtures. Review those guarantees before implementing
    the provider; no native transport has been qualified by this prose change.
  - Windows services now specify post-COMMIT outcomes independent of ACK,
    generated metadata ownership, operation-aware lock errors, a permanently
    registered console trampoline, owned supervisor stdio, and portable/POSIX
    Daemon corpus separation in `CX-P2-08`. `3850ce35` also corrects the obsolete fixture-list
    reference to the derived `include_fixtures()` owner.
    The round-5 touchpoint review found that a lost ACK's successful liveness
    reconciliation had no explicit public result. `6866eb3d` now requires one
    token-bound probe within the remaining existing budget: return 0 for the
    matching live supervisor, otherwise 125 with the indeterminate outcome.
    Preserve transfer state 2 in diagnostics and never relaunch or infer
    liveness from the record alone. Exact outcome fixtures are required; this
    clarification is not independent-panel approval or native execution proof.
  - Approval promotes the request lists to `CL-P2-02/03/04/14` scope. Design
    merge, implementation and native qualification are separate acceptance steps.
- **`CX-C-01` follow-ups** (batch 26 comment on PR26; no PR yet). Owner: Codex
  (`tools/bench/scripts/ccompat_checkpoint.sh`,
  `src/tests/python/test_ccompat_checkpoint_script.py`). Prerequisite: none.
  They fail closed today. (1) Read the RED gate summary in a `finally` block,
  with a test. (2) Make parent budget runs opt-in (`--budget-parent`).
  (3) Record the QuietCheck verdict in `summary.json`. (4) The macOS `sun_path`
  is 104 bytes: shorten the paths or use `$TMPDIR`. (5) The dry-run `READER=`
  placeholder and the `BTRC_NATIVE_TARGET`/`SYSROOT` record. Acceptance: one
  small PR with tests, before `MAC-C-02` uses the script.
- **`CL-P2-22` lifecycle shape check (2026-10-18).** Entry constraints for
  Codex's lifecycle owners. No `CX-P2-36` or `CX-P2-41` draft exists yet, so
  this is the shape to write them against (cited from
  `docs/design/ui-contracts/ui2-approved.md`).
  - **Both owners.**
    - The OS owns the loop: the host entry calls `GUI.attachHost` on the main thread and never `GUI.run`, which is typed unsupported (:250).
    - `requestTurn` is coalesced and never runs work inline. `scheduleTurn` arms one replaceable native timer, and each wake runs one bounded `serviceTurn` and returns. No polling.
    - The host link stays provisional until `CL-UIA-22`, with no private hosted bridge in the meantime (:797).
  - **`CX-P2-36` (iOS).**
    - The wake is a common-mode main-run-loop source, and the clock is `CACurrentMediaTime`.
    - Scene delegates use the landed `scope = "instance"` adapters with `terminal = sceneDidDisconnect:`. The receiver is released after that call, so a process-scoped owner holds close and drain.
    - A system scene disconnect is host-forced and gives `OWNER_LOST`.
    - Adapters accept only `executor = "caller"`, `failure = "abort"`, so each delegate method catches BTRC exceptions and routes them to an orderly quit.
  - **`CX-P2-41` (Android).**
    - The wake is a coalesced Handler message on the main Looper that drains one slice. Choreographer is separate. The clock is `uptimeMillis`.
    - Lifecycle natives are registered once per process on main, with `executor = "main"` and `cancellation = "entry-barrier"`; a second live registration throws. Never call a `main` class from a worker, and hold the Activity as a `JavaWeak`.
    - Destroying the Activity gives `OWNER_LOST`, and recreating it starts a fresh generation.
    - Until both importers take reader v2's private natives and nested classes, natives must be public methods of top-level classes.
  - **Routed to `CL-UIA-22`.**
    1. Blocking: the host link (`attachHost`, `IApplicationHost`) is not in source, and the `CX-P2-36`/`41` rows do not depend on `CX-UIA-21` or `CL-UIA-14`.
    2. The Android shell is said to enter the program "through RegisterNatives" (:256, :791), but in the landed seam natives exist only after BTRC calls the factory. Entry needs `JNI_OnLoad`-time registration or an exported symbol.
    3. `transition()` is application-wide, while iPad scenes suspend individually.
    4. `BACKGROUND` versus `SUSPENDED`, memory warnings and termination have no mobile vocabulary.
    5. The hosted-application receiver interface is unfrozen.
- **Hosted macOS shell-survivor flake** (found in batch 10, 2026-10-18). Owner:
  Codex (the UI1 shell harness). On hosted macOS run 39109668584,
  `test_macos_native_shell[plain-python]` failed because an AppKit-private
  `_NSKeyboardFocusClipView` was still alive at every drain turn. The deadline
  was 2.0 s and each drain took 0.9–1.0 s. `main`'s run of the same harness at
  9da96a84 passed it, and the batch changed nothing in AppKit or the shell.
  Next: decide whether that class belongs in the private-survivor baseline,
  which `macos_private_survivors` partitions, or whether the harness drains
  too early on a loaded runner. Add a case that reproduces it.
- **`CX-UIA-10` follow-ups** (batch 36 comment on PR54; no PR yet). Owner: Codex
  (`src/tests/native/gui/shell/probes/macos`, the evidence shard).
  Prerequisite: none. (1) Add `wrong_field_identity` and `wrong_scroll_identity`
  mutation cases. (2) `native_controls[].ax_exposed` compares raw views
  (`ShellProbe.m:271`); map through `controlView`. (3) Test-record slot keys set
  frontend/variant values that `JUnitAdapter` never emits. Acceptance: the
  mutation tests fail on the old gate, and macos.yml `native-gui` is green.
  (4) Batch 46 (the UI1 checkpoint, `docs/design/ui-contracts/ui1-feasibility.md`):
  keyboard delivery is unproven for every key, not only Tab, because the
  hosted application is never activated (300 of 300 contexts per variant are
  `application_active=false`, `window_key=false`; nothing under `src/` or
  `tools/` calls `activate`). Have the probe request activation and record
  `application_active`/`window_key` after the request, or deliver through a
  declared route (`[window sendEvent:]` or field-editor commands) and record
  which. `CX-UIA-22` must not count E01–E03 or E33/E34 Return and Escape rows
  as passed until a run shows `window_key=true`. `MAC-UIA-02` covers GPU timing
  and an Accessibility Inspector capture only; it does not prove keyboard
  delivery.
- **`CX-UIA-11` residuals** (after batch 38). Owner: Claude for the flake/nix
  pins (WORKSTREAMS §3.3.1 hotspots); Codex re-runs the acceptance once they
  land. Prerequisites: a libdecor 0.2.5 fix for the Wayland
  selfhost+sanitizer restore-61 timeout (still open); `libdecor-0.pc` in the
  dev shell, so CI compiles `LibdecorPending` (landed in batch 41: the dev shell
  carries `libdecor.dev`); a pinned SDL fix for the X11 BadWindow clipboard
  crash (landed in batch 41: `nix/sdl3-x11-selection-requestor.patch`, guarded
  by `test_native_ui_sdl_clipboard_requestor.py`, which runs
  `ClipboardRequestor` mode 1 and passes). Codex may now add the
  `LibdecorPending` compile test and re-record the destroyed-requestor
  `ClipboardRequestor` row in `evidence/ui1-linux.toml`. Next acceptance: Codex
  re-runs the Wayland acceptance row and the `LibdecorPending` CI build; Wayland
  4/4 rows and the X11 clipboard probe pass.
  Batch 45: Claude changed `src/tests/native/gui/shell/NativeShell.btrc` (the
  CX-UIA-09 fixture) so that journey steps 1, 4, 5 and 6 wait, within a 15 s
  budget, for injected input to land before asserting. Before, they assumed one
  10 ms tick, and step 5 (`action.count == 1`) failed intermittently on a
  virtual display shared by parallel workers. Keep that pattern in new journey
  steps.
  Batch 46: the UI1 checkpoint admits Linux SDL to UI2 with X11 gating and
  Wayland carried. The re-records above (the destroyed-requestor row, then all
  four Wayland rows at the current revision, then `test_native_ui_shell_linux.py`'s
  failure count from 21 to 20) are now also the Wayland half of the UI2
  landing's evidence. Claude added a UI2-eligibility sentence to the `note` of
  `macos-hosted-correctness` and `linux-devcontainer-automation` in
  `docs/design/native-ui-catalog/hosts.toml` (a `CX-UIA-06` path; notes only,
  no `status` or `blocked_by` change).
- **UI2 landing chain** (batch 47: `CL-UIA-13` approved the UI2 contract in
  `docs/design/ui-contracts/ui2-approved.md`). Owner: Codex. Prerequisite: none
  for `CX-UIA-21`; `CX-UIA-22` and `CX-UIA-23` stack on it, and paths held by
  `CX-STDLIB-01/02/03/05` become claimable once those integrate (D28).
  `CX-UIA-21` writes the production interface exactly as the record's
  "Approved interface diff" gives it (the `I*.btrc` changes, the `GUI.btrc`
  facade mirrors, `GUI/ControlEvents.btrc`, the BackgroundJobs completion hook
  with its README contract and test, the portable fixtures under
  `src/tests/native/gui/ui2/`, the operation shard rows and
  `amendments/cx-uia-21.toml`, and the E-case link hunk as a fragment). The
  record's "Landing" section is authoritative for the owned paths each of
  `CX-UIA-21/22/23` gains. Rules to keep: receivers have one distinctly named
  method each; outcomes are owning classes with a `kind` enum, never rich enums
  carrying managed payloads; worker publication uses the fixed non-generic
  record; the macOS wake is a common-mode run-loop source (no `performBlock`);
  Linux composition goes through `SDL_EVENT_TEXT_EDITING`, and E01's Linux undo
  row stays missing for `CX-UIA-27`. Acceptance: `CL-UIA-14` lands the
  interface, macOS and Linux atomically with E01–E04, E29, E31, E35, E39, E40
  and E46 on both frontends.
- **`CX-P1-02` platform inventory.** Owner: the owner (sign-off), then Codex
  (the 58 cells in `platform-inventory.toml`) and Claude (the
  `platform-parity.md` totals fragment). Prerequisite: the owner's sign-off on
  `platform-adaptations.md` (WORKSTREAMS §7 Q9). The platform slices above
  assume those adaptation defaults. Acceptance: `test_platform_inventory`
  passes with the cells applied.
- **Claude `CL-REQ` packets awaiting Codex's minimal repros.** Neither failure
  is recorded on GitHub yet as a REQUEST, PR comment or issue (open and closed
  PRs 26–59 were searched).
  Codex posts each repro: the command, run through both frontends. Claude then
  opens the `CL-REQ` packet and owns the paired fix. Acceptance: a paired fix in
  both compilers plus a regression.
  - The catalog partition assertion (handoff step 6).
  - The Windows SDK qualified function type, which both compilers rejected in
    eight architecture/frontend cases (the Windows slice above).
- **Not active, carried.** Owner: Codex.
  - `CX-UIB-08` follow-up (batch 32): the 100,000-record fixture has 989
    repeated sort keys and only 8 distinct titles. Add a tie-break or richer
    titles before `CX-UIB-28` consumes the digest.
  - `CX-UIA-05` (broader surface): startable, since `CX-UIA-02` and
    `CL-UIA-24` landed, but unclaimed. Stage 30; it gates nothing under D28.
  - `CX-UIA-07`: unclaimed. Stage 30; it gates nothing under D28.


