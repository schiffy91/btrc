# UI2 Linux provider

Packet CX-UIA-23, assigned under PLAN D29. Branch
`codex/ui2-linux-provider`; source-only base `bd8b5904320e8f1e2d7e16f994e8c68977351f31`
combines preserved grid/input/layout/scroll source `47e64e21`, reviewed integration
`db269d6c`, and approved interface `ca4782e1`. The old qualification archives and
branch refs remain unchanged. This branch is an atomic UI2 landing dependency,
not an independently shippable provider/interface release.

## Owned paths

- `src/stdlib/GUI/Linux/{LinuxApplication,LinuxWindow,LinuxTextField,LinuxSelect,LinuxSlider,LinuxScrollView,LinuxImageView,LinuxView,LinuxActionQueue,LinuxContext,LinuxContainer,LinuxStack,LinuxPanel,LinuxButton,LinuxPublisher}.btrc`
- `src/stdlib/GUI/Linux/SDL.h`
- `src/tests/native/gui/ui2/probes/linux/{UI2LinuxProbe,UI2LinuxExecutor,UI2LinuxControls,UI2LinuxLifecycle}.btrc`
- `src/tests/native/gui/ui2/probes/linux/{UI2LinuxProbe.h,UI2LinuxProbe.c}`
- `src/tests/python/test_native_ui_core_linux.py`
- this report

Parent assignment adds the shared **private** semantic owner
`src/stdlib/GUI/ControlEventQueue.btrc`, its dedicated
`src/tests/native/gui/ui2/ControlEventQueue.btrc` regression and
`src/tests/python/test_native_ui_control_queue.py` driver. Both desktop providers use
this one implementation; `ControlEvents.btrc` remains the approved public
value surface. The existing click ActionMailbox is not replaced wholesale.

SDL symbol/export rows are an integrator fragment; no portable interface,
catalog, generated output, Mac provider or frozen evidence is edited here.
LinuxPublisher owns only this provider's bounded plain-data worker ingress;
LinuxContext carries its existing shared provider services. The approved
interface and ui2-approved.md govern; no second portable ownership model.

## Qualification state

Claim precedes implementation. Existing Linux 96-row repair and four Grid04
rows are being qualified from immutable archives by another agent. No UI2
native run, compiler build, guest, latency measurement or acceptance is claimed.
Before source work the host had 81.44 GB available. Native tests wait for the
parent's exclusive lane. The fixture-only checkpoint must precede production.

Required evidence includes real worker wake with the SDL waiter parked without
a polling timer, failed SDL wake, bounded class rotation and deadline dispatch,
host suspension stand-ins, revisioned reversible close, control draft/terminal
events with SDL composition, ownership-preserving mutation and retained image
presentation. Both frontends, plain/sanitized, X11/Wayland, original E40 counts
and the separate ten-minute load remain acceptance requirements. Linux undo,
physical IME, headless minimize/cover/scale evidence remain explicitly outside
the corresponding stand-in claims. Both complete desktop providers and the
interface must integrate atomically before product use.

## Source checkpoint: worker ingress and scheduler foundation

Claim `9bcca52c`; fixture-only checkpoint `8ffe3a0e` is deliberately
unexecuted. It uses a real native worker, an identity-only publication and an
indefinite SDL wait, then the existing approved host suspension oracle. Remaining
native probes must establish the exact parked-wait and rejected-wake paths;
the delay in this first fixture is not by itself proof of the race boundary.

The first production slice adds LinuxPublisher's preallocated plain record
storage, mutex admission, generation/sequence guards, ordered replacement
barriers, atomically sealed cancellation with nonblocking retirement, and typed
native wake rejection. The UI thread alone owns callback registrations and
managed payload construction. Host wake callbacks run outside synchronization;
a failed wake after admission seals the endpoint rather than returning a
retryable rejection for an already accepted receipt. Host installation acquires
all publisher route guards before changing any receiver.

The same LinuxApplication turn services desktop and host attachment. SDL wait
has no 250 ms polling fallback. Input is bounded by 4096 events and 2 ms; work
and publishers by 64 deliveries and 2 ms; timer scanning by 256 entries; native
presentation by eight windows and 2 ms. Reposted work enters a later round and
windows/publishers/timer scanning rotate. Budgets are source choices, not yet
measured service-gap or latency claims. The old E40 fixture's exact-first-turn
4096 expectation must remain preserved in its archived repair proof; a separate
UI2 oracle must allow an earlier time-budget yield while retaining every event
and the same original burst/terminal cases.

