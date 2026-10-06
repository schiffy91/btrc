# CL-UIA-13 UI2 contract review: Feasibility review 1: macOS AppKit and Linux SDL

Reviewed read-only on main `f6c2f2ae` (2026-10-06) by an integrator review workflow (`wf_b7573fea-5df`). Verdict: **fix-first**. Every finding raised as blocking was adversarially verified; none was confirmed, and each is closed by a decision in [ui2-approved.md](../../ui2-approved.md).

## Summary

Feasibility reviewer 1 (macOS AppKit and Linux SDL), read-only on main f6c2f2ae, tree clean. Verdict: fix-first. I found 4 blocking and 14 non-blocking findings.

Most of the three drafts can be built on the real providers.
- The value types and typed receivers compile. A probe at the review workspace (not retained) feas1/ControlEventsProbe.btrc exercised nullable string keys, enum origins, typed invoke receivers and interface methods returning ICallbackRegistration. It compiled with the Python compiler and ran.
- Setter suppression, keyed selection, two-axis scroll and the close veto are provider-local work on both platforms:
  - macOS: windowShouldClose already has a bool return, and setStringValue, selectItemAtIndex and setDoubleValue send no action.
  - Linux: SDL only reports a close request.
- The rest of the surface is feasible on both: ordered mutation, IWindow.state, retained image presentation and worker wake (Linux uses SDL_PushEvent).

The blockers:
- B1 (condition 1): IApplication.attachHost has no adapter interface, outcome type, reference-provider meaning or fixture, so it cannot be frozen even provisionally. The adapter must cover both a push host (the mobile Handler or main queue) and a pull host (SDL, which cannot be woken by a foreign wait). E30 suspension has no desktop source unless the adapter injects lifecycle transitions.
- B2 (AppKit nested tracking loops): every macOS wake is default-mode only, and NSPopUpButton and NSSlider tracking, live resize and runModal run in other modes. The fixtures change a popup while open, hide or disable during a drag or open popup, and keep service gaps of 250 ms or less. These cannot all hold together with "queued receivers run after the native callback unwinds". The UI1 checkpoint routed this decision here, and the drafts do not make it.
- B3 (known conflict 1): the executor's "refuse to begin the interaction" when terminal capacity is unavailable cannot be implemented on AppKit. Native and accessibility-initiated interactions start inside AppKit, where no provider hook sees them. Reserving per registration and channel at subscribe time is a feasible replacement.
- B4 (condition 3): Linux has no preedit and no undo, and both are scheduled in UI3's CX-UIA-27. Stage 32 and CX-UIA-23 still require E01 on Linux, and the E01 fixture asserts that composition and undo are preserved.

UI1 conditions:
1. Not satisfiable as written (B1).
2. Satisfied. No portable rule says "main thread". All three drafts mark the Windows, iOS and Android rows provisional. The Android rows still say "main Looper", which is acceptable as a provisional mapping.
3. Not decided, and in effect contradicted by the packet schedule (B4).
4. Satisfiable. The drafts do not conflict with adding UI2 to the links for E42 (cases/E25-E47.toml:248) and E46 (:300). E42, however, is not in the Stage 32 exit or in the CX-UIA-22/23 acceptance (N6).

I did not repeat the carried UI1 gaps: hosted-macOS activation and keyboard, Wayland libdecor, no AT-SPI bridge, synthetic-only Linux input.

## Decisions proposed

- I classified a missing type or semantics that stops CX-UIA-21 from writing or freezing an operation as blocking. That is B1: condition 1 explicitly demands a provisional freeze.
- I classified the AppKit tracking-mode issue (B2) as blocking. The UI1 checkpoint routed the decision to CL-UIA-13, and parity E02 requires reordering "while open". Default-mode delivery cannot meet that, and common-mode delivery contradicts the drafts' "after native callback unwinds" wording unless the wording is redefined.
- B3 targets the executor's literal "refuse to begin the interaction" rule, which AppKit cannot implement for interactions initiated natively or through accessibility. The control-events "provider option" wording is feasible. I gave a reconciliation that works on both providers (reservation per registration and channel at subscribe time, plus coalesced step counts).
- I made condition 3 blocking (B4) because Stage 32 and CX-UIA-23 require E01 on Linux while the Linux preedit and undo work sits in UI3's CX-UIA-27 (codex.md:4093). The fix is a one-line decision in ui2-approved.md.
- Fault injection (N4) is non-blocking. Probe-owned injection is feasible: Objective-C exceptions are translated by the call adapter, and the Linux GPU and SDL allocations can be interposed.
- I did not re-raise the carried UI1 gaps: hosted-macOS activation and keyboard delivery, the Wayland libdecor hang, the missing AT-SPI bridge, and synthetic-only Linux input. Where they bear on a finding, I cite them as context.
- Condition 2 is judged satisfied. No portable rule names the process main thread, and each draft marks the Windows, iOS and Android rows provisional (control-events:6, executor:7-8, lifecycle:8-9).
- Condition 4 is judged satisfiable. It is a catalog edit in CX-UIA-21's reviewed amendment, and no draft contradicts it.
- Rule slip: I ran the compiler probe once with a `cd <repo> &&` prefix, which the review rules forbid. The probe wrote only into my scratchpad, and `git status` afterwards shows the tree clean at f6c2f2ae.

## Findings

### B1. IApplication.attachHost cannot be frozen: its adapter, outcome, reference-provider semantics and fixture are undefined (UI1 condition 1) (blocking)

Draft: ui2-executor.md

**What the draft gives.**
- ui2-executor.md:54 gives only `UI thread: platform host adapter → attach outcome plus scoped registration`. Neither type is defined.
- :60-65 states rules only.
- No fixture in :244-249 exercises attachHost. The shell journey is program-owned: main → GUI.initialize → GUI.run (UI1 Linux review finding 11, NativeShell.btrc:153-194).

