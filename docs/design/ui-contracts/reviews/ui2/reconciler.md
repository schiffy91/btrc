# CL-UIA-13 UI2 contract review: Reconciler

Reviewed read-only on main `f6c2f2ae` (2026-10-06) by an integrator review workflow (`wf_b7573fea-5df`). Verdict: **approve**. Every finding raised as blocking was adversarially verified; none was confirmed, and each is closed by a decision in [ui2-approved.md](../../ui2-approved.md).

## Summary

Reconciler verdict for CL-UIA-13: 0 blocking findings. Every cross-draft inconsistency, including the two known conflicts in index.md and a third one I found (whether an accepted commit is delivered after its target loses eligibility), can be settled in ui2-approved.md by choosing one side and naming it. No Codex draft revision is needed. Claude must still write several concrete shapes that the drafts leave to "review" (the close-transaction API, the batch result encoding, the attachHost host link and the publisher payload). The record also has to fix packet scope and owned paths before CX-UIA-21/22/23 can apply it exactly. Evidence is cited per finding. One reference-compiler probe compiled the reconciled typed shapes: `string?` in interface returns and parameters, enum-typed payload fields and a typed `invoke` receiver. File: the review workspace (not retained) reconciler/KeyedSelectProbe.btrc. Selfhost parity is left to the parity reviewer.

RECONCILED OPERATION TABLE. Drafts: CE = ui2-control-events.md (CX-UIA-18), EX = ui2-executor.md (CX-UIA-19), LC = ui2-lifecycle.md (CX-UIA-20). Status codes: N = new catalog id; C = existing id whose semantics change (listed as changed in ui2-approved.md); R = record-supplied, needed by a draft's described behavior but not named by it; RN = renamed from the draft spelling. All subscriptions use `(I<Owner><Event>Handler handler, CallbackScope owner) -> ICallbackRegistration`, and every handler method is `void invoke(<Value> value)`.

| Operation id | Draft | Reconciled signature | E-cases | Status |
|---|---|---|---|---|
| ITextField.onDraftChanged / .onCommit / .onCancel | CE:286 | (ITextControlEventHandler handler, CallbackScope owner) -> ICallbackRegistration | E01, E39 | N |
| ITextControlEventHandler.invoke | CE:290 | (TextControlEvent event) -> void | E01 | N |
| ITextField.setText | CE:143-147 | unchanged signature; "unchanged" means equal to the accepted baseline; changed publication = MODEL cancel + new baseline + revision | E01 | C |
| ITextField.text | CE:28-30 (not listed) | returns the live draft without validateEditing or committing composition | E01 | C (added) |
| ITextField.setEnabled | CE:292-294 | eligibility loss per LC | E39 | C |
| ISelect.setOptions | CE:287 | (SelectModel model) -> void | E02, E33 | N |
| ISelect.optionsState | CE:287 | () -> SelectModel | E02, E33 | N |
| ISelect.selectedKey | CE:287 | () -> string? | E02, E33 | N |
| ISelect.setSelectedKey | CE:287 | (string? key) -> void | E02, E33 | N |
| ISelect.onChanged / .onCommit / .onCancel | CE:287 | (ISelectionControlEventHandler handler, CallbackScope owner) -> ICallbackRegistration | E02, E33, E39 | N |
| ISelectionControlEventHandler.invoke | CE:290 | (SelectionControlEvent event) -> void | E02, E33 | N |
| ISelect.setItems, .itemCount, .selectedIndex, .setSelectedIndex, .setItemEnabled, .isItemEnabled, .selectedTitle | CE:177-185, 287 | D24 shim projection; signatures unchanged | E02 | C |
| ISelect.setEnabled | CE:292-294 | eligibility loss | E39 | C |
| ISlider.range | CE:288 | () -> SliderRange | E34 | N |
| ISlider.setRange | CE:288 | (double minimum, double maximum, double step) -> void | E34 | N |
| ISlider.setRangeValue | CE:288 | (SliderRange range, double value) -> void | E34 | N |
| ISlider.onPreview / .onCommit / .onCancel | CE:288 | (ISliderControlEventHandler handler, CallbackScope owner) -> ICallbackRegistration | E03, E34, E39 | N |
| ISliderControlEventHandler.invoke | CE:290 | (SliderControlEvent event) -> void | E03, E34 | N |
| ISlider.setValue / .setEnabled | CE:288 | snapping, MODEL cancel, unchanged no-op / eligibility | E03, E34, E39 | C |
| IApplication.createSlider, GUI.createSlider | CE:295-300 | signatures kept; validity widened to setRange's; intervals map to a step; ticks decoupled from steps | E34 | C |
| IScrollView.offset | CE:289 | () -> ScrollOffset | scroll fixture (E09 not claimed) | N |
| IScrollView.visibleRect | CE:289 | () -> ScrollRect | scroll fixture | N |
| IScrollView.scrollToOffset | CE:289 | (ScrollOffset offset) -> void | scroll fixture | N |
| IScrollView.onOffsetChanged | CE:289 | (IScrollControlEventHandler handler, CallbackScope owner) -> ICallbackRegistration | scroll fixture | N |
| IScrollControlEventHandler.invoke | CE:290 | (ScrollControlEvent event) -> void | scroll fixture | N |
| IScrollView.scrollOffset, .scrollTo, .setContentSize | CE:289 | vertical compatibility; two-axis clamp | scroll fixture | C |
| IApplication.createPublisher | EX:47 | (int capacity, IApplicationPublicationHandler handler, CallbackScope owner) -> ApplicationPublisherOutcome {kind, IApplicationPublisher? publisher, ICallbackRegistration? registration}; payload provisionally identity-only | E04, E24 | N |
| IApplicationPublisher.tryPublish | EX:48 (was IUIWorkPublisher) | (long long generation, long long sequence, WorkSuspensionPolicy suspension, long long replacementKey, long long payload) -> PublishOutcome; any thread | E04, E24, E40 | N/RN |
| IApplicationPublisher.requestCancel | EX:49 | (long long generation, long long sequence) -> PublishCancelOutcome; any thread | E04 | N/RN |
| IApplicationPublicationHandler.invoke | EX:50 (was IUIWorkReceiver.deliver) | (ApplicationPublication publication) -> void; UI executor thread | E04, E24 | N/RN |
| IApplication.schedule | EX:53 | (IApplicationWork work, double delaySeconds, WorkSuspensionPolicy policy, long long replacementKey) -> ScheduleOutcome {kind, ICallbackRegistration?} | E24, E30 | N |
| IApplication.attachHost | EX:54 | (IApplicationHost host, CallbackScope owner) -> ApplicationHostAttachOutcome {kind, IApplicationHostAttachment? attachment, string error}; PROVISIONAL (UI1 condition 1) | E30, mobile UI1 shells | N |
| IApplicationHost.requestTurn | R (EX:226-233) | () -> bool; any thread, coalesced, never inline; PROVISIONAL | E04, E30 | R |
| IApplicationHostAttachment.serviceTurn | R | () -> void; UI executor thread, one bounded turn; PROVISIONAL; attachment extends ICallbackRegistration for detach | E40 | R |
| IApplicationHostAttachment.transition | R | (ApplicationActivity activity) -> void; PROVISIONAL | E30, E42 | R |
| GUI.createPublisher / GUI.schedule / GUI.attachHost | R (facade mirrors, GUI.btrc:82-102) | same as the IApplication ops | as above | R |
| IApplication.post, GUI.post | EX:51 | exceptions kept; shared accounting and fairness; defer default | E24, E40 | C |
| IApplication.postAfter, GUI.postAfter | EX:52 | monotonic; macOS common-mode timer; one-shot defer-until-resume | E30, E40 | C |
| IApplication.isRunning | EX:55 | attached and servicing, including an OS-owned loop | — | C |
| IApplication.run, GUI.run | EX:60-61 | rejects a host-attached application; lossless fair pump | E40 | C |
| IApplication.requestQuit, GUI.requestQuit | EX:56 + LC:97-103 | stays irreversible; native quit is coordinated first (decision 8) | E46, E31 | C |
| IApplication.close/.pollClose, GUI.close | EX:57 | seal, no worker join, no nested pump | E31 | C |
| BackgroundJobExecutor.subscribeCompletionReady | EX:58 | owner-thread; NOT a UI catalog id (BackgroundJobs package) | E04 | non-catalog |
| IWindow.requestClose | LC:41 | (WindowCloseReason reason) -> WindowCloseRequestOutcome | E46 | N |
| IWindow.onCloseRequested | LC:41 | (IWindowCloseRequestHandler handler, CallbackScope owner) -> ICallbackRegistration; one live handler | E46 | N |
| IWindowCloseRequestHandler.invoke | R (LC:50-53) | (IWindowCloseTransaction transaction) -> void | E46 | R |
| IWindowCloseTransaction.decide | R | (WindowCloseDecision decision, long long documentRevision) -> WindowCloseOutcome | E46 | R |
| IWindowCloseTransaction.completeSave | R | (long long attempt, long long savedRevision, bool succeeded, string error) -> WindowCloseOutcome | E46 | R |
| IWindowCloseTransaction.state | R | () -> WindowCloseState | E46 | R |
| IWindow.state | LC:43 | () -> WindowState | E42 | N |
| IWindow.onStateChanged | LC:43 | (IWindowStateHandler handler, CallbackScope owner) -> ICallbackRegistration | E42 | N |
| IWindowStateHandler.invoke | R | (WindowState state) -> void | E42 | R |
| IWindow.close / .pollClose | LC:42 | prompt-free final close | E31, E46 | C |
| IWindow.hide / .show / .isVisible | R (LC:187-203) | eligibility and state notification | E39, E42 | C (added) |
| IContainer.insert | LC:44 | (IView child, int index) -> void | E29 | N |
| IContainer.move | LC:44 | (IView child, int destinationIndex) -> void | E29 | N |
| IContainer.applyBatch | LC:44 | (long long expectedTreeRevision, Vector<ContainerEdit> edits) -> ContainerBatchResult | E29 | N |
| IContainer.treeRevision | R (LC:120 needs it) | () -> long long | E29 | R |
| IContainer.attach/.detach/.childAt/.childCount | LC:45 | committed order; detach cancels capture | E29, E39 | C |
| IView.interactionState | LC:46 | () -> ViewInteractionState | E39 | N |
| IView.onInteractionStateChanged | LC:46 | (IViewInteractionStateHandler handler, CallbackScope owner) -> ICallbackRegistration | E39 | N |
| IViewInteractionStateHandler.invoke | R | (ViewInteractionState state) -> void | E39 | R |
| IView.isVisible/.setVisible/.close/.pollClose | LC:47 | local flag kept; UI-executor drain | E31, E39 | C |
| IImageView.setImageHandle/.setImage, IImageHandle.close | LC:48 | retained presentation; linearized close/publish race | E35 | C |
| IButton.setEnabled, IButton.onAction | R (decision C3) | queued clicks rechecked at delivery | E39 | C (added) |

