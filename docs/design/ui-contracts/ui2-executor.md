# UI2 executor: worker publication, fair dispatch and host-owned loops

**Review draft — CX-UIA-19, `ui-2-contract-executor`.** This document proposes
behavior, operation ids and fixtures; it changes no public contract or provider.
Claude reviews it only in **CL-UIA-13**, against real UI1 results. CL-P2-22 may
use its host-loop shape for the earlier lifecycle compatibility check, without
freezing it. Windows, iOS/iPadOS and Android mappings remain provisional until
CL-UIA-22 checks their real shells. No native execution or performance result is
claimed here.

The source baseline is `f4317455de1e567d4d6290139e5ba28fbada7d0c`. References:

- [IApplication](../../../src/stdlib/GUI/IApplication.btrc) declares
  `IApplicationWork.run`, UI-thread-only `post`/`postAfter`, non-inline work,
  bounded admission and close/pollClose.
- [LinuxApplication](../../../src/stdlib/GUI/Linux/LinuxApplication.btrc)
  (`post`, `pumpEvents`, `runWork`, `runDelayed`, `pumpOnce`) checks the UI
  thread, limits dispatch to 4,096 events, and polls once past that boundary.
  Capturing a whole work batch and scanning a live timer list do not establish
  fairness under replenishment.
- [MacOSApplication](../../../src/stdlib/GUI/MacOS/MacOSApplication.btrc)
  (`post`, `postAfter`) uses the main run loop and native timer registrations;
  its native callback and pending-work owners already participate in shutdown.
- [BackgroundJobExecutor](../../../src/stdlib/BackgroundJobs/BackgroundJobExecutor.btrc)
  owns bounded job slots. `submit`, `cancel`, `poll`, `awaitCompletion` and
  `close` require its creating thread. A terminal slot retains its work until
  the owner takes `BackgroundJobCompletion`; `close` currently joins workers.
- [Callback](../../../src/stdlib/Callback.btrc) owns
  `ICallbackRegistration`, `CallbackScope` and `CallbackCancellation`, including
  pending, complete, retryable-failure and failed cancellation outcomes.
- [Native interop ownership](../native-interop-ownership.md), invariants 2–4,
  requires entry pinning and executor-affine release; ordinary ARC counters are
  not atomic. A thread-safe queue does not make arbitrary managed captures safe.
- [Native UI parity](../native-ui-parity.md), UI2 and E04/E24/E30/E40, defines
  the required behavior and controlled-load budgets. [PLAN](../../../PLAN.md)
  D24 requires a host-owned loop and reuse of `UIEventKind`/`UISemantics`.

## Proposed operations and compatibility

Names below are proposed catalog ids, not declarations to copy into production.
The payload/writer ABI needs the ownership review below before signatures freeze.
New ids enter a reviewed catalog amendment; they do not change the frozen UI0
162-operation denominator. Existing ids keep their identity when strengthened.

| Operation id | Proposed input/result and execution context |
|---|---|
| `IApplication.createPublisher` | UI thread: capacity, maximum payload bytes, delivery receiver and lifetime scope → outcome containing a publisher and `ICallbackRegistration`; fail atomically before native publication. |
| `IUIWorkPublisher.tryPublish` | Worker or UI thread: generation, sequence, suspension class, optional replacement key, bounded plain-data payload → explicit admission outcome. Never execute the receiver inline. |
| `IUIWorkPublisher.requestCancel` | Worker-safe generation/sequence cancellation intent → requested, already terminal, stale or closed; no callback or managed release on the producer. |
| `IUIWorkReceiver.deliver` | UI executor only: immutable delivery snapshot and receipt identity; invoked only after generation and registration checks. Receiver retained by its UI registration. |
| `IApplication.post` | Existing UI-thread operation stays non-inline and source-compatible; shares accounting/fairness rules, with its existing exception-based rejection. It does not become worker-safe. |
| `IApplication.postAfter` | Existing UI-thread operation stays non-inline and returns `ICallbackRegistration`; uses monotonic deadlines and declared default suspension policy. |
| `IApplication.schedule` | UI thread: work, monotonic delay and explicit cancel/defer/replace policy → scheduling outcome and existing registration type. Provides the explicit policy missing from `postAfter`. |
| `IApplication.attachHost` | UI thread: platform host adapter → attach outcome plus scoped registration; one owner-loop attachment per application. Does not start or nest a loop. |
| `IApplication.isRunning` | Existing query means attached and servicing, including an OS-owned loop; suspended is a separate lifecycle state, not a second loop. |
| `IApplication.requestQuit` | Existing nonblocking request starts the shared shutdown protocol; a mobile adapter requests permitted scene/activity teardown, never process termination. |
| `IApplication.close`, `IApplication.pollClose` | Existing operations seal admission and report drain status; neither joins a worker synchronously nor pumps nested UI events in the proposed integration. |
| `BackgroundJobExecutor.subscribeCompletionReady` | Proposed owner-thread registration of a bounded native wake endpoint; reports that terminal slots are available, without handing `BackgroundJobCompletion` to a worker-side UI callback. |

