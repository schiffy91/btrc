# UI2 lifecycle contract draft

Packet: **CX-UIA-20**. Status: **proposal for CL-UIA-13 review only**.
Source baseline: `f4317455de1e567d4d6290139e5ba28fbada7d0c`.
This document neither changes a public interface nor records executed evidence.
Claude owns approval under [D27](../../../WORKSTREAMS.md#2-decision-d27-two-builder-agents-and-which-ui-work-starts-early).
The eventual interface landing is CX-UIA-21, with macOS and Linux providers
landed atomically through CL-UIA-14. Windows, iOS/iPadOS and Android remain
provisional until CL-UIA-22 reviews their real shells.

## Scope and source observations

This is UI2's only draft writer for IView lifecycle semantics. UI3 commands,
UI5 layout, UI8 semantic trees and UI9 presentation consume the state defined
here; they do not add a second ownership or shutdown model. The executor draft
is CX-UIA-19 (`ui2-executor.md`), and control events are CX-UIA-18
(`ui2-control-events.md`). Their signatures are reconciled in CL-UIA-13.

| Current source | Observation at the baseline | Proposal and acceptance case |
|---|---|---|
| [IWindow](../../../src/stdlib/GUI/IWindow.btrc), [MacOSWindow](../../../src/stdlib/GUI/MacOS/MacOSWindow.btrc), [LinuxApplication](../../../src/stdlib/GUI/Linux/LinuxApplication.btrc) | The public API has final close/drain, but no dirty-close decision. `windowShouldClose` returns true; Linux closes after a request. | Separate request/decision from irreversible close, E46. |
| [IContainer](../../../src/stdlib/GUI/IContainer.btrc) | Attach/detach transfer subtree responsibility, but no ordered move or batch result exists. | Identity-preserving mutation with explicit failure outcomes, E29. |
| [IView](../../../src/stdlib/GUI/IView.btrc), [LinuxWindow](../../../src/stdlib/GUI/Linux/LinuxWindow.btrc) | `isVisible` means a local flag. Linux hidden/minimized events return without updating the stored frame-eligibility flag. | Separate eligibility and exposure, E39/E42. |
| [Callback](../../../src/stdlib/Callback.btrc), both window providers | Cancellation has pending/failure states. Window destructors require completed teardown; ordinary final reference release cannot stand in for asynchronous cleanup. | Explicit executor-bound close/drain and retained cleanup ownership, E31. |
| [IImageHandle](../../../src/stdlib/GUI/IImageHandle.btrc), [MacOSImageView](../../../src/stdlib/GUI/MacOS/MacOSImageView.btrc), [LinuxImageView](../../../src/stdlib/GUI/Linux/LinuxImageView.btrc) | macOS gives NSImageView a native image; Linux retains a mutable handle and stops painting when it closes. | Independent retained presentation, E35. |

These are source observations, not native behavioral results. The normative
case descriptions and numeric thresholds remain in
[native-ui-parity](../native-ui-parity.md); the stage exit remains
[PLAN Stage 32](../../../PLAN.md#stage-32-ui2-contracts-events-executor-lifecycle-and-the-libraryui-split).

## Proposed operations and values

Names below are proposed catalog operation ids, not declarations to import.
Existing ids keep their identity even when semantics are strengthened. New ids
stay pending until the approved interface diff and a reviewed catalog release.
Do not change the frozen 162-operation or 47-case denominator for this draft.

| Owner and operation ids | Proposed contract | Cases |
|---|---|---|
| `IWindow.requestClose`, `IWindow.onCloseRequested` (new) | Request reason and owner generation identify a pending transaction; one scope-owned decision handler receives it. Request is nonblocking. | E46 |
| `IWindow.close`, `IWindow.pollClose` (existing) | Irreversible authorized shutdown and nonblocking completion query; neither presents a prompt. | E31/E46 |
| `IWindow.state`, `IWindow.onStateChanged` (new) | Immutable coherent state snapshot and scope-owned notification covering size, scale, activation and exposure. | E42 |
| `IContainer.insert`, `IContainer.move`, `IContainer.applyBatch` (new) | Ordered operations with validated indices and an explicit transaction result. | E29 |
| `IContainer.attach`, `IContainer.detach`, `IContainer.childAt`, `IContainer.childCount` (existing) | Existing ownership preserved; enumeration exposes committed order. | E29 |
| `IView.interactionState`, `IView.onInteractionStateChanged` (new) | Effective state snapshot and observation; local enabled preferences remain owned by controls. | E39 |
| `IView.isVisible`, `IView.setVisible`, `IView.close`, `IView.pollClose` (existing) | Local visibility remains local; shutdown invalidates delivery eligibility and drains on the UI executor. | E31/E39 |
| `IImageView.setImageHandle`, `IImageView.setImage`, `IImageHandle.close` (existing) | Publication retains presentation independently of the caller's handle. | E35 |

All subscriptions return the existing `ICallbackRegistration`, accept a
`CallbackScope`, and obey CX-UIA-18 cancellation rules. Exact value type names,
handler signatures and error representation need review, not separate callback
infrastructure. Values carry stable owner identity plus generation; native
pointers and callbacks never become restoration data.

## Close request is a revision-checked transaction

The request path serves native window close, app quit, and later UI3/UI5/UI7
navigation. A request contains owner identity/generation, a transaction id,
reason and intended document revision. The document owner supplies revision
and dirty-state truth. The window never infers successful persistence from a
dialog disappearing, a worker finishing, or an OS saved-state checkpoint.

The proposal permits one decision handler per close owner. A second live
handler registration fails explicitly. No handler means the application has
declared the owner safe to close; callers with dirty state must register before
exposing it. Canceling a handler while its transaction is pending resolves that
request as canceled. Repeated requests for the same owner and pending intent
return the existing transaction; another window receives its own transaction.

| State | Trigger | Result |
|---|---|---|
| Open | Request accepted | Enter AwaitingDecision; capture revision and retain owner/transaction. Synchronously veto or defer native destruction. |
| AwaitingDecision | Cancel | Resolve Canceled; keep draft, route, focus and scroll anchor. Return to Open. |
| AwaitingDecision | Discard | Authorize only the acknowledged revision. If newer edits exist, request a new decision before proceeding. |
| AwaitingDecision | Save | Enter Saving; issue one document save with transaction/revision identity. |
| Saving | Save failure | Preserve the dirty draft; return to AwaitingDecision with the error. Retry requires a new explicit Save choice. |
| Saving | Successful save of current intended revision | Authorize shutdown/navigation once. |
| Saving | Completion for an older revision after another edit | Preserve the newer draft; return to AwaitingDecision. Never close from the stale completion. |
| AwaitingDecision or Saving | Owner invalidated, parent lost, or cancellation | Resolve Canceled/OwnerLost once; invalidate late completions. A save already in progress may still persist its captured revision, but cannot authorize close. |
| Authorized | Matching owner/generation still live | Consume a single-use authorization and call final close, or commit the selected navigation. |
| Closing | Repeated request or completion | No new prompt/save/authorization. Observe the existing drain. |

Decisions are serialized on the UI executor. Save work may run on a worker;
its completion is marshaled back and checked against transaction, generation
and revision. Domain editing may continue while Saving; it therefore must be
revisioned. No duplicate save is issued merely because another native close
arrives. An explicit retry has a distinct attempt identity.

Native synchronous answers never wait for async Save/Discard/Cancel. A denied
native close returns immediately; the later authorized continuation bypasses
the decision hook once, scoped to its transaction. This prevents a recursive
prompt without creating a global bypass flag. No nested modal loop or busy
poll is allowed. Application-initiated `close()` remains the low-level final
shutdown API; dirty-dismissal entry points must call `requestClose` instead.

For app-wide quit, the application coordinator first collects authorizations
from all windows, revalidates their revisions, then begins irreversible close.
One cancellation leaves every not-yet-closed window usable. Saved documents
may remain saved after a canceled quit; pending Discard choices do not destroy
drafts before the group commits. New windows/edits invalidate the affected
authorization and force reconciliation before commit. Once final close starts,
teardown failure is reported; it cannot resurrect windows already destroyed.

Interactive Back preview does not mutate durable state or pop a route. A
canceled gesture cancels the preview, not the draft. Android uses native Back
integration, not an ordinary key binding. OS process death or forced termination
cannot promise a consent dialog or completed save; recovery is limited to
previously durable checkpoints under E47, outside this packet's contract.

## Ordered mutation and failure policy

`insert(child, index)` admits an open detached child at `0..childCount`.
`attach` remains append. `move(child, destinationIndex)` addresses an already
attached direct child, with the destination in the final sequence after removal
(`0..childCount-1`). Moving to the same index succeeds without detach/recreate.
`detach` returns the same open child. Cross-parent reparenting remains explicit
detach then insert; a batch is limited to one parent in this proposal.

`applyBatch` receives the expected tree revision and an ordered list of insert,
move and detach edits. Validate the whole proposed sequence first: cycles,
duplicate children, foreign providers, closed/attached insertions, indices and
revision mismatch fail without native mutation or ownership transfer. On success,
the parent commits one new tree revision and notification. Existing identities,
subscriptions and surviving focus/selection persist. A move is not a close.

The batch retains old and proposed children while native operations execute.
The UI executor serializes it; reentrant mutation fails before changing the
tree. Semantic notifications and user input against intermediate order are
deferred until a result exists. Native callbacks during mutation cannot invoke
application code against a partly updated tree. This does not promise an atomic
compositor frame or atomic native toolkit API.

| Result | Observable tree and ownership | Retry |
|---|---|---|
| Committed | Complete requested order; one revision. Detached results transfer back to the caller, still open. | No retry needed. |
| Rejected | Validation failed; original tree/revision unchanged. | Correct the request. |
| RolledBack | A native step failed; inverse operations restored the original order and ownership. Report failing step/error. | Explicit new batch against the original revision. |
| FailedConsistent | Rollback also failed; return the reconciled actual child order, a new revision, failed step and retained/detached ownership list. Mark the parent faulted and disable interaction pending recovery. | No blind replay; caller must recover or close the faulted parent. |

A provider must reconcile native membership before returning FailedConsistent.
If it cannot prove membership, it quarantines that parent, retains all possibly
owned children, reports pending/failed cleanup, and permits only inspection and
close/drain. It never labels unknown ownership a successful rollback. Child
enumeration in this terminal fault exposes the last coherent logical snapshot
with an explicit fault state; it is not represented as verified native order.
CL-UIA-13 must choose the concrete result/error encoding, including this
quarantine state. Failure does not implicitly close detached children or emit
duplicate attach/selection events. E29 injects both forward and inverse failure.

## Effective interaction state

The state snapshot separates facts which existing visibility queries conflate:

| Field | Meaning |
|---|---|
| Local visibility | The flag owned by this view; preserved through ancestor transitions. |
| Local enabled preference | A control's existing enabled preference, when supported; neutral true for owners with no enabled setting. No second enabled store on IView. |
| Inherited eligibility | Ancestor visibility/enabled constraints, attachment, lifetime and any temporary fault/interaction barrier. |
| Effective input eligibility | Open, attached to an eligible owner, locally eligible and eligible through ancestors. Rechecked at delivery, including queued actions. |
| Layout participation | Whether layout reserves space; hiding alone preserves current layout participation. Collapse is a later explicit UI5 policy. |
| Exposure | Observed presentation state from the window, separate from eligibility and layout. Unknown/offscreen does not itself mean disabled. |

On an eligible-to-ineligible transition, mark the subtree unavailable before
admitting another input event. Settle still-active interactions once: cancel pointer
capture without synthesizing activation; cancel uncommitted IME composition
while preserving already committed text; dismiss popups whose anchor vanished;
move focus to a valid owner using the command/focus policy, or clear it. Notify
state subscribers after the coherent transition. Cancellation carries SYSTEM
origin and the original interaction identity from CX-UIA-18. An already accepted
commit is terminal and never receives a later synthetic cancel. If its queued
delivery becomes ineligible, discard domain delivery while retaining resource
cleanup; do not turn it into another command. A callback already admitted
may finish; it may not enqueue new mutations into an ineligible generation.

For native IME paths that cannot cancel without committing, the provider must
report the mismatch for review, not silently substitute a different editing
policy. UI3 owns command routing and UI8 owns semantic-tree mapping. A disabled
but visible control remains distinguishable from hidden content; an offscreen
virtualized item may remain semantically realizable. Restoring eligibility never
replays input, steals focus, or resets child enabled preferences. Detach cancels
capture but preserves registered subscriptions for reattachment, as IView does
today; close cancels subscriptions permanently.

## Window state and exposure

`state` supplies content dimensions in logical points, backing scale, requested
visibility, native visibility/minimized state, window activation, application
activity, exposure (`exposed`, `notExposed`, `unknown`) and drawable readiness.
Keep reasons for `notExposed` so hiding, minimization and known occlusion can be
tested separately. Resizing/scale changes yield one coherent snapshot revision;
the executor draft owns any latest-value notification coalescing. Reading the
snapshot before subscribing and then subscribing must have a documented
revision handshake or initial delivery so clients cannot miss the first change.

No provider infers complete occlusion from missing paint events. SDL/Wayland
may report unknown occlusion. A hidden/minimized/inactive scene or unusable
drawable suppresses presentation when platform policy establishes that it is
non-presentable; mere window deactivation does not universally hide a window.
The model and latest invalidation survive suppression. Drawable restoration
renders the current revision once without replaying obsolete frames. Audio and
worker completion keep their own lifecycle policy; exposure cannot stop them
incidentally. No exposure rule substitutes for an explicit close.

## Final release and executor shutdown

The existing `CallbackCancellation` states remain the vocabulary: NotRequested,
Pending, Complete, RetryableFailure and Failed. Exact spelling remains the
existing enum's spelling. A request/prompt/save does not seal its owner's
executor domain. **Final `close()` does**: invalidate delivery generation,
reject new domain work, cancel registrations, settle active input, drain
admitted callbacks and descendants, then destroy native resources on the UI
executor. `pollClose()` never begins shutdown, pumps a nested event loop or
retries a failed native operation.

Aliases observe one owner and one shutdown. Attached children cannot be closed
by an alias; parent shutdown owns their close. Partial construction records each
successfully acquired resource before publication and unwinds only those
resources. A callback initiating close may return Pending; it must return to
the executor before that callback can drain. UI-thread waits for itself are
forbidden. Native callback exceptions are contained at the boundary, recorded,
and trigger the declared cancellation/error path; no exception crosses a C ABI.

Pending and failure both retain cleanup responsibility. Complete alone means
the native resources and registrations are released and no future callback can
enter. A retryable result is not an instruction for `pollClose` to repeat a
failed foreign call: any retry needs a separately approved explicit operation.
A permanent failure stays observable and owned; it is never reported as closed
successfully. CL-UIA-13 reconciles today's thrown provider errors with these
states before freezing the interface.

To handle the last external reference disappearing off the UI thread, a native
owner must hold a pre-registered executor cleanup lease independently of that
external reference. Its terminal cleanup capacity is reserved before native
publication, using CX-UIA-19's terminal channel. Dropping the external reference
signals that lease; it does not run native destruction on the worker. The lease
keeps the executor and cleanup state alive until Complete. This is a proposal
requiring proof with the language's existing ownership/cycle rules, not a claim
that current destructors already support it. No resurrection of a partly
destroyed managed object or captured raw `self` is permitted.

Application shutdown first stops domain admission and requests owner close,
then continues servicing terminal cleanup until leases drain. Only afterward
may the executor stop. If the process cannot remain alive, report unfinished
cleanup; do not silently drop it or call worker-side native destruction a
fallback. Until the lease mechanism is proven, callers must retain owners and
explicitly complete close/drain before final release. CL-P2-22 consumes this
ordering for mobile lifecycle design; it does not approve this UI contract.

## Retained image presentation

Successful `setImageHandle` acquires an independent native/pixel presentation
reference before replacing the view's prior reference. It does not require
encoding/decoding on the UI thread. Caller reference release and explicit
`IImageHandle.close()` affect future publication, not presentations already
accepted. Two views retain independent presentations. Clearing/replacing one
does not invalidate the other. Detach alone preserves presentation; final view
close releases it after native use has drained.

Publication of a closed or foreign-provider handle fails explicitly and leaves
the previous presentation intact, including when it is the same handle alias
previously published. A racing close/publication has one linearized outcome:
publication acquired the presentation and succeeds, or observes closed and
fails. It never creates a partially retained image. Handle dimensions remain
queryable after close as immutable metadata; native resource access does not.
Worker creation remains supported. The provider defines any native-resource
release affinity and honors it on the final presentation reference.

## Platform feasibility to prove

Every row is a proposed mapping, not implementation or passed evidence.

| Platform | Close and executor boundary | Mutation, exposure and image proof |
|---|---|---|
| macOS | AppKit synchronous close delegate denies pending decisions; later authorized continuation closes once on the main executor. Application quit coordinates windows. | NSView order/rollback, native editor composition settlement, screen/backing notifications and occlusion state; independently retained NSImage. Test callback-close without a nested loop. |
| Linux SDL | SDL close event becomes a request, not immediate destruction; SDL UI thread owns final drain. | Software tree order and actual native/GPU membership reconcile; X11 and Wayland measured separately; unknown compositor occlusion preserved. Replace mutable-handle painting dependency with retained presentation. |
| Windows | Win32 close/quit dispatch routes through the transaction and message-thread continuation; shell/COM interop still gated. | Child order and rollback, focus/IME transitions, DPI/minimize/drawable loss, image resource lifetime. Desktop activity and exposure stay distinct. |
| iOS / iPadOS | UIKit scene dismissal is a request where veto is supported; forced background termination is not. Main-run-loop drain obeys suspension limits. | Scene activation/size/scale, image retention and view order. iPad multi-scene, split view and Stage Manager require two-scene isolation checks. One `ios` family; record iPhone/iPad `device_class`. |
| Android | Native Back callback/preview has commit/cancel semantics; Activity destruction is not a vetoable desktop close. JNI callbacks marshal onto the UI executor. | ViewGroup order, IME/capture settlement, Activity/window/drawable transitions and retained image lifetime. Process recreation cannot resume an old transaction with native handles. |

Windows/iOS/Android require Stage 24/25 host support and their Objective-C/JNI/COM
interop packets before native proof. CL-UIA-22 may require a versioned contract
change landed atomically with macOS/Linux; this table does not bypass that gate.

## Acceptance outlines for implementation packets

Run every applicable path for **100 cycles**, per frontend (`reference`,
`selfhost`), provider and sanitizer configuration supported by that host.
Linux runs both X11 and Wayland; iOS records iPhone and iPad destinations.
Record unsupported paths with their platform reason; never count skips as
passed. These outlines prescribe future tests; this draft executes none.

| Case and operation ids | Required sequence and fault injection | Oracle |
|---|---|---|
| E46: `IWindow.requestClose`, `IWindow.onCloseRequested`, `IWindow.close` | Per applicable close/quit/Back/tab/navigation path: Save, Discard, Cancel, save failure/retry, repeated native request, edit during save, late completion and parent loss. Include two windows and app-wide quit cancellation. | 0 lost drafts, duplicate saves, stale-revision closes or wrong-window results. Canceled preview preserves route/focus/scroll. One terminal outcome per transaction. |
| E29: `IContainer.insert`, `.move`, `.applyBatch`, `.detach` | Mutate with focused editor and pending image load. Inject failure at every forward and rollback boundary; include duplicate child, stale revision, reentry and cross-parent rejection. | Exact committed/rolled-back order, stable surviving identities, explicit ownership on every failure; no duplicate children, stale selection or callbacks from intermediate order. Quarantine is observable. |
| E31: `IView.close`, `.pollClose`, `IWindow.close`, `.pollClose` | Construction failure after each native acquisition; callback exception; close during callback; worker last release; application quit with pending cleanup; full domain queue when terminal release is needed. | 0 orphan handles, registrations, double releases or callbacks to destroyed owners. Complete only after drain; Pending/Failed retain a named owner. No UI-thread block. |
| E35: `IImageView.setImageHandle`, `.setImage`, `IImageHandle.close` | Worker creation, publish to two views, caller release, explicit close, race publication/close, clear/replace/detach/teardown in each order, reject closed/foreign handles. | Already-published images stay valid; rejected publication preserves prior content. 0 blank/stale images, use-after-free or leaked native resources after drain. |
| E39: `IView.interactionState`, `.onInteractionStateChanged`, `.setVisible` | Hide ancestor during composition, hide captured slider, disable form with popup/queued action, detach/reattach and restore. | Exactly one cancel/settlement; no later input changes an ineligible target. Child preferences preserved, focus not stolen, hidden/disabled/offscreen semantics distinguished. |
| E42: `IWindow.state`, `.onStateChanged` | Two windows; hide/minimize/cover/restore, display/scale change and drawable loss while model updates arrive; include app activity independently. | Unknown stays unknown; latest state/invalidation retained. When settled and known non-presentable, 0 presentation attempts over 60 s; current restored frame p95 ≤100 ms after drawable readiness. |

E42 timing on hosted/simulated runners is diagnostic unless qualification policy
admits that runner; physical exposure, display topology and mobile suspension
evidence remain owner sessions. Preserve raw transition order, revision/owner
identities, fault boundaries, final ownership counts and runner provenance.
E46 traces must contain revision ids and outcomes, never sensitive draft text.

## CL-UIA-13 review decisions and integration dependencies

Only CL-UIA-13 reviews and reconciles this draft as the UI2 contract. Its review
must resolve these concrete choices before CX-UIA-21 writes interfaces:

1. Freeze the transaction value/handler/result shape and the no-handler policy;
   verify application quit coordination without adding a second command owner.
2. Prove rollback and quarantine encoding on real macOS/Linux shells; do not
   weaken partial-failure visibility to make a provider appear atomic.
3. Reconcile IME cancellation and callback admission with CX-UIA-18, and state
   notification coalescing/generation checks with CX-UIA-19.
4. Prove the cleanup lease without violating ARC/cycle collection, and choose
   error reporting for thrown teardown failures versus cancellation statuses.
5. Approve retained presentation and the closed-handle publication race rule.

CL-P2-22 may use the request-versus-final-close distinction, suspension limits
and terminal-drain ordering as inputs while UI2 approval is pending. No compiler,
runtime, native-reader or generated-file change is authorized by this document.
If the lease or value representation requires such a change, the implementing
packet files a minimal reproduction as a `REQUEST` before proceeding. E47
restoration schemas, UI3 navigation policy, UI5 layout policy and UI8 semantic
tree contracts remain with their designated packets.
