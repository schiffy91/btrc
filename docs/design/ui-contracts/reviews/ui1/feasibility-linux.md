# CL-UIA-09 UI1 checkpoint: Feasibility review 2: Linux SDL (X11 and Wayland)

Reviewed read-only on main `19f75abf` (2026-10-06) by an integrator review workflow (`wf_271409ca-5fd`). Verdict: **approve**.

## Summary

Reviewer 2 (Linux SDL, X11 and Wayland). Verdict: approve "Linux on the shipping SDL provider proceeds to UI2". I found no blocking finding, but the decision record must scope the claim: X11 is the gating backend, and Wayland is eligible with one open dependency defect carried.

**X11 evidence (strong).**
- The ledger at 72592d36 shows 4 of 4 rows passing (reference and selfhost, plain and ASan/UBSan). Each row ran 100 cycles, 100 GPU frames and 100 fresh-process restores, with zero teardown, handle and registration counts (ui1-linux.toml:11-51).
- More importantly, hosted main CI at the current HEAD re-ran the same four rows at the default 100 cycles and 100 restores, and all passed. That run is CI 37422912212 on 19f75abf, unit shard job 112136078860.
- The same run passed the clipboard-requestor guard on the patched SDL.
- The Linux provider source has not changed since 72592d36 (`git diff 72592d36..19f75abf -- src/stdlib/GUI/Linux` is empty).
- Hosted runs therefore exist. The ledger simply does not cite them.

**Wayland evidence (partial).**
- 3 of 4 rows pass. The selfhost ASan/UBSan row hangs at restore 61, inside libdecor 0.2.5's GTK dispatch. This is the second recorded occurrence (restore 56 in batch 30).
- The cause is outside btrc and outside UI2's surface. It is well characterised by LibdecorPending.
- It is still open and has no CI coverage. That leaves CX-UIA-11's own acceptance item 1 unmet.

**Remaining gaps (all carried, none block entry).**
- E40 is a recorded failing reproduction, as Stage 31 requires. Its repair is UI2's executor deliverable.
- E46 is UI2's lifecycle deliverable. SDL can veto a close natively.
- E47 is UI1/UI5/UI10, not UI2.
- "No bridge" is D23/UI8 work. It blocks the Stage 31 Linux close (CL-UIA-10), not UI2 entry.
- Not proven at UI1: synthetic-only input, no IME, no resize or exposure exercise, and window-count-only leak accounting. Each affects specific UI2 cases (listed under carried gaps).

**Feasibility on SDL.** The provider already has the loop shape the executor draft needs:
- SDL_WaitEventTimeout plus an SDL_EVENT_USER wake (SDL.h:84-97; LinuxApplication.btrc:261-302);
- UI-thread checks;
- a bounded shutdown drain.

The close veto, setter suppression, two-axis scroll and ordered mutation are all provider-local on custom-drawn controls. No UI2 operation is infeasible on SDL.

**D23.** D27 already scopes D23 so that Linux UI2/UI3 stays on SDL (WORKSTREAMS Q34, CLAUDE.md D27). The executor draft names the GLib-context replacement if GTK4 wins (ui2-executor.md:224).

**D24 on mobile.** The host-owned loop is confirmed at design level only. ios.md:19-26, android.md:23-28 and ui2-executor.md:54,60-65,226-227 agree on four points:
- UIApplicationMain, or the Activity with the main Looper, owns entry;
- the GUI layer attaches;
- there is no nested GUI.run;
- the executor wakes the host loop.

No shell exists and CL-P2-22 has not run.

**Open toolkit choices.** Win32 vs WinUI and Views vs GameActivity can stay open until CL-UIA-22, under the conditions in finding 12.

## Findings

### 1. X11 supports UI2 entry, and hosted 100-cycle proof at main exists but is not in the ledger (non-blocking)