`GUI.run` and `IApplication.run` remain the desktop convenience entry. `run`
rejects an already host-attached application; attachment rejects a running or
closed application. Attachment failure leaves neither a registered native source
nor a retained receiver. Detaching seals ingress and drains before its
registration becomes complete. No new cancellation hierarchy replaces
`ICallbackRegistration`/`CallbackScope`.

## Admission and ownership

The UI owner preallocates a bounded mailbox and installs its receiver, scope and
cleanup lease before exporting a worker writer. The producer holds an explicitly
synchronized **native writer lease**, not an `IView`, callback receiver, mutable
managed collection or managed closure. The eventual btrc API must expose only a
checked handle whose lifetime is independent of UI-object ARC. It cannot be a
raw pointer to a reclaimed application. No new compiler transfer semantics are
assumed by this draft.

General publication copies a bounded plain-data record into reserved storage.
Managed strings, object pointers, JNI local references and UI handles are not
plain-data payloads. Large results stay in the owning job slot or an explicitly
reviewed unique-resource transport; a small identity notification wakes the owner
to retrieve them. This keeps the existing `BackgroundJobCompletion` owner path
instead of moving it across arbitrary threads. Real-time/audio callbacks cannot
call this allocating or locking path; their existing bounded real-time channel
remains separate.

Each application declares limits for outstanding normal work, mailbox bytes,
publishers and deferred/replacement keys. Accepted, executing and suspended work
all count until terminal disposal. Immediate work, due/future timers and worker
results cannot evade accounting by moving between queues. A bounded reserved
control lane handles close, cancellation, wake state and cleanup; it is charged
when a publisher/owner is created, not allocated opportunistically at close.

Admission checks and commits under the same mailbox synchronization:

1. Validate the live native writer lease, payload size and generation. An epoch
   never reuses an exhausted identity; exhaustion rejects explicitly.
2. Reserve storage and terminal cleanup capacity. If either is unavailable,
   reject before accepting responsibility for delivery.
3. Copy/publish the immutable record with release/acquire synchronization, mark
   the receipt accepted, and arrange one native-loop wake for pending work.
4. Return without waiting for UI progress. A mutex may serialize this bounded
   operation; it may not be held across a callback, native blocking call or join.

| Admission outcome | Ownership and caller obligation |
|---|---|
| accepted | Mailbox owns its copy and terminal accounting; caller may release its original. Acceptance is not a promise that a closing target will receive a callback. |
| replaced | Only an explicitly replaceable record with the same owner, generation, interaction, registration epoch and key is replaced. Retire the prior receipt as superseded and dispose its payload once. |
| full | No ownership transfer; preserve/retry nonreplaceable product intent through an explicit caller policy. Never silently spin or drop a final commit. |
| closed / stale / cancelled | No new delivery; caller retains its input. Stale generation and requested cancellation remain distinct diagnostic reasons. |
| invalid / resource-failed / wake-failed | No accepted receipt if failure occurs before commit. After commit, fail the endpoint and account for the accepted receipt through terminal cleanup; never report a retryable rejection that could duplicate it. |