**Reference-provider facts.**
- Linux SDL owns the only blocking wait: pumpOnce → pumpEvents → btrcSdlWaitEvent (LinuxApplication.btrc:217-231, 292-302).
- SDL exposes the display connection (SDL_PROP_WINDOW_X11_DISPLAY_POINTER is bound) but not its own event-queue wakeup. A foreign host waiting on its own fds therefore cannot see btrcSdlPushWake (SDL.h:92-97) without polling, and executor:124-125 forbids polling as the success path.
- So Linux needs a pull-style host that calls into the provider's wait or turn. The mobile rows (executor:226-227) are push-style: a Handler or main-queue wake drains one slice and returns.
- macOS delivery already rides the main CFRunLoop (MacOSApplication.btrc:381, 392; MacOSRunLoop.btrc:30-35), so attaching under a foreign [NSApp run] is feasible. But the constructor installs its own NSApplication delegate and activation policy (MacOSApplication.btrc:326-330), which a host-owned NSApp would own.

**Effect on E30.**
- E30's suspend, resume and recreate (executor:205-217, 248) has no OS source on either desktop provider. Only a host adapter that injects lifecycle transitions can make E30 provable on macOS and Linux.
- ios.md:25 defers the GUI.run compatibility decision to UI2. The drafts never say what run() does on a host-attached platform.

**Recommendation:** Freeze a provisional shape in ui2-approved.md, along these lines:
- `interface IUIHost { void requestTurn(); void scheduleTurn(unsigned long long monotonicDeadlineNs); }`. requestTurn must be thread-safe and coalesced.
- `IApplication.attachHost(IUIHost host, CallbackScope owner) -> ICallbackRegistration`.
- `IApplication.serviceTurn(...)`, which returns the next deadline. A pull host may call it with a blocking timeout; a push host calls it with zero.
- `IApplication.hostLifecycle(UIHostState)` (active, inactive, suspended, terminating).
- Desktop run() = attaching the provider's built-in host (SDL wait on Linux, CFRunLoop on macOS) plus running it.

Also:
- Require the macOS attach path not to replace a host-owned NSApplication delegate.
- Add a host-attached shell-journey fixture on macOS and Linux, driven by a test host. It injects suspend and resume so that E30's cancel, defer and replace policies are provable on the reference providers before CX-UIA-16/17 consume it.

**Adversarial verification:** not a blocker; closed in the approved record. Most of the facts in the finding check out. It does not block approval, though, because the gap can be closed in Claude's own approved record as a provisional row plus carried gaps.

What holds:
- ui2-executor.md:54 names `attachHost` with an undefined "platform host adapter" and an undefined "attach outcome".
- No fixture at :244-249 exercises attachHost.
- NativeShell.btrc:153-194 is program-owned: main, GUI.initialize, GUI.run.
- On Linux the only blocking wait is pumpOnce → pumpEvents → SDL_WaitEventTimeout (LinuxApplication.btrc:217-231, 292-302). btrcSdlPushWake is an SDL_PushEvent of a user event (SDL.h:92-97).
- The MacOSApplication constructor calls setDelegate, setActivationPolicy and finishLaunching (MacOSApplication.btrc:315-331).
- ios.md:25-26 defers the GUI.run compatibility decision to UI2.

Why this is not a blocker that needs a Codex draft revision:

1. **The drafts do not freeze signatures; the approved record does, and Claude writes it.**
   - executor:40-41 says its rows are "not declarations to copy into production" and that the ABI is reviewed "before signatures freeze".
   - The lifecycle draft's CL-UIA-13 decisions (:311) tell CL-UIA-13 to "Freeze the transaction value/handler/result shape".
   - executor:267-269 tells CL-UIA-13 to "approve or revise operation names … loop-mode rules".
   - CL-UIA-13 step 4 has Claude write ui2-approved.md, the frozen interface diff. CX-UIA-21 step 1 then applies ui2-approved.md exactly.
   - So defining the adapter type is the approved record's job, and the finding's own recommendation is to "Freeze a provisional shape in ui2-approved.md".

2. **The UI1 condition already expects this.** Condition 1 (ui1-feasibility.md:29-31) is an action assigned to CL-UIA-13, and it says "at least provisionally". D27 already makes UI2 approval provisional for Windows, iOS and Android until CL-UIA-22, and CL-P2-22 and CL-UIA-22 remain the real checks (ui1-feasibility.md:21-25). A provisional attachHost row is exactly the resolution the condition allows.

3. **The semantics the finding calls undefined are partly in the draft.**
   - :60-62 says run rejects an already host-attached application, and attach rejects a running or closed one.
   - :226 says a UIKit delegate never calls GUI.run.
   - The push-wake, bounded-turn model is stated at :186 ("each native-loop turn services bounded slices") and :225-227 ("bounded executor turn"; "drains one bounded slice, then returns").
   - Choosing pull versus push, or adding a serviceTurn operation, is a choice within these stated rules that the approved record can make.

4. **The Linux foreign-host problem is not a UI2 requirement.** The draft maps Linux to its own SDL loop (:224), and a GLib main-context adapter replaces it only if D23 picks GTK4. UI2 needs no foreign host on Linux. The "pull host" is the finding's own proposal.

5. **E30 is not part of Stage 32's exit.** CLAUDE.md Stage 32 requires E01–E04, E29, E31, E35, E39, E40 and E46 only. Desktop E30 provability is therefore a carried row, with the test-host injection the finding suggests as one option. The approved record can also state the macOS rule (attach must not replace a host-owned NSApplication delegate) and can require CX-UIA-21/22/23 to add a host-attached fixture. That is a directive in Claude's file, not a draft defect.

Recommended disposition: in ui2-approved.md, freeze a provisional attachHost adapter shape. Record the following as carried gaps:
- no reference-provider host-attached evidence until a test host or CX-UIA-16/17 exists;
- desktop E30 suspension sources;
- the macOS delegate constraint.

### B2. AppKit nested tracking and modal loops: the drafts' delivery rules, the while-open and during-drag fixtures, and the E40 budgets contradict each other on macOS (blocking)

Draft: all three (ui2-executor.md, ui2-control-events.md, ui2-lifecycle.md)

**macOS wakes are default-mode only.**
- The action and window wake is NSNotificationQueue `enqueueNotification:postingStyle:` with NSPostASAP (MacOSRunLoop.btrc:16, 34), which posts in NSDefaultRunLoopMode only.
- postAfter and the shutdown tick use `+[NSTimer scheduledTimerWithTimeInterval:repeats:block:]` (MacOSApplication.btrc:160, 392), also default mode.
- NSPopUpButton menus, NSSlider and NSScroller drags and live resize run AppKit-owned loops in NSEventTrackingRunLoopMode. runModal (showAlert, MacOSWindow.btrc:268-276; NSOpenPanel) runs NSModalPanelRunLoopMode.