This is NOT a buildable/qualified complete UI2 provider yet: expanded IView,
IContainer, control and window methods, semantic terminal reservations,
receipt traces, grouped quit, composition dispatch/cancellation, retained image
presentation and native probes remain work in progress. No temporary method
stubs were added. Public interface bytes remain exactly the approved dependency.
Only formatter and diff checks have run; no compiler, C, native or pytest test
has run on this UI2 source. The 53 operations remain unqualified until the
complete atomic provider landing and its required gates.

The dedicated drivers are named `test_native_ui_core_linux.py` and
`test_native_ui_control_queue.py` to join the existing Makefile
`test_native_ui_*.py` collection. The original fixture-only commits remain
preserved; no Makefile discovery exception is needed.

## Shared private semantic owner

The dedicated fixture-only checkpoint `f401dfea` precedes
ControlEventQueue production. The queue is UI-executor-only, one per window,
with an application terminal pool; it has no native loop/wake implementation.
Typed channels reuse CallbackContext admission and receiver drain. Every live
channel holds a base terminal credit, and overlapping interactions draw extra
credits before native begin. Tickets are unique and retired exactly once;
normal capacity includes executing records. Replacement is confined to the
matching owner/generation/interaction/key in a replaceable suffix. Disposition
counters are seven bounded counters, not an ever-growing receipt log.

`rebind` preserves receiver/scope/reservation for detach and reattachment within
one application. A same-queue move changes nothing; crossing queues disposes
old queued snapshots as ineligible and retires unused tickets. A detached
application queue supports subscription before window attachment. Native owners
must settle eligibility before rebind and capture immutable owning snapshots.
Explicit `ticket.retire()` releases a ticket when native begin rolls back or an
interaction ends without a terminal event.

The source fixture covers replacement barriers, normal saturation with terminal
progress, refusal of additional overlapping reservations, delivery-time
eligibility/generation, in-flight cancellation, cross-queue migration,
same-queue preservation and throwing-receiver retirement. All are still
**unexecuted**. Formatter/Ruff/diff checks passed. No provider wiring or UI2
acceptance is inferred from this shared source checkpoint.

Source review found that user-provided wake adapters can throw after admission.
The Linux publisher now catches that failure, seals the endpoint, preserves the
original ACCEPTED/REPLACED outcome, and retires an atomic notification claim in
`finally`. This eliminates the second mutex acquisition and its stranded-claim
failure path. The UI service reports the latched failure; cancellation can
still drain the accepted receipt and release the host. The shared semantic
queue applies the same post-admission rule for both false and throwing wakes.
No retries or synthetic delivery hide a native source failure.

Additional unexecuted native fixtures cover the throwing host's accepted and
replacement paths, stable COMPLETE cancellation with no receiver entry or wake
retry, false/throwing semantic wakes for initial/replacement records, rejected
construction under an already-cancelled scope returning all terminal credits,
and one registration cancelling during its terminal callback while another
registration on the same receiver continues. Formatter and diff checks passed;
these source assertions are not runtime evidence.

Independent review identified a terminal-credit seam: a retained ticket alias
could retire an entered extra terminal credit after its channel cancelled.
Producer retirement now refuses a still-queued ticket; only record completion
returns that credit. Terminal publication checks channel ownership even after
cancellation. A dedicated unexecuted fixture cancels and republishes inside an
extra-ticket callback, asserts capacity remains unavailable until callback
return, and rejects a closed channel attempting to retire another channel's
ticket. Formatter/diff checks passed; native proof remains pending.

Publisher delivery now pins CallbackContext entry while holding the same native
mutex as generation validation and dequeue, then releases synchronization before
calling the receiver. A newer generation therefore cannot enter between those
operations; an already-entered callback may finish. Fixed plain counters record
accepted, pending (queued plus entered), delivered, cancelled, stale-generation,
superseded, closed and failed receipts without allocating producer-side managed
state or keeping unbounded history. The fixture checks generation replacement,
explicit cancellation, suspended cancellation, receiver delivery and failure
cleanup conservation. All runtime and sanitizer proof remains pending.

