# CX-UIA-22: approved UI2 macOS provider

Packet: CX-UIA-22. Branch: `codex/ui2-macos-provider`.
Owner: Codex under the integrator's D29 assignment.
Base: `db269d6cbd9ede0c4f3e06406bdc17cb14928248`.
Exact owned provider/probe/driver paths are reserved in WORKSTREAMS.md §3.3.2.

The approved `ui2-approved.md` record governs the 53 operations, common-mode
source/timers, bounded worker publication, control events, revisions, cancellable
close and lifetime rules. No redesign, portable interface changes or compiler
work belongs to this packet. UI2 lands atomically with the Linux provider and
portable interface; incomplete providers are not shippable stubs.

## Recovered dependencies

Reused original source commits a809416b, 55b2dc52 and d44fad90 as 058dba01,
b29c2099 and 6fc9fc54. The only cherry-pick conflict restored the absent
CX-UIA-21 report. All portable interfaces/facade, BackgroundJobExecutor,
BackgroundJobs README, native fault fixtures, portable UI2 fixtures and
BackgroundJobs driver compare byte-identical with preserved ca4782e1.
This includes sticky cancellation and explicit native retry, qualified by the
prior 26 paired/sanitized BackgroundJobs cases, as recorded in its report.
No previous qualification is claimed for new provider behavior.
The ca4782 catalog amendment remains integration-owned and is not duplicated
here. Binding data will be an explicit final fragment; generated output is
reserved for the integrator. Current button-alignment and lifecycle repairs
come from the db269d6c base and must remain intact.

## Source baseline and proof plan

Current MacOSRunLoopSignal wakes via main-thread-only NSNotificationQueue in
default mode. MacOSApplication posts one performBlock per work item and uses
default-mode timers. They cannot implement approved worker-safe common-mode
publication. MacOSTextField.text calls validateEditing, so a getter can affect
editing; setText compares live draft rather than accepted baseline. Existing
providers lack the frozen UI2 methods. These are inspected source gaps, not
executed native red results.

Add meaningful fixture-only checkpoints using real provider entry paths before
each implementation owner. Native acceptance requires both frontends, plain and
ASan/UBSan, portable shared oracles plus real macOS probes, actual active/key
context for keyboard rows, zero-owned cleanup and unchanged approved E40 limits.
The observed loginwindow foreground currently prevents local GUI qualification.
No unlock, permission or system-settings change is requested.

Inspection/recovery began 2026-10-08 at approximately 01:44 UTC. Source/static
work proceeds while Linux owns the native lane; no compiler/native/GUI execution
has run for this packet. Execution and wait intervals will be recorded when the
integrator allocates qualification. Implementation and all new evidence pending.

## Fixture-only worker wake checkpoint

`RunLoopWake.btrc` uses the existing MacOSRunLoopSignal API from a real spawned
worker, then enters the real default or tracking CF run-loop mode with no polling
timer. It requires one UI-thread callback in each mode and no callback after
scope cancellation. The probe installs no source or common-mode membership on
the provider's behalf. The dedicated native driver selects both frontends and
plain/sanitized builds through existing fixtures, records stdout/stderr and uses
the common AppKit execution marker. Ruff and canonical BTRC formatting passed.
This checkpoint is deliberately before provider edits. Native red has **not**
run: the Linux qualification owns the lane. The expected baseline failure is
current wake() rejecting the worker thread; execution must confirm it when the
integrator grants a slot. No native or E04 pass is claimed.

The driver was renamed to `test_native_ui_core_macos.py` after verifying the
canonical `test_native_ui_*.py` discovery at Makefile:344. This is a fixture-only
follow-up to e968c459, whose original red candidate remains retained. The
`macos_gui` marker is present; the integrator owns adding the final execution
function inventory at atomic landing. No Makefile exception is needed.

A second fixture-only checkpoint adds `RunLoopDeadline.btrc`: one monotonic
deadline must wake each real native mode, never early or inline; replacement,
disarming and close must suppress superseded callbacks. It shares the actual
native driver and probe. This extends the internal signal with the deadline
contract the provider needs, without adding portable operations. The old owner
has no deadline API, so semantic compilation is expected to fail until the
implementation and native binding fragment are present. Native red is pending.

## Shared private semantic dependency

The integrator assigned `GUI/ControlEventQueue.btrc` to the Linux/shared owner.
Its exact cd5530af bytes are reused here without modification. It supplies typed
channels, reserved terminal tickets, ordered replacement barriers, retirement
and channel migration between a detached queue and window queues. The macOS
provider owns native capture, wake, budgets and lifecycle admission only. This
dependency has source/static review only; generic instantiation and behavior
remain unqualified until the shared fixtures execute.

`RunLoopLifetime.btrc` adds a fixture-only checkpoint for scope cancellation and
source close initiated inside delivery (both must remain PENDING until return),
300 slot-reuse cycles, 100 worker-wake/close races and 300 real CF source-factory
failures. A test-only dyld interposer fails one native acquisition after the
provider has acquired registry/POD storage; the fixture verifies the fault was
consumed and that subsequent sources still work. The provider is not replaced
by a model or copied helper. The driver retains native fault-build diagnostics.
These fixtures are source/static checked only; no native result is claimed.
The final marked execution function is `test_ui2_native_run_loop_modes`.