A normal queue filled with previews cannot consume a terminal-event reservation.
Each in-progress edit/gesture needs its own pre-reserved commit/cancel capacity;
when it cannot be reserved, refuse to begin the interaction with an explicit
outcome. Do not retroactively reject a native final input already dequeued. The
provider retains that event, yields its source, or delivers it through the
bounded terminal lane. Lossless admission is not an unbounded-memory promise.

Native wake coalescing is separate from payload coalescing. A single pending
wake may represent many records. On draining, clear the wake flag and recheck
the queue under synchronization so a producer racing the empty transition
cannot strand work. Test failed wake installation, producer-versus-drain and
producer-versus-close interleavings. A native-source failure seals the endpoint,
reports failure and preserves cleanup obligations; periodic polling is not the
fallback success path.

## Delivery, cancellation and background completion

An accepted receipt has exactly one terminal disposition: delivered, cancelled,
stale-generation, superseded, closed or failed. Delivery is FIFO for ordered
records within one owner/generation/interaction; unrelated native event classes have no
invented global order. Replacement is opt-in and may not cross an ordered
barrier or replace a commit, release, close decision or completion side effect.
Snapshots carry interaction id, sequence, model revision and origin as defined by
the control draft. Relative keyboard/accessibility adjustments are ordered,
nonreplaceable operations even when their resulting value is a snapshot. Reuse
`UIEventKind` for semantic event meaning, not executor control messages; this
draft proposes no new event-kind constants.
The [control draft](ui2-control-events.md) owns preview/commit/cancel semantics:
setters synthesize no user actions (an explicit MODEL-origin cancellation is not
a product command), native synchronous decisions stay synchronous,
and queued semantic notifications run after their native callback unwinds.

Immediately before invocation, the UI executor rechecks the registration,
generation, cancellation and lifecycle eligibility. It pins the receiver across
the callback. Cancelling during that callback prevents later entry but does not
free the in-flight receiver. `pollCompletion` observes progress; retryable native
unregister failure requires the existing explicit cancellation retry protocol.
No receiver runs while queue synchronization is held. Exceptions are contained
by the provider callback boundary, recorded as failed receipts and routed to the
existing application error policy after cleanup.

For BackgroundJobs, worker code marks its existing slot terminal, then signals
the bounded completion-ready endpoint. The owning thread drains `poll()` under
the fair completion budget and obtains the original ticket, kind and work from
`BackgroundJobCompletion`. A level-triggered ready bit persists until terminal
slots are drained; ordinary queue saturation must not lose a completion.
Registration after a slot becomes terminal must observe that ready state too.
Cancelling a UI subscription never changes the actual completed/failed/cancelled
job result. It suppresses stale UI delivery while the owner still reclaims work.

A closed window invalidates its generation before any next delivery. Reopening
or recycling a view uses a fresh generation. A failed save or cancelled close
prompt does **not** invalidate it: the [lifecycle draft](ui2-lifecycle.md) keeps
that reversible transaction alive until close is authorized. Completion after
irreversible close is reclaimed without touching that window; an application
service may still observe the job outcome through its own live registration.

At application shutdown: seal public ingress, cancel domain deliveries, finish
in-flight callbacks, drain reserved terminal cleanup, then unregister native
wake sources and release leases. Keep native writer storage alive until all
producer leases are retired. A worker that never cooperates yields pending or
failed cleanup, never a false complete result or a blocking UI-thread join.
The current `BackgroundJobExecutor.close` joins synchronously; the UI integration
therefore needs a reviewed asynchronous stop/drain adapter or owner placement
that preserves its owner-thread checks. Calling its existing `close` from a
random helper thread is invalid.

Final UI-affine release also needs a cleanup lease reserved while the object is
live. Posting an already-destroyed object from a destructor is not a solution.
Failed cleanup remains retained and observable under E31; this design cannot
change native interop `release-executor` behavior or make ARC atomic.

## Fair dispatch and suspension

Each native-loop turn services bounded slices of input, semantic work/worker
completions, due timers, presentation and close/cleanup. Rotate the starting
class and the active window/scene to prevent a busy first owner starving others.
Both a count budget and a monotonic time budget bound each slice. The provider
records their chosen values in evidence; 4,096 is a regression boundary, not a
portable scheduler constant. Reposted immediate work and zero-delay timers enter
a subsequent scheduling round, never the currently iterated live list.