New catalog ids: CE 24, EX 12 (including the 6 record-supplied host-link and facade ids), LC 16 (including 7 record-supplied). That is 52 ids for the next reviewed ui-operation release (CX-UIA-21 step 4); the frozen 162/1,620 denominators do not change.

Value declarations, which carry no catalog ids:
- ControlEvents.btrc: ControlEventContext, ControlOrigin, ControlCancelReason, TextControlEvent, SelectOption, SelectModel, SelectAvailability, SelectionControlEvent, SliderRange, SliderInputKind, SliderControlEvent, ScrollOffset, ScrollRect, ScrollControlEvent.
- Executor values: ApplicationPublisherOutcome, PublishOutcome, PublishCancelOutcome, ApplicationPublication, WorkSuspensionPolicy, ScheduleOutcome, ApplicationHostAttachOutcome, ApplicationActivity.
- Lifecycle values: WindowCloseReason, WindowCloseDecision, WindowCloseState, WindowCloseOutcome, WindowCloseRequestOutcome, WindowState, WindowExposure, ViewInteractionState, ContainerEdit, ContainerBatchResult.

CX-UIA-21's owned paths list only ControlEvents.btrc as a new file. Either declare the executor and lifecycle values in IApplication.btrc, IWindow.btrc, IContainer.btrc and IView.btrc (precedent: ButtonTypography in IButton.btrc, StackAlignment in IStack.btrc), or add new files to that packet with a GUI/btrc.toml exports fragment.

## Decisions proposed