**What the drafts require.**
- Queued receivers run "after native dispatch" or "after their native callback unwinds" (control-events:88-89; executor:139-142).
- E02: "reorder and relabel while open; disable/remove candidate" (control-events:334, rules at :168-175).
- E33: refresh while open (:336).
- E39: "disable a form while a popup ... is pending" and "hide a captured slider before release" (lifecycle:299).
- E03: eligibility loss during a drag (control-events:335).
- E40: maximum service gap of 250 ms or less, and close begins within 250 ms (executor:251-258).

**The conflict.**
- With default-mode delivery, no application code can run while a popup or drag is tracking. The while-open and during-drag rows cannot be driven through the portable API, and the gap budget fails during tracking.
- With common-mode delivery, application code runs inside AppKit's mouseDown or menu-tracking stack. That contradicts "after the native callback unwinds" unless the phrase is redefined, and it needs a reentrancy rule. NSMenu has cancelTracking; NSSlider has no public cancel.

**Quit.** MacOSApplication.btrc:239-242 returns NSTerminateCancel, which also cancels a system logout or restart. NSTerminateLater, the async-correct answer, runs NSModalPanelRunLoopMode until the reply, so it works only with modal-mode delivery. Modal-mode delivery also runs queued work inside the callers of showAlert and chooseDirectory.

The UI1 checkpoint sent this decision to CL-UIA-13 (ui1-feasibility.md:63-65; reviews/ui1/feasibility-macos.md:101-105). The executor's macOS row only lists it as proof to collect (executor:223).

**Recommendation:** Record the choice in ui2-approved.md:
- **Wake and timers.** On macOS, schedule the wake source and timers in NSRunLoopCommonModes, at least default plus NSEventTrackingRunLoopMode. Use NSRunLoop addTimer:forMode: or a CFRunLoopSource, through binding fragments.
- **Wording.** Redefine "after native dispatch" as "after the native callback that produced the snapshot returns; delivery may occur inside a platform-owned tracking loop".
- **Reentrancy rule.** A model change, eligibility loss or close that targets a control under active native tracking ends that tracking and emits exactly one MODEL or SYSTEM cancel. Use NSMenu cancelTracking for popups. For sliders, see N1.
- **Legacy APIs.** Classify showAlert and chooseDirectory as legacy nested-loop APIs (N10).
- **Quit.** Choose between NSTerminateCancel (record that logout is not continued as an adaptation) and NSTerminateLater (requires modal-mode delivery).
- **Trials.** Add macOS E40/E24 trials with an open popup, a slider drag and a sheet.

**Adversarial verification:** not a blocker; closed in the approved record. Most of the finding's facts are correct, but the problem does not block approval. The approved record can settle it by choosing among the drafts' own options and recording adaptations and carried gaps, which is the remedy the reviewer proposes ("Record the choice in ui2-approved.md").

**Verified against the sources (main f6c2f2ae):**
- MacOSRunLoop.btrc:16,34 wakes through `NSNotificationQueue enqueueNotification:postingStyle:` with NSPostASAP. That call posts only in the default mode. MacOSActionQueue and MacOSWindowEvents both wake through this signal.
- postAfter (MacOSApplication.btrc:392) and the shutdown tick (:160) use `+[NSTimer scheduledTimerWithTimeInterval:repeats:block:]` (GUI/btrc.toml:442), which is also default mode only.
- showAlert calls `runModal` (MacOSWindow.btrc:275), and so does MacOSDirectoryPicker.btrc:41.
- `applicationShouldTerminate` returns NSTerminateCancel (MacOSApplication.btrc:239-242).

**One overstatement.** The claim that macOS wakes are default-mode only is too broad. `IApplication.post` uses `-[NSRunLoop performBlock:]` (MacOSApplication.btrc:381; btrc.toml:441). As I understand it, that call schedules work in the common modes. So the provider already has a common-mode delivery path.

**Why this does not block:**

1. **The loop mode is already CL-UIA-13's decision.**
   - The executor draft lists "termination and loop-mode rules" among the CL-UIA-13 decisions (ui2-executor.md:267-270).
   - Its macOS row names the candidates as "a main-run-loop source or main-queue wake" and the required proof as "common/modal loop-mode behavior and no recursive dispatch" (:223). Both candidates allow common-mode scheduling.
   - The UI1 checkpoint already records run-loop modes as a carried gap (ui1-feasibility.md:63-65). The macOS review rated it non-blocking: "decide on common-mode timers or run-loop sources" (feasibility-macos.md:101-105).
   - Choosing default plus NSEventTrackingRunLoopMode delivery means choosing an option the drafts already offer. It needs binding fragments only (addTimer:forMode:, performInModes:, or the forModes: queue variant), not a compiler change.

2. **The drafts' wording does not contradict common-mode delivery.**
   - The executor says queued notifications "run after their native callback unwinds" (:139-142). Delivery on a later iteration of a tracking loop happens after the target/action callback that produced the snapshot has returned.
   - The text's purpose is to forbid inline or re-entrant delivery (control-events:88-92). At most the record adds a clarifying sentence.

3. **The re-entrancy semantics are already in the drafts.**
   - If a refresh removes the active candidate, or a popup cannot survive it, the popup closes with one MODEL cancel (control-events:173-175).
   - A changed range during a drag cancels the drag, and a delayed pointer-up from the abandoned interaction is ignored (:211-213).
   - Eligibility loss cancels capture and dismisses popups with a SYSTEM cancel (lifecycle:164-169).
   - Mechanisms such as NSMenu cancelTracking, or a slider mechanism, are provider mapping details for CX-UIA-22. Popup survivability is the drafts' own review decision 3 (control-events:354-355).