## Common-mode source implementation checkpoint (unqualified)

The source draft replaces NSNotificationQueue transport with one version-0 CF
source registered in common modes, explicitly including AppKit tracking. Worker
wake takes only a short native mutex around source signalling and wakeup. The
raw context contains POD and a bounded UI-registry slot; the worker never
accesses that registry or retains/releases a managed callback. A UI-only
CallbackContext pins receiver entry, and an OwnedClosure owns raw-state cleanup.
The registry has 256 reusable source slots; source invalidation and receiver
cancellation must complete before slot reuse and final UI release. UI ownership
must retain each signal until all producers have retired.

A single armed common-mode CF timer replaces the requested deadline. The clock
is CACurrentMediaTime, converted to monotonic nanoseconds; the native alarm's
civil-time input is a wake hint, and delivery rechecks the monotonic deadline.
An early alarm is rearmed, a due alarm signals the source after the timer callback,
and disarming/close invalidates the timer. Native timer allocation failure is
sticky and wakes the source so the future executor can record orderly failure.
There is no polling timer or performBlock per work item.

Internal requestClose/pollClose close ingress before draining the receiver and
return PENDING when initiated inside delivery. Existing void close remains only
for legacy owners that already canceled/drained their scope; new UI2 lifecycle
callers must use the nonblocking pair. Polling never starts cancellation.
Canonical BTRC formatting and git diff --check passed. Native binding projection,
semantic compilation, actual fault interception and both-frontends plain/
sanitized fixtures are **not run**; these source checkpoints are not an E04,
E30, E31 or E40 qualification. Scheduler, publisher and full provider integration
remain unfinished, and atomic UI2 landing is still blocked on them and evidence.

The final integrator binding fragment must add these symbols to the existing
MacOS.MacOSRunLoop binding (retaining its callback interface until consumers
are migrated), and add that module to QuartzCore frameworks:

```text
CFRunLoopSourceContext, CFRunLoopSourceRef, CFRunLoopRef,
CFRunLoopGetMain, CFRunLoopSourceCreate, CFRunLoopSourceSignal,
CFRunLoopSourceInvalidate, CFRunLoopWakeUp, CFRunLoopAddSource,
CFRunLoopAddCommonMode, CFRelease, kCFRunLoopCommonModes,
btrcMacOSTrackingRunLoopMode,
CFRunLoopTimerContext, CFRunLoopTimerRef, CFRunLoopTimerCreate,
CFRunLoopAddTimer, CFRunLoopTimerInvalidate, CFAbsoluteTimeGetCurrent,
CACurrentMediaTime
```

This is a source requirement list, not a generated catalog or verified reader
projection. The source/fault fixture qualification will determine the exact
accepted reader rows before the final fragment is committed.

## Scheduled-work baseline fixture

`WorkQueue.btrc` directly exercises the provider-owned scheduler that will replace
per-item performBlock dispatch: future/immediate work share capacity, cancellation
releases capacity, handlers are never inline, self-posted work waits for a fresh
round, suspended cancel rejects, deferred work remains charged, and keyed
replacement retires one superseded receipt. This fixture-only checkpoint precedes
MacOSExecutor.btrc. Its native compilation/execution remains pending; the new
internal owner is absent at baseline. It supplements, rather than replaces, the
required public IApplication host and real-loop acceptance journeys.

## Scheduled-work source checkpoint (unqualified)

MacOSExecutor.btrc now contains MacOSWorkQueue and its scoped admitted-work
record. Immediate and delayed calls share the same capacity while queued,
executing or suspended. Cancellation releases the receiver through CallbackContext
and wakes the native source to reconsider the deadline. Each scheduling round
uses an admission-sequence watermark, so a self-posted call waits for another
round. Replacement stops at ordered/executing barriers; cancel/defer/replace
suspension behavior and bounded receipt-disposition counters are explicit.
Cancellation during an entered receiver stays PENDING until return. The queue
never closes its shared native signal or enters a loop.

This is scheduler storage/admission code, not the complete fair executor: native
turn count/time budgets, publisher rotation, host attachment, application/window
cleanup and public MacOSApplication wiring remain to implement. The new owner
also needs its own native NSThread binding row in the final fragment. Canonical
formatting parsed it; native projection, generic/semantic compilation and actual
WorkQueue fixture execution remain pending.

Shared semantic dependency is advanced byte-for-byte to 798e3fd0: this retains
queued terminal credit until record retirement and contains false/throwing
post-admission wake failures without reporting an ambiguous rejection. The
shared owner supplied the correction and its fixture; this provider does not
fork that implementation. Behavior qualification is still pending.

## Continuation checkpoint

Latest source checkpoints: native wake/deadline ownership 52277adf, scheduler
admission/retirement fbb98b09, shared queue dependency 978f46c8 (exact upstream
798e3fd0). All are unpublished. Fixture-only checkpoints remain e968c459,
d886048d, 43cd1abf and f86484a7. Four fixture choices × two frontends × two
sanitizer variants give 16 planned Mac rows, not executed results. The final
function name is test_ui2_native_run_loop_modes. The integrator owns exact
collection/skip admission and the native binding fragment. A test-only export
of the private shared queue is assigned to its owner in GUIProviderRoot; it
must never become a production export.