- Known conflict 1 (terminal capacity): take the executor side. A terminal reservation is mandatory and per interaction. Each live control-event registration is charged a terminal slot at subscribe time; additional overlapping interactions draw from the pool. On exhaustion the provider yields its native source (stops dequeuing). It refuses an interaction start only at a synchronous native decision point, never retroactively, and never drops a dequeued final input. CE:99-101's 'provider option' is superseded. Name the two lanes: the terminal reservation (COMMIT/CANCEL) and the control lane (close, cancellation, wake, cleanup).
- Known conflict 2 (text eligibility loss): take the lifecycle side. Cancel the active composition (never commit marked text; record an adaptation where a platform can only commit) and keep the non-composing draft in the editor. End the interaction with exactly one SYSTEM CANCEL (reason ELIGIBILITY_LOSS) that carries the retained draft and does not restore the baseline. Dirtiness is measured against the accepted baseline, so a later Return commits the retained draft once and Escape restores the baseline. Mere occlusion settles nothing.
- Third conflict (accepted commit vs eligibility loss): queued domain deliveries, including IButton.onAction clicks, recheck effective eligibility at invocation. An ineligible target gets a new receipt disposition `ineligible`, never a converted CANCEL. IButton.onAction and IButton.setEnabled become changed ids, and E01's oracle carves out the ineligible disposition.
- Ordering: ordered control records are FIFO by admission within one window or scene, across channels, interactions and controls. A replaceable record is replaced in place only if every later record is also replaceable. There is no order across windows or scenes or between executor classes. The replacement key is (owner, generation, interaction, registrationEpoch, channel).
- CE decision 1 (composition preservation): provisional on both macOS and Linux. macOS has no marked-text evidence or delegate binding, and setText must compare against the baseline without validateEditing (MacOSTextField.btrc:63-75). Linux gets SDL_EVENT_TEXT_EDITING plumbing (UI1 condition 3). Physical IME is an owner session.
- CE decision 2 (MODEL cancellation as observation): approved. A MODEL CANCEL goes only to onCancel. Adapters dispatch product commands only for USER-origin COMMIT. Every event carries modelRevision so consumers can reject stale application. This is sufficient for the BTRSmith subscription migration (CL-UIA-15..18).
- CE decision 3 (popup survival across keyed refresh): provider-optional and observable. LinuxSelect is a custom overlay and may retain the candidate by key. MacOSSelect's setMenu replacement (MacOSSelect.btrc:61-75) must emit one MODEL cancel on any refresh that changes the item set while the menu is tracking, unless it mutates NSMenuItems in place. Retention is never inferred without evidence. Mobile rows are provisional.
- CE decision 4 (terminal capacity, relative adjustments, model revisions, cross-channel order in the bounded queue): per the conflict-1 and ordering decisions. Relative adjustments are ordered and never replaceable (EX:135-136). Revision vocabulary per the glossary.
- CE decision 5 (slider factory and pointer bound): keep the createSlider signatures; widen validity to setRange's (equal endpoints inert, no 1,000 cap); intervals map to a step; ticks are decoupled and macOS snaps in the provider. Pointer error is at most half a step plus measured projection error, recorded per provider. Keyboard and accessibility paths stay exact long long, and UI2 adds no integer slider interface.
- EX review (operation names): approved with renames IUIWorkPublisher -> IApplicationPublisher and IUIWorkReceiver.deliver -> IApplicationPublicationHandler.invoke, plus the facade mirrors GUI.createPublisher, GUI.schedule and GUI.attachHost. BackgroundJobExecutor.subscribeCompletionReady is a non-catalog stdlib change.
- EX review (native-writer transport): provisionally freeze an identity-only plain-data payload (long long) with generation, sequence, suspension and replacementKey. Byte payloads come later. The parity reviewer confirms a worker-held handle is expressible; otherwise REQUEST(CL-REQ) and gate E04's worker rows.
- EX review (admission accounting): post, postAfter and schedule keep the GUI.initialize workCapacity budget. Each publisher preallocates its own capacity at createPublisher against a separate application publisher budget, and exhaustion returns an outcome. The control lane is charged at owner or publisher creation. Accepted, executing and suspended receipts count until disposition.
- EX review (suspension defaults): post defaults to defer and postAfter is a one-shot defer-until-resume, as drafted. Animation owners must use schedule with replace. Desktop has no suspension, so E30's suspension rows are adapted there and owned by Stage 35 or CL-UIA-22.
- EX review (termination): requestQuit stays irreversible. Native quit runs a provider-internal group close coordinator first (LC:97-103). Shutdown order is per EX:169-177. The BackgroundJobs nonblocking stop adapter is a prerequisite before the UI close budget is advertised.
- EX review (loop modes): on macOS the wake and timers are registered in common modes; no recursive dispatch during tracking; E40 and E24 trials cover popup tracking, slider drag, live resize and a sheet. On Linux the pump checks its budget before dequeue (fixes LinuxApplication.btrc:221-228).
- LC decision 1 (transaction shape, no-handler policy, quit coordination): approve the no-handler policy (LC:64-66). The record supplies IWindowCloseTransaction.{decide, completeSave, state}, WindowCloseRequestOutcome and WindowCloseState spelled with CANCELLED. App quit uses the provider-internal coordinator; no second command owner.
- LC decision 2 (rollback and quarantine encoding): ContainerBatchResult kinds COMMITTED, REJECTED, ROLLED_BACK, FAILED_CONSISTENT and FAILED_QUARANTINED, with treeRevision, failedStep, error and detached/retained lists. A faulted parent appears as ViewInteractionState.faulted. Add IContainer.treeRevision(). The record does not demand atomic native operations.
- LC decision 3 (IME cancellation and callback admission with CE; coalescing and generation with EX): the conflict-2 and conflict-3 decisions above. State notifications are replaceable keyed records. Generations follow the glossary. A callback already admitted may finish but cannot enqueue into an ineligible generation.
- LC decision 4 (cleanup lease and teardown errors): the lease is not frozen; callers complete close before release; off-executor final release of an open owner stays fatal. Teardown failures are reported as FAILED or RETRYABLE_FAILURE with ownership kept, not thrown from pollClose. Programmer errors still throw.
- LC decision 5 (retained presentation and close/publish race): approved as drafted (LC:252-267). Linux must stop painting from the mutable handle (LinuxImageView retains LinuxImageHandle.pixels(), which throws after close: LinuxImageView.btrc:51,59).
- UI1 condition 1: attachHost is provisionally frozen as attachHost(IApplicationHost host, CallbackScope owner) -> ApplicationHostAttachOutcome. IApplicationHost.requestTurn() is any-thread. IApplicationHostAttachment (an ICallbackRegistration) provides serviceTurn() and transition(ApplicationActivity) on the UI executor thread. GUI.attachHost mirrors it. Confirmation by CL-P2-22 and CL-UIA-22 is required, and any later change is a versioned change.
- UI1 condition 2: the normative wording is 'the application's UI executor thread'. Per-platform main-thread or Looper statements are provider mappings. The Windows and Android rows in EX:225/227, CE:312/314 and LC:277/279 are marked provisional individually, so WinUI or GameActivity outcomes are mapping changes.
- UI1 condition 3: CX-UIA-23 plumbs SDL_EVENT_TEXT_EDITING (preedit draft, composing flag, SDL_ClearComposition for cancellation) with synthetic TEXT_EDITING injection. Linux composition rows stay implemented-unverified until an owner IME session; this is not recorded as an adaptation.
- UI1 condition 4: add UI2 to E42 and E46 `links` and owner text in cases/E25-E47.toml, via CX-UIA-21's carried fragment hunk or the integrator at CL-UIA-14, and to native-ui-parity.md:916 and :1001 in the same commit. Optionally add UI2 to E01–E04's links.
- Landing scope: CL-UIA-14 requires E01–E04, E29, E31, E35, E39, E40 and E46 on macOS and Linux X11, both frontends, plain and sanitized. Add E40 to CX-UIA-22 and E31 to CX-UIA-23. E24, E30 (desktop subset), E33, E34 and E42 are UI2 partial contributions. Widen CX-UIA-22, CX-UIA-23 and CX-UIA-21 owned paths for all IView and IContainer implementers and NativeGUI.btrc's ForeignView, sequenced after CX-STDLIB-01/02/03/05.
- Spelling: CANCELLED everywhere (the codebase convention), `CallbackScope owner` in new subscriptions, `I<Owner><Event>Handler.invoke` receivers, long long identifiers, and BackgroundJobs-style outcome enums for new runtime outcomes.