**Local ledger.** ui1-linux.toml:29-51 records linux-x11-plain and -sanitized for reference and selfhost at 72592d36, all passed. Each row's diagnostic shows cycles 100, frames 100, fresh_process_restores 100, nonzero_teardown_cycles 0, native_handles 0 and live_registrations 0.

**Hosted run at main.** CI run 37422912212 (main, 19f75abf, push, success), job 112136078860 `tests (unit)`. Its skip-report artifact 11394289502 shows these rows passed: test_native_ui_shell_linux.py::test_linux_native_shell[plain-python], [plain-selfhost], [sanitized-python] and [sanitized-selfhost]. It also shows test_native_ui_sdl_clipboard_requestor.py both cases passed, and test_ui0_catalog.py 114 passed.

**Why that run is a full-strength X11 row.**
- BTRC_UI_SHELL_CYCLES is set nowhere in CI, so the default of 100 applies (native_ui_shell_fixtures.py:183).
- The harness always runs 100 restores (native_ui_shell_fixtures.py:227-239).
- The unit shard runs under tools/virtual-display.sh, which defaults to X11.
- The run postdates the batch-41 SDL patch and the batch-45 journey waits (NativeShell.btrc:53-61).
- `git diff --stat 72592d36..19f75abf -- src/stdlib/GUI/Linux` is empty, so provider behavior equals the ledger revision.

**Recommendation:** Cite run 37422912212 and job 112136078860 in the CL-UIA-09 decision record as the current X11 evidence. Promote it into the evidence shard, as batch 36 did for macOS, with runner linux-devcontainer and device_class stand-in. Do not describe the Linux UI1 evidence as local-only.

### 2. Wayland is 3 of 4: an open libdecor 0.2.5 hang in SDL_ShowWindow (carried; a prerequisite for the Linux Wayland half of the UI2 landing) (non-blocking)

**The failure.** ui1-linux.toml:53-57: linux-wayland-sanitized/selfhost observed failed. The 100 primary journeys passed, but restore 61 timed out after 30 s with empty output. The stack (SDL_ShowWindow -> Wayland_ShowWindow -> libdecor_plugin_gtk_dispatch -> poll(-1)) comes from an earlier capture; no stack was taken for restore 61 itself.

**The dependency reproduction.** ui1-linux.toml:59-69: LibdecorPending passes with dispatch(0) and hangs with dispatch(-1) (probes/linux/README.md:82-87).

**A second occurrence.** claude-integration-record.md:292 (batch 30): restore 56 timed out inside libdecor's GTK plugin.

**Product exposure.** The blocking call is LinuxWindow.show -> SDL_ShowWindow (LinuxWindow.btrc:698), so any btrc GUI app that SDL routes through libdecor can hang at window show. It is not test infrastructure.

**Status.**
- Still open per CODEX.md:271-283.
- CX-UIA-11 acceptance item 1 requires the --wayland variant to pass for all four rows (codex.md:3373), so that item is unmet.
- Wayland has no CI coverage: tools/virtual-display.sh defaults to x11, and no workflow sets BTRC_VIRTUAL_DISPLAY.

**UI2 acceptance this blocks on Wayland.**
- CX-UIA-23 acceptance runs every UI2 case under --wayland (codex.md:3918-3920).
- The lifecycle draft requires both X11 and Wayland (ui2-lifecycle.md:289).
- The executor's Linux row needs E40 on both backends (ui2-executor.md:224).
- The window-showing fixtures are affected most: E46 (two windows, app quit), E42/E39 (hide then re-show), and E40's 10-minute two-window load (ui2-executor.md:251-257).
- The executor's close-within-250 ms rule cannot hold while the UI thread is blocked in poll(-1).

**Recommendation:** **Scope of the decision record.** State Linux eligibility as "SDL: X11 is the gating backend. Wayland is eligible with a carried dependency defect: 3 of 4 rows pass, the selfhost sanitized row failed." Record CX-UIA-11 as integrated with this residual disclosed.