4. **The modal and legacy APIs fit the drafts as written.**
   - The lifecycle draft already forbids nested modal loops on the decision path (:93-94).
   - The E40 load excludes blocking handlers (executor:251-262).
   - The Windows row already says nested modal loops must not re-enter semantic delivery (:225).
   - So excluding the modal-panel mode, and calling showAlert and chooseDirectory legacy nested-loop APIs, is consistent with the drafts. Choosing it is a classification in the record.

5. **Quit is a record-level choice.** The UI1 macOS review endorsed NSTerminateCancel plus a quit request as "the shape ui2-lifecycle.md:90-95 asks for". Not continuing a logout can be recorded as a macOS adaptation. NSTerminateLater would be the alternative.

6. **The trials can go into CX-UIA-22's acceptance from the record.** UI1 already recommended E40 and E24 runs with an open popup, a slider drag and a sheet.

Codex does not need to revise any draft. Every recommendation in the finding fits in ui2-approved.md as a choice, a clarification, an adaptation or a carried gap.

### B3. Known conflict 1: the executor's rule to refuse to begin an interaction without reserved terminal capacity cannot be implemented on AppKit (blocking)

Draft: ui2-executor.md (vs ui2-control-events.md)

**The two texts.**
- executor:112-117: "Each in-progress edit/gesture needs its own pre-reserved commit/cancel capacity; when it cannot be reserved, refuse to begin the interaction".
- control-events:98-101 makes reservation a provider option.

**Why macOS cannot refuse.** macOS interactions begin inside AppKit:
- NSSlider tracking starts in mouseDown.
- A field-editor session starts on a first-responder change.
- NSPopUpButton opens on a click or on AXPress.
- Accessibility actions (AXPress, AXIncrement, setting AXValue) never pass through the local event monitors the provider uses (MacOSViewInput.btrc:54; MacOSWindow.btrc:255). The provider has no point at which it can refuse.

**Backpressure.** macOS also cannot push back on AppKit dispatch. Linux can, by not polling SDL.

**Today's overflow behavior.** Both providers' ActionMailbox overflow is latched and fatal: "capacity exceeded; close this action queue" (ActionMailbox.btrc:35, 55-59). Relative adjustments must be lossless (control-events:85), but UIRangeAdjustment is a single-step enum with no count (UI/Element.btrc:52-60), so key repeat while delivery is stalled needs one slot per step.

**Recommendation:** Resolve conflict 1 as follows:
- **Reservation.** Reserve terminal capacity per registration × event channel at subscribe time. A control channel has at most one active interaction, so this equals per-interaction reservation without refusing a native start. A subscription fails explicitly when capacity is unavailable.
- **Relative adjustments.** Coalesce consecutive adjustments of one control into one ordered record that carries a signed small-step count, a large-step count and the endpoint flags, by adding a count field to SliderControlEvent. This avoids one slot per key repeat.
- **Overflow.** Replace the latched-fatal mailbox overflow with the explicit pressure path.
- **Linux.** Linux may additionally yield its SDL source.

**Adversarial verification:** not a blocker; closed in the approved record. The finding is partly true, but it does not block approval. It describes known conflict 1, which docs/design/ui-contracts/index.md:15-18 already assigns to CL-UIA-13. The drafts already offer enough options for the approved record to settle it.

**What checks out.**
- ui2-executor.md:112-117 does say "refuse to begin the interaction". ui2-control-events.md:98-101 does make reservation "a provider option for the executor review".
- control-events:85 requires lossless relative adjustments. UIRangeAdjustment (UI/Element.btrc:52-60) is a single-step enum with no count.
- Both providers build on ActionMailbox, whose overflow latches and then throws "capacity exceeded; close this action queue" (ActionMailbox.btrc:35, 56-59, used by MacOSActionQueue.btrc:77 and LinuxActionQueue.btrc:67).
- Accessibility actions such as AXIncrement, AXPress and setting AXValue do not pass through NSEvent local monitors, and no NSSlider, NSPopUpButton or accessibility hook is bound in GUI/btrc.toml. A macOS provider therefore cannot refuse an accessibility-initiated adjustment or popup open.

**What is overstated.** "The provider has no point at which it can refuse" is false for pointer and keyboard starts.
- The provider already installs local NSEvent monitors that run before AppKit's sendEvent dispatch and can swallow the event by returning null: MacOSViewInput.invoke returns null to consume, and MacOSWindow.onKey monitors keyDown.
- Mouse-down events that would start NSSlider tracking or open an NSPopUpButton reach those monitors before tracking begins.
- For text, AppKit's control:textShouldBeginEditing: delegate method could be bound with the same delegate-protocol machinery already used for windowShouldClose: (GUI/btrc.toml:415-430).
- The missing refusal point is therefore narrow: accessibility actions, which are a UI8 dependency (control-events E34 row). macOS keyboard delivery is already an unproven carried gap in ui1-feasibility.md.

**Why it is resolvable without new design.** The drafts already contain every piece the recommended resolution needs:
- Executor:89-91 charges reserved lanes when a publisher or owner is created. Lifecycle:233-235 reserves terminal capacity before native publication. Subscribe-time reservation is the drafts' own pattern.
- Executor:115-117 already covers input that cannot be refused: "Do not retroactively reject a native final input already dequeued. The provider retains that event, yields its source, or delivers it through the bounded terminal lane." That covers accessibility actions on macOS.
- Exhaustion after commit already has an explicit outcome: "fail the endpoint and account for the accepted receipt" (executor:110). Control-events:97-99 requires that explicit pressure or failure path.
- On macOS, delivery and AppKit dispatch share the main thread, so a backlog builds only when the wake source is not serviced in some run-loop modes (tracking, modal) or delivery is blocked from re-entering. The modes gap is already a carried gap routed to this review's E40/E24 rows (ui1-feasibility.md "run-loop modes"; feasibility-macos.md:105, 160).
- The latched-fatal mailbox describes today's implementation, which the drafts explicitly say they do not claim already meets the contract (control-events:100-101). Replacing it is CX-UIA-22 and CX-UIA-23 provider work.

CL-UIA-13 can therefore write ui2-approved.md as follows:
- Reservation is a provider choice: refuse at a pre-begin hook where one exists, otherwise reserve per registration and channel at subscribe time.
- Native input that cannot be refused is retained in a bounded terminal lane, with explicit endpoint failure when that lane is exhausted.
- The macOS accessibility-action path is recorded as a provisional adaptation and carried gap.