Check the budget **before dequeue**, or retain the dequeued event in an owned
carry slot across the yield. Preserve every admitted nonreplaceable event and
its ordering through the next turn. Close/cleanup has a reserved scheduling
opportunity every turn. Input floods cannot monopolize rendering, and rendering
cannot block on a missing drawable. Only runnable classes accrue service-gap
measurements; future timers, hidden presentation and suspended work do not.

Timers use a monotonic deadline, not civil time. A due timer fires at most once
unless its owner explicitly reschedules it. Suspension policies apply per
scene/owner, while live scenes and application services continue independently:

| Policy | While suspended | On resume or recreation |
|---|---|---|
| cancel | Mark queued work cancelled; retain only required cleanup. Reject newly submitted work for that suspended policy. | Never replay it. A fresh request gets a fresh receipt. |
| defer | Retain bounded semantic work and original monotonic deadline. Capacity exhaustion rejects explicitly. | Deliver eligible nonstale work once; an overdue timer runs once, not once per missed interval. |
| replace | Keep only the newest state for each declared bounded key. | Deliver that state once; expired animation frames produce one current invalidation rather than a backlog. |

For compatibility, `post` defaults to defer, while `postAfter` is a one-shot
defer-until-resume timer; `schedule` makes other policies explicit. Animation
owners must choose replace rather than inheriting the timer default. Wall-clock
changes never accelerate, resurrect or reorder monotonic work. Product/audio
clocks remain separate. A process killed by the OS cannot promise in-memory
completion; durable work must use the lifecycle/restoration contract, not an
executor queue. Recreation gets a fresh generation and never replays old commits.

## Five-platform host mapping (proposal, not qualification)

| Family | Native-loop attachment and wake candidate | Required proof or dependency |
|---|---|---|
| macOS | Existing NSApplication owner, a main-run-loop source or main-queue wake with one coalesced pending signal; desktop `run` delegates to it. | UI1 AppKit result, common/modal loop-mode behavior and no recursive dispatch; preserve existing callback pinning. |
| Linux | Existing SDL loop on X11/Wayland, native wake event and owned carry slot. If D23 selects GTK4, a bound GLib main context replaces this adapter. | UI1 SDL E40 proof on both backends; GTK4 route waits for D23 and the GObject binding. GLib context affinity remains checked. |
| Windows | Application-owned message loop with `MsgWaitForMultipleObjectsEx`, event/message wake and a bounded executor turn. | Stage 24/25 target/host lane; function-table and COM interop; nested modal loops must preserve close/cancellation without reentering semantic delivery. |
| iOS / iPadOS | UIApplication/scene delegates own entry. Attach on the main thread; a main-loop wake schedules bounded work and returns to UIKit. Never call a desktop blocking `GUI.run` from a delegate. | Stage 24/25 host lane, UIKit interop CL-P2-21 and lifecycle review CL-P2-22. Use the `ios` family with separate iPhone/iPad `device_class` evidence, independent scene generations and hardware-keyboard input where available. |
| Android | Activity and main Looper own entry; a coalesced Handler wake drains one bounded slice, then returns. Choreographer supplies presentation opportunities separately. | Stage 24/25 host lane and checked JNI CL-P2-09/CL-P2-24; CL-P2-22 lifecycle review. Activity recreation invalidates its generation, never an unrelated live application service. |

Adapters expose host lifecycle transitions to the same executor state machine;
they do not each invent a second scheduler or ownership model. Android Back and
iOS scene-disconnect requests follow platform/lifecycle decisions rather than
unconditionally killing the process. External callbacks cannot invoke UI work
before host attachment; registration and initial-ready checks close that race.

## Fixture outlines and evidence

All outcomes below are acceptance targets, not measured results. Execute through
reference and selfhost with plain and ASan/UBSan provider configurations where
supported. Record revision, provider, frontend, runner, native backend, limits,
clock mapping, load and platform/device class. Hosted/simulator correctness is
stand-in evidence; physical latency and the 30-minute BTRSmith audio/UI soak keep
their own gates. Do not convert unavailable native evidence into a pass.