**Fix and gating.**
- Name the fix's owner: Claude, for the nix pins (CODEX.md:271).
- Fix options: a scoped libdecor patch, like nix/sdl3-x11-selection-requestor.patch, or an upstream bump.
- Make the fix a prerequisite of the Wayland rows for CL-UIA-14's Linux landing and for the CL-UIA-11 Wayland CI shard.

**Harness.** Add a stack capture on restore timeout (native_ui_shell_fixtures.py:228-230), so future Wayland hangs are attributed directly rather than by similarity.

### 3. E40: a failing reproduction exists as Stage 31 requires, but only on X11, plain builds, one trial per size; the executor's Linux row wants both backends (non-blocking)

**The ledger records.** ui1-linux.toml:89-291 hold 32 linux-event-boundary slots and 2 E40 ui-case slots. 18 fail at 4,097 and 8,193 events, across keys, release, text and close and both frontends. Revision bbe4f56e is kept on origin/evidence/cx-uia-11-e40-repro.

**Root cause on main.** In LinuxApplication.btrc:221-228, the loop `while (received && dispatched < 4096)` polls event 4,097 and then discards it.

**How the reproduction was run.**
- The documented command is X11 only (probes/linux/README.md:97-103).
- The branch's test builds without sanitizers and runs one trial per size: test_native_ui_shell_linux.py@bbe4f56e, lines 29-85.

**What UI2 expects.**
- The executor draft's Linux mapping needs a "UI1 SDL E40 proof on both backends" (ui2-executor.md:224).
- It also needs 100 bursts per size (ui2-executor.md:249).
- CLAUDE.md:1057 is met: the reproduction is recorded as failing, on a branch.

**The repair.** CX-STDLIB-01's starting revision d6df2cb6 is not in this repository (`git cat-file` fails); it lives in the Codex workspace (CODEX.md:60).

**Recommendation:** Carry E40 as UI2's own deliverable. CX-STDLIB-01 and CX-UIA-23 acceptance must run E40 under X11 and Wayland, both frontends, plain and sanitized, 100 bursts per size. The 4,097 close-loss case must also hold under a flood: the close lane's reserved turn (ui2-executor.md:196-197) covers `IUIWorkPublisher`, fair dispatch and E40. Nothing here gates UI2 entry.

### 4. E46 missing is UI2's deliverable; Stage 31's literal E46 exit is circular, and the catalog's E46 links omit UI2 (non-blocking)

**What the fixture observes.** NativeShell.btrc:138-145 closes with a dirty draft, and the harness requires `dirty-close=missing` (native_ui_shell_fixtures.py:205). The Linux provider closes immediately on request: LinuxApplication.btrc:280 (`if (window.closeRequested()) { window.close(); ... }`) and LinuxWindow.btrc:566.

**Why SDL can do it.** SDL only reports a close event; it destroys nothing. A veto is therefore a provider-local change on X11 and Wayland.

**The circular dependency.**
- CLAUDE.md:1055 (Stage 31 exit) and ref:3424-3426 require an E46 transaction at UI1.
- The portable decision hook, `IWindow.requestClose`/`onCloseRequested`, is a UI2 proposal (ui2-lifecycle.md:41).
- A portable-contract edit is gated on UI2 approval (D27, "Stays gated").
- native-ui-parity.md:689-690 makes E46/E47 conditional: "as their dependent owners land".

**The catalog inconsistency.**
- cases/E25-E47.toml:300 links E46 to UI1/UI3/UI5/UI7, and native-ui-parity.md:1001 lists the same.
- CLAUDE.md:1087, ui-contracts/index.md:13 and codex.md:3920 all assign E46 to UI2.

**Recommendation:** Record explicitly in ui1-feasibility.md that E46 does not gate UI1 to UI2 entry. It is delivered by UI2's lifecycle operations and extended in UI3/UI5/UI7. Cite native-ui-parity.md:689-690. Reconcile the E46 links, adding UI2, through the reviewed catalog amendment at CL-UIA-13 or CX-UIA-21.

