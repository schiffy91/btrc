# CL-UIA-09 UI1 checkpoint: Feasibility review 1: macOS AppKit

Reviewed read-only on main `19f75abf` (2026-10-06) by an integrator review workflow (`wf_271409ca-5fd`). Verdict: **approve**.

## Summary

Feasibility reviewer 1 (macOS AppKit), read-only on main 19f75abf. Verdict: the CX-UIA-10 evidence supports "macOS AppKit proceeds to UI2". I found 0 blocking findings. Every gap below is a known gap that UI2, UI3 or later work has to carry. None of them stops CL-UIA-13 or CX-UIA-21/22 from starting.

How the evidence was checked:
- Read with gh api, then streamed the artifact into memory; nothing was written to disk.
- Run 37318960723: macOS workflow, pull_request event, head 43b24996, conclusion success.
- Job 111799425898: native-gui on macos-15, success, 14:40:43–15:30:36Z.
- Artifact 11354918053 (junit-macos-native-gui): 23,559-byte zip, not expired, expires 2026-10-19T15:30:23Z.
- The SHA-256 of native-gui.xml is f132900efa18bb40422c4c82a9ab3249aa4f138258d7b466957baa5fd8428c08. This matches ui1-macos.toml:4.
- The JUnit has 366 tests: 304 passed, 62 skipped, 0 failed or errored.
- All four test_macos_native_shell variants passed: [plain-python] 276.7 s, [plain-selfhost] 268.3 s, [sanitized-python] 289.0 s, [sanitized-selfhost] 285.0 s.
- The 17 rejection mutations passed, plus the Commit-among-window-widgets negative test and the two inactive-tab-context tests.

The four ui1_macos_evidence payloads match the TOML value for value:
- Provenance: btrc_revision 25a160f7, plain or asan-ubsan, stand-in, macOS-15.7.9-arm64, reference or selfhost.
- Counts: 100 cycles, 100 GPU frames, 100 fresh-process restores.
- Survivors: 0 provider and 0 registration. Teardown rows are 100 x (0,1,0); private_objects is 1; subview_total is 60 in all 100 cycles.
- AX fixture identities are mapped through controlView: field = NSTextFieldCell / AXTextField; button = NSButtonCell / AXButton, labelled "Commit"; scroll = NSScrollView / AXScrollArea.
- All 300 Tab contexts are (application_active false, window_key false).
- The Tab order is field x4 in all 100 cycles; Full Keyboard Access is false.
- GPU view: direct first-responder true, AX-exposed false, never reached by Tab.

The evidence directly supports these parts of UI2:
- Lifecycle: the host-owned loop (GUI.run, then NSApplication.run) with post and postAfter. The application was re-initialized 100 times in one process.
- Control events: IButton.onAction queued delivery gives exactly one action per click (NativeShell.btrc:107-110), so the lifetime model the control-events draft reuses holds on AppKit.
- Lifecycle: the callback registration ends closed, and scope.cancel and GUI.close both return COMPLETE (NativeShell.btrc:198-201).
- Lifecycle: a native close (performClose) started inside an application callback (step 8) completes without a nested loop.
- Test harness: mouse injection through postEvent works without a key window.
- Executor/lifecycle: the AppKit hooks UI2 needs are already bound:
  - the windowShouldClose: delegate (GUI/btrc.toml:415,431);
  - applicationShouldTerminate: already answers NSTerminateCancel and turns the quit into a request (MacOSApplication.btrc:239-242), which is the shape ui2-lifecycle.md:90-95 asks for;
  - the notification observer, target/action and event-monitor adapters.

Provenance caveat: the evidence predates seven compiler commits and the batch-45 fixture change. macOS native-gui has not run on main since (finding 9). A focus=native-gui dispatch on main before recording would make the evidence current.

## Findings

### Keyboard delivery is unproven on hosted macOS for every key, not only Tab: the app is never activated, so the window is never key (non-blocking)