| Case | Fixture and assertions |
|---|---|
| E04 / N04 | Park the native loop with no polling timer. Complete worker jobs before subscription, during sleep, during drain-to-empty and after close. Cancel before and during callback; recycle target generations. Assert a native wake, one terminal disposition per accepted receipt, no stale mutation, no duplicate side effect, and zero retained payloads/leases after successful drain. Inject wake and unregister failure and observe explicit pending/failed cleanup. |
| E24 / N04/N20/N27/N48 | Fill exactly the declared capacity and byte limit, then publish one more item; mix deferred work, timers and cell-image updates. Assert explicit full, bounded depth/bytes, replacement only by matching key/generation, terminal reservation survives preview pressure, and no image from an old cell generation appears. Close a scene with producers active and verify accepted equals all terminal dispositions plus explicitly pending cleanup. |
| E30 / N01/N04/N48 | For cancel/defer/replace, suspend with edits, delayed work and frames pending, move wall time both directions, then resume. Repeat with recreation instead of resume, and with two independently suspended scenes (including iPad). Assert cancelled work never returns, deferred overdue timers run once, replacement delivers only final state, fresh generation rejects old work, and no frame backlog or duplicated durable command appears. |
| E40 / N04/N05/N08/N48 | Inject identifiable 4,095, 4,096, 4,097 and 8,193-event bursts, **100 bursts per size**, placing final release, committed text and close at the boundary in separate trials. Record native enqueue rejection separately. Assert zero unexplained loss, duplicate delivery or reordered ordered events; if budgets change, retain these cases and add limit−1/limit/limit+1/two-limits+1. |

E40 also runs a separate **10-minute** declared load with bounded, nonblocking
handlers, sustained input, worker completions, due timers, self-posting immediate
and delayed work, and two visible windows or independently updating regions.
Measure monotonic admission-to-delivery per accepted short semantic command:
**p95 ≤100 ms**. Measure the maximum gap while each input/completion/timer/
presentation class is continuously runnable: **≤250 ms**. A close request begins
its decision/shutdown path within **250 ms**; asynchronous save or resource drain
has its separate contract. Sample handler duration, producer rate, accepted and
rejected counts, coalescing/dispositions, queue bytes/depth and presentation.
Never report rejected work as delivered. Overload and intentionally blocking
handlers are separate trials; no preemption guarantee is inferred from these
budgets. Presentation timestamps, not callback duration, feed the separate frame
and input-to-visible gates.

## Review and landing dependencies

- **CL-UIA-13:** approve or revise operation names, bounded native-writer transport,
  admission accounting, suspension defaults, termination and loop-mode rules
  with the control and lifecycle drafts. Actual interface edits wait for that
  approval and the atomic UI2 provider landing (CX-UIA-21 and CL-UIA-14).
- **CL-P2-22:** check this host-owned shape against I1/A1 lifecycle before those
  owners land; CL-UIA-22 rechecks contracts on all five real shells.
- **BackgroundJobs implementation:** it is a compiler-import-sensitive package.
  WORKSTREAMS §3.4 notes that `BackgroundJobExecutor.btrc` itself is currently
  outside the compiler closure, while other BackgroundJobs modules are inside.
  Do not infer that a shared wake/worker change is exempt: the implementation
  lane builds its own `btrcc` and reaches the bootstrap fixed point, then performs
  the host-entry parity checks required by §3.4 when touching the import closure.
- **Ownership request:** no compiler/runtime implementation is authorized here.
  If the native writer lease needs new transfer, affinity or holder support,
  submit `REQUEST(CL-REQ)` with a minimal two-frontend reproduction before
  implementation. Preserve the existing interop ownership model; do not bypass
  it with cross-thread managed captures.
- **Shutdown request:** the BackgroundJobs integration owner must provide a
  nonblocking completion/stop strategy before advertising the UI close budget.
  Current synchronous `close` and owner-only `poll` are explicit constraints,
  not proof that such an adapter already exists.
