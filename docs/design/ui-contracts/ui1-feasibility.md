# UI1 feasibility checkpoint: macOS AppKit and Linux SDL proceed to UI2

**Packet:** `CL-UIA-09` (`ui-1-feasibility-review`), Stage 31.
**Decided:** 2026-10-06, on main `19f75abf`, under the standing design rule
(two feasibility reviewers and one parity reviewer, each blocking finding
adversarially verified; 0 unresolved blocking findings).
**Review files:** [feasibility, macOS](reviews/ui1/feasibility-macos.md),
[feasibility, Linux](reviews/ui1/feasibility-linux.md),
[parity and catalog](reviews/ui1/parity-catalog.md).

## Decision

| Platform | UI2 entry | Basis |
| --- | --- | --- |
| macOS AppKit | **Eligible**, both frontends, plain and ASan/UBSan | `CX-UIA-10` hosted evidence (`evidence/ui1-macos.toml`; run 37318960723, JUnit artifact 11354918053, SHA-256 `f132900e…`): 100 cycles, 100 fresh-process restores, 0 provider and 0 registration survivors, fixture AX identities mapped through `controlView`, one action per click, `scope.cancel` and `GUI.close` COMPLETE, a native close started inside a callback completes without a nested loop. |
| Linux SDL, X11 | **Eligible**, both frontends, plain and ASan/UBSan; X11 is the gating backend | `CX-UIA-11` evidence (`evidence/ui1-linux.toml`, rows at `72592d36`) plus hosted Linux CI at main `19f75abf` (run 37422912212), with the batch 41 SDL selection-requestor patch and the batch 45 bounded journey waits. |
| Linux SDL, Wayland | **Eligible with a carried residual** | 3 of 4 rows pass; the selfhost ASan/UBSan row stalls at restore 61 inside libdecor 0.2.5's GTK plugin (`SDL_ShowWindow`). The Wayland halves of the UI2 landing rows wait for that fix (Claude-owned nix pin) and for a re-run of all four rows at the current revision (`CX-UIA-11` residual in CODEX.md). Wayland is not recorded as qualified. |
| Windows, iOS, Android | **Blocked** | No shell exists yet. The blockers stay as `hosts.toml` already records them: `ui-1-windows-shell` with `platforms-p1-host-windows` (and `tooling-windows-ci-arm64-llvm` for ARM64); `ui-1-ios-shell` with the iOS simulator host items; `ui-1-android-shell` with the Android emulator host items (CLAUDE.md appendix ids). |

D23 scopes GTK4 to UI4–UI8, so UI2 and UI3 on Linux stay on the shipping SDL
provider. D24's host-owned loop is **design-confirmed** for iOS and Android
(`native-ui-shells/ios.md`, `android.md`, `ui2-executor.md`'s
`IApplication.attachHost`) but not yet evidenced: `CL-P2-22` and `CL-UIA-22`
remain the real checks. Win32 versus WinUI and Android Views versus
GameActivity stay open until those shells report; `CL-UIA-22` decides them.

## Conditions for the UI2 contract review (`CL-UIA-13`)

1. Freeze `IApplication.attachHost` at least provisionally, so the iOS and
   Android shells (`CX-UIA-16`, `CX-UIA-17`) can run the shared journey in
   host-attached form without a private bridge.
2. Phrase executor affinity as "the application's UI executor thread", never
   "the process main thread" (GameActivity runs `android_main` off the main
   thread), and mark the Windows and Android rows of the executor and
   control-events drafts provisional, so a WinUI or GameActivity outcome is a
   mapping change rather than a portable-contract break.
3. Decide how SDL text editing reports composition: record an adaptation, or
   have `CX-UIA-23` plumb `SDL_EVENT_TEXT_EDITING`. No UI1 evidence covers IME
   on either platform, so the control-events composition rules stay
   provisional for macOS and Linux until an owner IME session.
4. Add UI2 to E42's and E46's catalog milestone links in the reviewed UI2
   catalog amendment (`cases/E25-E47.toml`); UI2 delivers the E46 dirty-close
   veto on both platforms (`MacOSWindow.btrc:19` and the Linux provider close
   immediately today), so Stage 31 cannot claim E46.

## Gaps UI2 and later work carry

None of these blocks UI2 entry; each is owned below.

- **macOS keyboard delivery.** On hosted macOS the application is never
  activated and the window is never key (300 of 300 pre-Tab contexts per
  variant), so Tab, Return, Escape and arrow delivery are unproven. This
  affects E01 commit and cancel, E02/E33 popup keyboard, E03/E34 keyboard
  adjustment, E39 focus redirection and E42 activation state. Owner: a
  `CX-UIA-10` follow-up that activates the application (or uses a declared
  delivery route and records it); `CX-UIA-22` must not count those rows as
  passed until a run shows `window_key=true`. `MAC-UIA-02` covers GPU timing
  and an Accessibility Inspector capture only and does not prove keyboard
  delivery; it needs the same activation before it can.
- **macOS key-view loop with Full Keyboard Access off,** and the GPU view's
  programmatic-only focus with no AX element: UI3 (E05–E07, E13/E14), UI8 and
  UI9. UI2's E39 must handle a programmatically focused GPU view.
- **macOS run-loop modes:** `postAfter`'s timer fires only in the default mode
  and stalls during tracking, live resize and modal loops. Carried by the
  executor's E40/E24 rows and E02/E03 delivery while tracking.
- **E31 oracle:** survivors are counted after a probe-owned 200 ms drain, not
  at COMPLETE, and the one allowed AppKit-private survivor's class is not
  recorded. Carried by the UI2 lifecycle acceptance.
- **E40 lossless pump:** both compilers drop the 4,097th queued event on Linux
  today; the repair is `CX-STDLIB-01` (CODEX.md), re-verified by `CX-UIA-23`
  under X11 and Wayland, both frontends, plain and sanitized. No macOS burst
  evidence exists yet, and `CX-UIA-22`'s acceptance should add E40.
- **Linux accessibility:** no AT-SPI bridge (a fixed "no bridge" source label,
  not a queried tree). It blocks the Stage 31 Linux close and the
  accessibility half of E03/E34 and E39 semantics on Linux SDL (D23, UI8:
  `CL-UIA-10`, `CL-UIB-12`), not UI2 entry.
- **Linux input and windowing coverage:** input is synthetic SDL-queue
  injection only, resize, hide and minimize exposure are unexercised, and leak
  accounting counts SDL windows only with LeakSanitizer off. Carried by the
  UI2 Linux rows for E31, E35, E39 and E42.
- **E47** is fixture-only restoration with no stdlib contract; it is a
  UI1/UI5/UI10 item, not a UI2 dependency.
- **Evidence freshness:** the macOS shard is at merge `25a160f7`, before seven
  compiler commits and the batch 45 fixture change, and macOS `native-gui` does
  not run on main pushes; its JUnit artifact expires 2026-10-19. The Linux
  shard predates batches 41 and 45, and its clipboard destroyed-requestor row
  awaits Codex's re-record on the patched SDL. A `focus=native-gui` dispatch on
  main refreshes both before the UI2 landing.

## Catalog

The catalog has no milestone-eligibility field, and every direct encoding the
parity reviewer tried is rejected by the loader. The decision is recorded here
and as notes on the two eligible routes in `native-ui-catalog/hosts.toml`
(`macos-hosted-correctness`, `linux-devcontainer-automation`); no `status` or
`blocked_by` changes, and the validator accepts the edit. A machine-checkable
field would be a `btrc.ui-hosts/3` schema change owned by `CX-UIA-06` and is
not needed for UI2.