Tab and Return are both sent by the same key() helper, `[NSApplication.sharedApplication sendEvent:]` (ShellProbe.m:59-75). AppKit routes key events to the key window. In JUnit artifact 11354918053, all 300 pre-Tab contexts in each of the four variants are (application_active=false, window_key=false), and the responder stays NSTextView/field after every Tab. Return's effect is never observed: step 3 sends text and Enter (NativeShell.btrc:101-103), and step 4 waits only for text()=="draft" (NativeShell.btrc:104-105). That is satisfied by the direct insertText:replacementRange: call (ShellProbe.m:80) plus validateEditing, whether or not Return arrived. The likely root cause is in the provider and harness, not a limit of AppKit. MacOSApplication.btrc:328-330 sets the activation policy to Regular, MacOSWindow.btrc:245 show() only calls makeKeyAndOrderFront, and no activate or activateIgnoringOtherApps call exists anywhere under src/ or tools/ (grep). UI2 cases affected:
- E01: ITextField.onCommit (Return or IME Done) and onCancel (Escape);
- E02/E33: ISelect popup keyboard navigation and Escape to onCancel;
- E03/E34: ISlider keyboard and accessibility UIRangeAdjustment commits, and Escape cancel during a drag;
- E39: focus redirection;
- E42: IWindow.state activation and application-activity fields, which can never change on a hosted app that is never active.
CX-UIA-22's acceptance (codex.md:3866) asks for E01-E03 on hosted macos.yml.

**Recommendation:** Do not block UI2 entry. Record this as a carried gap with an owner. Add a CX-UIA-10 follow-up: the probe requests activation and records application_active/window_key after the request, or delivers through [window sendEvent:] or field-editor commands with the caveat recorded. CX-UIA-22 must not count E01/E02/E03/E34 Return or Escape rows as passed until a run shows window_key=true, or a declared non-NSApp delivery route is used.

### MAC-UIA-02 does not cover Tab or keyboard delivery, though CODEX.md cites it for that (non-blocking)

CODEX.md:269-270 says Tab delivery is unproven `(MAC-UIA-02)`, but the packet itself does not cover it:
- MAC-UIA-02 exists (owner.md:1185-1216; WORKSTREAMS.md:852). Its scope is GPU timing rows plus an Accessibility Inspector screenshot ("Shrunk to the timing rows", owner.md:1195).
- Its step 2 relies on BTRC_UI_SHELL_PAUSE=1, which no file under src/ or tools/ defines (grep). The fixture knows only BTRC_UI_SHELL_NO_AX and BTRC_UI_SHELL_NO_SCROLL.
- Its acceptance names "GPU timing rows (frame pacing, idle CPU)" that test_native_ui_shell_macos.py does not produce.
- Its step 1 launches the fixture from pytest without activating it, so on the owner's Mac the app would stay inactive too.

**Recommendation:** The CL-UIA-09 decision record should not name MAC-UIA-02 as the Tab-delivery route. Either amend MAC-UIA-02 (owner packet: add activation plus Tab, Return, Escape and IME-composition rows, and drop or implement the pause hook), or route keyboard delivery through the hosted activation follow-up in finding 1.

### With Full Keyboard Access off, the native key-view loop cannot give field, button, scroll, gpu even when Tab is delivered (non-blocking)

From the native key-view data, identical in all 100 cycles of all four variants:
- field: next_key_view = button, next_valid_key_view = 'other';
- button: can_become_key_view = false;
- scroll: accepts_first_responder = false and can_become_key_view = false;
- gpu: accepts_first_responder = false, next_key_view = 'other';
- full_keyboard_access = false.
summarize_macos_shell only reports 'passed' when tab_order == [field, button, scroll, gpu] (test_native_ui_shell_macos.py:109-113). That order is not default AppKit behavior, and agents may not change the FKA system setting. This is UI3 (E05-E07, E13/E14) and UI8 policy. UI2 needs only E39's "move focus to a valid owner".

**Recommendation:** Carry this to the UI3 contract (CX-UIA-24) as a platform-adaptation question: what Tab must reach on macOS when FKA is off. It does not affect UI2 entry.

### 'GPU direct focus succeeds' is programmatic only; the GPU view is not focusable by the user and has no AX element (non-blocking)

