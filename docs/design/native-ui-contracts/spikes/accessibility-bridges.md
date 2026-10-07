# Accessibility bridge feasibility

CX-UIB-07, 2026-10-04. **Partial findings; macOS evidence is not yet verified.**

A btrc process can serve a small AT-SPI wire tree over the actual accessibility
D-Bus, using the same direct libdbus/pull-dispatch pattern as Tray/Linux. Both
compilers produced working executables, and a separate client read a window,
button and virtual child. This proves wire exposure, not a complete AT-SPI
bridge, Orca navigation or production accessibility.

Both hosted macOS attempts failed compilation in both compilers. Separating
the Objective-C implementation fixed the first header-import failure, but the
repaired prototype then failed the managed-to-raw ownership check at its
`NSView` argument. Neither attempt executed the accessibility probe or recorded
native properties. **Hosted-runner AX/TCC trust is unknown**, not an inferred
yes or no. Mac acceptance waits for an approved Objective-C adapter/borrow seam.

## Prototype and reproductions

The never-merge branch is `codex/cx-uib-07-spike`. Its repaired commit is
[`0d6127a6`](https://github.com/schiffy91/btrc/tree/0d6127a6/spikes/accessibility-bridges),
based on main `bfa950e2d1779491da960762491c55b6265e763a`.
It has no PR. This findings PR contains only this document. The original
prototype and retained evidence are at `eb5e94ed`, based on main
`f4317455de1e567d4d6290139e5ba28fbada7d0c`.

Linux commands, from the prototype checkout's root:

```bash
nix develop --command bash spikes/accessibility-bridges/run-linux.sh reference
nix develop --command bash spikes/accessibility-bridges/run-linux.sh selfhost PATH_TO_CURRENT_BTRCC
```

The original commands were executed successfully on `eb5e94ed` in the pinned
development shell, using Xvfb and a private D-Bus/accessibility session.
Each compiles to strict C11 with warnings as errors, runs a separate Gio client,
checks the real replies and orderly server exit, and saves a JSON tree. The
self-hosted compiler was freshly built for that base with pinned GCC 15.2.
Historical results: **2 passed, 0 skipped, 0 failed** functional executions,
one per compiler. The following checked-in artifacts retain their original
source hashes and provenance:

- [Reference tree](https://github.com/schiffy91/btrc/blob/eb5e94ed/spikes/accessibility-bridges/evidence/linux-reference-tree.json)
- [Self-host tree](https://github.com/schiffy91/btrc/blob/eb5e94ed/spikes/accessibility-bridges/evidence/linux-selfhost-tree.json)
- [Provenance and source hashes](https://github.com/schiffy91/btrc/blob/eb5e94ed/spikes/accessibility-bridges/evidence/provenance.json)

The repaired head `0d6127a6` was rerun on 2026-10-04: **2 passed, 0 skipped,
0 failed**, one fresh strict-C11 build and separate client execution per frontend.
Its Linux package now lives in `src/tests/native/gui/accessibility/spike_linux/`
so repository import audits inspect it. Both fresh dumps are 676 bytes and have
SHA-256 `97d96614f3365a470c50efa2e6cc20cfab46eb4af7539581b3f6d267aa56c55d`;
the tree matches the historical capture. Fresh outputs are
`build/accessibility-spike/{reference,selfhost}/tree.json`. The self-hosted
compiler was built from matching compiler sources at `bfa950e2` in pinned Nix
with GCC 15.2; its SHA-256 is
`d985392e203046c270b368b482112c30ba8e9aa0d498c66e489f4085b1f08edf`.

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

Claude dispatched the permitted native run on the prototype head `eb5e94ed`:

- [macOS run 37172345932](https://github.com/schiffy91/btrc/actions/runs/37172345932),
  native-gui job 111349170278, completed with failure. Dispatch count: **1**.
- Genuine `junit-macos-native-gui` artifact 11292718381 (6,681 bytes) was
  downloaded and inspected on 2026-10-04 after initial artifact-host denials
  cleared. Both `test_macos_virtual_gpu_accessibility[reference]` and
  `[selfhost]` failed at the `result.successful` assertion before native build
  or execution, with `Objective-C header declarations require adapter lowering`.
- Neither testcase has `ax_trusted`, `virtual_child_attached`, `press_selector`
  or `default_press_result` properties. The report establishes a compile failure,
  not an observed trust value or accessibility runtime failure.

The original fixture unnecessarily exposed its inline Objective-C implementation
through `native.bindings`. The repair separates a plain C declaration
(`void *` view handle) from the test-only `.m` adapter, compiles that adapter with
the selected Apple SDK, and links it through the existing native plan. It adds
no production bridge, subclass, compiler workaround or workflow change.

A local Linux smoke test imported the exact plain-C header through both
frontends, compiled and linked a C stub under strict C11, and executed both
binaries successfully. Source review also found and fixed a missing timeout
in the delegated native-build runner. These checks validate the C boundary
and bounded harness; they do not establish Apple SDK compilation, NSView
conversion or native accessibility behavior.

On repaired prototype `0d6127a6`, the whole local unit shard finished with
**5,930 passed, 3,107 skipped, 0 failed**, plus one existing Python `forkpty`
deprecation warning. It used the pinned Linux development shell, Xvfb, two
workers and the source-matched compiler under Tini. The Mac cases are among the
platform skips. Lint, both source-format checks and generated-source checks
passed; all 10 focused import-audit/timeout checks also passed. The earlier five
import-audit failures were corrected by moving the Linux fixture into the
audited native-test tree, without changing compiler or shared audit code.

The integrator arranged [macOS run 37217909473](https://github.com/schiffy91/btrc/actions/runs/37217909473)
on the published repaired head `0d6127a6`. Native-gui job `111482632627` failed:
**239 passed, 58 skipped, 2 failed** in 1,749.25 seconds. The downloaded failed
job log shows that both accessibility cases stop at the compilation assertion:

```text
Argument to 'spikeAccessibilityProbe()' cannot forward a managed value as a raw
representation because the parameter is not proven borrow-only
```

The rejected fixture call is `spikeAccessibilityProbe((void*)surface.nativeView())`.
The earlier Objective-C header diagnostic is gone. Neither executable runs, so
this is an ownership-boundary failure, not a native accessibility runtime failure.
The JUnit artifact is `11310420586` (6,619 bytes); direct download was denied at
its storage host. The integrator inspected it and [reported both failures and
absent native properties](https://github.com/schiffy91/btrc/pull/42#issuecomment-5982621239).
Codex read the failed job log directly; no AX-trust result is inferred.

The integrator suggested a `read-only-borrows` manifest entry. Testing that
exact addition against the unchanged plain-C header on Linux makes **both
compilers reject it** with `read-only-borrows requires a const scalar pointer
parameter`. Its parameter is `void *native_view`, and the adapter calls setters
on the view before clearing the parent/child relation. Changing the declaration
to pretend this is a read-only scalar buffer would misdescribe the probe. The
existing `borrowed-parameters` metadata covers declared native resources; it is
not an arbitrary mutable `void *` borrow annotation.

CL-UIB-09 must identify the approved nonescaping mutable Objective-C object
boundary or provide the required adapter support. No compiler changes, ownership
check bypass, further prototype push or Codex dispatch was made. The prototype
remains never-merge, and Mac acceptance remains open.

## Interop gaps and next proof

For **CL-UIB-12 (Linux UI interop)**, qualify the D-Bus method/property vtables
and callback boundary required by the SDL route, through both compilers and
sanitizers after D23 selects that route. This prototype uses bounded pull
dispatch, so it does not establish vtable/callback support and demonstrates no
compiler defect in that untested path. GTK-specific interop remains conditional
on the other D23 route.

The production Linux bridge remains Codex's **CX-UIB-23/24** work: registry
embedding, the complete interfaces/events, stable semantic keys, UI-thread
ownership and parent/child teardown. It needs a separate Orca or pyatspi
discovery/navigation client; direct wire calls alone are insufficient.

For **CL-UIB-09 (Objective-C UI interop)**, first resolve the concrete
managed-`NSView` to test-adapter boundary above and obtain native evidence before
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