### 5. AT-SPI "no bridge" is a source-level label; it does not gate UI2 but does block the Stage 31 Linux close, and the hosts.toml blocker is stale (non-blocking)

**Where the label comes from.**
- ShellProbe.c:56 prints a fixed `"accessibility":"no bridge"`, and native_ui_shell_fixtures.py:216 asserts it.
- The ledger notes say it is not a queried tree (ui1-linux.toml:7-8 and :15).

**What the plan requires.**
- Stage 31's shell-harness exit requires "accessibility bridges and tree artifacts from the start" (CLAUDE.md, Stage 31 Exit).
- The bucket-4 rule applies UI8 acceptance to UI4–UI7 landings, not to UI2 (CLAUDE.md:1009).
- D23 defers the bridge choice: GTK4, or SDL plus an AT-SPI bridge.

**Stale blocker.** hosts.toml:61-70 leaves `linux-devcontainer-tree` blocked_by `ui-1-linux-sdl-baseline`. That packet has reported, and the actual blocker is D23 (CL-UIA-10) with the bridge work (CX-UIB-07/CL-UIB-12).

**UI2 parts affected.**
- E39's hidden, disabled and offscreen semantics distinction (ui2-lifecycle.md:299).
- The accessibility half of the relative range adjustments (UIRangeAdjustment) in E03/E34 (ui2-control-events.md:85, 214-215, 337).

**Recommendation:** Carry the gap. Mark the Linux SDL accessibility-input and semantics rows of E39 and E03/E34 as unavailable (no bridge), never passed. List it as a CL-UIA-10 blocker for the Stage 31 Linux close. Have the hosts.toml owner retarget `blocked_by` to the D23 and bridge items.

### 6. All Linux input is synthetic SDL-queue injection, and neither session has an IME; there is no Linux composition data for UI2 text events (non-blocking)

**Synthetic input.** ShellProbe.c:15-44 and SDL.h:155-222 push pointer, key, text, wheel and close events with SDL_PushEvent into SDL's own queue. The X11 and Wayland rows therefore differ in window, surface, presentation and teardown only, not in native input translation. hosts.toml:59 says synthetic input does not qualify IME.

**No IME, no preedit.**
- headless-session.sh:152 writes `[input-method] path=`, so Wayland has no input method; Xvfb has none either.
- The provider flattens only SDL_EVENT_TEXT_INPUT (SDL.h:69-73), with no TEXT_EDITING/preedit (source audit, ui1-linux.toml:85).

**UI2 parts affected.**
- The composing flag of `ITextField.onDraftChanged`.
- E01's IME preedit/commit paths (ui2-control-events.md:333).
- E39's IME settlement (ui2-lifecycle.md:165-176).
- Review question 1 in ui2-control-events.md:350-351 ("can preserve composition on macOS and Linux") has no Linux evidence.

**Recommendation:** CL-UIA-13 should record one of two outcomes for Linux SDL composition. Either it is an adaptation (composing is always false; E01 and E39 IME rows unavailable), or CX-UIA-23 must plumb SDL_EVENT_TEXT_EDITING and add ibus/fcitx to the headless session. Physical IME evidence stays with MAC-UIA-01 and Q33.

### 7. Window resize and exposure are never exercised on Linux at UI1 (non-blocking)

**What UI1 asks for.** native-ui-parity.md:680-681 asks UI1 to "prove input, focus, resize, accessibility inspection and teardown".

**What the fixtures do.**
- NativeShell.btrc never resizes or hides its window.
- src/tests/native/gui/linux/{LinuxGUIControls,LinuxGUIReparent,LinuxGUIShutdown}.btrc contain no resize either: a grep for resize, SetWindowSize and WINDOW_RESIZED finds nothing.

**Provider source.**
- LinuxWindow.btrc:577 ignores SDL_EVENT_WINDOW_HIDDEN and MINIMIZED.
- LinuxWindow.btrc:246 throws after more than 120 unavailable frames.
- On Wayland, xdg-shell never tells the client it is minimized.