Checkpoint before independent compiler admission review: `c98552d2` preserves
an unexecuted native eligibility fixture. LinuxContext now owns the private
terminal pool (16384 slots), detached semantic queue and native wake adapter;
LinuxViewNode has source-only observation/generation/eligibility foundations.
This foundation is deliberately not claimed as an implemented operation yet:
window/application service wiring, root refresh, enabled-control overrides,
composition settlement and the other UI2 methods remain unfinished. No build
or native test was attempted, and this WIP checkpoint must not land alone.

D29 parent additionally assigns `src/tests/gui_provider_root.py` for the single
private `ControlEventQueue` test export. The copied fixture manifest alone may
expose that owner; production package exports remain unchanged. This supports
shared white-box receipt tests and both provider fixtures without promoting the
private queue to the portable API.

Source wiring now services per-window and detached semantic queues in a rotating
64-record/2 ms slice after native capture. Window show/hide/minimize/restore,
application suspension, attachment and ancestor visibility update inherited
eligibility; input and focus admission consult that state. Existing enabled
preferences remain in the controls and are queried virtually, with no second
IView enabled store. State observers use live-generation admission separately
from domain eligibility, so hidden/disabled observations can be delivered.
Snapshots are copied for callers and queued notifications, revisions advance
only when facts change, and unchanged refreshes emit no replay. The entire
subtree is marked before settlement and notification.

This remains incomplete UI2 source: semantic control terminals, composition
settlement, button action migration, container transactions, full WindowState
and reversible/grouped close still require wiring and genuine fixtures. The
minimize/restore source path is not native evidence and does not close the old
01 qualification gap. Formatter/diff checks passed; no compiler/native tests.

D29 parent extends ownership to
`src/tests/native/gui/linux/LinuxGUIControls.btrc` solely to reconcile its old
image-close assertion with approved retained presentation. The original bytes
remain in base `47e64e21` and the preserved immutable qualification archives.
New fixture-only checkpoint `294f821a` captures actual GPU pixels before/after
handle close, rejects republishing the closed alias, clears presentation and
checks subsequent native subtree drain. It is unexecuted; no failed runtime
result is invented or discarded.

Retained-image source repair captures a strong pixel reference and immutable
native identity when a handle is published. Painting/fitting use that retained
presentation; closing the handle no longer erases an installed image. Even a
same-alias publication checks handle openness before its no-op. Clearing or
completed view close releases retained pixels and identity. The existing
LinuxGUIControls assertion now checks identical captured RGBA and identity after
close, rejection of the closed alias, and cleared pixels after explicit clear;
its existing final application teardown remains. These are approved contract
changes, not a new release allowance. Both new and reconciled native fixtures
remain unexecuted; formatter/diff passed.

The shared owner adds the private `IControlEventChannel` projection for rebind
and existing cancellation. Linux nodes retain a bounded-to-live-registration
routing inventory, prune completed channels, and route every typed control
channel across queues through this projection. The node's existing callback
scope remains the lifetime owner; this creates no portable wrapper API. The
shared migration fixture now exercises the erased projection. Unexecuted.

Two-axis scroll fixture-only checkpoint `c4548313` uses SDL's real event queue
for a horizontal/vertical wheel input, then checks independent clamping,
vertical-call x preservation, MODEL/USER/SYSTEM observations, viewport/document
intersection, no-op suppression and cancellation. Source implementation now
stores both extents and offsets, updates both child translations atomically,
returns owning geometry snapshots, and publishes replaceable revisioned actual
geometry through the shared state-observation channel. Existing vertical thumb
geometry/drag behavior remains. This does not claim E09 focus or UI6 collection
anchor behavior. Fixture and implementation are still unexecuted; only formatter
and diff checks passed. Expanded IContainer and other UI2 controls still need
implementation before the whole provider can compile/qualify.

A further independent source review found queue-local registration identifiers
could collide across windows. The application terminal pool now allocates
monotonic registration identities, and tickets check both pool identity and
registration identity before any closed-channel cleanup. New unexecuted cases
try a closed channel against an extra ticket from a second queue, once sharing
the application pool and once using a different pool, then prove the rightful
channel can still deliver and return every credit. Formatter/diff passed.

