# Native shell fixture (CX-UIA-09)

`NativeShell.btrc` uses the public GUI facade and interfaces for application
behavior. Test-only probes supply input and native observations. It creates a
text field, button, scroll view containing 50 labels, and a capturable GPU child.
A scripted native event sequence enters a draft, sends Enter and Tab, activates
the button, scrolls, reads back a blue GPU frame, and requests a native close
while the draft remains dirty. One process repeats this 100 times by default.

Run both frontends, plain and ASan/UBSan, on a private display:

```sh
export BTRC_TEST_RUNNER=linux-devcontainer
nix develop --command tools/ui/headless-session.sh --x11 -- python3 -m pytest src/tests/python/test_native_ui_shell.py src/tests/python/test_native_ui_shell_linux.py -q -rs
nix develop --command tools/ui/headless-session.sh --wayland -- python3 -m pytest src/tests/python/test_native_ui_shell.py src/tests/python/test_native_ui_shell_linux.py -q -rs
```

The macOS rows live in `test_native_ui_shell_macos.py`; they require the native
header reader and AppKit. Hosted GPU readback is correctness evidence, not a
pacing or hardware measurement. `BTRC_UI_SHELL_CYCLES=1` is a development smoke
check; only the default 100-cycle run meets the lifecycle gate. The fixture
checks every retained portable view alias is closed, callback registration is
closed, and owned native handle counts return to zero. ASan leak detection is
disabled for process-global SDK allocations, as in existing provider tests;
these explicit ownership checks do not claim a whole-process allocation audit.

The probe header defines a C ABI shared by both providers. macOS observes weak
references to native views and walks in-process NSAccessibility children,
without TCC-dependent cross-process automation. Its native count includes the window and labels, and separately bounds
AppKit's process-retained editable field and field editor to one each across
all cycles, matching the existing StackProbe retention baseline. Linux counts SDL windows: its controls are
drawn nodes, not native child windows. Their retained portable aliases prove
closure. SDL keyboard/text routing confirms editor focus but cannot identify
arbitrary drawn views; the probe reports `focused_editor`, and accessibility
is explicitly `no bridge`. Pointer/key/wheel injection uses the existing
`btrcSdlPush*` helpers. Text uses immutable SDL event storage because the helper's
mutable ring is local to the provider's generated translation unit.

E01's Enter subscription, E46's dirty-close negotiation, and the stdlib E47
restoration contract remain missing. A passing baseline is not parity for
those contracts. Tab is injected and the resulting native focus is recorded;
provider focus behavior is classified by the subsequent proof packets.

For the fixture-owned E47 harness, `ShellState.c` flushes the side-effect journal
and publishes draft plus scroll anchor in one checkpoint rename. The harness
launches 100 fresh processes in restore mode and checks the draft, anchor,
commit count, and byte-identical journal after each. Restore mode reads state
without opening the GUI or replaying an action. This proves fixture storage
and replay discipline, not scene restoration, power-loss durability, or a
transaction spanning the checkpoint and external side effects.

Per-provider/frontend/build-mode JSONL under `build/ui-shell/` is validated by
`LedgerDocument`. Mobile rows are unavailable until their shell packets land;
Windows checks the actual missing-provider compile diagnostic. These are
stand-in test records, not passed acceptance-case catalog slots.