The GPU child is a plain NSView: native_class 'NSView', acceptsFirstResponder false, isAccessibilityElement false, ax_exposed false, next_key_view 'other'. makeFirstResponder: still made it first responder in all 100 cycles (ShellProbe.m:240-241). That means makeFirstResponder bypasses acceptsFirstResponder; it does not show that a click or Tab can focus the view. The ui1-macos.toml notes say "GPU direct focus succeeds", which reads stronger than the evidence. On the positive side, 100 of 100 readback frames on paravirtual Metal support UI2's E42 drawable-readiness feasibility.

**Recommendation:** Carry to UI3, UI8 (virtual GPU content in the AX tree) and UI9. UI2's E39 must still handle a programmatically focused GPU view when it becomes ineligible. In the decision record, describe GPU focus as 'programmatic only'.

### E46 dirty-close veto is missing at UI1, and the plan is inconsistent about which milestone owns it (non-blocking)

MacOSWindow.btrc:19 `windowShouldClose` returns true. This matches ui1-macos.toml:34-40 and the fixture's deliberate `dirty-close=missing` marker (NativeShell.btrc:216), which the harness regex requires (native_ui_shell_fixtures.py:204-207).
Feasibility is supported:
- the delegate method is bound with a bool return (GUI/btrc.toml:415, 431);
- quit already defers: NSTerminateCancel plus requestQuit (MacOSApplication.btrc:239-242).
The plan disagrees on the owning milestone:
- CLAUDE.md:1055 makes E46 a Stage 31 (UI1) exit;
- native-ui-parity.md:1001 and cases/E25-E47.toml:298 link E46 to UI1/UI3/UI5/UI7, without UI2;
- ui2-lifecycle.md:41 and CLAUDE.md:1087 put it in UI2 (IWindow.requestClose / onCloseRequested).
The existing IWindow.showAlert uses runModal (MacOSWindow.btrc:275). That is a nested modal loop, which ui2-lifecycle.md:93-94 forbids for the decision path.

**Recommendation:** Not blocking: E46 is UI2's own deliverable, and the AppKit hook exists. The record should say:
- macOS E46 stays missing at UI1 and lands through CX-UIA-20/21/22 and CL-UIA-14;
- CL-UIA-10 cannot claim E46 for macOS before that;
- E46's milestone links need UI2 added in a reviewed catalog release.
CX-UIA-22 should use a sheet with a block completion (a binding fragment), not runModal. It should also update the static `dirty-close=missing` marker when E46 lands. The lifecycle draft's no-handler policy (ui2-lifecycle.md:64-66) keeps step 8's dirty native close valid.

### Run-loop modes are never exercised, and postAfter timers fire only in the default mode (non-blocking)

postAfter uses `+[NSTimer scheduledTimerWithTimeInterval:repeats:block:]` (MacOSApplication.btrc:392). AppKit schedules that timer in the default run-loop mode only. Delayed work therefore stops during NSPopUpButton menu tracking, NSSlider or scroller drags, live resize, and runModal (showAlert at MacOSWindow.btrc:275, and the DirectoryPicker runModal noted in ui1-macos.toml:58-64). The UI1 journey never enters any of these modes. The executor draft lists this as required macOS proof: "common/modal loop-mode behavior and no recursive dispatch" (ui2-executor.md:223). It bears on the fairness and service-gap budgets (≤250 ms, ui2-executor.md:184-199, 250-258) and on E02/E03 preview delivery while tracking.

**Recommendation:** Carry to CL-UIA-13 (executor review) and CX-UIA-22. Add E40/E24 trials with an open popup, a slider drag and a modal or sheet, and decide on common-mode timers or run-loop sources.

### Zero survivors are counted after a 200 ms drain owned by the probe, not at the moment close returns COMPLETE; one AppKit-private survivor's class is not in the durable evidence (non-blocking)

NativeShell.btrc:201-204 calls GUI.close() (COMPLETE), then shellProbeDrain(), which runs 10 run-loop turns of 20 ms (ShellProbe.m:115-123), and only then counts the weak sets. Whether provider objects were already deallocated when COMPLETE was returned is not measured.
The validator allows at most one AppKit-private survivor per cycle (test_native_ui_shell_macos.py:52-56). Every row is (0,1,0). The class is printed only on stderr (ShellProbe.m:128-129), and the JUnit has no system-out or system-err (0 tags), so the class is not durable.
ui2-lifecycle.md:224-226 defines "Complete alone means the native resources and registrations are released".

