<a id="plan-moved-to-claudemd"></a>

# PLAN: unified btrc and BTRSmith roadmap

Updated **2026-10-20** for the owner-directed consolidation and repair queue.
The five-platform priorities and earlier execution handoff remain below. Read [AGENTS.md](AGENTS.md) first for architecture and
development rules. Detailed evidence below retains its original dates; this
planning update does not assert new implementation or qualification results.

This is the single active plan. It combines the former CLAUDE.md roadmap,
CODEX.md provider queue, and PLAN.md compatibility index. Stage numbers, packet
IDs, numeric budgets and acceptance criteria retain their meaning. CLAUDE.md and
CODEX.md are role entry points; any retained roadmap copies or compatibility
anchors there are subordinate to this plan's current priorities, not independent
queues.
The original `CX-PLAN-01` plan-split introduction remains historical provenance;
D29 governs the consolidated queue. [WORKSTREAMS.md](WORKSTREAMS.md) retains file claims and the coordination protocol;
[the integration record](docs/design/claude-integration-record.md) retains dated
batch evidence. The frozen [reference](docs/design/plan-reference.md) and every
`ref:N` line citation remain unchanged. This document has no effort or calendar
estimates: order follows the owner's stack rank and demonstrated dependencies.

## Owner-directed consolidation and repairs (2026-10-20)

The owner explicitly changed the sequence: document every branch's remaining
gaps here, merge the accumulated work into `main`, then fix it on `main`.
For this consolidation, that instruction supersedes the earlier requirement
to finish qualification before landing. Architecture, acceptance thresholds,
resource assertions and evidence requirements remain unchanged. Landing does
not close the gaps below or make the combined tree qualified.

The starting `main` was `dc97d1f23610a7135d8471cbc0450e39ac196452`.
All 16 open PR heads were already ancestors of integration `7bcf11cf`.
The consolidation also includes the three published diagnostic branches and
three saved local diagnostic/repair branches listed below, with their histories.
PR #106 was retargeted from `claude/parity-wave-2` to `main`.
There were 21 remote branches including `main` before landing; 252 older remote
branches had already been retired with recovery records.

### Branch inventory and remaining work

The gap IDs refer to the repair queue immediately below. Every implementation
row also needs G07 on the final combined revision. “No separate defect
identified” records the current audit result; it does not assert a passing gate.
Historical heads remain useful provenance after their branches are deleted.