**UI2 parts affected.**
- The lifecycle draft's `IWindow.state`/`onStateChanged` (E42).
- `IView.interactionState` (E39).
- The SYSTEM-resize origin of `IScrollView.onOffsetChanged` (ui2-control-events.md:246).
- The executor rule that rendering never blocks on a missing drawable (ui2-executor.md:198).

**Recommendation:** Record resize and exposure as not proven at UI1 for Linux. Carry them into CX-STDLIB-01 (the external hide/show repair), CX-STDLIB-02 and CX-UIA-23, with separate X11 and Wayland rows and an explicit "unknown" exposure path for Wayland.

### 8. The Linux "0 leaked handles" claim counts SDL windows only, with LeakSanitizer off (non-blocking)

**What the probe counts.** ShellProbe.c:46-51 counts SDL windows only. shellProbePrivateCount returns a hard-wired 0 and shellProbeDrain is a no-op (ShellProbe.c:52-53).

**Sanitizer settings.** ASAN_OPTIONS is detect_leaks=0 for the shell (native_ui_shell_fixtures.py:52) and for every Linux provider test (linux_provider_fixtures.py:117). The shell README:22-25 discloses this.

**What the evidence covers.** Zero SDL windows, closed portable aliases and zero registrations per cycle.

**What it does not cover.** WebGPU surfaces and devices, text-input sessions, fonts and image textures.

**Recommendation:** Carry the gap into the Linux acceptance for E31 (cleanup leases: ui2-lifecycle.md:297) and E35 (retained image presentation: ui2-lifecycle.md:298). Add non-window native resource counters to the UI2 Linux probes, or enable LeakSanitizer with a suppression file for SDK globals instead of detect_leaks=0.

### 9. Stale Linux ledger rows after batches 41 and 45 (non-blocking)

**Clipboard row.** ui1-linux.toml:77-81 still records sdl-clipboard-requestor-lifetime/x11-destroyed-requestor as observed failed. On main, the patched SDL passes test_sdl_clipboard_owner_survives_its_requestor[destroyed-requestor] (CI 37422912212). test_native_ui_shell_linux.py:66 pins the total at 21 failures, which bakes in that stale count.

**Wayland rows.** They were not re-run after the SDL patch (497c0bc1) or the journey waits (2f94a67e). CODEX.md:279-283 already asks Codex to re-record.

**Recommendation:** Have Codex re-record the destroyed-requestor row and the four Wayland rows on current main before CL-UIA-14. Adjust the ledger test's failure count in the same change.

### 10. The shell fixture puts required side effects inside assert() (non-blocking)

**Where.**
- NativeShell.btrc:127 `assert(readback != null && readback.submit())`.
- NativeShell.btrc:200 `assert(scope.cancel() == ...)`.
- NativeShell.btrc:201 `assert(GUI.close() == ...)`.
- ShellState.c:14-19, 23-29 and 40-44 run fopen, fprintf, fsync, rename and fscanf inside assert().

**Why current evidence is still valid.** The harness never defines NDEBUG (native_ui_shell_fixtures.py:108-124).

**Why it matters later.** Batch 34 replaced the same pattern in the probes with REQUIRE (LibdecorPending.c:13-19). Under NDEBUG, teardown and the checkpoint would silently vanish and produce false passes.

**Recommendation:** Low priority. Apply the probes' REQUIRE pattern to the fixture before any release-mode or NDEBUG run, for example in CL-UIA-22 or P7.

### 11. D24's host-owned loop for mobile is confirmed only at design level; the shared fixture cannot run under a host-owned loop without UI2's attachHost (non-blocking)

**Where the design agrees.** The rule is the same in each:
- ios.md:19-26: UIApplicationMain owns the loop; the GUI layer attaches; there is no second GUI.run.
- android.md:23-28: the Activity and main Looper own entry, with a Handler wake.
- ui2-executor.md:54 (`IApplication.attachHost`), :60-65 and :226-227.

