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