**Recommendation:** Carry to the E31 oracle in CX-UIA-21/22. Decide whether AppKit's deferred deallocation (autorelease or Core Animation) after COMPLETE is allowed. Record the surviving private class in the evidence.

### No UI1 macOS evidence on IME composition or text-field editing events; control-events review decision 1 has nothing to rest on (non-blocking)

The probe inserts committed text through insertText:replacementRange: with NSNotFound (ShellProbe.m:80); there is no marked-text path. The MacOSTextField binding has no delegate, notification or hasMarkedText symbols (GUI/btrc.toml:175-188). ui2-control-events.md:350-351 asks CL-UIA-13 to decide, using UI1 results, whether macOS can preserve composition, and the macOS row (ui2-control-events.md:310) asks for the IME, selection and undo evidence UI1 does not have. A feasible route exists on mechanisms already bound:
- the NSNotificationCenter observer (GUI/btrc.toml:225, 234);
- target/action (GUI/btrc.toml:206-216);
- the local event monitor.
Physical IME is only on the macos-owner route (hosts.toml:39-49).

**Recommendation:** CL-UIA-13 should keep decision 1 provisional for macOS. CX-UIA-22's E01 must prove composition preservation, and an owner session must cover physical IME.

### The evidence revision has fallen behind main, and macOS native-gui does not run on main pushes (non-blocking)

The evidence comes from tested merge 25a160f7, which is GitHub's PR merge ref and is absent from the local repo; its source head 43b24996 is an ancestor of main. Since then, main has 7 compiler commits (tuple typedefs; CL-REQ-09 float literals) and the batch-45 fixture change 2f94a67e to NativeShell.btrc; the stdlib is unchanged. The macos.yml native-gui job runs only in the native-gui, release and lane-macos tiers (ci/tiers.toml:235-240). It was skipped on main run 37422912514 for 19f75abf (job 112136080724). The batch-45 change was checked on Linux only (claude-integration-record.md:504-507). The full JUnit artifact expires 2026-10-19T15:30:23Z.

**Recommendation:** Before CL-UIA-09 records the decision, dispatch `gh workflow run macos.yml -f focus=native-gui` on main and cite that run. Alternatively, state the evidence revision explicitly as source 43b24996 / merge 25a160f7.

### The catalog cannot express 'eligible for UI2', and CL-UIA-09 does not own the files that would (non-blocking)

CL-UIA-09's acceptance item 2 (claude.md:5995) says "The catalog marks macOS and Linux-SDL as eligible for UI2", but:
- hosts.toml (schema btrc.ui-hosts/2) has only route status and blocked_by;
- the macos-hosted-tree route is still 'unverified' with blocked_by=['ui-1-macos'] (hosts.toml:28-37), although CX-UIA-10 landed in-process AX tree properties;
- no operation or case shard cites test_macos_native_shell (grep);
- CL-UIA-09 owns only ui1-feasibility.md and PLAN.md (claude.md:5977-5978); hosts.toml belongs to CX-UIA-06.
The catalog admission check passes: 1,620/1,620 operation slots, 470/470 case slots and 300/300 family cells, with 0 missing and 0 undeclared.

**Recommendation:** Record UI2 eligibility in ui1-feasibility.md, or amend acceptance item 2. Separately, ask CX-UIA-06's owner to move macos-hosted-tree off blocked_by ui-1-macos, scoped to an in-process AX tree with no AX-trust or VoiceOver claim.

### Known CX-UIA-10 follow-ups confirmed in the artifact (non-blocking)

native_controls ax_exposed is false for field and button, and true only for scroll, because ShellProbe.m:271 compares raw NSTextField and NSButton views while the AX tree exposes their cells. is_accessibility_element is false for both views. The gate itself rejects a wrong field or scroll identity (test_native_ui_shell_macos.py:67-68), but no mutation test covers it. Test-record slot keys carry frontend and variant values that JUnitAdapter does not emit, so `--junit` cannot bind these records. All three match CODEX.md:262-268.

