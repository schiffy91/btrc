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