**What is missing.** No UIKit or Android shell exists (test_native_ui_shell.py:26-37 records them unavailable), and CL-P2-22 has not run (no record in claude-integration-record.md).

**The fixture mismatch.**
- NativeShell.btrc:153-194 is program-owned: main, then GUI.initialize, then GUI.run, repeated as 100 in-process cycles.
- The mobile notes require 100 scene connect/disconnect cycles (ios.md:119-121) and 100 Activity recreations (android.md:114-116).
- ios.md:25-26 defers the GUI.run compatibility decision to UI2.

**Blocked platforms and their items.**
- **Windows** (`ui-1-windows-shell`, CX-UIA-15): CL-P1-06, CL-P1-14, CL-P1-15, `platforms-p1-host-windows` (CX-P1-07), `platforms-interop-function-table-calls` (CL-P2-06), `platforms-w1-win32-com-imports` (CL-P2-10), `tooling-cross-gpu-deps`.
- **iOS** (`ui-1-ios-shell`, CX-UIA-16): `tooling-ios-simulator-runtimes`, `platforms-p1-host-ios`, `platforms-i1-objc-protocol-adapters` (CL-P2-21), `platforms-i1-app-lifecycle` (CX-P2-36), `platforms-i2-gpu`.
- **Android** (`ui-1-android-shell`, CX-UIA-17): `tooling-android-sdk-ndk`, `tooling-android-ci-emulator`, `platforms-p1-host-android`, `platforms-a1-checked-jni` (CL-P2-09/24), `platforms-a1-activity-lifecycle` (CX-P2-41), `platforms-a2-gpu`.

**Recommendation:** Record D24 as design-confirmed for mobile, not evidenced; CL-P2-22 and CL-UIA-22 remain the real checks. CL-UIA-13 should freeze `attachHost`, at least provisionally, so CX-UIA-16/17 can run the shared journey in host-attached form without a private bridge.

### 12. Win32 vs WinUI and Views vs GameActivity can stay open until CL-UIA-22, under two conditions (non-blocking)

**The UI2 portable operations are host-neutral.**
- Desktop `run` covers an app-owned loop, as in Win32 or SDL.
- `attachHost` covers a framework-owned loop: WinUI's Application.Start/DispatcherQueue, UIKit, or a Looper (ui2-executor.md:54, 60-65).

**The two UI2 reference providers already span both extremes:**
- macOS uses native controls under an OS run loop;
- Linux SDL uses custom-drawn editors under an app-owned wait loop (LinuxApplication.btrc:292-312).

**What the provisional rows presuppose.**
- Windows: Win32 MsgWaitForMultipleObjectsEx and EDIT/common controls (ui2-executor.md:225; ui2-control-events.md:312).
- Android: Views with EditText/SeekBar and a main Looper Handler (ui2-executor.md:227; ui2-control-events.md:314; android.md:19-21).
- GameActivity runs android_main on a non-main native thread, so main-thread affinity wording would not fit it. The Linux provider checks SDL_IsMainThread (LinuxApplication.btrc:102), but that is provider-specific.
- windows.md:20-21 and android.md:19-21 state these routes as proposals, not decisions.

**Recommendation:** Leave both choices to CL-UIA-22, with two conditions for CL-UIA-13. First, phrase executor affinity as "the application's UI executor thread", never "process main thread". Second, mark the Windows and Android rows in the executor and control-events drafts as provisional pending these choices, so a GameActivity or WinUI outcome is a mapping change, not a portable-contract break.

## Gaps UI2 and later carry