Next implementation dependencies: qualify the CF projection and scheduler
instantiation under an allocated native lane; compose publisher/host/fair-turn
execution into MacOSApplication; then connect view/window state and all control
channels. The planned state ownership matches Linux: an application context
owns the terminal pool and detached queue, windows own semantic queues, views
carry copied inherited eligibility with no child-to-parent ARC backreference,
and state-observation admission differs from domain-input eligibility. Native
text delegates, keyed selection, slider capture, scroll observation, batch
rollback, close transactions and retained image concurrency remain unfinished.
No final UI2 provider, benchmark, GUI acceptance, or main integration is claimed.

## Publisher fixture-only checkpoint

`Publisher.btrc` uses a real worker to fill a two-record native publisher before
any UI delivery. It checks explicit FULL, cancellation, unknown identity versus
already-terminal identity, keyed supersession, fresh-generation retirement,
suspension and cancellation from inside an entered receiver. Fixed disposition
counters must conserve seven admitted receipts with no pending work. The class
does not exist at this fixture-only checkpoint; actual compiler/native red
remains pending the allocated lane and native-binding fragment.

Shared dependency now matches 5f2cc694 exactly: IControlEventChannel provides
private erased rebind/cancellation routing, and terminal-pool-wide identities
plus pool validation prevent cross-window ticket collisions. These changes
come from the shared owner; no public interface or production export changes.

The publisher fixture additionally places cancel-policy work behind a deferred
head before suspension. Cleanup must retire that canceled receipt without
delivering/reordering the deferred record or leaving a permanently runnable
cleanup wake. This remains a fixture-only checkpoint before publisher source.

## First native projection corrections

Parent-owned source projection retained the actual Objective-C binding rejection:
C functions and records require a separate C-language binding. The approved
existing mixed-binding design now has RunLoop.h declare CF/CABase symbols and
RunLoop.m own only the tracking-mode bridge. The native probe follows the same
C-declaration/Objective-C-source split. The final manifest remains integrator-owned.
The next projection reached a real BTRC static-initializer error; the UI-only
registry now lazily initializes nullable storage, and the source constructor
uses a non-null local OwnedClosure for context construction. No compiler rule
was relaxed. Five fixture choices yield 20 planned paired/sanitized rows; none
of these new UI2 rows has executed yet.

Publisher fixture now also calls a false-returning and a throwing host from a
real producer. Both faults occur after admission: the producer must receive
ACCEPTED, subsequent ingress is closed, UI service reports the wake failure,
and cancellation retires exactly one FAILED receipt without callback delivery.
This source-only fixture precedes the publisher implementation commit; no
executed red/native result is claimed.

## Interaction state fixture-only checkpoint

The private state-owner regression requires immutable revisioned snapshots,
no initial replay, hidden/disabled state observation while domain admission is
ineligible, unchanged-state no-op, exposure independent of eligibility, and
queue rebind retiring stale records while same-window movement preserves the
generation. It exercises the shared semantic queue with a real native wake
source; actual native controls and subtree wiring remain a separate next step.
Six fixture choices mean 24 planned rows, all still unexecuted.

Parent's retained SDK reference projection successfully transpiles RunLoopWake,
RunLoopDeadline and (after the shared 818e9ee0 generic correction) WorkQueue
without diagnostics. This is frontend evidence, not C compilation or native
execution. The Lifetime projection correctly rejected Atomic owners embedded
in a shallow-copyable C struct: that fixture now borrows two AtomicBuffer cells
retained until the worker joins. Publisher atomics are direct fields of the
UI-retained class owner; its raw C ring/state contains only copyable data. The
compiler safety rule remains unchanged. Shared queue source equals 818e9ee0
byte-for-byte (local61012911), whose proof likewise covers reference transpile
only.

## Publisher and interaction-state source checkpoints

MacOSPublisher now owns the bounded POD ring/recent-terminal ledger, direct
class-owned atomics, UI callback gate, and borrowed worker host route. Admission
and callback entry share a mutex; host callbacks run outside it with an atomic
in-flight claim. Cancellation seals ingress without joining a producer and
waits through polling for entered callbacks/host notifications. Accepted records
remain charged until one explicit disposition; an unknown sequence gap is not
reported as already-terminal. Suspended cancellation cleanup can bypass a
deferred head without changing surviving domain order. False/throwing host
requests after admission preserve ACCEPTED and latch failure. Independent review
found the suspend/resume native wake was unchecked; fixture b06727bd now covers
that failure and the source seals/latches it consistently.

MacOSControlEvents adds the application terminal pool/detached queue and copied
view interaction snapshots. Observation admission checks live generation while
domain admission also checks eligibility. Native owners must supply actual local
flags, mark a complete subtree before settling interactions, then publish; this
file does not claim that native wiring already exists. Cross-window channel
routing uses the shared core; partial rebind failure closes the state owner and
must be exposed as native-owner quarantine, never a fictitious rollback.

Both drafts passed independent source review (including the publisher correction),
canonical formatting and diff checks only. Actual semantic compilation, generated
worker-call ARC audit, paired native/sanitized fixtures and host/application
integration remain open. No native build or GUI execution ran in this agent's
source lane. The final MacOSControlEvents binding requires NSThread; the
integrator owns that row and all catalog/skip/generated integration.

## Native leaf state wiring

