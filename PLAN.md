<a id="plan-moved-to-claudemd"></a>

# PLAN: unified btrc and BTRSmith roadmap

Updated **2026-10-08**. Read [AGENTS.md](AGENTS.md) first for architecture and
development rules.

This is the single active plan. It combines the former CLAUDE.md roadmap,
CODEX.md provider queue, and PLAN.md compatibility index. Stage numbers, packet
IDs, numeric budgets and acceptance criteria retain their meaning. CLAUDE.md and
CODEX.md are entry points with compatibility anchors, not independent queues.
The original `CX-PLAN-01` plan-split introduction remains historical provenance;
D29 governs the consolidated queue. [WORKSTREAMS.md](WORKSTREAMS.md) retains file claims and the coordination protocol;
[the integration record](docs/design/claude-integration-record.md) retains dated
batch evidence. The frozen [reference](docs/design/plan-reference.md) and every
`ref:N` line citation remain unchanged. This document has no effort or calendar
estimates: order follows demonstrated dependencies and payoff.

## Goals versus status (2026-10-08)

The owner's goals are a fast compiler across real build workloads and a usable
standard library with native GUI on macOS, Linux, Windows, iOS/iPadOS and
Android. BTRSmith is the real application used to prove the compiler and library.
Report progress against those outcomes: measured benchmark versus target,
working library features per platform, and completed application journeys.
Branch consolidation, test counts and environment repairs support those goals;
they do not by themselves demonstrate faster compilation or delivered GUI features.

**Overall:** the compiler is substantially implemented and has broad correctness
evidence. Final performance acceptance is open. Desktop GUI shells and selected
features work, while the complete desktop library and Windows/mobile providers
remain incomplete. The Windows ARM64 slice and consolidated plan are on main `cbd3ddcd`;
the broader compiler and GUI candidate is not yet qualified. There is no
defensible overall percentage complete: the remaining items have different scope
and several acceptance measurements are missing.

### Goal 1: fast compilation and bounded memory