- Wayland libdecor 0.2.5 hang in SDL_ShowWindow (ui1-linux.toml:53-69; batch 30 restore 56). It blocks the Wayland rows of CX-STDLIB-01, CX-UIA-23 and CL-UIA-14 for E40, E46, E29, E39 and E42, and the executor's close-within-250 ms rule. The fix is owned by Claude (nix pin). It is also a prerequisite for the Wayland half of the CL-UIA-11 CI shard.
- E40 lossless pump (LinuxApplication.btrc:221-228). Its repair is CX-STDLIB-01, re-verified by CX-UIA-23. It must run under X11 and Wayland, both frontends, plain and sanitized, 100 bursts per size. It affects IUIWorkPublisher, fair dispatch and the close lane (E40, E04, E24).
- E46 dirty-close veto. It is UI2 lifecycle work (IWindow.requestClose, onCloseRequested, close, pollClose). The Linux provider currently closes immediately (LinuxApplication.btrc:280). The catalog's E46 links need UI2 added (cases/E25-E47.toml:300).
- E47 is fixture-only restoration with no stdlib contract. It belongs to UI1/UI5/UI10, not UI2, and affects no UI2 operation.
- No AT-SPI bridge or tree. The decision is D23/UI8 (CL-UIA-10, CL-UIB-12). On Linux SDL, mark the E39 semantics distinction and the accessibility half of E03/E34 (UIRangeAdjustment) unavailable. This blocks the Stage 31 Linux close, not UI2.
- No IME or preedit: the SDL.h flattening reads TEXT_INPUT only, and the sessions have no input method. Affected: ITextField.onDraftChanged's composing flag, E01's IME paths and E39's IME settlement. CL-UIA-13 decides between recording an adaptation and having CX-UIA-23 plumb SDL_EVENT_TEXT_EDITING.
- Synthetic SDL-queue input only. Backend input translation (XTest, wl_keyboard, text-input-v3, HiDPI pointer scale) is unqualified on both backends.
- Resize, hide and minimize exposure are unexercised (LinuxWindow.btrc:246, 577). Affected: IWindow.state/onStateChanged (E42), IView.interactionState (E39), the SYSTEM origin of IScrollView.onOffsetChanged, and the executor's missing-drawable rule.
- Leak accounting counts SDL windows only, with detect_leaks=0. E31 and E35 Linux acceptance needs non-window resource counters or LeakSanitizer with suppressions.
- Tab traversal: LinuxSlider focus is a no-op and Button and ScrollView have no keys. This is UI3 work, with E39's focus-move dependency.
- Stale ledger rows: the clipboard destroyed-requestor row and the Wayland rows have not been re-run since batches 41 and 45. Codex re-records them per CODEX.md:279-283.
- The mobile shared-fixture form depends on UI2's attachHost. Windows, iOS and Android are blocked on the PLAN items listed in finding 11, and D24 is design-confirmed only until CL-P2-22 and CL-UIA-22.

## Catalog

**Eligibility record.** The catalog has no UI2-eligibility field, so record Linux eligibility as note-only evidence. Use a CL-UIA-09-claimed `evidence/<kebab>.toml` test record with `note` only, per catalog README:23 and :111-115.

The note should read: "Linux SDL eligible for UI2: X11 is the gating backend (ledger 72592d36 rows plus hosted CI 37422912212, job 112136078860, at 19f75abf, 4 of 4). Wayland is eligible with the carried libdecor residual (3 of 4 rows; ui1-linux.toml:53-57)."

Do not classify Wayland as qualified.

**Separate changes, each through its owner:**
- **E46 links.** Add UI2 to E46's links in cases/E25-E47.toml:300, through the reviewed CX-UIA-21/CL-UIA-13 amendment.
- **Host route.** Retarget the `linux-devcontainer-tree` route's `blocked_by` in hosts.toml:70, from `ui-1-linux-sdl-baseline` to the D23 and bridge items (CL-UIA-10, CL-UIB-12). This goes through the hosts.toml owner packet.
- **Clipboard row.** Codex re-records the x11-destroyed-requestor row (ui1-linux.toml:77-81) as passed on the patched SDL, and updates the 21-failure count in test_native_ui_shell_linux.py:66.
