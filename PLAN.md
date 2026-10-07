# PLAN: unified btrc and BTRSmith roadmap

Updated **2026-10-07**. The initial reconciliation used upstream main
[`c011371b`](https://github.com/schiffy91/btrc/commit/c011371bf2cafd526348f3c6fc81f8958ddd0f9c)
(batch 50), the six initially open btrc PRs, and the remote branch inventory.
Current upstream main is `87dd60d7`. PR60 combines the `ad72af03` integration
with the `5dbf80a1` Weston backport; qualification and remaining work are
recorded below.
Read [AGENTS.md](AGENTS.md) first for architecture and development rules.

This is the single active plan. It combines the former CLAUDE.md roadmap,
CODEX.md provider queue, and PLAN.md compatibility index. Stage numbers, packet
IDs, numeric budgets and acceptance criteria retain their meaning. CLAUDE.md and
CODEX.md are entry points with compatibility anchors, not independent queues.
[WORKSTREAMS.md](WORKSTREAMS.md) retains file claims and the coordination protocol;
[the integration record](docs/design/claude-integration-record.md) retains dated
batch evidence. The frozen [reference](docs/design/plan-reference.md) and every
`ref:N` line citation remain unchanged. This document has no effort or calendar
estimates: order follows demonstrated dependencies and payoff.

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

## Navigation

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
Main remains at `87dd60d7` until
the combined tree passes its required gates. iOS and Windows ARM64 are separate
pending their native failure investigations.

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
Its updated hosted CI, macOS, Windows and Android workflows have started;
qualification of its complete tree remains pending.
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
with stdlib imports. Ruff, full btrc formatting and diff checks pass; a fresh
compiler and the same focused native suite are running. The candidate remains
unqualified pending that result and the final matrix. Merge resolution preserves
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
| Stages 26–29 | Interop ownership design exists; HTTP and Windows service revision-5 designs address their round-4 findings and pass docs/static CI. | Complete PR51/52 contract review, then implement checked service/interop providers and qualify actual target ABIs and dependency closure. |
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

1. **Reconcile safely.** Pin the base SHA, inventory every local/remote branch,
   inspect live claims, preserve evidence and recover disk. Keep main fast-forward
   only; use a hub clone outside Drive for edits and gates. No system-setting
   changes and no deletion of cited outputs.
2. **Publish one coherent plan.** Preserve all 43 stages, the 286 item map,
   D1–D28 history and provider assignments; point executable roadmap consumers at
   PLAN.md and retain CI's test-read classification. Verify links, anchors,
   item coverage and unchanged frozen reference.
3. **Resolve active compiler blockers in dependency order.** Finish `CL-C-09`
   generic/tag collisions and `CL-C-13` first-diagnostic parity before C2
   integration. Complete `CL-REQ-10/11` and rich-enum fixes only with paired
   regressions. Land the tested `CL-P1-06` candidate before hosted-ABI availability. Preserve the
   schema/writer serialization in the stage contracts.
4. **Deliver independent provider repairs.** Port `CX-STDLIB-01`…`05`, admit
   fixtures through normal drivers, and qualify both frontends. `02` precedes
   `04` because both own LinuxGrid. UI2 public-interface work remains an atomic
   interface/macOS/Linux landing; the existing-interface fixes need not wait.
5. **Finish the remaining five implementation/contract PRs.** PR42
   findings landed at `87dd60d7`; its missing native evidence stays open.
   PR51/52 require final review of their revision-5 contract corrections.
   PR53 reuses the merged Windows executor and needs real ARM64 acceptance.
   PR34's runtime-selection candidate `1844837b` passed the current local
   50-case matrix; its latest hosted run reached launch but completed zero
   fixtures. Hosted launch and the iOS 17 floor remain unqualified.
   PR35's activity-recreation repair is included in `ad72af03`, whose combined
   Android lane passed all 56 executions. Finish the
   remaining combined gates before landing it.
   Their general-provider/process-lifecycle gaps remain explicit.
   Scope-only CI is insufficient.
6. **Integrate bounded batches.** Reproduce each defect, apply the owner-layer
   fix, run focused red/green tests, inspect the final diff, then run D5 and
   required native checks. Recheck main and claims before each merge. Record
   exact source SHA, host/toolchain, commands, outcomes, skips and retained logs.
7. **Close the loop.** Update each branch/issue disposition and qualification
   row after its evidence lands. Run the final full matrix on the actual merged
   tree. Report harmonized only when the agreed integration scope is resolved;
   distinguish pending product-roadmap, physical and account requirements.

## Completion contract

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
These are the current checkpoints; the detailed status above retains the earlier
failed runs and their evidence rather than replacing them with later passes.

| Integration checkpoint | Current head | Qualification / remaining work |
|---|---|---|
| PR60, `codex/harmonize-plan` | `56909225` | All four hosted workflows passed. The earlier local `ad72af03` full matrix passed; later changes still need final-tree qualification and landing. |
| PR65, `codex/integrate-c2-arrays` | `93856dfc` | Published with the AppKit comparison repair and plan. Its four hosted workflows are running; both Android emulator jobs passed. The source-matched AppKit run passed 41 tests, but the earlier restore-54 owned-field survivor remains unexplained and full integrated qualification remains open. |
| Local REQ-10/11 and rich-enum integration, `codex/integrate-rich-enum-diagnostics` | `9a01104c` | Includes C2, safe main-stack startup, finite nullable cycles, nested payload-store refusal, deferred realtime checks and positioned diagnostics. Fresh native qualification is running after the predecessor's 20 diagnostic failures. Not yet published or merged into main. |
| PR53, Windows ARM64 host | `06870dfc` | General CI passed; the native GNU-route tiny C build still crashes before compiler/bootstrap execution. Native MSVC/wgpu evidence does not close this gap. |
| PR34, iOS host | Published `f49c5fe1`; local `1844837b` | Local 50-case matrix passed. Hosted launch completed zero fixtures; iOS 17 floor and final hosted acceptance remain open. |

One code candidate currently occupies the shared hosted CI allowance: PR65.
Recheck queued and running workflows before publishing another candidate.
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
| `stage17/c2-l1` | `4ef167af` | CL-C-09: repair generic/tag capture, typedef diagnostic order, native tag and LSP regressions; rerun paired review. |
| `stage17/c2-l2` | `2e65f7c6` | CL-C-13: fix declaration-vs-shadow diagnostic order and callee-first checks for interface/Atomic/Mutex receivers. |
| `stage18/req-ui2-bc-rich-enum-payloads` | `6ad62d2f` | Integrated through local `9a01104c` with nested payload-store repair. Native sanitizer cases passed at `2d645e27`; its inferred-global diagnostic ordering repair passed in the broader `cec4cc13` run. Final integrated qualification and owner-rebinding/shallow-struct gaps remain open. |
| `stage18/req-ui2-dg` | `1cc97ab8` | Merged locally at `cec4cc13`, with realtime checks deferred until finite generic closure. Its 20 diagnostic failures are corrected in `9a01104c`; fresh native qualification is running. |
| `stage18/req10-parity-gaps` | `e1bc5dfa` | Integrated with safe main-stack startup replacing the parked-thread fork exemption. Native single-thread startup/two-worker handoff and deep-expression parity passed in the recorded REQ-10 run; naming repair `148c3f42` and later integration are retained. Linux hard-limit paths and final matrix remain open. |
| `stage18/req11-tuple-sizeof-recursion` | `271397d3` | Integrated through local `9a01104c` with paired finite-nullable-cycle repair. Native focused run at `f3a5d3c6` passed 1,210 checks; the two corpus marker checks passed at `d2ffae69`. Final integrated matrix remains open. |
| `stage24/apple-standin-extraction` | `7b3d1195` | Review extraction workflow/evidence against hosted-ABI prerequisites; stand-in Apple data does not replace pinned-Xcode proof. |
| `stage24/apple-standin-extraction-run` | `9c0d737d` | Review extraction workflow/evidence against hosted-ABI prerequisites; stand-in Apple data does not replace pinned-Xcode proof. |
| `stage24/hosted-abi-platform-targets` | `8df5d732` | CL-P1-08: wait for CL-P1-06 and qualified extractor inputs, then review schema/generation parity. |
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
| [#14](https://github.com/schiffy91/btrc/issues/14) | Tech debt: two architecture contracts (test_lowering_architecture.py vs test_compiler_structure_contract.py) encode the same rules differently | PR60 adds the shared rule-to-check mapping and module-change procedure in [compiler structure](docs/design/compiler-structure.md#mapping-the-two-architecture-contracts); structural validation and landing remain pending. |
| [#13](https://github.com/schiffy91/btrc/issues/13) | Tech debt: reference and self-host emit different C (runtime helper layout, ~1000 lines on small programs) | Resolved by shared runtime order and the pinned full-C identity sample at `362a43b7`; 776 cases pass. |
| [#12](https://github.com/schiffy91/btrc/issues/12) | Tech debt: emitted C depends on temp numbering through the 1000-character wrap rule | Paired compiler regression and relevant C/IR stage |
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
in WORKSTREAMS §3.3. D29 governs integration authority for this session.

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
opening each implementation branch. Existing unpublished source revisions below
are preserved in the Codex workspace and recovery bundles; they are not yet
remote branches or merged code. Publish reviewable repair commits with their tests.

| Unit | Outcome and scope | Starting evidence | Remaining acceptance |
|---|---|---|---|
| CX-STDLIB-01 (from UIA23) | Retain queued input; match popup hit testing to painted position; preserve text/selection on clipboard Cut failure; honor external hide/show rendering | `d6df2cb6335e122526204f0408602aeef6d31b66`; 84 native cases across staged revisions, plus final controls | Port to current main, wire normal driver, rerun both compilers and sanitizer/control cases on final source; catalog: a new `evidence/ui2-linux-e40.toml` shard plus the E40 hunk in `cases/E25-E47.toml`, carried per WORKSTREAMS §3.3 step 4 ([catalog README](docs/design/native-ui-catalog/README.md)) |
| CX-STDLIB-02 (from UIB26) | Grid and both Stack orientations invoke child layout so scroll offsets clamp after resize | Combined `0f6f3448967720480365d43980c74baf7280b7e4`; 40/40 final-source native cases | Port combined repair, wire normal driver, verify actual pixel/offset behavior and fixture discovery |
| CX-STDLIB-03 (from UIB18) | Explicit Mac button alignment survives title/symbol updates; defaults preserved | `f6071c8aa1c42998fd1db3266d078285798299af`; source reviewed/formatted only | Wire actual AppKit fixture; compile and execute on macOS through both compilers; no native pass yet |
| CX-STDLIB-04 | Reject an invalid Linux grid replacement without losing the old child | Source finding: Linux detaches before validating; Mac validates/rolls back | Reproduce with an already-parented replacement; check old child identity/rendering, valid replacement, null clear and ownership cleanup; fix only after reproduction |
| CX-STDLIB-05 | Keep scrollbar geometry valid in a tiny viewport | Source candidate: 24-point minimum thumb can exceed available track | Reproduce at small/normal sizes, overflow/non-overflow and actual pointer/pixel behavior; no executed failure or fix claimed |

### Repair files and test admission

CX-STDLIB-01 production files are
`src/stdlib/GUI/Linux/{LinuxApplication,LinuxSelect,LinuxTextField,LinuxWindow}.btrc`.
Its existing event fixture is under `src/tests/native/gui/linux/`; the other probes
are under `src/tests/native/gui/ui2/probes/linux/`. Move the existing collector into
`src/tests/python/test_native_ui_linux_spike.py` with the established platform,
native-reader and display guards; remove the old collector to avoid duplicate
unguarded collection. The historical `spike` spelling does not relax acceptance.
Its catalog update is the new `docs/design/native-ui-catalog/evidence/ui2-linux-e40.toml`
shard plus the E40 hunk in `docs/design/native-ui-catalog/cases/E25-E47.toml`.

CX-STDLIB-02 owns `src/stdlib/GUI/Linux/{LinuxGrid,LinuxStack}.btrc`, the existing
`src/tests/native/gui/layout/linux/{LinuxGridScrollResize,LinuxStackScrollResize}.btrc`
fixtures and `src/tests/python/test_native_ui_layout_resize.py`. Use the combined
repair rather than applying both the original Grid-only and combined patches.
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
| Windows | Recheck the smallest real SDK import, then Toolhelp/process thread count | Historical SDK reads succeeded but both compilers rejected a qualified function type in eight architecture/frontend cases. Recheck with current compilers; request the narrow paired codec repair if still failing. Preserve ABI qualifiers. Use real x64/ARM64 execution. |
| iOS/iPadOS | App-private file create/write/read and relaunch persistence through both frontends | Actual iOS target/provider/cache selection, required nongeneric Foundation ownership/calls, filesystem seam and a real Xcode simulator host. Full UIKit widgets are not prerequisites for this service. |
| Android | NativeActivity host execution, then app-private file create/write/read and relaunch persistence | NDK/SDK, correct target/provider selection, trusted host-derived roots, filesystem seam and emulator execution. Initial private roots need not wait for the complete Java UI/JNI stack. |
| Each mobile GUI | Lifecycle, one native button and one editable field with events and safe teardown | Checked UIKit/main-executor adapters on iOS; checked JNI/Looper/callback ownership on Android. GPU embedding and richer collection controls are subsequent milestones. |

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
  `3850ce35`, address the round-4 findings and have green docs CI. Contract
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
- **PR53, `CX-P1-03` Windows ARM64 toolchain** (`codex/cx-p1-03`,
  published head `06870dfc`). Owner: this authorized integration session.
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
  The qualification command, pinned toolchain, Job containment and deadlines
  are unchanged; diagnostic success cannot turn the original failure green.
  Updating this existing PR stays within the two-active-code-PR allowance.
  Remaining acceptance: byte-identical three-stage native bootstrap and C
  from cross/native compilers, plus the complete native lane on the final head.
- **PR34, `CX-P1-04` iOS simulator test host** (`codex/cx-p1-04`,
  published head `f49c5fe1`, local candidate `1844837b`). Main `87dd60d7` is merged into the branch. The UIKit app entry now has a responsive
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
  **PR52, `CX-P2-01` Windows services design** (revision 5 `3850ce35`).
  Both are refreshed onto main with green docs/static checks. The authorized
  integration session owns the final review of the round-4 findings.
  - HTTP now requires provider-owned `Connection: close` on Android requests
    and redirects, bounded admission while native I/O drains, and hermetic
    Windows revocation fixtures. Review those guarantees before implementing
    the provider; no native transport has been qualified by this prose change.
  - Windows services now specify post-COMMIT outcomes independent of ACK,
    generated metadata ownership, operation-aware lock errors, a permanently
    registered console trampoline, owned supervisor stdio, and portable/POSIX
    Daemon corpus separation. `3850ce35` also corrects the obsolete fixture-list
    reference to the derived `include_fixtures()` owner.
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
| D27 | **Two builder agents (Claude and Codex); early UI work** | **Amended by D28 (2026-10-06):** D28’s independent-slice rule and D29’s unified plan govern the provider queue. Existing-interface repairs and per-platform slices do not wait on the Stays-gated shell or Stage 33/34 bullets. Codex creates no workflow file; Claude adds lane workflows.<br>**Status.** In force 2026-10-03: the owner asked for the Claude/Codex split and started Codex on it. The owner may strike any clause; work under a struck clause takes no new packets, and its in-flight packets finish or park. Stage 24's early start (the last clause's first bullet) was approved on 2026-10-03, when the owner asked for all the UI work, iOS, iPadOS and Android included, to run in parallel (WORKSTREAMS.md §7 Q2).<br>**Roles.** Claude (the main session) stays the integrator and the one contract owner D6(c) asks for. It alone changes the compilers, shared specs, generators, generated files, `src/runtime/**` (`c/`, `gpu/`, `windows/`), the native readers, editor tooling (`src/devex/**`, except a file a Codex packet names while no C-track packet holds it) and the hotspot files (Makefile, `flake.nix`, `flake.lock`, `nix/*`, `conftest.py`, `runner_capabilities.py`, `native_plan.py`, `budget_bench.py`, `ci.yml`, `macos.yml`, `windows.yml`, PLAN.md, AGENTS.md). It also applies the integrator-owned data (`btrc.toml` manifests, expected-skip manifests, denominators, `ci/tiers.toml`), which Codex changes only through `fragment:` commits. It approves and freezes every contract, merges every branch and pushes `main`. Codex (OpenAI) is a second builder. It owns stdlib platform providers and UI (`GUI`, `UI`, `Tray`, `App`, except their `btrc.toml`), OS-service providers that need no compiler change, test hosts, packaging and host tooling in `tools/` directories it owns, the lane workflows it creates, fixtures, examples, evidence harnesses and their docs, and the BTRSmith UI slices. It may draft UI contracts as the single designated writer chain. A draft becomes a contract only when Claude approves it under the standing design rule. Codex files a request for any compiler, spec or runtime change, and Claude turns it into a packet. Owner steps are `MAC-` packets, one command each.<br>**Mechanics.** `WORKSTREAMS.md` assigns the packets and their paths. Codex works on `codex/…` branches, claims a packet with a draft PR titled `[CX-…]` that carries a `Packet:` line, opens draft PRs to `main` only to get CI, and never merges. Claude integrates at most two Codex code branches per batch into `main-kn9jxh`. Docs-only branches do not count, and an atomic landing (UI2, UI3, a Stage 34 landing, a Stage 35 track milestone, the Windows FileSystem/Process landing) counts as one. Claude runs D5 and pushes per D4. The parity rule is unchanged.<br>**Amends D1.** D1 still orders Claude's work and the gate queue, except for the early starts named in the last clause. A Codex packet may run ahead of its bucket when its dependencies are met on `main`, or when it is planning or spike work, and it changes no file on Claude's list. Codex batches never displace a bucket 1–3 batch or a quiet window.<br>**Amends D6(c).** The bucket 3–4 platform lanes may be split between the two agents. There is still one contract owner (Claude), and one writer at a time per hotspot. IView, IWindow and `App.btrc` form one Codex writer chain.<br>**UI work that starts now:**<br>• UI0: the focused GUI gate, the catalog and drift test, the host matrix, the BTRSmith caller map and the headless Wayland/X11/AT-SPI tooling;<br>• the native-shell fixture and its macOS and Linux-SDL proofs;<br>• docs-only drafts of the UI2 and UI4–UI9 contracts;<br>• spikes that merge only a findings note: GTK4/WebGPU in plain C, Win32/UIKit/Android shell notes, the collection data model, accessibility bridges;<br>• the 100,000-row fixture generator.<br>**Starts as soon as its in-stage dependencies land,** without waiting for buckets 2–3 to close: the macOS and Linux-SDL halves of UI1–UI3 and the tray (Stages 31–33). UI2 and UI3 approvals are provisional for Windows, iOS and Android until `CL-UIA-22` re-checks them on the real shells. A change then is a versioned contract change, landed atomically with macOS and Linux. If D23 picks GTK4, `CX-UIA-29` ports the Linux UI2/UI3 core to GTK4 before the Linux UI4 work.<br>**Stays gated:**<br>• any portable-contract edit before its packet is approved; such edits land atomically with both reference providers;<br>• the btrc-hosted GTK4 spike and D23, which come after interop step 7 (`CL-P2-24`) and the GObject binding (step 8);<br>• the Windows, iOS and Android shells and UI tracks (Stages 23–29 first);<br>• Stage 34–37 provider work, which waits for the Stage 33 landing, the five shells and `CL-UIA-22`;<br>• BTRSmith screen migration, which waits for its btrc landing and pin bump;<br>• every compiler, spec and runtime change the last clause does not name;<br>• Mac, device and account evidence (D8).<br>**Codex stdlib code while bucket 2 runs:**<br>• no `#if`, `#ifdef` or `#undef` in `src/stdlib` until C4 lands; after that, only conditions valid on every target, and never `#undef`;<br>• no struct member spelled `T[] name` (write `T* name`);<br>• no `volatile T*`;<br>• import every btrc type spelled `struct X`, `union X` or `enum X`;<br>• no identifier that C3 reserves (`inline`, `restrict`, `va_arg`, `_Alignas`, …).<br>Codex stdlib branches are re-gated after C4, r09, r13, the C3 vocabulary commit and r15a.<br>**Claude may also start early** (each item an explicit amendment of D1):<br>• Stage 24 (`CL-P1-03`…`15`) and Stage 25's compiler packets (`CL-P1-16`…`20`), once C4 lands (`CL-C-06`). They interleave with C2/C3 by hotspot, never beside `CL-C-07` or `CL-C-23`, and `CL-P1-05` never beside `CL-C-25` or `CL-C-30`. Interop (`CL-P2-05`…`24`), the GObject binding (`CL-UIA-06`…`08`) and `CL-UIB-16` wait for bucket 2's close (`CL-C-40`);<br>• bucket-1 preparation that measures nothing: the runbook kit, the Stage B key and journal spec, never-merged floor spikes, reference attribution tooling and the host manifests (the x86_64 workflow waits for D7's probe);<br>• Stage 38 CI on runners that already exist: the macOS hardware skip tier, BTRSmith Linux CI and CI tiers;<br>• the BTRSmith UI2 subscriptions and Library.UI split (`CL-UIA-15`…`18`) once UI2 lands, because bucket 1 measures the D9 BTRSmith copy pinned by `CL-R-01`, never BTRSmith `main`. |
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

**Where more lanes help (campaign scheduling, subject to active session capacity).** Implementation-bound stages (16–19, 25, 28, 34–36) do get shorter with more lanes. Each stage therefore has **one integrator sub-agent** running the scripted merge-batch procedure below. The main session stays coordinator and gate runner.

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
    - BTRSmith clones are capped at 1 until the podman shrink is done, and at 2 afterwards.
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
- **Prerequisites (D8).**
  - ≥150 GB free or an external SSD.
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
  - You approve the interface diff.
  - E01–E04, E29, E31, E35, E39, E40 and E46 pass on macOS and Linux with sanitizers.
  - **The E40 repair lands with its Stage 31 reproduction:** 0 lost events across bursts of 4,095, 4,096, 4,097 and 8,193 events, with progress for input, rendering and close (D28: lands earlier as CX-STDLIB-01; Stage 32 re-verifies the 4,095/4,096/4,097/8,193 bursts on the UI2 provider).
  - BTRSmith idle wakeups are measured before and after.
  - Library.UI is limited to the musical surfaces.
- **Approval (batch 47, 2026-10-06).** `ui-2-contract-review` (`CL-UIA-13`): the three UI2 drafts are approved under the standing design rule in [`ui2-approved.md`](docs/design/ui-contracts/ui2-approved.md), the frozen interface diff and the operation ids the catalog gains, with the review files under `docs/design/ui-contracts/reviews/ui2/` (two feasibility reviewers, a reconciler and a parity reviewer; eight findings raised as blocking were each verified not to block and are closed by decisions in the record). The host link (`IApplication.attachHost` and its types) is provisional everywhere; the Windows, iOS and Android rows stay provisional until `CL-UIA-22`. Next: `CX-UIA-21` writes the production interface from the record, `CX-UIA-22` (macOS) and `CX-UIA-23` (Linux) stack on it, and `CL-UIA-14` lands all three atomically.
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
| Shared specs | `grammar.ebnf`; `ast.asdl` plus generated code; `native_abi.asdl`; `hosted_abi.toml` plus generated code; `targets.toml` (D21; generated into the hosted-ABI modules); `intrinsic_effects.toml` (owned by the Stage 19 vocabulary owner); `src/runtime/c` plus manifest; the boundary manifest. One owner per schema commit. |
| **Derived artifacts** | No lane commits any of these: `src/stdlib/btrc.symbols`, `src/stdlib/btrc.lock`, `src/devex/lsp/catalog/generated.py`, boundary re-captures, the generated `source_count` updates, or `GUI/btrc.toml` and other `btrc.toml` exports. Lanes submit manifest fragments. |
| Hotspot files (one owner at a time) | • **Compiler:** `pipeline/ModuleUnits.btrc` with `application/modules.py`; `cli/Driver.btrc`; `pipeline/Pipeline.btrc`; `ir/Emitter.btrc`; `backend/c_emitter.py`; `syntax/Identity.btrc`; `tools/compiler_codegen/ast.py` with generated `Node.btrc`<br>• **Tools:** `tools/native_plan.py`; `tools/budget_bench.py`; `Makefile`; `conftest.py`; `flake.nix`, `flake.lock` and `nix/*`<br>• **The 97-file btrc inventory:** `test_compiler_structure_contract.py`, `docs/design/compiler-structure.md`, AGENTS.md<br>• **Docs:** `docs/design/compile-performance.md`, `separate-compilation.md`, PLAN.md, AGENTS.md. Lanes write JSON; the integrator writes the tables.<br>• **UI:** IView, IWindow and `App.btrc`<br>• **BTRSmith:** ApplicationSession, ApplicationView, GUIApplication and the Make graph |
| Parsers | `Parser.btrc` and `parser.py` are touched by every C lane, so they are not single-owner. Shared body parsing lands first, as `_parse_body`, then lanes merge in a set order and rebase. |
| Google Drive | Agents never work in the Drive checkouts or in worktrees whose gitdir lives in Drive. They work from `~/.cache/btrc/hub.git` and `~/.cache/btrsmith/hub.git`. The integrator fetches batches into Drive. Gates never run from Drive. Check `git status` at the start of every stage. |
| Disk and RAM | • **Free disk** re-checked at every stage start.<br>• **`build/test-btrcc`:** LRU prune before every wave.<br>• **btrcc builds:** the `btrcc-build` semaphore allows N=2. The integrator builds one btrcc per base SHA, and lanes pin it. That is sound unless a lane edits a compiler stdlib import (the root prelude, FileSystem, Digest, BackgroundJobs, Process, Platform, IO, JSON, TOML, Datetime, Console); such a lane builds its own and runs bootstrap.<br>• **Writer worktrees:** at most 4 before the podman shrink, 6 after.<br>• **BTRSmith clones:** 1 before the shrink, 2 after. Clean test outputs after each run, and sign behind `locks/signing`.<br>• **Guests:** the active shared Podman VM uses 28 GiB; an Android emulator uses about 4 GiB and an iOS simulator 2–3 GiB. No local Windows VM (D8). At most one beside a gate, none during bootstrap or a quiet round. Never put caches in `/tmp`. |
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

**Codex lanes (D27, D28).** OpenAI Codex is a second builder. [`PLAN.md`](PLAN.md) is Codex's queue; [`WORKSTREAMS.md`](WORKSTREAMS.md) §3 is the claim/branch/fragment protocol, and every rule above about lanes applies to Codex lanes too.

| Codex lanes | Rule |
|---|---|
| Branches and claims | A Codex branch starts with `codex/`, one packet per branch. The claim key is the draft PR title `[CX-…]` plus the report's `Packet:` line, not the branch name. The draft PR opens against `main` with its first commit and lists the packet's owned paths first; that is the claim (WORKSTREAMS.md §3.3). |
| Draft PRs | Only for CI. Codex never merges or closes a PR, and never pushes `main`, `main-kn9jxh` or another agent's branch. Claude closes the PR after integrating it. |
| Owned paths | Each packet edits only its listed paths. Compiler sources, shared specs, generators, generated files, `src/runtime/**`, the native readers, editor tooling and the hotspot files above stay Claude's (WORKSTREAMS.md §3.3.1). |
| `fragment:` and `derived:` commits | A branch ends with up to two special commits. `fragment: <what>` carries hand-written changes to integrator-owned data (`btrc.toml` exports and native rows, expected-skip rules, denominators, Makefile lines, `ci/tiers.toml`), which Claude re-applies. `derived: regenerate` carries `btrc.lock`, `btrc.symbols` and the LSP catalog, which Claude drops and regenerates. |
| Compiler requests | A compiler, spec, runtime or hotspot change goes in the PR body as a `REQUEST(<target>)` block (WORKSTREAMS.md §3.6). Claude turns it into a packet in its next batch. |
| Batch cap | At most two Codex code branches per integration batch; docs-only branches do not count, and an atomic landing counts as one. Codex batches never displace a bucket 1–3 batch or a quiet window. |
| Evidence | Codex proves its work in a Linux container and on GitHub runners. Mac, device and account evidence is an owner (`MAC-`) packet, and stand-in evidence is labelled stand-in (D8). |

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