**Recommendation:** Keep these as Codex follow-ups. They do not affect UI2 entry.

### CX-UIA-22's acceptance leaves out E40, which the Stage 32 exit requires on macOS; no macOS burst evidence exists (non-blocking)

CLAUDE.md:1087 requires E01–E04, E29, E31, E35, E39, E40 and E46 on macOS and Linux. CX-UIA-22's acceptance (codex.md:3866) lists E01-E04, E29, E31, E35, E39 and E46, but not E40. No macOS run has injected the 4,095/4,096/4,097/8,193 bursts. macOS GUI.post admission is capped at workCapacity 256 (MacOSApplication.btrc:315) and throws "Application work capacity exceeded" when full (MacOSApplication.btrc:122-130). That is an explicit rejection rather than silent loss, but it is unmeasured against ui2-executor.md:249. In the catalog, macOS E40 is partial / implemented-unverified.

**Recommendation:** CL-UIA-13 should reconcile CX-UIA-22's acceptance with the Stage 32 exit, adding E40, and with the drafts' E24, E30 and E42.

## Gaps UI2 and later carry

- Keyboard delivery (Tab, Return, Escape, arrows) on hosted macOS: the app is never active and the window never key (300 of 300 contexts per variant are false/false), and no activate call exists. Affects E01 onCommit/onCancel, E02/E33 popup keyboard and Escape, E03/E34 keyboard UIRangeAdjustment and Escape, E39 focus redirection, and E42 activation state. Owner: a CX-UIA-10 follow-up that activates the app or uses a declared delivery route, plus an amended MAC-UIA-02.
- Key-view traversal with Full Keyboard Access off is a platform-adaptation question for UI3 (E05-E07, E13/E14) and UI8, not UI2.
- GPU view focus and AX: acceptsFirstResponder is false, the view is not in the key loop and has no AX element, and only programmatic makeFirstResponder works. Carry to UI3, UI8 and UI9; UI2's E39 must handle a programmatically focused GPU view.
- E46 dirty-close veto: windowShouldClose returns true (MacOSWindow.btrc:19). It is delivered by UI2 (CX-UIA-20/21/22, CL-UIA-14) with a sheet, not runModal. Stage 31 cannot claim E46 for macOS, and E46's catalog milestone links lack UI2.
- Run-loop modes: postAfter's NSTimer is default-mode only and stalls during menu/slider/scroller tracking, live resize and modal loops. Carry to the executor's E40/E24 and to E02/E03 delivery while tracking.
- E31 oracle: survivors are counted after a 200 ms drain owned by the probe, not at COMPLETE. The AppKit-private survivor allowance of at most one needs its class recorded.
- IME composition, marked text and NSTextField editing events have no UI1 evidence; control-events review decision 1 stays provisional for macOS, and physical IME is an owner session.
- E40 bursts on macOS are unmeasured, and CX-UIA-22's acceptance omits E40.
- E47 is fixture-only (single scene, stdlib restoration missing); it is not a UI2 dependency.
- Evidence freshness: the evidence is at 43b24996 / merge 25a160f7. Main has 7 compiler commits and the batch-45 fixture change since, with no macOS native-gui run; the JUnit artifact expires 2026-10-19.

## Catalog

No catalog edit is needed for macOS to enter UI2, and the admission check passes (1,620/1,620, 470/470, 300/300; 0 missing, 0 undeclared). No schema field can express 'eligible for UI2', so record macOS UI2 eligibility in docs/design/ui-contracts/ui1-feasibility.md, or amend CL-UIA-09's acceptance item 2. Three follow-ups, each through its owner:\n- CX-UIA-06 fragment: move hosts.toml route macos-hosted-tree off blocked_by ui-1-macos, scoped to an in-process AX tree with no AX-trust or VoiceOver claim.\n- Reviewed catalog release: add UI2 to E42's and E46's milestone links, which ui2-lifecycle.md and CLAUDE.md Stage 32 assign to UI2.\n- When CX-UIA-22 lands: wire the shell and UI2 test node ids into case regression lists so `--junit` can bind them, after the JUnitAdapter slot-key follow-up.
