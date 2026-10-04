# Accessibility bridge feasibility prototype

CX-UIB-07. This branch is pushed without a PR and is never merged. Production
stdlib/compiler/workflow files are unchanged. The Linux native fixture lives in
`src/tests/native/gui/accessibility/spike_linux/` so the repository audits its
direct imports. The throwaway `test_native_ui_accessibility_spike.py` is collected
by `make test-native-gui`'s existing glob on macOS. Both remain on this never-merge
branch.

## Linux

The tree and message dispatch live in Main.btrc. Bridge.h opens the actual
accessibility bus with the same DBusError-bitfield adapter pattern used by
Tray/Linux; it reuses that module's basic-value marshalling helpers. A separate
Gio client obtains the address from org.a11y.Bus, launches the executable, and
reads GetChildren/GetRole/GetRoleName and Properties.Get(Name) over D-Bus.
It verifies a window/frame, button and virtual label, then requests orderly
shutdown and checks exit 0. Role constants 23/43/29 were checked against pyatspi.

```bash
nix develop --command bash spikes/accessibility-bridges/run-linux.sh reference
nix develop --command bash spikes/accessibility-bridges/run-linux.sh selfhost PATH_TO_CURRENT_BTRCC
```

Use a compiler built from the same main source and pinned development shell.
The captured trees in `evidence/` identify their frontend and preserve the
original `eb5e94ed` evidence and paths. Fresh executions write trees under
`build/accessibility-spike/{reference,selfhost}/`. Three wire objects
are **not full AT-SPI support**: this experiment has no registry embedding,
state/parent/component interfaces, actions, notifications, focus changes,
screen-reader navigation or production ownership stress tests. The button name
is a semantic label; no native GUI widget is instantiated by this wire probe.
The server runs a bounded pull loop (30 seconds idle maximum) and releases
its private connection after the client requests Quit.

## macOS

The fixture compiles a btrc MacOSGPUSurface consumer through both compilers.
The imported Bridge.h exposes only a C function taking a void-pointer handle.
The test compiles Bridge.m separately with the selected Apple SDK and links its
object with the generated native plan; it does not import Objective-C declaration
bodies into btrc. That test-only adapter attaches one NSAccessibilityElement virtual
button to the surface's NSView and reads its role, label, parent and child list
back in-process. It records AXIsProcessTrusted() without prompting/changing TCC,
checks whether the default element exposes a press selector, and records its
result. It defines no subclass overrides and does not prove VoiceOver use.

The existing macOS focused workflow collects it. The packet's permitted dispatch
was run 37172345932 at eb5e94ed. Both frontend rows failed before native execution
because the old inline Objective-C binding required adapter lowering. Its actual
JUnit has no accessibility properties. The split C/Objective-C adapter is the
fixture repair; it still needs an integrator-arranged run after local validation.
Do not issue a duplicate dispatch or infer trust from the compile failure.

JUnit testcase properties preserve
`virtual_child_attached`, `ax_trusted`, `press_selector` and
`default_press_result` in the workflow's existing uploaded artifact. A successful
in-process property test is not an assertion that the hosted runner grants AX
trust: use the observed boolean. If artifact/network access prevents reading it,
record trust as unknown, not false. Local Linux collection is not macOS execution.

The findings PR must own only
`docs/design/native-ui-contracts/spikes/accessibility-bridges.md` and carry the
exact dispatch/evidence state plus requests for CL-UIB-09 and CL-UIB-12.
