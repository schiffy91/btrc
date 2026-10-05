# UI2 control events: review draft

**Status:** CX-UIA-18, docs only; not approved and not implemented. Source
baseline: `f4317455de1e567d4d6290139e5ba28fbada7d0c`. Review only in
`CL-UIA-13`, alongside the executor and lifecycle drafts, using UI1 results.
Windows, iOS/iPadOS and Android mappings are provisional until `CL-UIA-22`.
This proposes no compiler, runtime or generated-file changes.

## Sources and scope

[PLAN Stage 32](../../../PLAN.md#stage-32-ui2-contracts-events-executor-lifecycle-and-the-libraryui-split)
and [CX-UIA-18](../../workstreams/codex.md#cx-uia-18) require scoped text,
selection, range and scroll events. The acceptance authority is
[E01–E03 and E33–E34](../native-ui-parity.md). D24 retains the index selector
shim until BTRSmith re-pins and reuses the existing UI vocabulary.

The current portable interfaces have text getters/setters, index-only select
state, a double-valued slider without public range mutation, and vertical-only
scroll offset:
[ITextField](../../../src/stdlib/GUI/ITextField.btrc),
[ISelect](../../../src/stdlib/GUI/ISelect.btrc),
[ISlider](../../../src/stdlib/GUI/ISlider.btrc), and
[IScrollView](../../../src/stdlib/GUI/IScrollView.btrc).
[IButton.onAction](../../../src/stdlib/GUI/IButton.btrc) already uses queued
delivery with independently scoped cancellation. That lifetime model is reused.

The source baseline is not a parity claim. In particular,
[MacOSTextField.setText](../../../src/stdlib/GUI/MacOS/MacOSTextField.btrc)
compares through `text()`, whose implementation calls `validateEditing()`;
that requires scrutiny for IME side effects before declaring unchanged model
publication harmless. Both selector providers rebuild their option
presentation, and both slider constructors reject more than 1,000 intervals.
The fixture outlines below expose these gaps rather than assume them fixed.

## Proposed values and callback ownership

Propose one cohesive `GUI/ControlEvents.btrc` module for the types below.
These are semantic schemas, not compiled declarations. Strings and event
objects own their data; providers must copy any native borrowed storage before
returning from its callback. No native editor, event pointer, Java reference or
SDK range escapes the boundary.

| Proposed type | Contents and invariant |
| --- | --- |
| `ControlEventContext` | Source generation, monotonic interaction id and sequence, model revision, `USER`/`MODEL`/`SYSTEM` origin. Identity is scoped to a live control; sequence exhaustion fails explicitly, never wraps. |
| `TextControlEvent` | Context, owned text snapshot, phase (`DRAFT`, `COMMIT`, `CANCEL`), composing flag and optional cancellation reason. A composing snapshot is not committed text. |
| `SelectOption` | Unique nonempty string `key`, owned `title`, `enabled`; duplicate titles are allowed. Keys are opaque, case-sensitive and independent of order or localized title. |
| `SelectModel` | Owned option snapshot, nullable selected key, availability (`READY`, `LOADING`, `EMPTY`, `ERROR`), owned status text. The provider copies the caller's mutable vector. |
| `SelectionControlEvent` | Context, phase (`CHANGE`, `COMMIT`, `CANCEL`), previous accepted key, candidate key, resulting accepted key and optional cancellation reason. Keys may be null; titles are presentation only. |
| `SliderRange` | Finite minimum, maximum and nonnegative step; zero step means continuous. Minimum may equal maximum. |
| `SliderControlEvent` | Context, phase (`PREVIEW`, `COMMIT`, `CANCEL`), projected double value, range revision, absolute-pointer versus relative-adjustment input, existing `UIRangeAdjustment`, optional cancellation reason. |
| `ScrollOffset` / `ScrollRect` | Finite logical-point x/y and, for the rectangle, nonnegative width/height; document top-left origin. |
| `ScrollControlEvent` | Context, actual offset and visible rectangle after clamping. This is state observation, not a command. |
| `ControlCancelReason` | Escape/back, capture loss, eligibility loss, model replacement, source closing, or platform interruption. No string parsing to decide behavior. |

Each event receiver has one typed `void invoke(<Event> event)` operation.
Subscription methods take that receiver followed by `CallbackScope owner` and
return `ICallbackRegistration`. All reads, setters, subscriptions and delivery
are confined to the control's application UI executor. This draft does not make
controls worker-safe; workers use CX-UIA-19's publisher.

Use [Library.Callback](../../../src/stdlib/Callback.btrc), not a second token
or lifetime scheme. An independent application/component scope owns the
registration before native publication. Match the existing button policy:
one receiver per control/event channel; reject a replacement until the old
registration has completed cancellation. Distinct channels may have distinct
receivers. No subscription replays an initial action; initialize from getters.

Cancellation closes admission, unregisters native delivery and discards queued
events for that registration epoch. `cancel()` and `pollCompletion()` remain
nonblocking; retain the registration/scope until completion. Cancellation from
inside a callback lets that admitted callback return, then releases its owned
payload on the required executor. It cannot synchronously drain itself. A
registration cancellation does **not** invoke the receiver's control-cancel
event. A failed native unregister follows the existing retryable/failed
CallbackCancellation states; it is never reported as a completed release.

## Delivery, decisions and suppression

| Boundary | Class | Coalescing and return behavior |
| --- | --- | --- |
| Native edit acceptance, key consumption, popup navigation, pointer capture | Synchronous native decision | Resolve while the OS callback is active. No await, application command or nested event loop. Existing UI3 input/command precedence remains authoritative. |
| Text draft, select candidate change, absolute slider preview | Queued semantic state | May replace only an undelivered snapshot of the same source generation, interaction, registration epoch and event channel. |
| Text/select/slider commit or cancel | Queued terminal event | Never coalesce or cross a terminal boundary. Exactly one terminal result per accepted interaction while its subscription is live. |
| Keyboard/accessibility relative range adjustments | Queued semantic operation | Lossless: replacing `+1` with another `+1` would lose intent. Their preview and terminal records stay ordered. |
| Scroll offset/viewport observation | Queued state observation | Latest actual geometry may replace pending geometry; include origin so a model scroll is not treated as user input. |

Native decisions update control state and capture an immutable snapshot; queued
receivers run after native dispatch through CX-UIA-19's fair executor. Never
re-read a mutable native control when delivering an older event. Per-control
sequence order applies across channels. Listeners may publish model state, but
that publication cannot re-enter the current user callback.

Coalescing may not move a newer preview ahead of an intervening terminal event,
relative adjustment, model revision, or another control's ordered event. Keep
the final snapshot before its commit, or carry the complete final snapshot in
the commit if that preview was replaced. A full queue must use the executor's
explicit pressure/failure path, not silently discard an accepted commit or
throw through a foreign callback. Reserving terminal capacity before admitting
an interaction is a provider option for the executor review, not an assertion
that today's mailbox already does it.

**Setter rule:** model publication produces zero `USER` draft/change/preview or
commit events, including native notifications caused by a setter. Providers
track setter origin and suppress those callbacks; disabling an entire native
event channel would also suppress unrelated real input and is insufficient.
An unchanged publication is a true no-op: no owner replacement, revision bump,
caret move, composition reset, undo entry or event.

A changed model can invalidate an unfinished interaction. Settle it exactly
once with a `MODEL` cancel notice, never a user action or application command.
The notice describes the abandoned interaction, not permission to overwrite
the newly published model. A lifecycle transition may similarly produce a
`SYSTEM` cancel while the receiver remains live. Owner close or scope
cancellation instead discards delivery and drains resources. A commit already
accepted by native dispatch is terminal: eligibility loss does not turn it
into a second cancel; generation/cancellation checks can still prevent delivery
to a destroyed owner. CX-UIA-20 owns that teardown order.

## Text: draft is not commit

Native composition, selection and undo remain with the editor. A user edit
begins an interaction with the last accepted text as its cancellation baseline.
Draft events contain the current text and whether marked/preedit text is
active. The model must not echo preedit text back through `setText` as though it
were final. An identical published value does not terminate composition.

For the current single-line field, Return/IME Done commits the finalized draft
once; ordinary accepted focus departure commits once if the interaction is
dirty. A platform notification for both Return and end-editing is one
interaction, not two commits. A no-edit focus/blur produces no command.
Composition acceptance first finalizes the draft; the same key must not also
trigger an unrelated default-button command. The detailed routing remains UI3.

Escape first cancels active IME composition under native editor rules. If there
is no composition, it cancels the unfinished edit and restores the last
accepted text. Cancellation never manufactures a commit. Eligibility loss
settles active composition, cancels the unfinished edit and restores its
baseline before subsequent input dispatch; mere occlusion does not do so.
Native focus/IME feasibility is a review question, not a reason to silently
commit on every platform interruption.

Changed `setText` is authoritative model replacement: terminate the old
interaction with a MODEL cancel, establish the new accepted baseline and
advance the model revision. Providers must document any necessary native undo
boundary for changed text; unchanged text must preserve undo/selection and
composition. A queued event carries its old revision so a consumer can reject
stale model application. Validation of a committed value belongs to the
application; no asynchronous validator runs in the native edit-decision hook.

## Selection: identity and availability

`setOptions(SelectModel model)` validates and publishes one coherent snapshot.
Reject duplicate/empty keys, missing selected keys, inconsistent availability
or null required text before changing any native state. `EMPTY` requires zero
options and no selection; `READY` requires at least one option and may have no
selection. `LOADING` and `ERROR` may retain a previous snapshot/selection for
display, but cannot accept a user commit until ready. Status text is owned
presentation data. An all-disabled READY list differs from EMPTY.

A model-selected disabled option may remain selected and displayed; users
cannot newly choose it. No provider silently chooses the first enabled option.
Removing the selected key requires the caller's new model to specify a valid
replacement or null. `selectedKey()` immediately exposes that outcome, with
zero user commits. `setSelectedKey` accepts null or an existing key, including a
disabled key for model presentation; it is not a user activation API.

Reordering or relabeling options preserves selected and active-popup keys,
disabled policy and interaction identity when the provider can do so. A user
navigation step may emit CHANGE for a candidate; explicit acceptance emits one
COMMIT with the accepted key. Escape/back cancels the candidate and restores
the accepted selection and valid focus. Re-selecting the already accepted key
does not fabricate a changed-value command. If a refreshed model removes or
disables the active candidate, or a native popup cannot survive a refresh,
close it with one MODEL cancel and restore focus; never guess an index.

The legacy index shim remains through the BTRSmith pin bump (D24). `setItems`
keeps its current signature and validation: a nonempty list requires a valid
index, and an empty list requires -1. Internally assign keys in a reserved
namespace for that replacement snapshot; duplicate titles remain distinct.
The shim cannot promise stable identity across `setItems` calls. On a keyed
model, legacy index getters/setters project the current ordering; -1 represents
no selection. Existing item-enabled methods address the current snapshot.
Document that mixing replacement via `setItems` with stable-key clients ends
the stable-key session; never infer a key from a title.

## Slider: coherent range and exact product coordinates

`setRange(min, max, step)` validates the whole range, then clamps/snaps the
current value atomically. `setRangeValue(SliderRange range, double value)`
publishes range and value as one transaction: reject an invalid/out-of-range
input before mutation, then apply documented snapping. Keep the focused owner.
`range()` returns a snapshot. Existing `setValue` still rejects nonfinite or
out-of-range input and emits no user action.

Reject reversed ranges, nonfinite endpoints/step, negative step and a span
whose double representation overflows. Equal endpoints are a valid inert
range: value equals that endpoint and user input emits no commit. For positive
step, snap to the nearest `min + k*step` inside the range (ties toward the higher
value); the maximum is additionally reachable as an endpoint, including when
the span is not divisible by step. Continuous mode uses step zero. Reject a
step that cannot advance the represented value at the range's precision;
the exact-value adapter below is the route for unrepresentable integer steps.
Visible tick density is independent of logical steps: 999, 1,000 and 1,001
logical intervals must not change validity merely because of the old cap.

A pointer drag captures the starting value/range revision, emits replaceable
absolute PREVIEW snapshots and ends with one COMMIT. Capture loss, Escape or
eligible-to-ineligible transition cancels and restores the starting value if
the model revision still matches. Never restore over newer model state.
Changed range/value publication during a drag cancels that interaction before
publishing the new coherent state; unchanged refresh preserves it. A delayed
pointer-up from the abandoned interaction is ignored. Keyboard repeat and
accessibility adjustments are discrete committed intents, with an existing
`UIRangeAdjustment` identifying small/large increment/decrement or endpoint.

The native double is a projection, **never the authority for a 64-bit product
timeline**. Reuse
[UISemanticRange and UIRangeAdjustment](../../../src/stdlib/UI/Element.btrc)
for exact `long long` state and intents. The product adapter keeps exact
minimum/maximum/value/steps, applies relative adjustments using checked integer
arithmetic and clamps without overflow. A keyboard/accessibility commit carries
its adjustment even if the projected double cannot visibly move. A no-op model
refresh never reconstructs the integer from the projection.

For pointer input, the adapter explicitly quantizes the normalized position to
its exact logical grid and documents its error bound: at most half a logical
step plus the coordinate/projection error propagated to the integer domain.
Record track width, coordinate precision and the actual measured bound; an
arbitrary fixed one-unit guarantee would be false for huge ranges. Tests around
2^53 use exact integer assertions for keyboard/accessibility/no-op refresh and
the declared bound for pointer input. Changing application integers into
doubles to pass the test is prohibited. UI2 proposes the event information
needed by this adapter, not an unreviewed new integer slider interface.

## Scrolling: two axes and observation

Add `offset()`, `visibleRect()`, `scrollToOffset(ScrollOffset offset)` and
`onOffsetChanged`. Coordinates count logical points from document top-left on
every platform; providers normalize native axis direction, scale and insets.
Clamp each requested axis to `[0, max(0, contentExtent - viewportExtent)]`;
the visible rectangle is the viewport intersected with document bounds.
Reject nonfinite input before mutation. A content/viewport resize clamps both
axes coherently, preserving the offset where possible.

Offset observation reports USER input, MODEL scroll requests or SYSTEM resize
with actual clamped geometry; it is never a semantic command. Subscribe first,
read the initial state, and accept later snapshots by sequence. No animation or
scroll-end guarantee is invented here. A no-op request emits nothing.
Retain `scrollOffset()` and `scrollTo(double)` as the vertical compatibility
surface; the latter preserves x while updating y. Avoid an overload-only
catalog distinction: `scrollToOffset` has its own stable operation id.

Collection anchor identity and nested-scroll handoff remain UI6. This change
supplies geometry and observation; it does not claim E09 is closed.

## Existing UI vocabulary

D24 requires reuse rather than a parallel event enum. The phase and origin in
typed payloads distinguish states that `UIEventKind` alone cannot represent:

| Existing vocabulary | Typed interpretation |
| --- | --- |
| `UI_VALUE_CHANGED` | Text draft/value state; phase is required to distinguish final text. |
| `UI_SELECTION_CHANGED` | Keyed candidate/accepted selection with explicit phase. |
| `UI_RANGE_POINTER_PRESSED`, `MOVED`, `RELEASED`, `CANCELLED` | Input route into a slider interaction; not an automatic extra product command. |
| `UI_RANGE_ADJUSTED` plus `UIRangeAdjustment` | Exact relative keyboard/accessibility intent. |
| `UI_SCROLLED`, `UI_VIEWPORT_CHANGED` | Actual offset and visible-rectangle state. |

The UI adapter consumes one typed terminal result to invoke a product command;
it must not dispatch both a raw pointer-release command and the typed commit.
`UISemantics` supplies labels, values, disabled/read-only/busy presentation via
the shared semantics owners; this draft creates no new accessibility tree.
The existing role/value vocabulary is reused; full accessibility proof belongs
to UI8. No new UIEventKind constants or renumbering are proposed here.

## Proposed operation inventory

All ids below are proposals, including receiver entry points. Existing methods
not listed remain unchanged. Value schemas above need approved declarations
and export rows during `CX-UIA-21`; they introduce no implicit public builder
methods. This table does not amend the frozen UI0 denominator.

| Owner | New operation ids and proposed signatures | Changed existing ids |
| --- | --- | --- |
| ITextField | `ITextField.onDraftChanged`, `ITextField.onCommit`, `ITextField.onCancel`: `(ITextControlEventHandler handler, CallbackScope owner) -> ICallbackRegistration` | `ITextField.setText` (no-op/authoritative replacement semantics) |
| ISelect | `ISelect.setOptions(SelectModel model) -> void`; `ISelect.selectedKey() -> string?`; `ISelect.setSelectedKey(string? key) -> void`; `ISelect.optionsState() -> SelectModel`; `ISelect.onChanged`, `ISelect.onCommit`, `ISelect.onCancel`: `(ISelectionControlEventHandler handler, CallbackScope owner) -> ICallbackRegistration` | `ISelect.setItems`, `ISelect.selectedIndex`, `ISelect.setSelectedIndex`, `ISelect.setItemEnabled`, `ISelect.isItemEnabled`, `ISelect.itemCount`, `ISelect.selectedTitle` (shim/projection semantics) |
| ISlider | `ISlider.range() -> SliderRange`; `ISlider.setRange(double minimum, double maximum, double step) -> void`; `ISlider.setRangeValue(SliderRange range, double value) -> void`; `ISlider.onPreview`, `ISlider.onCommit`, `ISlider.onCancel`: `(ISliderControlEventHandler handler, CallbackScope owner) -> ICallbackRegistration` | `ISlider.setValue` (unchanged refresh, model cancellation and snapping); `ISlider.setEnabled` (eligibility-loss cancellation) |
| IScrollView | `IScrollView.offset() -> ScrollOffset`; `IScrollView.visibleRect() -> ScrollRect`; `IScrollView.scrollToOffset(ScrollOffset offset) -> void`; `IScrollView.onOffsetChanged(IScrollControlEventHandler handler, CallbackScope owner) -> ICallbackRegistration` | `IScrollView.scrollOffset`, `IScrollView.scrollTo`, `IScrollView.setContentSize` (two-axis compatibility/clamp) |
| Typed receivers | `ITextControlEventHandler.invoke(TextControlEvent event) -> void`; `ISelectionControlEventHandler.invoke(SelectionControlEvent event) -> void`; `ISliderControlEventHandler.invoke(SliderControlEvent event) -> void`; `IScrollControlEventHandler.invoke(ScrollControlEvent event) -> void` | None |

Inherited eligibility methods on IView and IWindow belong to CX-UIA-20.
`ITextField.setEnabled` and `ISelect.setEnabled` also acquire the shared
eligibility-loss behavior defined there; disabling a select's active option
through `setItemEnabled` follows model invalidation above. Factories
`IApplication.createSlider` and `GUI.createSlider` need a reviewed compatibility
decision for their existing interval argument when new range mutation lands;
they are **not** silently respelled or removed by this draft. The ledger
inventory for those factory changes must be part of the approved interface
diff if the review changes them.

## Five-platform review map

These are implementation candidates and required checks, not observed native
results. Linux means the current SDL provider for UI2/UI3; a GTK4 route follows
D23 and CX-UIA-29, not this draft.

| Family | Candidate native sources and provider work | Required review evidence |
| --- | --- | --- |
| macOS | NSTextField editor/delegate changes and end-editing; NSPopUpButton target/action; NSSlider tracking; NSScrollView clip-view bounds. Suppress setter notifications without disturbing the field editor. | UI1 AppKit fixture, IME/selection/undo preservation, popup refresh cancellation, terminal delivery after native callback. |
| Linux | SDL text-input/editing and keyboard/pointer events feeding the existing control owners; LinuxSelect popup model; LinuxSlider capture; LinuxScrollView geometry. | X11 and Wayland logs separately; real composition coverage where available, capture loss, no closed-popup keyboard assumptions, large-list reachability. |
| Windows | EDIT notifications/IME completion, common-control selection notifications, trackbar scroll notifications and HWND viewport state translated to typed events. | Real Win32 shell plus input/IME lifetime checks; keyboard and accessibility increments retain intent instead of decoding a rounded trackbar value. |
| iOS / iPadOS | UITextField editing actions/delegate, a keyed picker/menu selection owner, UISlider tracking and UIScrollView delegate; scene-owned delivery. | iPhone and iPad destinations in the same ios family; software and hardware keyboard, pointer/capture interruption on iPad, focus/scene transitions and one terminal event. |
| Android | EditText TextWatcher/editor actions with composition distinguished, keyed selection/list adapter, SeekBar tracking and actual scroll callbacks. | Main Looper delivery, programmatic-listener suppression, InputConnection composition, Activity recreation generation checks, hardware/software keyboard. |

New-platform feasibility depends on the target/host and checked native interop
work assigned in [the UI lanes](../../workstreams/codex-ui-lanes.md). The
portable API never exposes NSTextField delegate selectors, Win32 notification
codes or JNI handles. A simulator/hosted run is stand-in evidence; no physical
IME, assistive-technology or real-device result is claimed by this document.

## Fixture outlines and evidence requirements

Implement these with real shell fixtures, each through reference and selfhost,
plain and sanitized where the host supports it. Record provider, frontend,
source revision, input mechanism, event trace, final state, callback lifetime
counters and sanitization mode. Traces include identity/revision/phase/origin,
not sensitive editor text. Exercise cancellation while queued and from inside
a callback. Expected zero below means an assertion, not a skipped branch.

| Case | Driver outline | Required assertions and operation coverage |
| --- | --- | --- |
| E01 | Type, use real IME preedit/commit, Return, focus departure and Escape; republish unchanged text while selection/composition/undo are active; replace with changed model text; cancel scope before delivery. Repeat each terminal path 100 times. | Exactly one USER commit per accepted dirty edit, zero for setters/cancel; unchanged publication preserves selection, composition and undo. MODEL replacement invalidates the old interaction; no callback after cancellation drains. `ITextField.setText/onDraftChanged/onCommit/onCancel` and typed receiver. |
| E02 | Open duplicate-label keyed options; reorder and relabel while open; disable/remove candidate and selected keys; publish replacement/null selection; cancel popup; exercise index shim separately. | Identity follows key; explicit unavailable selection; active candidate either survives or emits one MODEL cancel; no guessed index or setter-generated USER commit. `ISelect.setOptions/selectedKey/setSelectedKey/optionsState/onChanged/onCommit/onCancel` and legacy projection methods. |
| E03 | Drag with several previews, release; repeat with capture loss/Escape/eligibility loss; delay executor delivery, interleave previews and final commits across controls; then cancel a registration. | One accepted commit, or one cancellation with no stale commit; final snapshot survives preview replacement; ordering holds across channels; queued data released after cancellation. `ISlider.onPreview/onCommit/onCancel`, `setValue`, typed receiver. |
| E33 | 0, 1, 100 and 10,000 options; 320/480/1024 logical-unit widths; long/duplicate labels; all-disabled; 100/200% text; each viewport edge. Open without pointer, reach final enabled item by scrolling/search, refresh while open and cancel back to valid focus. | Unselected, loading, empty and error are distinct. Accepted selection commits once; setters commit zero times. Popup content remains reachable. UI2 validates the model/event subset; UI3/UI4/UI7 still own complete keyboard/search/layout proof. E33 is not closed by model-only tests. |
| E34 | Update range/step/value while focused and during drag; equal/reversed/nonfinite ranges; 999/1,000/1,001 intervals; negative/fractional values; exact integers at 2^53-1, 2^53 and 2^53+1. Apply small/large keyboard/accessibility adjustments and no-op refresh. | Atomic acceptance or rejection, retained owner/focus, zero stale commit after cancellation. Exact integer assertions for relative/no-op paths; documented pointer bound. `ISlider.range/setRange/setRangeValue/setValue` and event methods. Full accessibility/native-input portions remain UI4/UI8 dependencies. |

Add a supporting two-axis scroll fixture: independent horizontal/vertical moves,
negative/oversized requests, small/empty content, resize clamping and a nested
scroll view. Assert the actual offset/visible rect and USER/MODEL/SYSTEM origin,
zero observation for no-op scroll, and cancellation cleanup. This exercises
the proposed scroll ids without inventing a new frozen E id or claiming E09.

## Review decisions and landing handoff

`CL-UIA-13` must reconcile the payload names and queue/lifecycle rules with
CX-UIA-19/20 and decide, using UI1 results:

1. Whether the native edit-completion/focus policy can preserve composition on
   macOS and Linux; explicit adaptations replace undocumented differences.
2. Whether MODEL cancellation as non-action observation is sufficient for
   asynchronous model replacement and the BTRSmith migration.
3. Which popup providers can retain live interaction through keyed refresh;
   cancellation is observable and is not silently labelled preservation.
4. How terminal-event capacity, relative adjustments, model revisions and
   cross-channel order fit the executor's bounded queue.
5. The slider factory/interval compatibility rule and the exact-value adapter's
   pointer bound, without relaxing keyboard/accessibility integer precision.

No compiler request is currently identified: the proposal uses existing
managed classes, interfaces, owned strings, `long long`, callbacks and the UI
vocabulary. If feasibility needs new interop or compiler behavior, file a
`REQUEST` for the owning Claude packet instead of adding a private provider ABI.

The approved changes go through CX-UIA-21, macOS CX-UIA-22 and Linux CX-UIA-23,
then CL-UIA-14's atomic landing. Keep Windows/iOS/Android approval provisional
until CL-UIA-22, and preserve the selector shim until BTRSmith re-pins. This
draft neither freezes operation ids nor records any acceptance case as passed.