## Findings

### Known conflict 1: is terminal-event capacity reserved per interaction? Choose the executor's mandatory reservation (non-blocking)

Draft: CE vs EX (and LC)

CE ui2-control-events.md:97-101: reservation 'is a provider option for the executor review, not an assertion that today's mailbox already does it'. EX ui2-executor.md:112-117 makes it mandatory: 'Each in-progress edit/gesture needs its own pre-reserved commit/cancel capacity; when it cannot be reserved, refuse to begin the interaction... Do not retroactively reject a native final input already dequeued. The provider retains that event, yields its source, or delivers it through the bounded terminal lane.' EX:93-99 step 2 also reserves 'terminal cleanup capacity'. LC ui2-lifecycle.md:233-236 uses 'CX-UIA-19's terminal channel' for cleanup leases. Today's pump drops a dequeued event at the budget boundary: LinuxApplication.btrc:221-228 polls the 4,097th event and exits the loop (UI1 E40 failure, ui1-feasibility.md:69-72). ActionMailbox.btrc:56-65 latches overflow rather than reserving.

**Recommendation:** Record: a terminal reservation is mandatory and per interaction, never shared with previews (EX side). Mechanism: (a) each live control-event registration is charged one terminal slot at subscribe time, from a terminal pool sized at application creation. (b) An additional interaction on the same control draws a slot when it begins. (c) If no slot is available, the provider first yields its native source: it does not dequeue further native input (the lossless pump, EX:194-197). It refuses an interaction start only at a synchronous native decision point (CE:82) where the platform has one, never retroactively. The reservation applies whichever of onCommit/onCancel are subscribed; a channel with no live registration discards its event. Name the two reserved lanes distinctly: the 'terminal reservation' (COMMIT/CANCEL records) and the 'control lane' (close, cancellation, wake state, cleanup leases; EX:89-91, LC:233-236). CE's 'provider option' wording is superseded.

### Known conflict 2: what text eligibility loss cancels. Choose the lifecycle draft: cancel composition, keep the draft, and emit one SYSTEM cancel (non-blocking)

Draft: CE vs LC

CE:135-139: 'Eligibility loss settles active composition, cancels the unfinished edit and restores its baseline before subsequent input dispatch.' LC:164-168: 'cancel uncommitted IME composition while preserving already committed text'. Both use SYSTEM origin (CE:113-114, LC:169-170) and never commit (CE:137, LC:166). The parity doc favors keeping drafts. native-ui-parity.md:593-595 (item 13) lists 'capture, hover, popups, focus and active composition' as what eligibility loss settles, not drafts. :585-587 (item 12) says hardware keyboard switches must not 'fabricate a commit or discard a draft'. E46 (:1001) preserves drafts on Cancel. Restoring the baseline would mean a setStringValue over the live editor, which contradicts CE's own rule that unchanged state preserves undo and selection (CE:145-146). Native default on all five shells is that the text stays when focus leaves.

**Recommendation:** Record that eligibility loss (hide, disable, detach, modal barrier, fault quarantine) of an editor with an active interaction does the following, exactly once and before the next input dispatch:
(1) It cancels the composition: it never commits marked text. Where the platform can only commit, record an adaptation (LC:176-178).
(2) It keeps the non-composing draft as the editor's text.
(3) It ends the interaction with one SYSTEM CANCEL, reason ELIGIBILITY_LOSS. That event carries the retained draft and composing=false and does not restore the baseline.
Dirtiness is measured against the accepted baseline. The next user edit, Return or focus-in starts a new interaction whose baseline is the last accepted text, so a later Return commits the retained draft once, and Escape still restores the baseline. Mere occlusion settles nothing (both drafts agree). Escape keeps CE's restore-baseline rule (CE:135-137).

### Third conflict, not in index.md: is a natively accepted commit delivered after its target becomes ineligible? Choose recheck and discard (non-blocking)

Draft: CE vs LC/EX

CE:115-118: 'A commit already accepted by native dispatch is terminal: eligibility loss does not turn it into a second cancel; generation/cancellation checks can still prevent delivery to a destroyed owner.' Read with CE:84, this means delivery to a live but ineligible owner. LC:170-174: 'If its queued delivery becomes ineligible, discard domain delivery while retaining resource cleanup; do not turn it into another command.' EX:144-146 rechecks 'lifecycle eligibility' immediately before invocation. Today's IButton contract keeps queued clicks after setEnabled(false): GUI/README.md:43-50 says only scope cancellation and close discard them; LinuxButton.btrc:112-118 and MacOSButton.btrc:66 do not move the action generation. native-ui-parity.md:598-599 (item 13): 'Command availability is rechecked when queued actions run.' E39 (:848) disables a form while a queued action is pending.

**Recommendation:** Record the LC/EX side. Every queued domain delivery (control terminal events and IButton.onAction clicks) rechecks effective eligibility at invocation. An ineligible target's record gets a new, observable receipt disposition `ineligible`, added to EX:129's six. It is never converted into a CANCEL and never delivered later. List IButton.onAction and IButton.setEnabled as changed existing ids and tell the BTRSmith rename table (CL-UIA-14 step 3). Amend E01's oracle (CE:333) to 'exactly one USER commit per accepted dirty edit, unless its disposition is ineligible in the trace'.

### Ordering scope differs: per control across channels (CE) vs per owner/generation/interaction (EX) (non-blocking)

Draft: CE vs EX

CE:90-91: 'Per-control sequence order applies across channels.' CE:94-96: coalescing may not move a newer preview ahead of '...another control's ordered event'. EX:130-132: 'Delivery is FIFO for ordered records within one owner/generation/interaction; unrelated native event classes have no invented global order.' Under EX, a MODEL cancel from interaction 1 could be overtaken by interaction 2's draft on the same control. EX:186-192 rotates fairness across classes and windows or scenes.

**Recommendation:** Record: ordered control-event records are delivered in admission order within one window or scene's semantic queue, across channels, interactions and controls. A replaceable record (draft, candidate, absolute preview, scroll or state observation) is replaced in place only when every record admitted after it is also replaceable; otherwise the new snapshot is appended. There is no order across windows or scenes, or between executor classes (input, worker completions, timers, presentation, control lane). The replacement key is (owner, generation, interaction, registration epoch, channel), which reconciles CE:83's 'event channel' with EX:107's 'key'.

### Payload and scope vocabulary must be spelled once: identifiers, revisions, origins, cancellation, 'terminal' (non-blocking)

Draft: CE, EX, LC