Container fixture-only checkpoint `644f3200` checks real overlapping panel pixels
and generation-preserving move, stale rejection, failed provider attachment with
successful inverse, failed inverse quarantine, retained ownership and eventual
close. The attachment fault is injected after the actual provider node route
changes; it does not implement the result policy. Native execution is pending.

Container mutation source is checkpointed for semantic compilation review:
whole-sequence validation precedes native work; saved routes/frames and owning
references support inverses; unknown inverse failure quarantines the last
coherent child order while retaining additional possible children for close.
Move uses order changes without detach. Channel routes/generations are deferred
across native mutation and committed only at the coherent result; native pump
reentry is barred. This draft still needs independent source review (including
post-result notification failure handling), paired transpilation and real native
red/green qualification. It must not be described as a completed outcome.

### Reference-only source projection (2026-10-08)

The first bounded reference transpilation of the exact shared queue fixture at
`3d81dcea` failed with four semantic diagnostics: three unconstrained generic
comparisons with bare null, and the nullable generic receiver passed directly
to the non-null `CFunction` parameter. The correction uses the existing
`CallbackContext` typed-null idiom and projects the receiver to `Receiver` only
after its explicit null rejection. No compiler or nullability rule changed.
The unchanged fixture now transpiles to C in 2.25 seconds (exit 0); its nullable
fixture-access warnings are retained. This is source acceptance only: no C
compilation, self-host parity, sanitizer or native runtime assertion ran.

Evidence is outside Drive under
`~/.cache/btrc/plan-consolidation-2026-10-07/ui2-linux-source-projection/`:
`3d81dcea/` retains the failed diagnostics and original data root;
`generic-fix-1/` retains the corrected data root, generated C, exact source diff,
SHA-256, command, result and full warnings. Reference time is 0.92 seconds for
the failed attempt and 2.25 seconds for the corrected attempt. Linux SDK source
projection needs the existing qualified Linux image: its ARM ELF reader and
SDK paths cannot be reused directly on this Mac. No ABI declarations were
invented to bypass that requirement.

The shared queue fixture additionally covers the reconciled terminal eligibility
rule (`ui2-approved.md:514–520`): a lifecycle cancel receipt is admitted once,
then retires as INELIGIBLE if the target is ineligible at invocation; restoring
eligibility neither delivers nor replays it, and scope drain returns the base
credit. This does not add a terminal bypass or a second public contract. The
expanded fixture reference-transpiles (exit 0, 2.24 seconds); all behavioral
assertions remain unexecuted. Evidence: `ui2-linux-source-projection/terminal-eligibility/`.

### Linux SDK projection and cancellation identity follow-up

The allocated existing-image reference projection passed against provider source
`818e9ee049041cd3eb5da7c90afd45a7a2db4aa3` and compiler
`808592c9735bd012fbde0dfd000ac8a72911de97` in 5.787 seconds. It used the real
Linux ARM native reader and strict imports, with a 90-second deadline; no C
compilation/link, GUI execution or assertion execution occurred. The isolated
entry retains the exact receiver/host/receipt-check class block from the native
executor fixture. Evidence lives at
`linux-provider-native-2202-grid47/ui2-publisher-818e9ee0/` in the consolidation
root; result, source inventory, reader/shell hashes and generated C are retained.
The full application scheduler was not projected: it remains in the real
LinuxApplication owner, whose provider-conformance work is incomplete. No fake
providers or copied scheduler implementation stand in for that closure.

Emitted-source review then exposed an independent cancellation identity defect:
a never-admitted sequence gap below the high-water mark, or an already-entered
callback, was reported as already terminal. Fixture-only checkpoint `3e71518d`
adds gap, entered-call, true terminal, bounded eviction and conservation checks.
The subsequent implementation retains only `capacity` recent terminal identities
in preallocated plain storage under the existing mutex and separately recognizes
the currently entered identity. Unknown/evicted identities are STALE; entered
cancellation intent is REQUESTED, and the already-entered call may finish once.
All retirement paths update the same bounded ledger and aggregate dispositions.
This follow-up has formatting/diff inspection only and is **not covered by the
818 projection**; both frontend source checks and native red/green execution
remain pending. No heavy process was launched for this follow-up.
