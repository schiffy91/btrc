# Accessibility bridge feasibility

CX-UIB-07, 2026-10-04. **Partial findings; macOS execution is pending.**

A btrc process can serve a small AT-SPI wire tree over the actual accessibility
D-Bus, using the same direct libdbus/pull-dispatch pattern as Tray/Linux. Both
compilers produced working executables, and a separate client read a window,
button and virtual child. This proves wire exposure, not a complete AT-SPI
bridge, Orca navigation or production accessibility.

The macOS prototype is prepared and collected for both compilers, but has not
executed on an Apple runner. **Hosted-runner AX/TCC trust is unknown**, not an
inferred yes or no. This packet's macOS acceptance remains open.

## Prototype and reproductions

The never-merge branch is `codex/cx-uib-07-spike`, commit
[`eb5e94ed`](https://github.com/schiffy91/btrc/tree/eb5e94ed/spikes/accessibility-bridges),
based on main `f4317455de1e567d4d6290139e5ba28fbada7d0c`.
It has no PR. This findings PR contains only this document.

Linux commands, from the prototype checkout's root:

```bash
nix develop --command bash spikes/accessibility-bridges/run-linux.sh reference
nix develop --command bash spikes/accessibility-bridges/run-linux.sh selfhost PATH_TO_CURRENT_BTRCC
```

Both commands were executed successfully against the same source base in the
pinned development shell, using Xvfb and a private D-Bus/accessibility session.
Each compiles to strict C11 with warnings as errors, runs a separate Gio client,
checks the real replies and orderly server exit, and saves a JSON tree. The
self-hosted compiler was freshly built for that base with pinned GCC 15.2.
Results: **2 passed, 0 skipped, 0 failed** functional executions, one per compiler.

- [Reference tree](https://github.com/schiffy91/btrc/blob/eb5e94ed/spikes/accessibility-bridges/evidence/linux-reference-tree.json)
- [Self-host tree](https://github.com/schiffy91/btrc/blob/eb5e94ed/spikes/accessibility-bridges/evidence/linux-selfhost-tree.json)
- [Provenance and source hashes](https://github.com/schiffy91/btrc/blob/eb5e94ed/spikes/accessibility-bridges/evidence/provenance.json)

Both dumps contain the following real wire values (roles independently checked
against the installed pyatspi constants):

| Path suffix | Name | Role number / name | Children |
|---|---|---|---|
| root | BTRC accessibility window | 23 / frame | button, virtual |
| button | Native contract button | 43 / push button | none |
| virtual | Virtual GPU child | 29 / label | none |

The labels describe semantic nodes; this Linux probe does not instantiate a
native window/button widget or attach itself to a production GPU view.

## What the Linux result establishes

`Main.btrc` owns the tree and method dispatch. It answers
`org.a11y.atspi.Accessible.GetChildren`, `GetRole`, `GetRoleName` and
`org.freedesktop.DBus.Properties.Get(Name)`. Child references use the required
`(so)` bus-name/object-path form. Unknown objects, methods and properties return
explicit D-Bus errors.

The only new C adapter opens/registers a private connection to the address
returned by `org.a11y.Bus.GetAddress`, because DBusError's bitfields remain on
the C side, as in Tray/Linux. Basic-value append/read helpers are reused from
Tray/Linux. No tree or accessibility reply implementation is hidden in C.
The server services messages in a bounded pull loop, with no foreign callback
vtable, and releases its connection on the test client's Quit request.

This deliberately incomplete wire interface has no registry embedding,
Application/Component/State/Parent interfaces, focus or structure events,
keyboard actions, hit-testing, coordinate conversion, text ranges, stable-key
recycling or screen-reader navigation. A direct D-Bus client can inspect it;
that does not mean an assistive client discovers it. There is no sanitizer,
stress, UI-thread scheduling or cancellation-lifetime qualification here.

## macOS probe and outstanding evidence

The prototype adds one `test_native_ui_*.py` module, collected by the existing
`make test-native-gui` glob. Local pytest collection found both reference and
self-host cases; collection does not prove Apple compilation or execution.
No workflow is changed.

The planned native run compiles a btrc MacOSGPUSurface consumer and passes its
NSView to a test-only Objective-C adapter. The adapter attaches one
NSAccessibilityElement virtual button and reads the native child list, label,
role and parent back in-process. It clears the parent/child relationship before
closing the surface. It records, without prompting or changing TCC:

- `virtual_child_attached`;
- `ax_trusted`, from `AXIsProcessTrusted()`;
- whether the default element responds to `accessibilityPerformPress`;
- the default press result, when that selector exists.

The existing workflow uploads JUnit containing those testcase properties.
In-process property reads do not require or establish external AX trust.
No Objective-C subclass override is defined by this probe, so custom press
behavior remains a separate requirement even if default property exposure works.

Once the single heavy-CI slot is available, the packet permits one dispatch:

```bash
gh workflow run macos.yml --ref codex/cx-uib-07-spike -f focus=native-gui
```

Dispatch count: **0**. Run ID: **not yet assigned**. It is queued behind the
native-shell/focused-gate work under the current CI-cap policy. Do not call the
macOS part passed until the native test and its JUnit properties are inspected.
This environment also currently receives Forbidden responses when downloading
GitHub job logs/artifacts; required network-domain additions were saved in the
environment draft but are not known to be active. If that persists, obtaining
the actual JUnit values remains an explicit evidence prerequisite.

## Interop gaps and next proof

For **CL-UIB-09 (Linux accessibility bridge)**, reuse the direct libdbus boundary
pattern, then supply registry embedding and the complete set of interfaces/events
required by the approved accessibility contract. Map stable semantic keys to
object paths, enforce UI-thread ownership, and define parent/child teardown so
stale accessible references fail predictably. Reproduce with a separate Orca or
pyatspi discovery/navigation client; direct wire calls alone are insufficient.
No compiler defect was demonstrated by the narrow prototype.

For **CL-UIB-12 (macOS virtual accessibility)**, inspect the native run before
choosing property-only elements versus Objective-C subclasses. Custom actions
(press/increment/decrement), dynamic hit testing and focus behavior need an
implementation that can route native accessibility callbacks to the approved
UI executor with a lifetime/unregister barrier. An NSAccessibilityElement with
a role and label does not implement a GPU control's application action. Any
required subclass overrides depend on I1 step 6 and must be checked through the
approved interop mechanism; this spike must not create a parallel ownership model.

The eventual contract needs both native in-process checks and assistive-client
checks. If a hosted Mac reports `ax_trusted: false`, that limits cross-process
inspection on that runner; it does not disprove the in-process native tree.
If it reports true, an actual external query is still needed before claiming
VoiceOver/AX navigation. The present result for trust remains **unknown**.
