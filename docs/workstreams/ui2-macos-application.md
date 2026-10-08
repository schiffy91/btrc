# Public macOS Application composition

Integrator-assigned D29 continuation from clean904d2716, preserving the existing
qualified Window and foundation sources. Branch codex/ui2-macos-application.
Owned Application/Executor/RunLoop seams and original public host fixture/driver
are listed in WORKSTREAMS. TextField, Slider and Select implementations belong
to separate coordinated owners; no portable interface or context change is
part of this packet without coordination.

Actual b6/f75 original NativeApplicationHost reference baseline (session25358)
retains19 errors: Application3, TextField3, Slider6, Select7, plus the nullable
publisher fixture warning. Evidence application-baseline-result.json in
ui2-macos-foundations-b6a4fe3e-compiler-f75c737b; aggregatee7d442. No C/link/native
public Application acceptance has occurred. Preserve every original assertion.

One MacOSApplication lifecycle composes the existing MacOSWorkQueue,
MacOSPublisher, staged MacOSRunLoopSignal and explicit MacOSControlContext.
Constructor must leave a foreign host delegate unchanged. post/postAfter and
schedule share work accounting; internal run and external attachment share
bounded service and nonblocking shutdown. Native group quit remains separate.
Original internal-run native shell and public hosted behavior both require
paired plain/sanitized acceptance; component proofs do not substitute for them.

Source work begins while another agent owns the native attribution lane.
No test/compiler/AppKit process is authorized concurrently.

Source checkpoints (unexecuted)
------------------------------

The original public host fixture is preserved; d506d3c7 imports the reviewed
checked-local worker capture. Fixture-only dce2844e/93671180/8efa0ba0/95178fc0/
e448a244 add failed attachment retry, shared cancellation wake, real Window
activity propagation, residual ordered Window delivery and sticky hosted work
failure versus completed scope cleanup. These are source regressions; no new
red or green compiler/native execution is claimed.

The production draft removes the independent performBlock/NSTimer work lane.
MacOSApplication composes the existing work queue, publisher, staged CF source,
semantic context and window/view close owners. Immediate/future work retains
workCapacity; publishers have a separate 4096-slot/256-channel budget. Five
provider classes rotate with 64 service opportunities and a 2ms monotonic turn
budget. Fairness and timing outcomes remain unmeasured.

A caller CallbackScope tracks a state-free cleanup projection of the same host
attachment. It returns COMPLETE only after actual application resources drain;
the public attachment separately retains FAILED for a recorded work outcome,
as required by ui2-approved.md240–242. Failed native cleanup is never converted
to completion. This avoids permanently poisoning CallbackScope's resource
retention with an already-drained operation failure.

The Window owner retains native-derived activity unless an external host gives
an override. Injected SUSPENDED suppresses presentability and input eligibility;
this is stand-in host evidence only once the real fixture executes. Readiness
queries do not dequeue; remaining window terminals request another bounded turn.
Native multi-window quit coordination remains separate. The normal native
pointer/key callback reentrancy seam has been reported for a coordinated existing
context guard; public-host conformance and internal-run regressions remain open.

The integrator subsequently approved the narrow existing-context correction:
MacOSControlContext counts entered synchronous native receivers, and the
existing pointer/scroll/key owners balance that guard with finally-only exits.
Host service and application resource close consult the same guard. Deferred
service readiness wakes after the outer receiver or transaction unwinds;
application work still uses its separate existing scheduling-round guard.
Fixture-only0924e7ec/b2f16dbd inject actual owned-window AppKit mouse/key events,
requiring no nested work and PENDING close until native return. These cases
remain unexecuted. No new public API or copied lifecycle owner was introduced.