The next fixture-only sequence 2c3a6d7d / 9d282155 / f008e264 exercises an
actual NSView and NSButton: native hidden/enabled flags agree with revisioned
snapshots, observations are deferred, no-op setters do not enqueue, hide/show
preserves a disabled preference, and closing inside an entered observation
returns PENDING until that callback drains. It is a seventh fixture choice
(28 planned rows), not yet projected or executed.

MacOSView now owns a state registration scope alongside its existing native
input scope. Application composition can provide a context; legacy direct
constructors retain a standalone context with no automatic native dispatcher.
The base view marks hidden state before synchronous capture cancellation,
records native failure as observable quarantine, and retains its NSView until
both callback scopes drain. MacOSButton forwards the full IView state surface
and reads its actual native enabled flag after mutation; its prior alignment
logic is unchanged. State snapshots do not become a second enabled preference.

This is a leaf-level source slice. Containers must use distinct whole-subtree
mark, settle and publish traversals rather than recursively invoke the combined
leaf refresh. Application factories/context servicing, all other IView owners,
control domain delivery rechecks, editing, transactions and fair turns remain
unfinished. No complete provider/interface landing is claimed.

Parent evidence now additionally records zero-diagnostic reference SDK
transpilation for all six frozen foundation fixture types at 2b6f37fb, direct
borrowed signal/host calls in generated producer code (no managed ARC transfer),
and 20 strict C/Objective-C syntax checks across programs and native adapters.
Those checks did not produce objects, link executables, or execute native code.
The new native-view slice is not covered by that frozen proof.

The leaf owner exposes separate markInteraction / settleInteraction /
publishInteraction phases for upcoming container traversal. Its combined
refresh remains leaf-only, and an eligibility-loss flag survives between the
mark and settle phases. This is preparation for the required whole-subtree
barrier, not evidence that containers are already wired or qualified.

## Subtree and context source freeze — 2026-10-08 03:32 UTC

Fixture-only cb5e4372 adds NativeTreeState, a real NSView nested tree that checks
deferred coherent observations, ancestor hide/show, unchanged local disabled
preference, detach/reattach, and descendant close ownership. Fixture-only
ce074cde and 0047bb5b add explicit foreign-context rejection with the exact
old native/logical tree retained, default-constructor composition, and renewal
after the default context closes. Eight fixture choices now describe 32 paired
plain/sanitized rows. These new rows have not been transpiled or executed.

All existing macOS IView wrappers now forward state subscriptions and the three
private traversal phases to their existing native owner. Constructors accept
the optional shared semantic context without changing existing arguments.
Containers mark every descendant before any eligibility settlement, then
publish observations after the coherent transition. Route migration occurs
after settlement, so a terminal uses its original registration reservation.
Detach marks eligibility before native removal; visibility/detach failures
retain native owners and expose quarantine instead of reporting a rollback.

Independent review identified context rejection occurring after native attach.
The corrected admission checks semantic pool identity before native attachment
or ownership transfer. Legacy direct constructors share a lazy UI-only default
context; a closed default is renewed. Closing an individual view/container does
not close that context. This replaces the earlier per-constructor standalone
fallback. Application claim, wake adoption, shutdown and sequential-application
qualification remain part of the unfinished application integration; this
source checkpoint does not claim those are implemented.

Fixture-only a8702f8e additionally cancels a state registration from its entered
receiver and requires replacement rejection until the callback drains, followed
by successful replacement after COMPLETE. Source correction 2014f750 checks
pollCompletion rather than isOpen. It is a genuine lifetime assertion, but its
red and green executions remain pending.

The independent reviewer cleared the bounded context correction and reviewed
the traversal shape. Canonical BTRC formatting, Python formatting/lint and
git diff --check are the only local checks in this source lane. No SDK reader,
reference/selfhost compilation, C/link job, GUI test or guest ran alongside
the Linux qualification. Earlier six-fixture reference/strict-C evidence is
pinned to its earlier inputs and does not qualify this freeze.

Next qualification should project the six foundations plus NativeViewState
first. NativeTreeState deliberately precedes the still-unimplemented ordered
IContainer operations; it can first stop at interface completeness. Ordered
container transactions, native input/domain eligibility gates, control event
settlement, application/window host lifecycle and fair turn composition remain
unfinished. No complete provider or atomic UI2 landing is claimed. This slice
adds no native selectors beyond the previously reported ui2InitializeAppKit
probe declaration; the parent still owns every binding/export/generated and
known-AppKit admission fragment.

## First frozen qualification attempt

The parent supplied a fresh Mac compiler from reference source 56d548c4,
binary SHA-256
`41fde50cf256b3ef5a322648d0f5dd735f03ea28677d5bfb4c6f9423d90c13a1`.
The reviewed private recipe ran under gate and gui-capture with over 80 GB free.
Session 87921 ended with exit 1 and released both locks. All seven reference
fixtures transpiled; the six foundations emitted zero diagnostics. NativeViewState
emitted two nullability warnings in MacOSView, so the stage stopped before any
C syntax, object compilation, linking or native execution. This is not a green
qualification, and the selfhost fixture stage did not run.

Evidence remains at
`~/.cache/btrc/plan-consolidation-2026-10-07/ui2-macos-qualification-4dc8d9d3/results/qualification1/reference/`
with the immutable source archives, actual compiler/reader/tool pins, all seven
generated programs/plans, diagnostics and stage failure. The warnings point to
field access after intervening state-owner calls: nativeView's nullable return
and quarantineInteraction's isHidden call. Both now hold a checked local NSView
reference across those calls. The compiler guard and fixture assertions are
unchanged. Reprojection of this bounded source correction remains pending.