Identity terms:
- CE:45 'source generation, monotonic interaction id and sequence, model revision, USER/MODEL/SYSTEM origin'.
- EX:48 generation and sequence; EX:107 'registration epoch and key'; EX:129-130 'receipt identity'.
- LC:53 'stable owner identity plus generation', LC:58 'transaction id... intended document revision', LC:120-124 'tree revision', LC:191 'snapshot revision'.
Cancellation terms:
- CE:54 ControlCancelReason; CE:69-76 registration cancellation; EX:49 requestCancel outcomes; EX:205-207 suspension 'cancel'; LC:74-80 transaction 'Canceled'; LC:207-209 CallbackCancellation.
The spelling 'Canceled' (LC:66,74,80) breaks the codebase convention: APP_POINTER_CANCELLED, BACKGROUND_JOB_CANCELLED, UI_RANGE_POINTER_CANCELLED, DIRECTORY_PICKER_CANCELLED and CallbackCancellation.
'Terminal' has four meanings: CE:84 terminal event; EX:129 terminal disposition; EX:116 terminal lane; LC:139-145 terminal fault.

**Recommendation:** Record a glossary.
Identifiers:
- `long long generation`: per live native owner (view, window, scene, publisher); fresh on reopen or recreate.
- `long long registrationEpoch`.
- `long long interaction` and `long long sequence`: per control, monotonic, explicit exhaustion, never wrap.
- Revisions are named by owner: modelRevision (control), rangeRevision (slider), documentRevision (application-supplied in close transactions), treeRevision (container), stateRevision (window and interaction snapshots).
- ControlOrigin {CONTROL_ORIGIN_USER, _MODEL, _SYSTEM}. Eligibility loss is SYSTEM even when caused by setEnabled, setVisible or detach. MODEL is value, option or range replacement.
Cancellation:
- Spell CANCELLED everywhere: WINDOW_CLOSE_CANCELLED, CONTROL_CANCEL_ELIGIBILITY_LOSS, and so on.
- Keep four cancellation types distinct and non-interchangeable: ControlCancelReason, WindowCloseState, PublishCancelOutcome, CallbackCancellation.
'Terminal':
- 'terminal event' = COMMIT/CANCEL.
- 'receipt disposition' = EX:129's list plus `ineligible`.
- 'control lane' replaces 'terminal lane/channel' for cleanup.
- 'faulted/quarantined' replaces 'terminal fault'.

### Receiver and interface spellings differ across drafts and from existing GUI conventions (non-blocking)

Draft: CE vs EX vs LC

Draft spellings:
- CE:290 uses `I*ControlEventHandler.invoke`.
- EX:48-50 uses `IUIWorkPublisher` and a receiver method `IUIWorkReceiver.deliver`.
- LC:50-53 names no handler types.
Existing receivers: IButtonAction.invoke (IButton.btrc:4), IApplicationWork.run, IViewPointerHandler.pointer, IWindowKeyHandler.key; IQueuedAction.deliver is provider-internal (ActionMailbox.btrc:7-10). The scope parameter is `owner` in IView.btrc:29-30, IWindow.btrc:29 and CE:57, but `scope` in IButton.btrc:48. GUI interfaces carry no 'UI' infix; `UI*` is Library.UI's prefix (UI/Element.btrc:17-60).

**Recommendation:** Record:
- New subscription receivers are `I<Owner><Event>Handler` with `void invoke(<Value>)`.
- Rename IUIWorkPublisher to IApplicationPublisher, and IUIWorkReceiver.deliver to IApplicationPublicationHandler.invoke.
- Name the LC handlers IWindowCloseRequestHandler, IWindowStateHandler and IViewInteractionStateHandler.
- The scope parameter is `CallbackScope owner` in every new subscription.
- Leave existing ids unrenamed.

### The lifecycle draft leaves the close-transaction, state-value and batch-result shapes to review; the record must supply them (non-blocking)

Draft: LC

LC:50-53: 'Exact value type names, handler signatures and error representation need review.' LC:146-148: 'CL-UIA-13 must choose the concrete result/error encoding, including this quarantine state.' LC:313-314 is review decision 1. LC:120 has applyBatch take an 'expected tree revision', but no getter for the current revision is proposed (LC:44-45). CX-UIA-21 must 'Apply ui2-approved.md exactly' (codex.md:3813).

**Recommendation:** Supply these in the record:
- IWindowCloseTransaction.{decide(WindowCloseDecision, long long documentRevision), completeSave(long long attempt, long long savedRevision, bool succeeded, string error), state()}, with WindowCloseState {OPEN, AWAITING_DECISION, SAVING, AUTHORIZED, CLOSING, CANCELLED, OWNER_LOST}.
- WindowCloseRequestOutcome {PENDING (with transaction), ALREADY_PENDING (same transaction), AUTHORIZED_NO_HANDLER, CLOSING, CLOSED}.
- IContainer.treeRevision().
- ContainerBatchResult {kind: COMMITTED | REJECTED | ROLLED_BACK | FAILED_CONSISTENT | FAILED_QUARANTINED, long long treeRevision, int failedStep, string error, Vector<IView> detached, Vector<IView> retained}.
- WindowState {logical width and height, backingScale, requestedVisible, nativeVisible, minimized, windowActive, ApplicationActivity, WindowExposure {EXPOSED, NOT_EXPOSED, UNKNOWN} plus a notExposed reason, drawableReady, stateRevision}.
- ViewInteractionState with the six LC:153-162 fields plus a `faulted` barrier.
The no-handler policy (LC:64-66) is approved as written.

### App-wide quit: requestQuit seals admission (EX), but LC needs a cancellable group decision first (non-blocking)

Draft: EX vs LC

EX:56: requestQuit 'starts the shared shutdown protocol'. EX:169-171: 'seal public ingress, cancel domain deliveries...'. LC:97-103: the coordinator 'collects authorizations from all windows... One cancellation leaves every not-yet-closed window usable.' Today requestQuit seals admission: post() throws after quit (LinuxApplication.btrc:122-127,134-139; MacOSApplication.btrc:122-130,144-151), so a Save that needs worker publication could not finish. Native quit enters through MacOSApplication.btrc:239-242 (applicationShouldTerminate -> requestQuit) and LinuxApplication.btrc:223 (SDL_EVENT_QUIT -> requestNativeClose on every window, then immediate close at :280).

**Recommendation:** Record:
- IApplication.requestQuit stays irreversible (EX side).
- Native quit routes through a provider-internal group coordinator first: applicationShouldTerminate keeps NSTerminateCancel, and SDL_EVENT_QUIT is handled the same way. The coordinator opens one transaction per window that has a handler (reason WINDOW_CLOSE_APPLICATION_QUIT). In group mode an AUTHORIZED transaction holds without closing until every window authorizes and revisions revalidate. The coordinator then calls requestQuit. Any CANCELLED leaves all windows open (LC:97-103).
- No new public id is needed. An app-initiated coordinated quit command belongs to UI3 (CX-UIA-24).
- UI2's E46 entry paths are native window close, native application quit and IWindow.requestClose, each with two windows. Back and tab navigation are UI3 (Stage 33 exit).

