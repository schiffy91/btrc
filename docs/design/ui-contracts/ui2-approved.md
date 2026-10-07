# UI2 approved interface record

**Packet:** `CL-UIA-13` (`ui-2-contract-review`), Stage 32.
**Decided:** 2026-10-06, on main `f6c2f2ae`. The tree is clean, and `f6c2f2ae` adds only docs on top of `19f75abf`.
**Basis:** the standing design rule for Codex contract drafts (CLAUDE.md, "Standing approvals"; D27 as amended by D28). A Codex-drafted UI contract is approved once Claude's two feasibility reviewers and one parity reviewer leave no blocking finding open. As Stage 32 requires, a reconciler also aligned the three drafts.
**Verification:** no blocking finding was confirmed. Every finding a reviewer raised as blocking is closed by a decision in this record (next section), and no Codex draft needs revising.
**Review files:**
- [Feasibility, macOS AppKit and Linux SDL](reviews/ui2/feasibility-desktop.md): fix-first, with B1–B4 raised as blocking.
- [Feasibility, Windows, iOS/iPadOS and Android](reviews/ui2/feasibility-other.md): fix-first, with finding 1 raised as blocking.
- [Reconciler](reviews/ui2/reconciler.md): approve, no blocking findings.
- [Parity](reviews/ui2/parity.md): fix-first, with three findings raised as blocking.

**Drafts reconciled:**
- [ui2-control-events.md](ui2-control-events.md) (CX-UIA-18), cited below as "CE".
- [ui2-executor.md](ui2-executor.md) (CX-UIA-19), cited as "EX".
- [ui2-lifecycle.md](ui2-lifecycle.md) (CX-UIA-20), cited as "LC".

They were checked against the [UI1 checkpoint](ui1-feasibility.md) and the real UI1 shells: AppKit, and SDL on X11 with Wayland carried. The Win32, UIKit and Android shell notes are in [`../native-ui-shells/`](../native-ui-shells/).

**Status:**
- **Frozen for CX-UIA-21** to write. Where a draft and this record differ, this record governs.
- **Provisional on every platform:** the host link (`attachHost` and its types).
- **Provisional until `CL-UIA-22`:** the Windows, iOS/iPadOS and Android mappings.
- **Later changes:** any later change to this surface is a versioned contract change, landed atomically with macOS and Linux (D27).
- **What this record does not do:** it edits nothing under `src/`, records no E-case as passed, and leaves the frozen 2026-09-21 release (162 operations, 47 cases) unchanged.

## Blocking findings and how this record closes them

