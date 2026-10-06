# CL-UIA-13 UI2 contract review: Feasibility review 2: Windows, iOS/iPadOS and Android

Reviewed read-only on main `f6c2f2ae` (2026-10-06) by an integrator review workflow (`wf_b7573fea-5df`). Verdict: **fix-first**. Every finding raised as blocking was adversarially verified; none was confirmed, and each is closed by a decision in [ui2-approved.md](../../ui2-approved.md).

## Summary

I reviewed feasibility for Windows (Win32 or WinUI), iOS/iPadOS (UIKit) and Android (Views or GameActivity), from native-ui-shells/{windows,ios,android}.md and each draft's five-platform map, against main f6c2f2ae. One finding blocks: UI1 condition 1 is unmet. ui2-executor.md:54 names `IApplication.attachHost` in one line but gives no adapter type, no program entry, no GUI facade entry, no route for host-created scenes or Activities to become IWindows, and no lifecycle vocabulary. ios.md:25-26 defers the GUI.run decision to UI2, and the drafts never make it. The CX-UIA-16 packet already contradicts the draft ("GUI.run maps to the OS-owned loop" versus ui2-executor.md:60). CX-UIA-16 and CX-UIA-17 may not touch GUI.btrc or GUI/I*.btrc, so without a frozen shape they would have to build a private bridge. Apart from that, I found no portable rule that forecloses a reasonable Windows, iOS or Android mapping. The rest is non-blocking, and much of it is AppKit-shaped wording that ui2-approved.md should fix. The close transaction assumes the veto is decided when the request arrives, but Android predictive Back and iOS sheets need intercept declared before the gesture, and there is no row for host teardown that cannot be vetoed. The fair-dispatch rule is written for a loop the program owns, and run-loop modes and Win32 modal loops matter for E40. GameActivity's per-Activity android_main thread cannot be the UI executor. Slider value() must be a double held by the provider. Accessibility absolute set-value has no input class. Setter echoes on Android can arrive late, so they must be suppressed by comparing values. Android child moves must not detach views from the window. The timer clock domain is undefined. I also give platform evidence for both known conflicts. Both rules are implementable; I recommend adopting the executor's per-interaction reservation, taken at the native begin hook. On text eligibility loss, the lifecycle rule (keep finalized text) is achievable on iOS and Android only by provider-side text surgery, and its adaptation clause must stay. The Windows, iOS and Android rows remain provisional until CL-UIA-22. Win32 versus WinUI and Views versus GameActivity stay open, subject to finding 2.

## Decisions proposed