## Bounded native qualification passed on a9ffe1bd

After two independent source reviews, a fresh private preparation retained the
failed 4dc8d9d3 attempt and changed only MacOSView's checked-local references.
Session **58776** completed with exit **0**, then released gate and gui-capture.
Provider source was **a9ffe1bdede727cdf041d4a81601596ab62051d4**; both frontends
used compiler source **56d548c49ca027c9698c8546acdaf4df918630bd** and the fresh
selfhost binary/hash recorded above. SDK reader SHA-256 was
`40ff12368f1241c482fd56cadc81e85baff07855a736c28a97e0fe26a7b8561d`.
Host provenance: **Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0**. Apple clang used
SDK 27.0 and target `arm64-apple-macosx14.0.0`; exact selected tool hashes and
versions are recorded per stage.

| Completed stage | Actual result |
| --- | --- |
| Reference and selfhost projection | 14/14, zero diagnostics |
| Strict C11/Objective-C syntax | 56/56 |
| Plain and ASan/UBSan native linking | 28/28 |
| Plain and ASan/UBSan native execution | 28/28 |

The seven fixture types are RunLoopWake, RunLoopDeadline, WorkQueue,
RunLoopLifetime, Publisher, InteractionState and NativeViewState. Original
assertions, fault injection, runtime deadlines and sanitizer policy were
unchanged. All seven ran through each frontend in both runtime modes. The
twelve stages took 151.952 seconds in total. Final verification rehashed all
28 executables, Lifetime fault dylibs, generated C/plans, stage records and the
selfhost compiler. These are integrity hashes; no certificate-signing claim is
made for this GUI fixture run.

The aggregate and complete retained logs are under
`~/.cache/btrc/plan-consolidation-2026-10-07/ui2-macos-qualification-a9ffe1bd/qualification-result.json`.
Every stage retained its exact input manifest, tool commands and output, and
checked disk headroom and source file sets/hashes. No guest or competing native
build ran in this lane.

This proves the bounded foundations and native leaf-state slice. NativeTreeState's
four rows remain unexecuted because ordered IContainer operations are unfinished.
Default-context composition/renewal, complete subtree transactions, control-domain
events, application/host/window lifecycle and fair-turn integration still need
their own implementation and native acceptance. These results neither qualify
active/key focus journeys nor complete UI2 or the final repository matrix.

## Ordered-container continuation (source preparation)

After the paired foundation proof at `a9ffe1bd`, the next bounded slice is
`MacOSContainer` conformance to the approved ordered `IContainer` interface and
the `MacOSStack`, `MacOSPanel`, and `MacOSScrollView` forwarding owners. The
existing `NativeTreeState` four rows remain unexecuted. Source inspection finds
`insert`, `move`, `applyBatch`, and `treeRevision` missing; this is not yet an
executed baseline diagnostic.

The D29 claim additionally reserves `src/stdlib/GUI/MacOS/Container.h` and
`Container.m` for the cohesive native order/membership bridge. Native manifest
rows remain integrator-owned fragments. `MacOSGrid` retains its cell-specific
layout semantics. No portable interface, compiler, or runtime change is claimed.

The implementation must satisfy `ui2-lifecycle.md:113–149` and
`ui2-approved.md:674–685`: validate the entire proposed sequence before native
transfer, preserve editor/marked-text state on MOVE, retain old and proposed
owners through a transaction, prevent reentrant intermediate-tree delivery,
commit one revision, and distinguish verified rollback, reconciled failure, and
unknown-ownership quarantine. Fixture-only ordering/rejection/fault controls
precede production changes. The current native lane belongs to the parent
compiler measurement; preparation does not execute a compiler or native probe.

The first ordered-container fixture draft adds `NativeContainerOrder` plus a
test-only `UI2ContainerProbe` Objective-C class. It observes physical/plain and
arranged/stack order independently, uses an actual NSWindow/NSTextField field
editor with marked text and selection, and swizzles targeted native order steps
before/after side effects and native membership inspection. The planned rows
cover validation/revision rejection, one batch revision, same-index MOVE,
forward failure, inverse failure, reconciliation and quarantine. These fixtures
have not been projected or executed. Their native editing notification checks
do not claim the still-unimplemented typed text commit/cancel channels; that
E29 acceptance remains open. Attach/detach fault coverage and unexpected native
input/reentrant delivery probes are still being prepared.

A subsequent fixture-only extension targets actual `addSubview:` and
`removeFromSuperview` before and after their side effects. It requires a
verified rollback to restore both native membership and the managed restriction
against closing an attached child. These four paths are prepared, not executed;
unexpected-input and reentrant-delivery fixtures remain outstanding.

Independent fixture review identified two oracle gaps, now strengthened in
source: rejected/stale batches require zero actual native mutation calls, and
order checks require exact native subview/arranged-subview counts as well as
each identity's index. Review and formatting are not execution evidence.

### Executed ordered-container baseline

