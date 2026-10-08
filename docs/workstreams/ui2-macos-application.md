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
ui2-macos-foundations-b6a4fe3e-compiler-f75c737b; aggregatee7d442. That baseline had no C/link/native public Application acceptance. The original
assertions are preserved in the completed attached-host qualification below.

One MacOSApplication lifecycle composes the existing MacOSWorkQueue,
MacOSPublisher, staged MacOSRunLoopSignal and explicit MacOSControlContext.
Constructor must leave a foreign host delegate unchanged. post/postAfter and
schedule share work accounting; internal run and external attachment share
bounded service and nonblocking shutdown. Native group quit remains separate.
Original internal-run native shell and public hosted behavior both require
paired plain/sanitized acceptance; component proofs do not substitute for them.

Source preparation and native qualification use separately allocated lanes;
all other writers remain read-only during native execution.

Historical source checkpoints (before qualification)
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

### Current compiler component qualification (2026-10-08)

Frozen provider `70df20a991826a2f802bff251abd355c8499abbb` and current
compiler `f75c737bbf4002553099ce2856b9bbc86494622a` completed the reviewed
three-component matrix under the gate, GUI-capture and compiler-build locks.
`WorkQueue`, `NativeContainerBarrier` and `NativeCaptureFailure` passed both
frontends with plain and ASan/UBSan execution: six zero-diagnostic projections,
28 strict C/Objective-C checks, 12 links and 12 native runs. Session 24190
terminated with status zero. The 180 recorded process groups are absent and
leaders reaped; source inventories, logs and executed binaries were rehashed.

Evidence: `~/.cache/btrc/plan-consolidation-2026-10-07/ui2-macos-application-70df20a9-compiler-f75c737b/component-result.json`,
SHA256 `a54c1f28b116c6a17bb3a9caef28379341e36e4c4d8afc52bd3b1d4457e57f0f`.
This qualifies the updated executor and shared delivery-barrier components.
It does not execute the public Application host fixture or prove complete
Application integration. That original fixture awaits the real TextField,
Slider and Select owners; its assertions and prior conformance failure remain
intact. No broader UI2 completion is claimed.

### Original public attached-host qualification (2026-10-08)

The original rich `NativeApplicationHost.btrc` now passes both frontends, plain
and ASan/UBSan, without changing its assertions. Session 62235 terminated zero:
two zero-diagnostic projections, 22 strict C/Objective-C source checks, four
links and all four native runs pass. Each native run prints the original success
marker. Its only stderr is `Host deadline failure`, deliberately raised and
handled by the failure-case fixture; there are no sanitizer reports. All 122
recorded process groups are absent and leaders reaped, with final source, tool,
log and executable hashes unchanged. Independent result review is clear.

The immutable composition uses Application `af71b170d6a723d008d7f8b28de85d79ca7de1cb`,
three Text donor files from `88db78e5b0db29c8b5b30325882beea9046c70d3`, and six
Range/Select donor files from `209fe7f7b8d08c26d070129c1d4bc535bcbe3f2e`.
The 343-file provider inventory and private manifest retain exact donor paths,
modes and hashes; binding metadata is composed from the original test-driver
constants. Compiler source is `f75c737bbf4002553099ce2856b9bbc86494622a`, with
131 inventoried compiler files and self-host binary SHA-256
`60639d608d3e09bec4dcdfaf76d3575cdeb135b04d2102858cf15a9f089efbf3`.
Native qualification uses SDK 27 on arm64, target macOS 14, the original native
flags and stage deadlines. The managed fixture remains byte-identical at
`3c9554ce8a82fe2eea27b3e2450f81bf3cf54ef550069c0529aeb00a8dc3943b`.

Three observed failures led to bounded repairs, with all earlier records kept:

- Original composition `b97732ba` fails reference projection because the raw
  callback-slot getter `NSApplication.delegate` is not exposed. Record
  `4f805ef0f439d6e3fec830a460c2ae88ba7f4e6ebd6eac73eaffa0955abe066e` is preserved.
  Application-only `9ff2b912` uses the existing scoped setter before the run
  teardown transaction. Failed activation leaves the owner open; occupied-slot
  rollback remains the generated callback owner's responsibility. This does
  not claim separately executed standalone foreign-delegate rejection.
- The next original public native run fails eventual close after native callback
  unwind; aggregate `9f0fbaab192ca0b0222b07a7e74a7d793d42b14fb6eb30b162521987eab3239f`
  retains that failure. Fixture-only `21ee445b` isolates the trapped deferred
  cancellation with two real registrations; baseline receipt
  `4cc3fab55004a1db56602c1b370363b5e4845533864946bb310534ddacf79ce1`
  records the exact `cancel(first) == COMPLETE` native assertion after setup
  passes. Repair `676d5043` removes only the cancelled registration's queued
  identity in the existing context, then releases its deferred payload.
  Native/entered completion and terminal credits remain owned by the original
  registration. All four Barrier cells pass, including unrelated queued-record
  survival, entered cancellation, and complete credit restoration; receipt
  `e3b6a071f73a495f187efceb8ff8e6f7177ad69d7c84d0dfb11633bf5df46aa0`.
- That repaired public run reaches a later probe failure. Diagnostic receipt
  `c8ce66c031e7f745e1a495959d6ca61c7bffc19733f016d798fb51d43739cfe5`
  proves key iteration 1 selected an invisible, closed prior same-title window
  with zero children while the current visible window had one child. Probe-only
  `af71b170` selects exactly one visible matching window and rejects ambiguity.
  Event construction, dispatch, child-count predicate, provider sources and
  managed assertions remain unchanged. The final four-cell pass follows this
  actual diagnostic. The already-qualified Barrier fixture and production bytes
  are unchanged, so its four cells were retained rather than repeated.

Final evidence is
`~/.cache/btrc/plan-consolidation-2026-10-07/ui2-macos-public-application-af71b170-compiler-f75c737b/application-result.json`,
SHA-256 `b9c1d2dc59beae175500f2674cb14937412cdbbbbf4853c25b985042af9c742f`.
Its prepared manifest is `2196a76ad6859d84e8b23d92ef6afb152702336b27e09729dd5c227923a59720`;
qualifier `ad96e963f041afc0ad7960492775e4f0f05b991d67129c5bc08e06bb0d92ba26`
and runner `8ea2d374548a3b64818416d986bdb069472f288552f7d2ba1b1b5a41e78c460f`
retain the reviewed first-failure policy and all-exit process cleanup.

This qualifies the original public attached-host Application contract on this
composition, including native callback close/unwind and cleanup-scope behavior.
It does not qualify standalone application run/delegate admission, native group
quit, all Range/Select/Scroll input journeys, all UI2, Linux integration or a full
platform/product matrix. Historical component and partial source statements
above retain their original scope; the attached-host outcome is now superseded
by this executed proof.