The optional coalesced-count field on SliderControlEvent is a schema detail Claude can put in the frozen diff (the reconciler "aligns the payload", workstreams/claude.md:6182). It is not needed to unblock approval, and no Codex draft revision is required.

**A flaw in the recommendation itself, not the finding.** Per-channel reservation does not equal per-interaction reservation when a new interaction starts before the previous terminal event is delivered. The approved record should size the lane with that in mind.

### B4. UI1 condition 3 is undecided, and the packet schedule makes E01's Linux composition and undo claims unprovable at UI2 (blocking)

Draft: ui2-control-events.md

**Linux today.**
- LinuxTextField has no undo stack and no Return or Escape handling (LinuxTextField.btrc:166-197).
- It accepts only committed text input (:199-203).
- SDL.h flattens SDL_EVENT_TEXT_INPUT only (SDL.h:68-72).
- The headless sessions have no input method (headless-session.sh:152).

**The schedule.**
- Linux undo/redo and SDL_EVENT_TEXT_EDITING flattening are scheduled in UI3's CX-UIA-27 (codex.md:4093).
- Stage 32's exit requires E01 on Linux, and CX-UIA-23's acceptance says "E01-E04, E29, E35, E39 and E46 pass as on macOS" (codex.md:3920).
- The E01 fixture asserts that unchanged publication "preserves selection, composition and undo" and exercises "real IME preedit/commit" (control-events:333).
- The draft leaves condition 3 open: the Linux row asks for "real composition coverage where available" (:311), and review decision 1 (:350-351) is unresolved.

**Effect.** The composing flag of onDraftChanged and the IME settlement on eligibility loss (lifecycle:166-168) have no Linux implementation at UI2.

**Recommendation:** Decide in ui2-approved.md. Recommended:
- **Pull preedit into CX-UIA-23.**
  - Flatten SDL_EVENT_TEXT_EDITING (text, start, length) in SDL.h.
  - Keep a preedit buffer in LinuxTextField that drives the composing flag.
  - Cancel composition with SDL_ClearComposition on Escape and on eligibility loss.
  - Prove it with synthetic TEXT_EDITING pushes, labelled stand-in. Real ibus/fcitx evidence stays with the owner and Q33.
- **Undo.** Either move LinuxTextField undo into CX-UIA-23, or record E01's Linux undo-preservation row as an adaptation deferred to CX-UIA-27, and never count it as passed at UI2.

**Adversarial verification:** not a blocker; closed in the approved record. The facts in the finding are correct, but the problem can be settled in the approval record. It does not need a draft revision before approval.

What I verified at f6c2f2ae:
- LinuxTextField.btrc:166-197 has no undo stack and does not handle Return or Escape. textInput (:199-203) takes only committed text.
- SDL.h:68-72 flattens SDL_EVENT_TEXT_INPUT and never SDL_EVENT_TEXT_EDITING.
- headless-session.sh:152 starts weston with an empty input-method path.
- codex.md:4093 puts Linux undo/redo and the TEXT_EDITING flattening in CX-UIA-27 (UI3). CX-UIA-23's owned paths do not include SDL.h.
- codex.md:3920 makes CX-UIA-23's acceptance "E01-E04, E29, E35, E39 and E46 pass as on macOS".
- native-ui-parity.md:724 defines E01 as including composition and undo preservation.
- control-events.md:311 asks only for "real composition coverage where available", and review decision 1 (:350-351) is open.
- The schedule mismatch is real: at UI2, Linux cannot prove E01's composition or undo-preservation rows, nor the lifecycle's IME settlement on eligibility loss (lifecycle:166-168).

Why it does not block approval:
1. UI1 condition 3 already offers two options for the review to choose between: record an adaptation, or have CX-UIA-23 plumb SDL_EVENT_TEXT_EDITING. Either can be written in ui2-approved.md, and the finding's own recommendation is "Decide in ui2-approved.md".
2. The drafts hand this decision to CL-UIA-13 on purpose:
   - Control-events decision 1 says "explicit adaptations replace undocumented differences".
   - Lifecycle:176-177 says a provider whose IME cannot cancel without committing "must report the mismatch for review".
   - Lifecycle decision 3 (:317) reconciles IME cancellation in CL-UIA-13.
3. The UI1 checkpoint already marks the composition rules provisional on both macOS and Linux "until an owner IME session". The E01 composition row is already a carried gap. macOS has the same kind of gap: no IME evidence, and hosted keyboard delivery is unproven.
4. The undo row can be recorded as an adaptation deferred to CX-UIA-27, where E14 undo/redo already lives, and not counted as passed at UI2. Unchanged setText is already a true no-op on Linux (LinuxTextField.btrc:232), so the selection and caret half of the claim holds today.
5. The adaptation is technically feasible. LinuxWindow.btrc:558-559 already starts and stops SDL text input on focus changes, so a Linux SDL row can say:
   - the platform IME draws the preedit;
   - the composing flag stays false until CX-UIA-27;
   - eligibility loss stops text input.
   If the record instead pulls preedit into CX-UIA-23, that is a packet-scope amendment by Claude, not a contract defect to send back to Codex.
6. CL-UIA-14's Stage 32 exit line ("E01 passes on Linux") can carry the deferred Linux composition and undo rows as recorded gaps. That is a landing-evidence question, not a reason to withhold contract approval.

So the record must decide condition 3 explicitly and amend or annotate CX-UIA-23's E01 acceptance. It is a required item in ui2-approved.md, not an unresolved blocking finding.

### N1. macOS native NSSlider tracking cannot honor Escape, capture loss, model change or eligibility-loss cancellation, and the E03 oracle cannot detect this (non-blocking)

Draft: ui2-control-events.md

**macOS today.**
- MacOSSlider uses native NSSlider tracking with setContinuous(false) and no target/action (MacOSSlider.btrc:247-259).
- AppKit's control-tracking loop dequeues mouse events only; key events stay queued until mouse-up.
- Local event monitors, the provider's only input route (MacOSViewInput.btrc:54), are not called for events consumed by nested control-tracking loops.
- Resign-key and deactivation (MacOSViewInput.btrc:50-52, 88-93) do not end AppKit's tracking.
- Programmatic setDoubleValue during tracking is overwritten by the next drag.
- NSSliderCell or accessibility overrides need Objective-C subclassing, which is interop step 6 (Stage 29; native-interop-ownership.md:1151).