At fixture-only `3fab9f9e`, the frozen reference compiler `56d548c4` rejected
the original `NativeTreeState` in 4.685 seconds with exactly the four missing
`IContainer` operations and one nullable `NSView` return warning in
`MacOSContainer.nativeView`. Session 38659 ended with exit 1, and both host
leases were released. Evidence is
`ui2-macos-container-baseline-3fab9f9e/results/baseline1/reference/` under the
standing evidence root. An initial invalid `--stage` argument started no
compiler and is retained separately in `invocation-error.json`. No native C,
link, or program execution occurred.

The first production source increment adds the narrow native ordering adapter
and a private `IMacOSView.reconcileAttachment` operation. Each existing wrapper
forwards to its actual view/container owner, preserving GPU/text owner guards;
the two underlying owners compare the actual native superview before updating
their attachment fact. Reconciliation does not settle, publish, rebind, or
create a second owner. The nullable-return warning uses a checked local as in
the previously qualified leaf correction. Ordered conformance and transaction
barrier integration remain unfinished; this source increment is unprojected.

The provider-private context/input barrier draft follows fixture-only
`42870710`: semantic servicing checks the barrier before dequeue; legacy
CANCEL/EXIT delivery copies fixed payloads into one pre-reserved terminal record
per input registration and runs only after coherent transaction cleanup. Scope
cancellation seals queued admission, and receiver entry keeps cancellation
pending. Independent review caught an EXIT admission check after a CANCEL
receiver closes the context; the source now rechecks context and registration
immediately before EXIT, with a deterministic fixture for that transition.

Normal pointer/scroll consumption remains synchronous outside mutation.
Unexpected ordinary monitor entry while a transaction is active is currently
an explicit latched transaction failure, not normal-input deferral; complete
UI2 deferred-input acceptance is therefore still open. Container transaction
and application host dispatch have not yet been wired to the barrier. These
source and fixture additions are formatter-checked only, with no new projection,
C/link or native runtime claim.

### Ordered transaction source draft

The current draft implements the four `IContainer` operations in
`MacOSContainer` and forwards them through Stack, Panel and ScrollView. It
simulates the whole edit sequence before native mutation, retains old/proposed
owners, captures an inverse journal, verifies actual native order, and reports
committed, rejected, verified rollback, reconciled fault, or retained quarantine.
MOVE uses only the reviewed native order primitive; attachment facts reconcile
only after observed physical membership. Old append/detach mutations now enter
the same transaction. A quarantined close retains uncertain owners until
membership can be inspected again, then drains attached and detached children.

Grid is still a cell-addressed public API. Its shared internal container now
captures the exact native cell placement before mutation so rollback cannot
accidentally use the grid's mutable next-insertion cursor. The optional private
layout projection leaves existing plain/fault-injection layout implementers
compatible; it does not add portable Grid operations. GPU and text wrapper
attachment guards remain on their existing owners.

This is an unprojected source draft pending independent journal/reconciliation
review. The original four-error baseline and all prior runtime proof remain
unchanged. Complete application dispatch integration, unexpected native input
deferral, typed control event acceptance, and full UI2 remain open. No new
compiler, syntax, link, or runtime execution occurred while the product library
journey owns the heavy lane.

Independent review found three further boundaries, covered by fixture-only
`00d2ee91` before their source correction:

- Deferred CANCEL receiver failure must occur on a later service turn, after
  `applyBatch` has returned its truthful typed outcome and ownership.
  `endMutation` now only releases the barrier and requests a turn; the context
  service processes one queued terminal before ordinary semantic records. It
  preserves queued cleanup after context closure, without admitting receivers.
- Stack arranged order is not a physical ownership inventory. Reconciliation
  now independently enumerates every physical subview and rejects unknown
  children. The fixture adds a real unarranged child, requires quarantine and
  retryable close while that child remains, then removes it and drains owners.
- A constructor failure before `_interaction` exists must retain its original
  error. Completed/partial native-owner cleanup now precedes context lookup in
  container close; a layout that throws while producing its native view covers
  the destructor path.

The new probes and corrections are source-only. Application host wiring must
call the guarded context service; direct shared-queue dispatch remains a private
API and is not a substitute for that integration. No root callback, threshold,
or native ownership assertion was weakened.

A second independent source review found a BTRC control-flow mismatch in the
new pointer entry counter: this language's current `finally` behavior does not
run on a return escaping the `try`. The provider now stores the callback result,
falls through the cleanup, and returns afterward. Existing barrier fixtures
require final COMPLETE and balanced terminal credit after an actual PRESS, so
they cover the resulting stuck-drain failure. No compiler change or execution
claim accompanies this source correction.

### Initial ordered-container SDK projection

The allocated three-fixture reference attempt at `f46c2465` stopped on the
first fixture after 2.064 seconds: the SDK reader rejects a bare Objective-C
class in a selected-symbol list (`Unsupported native declaration:
BTRCMacOSContainerOrder`). Existing repository bindings select explicit method
selectors. Session 27312 ended with exit 1 and released gate/gui-capture; no
BTRC semantics, C compilation, link, runtime, or later fixture was reached.
The preserved record is
`ui2-macos-container-projection-f46c2465/results/projection1/reference/NativeTreeState/projection.json`.

The correction selects the bridge's three exact class method selectors in the
private fragment, and the test driver's exact twenty `UI2ContainerProbe`
selectors. It changes projection metadata, not compiler acceptance or runtime
behavior. The original rejected manifest/attempt remains immutable.