| Finding raised as blocking | Raised by | Closed by |
| --- | --- | --- |
| `IApplication.attachHost` has no adapter type, outcome, reference meaning or fixture (UI1 condition 1) | desktop B1 | [Host link](#iapplication-and-the-executor-types): `IApplicationHost`, `IApplicationHostAttachment` and `ApplicationHostAttachOutcome` are frozen provisionally, with a test-host fixture on macOS and Linux |
| AppKit nested tracking and modal loops contradict "after native dispatch", the while-open fixtures and the E40 budgets | desktop B2 | [macOS and Linux provider decisions](#macos-and-linux-provider-decisions): common-mode wake and timers, revised delivery wording, a reentrancy rule, legacy nested-loop classification, the quit choice and tracking trials |
| The executor's "refuse to begin the interaction" cannot be implemented on AppKit | desktop B3 | [Known conflict 1](#known-conflict-1-terminal-capacity): reservation per registration and channel at subscribe time, plus a begin-hook draw for additional interactions only |
| SDL composition and undo are scheduled in UI3, but E01 is required on Linux at UI2 | desktop B4 | [UI1 condition 3](#ui1-conditions): CX-UIA-23 plumbs `SDL_EVENT_TEXT_EDITING`; the Linux undo-preservation row of E01 is deferred to CX-UIA-27 and never counted at UI2 |
| `attachHost` is named but not freezable; the GUI.run/entry decision is unmade; host-created windows have no route | feasibility-other 1 | Host link rules (a)–(h) adopted. The hosted-application receiver is named and assigned (see [Carried gaps](#carried-gaps-and-owners)) |
| A typed generic publisher/receiver with "maximum payload bytes" cannot be written in either compiler | parity 1 | A fixed, non-generic, identity-only record (`ApplicationPublication`, the record the parity reviewer probed as `UIWorkRecord`). "Maximum payload bytes" is dropped |
| `attachHost`, `createPublisher` and `schedule` cannot be reached from portable code: the application slot is package-private | parity 2 | Facade mirrors: `GUI.attachHost`, `GUI.createPublisher` and `GUI.schedule` |
| `BackgroundJobExecutor.subscribeCompletionReady` cannot be a UI catalog id | parity 3 | It becomes a [non-catalog BackgroundJobs contract](#non-catalog-change-backgroundjobexecutorsubscribecompletionready) |

## Approved interface diff

### Conventions for every entry

- **Origin column.**
  - **CE, EX, LC:** the draft and line that proposed the entry.
  - **R:** a record-supplied entry. A review names it, a draft's described behaviour needs it, and the draft left its shape to this review.
  - **RN:** renamed from the draft's spelling.
- **Status column.**
  - **New:** a new catalog operation id.
  - **Changed:** an existing id keeps its identity and its slots. Its signature is unchanged unless the row says otherwise.
- **Subscriptions.**
  - Shape: `ICallbackRegistration on<Event>(I<Owner><Event>Handler handler, CallbackScope owner)`.
  - One live receiver per control and channel. A second registration throws until the old one has completed cancellation (the existing `IButton.onAction` policy).
  - There is no initial delivery. Cancellation follows CE "Proposed values and callback ownership".
  - Exhausting the terminal pool at subscribe time throws, like `post`'s capacity rejection. A subscription keeps its `ICallbackRegistration` return, so it cannot carry a typed outcome.
- **Receivers.** Each receiver interface declares one method with its own name, as `IWindowKeyHandler.key` and `IViewPointerHandler.pointer` already do.
  - Neither compiler has overloading, and lambdas cannot implement an interface. With distinct names, one component class can implement several channels.
  - This follows the parity review. The reconciler's uniform `invoke` is not adopted.
- **Values.**
  - Values are owning classes with public fields.
  - An outcome is a class with a `kind` enum field (named `<Outcome>Kind`, as in BackgroundJobs) plus owning fields.
  - Enumerators are prefixed, so bare names never collide.
  - An optional reason is encoded with a `NONE` enumerator, never as `Enum?`.
  - No rich enum carries a managed payload: see CL-REQ-UI2-B/C.
- **Identifiers.**
  - Generation, interaction, sequence, registration epoch and every revision are `long long`.
  - They are monotonic and never wrap; exhaustion fails explicitly.
- **Thread.** Every operation runs on the application's UI executor thread unless its row says "any thread". The definition is under [Shared rules](#shared-rules).
- **Placement.**
  - Control-event values go in the new `GUI/ControlEvents.btrc`.
  - Executor and lifecycle values go in their owner's `I*.btrc` file, following the `ButtonTypography` and `StackAlignment` precedent.
  - Every handler interface goes in its owner's `I*.btrc` file, where the catalog drift gate finds it.
  - `ApplicationActivity` is declared in `IWindow.btrc`, and `WindowExposure` and its reason in `IView.btrc`. This keeps the import graph `IApplication → IWindow → IView` acyclic.
- **Parity-confirmed shapes.** These compile and run identically on the reference compiler at `f6c2f2ae` and on a btrcc (built from `3ca9baa6` = `19f75abf` plus the stage17/c2-l2 lane, with no stdlib or runtime diff):
  - the value classes, nullable `string?` keys, enums and `Vector`-owned option models;
  - `CallbackScope` subscriptions;
  - `UIRangeAdjustment`/`UISemanticRange` reuse, exact at 2^53+1;
  - a mutex-guarded worker publisher called through an interface from a spawned thread (parity review);
  - a typed `string?` select probe (reconciler);
  - the record-writer probe `the review workspace (not retained) record/ApprovedSurfaceProbe.btrc`: one class implementing two receivers with distinct method names, an `unsigned long long` interface parameter, an interface extending `ICallbackRegistration`, a class with `Vector<interface>` fields, and `long long` values above 2^53. It ran through both compilers, `cc -std=c11 -fsanitize=address,undefined`, and printed PASS.

### Value types

**`GUI/ControlEvents.btrc`** (new module). It imports `Library.UI.Element` and `Library.Vector`; `Library.UI` never imports `Library.GUI`.

| Type | Fields or enumerators | Origin |
| --- | --- | --- |
| `enum ControlOrigin` | `CONTROL_ORIGIN_USER`, `CONTROL_ORIGIN_MODEL`, `CONTROL_ORIGIN_SYSTEM` | CE:45; reconciler glossary |
| `enum ControlPhase` | `CONTROL_PHASE_DRAFT`, `CONTROL_PHASE_CHANGE`, `CONTROL_PHASE_PREVIEW`, `CONTROL_PHASE_COMMIT`, `CONTROL_PHASE_CANCEL` | R: the CE:46–51 phases, under the parity rule for enumerators. This is the reconciler's probe spelling |
| `enum ControlCancelReason` | `CONTROL_CANCEL_NONE`, `CONTROL_CANCEL_ESCAPE` (Escape or Back), `CONTROL_CANCEL_CAPTURE_LOSS`, `CONTROL_CANCEL_ELIGIBILITY_LOSS`, `CONTROL_CANCEL_MODEL_REPLACEMENT`, `CONTROL_CANCEL_SOURCE_CLOSING`, `CONTROL_CANCEL_PLATFORM_INTERRUPTION` | CE:54; `NONE` from parity |
| `class ControlEventContext` | `long long generation; long long interaction; long long sequence; long long modelRevision; ControlOrigin origin;` | CE:45 |
| `class TextControlEvent` | `ControlEventContext context; ControlPhase phase; string text; bool composing; ControlCancelReason cancelReason;` (phase is DRAFT, COMMIT or CANCEL) | CE:46 |
| `class SelectOption` | `string key; string title; bool enabled;` | CE:47 |
| `enum SelectAvailability` | `SELECT_AVAILABILITY_READY`, `SELECT_AVAILABILITY_LOADING`, `SELECT_AVAILABILITY_EMPTY`, `SELECT_AVAILABILITY_ERROR` | CE:48 |
| `class SelectModel` | `Vector<SelectOption> options; string? selectedKey; SelectAvailability availability; string statusText;` | CE:48 |
| `class SelectionControlEvent` | `ControlEventContext context; ControlPhase phase; string? previousKey; string? candidateKey; string? acceptedKey; ControlCancelReason cancelReason;` (phase is CHANGE, COMMIT or CANCEL) | CE:49 |
| `class SliderRange` | `double minimum; double maximum; double step;` | CE:50 |
| `enum SliderInputKind` | `SLIDER_INPUT_ABSOLUTE_POINTER`, `SLIDER_INPUT_RELATIVE_ADJUSTMENT`, `SLIDER_INPUT_ABSOLUTE_ASSISTIVE` | CE:51; the third class is from feasibility-other 7 |
| `class SliderControlEvent` | `ControlEventContext context; ControlPhase phase; double value; long long rangeRevision; SliderInputKind input; UIRangeAdjustment adjustment; int count; ControlCancelReason cancelReason;`. Phase is PREVIEW, COMMIT or CANCEL. `adjustment` is `UI_RANGE_ADJUST_NONE` unless the input is relative. `count` is at least 1 for a relative adjustment and 0 otherwise | CE:51; `count` from desktop B3 |
| `class ScrollOffset` | `double x; double y;` | CE:52 |
| `class ScrollRect` | `double x; double y; double width; double height;` | CE:52 |
| `class ScrollControlEvent` | `ControlEventContext context; ScrollOffset offset; ScrollRect visibleRect;` | CE:53 |

**`IApplication.btrc` values**

| Type | Fields or enumerators | Origin |
| --- | --- | --- |
| `enum WorkSuspensionPolicy` | `WORK_SUSPENSION_CANCEL`, `WORK_SUSPENSION_DEFER`, `WORK_SUSPENSION_REPLACE` | EX:205–209 |
| `enum PublishOutcome` | `PUBLISH_ACCEPTED`, `PUBLISH_REPLACED`, `PUBLISH_FULL`, `PUBLISH_CLOSED`, `PUBLISH_STALE`, `PUBLISH_CANCELLED`, `PUBLISH_INVALID`, `PUBLISH_RESOURCE_FAILED`, `PUBLISH_WAKE_FAILED` | EX:104–110 |
| `enum PublishCancelOutcome` | `PUBLISH_CANCEL_REQUESTED`, `PUBLISH_CANCEL_ALREADY_TERMINAL`, `PUBLISH_CANCEL_STALE`, `PUBLISH_CANCEL_CLOSED` | EX:49 |
| `class ApplicationPublication` | `long long generation; long long sequence; long long replacementKey; long long payload;` | EX:50; parity form (a) |
| `class ApplicationPublisherOutcome` | `ApplicationPublisherOutcomeKind kind; IApplicationPublisher? publisher; ICallbackRegistration? registration;`. Kinds: `APPLICATION_PUBLISHER_CREATED`, `APPLICATION_PUBLISHER_BUDGET_EXHAUSTED`, `APPLICATION_PUBLISHER_CLOSED`, `APPLICATION_PUBLISHER_RESOURCE_FAILED`. Both references are non-null only for CREATED | EX:47; reconciler |
| `class ScheduleOutcome` | `ScheduleOutcomeKind kind; ICallbackRegistration? registration;`. Kinds: `SCHEDULE_ACCEPTED`, `SCHEDULE_REPLACED`, `SCHEDULE_FULL`, `SCHEDULE_CLOSED`, `SCHEDULE_CANCELLED` (the cancel policy while suspended) | EX:53, 207 |
| `class ApplicationHostAttachOutcome` | `ApplicationHostAttachOutcomeKind kind; IApplicationHostAttachment? attachment; string error;`. Kinds: `APPLICATION_HOST_ATTACHED`, `APPLICATION_HOST_ALREADY_ATTACHED`, `APPLICATION_HOST_APPLICATION_RUNNING`, `APPLICATION_HOST_APPLICATION_CLOSED`, `APPLICATION_HOST_ATTACH_FAILED`. **Provisional** | EX:54, 60–65; reconciler |

**`IWindow.btrc` values**

| Type | Fields or enumerators | Origin |
| --- | --- | --- |
| `enum ApplicationActivity` | `APPLICATION_ACTIVITY_ACTIVE`, `APPLICATION_ACTIVITY_INACTIVE`, `APPLICATION_ACTIVITY_BACKGROUND`, `APPLICATION_ACTIVITY_SUSPENDED`, `APPLICATION_ACTIVITY_UNKNOWN` | Reconciler; `UNKNOWN` from desktop N7 |
| `enum WindowCloseReason` | `WINDOW_CLOSE_NATIVE_REQUEST`, `WINDOW_CLOSE_APPLICATION_QUIT`, `WINDOW_CLOSE_PROGRAM_REQUEST` (Back and tab navigation reasons are UI3) | LC:58–60; reconciler |
| `enum WindowCloseDecision` | `WINDOW_CLOSE_DECISION_SAVE`, `WINDOW_CLOSE_DECISION_DISCARD`, `WINDOW_CLOSE_DECISION_CANCEL` | LC:74–76 |
| `enum WindowCloseState` | `WINDOW_CLOSE_OPEN`, `WINDOW_CLOSE_AWAITING_DECISION`, `WINDOW_CLOSE_SAVING`, `WINDOW_CLOSE_AUTHORIZED`, `WINDOW_CLOSE_CLOSING`, `WINDOW_CLOSE_CANCELLED`, `WINDOW_CLOSE_OWNER_LOST` | Reconciler |
| `class WindowCloseOutcome` | `WindowCloseOutcomeKind kind; WindowCloseState state; long long attempt;` (`attempt` is 0 when there is none). Kinds: `WINDOW_CLOSE_OUTCOME_APPLIED`, `WINDOW_CLOSE_OUTCOME_STALE_REVISION`, `WINDOW_CLOSE_OUTCOME_STALE_ATTEMPT`, `WINDOW_CLOSE_OUTCOME_NOT_PENDING` | R, from LC:71–82 |
| `class WindowCloseRequestOutcome` | `WindowCloseRequestOutcomeKind kind; IWindowCloseTransaction? transaction;`. Kinds: `WINDOW_CLOSE_REQUEST_PENDING`, `WINDOW_CLOSE_REQUEST_ALREADY_PENDING`, `WINDOW_CLOSE_REQUEST_AUTHORIZED_NO_HANDLER`, `WINDOW_CLOSE_REQUEST_CLOSING`, `WINDOW_CLOSE_REQUEST_CLOSED`. `transaction` is non-null for PENDING and ALREADY_PENDING | Reconciler |
| `class WindowState` | `double width; double height; double backingScale; bool requestedVisible; bool nativeVisible; bool minimized; bool windowActive; ApplicationActivity applicationActivity; WindowExposure exposure; WindowExposureReason notExposedReason; bool presentable; long long stateRevision;`. Width and height are logical content points | LC:187–194; reconciler; desktop N7 renames `drawableReady` to `presentable` |

**`IView.btrc` values**

| Type | Fields or enumerators | Origin |
| --- | --- | --- |
| `enum WindowExposure` | `WINDOW_EXPOSURE_EXPOSED`, `WINDOW_EXPOSURE_NOT_EXPOSED`, `WINDOW_EXPOSURE_UNKNOWN` | LC:189; reconciler |
| `enum WindowExposureReason` | `WINDOW_EXPOSURE_REASON_NONE`, `WINDOW_EXPOSURE_REASON_HIDDEN`, `WINDOW_EXPOSURE_REASON_MINIMIZED`, `WINDOW_EXPOSURE_REASON_OCCLUDED` | R, from LC:190–191 ("keep reasons for `notExposed`") |
| `class ViewInteractionState` | `bool localVisible; bool localEnabled; bool inheritedEligible; bool effectiveEligible; bool layoutParticipating; WindowExposure exposure; bool faulted; long long stateRevision;` | LC:153–162; reconciler adds `faulted` |

**`IContainer.btrc` values.** IContainer.btrc gains `import Library.Vector;`.

| Type | Fields or enumerators | Origin |
| --- | --- | --- |
| `enum ContainerEditKind` | `CONTAINER_EDIT_INSERT`, `CONTAINER_EDIT_MOVE`, `CONTAINER_EDIT_DETACH` | LC:120 |
| `class ContainerEdit` | `ContainerEditKind kind; IView child; int index;`. Insert takes `0..childCount`; move takes the destination `0..childCount-1`; detach ignores the index (-1). This is an owning class, never a rich enum | LC:113–121; parity |
| `class ContainerBatchResult` | `ContainerBatchResultKind kind; long long treeRevision; int failedStep; string error; Vector<IView> detached; Vector<IView> retained;` (`failedStep` is -1 when there is none). Kinds: `CONTAINER_BATCH_COMMITTED`, `CONTAINER_BATCH_REJECTED`, `CONTAINER_BATCH_ROLLED_BACK`, `CONTAINER_BATCH_FAILED_CONSISTENT`, `CONTAINER_BATCH_FAILED_QUARANTINED` | LC:134–149; reconciler |

### ITextField (`extends IView`)

| Operation id | Signature | Origin | E-cases | Status |
| --- | --- | --- | --- | --- |
| `ITextField.onDraftChanged` | `ICallbackRegistration onDraftChanged(ITextControlEventHandler handler, CallbackScope owner);` | CE:286 | E01, E39 | New |
| `ITextField.onCommit` | `ICallbackRegistration onCommit(ITextControlEventHandler handler, CallbackScope owner);` | CE:286 | E01, E39 | New |
| `ITextField.onCancel` | `ICallbackRegistration onCancel(ITextControlEventHandler handler, CallbackScope owner);` | CE:286 | E01, E39 | New |
| `ITextControlEventHandler.textEvent` | `interface ITextControlEventHandler { void textEvent(TextControlEvent event); }` | CE:290 (RN from `invoke`) | E01 | New |
| `ITextField.setText` | `void setText(string text);` | CE:143–147 | E01 | Changed. "Unchanged" means equal to the accepted baseline, and is then a true no-op. A changed value ends any open interaction with one MODEL cancel, sets a new baseline and increments `modelRevision` |
| `ITextField.text` | `string text();` | R (CE:28–30) | E01 | Changed. Returns the live draft; never validates, commits or disturbs composition (macOS stops calling `validateEditing` here) |
| `ITextField.setEnabled` | `void setEnabled(bool enabled);` | CE:292–294 | E39 | Changed. Eligibility loss follows [known conflict 2](#known-conflict-2-what-text-eligibility-loss-cancels) |

### ISelect (`extends IView`)

| Operation id | Signature | Origin | E-cases | Status |
| --- | --- | --- | --- | --- |
| `ISelect.setOptions` | `void setOptions(SelectModel model);` | CE:287 | E02, E33 | New |
| `ISelect.optionsState` | `SelectModel optionsState();` | CE:287 | E02, E33 | New |
| `ISelect.selectedKey` | `string? selectedKey();` | CE:287 | E02, E33 | New |
| `ISelect.setSelectedKey` | `void setSelectedKey(string? key);` | CE:287 | E02, E33 | New |
| `ISelect.onChanged` | `ICallbackRegistration onChanged(ISelectionControlEventHandler handler, CallbackScope owner);` | CE:287 | E02, E33, E39 | New |
| `ISelect.onCommit` | `ICallbackRegistration onCommit(ISelectionControlEventHandler handler, CallbackScope owner);` | CE:287 | E02, E33, E39 | New |
| `ISelect.onCancel` | `ICallbackRegistration onCancel(ISelectionControlEventHandler handler, CallbackScope owner);` | CE:287 | E02, E33, E39 | New |
| `ISelectionControlEventHandler.selectionEvent` | `interface ISelectionControlEventHandler { void selectionEvent(SelectionControlEvent event); }` | CE:290 (RN from `invoke`) | E02, E33 | New |
| `ISelect.setItems`, `.itemCount`, `.selectedIndex`, `.setSelectedIndex`, `.setItemEnabled`, `.isItemEnabled`, `.selectedTitle` | Unchanged signatures | CE:177–185 | E02 | Changed. These form the D24 index shim, projecting the current keyed snapshot (CE:177–185) |
| `ISelect.setEnabled` | `void setEnabled(bool enabled);` | CE:292–294 | E39 | Changed: eligibility loss |

### ISlider (`extends IView`)

| Operation id | Signature | Origin | E-cases | Status |
| --- | --- | --- | --- | --- |
| `ISlider.range` | `SliderRange range();` | CE:288 | E34 | New |
| `ISlider.setRange` | `void setRange(double minimum, double maximum, double step);` | CE:288 | E34 | New |
| `ISlider.setRangeValue` | `void setRangeValue(SliderRange range, double value);` | CE:288 | E34 | New |
| `ISlider.onPreview` | `ICallbackRegistration onPreview(ISliderControlEventHandler handler, CallbackScope owner);` | CE:288 | E03, E34, E39 | New |
| `ISlider.onCommit` | `ICallbackRegistration onCommit(ISliderControlEventHandler handler, CallbackScope owner);` | CE:288 | E03, E34, E39 | New |
| `ISlider.onCancel` | `ICallbackRegistration onCancel(ISliderControlEventHandler handler, CallbackScope owner);` | CE:288 | E03, E34, E39 | New |
| `ISliderControlEventHandler.sliderEvent` | `interface ISliderControlEventHandler { void sliderEvent(SliderControlEvent event); }` | CE:290 (RN from `invoke`) | E03, E34 | New |
| `ISlider.value` | `double value();` | R (feasibility-other 7) | E03, E34 | Changed. Returns the double the provider holds as authority, never a read-back of the native control |
| `ISlider.setValue` | `void setValue(double value);` | CE:288 | E03, E34 | Changed: snapping, a MODEL cancel on change, an unchanged value is a no-op |
| `ISlider.setEnabled` | `void setEnabled(bool enabled);` | CE:288 | E39 | Changed: eligibility loss |

### IScrollView (`extends IContainer`)

| Operation id | Signature | Origin | E-cases | Status |
| --- | --- | --- | --- | --- |
| `IScrollView.offset` | `ScrollOffset offset();` | CE:289 | Scroll fixture (E09 not claimed) | New |
| `IScrollView.visibleRect` | `ScrollRect visibleRect();` | CE:289 | Scroll fixture | New |
| `IScrollView.scrollToOffset` | `void scrollToOffset(ScrollOffset offset);` | CE:289 | Scroll fixture | New |
| `IScrollView.onOffsetChanged` | `ICallbackRegistration onOffsetChanged(IScrollControlEventHandler handler, CallbackScope owner);` | CE:289 | Scroll fixture | New |
| `IScrollControlEventHandler.scrollEvent` | `interface IScrollControlEventHandler { void scrollEvent(ScrollControlEvent event); }` | CE:290 (RN from `invoke`) | Scroll fixture | New |
| `IScrollView.scrollOffset`, `.scrollTo`, `.setContentSize` | Unchanged signatures | CE:250–251 | Scroll fixture | Changed. These are the vertical compatibility surface: `scrollTo` preserves x, and both axes clamp |

### IApplication and the executor types

| Operation id | Signature | Origin | E-cases | Status |
| --- | --- | --- | --- | --- |
| `IApplication.createPublisher` | `ApplicationPublisherOutcome createPublisher(int capacity, IApplicationPublicationHandler handler, CallbackScope owner);` | EX:47 | E04, E24 | New |
| `IApplication.schedule` | `ScheduleOutcome schedule(IApplicationWork work, double delaySeconds, WorkSuspensionPolicy policy, long long replacementKey);` | EX:53 | E24, E30 | New |
| `IApplication.attachHost` | `ApplicationHostAttachOutcome attachHost(IApplicationHost host, CallbackScope owner);` | EX:54 | E30, E40 (host-attached journey) | New, **provisional** |
| `IApplicationPublisher.tryPublish` | `PublishOutcome tryPublish(long long generation, long long sequence, WorkSuspensionPolicy suspension, long long replacementKey, long long payload);` (any thread; never throws; never runs the receiver inline) | EX:48 (RN from `IUIWorkPublisher`) | E04, E24, E40 | New |
| `IApplicationPublisher.requestCancel` | `PublishCancelOutcome requestCancel(long long generation, long long sequence);` (any thread; no callback or managed release on the producer) | EX:49 (RN) | E04 | New |
| `IApplicationPublicationHandler.deliver` | `interface IApplicationPublicationHandler { void deliver(ApplicationPublication publication); }` | EX:50 (RN from `IUIWorkReceiver.deliver`; the method keeps the draft's name) | E04, E24 | New |
| `IApplicationHost.requestTurn` | `bool requestTurn();` (any thread; coalesced; never runs work inline) | R (EX:226–233; reconciler) | E04, E30 | New, **provisional** |
| `IApplicationHost.scheduleTurn` | `void scheduleTurn(unsigned long long monotonicDeadlineNs);` | R (desktop B1) | E24, E30 | New, **provisional** |
| `IApplicationHostAttachment.serviceTurn` | `void serviceTurn();` | R (reconciler; desktop B1) | E40 | New, **provisional** |
| `IApplicationHostAttachment.transition` | `void transition(ApplicationActivity activity);` | R (reconciler) | E30, E42 | New, **provisional** |
| `IApplication.post` | `void post(IApplicationWork work);` | EX:51 | E24, E40 | Changed. Shares accounting and fairness, keeps its exceptions, defers when suspended, and stays UI-thread only |
| `IApplication.postAfter` | `ICallbackRegistration postAfter(double delaySeconds, IApplicationWork work);` | EX:52 | E30, E40 | Changed. Monotonic; a one-shot timer that defers until resume; macOS registers it in common modes |
| `IApplication.isRunning` | `bool isRunning();` | EX:55 | — | Changed: true while attached and servicing, including an OS-owned loop |
| `IApplication.run` | `void run();` | EX:60–61 | E40 | Changed: throws on a host-attached application; a lossless fair pump |
| `IApplication.requestQuit` | `void requestQuit();` | EX:56; LC:97–103 | E31, E46 | Changed: stays irreversible; native quit is coordinated first |
| `IApplication.close`, `IApplication.pollClose` | Unchanged | EX:57 | E31 | Changed: seal, no worker join, no nested pump |
| `IApplication.createSlider` | `ISlider createSlider(double minimum, double maximum, int intervals);` | CE:295–300 | E34 | Changed: validity widened (CE decision 5) |

The two host-link interfaces are declared as follows (both **provisional**):

```btrc
interface IApplicationHost {
	bool requestTurn();
	void scheduleTurn(unsigned long long monotonicDeadlineNs);
}

interface IApplicationHostAttachment extends ICallbackRegistration {
	void serviceTurn();
	void transition(ApplicationActivity activity);
}
```

**Host link rules (provisional).** These settle UI1 condition 1, desktop B1 and feasibility-other 1.

**Who implements and calls what**

- **`IApplicationHost`** is implemented by a platform shell's host entry, in its provider directory, or by a test host under `src/tests/native/gui/ui2/`. Application code never implements it.
  - `requestTurn()` returns true while the attachment is open and false once detach has completed.
  - `scheduleTurn` is called by the provider on the UI executor thread, with the earliest deadline at which it needs a turn, in its declared monotonic clock. Each call replaces the previous deadline, and 0 means no timed turn is pending. A pull host uses it as its wait timeout; a push host arms one native timer.
- **`IApplicationHostAttachment`** is implemented by the provider.
  - **`serviceTurn()`** runs one bounded fair turn (EX:186–199) and returns. It never blocks, never nests a loop and never throws into the host.
  - **`transition`** feeds the suspension policies and `WindowState.applicationActivity`.
  - **`cancel()`** detaches: it seals ingress, drains, and then completes. A work failure the provider records ends the attachment with an orderly quit: its cancellation reports `CALLBACK_CANCELLATION_FAILED`, and the host entry reports the recorded diagnostic. In hosted mode there is no `run()` to rethrow it.

**Attaching, running and quitting**

- **`attachHost`** allows one attachment per application. It fails with an outcome on a running, closed or already-attached application. A failure leaves no registered native source and no retained receiver (EX:60–65). It neither starts nor nests a loop.
- **On macOS,** the attach path never replaces a host-owned `NSApplication` delegate.
- **Desktop `run()`** attaches a provider-internal host (CFRunLoop on macOS, SDL wait on Linux) and runs its pull loop, so one executor state machine serves both forms.
- **`GUI.run` on a host-owned provider** (iOS, Android) throws the typed unsupported error.
- **`requestQuit` under a host** closes the owned windows and completes the detach. It never terminates the process, and may request scene or Activity teardown where the platform allows it.

**Windows and program entry**

- **`createWindow`, where the host owns top-level creation,** throws the typed unsupported error for top-level windows. Host-created windows arrive with a fresh generation through the hosted-application receiver, which is deferred (see [Carried gaps](#carried-gaps-and-owners)).
- **Program entry:** `main()` calls the facade on every platform. On iOS, `UIApplicationMain` never returns. On Android, the Java shell calls the program entry through `RegisterNatives`.

**Fixture**

A host-attached shell journey on macOS and Linux, driven by a test host, injects `transition(APPLICATION_ACTIVITY_SUSPENDED)` and a resume. It proves E30's cancel, defer and replace policies on the reference providers as **stand-in** evidence: the transitions are injected, not OS suspension.

**Confirmation and corrections**

- `CL-P2-22` and `CL-UIA-22` confirm the host-link surface; any change is versioned.
- The text of CX-UIA-16 step 1 and CX-P2-36 step 1 ("GUI.run maps to the OS-owned loop") is corrected to "`GUI.attachHost` from the host entry".

### GUI facade

Each new entry calls `GUIProvider.requireUIThread()` and forwards to `GUIApplicationSlot.require()`, as `GUI.post` does. They are cataloged as `[[additions]] owner = "GUI"`.

| Operation id | Signature | Origin | E-cases | Status |
| --- | --- | --- | --- | --- |
| `GUI.createPublisher` | `class ApplicationPublisherOutcome createPublisher(int capacity, IApplicationPublicationHandler handler, CallbackScope owner)` | R (parity 2; reconciler) | E04, E24 | New |
| `GUI.schedule` | `class ScheduleOutcome schedule(IApplicationWork work, double delaySeconds, WorkSuspensionPolicy policy, long long replacementKey)` | R | E24, E30 | New |
| `GUI.attachHost` | `class ApplicationHostAttachOutcome attachHost(IApplicationHost host, CallbackScope owner)` | R | E30 | New, **provisional**. Requires `GUI.initialize` first. When the attachment's cancellation completes, the facade closes the application and clears `GUIApplicationSlot`, as `GUI.run` does on return |
| `GUI.post`, `GUI.postAfter`, `GUI.run`, `GUI.requestQuit`, `GUI.close` | Unchanged | EX:51–61 | As their `IApplication` rows | Changed |
| `GUI.createSlider` | Unchanged | CE:295–300 | E34 | Changed: validity widened |
| `GUI.chooseDirectory` | Unchanged | R (desktop N10) | E40, E46 | Changed: classified as a legacy nested-loop API |

### IWindow and the close-transaction types

| Operation id | Signature | Origin | E-cases | Status |
| --- | --- | --- | --- | --- |
| `IWindow.requestClose` | `WindowCloseRequestOutcome requestClose(WindowCloseReason reason);` | LC:41 | E46 | New |
| `IWindow.onCloseRequested` | `ICallbackRegistration onCloseRequested(IWindowCloseRequestHandler handler, CallbackScope owner);` (one live handler) | LC:41 | E46 | New |
| `IWindow.state` | `WindowState state();` | LC:43 | E42 | New |
| `IWindow.onStateChanged` | `ICallbackRegistration onStateChanged(IWindowStateHandler handler, CallbackScope owner);` | LC:43 | E42 | New |
| `IWindowCloseRequestHandler.closeRequested` | `interface IWindowCloseRequestHandler { void closeRequested(IWindowCloseTransaction transaction); }` | R (LC:50–53; reconciler name; parity method naming) | E46 | New |
| `IWindowCloseTransaction.decide` | `WindowCloseOutcome decide(WindowCloseDecision decision, long long documentRevision);` | R (reconciler) | E46 | New |
| `IWindowCloseTransaction.completeSave` | `WindowCloseOutcome completeSave(long long attempt, long long savedRevision, bool succeeded, string error);` | R (reconciler) | E46 | New |
| `IWindowCloseTransaction.state` | `WindowCloseState state();` | R (reconciler) | E46 | New |
| `IWindowStateHandler.stateChanged` | `interface IWindowStateHandler { void stateChanged(WindowState state); }` | R | E42 | New |
| `IWindow.close`, `IWindow.pollClose` | Unchanged | LC:42 | E31, E46 | Changed: the prompt-free final close |
| `IWindow.hide`, `.show`, `.isVisible` | Unchanged | R (LC:187–203) | E39, E42 | Changed: eligibility and state notification |
| `IWindow.showAlert` | Unchanged | R (desktop N10) | E40, E46 | Changed: classified as a legacy nested-loop API |

### IContainer (`extends IView`)

| Operation id | Signature | Origin | E-cases | Status |
| --- | --- | --- | --- | --- |
| `IContainer.insert` | `void insert(IView child, int index);` | LC:44 | E29 | New |
| `IContainer.move` | `void move(IView child, int destinationIndex);` | LC:44 | E29 | New |
| `IContainer.applyBatch` | `ContainerBatchResult applyBatch(long long expectedTreeRevision, Vector<ContainerEdit> edits);` | LC:44 | E29 | New |
| `IContainer.treeRevision` | `long long treeRevision();` | R (LC:120) | E29 | New |
| `IContainer.attach`, `.detach`, `.childAt`, `.childCount` | Unchanged | LC:45 | E29, E39 | Changed: committed order; detach cancels capture and keeps subscriptions |

### IView

| Operation id | Signature | Origin | E-cases | Status |
| --- | --- | --- | --- | --- |
| `IView.interactionState` | `ViewInteractionState interactionState();` | LC:46 | E39 | New |
| `IView.onInteractionStateChanged` | `ICallbackRegistration onInteractionStateChanged(IViewInteractionStateHandler handler, CallbackScope owner);` | LC:46 | E39 | New |
| `IViewInteractionStateHandler.interactionChanged` | `interface IViewInteractionStateHandler { void interactionChanged(ViewInteractionState state); }` | R | E39 | New |
| `IView.isVisible`, `.setVisible`, `.close`, `.pollClose` | Unchanged | LC:47 | E31, E39 | Changed: the local flag is kept; drains on the UI executor |

### IButton, IImageView and IImageHandle: changed ids only

| Operation id | Origin | E-cases | Change |
| --- | --- | --- | --- |
| `IButton.onAction`, `IButton.setEnabled` | R ([third conflict](#third-conflict-accepted-commit-versus-eligibility-loss)) | E39 | Queued clicks recheck effective eligibility at delivery. An ineligible target's click gets the `ineligible` disposition. The comment changes; the signatures do not |
| `IImageView.setImageHandle`, `IImageView.setImage`, `IImageHandle.close` | LC:48, 252–267 | E35 | Retained presentation; close and publish linearized |

### Non-catalog change: `BackgroundJobExecutor.subscribeCompletionReady`

This is not a UI catalog id; the drift gate rejects it (parity 3). It is specified as a BackgroundJobs contract in `src/stdlib/BackgroundJobs/README.md`, with its own regression test in `src/tests/python/test_background_jobs_runtime.py`, and E04's case rows cite that test as a regression. CX-UIA-21 fixes its signature in that README.

The obligations come from EX:58 and EX:153–160:
- It runs on the owner thread.
- It registers a bounded native wake endpoint.
- The ready bit is level-triggered and persists until the terminal slots are drained.
- A registration made after a slot is already terminal observes the ready state.
- It never hands a `BackgroundJobCompletion` to a worker-side UI callback.

The provider-side wake endpoint remains the GUI publisher path above.

## Operation ids the catalog gains

These 53 ids are added in the next reviewed ui-operation release (CX-UIA-21 step 4). Pending ids go from 17 (170 slots) to 70 (700 slots). The frozen denominators do not change.

```text
ITextField.onDraftChanged
ITextField.onCommit
ITextField.onCancel
ITextControlEventHandler.textEvent
ISelect.setOptions
ISelect.optionsState
ISelect.selectedKey
ISelect.setSelectedKey
ISelect.onChanged
ISelect.onCommit
ISelect.onCancel
ISelectionControlEventHandler.selectionEvent
ISlider.range
ISlider.setRange
ISlider.setRangeValue
ISlider.onPreview
ISlider.onCommit
ISlider.onCancel
ISliderControlEventHandler.sliderEvent
IScrollView.offset
IScrollView.visibleRect
IScrollView.scrollToOffset
IScrollView.onOffsetChanged
IScrollControlEventHandler.scrollEvent
IApplication.createPublisher
IApplication.schedule
IApplication.attachHost
IApplicationPublisher.tryPublish
IApplicationPublisher.requestCancel
IApplicationPublicationHandler.deliver
IApplicationHost.requestTurn
IApplicationHost.scheduleTurn
IApplicationHostAttachment.serviceTurn
IApplicationHostAttachment.transition
GUI.createPublisher
GUI.schedule
GUI.attachHost
IWindow.requestClose
IWindow.onCloseRequested
IWindow.state
IWindow.onStateChanged
IWindowCloseRequestHandler.closeRequested
IWindowCloseTransaction.decide
IWindowCloseTransaction.completeSave
IWindowCloseTransaction.state
IWindowStateHandler.stateChanged
IContainer.insert
IContainer.move
IContainer.applyBatch
IContainer.treeRevision
IView.interactionState
IView.onInteractionStateChanged
IViewInteractionStateHandler.interactionChanged
```

**Amendment file: `docs/design/native-ui-catalog/amendments/cx-uia-21.toml`.** It is added to CX-UIA-21's owned paths and matches the loader's `amendments/(?:cl|cx|mac)-…` pattern.
- `release = "ui0-source-inventory-2026-09-21"`.
- `[current]` becomes:
  - `interface_files = 20` (no new `I*.btrc` file)
  - `interfaces = 37` (25 + 12)
  - `interface_declarations = 202` (152 + 50)
  - `facade_declarations = 29` (26 + 3)
- These counts assume the `I*.btrc` and `GUI.btrc` state at `f6c2f2ae`. If a CX-STDLIB unit changes those files first, CX-UIA-21 recomputes them; `test_surface_counts_explain_the_frozen_release_delta` is authoritative.
- Each `[[additions]]` row has `decision = "CL-UIA-13 (ui2-approved.md)"`. The provisional rows also carry `reason = "Provisional host link until CL-P2-22 and CL-UIA-22"`.

| `source` | `owner` | `parent` | Declarations | `links` |
| --- | --- | --- | --- | --- |
| `ITextField.btrc` | `ITextField` | `IView` | 3 | UI2, E01, E39 |
| `ITextField.btrc` | `ITextControlEventHandler` | — | 1 | UI2, E01 |
| `ISelect.btrc` | `ISelect` | `IView` | 7 | UI2, E02, E33, E39 |
| `ISelect.btrc` | `ISelectionControlEventHandler` | — | 1 | UI2, E02, E33 |
| `ISlider.btrc` | `ISlider` | `IView` | 6 | UI2, E03, E34, E39 |
| `ISlider.btrc` | `ISliderControlEventHandler` | — | 1 | UI2, E03, E34 |
| `IScrollView.btrc` | `IScrollView` | `IContainer` | 4 | UI2 |
| `IScrollView.btrc` | `IScrollControlEventHandler` | — | 1 | UI2 |
| `IApplication.btrc` | `IApplication` | — | 3 | UI2, E04, E24, E30 |
| `IApplication.btrc` | `IApplicationPublisher` | — | 2 | UI2, E04, E24, E40 |
| `IApplication.btrc` | `IApplicationPublicationHandler` | — | 1 | UI2, E04, E24 |
| `IApplication.btrc` | `IApplicationHost` | — | 2 | UI2, E30, E40 |
| `IApplication.btrc` | `IApplicationHostAttachment` | `ICallbackRegistration` | 2 | UI2, E30, E40, E42 |
| `GUI.btrc` | `GUI` | — | 3 | UI2, E04, E24, E30 |
| `IWindow.btrc` | `IWindow` | — | 4 | UI2, E42, E46 |
| `IWindow.btrc` | `IWindowCloseRequestHandler` | — | 1 | UI2, E46 |
| `IWindow.btrc` | `IWindowCloseTransaction` | — | 3 | UI2, E46 |
| `IWindow.btrc` | `IWindowStateHandler` | — | 1 | UI2, E42 |
| `IContainer.btrc` | `IContainer` | `IView` | 4 | UI2, E29 |
| `IView.btrc` | `IView` | — | 2 | UI2, E39 |
| `IView.btrc` | `IViewInteractionStateHandler` | — | 1 | UI2, E39 |

**Operation shard files.**
- New owner files:
  - `operations/{ITextControlEventHandler,ISelectionControlEventHandler,ISliderControlEventHandler,IScrollControlEventHandler,IApplicationPublisher,IApplicationPublicationHandler,IApplicationHost,IApplicationHostAttachment,IWindowCloseRequestHandler,IWindowCloseTransaction,IWindowStateHandler,IViewInteractionStateHandler}.toml`.
- Rows appended to the existing owner files:
  - `operations/{ITextField,ISelect,ISlider,IScrollView,IApplication,GUI,IWindow,IContainer,IView}.toml`.
- The Windows, iOS and Android cells are `implementation = "missing"` with evidence `unavailable` (typed unsupported) until `CL-UIA-22`.

**Changed existing ids.** These 51 ids gain no slots; their semantics and notes are updated in their owner shards:
- `ITextField.setText`, `ITextField.text`, `ITextField.setEnabled`
- `ISelect.setItems`, `ISelect.itemCount`, `ISelect.selectedIndex`, `ISelect.setSelectedIndex`, `ISelect.setItemEnabled`, `ISelect.isItemEnabled`, `ISelect.selectedTitle`, `ISelect.setEnabled`
- `ISlider.value`, `ISlider.setValue`, `ISlider.setEnabled`
- `IScrollView.scrollOffset`, `IScrollView.scrollTo`, `IScrollView.setContentSize`
- `IApplication.createSlider`, `IApplication.post`, `IApplication.postAfter`, `IApplication.isRunning`, `IApplication.run`, `IApplication.requestQuit`, `IApplication.close`, `IApplication.pollClose`
- `GUI.createSlider`, `GUI.post`, `GUI.postAfter`, `GUI.run`, `GUI.requestQuit`, `GUI.close`, `GUI.chooseDirectory`
- `IWindow.close`, `IWindow.pollClose`, `IWindow.hide`, `IWindow.show`, `IWindow.isVisible`, `IWindow.showAlert`
- `IContainer.attach`, `IContainer.detach`, `IContainer.childAt`, `IContainer.childCount`
- `IView.isVisible`, `IView.setVisible`, `IView.close`, `IView.pollClose`
- `IImageView.setImageHandle`, `IImageView.setImage`, `IImageHandle.close`
- `IButton.onAction`, `IButton.setEnabled`

No `[[changes]]` rows are needed, because no signature changes.

**E-case link changes.** These go in the same reviewed amendment.
- **Catalog hunk:** CX-UIA-21 carries it as a fragment hunk (WORKSTREAMS §3.3 step 4), and CL-UIA-14 applies it. It adds `"UI2"` to `links` for:
  - `E01`, `E02`, `E03` and `E04` (`cases/E01-E24.toml`, which today name no milestone);
  - `E42` and `E46` (`cases/E25-E47.toml`; UI1 condition 4).
- **Owner text:** E42's owner text becomes "…; UI1/UI2/UI5/UI9" and E46's becomes "…; UI1/UI2/UI3/UI5/UI7". The same change goes into `native-ui-parity.md:916` and `:1001` in the landing commit.
- **Already linked:** E24, E29, E30, E31, E33, E34, E35, E39 and E40 already link UI2.
- **E04's regressions** also cite the BackgroundJobs `subscribeCompletionReady` test.

**Surface rows.** The 15 `ControlEvents.btrc` symbols need `surface/GUIModules.toml` rows (`disposition = "family"`, links including UI2) before `check --strict --kind surface` passes.
- **If `surface/GUIModules.toml` exists at CX-UIA-21's base,** CX-UIA-21 adds the rows as a claimed hunk.
- **Otherwise,** CX-UIA-05 (that file's writer) includes them.

`GUI/btrc.toml` exports `ControlEvents` through CX-UIA-21's exports fragment.

## Reconciled decisions

### Known conflict 1: terminal capacity

The executor's side is adopted, implemented so that AppKit can honour it. This draws on the reconciler, desktop B3 and feasibility-other 5.

**Reservation**
1. A terminal reservation (COMMIT/CANCEL) is mandatory and is never shared with previews.
   - Each live control-event registration is charged one terminal slot per event channel at subscribe time, from a terminal pool the provider sizes at application creation.
   - The pool size is recorded in evidence; UI2 adds no `initialize` parameter.
   - A control channel has at most one active interaction, so the first interaction never needs a refusal hook.
   - The reservation applies whether `onCommit` or `onCancel` is subscribed. A channel with no live registration discards its event.
2. An additional overlapping interaction on the same control draws a slot at its native begin hook: editing or first-responder start, or touch or tracking start. It never draws per keystroke, and never inside a composition.

**When capacity runs out**
- The provider first yields its native source and stops dequeuing; this is how Linux SDL behaves.
- It refuses an interaction start only at a synchronous native decision point (CE:82), and never retroactively.
- A refused begin leaves native state unchanged and reports through the application error policy.
- A dequeued final input is never dropped.
- The latched-fatal mailbox overflow is replaced by the explicit pressure path.

**Relative adjustments** stay ordered and are never replaced (EX:135–136).
- Consecutive identical `UIRangeAdjustment` steps of one control may merge into the tail record of that window's queue, raising `SliderControlEvent.count`. This merge is allowed only while that record is still undelivered and is the last record admitted.
- This is lossless because saturating steps of one kind commute. Different adjustments are never merged.
- The product adapter applies `count` with checked integer arithmetic.

**Names.** There are two reserved lanes: the **terminal reservation** (COMMIT/CANCEL records) and the **control lane** (close, cancellation, wake state and cleanup; EX:89–91). CE:97–101's "provider option" wording is superseded.

### Known conflict 2: what text eligibility loss cancels

The lifecycle side is adopted. Eligibility loss is hide, disable, detach, a modal barrier or fault quarantine. When an editor with an active interaction loses eligibility, the following happens exactly once, before the next input dispatch:

1. The composition is cancelled; marked text is never committed. A platform that can only commit records an adaptation (LC:176–178), whichever rule applies.
2. The non-composing draft stays as the editor's text.
3. The interaction ends with one SYSTEM cancel carrying `CONTROL_CANCEL_ELIGIBILITY_LOSS`, the retained draft and `composing = false`. The baseline is not restored.

Dirtiness is measured against the accepted baseline:
- The next edit, Return or focus-in starts a new interaction from the last accepted text.
- A later Return therefore commits the retained draft once.
- Escape still restores the baseline (CE:135–137).

Occlusion alone settles nothing.

Platform notes:
- **macOS:** the provider settles editing before `setHidden`, and binds `hasMarkedText` and the discard of marked text.
- **Android:** system Back on a focused editor follows the platform (it dismisses the IME) and never restores the baseline.
- **Touch-only iOS and Android:** E01's cancel row is an adaptation; hardware Escape is the cancel path.

### Third conflict: accepted commit versus eligibility loss

This conflict was not in index.md; the LC and EX side is adopted.
- **Delivery recheck.** Every queued domain delivery, control terminal events and `IButton.onAction` clicks alike, rechecks effective eligibility at invocation.
- **The `ineligible` disposition.** An ineligible target's record gets a new receipt disposition, `ineligible`, added to EX:129's six. It is observable in provider traces and counters. It is never converted into a CANCEL and never delivered later.
- **E01 oracle.** CE:333 now reads: "exactly one USER commit per accepted dirty edit, unless its disposition is `ineligible` in the trace".
- **BTRSmith.** `IButton.onAction` and `IButton.setEnabled` are listed as changed ids for the BTRSmith rename table (CL-UIA-14 step 3).

### Shared rules

**Ordering and replacement**
- Ordered control records are delivered in admission order within one window's or scene's semantic queue, across channels, interactions and controls.
- A replaceable record (a draft, candidate, absolute preview, or a scroll or state observation) is replaced in place only when every record admitted after it is also replaceable. Otherwise the new snapshot is appended.
- No order is defined across windows or scenes, or between executor classes (input, worker completions, timers, presentation, control lane).
- The replacement key is (owner, generation, interaction, registrationEpoch, channel).
- A publisher record with `replacementKey == 0` is ordered. A positive key is replaceable within its publisher, generation and key. `WORK_SUSPENSION_REPLACE` requires a positive key; otherwise the call is invalid (`PUBLISH_INVALID`, or a throw from `schedule`).

**Glossary**

- **Generation:** one per live native owner (view, window, scene or publisher), fresh on reopen or recreation.
- **Revisions**, named by owner:
  - `modelRevision` for a control;
  - `rangeRevision` for a slider;
  - `documentRevision`, supplied by the application in close transactions;
  - `treeRevision` for a container;
  - `stateRevision` for window and interaction snapshots.
- **Origin:** MODEL means value, option or range replacement. SYSTEM covers lifecycle, including eligibility loss caused by `setEnabled`, `setVisible` or detach.
- **Cancellation types:** four distinct types that never substitute for one another: `ControlCancelReason`, `WindowCloseState`, `PublishCancelOutcome` and `CallbackCancellation`.
- **Terminal terms:**
  - a "terminal event" is a COMMIT or CANCEL;
  - a "receipt disposition" is one of delivered, cancelled, stale-generation, superseded, closed, failed or ineligible;
  - "faulted/quarantined" replaces "terminal fault".

**Initial state.** No subscription replays an initial delivery. Each state observation carries its revision. A client subscribes, reads the getter, and ignores queued snapshots whose revision is at or below the one it read.

**Errors**
- **Programmer errors throw a string,** as today. These include invalid or nonfinite arguments, the wrong thread, a closed or foreign owner, a second live handler, an invalid transition, and a terminal-pool overrun at subscribe time.
- **Expected runtime conditions return typed outcomes:** capacity, staleness, closing during a race, native mutation failure and transaction results.
- **`close`/`pollClose`** report teardown only as a `CallbackCancellation`. A native teardown failure returns FAILED or RETRYABLE_FAILURE, keeps ownership, and records its diagnostic under the existing `run()` failure policy.
- **A throwing receiver** follows the existing work-error policy: the failure is recorded, an orderly quit follows, and `run()` rethrows it.
- **`tryPublish` and `requestCancel`** never throw.

**Executor affinity.** The normative phrase is "the application's UI executor thread": the thread that called `GUI.initialize`, or the host thread that attached the application. It never means the process main thread.
- These are provider facts, not portable rules:
  - UIKit and AppKit fix it to the main thread;
  - Android Views use the main Looper;
  - a GameActivity route needs a UI executor thread that lives as long as the process, created by custom glue rather than native_app_glue's per-Activity `android_main`, and its interop executor is `caller`;
  - Win32 and WinUI use the owning message or `DispatcherQueue` thread.

**Delivery wording.** CE:89 and EX:142 now read: "after the native callback that produced the snapshot returns; delivery may occur inside a platform-owned tracking loop". A receiver delivered during tracking never re-enters tracking and never starts a nested loop.

**Clock**
- UI deadlines use a monotonic clock that excludes device-suspended time: `CACurrentMediaTime` on Apple platforms, `uptimeMillis` on Android, and the provider's monotonic clock on Linux and Windows. Each provider declares its clock in evidence.
- E30's oracle does not depend on the clock: a timer due before or during suspension fires at most once after resume.
- The wall-clock-move trial runs only on disposable CI runners, or through an injected civil-clock source.

**Fairness** is stated as an outcome.
- Each wake services the provider's own classes in bounded slices (a count budget plus a monotonic time budget, recorded in evidence) and then yields to the host.
- Rotation and the check before dequeue apply to provider-owned queues.
- Service gaps are measured per class, and only runnable classes accrue them. Fairness for host-scheduled input and presentation is measured, not scheduled.
- **macOS** drains one provider queue under count and time budgets, never a `performBlock` per item.
- **Win32** may deliver semantic work from a coalesced wake posted to a message-only HWND that an OS modal loop dispatches, provided no application callback is on the stack. Otherwise every platform declares its OS-modal intervals uniformly in E40's gap measurement.

### Control-events review decisions (CE:347–359)

1. **Composition preservation** is provisional on both macOS and Linux.
   - macOS has neither marked-text evidence nor a delegate binding.
   - Linux gets `SDL_EVENT_TEXT_EDITING` plumbing (UI1 condition 3).
   - Physical IME evidence is an owner session (MAC-UIA-01 / the Q33 route).
2. **MODEL cancellation as observation** is approved.
   - A MODEL cancel goes only to `onCancel`, and adapters dispatch product commands only for a USER-origin COMMIT.
   - Every event carries `modelRevision` so that a consumer can reject a stale application.
   - This is enough for the BTRSmith subscription migration (CL-UIA-15–18).
3. **Popup survival across a keyed refresh** is optional for the provider and always observable.
   - LinuxSelect is a custom overlay and may retain the candidate by key.
   - MacOSSelect, which replaces its menu with `setMenu`, either mutates its `NSMenuItem`s in place, or ends tracking with `NSMenu cancelTracking` and emits one MODEL cancel on any refresh that changes the item set while the menu is open.
   - Retention is never inferred without evidence, and the mobile rows are provisional.
4. **Terminal capacity, relative adjustments, revisions and cross-channel order** follow known conflict 1, the ordering rule and the glossary.
5. **The slider factory and the pointer bound.**
   - Both `createSlider` signatures stay. Their validity widens to `setRange`'s:
     - equal endpoints give an inert control;
     - there is no 1,000-interval cap;
     - `intervals > 0` maps to `step = span / intervals`, and `0` means continuous.
   - Ticks are chosen by the provider and decoupled from steps, so macOS snaps in the provider, with ties toward the higher value (CE:199–201).
   - The pointer error is at most half a step plus the measured projection error, recorded per provider.
   - Keyboard and accessibility paths stay exact in `long long`, through the product adapter.
   - UI2 adds no integer slider interface.
   - `value()` and `range()` return the double the provider holds as authority, and validity is judged in the portable double domain.
   - An absolute assistive value (`SLIDER_INPUT_ABSOLUTE_ASSISTIVE`) produces one COMMIT, no PREVIEW, and is subject to the pointer-style bound.

The CE rules for selection (CE:153–185), the slider range (CE:189–234) and two-axis scroll (CE:238–255) are approved as drafted, with three refinements:

- **Setter echoes.** A provider recognizes a setter echo by comparing it with the last published value and model revision. A synchronous reentrancy flag is not enough on Android or WinUI.
- **Overscroll.** Observed offsets are clamped, even during overscroll.
- **Visible rectangle.** `visibleRect` is the full viewport of the scroll view intersected with the document bounds, before any safe-area or IME inset is subtracted. Geometry adjusted for those insets belongs to UI5.

### Executor review decisions (EX:267–270)

- **Operation names.** `IUIWorkPublisher` is renamed `IApplicationPublisher`, and `IUIWorkReceiver.deliver` becomes `IApplicationPublicationHandler.deliver`. The facade gains `GUI.createPublisher`, `GUI.schedule` and `GUI.attachHost`. `BackgroundJobExecutor.subscribeCompletionReady` is not a catalog id.
- **Native-writer transport.**
  - A fixed, identity-only, plain-data record is frozen: generation, sequence, suspension, `replacementKey` and a `long long` payload.
  - "Maximum payload bytes" is dropped. A bounded byte payload would be a later versioned addition.
  - Large results stay with their owner (the `BackgroundJobCompletion` path, EX:79–82).
- **Worker rule.**
  - The UI owner retains the publisher through its outcome and registration for the publisher's whole life.
  - A worker uses the reference it was handed before it started, and never releases the last reference.
  - The publisher state a worker can reach is mutex-guarded plain data (EX:101–102).
  - A reference-count write from a worker found in E04's worker rows under the sanitizers is filed as CL-REQ-UI2-F before those rows freeze.
- **Admission accounting.**
  - `post`, `postAfter` and `schedule` keep `GUI.initialize`'s `workCapacity` budget.
  - Each publisher preallocates its capacity at `createPublisher` against a separate application publisher budget. The provider defines that budget and records it in evidence; exhausting it gives `APPLICATION_PUBLISHER_BUDGET_EXHAUSTED`.
  - The control lane is charged when an owner or publisher is created.
  - Accepted, executing and suspended receipts all count until their disposition.
- **Suspension defaults.**
  - `post` defers; `postAfter` is a one-shot timer that defers until resume.
  - Animation owners use `schedule` with `WORK_SUSPENSION_REPLACE`.
  - Desktop providers never report SUSPENDED. E30's native suspension rows are adaptations there and belong to Stage 35 or CL-UIA-22. The injected test-host rows run now as stand-ins.
- **Termination.**
  - `requestQuit` stays irreversible.
  - A native quit first runs a coordinator for a group of windows inside the provider (see LC decision 1).
  - Shutdown follows the order in EX:169–177.
  - The 250 ms close-start budget is measured, but no close drain budget is advertised until a nonblocking BackgroundJobs stop/drain adapter exists (EX:284–287).
- **Loop modes.** These are in the [provider decisions](#macos-and-linux-provider-decisions). On Linux, the pump checks its budget before dequeuing, which fixes `LinuxApplication.btrc:221-228`.

### Lifecycle review decisions (LC:313–321)

**1. Transaction shape, the no-handler policy and quit coordination** (approved).

*Requests and handlers*
- **No handler.** The no-handler policy (LC:64–66) is approved: no live handler gives `WINDOW_CLOSE_REQUEST_AUTHORIZED_NO_HANDLER`, and close begins.
- **The live handler is the intercept predicate.**
  - Providers answer `windowShouldClose`, `WM_QUERYENDSESSION` and `presentationControllerShouldDismiss` from it.
  - They keep `OnBackPressedCallback.isEnabled` and `isModalInPresentation` in sync with it.
  - Applications should register the handler only while the document is dirty, so that Android keeps its back-to-home animation.
- **Repeated requests.** A repeated request returns `WINDOW_CLOSE_REQUEST_ALREADY_PENDING` with the same transaction.
- **Cancelled handler.** Cancelling the handler while a transaction is pending resolves it as CANCELLED.

*Deciding and saving.* The document owner is the only authority on revision and dirtiness. The transaction records the highest `documentRevision` the owner has reported.
- **`decide` in AWAITING_DECISION.**
  - SAVE enters SAVING and issues a fresh attempt (`attempt` is greater than 0).
  - DISCARD authorizes only the acknowledged revision.
  - CANCEL resolves CANCELLED and keeps the draft, route, focus and scroll anchor.
- **`decide` in SAVING.**
  - CANCEL resolves CANCELLED; the save may still persist, but it cannot authorize close.
  - SAVE with a higher `documentRevision` reports an edit made during the save. The transaction records it and issues no new attempt.
  - Any other call is a programmer error.
- **Stale and late calls.** A lower revision returns `STALE_REVISION` and changes nothing. A call after the transaction has resolved returns `NOT_PENDING`.
- **`completeSave`.**
  - A wrong attempt returns `STALE_ATTEMPT`.
  - When `succeeded` is true and `savedRevision` equals the highest reported revision, the transaction is AUTHORIZED. The provider then consumes the single-use authorization and calls final close (CLOSING), bypassing the decision hook once.
  - When `succeeded` is true but `savedRevision` is lower, it returns `STALE_REVISION` and goes back to AWAITING_DECISION, keeping the newer draft.
  - When `succeeded` is false, it goes back to AWAITING_DECISION; a retry needs a new SAVE decision.

*Forced teardown and quit*
- **Host-forced teardown** (OS scene or Activity destruction, or process death) cannot be vetoed. It resolves any pending transaction as OWNER_LOST, and final close proceeds. Durability is E47's concern.
- **Native quit** (`applicationShouldTerminate`, `SDL_EVENT_QUIT`):
  - It opens one transaction with `WINDOW_CLOSE_APPLICATION_QUIT` for each window that has a handler.
  - In this group mode, an AUTHORIZED transaction holds without closing until every window has authorized and its revision revalidates. Only then does the coordinator call `requestQuit`.
  - Any CANCELLED leaves every window open.
- **No new public id.** An application-initiated coordinated quit command is UI3 (CX-UIA-24).
- **UI2's E46 entry paths** are native window close, native application quit and `IWindow.requestClose`, each with two windows. Back and tab navigation are UI3.
- **`IWindowCloseTransaction` exposes no reason or id accessor in UI2.** If UI3 navigation needs one, it is a UI3 versioned addition.

**2. Rollback and quarantine encoding.**
- `ContainerBatchResult` is defined above.
- A faulted parent shows `ViewInteractionState.faulted`. It permits only inspection and close/drain, and keeps every child it may own.
- `insert` and `move` are single-edit batches against the current `treeRevision`. Any result other than COMMITTED throws a string naming the result kind, and ownership is as that result describes. Callers who need typed failures use `applyBatch`.
- Native atomicity is not required.
- `move` never detaches the subtree from its window:
  - on macOS it reorders `NSStackView` arranged subviews, or uses `sortSubviewsUsingFunction:context:` through a C comparator shim, or `addSubview:positioned:relativeTo:` once it is shown not to resign the first responder;
  - on Android it never uses `removeView`/`addView`.
- E29 gains a row asserting zero commit or cancel events and preserved marked text across a move.

**3. IME cancellation and callback admission** follow known conflict 2 and the third conflict.
- State notifications are replaceable keyed records.
- A callback already admitted may finish, but it cannot enqueue into an ineligible generation.
- Restoring eligibility never replays input, steals focus or resets child enabled preferences.
- E39 handles a GPU view that was focused programmatically.

**4. Cleanup lease and teardown errors.** The lease is not part of the frozen surface.
- Callers complete close and drain before the final release (LC:246–248). A final release of an open owner off the UI executor keeps its named fatal diagnostic, and E31 asserts that policy.
- If a lease is built later, public handles hold only raw `Atomic<uint>` lease cells borrowed from `AtomicBuffer` storage the executor owns. They never hold managed references to native owners or scopes; the parity reviewer showed a lease reached through a managed field is lost in cycle collection. Component `CallbackScope`s are affine to the UI executor.
- Any lease work goes through `REQUEST(CL-REQ)`.
- **E31 COMPLETE** means:
  - native resources and registrations are released, and no callback can enter, at the moment COMPLETE is returned;
  - platform-deferred deallocation (autorelease, Core Animation) is observed within a bounded drain;
  - the class of the one allowed AppKit-private survivor is named and bounded in the evidence.

**5. Retained presentation and the close/publish race** are approved as drafted (LC:252–267).
- Linux retains the identity and the `Image` at publication, so it stops painting from a mutable handle.
- It checks `isOpen` before the early return for the same alias.
- It linearizes close against publication, either with a locked or atomic open state, or by confining close to the UI executor after handoff.

**Window state** (LC:187–203; desktop N7)
- `presentable` is a property of the window. Drawable readiness of a GPU child belongs to `IGPUView` and UI9, with no UI2 operation.
- Linux derives application activity from window focus, with debouncing; it is UNKNOWN before the first observation.
- Linux hidden and minimized events update the stored eligibility flag.
- Unknown occlusion stays unknown, and no provider infers occlusion from missing paint events.

### UI1 conditions

1. **Freeze `attachHost` at least provisionally: met.** The host link is frozen provisionally as above, with rules (a)–(h) from feasibility-other 1 and the test-host fixture from desktop B1. `CL-P2-22` and `CL-UIA-22` confirm it. The hosted-application receiver is a named carried gap, not a private bridge.
2. **Executor affinity: met.**
   - The normative phrase is recorded under Shared rules.
   - The Windows and Android rows are marked provisional one by one (EX:225 and 227, CE:312 and 314, LC:277 and 279), so a WinUI or GameActivity outcome changes a mapping and does not break the contract.
   - The Android rows state that the main Looper is the Views mapping.
3. **SDL composition: plumbed, not adapted.**
   - CX-UIA-23 flattens `SDL_EVENT_TEXT_EDITING` (text, start, length) in `SDL.h` into a preedit buffer in `LinuxTextField` that drives `composing`. It uses `SDL_ClearComposition` for cancellation on Escape and on eligibility loss, and proves the path with synthetic `TEXT_EDITING` events pushed through `SDL_PushEvent`.
   - The Linux composition rows stay implemented-unverified (stand-in) until an owner IME session.
   - Linux undo is not pulled forward. E01's Linux undo-preservation row is classified missing, with CX-UIA-27 named, and is never counted as passed at UI2.
4. **UI2 on E42 and E46: met** by the link hunk above, together with E01–E04.

### macOS and Linux provider decisions

These settle desktop B2 and N1–N15.

**macOS run loop and tracking**
- **Run-loop modes.** The macOS wake source and every `postAfter`/`schedule` timer register in `kCFRunLoopCommonModes`, at least the default mode plus `NSEventTrackingRunLoopMode`.
  - The wake is a version-0 `CFRunLoopSource` on `CFRunLoopGetMain()`, signalled from any thread with `CFRunLoopSourceSignal` plus `CFRunLoopWakeUp`.
  - Its perform callback is a btrc C callback table (`Callback.btrc` CFunction/OwnedClosure).
  - CX-UIA-22 step 3's "performBlock" alternative is dropped: it is not thread-safe. `[NSApp postEvent:atStart:]` is not dequeued during tracking.
- **Reentrancy.** A model change, eligibility loss or close that targets a control under active native tracking ends that tracking and emits exactly one MODEL or SYSTEM cancel. Popups use `NSMenu cancelTracking`.
- **Slider: provider-owned tracking on macOS** (N1).
  - The local monitor consumes `mouseDown` on the `NSSlider`, drags are tracked in the main loop, and the provider sets `doubleValue`.
  - E03's oracle is tightened for each trigger: release gives exactly one COMMIT; Escape, capture loss and eligibility loss each give exactly one CANCEL, with the start value restored if the revision matches.
  - Native `NSSliderCell` tracking overrides wait for Objective-C subclassing (interop step 6, Stage 29).
- **Legacy nested-loop APIs** (N10). `IWindow.showAlert` and `GUI.chooseDirectory`:
  - are excluded from the executor's fairness guarantees;
  - are forbidden inside close-decision handlers.

  The application presents Save/Discard/Cancel in its own UI. An asynchronous prompt API is not part of UI2.
- **Quit.** `applicationShouldTerminate` keeps `NSTerminateCancel`. That logout is not continued while a decision is pending is recorded as a macOS adaptation.

**Linux**
- **Quit.** Linux sets `SDL_HINT_QUIT_ON_LAST_WINDOW_CLOSE=0`.
- **Pump.** The Linux pump keeps no 250 ms idle polling cap for E04; it wakes for worker results through `btrcSdlPushWake`.

**Trials and fixtures**
- **Quit trial.** E46's quit-cancel trial is driven by `[NSApp terminate:]` on macOS and an injected `SDL_EVENT_QUIT` on Linux.
- **macOS E40 and E24** add trials with an open popup, a slider drag, live resize and a sheet (never `runModal`).
- **Fault injection** (N4). RolledBack, FailedConsistent and quarantine are proven by probe-owned seams:
  - on macOS, swizzled AppKit mutation selectors under `src/tests/native/gui/ui2/probes/macos` raise `NSException`, which the adapter translates;
  - on Linux, the GPU and SDL allocations of a reattach are interposed.

  Infallible software steps are not fault boundaries. No fault seam is compiled into the shipped stdlib.
- **E42 on headless Linux** (N8). The minimize, cover and display/scale rows are recorded as unavailable on headless runners. The 60-second zero-presentation oracle is proven through hide. A minimal window manager for the X11 session would be a later nix change owned by Claude, not scheduled here.

### Deviations from the reconciler's table

1. **Receiver method names** follow the parity review: `textEvent`, `selectionEvent`, `sliderEvent`, `scrollEvent`, `deliver`, `closeRequested`, `stateChanged` and `interactionChanged`, instead of `invoke`.
2. **`IApplicationHost.scheduleTurn`** is added (desktop B1), so that pull hosts and push hosts both learn timer deadlines.
3. **`ApplicationActivity`** gains `UNKNOWN`, and `WindowState.drawableReady` becomes `presentable` (desktop N7).
4. **`SliderControlEvent.count`** is added, for lossless merging of identical relative adjustments (desktop B3, restricted to identical steps).
5. **`ControlPhase`** is supplied as one shared enum; the reconciler's value list omitted the phase type that CE requires.

The new-id count rises from 52 to 53.

### Scope of the UI2 landing

| Scope | E-cases |
| --- | --- |
| Required at CL-UIA-14 on macOS and Linux X11, both frontends, plain and ASan/UBSan | E01, E02, E03, E04, E29, E31, E35, E39, E40, E46 |
| Packet acceptance additions | E40 is added to CX-UIA-22, including the macOS tracking trials. E31 is added to CX-UIA-23 |
| UI2 partial contributions, recorded as implemented-unverified and not closed | E24 (saturation and terminal survival); E30 (the monotonic deadline and wall-clock rows, plus injected test-host suspension; native suspension goes to Stage 35/CL-UIA-22); E33 and E34 (the model and event subset; UI3/UI4/UI7/UI8 own the rest); E42 (the window-state subset; hosted timings are diagnostic, LC:302–304) |
| Waiting | The Wayland halves wait for the libdecor fix and a re-run of all four rows (ui1-feasibility.md:17) |
| Numeric budgets | E40's p95 ≤100 ms, service gaps ≤250 ms and close start ≤250 ms apply to plain builds. Sanitized runs check counts and losses only |

## Provisional rows

These are the Windows, iOS/iPadOS and Android mappings, and they stay provisional until `CL-UIA-22`.

Until the real shells implement the UI2 methods, the Windows, iOS and Android shells implement every new method by throwing the typed unsupported error, and their catalog cells stay missing. `CL-UIA-22` decides Win32 versus WinUI and Android Views versus GameActivity. A mismatch is a versioned change, landed atomically with macOS and Linux.

| Platform | Host link and executor | Control events | Lifecycle, mutation, exposure, image |
| --- | --- | --- | --- |
| Windows (Win32 or WinUI) | An application-owned message loop with `MsgWaitForMultipleObjectsEx`, an event or message wake, and a bounded executor turn; or WinUI's `DispatcherQueue`. The executor thread is the owning message or `DispatcherQueue` thread. A coalesced wake to a message-only HWND may deliver semantic work from inside an OS modal loop when no application callback is on the stack. Otherwise the OS-modal intervals are declared for E40 | EDIT notifications and IME completion, common-control selection notifications, trackbar notifications and HWND viewport state. Keyboard and accessibility increments keep their intent instead of decoding a rounded trackbar value. Setter echoes are recognized by comparing value and revision, because WinUI echoes asynchronously | Win32 close and quit route through the transaction and a continuation on the message thread. `WM_QUERYENDSESSION` is answered from the live handler. Child order and rollback, focus and IME transitions, DPI, minimize, drawable loss and image resource lifetime. Desktop activity and exposure stay distinct |
| iOS / iPadOS (UIKit) | `UIApplicationMain` and the scene delegates own entry; `main()` never returns. The host entry calls `GUI.attachHost` on the main thread, and a common-mode main-run-loop wake services one bounded turn and returns to UIKit. `GUI.run` is typed unsupported. The clock is `CACurrentMediaTime`. "Scene suspended" means scene background; process suspension freezes the whole application | `UITextField` editing actions and delegate, a keyed picker or menu selection owner, `UISlider` tracking, and the `UIScrollView` delegate with clamped offsets during overscroll. Keeping the draft on eligibility loss needs text surgery in the provider; a platform that can only commit records an adaptation. The touch-only E01 cancel row is an adaptation | Scene dismissal is a request only where a veto is supported (`presentationControllerShouldDismiss`, with `isModalInPresentation` kept in sync with the live handler). A system scene disconnect is host-forced and gives OWNER_LOST. Scene activation, size, scale, image retention and view order. iPad multi-scene, split view and Stage Manager need two-scene isolation checks. One `ios` family, with iPhone/iPad `device_class` |
| Android (Views or GameActivity) | The Views mapping: Activity and the main Looper own entry; a coalesced Handler wake drains one bounded slice; Choreographer supplies presentation opportunities. The Java shell calls the program entry through `RegisterNatives`. A GameActivity route needs a custom UI executor thread that lives as long as the process (interop executor `caller`). The clock is `uptimeMillis` | `EditText` `TextWatcher` and editor actions, with composition distinguished; a keyed list adapter; `SeekBar` tracking; actual scroll callbacks. There is no stock two-axis scroller, so a nested or custom scroller is needed and its interaction with the nested-scroll fixture is checked. Setter echoes arrive asynchronously and are recognized by comparing value and revision. Back on a focused editor dismisses the IME and never restores the baseline | `OnBackPressedCallback.isEnabled` is kept in sync with the live handler. Activity destruction cannot be vetoed and gives OWNER_LOST. `ViewGroup` order without `removeView`/`addView`; IME and capture settlement; Activity, window and drawable transitions; image lifetime. Recreation gets a fresh generation, and no old transaction resumes |

## Carried gaps and owners

| Gap | Owner |
| --- | --- |
| Hosted-application receiver: `attached`, `windowConnected`, `windowEnding` (cannot be vetoed), `lifecycleChanged`, `detached`, delivering host-created windows with a fresh generation | `CL-P2-22` drafts its name and signatures against CX-P2-36/CX-P2-41. `CL-UIA-22` freezes it as a versioned addition, landed atomically with macOS and Linux, before CX-UIA-16/17 run their window step. Neither shell builds a private bridge meanwhile |
| Hosted macOS keyboard delivery (the window never becomes key) | A CX-UIA-10 follow-up. CX-UIA-22 counts no Tab, Return, Escape or arrow row until a run shows `window_key=true` |
| macOS key-view loop with Full Keyboard Access off; GPU-view focus | UI3 (E05–E07, E13/E14), UI8 and UI9 |
| IME evidence on both platforms | An owner session (MAC-UIA-01 / the Q33 route). The composition rows stay implemented-unverified |
| Linux undo and redo | CX-UIA-27 (E14). E01's Linux undo row is missing at UI2 |
| E40 lossless pump | CX-STDLIB-01, re-verified by CX-UIA-23 on X11, with Wayland after the libdecor fix. macOS E40 is in CX-UIA-22 |
| Wayland libdecor 0.2.5 stall | Claude (the nix pin; the CX-UIA-11 residual) |
| No AT-SPI bridge; the accessibility halves of E03, E34 and E39 on Linux | CL-UIA-10 and CL-UIB-12 (UI8) |
| Synthetic-only Linux input; leak accounting that counts SDL windows only, with LeakSanitizer off | The CX-UIA-23 rows for E31, E35, E39 and E42 |
| E42 minimize, cover and display rows on headless Linux | Unavailable at UI2. A minimal window manager would be a later Claude-owned nix change |
| Evidence freshness (the macOS shard predates batch 45; the JUnit artifact expires 2026-10-19) | A `focus=native-gui` dispatch on main before the CL-UIA-14 landing |
| Cleanup lease | Deferred. Optional work is CL-REQ-UI2-F through `REQUEST(CL-REQ)` |
| Nonblocking BackgroundJobs stop/drain adapter (a prerequisite for advertising the UI close budget) | Unassigned. CL-UIA-14 files it as a Codex request. CX-UIA-21 delivers only `subscribeCompletionReady` |
| Objective-C subclassing (`NSSliderCell` tracking, `accessibilityPerformIncrement`) | Interop step 6, Stage 29 (native-interop-ownership.md:1151). Relative adjustments initiated by accessibility on macOS are a UI8 dependency |
| An asynchronous prompt to replace `showAlert`/`chooseDirectory` | Not UI2 |
| Win32 versus WinUI; Views versus GameActivity; the Android key-filter issue (feasibility-other 2) | `CL-UIA-22`, and UI3 for the key filter |
| The `ControlApplyResult` divergence from this record's error rule | Flagged to `CL-UIB-02` |
| E47 restoration | UI1/UI5/UI10; not a UI2 dependency |

## Compiler gaps

No compiler change blocks UI2. The parity reviewer's reproductions are in `reviews/ui2/parity.md`, with the probes under `the review workspace (not retained) parity/`. Each gap is proposed as a Claude packet: a fix that changes behavior lands paired in both compilers, and a btrcc-only parity fix is labelled as such.

| Proposed packet | Scope | Reproduction (summary) | UI2 status | Acceptance |
| --- | --- | --- | --- | --- |
| `CL-REQ-UI2-A`: generic interface implementation | Both compilers, paired | `class ProgressReceiver implements IUIWorkReceiver<ProgressRecord>` gives `Expected LBRACE, got LT '<'` at 7:50 in both | Not needed: UI2 freezes a non-generic record. Not scheduled unless a versioned change wants typed payloads | Generic interface implementation and dispatch pass in both compilers, with corpus tests |
| `CL-REQ-UI2-B`: btrcc rich-enum variant with a `Vector<class>`/`Vector<interface>` payload | btrcc parity defect | `BatchResult.FailedConsistent(1LL, retained)` runs under the reference compiler; btrcc reports `expects 'Vector<IProbeView>' but got 'Vector<IProbeView*>'` (also in the 2026-10-03 bundle) | Not used by UI2 (outcomes are owning classes) | The reproduction transpiles and runs identically under both compilers, with a regression test |
| `CL-REQ-UI2-C`: borrowed managed payload escaping a rich enum | Both compilers, paired; memory safety | `return DetachResult.Detached(child)` from a function whose local owns `child`, followed by a read, gives ASan `heap-use-after-free` under both | UI2 forbids rich enums with managed payloads until this is fixed | The reproduction is ASan-clean, or rejected with identical diagnostics, in both compilers |
| `CL-REQ-UI2-D`: realtime POD rule for `OwnedBuffer`/`SPSCQueue`/`Span` not rechecked at generic specialization | Both compilers, paired | `UIWorkMailbox<string>` or `UIWorkMailbox<ProbeView>` transpiles, then `cc` reports `incompatible pointer type`. The reference compiler skips the check at `analyzer/types.py:1746-1749`; btrcc checks at `analyzer/validation/Types.btrc:879` | Moot for UI2 (non-generic POD record) | Specialization is rejected with identical diagnostics in both compilers |
| `CL-REQ-UI2-E` (optional): `Atomic<T>` with 64-bit integer payloads | Both compilers, paired | `Atomic<unsigned long long>` gives "payload must be bool, int, uint, or a raw pointer" (4:10 versus 4:2) | Not needed: admission uses the bounded mutex | General compiler work |
| `CL-REQ-UI2-F` (optional): executor-affine release for managed classes | Both compilers, paired | A worker nulling the last holder of a component with a `CallbackScope` aborts with "Callback scope destruction requires its creating thread"; a cycle-collected `__del__` reading a managed `lease` field finds it null | Not needed: today's fatal rule and the raw `Atomic<uint>` lease-cell pattern hold | Needed only if E04's worker rows or a future lease require it |
| `CL-REQ-UI2-G`: btrcc diagnostic positions in files with imports, and wording parity | btrcc parity defect | The reference reports `DiagnosticLineWithImport.btrc:4:14`; btrcc reports `515:14` with no file name. Wording also differs for a duplicate member, an ambiguous bare enumerator and a lambda passed as an interface | Not blocking; affects the diagnostics of CX-UIA-21's fixtures | Identical file, line, column and wording in both compilers, with tests |

**Binding data only.** These are not compiler work; they are integrator-applied `GUI/btrc.toml` fragments carried by CX-UIA-22 and CX-UIA-23.
- **macOS (CX-UIA-22):**
  - `CFRunLoopGetMain`, `CFRunLoopSourceCreate`, `CFRunLoopSourceSignal`, `CFRunLoopWakeUp`, `CFRunLoopAddSource`;
  - `NSRunLoop addTimer:forMode:`; `NSMenu cancelTracking`;
  - the `NSTextField` delegate methods and `currentEditor`; `NSTextView hasMarkedText` and the `NSTextInputContext` discard of marked text;
  - `NSClipView` bounds notifications;
  - the `NSWindow` occlusion, backing-scale and miniaturize selectors and notifications.
- **Linux (CX-UIA-23):** the `SDL_EVENT_TEXT_EDITING` flattening and `SDL_ClearComposition`.

## Landing

1. **CX-UIA-21 writes the production interface from this record, exactly as it is written here:**
   - the `I*.btrc` changes, the `GUI.btrc` facade mirrors and `GUI/ControlEvents.btrc`;
   - the BackgroundJobs completion hook, with its README contract and regression test;
   - portable fixtures under `src/tests/native/gui/ui2/` for E01–E04, E29, E31, E35, E39, E40 and E46, plus the two-axis scroll fixture and the host-attached journey;
   - the operation shard rows, `amendments/cx-uia-21.toml`, and the E-case link hunk as a fragment.
2. **CX-UIA-21's owned paths gain:**
   - `src/stdlib/GUI/{IButton,IImageView}.btrc` (comments only);
   - `src/tests/native/gui/NativeGUI.btrc` (`ForeignView`);
   - `docs/design/native-ui-catalog/amendments/cx-uia-21.toml` and the named operation shard files;
   - `src/stdlib/BackgroundJobs/README.md` and `src/tests/python/test_background_jobs_runtime.py`;
   - the `surface/GUIModules.toml` hunk, if that file exists.
3. **CX-UIA-22 and CX-UIA-23 stack on CX-UIA-21.**
   - **CX-UIA-22 gains** every macOS `IView` implementer it does not yet own: `MacOS{Button,GPUView,Grid,Label,LevelIndicator,Panel,ProgressIndicator,Stack}.btrc`, plus `MacOSViewInput.btrc` for provider-owned slider tracking.
   - **CX-UIA-22 acceptance** gains E40 with the macOS tracking trials. Step 3 drops `performBlock`.
   - **CX-UIA-23 gains** `Linux{Container,Stack,Panel,Button}.btrc` and `Linux/SDL.h`. Its acceptance gains E31.
   - **Sequencing.** Paths held by CX-STDLIB-01/02/03/05 are claimable only after those units integrate (D28), so the UI2 landing follows them.
4. **CL-UIA-14 lands the interface, macOS and Linux in one atomic commit on `integ/ui2`.**
   - It applies the fragments and regenerates the derived files.
   - It runs the full batch gate, pushes main, reads all three workflows and ingests the E-case results.
   - It adds the changed ids to the BTRSmith rename table, with the D24 shim noted: the `ISelect` and `IScrollView` entries plus `IButton.onAction`/`setEnabled`.
5. **Packet-text corrections.** Claude makes these when recording this approval; they are WORKSTREAMS text, not source:
   - CX-UIA-16 step 1 and CX-P2-36 step 1 become "`GUI.attachHost` from the host entry";
   - CX-UIA-22 step 3 drops `performBlock`;
   - the acceptance additions above.
6. **Approval record.** The approval row and these review files are recorded in CLAUDE.md, Stage 32, and in the [integration record](../claude-integration-record.md).
7. **Nothing here edits `src/`.** The record changes no compiler, spec, runtime, generated or catalog file. Every source change belongs to CX-UIA-21, CX-UIA-22 and CX-UIA-23, landed through CL-UIA-14.