**What the draft requires.** The rule at control-events:207-213 says Escape, capture loss and eligibility loss cancel and restore, and a changed model cancels the drag.

**The oracle.** The E03 oracle accepts "One accepted commit, or one cancellation with no stale commit" (:335), so a provider that ignores Escape passes.

**Linux.** Feasible: the provider owns the pointer path (LinuxSlider.btrc:320-327). It has no key handling yet.

**Recommendation:** Choose one and record it:
- Provider-owned tracking on macOS: consume mouseDown on the NSSlider in the local monitor, track drags in the main loop, and set doubleValue.
- Or an AppKit adaptation: no Escape or capture-loss cancel during native tracking, and a model change ends tracking with a synthetic mouse-up through the bound postEvent:atStart:.

In either case, tighten E03's oracle per trigger. Release must give exactly one COMMIT. Escape, capture loss and eligibility loss must each give exactly one CANCEL with the start value restored, or an explicitly declared adaptation.

### N2. "Unchanged publication" is undefined (accepted baseline or live draft), and both providers compare against the live editor text (non-blocking)

Draft: ui2-control-events.md

**The draft.** control-events:103-108, 125-126 and 143-147 say an unchanged publication is a true no-op, while a changed setText is a MODEL replacement that cancels the interaction.

**macOS.** MacOSTextField.setText compares through text(), which calls validateEditing and so includes uncommitted, possibly marked, field-editor text (MacOSTextField.btrc:63-75).

**Linux.** LinuxTextField.setText compares the live _text and moves the caret to the end on change (LinuxTextField.btrc:229-237).

**Effect.** A model that republishes its last accepted value during an edit, as a periodic refresh does, counts as changed. The provider issues a MODEL cancel and the user's draft and composition are destroyed. This contradicts E01 (native-ui-parity.md:724).

**Recommendation:** Define "unchanged" as equal to the control's accepted baseline: the last committed or model-published value at the current revision, not the live draft. Require providers to keep that baseline separately. On macOS, do not call validateEditing to read it.

### N3. macOS has no worker-safe wake today, and CX-UIA-22's "performBlock" alternative is not thread-safe (non-blocking)

Draft: ui2-executor.md

**What the draft needs.** tryPublish must work from a worker and "arrange one native-loop wake" (executor:48, 97-101). BackgroundJobs needs a completion-ready endpoint (:58, 153-158).

**macOS today.**
- MacOSRunLoopSignal requires the main thread and uses NSNotificationQueue.defaultQueue, which is per-thread (MacOSRunLoop.btrc:16, 19, 30-35).
- post uses NSRunLoop.currentRunLoop() (MacOSApplication.btrc:381). On a worker that is the worker's own loop, and NSRunLoop is not thread-safe.
- codex.md:3861 nevertheless offers "CFRunLoopSource or performBlock".

**Linux.** Fine: btrcSdlPushWake uses SDL_PushEvent, which is thread-safe (SDL.h:92-97).

**Related: E04 on Linux.** waitMilliseconds caps every wait at 250 ms (LinuxApplication.btrc:264), so "Park the native loop with no polling timer" (executor:246) needs that cap removed whenever no deadline and no pending GPU device exist.

**Recommendation:** For macOS, use a version-0 CFRunLoopSource on CFRunLoopGetMain():
- Schedule it in the modes chosen under B2.
- Signal it from any thread with CFRunLoopSourceSignal plus CFRunLoopWakeUp.
- Its perform callback is a btrc-implemented C callback table, which already exists (Callback.btrc:3-11; native-interop-ownership.md §2.1).
- This needs binding fragments only.

Drop "performBlock" from CX-UIA-22 step 3. [NSApp postEvent:atStart:] is documented as callable from secondary threads and is already bound, but it is not dequeued during tracking loops.

On Linux, drop the 250 ms idle cap for E04.

### N4. E29 and E31 fault injection needs declared probe-level seams, because no natural native failure exists on either provider (non-blocking)

Draft: ui2-lifecycle.md

**What the draft asks for.**
- E29: "Inject failure at every forward and rollback boundary" (lifecycle:296).
- E31: "Construction failure after each native acquisition" (:297).
- Review decision 2: "Prove rollback and quarantine encoding on real macOS/Linux shells" (:315-316).

**Neither provider fails naturally.**
- macOS mutations are addSubview, removeFromSuperview and add/removeArrangedSubview (MacOSView.btrc:52-67; MacOSStack.btrc:39-41). They return no failure. Objective-C exceptions are translated by the call adapter (native-interop-ownership.md F1).
- Linux reorder is btrc vector manipulation. Only a GPU-backed reattach allocates.

**Constraints.**
- CX-UIA-21 writes portable fixtures "against the interfaces only" (codex.md step 3).
- The only existing seam precedent is test-only C interposition (src/tests/native/gui/AllocationFaults.h).

**Recommendation:** State that RolledBack, FailedConsistent and quarantine are proven by probe-owned injection:
- macOS: swizzle the AppKit mutation selectors under src/tests/native/gui/ui2/probes/macos to raise NSException, which the adapter translates to a btrc exception.
- Linux: interpose the GPU and SDL allocations a reattach performs.

Also state that infallible software steps are not boundaries, and never compile a fault seam into the shipped stdlib.

### N5. A macOS move must not pass through removeFromSuperview when the subtree holds the first responder (non-blocking)

Draft: ui2-lifecycle.md

**The draft.**
- "Existing identities ... surviving focus/selection persist. A move is not a close" (lifecycle:120-125, with move semantics at :113-117).
- E29: "Mutate with focused editor" (:296).

**macOS today.** MacOSView.detachNative is removeFromSuperview (MacOSView.btrc:64-67). Removing a view that holds the first responder ends the field-editor session. The control-events rule (:128-131) then makes that a USER commit on focus departure, and IME composition ends. Both are "callbacks from intermediate order" that E29 forbids.