The measurements below are the historical `65057cb` record, retained in
[the performance baseline](#recorded-performance-and-coverage-baseline).
They are not current-source measurements. Ratios describe that record's distance
from the target, not a measured regression or a forecast. Stages 5–13 define the
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
| Compiler peak footprint | ≤1.5 GiB | 2.966 GiB; aggregate build memory 4.828 GiB | Historical compiler peak roughly 2× the limit; current footprint unqualified |
| Self-compilation and full corpus | Median wall time and RSS within 5% of Stage 5 baselines, or an explained tradeoff | Current baseline/acceptance round outstanding | Unproven |
| Parallel workers and module builds | 1/2/4/8-worker wall/RSS sweep; module release ≤110% of whole-program | Current acceptance outstanding | Unproven |

The Python reference compiler also retains its own final targets: transpilation
≤60 s, cold development ≤75 s, edit median ≤10 s/p95 ≤15 s, batch ≤60 s and
peak ≤1.5 GiB. Current acceptance is missing. The paired incremental mechanism
must prove that a body edit analyzes and lowers exactly one changed source group
and does not lower unchanged groups; passing intermediate timing budgets does
not close that requirement.

**Next measurable outcomes:** qualify the current compiler/BTRSmith pin, capture
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
or performance acceptance follows from these instrumented counts.

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

### Goal 2: usable standard library and native GUI on five platforms

These rows distinguish a compiler or fixture host from an application-facing
provider. The detailed feature acceptance remains in Stages 22–37 and the
[provider implementation queue](#provider-implementation-queue).

| Platform | Demonstrated capability | Missing product capability / next demonstrable result |
|---|---|---|
| macOS | AppKit shell and selected controls; all four current shell variants complete 100-cycle/100-frame journeys with zero owned survivors | The coordination repair is on main after the affected native gate passed (327 pass, 67 expected skips). Current-compiler window/run-loop, application components and a real text-editing fixture pass separately. Complete public application/control integration, remaining activation/lifecycle, services and accessibility qualification stay open. |
| Linux | SDL shell; 100 focused Linux ARM64 provider cases pass with 100 counterfactual rows classified; repaired Wayland candidate passes dedicated checks | The shared-display repair is independently qualified on its original X11 gate: 324 passes, 199 expected platform skips and no failures/errors. Qualify the assembled tree, then land UI2 and remaining features/accessibility. Wayland remains report-only until its required main acceptance. |
| Windows | Actual ARM64 compiler build, three-stage bootstrap fixed point, compiled sample execution and MSVC ABI/wgpu adapter smoke pass at `110a514c`; all hosted workflows pass and PR53 landed on main `49f136ec` | Qualify SDK/OS service providers and demonstrate a native shell with button, editable field, events and safe teardown. These compiler/ABI passes do not establish a complete GUI provider. |
| iOS/iPadOS | Local simulator fixture host passes 50 cases | Qualify hosted and minimum-OS execution; demonstrate app-private file persistence and checked UIKit lifecycle/button/text-field providers. Host passes do not prove those providers. |
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
counted as evidence. The post-merge main Linux CI, Windows and Windows ARM64 workflows pass at exact `cbd3ddcd`. The macOS workflow still has its unit-test job running; self-host tests, bootstrap, C11 and both corpus jobs pass. Final post-merge status remains open until that workflow terminates.

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
Final combined-tree Linux qualification remains open. The original
full Wayland gate at `14f9e193` passes all 322 executed cases, with 199 expected
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

The missing method implementations now exist; qualification remains scoped to the results below.
Application provider `70df20a9` with compiler `f75c737b` passes WorkQueue,
NativeContainerBarrier and NativeCaptureFailure through both frontends, plain
and ASan/UBSan: 12 native rows, six zero-diagnostic projections, 28 strict
C/Objective-C checks and 12 links. Independent review rehashes all input/log
inventories and verifies all 180 command groups absent. Aggregate
`a54c1f28b116c6a17bb3a9caef28379341e36e4c4d8afc52bd3b1d4457e57f0f`
is retained in `ui2-macos-application-70df20a9-compiler-f75c737b`.
Public ApplicationHost has not been rerun and is not qualified by those components.

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
TOML object and allows qualification to continue; the compiler parity defect
remains open. Evidence is retained in `macos-range-current-f75-r4/METADATA-ORDER.md`
under the local audit preparation directory.

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

**Current working capability:** product `5bb466b7` with immutable compiler
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
The exact source assertion and cause are under investigation; the self-hosted
application-shutdown row and Linux product derivation/install do not complete.
The private artifact is `11554081040`, SHA-256
`9c9ed38209251a14a5ccc639dd5e3b58b0d42053118b60afa54af554e01594ee`;
artifact provenance review remains pending. Workflow revision `b383f9f2` changes
only compiler pins, artifact label and historical wording. Final combined gates
remain pending. App descendants are checked and cleaned on ordinary test failure
as well as timeout. No full MVP claim.

### Integration status in service of the goals

**Current checkpoint, October 8:** main is `cbd3ddcdb25b9c7519f2babc3dce38647b3a0212`,
which merged the consolidated plan and qualified Mac test-coordination repair
through PR69. The final PR head passed 36 selected checks; post-merge workflows
are still running. This does not merge the remaining compiler/UI2/product work.
The locally assembled candidate combines the reviewed token/reply lifetime,
GCC pointer-temporary and Linux test-coordination repairs. Its 172 affected
checks, generated-source validation, lint and formatting pass; its full matrix
and applicable native qualification remain required.

Windows PR53 previously merged on main at
`49f136ec94bb46cf67dd9bf407df6e4b0d79332c`. Its source tree is exactly the
qualified `110a514c` / hosted merge `93093bd4` tree. All five hosted workflows
passed, including actual Windows ARM64 compiler/bootstrap, sample execution and
MSVC ABI/wgpu checks. All post-merge workflows on main `49f136ec` also pass,
including Linux and macOS. The Linux full test shards, bootstrap, all eight C11 cells,
generated checks, lint, formatting, extension and release hygiene passed;
skipped standalone jobs are not counted as evidence. This independent slice did
not wait for UI2 or the remaining compiler work.

Current broader candidate `3974d47b` is published in
[draft PR68](https://github.com/schiffy91/btrc/pull/68). Its original hosted matrix has
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

### Outcome execution register

This register connects the goals to the next deliverable. Owners below are
responsible roles, not claims that a builder is currently running. The October 7
review used three read-only subagents (performance, platform/library and execution)
plus the main integrator. The October 8 implementation wave has produced the
reviewed token-lifetime candidate rebased at `71352c50`, the qualified Linux
provider repairs, and paired native BTRSmith library proof; their remaining
qualification is recorded below. Implementation assignments must also carry a live
WORKSTREAMS claim and exact base SHA. Update a row when its result or blocker
changes; historical test totals alone do not advance its status.

| Outcome | Current state / evidence | Responsible role | Next acceptance and actual blocker |
|---|---|---|---|
| Current compiler speed and memory matrix | Token candidate `71352c50` reduces the focused Linux heavy-stdlib reported peak by 8.241%. Combined lifetime candidate `92691bee` passes 164 focused checks. Whole-product targets remain unqualified | Performance owner; main session runs quiet measurements | Private current-product Linux RSS comparison `37771609277` failed during image-layer commit before compiler execution or samples. Mac quiet admission has no completed paired round. Stage 4/pin, Stage 5 and final product matrix remain open. |
| Faster incremental edits | Current tuple/instance repair proves one changed group for inventory-preserving edits and three for genuinely new shared tuple shapes, across both frontends/release/debug with strict native outputs and clean-versus-incremental equality | Incremental compiler owner | Finish current combined gates, then measure edit median/p95 and memory. Full consulted-fact/analysis reuse and Stage 9 counters remain open. Work counts are not speed results. |
| Useful desktop library improvement | Linux components pass 100 native cases plus 100 counterfactual rows; all 11 inherited-interface regressions pass. Wayland at its recorded source passes. X11 repair run `37763215278` is independently qualified: 324 pass, 199 expected platform skips, zero failures/errors | Provider repair owner; main integrator qualifies | Qualify the assembled tree with the reviewed X11 coordination repair. Keep genuine external focus-loss cancellation and original native assertions. |
| UI2 events, executor and lifecycle on desktop | macOS foundation and ordered-container components have scoped native passes. Window and capture/run-loop replay each add eight native passes on compiler `f75c737b`. Public application baseline exposes 19 missing methods | Application, text-field and range/selection owners | Implement and qualify those methods with original native assertions. Linux Window source is reviewed; its native baseline/candidate run awaits a hosted slot. Full UI2 and application quit remain open. |
| Windows and mobile application-facing services | Windows ARM64 compiler/bootstrap/sample/MSVC ABI/wgpu slice is on current main `cbd3ddcd`; mobile fixture-host results remain separate from complete providers | Platform slice owners | Prove Windows SDK/service operations and native shell; iOS/Android persistence and button/text-field/lifecycle providers. Each waits only for its own ABI/host/ownership prerequisites. |
| BTRSmith macOS/Linux MVP on the current stack | Both macOS library journeys and current-product CLI/MCP/live-agent acceptance pass against `3974d47b`. With compiler `f75c737b`, Linux paired live-agent acceptance now passes; the following audio step fails reference application shutdown. | BTRSmith owner and integrator | Diagnose and repair the unchanged shutdown assertion, complete paired audio and installed-product qualification, then qualify the product pin and remaining MVP outcomes. The full MVP remains incomplete. |
| One qualified implementation on main | PR69 consolidated plan and qualified Mac test coordination merged at `cbd3ddcd` after 36 passing selected checks. Prepared compiler/Linux repair integration passes 172 affected checks plus generated/lint/format | Main integrator | Complete final combined tests/bootstrap/C11/static/generated/extension/hygiene and applicable native evidence, then merge qualified repairs. Track UI2 and product changes separately until their acceptance passes. |

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

- [Goals versus status](#goals-versus-status-2026-10-08)
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

This is the current continuation queue. Initial inventory and plan consolidation
are done on the candidate branch; main publication and final implementation
qualification remain open. Recheck changed heads, claims and host capacity rather
than restarting completed work within Stages 1–4 or repeating entire audits.

1. **Finish the in-flight qualification and reconcile one candidate.** Retain
   the running `3974d47b` Mac unit checks; repair the X11 diagnostic artifact
   export and rerun it before choosing a provider or isolation change.
   Independently land the consolidated plan after its own gates, then combine
   the measured token-lifetime improvement and an evidence-backed GUI repair.
   Record exact terminal results and qualify that complete source tree. Failed
   checks remain explicit; focused checks do not replace final qualification.
2. **Give performance and BTRSmith their own next action.** Identify and close the
   remaining Stage 4/pin prerequisites for the D9 measurement copy. Qualify the
   current application smoke and capture Stage 5's matrix at the next passing quiet
   window. Prepare run manifests and analyze existing memory failures while the
   host is busy. A pre-Stage-4 diagnostic is permitted as labelled evidence, not
   final acceptance. Then implement the measured bottleneck and Stage B reuse with
   paired correctness and before/after evidence; never silently refresh targets.
3. **Run independent GUI delivery alongside permitted review/build work.** Continue
   from the approved `CX-UIA-21` interface and qualified macOS component snapshots.
   Complete host wiring and independent Linux provider work with actual native exits.
   `CX-STDLIB-02` precedes `04` on LinuxGrid. Recover or reconstruct unavailable
   patches; never wait indefinitely for an unverified bundle. UI2 still lands
   atomically with macOS and Linux providers after their required acceptance.
4. **Advance platform slices on their own prerequisites.** Review PR51/52 service
   contracts; build small native Windows services on landed PR53; qualify PR34's hosted/iOS 17
   cases and PR35's combined Android host. Follow each with its small service or
   GUI operation. These gaps do not block independent Mac/Linux MVP validation.
5. **Integrate, rerun and report outcomes.** For each changed packet reproduce the
   defect, apply the owner-layer fix, review and run focused regressions. Use the
   bounded batch gate and affected native checks, then the full matrix on the final
   combined tree. Update the outcome register, catalog, issue evidence and branch
   dispositions when each result lands. Report harmonized only under the completion
   contract below, with product-roadmap and physical/account gaps still explicit.

Use the [Ultracode recommendation](#ultracode-recommendation) for the bounded
subagent rerun. Parallel assignment never overrides shared-file ownership, host
locks, quiet measurement rules or CI concurrency limits.

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
| PR60, `codex/harmonize-plan` | `50bf1c8c` | Predecessor `b5e3f81a` completed with 17,664 passes, nine structural-audit failures and 168 skips. All nine are resolved by the expanded 155-check target-conditioned audit; Linux-target reference transpilation passes after the arithmetic repair. The combined run completed 17,803 passed, zero failed and 168 skipped in 1,863.14 seconds; the skip audit then failed on two Linux-only hard-limit cases, stopping before bootstrap/C11. Local `8c71dda6` adds narrow macOS classifications: 61 ledger checks pass and the retained report reclassifies with zero unexpected skips. Local `e497ac98` repairs quiet measurement orchestration; 106 combined focused checks pass. The combined local tree `a8d92cb8` has passed lint, formatting, generated-source and extension checks, and passed bootstrap in 594.69 seconds with zero skips. All eight strict-C11 configurations (GCC and Clang, -O0 through -O3) passed 2,036 checks each without skips. The serialized remaining-gate run finished successfully, including the plan and diff checks. This resumes the remaining gates; it is not a fresh full make test result. Neither repair is published yet; full final qualification remains pending. |
| PR65, `codex/integrate-c2-arrays` | `93856dfc` | Published with the AppKit comparison repair and plan. All hosted workflows are terminal: 37 successful checks and three skipped jobs (static and two native-GUI jobs). The source-matched AppKit run passed 41 tests, but the earlier restore-54 owned-field survivor remains unexplained and full integrated qualification remains open. |
| Local REQ-10/11, rich-enum and Apple availability integration, `codex/integrate-rich-enum-diagnostics` | `ba6c221d` | Apple schema and pinned tables passed 186 focused checks plus static/generated checks; semantic consumers and final integration remain open. Before `bb40e39c`, parent `9a01104c` passed 1,179 native checks with three platform skips. The first Linux cast attempt failed; the revised integer arithmetic and all-target structural audit pass their focused checks and full Linux-target reference transpilation. The earlier REQ-10/11 and rich-enum changes are integrated into the combined candidate; the Apple merge is now included in `06c3923a`; full qualification/main landing remain pending. |
| PR53, Windows ARM64 host | Merged main `49f136ec`, tested head `110a514c` | All five workflows and native ARM64 compiler/bootstrap/sample plus MSVC ABI/wgpu checks pass. Merged tree equals tested tree; archive checksum verified. Broader provider and combined-tree gates remain separate. |
| PR68, `codex/integrate-compiler-harmonization` | Published `71a22734` | Android tooling/API29/API36, Windows/native bootstrap, Linux bootstrap/release and both GUI lanes pass. General CI still running with tuple-order parity and two peak-memory regressions already failed; macOS queued. Main integration remains gated on repair and qualification. |
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
  clarification passed static CI. The authorized
  integration session owns `CL-P2-01` round 5: the final review of the round-4 findings.
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

**Use the owner's requested independent rerun with bounded subagents, beginning
at the current outcome register.** The October 7 review has one main integrator
and three read-only specialists: performance, platforms/library and execution.
"Ultracode" is the retained workflow name here; it is not proof that a particular
model, plugin or CLI has been selected. Record the actual available tool/model
when resolved; do not silently substitute one or claim a mode switch.

This session exposes four agent slots total. The larger agent counts retained in
stage designs describe work decomposition, not simultaneous runnable workers.
Batch those roles within current capacity and preserve independent reviewers.
Do not restart Stage 1, reimplement the landed daemon repair, or rerun completed
contract drafting merely to populate a new wave.

| Wave | Main session | Up to three subagent roles | Exit |
|---|---|---|---|
| Review (performed October 7) | Reconcile supported findings and update PLAN | Performance; platform/library; execution review | Goals, evidence gaps, actual dependencies and stale instructions reviewed |
| Bounded implementation pilot (next) | Integrate and schedule gates | UI2 interface writer; disjoint provider repair writer; reviewer/performance preparation | Reviewable current-source commits with narrow acceptance; elapsed work/wait/rework recorded |
| Qualification | Own exact candidate and serialized gates | Read-only evidence analysis only when host rules permit; independent remote work within CI cap | Full required combined-tree gates and affected native checks; failures become bounded owner tasks |
| Quiet performance round | Run the approved benchmark matrix | All agents paused as required by the quiet rule | Source-matched samples, instructions/footprint and goal deltas; missing samples stay unqualified |
| Product acceptance | Coordinate qualified BTRSmith pin and screen journeys | Disjoint product/provider work as prerequisites become ready | Demonstrated MVP journeys and budgets; additional platform releases tracked separately |

A writer starts only with a base SHA, owned paths, exact deliverable and regression
acceptance. One writer per hotspot; at most two code branches per integration
batch under the existing protocol. Approved interfaces retain atomic provider
landing. Use existing clones within the six-clone cap. The main session owns
integration and resource scheduling; a second integrator must not race it.

"Rerun everything" means independently review all goal areas and complete the
required validation on the final combined tree. During development, reuse valid
source-matched evidence and rerun checks affected by new changes or failures.
Record the reason for an unchanged expensive rerun; never bypass a required final
check. Platform qualification needs that platform, and a model switch does not
turn unavailable hardware or native evidence into a pass.

Measure this pilot before increasing fan-out. More independent implementation
and review may shorten delivery; serial gates, quiet windows and hardware remain
constraints. Neither agent count nor model quality has been established as the
principal delay. Apply the progress-measurement categories above and size the
next wave from accepted outcomes and measured waiting time.

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