Independent contract review identified an unresolved notification wording seam:
`ui2-lifecycle.md:124` says a committed batch produces one tree revision and
notification, while the finalized surface in `ui2-approved.md:303–304` defines
`applyBatch` and `treeRevision` without a tree-change subscription or payload.
`ViewInteractionState` does not contain order or tree revision. The provider
therefore preserves exactly one committed tree revision and the typed result,
plus legitimate changed interaction-state notifications; it does not fabricate
state changes when eligibility is unchanged. Tree-notification acceptance stays
open pending the integrator's contract interpretation. No public API or contract
document was changed.

The corrected-selector attempt at `4d1cd3d0` reached real reference BTRC
transpilation for NativeTreeState, then stopped under the unchanged zero-
diagnostics policy on one nullable `NSView? .superview` warning in native-order
reconciliation. Session 70984 ended with exit 1 after 10.364 seconds and released
both locks. Generated C and link plan are retained under
`ui2-macos-container-projection-4d1cd3d0/results/projection1/reference/`; the other
two fixtures and all C/link/runtime phases were not attempted. The source
correction explicitly rejects a null child from the native enumeration before
looking up its owner or checking its parent, preserving the existing failure
classification. Its diagnostic-free replay remains pending.


The allocated `7a95ccdf` reference attempt (session 98663, terminal exit 1)
proved NativeTreeState transpiles with zero diagnostics in 9.625 seconds. The
next fixture, NativeContainerOrder, stopped after 5.161 seconds on three direct
casts from portable interfaces to `IMacOSView` and two nullable native-host
argument warnings. NativeContainerBarrier and every C/link/runtime phase were
not attempted. Both leases were released after 14.897 seconds; admission free
space was 81,445,392,384 bytes. The exact result remains under
`ui2-macos-container-projection-7a95ccdf/results/projection1/reference/project-plain.json`
(SHA256 `95378e6054809e44d7b791e45ee82e2011b4ec849b8eaee3161f3d574308e401`).

The fixture-only correction uses the provider's existing nullable checked
interface-projection pattern and rejects a null host before attachment. Every
native order/count, editor identity/selection/composition, zero-mutation
rejection, rollback, and ownership assertion is preserved. It changes no
provider/compiler implementation or diagnostic policy. A fresh source-pinned
reference replay remains pending; the previous failed attempt is immutable.


The `ac165e5c` reference attempt (session 67678, terminal exit 1) passed
NativeTreeState and NativeContainerOrder with zero diagnostics in 9.794 and
9.389 seconds. NativeContainerBarrier also transpiled, but its seven fixture
nullability warnings stopped the unchanged zero-diagnostics policy after
9.075 seconds. No native C compilation, linking or execution occurred. Gate
and gui-capture were released after 28.367 seconds. Exact evidence remains at
`ui2-macos-container-projection-ac165e5c/results/projection1/reference/project-plain.json`
(SHA256 `b2aaec57e9759a2790d3e70062c4241533fdb7aac5a6c59374a47bf5fc7aa752`).

Barrier fixture repair uses explicit checked locals for the SDK's nullable
native view, host and pointer-event results, and checks the nullable registration
before cancellation. It retains the original registration assertion and every
pressed/cancelled/exited count, semantic barrier, typed batch ownership,
revision and balanced-credit predicate. These are fixture precondition checks;
provider behavior, compiler acceptance and diagnostic policy are unchanged.
The corrected fixture has not yet been projected or executed.


At frozen `71397941`, all three ordered-container fixtures (NativeTreeState,
NativeContainerOrder and NativeContainerBarrier) now pass reference and
self-hosted SDK/BTRC projection with zero diagnostics. Sessions 52922 and 17238
both ended with exit 0, taking 28.352 and 11.210 seconds respectively. The
reference compiler is exact `56d548c4`; the retained self-hosted binary SHA256 is
`41fde50cf256b3ef5a322648d0f5dd735f03ea28677d5bfb4c6f9423d90c13a1`.
Input inventories and native reader/tool identities passed their end checks.
The paired result is
`ui2-macos-container-projection-71397941/results/projection1/paired-result.json`
(SHA256 `eb087dcc0905faa3d6bb1682b8bfc6415b2447626a6826b54ee2858e74870d0e`).
Both leases are released. No strict C compilation, linking, sanitizer run or
native behavior was attempted in these bounded stages; MOVE editor continuity,
rollback fault behavior and terminal-delivery execution remain open. Earlier
failed selector/nullability evidence is preserved alongside the successful
source-pinned preparation.


### Ordered-container bounded native qualification

Frozen provider `71397941` now passes the allocated component qualification:
six diagnostic-free projections, 34 strict C/Objective-C translation-unit
checks, 12 successful links, and all 12 actual native runs (NativeTreeState,
NativeContainerOrder and NativeContainerBarrier × reference/selfhost ×
plain/ASan+UBSan). Final session 46199 ended with exit 0; gate and gui-capture
are released. No capability skip, original assertion change, provider focus
exception or diagnostic waiver was used.

The actual native cases exercise subtree eligibility, ordered insertion/move,
native child counts/order, real field-editor identity/selection/marked text,
zero-operation invalid/stale batch rejection, before/after attachment/order
faults, inverse failure and native reconciliation/quarantine, retained ownership,
semantic delivery barriers and deferred terminal callbacks (including callbacks
that cancel/close or throw after the typed batch result is returned). These are
bounded fixture observations, not full application-host/control integration.