**Recommendation:** Specify the macOS move path:
- Stacks: reorder NSStackView arranged subviews.
- Plain containers: use sortSubviewsUsingFunction:context: through a C comparator shim, or addSubview:positioned:relativeTo: once it is verified not to resign the first responder.

Add an E29 row asserting zero commit or cancel events and preserved marked text across a move.

### N6. The new IView and IContainer operations reach provider files outside CX-UIA-22/23's owned paths, and the packet acceptance lists omit Stage 32 cases (non-blocking)

Draft: ui2-lifecycle.md (landing scope)

**IContainer implementers forward attach and detach explicitly.**
- MacOSStack.btrc:91-93 and MacOSPanel.btrc:82-84.
- LinuxStack.btrc:90-92, which relayouts.
- LinuxContainerView in LinuxContainer.btrc:31-36.

**IView methods are forwarded per class on macOS** (for example MacOSTextField.btrc:39-61).

**Files the packets do not own.**
- CX-UIA-22 (codex.md:3844): MacOSButton, MacOSLabel, MacOSPanel, MacOSProgressIndicator, MacOSLevelIndicator, MacOSStack, MacOSGrid and MacOSGPUView.
- CX-UIA-23 (codex.md:3894): LinuxContainer, LinuxStack and LinuxPanel.

**Acceptance gaps.**
- CX-UIA-23's acceptance omits E31 (codex.md:3920).
- CX-UIA-22's acceptance omits E40, as the UI1 review noted.
- Neither covers E42, although condition 4 adds UI2 to E42's links.

**Recommendation:** Before the atomic landing:
- Extend the owned paths, or route the new surface through shared base owners.
- Add E31 to CX-UIA-23's acceptance and E40 to CX-UIA-22's.
- Add E42's hide and minimize rows where the runner can produce them (N8).

### N7. IWindow.state's "drawable readiness" and "application activity" fields are shaped by SDL (non-blocking)

Draft: ui2-lifecycle.md

**The draft.** lifecycle:187-194 defines both as window-level fields.

**Linux.** The window renders through one WebGPU surface (LinuxWindow.btrc:162-176, 236-247), so a window drawable exists.

**macOS.** A window has no single drawable: AppKit draws the tree, and each IGPUView owns its own CAMetalLayer (IGPUView.btrc docs).

**Application activity.** SDL has no application-active signal on X11 or Wayland, only per-window focus (LinuxWindow.btrc:572-573).

**Recommendation:** Define drawable readiness per IGPUView, and make the window field "presentable". Make application activity tri-state (active, inactive, unknown); on Linux, derive it from window focus with debouncing.

### N8. E42's minimize, cover and display or scale rows cannot be produced in the Linux headless sessions (non-blocking)

Draft: ui2-lifecycle.md

**X11.** The X11 session is bare Xvfb with no window manager (headless-session.sh:138-143), so iconify never happens.

**Wayland.** Weston headless never tells the client it is minimized.

**LinuxWindow today.** It ignores HIDDEN and MINIMIZED (LinuxWindow.btrc:577) and throws after 120 unavailable frames (:246).

**The fixture.** E42 is lifecycle:300.

**macOS hosted.** It can miniaturize and occlude, but it cannot change displays, scale or activation (UI1 carried gap).

**Recommendation:** Record the Linux minimize, cover and display rows as unavailable on headless runners, or add a minimal window manager to the X11 session (a Claude-owned nix change). Prove the 60-second zero-presentation oracle through hide.

### N9. The drafts do not say which monotonic clock deadlines use, and E30's wall-clock move needs a seam (non-blocking)

Draft: ui2-executor.md

**The draft.** executor:201-217 requires "monotonic deadline".

**Providers.**
- Linux uses SDL_GetTicksNS, which is CLOCK_MONOTONIC and excludes suspended time (LinuxApplication.btrc:245, 263).
- macOS NSTimer and CFRunLoop use mach absolute time, which stops during sleep.

**E30.** "move wall time both directions" (:248) requires changing the system clock, which agents may not do on the owner's Mac.

**Recommendation:** State that UI deadlines exclude device-suspended time. That matches both reference providers, CACurrentMediaTime on iOS and uptimeMillis on Android. Run the wall-clock-move trial only on disposable CI runners, or through an injected civil-clock source.

### N10. Legacy nested-loop APIs contradict UI2's "no nested loop" guarantees on both providers (non-blocking)

Draft: ui2-lifecycle.md / ui2-executor.md

**IWindow.showAlert.**
- macOS: NSAlert runModal (MacOSWindow.btrc:268-276).
- Linux: SDL_ShowSimpleMessageBox, which blocks (LinuxWindow.btrc:706-709).

**GUI.chooseDirectory.**
- macOS: NSOpenPanel runModal (MacOSDirectoryPicker binding).
- Linux: pumpOnce called nested through ILinuxDialogPump (LinuxDirectoryPicker.btrc:9-12; GUIProvider.btrc:47-49). It re-enters runWork and dispatchActions from inside the caller's callback.

**The drafts.**
- "No nested modal loop or busy poll" (lifecycle:93-94).
- control-events:82.
- executor:57.

**Consequences.**
- A decision handler that prompts with showAlert re-enters the loop.
- CX-UIA-22 step 3 promises "an asynchronous sheet" (codex.md:3861), but the lifecycle draft defines no prompt operation.

**Recommendation:** Mark showAlert and chooseDirectory as legacy nested-loop APIs:
- They are excluded from the executor's fairness guarantees.
- They are forbidden in close-decision handlers.

State that the application presents Save/Discard/Cancel. Alternatively, add an async prompt: a sheet on macOS, and an in-window overlay on Linux, because SDL's message box blocks.

### N11. App-wide quit coordination has no operation and conflicts with the irreversible requestQuit (non-blocking)

Draft: ui2-lifecycle.md / ui2-executor.md

**The drafts.** lifecycle:97-103 says quit collects authorizations from every window before any becomes irreversible. executor:56 says requestQuit "starts the shared shutdown protocol".

**requestQuit today is irreversible.** It closes admission and abandons domain delivery:
- Linux: LinuxApplication.btrc:122-127, 136-138, 238.
- macOS: MacOSApplication.btrc:122-130, 144-151, 265.