### UI1 condition 1: freeze attachHost provisionally. The executor draft has no portable host-adapter type and no turn-servicing entry (non-blocking)

Draft: EX

EX:54 'platform host adapter → attach outcome plus scoped registration'. EX:226-227: 'a main-loop wake schedules bounded work and returns to UIKit'; 'a coalesced Handler wake drains one bounded slice, then returns'. EX:229-233: 'Adapters expose host lifecycle transitions to the same executor state machine.' The host needs an entry that drains a slice, but none is defined. ui1-feasibility.md:29-31 asks for the freeze so CX-UIA-16/17 can run the journey 'without a private bridge'. ios.md:19-26 and android.md:23-28 assume it.

**Recommendation:** Provisionally freeze IApplication.attachHost(IApplicationHost host, CallbackScope owner) -> ApplicationHostAttachOutcome.
- IApplicationHost.requestTurn() -> bool is implemented by the platform shell (UIKit, Android Views or GameActivity, WinUI DispatcherQueue). It is callable from any thread, coalesced and never runs work inline.
- IApplicationHostAttachment, which extends ICallbackRegistration, provides serviceTurn() (one bounded fair turn per EX:186-199, on the application's UI executor thread) and transition(ApplicationActivity).
- Rules from EX:60-65: one attachment per application; attach fails on a running or closed application; run() rejects an attached one; detach seals ingress and drains before completing.
- Add GUI.attachHost. Errors in hosted mode surface through the attachment and requestQuit, because there is no run() to rethrow them.
- Mark the whole surface PROVISIONAL until CL-P2-22 and CL-UIA-22. A later change is a versioned contract change landed atomically with macOS and Linux (D27).

### UI1 condition 2: executor affinity wording and per-row provisional marking (non-blocking)

Draft: CE, EX, LC

Portable sources already say 'UI thread' or 'UI executor': IApplication.btrc:19-21, IButton.btrc:19, IView.btrc:20. Main-thread wording sits in the platform rows: EX:226 'Attach on the main thread', EX:227 'Activity and main Looper own entry', CE:314 'Main Looper delivery', LC:275 'main executor'. The drafts are provisional only at document level (CE:6, EX:7-9, LC:8-9). CallbackScope binds to its creating thread (Callback.btrc:389). android_main runs off the main thread under GameActivity (feasibility-linux.md:256).

**Recommendation:** Record the normative phrase 'the application's UI executor thread: the thread that called GUI.initialize, or the host thread that attached it'. It never means the process main thread. Platform rows state the mapping as a fact of that provider: UIKit and AppKit fix it to the main thread; Android Views to the main Looper; GameActivity to android_main's ALooper; Win32 or WinUI to the owning message or DispatcherQueue thread. Mark the Windows and Android rows of EX:225/227, CE:312/314 and LC:277/279 individually 'provisional pending CL-UIA-22 (Win32 vs WinUI, Views vs GameActivity)', so either outcome is a mapping change rather than a portable break.

### UI1 condition 3: SDL composition. Have CX-UIA-23 plumb SDL_EVENT_TEXT_EDITING rather than record an adaptation (non-blocking)

Draft: CE

The SDL flattening reads TEXT_INPUT only (SDL.h:69-73), and LinuxWindow.dispatch handles only SDL_EVENT_TEXT_INPUT (LinuxWindow.btrc:611-617). Yet the provider already activates SDL text input and positions the IME rectangle (LinuxWindow.btrc:548-560), so a real ibus or fcitx session would send TEXT_EDITING preedit that is currently ignored. Synthetic injection already uses SDL_PushEvent (SDL.h:216). CE:46 makes 'composing' part of TextControlEvent, and E01 (CE:333) and E39 (LC:299) need composition rows. feasibility-linux.md:165 and :268 ask for this decision.

**Recommendation:** Record the plumbing choice. CX-UIA-23 flattens SDL_EVENT_TEXT_EDITING (text, start, length) into LinuxTextField's preedit draft and the composing flag. It uses SDL_ClearComposition for eligibility-loss cancellation. Its provider-logic tests inject synthetic TEXT_EDITING through SDL_PushEvent. Linux composition rows stay implemented-unverified (not adapted, not passed) until an owner IME session (MAC-UIA-01/Q33 route). macOS stays provisional too: no marked-text evidence, and no NSTextField delegate or notification binding (feasibility-macos.md:115-123). CE review decision 1 is therefore provisional on both platforms.

### UI1 condition 4: add UI2 to E42's and E46's catalog milestone links (non-blocking)

Draft: LC

docs/design/native-ui-catalog/cases/E25-E47.toml:246-249 (E42 links N01/N02/N25/N48/UI1/UI5/UI9; owner text 'UI1/UI5/UI9'). :298-301 (E46 links .../UI1/UI3/UI5/UI7). native-ui-parity.md:916 and :1001 carry the same milestone lists. LC:43 and LC:41 assign E42 and E46 to UI2. CLAUDE.md Stage 32 exit lists E46. The loader accepts roadmap ids in links (test_ui0_catalog.py:1137-1139). cases/ is CX-UIA-30's shard; CX-UIA-21 owns only operations/ (codex.md:3799).

**Recommendation:** Record the E42 and E46 hunk: add 'UI2' to `links` and to the owner milestone text. It travels as a fragment hunk on cases/E25-E47.toml, carried by CX-UIA-21 per WORKSTREAMS §3.3 step 4 (as CX-STDLIB-01 does for E40), or the integrator applies it at CL-UIA-14. Update native-ui-parity.md:916 and :1001 in the same commit. Optionally add UI2 to E01–E04's links too (E01-E24.toml:27,40,53,66 name no milestone). Name the amendment file the loader must admit, for example amendments/cx-uia-21.toml (catalog README).

### setText's 'unchanged' comparison is ambiguous and the macOS provider compares against the live draft (non-blocking)

Draft: CE

CE:103-108 says an unchanged publication is a true no-op. CE:126: 'An identical published value does not terminate composition.' CE:143-146: changed setText is authoritative replacement. MacOSTextField.btrc:71-75 compares against text(), and text() calls validateEditing (:63-67). If 'unchanged' meant equal to the live draft including marked text, every model republish during an edit would cancel it, and E01's 'republish unchanged text while... composition... active' (CE:333) could not pass.

**Recommendation:** Record: 'unchanged' means equal to the control's accepted baseline (model value), not the live draft. Providers compare without validating or committing the editor. List ITextField.text as a changed id: it returns the live draft, and reading it never validates, commits or disturbs composition.

### The keyed select model duplicates Library.UI's UISelectOption/UISelect with different spellings and incompatible limits (non-blocking)

Draft: CE

UI/Element.btrc:563-581 defines UISelectOption(value, label, enabled). UI/Element.btrc:583-632 defines UISelect, whose valid() requires 1..128 options and a nonempty selected value (:622, :630). CE:47-48 proposes SelectOption key/title/enabled and SelectModel with nullable selection, EMPTY and 10,000 options (E33, CE:336). CE:14-15 claims reuse of 'the existing UI vocabulary'. The UI4 pre-draft already extends SelectModel's key/title (native-ui-contracts/ui4-controls.md:300-306).

**Recommendation:** Record: keep CE's GUI SelectOption/SelectModel with key/title, because UI4 depends on them and UISelect's limits contradict E33. Document the adapter mapping value->key and label->title for Library.UI and BTRSmith. Do not route GUI through UISelect.

### Reusing UIRangeAdjustment adds a GUI -> Library.UI import edge (non-blocking)

Draft: CE

CE:51 and CE:215-219 reuse UIRangeAdjustment and UISemanticRange (UI/Element.btrc:52-60,62-123). No GUI source imports Library.UI today (grep). UI imports only UI.* (UI/Element.btrc:14-15; Render.btrc:16-19), so the edge creates no cycle.

**Recommendation:** Accept the edge. ControlEvents.btrc imports Library.UI.Element. Typed GUI payloads do not embed UIEventKind; the Library.UI adapter maps phases to UIEventKind per the CE:262-268 table.

### Slider factory compatibility (CE decision 5): the factories reject ranges that setRange would accept (non-blocking)

Draft: CE

The factories reject `maximum <= minimum` and `intervals > 1000` (MacOSSlider.btrc:18, LinuxSlider.btrc:21). CE:196-205 makes equal endpoints a valid inert range and removes the 1,000 cap. macOS couples logical steps to tick marks (MacOSSlider.btrc:28-29 setNumberOfTickMarks/allowsTickMarkValuesOnly; :71 closestTickMarkValueToValue). Linux draws ticks only for <=64 intervals (LinuxSlider.btrc:58). Factory ids: IApplication.createSlider (IApplication.btrc:43), GUI.createSlider (GUI.btrc:68).

**Recommendation:** Keep both factory signatures. Widen their validity to setRange's: equal endpoints are inert, and any interval count is allowed. intervals>0 maps to step = span/intervals; 0 means continuous. Visible ticks are provider-chosen and decoupled from steps, so macOS must snap in the provider (ties toward the higher value, CE:199-201) instead of using tick-mark snapping. List both as changed ids. Approve CE's pointer bound: at most half a logical step plus propagated projection error, measured and recorded per provider. Keyboard and accessibility paths stay exact long long. No integer slider interface in UI2.

### E-case scope differs between the drafts, the Stage 32 exit and the landing packets (non-blocking)

Draft: CE, EX, LC

The drafts add E24, E30 (EX:247-248), E33, E34 (CE:336-337) and E42 (LC:300). The Stage 32 exit (CLAUDE.md Stage 32; claude.md:6229) and CX-UIA-21 fixtures (codex.md:3815) cover only E01–E04, E29, E31, E35, E39, E40 and E46. CX-UIA-22 acceptance (codex.md:3866) omits E40 (feasibility-macos.md:148-152). CX-UIA-23 acceptance (codex.md:3920) omits E31. CE itself says E33 and E34 are not closed by UI2 (CE:336-337), and desktop has no suspension for E30.

**Recommendation:** Record a scope table.
- Required at CL-UIA-14 on macOS and Linux X11, both frontends, plain and sanitized: E01–E04, E29, E31, E35, E39, E40 and E46.
- Add E40 to CX-UIA-22, with macOS bursts including popup tracking, slider drag, live resize and a sheet. Add E31 to CX-UIA-23.
- UI2 contributions recorded partial (implemented-unverified), not closed: E24 (saturation and terminal survival), E30 (monotonic deadline and wall-clock rows only; suspension rows adapted on desktop and owned by Stage 35 or CL-UIA-22), E33/E34 (model and event subset), E42 (window-state subset; hosted timings are diagnostic, LC:302-304).
- Wayland halves wait for the libdecor fix (ui1-feasibility.md:17).

### The IView and IContainer additions reach files no UI2 packet owns, and some are held by CX-STDLIB units (non-blocking)

Draft: LC

btrc interfaces need explicit implementations. Every macOS view class implements IView by delegation (15 classes, grep `implements .*IMacOSView`), but CX-UIA-22 owns only 7 of them (codex.md:3844). It is missing MacOSButton, MacOSGPUView, MacOSGrid, MacOSLabel, MacOSLevelIndicator, MacOSPanel, MacOSProgressIndicator and MacOSStack. On Linux the IView additions fit LinuxNodeView (LinuxView.btrc:359, owned), but the IContainer additions need LinuxContainerView (LinuxContainer.btrc:31) and LinuxStack's relayout override (LinuxStack.btrc:90-92), which CX-UIA-23 does not own (codex.md:3894). Holds: LinuxStack by CX-STDLIB-02 (CODEX.md:78); MacOSButton by CX-STDLIB-03 (CODEX.md:86); LinuxApplication, Window, TextField and Select by CX-STDLIB-01; LinuxScrollView by CX-STDLIB-05 (codex.md:3881). The test fixture ForeignView implements IView (src/tests/native/gui/NativeGUI.btrc:198).

**Recommendation:** Record the widened owned paths: CX-UIA-22 takes all macOS IView implementers; CX-UIA-23 takes LinuxContainer, LinuxStack and LinuxPanel; CX-UIA-21 takes NativeGUI.btrc. Sequence the UI2 landing after CX-STDLIB-01/02/03/05 integrate (D28). Alternatively, the record can narrow IView additions so they land on a provider base class, but macOS has none.

### The executor's publisher payload and worker handle cannot be frozen from the draft; freeze an identity-only payload provisionally (non-blocking)

Draft: EX

EX:41-42: 'The payload/writer ABI needs the ownership review below before signatures freeze.' EX:71-75: 'checked handle whose lifetime is independent of UI-object ARC... No new compiler transfer semantics are assumed.' EX:79-81: 'a small identity notification wakes the owner to retrieve them'. EX:279-283 sets out the REQUEST path. Existing cross-thread pattern: BackgroundJobs shares managed objects whose cross-thread state is atomic (BackgroundJobExecutor.btrc:65-73 BackgroundJobCancellation with Atomic<bool>). Its outcome vocabulary (QUEUE_FULL, CANCEL_STALE, ALREADY_TERMINAL; :14-30) matches EX:104-110.

**Recommendation:** Provisionally freeze tryPublish with a fixed plain-data payload (`long long payload`), plus generation, sequence, suspension and replacementKey. A bounded byte payload is a later versioned addition. createPublisher drops 'maximum payload bytes' until then. Spell outcomes in the BackgroundJobs style (enum plus outcome class, no throws). The parity reviewer must confirm that both compilers can express a worker-held publisher whose refcount the worker never touches. If they cannot, file REQUEST(CL-REQ) per EX:279-283 and gate E04's worker rows on it.

### Error representation: three styles; the record needs one rule (non-blocking)

Draft: CE, EX, LC

Existing setters throw strings ('Invalid native slider range', MacOSSlider.btrc:18; 'Application work capacity exceeded', LinuxApplication.btrc:140). EX uses outcome objects for new operations (EX:47-58, 104-110) and keeps exceptions for post (EX:51). LC uses CallbackCancellation statuses and asks to reconcile thrown teardown errors (LC:224-230, LC:319). CE's 'reject' (CE:153-156, 189-198, 242) leaves the mechanism unstated. The UI4 pre-draft returns ControlApplyResult (ui4-controls.md:110, 252).

**Recommendation:** Record:
- Programmer errors throw a string, as today: invalid or nonfinite arguments, wrong thread, closed or foreign owner, a second live handler.
- Expected runtime conditions return typed outcomes: capacity, stale, closed during a race, native mutation failure, transaction results.
- close and pollClose report teardown progress only as CallbackCancellation. A native teardown failure returns FAILED or RETRYABLE_FAILURE, keeps ownership, and records its diagnostic under the existing run() failure policy instead of throwing from pollClose.
- A throwing receiver follows the existing work-error policy: recorded, orderly quit, rethrown by run() (GUI/README.md:39-41).
- Flag the ControlApplyResult divergence to CL-UIB-02.

### The GUI facade mirrors are missing for the new IApplication operations (non-blocking)

Draft: EX

GUI.btrc:82-102 mirrors every IApplication scheduling and lifecycle op (post, postAfter, requestQuit, run, close). The catalog has GUI.post, GUI.postAfter, GUI.run, GUI.requestQuit and GUI.close (operations/GUI.toml). EX:45-58 adds createPublisher, schedule and attachHost to IApplication only. CX-UIA-21 owns GUI.btrc (codex.md:3795).

**Recommendation:** Add GUI.createPublisher, GUI.schedule and GUI.attachHost to ui2-approved.md, each with GUIProvider.requireUIThread except where the draft says worker-safe.

### BackgroundJobExecutor.subscribeCompletionReady is not a UI catalog operation (non-blocking)

Draft: EX

EX:58 lists it as a proposed catalog id. The catalog README limits operations/ to GUI owner files (native-ui-catalog/README.md table), and BackgroundJobs is not among them. CX-UIA-21 owns only its 'completion hook' (codex.md:3797).

**Recommendation:** List it in ui2-approved.md as a non-catalog stdlib change with its own BackgroundJobs regression test. Keep EX's nonblocking stop or drain constraint (EX:174-177, 284-287): the UI close budget is not advertised until that adapter exists.

### macOS run-loop modes and the wake signal: worker publication needs a new wake, and timers must not stall during tracking (non-blocking)

Draft: EX

MacOSRunLoopSignal.wake requires the main thread (MacOSRunLoop.btrc:19,30-35), so it cannot serve a worker. postAfter uses NSTimer.scheduledTimerWithTimeInterval (MacOSApplication.btrc:392), which runs in the default mode only and stalls during menu or slider tracking, live resize and runModal (feasibility-macos.md:101-105). EX:223 requires 'common/modal loop-mode behavior and no recursive dispatch'. CX-UIA-22 step 3 names CFRunLoopSource or performBlock (codex.md:3861).

**Recommendation:** Record that on macOS the publisher wake and the postAfter/schedule timers register in kCFRunLoopCommonModes, so they also run during event tracking and modal panels. Semantic receivers delivered during tracking must not re-enter tracking or start a nested loop. The E40 and E24 macOS trials include an open popup, a slider drag, live resize and a sheet (not runModal, LC:93-94).

### Cleanup lease and E31 final-release policy: defer the lease and keep today's rule (non-blocking)

Draft: EX, LC

LC:232-248 and EX:179-182 propose a pre-reserved executor cleanup lease and both call it unproven. Destructors are fatal today if close has not completed (MacOSWindow.btrc:328, MacOSApplication.btrc:484, LinuxScrollView.btrc:110). LC:297 adds a 'worker last release' row to E31. The UI1 E31 oracle counts survivors after a 200 ms probe drain (ui1-feasibility.md:66-68).

**Recommendation:** Record:
- The cleanup lease is not part of the frozen UI2 surface. Callers must complete close and drain before the final release (LC:246-248). A final release of an open owner off the UI executor keeps its fatal diagnostic, and E31 asserts that declared policy.
- Any lease work goes through REQUEST(CL-REQ).
- E31 COMPLETE means native resources and registrations are released at the moment COMPLETE is returned.
- Name and bound the one allowed AppKit deferred-deallocation survivor class (autorelease or Core Animation) in the evidence.

### Suspension and activity state are described twice (non-blocking)

Draft: EX vs LC

EX:55 calls suspended 'a separate lifecycle state'. EX:202-213 sets per-scene suspension policies. LC:188-189 has IWindow.state carry 'window activation, application activity'. Neither defines the state's source or its enum. Desktop providers have no suspension.

**Recommendation:** Record one ApplicationActivity enum {ACTIVE, INACTIVE, BACKGROUND, SUSPENDED}. It is reported by the host link (IApplicationHostAttachment.transition) on mobile and by the provider on desktop (never SUSPENDED there). It feeds both the executor's suspension policies and WindowState. Window activation stays a separate per-window boolean.

### Initial-state handshake for observations: CE forbids replay, LC leaves it open (non-blocking)

Draft: CE vs LC

CE:67 'No subscription replays an initial action; initialize from getters.' CE:247-248 'Subscribe first, read the initial state, and accept later snapshots by sequence.' LC:193-194 'must have a documented revision handshake or initial delivery'.

**Recommendation:** Record: no initial delivery for any subscription. Each state observation (scroll offset, WindowState, ViewInteractionState) carries its revision. The client subscribes, reads the getter, and ignores queued snapshots with revision <= the one it read. State observations are replaceable keyed records (finding 4).

## Compiler gaps

- None confirmed. The reference compiler transpiled a probe (the review workspace (not retained) reconciler/KeyedSelectProbe.btrc) with an interface returning and accepting `string?`, enum-typed public fields in payload classes and a typed `invoke` receiver. Selfhost parity was not checked; that is the parity reviewer's job.
- Potential, not confirmed: a worker-held IApplicationPublisher (EX's 'native writer lease', ui2-executor.md:69-75) must not touch ARC counts from the worker. If both compilers cannot express a handle whose refcount only the UI executor thread changes (BackgroundJobs' shared-slot precedent, BackgroundJobExecutor.btrc:65-73), file REQUEST(CL-REQ) with a two-frontend reproduction per ui2-executor.md:279-283 before freezing E04's worker rows.
- Deferred, not frozen: the lifecycle cleanup lease (ui2-lifecycle.md:232-248) may need ownership or cycle-collector support. It is out of the UI2 surface; any implementation goes through REQUEST(CL-REQ).