Both generated frontends passed 17 strict translation units each. Each
sanitized variant recorded 20 real compile/link commands with
`-fsanitize=address,undefined -fno-sanitize-recover=all`; all six sanitized native
executions returned 0 with expected output and no sanitizer failure in retained
stderr. All 319 frozen provider inputs, 131 compiler inputs, the retained
self-hosted compiler and every linked executable were independently rehashed
after completion. Complete commands/stdout/stderr and failed predecessors remain
under `ui2-macos-container-projection-71397941/results/projection1/`.
The aggregate `component-result.json` SHA256 is
`d6bd4646020aeb630f7352df9a0fb4cbfdd6c318036764aa30ec4319ffc4aafd`.

This closes the bounded native evidence gap for these three fixtures. It does
not close the remaining normal native-input deferral/application-host wiring,
all typed controls, lifecycle/publisher integration, the documented tree-change
notification wording seam, atomic Linux/macOS UI2 landing, or the final full
repository/platform matrix. No partial provider landing or release claim follows
from this component result.

## Public application-host slice: fixture checkpoint

The next product-facing fixture is `NativeApplicationHost.btrc`. It uses the
actual `IApplication` returned by `MacOSApplication`, not a narrowed test
application. Its native test host installs a real AppKit delegate before
construction and verifies that construction, attachment and teardown preserve
that identity. Public calls cover no-inline dispatch, the shared post/schedule
capacity, cancellation/disarming of a future timer, next-round reposts and
reentrant service, injected suspension policies, worker publication, a real
factory-created view's semantic observation and close from entered work.
`NativeCaptureFailure.btrc` separately requires sticky first-error reporting
outside the container barrier, including false/throwing host wake and a closed
native source; fault reporting must leave cleanup available.

These are **unexecuted fixture checkpoints**, not red execution evidence. The
previous qualified provider remains 71397941. The public application currently
lacks createPublisher/schedule/attachHost, and its reachable window, text,
selection, slider and scroll owners still have missing approved UI2 operations.
A genuine application projection may report those conformance dependencies
before running the host fixture. They will not be hidden by stubs, narrowed
interfaces, changed assertions or a private replacement application.

The application implementation will own one explicit semantic context and pass
it to every factory; it will not borrow the standalone default context. One
executor state machine will serve external attachment and desktop run. Delegate
installation belongs only to the desktop run owner. Native wake registration,
host receiver and producer routes must be acquired/rolled back together; host
route changes must hold each publisher's existing change guard. Service uses a
sequence watermark for work, bounded rotating lanes for work, publishers and
semantic queues, and a cleanup opportunity on every turn. Count/time limits are
implementation facts to record and qualify, not an E40 pass claim. The service
boundary catches failures, seals ingress and initiates nonblocking drain; it
must never lose the public typed attachment/cancellation outcome to a receiver
exception. Normal pointer/key consumption remains synchronous where the
existing public bool contract requires it; transaction barriers and semantic
host service must prevent callbacks against intermediate ownership.

The integrator owns a disjoint source-only MacOSScrollView correction and its
new fixture, including explicit context constructor injection. The macOS agent
retains Application/Executor/ControlEvents and other named claimed owners.
Production binding manifests, generated files and final AppKit execution
inventory remain integrator-owned. No new native execution has begun.

`MacOSControlContext.recordNativeFailure` now provides the UI-native capture
seam used by the disjoint scroll observation work. It stores the first error
before requesting a wake, contains a false/throwing wake, and does not repeat
that wake for later diagnostics. Context dispatch surfaces it outside mutation
and entered-input barriers, after already-reserved terminal cleanup and before
another semantic dequeue. Cleanup remains independent. The method requires the
UI thread; it does not promise arbitrary-thread exception containment.
The integrator and independent reviewer cleared this bounded source change.
NativeCaptureFailure remains unexecuted; it is not yet a real AppKit-notification
or pending-terminal reentry qualification.

### Staged wake attachment prerequisite

Independent contract review confirmed that the first failed attach cannot leave
an application constructor's already-registered CF source behind. The new
fixture-only `RunLoopAttachment` requests an unregistered signal, observes real
`CFRunLoopAddSource` calls through the existing native fault probe, rejects a
closed callback scope without registration, rejects premature timed dispatch,
then preserves a real worker's pre-attachment signal through one successful
registration. Duplicate subscription cannot replace that successful route;
actual default/tracking-mode delivery and closed-source suppression remain
required. Source preparation and formatting only; no baseline compiler or
native execution has run for this fixture yet.

The staged-signal implementation now accepts private constructor argument
`registered = false`; standalone callers retain the prior eager default.
Subscription commits callback-scope admission before registering the same CF
source, so pre-attachment worker readiness survives without a polling timer or
second source. Nonzero native timer scheduling before registration is rejected
before changing any deadline. Source review found no fallible acquisition after
receiver publication: the remaining CF add operations are void and do not pump
callbacks; UI ownership excludes concurrent source closure. Duplicate admission
preserves the existing route. The independent reviewer cleared this bounded
source change. Actual AddSource counts and replay remain unexecuted, and the
application has not yet switched to staged registration.