| Branch / PR / audited head | What it does | Remaining work |
|---|---|---|
| `main`, `dc97d1f2` | Holds the previously integrated baseline. | Receive this consolidation, then close G01–G07 and reconcile G09. |
| `codex/windows-sockets-20261019`, [#107](https://github.com/schiffy91/btrc/pull/107), `83d7c412` | Combines platform integration with SDK-backed Winsock HTTP support. | G04 and final Windows HTTP/native corpus evidence; service supervision remains G08. |
| `claude/parity-wave-3`, [#106](https://github.com/schiffy91/btrc/pull/106), `f1bb5c7d` | Aligns function-pointer conversions and nullable calls between compilers. | No separate unresolved source defect identified; final parity, bootstrap and C11 evidence under G07. |
| `claude/integ-b18`, [#105](https://github.com/schiffy91/btrc/pull/105), `3e8bb4b4` | Combines compiler parity, ABI fixes and Windows, Android, iOS and macOS changes. | Shared G01–G07; no additional missing branch source identified. |
| `claude/win-shell`, [#104](https://github.com/schiffy91/btrc/pull/104), `9aad8c4b` | Implements the native Win32 GUI shell on x64 and ARM64. | G04, including observer regression and all native frontend/sanitizer variants. |
| `claude/ios-corpus`, [#103](https://github.com/schiffy91/btrc/pull/103), `f881b735` | Runs the full applicable corpus through both compilers on the hosted iOS simulator. | Final combined corpus/host evidence under G07; retain restricted and missing-provider classifications. Simulator results do not establish device coverage. |
| `claude/android-corpus`, [#102](https://github.com/schiffy91/btrc/pull/102), `6efc6224` | Adds Android corpus execution and host supervision on emulators. | G05 and final two-compiler corpus/host evidence. |
| `claude/macos-flakes`, [#101](https://github.com/schiffy91/btrc/pull/101), `48fb9921` | Improves hosted macOS reader diagnostics and bounded shell execution. | No separate new branch defect identified; combined macOS E40 failures remain G03. |
| `claude/parity-wave-2`, [#100](https://github.com/schiffy91/btrc/pull/100), `c5009984` | Aligns opaque/native storage, pointer/null and callback behavior between compilers. | Final parity, bootstrap and C11 gates under G07. |
| `claude/integ-b17`, [#99](https://github.com/schiffy91/btrc/pull/99), `5f55c5a5` | Combines Windows corpus, regex, terminal and process support. | Historical temporary-directory defects were repaired downstream; final combined Windows evidence remains G07. |
| `claude/win-process`, [#97](https://github.com/schiffy91/btrc/pull/97), `8ef8421e` | Implements the `CreateProcessW` launch seam and Windows Process provider. | Final native process qualification under G07; the separately specified service supervisor remains G08. |
| `claude/win-regex-terminal`, [#96](https://github.com/schiffy91/btrc/pull/96), `62235115` | Adds Windows regex, glob, fnmatch and console Terminal support. | No separate new source defect identified; final Windows/native corpus coverage remains G07. |
| `claude/win-filesystem`, [#95](https://github.com/schiffy91/btrc/pull/95), `578f5bae` | Implements Windows filesystem operations, private directories, locks and durable replacement. | The junction fixture publication protocol was repaired downstream; final repaired native execution remains G07. NTFS durability assumptions are not crash-test evidence. |
| `claude/win-corpus`, [#94](https://github.com/schiffy91/btrc/pull/94), `add1f88b` | Runs the applicable corpus on hosted Windows x64 and ARM64. | Historical temporary-directory failures were repaired downstream; final runs and exact restricted/missing-provider accounting remain G07. |
| `codex/cx-uia-21-interface`, [#67](https://github.com/schiffy91/btrc/pull/67), `dcf8e628` | Combines compiler/platform work with UI2 interfaces, controls and lifecycle acceptance. | G01–G07; new macOS lifecycle acceptance has compile/link evidence where native hosted execution remains outstanding. |
| `codex/cx-p2-01-r2`, [#52](https://github.com/schiffy91/btrc/pull/52), `6866eb3d` | Specifies Windows service supervision and process containment. | G08: this branch is a specification; implementation and native acceptance are still absent. |
| `codex/cx-p1-04`, [#34](https://github.com/schiffy91/btrc/pull/34), `f49c5fe1` | Adds standalone iPhone and iPad simulator test-host tooling. | Later host work supersedes this head's launch-identity failure; qualify the combined tooling under G07 rather than claiming the historical head passed. |
| `codex/ui2-completion-20261019`, published `a7611638`, local `7bcf11cf` before these merges | Accumulates integration repairs, Android process snapshots and isolated nested GUI reports. | G01–G07; nested report isolation passed 26 portable tests, but the full unit run remains incomplete. |
| `codex/e40-loop-diagnostic-20261020`, `3a5aba9f` | Captures bounded loop counters and stacks for two failing macOS tracking routes. | G03; starvation is confirmed and the transport repair now passes compile/link checks. Hosted tracking, presentation and lifecycle acceptance remain open. |
| `codex/bench-memory-diagnostic-20261020`, `5e7e5fea` | Compares pinned baseline/candidate compiler memory on one hosted Linux environment. | G06; metadata collection is repaired. The focused run exceeded the unchanged BenchArc allowance by 61,440 bytes; an ordinary run passed. Retain both outcomes and qualify the allocation repair. |
| `codex/windows-user-observer-20261020`, `16b3cc2f` | Compares count-only and instrumented Windows USER-resource observations. | G04; initial observer intrusion is demonstrated, while a later count increase remains unexplained. The merged repair removes the foreign WNDPROC query from the current observer. |
| Local `codex/linux-unit-diagnostic-20261020`, `02b22eaa` | Retains the first failure from the complete Linux unit selection. | G01; the post-merge diagnostic identified three failures, now repaired with 100 focused checks passing. The complete unit gate remains open. |
| Local `codex/linux-gui-sharding-20261020`, `1ebaefa7` | Splits each Linux GUI session into four deterministic partitions and checks exact combined coverage. | G02; inventory and setup-time skip checks now pass. Hosted partition execution and complete coverage remain open. |
| Local `codex/windows-observer-repair-20261020`, `970ce901` | Removes the intrusive foreign WNDPROC query and adds a hidden ANSI-window observer regression. | G04; all eight cross-build/link variants and all four native x64 variants pass. ARM64 execution and final-revision qualification remain open. |
| Local `codex/pytest-failure-journal-20261020`, `8572952c`, integrated as `34cdb461` | Preserves failed test names, errors and captured output before a test session ends. | G07; 187 reporting/workflow checks pass, including interrupted serial and parallel sessions. Full hosted unit qualification remains open. |

### Repairs landed after consolidation

All 16 PRs were recorded as merged when `b0317191` reached main. There are
zero open PRs. After the final diagnostic runs ended, their two branches were
retired as well. All 272 stale remote branches have recovery records, and
`main` is the only remaining remote branch.

The first repair batch passed 246 portable tests on `c8c4feb4`, with no skips,
and passed targeted Ruff lint/format checks. It fixes the benchmark image
metadata command, updates the Linux qualification inventory for all E40 and
GUI partition rows, exercises setup-time skip identities with and without xdist,
and composes Windows diagnostic mocks with the observer regression. The first
attempt exposed an undeclared PyYAML test dependency; the regression now uses
the existing workflow parser. The declared development dependencies also require
Pluggy 1.2 or newer, matching the hook wrapper API already used by the skip ledger
and GUI collection plugin.

On `c9db9e1e`, lint, formatting, generated sources, package and extension builds
passed, followed by 173 structure/hygiene tests with no skips. Eight Windows
shell/observer cross-builds also passed; those checks did not execute Windows
programs. Local bootstrap was stopped after detecting an existing iOS simulator,
as the host policy requires bootstrap to run without a guest. The simulator was
left untouched. Bootstrap remains open in the hosted matrix.

The next unit repair batch on `0320e738` passed all 100 build-safety, host-manifest
and strict-import tests, with no skips, plus targeted lint/format checks. It
checks the parallel, serial E40 and bootstrap phases separately, preserves host
manifest identity when a diagnostic temp directory is inside the repository,
and supplies the Publisher fixture's three missing direct imports. The complete
hosted unit selection still needs to finish.

Android run `39446987361` on `a7611638` completed successfully: both API levels
passed all 28 host fixtures and both compilers' CheckJNI-enabled round trips and
expected refusal cases. Each API corpus recorded 2,044 passes and six classified
GPU dependency skips, with no failures or errors. The earlier transport loss has
no demonstrated cause; this successful run is retained evidence, with final-main
qualification still pending.

### Live issue tracker and 2026-10-21 repair batch

Open post-consolidation blockers and queues are tracked in GitHub Issues on
`schiffy91/btrc` so status updates, CI run links and agent handoffs use `gh issue`
without dirtying the working tree or triggering markdown-gated CI runs. Historical
October 7 to 19 execution records live in
[docs/design/claude-integration-record.md](docs/design/claude-integration-record.md).

- [#108](https://github.com/schiffy91/btrc/issues/108): `[G01/G04] Hosted Linux and macOS unit shard timeouts and macOS unit failures`
- [#109](https://github.com/schiffy91/btrc/issues/109): `[G02] Hosted Linux GUI eight-partition qualification`
- [#110](https://github.com/schiffy91/btrc/issues/110): `[G03] Hosted macOS E40 slider tracking and observation serialization`
- [#111](https://github.com/schiffy91/btrc/issues/111): `[G06] Hosted iOS simulator and Android emulator two-compiler corpus qualification`
- [#112](https://github.com/schiffy91/btrc/issues/112): `[G07] Final post-consolidation verification matrix across all platforms` (`G05` and `G09` closed)
- [#113](https://github.com/schiffy91/btrc/issues/113): `[G08] Implement Windows service supervision and process containment (CX-P2-01-R2)`

The 2026-10-21 repair batch lands the G01 through G04 code and test repairs
together with this document cleanup:
1. Renamed `IApplicationNativeWake.btrc` to `ApplicationNativeWake.btrc` so the
   internal provider wakeup protocol does not trigger `test_ui0_catalog.py`.
2. Added `timeout=30` to the six untimed `subprocess.run` calls in
   `test_ci_workflow_contracts.py`, `test_native_ui2_fairness_linux.py` and
   `test_native_ui2_macos_e40.py`.
3. Guarded nullable member accesses in `MacOSWindow.btrc` and `MacOSSelect.btrc`
   so zero-diagnostic AppKit builds emit no warnings.
4. Fixed `UI2MacOSImages.m` (`@YES`/`@NO` boolean boxing), `MacOSTextFieldConformance.btrc`,
   `MacOSScrollViewConformance.btrc` and `ScrollViewControl.m` (`window.show()` before
   first-responder and scroll checks, baseline `setText` republication, and two-axis
   viewport scroller expectations), `MacOSApplication.btrc`, `LinuxApplication.btrc`
   and `NativeApplication.btrc` (`"Application work capacity exceeded"` on
   `SCHEDULE_FULL`, close lifecycle guards, `loopActive`/`activationActive()` dispatch
   guards, and deferred desktop delegate installation), `MacOSContainer.btrc`,
   `MacOSView.btrc` and `MacOSViewState.btrc` (`MacOSContainerEligibility` and
   `MacOSViewEligibility` adapters breaking `MacOSViewState` cycles before `__del__`),
   `MacOSWindow.btrc` (in-place `WindowState` updates so `__del__` never replaces a
   managed field on a destroying window), `NativeSlider.btrc` (`NSApplication.sendEvent`
   before tracking), and `MacOSActionQueue.btrc` (deferring mailbox wake until
   active button activations finish).
5. Marked the AppKit-using macOS UI2 test modules with `@pytest.mark.macos_gui`
   so `UI2MacOSApplicationQuit` and its siblings serialize under the macOS GUI
   session lock, grouped `@pytest.mark.linux_gui` tests into one xdist group on
   the Linux `unit` shard (`--dist=loadgroup`), and raised the `unit` job
   timeouts (`180` minutes on Linux, `240` minutes on macOS).
6. Integrated the Linux GUI skip-ledger/sharding/fixture repairs (`23d69204` and
   `linux_provider_fixtures.py`) and the macOS E40 slider tracking and
   observation-lock repairs (`d9c24bd4` and `90491d5d` in `Load.m` and `Tracking.m`).

### Repair queue after landing

- **G01: identify and fix Linux unit failures.** In
  [run 39421612625](https://github.com/schiffy91/btrc/actions/runs/39421612625),
  unit job `118624440926` hit its 90-minute limit at about 92% with 57 failure
  and two error progress markers. The aborted run did not retain failing node
  identities or terminal JUnit. Nested GUI tests overwrote the default report;
  `7bcf11cf` isolates those reports and passed 26 portable checks. Main diagnostic
  [39453105197](https://github.com/schiffy91/btrc/actions/runs/39453105197) stopped
  with 2,271 passes, 32 skips and three failures: stale two-phase test assumptions,
  manifest-path spelling under a repository-local temp root, and the Publisher
  fixture's missing direct imports. Those defects are repaired in `0320e738`
  and covered by the 100 passing local checks above. Rerun the full hosted unit
  selection to expose any later failures. Do not count synthetic nested-test
  artifacts as the parent unit suite. The next diagnostic,
  [39459104276](https://github.com/schiffy91/btrc/actions/runs/39459104276),
  stopped at the Game example's warning-free assertion: 4,235 passed,
  2,929 skipped and one failed before fail-fast. The same 39 nullable-access
  warnings also fail NativeShell transpilation. Repair `6a2f1925` adds guarded
  local snapshots in the seven GUI owners. All 24 paired portable queue,
  capture, slider and publisher cases passed, including sanitizer variants,
  with no skips. The compiler's regenerated C is byte-identical to the pinned
  compiler used for those checks.
  This partial diagnostic is not a completed unit suite. The e2e5f432 unit job
  was canceled, so complete unit qualification remains open.
- **G02: finish Linux GUI execution and prove complete coverage.** The same
  run's X11 job `118624440733` and Wayland job `118624440379` hit 90 minutes
  at about 66% and 58%. The merged partition implementation retains the original
  selection, case budgets and dedicated E40 exclusions. Portable tests, corrected inventory expectations and setup-time skips now pass.
  Prove that
  the four cells per session are disjoint, complete and actually executed.
  X11 remains required; Wayland retains its existing report-only classification.
  All eight partitions on `e2e5f432` completed with failures. Canonical reports
  account for all 876 X11 and 874 Wayland nodes without missing or duplicate
  entries; setup errors and skips remain distinct from executed passes. Retained JUnit
  identifies hidden-window input setup, the shared nullable warnings, duplicated
  sanitized fixture builds exceeding the unchanged 120-second compile limit,
  unequal shell-probe headers, and 1,800-second waits for the GUI execution lock.
  Validate these repairs with the original case, sanitizer and lock budgets.
  Repairs `d3a6f765`/`04ac5a15` group each expensive fixture/frontend/sanitizer
  combination on one of four workers and preserve canonical IDs when xdist
  decorates its scheduling IDs. The new real-xdist regression exposed the
  mutable Item-hash lookup defect on its first run; 226 other portable checks
  passed. Repairs `457afcda` and `41d1c4c7` establish one visible window before
  input, require attached controls to be eligible, and retain Mac caret
  declarations only in their dedicated platform header. Repair `e088340e`
  gives GUI lease waiters FIFO tickets with kernel-backed crash cleanup.
  Each last-recorded holder in the four timeout reports eventually passed
  within the wait limit; the evidence supports cumulative unfair waiting.
  The new portable gate passed 327 scheduling, coordination, evidence and
  contract tests with no skips. Hosted execution remains outstanding.
- **G03: repair macOS tracking and presentation.** All four E40
  frontend/sanitizer cells in
  [run 39421612565](https://github.com/schiffy91/btrc/actions/runs/39421612565)
  failed. Tracking journeys lacked native entry/service and load cases lacked
  positive presentation. Focused
  [run 39435082788](https://github.com/schiffy91/btrc/actions/runs/39435082788)
  confirmed native-loop starvation in both desktop and host routes. The posted
  tracking event was never dequeued while the traces recorded 131,823 and
  106,996 source rounds, respectively; all four sampled stacks remained inside
  native event retrieval and the provider's wake delivery. Both cases aborted
  at the original tracking-completion assertion. Repair `b82910e8` coalesces
  requests during delivery and defers the next delivery through a one-millisecond
  common-mode timer. Each entered callback retains its state through reentrant
  close. New Signal cases cover repeated requests, worker requests during the
  pause, a fresh request after an idle turn, and callback-close races.
  All ten affected reference/selfhost Signal, Executor, ApplicationHost,
  E40 Boundary and E40 Load builds compiled and linked; none executed locally.
  Prove tracking, presentation, lifetime and the original timing budgets in
  hosted native runs. The full E40 and lifecycle matrix remains open.
  Focused [39460816421](https://github.com/schiffy91/btrc/actions/runs/39460816421)
  confirms the old busy loop is gone: both routes now wait and return native
  events after the trigger is posted. Tracking still does not enter or complete.
  That fixture used timestamps between 2^45 and 2^46 seconds as event IDs
  without verifying their native readback; the API requires elapsed uptime.
  Existing traces cannot distinguish identity normalization, mask exclusion or
  event discard. Further production scheduling changes require bounded
  post/readback/dequeue evidence that separates these possibilities.
  All four e2e5f432 E40 cells still fail. Fixture repair `565309c4` uses actual
  uptime, application-defined payload fields and mouse event numbers; a
  compact full-trial keyboard ledger preserves late-duplicate detection.
  Diagnostics serialize bounded identity rows from main and producer threads.
  All eight reference/selfhost × plain/sanitized Boundary and Load compile/link
  checks passed. None launched a native GUI executable. The original receipts,
  assertions and deadlines remain unchanged. Native execution must still prove
  that AppKit preserves these identities.
- **G04: finish Windows observer repair and strict resource qualification.**
  Reference UBSan in
  [run 39421612635](https://github.com/schiffy91/btrc/actions/runs/39421612635)
  grew from USER 6 to 7 at cycle 37. The paired
  [diagnostic 39446288124](https://github.com/schiffy91/btrc/actions/runs/39446288124)
  passed count-only at USER 6 for all 102 cycles and 100 restores. Instrumented
  mode observed an initial USER increment around `GetClassLongPtrW(GCLP_WNDPROC)`
  and a separate USER 7 to 8 increase at cycle 66 before that cycle's queries.
  A returned opaque procedure handle also cannot support the old module-address
  inference. The merged repair removes that query and exercises the actual
  observer around a hidden ANSI window. All eight frontend × x64/ARM64 ×
  plain/UBSan cross-build/link variants passed on `c9db9e1e` in 106.37 seconds.
  The four x64 native variants then passed in
  [39452977983](https://github.com/schiffy91/btrc/actions/runs/39452977983):
  each held GDI 13 and USER 6 through all 102 cycles and completed 100 restores.
  The hidden ANSI observer held USER 3 and GDI 0 before and after observation,
  then destroyed its window and unregistered its class. These successful runs
  do not attribute the earlier intermittent late increase. ARM64 execution
  subsequently passed too: all eight c9db9e1e variants completed 102 cycles and
  100 restores with the original resource and cleanup assertions. The complete
  Windows workflow on `e2e5f432`,
  [39464780407](https://github.com/schiffy91/btrc/actions/runs/39464780407),
  also completed successfully. Retain exact results and validate any subsequent
  changes to shared GUI ownership code; do not attribute the earlier intermittent
  increase solely from a passing run.
- **G05: resolve Android API 36 transport loss.** In
  [run 39421612552](https://github.com/schiffy91/btrc/actions/runs/39421612552),
  API 36 went offline during the ninth of 28 host fixture cases; ADB exited 255.
  API 29 and target corpus results do not explain the disconnect. Snapshot
  commits `fecba284`/`a7611638` retain owned process state before shutdown;
  their 110 portable checks passed. The successful
  [run 39446987361](https://github.com/schiffy91/btrc/actions/runs/39446987361)
  now supplies the fixture and corpus evidence recorded above. Repair a
  demonstrated transport cause if it recurs, and retain
  complete final-revision host/corpus evidence. No transport fix is claimed.
- **G06: fix benchmark metadata collection and the memory regression.**
  `BenchArc` and `RunStrings` exceeded their original peak-memory allowances
  by 32,768 and 61,440 bytes. The attribution
  [run 39446272710](https://github.com/schiffy91/btrc/actions/runs/39446272710)
  failed on the Podman image-inspect `.Id` template before measuring anything.
  Raw structured metadata capture and its success/failure workflow regressions
  now pass. Completed main diagnostic
  [39453110378](https://github.com/schiffy91/btrc/actions/runs/39453110378)
  built both pinned compilers and completed all 24 compiler/data-root samples.
  Old main passed the original guard on that host. Candidate `c9db9e1e` failed
  only BenchArc: peak 16,375,808 bytes against baseline 15,265,792, exceeding
  the unchanged allowance by 61,440 bytes. RunStrings passed, so its earlier
  failure did not reproduce. Cross runs show contributions from both compiler
  and data-root changes; they do not identify one allocation owner by themselves.
  The ordinary benchmark job in
  [39452977956](https://github.com/schiffy91/btrc/actions/runs/39452977956)
  passed on the same `c9db9e1e` source: BenchArc used 15,659,008 bytes,
  655,360 below the same limit. Its 44 size, line-count and parity metrics
  match the diagnostic. The diagnostic's peaks were higher for all 11
  programs; differing host kernels and missing ordinary-run binary hashes
  and raw samples prevent attributing that variation. Retain both outcomes.
  Repair `9e23e9a3` replaces 20 eager optional name maps in each
  `FeManifestBlock` with per-block storage allocated only for declared metadata.
  A fresh strict-C11 compiler build passed, followed by all 148 package tests
  with no skips, failures or errors. BenchArc and RunStrings emitted byte-identical
  C before and after the repair with the same current data root and strict imports.
  The first build exposed five nullable-access warnings; direct local guards
  repaired those warnings before the successful fresh build. Actual memory
  savings remain unmeasured. Keep the unchanged hosted guard for later repairs.
  Do not rebaseline, subtract a reporter floor or relax limits. No local compiler
  performance measurements are authorized. The unchanged ordinary strict
  benchmark passed all 235 metrics on `e2e5f432` in
  [39464780404](https://github.com/schiffy91/btrc/actions/runs/39464780404).
  BenchArc peaked at 15,237,120 bytes. This is acceptance evidence for that
  revision, not a controlled estimate of memory saved by the allocation change.
- **G07: qualify the final combined revision.** Run and reconcile `make test`,
  `make bootstrap`, all eight `make test-c11` configurations, lint, formatting,
  generated-source, extension and repository-hygiene gates, plus the affected
  platform/native/E40/corpus and memory checks. Keep exact revisions, selections,
  skips and provenance. Earlier focused passes and compile-only checks cover
  only their recorded scope. The earlier macOS btrc job finished with 6,149
  passes, 57 skips and one naming failure in `FacadeHost.btrc`; `5210b4d5`
  already repaired that import and the current naming gate passes. Host Android
  [39451973769](https://github.com/schiffy91/btrc/actions/runs/39451973769) and
  Host Windows [39451973958](https://github.com/schiffy91/btrc/actions/runs/39451973958)
  completed successfully on consolidated main `b0317191`. Android API 29 and
  36 each passed 28 host checks, both JNI frontends and 2,044 corpus cases with
  six classified GPU dependency skips. Windows passed 111 portable checks and
  16 native host checks on each architecture, without skips or cleanup warnings.
  The 22 audited host dependency groups are unchanged through `b119cd37`;
  these remain `b0317191` executions and do not qualify Windows GUI behavior.
  The `c9db9e1e` Windows native bootstrap also passed in
  [39452977983](https://github.com/schiffy91/btrc/actions/runs/39452977983).
  Its x64 corpus passed 2,020 cases with 30 declared skips: each frontend had
  four missing-provider and 11 restricted cases. These results precede the
  compiler allocation repair; retain renewed compiler provenance and final
  qualification. Preserve missing provider/device evidence as open coverage
  in the existing roadmap. On `e2e5f432`, Linux CI completed both compiler
  corpora (1,025 passes each), all eight C11 configurations (2,050 passes each),
  bootstrap, the selfhost tests, all eight E40 cells, release and the strict
  benchmark successfully. GUI partitions failed
  and unit was canceled; the workflow therefore does not establish a full pass.
  Windows, ARM64 Toolchain, Host Android, Host Windows and Host iOS workflows
  all completed successfully on that revision. These receipts precede the
  current GUI repairs. macOS unit and native/E40 qualification remain separate.
  The automatic main unit selection already contains the native GUI/lifecycle
  suites with the same provider environment, worker count and case budgets as
  the focused GUI job; a second dispatch would duplicate that selection.
  Before claiming coverage, reconcile its terminal per-node skip report.
  The earlier macOS unit job `118783223416` in
  [39464780421](https://github.com/schiffy91/btrc/actions/runs/39464780421)
  exceeded its three-hour limit at 99%. Its log contains 73 failure markers,
  but no failing node identities, final JUnit or skip report survived. The
  retained native-reader prerequisite checks were unchanged and usable;
  those checks do not identify the test failures. Repair `34cdb461` adds an
  optional controller-only failure journal with immediate console output.
  The macOS unit job enables it and retains partial JSONL separately from
  qualification reports. The 187 passing reporting/workflow checks include
  interrupted serial and parallel sessions, collection deduplication and
  appending evidence across sessions. Selection, workers and time limits
  remain unchanged. Partial failure diagnostics cannot establish coverage
  or replace the final classified skip report.
  The Android/iOS/Windows host workflows and their executor, JNI, corpus,
  compiler and toolchain inputs are unchanged by the GUI repair batch.
  Their successful e2e5f432 receipts retain that revision and do not claim
  native executions on a later revision.
- **G08: implement the separately scoped Windows service design.** PR #52
  lands its specification only. The existing service-supervision/containment
  roadmap items still need implementation and native acceptance; merging that
  document does not create those capabilities or expand the Process provider's
  current claim.
- **G09: PR and remote-branch reconciliation complete.** All 16 PRs merged;
  there are zero open PRs and `main` is the only remote branch. All audited heads
  are integrated. The 272 stale branches were retired with recovery references,
  bundles and receipts; the final two were deleted at their verified tips after
  their diagnostic runs ended. Another 86 local branch references were retired
  into recovery refs and verified bundles. Branches attached to retained
  worktrees and active repair clones remain protected. Two managed-worktree
  archive requests are queued; their completion is not yet confirmed.

The consolidation's local audit and retained artifacts are under
`~/.cache/btrc/consolidation-20261019/`, beginning with
`main-consolidation-owner-directed.json`. Git history and the linked hosted
runs provide the portable record. Update this queue as fixes land on main;
do not mark the overall work complete while G01–G07 remain open.


## Owner priorities and execution handoff (2026-10-12)

**Correctness, then cross-platform capability, then performance.** A correct
compiler, usable standard library, native GUI and working BTRSmith across
**macOS, Linux, Windows, iOS/iPadOS and Android** are the delivery priority, even
while compilation is slow or memory use is high. All five platform families are
in scope for BTRSmith as well as for the compiler and library. macOS/Linux MVP
milestones remain useful evidence; they are not the end of the product scope.

The owner approved the stack rank below and requested a plan that another capable
agent can execute with judgment. This update supersedes older performance-first
bucket ordering, fixed "next wave" assignments, and the macOS/Linux-only BTRSmith
destination wherever they conflict. Existing stage numbers and packet IDs remain
stable references, not a mandatory execution sequence. Architecture, correctness,
parity, ownership, native-evidence requirements and acceptance thresholds remain
in force. The frozen reference remains unchanged.

This is an execution handoff, not an assignment to the agent that edited the
document, a promise that this chat will execute it, or a claim that implementation
is currently running. The executing agent or team must establish its actual role,
current file claims and available authority. Historical session-specific grants
do not automatically transfer to a new executor.

### Approved stack rank

| Rank | Outcome | What advances the goal |
|---|---|---|
| **1** | **Fix correctness defects that block platforms.** | Remove demonstrated compiler, runtime and interoperability blockers to native platform work. Examples include Windows ownership/callbacks, UIKit lifecycle integration and Android JNI/callback handling. Choose from current evidence; do not assume every historical blocker still exists or require all unrelated compiler work to finish first. |
| **2** | **Make the core standard library usable everywhere.** | Deliver platform-native storage and persistence, Unicode paths, networking, asynchronous work and reliable resource cleanup on all five platform families. Use existing shared APIs and OS-appropriate semantics. A real operation through the provider advances this rank; a design or test host alone does not. |
| **3** | **Deliver working native GUI on every platform.** | Deliver real windows/activities, controls, text editing, input/focus, events, rendering, accessibility and safe teardown using checked native bindings. Qualify the affected behavior through both compilers on the actual target. A fixture shell or one passing control remains a bounded milestone. |
| **4** | **Make BTRSmith work on every platform.** | Prove platform-appropriate library import, browse/search, playback, settings, persistence and restart/shutdown journeys using the current qualified compiler and library. Desktop and mobile interaction may differ; preserve the intended user outcomes and document actual OS constraints. |
| **5** | **Complete platform coverage and product qualification.** | Close the remaining standard-library and GUI feature matrix, packaging/installation, lifecycle/restoration, audio/GPU behavior, and required OS/device coverage. Distinguish implemented, target-tested, integrated and fully qualified capabilities. Partial demonstrations do not close a platform. |
| **6** | **Meet compiler and application speed/memory targets.** | Optimize the real workload matrix against the retained budgets, including compiler edit median ≤5 s/p95 ≤8 s, cold transpilation ≤10 s and peak footprint ≤1.5 GiB. Keep all other compile, application, audio, latency and memory targets visible until their original acceptance passes. |

**Integrate qualified changes throughout all six ranks.** Reconcile existing work
and dependencies, qualify the actual combined tree and land through the authorized
integrator. Do not postpone all integration until every platform is finished, or
merge experiments and evidence-only branches mechanically. Report working branch
capability separately from capability available on main and in a pinned product.

### How the executing agent should choose work

Use the rank to choose valuable outcomes, not to impose a waterfall. A platform
provider can advance while another platform's compiler blocker is being repaired.
Do not require all of rank 1 or every platform at rank 2 to finish before starting
an independently feasible rank 3 or 4 slice. Prefer changes that remove a shared
blocker or deliver a missing user-visible capability; avoid repeatedly polishing
the most mature platform while Windows or mobile implementation stays untouched.

At the start of an execution run, reconcile current source, claims and the relevant
existing evidence. Then select a bounded deliverable and explain its rank, target
platforms, dependency and observable success condition. The agent chooses the
implementation approach, task decomposition, order within a rank, useful parallel
work and test strategy within the existing architecture and gates. The examples
here are leads to verify, not preassigned patches or an instruction to redo work.

When a dependency blocks a slice, name the exact missing behavior, its evidence
and the owner/action needed to unblock it. Pursue another valuable independent
slice where possible. Do not substitute speculative wrappers, weaken shared
contracts, or fill the wait with repeated broad audits. Respect current ownership
and access constraints; make their effect on delivery explicit rather than
silently consuming effort on peripheral work.

Performance work moves ahead only when a demonstrated resource or timing problem
prevents building, launching or functioning, or when it is necessary to repair a
correctness defect. Merely missing an optimization target is not a prerequisite
for unrelated platform implementation. An actual functional blocker should get
the smallest sound repair that restores progress before broader optimization.
Keep failed budgets and required deadlines visible; this ordering neither raises
them nor converts failed acceptance into a pass. Functional delivery can advance
while performance acceptance remains open, but full qualification cannot be
claimed until its applicable criteria pass.

### Communication and progress reporting

**Over-communicate decisions, results and blockers in plain language.** The owner
should not have to infer whether work is running, waiting, blocked or stopped.
Communication should make the work reviewable without requiring permission for
routine decisions that are already authorized.

- Before a work unit, state the intended capability, affected platforms, why it
  is the highest-value available work, and what result will prove it.
- During active execution, give regular concise updates. Explain discoveries,
  material changes of approach, unexpected failures, blocked dependencies and
  work that has actually started or completed. Before a long build or gate,
  explain what it establishes and how progress will be observed; report the
  result when it ends. Avoid hours of unexplained silence, repetitive unchanged
  status messages and extra polling solely to manufacture updates.
- Before an expensive rerun or wider agent wave, explain the evidence gap it
  resolves and why the existing results cannot answer it. Use judgment within
  current authorization; this explanation is not a new approval ritual.
- At each delivery or handoff, report **goal/rank → platform and capability →
  previous state → result and evidence → integration state → remaining blocker
  and next action**. Say explicitly when no product capability advanced.
- Keep an executive view for all five platform families and BTRSmith. Show
  working capabilities, missing capabilities and blockers; retain exact source
  and evidence links in the underlying rows. Track performance actuals versus
  targets separately so they do not take over the platform-delivery narrative.
- State whether work is continuing and what is actually active. If execution
  stops, record the reason and a concrete handoff. Never imply that an idle agent,
  prepared script, draft PR or saved plan is actively implementing the product.

### Evidence, quota and handoff discipline

Use subagents when an independent implementation or targeted review will improve
delivery. Choose the smallest useful team for the actual work; no fixed swarm,
model switch or repeated plan review is required. One owner holds a shared file
at a time. Reuse valid source-matched evidence, existing test hosts and qualified
toolchains. Re-run what changed or remains unproved, and preserve every required
final combined-tree and native gate. Independent review should resolve concrete
risks in a patch or result rather than repeatedly inventorying the whole project.

Test counts, generated reports, branches opened and hours spent are supporting
information. The main progress measures are **capabilities delivered, platform
blockers removed, and qualified changes landed**. Maintain implemented revision,
tested revision/environment, merged revision and remaining acceptance separately;
never promote simulator/emulator or hosted evidence into physical-device proof.

Keep PLAN.md current as outcomes and blockers change, linking detailed evidence
instead of copying entire logs. Preserve the existing stage/packet definitions,
native catalog, denominators, numeric budgets and historical failure evidence.
At handoff, leave the current branch/commit, changed paths, meaningful checks and
failures, any genuinely live process, and the next bounded action. Another agent
should be able to continue without repeating the investigation or assuming that
the document's author will return to execute it.

## Execution record (Claude integrator, from 2026-10-12)

Detailed October 7 to 19 batch logs, diagnostics and provider handoff records moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md). Live post-consolidation blockers and queues are tracked in GitHub Issues [#108](https://github.com/schiffy91/btrc/issues/108) through [#113](https://github.com/schiffy91/btrc/issues/113).

## Provider implementation queue

Active provider and qualification blockers are tracked in GitHub Issues [#108](https://github.com/schiffy91/btrc/issues/108) through [#113](https://github.com/schiffy91/btrc/issues/113). Historical queue records live in [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#provider-implementation-queue).

## Goal and ownership

See [Owner priorities and execution handoff (2026-10-12)](#owner-priorities-and-execution-handoff-2026-10-12) above and [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#goal-and-ownership).

## Why the queue changes

See [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#why-the-queue-changes).

## First delivery queue

See [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#first-delivery-queue).

### Repair files and test admission

See [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#repair-files-and-test-admission).

## Platform slices beyond the repairs

See [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#platform-slices-beyond-the-repairs).

## Validation and progress reporting

See [Communication and progress reporting](#communication-and-progress-reporting) above and [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#validation-and-progress-reporting).

## Provider handoff at the consolidation snapshot

See [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#provider-handoff-at-the-consolidation-snapshot).

## Active assignments carried from WORKSTREAMS (D28)

See [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#active-assignments-carried-from-workstreams-d28) and GitHub Issues [#108](https://github.com/schiffy91/btrc/issues/108) through [#113](https://github.com/schiffy91/btrc/issues/113).


## Owner update: separate Claude and Codex plans (2026-10-06)

Historical D28 split, superseded only in storage and this session's integration
role by D29. Its independent-provider scheduling, actual prerequisites, parity
and native-evidence rules remain. Batch 40 moved the roadmap to CLAUDE.md and
provider assignments to CODEX.md; this consolidation reunites them without
changing stage IDs or erasing qualification gaps.

## Roadmap context before the split

The September 30 roadmap replaced the frozen 3,885-line reference. All `ref:N`
citations continue to name that unchanged file. Historical progress is in the
[integration record](docs/design/claude-integration-record.md).

## Status (2026-09-30)

This historical anchor is retained. The September status is available in the
[pre-consolidation source](https://github.com/schiffy91/btrc/blob/c011371bf2cafd526348f3c6fc81f8958ddd0f9c/CLAUDE.md#status-2026-09-30).
Use the October 7 status above for current scheduling; old test counts, disk space,
CI triggers, branch state and no-push instructions are not current facts.

## Progress log

The append-only [integration record](docs/design/claude-integration-record.md)
retains each batch's source revisions, reviews, failures and evidence. New
integration results go there and update the current status here. Do not rewrite
past results as though they ran on a later tree.

## Claude handoff: migrate and synchronize the plans

The October 6 migration completed in batch 40. Its split-file checklist is
superseded by D29. Maintain one plan here, entry-point compatibility anchors,
AGENTS.md architecture rules, executable test-read consumers and unchanged frozen
reference citations. Claims remain in WORKSTREAMS.md and detailed packet contracts
remain in docs/workstreams; neither is a competing active queue.

## Decisions (all resolved 2026-09-30)

D1–D26 were settled on 2026-09-30; D27/D28 and D29 amend them. Later WORKSTREAMS questions explicitly requiring owner approval remain open unless a recorded decision resolves them. D27 (2026-10-03) adds a second builder agent, OpenAI Codex; [`WORKSTREAMS.md`](WORKSTREAMS.md) assigns every remaining item to Claude, Codex or the owner as work packets, and this plan stays the roadmap. D28 (2026-10-06) makes [`PLAN.md`](PLAN.md) Codex's active queue and results. WORKSTREAMS.md keeps the shared path claims and cross-agent dependencies, and old packet ids stay for traceability. Where stage text further down still says "you approve", "you close", "if approved", "your checklist" or "blocked on push", the resolution in this section and the standing approvals after it govern. A stage still waits for any unresolved approval or demonstrated technical prerequisite that applies to it.

| # | Decision | Resolution |
|---|---|---|
| D1 | **Bucket order** | **The reference's bucket order**, Stages 1–43 as numbered. UI-first is rejected. |
| D2 | **Disk reclaim** | **The allowlist sequence, as listed:**<br>1. **Preserve first.** Copy the measurement tooling to `~/.cache/btrc/tools`: from `perf/`, `gates.sh`, `bench.sh`, `build_btrcc.sh`, `edit_instr.py`, `cmp_units.py`, `instr.sh`, `sample_*.py`, `bsm_env.sh`, `native_build.py` and `edit_e2e.sh`; plus `m12/split.py`. Stage 3 commits it into `tools/bench`.<br>2. **Keep** every cited path that still resolves: `perf/edit-cold-2026-09-22`, `perf/e2e-2026-09-24`, `perf/btrcc-65057cb`, `bench/final-*`, `bsm-measure`, `checkpoints/2026-09-22-*` and `gcroots`.<br>3. **Delete only** the `btrcc-m11*`/`btrcc-m12*` binaries and their build logs, the `step*` directories, uncited `perf/` workspaces, and `build/test-btrcc` fingerprints beyond the newest 20 plus pinned ones.<br>4. **BTRSmith:** after a citation check, clean `~/.cache/btrsmith/build/tests`, and `perf` only if nothing cites it. Keep `build/evidence` and `signing`.<br>5. **Podman:** inspect actual ownership before any cleanup. The October 7 audit found `podman-machine-default` shared with active SEMU work (8 CPUs, 28 GiB RAM, 180 GiB virtual disk); preserve it and its volumes. The earlier 40 GB/6 CPU recreation applied only to a dedicated btrc machine and does not authorize replacing this shared VM.<br><br>No local Windows VM (D8), so the bucket-3 target is **≥100 GB free before Stage 23**. If free space is short, re-prune `build/test-btrcc` and the BTRSmith test outputs, and install one iOS runtime at a time. |
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
| D27 | **Two builder agents (Claude and Codex); early UI work** | **Amended by D28 (2026-10-06):** D28’s independent-slice rule and D29’s unified plan govern the provider queue. Existing-interface repairs and per-platform slices do not wait on the Stays-gated shell or Stage 33/34 bullets. Codex creates no workflow file; Claude adds lane workflows.<br>**Status.** In force 2026-10-03: the owner asked for the Claude/Codex split and started Codex on it. The owner may strike any clause; work under a struck clause takes no new packets, and its in-flight packets finish or park. Stage 24's early start (the last clause's first bullet) was approved on 2026-10-03, when the owner asked for all the UI work, iOS, iPadOS and Android included, to run in parallel (WORKSTREAMS.md §7 Q2).<br>**Roles.** Claude (the main session) stays the integrator and the one contract owner D6(c) asks for. It alone changes the compilers, shared specs, generators, generated files, `src/runtime/**` (`c/`, `gpu/`, `windows/`), the native readers, editor tooling (`src/devex/**`, except a file a Codex packet names while no C-track packet holds it) and the hotspot files (Makefile, `flake.nix`, `flake.lock`, `nix/*`, `conftest.py`, `runner_capabilities.py`, `native_plan.py`, `budget_bench.py`, `ci.yml`, `macos.yml`, `windows.yml`, PLAN.md, AGENTS.md). It also applies the integrator-owned data (`btrc.toml` manifests, expected-skip manifests, denominators, `ci/tiers.toml`), which Codex changes only through `fragment:` commits. It approves and freezes every contract, merges every branch and pushes `main`. Codex (OpenAI) is a second builder. It owns stdlib platform providers and UI (`GUI`, `UI`, `Tray`, `App`, except their `btrc.toml`), OS-service providers that need no compiler change, test hosts, packaging and host tooling in `tools/` directories it owns, the lane workflows it creates, fixtures, examples, evidence harnesses and their docs, and the BTRSmith UI slices. It may draft UI contracts as the single designated writer chain. A draft becomes a contract only when Claude approves it under the standing design rule. Codex files a request for any compiler, spec or runtime change, and Claude turns it into a packet. Owner steps are `MAC-` packets, one command each.<br>**Mechanics.** `WORKSTREAMS.md` assigns the packets and their paths. Codex works on `codex/…` branches, claims a packet with a draft PR titled `[CX-…]` that carries a `Packet:` line, opens draft PRs to `main` only to get CI, and never merges. Claude integrates at most two Codex code branches per batch into `main-kn9jxh`. Docs-only branches do not count, and an atomic landing (UI2, UI3, a Stage 34 landing, a Stage 35 track milestone, the Windows FileSystem/Process landing) counts as one. Claude runs D5 and pushes per D4. The parity rule is unchanged.<br>**Amends D1.** D1 still orders Claude's work and the gate queue, except for the early starts named in the last clause. A Codex packet may run ahead of its bucket when its dependencies are met on `main`, or when it is planning or spike work, and it changes no file on Claude's list. Schedule eligible batches by the approved stack rank and actual dependencies; preserve active gate/measurement isolation.<br>**Amends D6(c).** The bucket 3–4 platform lanes may be split between the two agents. There is still one contract owner (Claude), and one writer at a time per hotspot. IView, IWindow and `App.btrc` form one Codex writer chain.<br>**UI work that starts now:**<br>• UI0: the focused GUI gate, the catalog and drift test, the host matrix, the BTRSmith caller map and the headless Wayland/X11/AT-SPI tooling;<br>• the native-shell fixture and its macOS and Linux-SDL proofs;<br>• docs-only drafts of the UI2 and UI4–UI9 contracts;<br>• spikes that merge only a findings note: GTK4/WebGPU in plain C, Win32/UIKit/Android shell notes, the collection data model, accessibility bridges;<br>• the 100,000-row fixture generator.<br>**Starts as soon as its in-stage dependencies land,** without waiting for buckets 2–3 to close: the macOS and Linux-SDL halves of UI1–UI3 and the tray (Stages 31–33). UI2 and UI3 approvals are provisional for Windows, iOS and Android until `CL-UIA-22` re-checks them on the real shells. A change then is a versioned contract change, landed atomically with macOS and Linux. If D23 picks GTK4, `CX-UIA-29` ports the Linux UI2/UI3 core to GTK4 before the Linux UI4 work.<br>**Stays gated:**<br>• any portable-contract edit before its packet is approved; such edits land atomically with both reference providers;<br>• the btrc-hosted GTK4 spike and D23, which come after interop step 7 (`CL-P2-24`) and the GObject binding (step 8);<br>• the Windows, iOS and Android shells and UI tracks (Stages 23–29 first);<br>• Stage 34–37 provider work, which waits for the Stage 33 landing, the five shells and `CL-UIA-22`;<br>• BTRSmith screen migration, which waits for its btrc landing and pin bump;<br>• every compiler, spec and runtime change the last clause does not name;<br>• Mac, device and account evidence (D8).<br>**Codex stdlib code while bucket 2 runs:**<br>• no `#if`, `#ifdef` or `#undef` in `src/stdlib` until C4 lands; after that, only conditions valid on every target, and never `#undef`;<br>• no struct member spelled `T[] name` (write `T* name`);<br>• no `volatile T*`;<br>• import every btrc type spelled `struct X`, `union X` or `enum X`;<br>• no identifier that C3 reserves (`inline`, `restrict`, `va_arg`, `_Alignas`, …).<br>Codex stdlib branches are re-gated after C4, r09, r13, the C3 vocabulary commit and r15a.<br>**Claude may also start early** (each item an explicit amendment of D1):<br>• Stage 24 (`CL-P1-03`…`15`) and Stage 25's compiler packets (`CL-P1-16`…`20`), once C4 lands (`CL-C-06`). They interleave with C2/C3 by hotspot, never beside `CL-C-07` or `CL-C-23`, and `CL-P1-05` never beside `CL-C-25` or `CL-C-30`. Interop (`CL-P2-05`…`24`), the GObject binding (`CL-UIA-06`…`08`) and `CL-UIB-16` wait for bucket 2's close (`CL-C-40`);<br>• bucket-1 preparation that measures nothing: the runbook kit, the Stage B key and journal spec, never-merged floor spikes, reference attribution tooling and the host manifests (the x86_64 workflow waits for D7's probe);<br>• Stage 38 CI on runners that already exist: the macOS hardware skip tier, BTRSmith Linux CI and CI tiers;<br>• the BTRSmith UI2 subscriptions and Library.UI split (`CL-UIA-15`…`18`) once UI2 lands, because bucket 1 measures the D9 BTRSmith copy pinned by `CL-R-01`, never BTRSmith `main`. |
| D28 | **Independent stdlib slices** | **Owner-directed, 2026-10-06; storage/role amendment D29, 2026-10-07.** Existing-interface provider repairs with normal regression drivers do not wait for BTRSmith reconciliation, future UI contracts or all five shells. New platform slices wait for their own demonstrated prerequisites. Shared interface changes retain review and coordinated acceptance. A blocked slice does not stop independent work. Batch corrections and retain measured CI concurrency and required gates. The former separate CLAUDE/CODEX plan storage and Claude-only integration restriction are superseded by D29 for this session; unfinished implementation and native qualification remain open. |

| D29 | **One plan; authorized integration** | **2026-10-07:** the owner requests consolidation and implementation/integration into main. PLAN.md owns both queues. This session may resolve and merge work after the required review and gates. D28’s independent-slice rule remains; its separate-file and Claude-only integration restrictions are superseded for this session. See the owner update at the top. |

### Standing approvals (every "you" step in the stages)

| Step in the stages | Resolution |
|---|---|
| Pushes, `ci/**` branches, pin bumps | D4. Every "blocked on push" step proceeds after its gate. |
| Closing issues (Stages 4, 9, 39, 40) | The agent posts the evidence and closes the issue once its acceptance is demonstrated, including #6's side-by-side visual review. Issues whose acceptance needs a listening approval or physical hardware (#4, #5, #21, #22, and Stage 40's records) stay open with the evidence posted. |
| Design and interface approvals (Stage 27's ownership plan; Stage 32's interface diff and `ui.snapshot` change; Stage 34's contract packets) | Approved when its two adversarial reviewers and the parity reviewer leave no unresolved blocking finding. The main session records the approval and the review files in this plan. |
| Codex contract drafts and Codex branches (D27) | A UI contract Codex drafts is approved when Claude's two feasibility reviewers and one parity reviewer leave no blocking finding open; Claude records the approval and the review files in this plan, and from then on owns the contract. A Codex branch lands only through Claude's batch gate (WORKSTREAMS.md §3.8). Outside D29’s authorized harmonization session, provider lanes do not push main or merge PRs. No session edits the frozen reference or claims evidence it has not obtained. |
| Stage 15's "≤0.3% or you explicitly accept more" | ≤0.3% passes. Up to 1% is accepted with the delta recorded. Above 1%, apply D17 or optimize before landing. |
| Stage 12's conditional tiers (borrowed returns, M9 arena, thread-confined ARC, M8b) | A tier runs when a Stage 12 profile attributes ≥5% of a still-open row's cost to what it removes (M8b uses D17's 20%). Otherwise it is declined, with the numbers recorded. |
| Parity exceptions | None. Anything that changes observable behavior is paired. |
| Quiet measurement rounds (Stages 5, 41 and the quiet queue) | The agent changes no system settings. Measurement workspaces live under `~/.cache/btrc/bench.noindex/` (Spotlight skips `*.noindex`). A round starts only when an automated check passes for 60 s: no agents, builds or guests running; podman stopped (the btrc machine only); `tmutil currentphase` is `BackupNotRunning`; Google Drive, `mds` and `mdworker` each under 5% CPU. Otherwise the round waits and retries, overnight preferred. Instructions retired and peak memory are the primary comparison (PLAN.md); wall-clock medians come from quiet runs. |
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
| **Agent handoff** | Keep AGENTS.md and this plan consistent: BTRSmith issue #15 replaces `GOAL.md`; 12,439/172 and 309 boundary records are historical, while the current manifest has 311 records. Record current gates/skips and actual host capacity separately from those historical results. |

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

The buckets below organize the retained technical work. Their numbers and display
order do not override the [approved stack rank](#approved-stack-rank), and finishing
compiler optimization is not a prerequisite for independent platform delivery.

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

**Where more lanes may help.** Independent implementation and review can improve delivery when dependencies, file ownership and current capacity permit it. The executing agent chooses a useful team and keeps one authorized integration owner when parallel writers are used; a dedicated integrator subagent is optional. Preserve the merge and gate procedure below without assuming fixed staffing.

Stage numbers preserve the historical mapping. Actual starts follow the October
12 priorities and demonstrated dependencies; platform implementation may overlap
other stages. Planning is useful when it unblocks a concrete deliverable, not as
a standing wave ahead of every bucket.

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
  3. **Inspect guest ownership** (D2), after `podman machine list`. The current `podman-machine-default` is shared with SEMU; preserve it and its volumes. Do not replay the retired dedicated-btrc resize/recreation step on this guest.
  4. **Hub clones outside Drive.**
     - Create `~/.cache/btrc/hub.git` and `~/.cache/btrsmith/hub.git`.
     - Every agent worktree or clone is made from a hub. The integrator fetches finished batches into the Drive checkouts.
     - Apply the D3(b) branch dispositions, then run `git worktree prune`.
  5. **Locks and capacity rules.** Create `~/.cache/btrc/locks/{gate,bench,linux-ci,guest,gui-capture,signing}` plus a counting `btrcc-build` semaphore with N=2. Use `lockf`, or util-linux `flock` from nix, because macOS has no `flock`. The capacity policy goes into PLAN.md:
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
       - the lost-evidence list for the 23 missing paths
       - the D5 gating amendment if approved
     - **AGENTS.md and this plan’s current status:** reconcile the structure-first review, BTRSmith issue #15, current test/skip counts and the 311-record boundary manifest. Preserve 12,439/172 and 309 only as dated historical evidence.
  7. **BTRSmith docs** in the same pass.
- **Exit and gates.**
  - No currently-resolving cited path was removed, and the 23 already-missing paths are recorded in this plan as lost.
  - The measurement scripts exist outside `perf/`.
  - Free disk is recorded:
    - ≥80 GB is needed to continue.
    - ≥100 GB is a Stage 23 prerequisite (D2/D8).
    - BTRSmith clones are capped at 2 under AGENTS.md. The earlier one-clone cap depended on shrinking the former dedicated btrc guest; it does not authorize resizing the shared SEMU guest.
  - Hub clones and locks exist, and the capacity policy is in PLAN.md.
  - BTRSmith is clean (D3a), and the branch dispositions are recorded (D3b).
  - This plan, AGENTS.md and `docs/design/platform-parity.md` agree.
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
    - A fresh `make test-boundaries` log gives the record count (311 records at the October 7 snapshot; verify the current manifest) and how many are checked inside nix.
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
- **Goal.** Close the structure-first step PLAN.md calls load-bearing, and BTRSmith issue #20 (the remaining-native-code audit). Then re-pin BTRSmith, so the measured workload is final and measured only once.
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
  - `ccompat-r18-preprocessor-conditionals` (C4, approved by D19; after C1 integrates)
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
- **Depends on.** Stage 15. C4 follows C1 integration under D18 and D19.
- **Parallelization: WORKFLOW, a serial first step, then 3 lanes.**
  1. **Serial.** r02 and r06 land as one shared `_parse_body` helper used by `_parse_for_stmt`, `_parse_if_stmt` and `_parse_while_stmt`, in both compilers.
  2. **Lanes.** Each does Python first, then the btrc port by the same agent in the same commit. Each lane builds its own btrcc under the semaphore.
     - `wt/c1-decl`: r01, then r03, then r19, then r07, plus 1 read-only agent mining C headers.
     - `wt/c1-lit`: r05.
     - `wt/c1-sem`: r04.
  3. **Merge order:** refusal, r02/r06, r01, r05, r04, r03, r19, r07.
  4. **1 parity reviewer per construct** (semantics, diagnostics, ARC witnesses), reusing the lane's btrcc. C11 strictness is left to the gate.
  5. **C4 (approved by D19), after `ccompat-c1-integrate`:**
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
  - `ccompat-r12-bitfields` (approved by D19, which names the probe battery and native headers as consumers)
  - `ccompat-c2-integrate`
- **Exit.**
  - Approved C2 rows are PASS.
  - `sizeof` and `offsetof` match gcc and clang.
  - The flexible-array divergence and the misleading `{[2]=7}` diagnostic are gone.
  - No `&` is ever taken of a bitfield.
  - The memory delta is recorded.
- **Parallelization: WORKFLOW.**
  - 3 read-only spec drafters: unions, anonymous members and designators; flexible arrays; bitfields.
  - Then the serial schema commit, with 2 reviewers.
  - Then 2 lanes, because they share `ir/lowering/Aggregates.btrc`, Types and struct parsing:
    - **L1:** r09, then r08, then r10.
    - **L2:** r13, then the enum-tag fix, then r12.
  - Merge order: r09, r08, r13, enum, r10, r12.
  - 1 parity reviewer per construct.

### Stage 18: Multi-dimensional arrays, alone (approved, D19)
- **Items.** `ccompat-r17-multidimensional-arrays`.
- **Exit.**
  - A 2D corpus passes through both compilers under strict C11, and the pinned rejection tests are inverted.
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
  - `ccompat-r14-variadic-definitions` (approved by D19)
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
    - r14
  - **Merge order:** r15b, r15c, r15d, r16, stragglers, r15a, then r14 as its own batch.
- **Reconciled with Stage 20** (`c-vocabulary-specifiers.md`, `c-goto-labels.md`). The vocabulary commit reserves the goto design's schema at zero bytes: `GotoStmt(name, name_line, name_col)`, `LabelStmt(name)` (a label owns no statement), `IRGoto` and `IRLabel(falls_through)`. The pending-refusal tables hold no `goto` entry. The btrc lambda-termination parity commit (D-13) lands before this stage; r15b keeps the completion table and D-7's missing-return and lambda wording.

### Stage 20: goto and labels, alone (approved, D19)
- **Items.** `ccompat-r11-goto-labels`. `goto` is already a keyword (grammar.ebnf:38).
- **Exit.**
  - Every unsafe-path negative test gives identical diagnostics.
  - Positive cleanup programs are clean under the ARC witness.
- **Overlap.** It may **overlap Stage 19's r15c/r15d/r16 lanes**, rebasing after r15b (`_Noreturn` flow).
- **Design** (`docs/design/c-goto-labels.md`).
  - `LabelStmt(name)` is a statement-list item that owns no statement; its schema lands in Stage 19's vocabulary commit.
  - No interim message: until this stage, both parsers keep today's `goto` errors, so the probes change once.
  - Released re-initialization: a backward goto releases the owners its frame declared after the label, so each pass releases the previous pass's values, as a loop does.
  - Forward-only realtime: a backward goto is the blocking effect `backward goto 'L'`; a forward goto is effect-free.
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
- **Prerequisites (D2/D8).**
  - ≥100 GB free before this stage, with no local Windows VM, as the current D2/D8 decisions require. The former 150 GB estimate included local VM provisioning and is superseded.
  - Android SDK licences accepted by you.
  - Re-check free disk before each download.
- **Exit.**
  - The pinned NDK (29.0.14206865), SDK, a JDK and zig 0.16.0 are available in `nix develop .#platforms` (batch 16 added the shell; the default shell stays without them).
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
- **Status (batch 48, 2026-10-06).** On main: commit 1a (`CL-P1-03`, targets.toml schema 2, batch 22), 1b (`CL-P1-04`, one target owner per compiler, batch 29), the hosted-platform extractor (`CL-P1-07`, batch 31) and 1c (`CL-P1-05`, the per-row data model, environment-aware macros, M3 and per-OS release C, batch 48). Next: 1d (`CL-P1-06`, the LSP `btrc.target` setting), then the sub-batch 1 gate.
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
  - The drift test reports 19 files, 24 interfaces and 162 declarations for the frozen 2026-09-21 release (`ui0-source-inventory-2026-09-21`), pins every later source change as a reviewed amendment, and fails when a dummy method is added. On `8b73c79` the source has 20 files, 25 interfaces and 178 declarations: Codex's PR #21 (`CX-UIA-02`) pins the difference as amendments, and every later re-freeze is a new reviewed release, `CX-UIA-05` first (D27; WORKSTREAMS.md §7 Q35).
  - The catalog lives in `docs/design/native-ui-catalog.toml` (the seed, with `ui0-source-amendments.toml` and `ui0-catalog.md`) plus shard documents under `docs/design/native-ui-catalog/`, merged by subject by `tools/qualification/ui_catalog.py` and checked by `test_ui0_catalog.py`. The seed changes only through reviewed releases (WORKSTREAMS.md §7 Q36).
  - All 1,620 operation slots and 470 case slots are classified, in the ledger format.
  - 100% of BTRSmith callers are mapped.
  - The journey catalog is frozen.
  - Linux GUI tests run under both Wayland and X11.
  - 1 gate plus linux-ci.
- **Depends on.** D24, D25. Read-only mapping may start during bucket 3's gate windows. Under D27 the UI0 packets start now (WORKSTREAMS.md §2). D23 decides the Linux toolkit for UI4–UI8 only, so the UI2/UI3 Linux work stays on the SDL provider; `CX-UIA-29` ports it if D23 picks GTK4.
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
  - **E40.** The reproduction is written and recorded as failing in the catalog. It stays on a branch (D24) until its repair lands as CX-STDLIB-01 (PLAN.md, D28).
  - **GObject.** Binding parity holds and the bootstrap is byte-stable.
  - **Toolkit.** The GTK feasibility record exists, D23 is recorded, and the Linux GUI shard is green.
- **Status (batch 46, 2026-10-06).** `ui-1-feasibility-review` (`CL-UIA-09`) is recorded in [`ui1-feasibility.md`](docs/design/ui-contracts/ui1-feasibility.md): macOS AppKit and Linux SDL (X11 gating, Wayland carried) enter UI2 on both frontends; Windows, iOS and Android stay blocked. The Stage 31 exit is still open: the five-platform shell harness, E46, E47, the GObject binding, the GTK spike and D23, and the Linux GUI shard's Wayland row, which reports only until it runs green on main (`CL-UIA-11` landed in batch 50 with X11 gating).
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
  - Interface approval is already recorded below; preserve its reviewed contract. A material contract change follows the standing design-review rule.
  - E01–E04, E29, E31, E35, E39, E40 and E46 pass on macOS and Linux with sanitizers.
  - **The E40 repair lands with its Stage 31 reproduction:** 0 lost events across bursts of 4,095, 4,096, 4,097 and 8,193 events, with progress for input, rendering and close (D28: lands earlier as CX-STDLIB-01; Stage 32 re-verifies the 4,095/4,096/4,097/8,193 bursts on the UI2 provider).
  - BTRSmith idle wakeups are measured before and after.
  - Library.UI is limited to the musical surfaces.
- **Approval (batch 47, 2026-10-06).** `ui-2-contract-review` (`CL-UIA-13`): the three UI2 drafts are approved under the standing design rule in [`ui2-approved.md`](docs/design/ui-contracts/ui2-approved.md), the frozen interface diff and the operation ids the catalog gains, with the review files under `docs/design/ui-contracts/reviews/ui2/` (two feasibility reviewers, a reconciler and a parity reviewer; eight findings raised as blocking were each verified not to block and are closed by decisions in the record). The host link (`IApplication.attachHost` and its types) is provisional everywhere; the Windows, iOS and Android rows stay provisional until `CL-UIA-22`. Next: `CX-UIA-21` writes the production interface from the record, `CX-UIA-22` (macOS) and `CX-UIA-23` (Linux) stack on it, and `CL-UIA-14` lands all three atomically.
- **Parallelization: WORKFLOW, about 12 agents.**
  - **Completed design work.** The control-events, executor and lifecycle drafts and their approval are recorded above. Do not restart drafting or request the same approval again.
  - **Remaining implementation review.** Review production changes against that approved record and actual provider acceptance. Material contract changes use the standing feasibility/parity review rule.
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
  - **Then milestone by milestone, UI4 to UI7.** macOS and Linux agents, each optionally split into 2 by family, each carrying the family's accessibility and GPU work. Under D27 these provider lanes are Codex's and Claude stays the contract owner and integrator. Existing-interface repairs taken out of these lanes (CX-STDLIB-02 Grid/Stack resize, CX-STDLIB-03 Mac button alignment, CX-STDLIB-04/05) run now from PLAN.md (D28). Only new UI4–UI9 contract and feature work keeps this stage's gate. Lanes carry `btrc.toml` changes as `fragment:` commits and regenerated files as `derived:` commits (WORKSTREAMS.md §3.5); the integrator re-applies the fragments, regenerates, and lands the contract plus providers atomically. An in-flight track owns its provider directory.
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
  - Each agent (a Codex lane under D27) owns one provider directory, `GUI/{Windows,IOS,Android}`, while its track is in flight, and submits `btrc.toml` changes as `fragment:` commits and regenerated files as `derived:` commits (WORKSTREAMS.md §3.5).
  - Each moves through core, then controls and layout, then collections and services, with accessibility and GPU inside every step.
  - Contract defects go back to the single contract owner, Claude (D27).
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
  - 1 integrator (Claude) owns ApplicationSession, ApplicationView and GUIApplication. The event-loop change is serial.
  - Per-slice agents (Codex lanes under D27, in BTRSmith `codex/*` branches) work on disjoint frontend files: Library 2 (grid, picker), Settings 1, Player 2, accessibility 1 per screen.
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
  - The catalog resolves 470 of 470 case slots and 1,620 of 1,620 operation slots, and 50 of 50 core families. Those are the frozen 2026-09-21 release's counts; every slot of each later reviewed ui-operation release resolves too (WORKSTREAMS.md §7 Q35).
  - UI11 families are dispositioned.
  - A full gate.
  - **Deferred UI10 parts** (native-ui-parity.md:1142–1147): "all numeric goals on the named matrix" closes in Stage 41, and "minimum/current OS and SDK-update evidence" closes in Stage 42. The UI10 row stays open until Stage 42.
- **Parallelization: WORKFLOW.**
  - A serial script schema (Claude), then 5 per-platform driver agents (Codex lanes under D27, each owning its driver directory while in flight).
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

**October 12 scope clarification:** the historical heading and packet IDs remain
for compatibility. The macOS MVP is an intermediate milestone; the BTRSmith
installed-product/core-journey matrix includes macOS, Linux, Windows, iOS/iPadOS
and Android. Adapt interactions to the OS without dropping core outcomes.

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

The final ledger covers the compiler, standard library, native GUI and BTRSmith
on all five platform families under the October 12 scope. Missing Windows or
mobile product evidence remains an open exit, even when desktop milestones pass.

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
| Targeted read-only review or triage | Resolve a concrete question needed for delivery; reuse existing evidence. Choose the smallest useful team, avoid repeated whole-project audits, and respect measurement/resource constraints. |
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
| Shared specs | `grammar.ebnf`; `ast.asdl` plus generated code; `native_abi.asdl`; `hosted_abi.toml` plus generated code; `targets.toml` (D21; generated into the hosted-ABI modules); `intrinsic_effects.toml` (owned by the Stage 19 vocabulary owner); `src/runtime/c` plus manifest; the boundary manifest. One owner per schema commit. |
| **Derived artifacts** | No lane commits any of these: `src/stdlib/btrc.symbols`, `src/stdlib/btrc.lock`, `src/devex/lsp/catalog/generated.py`, boundary re-captures, the generated `source_count` updates, or `GUI/btrc.toml` and other `btrc.toml` exports. Lanes submit manifest fragments. |
| Hotspot files (one owner at a time) | • **Compiler:** `pipeline/ModuleUnits.btrc` with `application/modules.py`; `cli/Driver.btrc`; `pipeline/Pipeline.btrc`; `ir/Emitter.btrc`; `backend/c_emitter.py`; `syntax/Identity.btrc`; `tools/compiler_codegen/ast.py` with generated `Node.btrc`<br>• **Tools:** `tools/native_plan.py`; `tools/budget_bench.py`; `Makefile`; `conftest.py`; `flake.nix`, `flake.lock` and `nix/*`<br>• **The 97-file btrc inventory:** `test_compiler_structure_contract.py`, `docs/design/compiler-structure.md`, AGENTS.md<br>• **Docs:** `docs/design/compile-performance.md`, `separate-compilation.md`, PLAN.md, AGENTS.md. Lanes write JSON; the integrator writes the tables.<br>• **UI:** IView, IWindow and `App.btrc`<br>• **BTRSmith:** ApplicationSession, ApplicationView, GUIApplication and the Make graph |
| Parsers | `Parser.btrc` and `parser.py` are touched by every C lane, so they are not single-owner. Shared body parsing lands first, as `_parse_body`, then lanes merge in a set order and rebase. |
| Google Drive | Agents never work in the Drive checkouts or in worktrees whose gitdir lives in Drive. They work from `~/.cache/btrc/hub.git` and `~/.cache/btrsmith/hub.git`. The integrator fetches batches into Drive. Gates never run from Drive. Check `git status` at the start of every stage. |
| Disk and RAM | • **Free disk** re-checked at every stage start.<br>• **`build/test-btrcc`:** LRU prune before every wave.<br>• **btrcc builds:** the `btrcc-build` semaphore allows N=2. The integrator builds one btrcc per base SHA, and lanes pin it. That is sound unless a lane edits a compiler stdlib import (the root prelude, FileSystem, Digest, BackgroundJobs, Process, Platform, IO, JSON, TOML, Datetime, Console); such a lane builds its own and runs bootstrap.<br>• **Writer worktrees:** at most 4 before the podman shrink, 6 after.<br>• **BTRSmith clones:** 1 before the shrink, 2 after. Clean test outputs after each run, and sign behind `locks/signing`.<br>• **Guests:** the active shared Podman VM uses 28 GiB; an Android emulator uses about 4 GiB and an iOS simulator 2–3 GiB. No local Windows VM (D8). At most one beside a gate, none during bootstrap or a quiet round. Never put caches in `/tmp`. |
| GUI capture and devices | One queue per window server and per device. Devices driven through the Mac count against it, at most two at a time. Human-in-the-loop sessions are serial. |
| Authority | Only the main session pushes, after a green batch gate (D4). Agents close issues only under the standing approvals. No agent changes system settings (Spotlight, Time Machine), enters credentials, creates accounts or accepts agreements other than the Android SDK licences. Signing: agents commit unsigned, and the integrator signs when the 1Password agent is available, otherwise commits unsigned rather than stall. |
| Duplicate items | Each pair runs as one unit:<br>• `platforms-p0-matrix-pin` and `tooling-p0-toolchain-matrix`<br>• `ui-0-product-journeys` and `btrsmith-ui0-callers`<br>• `ui-4/5/6/7/9-btrsmith-*` and the matching `btrsmith-ui-slice*`<br>• `ui-10-btrsmith-mobile` and `slice5`<br>• `ui-10-automation-diagnostics` and `qualification-p5-journey-drivers`<br>• `ui-6-stress-fixture` and `qualification-catalog-fixtures`<br>• `qualification-ci-btrsmith` and `btrsmith-q-ci`<br>• `tooling-audio-loopback-rig` and `qualification-p6-audio-latency-rig`<br>• `tooling-target-debuggers` inside `qualification-p7-devtools-targets`<br>• `platforms-p4-dependency-crossbuild` and `btrsmith-package-closure` |

**Merge-batch procedure (one authorized integration owner):**
1. Fetch the lanes' unsigned branches from the hub, and rebase them in the stage's merge order.
2. Apply the `btrc.toml` fragments. Run `make compiler-codegen-generate`, re-resolve the stdlib lock, and regenerate `btrc.symbols` and the LSP catalog.
3. Re-capture boundary records with reasons, and update `source_count` and the fixture lists. Write the docs tables from the lanes' JSON. All of this goes in one merge commit.
4. Build one btrcc for the new base SHA, so the next wave can pin it. Prune `test-btrcc`.
5. Hand the batch to the main session for the D5 gate. When it is green, the main session pushes `main` (D4).
6. If the gate is green, fetch into the Drive checkout. If it is red, run D5's revert-bisect and send the culprit back to its lane.

**Codex lanes (D27, D28).** OpenAI Codex is a second builder. [`PLAN.md`](PLAN.md) is Codex's queue; [`WORKSTREAMS.md`](WORKSTREAMS.md) §3 is the claim/branch/fragment protocol, and every rule above about lanes applies to Codex lanes too.

| Codex lanes | Rule |
|---|---|
| Branches and claims | A Codex branch starts with `codex/`, one packet per branch. The claim key is the draft PR title `[CX-…]` plus the report's `Packet:` line, not the branch name. The draft PR opens against `main` with its first commit and lists the packet's owned paths first; that is the claim (WORKSTREAMS.md §3.3). |
| Draft PRs | Only for CI. Codex never merges or closes a PR, and never pushes `main`, `main-kn9jxh` or another agent's branch. Claude closes the PR after integrating it. |
| Owned paths | Each packet edits only its listed paths. Compiler sources, shared specs, generators, generated files, `src/runtime/**`, the native readers, editor tooling and the hotspot files above stay Claude's (WORKSTREAMS.md §3.3.1). |
| `fragment:` and `derived:` commits | A branch ends with up to two special commits. `fragment: <what>` carries hand-written changes to integrator-owned data (`btrc.toml` exports and native rows, expected-skip rules, denominators, Makefile lines, `ci/tiers.toml`), which Claude re-applies. `derived: regenerate` carries `btrc.lock`, `btrc.symbols` and the LSP catalog, which Claude drops and regenerates. |
| Compiler requests | A compiler, spec, runtime or hotspot change goes in the PR body as a `REQUEST(<target>)` block (WORKSTREAMS.md §3.6). Claude turns it into a packet in its next batch. |
| Batch cap | At most two Codex code branches per integration batch; docs-only branches do not count, and an atomic landing counts as one. Schedule eligible batches by the approved stack rank and actual dependencies; preserve active gate/measurement isolation. |
| Evidence | Codex proves its work in a Linux container and on GitHub runners. Mac, device and account evidence is an owner (`MAC-`) packet, and stand-in evidence is labelled stand-in (D8). |

## Ultracode recommendation

Use the [owner priorities and execution handoff](#owner-priorities-and-execution-handoff-2026-10-12),
not a fixed restart or staffing plan. "Ultracode" is the retained workflow name;
it is not proof of a selected model, plugin or CLI. The executing agent can choose
suitable available tools and independent subagents without assuming that the
agent that wrote this plan will run them.

Size the team around concrete implementation and review needs. Give each writer
an actual base revision, owned paths, bounded outcome and meaningful acceptance;
keep one writer per hotspot and one authorized integration owner. Delegate
independent work when it improves delivery, and avoid broad review waves merely
to occupy slots. Current file claims, resource limits and batch rules still apply.

"Rerun everything" means complete the required validation of the final combined
tree and resolve missing goal evidence. During development, reuse valid
source-matched results and rerun affected or unproved checks. Explain expensive
unchanged reruns, retain failures and never bypass required gates. Actual target,
OS/device and account evidence must remain correctly scoped.

The useful outputs are working capabilities on the five platforms, removed
blockers and qualified changes integrated into main. Report those changes and
remaining gaps regularly. More agents, model switches, test totals and additional
reports are not substitutes for those outcomes. Keep performance-only work at
rank 6 unless a demonstrated functional blocker requires it earlier.

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
| 16 | `ccompat-r02-braceless-bodies`, `ccompat-r06-empty-statement`, `ccompat-r01-void-unnamed-params`, `ccompat-r05-adjacent-strings`, `ccompat-r04-char-array-string-init`, `ccompat-r03-multi-declarators`, `ccompat-r19-comma-operator` (moved from 21), `ccompat-r07-function-pointer-declarators`, `ccompat-c1-integrate`, `ccompat-r18-preprocessor-conditionals` (approved by D19, after C1) |
| 17 | `ccompat-c2-schema`, `ccompat-r09-union-declarations`, `ccompat-r08-typedef-struct-anonymous-members`, `ccompat-r10-designated-init-compound-literals`, `ccompat-r12-bitfields` (approved by D19), `ccompat-r13-flexible-array-members`, `ccompat-x-enum-tag-spelling`, `ccompat-c2-integrate` |
| 18 | `ccompat-r17-multidimensional-arrays` |
| 19 | `ccompat-c3-schema-vocabulary`, `ccompat-r15a-qualifiers-storage-classes`, `ccompat-r15b-inline-noreturn`, `ccompat-r15c-static-assert`, `ccompat-r15d-alignment`, `ccompat-r16-wide-literals-long-double`, `ccompat-x-expression-stragglers`, `ccompat-r14-variadic-definitions` (approved by D19), `ccompat-c3-integrate` |
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

## Historical stage progress anchors

These links retain the old progress anchors; stage specifications and current
status above remain authoritative.

### Stage 1: pre-flight (closed 2026-09-30)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#stage-1-pre-flight-closed-2026-09-30).

### Stage 2: baselines, CI health, evidence and skip ledgers (started 2026-09-30)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#stage-2-baselines-ci-health-evidence-and-skip-ledgers-started-2026-09-30).

### Stage 3: measurement harness, peak guard, Linux-portable bench (lanes done 2026-10-01)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#stage-3-measurement-harness-peak-guard-linux-portable-bench-lanes-done-2026-10-01).

### Stage 4: structure-first drift review (wave 1 done 2026-10-01)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#stage-4-structure-first-drift-review-wave-1-done-2026-10-01).

### Stage 14: C5 inventory (done 2026-10-01, cloud lane `stage14/ccompat-inventory`)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#stage-14-c5-inventory-done-2026-10-01-cloud-lane-stage14ccompat-inventory).

### Stage 15: C1 schema commit (done 2026-10-02, main session)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#stage-15-c1-schema-commit-done-2026-10-02-main-session).

### Stage 17: C2 design (done 2026-10-02, main session)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#stage-17-c2-design-done-2026-10-02-main-session).

### Stage 16: C1 constructs (lanes integrated 2026-10-02)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#stage-16-c1-constructs-lanes-integrated-2026-10-02).

### Stages 16 (C4), 19 and 20: designs (done 2026-10-02)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#stages-16-c4-19-and-20-designs-done-2026-10-02).

### Stage 18: emission-order parity (lane `stage18/emit-order`, 2026-10-02)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#stage-18-emission-order-parity-lane-stage18emit-order-2026-10-02).

### Stage 22: P0 inventory (inventory done 2026-10-02, cloud lane `stage22/p0-inventory`; the stage stays open)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#stage-22-p0-inventory-inventory-done-2026-10-02-cloud-lane-stage22p0-inventory-the-stage-stays-open).

### Stage 22 (read-only planning, cloud lane `stage22/p0-matrix`, 2026-10-02)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#stage-22-read-only-planning-cloud-lane-stage22p0-matrix-2026-10-02).

### Stage 27: interop ownership design (design step 0, lane `stage27/interop-design`, 2026-10-02)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#stage-27-interop-ownership-design-design-step-0-lane-stage27interop-design-2026-10-02).

### Stage 24: target-contract design (lane `stage24/target-contract-design`, 2026-10-02)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#stage-24-target-contract-design-lane-stage24target-contract-design-2026-10-02).

### Two builder agents: Gate 0 (D27, 2026-10-03)

Moved to [docs/design/claude-integration-record.md](docs/design/claude-integration-record.md#two-builder-agents-gate-0-d27-2026-10-03).