**Native quit paths.**
- macOS native quit calls requestQuit directly (MacOSApplication.btrc:239-242).
- On Linux, SDL_EVENT_QUIT closes every window through requestNativeClose (LinuxApplication.btrc:223).
- SDL3's default SDL_HINT_QUIT_ON_LAST_WINDOW_CLOSE also sends a QUIT when the last window's close is requested, which duplicates the window transaction.

**Recommendation:** Specify the quit path:
- A native quit (applicationShouldTerminate, SDL_EVENT_QUIT) starts a provider-internal group of window transactions with reason APP_QUIT. Only the group commit calls requestQuit.
- A programmatic requestQuit stays irreversible.
- On Linux, set SDL_HINT_QUIT_ON_LAST_WINDOW_CLOSE=0.
- Drive E46's quit-cancel trial with [NSApp terminate:] on macOS and an injected SDL_EVENT_QUIT on Linux.

### N12. Known conflict 2 (what text eligibility loss cancels): both variants are feasible on both providers (non-blocking)

Draft: ui2-control-events.md vs ui2-lifecycle.md

**The two texts.**
- control-events:137-139: restore the baseline.
- lifecycle:166-168: preserve already committed text.

**macOS native behavior.** Hiding an ancestor of the first responder passes first-responder status on. That ends the field editor and commits its text into the cell.

**Restoring the baseline on macOS.** The provider must discard marked text (NSTextInputContext discardMarkedText) and call abortEditing before setHidden. This is feasible because every eligibility change is initiated by the provider, through setVisible, setEnabled or detach. MacOSTextField already binds abortEditing (btrc.toml MacOSTextField symbols).

**Escape interception on macOS.** Local monitors run before the input method, so intercepting Escape there must skip it while the field editor has marked text.

**Linux.** Either variant is trivial, because the provider owns _text (LinuxTextField.btrc:15-36).

**Recommendation:** Pick one rule. I recommend the control-events baseline restore, which is consistent with Escape. Require the macOS provider to settle editing before calling setHidden, and bind hasMarkedText and discardMarkedText.

### N13. E35: the Linux image view does not retain its presentation, and a closed-handle republish succeeds silently (non-blocking)

Draft: ui2-lifecycle.md

**Linux today.**
- LinuxImageView paints through the live handle and stops once the handle is closed (LinuxImageView.btrc:69-74, 58).
- Republishing the same alias of a closed handle returns early as success (:92).
- Handles are created on workers (:9-12), so close may race with publication.

**macOS.** Already retains the NSImage natively (MacOSImageView.btrc:58-66; MacOSImageHandle.btrc:120-127).

**Recommendation:** On Linux, retain the identity and the Image at publication, and check isOpen before the same-alias early return. Linearize close against publication: either an atomic or locked open state, or close confined to the UI executor after handoff.

### N14. E31's definition of Complete conflicts with AppKit's deferred deallocation, and the fallback for a worker's last release has no oracle (non-blocking)

Draft: ui2-lifecycle.md

**The draft.** "Complete alone means the native resources ... are released" (lifecycle:224-226). The lease is unproven, with a fallback (:232-248).

**UI1 carried gap.** UI1 found that survivors are counted only after a 200 ms drain the probe owns (ui1-feasibility.md:66-68).

**Destructors on the wrong thread.**
- macOS: native owners' __del__ calls close(), which throws off the main thread (MacOSWindow.btrc:124-126, 328).
- Linux: LinuxApplication.close requires SDL's main thread (LinuxApplication.btrc:102, 370).

**Recommendation:** Define Complete as:
- the provider's claims are released, and no callback can enter;
- platform-deferred deallocation (autorelease, Core Animation) is observed within a bounded drain;
- the class of the one allowed private survivor is recorded.

Until the lease is proven, declare the off-executor final-release policy (for example, a named fatal diagnostic) so that E31's worker-last-release row has an oracle.

### N15. The fairness rules are worded around an app-owned pump (SDL) (non-blocking)

Draft: ui2-executor.md

**The wording.** executor:186-196: "Each native-loop turn services bounded slices of input ... Rotate the starting class" and "Check the budget before dequeue".

**AppKit.** NSApplication owns input dequeue and dispatch, one event per nextEvent, so the provider bounds only its own sources. Per-item performBlock (MacOSApplication.btrc:381) runs every queued block in one CFRunLoop pass, with no time budget.

**Linux.** The wording fits the SDL pump (LinuxApplication.btrc:217-231).

**Recommendation:** State fairness as an outcome: bounded provider slices, and measured service gaps per class. Apply rotation and check-before-dequeue to provider-owned queues. On macOS, replace per-item performBlock with one provider queue drained under count and time budgets.

## Compiler gaps

- None needed for the proposed value types. ControlEventsProbe.btrc covers nullable string keys (string? returns and parameters), enum origins, typed invoke receivers and interface methods returning ICallbackRegistration. It compiled with the Python compiler and ran correctly.
- Interop capability, not needed for UI2 if accessibility stays deferred: Objective-C subclassing and overrides (`superclass`/`overrides`) arrive only at interop step 6, Stage 29 (native-interop-ownership.md:1151). Until then macOS cannot override NSSliderCell tracking or accessibilityPerformIncrement. Cancellation during native tracking therefore needs provider-owned tracking (N1), and accessibility-initiated relative adjustments stay a UI8 dependency.
- Binding data only, as GUI/btrc.toml fragments that are integrator-owned:
- the CoreFoundation symbols for the CFRunLoopSource wake (CFRunLoopGetMain, CFRunLoopSourceCreate, CFRunLoopSourceSignal, CFRunLoopWakeUp, CFRunLoopAddSource);
- NSRunLoop addTimer:forMode: with common modes;
- NSMenu cancelTracking;
- the NSTextField delegate methods and currentEditor;
- NSTextView hasMarkedText and the NSTextInputContext discard of marked text;
- NSClipView bounds notifications;
- the NSWindow occlusion, backing-scale and miniaturize selectors and notifications;
- the SDL_EVENT_TEXT_EDITING flattening and SDL_ClearComposition.
The CFRunLoopSource perform callback relies on btrc-implemented C callback tables, which are already implemented (native-interop-ownership.md §2.1; Callback.btrc CFunction and OwnedClosure).