- Treated the provisional headers (ui2-control-events.md:6, ui2-executor.md:7-8, ui2-lifecycle.md:8-9) as satisfying condition 2's 'mark provisional' requirement. Recorded the missing definition of 'UI executor thread' and the Views-only Android rows as non-blocking (finding 2).
- Classified the attachHost gap as blocking, not as wording: CX-UIA-16 and CX-UIA-17 may not touch GUI.btrc or GUI/I*.btrc, and ApplicationSlot.btrc:3-6 lets only the facade manage the application slot, so without a frozen host shape and facade entry the mobile shells cannot run the shared journey without a private bridge, which UI1 condition 1 forbids.
- Judged that no UI2 portable rule forecloses Win32 or WinUI, or Android Views or GameActivity. The one GameActivity constraint (the executor thread must outlive Activity recreation) is satisfiable with custom glue, so both choices stay open for CL-UIA-22.
- For known conflict 1, recommended the executor draft's per-interaction reservation, after checking that each platform has a native hook that can refuse to begin.
- For known conflict 2, gave platform evidence only and did not pick between the two rules (the reconciler's call). Both are implementable; the lifecycle rule needs provider text surgery on iOS and Android, and its adaptation clause must survive.
- Left UI1 conditions 3 (SDL composition) and 4 (catalog milestone links) to the macOS/Linux feasibility reviewer and the parity reviewer; nothing in my platforms changes them.
- Ran no compiler probe: the proposed host shape uses only interfaces, enums, CallbackScope and ICallbackRegistration, all already used in IApplication.btrc and Callback.btrc.

## Findings

### 1. attachHost is named but cannot be frozen; the GUI.run and entry decision deferred to UI2 is not made; host-created windows have no portable route (blocking)

Draft: Provisional host attachment (CL-UIA-22 re-checks it on the real shells):

```
/* Opaque. Created only by a provider's host entry; carries no native handle. */
interface IApplicationHost { bool ownsTopLevelWindows(); }
enum HostLifecycleState { HOST_FOREGROUND_ACTIVE, HOST_FOREGROUND_INACTIVE, HOST_BACKGROUND, HOST_TERMINATING }
enum HostWindowEndReason { HOST_WINDOW_USER_CLOSED, HOST_WINDOW_RECREATING, HOST_WINDOW_SESSION_ENDING, HOST_WINDOW_DISCONNECTED }
/* Program-supplied; retained by the attach registration; every call runs on the UI executor. */
interface IHostedApplication {
  void attached(IApplication application);
  void windowConnected(IWindow window);                          // host-created scene, Activity or top-level window; fresh generation
  void windowEnding(IWindow window, HostWindowEndReason reason); // cannot be vetoed; delivered once, before native teardown, when the platform calls back
  void lifecycleChanged(IWindow? window, HostLifecycleState state); // null means application-wide
  void detached(CallbackCancellation outcome);
}
IApplication: ICallbackRegistration attachHost(IApplicationHost host, IHostedApplication receiver, CallbackScope owner);
GUI: class ICallbackRegistration host(IHostedApplication receiver, CallbackScope owner, int workCapacity = 256);
```

Rules:
- GUI.host calls initialize and then attachHost with the provider's host. Cancelling the registration detaches: it seals admission, closes owned windows and drains; on Complete the facade clears the slot, as GUI.close does.
- On desktop, GUI.host services the provider's loop until detach completes, then returns.
- On iOS, GUI.host enters UIApplicationMain and never returns.
- On Android, the Java shell invokes the program entry, and GUI.host returns with the Looper still running.
- GUI.run on a provider whose loop the host owns throws the typed unsupported error.
- When the host owns top-level windows, createWindow throws the typed unsupported error for top-level windows.
- requestQuit under a host never terminates the process.

The whole attachHost specification is ui2-executor.md:54 ("UI thread: platform host adapter -> attach outcome plus scoped registration; one owner-loop attachment per application. Does not start or nest a loop"), :60-65 (run and attach are mutually exclusive; detach seals and drains) and :229-233 ("Adapters expose host lifecycle transitions to the same executor state machine").

What the draft leaves undefined:
- the adapter's type, and who constructs it;
- which side calls which: the host's service turn into the application, or the application's wake into the host;
- any lifecycle-transition vocabulary;
- a GUI facade entry.

The decisions that depend on it:
- ios.md:24-26: "Any GUI.run compatibility entry is decided in UI2; it cannot silently turn an already-running UIKit app into a nested loop". The drafts only restate that GUI.run is a "desktop convenience entry" (ui2-executor.md:60).
- docs/workstreams/codex.md, CX-UIA-16 step 1: "GUI.run maps to the OS-owned loop". This contradicts ui2-executor.md:60-61.
- codex.md, CX-P2-36 step 1: "GUI.run and poll adapt to the OS-owned loop".

Windows come from the host, but the API has no route for them:
- ios.md:19-21: the scene delegate owns each scene's window and its generation.
- ios.md:39 and android.md:43: IWindow is the scene's UIWindow, or the Activity's content.
- android.md:23-28: no main(), and no GUI.run from onCreate.
- No draft defines how a scene or Activity the host creates becomes an IWindow, what IApplication.createWindow (IApplication.btrc:29) does under a host, or what requestQuit does on iPhone, where no scene teardown is permitted (ui2-executor.md:56).

The shells cannot fix this themselves:
- CX-UIA-16 and CX-UIA-17 'Must not touch' src/stdlib/GUI/I*.btrc and GUI.btrc.
- ApplicationSlot.btrc:3-6: "the facade alone publishes and clears this slot".
- GUI.btrc:88-93: run closes the application before it returns.
- The shared journey is program-owned: NativeShell.btrc:162-201 runs 100 cycles of GUI.initialize, then GUI.run, then assertions, then GUI.close.

CL-P2-22 also needs "the lifecycle event names" (docs/workstreams/claude.md:5310), which no draft supplies. UI1 condition 1 (ui1-feasibility.md:29-31) asks for exactly this freeze.

**Recommendation:** Before approval, freeze provisionally in ui2-approved.md, with CL-UIA-22 re-checking it:
(a) an opaque, provider-implemented host type that only a provider's host entry creates;
(b) a program-supplied hosted-application receiver, with attached, windowConnected, windowEnding (cannot be vetoed), lifecycleChanged and detached;
(c) the IApplication.attachHost signature and its failure outcomes;
(d) a GUI facade entry that initializes and attaches, and releases GUIApplicationSlot when the registration completes;
(e) GUI.run on host-owned providers throws the typed unsupported error;
(f) createWindow under a host that owns top-level creation is typed unsupported for top-level windows, and host windows arrive through windowConnected with a fresh generation;
(g) requestQuit under a host closes owned windows and completes the detach, never terminates the process, and may additionally request scene or Activity teardown where the platform allows it;
(h) the program entry: main() calls the facade on every platform; on iOS it never returns; on Android the Java shell calls the program entry through RegisterNatives.

Precedent: SDL3's SDL_MAIN_USE_CALLBACKS / SDL_EnterAppMainCallbacks puts the same callback shape on the shipping Linux SDL provider, so the shared journey can have one hosted form on every platform, with each cycle being an attach and detach driven from detached(). Then correct CX-UIA-16 step 1 and CX-P2-36 step 1 to match.

**Adversarial verification:** not a blocker; closed in the approved record. Most of the facts in the finding are right, but the gap does not block approval. CL-UIA-13 itself is meant to fill it, in ui2-approved.md, as a provisional row plus carried gaps. Codex does not need to revise a draft.

What holds:
- ui2-executor.md:54 gives attachHost only as "platform host adapter -> attach outcome plus scoped registration". It names no adapter type, no receiver for windows the host creates, no app-level lifecycle enum and no GUI facade entry.
- IApplication.btrc:29 createWindow and GUI.btrc:88-93 run/close are program-owned. NativeShell.btrc:162-201 runs initialize, run and close as 100 cycles.
- CX-UIA-16 and CX-UIA-17 may not touch I*.btrc or GUI.btrc.
- codex.md:3587 (CX-UIA-16 step 1, "GUI.run maps to the OS-owned loop") and codex.md:2283 (CX-P2-36) are loosely worded against ui2-executor.md:60-61.

Why it does not block:
1. The drafts deliberately leave signature freezing to CL-UIA-13.
   - Executor draft :40-41: the ids are "proposed catalog ids, not declarations… before signatures freeze".
   - Lifecycle draft :51-53 and :147: "Exact value type names, handler signatures… need review"; "CL-UIA-13 must choose the concrete result/error encoding".
   - CL-UIA-13 step 4 writes ui2-approved.md as "the frozen interface diff", and CX-UIA-21 step 1 applies it "exactly to the interfaces and the facade". A provisional attachHost signature, an opaque host type and a facade entry can therefore all be written there. That is what the reviewer's own recommendation says.
   - UI1 condition 1 (ui1-feasibility.md:29-31) asks only for a freeze "at least provisionally", and the UI1 Linux review rated this item non-blocking (feasibility-linux.md:222-241).
2. Everything specific to mobile is provisional by rule and can be carried.
   - D27: UI2 approvals are provisional for Windows, iOS and Android until CL-UIA-22. A mismatch found then is a versioned contract change (claude.md:6140).
   - D28: "A real missing API blocks its dependent slice only."
   - The UI2 landing (CL-UIA-14) is macOS and Linux, which use desktop run and need no host attachment.
   - native-ui-parity.md:428 puts the "OS-owned mobile event loop" under N01 at UI1. UI2 depends on "UI1 for the provider under test" (:695), which no mobile provider has met.
   - CX-UIA-16 and CX-UIA-17 are gated behind bucket-3 prerequisites (CL-P2-21, CL-P2-24, CX-P2-36, CX-P2-41, the host lanes). So the route for host-created windows and the lifecycle names can be carried to CL-P2-22, which exists to check "the lifecycle event names" against the draft and then against ui2-approved.md (claude.md:5310-5312), and to CL-UIA-22.
3. Several sub-claims are overstated.
   - The direction of calls is stated: ui2-executor.md:226-227 says a main-loop or Handler wake drains one bounded slice, then returns to the host.
   - requestQuit on mobile is defined at :56: it starts the shared shutdown, requests teardown only where the platform permits it, and never terminates the process.
   - The GUI.run decision is made: :60-61 and :226 keep run as the desktop entry, mutually exclusive with attach, and forbid a blocking GUI.run from a delegate. Behaviour on host-owned providers follows Stage 32's existing typed-unsupported rule.
4. The CX-UIA-16 and CX-P2-36 step-1 wording is packet text, not a draft. The approval record can note the correction.

What CL-UIA-13 should record:
- A provisional attachHost row in ui2-approved.md: an opaque host type created by the provider, run and attach mutually exclusive, GUI.run typed-unsupported on host-owned providers.
- The hosted-window receiver and lifecycle vocabulary as a carried gap owned by CL-P2-22 and CL-UIA-22.
- The two packet-step corrections.

### 2. Executor affinity: define 'the application's UI executor thread'; the Android rows assume Views; GameActivity's per-Activity thread cannot be the executor (non-blocking)

Draft: Affinity: "UI executor thread" means the single thread that created the application and services its loop: the AppKit or UIKit main thread, the Android main Looper thread (Views), SDL's main thread, the Win32 or WinUI dispatcher thread, or a process-lifetime native thread for a GameActivity route. It is never defined as the process's first thread. It must outlive scene and Activity recreation.

Android rows: "UI executor Looper delivery (the main Looper for Views; a persistent native ALooper for GameActivity; provisional until CL-UIA-22)."

Condition 2 is mostly met, with gaps:
- No portable rule says "process main thread".
- The headers mark the Windows, iOS and Android rows provisional (ui2-control-events.md:6, ui2-executor.md:7-8, ui2-lifecycle.md:8-9).
- The term itself is never defined. The executor table says "UI thread" (ui2-executor.md:47-54), and the providers check main-thread APIs (MacOS/GUIProvider.btrc:20, Linux/GUIProvider.btrc:25).

The Android rows assume Views:
- ui2-executor.md:227: "Activity and main Looper own entry".
- ui2-control-events.md:314: "Main Looper delivery".

GameActivity consequences:
- native_app_glue creates a new android_main thread in each Activity's onCreate and ends it on destroy. The executor's rules (ui2-executor.md:165-167, 202-203, 227) require application services to outlive scene and Activity recreation. A UI executor on that per-Activity thread would die at every recreation.
- GameActivity's key-event filter runs on the Java main thread, before android_main sees the event. The existing synchronous IWindowKeyHandler, which returns 'consumed' (IWindow.btrc:5-7), therefore cannot run on an android_main executor. That is a UI3 and CL-UIA-22 issue, not a UI2 one.
- native-interop-ownership.md:71-72 and 471-475 fix the interop executor `main` as Looper.getMainLooper(). A GameActivity UI executor would bind as `caller`, not `main`.

**Recommendation:** Add one defining sentence to the executor and control drafts. Reword the Android rows so the main Looper is the Views mapping. Record that a GameActivity route needs a UI executor thread that lives as long as the process (custom glue, not native_app_glue's per-Activity android_main), and that its interop executor is `caller`. List the key-filter issue for UI3 and CL-UIA-22.

### 3. Close transaction assumes the veto is decided when the request arrives (desktop-shaped); it needs a pre-declared intercept predicate and a path for teardown that cannot be vetoed (non-blocking)

Draft: State table row: "Open, AwaitingDecision or Saving | Host teardown that cannot be vetoed (UIScene disconnect or destruction, system Activity finish, WM_ENDSESSION) | Deliver one notice that cannot be vetoed before native teardown when the platform provides a callback; resolve any pending transaction as OwnerLost; begin final close. No prompt or save is promised; durability is E47's checkpoint."

Intercept rule: "Where the platform must know before the gesture (Android OnBackPressedCallback.isEnabled, iOS isModalInPresentation), the provider derives it from whether a decision handler is live. Applications register the handler only while dirty."

iOS row: "UIKit scene and session destruction can never be vetoed; only presented-sheet dismissal and in-app navigation can."

The draft today:
- ui2-lifecycle.md:73: "Request accepted -> ... Synchronously veto or defer native destruction".
- :64-69: a registered decision handler means a decision is required.
- :105-109 covers Back preview and OS death.
- The state table (:71-82) has no transition from Open for a host teardown that cannot be vetoed.

What that misses:
- **Android predictive Back.** For apps targeting API 36, onBackPressed and KEYCODE_BACK are no longer dispatched. The system decides at gesture start from the set of enabled OnBackPressedCallback/OnBackInvokedCallback. Interception must therefore be declared before the gesture.
- **iOS sheets** need isModalInPresentation set ahead of time; presentationControllerShouldDismiss is the only synchronous query.
- **UIKit has no veto for scene or session destruction** (app-switcher swipe, closing an iPadOS window, requestSceneSessionDestruction). The row at :278, "UIKit scene dismissal is a request where veto is supported", is therefore inaccurate.
- **Android Activity finish** by the system or by task removal, and **Win32 WM_ENDSESSION** after WM_QUERYENDSESSION (which must be answered synchronously, with ShutdownBlockReasonCreate), are also teardowns that cannot be vetoed.
- Without such a row, the application gets no notification at all. It can only poll IWindow.isOpen (IWindow.btrc:13).

**Recommendation:** State that the live decision-handler registration is the pre-declared intercept predicate. Providers keep OnBackPressedCallback.isEnabled and isModalInPresentation in sync with it, and answer WM_QUERYENDSESSION, windowShouldClose and presentationControllerShouldDismiss from it. Recommend registering the handler only while dirty, so Android keeps the back-to-home animation. Add an Open/AwaitingDecision/Saving -> Closing(host-forced) row: it is delivered as a notice that cannot be vetoed (finding 1's windowEnding), resolves any pending transaction as OwnerLost, and points to E47 for durability. Correct the iOS row.

### 4. The fair-dispatch rule is written for a program-owned loop; run-loop modes and Win32 modal loops decide E40 on these platforms (non-blocking)

Draft: "Under a host-owned loop (UIKit, Android Looper, WinUI, or Win32 OS modal loops), each wake services bounded slices of the provider's own classes (semantic work, completions, due timers, close and cleanup) and returns to the host. Input and presentation scheduled by the host count toward the gap measurement but are not reordered by the provider. Wakes must run in every loop mode the host uses for tracking (Apple: common modes or the main dispatch queue). Delivery from an OS-owned modal loop is permitted when no application callback is on the stack."

The rule at ui2-executor.md:186-199 reads: "Each native-loop turn services bounded slices of input, semantic work/worker completions, due timers, presentation and close/cleanup. Rotate the starting class".

Where the provider does not own the turn:
- Under UIKit, the Android Looper and WinUI, the provider does not schedule native input dispatch: UIKit, the InputEventReceiver and the dispatcher deliver input. Nor does it schedule presentation: Core Animation's commit and Choreographer do. ui2-executor.md:227 concedes this for Choreographer.

Where the E40 gap budget breaks:
- **iOS.** UIScrollView tracking runs UITrackingRunLoopMode. A wake registered only in the default mode stalls on every scroll, and E40's continuously-runnable gap budget (≤250 ms, ui2-executor.md:255-256) fails. This is the macOS gap already carried at ui1-feasibility.md:63-65. The main dispatch queue and kCFRunLoopCommonModes sources keep running during tracking.
- **Windows.** ui2-executor.md:225 says "nested modal loops must preserve close/cancellation without reentering semantic delivery". DefWindowProc's move, size and menu modal loops run for as long as the user drags. If no semantic delivery is allowed inside them, the same budget is unmeetable on Win32.

**Recommendation:** Restate the rule for host-owned loops: the provider services its own classes in bounded slices for each wake, and yields back to the host. Fairness for host-scheduled input and presentation is measured, not scheduled. Require wakes to be registered in all common modes on Apple platforms. Win32 may deliver semantic work from a coalesced wake posted to a message-only HWND that an OS modal loop dispatches, as long as no application callback is on the stack. Otherwise declare OS-modal intervals uniformly for every platform in E40's gap measurement.

### 5. Known conflict 1 (terminal capacity reserved per interaction): implementable on all three platforms; adopt the executor rule, reserving at the native begin hook (non-blocking)

Draft: "Terminal capacity is reserved when an interaction begins, at the provider's native begin hook (editing start, tracking or gesture start, or a discrete keyboard or accessibility intent). If it cannot be reserved, the provider refuses the begin and leaves native state unchanged. It never refuses inside an IME composition, and never rejects a terminal input already dequeued."

The two drafts disagree:
- ui2-control-events.md:97-101: reservation "is a provider option".
- ui2-executor.md:112-117: "Each in-progress edit/gesture needs its own pre-reserved commit/cancel capacity; ... refuse to begin the interaction".

Native hooks that can refuse to begin:
- **iOS:** textFieldShouldBeginEditing:; UIControl beginTrackingWithTouch:withEvent:, via the checked Step 6 subclass (ios.md:44-47); gestureRecognizerShouldBegin:. accessibilityIncrement and accessibilityDecrement return void, so refusing there is a no-op that VoiceOver announces.
- **Android:** an OnTouchListener that consumes ACTION_DOWN ahead of SeekBar; an InputFilter on the first edit.
- **Windows:** a trackbar subclass on WM_LBUTTONDOWN; UIA IRangeValueProvider::SetValue can return a failure HRESULT.

Where refusal is not clean: in the middle of an IME composition. Win32 IMM composition, and iOS marked text set through setMarkedText.

**Recommendation:** Resolve for the executor's rule, and replace ui2-control-events.md:97-101 with it. Take the reservation at the native begin hook: editing or first-responder start, or touch or tracking start. Never take it per keystroke or inside a composition. A refused begin leaves native state unchanged and reports the explicit outcome through the application error policy.

### 6. Known conflict 2 (what text eligibility loss cancels): platform evidence; keep the IME adaptation clause whichever rule is chosen (non-blocking)

Draft: "Android system Back while an editor is focused follows the platform's editor rule (dismiss the IME) and is not a text cancel. Text cancel by key is hardware Escape. On touch-only iOS and Android, E01's cancel path is a recorded adaptation."

The two drafts disagree:
- ui2-control-events.md:137-139: eligibility loss "cancels the unfinished edit and restores its baseline".
- ui2-lifecycle.md:166-167: it cancels "uncommitted IME composition while preserving already committed text", with the adaptation clause at :176-178.

Native capability:
- **Win32 IMM** can cancel a composition: ImmNotifyIME(NI_COMPOSITIONSTR, CPS_CANCEL).
- **iOS UITextField** has no public cancel. resignFirstResponder and unmarkText commit the marked text, so the lifecycle rule needs provider surgery: snapshot the text minus markedTextRange, resign, then restore the snapshot.
- **Android:** finishComposingText commits. A cancel means deleting the span between BaseInputConnection.getComposingSpanStart and getComposingSpanEnd, then calling restartInput.

The control rule (restore the baseline) is achievable on every platform, but it discards text the user typed whenever a form is disabled even briefly.

A related point: ControlCancelReason "Escape/back" (ui2-control-events.md:54). On Android, system Back on a focused editor first dismisses the IME, and E18 (native-ui-parity.md:756) requires Back to follow the platform's active editor rules.

**Recommendation:** Either rule is implementable. The lifecycle rule is closer to E39's no-loss oracle, but costs provider text surgery on iOS and Android. Whichever is chosen, keep ui2-lifecycle.md:176-178 so a platform that can only commit reports an adaptation. State that Android system Back on a focused editor follows the platform (dismiss the IME) and never restores the baseline. Hardware Escape is the cancel path; on touch-only iOS and Android, E01's cancel row is an adaptation.

### 7. Slider: value() must be the double the provider holds, not a read-back of the native control; accessibility absolute set-value has no input class (non-blocking)

Draft: "value() returns the provider-held double authority (the last published or user-projected value), never a read-back from a lower-precision native control. Validity is judged in double precision. SliderControlEvent input: ABSOLUTE_POINTER | RELATIVE_ADJUSTMENT | ABSOLUTE_ASSISTIVE. ABSOLUTE_ASSISTIVE is a single COMMIT with no PREVIEW; the exact-value adapter applies the pointer-style declared bound."

**Value authority.**
- MacOSSlider.value() reads the native doubleValue (MacOSSlider.btrc:66). That works on macOS only because NSSlider stores a double.
- On the other platforms the native control is lower precision: UISlider.value is a 32-bit Float, Win32 trackbar positions are LONG, and Android SeekBar progress is an int.
- LinuxSlider already holds the authority itself (LinuxSlider.btrc:14, 83).
- The draft's validity rule "Reject a step that cannot advance the represented value at the range's precision" (ui2-control-events.md:201-203) is ambiguous about whose precision. The no-op-refresh rule (:210-211) and E34 (native-ui-parity.md:790) fail if a provider compares against a rounded native read-back.

**Input class.**
- SliderControlEvent's input field is binary (ui2-control-events.md:51), and accessibility adjustments are limited to UIRangeAdjustment (:214-215; Element.btrc:52-59: small or large increment or decrement, and the endpoints).
- UIA IRangeValueProvider::SetValue(double), Android ACTION_SET_PROGRESS (a float ACTION_ARGUMENT_PROGRESS_VALUE) and macOS setAccessibilityValue all deliver absolute values.

**Recommendation:** Require value() and range() to return the double authority the provider holds, and judge validity in the portable double domain, never in native precision. Add a third input class for absolute, discrete assistive or programmatic-AT values: one COMMIT, no PREVIEW, with the declared pointer-style bound in the exact-value adapter.

### 8. Setter suppression must compare values and revisions; Android and WinUI echo setters asynchronously (non-blocking)

Draft: "Setter echoes may arrive after the setter returns (Android Spinner, IME re-sync, WinUI TextChanged). Providers recognize them by comparing against the last published value and revision, not only with a reentrancy flag."

The rule at ui2-control-events.md:103-106: "Providers track setter origin and suppress those callbacks".

Echoes that arrive after the setter returns:
- Android Spinner.setSelection delivers OnItemSelectedListener on a later layout pass.
- After setText and restartInput, the IME can re-sync on a later turn.
- If WinUI is chosen, TextBox raises TextChanged asynchronously; TextChanging is the synchronous event.

Echoes that are synchronous:
- Win32 EN_CHANGE from SetWindowText.
- iOS UIScrollView setContentOffset triggers scrollViewDidScroll.

No echo at all: UIKit control setters (text, value) send no UIControl events.

**Recommendation:** State the obligation in terms of outcome: an echo is recognized by comparing against the last published value and model revision. A synchronous reentrancy flag is not sufficient on Android or WinUI.

### 9. Two-axis scroll mapping on mobile: insets, overscroll, and no stock two-axis scroller on Android (non-blocking)

Draft: "Observed offsets are reported clamped during native overscroll or rubber-banding. visibleRect is the viewport after removing system-obscured insets (safe area and IME) as reported by the provider; UI5 owns the inset policy."

The draft (ui2-control-events.md:238-244) clamps to [0, max] and says "providers normalize native axis direction, scale and insets".

Platform behavior:
- **iOS:** contentOffset is shifted by adjustedContentInset (the safe area, plus the keyboard if the app adds it), and goes outside the bounds during rubber-banding.
- **Android:** ScrollView scrolls vertically only and HorizontalScrollView horizontally only, so two axes need nested scrollers or a custom OverScroller view. android.md:45 covers only RecyclerView.

E18 makes keyboard occlusion observable, but the draft does not say whether the viewport excludes system insets.

**Recommendation:** State that observed offsets are clamped even during overscroll. Define whether visibleRect excludes the safe-area and IME insets; the boundary can stay with UI5, but the rule has to be stated. Note Android's nested or custom scroller in the provisional Android row, and its interaction with the nested-scroll fixture.

### 10. Ordered mutation on Android must not use removeView/addView; image retention mapping notes (non-blocking)

Draft: Android row addition: "Ordered move uses a provider ViewGroup's detachViewFromParent/attachViewToParent (or drawing and traversal order), never removeView/addView, so focus, the IME and SurfaceView surfaces survive. IImageHandle.close never recycles a Bitmap that a view still presents."

Windows row addition: "Image publication takes its own HBITMAP reference."

**The mutation contract.**
- ui2-lifecycle.md:117 and :121-125: a move "succeeds without detach/recreate"; "surviving focus/selection persist. A move is not a close".
- E29 (native-ui-parity.md:776) mutates while an editor is focused.

**What removeView/addView does on Android.** It detaches the view from the window: focus is cleared, the InputConnection finishes (losing the composition), and a SurfaceView child's surface is destroyed, which would churn the GPU generation (android.md:48-53). The protected ViewGroup.detachViewFromParent and attachViewToParent move children without a window detach; RecyclerView uses them. Overriding drawing and traversal order is the alternative.

**Other platforms.** iOS insertSubview and exchangeSubview, and Win32 SetWindowPos z-order, preserve native identity.

**Image retention (E35, ui2-lifecycle.md:252-267).**
- Android: IImageHandle.close must not call Bitmap.recycle while a view still draws the bitmap.
- Win32: STM_SETIMAGE references the caller's HBITMAP, so publication must take its own reference (refcount, or CopyImage).

**Recommendation:** Add these mapping obligations to the provisional Android and Windows rows (ui2-lifecycle.md:277, 279), so CX-UIA-15 and CX-UIA-17 do not pick the detaching path. The portable rule stays as drafted.

### 11. Timer clock domain and per-scene suspension on iOS (non-blocking)

Draft: "Each provider records whether its timer clock counts device sleep. A timer due before or during suspension or sleep fires at most once after resume. On iOS, a 'suspended scene' is a backgrounded scene; process suspension freezes the whole executor."

**Clock domain.** ui2-executor.md:201 says "Timers use a monotonic deadline". The platform clocks differ on device sleep:
- Android Handler.postAtTime uses uptimeMillis (CLOCK_MONOTONIC), which stops in deep sleep.
- On Darwin, CLOCK_MONOTONIC keeps advancing during sleep, but mach_absolute_time and CLOCK_UPTIME_RAW do not.
- On Windows, QueryUnbiasedInterruptTime excludes sleep.

Whether E30's "deferred overdue timers run once" (ui2-executor.md:248) fires after a device sleep therefore depends on the platform.

**Per-scene suspension.** E30 asks for "two independently suspended scenes (including iPad)". iOS suspends the process, never a single scene; a scene can only be backgrounded while the process runs.

**Recommendation:** Make each provider declare its timer clock (whether it counts suspend time) in evidence. Make the E30 oracle independent of the clock: a timer due before or during suspension fires at most once after resume. Define "scene suspended" for iOS as scene background, and process suspension as a freeze of the whole application.
